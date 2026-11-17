#!/usr/bin/env python3
"""The context-response benchmark: five series of multi-turn runs through real Training Mode Sessions.

Training Mode only.  Each series is one multi-turn problem (``measurements/context-response-benchmark/series.json``,
the same file ``scripts/session_client.py --teacher`` reads) with its inputs for turns 2 and 3.  Each runs in its own
fresh Training Mode Session on the v2.0 Base, seeds 1 to 50, the serial child, backend ``off`` and the session's default
maximum number of codelets.  The teacher is ``set_teacher`` in process, so the order of turns, and the results, are
reproducible: the same code gives the same conversations.  Nothing is tuned.

    .venv/bin/python scripts/context_response_benchmark.py \\
        --database-url postgresql+asyncpg://USER:PASS@localhost:5432/NAME --out DIR [--series 1,3] [--seeds 50]

The script refuses to overwrite: ``DIR`` must not exist.  It creates ``DIR`` and writes ``series-N.json`` (every run's
conversation, the settings the session took, the learned structure and the time) for each series, then ``SUMMARY.md``.
With more than one series, each series runs in its own process at the same time.  The database is created if it does
not exist and holds one session per series.  ``--max-codelets`` and ``--seeds`` are only for tests and trials; the
reference run states neither.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # this checkout's `server`, not an installed one
SERIES_FILE = REPO / "measurements" / "context-response-benchmark" / "series.json"
URL = "/api/training-mode/sessions"
SERIES_LABEL = "series over"


def load_series() -> list[dict]:
    sys.path.insert(0, str(REPO / "scripts"))
    import session_client

    return session_client.load_series(str(SERIES_FILE))


def teacher_for(series: dict):
    """The teacher of ``set_teacher``: the next input of the series, then the series' end."""
    inputs = series["inputs"]
    label = series.get("end_label", SERIES_LABEL)

    def teacher(conversation: dict):
        index = conversation["waiting_for"] - 2
        return inputs[index] if index < len(inputs) else {"end": True, "label": label}

    return teacher


async def ensure_database(url: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    name = url.rsplit("/", 1)[1]
    admin = create_async_engine(url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with admin.connect() as conn:
        if (await conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name})).fetchone() is None:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await admin.dispose()


def learned(before: dict, after: dict) -> dict:
    """What a session's configuration gained over the series, against the v2.0 Base: nodes and links added, links by type."""
    nodes = set(after["slipnet_node_defs"]) - set(before["slipnet_node_defs"])
    links = set(after["slipnet_link_defs"]) - set(before["slipnet_link_defs"])
    by_type = collections.Counter(k[2] for k in links)
    changed = sum(1 for k in set(after["slipnet_link_defs"]) & set(before["slipnet_link_defs"])
                  if after["slipnet_link_defs"][k] != before["slipnet_link_defs"][k])
    return {"nodes_added": len(nodes), "links_added": len(links), "links_by_type": dict(sorted(by_type.items())),
            "existing_links_changed": changed, "node_names": sorted(k[0] for k in nodes)[:200]}


async def run_series(url: str, number: int, seeds: int | None, max_codelets: int | None, out: Path) -> None:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    os.environ["DATABASE_URL"] = url
    from server.api import runs as runs_module
    from server.config import SEED_DATA_DIR
    from server.db import get_session
    from server.main import app
    from server.services import training_base as tb
    from server.services import training_mode_session_service as bs
    from server.services.configuration_startup import startup_configuration
    from server.services.configuration_store import ConfigurationStore, read_revision, set_configuration_store
    from server.services.run_service import RunService
    from server.services.training_mode_session_executor import SerialExecutor

    series = load_series()[number - 1]
    target = out / f"series-{number}.json"
    if target.exists():
        raise SystemExit(f"{target} exists")
    meta = await startup_configuration(url, SEED_DATA_DIR)
    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        store = ConfigurationStore(meta, await read_revision(s))
    set_configuration_store(store)
    runs_module._run_service = RunService(store)

    async def _session():
        s = factory()
        try:
            yield s
        finally:
            await s.close()

    app.dependency_overrides[get_session] = _session
    executor = SerialExecutor()
    service = bs.TrainingModeSessionService(factory, lambda: meta, executor=executor)
    await service.start()
    bs.set_training_mode_session_service(service)
    started = time.monotonic()
    try:
        settings: dict = {"backend": "off", "seeds_per_problem": seeds if seeds is not None else series["seeds"]}
        if max_codelets is not None:
            settings["max_codelets"] = max_codelets
        body = {"name": f"context-response benchmark, series {number}", "settings": settings,
                "problems": [{"initial": series["initial"], "modified": series["modified"], "target": series["target"],
                              "multi_turn": True}]}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(URL, json=body)
            resp.raise_for_status()
            created = resp.json()["session"]
            tid = created["id"]
            service.set_teacher(tid, teacher_for(series))
            (await client.post(f"{URL}/{tid}/start")).raise_for_status()
            while True:
                b = (await client.get(f"{URL}/{tid}")).json()
                if b["state"] == "running" and b["activity"] == "idle":
                    break
                await asyncio.sleep(0.5)
            summary = b
            convs = []
            for seed in range(1, settings["seeds_per_problem"] + 1):
                convs.append((await client.get(f"{URL}/{tid}/problems/1/runs/{seed}")).json())
            after = service._live[tid].config.document.tables
            gained = learned(tb.resolve_base().document.tables, after)
            (await client.post(f"{URL}/{tid}/stop")).raise_for_status()
        result = {"series": number, "problem": {k: series[k] for k in ("initial", "modified", "target", "inputs")},
                  "settings": summary["settings"], "configuration_base": summary["settings"].get("configuration_base"),
                  "seconds": round(time.monotonic() - started, 1), "learned": gained, "conversations": convs}
    finally:
        app.dependency_overrides.clear()
        set_configuration_store(None)
        bs.set_training_mode_session_service(None)
        await service.stop()
        executor.close()
        await engine.dispose()
    with open(target, "x", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(f"series {number}: {len(convs)} runs in {result['seconds']} s -> {target}", flush=True)


def one_line(rule: str) -> str:
    """A rule's English text on one line (it is several lines, and a table cell holds one)."""
    return "; ".join(part.strip() for part in rule.splitlines() if part.strip())


def top(counter: collections.Counter, n: int) -> str:
    return "; ".join(f"`{k}` x{v}" for k, v in counter.most_common(n)) or "none"


def summarise(out: Path, numbers: list[int], head: dict) -> str:
    lines = ["# Context-response benchmark: summary", ""]
    lines += [f"- Commit: {head['commit']}", f"- Base: {head['base']}", f"- Settings: {head['settings']}",
              f"- Run time: {head['seconds']} s (the series ran at the same time, each in its own process)", ""]
    for n in numbers:
        r = json.loads((out / f"series-{n}.json").read_text(encoding="utf-8"))
        p = r["problem"]
        lines += [f"## Series {n}: `{p['initial']}:{p['modified']}::{p['target']}:?`, inputs {p['inputs']}", "",
                  f"Session settings taken: `{json.dumps(r['settings'], sort_keys=True)}`; {len(r['conversations'])} runs in "
                  f"{r['seconds']} s.", ""]
        ends = collections.Counter(c["end_reason"] if c["end_reason"] != "teacher" else f"teacher ({c['end_label']})"
                                   for c in r["conversations"])
        lines += [f"Run end reasons: {top(ends, 10)}", "",
                  "| Turn | Reached | Answered | Statuses | Top responses (distinct) | Codelets median / mean | "
                  "Unperceived at end | Top rules (top rule // bottom rule) | Full posts (median) | Overflowing batches (median) | Evicted (median) | "
                  "Evicted per codelet |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for turn in range(1, len(p["inputs"]) + 2):
            ts = [t for c in r["conversations"] for t in c["turns"] if t["turn"] == turn]
            if not ts:
                lines.append(f"| {turn} | 0 | 0 | | | | | | | | | |")
                continue
            answered = [t for t in ts if t["positions"]["response"] is not None]
            statuses = collections.Counter(t["status"] for t in ts)
            responses = collections.Counter(t["positions"]["response"] for t in answered)
            codelets = [t["codelets"] for t in ts]
            evs = [t["evidence"] for t in ts if t["evidence"]]
            unperceived = sum(1 for e in evs if e["unperceived"] > 0)
            rules = collections.Counter(one_line(e["rule"]["top_rule"]) + " // " + one_line(e["rule"]["bottom_rule"])
                                        for t in answered if (e := t["evidence"]) and e["rule"])
            def med(key):
                return statistics.median([e["coderack"][key] for e in evs]) if evs else ""
            ev_total = sum(e["coderack"]["evicted"] for e in evs)
            per = f"{ev_total / sum(t['codelets'] for t in ts if t['evidence']):.3f}" if evs else ""
            lines.append(
                f"| {turn} | {len(ts)} | {len(answered)} | {top(statuses, 6)} | {top(responses, 5)} ({len(responses)} distinct) "
                f"| {statistics.median(codelets):g} / {statistics.mean(codelets):.1f} | {unperceived} of {len(evs)} "
                f"| {top(rules, 3)} | {med('full_posts'):g} | {med('overflowing_batches'):g} | {med('evicted'):g} | {per} |")
        g = r["learned"]
        lines += ["", f"Learned over the series (the session's configuration against the v2.0 Base): {g['nodes_added']} nodes added, "
                  f"{g['links_added']} links added, links by type {json.dumps(g['links_by_type'])}, "
                  f"{g['existing_links_changed']} existing links changed.", ""]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--database-url", required=True, help="postgresql+asyncpg://... for the benchmark's database")
    ap.add_argument("--out", required=True, help="output folder; must not exist")
    ap.add_argument("--series", default="1,2,3,4,5", help="comma-separated series numbers (default all five)")
    ap.add_argument("--seeds", type=int, default=None, help="seeds per series (default: the series file's 50)")
    ap.add_argument("--max-codelets", type=int, default=None, help="default: the session's own default")
    ap.add_argument("--worker", action="store_true", help="internal: run the one series in this process")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    numbers = [int(x) for x in a.series.split(",")]
    count = len(load_series())
    if any(not 1 <= n <= count for n in numbers):
        raise SystemExit(f"series are 1..{count}")
    if a.worker:
        asyncio.run(run_series(a.database_url, numbers[0], a.seeds, a.max_codelets, out))
        return
    if out.exists():
        raise SystemExit(f"{out} exists; this script never overwrites")
    out.mkdir(parents=True)
    asyncio.run(ensure_database(a.database_url))
    sys.path.insert(0, str(REPO))
    from server.config import SEED_DATA_DIR
    from server.services.configuration_startup import prepare_database

    asyncio.run(prepare_database(a.database_url, SEED_DATA_DIR))  # create the tables and load the standard once
    started = time.monotonic()
    procs = []
    for n in numbers:
        cmd = [sys.executable, str(Path(__file__).resolve()), "--database-url", a.database_url, "--out", str(out),
               "--series", str(n), "--worker"]
        if a.seeds is not None:
            cmd += ["--seeds", str(a.seeds)]
        if a.max_codelets is not None:
            cmd += ["--max-codelets", str(a.max_codelets)]
        procs.append(subprocess.Popen(cmd, cwd=REPO))
    codes = [p.wait() for p in procs]
    if any(codes):
        raise SystemExit(f"a series failed: exit codes {codes}")
    seconds = round(time.monotonic() - started, 1)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, capture_output=True,
                           text=True).stdout.strip()
    first = json.loads((out / f"series-{numbers[0]}.json").read_text(encoding="utf-8"))
    head = {"commit": f"{commit}{' plus uncommitted changes' if dirty else ''}",
            "base": "the v2.0 Base (`configuration_base` `training-v2`), one fresh Training Mode Session per series",
            "settings": json.dumps(first["settings"], sort_keys=True) + "; the serial child; teacher `set_teacher` in process",
            "seconds": seconds}
    (out / "SUMMARY.md").write_text(summarise(out, numbers, head), encoding="utf-8")
    print(f"wrote {out / 'SUMMARY.md'}")


if __name__ == "__main__":
    main()
