"""``validate_overrides`` checks a run's overrides against the configuration the run executes under.

A reference parameter's shape (a list of names or a map keyed by names) is the configuration's own
``engine_params.refers_to``, so the check needs that configuration: ``meta`` is required, and the
same override is accepted under one configuration and refused under another that declares the
parameter differently (ruling 56).
"""

from __future__ import annotations

import dataclasses

import pytest

from server.engine.parameters import UnknownParameter, validate_overrides
from tests.support.standard_configuration import standard_meta

NAME = "top_down_slipnodes"


def _declared(refers_to: str):
    meta = standard_meta()
    return dataclasses.replace(meta, param_refers_to={**meta.param_refers_to, NAME: refers_to})


def test_meta_is_required() -> None:
    with pytest.raises(TypeError):
        validate_overrides({})  # type: ignore[call-arg]
    assert validate_overrides({}, standard_meta()) == {}
    assert validate_overrides(None, standard_meta()) == {}


def test_a_reference_parameter_is_checked_against_the_configuration_given() -> None:
    as_list, as_map = ["plato-opposite"], {"plato-opposite": 3}
    standard = standard_meta()
    assert standard.param_refers_to[NAME] == "trigger_node_list"
    assert validate_overrides({NAME: as_list}, standard) == {NAME: as_list}
    with pytest.raises(ValueError, match="list of names"):
        validate_overrides({NAME: as_map}, standard)
    # the same two overrides under a configuration that declares the parameter a map
    mapped = _declared("node_map")
    assert validate_overrides({NAME: as_map}, mapped) == {NAME: as_map}
    with pytest.raises(ValueError, match="map of names to numbers"):
        validate_overrides({NAME: as_list}, mapped)


def test_an_unknown_parameter_is_refused_whatever_the_configuration() -> None:
    with pytest.raises(UnknownParameter):
        validate_overrides({"no_such_parameter": 1}, standard_meta())
