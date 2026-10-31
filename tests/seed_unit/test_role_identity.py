"""Role identity (gate G5), the skeleton laid down by work package EN0.

The role mechanism of the configuration-source plan (3.2) replaces the engine's node-name
literals with roles resolved once at Slipnet build.  G5 is the check that makes the
replacement safe: for every role, *the node found through ``slipnet.roles`` is the node
found by the old literal* (``is``, not ``==``), and the ordered lists
(``rule.dimension_order``, ``answer.description_dimension``, the number ladder, the
alphabet) equal the old tuples, element for element.

This module has two halves:

* **Today's side.**  The role-to-literal table (``tests/support/role_table.py``)
  is checked against the Metacat Standard Configuration (every literal names a node or
  codelet type that exists; the roles, the relations, the numbers and the letters
  account for all 59 nodes), against the engine's own constants (the ordered lists), and
  against ``role_identity_today.json``, recorded from today's code, which is what the
  later comparison reads.
* **The comparison, running since EN3.**  Each role, ordered list and codelet role is a
  test that resolves through ``slipnet.roles`` (``server/engine/roles.py``) and asserts
  identity with today's literal.  The one place that reads a role off ``slipnet.roles`` is
  ``_resolve``.

Regenerate the recording after an approved change with
``.venv/bin/python tests/seed_unit/test_role_identity.py --write``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.support.role_table import (
    CODELET_ROLES, LETTER_NODES, NUMBER_NODES, ORDERED_ROLES, RELATION_NODES, SINGLE_ROLES,
    role_attr,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = REPO_ROOT / "seed_data"
RECORDING = Path(__file__).with_name("role_identity_today.json")


def _meta():
    from server.engine.metadata import MetadataProvider

    return MetadataProvider.from_standard_configuration(str(SEED_DIR))


def todays_lists() -> dict[str, list[str]]:
    """The ordered lists as today's engine code holds them."""
    from server.engine.answers import _ANSWER_DESCRIPTION_THEME_TYPES
    from server.engine.images import _LETTER_NAMES, _NUMBER_NAMES
    from server.engine.rules import _RULE_DIMENSION_ORDER_NAMES

    return {
        "rule.dimension_order": list(_RULE_DIMENSION_ORDER_NAMES),
        "answer.description_dimension": list(_ANSWER_DESCRIPTION_THEME_TYPES),
        "ladder": list(_NUMBER_NAMES),
        "alphabet": list(_LETTER_NAMES),
    }


def record_today() -> dict:
    """What is recorded from today's code: the role table, the ordered lists, and the
    Slipnet's node order (which is behaviour: it fixes iteration and so RNG order)."""
    from server.engine.slipnet import Slipnet

    slipnet = Slipnet.from_metadata(_meta())
    return {
        "note": "recorded from the engine before EN3; compared by tests/seed_unit/test_role_identity.py",
        "single_roles": SINGLE_ROLES,
        "ordered_roles": {k: list(v) for k, v in ORDERED_ROLES.items()},
        "codelet_roles": CODELET_ROLES,
        "ordered_lists_in_engine_code": todays_lists(),
        "slipnet_node_order": list(slipnet.nodes),
    }


@pytest.fixture(scope="module")
def meta():
    return _meta()


@pytest.fixture(scope="module")
def slipnet(meta):
    from server.engine.slipnet import Slipnet

    return Slipnet.from_metadata(meta)


# ---------------------------------------------------------------------------
# Today's side
# ---------------------------------------------------------------------------


def test_the_table_has_the_planned_shape() -> None:
    assert len(SINGLE_ROLES) == 24
    assert {k: len(v) for k, v in ORDERED_ROLES.items()} == {
        "rule.dimension_order": 8, "answer.description_dimension": 5}
    assert len(CODELET_ROLES) == 5
    assert len(set(SINGLE_ROLES.values())) == len(SINGLE_ROLES)  # one role, one node here


@pytest.mark.parametrize("role", sorted(SINGLE_ROLES))
def test_todays_literal_of_a_role_finds_a_node(slipnet, role) -> None:
    node = slipnet.nodes[SINGLE_ROLES[role]]
    assert node.name == SINGLE_ROLES[role]
    assert node, "a node must be truthy: roles replace `is not None` by truthiness (plan 4.2)"


def test_every_node_of_the_standard_configuration_is_truthy(slipnet) -> None:
    assert all(bool(n) for n in slipnet.nodes.values())


@pytest.mark.parametrize("role", sorted(CODELET_ROLES))
def test_todays_literal_of_a_codelet_role_is_a_codelet_type(meta, role) -> None:
    assert CODELET_ROLES[role] in meta.codelet_specs


def test_roles_relations_numbers_and_letters_account_for_all_59_nodes(slipnet) -> None:
    named = set(SINGLE_ROLES.values())
    for names in ORDERED_ROLES.values():
        named |= set(names)
    accounted = named | set(RELATION_NODES) | set(NUMBER_NODES) | set(LETTER_NODES)
    assert accounted == set(slipnet.nodes)
    assert len(slipnet.nodes) == 59


def test_ordered_roles_equal_the_engines_own_lists() -> None:
    today = todays_lists()
    assert list(ORDERED_ROLES["rule.dimension_order"]) == today["rule.dimension_order"]
    assert list(ORDERED_ROLES["answer.description_dimension"]) == today["answer.description_dimension"]
    assert list(NUMBER_NODES) == today["ladder"]
    assert list(LETTER_NODES) == today["alphabet"]
    assert len(today["alphabet"]) == 26


def test_the_recording_matches_todays_code() -> None:
    """The committed recording is what today's code says (EN3 compares against it)."""
    assert json.loads(RECORDING.read_text()) == json.loads(json.dumps(record_today()))


# ---------------------------------------------------------------------------
# The comparison (EN3)
# ---------------------------------------------------------------------------


def _roles(slipnet):
    return slipnet.roles


def _resolve(roles, role: str):
    """The one place that reads a role off ``slipnet.roles`` (EN3 may adjust it)."""
    return getattr(roles, role_attr(role))


@pytest.mark.parametrize("role", sorted(SINGLE_ROLES))
def test_role_resolves_to_the_node_the_literal_finds(slipnet, role) -> None:
    node = _resolve(_roles(slipnet), role)
    assert node is slipnet.nodes[SINGLE_ROLES[role]]


@pytest.mark.parametrize("role", sorted(ORDERED_ROLES))
def test_ordered_role_equals_the_old_tuple(slipnet, role) -> None:
    resolved = _resolve(_roles(slipnet), role)
    assert len(resolved) == len(ORDERED_ROLES[role])
    assert all(a is slipnet.nodes[name] for a, name in zip(resolved, ORDERED_ROLES[role]))


def test_ladder_and_alphabet_equal_the_old_lists(slipnet, meta) -> None:
    """The ladder and the alphabet are data, not roles (plan 3.2, 3.13): the nodes that have a
    ``numeric_value`` ordered by it, the nodes that have a ``glyph`` ordered by it.  EN5b gives
    them records on the Slipnet; until then the provider's node columns say the same thing."""
    specs = meta.slipnet_node_specs.values()
    letters = [s.name for s in sorted((s for s in specs if s.glyph), key=lambda s: s.glyph)]
    numbers = [s.name for s in sorted((s for s in specs if s.numeric_value is not None),
                                      key=lambda s: s.numeric_value)]
    assert letters == list(LETTER_NODES)
    assert numbers == list(NUMBER_NODES)
    assert all(slipnet.nodes[n] for n in letters + numbers)


@pytest.mark.parametrize("role", sorted(CODELET_ROLES))
def test_codelet_role_resolves_to_the_literal_type(slipnet, meta, role) -> None:
    roles = _roles(slipnet)
    resolved = _resolve(roles, role)
    assert getattr(resolved, "name", resolved) == CODELET_ROLES[role]


def test_node_roles_are_a_frozenset_on_each_node(slipnet) -> None:
    _roles(slipnet)
    for role, literal in SINGLE_ROLES.items():
        assert role in slipnet.nodes[literal].roles


if __name__ == "__main__":
    if "--write" in sys.argv:
        RECORDING.write_text(json.dumps(record_today(), indent=1, sort_keys=False) + "\n")
        print(f"wrote {RECORDING}")
