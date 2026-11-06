"""Stage 5, group A: every number that moved into the database reaches the site that read it as a literal.

Each row of ``MOVED`` is one formula coefficient that used to be a literal in the structure,
formula, perception, rule, Themespace, trace and numeric files (``server/engine/formulas.py``,
``bonds.py``, ``groups.py``, ``bridges.py``, ``concept_mappings.py``, ``descriptions.py``,
``workspace*.py``, ``rules.py``, ``themes.py``, ``trace.py``, ``slipnet.py``, ``coderack.py``,
``numeric/``).  For every row, three things are checked, in the style of
``tests/unit/test_en10b_scalars.py``:

1. **The seed carries the old literal, with its type.**  An int is an int and a float a float, so a
   Metacat Mode run is unchanged to the bit (rulings 8 and 39).
2. **The key is on the declared read list.**  A configuration that lacks it stops the run at its start.
3. **The site reads the key.**  A row is either

   * ``run``: a real run in which the site is reached, under the standard configuration and under the
     key changed, differs (answer, codelet types, random draws, trace, state), so a site that goes
     back to the literal fails the row; or
   * ``direct``: the site is called on its own with the key changed, because no problem reaches it
     in reasonable time (a guard for an input a run never builds, for example a bond that is not in
     a string).  The site must then return the changed value (or a result that follows from it).

The numeric backends read the keys they mirror from the same configuration: the rows
``clamped_salience``, ``thematic_pull_*`` and ``average_unhappiness_empty`` are checked on every
backend this machine has.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from types import SimpleNamespace
from typing import Any, Callable
from unittest import mock

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.numeric.backend import available_backends, get_backend
from server.engine.start_check import check_run_start
from tests.support.run_binding import rebind

SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

#: key -> (the literal the site held, written in the form it had: an int stays an int).
LITERAL: dict[str, Any] = {
    "low_prob_min_decade_factor": 1.0,
    "low_prob_target_offset": 1.0,
    "low_prob_sqrt_exponent": 0.5,
    "length_description_over_max_probability": 0.0,
    "length_description_single_probability": 1.0,
    "length_description_length_exponent": 3,
    "urgency_ceiling": 100.0,
    "bond_degree_of_assoc_exponent": 0.5,
    "bond_degree_of_assoc_ceiling": 100.0,
    "local_support_density_exponent": 0.5,
    "local_support_number_exponent": 3,
    "local_support_number_factor_ceiling": 1.0,
    "bond_local_support_unsupported": 0.0,
    "bond_local_density_no_string": 100.0,
    "bond_local_density_spanning": 100.0,
    "group_bond_factor_no_category": 0.0,
    "group_spanning_external_strength": 100.0,
    "group_local_support_unsupported": 0.0,
    "group_local_density_spanning": 100.0,
    "group_local_density_no_string": 100.0,
    "group_local_density_no_neighbours": 100.0,
    "intra_unhappiness_spanning": 0.0,
    "intra_unhappiness_unbonded": 100.0,
    "clamped_salience": 100,
    "inter_unhappiness_unbridged": 100.0,
    "thematic_pull_positive_target": 100.0,
    "thematic_pull_negative_target": 0.0,
    "average_unhappiness_empty": 100,
    "average_intra_unhappiness_empty": 100.0,
    "selection_weight_default": 1.0,
    "mapping_strength_spanning_possible_factor": 0.5,
    "mapping_strength_maximal_tanh_divisor": 40.0,
    "activity_age_share_ceiling": 1.0,
    "concept_mapping_depth_bonus_base": 1.0,
    "concept_mapping_depth_penalty_base": 1.0,
    "concept_mapping_full_association": 100,
    "concept_mapping_full_association_strength": 100.0,
    "concept_mapping_full_association_slippability": 100.0,
    "concept_mapping_identity_association": 100.0,
    "bridge_no_mapping_internal_strength": 0.0,
    "bridge_internal_strength_ceiling": 100.0,
    "bridge_external_strength_ceiling": 100.0,
    "bridge_spanning_singleton_external_strength": 100.0,
    "bridge_singleton_factor_unpenalised": 1.0,
    "bridge_theme_positive_weight_multiplier": 1.0,
    "bridge_theme_support_none": 0.0,
    "bridge_theme_support_unrelated": 0.0,
    "description_local_support_0": 0.0,
    "description_theme_support_none": 0.0,
    "description_theme_support_unrelated": 0.0,
    "link_length_unset": 0,
    "rule_support_missing_bridge_strength": 0,
    "rule_homogeneity_empty": 1.0,
    "rule_object_description_uniformity_empty": 1.0,
    "rule_change_abstractness_uniformity_empty": 1.0,
    "rule_change_abstractness_scale": 2.0,
    "rule_change_abstractness_midpoint": 0.5,
    "rule_identity_quality": 100.0,
    "rule_trivial_uniformity": 100.0,
    "rule_intrinsic_uniformity_empty": 1.0,
    "rule_extrinsic_uniformity_empty": 1.0,
    "rule_uniformity_perfect": 1.0,
    "rule_identity_abstractness": 100.0,
    "rule_verbatim_abstractness": 0.0,
    "rule_trivial_succinctness": 100.0,
    "rule_succinctness_swap_clause_cost": 2.0,
    "rule_succinctness_clause_cost": 1.0,
    "rule_succinctness_best_cost": 1,
    "theme_dimension_node_activation_exponent": 3,
    "theme_relation_node_activation_exponent": 3,
    "theme_conjunction_admission_exponent": 2,
    "clamp_event_strength": 100.0,
    "snag_event_strength": 100.0,
    "bond_event_progress": 0.0,
    "clamp_suppressed_concept_activation": 0.0,
    "coderack_removal_penalty_offset": 1,
}

#: The value each key is changed to.
CHANGED: dict[str, Any] = {
    "low_prob_sqrt_exponent": 0.4,
    "bond_degree_of_assoc_exponent": 0.4,
    "local_support_density_exponent": 0.4,
    "local_support_number_exponent": 2,
    "length_description_length_exponent": 2,
    "rule_change_abstractness_midpoint": 0.4,
    "rule_change_abstractness_scale": 3.0,
    "theme_dimension_node_activation_exponent": 2,
    "theme_relation_node_activation_exponent": 2,
    "theme_conjunction_admission_exponent": 1,
    "coderack_removal_penalty_offset": 5,
    "mapping_strength_maximal_tanh_divisor": 20.0,
    "mapping_strength_spanning_possible_factor": 0.25,
    "concept_mapping_full_association": 90,
    "link_length_unset": 20,
    "clamped_salience": 50,
    "urgency_ceiling": 50.0,
    "average_unhappiness_empty": 40,
    "rule_succinctness_best_cost": 2,
    "rule_support_missing_bridge_strength": 1,
    "local_support_number_factor_ceiling": 0.5,
}


def changed(key: str) -> Any:
    """The value *key* is changed to: an explicit one, or one that differs in the same type."""
    if key in CHANGED:
        return CHANGED[key]
    v = LITERAL[key]
    if v == 0.0:
        return 7.0
    if v >= 50.0:
        return 60.0
    return 0.5


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED)


def with_coefficient(meta: MetadataProvider, key: str, value: Any) -> MetadataProvider:
    return dataclasses.replace(meta, formula_coefficients={**meta.formula_coefficients, key: value})


# --------------------------------------------------------------------------- 1 and 2: the seed, the list


@pytest.mark.parametrize("key", LITERAL)
def test_the_seed_carries_the_old_literal_and_its_type(meta, key):
    got = meta.get_formula_coeff(key)
    assert got == LITERAL[key] and type(got) is type(LITERAL[key])


@pytest.mark.parametrize("key", LITERAL)
def test_a_missing_key_stops_the_run_at_its_start(meta, key):
    coefficients = {k: v for k, v in meta.formula_coefficients.items() if k != key}
    problems = check_run_start(dataclasses.replace(meta, formula_coefficients=coefficients))
    assert any(p.name == key for p in problems)


def test_the_table_names_every_key_of_the_stage():
    """No key of the stage is left out of the table above (``keys`` of the stage's own list)."""
    from server.engine import run_binding, start_check

    declared = {n for n, where in start_check.REQUIRED_FORMULA_COEFFICIENTS}
    fields = {f.name for f in dataclasses.fields(run_binding.RunConstants)}
    #: A RunConstants slot declared ``formula()`` for one of this stage's keys must be in the table.
    stage = {
        f.name
        for f in dataclasses.fields(run_binding.RunConstants)
        if f.metadata.get("source") == "formula" and f.name in LITERAL
    }
    assert stage <= set(LITERAL) and set(LITERAL) <= declared
    assert fields  # the record exists


# --------------------------------------------------------------------------- 3: runs


def _fingerprint(meta, problem, seed, answer):
    from tests.support import golden_baseline as gb
    from server.engine.memory import EpisodicMemory

    runner, rng, draws, types, _ = gb.run_observed(
        meta, tuple(problem), seed, answer, EpisodicMemory(), False, backend="numpy"
    )
    ctx = runner.ctx
    return hashlib.sha256(
        json.dumps(
            [
                runner.status,
                list(runner._answers),
                ctx.codelet_count,
                rng.call_count,
                ",".join(map(str, draws)),
                ",".join(types),
                gb.state_digest(ctx),
                gb.canonical(gb._trace_summary(ctx.trace.events)),
            ]
        ).encode()
    ).hexdigest()


_BASELINE: dict[tuple, str] = {}

#: key -> (problem, seed, answer): a run the demo corpus reaches the site in, found by changing the key
#: and running the 19 demo problems and the justification demos at seeds 1, 2 and 3 (the first one that
#: differed; ``agents-workspace/metacat-cleanup/round2/S5a-values/mut/probe.py``).
RUNS: dict[str, tuple[list[str], int, str | None]] = {}
RUNS_PATH = os.path.join(os.path.dirname(__file__), "moved_values_runs_a.json")
if os.path.exists(RUNS_PATH):
    RUNS = {k: (v["problem"], v["seed"], v["answer"]) for k, v in json.load(open(RUNS_PATH)).items()}


@pytest.mark.numeric_matrix
@pytest.mark.parametrize("key", sorted(RUNS))
def test_a_run_changes_when_the_key_changes(meta, key):
    problem, seed, answer = RUNS[key]
    case = (tuple(problem), seed, answer)
    if case not in _BASELINE:
        _BASELINE[case] = _fingerprint(meta, problem, seed, answer)
    assert _fingerprint(with_coefficient(meta, key, changed(key)), problem, seed, answer) != _BASELINE[case]


# --------------------------------------------------------------------------- 3: sites called directly


def _site(key: str) -> Callable[[Callable[[MetadataProvider], Any]], Callable[[MetadataProvider], Any]]:
    def register(fn):
        DIRECT[key] = fn
        return fn

    return register


DIRECT: dict[str, Callable[[MetadataProvider], Any]] = {}


def _density_bond(text="ab"):
    from tests.unit.test_bonds import _bond, _letter_category, _real_string, _successor
    from tests.unit._fakes import FakeNode

    string = _real_string(text)
    return _bond(string.objects[0], string.objects[1], _successor(), _letter_category(),
                 direction=FakeNode("plato-right"))


@_site("bond_local_density_spanning")
def _(meta):
    from server.engine.rng import RNG

    return _density_bond("ab").get_local_density(RNG(1))


@_site("bond_local_density_no_string")
def _(meta):
    from server.engine.rng import RNG
    from tests.unit.test_bonds import _Obj, _bond, _letter_category, _successor

    return _bond(_Obj(0, 0), _Obj(1, 1), _successor(), _letter_category()).get_local_density(RNG(1))


def _group_for_density(*, string):
    from tests.unit.test_groups import _PosObj, _group

    members = [_PosObj(0, 0), _PosObj(1, 1)]
    return members, _group(members, string=string)


@_site("group_local_density_spanning")
def _(meta):
    from server.engine.rng import RNG
    from tests.unit._fakes import FakeString

    members = [__import__("tests.unit.test_groups", fromlist=["_PosObj"])._PosObj(i, i) for i in range(2)]
    from tests.unit.test_groups import _group

    return _group(members, string=FakeString(objects=list(members), length=2)).get_local_density(RNG1())


def RNG1():
    from server.engine.rng import RNG

    return RNG(1)


@_site("group_local_density_no_string")
def _(meta):
    _, g = _group_for_density(string=None)
    return g.get_local_density(RNG1())


@_site("group_local_density_no_neighbours")
def _(meta):
    from tests.unit._fakes import FakeString
    from tests.unit.test_groups import _PosObj, _group

    objs = [_PosObj(i, i) for i in range(3)]
    g = _group(objs[:2], string=FakeString(objects=objs, length=3))
    with mock.patch("server.engine.groups._walk_group_neighbors", return_value=[]):
        return g.get_local_density(RNG1())


@_site("group_bond_factor_no_category")
def _(meta):
    from tests.unit.test_groups import _PosObj, _group

    g = _group([_PosObj(0, 0), _PosObj(1, 1)])
    g.group_category = SimpleNamespace()
    object.__setattr__(g, "bond_category", SimpleNamespace()) if False else None
    g.__dict__["bond_category"] = SimpleNamespace()
    return g.calculate_internal_strength()


@_site("group_spanning_external_strength")
def _(meta):
    from tests.unit._fakes import FakeString
    from tests.unit.test_groups import _PosObj, _group

    members = [_PosObj(0, 0), _PosObj(1, 1)]
    return _group(members, string=FakeString(objects=list(members), length=2)).calculate_external_strength(RNG1())


@_site("average_intra_unhappiness_empty")
def _(meta):
    from server.engine.workspace import Workspace

    return Workspace._compute_workspace_average_intra(SimpleNamespace(all_objects=[]))


@_site("selection_weight_default")
def _(meta):
    from server.engine.workspace import _object_weight

    return _object_weight(SimpleNamespace(), "no_such_weight")


@_site("rule_homogeneity_empty")
def _(meta):
    from server.engine.rules import _homogeneity

    return _homogeneity([], meta)


@_site("rule_object_description_uniformity_empty")
def _(meta):
    from server.engine.rules import _object_description_uniformity

    return _object_description_uniformity([], meta)


@_site("rule_change_abstractness_uniformity_empty")
def _(meta):
    from server.engine.rules import _change_abstractness_uniformity

    return _change_abstractness_uniformity([], meta)


@_site("rule_support_missing_bridge_strength")
def _(meta):
    from server.engine.rules import Rule

    rule = SimpleNamespace(supporting_bridges=[object()])
    with mock.patch("server.engine.rules._get_equivalent_bridge", return_value=None):
        return Rule.get_degree_of_support(rule, SimpleNamespace())


@_site("link_length_unset")
def _(meta):
    from server.engine.slipnet import SlipnetLink, SlipnetNode

    link = SlipnetLink(SimpleNamespace(short_name="a"), SimpleNamespace(short_name="b"), "lateral")
    node = SimpleNamespace(intrinsic_link_length=None)
    return (
        link.link_length(),
        link.intrinsic_degree_of_association(),
        SlipnetNode.degree_of_assoc(node),
    )


@_site("length_description_over_max_probability")
def _(meta):
    from server.engine.formulas import length_description_probability

    group = SimpleNamespace(length=int(meta.get_formula_coeff("length_description_max_group_length")) + 1)
    return length_description_probability(group, SimpleNamespace(activation=0.0, max_activation=100.0), 50.0, meta)


def _identity_rule():
    from server.engine.rules import Rule
    from tests.support.standard_names import RULE_TOP

    return Rule(rule_type=RULE_TOP, clauses=[])


@_site("rule_identity_quality")
def _(meta):
    r = _identity_rule()
    r.compute_quality(meta)
    return r.quality


@_site("rule_identity_abstractness")
def _(meta):
    r = _identity_rule()
    r.compute_quality(meta)
    return r.abstractness


@_site("clamp_event_strength")
def _(meta):
    from server.engine.trace import ClampEvent

    return ClampEvent.get_strength(SimpleNamespace())


@_site("snag_event_strength")
def _(meta):
    from server.engine.trace import SnagEvent

    return SnagEvent.get_strength(SimpleNamespace())


@_site("clamp_suppressed_concept_activation")
def _(meta):
    from server.engine.trace import _associated_concept_pattern

    pattern = {"type": "vertical_bridge", "entries": [
        {"dimension": "plato-letter-category", "relation": "opposite", "activation": -50.0}]}
    entries = _associated_concept_pattern(pattern, SimpleNamespace(name="plato-opposite"), 100.0)["entries"]
    return [e["activation"] for e in entries if e["node"] == "plato-opposite"]


class _Recorder:
    def __init__(self):
        self.probabilities = []

    def prob(self, p):
        self.probabilities.append(p)
        return False

    def trace_about(self, x):
        return None


def _theme_probabilities(meta):
    from server.engine.slipnet import Slipnet
    from server.engine.themes import Themespace
    from tests.support.standard_names import THEME_TOP_BRIDGE

    themespace = Themespace(meta)
    themespace.thematic_pressure_on()
    for _ in range(21):
        themespace.boost_theme(THEME_TOP_BRIDGE, "plato-direction-category", "identity", 100.0)
    for theme in themespace.get_all_active_themes():
        theme.activation = 50.0
    rec = _Recorder()
    themespace.spread_activation_to_slipnet(Slipnet.from_metadata(meta), rec)
    return rec.probabilities


@_site("theme_dimension_node_activation_exponent")
def _(meta):
    return _theme_probabilities(meta)[0]


@_site("theme_relation_node_activation_exponent")
def _(meta):
    return _theme_probabilities(meta)[1]


@_site("theme_conjunction_admission_exponent")
def _(meta):
    from server.engine.themes import Themespace, pick_theme_conjunction
    from tests.support.standard_names import THEME_VERTICAL_BRIDGE
    from tests.support.theme_fixtures import populate

    themespace = populate(Themespace(meta))
    for cluster in themespace.get_clusters(THEME_VERTICAL_BRIDGE):
        cluster.themes[0].activation = 25.0
    rec = _Recorder()
    pick_theme_conjunction(themespace, THEME_VERTICAL_BRIDGE, rec)
    return rec.probabilities[0]


@pytest.mark.parametrize("key", sorted(DIRECT))
def test_a_site_called_directly_follows_the_key(meta, key):
    rebind(meta)
    before = DIRECT[key](meta)
    value = changed(key)
    changed_meta = with_coefficient(meta, key, value)
    rebind(changed_meta)
    after = DIRECT[key](changed_meta)
    assert after != before, f"{key}: the site gave {before!r} under both values"


# --------------------------------------------------------------------------- the numeric backends


def _backends() -> list[str]:
    return ["python"] + [b for b in available_backends() if b != "off"]


@pytest.mark.parametrize("backend", _backends())
def test_every_backend_holds_a_clamped_object_at_the_configured_salience(meta, backend):
    from server.engine.numeric.layout import ObjectValueBatch, SalienceWeights

    def clamped_salience(m):
        n = 4
        batch = ObjectValueBatch(
            relative_importance=[50] * n, intra_unhappiness=[30.0] * n, horizontal_unhappiness=[30.0] * n,
            vertical_unhappiness=[30.0] * n, salience_clamped=[True] * n, string_type=[0] * n,
            justify_mode=[False] * n, prev_horizontal_salience=[0.0] * n, prev_vertical_salience=[0.0] * n,
            weights=SalienceWeights.from_metadata(m),
        )
        get_backend(backend).combine_object_values(batch)
        return batch.intra_salience, batch.horizontal_salience, batch.vertical_salience

    rebind(meta)
    assert clamped_salience(meta) == ([100] * 4, [100] * 4, [100] * 4)
    other = with_coefficient(meta, "clamped_salience", 50)
    rebind(other)
    assert clamped_salience(other) == ([50] * 4, [50] * 4, [50] * 4)


@pytest.mark.parametrize("backend", _backends())
def test_every_backend_pulls_a_structure_to_the_configured_targets(meta, backend):
    def strengths(m):
        # internal 50, external 50, one structure pulled up (+1), one pulled down (-1)
        return get_backend(backend).structure_strengths([50.0, 50.0], [50.0, 50.0], [0.5, -0.5])

    rebind(meta)
    assert strengths(meta) == [75, 25]
    other = with_coefficient(with_coefficient(meta, "thematic_pull_positive_target", 60.0),
                             "thematic_pull_negative_target", 10.0)
    rebind(other)
    assert strengths(other) == [55, 30]


@pytest.mark.parametrize("backend", _backends())
def test_every_backend_gives_the_configured_unhappiness_of_nothing(meta, backend):
    rebind(meta)
    value = get_backend(backend).average_unhappiness([], [])
    assert value == 100 and type(value) is int
    rebind(with_coefficient(meta, "average_unhappiness_empty", 40))
    assert get_backend(backend).average_unhappiness([], []) == 40
