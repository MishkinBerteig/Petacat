"""Only ``consolidator`` reads a node's ``noticings`` count (v2.0 plan section 4.3, "Only ``consolidator`` reads it,
so it cannot disturb perception").

Inside ``server/engine/`` the count is read in exactly one place, the ``noticings`` builtin, which reads the spec
field of the same name; no other engine module names either.  No codelet body, in the Metacat Standard Configuration
or in the v2.0 Base, calls the builtin except ``consolidator``'s.  (Writing the count is the change API's, through
``propose_ops``, and a body may spell the column when it proposes an ``adjust`` of it.)
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "server" / "engine"
BUILTINS = "codelet_dsl/builtins.py"
SPEC = "metadata.py"


def _reads(tree: ast.AST) -> list[int]:
    """Lines that name the count: an attribute ``.noticings``, a name ``noticings`` or a keyword ``noticings=``."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "noticings":
            lines.append(node.lineno)
        elif isinstance(node, ast.Name) and node.id == "noticings":
            lines.append(node.lineno)
        elif isinstance(node, ast.keyword) and node.arg == "noticings":
            lines.append(node.value.lineno)
        elif isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "noticings":
            lines.append(node.lineno)
        elif isinstance(node, ast.FunctionDef) and node.name == "noticings":
            lines.append(node.lineno)
        elif isinstance(node, ast.Constant) and node.value == "noticings":
            lines.append(node.lineno)
    return sorted(set(lines))


def test_no_engine_module_reads_the_count_except_the_builtin_and_the_spec_field_it_reads():
    found = {}
    for path in sorted(ENGINE.rglob("*.py")):
        rel = path.relative_to(ENGINE).as_posix()
        lines = _reads(ast.parse(path.read_text()))
        if lines:
            found[rel] = lines
    assert set(found) == {BUILTINS, SPEC}, found
    # in the builtins module it is the registry entry and the function; the spec holds the one field
    assert len(found[SPEC]) == 1, found[SPEC]


def test_the_scan_finds_a_read_in_a_module_that_should_not_have_one():
    assert _reads(ast.parse("def f(spec):\n    return spec.noticings\n"))
    assert _reads(ast.parse("x = noticings(node)\n"))


def _bodies():
    """(label, source) of every codelet body: the Standard's and the v2.0 Base's."""
    for row in json.loads((ROOT / "seed_data" / "codelet_types.json").read_text()):
        if row.get("execute_body"):
            yield f"Standard {row['name']}", row["execute_body"]
    for path in sorted((ROOT / "training_base" / "v2.0" / "codelets").glob("*.py")):
        yield f"v2.0 Base {path.stem}", path.read_text()


def test_no_codelet_body_calls_noticings_except_consolidators():
    callers = set()
    for label, source in _bodies():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "noticings":
                callers.add(label)
    assert callers == {"v2.0 Base consolidator"}, callers
