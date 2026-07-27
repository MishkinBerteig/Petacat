#!/usr/bin/env python3
"""Regenerate seed_data/slipnet_links.json from the reference Scheme slipnet.

The original Petacat seed data dropped every explicit link length, so all 202
links fell back to ``SlipnetLink.link_length()``'s default of 50.  In the Scheme
(``slipnet.ss``), ``set-link-length`` also sets ``fixed-length? #t``, so any link
declared with ``length:`` / ``all-lengths:`` is fixed even when it also carries a
label.  Only links declared with ``label:`` alone are dynamic (their length comes
from the label node's intrinsic/shrunk link length).

Run from the Petacat repo root:

    python3 scripts/regen_slipnet_links.py [--check]

``--check`` verifies the checked-in JSON matches the Scheme without writing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCHEME = REPO.parent / "Metacat" / "slipnet.ss"
OUT = REPO / "seed_data" / "slipnet_links.json"

LETTERS = list("abcdefghijklmnopqrstuvwxyz")
NUMBERS = ["one", "two", "three", "four", "five"]

_KINDS = {
    "category-link*": "category",
    "instance-link*": "instance",
    "property-link*": "property",
    "lateral-link*": "lateral",
    "lateral-sliplink*": "lateral_sliplink",
}


def read_conceptual_depths(text: str) -> dict[str, int]:
    """Pull ``(plato-x "short" conceptual-depth: N)`` declarations."""
    depths: dict[str, int] = {}
    pattern = re.compile(
        r'\(plato-([a-z0-9-]+)\s+"[^"]*"\s+conceptual-depth:\s*(\d+)'
    )
    for m in pattern.finditer(text):
        depths[m.group(1)] = int(m.group(2))
    return depths


def top_level_forms(text: str) -> list[str]:
    """Extract each top-level link-declaring s-expression, balanced-paren aware."""
    forms: list[str] = []
    opener = re.compile(r"\((" + "|".join(re.escape(k) for k in _KINDS) + r")")
    i = 0
    while True:
        m = opener.search(text, i)
        if m is None:
            return forms
        start = m.start()
        depth = 0
        j = start
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        forms.append(text[start : j + 1])
        i = j + 1


def parse_length(body: str, depths: dict[str, int]) -> int | None:
    """Parse a ``length:`` / ``all-lengths:`` value, including ``(- (cd a) (cd b))``."""
    m = re.search(r"(?:all-lengths|length):\s*(-?\d+)", body)
    if m:
        return int(m.group(1))
    m = re.search(
        r"(?:all-lengths|length):\s*\(-\s*\(cd\s+plato-([a-z0-9-]+)\)\s*"
        r"\(cd\s+plato-([a-z0-9-]+)\)\s*\)",
        body,
    )
    if m:
        return depths[m.group(1)] - depths[m.group(2)]
    return None


def parse_scheme_links(text: str, depths: dict[str, int]) -> list[dict]:
    links: list[dict] = []

    def add(src: str, dst: str, kind: str, label: str | None, length: int | None) -> None:
        links.append(
            {
                "from_node": f"plato-{src}",
                "to_node": f"plato-{dst}",
                "link_type": kind,
                "label_node": f"plato-{label}" if label else None,
                "link_length": length,
                "fixed_length": length is not None,
            }
        )

    for form in top_level_forms(text):
        flat = " ".join(form.split())
        kind_name = re.match(r"\((\S+)", flat).group(1)
        kind = _KINDS[kind_name]
        body = flat[len(kind_name) + 2 : -1]

        label_m = re.search(r"label:\s*([a-z0-9-]+)", body)
        label = label_m.group(1) if label_m else None
        length = parse_length(body, depths)

        # Strip the keyword arguments, leaving "<lhs> <arrow> <rhs>".
        core = re.sub(
            r"(?:label:|all-lengths:|length:)\s*(?:\([^()]*(?:\([^()]*\)[^()]*)*\)|[a-z0-9-]+|-?\d+)",
            "",
            body,
        ).strip()
        m = re.match(
            r"^(\([^)]*\)|[a-z0-9-]+)\s*(<-->|-->)\s*(\([^)]*\)|[a-z0-9-]+)$", core
        )
        if m is None:
            raise SystemExit(f"could not parse link declaration: {core!r}")

        lhs, arrow, rhs = m.groups()
        expand = lambda s: s[1:-1].split() if s.startswith("(") else [s]
        for a in expand(lhs):
            for b in expand(rhs):
                add(a, b, kind, label, length)
                if arrow == "<-->":
                    add(b, a, kind, label, length)

    # slipnet.ss:690-693 and :705-708 override the bulk category-link lengths for
    # letters and numbers with (category-depth - instance-depth).
    overrides: dict[tuple[str, str], int] = {}
    for letter in LETTERS:
        overrides[(f"plato-{letter}", "plato-letter-category")] = (
            depths["letter-category"] - depths[letter]
        )
    for number in NUMBERS:
        overrides[(f"plato-{number}", "plato-length")] = (
            depths["length"] - depths[number]
        )
    for link in links:
        key = (link["from_node"], link["to_node"])
        if link["link_type"] == "category" and key in overrides:
            link["link_length"] = overrides[key]
            link["fixed_length"] = True

    return links


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if not SCHEME.exists():
        print(f"reference Scheme not found at {SCHEME}", file=sys.stderr)
        return 2

    text = SCHEME.read_text()
    depths = read_conceptual_depths(text)
    links = parse_scheme_links(text, depths)

    existing = json.loads(OUT.read_text())
    old_links = existing["links"] if isinstance(existing, dict) else existing

    # Preserve the checked-in ordering so the diff stays readable.
    order = {
        (lk["from_node"], lk["to_node"], lk["link_type"]): i
        for i, lk in enumerate(old_links)
    }
    links.sort(
        key=lambda lk: order.get(
            (lk["from_node"], lk["to_node"], lk["link_type"]), len(order)
        )
    )

    if len(links) != len(old_links):
        print(
            f"link count changed: scheme={len(links)} existing={len(old_links)}",
            file=sys.stderr,
        )
        return 2

    payload = json.dumps(links, indent=2) + "\n"
    if args.check:
        if payload != OUT.read_text():
            print("slipnet_links.json is out of date with slipnet.ss", file=sys.stderr)
            return 1
        print(f"OK: {len(links)} links match slipnet.ss")
        return 0

    OUT.write_text(payload)
    fixed = sum(1 for lk in links if lk["fixed_length"])
    print(f"wrote {len(links)} links to {OUT} ({fixed} fixed-length, {len(links) - fixed} dynamic)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
