"""Tests for MetadataProvider loading from seed_data/."""

import os
import pytest
from server.engine.metadata import MetadataProvider


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def test_loads_slipnet_nodes(meta):
    assert len(meta.slipnet_node_specs) == 59
    assert "plato-a" in meta.slipnet_node_specs
    assert "plato-successor" in meta.slipnet_node_specs
    assert meta.slipnet_node_specs["plato-a"].conceptual_depth == 10
    assert meta.slipnet_node_specs["plato-sameness"].conceptual_depth == 80


def test_loads_slipnet_links(meta):
    assert len(meta.slipnet_link_specs) > 200


def test_loads_codelet_types(meta):
    assert len(meta.codelet_specs) == 27
    assert "bottom-up-bond-scout" in meta.codelet_specs
    assert "breaker" in meta.codelet_specs
    spec = meta.get_codelet_spec("bottom-up-bond-scout")
    assert spec.family == "bond"
    assert spec.phase == "scout"
    assert spec.default_urgency == 35


def test_loads_urgency_levels(meta):
    assert meta.get_urgency("extremely_low") == 7
    assert meta.get_urgency("low") == 35
    assert meta.get_urgency("extremely_high") == 91


def test_loads_engine_params(meta):
    assert meta.get_param("max_activation") == 100
    assert meta.get_param("update_cycle_length") == 15
    assert meta.get_param("max_coderack_size") == 100
    assert meta.get_param("full_activation_threshold") == 50


def test_loads_formula_coefficients(meta):
    assert meta.get_formula_coeff("temp_exponent_base") == 0.5
    assert meta.get_formula_coeff("temp_exponent_scale") == 30.0
    assert meta.get_formula_coeff("unhappiness_weight") == 70.0


def test_loads_posting_rules(meta):
    assert len(meta.posting_rules) > 0
    bond_scout_rules = [
        r for r in meta.posting_rules if r.codelet_type == "bottom-up-bond-scout"
    ]
    assert len(bond_scout_rules) == 1


def test_loads_demo_problems(meta):
    assert len(meta.demo_problems) > 0
    run7 = [d for d in meta.demo_problems if d.name == "run7"]
    assert len(run7) == 1
    assert run7[0].initial == "abc"
    assert run7[0].modified == "abd"
    assert run7[0].target == "xyz"
    assert run7[0].seed == 3852097033


def test_loads_theme_dimensions(meta):
    assert len(meta.theme_dimensions) == 9
    dir_dim = [d for d in meta.theme_dimensions if d.slipnet_node == "plato-direction-category"]
    assert len(dir_dim) == 1
    assert "identity" in dir_dim[0].valid_relations
    assert "opposite" in dir_dim[0].valid_relations


def test_loads_slipnet_layout(meta):
    assert len(meta.slipnet_layout) == 59
    assert meta.slipnet_layout["plato-a"] == (2, 0)
    assert meta.slipnet_layout["plato-identity"] == (1, 0)


def test_loads_codelet_patterns(meta):
    assert "rule-codelet-pattern" in meta.codelet_patterns
    rule_pattern = meta.codelet_patterns["rule-codelet-pattern"]
    assert len(rule_pattern) == 3
    # The tier is named, not numbered: a pattern says *which* level and the run
    # resolves it against ``urgency_levels``.
    assert rule_pattern[0] == ("rule-scout", "very_high")
    assert meta.get_urgency(rule_pattern[0][1]) == 77


def test_get_param_default(meta):
    assert meta.get_param("nonexistent", 42) == 42


def test_fixed_length_false_loaded_correctly(meta):
    """Links with explicit fixed_length: false should load as fixed_length=False."""
    # Lateral links between letters have fixed_length: false in the JSON
    letter_links = [
        lk for lk in meta.slipnet_link_specs
        if lk.from_node == "plato-a" and lk.to_node == "plato-b"
        and lk.link_type == "lateral"
    ]
    assert len(letter_links) == 1
    assert letter_links[0].fixed_length is False
    assert letter_links[0].label_node == "plato-successor"


def test_fixed_length_with_link_length_loaded_correctly(meta):
    """Links with explicit link_length (no fixed_length key) should be fixed."""
    instance_links = [
        lk for lk in meta.slipnet_link_specs
        if lk.from_node == "plato-letter-category" and lk.to_node == "plato-a"
    ]
    assert len(instance_links) == 1
    assert instance_links[0].fixed_length is True
    assert instance_links[0].link_length == 97


def test_spreading_activation_threshold_param(meta):
    """Spreading activation threshold should default to 100."""
    assert meta.get_param("spreading_activation_threshold") == 100


def test_loads_enum_values(meta):
    """MetadataProvider should load enum_values from enums.json."""
    assert len(meta.enum_values) == 14
    assert "run_statuses" in meta.enum_values
    assert "event_types" in meta.enum_values
    assert "bridge_types" in meta.enum_values
    assert "proposal_levels" in meta.enum_values
    assert "initialized" in meta.enum_values["run_statuses"]
    assert "bond_built" in meta.enum_values["event_types"]
    assert "top" in meta.enum_values["bridge_types"]
    assert "proposed" in meta.enum_values["proposal_levels"]


def test_enum_values_match_expected_counts(meta):
    """Each enum table should have the expected number of values."""
    assert len(meta.enum_values["run_statuses"]) == 6
    # 17: the 16 original types plus concept_activation, one of the seven
    # Temporal Trace event types of §4.4.
    assert len(meta.enum_values["event_types"]) == 17
    assert len(meta.enum_values["bridge_types"]) == 3
    assert len(meta.enum_values["bridge_orientations"]) == 2
    assert len(meta.enum_values["clause_types"]) == 3
    assert len(meta.enum_values["rule_types"]) == 2
    assert len(meta.enum_values["theme_types"]) == 3
    assert len(meta.enum_values["proposal_levels"]) == 3
    assert len(meta.enum_values["link_types"]) == 5
    assert len(meta.enum_values["codelet_families"]) == 8
    assert len(meta.enum_values["codelet_phases"]) == 4
    assert len(meta.enum_values["posting_directions"]) == 3
    assert len(meta.enum_values["param_value_types"]) == 5
    assert len(meta.enum_values["demo_modes"]) == 2


def test_the_bottom_up_posting_rules_are_in_the_order_the_engine_posts_them():
    """The seed file's order of the bottom-up rules *is* the posting order.

    `_post_bottom_up_codelets` walks these in sequence and each one it reaches draws
    from the run's random stream — a posting probability, and on success a count and
    sometimes a blurred object tally.  Two orderings of the same eleven rules therefore
    send every subsequent decision somewhere else, so the order is part of the
    configuration and not a detail of how the file happens to be written.

    The list here is the one `runner.py` used to hold as a Python literal, kept
    verbatim.  `PHASE 1 PLAN.md` §0.5 allows no cognitive change while the switches
    become data, and this is where that is checked: the seed file was reordered to
    match the code rather than the code reordered to match the file, because the code
    was what the oracle in `ORACLE-COMPARISON.md` measured.
    """
    import os

    from server.engine.metadata import MetadataProvider

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    meta = MetadataProvider.from_seed_data(seed_dir)

    assert [
        rule.codelet_type for rule in meta.posting_rules if rule.direction == "bottom_up"
    ] == [
        "bottom-up-bond-scout",
        "group-scout:whole-string",
        "bottom-up-bridge-scout",
        "important-object-bridge-scout",
        "bottom-up-description-scout",
        "rule-scout",
        "answer-finder",
        "answer-justifier",
        "progress-watcher",
        "jootser",
        "breaker",
    ]


def test_every_posting_formula_uses_only_names_the_engine_supplies():
    """The seed data and the formula vocabulary agree, checked from both ends.

    A formula naming something the engine does not supply would raise the first time
    its rule was consulted, which for a rarely-reached rule could be a long way into a
    run.  Checking the shipped formulas against the namespace makes that a property of
    the repository rather than of a particular run.
    """
    import ast
    import os

    from server.engine.metadata import MetadataProvider
    from server.engine.posting import POSTING_FORMULA_NAMES

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    meta = MetadataProvider.from_seed_data(seed_dir)

    for rule in meta.posting_rules:
        if not rule.posting_formula:
            continue
        used = {
            node.id
            for node in ast.walk(ast.parse(rule.posting_formula, mode="eval"))
            if isinstance(node, ast.Name)
        }
        unknown = used - POSTING_FORMULA_NAMES
        assert not unknown, (
            f"{rule.codelet_type}'s posting formula {rule.posting_formula!r} names "
            f"{sorted(unknown)}, which server/engine/posting.py does not supply"
        )


def test_each_posted_urgency_is_one_of_the_named_urgency_levels():
    """`urgency_when_posted` and `urgency_levels` must not drift apart.

    The engine used to reach these through `meta.get_urgency("low")`, `("medium")` and
    `("extremely_low")`, while the rules stated 35, 49 and 7 — the same numbers written
    twice, in two files, with nothing holding them together.  Now that the rules are
    what the engine reads, editing `urgency_levels.json` would move one and not the
    other, which is `PHASE 1 PLAN.md` §0.2(c)'s two-definitions problem arriving by the
    back door.

    Pinning every posted urgency to *some* named level is what makes that visible: it
    does not stop an admin choosing 42, but it does stop the shipped configuration
    quietly ceasing to mean what the named levels say.
    """
    import os

    from server.engine.metadata import MetadataProvider

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    meta = MetadataProvider.from_seed_data(seed_dir)

    named = set(meta.urgency_levels.values())
    for rule in meta.posting_rules:
        if rule.urgency_when_posted is None:
            continue
        assert rule.urgency_when_posted in named, (
            f"{rule.codelet_type} posts at urgency {rule.urgency_when_posted}, which is "
            f"no named level: {sorted(meta.urgency_levels.items(), key=lambda kv: kv[1])}"
        )

    # And the three the engine used to name, specifically.
    by_type = {r.codelet_type: r.urgency_when_posted for r in meta.posting_rules}
    assert by_type["bottom-up-bond-scout"] == meta.get_urgency("low")
    assert by_type["progress-watcher"] == meta.get_urgency("medium")
    assert by_type["jootser"] == meta.get_urgency("medium")
    assert by_type["breaker"] == meta.get_urgency("extremely_low")


def test_every_condition_is_a_predicate_the_engine_can_evaluate():
    """Conditions are boolean expressions over the posting vocabulary, or `always`.

    They used to be labels: eight distinct strings, none of them read anywhere, whose
    meaning lived in three separate pieces of Python. Now they are evaluated, so each
    one has to name quantities the engine supplies.
    """
    import ast
    import os

    from server.engine.metadata import MetadataProvider
    from server.engine.posting import POSTING_FORMULA_NAMES

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    meta = MetadataProvider.from_seed_data(seed_dir)

    for rule in meta.posting_rules:
        if rule.condition in ("", "always"):
            continue
        used = {
            node.id
            for node in ast.walk(ast.parse(rule.condition, mode="eval"))
            if isinstance(node, ast.Name)
        }
        unknown = used - POSTING_FORMULA_NAMES
        assert not unknown, (
            f"{rule.codelet_type}'s condition {rule.condition!r} names {sorted(unknown)}, "
            f"which server/engine/posting.py does not supply"
        )


def test_a_codelet_pattern_names_its_urgency_tier_rather_than_a_number():
    """One definition of a pattern, and it says *which* tier, not what the tier is.

    `server/engine/codelet_patterns.py` held five of the nine patterns a second time,
    in Python, for the control API — the same concept with two definitions, which is
    `PHASE 1 PLAN.md` §0.2(c).  Its own docstring stated the intended design: "urgencies
    are named rather than numeric: the values live in `urgency_levels` seed data, so a
    pattern says *which* level and the run resolves it."  The seed data stored 77 and
    91.

    Now that the Python copy is gone and the seed data is the only definition, it is the
    one that has to say which level.  `Coderack._pattern_entry` resolves a named
    urgency, so this costs nothing at the call sites and stops the numbers being
    written down twice.
    """
    import os

    from server.engine.metadata import MetadataProvider

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    meta = MetadataProvider.from_seed_data(seed_dir)

    assert meta.codelet_patterns, "no patterns loaded"
    for name, entries in meta.codelet_patterns.items():
        assert entries, name
        for codelet_type, urgency in entries:
            assert urgency in meta.urgency_levels, (
                f"{name} pins {codelet_type} at {urgency!r}, which is no named tier"
            )


def test_the_clampable_patterns_are_five_of_the_nine():
    """`gui.ss:599-603` puts five on the Options menu; `trace.ss` defines nine.

    Which five, and what the menu calls them, is real information that was only in the
    Python module.  It is a parameter now, and every name in it has to resolve to a
    pattern that exists.
    """
    import os

    from server.engine.metadata import MetadataProvider

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    meta = MetadataProvider.from_seed_data(seed_dir)

    menu = meta.get_param("clampable_codelet_patterns")
    assert list(menu) == ["top_down", "bottom_up", "rule", "bridge", "group"]
    for name, label in menu.items():
        assert label.endswith("codelet pattern"), label
        key = name.replace("_", "-") + "-codelet-pattern"
        assert key in meta.codelet_patterns, f"{name} names no pattern"


#: Engine parameters that are read by something other than the engine's own run loop,
#: or by nothing at all.  Every other key in ``engine_params.json`` must be a run
#: parameter.  Keeping the classification here rather than in prose is deliberate:
#: every written-out count of this in the repository had drifted from the source it
#: claimed to describe, in one case by five.
_READ_BY_THE_ENGINE_BUT_NOT_OFFERED = {
    # Named things rather than numbers in a range — no control kind renders them.
    "initial_codelet_types",
    "initial_codelet_urgency",
    "initial_codelet_rounds",
    # Numbers that could be offered and are not yet.
    "expiration_period",
    "num_youngest_structures",
    "max_theme_activation",
    "distance_threshold",
    "slippage_ignore_probability",
}

#: Read by the control API, never by a run.
_READ_BY_ANOTHER_LAYER = {"clampable_codelet_patterns"}

#: Read by nothing: Scheme-era, unported, superseded by the run request, or display.
_READ_BY_NOTHING = {
    "max_temperature",
    "maximum_rule_line_length",
    "garbage_collect_cycles",
    "step_cycles",
    "eliza_mode_default",
    "justify_mode_default",
    "initial_speed",
    "max_num_of_flashes",
    "max_flash_pause",
    "max_snag_pause",
    "text_scroll_pause",
    "codelet_highlight_pause",
}


def test_every_engine_parameter_is_classified():
    """No parameter may be silently neither offered nor accounted for.

    A key that is in `engine_params.json`, absent from `RUN_PARAMETERS`, and absent
    from the three sets above is one nobody has decided about — and the way this
    codebase's configuration defects have all begun is a value that is shipped,
    hashed and displayed while nobody has said what reads it.
    """
    import json
    import os

    from server.engine.parameters import RUN_PARAMETERS

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    with open(os.path.join(seed_dir, "engine_params.json")) as f:
        keys = set(json.load(f))

    offered = {p.name for p in RUN_PARAMETERS}
    classified = (
        offered
        | _READ_BY_THE_ENGINE_BUT_NOT_OFFERED
        | _READ_BY_ANOTHER_LAYER
        | _READ_BY_NOTHING
    )

    unclassified = keys - classified
    assert not unclassified, (
        "engine parameters that are neither offered per Run nor accounted for: "
        f"{sorted(unclassified)}. Decide what reads each one and put it in the right "
        "set in this file."
    )
    stale = classified - keys - offered
    assert not stale, f"classified names that are not in engine_params.json: {sorted(stale)}"


def test_a_parameter_is_not_both_offered_and_excused():
    """The four groups partition; nothing sits in two of them."""
    from server.engine.parameters import RUN_PARAMETERS

    offered = {p.name for p in RUN_PARAMETERS}
    groups = {
        "offered": offered,
        "engine, not offered": _READ_BY_THE_ENGINE_BUT_NOT_OFFERED,
        "another layer": _READ_BY_ANOTHER_LAYER,
        "nothing": _READ_BY_NOTHING,
    }
    names = list(groups)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            overlap = groups[left] & groups[right]
            assert not overlap, f"{left} and {right} both claim {sorted(overlap)}"
