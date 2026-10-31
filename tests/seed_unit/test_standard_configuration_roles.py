"""EN2: the Metacat Standard Configuration carries the role bindings and the data the node
columns hold, and the provider loads them.

Nothing in the engine reads any of this yet (EN3 adds the role mechanism).  These tests pin
the data against ``tests/support/role_table.py``, the record of what today's code names, so
that when a consumer starts reading the data it reads what the literals said.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.engine.metadata import MetadataProvider
from tests.support.role_table import (
    CODELET_ROLES, LETTER_NODES, NUMBER_NODES, ORDERED_ROLES, RELATION_NODES, SINGLE_ROLES,
)

SEED_DIR = Path(__file__).resolve().parents[2] / "seed_data"


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(str(SEED_DIR))


def _bound(meta, role):
    return [b.node_name for b in sorted(meta.node_roles, key=lambda b: b.ordinal) if b.role == role]


@pytest.mark.parametrize("role", sorted(SINGLE_ROLES))
def test_a_single_role_is_bound_to_the_node_the_literal_names(meta, role):
    assert _bound(meta, role) == [SINGLE_ROLES[role]]
    assert [b.ordinal for b in meta.node_roles if b.role == role] == [0]


@pytest.mark.parametrize("role", sorted(ORDERED_ROLES))
def test_an_ordered_role_is_in_todays_order(meta, role):
    assert _bound(meta, role) == list(ORDERED_ROLES[role])
    assert [b.ordinal for b in meta.node_roles if b.role == role] == list(range(len(ORDERED_ROLES[role])))


@pytest.mark.parametrize("role", sorted(CODELET_ROLES))
def test_a_codelet_role_is_bound_to_the_codelet_type_the_literal_names(meta, role):
    assert [b.codelet_type for b in meta.codelet_roles if b.role == role] == [CODELET_ROLES[role]]


def test_there_are_no_other_bindings(meta):
    assert {b.role for b in meta.node_roles} == set(SINGLE_ROLES) | set(ORDERED_ROLES)
    assert {b.role for b in meta.codelet_roles} == set(CODELET_ROLES)
    assert len(meta.node_roles) == len(SINGLE_ROLES) + sum(len(v) for v in ORDERED_ROLES.values())


def test_every_binding_names_something_that_exists(meta):
    assert all(b.node_name in meta.slipnet_node_specs for b in meta.node_roles)
    assert all(b.codelet_type in meta.codelet_specs for b in meta.codelet_roles)


def test_bindings_are_ordered_by_role_bytes_then_ordinal(meta):
    keys = [(b.role.encode(), b.ordinal) for b in meta.node_roles]
    assert keys == sorted(keys)
    keys = [(b.role.encode(), b.ordinal) for b in meta.codelet_roles]
    assert keys == sorted(keys)


def test_theme_relations_are_the_four_nodes_and_diff(meta):
    by = {r.name: r for r in meta.theme_relations}
    assert [r.name for r in meta.theme_relations] == ["identity", "opposite", "successor", "predecessor", "diff"]
    assert [r.ordinal for r in meta.theme_relations] == [0, 1, 2, 3, 4]
    assert [by[n].node_name for n in ("identity", "opposite", "successor", "predecessor")] == list(RELATION_NODES)
    assert by["diff"].node_name is None
    assert (by["identity"].abstractness, by["diff"].abstractness) == (0, 50)
    assert all(by[n].abstractness is None for n in ("opposite", "successor", "predecessor"))


def test_plain_name_is_the_name_less_the_prefix(meta):
    for name, spec in meta.slipnet_node_specs.items():
        assert spec.plain_name == name[6:], name


def test_letters_carry_their_glyph(meta):
    glyphs = {n: s.glyph for n, s in meta.slipnet_node_specs.items() if s.glyph is not None}
    assert list(glyphs) == [n for n in meta.slipnet_node_specs if n in LETTER_NODES]
    assert glyphs == {n: n[6:] for n in LETTER_NODES}
    assert len(set(glyphs.values())) == 26


def test_numbers_carry_their_value(meta):
    values = {n: s.numeric_value for n, s in meta.slipnet_node_specs.items() if s.numeric_value is not None}
    assert values == {n: i + 1 for i, n in enumerate(NUMBER_NODES)}


def test_display_columns_reproduce_the_tables_they_replace(meta):
    from server.engine.rule_english import _AN_LETTERS
    from server.engine.trace_display import _FULL_SLIPNODE_NAMES

    specs = meta.slipnet_node_specs
    assert {n: s.full_name for n, s in specs.items() if s.full_name} == _FULL_SLIPNODE_NAMES
    assert {n: s.cm_short_name for n, s in specs.items() if s.cm_short_name} == {
        "plato-letter-category": "LettCtgy"}
    assert {s.glyph for s in specs.values() if s.article_an} == set(_AN_LETTERS)
    assert {n for n, s in specs.items() if s.article_an is not None} == set(LETTER_NODES)


def test_posting_rules_have_unique_keys_in_file_order(meta):
    keys = [r.rule_key for r in meta.posting_rules]
    assert len(set(keys)) == len(keys) == 17
    assert keys == [r.codelet_type for r in meta.posting_rules]


def test_the_link_key_is_unique_in_the_standard_configuration(meta):
    keys = [(l.from_node, l.to_node, l.link_type, l.label_node or "") for l in meta.slipnet_link_specs]
    assert len(set(keys)) == len(keys) == 202


def test_the_files_the_loader_reads_are_all_in_the_bulk_list():
    from server.services.seeding import BULK_SEED_FILES

    assert {"roles.json", "theme_relations.json"} <= set(BULK_SEED_FILES)
    for name in BULK_SEED_FILES:
        json.loads((SEED_DIR / name).read_text())
