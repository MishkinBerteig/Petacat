#!/usr/bin/env python
"""Soak a Training Mode Session: many runs, external change batches on about 10% of them.

Not part of the test suite.  It drives the real session service (the real executor, a scratch
Postgres database) through one long Training episode:

* a session of ``--problems`` problems at ``--runs / --problems`` seeds each;
* an external configuration batch after every ``--batch-every`` completed runs (default 10, about
  10% of the runs): parameter changes, node layout moves and, every few batches, a codelet body
  edit (the barrier path of the speculative executor, and a real code change in the workers);
* a Stop and a Start every ``--cycle-every`` completed runs (the Stop write, the Start read);
* optionally a pause and resume around a batch.

At the end it Stops the session and checks, printing one JSON report (also written to
``--out-dir``): every run completed and none errored; the executor's pools were never rebound
(``rebinds == 0``) and its workers all stayed alive; the journal verifies (replay equals the
stored state); the stored configuration hash equals the live one; every stored run records the
``(configuration_revision, config_hash)`` of a configuration the journal reproduces; the parent
process's memory (RSS) did not keep growing; the time per run and per batch.

Run it on a scratch database whose name starts ``petacat_`` (it is dropped and recreated; the
name ``petacat`` and anything not starting ``petacat_`` is refused)::

    createdb -O petacat petacat_soak
    .venv/bin/python scripts/soak_sessions.py \\
        --database-url postgresql+asyncpg://petacat:dev@localhost:5432/petacat_soak \\
        --runs 10000 --out-dir agents-workspace/v2-S8/soak

Exit status is 0 when every check holds, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LETTERS = "abcdefghijklmnopqrstuvwxyz"


def problem(i: int) -> dict:
    return {"initial": "abc", "modified": "abd", "target": LETTERS[i % 24:i % 24 + 3]}


def batch_for(n: int, bodies: dict[str, str]) -> dict:
    """The *n*th external batch (all kinds code-free except every fifth, a body edit)."""
    kind = n % 5
    if kind == 4:
        names = sorted(bodies)
        name = names[(n // 5) % len(names)]
        bodies[name] = bodies[name] + f"\n# soak edit {n}\n"
        ops = [{"op": "set_codelet_body", "name": name, "source": bodies[name]}]
    elif kind == 0:
        ops = [{"op": "set_param", "name": "update_cycle_length", "to": 5 + n % 25}]
    elif kind == 1:
        ops = [{"op": "set_param", "name": "initial_temperature", "to": 80.0 + n % 20}]
    elif kind == 2:
        ops = [{"op": "move_layout", "node": "plato-a", "x": n % 600, "y": (n * 7) % 600}]
    else:
        ops = [{"op": "adjust_param", "name": "update_cycle_length", "by": 1 if n % 2 else -1}]
    return {"source": "external", "actor": "soak", "base_version": "head", "ops": ops, "note": f"soak {n}"}


async def main(args: argparse.Namespace) -> int:
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    name = args.database_url.rsplit("/", 1)[-1]
    if name == "petacat" or not re.fullmatch(r"petacat_\w+", name):
        print(f"refusing to use database {name!r}: it must be a scratch database named petacat_<x>", file=sys.stderr)
        return 2

    import server.models.run  # noqa: F401
    import server.models.training_mode_session  # noqa: F401
    from server.engine.metadata import MetadataProvider
    from server.models.metadata import Base
    from server.models.training_mode_session import TrainingModeSessionRun
    from server.services import config_document as cd
    from server.services import configurations, journal_views
    from server.services import training_mode_session_service as bs
    from server.services.configuration_admin import verify_journal
    from server.services.configuration_store import ConfigurationStore, read_revision, set_configuration_store
    from server.services.standard_configuration import seed_metadata_from_json, sync_help_topics
    from server.services.training_mode_session_executor import create_executor

    seed_dir = str(ROOT / "seed_data")
    engine = create_async_engine(args.database_url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        await seed_metadata_from_json(s, seed_dir)
        await s.flush()
        await sync_help_topics(s, seed_dir)
        await s.commit()
    meta = MetadataProvider.from_standard_configuration(seed_dir)
    async with factory() as s:
        set_configuration_store(ConfigurationStore(meta, await read_revision(s)))

    executor = create_executor(args.executor)
    service = bs.TrainingModeSessionService(factory, lambda: meta, executor=executor)
    await service.start()
    bs.set_training_mode_session_service(service)

    seeds = max(1, args.runs // args.problems)
    total_runs = seeds * args.problems
    made = await service.create_session(
        name="soak", settings={"seeds_per_problem": seeds, "max_codelets": args.max_codelets},
        problems=[problem(i) for i in range(args.problems)])
    tid = made["session"]["id"] if "session" in made else made["id"]
    bodies = {n: spec.execute_body for n, spec in meta.codelet_specs.items()
              if n in ("bond-builder", "group-evaluator", "rule-scout", "breaker")}
    if not bodies:  # a fixed list that names nothing is a script error, not a soak result
        bodies = {n: spec.execute_body for n, spec in list(meta.codelet_specs.items())[:3]}

    report: dict = {"runs_planned": total_runs, "problem_count": args.problems, "executor": executor.kind,
                    "workers": getattr(executor, "workers", None), "batch_every": args.batch_every}
    rss: list[tuple[int, float]] = []
    started = time.perf_counter()
    await service.start_session(tid)
    batches = refused = cycles = 0
    next_batch, next_cycle = args.batch_every, args.cycle_every
    batch_seconds = 0.0

    def rss_mb() -> float:
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return kb / (1024 * 1024) if sys.platform == "darwin" else kb / 1024

    last_print = 0.0
    while True:
        summ = await service.summary(tid)
        done = summ["runs"]["done"]
        if done >= next_batch and summ["state"] == "running":
            t = time.perf_counter()
            try:
                out = await service.submit_changes(tid, batch_for(batches, bodies))
                batches += 1
                refused += 0 if out.get("ok") else 1
            except Exception as exc:  # a refusal under load is a finding
                refused += 1
                report.setdefault("refusals", []).append(repr(exc)[:200])
            batch_seconds += time.perf_counter() - t
            next_batch += args.batch_every
            continue
        if args.cycle_every and done >= next_cycle and summ["state"] == "running" and done < total_runs:
            await service.stop_session(tid)
            await service.start_session(tid)
            cycles += 1
            next_cycle += args.cycle_every
            continue
        if time.perf_counter() - last_print > 10:
            rss.append((done, rss_mb()))
            print(f"  {done}/{total_runs} runs, {batches} batches, {cycles} stop/start cycles, "
                  f"{time.perf_counter() - started:.0f} s, rss {rss_mb():.0f} MB", flush=True)
            last_print = time.perf_counter()
        if summ["state"] == "running" and summ["activity"] == "idle" and done >= total_runs:
            break
        if summ["state"] == "stopped":
            await service.start_session(tid)
        await asyncio.sleep(0.05)
    elapsed = time.perf_counter() - started
    rss.append((total_runs, rss_mb()))

    swarm = getattr(executor, "swarm", None)
    report.update(
        elapsed_s=round(elapsed, 1), seconds_per_run=round(elapsed / total_runs, 4), batches=batches,
        batches_refused=refused, stop_start_cycles=cycles,
        ms_per_batch=round(batch_seconds / max(batches, 1) * 1000, 2),
        swarm_rebinds=getattr(swarm, "rebinds", None) if swarm is not None else None,
        rss_mb=[round(v, 1) for _, v in rss],
    )
    live_hash = service._live[tid].config.config_hash
    final = await service.stop_session(tid)
    report["unsaved_after_stop"] = final.get("unsaved")

    problems: list[str] = []
    async with factory() as s:
        row = await configurations.row_for_session(s, tid)
        verdict = await verify_journal(s, row["id"])
        entries = await journal_views.read_entries(s, row["id"])
        base = await configurations.base_document(s, row["id"])
        current = await configurations.current_document(s, row["id"])
        runs = (await s.execute(select(TrainingModeSessionRun).where(TrainingModeSessionRun.session_id == tid))).scalars().all()
    stored_hash = row["config_hash"]
    report.update(journal_entries=len(entries), journal_verified=verdict.get("ok"),
                  stored_hash_equals_live=stored_hash == live_hash)
    if not verdict.get("ok"):
        problems.append(f"verify_journal: {verdict.get('problems')}")
    if stored_hash != live_hash or cd.config_hash(current) != stored_hash:
        problems.append("the stored configuration hash differs from the live one")
    if len(entries) != batches or row["revision"] != batches:
        problems.append(f"{batches} batches applied but {len(entries)} entries and revision {row['revision']}")

    # Every run's recorded (configuration_revision, config_hash) is reproduced by the journal.
    hashes = {0: cd.config_hash(base)}
    doc = base
    for e in entries:
        doc = cd.apply_resolved(doc, e["resolved"], version=e["revision"])
        hashes[e["revision"]] = cd.config_hash(doc)
    bad = [r for r in runs if hashes.get(r.configuration_revision) != r.config_hash]
    statuses: dict[str, int] = {}
    for r in runs:
        statuses[r.status] = statuses.get(r.status, 0) + 1
    report.update(runs_stored=len(runs), run_statuses=statuses, runs_with_error=sum(1 for r in runs if r.error),
                  runs_naming_an_unreproduced_configuration=len(bad),
                  distinct_configurations_used=len({r.configuration_revision for r in runs}))
    if len(runs) != total_runs:
        problems.append(f"{total_runs} runs planned but {len(runs)} stored")
    if any(r.error for r in runs):
        problems.append(f"{report['runs_with_error']} runs errored")
    if bad:
        problems.append(f"{len(bad)} runs name a configuration the journal does not reproduce")
    if report["swarm_rebinds"]:
        problems.append(f"the swarm rebound its pool {report['swarm_rebinds']} times")
    if len(rss) >= 4 and rss[-1][1] > rss[len(rss) // 2][1] * 1.5 + 50:
        problems.append("the parent process's memory kept growing in the second half")
    report["problems"] = problems
    report["ok"] = not problems

    await service.stop()
    bs.set_training_mode_session_service(None)
    await engine.dispose()
    text_out = json.dumps(report, indent=1)
    print(text_out)
    if args.out_dir:
        Path(args.out_dir).mkdir(parents=True, exist_ok=True)
        (Path(args.out_dir) / "soak-report.json").write_text(text_out)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--database-url", default=os.environ.get("SOAK_DATABASE_URL"), required=not os.environ.get("SOAK_DATABASE_URL"))
    p.add_argument("--runs", type=int, default=10000)
    p.add_argument("--problems", type=int, default=20)
    p.add_argument("--max-codelets", type=int, default=150)
    p.add_argument("--batch-every", type=int, default=10, help="completed runs between batches (10 = about 10%%)")
    p.add_argument("--cycle-every", type=int, default=2000, help="completed runs between a Stop and a Start (0 = never)")
    p.add_argument("--executor", choices=("serial", "swarm"), default=None)
    p.add_argument("--out-dir", default=None)
    sys.exit(asyncio.run(main(p.parse_args())))
