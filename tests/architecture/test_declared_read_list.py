"""The declared read list holds the engine's reads to the Metacat Standard Configuration.

``server/engine/start_check.py`` names every parameter and formula coefficient the engine reads,
and derives the urgency levels the configuration's own code names (a codelet body that reads a
tier), so a configuration that lacks one stops the run at its start (I-1) instead of failing
mid-run.  This test keeps that list honest in both directions, by parsing the source:

* every literal name passed to ``get_param`` or ``get_formula_coeff`` anywhere in ``server/`` is
  declared, and ``get_urgency`` is never given a literal tier in ``server/`` (a tier the
  configuration's code names is the configuration's, derived by the run-start check from the
  bodies);
* a computed name is declared through each of its concrete names (a conditional expression
  names two), or is one of the few reads listed below whose names come from data;
* every declared name exists in the Metacat Standard Configuration, and no name is declared twice;
* the converse: every name stored in ``engine_params``, ``formula_coefficients`` and
  ``urgency_levels`` is read, by an accessor in ``server/``, by a seed codelet body, or (for a
  tier) by being named by a posting rule, a codelet pattern, a parameter that names a level or
  the clamp-background table.  There is no list of exceptions: a stored number nothing reads is
  a dead row (or a literal in the engine that ignores it), and the test fails until it is read
  or deleted;
* no read passes a code default (bug B12): ``get_param(name, default)`` is gone.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from server.engine import start_check as sc

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
SEED = ROOT / "seed_data"

_ACCESSORS = ("get_param", "get_formula_coeff", "get_urgency")

#: Reads whose name is not a literal and not a conditional of literals, and why each is fine.
#: (file relative to ``server/``, the accessor, the unparsed argument).  A new computed read
#: fails the test until it is declared here, with the reason.
_COMPUTED_READS: dict[tuple[str, str, str], str] = {
    ("api/runs.py", "get_param", "p.name"): "the per-run catalogue, shown with None when absent",
    ("engine/run_binding.py", "get_formula_coeff", "f.metadata['key'] or f.name"): "the name each formula() field declares, checked by _declarator_read",
    ("engine/run_binding.py", "get_param", "f.metadata['key'] or f.name"): "the name each param() field declares, checked by _declarator_read",
    ("engine/parameters.py", "get_param", "p.name"): "the per-run catalogue, shown with None when absent",
    ("engine/rule_english.py", "get_param", "name"): "the names are passed as literals to _param",
    ("engine/coderack.py", "get_urgency", "background"): "a level named by the clamp table (very_low)",
    ("engine/coderack.py", "get_urgency", "urgency"): "a level a codelet pattern names (checked per entry)",
    ("engine/coderack.py", "get_urgency", "entry['urgency']"): "a level a codelet pattern names (checked per entry)",
    ("engine/runner.py", "get_urgency", "self.meta.get_param('initial_codelet_urgency')"): "checked by name",
    ("engine/bridges.py", "get_urgency", "ctx.meta.get_param('bridge_recruit_urgency_level')"): "checked by name",
    ("engine/start_check.py", "get_param", "parameter"): "each parameter whose refers_to is urgency_level (a name the configuration declares)",
    ("services/run_service.py", "get_urgency", "ctx.meta.get_param('manual_clamp_background_level')"): "checked by name (refers_to urgency_level)",
    ("services/run_service.py", "get_urgency", "level"): "a level a codelet pattern names (checked per entry)",
    ("engine/posting.py", "get_urgency", "rule.urgency_level"): "a tier a posting rule names (checked per rule)",
    ("engine/posting.py", "get_urgency", "meta.get_param('default_urgency_level')"): "checked by name",
    ("engine/runner.py", "get_urgency", "self.meta.get_param('default_urgency_level')"): "checked by name",
}

#: Reads made by the seed codelet bodies (``seed_data/codelet_types.json``).  They are declared like the
#: engine's own, and no body passes a code default.
_BODY_READ = re.compile(r"meta\.(get_param|get_formula_coeff|get_urgency)\('([a-z_0-9]+)'(,)?")

#: Helper wrappers that take the name as their second argument: ``_param(meta, "name")``.
_WRAPPERS = {("engine/rule_english.py", "_param")}


#: ``RunConstants`` (``engine/run_binding.py``) declares a field as ``name: T = formula()`` or
#: ``= param()``, which reads the formula coefficient or engine parameter of the field's own name
#: (or of the literal passed: ``formula("other")``).  Those declarations are reads like any other.
_RUN_CONSTANTS_FILE = "engine/run_binding.py"
_DECLARATORS = {"formula": "get_formula_coeff", "param": "get_param"}


def _declarator_read(node: ast.AST) -> tuple[str, str] | None:
    if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
        return None
    call = node.value
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id in _DECLARATORS):
        return None
    accessor = _DECLARATORS[call.func.id]
    if call.args:
        arg = call.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return accessor, arg.value
        return None
    return accessor, node.target.id


def _reads() -> tuple[dict[tuple[str, str], set[str]], list[tuple[str, str, str]], list[str]]:
    """(accessor, literal name) -> files; computed reads; reads that pass a default."""
    literal: dict[tuple[str, str], set[str]] = {}
    computed: list[tuple[str, str, str]] = []
    defaults: list[str] = []
    for path in sorted(SERVER.rglob("*.py")):
        rel = path.relative_to(SERVER).as_posix()
        tree = ast.parse(path.read_text())
        if rel == _RUN_CONSTANTS_FILE:
            for node in ast.walk(tree):
                name = _declarator_read(node)
                if name is not None:
                    literal.setdefault(name, set()).add(rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and (rel, func.id) in _WRAPPERS and len(node.args) >= 2:
                arg = node.args[1]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    literal.setdefault(("get_param", arg.value), set()).add(rel)
                continue
            if not (isinstance(func, ast.Attribute) and func.attr in _ACCESSORS and node.args):
                continue
            if func.attr == "get_param" and (len(node.args) > 1 or node.keywords):
                defaults.append(f"{rel}:{node.lineno}")
            arg = node.args[0]
            names: list[ast.expr] = [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
            for name in names:
                if isinstance(name, ast.Constant) and isinstance(name.value, str):
                    literal.setdefault((func.attr, name.value), set()).add(rel)
                else:
                    computed.append((rel, func.attr, ast.unparse(name)))
    for body in json.loads((SEED / "codelet_types.json").read_text()):
        for accessor, name, comma in _BODY_READ.findall(body.get("execute_body", "")):
            literal.setdefault((accessor, name), set()).add(f"codelet body {body['name']}")
            if comma:
                defaults.append(f"codelet body {body['name']}: {name}")
    return literal, computed, defaults


def _declared() -> dict[str, set[str]]:
    return {
        "get_param": {n for n, _ in sc.REQUIRED_ENGINE_PARAMETERS}
        | {n for n, _ in sc.OPTIONAL_ENGINE_PARAMETERS},
        "get_formula_coeff": {n for n, _ in sc.REQUIRED_FORMULA_COEFFICIENTS},
        "get_urgency": set(_tiers_named_by_bodies()),
    }


def _tiers_named_by_bodies() -> dict[str, list[str]]:
    """The urgency tiers the Standard Configuration's codelet bodies read, which the run-start check
    requires of a configuration (``start_check.urgency_levels_read_by_bodies``)."""
    bodies = json.loads((SEED / "codelet_types.json").read_text())
    return sc.urgency_levels_read_by_bodies((b["name"], b.get("execute_body", "")) for b in bodies)


def _level_naming_parameters() -> tuple[str, ...]:
    """The Standard Configuration's parameters whose value names an urgency level
    (``engine_param_refs.json``: ``refers_to`` is ``urgency_level``)."""
    refs = json.loads((SEED / "engine_param_refs.json").read_text())
    return tuple(n for n, kind in refs.items() if kind == "urgency_level")


def test_every_literal_name_the_engine_reads_is_declared() -> None:
    literal, _, _ = _reads()
    declared = _declared()
    missing = sorted(
        f"{accessor}({name!r}) in {sorted(files)}"
        for (accessor, name), files in literal.items()
        if name not in declared[accessor]
    )
    assert not missing, "read but not on the declared read list in start_check.py: " + "; ".join(missing)


def test_the_engine_reads_no_tier_by_a_literal_name() -> None:
    """A tier is named by the configuration: by a codelet body, a posting rule, a codelet pattern,
    a clamp type or a parameter whose ``refers_to`` is ``urgency_level``.  Renaming a tier in the
    rows and in that code must leave a run unchanged, so no module of ``server/`` spells one."""
    literal, _, _ = _reads()
    offenders = sorted(
        f"get_urgency({name!r}) in {sorted(files)}"
        for (accessor, name), files in literal.items()
        if accessor == "get_urgency" and not all(f.startswith("codelet body ") for f in files)
    )
    assert not offenders, "the engine names an urgency tier: " + "; ".join(offenders)


def test_every_computed_read_is_accounted_for() -> None:
    _, computed, _ = _reads()
    unknown = sorted(set(computed) - set(_COMPUTED_READS))
    assert not unknown, f"computed reads with no entry in _COMPUTED_READS: {unknown}"


def test_no_read_passes_a_code_default() -> None:
    _, _, defaults = _reads()
    assert not defaults, f"get_param called with a default at {defaults} (bug B12)"


def test_every_declared_name_is_in_the_metacat_standard_configuration() -> None:
    seed = {
        "get_param": set(json.loads((SEED / "engine_params.json").read_text())),
        "get_formula_coeff": set(json.loads((SEED / "formula_coefficients.json").read_text())),
        "get_urgency": set(json.loads((SEED / "urgency_levels.json").read_text())),
    }
    absent = sorted(
        f"{accessor}: {name}"
        for accessor, names in _declared().items()
        for name in names
        if name not in seed[accessor]
    )
    assert not absent, f"declared but not in the Metacat Standard Configuration: {absent}"


def test_no_name_is_declared_twice() -> None:
    for label, table in (
        ("parameters", sc.REQUIRED_ENGINE_PARAMETERS + sc.OPTIONAL_ENGINE_PARAMETERS),
        ("coefficients", sc.REQUIRED_FORMULA_COEFFICIENTS),
    ):
        names = [n for n, _ in table]
        assert len(names) == len(set(names)), (
            f"{label} declared twice: {sorted({n for n in names if names.count(n) > 1})}"
        )


def test_every_declared_name_is_read_somewhere() -> None:
    """A declared name nothing reads would stop a run for no reason."""
    read = _names_read()
    unread = sorted(
        n
        for accessor, table in (
            ("get_param", sc.REQUIRED_ENGINE_PARAMETERS),
            ("get_formula_coeff", sc.REQUIRED_FORMULA_COEFFICIENTS),
            ("get_urgency", [(n, ", ".join(users)) for n, users in _tiers_named_by_bodies().items()]),
        )
        for n, _ in table
        if n not in read[accessor]
    )
    assert not unread, f"declared, but nothing reads them: {unread}"


def test_every_level_naming_parameter_is_declared() -> None:
    """A parameter whose value names an urgency level is itself read, so it is declared."""
    declared = _declared()["get_param"]
    assert set(_level_naming_parameters()) <= declared


# --- The converse: every stored name is read --------------------------------------------------


def _stored() -> dict[str, set[str]]:
    return {
        "get_param": set(json.loads((SEED / "engine_params.json").read_text())),
        "get_formula_coeff": set(json.loads((SEED / "formula_coefficients.json").read_text())),
        "get_urgency": set(json.loads((SEED / "urgency_levels.json").read_text())),
    }


def _names_read() -> dict[str, set[str]]:
    """Every name read, by accessor kind: literal accessor calls in ``server/`` (including the
    ``rule_english._param`` wrapper), the seed codelet bodies, and, for tiers, the data that
    names one (posting rules, codelet patterns, level-naming parameters, the clamp background)."""
    literal, _, _ = _reads()
    read: dict[str, set[str]] = {kind: set() for kind in _ACCESSORS}
    for (accessor, name) in literal:
        read[accessor].add(name)

    posting = json.loads((SEED / "posting_rules.json").read_text())
    for rule in posting["posting_rules"]:
        if rule.get("urgency_level"):
            read["get_urgency"].add(rule["urgency_level"])
    for entries in posting.get("codelet_patterns", {}).values():
        for entry in entries:
            read["get_urgency"].add(entry[1] if isinstance(entry, (list, tuple)) else entry["urgency"])
    params = json.loads((SEED / "engine_params.json").read_text())
    for parameter in _level_naming_parameters():
        read["get_urgency"].add(params[parameter])
    # A clamp type's ``codelet_background_level`` is read by ``trace_display`` through the type's
    # ``meta.clamp_types`` row.
    enums = json.loads((SEED / "enums.json").read_text())
    read["get_urgency"].update(
        row["codelet_background_level"]
        for row in enums["clamp_types"]
        if row.get("codelet_background_level")
    )
    return read


def test_every_stored_name_is_read_somewhere() -> None:
    """The half the other tests lack: nothing is stored that nothing reads.

    A stored number that nothing reads looks like a setting and does nothing (``default_urgency``),
    and one the engine repeats as a literal changes nothing when edited (``max_theme_activation``
    beside ten ``100.0``s).  Each of these names is the only copy of its number: it must be read.
    """
    read = _names_read()
    unread = {
        accessor: sorted(names - read[accessor]) for accessor, names in _stored().items()
    }
    unread = {k: v for k, v in unread.items() if v}
    assert not unread, f"stored, but nothing reads them: {unread}"
