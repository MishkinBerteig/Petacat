"""The declared read list holds the engine's reads to the Metacat Standard Configuration.

``server/engine/start_check.py`` names every parameter, formula coefficient and urgency level
the engine reads, so a configuration that lacks one stops the run at its start (I-1) instead of
failing mid-run.  This test keeps that list honest in both directions, by parsing the source:

* every literal name passed to ``get_param``, ``get_formula_coeff`` or ``get_urgency``
  anywhere in ``server/`` is declared;
* a computed name is declared through each of its concrete names (a conditional expression
  names two), or is one of the few reads listed below whose names come from data;
* every declared name exists in the Metacat Standard Configuration, and no name is declared twice;
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
    ("engine/parameters.py", "get_param", "p.name"): "the per-run catalogue, shown with None when absent",
    ("engine/rule_english.py", "get_param", "name"): "the names are passed as literals to _param",
    ("engine/coderack.py", "get_urgency", "background"): "a level named by the clamp table (very_low)",
    ("engine/coderack.py", "get_urgency", "urgency"): "a level a codelet pattern names (checked per entry)",
    ("engine/coderack.py", "get_urgency", "entry['urgency']"): "a level a codelet pattern names (checked per entry)",
    ("engine/runner.py", "get_urgency", "self.meta.get_param('initial_codelet_urgency')"): "checked by name",
    ("engine/bridges.py", "get_urgency", "ctx.meta.get_param('bridge_recruit_urgency_level')"): "checked by name",
    ("engine/start_check.py", "get_param", "parameter"): "each LEVEL_NAMING_PARAMETERS name, which is declared",
    ("services/run_service.py", "get_urgency", "level"): "a level a codelet pattern names (checked per entry)",
}

#: Reads made by the seed codelet bodies (``seed_data/codelet_types.json``).  They are declared like the
#: engine's own, and no body passes a code default.
_BODY_READ = re.compile(r"meta\.(get_param|get_formula_coeff|get_urgency)\('([a-z_0-9]+)'(,)?")

#: Helper wrappers that take the name as their second argument: ``_param(meta, "name")``.
_WRAPPERS = {("engine/rule_english.py", "_param")}


def _reads() -> tuple[dict[tuple[str, str], set[str]], list[tuple[str, str, str]], list[str]]:
    """(accessor, literal name) -> files; computed reads; reads that pass a default."""
    literal: dict[tuple[str, str], set[str]] = {}
    computed: list[tuple[str, str, str]] = []
    defaults: list[str] = []
    for path in sorted(SERVER.rglob("*.py")):
        rel = path.relative_to(SERVER).as_posix()
        tree = ast.parse(path.read_text())
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
        "get_urgency": {n for n, _ in sc.REQUIRED_URGENCY_LEVELS},
    }


def test_every_literal_name_the_engine_reads_is_declared() -> None:
    literal, _, _ = _reads()
    declared = _declared()
    missing = sorted(
        f"{accessor}({name!r}) in {sorted(files)}"
        for (accessor, name), files in literal.items()
        if name not in declared[accessor]
    )
    assert not missing, "read but not on the declared read list in start_check.py: " + "; ".join(missing)


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
        ("urgency levels", sc.REQUIRED_URGENCY_LEVELS),
    ):
        names = [n for n, _ in table]
        assert len(names) == len(set(names)), (
            f"{label} declared twice: {sorted({n for n in names if names.count(n) > 1})}"
        )


def test_every_declared_name_is_read_somewhere() -> None:
    """A declared name nothing reads would stop a run for no reason."""
    literal, _, _ = _reads()
    read = {name for (_, name) in literal}
    # Names the engine reads by value from a configuration key (the opening batch's level).
    unread = sorted(
        n
        for table in (sc.REQUIRED_ENGINE_PARAMETERS, sc.REQUIRED_FORMULA_COEFFICIENTS,
                      sc.REQUIRED_URGENCY_LEVELS)
        for n, _ in table
        if n not in read
    )
    assert not unread, f"declared, but nothing reads them: {unread}"


def test_every_level_naming_parameter_is_declared() -> None:
    """A parameter whose value names an urgency level is itself read, so it is declared."""
    declared = _declared()["get_param"]
    assert set(sc.LEVEL_NAMING_PARAMETERS) <= declared
