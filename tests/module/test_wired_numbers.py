"""Changing a stored number changes the behaviour it names, on every numeric backend.

Stage W of the Metacat cleanup wired in the numbers the engine used to repeat as literals:
``probabilistic_activation_exponent``, the four ``*_string_salience_*_weight`` coefficients and
``max_raw_importance`` (once dead rows), and ``max_activation``, ``max_theme_activation``,
``concept_activation_importance_threshold`` and ``jootsing_count_scale`` (half-wired: some reads
took the row and some a literal).  A wired site that reads its row on one path and ignores it on
another is exactly the defect, so each number is changed here, in a configuration built in the test
(never the seed files), and a real run is compared against the same run under the Metacat Standard
Configuration.  The whole module runs once per backend in the numeric matrix.

The sites are also pinned one by one, below, so a change that breaks only one site names it.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner

pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def base() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED_DIR)


def _params(base: MetadataProvider, **changes) -> MetadataProvider:
    return dataclasses.replace(base, params={**base.params, **changes})


def _coefficients(base: MetadataProvider, **changes) -> MetadataProvider:
    return dataclasses.replace(base, formula_coefficients={**base.formula_coefficients, **changes})


def _run(meta: MetadataProvider, problem=("abc", "abd", "xyz"), answer=None, seed=1, steps=1500):
    runner = EngineRunner(meta)
    runner.init_mcat(*problem, answer, seed=seed)
    runner.run_mcat(max_steps=steps)
    ctx = runner.ctx
    return (
        runner.status,
        ctx.codelet_count,
        ctx.rng.call_count,
        len(ctx.trace.events),
        round(ctx.temperature.value, 3),
    )


#: (name, how to change it, the run that shows it).  Each run was chosen because the change moves it.
_JUSTIFY = (("xqc", "xqd", "mrrjjj"), "mrrkkk")
CHANGES = {
    "probabilistic_activation_exponent": (lambda b: _coefficients(b, probabilistic_activation_exponent=1.0), {}),
    "intra salience weights": (
        lambda b: _coefficients(
            b, intra_string_salience_unhappiness_weight=20.0, intra_string_salience_importance_weight=80.0
        ),
        {},
    ),
    "inter salience weights": (
        lambda b: _coefficients(
            b, inter_string_salience_unhappiness_weight=80.0, inter_string_salience_importance_weight=20.0
        ),
        {},
    ),
    "max_raw_importance": (lambda b: _coefficients(b, max_raw_importance=100.0), {}),
    "max_activation": (lambda b: _params(b, max_activation=50), {}),
    "concept_activation_importance_threshold": (
        lambda b: _params(b, concept_activation_importance_threshold=100000),
        {},
    ),
    "max_theme_activation": (
        lambda b: _params(b, max_theme_activation=10),
        {"problem": _JUSTIFY[0], "answer": _JUSTIFY[1], "steps": 3000},
    ),
}


@pytest.mark.parametrize("name", sorted(CHANGES))
def test_changing_a_wired_number_changes_the_run(name: str, base: MetadataProvider) -> None:
    change, run_kwargs = CHANGES[name]
    assert _run(change(base), **run_kwargs) != _run(base, **run_kwargs), (
        f"{name} is stored, and changing it moved nothing"
    )


def test_concept_activation_events_all_obey_the_importance_threshold(base: MetadataProvider) -> None:
    """Every concept-activation event reaches the Trace through the one parameter.

    At 100000 none can: a clamp's own monitor used to take a literal 85, so 21 events still passed.
    """
    from server.engine.trace import CONCEPT_ACTIVATION

    def concept_events(meta) -> int:
        runner = EngineRunner(meta)
        runner.init_mcat("rst", "rsu", "xyz", None, seed=1)
        runner.run_mcat(max_steps=2500)
        return sum(1 for e in runner.ctx.trace.events if e.event_type == CONCEPT_ACTIVATION)

    assert concept_events(base) > 0
    assert concept_events(_params(base, concept_activation_importance_threshold=100000)) == 0


# --- one site at a time -------------------------------------------------------------------------


def _params_at(ceiling: float):
    from tests.support.standard_configuration import standard_activation

    return dataclasses.replace(standard_activation(), max_activation=ceiling)


def test_a_clamp_without_an_activation_pins_the_node_at_its_ceiling() -> None:
    from server.engine.slipnet import SlipnetNode

    node = SlipnetNode("n", "n", 50, _params_at(50.0))
    node.clamp()
    assert node.activation == 50.0
    node.clamp(0, 20.0)
    assert node.activation == 20.0


def test_the_label_flush_clips_at_the_nodes_ceiling() -> None:
    from server.engine.concept_mappings import ConceptMapping
    from server.engine.slipnet import SlipnetNode

    label = SlipnetNode("identity", "ident", 90, _params_at(50.0))
    label.activation = 40.0
    label.activation_buffer = 30.0
    mapping = ConceptMapping.__new__(ConceptMapping)
    mapping.label = label
    mapping.activate_label()
    assert label.activation == 50.0


def test_the_length_description_exponent_follows_the_ceiling() -> None:
    from server.engine.formulas import share_of_ceiling, unfilled_share_of_ceiling

    assert unfilled_share_of_ceiling(25.0, 50.0) == 0.5
    assert unfilled_share_of_ceiling(25.0, 100.0) == 0.75
    assert share_of_ceiling(25.0, 50.0) == 0.5
    # A ceiling of 0 is defined: nothing can be active, so every share is 0 and all the room is free.
    assert share_of_ceiling(0.0, 0.0) == 0.0
    assert unfilled_share_of_ceiling(0.0, 0.0) == 1.0


def test_theme_conjunction_admission_follows_the_theme_ceiling(base: MetadataProvider) -> None:
    from server.engine.themes import THEME_VERTICAL_BRIDGE, Themespace, pick_theme_conjunction
    from tests.support.theme_fixtures import populate

    class Recorder:
        def __init__(self) -> None:
            self.probabilities: list[float] = []

        def prob(self, p: float) -> bool:
            self.probabilities.append(p)
            return False

    def admissions(meta) -> list[float]:
        themespace = populate(Themespace(meta))
        for cluster in themespace.get_clusters(THEME_VERTICAL_BRIDGE):
            cluster.themes[0].activation = 25.0
        rng = Recorder()
        pick_theme_conjunction(themespace, THEME_VERTICAL_BRIDGE, rng)
        return rng.probabilities

    at_100 = admissions(base)
    at_50 = admissions(_params(base, max_theme_activation=50))
    assert at_100 and set(at_100) == {0.0625}
    assert set(at_50) == {0.25}


def test_a_theme_pattern_from_a_list_is_set_at_the_theme_ceiling(base: MetadataProvider) -> None:
    from server.engine.justify import _build_theme_pattern_dict, _theme_pattern_list_to_dict

    meta = _params(base, max_theme_activation=40)
    built = _theme_pattern_list_to_dict(["vertical_bridge", ("plato-direction-category", None)], meta)
    assert [e["activation"] for e in built["entries"]] == [40.0]
    built = _build_theme_pattern_dict("vertical_bridge", [("plato-direction-category", None)], meta)
    assert [e["activation"] for e in built["entries"]] == [40.0]


def test_a_clamped_theme_pattern_without_an_activation_is_set_at_the_theme_ceiling(
    base: MetadataProvider,
) -> None:
    from server.engine.themes import THEME_VERTICAL_BRIDGE, Themespace
    from server.engine.trace import clamp_theme_pattern

    meta = _params(base, max_theme_activation=40)
    themespace = Themespace(meta)
    cluster = next(c for c in themespace.clusters if c.theme_type == THEME_VERTICAL_BRIDGE)
    pattern = {
        "type": THEME_VERTICAL_BRIDGE,
        "entries": [{"dimension": cluster.dimension, "relation": cluster.valid_relations[0]}],
    }
    clamp_theme_pattern(pattern, themespace)
    assert max(t.activation for t in cluster.themes) == 40.0


def test_a_derived_concept_pattern_is_pinned_at_the_slipnets_ceiling() -> None:
    from server.engine.trace import _associated_concept_pattern

    entries = _associated_concept_pattern(
        ["vertical_bridge", ("plato-direction-category", "opposite")], None, 50.0
    )["entries"]
    assert [e["activation"] for e in entries] == [50.0]


def _snag_probability(scale: int) -> float:
    from server.engine.jootsing import attempt_jootsing
    from server.engine.trace import SnagEvent, TemporalTrace

    class Recorder:
        def __init__(self) -> None:
            self.asked: list[float] = []

        def prob(self, p: float) -> bool:
            self.asked.append(p)
            return False

    class Meta:
        codelet_patterns: dict = {}

        def get_param(self, name):
            return {"settling_period": 250, "max_clamp_period": 750, "grace_period": 100,
                    "satisfactory_rule_quality": 80, "jootsing_count_scale": scale,
                    "jootsing_recurring_clamps_min": 3, "jootsing_recurring_snags_min": 3,
                    "jootsing_elapsed_weight_at_start": 100.0}[name]

    trace = TemporalTrace()
    for count in range(6):
        trace.record_event(SnagEvent(
            codelet_count=100 * (count + 1), temperature=100.0,
            snag_theme_pattern={"type": "vertical_bridge",
                                "entries": [{"dimension": "plato-direction-category", "relation": "identity"}]},
        ))
    rng = Recorder()
    attempt_jootsing(trace, themespace=None, meta=Meta(), codelet_count=1000, rng=rng)
    # the first gate asks for the chance of *not* jootsing
    return 1.0 - rng.asked[0]


def test_the_snag_branch_of_the_jootser_reads_jootsing_count_scale() -> None:
    at_10, at_5, at_0 = _snag_probability(10), _snag_probability(5), _snag_probability(0)
    assert at_10 == pytest.approx(0.6)
    assert at_5 == pytest.approx(0.3)
    assert at_0 == 0.0


def test_a_node_holding_nothing_never_jumps_whatever_the_exponent() -> None:
    """The object-graph path agrees with the backends at a zero share (``0.0 ** -1.0`` raises)."""
    from server.engine.numeric.layout import jump_probability
    from server.engine.slipnet import SlipnetNode
    from tests.support.standard_configuration import standard_activation

    params = dataclasses.replace(
        standard_activation(), full_activation_threshold=0.0, probabilistic_exponent=-1.0
    )
    node = SlipnetNode("n", "n", 50, params)
    node.activation = 0.0

    class Rng:
        asked: list = []

        def trace_about(self, x):
            return None

        def prob(self, p):
            self.asked.append(p)
            return False

    rng = Rng()
    node.probabilistic_jump_to_full(rng)
    assert rng.asked == [0.0]
    assert jump_probability(0.5, -2000.0) == float("inf")
