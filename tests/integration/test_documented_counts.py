"""The test counts printed in the documentation agree with the suite that ran.

``TESTING.md``, ``README.md`` and the repository's ``CLAUDE.md`` all quote how many
cases each layer holds, how many the suite holds in total, and how many test
functions each file defines.  Those figures go stale the moment a test is added, and
a stale figure in a document about testing is the kind of error that survives a long
time because nothing contradicts it.

This restates them as assertions.  The numbers come from the session that is
running: ``session.items`` is the list pytest collected, so the layer totals, the
suite total and the per-file function counts are all derived from the same
collection the summary block reports, and checking them costs one pass over a list
that already exists.

**Held of a run that asked for everything.**  A narrowed invocation — one file,
``-k``, ``-m``, a chosen backend — collects a subset by design, and comparing a
subset against a document that describes the whole suite would fail for a reason
that has nothing to do with the document.  ``_STATE.full_suite`` is the same signal
the matrix uses to decide whether completeness is required of a run, so the two
agree about what "the whole suite" means.

The client's Vitest figures are outside this: they are produced by a different
runner in a different language, and this session has no access to them.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

from tests.conftest import LAYERS, _STATE, _layer_of

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The documents that quote the suite's size.  ``CLAUDE.md`` sits above the
#: repository and is checked when it is there, which is the arrangement on a working
#: checkout; its absence elsewhere is not a failure.
DOCUMENTS = {
    "TESTING.md": REPO_ROOT / "TESTING.md",
    "README.md": REPO_ROOT / "README.md",
    "CLAUDE.md": REPO_ROOT.parent / "CLAUDE.md",
}

#: A markdown table cell holding nothing but a count.
_COUNT_CELL = re.compile(r"^([\d,]+)$")

#: ``| `test_bonds.py` | 18 | ... |`` — a row of a per-file inventory table.
_FILE_ROW = re.compile(r"^\|\s*`(test_[\w.]+)`\s*\|\s*(\d+)\s*\|")

#: ``**`tests/unit/` — one class or function, ...**`` — the heading above one.
_INVENTORY_HEADING = re.compile(r"^\*\*`tests/(\w+)/`")

#: ``  unit           338 collected    338 run  ...`` — the summary block, quoted in
#: the documentation as sample output.
_SUMMARY_LINE = re.compile(r"^(\w+)\s+([\d,]+)\s+collected\b")

#: A total stated in prose: "1,526 cases", "1,526 test cases", "1,526 tests".  The
#: comma is required, so the matrix block's "250 tests" is not read as a total.
_TOTAL_CLAIM = re.compile(
    r"\b(\d{1,3}(?:,\d{3})+)\b(?=[^.\n]{0,12}?\b(?:cases|tests)\b)"
)


def _normalise_layer(cell: str) -> str | None:
    """``**seed unit**``, ``` `tests/seed_unit/` ``` and ``seed_unit`` -> ``seed_unit``."""
    token = cell.strip().strip("*`").strip()
    token = token.removeprefix("tests/").rstrip("/")
    token = token.replace(" ", "_")
    return token if token in LAYERS else None


def _requires_whole_suite() -> None:
    if not _STATE.full_suite:
        pytest.skip(
            f"narrowed by {_STATE.narrowed_by}: this run collected a subset, and the "
            "documented counts describe the whole suite. Run "
            "`.venv/bin/python -m pytest tests/ -q` to check them."
        )


def _present_documents() -> dict[str, str]:
    return {
        name: path.read_text(encoding="utf-8")
        for name, path in DOCUMENTS.items()
        if path.exists()
    }


def _collected_per_layer(session: pytest.Session) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in session.items:
        counts[_layer_of(item.nodeid)] += 1
    return dict(counts)


def _functions_per_file(session: pytest.Session) -> dict[str, set[str]]:
    """``tests/unit/test_bonds.py -> {test_a, test_b, ...}``.

    Parametrised cases collapse to the function that defines them, which is what the
    inventory tables count: the matrix runs many module files twice, and the column
    those tables carry is the number of test functions the file defines.
    """
    functions: dict[str, set[str]] = defaultdict(set)
    for item in session.items:
        path, _, rest = item.nodeid.replace("\\", "/").partition("::")
        functions[path].add(rest.split("[")[0])
    return functions


def _documented_layer_counts(text: str) -> list[tuple[int, str, int]]:
    """Every ``(line, layer, count)`` a document states, from tables and summaries."""
    found: list[tuple[int, str, int]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()

        summary = _SUMMARY_LINE.match(stripped)
        if summary and summary.group(1) in LAYERS:
            found.append((number, summary.group(1), int(summary.group(2).replace(",", ""))))
            continue

        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 3:
            continue
        named = {layer for cell in cells[:2] if (layer := _normalise_layer(cell))}
        if len(named) != 1:
            continue
        tail = _COUNT_CELL.match(cells[-1])
        if tail:
            found.append((number, named.pop(), int(tail.group(1).replace(",", ""))))
    return found


def test_every_documented_layer_count_is_the_count_that_was_collected(request):
    """Each layer's size, wherever a document states it."""
    _requires_whole_suite()
    measured = _collected_per_layer(request.session)
    wrong: list[str] = []
    checked = 0
    for name, text in _present_documents().items():
        for line, layer, stated in _documented_layer_counts(text):
            checked += 1
            if measured.get(layer) != stated:
                wrong.append(
                    f"{name}:{line} {layer} says {stated}, collected {measured.get(layer)}"
                )
    assert checked >= len(LAYERS), (
        f"only {checked} layer figures were found in the documentation; the parser "
        "no longer recognises the tables it exists to guard"
    )
    assert not wrong, "documented layer counts are out of date:\n  " + "\n  ".join(wrong)


def test_every_documented_suite_total_is_the_total_that_was_collected(request):
    """The "N cases in total" figure, wherever a document states it."""
    _requires_whole_suite()
    total = len(request.session.items)
    wrong: list[str] = []
    checked = 0
    for name, text in _present_documents().items():
        for match in _TOTAL_CLAIM.finditer(text):
            checked += 1
            stated = int(match.group(1).replace(",", ""))
            if stated != total:
                line = text[: match.start()].count("\n") + 1
                wrong.append(f"{name}:{line} says {match.group(1)}, collected {total}")
    assert checked, "no suite total was found in the documentation"
    assert not wrong, "documented suite totals are out of date:\n  " + "\n  ".join(wrong)


def test_the_file_inventory_lists_every_file_at_its_real_size(request):
    """``TESTING.md``'s per-file tables, against the files that were collected."""
    _requires_whole_suite()
    functions = _functions_per_file(request.session)
    text = DOCUMENTS["TESTING.md"].read_text(encoding="utf-8")

    stated: dict[str, int] = {}
    layer: str | None = None
    for line in text.splitlines():
        heading = _INVENTORY_HEADING.match(line)
        if heading:
            layer = heading.group(1)
            continue
        row = _FILE_ROW.match(line)
        if row and layer:
            stated[f"tests/{layer}/{row.group(1)}"] = int(row.group(2))

    assert stated, "no per-file inventory was found in TESTING.md"

    problems: list[str] = []
    for path, count in sorted(stated.items()):
        if path not in functions:
            problems.append(f"{path}: listed at {count}, but nothing was collected from it")
        elif len(functions[path]) != count:
            problems.append(f"{path}: listed at {count}, defines {len(functions[path])}")
    for path in sorted(functions):
        if path not in stated:
            problems.append(f"{path}: defines {len(functions[path])} tests, and is not listed")
    assert not problems, "TESTING.md's file inventory is out of date:\n  " + "\n  ".join(
        problems
    )
