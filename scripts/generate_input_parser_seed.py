#!/usr/bin/env python3
"""Write ``seed_data/input_parser.json`` from Metacat's own recording of its input parser.

Metacat Mode reads a problem through a port of Metacat's input parser
(``server/services/input_parser.py``).  The parser asks three things of a character: how
``char-downcase`` lowers it, whether the lowered character is ``char-alphabetic?`` and
whether it is ``char-numeric?``.  Those answers are data in the Metacat Standard Configuration
(the tables ``input_lowering_ranges`` and ``input_character_ranges``), and this script makes
them from ``tests/lockstep/data/parser_metacat.json.gz``, which
``tests/lockstep/metacat/record_parser.py`` writes by running the real procedures under the
patched Metacat's Chez Scheme.  Python's ``unicodedata`` is not used, so a Python upgrade
cannot change what Metacat Mode perceives.

    python3 scripts/generate_input_parser_seed.py            # write seed_data/input_parser.json
    python3 scripts/generate_input_parser_seed.py --check    # exit 1 if the file differs
    python3 scripts/generate_input_parser_seed.py --measure  # how far Python's tables differ

The recording lists the lowering as runs of consecutive characters.  Many Unicode letters lower
in pairs (every second character of a block), so single-character runs of one ``delta`` at a
constant spacing are merged into one row with a ``step``.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDING = ROOT / "tests" / "lockstep" / "data" / "parser_metacat.json.gz"
OUTPUT = ROOT / "seed_data" / "input_parser.json"


def lowering_rows(downcase: list[list[int]]) -> list[dict[str, int]]:
    """Merge the recording's runs into ``first, last, step, delta`` rows."""
    rows: list[dict[str, int]] = []
    singles: list[list[int]] = []

    def flush() -> None:
        i = 0
        while i < len(singles):
            j = i + 1
            if j < len(singles):
                step = singles[j][0] - singles[i][0]
                while (
                    j < len(singles)
                    and singles[j][2] == singles[i][2]
                    and singles[j][0] - singles[j - 1][0] == step
                ):
                    j += 1
            if j - i >= 2:
                rows.append({"first": singles[i][0], "last": singles[j - 1][0], "step": step,
                             "delta": singles[i][2]})
                i = j
            else:
                rows.append({"first": singles[i][0], "last": singles[i][0], "step": 1,
                             "delta": singles[i][2]})
                i += 1
        singles.clear()

    for first, last, delta in downcase:
        if first == last:
            singles.append([first, last, delta])
        else:
            flush()
            rows.append({"first": first, "last": last, "step": 1, "delta": delta})
    flush()
    rows.sort(key=lambda r: r["first"])
    return rows


def build(recording: dict) -> dict:
    # The parser lowers a character first and then asks about the lowered character, and
    # the recording states the answer for the lowered form of every character.  The two
    # agree for the lowered characters themselves when lowering is idempotent, which is checked.
    lowered = {}
    for first, last, delta in recording["downcase"]:
        for c in range(first, last + 1):
            lowered[c] = c + delta
    for c, to in lowered.items():
        assert lowered.get(to, to) == to, f"lowering is not idempotent at {c:#x}"
    return {
        "recording": {"revision": recording["revision"], "chez_version": recording["chez_version"]},
        "lowering_ranges": lowering_rows(recording["downcase"]),
        "character_ranges": (
            [{"kind": "alphabetic", "first": a, "last": b} for a, b in recording["alphabetic"]]
            + [{"kind": "numeric", "first": a, "last": b} for a, b in recording["numeric"]]
        ),
    }


def measure(recording: dict) -> dict[str, int]:
    """How many scalar values Python's own tables answer differently from Chez's."""
    lowered = {}
    for first, last, delta in recording["downcase"]:
        for c in range(first, last + 1):
            lowered[c] = c + delta

    def in_ranges(ranges: list[list[int]], c: int) -> bool:
        import bisect
        i = bisect.bisect_right([r[0] for r in ranges], c) - 1
        return i >= 0 and c <= ranges[i][1]

    out = {"lowering": 0, "alphabetic": 0, "numeric": 0}
    for c in range(0x110000):
        if 0xD800 <= c < 0xE000:
            continue
        low = lowered.get(c, c)
        py_low = chr(c).lower()
        py_low_c = ord(py_low) if len(py_low) == 1 else c
        if py_low_c != low:
            out["lowering"] += 1
        if chr(low).isalpha() != in_ranges(recording["alphabetic"], c):
            out["alphabetic"] += 1
        if chr(low).isnumeric() != in_ranges(recording["numeric"], c):
            out["numeric"] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if seed_data/input_parser.json differs")
    ap.add_argument("--measure", action="store_true", help="count the characters Python's tables answer differently")
    args = ap.parse_args()
    recording = json.load(gzip.open(RECORDING, "rt", encoding="utf-8"))
    if args.measure:
        print(json.dumps({"python": sys.version.split()[0], "unicodedata": unicodedata.unidata_version,
                          "chez": recording["chez_version"], "differences": measure(recording)}, indent=2))
        return 0
    text = json.dumps(build(recording), indent=1) + "\n"
    if args.check:
        same = OUTPUT.exists() and OUTPUT.read_text() == text
        print("seed_data/input_parser.json is up to date" if same else "seed_data/input_parser.json differs")
        return 0 if same else 1
    OUTPUT.write_text(text)
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
