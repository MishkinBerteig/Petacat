"""EN10b: the rules, language and perception files read their scalars from the configuration.

* the keys EN10b added carry the Metacat Standard Configuration's old literals, with their types;
* every name those files read is on the declared read list, so a configuration lacking one stops
  the run at its start;
* the coefficients that were wired are actually read (changing one changes the result).
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from server.engine.bonds import Bond
from server.engine.metadata import MetadataProvider
from server.engine.start_check import check_run_start
from server.engine.workspace_structures import WorkspaceStructure

SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

NEW_PARAMETERS = {
    "rule_swap_abstraction_probability": 0.75,
    "rule_subobjects_abstraction_probability": 0.75,
    "justify_retention_identity_percent": 50,
    "bridge_recruit_urgency_level": "very_high",
}
NEW_COEFFICIENTS = {
    "description_local_support_1": 20.0,
    "description_local_support_2": 60.0,
    "description_local_support_3": 90.0,
    "description_local_support_4_plus": 100.0,
    "concept_mapping_unlinked_association": 5.0,
    "bridge_theme_compatibility_sigmoid_beta": 4.0,
}


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(SEED)


@pytest.mark.parametrize("name,value", NEW_PARAMETERS.items())
def test_a_new_parameter_carries_the_old_literal_and_its_type(meta, name, value):
    got = meta.get_param(name)
    assert got == value and type(got) is type(value)


@pytest.mark.parametrize("name,value", NEW_COEFFICIENTS.items())
def test_a_new_coefficient_carries_the_old_literal_and_its_type(meta, name, value):
    got = meta.get_formula_coeff(name)
    assert got == value and type(got) is type(value)


@pytest.mark.parametrize("name", NEW_PARAMETERS)
def test_a_missing_new_parameter_stops_the_run_at_its_start(meta, name):
    params = {k: v for k, v in meta.params.items() if k != name}
    problems = check_run_start(dataclasses.replace(meta, params=params))
    assert any(p.name == name for p in problems)


@pytest.mark.parametrize("name", NEW_COEFFICIENTS)
def test_a_missing_new_coefficient_stops_the_run_at_its_start(meta, name):
    coefficients = {k: v for k, v in meta.formula_coefficients.items() if k != name}
    problems = check_run_start(dataclasses.replace(meta, formula_coefficients=coefficients))
    assert any(p.name == name for p in problems)


def test_a_bridge_recruit_level_the_configuration_lacks_stops_the_run_at_its_start(meta):
    params = {**meta.params, "bridge_recruit_urgency_level": "no_such_level"}
    problems = check_run_start(dataclasses.replace(meta, params=params))
    assert any(p.name == "no_such_level" for p in problems)


def test_the_weakness_exponent_is_read_from_the_bound_configuration(meta):
    class _S(WorkspaceStructure):
        pass

    s = _S()
    s.strength = 50.0
    assert s.weakness() == 100.0 - 50.0**0.95
    WorkspaceStructure.bind_meta(
        dataclasses.replace(
            meta, formula_coefficients={**meta.formula_coefficients, "weakness_exponent": 1.0}
        )
    )
    assert s.weakness() == 50.0


def test_a_structure_with_no_bound_configuration_names_what_needed_it():
    from server.engine.metadata import ConfigurationRequired

    WorkspaceStructure.bind_meta(None)

    class _S(WorkspaceStructure):
        pass

    with pytest.raises(ConfigurationRequired):
        _S().weakness()


def test_bond_internal_strength_reads_its_factors(meta):
    from tests.unit.test_bonds import _Obj, _bond, _letter_category, _sameness

    bond = _bond(_Obj(0, 0), _Obj(1, 1), _sameness(), _letter_category())
    base = bond.calculate_internal_strength()
    doubled = {**meta.formula_coefficients, "bond_compatibility_factor_same_type": 0.5}
    WorkspaceStructure.bind_meta(dataclasses.replace(meta, formula_coefficients=doubled))
    assert isinstance(bond, Bond)
    assert bond.calculate_internal_strength() < base
