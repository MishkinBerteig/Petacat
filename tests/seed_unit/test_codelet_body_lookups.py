"""Codelet bodies and descriptor predicates refer to concepts through roles, relations and
glyphs, never by a node name (v2.0 package CB).

The lint reads the Metacat Standard Configuration's code with the AST, so a comment quoting
Scheme (``(stochastic-pick (list plato-right plato-left) ...)``) is ignored.  The unit tests
cover the builtins ``role``, ``relation``, ``letter_node`` and ``descriptor_support`` and the
predicate helper ``letter_glyph``, present and absent.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.engine.codelet_dsl import builtins as B
from server.engine.metadata import MetadataProvider
from server.engine.roles import ROLES, Absent
from server.engine.slipnet import DESCRIPTOR_PREDICATE_NAMESPACE, Slipnet
from tests.support import reduced_configurations as rc

SEED_DIR = Path(__file__).resolve().parents[2] / "seed_data"


def _load(name: str):
    return json.loads((SEED_DIR / name).read_text())


# ---------------------------------------------------------------------------
# The lint
# ---------------------------------------------------------------------------


def _code():
    """(label, source, mode) of every codelet body and descriptor predicate."""
    for row in _load("codelet_types.json"):
        if row.get("execute_body"):
            yield f"codelet body {row['name']}", row["execute_body"], "exec"
    for node in _load("slipnet_nodes.json"):
        if node.get("descriptor_predicate"):
            yield f"descriptor predicate {node['name']}", node["descriptor_predicate"], "eval"


def test_no_body_or_predicate_names_a_node_or_builds_one():
    nodes = {n["name"] for n in _load("slipnet_nodes.json")}
    # What a node name is built from: the shared prefix of the names (``plato-``).
    prefixes = {n.split("-")[0] + "-" for n in nodes if "-" in n}
    found = []
    for label, source, mode in _code():
        for const in ast.walk(ast.parse(source, mode=mode)):
            if isinstance(const, ast.Constant) and isinstance(const.value, str):
                value = const.value
                if value in nodes or any(value.startswith(p) for p in prefixes):
                    found.append(f"{label}: {value!r} (line {const.lineno})")
    assert not found, "code names a node: " + "; ".join(found)


def test_the_lint_sees_a_node_name_in_code():
    # The lint is not vacuous: the same walk flags a body that names a node.
    tree = ast.parse("x = get_node('plato-left')")
    assert any(isinstance(n, ast.Constant) and n.value == "plato-left" for n in ast.walk(tree))


# ---------------------------------------------------------------------------
# The builtins
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(str(SEED_DIR))


@pytest.fixture(scope="module")
def ctx(meta):
    return SimpleNamespace(slipnet=Slipnet.from_metadata(meta))


def test_role_gives_the_bound_node(ctx):
    assert B.role(ctx, "direction.left") is ctx.slipnet.roles.direction_left
    assert B.role(ctx, "direction.left") is ctx.slipnet.nodes["plato-left"]


def test_role_gives_the_ordered_tuple(ctx):
    got = B.role(ctx, "rule.dimension_order")
    assert isinstance(got, tuple) and got == ctx.slipnet.roles.rule_dimension_order and len(got) == 8


def test_role_gives_a_codelet_type_spec(ctx):
    assert B.role(ctx, "evaluator.bond") is ctx.slipnet.roles.evaluator_bond


def test_every_role_of_the_vocabulary_resolves(ctx):
    for spec in ROLES:
        assert B.role(ctx, spec.name) is getattr(ctx.slipnet.roles, spec.attr)


def test_role_outside_the_vocabulary_raises_naming_it(ctx):
    with pytest.raises(ValueError, match="direction.sideways"):
        B.role(ctx, "direction.sideways")


def test_relation_gives_the_node_or_the_absent_token(ctx):
    assert B.relation(ctx, "identity") is ctx.slipnet.nodes["plato-identity"]
    missing = B.relation(ctx, "no-such-relation")
    assert isinstance(missing, Absent) and not missing


def test_letter_node_gives_the_node_with_that_glyph(ctx):
    assert B.letter_node(ctx, "a") is ctx.slipnet.nodes["plato-a"]
    assert B.letter_node(ctx, "z") is ctx.slipnet.nodes["plato-z"]


@pytest.mark.parametrize("ch", ["A", "Z", "1", " ", ""])
def test_letter_node_of_a_symbol_with_no_node_is_a_falsy_absent_token(ctx, ch):
    got = B.letter_node(ctx, ch)
    assert isinstance(got, Absent) and not got
    assert B.letter_node(ctx, ch) is got


def _slipnet_without(node: str) -> SimpleNamespace:
    return SimpleNamespace(slipnet=Slipnet.from_metadata(rc.provider(rc.node_removed(node))))


def test_a_configuration_lacking_a_letter_gives_an_absent_token():
    c = _slipnet_without("plato-a")
    assert not B.letter_node(c, "a")
    assert B.letter_node(c, "b")


def test_a_configuration_lacking_a_role_node_gives_the_roles_absent_token():
    c = _slipnet_without("plato-left")
    assert not B.role(c, "direction.left")
    assert B.role(c, "direction.right")


def test_a_configuration_lacking_a_relation_gives_an_absent_token():
    c = _slipnet_without("plato-identity")
    assert not B.relation(c, "identity")
    assert B.relation(c, "opposite")


def _group(*descriptors):
    ds = [SimpleNamespace(descriptor=d) for d in descriptors]
    return SimpleNamespace(is_built=True, get_all_descriptions=lambda: ds)


def test_descriptor_support_compares_by_identity(ctx):
    left, right = B.role(ctx, "direction.left"), B.role(ctx, "direction.right")
    string = SimpleNamespace(groups=[_group(left), _group(left), _group(right), _group()])
    assert B.descriptor_support(ctx, string, left) == 50.0
    assert B.descriptor_support(ctx, string, right) == 25.0
    # a node with the same name that is not the node does not count
    twin = SimpleNamespace(name=left.name)
    assert B.descriptor_support(ctx, string, twin) == 0.0


def test_descriptor_support_of_an_absent_token_is_zero(ctx):
    from server.engine.roles import absent

    string = SimpleNamespace(groups=[_group(B.role(ctx, "direction.left"))])
    assert B.descriptor_support(ctx, string, absent("direction.left")) == 0.0
    assert B.descriptor_support(ctx, SimpleNamespace(groups=[]), absent("direction.left")) == 0.0


def test_letter_glyph_predicate_helper():
    glyph = DESCRIPTOR_PREDICATE_NAMESPACE["letter_glyph"]
    assert "letter_category_name" not in DESCRIPTOR_PREDICATE_NAMESPACE
    letter = SimpleNamespace(descriptions=[], letter_category=SimpleNamespace(glyph="a", name="x"))
    assert glyph(letter) == "a"
    assert glyph(SimpleNamespace(descriptions=[], letter_category=None)) == ""
    assert glyph(SimpleNamespace(descriptions=[], letter_category=SimpleNamespace(glyph=None))) == ""
