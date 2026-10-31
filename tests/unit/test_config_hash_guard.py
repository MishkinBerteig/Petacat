"""The hash guard (plan 3.8): ``config_hash`` covers every provider field by reflection.

A configuration table added to ``MetadataProvider`` is hashed the day it is added, without
anyone remembering to add it to a list.  The only way a field stays out of the hash is the
explicit exclusion set, and this file pins that set, so excluding a field is a decision a
reviewer sees.  The hash is also a digest of per-field digests, so a caller that knows which
fields changed recomputes only those.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from server.engine import hashing
from server.engine.hashing import (
    HASH_EXCLUDED_FIELDS,
    combine,
    config_hash,
    field_digests,
    hashed_field_names,
)
from server.engine.metadata import MetadataProvider

SEED_DIR = Path(__file__).resolve().parents[2] / "seed_data"


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(str(SEED_DIR))


def test_the_exclusion_set_is_exactly_the_decided_one():
    assert HASH_EXCLUDED_FIELDS == {"demo_problems", "slipnet_layout", "enum_values"}


def test_every_provider_field_is_hashed_or_excluded(meta):
    names = {f.name for f in dataclasses.fields(MetadataProvider)}
    hashed = set(field_digests(meta))
    assert hashed | HASH_EXCLUDED_FIELDS == names
    assert not hashed & HASH_EXCLUDED_FIELDS
    assert HASH_EXCLUDED_FIELDS <= names, "an excluded name that is not a provider field"


def test_the_new_tables_are_hashed(meta):
    hashed = set(field_digests(meta))
    assert {"node_roles", "codelet_roles", "theme_relations", "codelet_patterns",
            "commentary_templates"} <= hashed


def test_a_field_added_to_the_provider_is_covered_without_editing_the_hasher(meta):
    @dataclasses.dataclass
    class Extended(MetadataProvider):
        a_new_table: tuple = ()

    base = Extended(**{f.name: getattr(meta, f.name) for f in dataclasses.fields(MetadataProvider)})
    other = dataclasses.replace(base, a_new_table=("one row",))
    assert "a_new_table" in field_digests(base)
    assert config_hash(base) != config_hash(other)


@pytest.mark.parametrize("name", sorted(
    f.name for f in dataclasses.fields(MetadataProvider) if f.name not in HASH_EXCLUDED_FIELDS))
def test_changing_a_hashed_field_changes_its_digest_and_the_hash(meta, name):
    value = getattr(meta, name)
    assert len(value) >= 2, name
    if isinstance(value, dict):
        changed = dict(reversed(list(value.items())))
    else:
        changed = type(value)(reversed(list(value)))
    other = dataclasses.replace(meta, **{name: changed})
    assert field_digests(other)[name] != field_digests(meta)[name]
    assert {k: v for k, v in field_digests(other).items() if k != name} == {
        k: v for k, v in field_digests(meta).items() if k != name}
    assert config_hash(other) != config_hash(meta)


def test_an_excluded_field_does_not_change_the_hash(meta):
    for name in HASH_EXCLUDED_FIELDS:
        value = getattr(meta, name)
        changed = type(value)(reversed(list(value.items()))) if isinstance(value, dict) else value
        other = dataclasses.replace(meta, **{name: changed})
        assert config_hash(other) == config_hash(meta)


def test_the_hash_is_the_combination_of_the_field_digests(meta):
    assert config_hash(meta) == combine(field_digests(meta))
    assert list(field_digests(meta)) == hashed_field_names(meta)


def test_recomputing_only_the_changed_field_gives_the_same_hash(meta):
    params = dict(meta.params)
    key = next(iter(params))
    params[key] = "changed" if not isinstance(params[key], str) else params[key] + "!"
    other = dataclasses.replace(meta, params=params)
    digests = dict(field_digests(meta))
    digests["params"] = field_digests(other)["params"]
    assert combine(digests) == config_hash(other)


def test_number_type_and_order_are_part_of_the_value(meta):
    coefficients = dict(meta.formula_coefficients)
    name = "length_description_max_group_length"
    assert type(coefficients[name]) is int
    as_float = dataclasses.replace(meta, formula_coefficients={**coefficients, name: float(coefficients[name])})
    assert config_hash(as_float) != config_hash(meta)


def test_the_scheme_is_part_of_the_digest(meta, monkeypatch):
    before = config_hash(meta)
    monkeypatch.setattr(hashing, "HASH_SCHEME", 3)
    assert config_hash(meta) != before


def test_the_hash_is_stable_between_two_loads(meta):
    again = MetadataProvider.from_standard_configuration(str(SEED_DIR))
    assert config_hash(again) == config_hash(meta)
