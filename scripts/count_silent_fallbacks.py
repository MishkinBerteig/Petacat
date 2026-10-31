#!/usr/bin/env python3
"""Count the engine's silent fallbacks across the golden-baseline set (EN0).

    .venv/bin/python scripts/count_silent_fallbacks.py --out FILE.json [--baseline engine_baseline.jsonl]

Runs every case of the golden baseline under ``tests/support/fallback_instrumentation.py``
(handled exceptions by ``except`` clause, lookups of a node the Slipnet does not hold by
call site) and writes the report.  Expected under the Metacat Standard Configuration: zero
hits at the three blanket ``except Exception`` blocks of ``justify.py`` and zero missing
node lookups, apart from the lookups the engine makes on purpose (listed by site).  With
``--baseline`` it also checks that observing changed nothing: the records of the observed
run equal the baseline's, line for line.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.support import golden_baseline as gb  # noqa: E402
from tests.support.fallback_instrumentation import Observation, blanket_sites  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, help="a baseline file the observed records must equal")
    args = ap.parse_args(argv)

    meta = gb.load_meta()
    records = []
    with Observation() as obs:
        for record, _ in gb.iter_cases(meta, lambda c: print(c, flush=True)):
            records.append(record)
    report = obs.report()
    report["runs"] = len(records)
    report["justify_blanket_handlers"] = [
        {"line": ln, "clause": clause}
        for ln, clause in blanket_sites(ROOT / "server" / "engine" / "justify.py")]
    if args.baseline:
        report["observed_records_equal_baseline"] = (
            gb.render(records, meta) == args.baseline.read_text())
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "missing_node_lookups"}, indent=1)[:3000])
    print("missing node lookups:", len(report["missing_node_lookups"]), "sites")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
