"""EN11a: the rule-signature token from the configuration, the new scalar keys, and the
narrowed ``Rule.currently_works``."""

from __future__ import annotations

import dataclasses
import os

import pytest

from server.engine import rules
from server.engine.metadata import MetadataProvider
from server.engine.start_check import check_run_start

from tests.support import reduced_configurations as rc

SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

NEW_PARAMETERS = {
    "flip_first_probability_more_spanning": 0.2,
    "flip_first_probability_fewer_spanning": 0.8,
    "flip_first_probability_equal_spanning": 0.5,
    "rough_count_few_threshold": 2,
    "rough_count_some_threshold": 4,
}


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(SEED)


def test_the_token_is_the_old_string_under_the_standard_configuration(meta) -> None:
    assert rules.group_or_string_token(meta) == "plato-group|string"


def test_the_token_follows_the_group_node_when_it_is_renamed(meta) -> None:
    specs = tuple(
        dataclasses.replace(s, node_name="renamed-group") if s.role == "object.group" else s
        for s in meta.node_roles
    )
    renamed = dataclasses.replace(meta, node_roles=specs)
    assert rules.group_or_string_token(renamed) == "renamed-group|string"


def test_the_token_has_a_value_without_the_group_role(meta) -> None:
    bare = dataclasses.replace(
        meta, node_roles=tuple(s for s in meta.node_roles if s.role != "object.group")
    )
    assert rules.group_or_string_token(bare) == "|string"


@pytest.mark.parametrize("name,value", NEW_PARAMETERS.items())
def test_a_new_parameter_carries_the_old_literal_and_its_type(meta, name, value) -> None:
    got = meta.get_param(name)
    assert got == value and type(got) is type(value)


@pytest.mark.parametrize("name", [*NEW_PARAMETERS, "sigmoid_divisor"])
def test_a_missing_name_stops_the_run_at_its_start(meta, name) -> None:
    params = {k: v for k, v in meta.params.items() if k != name}
    coeffs = {k: v for k, v in meta.formula_coefficients.items() if k != name}
    problems = check_run_start(
        dataclasses.replace(meta, params=params, formula_coefficients=coeffs)
    )
    assert any(p.name == name for p in problems)
