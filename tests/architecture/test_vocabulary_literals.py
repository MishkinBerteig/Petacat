"""The vocabulary guard: the engine does not spell a name the configuration binds.

Stage 4 of the Metacat finish (``agents-workspace/metacat-cleanup/round2/I4-names/NAME-DESIGN.md``,
section 4.3).  The engine owns *concepts* (a bridge joins the top strings, a clamp holds the
rack against a background); the configuration owns the *names* it gives them.  Every enum
table row the engine names carries a ``role`` (``server/engine/roles.py``, ``VOCABULARY``), and
the engine reads the name bound to the role once per run (``meta.vocabulary``).  So no line of
``server/engine/``, ``server/parallel/``, ``server/services/`` or ``server/api/`` may spell a bound
name, and no codelet body,
descriptor predicate or posting formula of the Metacat Standard Configuration may either: they
write ``role('bridge_type.top')``.

Test 1 is an AST walk of every module under those four trees (docstrings
and bare string statements are exempt) for a string literal equal to the name of a row of a
vocabulary table (``seed_data/enums.json`` and ``theme_relations.json``), to a link type, or to an
urgency level.  (``run_statuses`` is not scanned: ruling 13 keeps a run's lifecycle names as the
engine's own, and the services compare through ``runner.STATUS_*``.)  A hit is allowed only if it is in ``ALLOWED`` below, with its reason.  The list is
strict in both directions: a literal that is not listed fails, and an entry that is no longer hit
fails too (delete it).

Test 2 does the same for the code in the Standard Configuration files.

Test 3 pins each role to the row Metacat names (the old ``test_enum_constants`` pin, now stated on
the binding).

To list the current hits: ``.venv/bin/python tests/architecture/test_vocabulary_literals.py``.
"""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = REPO_ROOT / "seed_data"
TREES = (
    REPO_ROOT / "server" / "engine", REPO_ROOT / "server" / "parallel",
    REPO_ROOT / "server" / "services", REPO_ROOT / "server" / "api",
)

#: Files that are exempt as a whole, with the reason.  ``roles.py`` declares the engine's roles:
#: the suffix of a role (``bridge_type.top``) is the engine's own name for a concept, which the
#: configuration binds to a row of any name; the bound name itself is never written there.
EXEMPT_FILES: dict[str, str] = {
    "server/engine/roles.py": "declares the roles; a role's name is the engine's, not the row's",
}

#: Python's attribute-access builtins: the string they take is an attribute name (``getattr(o,
#: "vertical_bridge", None)``), a Python name and not a vocabulary one (ruling 13).
ATTRIBUTE_BUILTINS = frozenset({"getattr", "hasattr", "setattr", "delattr"})

#: ``(file, literal) -> (allowed count, reason)``.  Every entry says why the word is not the
#: vocabulary name in that place.  Keep this list as small as you can justify.
ALLOWED: dict[tuple[str, str], tuple[int, str]] = {
    # -- Python attribute names chosen by a bridge's orientation (ruling 13: attribute names stay)
    ("server/engine/bridges.py", "vertical_bridge"): (
        3, "the attribute of a Letter or Group that holds its vertical bridge, chosen by orientation"),
    ("server/engine/workspace.py", "vertical_bridge"): (
        1, "the attribute of a Letter or Group that holds its vertical bridge, walked with getattr"),
    # -- keys of private and wire formats, which the engine writes and a reader of that format reads
    ("server/engine/ids.py", "answer"): (
        1, "the id counter's key for Episodic Memory answers: a key of the allocator's own format"),
    ("server/engine/ids.py", "snag"): (
        1, "the id counter's key for Episodic Memory snags: a key of the allocator's own format"),
    ("server/engine/metadata.py", "answer"): (
        1, "a key of the demo_problems.json file format (the DemoProblem columns)"),
    ("server/engine/metadata.py", "initial"): (
        1, "a key of the demo_problems.json file format (the DemoProblem columns)"),
    ("server/engine/metadata.py", "modified"): (
        1, "a key of the demo_problems.json file format (the DemoProblem columns)"),
    ("server/engine/metadata.py", "target"): (
        1, "a key of the demo_problems.json file format (the DemoProblem columns)"),
    ("server/engine/answer_comparison.py", "answer"): (
        1, "the key of the API payload's preferred.answer, which the client reads"),
    ("server/engine/memory.py", "answer"): (
        1, "the key of the API payload's preferred.answer, which the client reads"),
    ("server/engine/serialization.py", "answer"): (
        1, "a field name of the Workspace state the client reads (state.answer)"),
    ("server/engine/serialization.py", "initial"): (
        1, "a field name of the Workspace state the client reads (state.initial)"),
    ("server/engine/serialization.py", "modified"): (
        1, "a field name of the Workspace state the client reads (state.modified)"),
    ("server/engine/serialization.py", "target"): (
        1, "a field name of the Workspace state the client reads (state.target)"),
    ("server/engine/serialization.py", "built"): (
        4, "the boolean field `built` of a bond, group, bridge and rule in the state the client reads"),
    ("server/engine/serialization.py", "category"): (
        2, "the field `category` of a bond and a group in the state the client reads"),
    ("server/engine/serialization.py", "verbatim"): (
        1, "the boolean field `verbatim` of a rule in the state the client reads"),
    ("server/engine/trace_display.py", "answer"): (
        1, "a field name of the display payload the client reads"),
    ("server/engine/trace_display.py", "initial"): (
        1, "a field name of the display payload the client reads"),
    ("server/engine/trace_display.py", "modified"): (
        1, "a field name of the display payload the client reads"),
    ("server/engine/trace_display.py", "target"): (
        1, "a field name of the display payload the client reads"),
    # -- names the engine owns and the configuration refers to
    ("server/engine/rule_english.py", "change"): (
        1, "key of the rule-English grammar's template table (commentary_templates.rule_english), engine-owned"),
    ("server/engine/rule_english.py", "swap"): (
        1, "key of the rule-English grammar's template table (commentary_templates.rule_english), engine-owned"),
    ("server/engine/rule_english.py", "verbatim"): (
        1, "key of the rule-English grammar's template table (commentary_templates.rule_english), engine-owned"),
    ("server/engine/runner.py", "answer_found"): (
        1, "STATUS_ANSWER_FOUND, a value of run_statuses (the run's lifecycle, kept by ruling 13), not an event type"),
    ("server/engine/slipnet.py", "category"): (
        1, "an engine-owned link behaviour (link_types.behaviour), which a link type's row refers to"),
    ("server/engine/slipnet.py", "instance"): (
        1, "an engine-owned link behaviour (link_types.behaviour), which a link type's row refers to"),
    ("server/engine/slipnet.py", "lateral"): (
        1, "an engine-owned link behaviour (link_types.behaviour), which a link type's row refers to"),
    ("server/engine/slipnet.py", "property"): (
        1, "an engine-owned link behaviour (link_types.behaviour), which a link type's row refers to"),
}


def _group(reason: str, entries: dict[str, dict[str, int]]) -> dict[tuple[str, str], tuple[int, str]]:
    """``{file: {literal: count}}`` of one reason, as ``ALLOWED`` entries."""
    return {(f, lit): (n, reason) for f, lits in entries.items() for lit, n in lits.items()}


#: ``server/services/`` and ``server/api/``.  The hits there are the words of data formats that
#: happen to be vocabulary names: the four problem fields, a payload key, a column.  Each group
#: states the format; none is compared with a name the configuration binds.  A vocabulary name
#: the services compare against (a proposal level, a string kind, a rule type, a run's story) is
#: read from ``meta.vocabulary`` and is not listed.
ALLOWED.update(_group(
    "a field of the problem JSON the API takes and returns (initial, modified, target, answer), "
    "or a column of demo_problems and of a Training Mode Session's problems: a key of that "
    "format, not the string kind's name",
    {
        "server/api/admin.py": {"answer": 1, "initial": 1, "modified": 1, "target": 1},
        "server/api/training_mode_sessions.py": {"answer": 4, "initial": 5, "modified": 5, "target": 5},
        "server/services/change_resolve/core.py": {"answer": 1, "initial": 1, "modified": 1, "target": 1},
        "server/services/config_document.py": {"answer": 2, "initial": 2, "modified": 2, "target": 2},
        "server/services/metadata_service.py": {"answer": 1, "initial": 1, "modified": 1, "target": 1},
        "server/services/problem_text.py": {"answer": 2, "initial": 2, "modified": 2, "target": 2},
        "server/services/review_service.py": {"answer": 1, "initial": 1, "modified": 1, "target": 1},
        "server/services/training_mode_session_service.py": {
            "answer": 11, "initial": 8, "modified": 8, "target": 8},
    }))
ALLOWED.update(_group(
    "a key of the Workspace-state payload the client reads: the problem fields (state.problem), "
    "and the boolean field `built`, `verbatim` and the `category` of a bond or group; the value "
    "behind each key is read from the vocabulary",
    {
        "server/services/capture_projection.py": {
            "answer": 2, "built": 4, "category": 2, "initial": 2, "modified": 2, "target": 2,
            "verbatim": 1},
    }))
ALLOWED.update(_group(
    "a key of the Review payload the client reads: `rules.top` and `rules.bottom`, and the "
    "`built` counts of the structure summary",
    {"server/services/review_service.py": {"bottom": 1, "built": 4, "top": 1}}))
ALLOWED.update(_group(
    "the key `top` of a Training Mode Session's top-answers list (the most frequent answers), "
    "which is not the rule type or bridge type `top`",
    {
        "server/api/training_mode_sessions.py": {"top": 2},
        "server/services/training_mode_session_service.py": {"top": 3},
    }))
ALLOWED.update(_group(
    "the key `change` of a configuration comparison row (added, removed or changed): a field of "
    "that payload, not the failure kind `change`",
    {
        "server/services/configuration_admin.py": {"change": 7},
        "server/services/configuration_compare.py": {"change": 7},
        "server/services/session_configuration_views.py": {"change": 5},
    }))
ALLOWED.update(_group(
    "the `proposed` column of a journal entry (the ops as submitted): a database column, not the "
    "proposal level `proposed`",
    {"server/services/journal_views.py": {"proposed": 2}}))
ALLOWED.update(_group(
    "the key `target` of the change schema's `reference` object (the table a column points to)",
    {"server/services/change_resolve/spec.py": {"target": 1}}))
ALLOWED.update(_group(
    "the audit action type `answer` and its payload key: the private format of the Audit action "
    "log (the id counters' `answer` kind is `ids.KIND_ANSWER`)",
    {"server/services/sinks.py": {"answer": 2}}))


def vocabulary_names() -> dict[str, set[str]]:
    """Every name the engine may not spell, with the tables it is a row of."""
    names: dict[str, set[str]] = {}

    def add(table: str, name: str) -> None:
        names.setdefault(name, set()).add(table)

    enums = json.loads((SEED_DIR / "enums.json").read_text())
    for table, rows in enums.items():
        if table in ("run_statuses", "param_value_types", "codelet_phases"):
            continue  # ruling 13: these stay, the engine owns them
        if table in ("codelet_families", "progress_focuses"):
            continue  # a family acts through its `serialised` column; a focus is a key of clamp_types
        for r in rows:
            add(table, r["name"])
    for r in json.loads((SEED_DIR / "theme_relations.json").read_text()):
        add("theme_relations", r["name"])
    for level in json.loads((SEED_DIR / "urgency_levels.json").read_text()):
        add("urgency_levels", level)
    return names


def _files() -> list[Path]:
    out: list[Path] = []
    for tree in TREES:
        out += sorted(p for p in tree.rglob("*.py") if "__pycache__" not in p.parts)
    return out


def _is_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel: str, names: set[str]) -> None:
        self.rel, self.names = rel, names
        self.hits: Counter[tuple[str, str]] = Counter()

    def visit_Expr(self, node: ast.Expr) -> None:  # docstrings and bare strings
        if not _is_str(node.value):
            self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # The attribute name given to getattr/hasattr/setattr/delattr is a Python name.
        if isinstance(node.func, ast.Name) and node.func.id in ATTRIBUTE_BUILTINS and len(node.args) >= 2:
            self.visit(node.args[0])
            for arg in node.args[2:]:
                self.visit(arg)
            for kw in node.keywords:
                self.visit(kw)
            return
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and node.value in self.names:
            self.hits[(self.rel, node.value)] += 1


def scan() -> Counter[tuple[str, str]]:
    names = set(vocabulary_names())
    hits: Counter[tuple[str, str]] = Counter()
    for path in _files():
        rel = str(path.relative_to(REPO_ROOT))
        if rel in EXEMPT_FILES:
            continue
        visitor = _Visitor(rel, names)
        visitor.visit(ast.parse(path.read_text(), filename=rel))
        hits += visitor.hits
    return hits


def test_the_engine_does_not_spell_a_bound_name() -> None:
    current = scan()
    problems = []
    for key, n in sorted(current.items()):
        allowed = ALLOWED.get(key, (0, ""))[0]
        if n > allowed:
            problems.append(f"NEW {key[1]!r} in {key[0]} (x{n}, allowed {allowed})")
    for key, (n, _reason) in sorted(ALLOWED.items()):
        if current.get(key, 0) < n:
            problems.append(
                f"RESOLVED, shrink ALLOWED: {key[1]!r} in {key[0]} (allowed {n}, now {current.get(key, 0)})"
            )
    assert not problems, (
        "The engine may not spell a name the configuration binds to a vocabulary role "
        "(read it from the run's vocabulary).\n  " + "\n  ".join(problems[:60])
        + (f"\n  ... and {len(problems) - 60} more" if len(problems) > 60 else "")
    )


def test_every_allowed_entry_has_a_reason() -> None:
    for key, (n, reason) in ALLOWED.items():
        assert n >= 1 and len(reason.split()) >= 4, f"{key}: say why in a sentence"
        assert (REPO_ROOT / key[0]).exists(), f"{key[0]} is not a file"


def _code_strings() -> list[tuple[str, str]]:
    """``(label, source)`` of every piece of code in the Standard Configuration files."""
    out: list[tuple[str, str]] = []
    for c in json.loads((SEED_DIR / "codelet_types.json").read_text()):
        out.append((f"body of {c['name']}", c.get("execute_body", "")))
    for n in json.loads((SEED_DIR / "slipnet_nodes.json").read_text()):
        if n.get("descriptor_predicate"):
            out.append((f"descriptor predicate of {n['name']}", n["descriptor_predicate"]))
    posting = json.loads((SEED_DIR / "posting_rules.json").read_text())
    for r in posting["posting_rules"]:
        key = r.get("rule_key", r["codelet_type"])
        for column in ("urgency_formula", "posting_formula", "count_formula", "condition"):
            if r.get(column):
                out.append((f"{column} of rule {key}", r[column]))
    return out


#: Urgency tier names that configuration code (a codelet body) may spell: a tier is a row of
#: ``urgency_levels`` that the body refers to, not a name the engine owns; a rename lists the
#: body as dangling, as it does a node named in code.
CODE_MAY_NAME = {"urgency_levels"}


def test_standard_configuration_code_spells_no_bound_name() -> None:
    names = vocabulary_names()
    problems = []
    for label, source in _code_strings():
        if not source.strip():
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = ast.parse(source, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names:
                if names[node.value] <= CODE_MAY_NAME:
                    continue
                problems.append(f"{label} spells {node.value!r}: write role('...')")
    assert not problems, "\n  " + "\n  ".join(problems[:60])


def test_every_role_is_bound_once_to_the_row_metacat_names() -> None:
    """The pin of the old ``test_enum_constants``: each role is bound exactly once in the
    Standard Configuration, and the name is the one Metacat uses (role ``bridge_type.top`` is
    the row ``top``)."""
    from server.engine.metadata import MetadataProvider
    from server.engine.roles import VOCABULARY

    meta = MetadataProvider.from_standard_configuration(str(SEED_DIR))
    bound = Counter(b.role for b in meta.vocabulary_bindings)
    assert set(bound) == {s.name for s in VOCABULARY}, "a role is unbound, or a binding names no role"
    assert all(n == 1 for n in bound.values())
    for b in meta.vocabulary_bindings:
        suffix = b.role.split(".", 1)[1]
        expected = {
            ("clamp_types", "rule_codelet"): "rule_codelet_clamp",
            ("clamp_types", "snag_response"): "snag_response_clamp",
            ("clamp_types", "justify"): "justify_clamp",
            ("clamp_types", "manual"): "manual_clamp",
        }.get((b.table, suffix), suffix)
        assert b.name == expected, f"{b.role} is bound to {b.name!r}, Metacat's name is {expected!r}"


def main() -> None:
    for (file, literal), n in sorted(scan().items()):
        print(f"{file}\t{literal!r}\t{n}")


if __name__ == "__main__":
    sys.exit(main())
