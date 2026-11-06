"""The policy guard: the engine does not decide by concept where the configuration can say.

Stage 6 of the Metacat finish.  Three kinds of cognition were written as program text, and each
is now read from the configuration:

* **A set of dimensions that behave one way** ("the dimensions that reverse together", "the
  dimensions a rule may name an object by") is an ordered role (``rule.object_naming_dimension``
  ...), bound in ``seed_data/roles.json`` and asked with one ``holds_role(node, role)``.  The
  engine may not ask the same question of one node with several concept roles joined by ``or`` (or
  ``any``/``in``): that spells the set again.
* **The four-string frame** (which bridge type joins which pair of strings, which theme type it
  feeds, which orientations a string kind maps in) is derived once per run from three tables by
  ``server/engine/frame.py``.  The engine may not write a table keyed by two or more bridge types,
  string kinds, theme types or rule types, or compare a string against one string kind, outside
  the places that write a format.
* **The initial-description program** is two tables (``initial_description_rules``,
  ``initial_activation_rules``) applied by ``server/engine/initial_program.py``.  A description
  of a letter is built there and nowhere else in the engine's perception of a new problem.

Like ``test_vocabulary_literals.py`` the lists below are strict in both directions: a hit that is
not listed fails, and an entry that is no longer hit fails too (delete it).  Every entry says why
the code is a definition the engine owns, or a format, and not a policy the configuration can
change.

To list the current hits: ``.venv/bin/python tests/architecture/test_no_policy_in_engine.py``.
"""

from __future__ import annotations

import ast
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TREES = (REPO_ROOT / "server" / "engine", REPO_ROOT / "server" / "parallel")

#: The calls that ask whether a node holds a role.
ROLE_QUESTIONS = frozenset({"holds_role", "_holds", "has_role", "_holds_role", "is_dimension_role"})

#: The roles that name a concept of the problem (a dimension, a position, a category ...).  Two
#: of them asked of one node in one ``or`` is a membership list written in code.
CONCEPT_PREFIXES = ("dimension.", "position.", "direction.", "object.", "bond_category.",
                    "group_category.", "alphabet.")

#: The vocabulary attributes that name a bridge type, a string kind, a theme type or a rule type.
FRAME_PREFIXES = ("bridge_type_", "string_kind_", "theme_type_", "rule_type_")

#: ``(file, kind, text) -> (allowed count, reason)``.
ALLOWED: dict[tuple[str, str, str], tuple[int, str]] = {
    ("server/engine/state_graph.py", "frame-table", "bridge_type_bottom bridge_type_top bridge_type_vertical"): (
        2, "keys of the state graph's own capture format (mapping strengths and inter-string averages); both ends are the engine's"),
    ("server/engine/state_graph.py", "frame-table", "rule_type_bottom rule_type_top"): (
        1, "keys of the state graph's capture format (rule_possible)"),
    ("server/engine/state_graph.py", "frame-table", "string_kind_answer string_kind_initial string_kind_modified string_kind_target"): (
        1, "keys of the state graph's capture format (the problem's four strings)"),
    ("server/engine/trace_display.py", "frame-table", "bridge_type_bottom bridge_type_top bridge_type_vertical"): (
        3, "fields of the display payload the client reads (top_bridges, vertical_bridges, bottom_bridges): a format, not a decision"),
}


def _files() -> list[Path]:
    return sorted(p for tree in TREES for p in tree.rglob("*.py") if "__pycache__" not in p.parts)


def _role_of(call: ast.AST) -> tuple[str, str] | None:
    """``(node text, role)`` when *call* is ``holds_role(node, "<concept role>")`` and the like."""
    if not isinstance(call, ast.Call):
        return None
    f = call.func
    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
    if name not in ROLE_QUESTIONS or not call.args:
        return None
    role = call.args[-1]
    if isinstance(role, ast.Constant) and isinstance(role.value, str) and role.value.startswith(CONCEPT_PREFIXES):
        subject = ast.unparse(call.args[0]) if len(call.args) > 1 else ast.unparse(f.value) if isinstance(f, ast.Attribute) else ""
        return subject, role.value
    return None


def _frame_attr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr.startswith(FRAME_PREFIXES):
        return node.attr
    return None


def scan() -> list[tuple[str, str, str]]:
    hits: list[tuple[str, str, str]] = []
    for path in _files():
        rel = str(path.relative_to(REPO_ROOT))
        tree = ast.parse(path.read_text(), filename=rel)
        for node in ast.walk(tree):
            # a set of dimensions spelled in an ``or``
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                asked = [r for r in (_role_of(v) for v in node.values) if r]
                by_subject: dict[str, set[str]] = {}
                for subject, role in asked:
                    by_subject.setdefault(subject, set()).add(role)
                for subject, roles in by_subject.items():
                    if len(roles) >= 2:
                        hits.append((rel, "role-set", " | ".join(sorted(roles))))
            # a table keyed by (or a tuple of) two or more frame names
            if isinstance(node, (ast.Dict, ast.Tuple, ast.List, ast.Set)):
                elements = node.keys if isinstance(node, ast.Dict) else node.elts
                names = sorted({a for e in elements if e is not None and (a := _frame_attr(e))})
                if len(names) >= 2:
                    hits.append((rel, "frame-table", " ".join(names)))
            # a decision by one frame name
            if isinstance(node, ast.Compare):
                for side in [node.left, *node.comparators]:
                    a = _frame_attr(side)
                    if a and a.startswith(("bridge_type_", "string_kind_")):
                        hits.append((rel, "frame-compare", a))
    return hits


def counts(hits):
    return Counter(hits)


def test_no_policy_in_engine() -> None:
    got = counts(scan())
    problems: list[str] = []
    for key, n in sorted(got.items()):
        allowed = ALLOWED.get(key, (0, ""))[0]
        if n > allowed:
            problems.append(f"{key[0]}: {key[1]} {key[2]!r} x{n} (allowed {allowed}): move it into the configuration "
                            "(a role, or a column of the frame tables), or list it with its reason")
    for key, (n, _reason) in sorted(ALLOWED.items()):
        if got.get(key, 0) < n:
            problems.append(f"{key[0]}: {key[1]} {key[2]!r} is hit {got.get(key, 0)} time(s), the list allows {n}: delete or lower the entry")
    assert not problems, "\n".join(problems)


def test_every_allowed_entry_gives_a_reason() -> None:
    assert all(reason.strip() for _n, reason in ALLOWED.values())


def test_initial_descriptions_are_built_by_the_program_only() -> None:
    """A ``Description(...)`` of a *letter* is made only in ``initial_program.py`` among the code that
    perceives a new problem (``runner.py`` no longer builds one)."""
    runner = (REPO_ROOT / "server" / "engine" / "runner.py").read_text()
    tree = ast.parse(runner)
    built = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "Description"]
    assert not built

    # nor does groups.py (a new group's first descriptions are rows) or answers.py (a translated
    # string's letters); the one Description groups.py makes is the probabilistic Length description
    for name, allowed in (("groups.py", {"attach_length_description"}), ("answers.py", set())):
        tree = ast.parse((REPO_ROOT / "server" / "engine" / name).read_text())
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                made = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Name) and n.func.id == "Description"]
                assert not made or fn.name in allowed, (name, fn.name)


if __name__ == "__main__":
    for (rel, kind, text), n in sorted(counts(scan()).items()):
        print(f"{rel}\t{kind}\t{text}\t{n}")
    sys.exit(0)
