"""The source-tree figures quoted in the documentation agree with the source tree.

``PHASE 0 PLAN.md`` carries *as-built* callouts giving the size of the engine, the
number of endpoints that take a database session, and the size of the codelet
builtins module; ``README.md`` says how many groups the Run Controls panel has.
Every one of them moves when a module, an endpoint, a builtin or a control group is
added, and none of them is contradicted by anything else in the repository.

Each check measures the figure from the source and compares it with what the
document states, so the document is checked rather than trusted.  The measurement
is defined here, once, and the number in the prose is the same number: a count of
Python files, a count of route functions, a count of lines, a count of rendered
group labels.

**Figures pinned to a baseline commit are not checked here.**  ``PHASE 0 PLAN.md``
states its measurements against commit ``2c5c086`` and quotes them as the evidence a
work package was decided on; they describe a checkout that is not this one, and
holding them to today's source would destroy the evidence.  Only the *as-built*
callouts, which describe the code as it now stands, are checked — each is found by
the sentence it is written in, and a rewrite that removes one fails here rather than
passing silently.

Two kinds of documented figure are deliberately outside this file.  A **wall-clock
figure** depends on the machine, and an assertion about it would fail on a slower one
for a reason that has nothing to do with the repository; those figures name the
machine and the backend they were taken under instead.  A **codelet count for a given
seed** is seeded-run agreement, which the phase plan places outside the gates on
purpose: it breaks legitimately whenever the order of random draws changes, and the
standard a change is held to is expected-range agreement
(``tests/module/test_expected_range.py``).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN = REPO_ROOT / "PHASE 0 PLAN.md"
README = REPO_ROOT / "README.md"

ENGINE = REPO_ROOT / "server" / "engine"
API = REPO_ROOT / "server" / "api"
BUILTINS = ENGINE / "codelet_dsl" / "builtins.py"

#: The panels that render one Run Controls group each.
RUN_CONTROL_PANELS = (
    REPO_ROOT / "client" / "src" / "components" / "RunControlsPanel.tsx",
    REPO_ROOT / "client" / "src" / "components" / "RunParametersPanel.tsx",
    REPO_ROOT / "client" / "src" / "components" / "RunDerivedPanel.tsx",
)

#: A rendered group heading: ``<div style={groupLabelStyle}>Run</div>``.
_GROUP_LABEL = re.compile(r"style=\{groupLabelStyle\}>")

_NUMBER = r"([\d,]+)"


def _stated(document: Path, pattern: str) -> list[int]:
    """Every number a document states in the given context."""
    text = document.read_text(encoding="utf-8")
    return [int(m.group(1).replace(",", "")) for m in re.finditer(pattern, text)]


def _one(document: Path, pattern: str, subject: str) -> int:
    values = _stated(document, pattern)
    assert values, (
        f"{document.name} no longer states {subject} in a form this test recognises; "
        f"the sentence it guards has been rewritten (pattern: {pattern!r})"
    )
    assert len(set(values)) == 1, f"{document.name} states {subject} as {values}"
    return values[0]


# ─────────────────────────────────────────────────────────────────────────────
# The engine's size
# ─────────────────────────────────────────────────────────────────────────────


def _engine_modules() -> list[Path]:
    """Every module under ``server/engine/``.

    ``.py`` files, recursively, excluding the empty ``__init__.py`` markers: a
    package marker is not a module anyone reads, and counting it would make the
    figure depend on how the code happens to be packaged.
    """
    return sorted(
        path
        for path in ENGINE.rglob("*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    )


def test_the_engines_module_count_and_line_count_are_as_documented():
    modules = _engine_modules()
    lines = sum(
        len(path.read_text(encoding="utf-8").splitlines()) for path in modules
    )
    stated_modules = _one(
        PLAN, rf"`server/engine/` holds {_NUMBER} modules", "the engine's module count"
    )
    stated_lines = _one(
        PLAN, rf"holds [\d,]+ modules and {_NUMBER} lines", "the engine's line count"
    )
    assert (stated_modules, stated_lines) == (len(modules), lines), (
        f"PHASE 0 PLAN.md says server/engine/ holds {stated_modules} modules and "
        f"{stated_lines} lines; it holds {len(modules)} modules and {lines} lines"
    )


# ─────────────────────────────────────────────────────────────────────────────
# The database boundary
# ─────────────────────────────────────────────────────────────────────────────


def _session_endpoints() -> list[str]:
    """Route functions in ``server/api/`` whose signature takes a session.

    A route function is one carrying a ``router.<verb>`` decorator, so a helper that
    happens to take a session is not counted and a mention in a docstring is not
    either.  This is the measurement behind "the database boundary": each of these is
    a place an HTTP request reaches Postgres.
    """
    found: list[str] = []
    for path in sorted(API.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorated = any(
                "router." in ast.unparse(d) for d in node.decorator_list
            )
            takes_session = "Depends(get_session)" in ast.unparse(node.args)
            if decorated and takes_session:
                found.append(f"{path.name}::{node.name}")
    return found


def test_the_number_of_endpoints_taking_a_session_is_as_documented():
    endpoints = _session_endpoints()
    stated = _one(
        PLAN,
        rf"with {_NUMBER} endpoints taking `Depends\(get_session\)`",
        "the endpoint count at the database boundary",
    )
    assert stated == len(endpoints), (
        f"PHASE 0 PLAN.md says {stated} endpoints take Depends(get_session); "
        f"{len(endpoints)} do"
    )


# ─────────────────────────────────────────────────────────────────────────────
# The codelet builtins
# ─────────────────────────────────────────────────────────────────────────────


def test_the_builtins_module_size_is_as_documented():
    source = BUILTINS.read_text(encoding="utf-8")
    lines = len(source.splitlines())
    functions = [
        node.name
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    stated_lines = _one(
        PLAN, rf"`builtins.py` holds {_NUMBER} lines", "the builtins line count"
    )
    stated_functions = _one(
        PLAN,
        rf"holds [\d,]+ lines across {_NUMBER} top-level functions",
        "the builtins function count",
    )
    assert (stated_lines, stated_functions) == (lines, len(functions)), (
        f"PHASE 0 PLAN.md says builtins.py holds {stated_lines} lines across "
        f"{stated_functions} top-level functions; it holds {lines} lines across "
        f"{len(functions)}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# The Run Controls panel
# ─────────────────────────────────────────────────────────────────────────────

_GROUP_COUNT_WORDS = {
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}


def test_the_run_controls_group_count_is_as_documented():
    """Each group renders exactly one ``groupLabelStyle`` heading."""
    rendered = sum(
        len(_GROUP_LABEL.findall(path.read_text(encoding="utf-8")))
        for path in RUN_CONTROL_PANELS
    )
    text = README.read_text(encoding="utf-8")
    match = re.search(r"decides how that problem executes, in (\w+) groups", text)
    assert match, (
        "README.md no longer describes the Run Controls panel in a form this test "
        "recognises; the sentence it guards has been rewritten"
    )
    word = match.group(1).lower()
    assert word in _GROUP_COUNT_WORDS, f"README.md says '{word} groups'"
    assert _GROUP_COUNT_WORDS[word] == rendered, (
        f"README.md says the Run Controls panel has {word} ({_GROUP_COUNT_WORDS[word]}) "
        f"groups; {rendered} group headings are rendered"
    )
