#!/usr/bin/env python3
"""How much of the engine, and of the code in the database, the golden baselines reach.

    .venv/bin/python scripts/golden_coverage.py                       # both baselines
    .venv/bin/python scripts/golden_coverage.py --which original      # the 188 original runs
    .venv/bin/python scripts/golden_coverage.py --which extended --jobs 8 --out DIR

Every case of the chosen baseline (``tests/support/golden_baseline.py``, ``golden_extended.py``)
runs in its own fresh interpreter exactly as the baseline captures it, under

* **coverage.py** (branch coverage, the ``sysmon`` core) over ``server/engine/**``; the lines and
  branches executed while importing the engine are added, since a fresh interpreter per case would
  otherwise count them for the first case only; and
* a ``sys.monitoring`` tool over the **code that lives in the database**: every codelet body
  (``seed_data/codelet_types.json``), descriptor predicate (``slipnet_nodes.json``) and posting
  formula, condition and urgency formula (``posting_rules.json``).  Those compile from strings
  to code objects named ``<codelet:NAME>``, ``<descriptor-predicate:NODE>`` and
  ``<posting-formula:CODELET-TYPE>``, which coverage.py cannot attribute; the tool counts the lines
  and the branch arcs of those code objects.  Line 0 (a module's RESUME) raises no line event and is
  left out of the line total.

It prints the totals and the files with the most unreached lines, and writes ``coverage.json``
(per file: missing lines and branches; per database unit: missing lines and branch arcs) into
``--out`` (default ``agents-workspace/golden-coverage/``).  Nothing here is part of the test suite:
it takes minutes, and the reached sets move with every engine change.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("COVERAGE_CORE", "sysmon")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TOOL = 4
DB_PREFIXES = ("<codelet:", "<descriptor-predicate:", "<posting-formula:")


# --------------------------------------------------------------------------- the database's code


class DbMonitor:
    """Lines and branch arcs executed in code objects compiled from the database."""

    def __init__(self) -> None:
        self.lines: set[tuple[str, int]] = set()
        self.branches: set[tuple[str, str, int, int]] = set()

    def start(self) -> None:
        mon = sys.monitoring
        mon.use_tool_id(TOOL, "golden-db-coverage")
        events = mon.events
        mon.register_callback(TOOL, events.PY_START, self._start)
        mon.register_callback(TOOL, events.LINE, self._line)
        mon.register_callback(TOOL, events.BRANCH_LEFT, self._branch)
        mon.register_callback(TOOL, events.BRANCH_RIGHT, self._branch)
        mon.set_events(TOOL, events.PY_START)

    def stop(self) -> None:
        mon = sys.monitoring
        mon.set_events(TOOL, 0)
        for event in (mon.events.PY_START, mon.events.LINE, mon.events.BRANCH_LEFT, mon.events.BRANCH_RIGHT):
            mon.register_callback(TOOL, event, None)
        mon.free_tool_id(TOOL)

    def _start(self, code, offset):  # noqa: ANN001
        mon = sys.monitoring
        if code.co_filename.startswith(DB_PREFIXES):
            events = mon.events
            mon.set_local_events(TOOL, code, events.LINE | events.BRANCH_LEFT | events.BRANCH_RIGHT)
        return mon.DISABLE

    def _line(self, code, line):  # noqa: ANN001
        self.lines.add((code.co_filename, line))
        return sys.monitoring.DISABLE

    def _branch(self, code, offset, destination):  # noqa: ANN001
        self.branches.add((code.co_filename, _code_id(code), offset, destination))
        return sys.monitoring.DISABLE


def _code_id(code) -> str:  # noqa: ANN001
    return f"{code.co_qualname}@{code.co_firstlineno}"


def _walk(code):  # noqa: ANN001
    yield code
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            yield from _walk(const)


def db_universe(meta) -> tuple[set, set, dict]:  # noqa: ANN001
    """Every line and branch arc of the database's code, and the source of each unit."""
    sources: list[tuple[str, str, str]] = []
    for name, spec in meta.codelet_specs.items():
        if spec.execute_body and spec.execute_body.strip():
            sources.append((f"<codelet:{name}>", spec.execute_body, "exec"))
    for name, spec in meta.slipnet_node_specs.items():
        if spec.descriptor_predicate:
            sources.append((f"<descriptor-predicate:{name}>", spec.descriptor_predicate, "eval"))
    for rule in meta.posting_rules:
        for text in (rule.posting_formula, rule.urgency_formula, rule.condition):
            if text:
                sources.append((f"<posting-formula:{rule.codelet_type}>", text, "eval"))
    lines: set = set()
    branches: set = set()
    units: dict = {}
    for filename, text, mode in sources:
        code = compile(text, filename, mode)
        unit_lines: set = set()
        unit_branches: set = set()
        for c in _walk(code):
            for _, _, line in c.co_lines():
                if line:  # line 0 is the module's RESUME
                    unit_lines.add((filename, line))
            for start, left, right in c.co_branches():
                unit_branches.add((filename, _code_id(c), start, left))
                unit_branches.add((filename, _code_id(c), start, right))
        lines |= unit_lines
        branches |= unit_branches
        units.setdefault(filename, []).append(text)
    return lines, branches, units


# --------------------------------------------------------------------------- the cases


def original_cases() -> list[dict]:
    from tests.support import golden_baseline as gb

    triples, justify = gb.demo_problems()
    cases = [{"id": gb.case_id("discovery", p, None, s), "run": ("discovery", p, None, s)}
             for p in triples for s in gb.SEEDS]
    cases += [{"id": gb.case_id("justify", p, a, s), "run": ("justify", p, a, s)}
              for p, a in justify for s in gb.SEEDS]
    cases.append({"id": "episode", "run": ("episode", gb.EPISODE_PROBLEM, None, gb.EPISODE_SEED)})
    return cases


def extended_cases(extra: Path | None = None) -> list[dict]:
    """The extended baseline's cases, plus the cases of the JSON list *extra* (candidates being measured)."""
    from tests.support import golden_extended as ge

    spec = ge.load_cases()
    cases = list(spec["cases"]) + (json.loads(extra.read_text()) if extra is not None else [])
    return [{"id": c["id"], "extended": c, "parameters": spec["parameters"], "backend": c.get("backend") or spec.get("backend")}
            for c in cases]


def run_case(case: dict) -> dict:
    """Run one case under both tools in this (fresh) process."""
    import coverage

    from tests.support import golden_baseline as gb
    from tests.support import golden_extended as ge

    meta = gb.load_meta()
    sys.monitoring.restart_events()
    cov = coverage.Coverage(config_file=False, branch=True, data_file=None,
                            include=[f"{ROOT}/server/engine/*"])
    monitor = DbMonitor()
    cov.start()
    monitor.start()
    try:
        if "extended" in case:
            ge.capture_case(meta, case["extended"], case["parameters"], case["backend"])
        else:
            from server.engine.memory import EpisodicMemory

            kind, problem, answer, seed = case["run"]
            if kind == "episode":
                memory, check = EpisodicMemory(), EpisodicMemory()
                for k in range(1, gb.EPISODE_RUNS + 1):
                    gb.capture_run(meta, problem, seed + k - 1, None, memory, "episode", run=k, check_memory=check)
            else:
                gb.capture_run(meta, problem, seed, answer, EpisodicMemory(), kind)
    finally:
        monitor.stop()
        cov.stop()
    data = cov.get_data()
    return {
        "engine": {f: (sorted(data.lines(f) or ()), sorted(data.arcs(f) or ())) for f in data.measured_files()},
        "db_lines": sorted(monitor.lines),
        "db_branches": sorted(monitor.branches),
    }


def import_baseline() -> dict:
    """What importing every engine module executes (counted once, not per case)."""
    import importlib
    import pkgutil

    import coverage

    cov = coverage.Coverage(config_file=False, branch=True, data_file=None, include=[f"{ROOT}/server/engine/*"])
    cov.start()
    import server.engine

    for module in pkgutil.walk_packages(server.engine.__path__, "server.engine."):
        try:
            importlib.import_module(module.name)
        except Exception:  # noqa: BLE001 - an optional backend that cannot import here
            pass
    cov.stop()
    data = cov.get_data()
    return {f: (sorted(data.lines(f) or ()), sorted(data.arcs(f) or ())) for f in data.measured_files()}


# --------------------------------------------------------------------------- the report


def measure(cases: list[dict], jobs: int, keep: Path | None = None) -> dict:
    engine: dict[str, list[set]] = {}
    db_lines: set = set()
    db_branches: set = set()

    def absorb(files: dict) -> None:
        for filename, (lines, arcs) in files.items():
            entry = engine.setdefault(filename, [set(), set()])
            entry[0] |= set(lines)
            entry[1] |= {tuple(a) for a in arcs}

    absorb(import_baseline())
    with ProcessPoolExecutor(jobs, max_tasks_per_child=1) as pool:
        for case, result in zip(cases, pool.map(run_case, cases)):
            if keep is not None:
                keep.mkdir(parents=True, exist_ok=True)
                (keep / (case["id"].replace("/", "_") + ".json")).write_text(json.dumps({
                    "id": case["id"],
                    "engine": {f: [lines, arcs] for f, (lines, arcs) in result["engine"].items()},
                    "db_lines": result["db_lines"], "db_branches": result["db_branches"]}))
            absorb(result["engine"])
            db_lines |= {tuple(x) for x in result["db_lines"]}
            db_branches |= {tuple(x) for x in result["db_branches"]}
    return {"engine": engine, "db_lines": db_lines, "db_branches": db_branches}


def report(measured: dict, out: Path) -> dict:
    import coverage
    from coverage.sqldata import CoverageData

    from tests.support import golden_baseline as gb

    out.mkdir(parents=True, exist_ok=True)
    data_file = out / "coverage.sqlite"
    if data_file.exists():
        data_file.unlink()
    data = CoverageData(basename=str(data_file))
    data.add_arcs({f: sorted(arcs) for f, (lines, arcs) in measured["engine"].items()})
    data.write()
    rc = out / "coveragerc"
    rc.write_text("[run]\nbranch = True\n")
    cov = coverage.Coverage(config_file=str(rc), data_file=str(data_file))
    cov.load()
    json_path = out / "engine.json"
    cov.json_report(outfile=str(json_path), ignore_errors=True, include=[f"{ROOT}/server/engine/*"])
    engine = json.loads(json_path.read_text())

    meta = gb.load_meta()
    universe_lines, universe_branches, units = db_universe(meta)
    missing_lines = sorted(universe_lines - measured["db_lines"])
    missing_branches = sorted(universe_branches - measured["db_branches"])
    totals = engine["totals"]
    summary = {
        "engine_lines": [totals["covered_lines"], totals["num_statements"]],
        "engine_branches": [totals["covered_branches"], totals["num_branches"]],
        "db_lines": [len(universe_lines) - len(missing_lines), len(universe_lines)],
        "db_branches": [len(universe_branches) - len(missing_branches), len(universe_branches)],
    }
    full = {
        "summary": summary,
        "engine_files": {f.replace(str(ROOT) + "/", ""): {
            "missing_lines": d["missing_lines"], "missing_branches": d["missing_branches"],
            "num_statements": d["summary"]["num_statements"], "num_branches": d["summary"]["num_branches"]}
            for f, d in engine["files"].items()},
        "db_missing_lines": [list(x) for x in missing_lines],
        "db_missing_branch_arcs": [list(x) for x in missing_branches],
    }
    (out / "coverage.json").write_text(json.dumps(full, indent=1))
    return full


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--which", choices=["original", "extended", "both"], default="both")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--out", type=Path, default=ROOT / "agents-workspace" / "golden-coverage")
    ap.add_argument("--extra-cases", type=Path, default=None,
                    help="a JSON list of further extended-format cases to measure with the baseline")
    ap.add_argument("--keep", type=Path, default=None,
                    help="write each case's own reached lines, arcs and database sets here (one JSON file per case)")
    args = ap.parse_args(argv)
    cases = (original_cases() if args.which in ("original", "both") else []) \
        + (extended_cases(args.extra_cases) if args.which in ("extended", "both") else [])
    started = time.time()
    measured = measure(cases, args.jobs, args.keep)
    full = report(measured, args.out)
    s = full["summary"]
    print(f"{len(cases)} cases in {time.time() - started:.0f}s ({args.which})")
    print(f"engine   lines {s['engine_lines'][0]}/{s['engine_lines'][1]}   branches {s['engine_branches'][0]}/{s['engine_branches'][1]}")
    print(f"database lines {s['db_lines'][0]}/{s['db_lines'][1]}   branch arcs {s['db_branches'][0]}/{s['db_branches'][1]}")
    worst = sorted(full["engine_files"].items(),
                   key=lambda kv: -(len(kv[1]["missing_lines"]) + len(kv[1]["missing_branches"])))[:12]
    for name, d in worst:
        print(f"  {name:48s} unreached lines {len(d['missing_lines']):4d}  branches {len(d['missing_branches']):4d}")
    print(f"details: {args.out / 'coverage.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
