#!/usr/bin/env python3
"""Capture the golden baseline (gate G3, work package EN0).

    .venv/bin/python scripts/capture_golden_baseline.py                 # write the committed files
    .venv/bin/python scripts/capture_golden_baseline.py --out DIR       # write a capture into DIR
    .venv/bin/python scripts/capture_golden_baseline.py --out DIR --text-dump
                                                                        # also every run's full English

The committed files are ``tests/lockstep/golden/engine_baseline.jsonl`` (one record per run:
answer, codelet count, final temperature, per-codelet RNG digest, trace and state hashes,
the English digests) and ``engine_baseline_rng.json.gz`` (every run's RNG call count for
every codelet).  The capture is built from the Metacat Standard Configuration
(``seed_data/*.json``) on the CPU numeric backend, float64, pinned by name.

The baseline is a statement about the engine as it stands before the configuration-source
engine packages.  Re-capture only to *accept* a deliberate change, and say so in the commit.
See ``tests/support/golden_baseline.py`` for what is recorded and how.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.support import golden_baseline as gb  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, help="directory to write into (default: the committed location)")
    ap.add_argument("--text-dump", action="store_true",
                    help="also write every run's full English and codelet types (with --out)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    started = time.time()
    count = 0

    def progress(case: str) -> None:
        nonlocal count
        count += 1
        if not args.quiet:
            print(f"[{count:3d}] {case}", flush=True)

    text, rng_gz, details = gb.capture(progress)
    out = args.out or gb.GOLDEN_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / gb.BASELINE_PATH.name).write_text(text)
    (out / gb.RNG_DETAIL_PATH.name).write_bytes(rng_gz)
    if args.text_dump:
        dump = out / "text"
        dump.mkdir(exist_ok=True)
        for name, body in gb.render_text_dump(details).items():
            (dump / name).write_text(body)
    print(f"{count} runs in {time.time() - started:.1f}s -> {out} "
          f"({len(text)} bytes + {len(rng_gz)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
