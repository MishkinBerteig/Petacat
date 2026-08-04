"""Module integration tests for Workspace."""

import os
import pytest
from server.engine.metadata import MetadataProvider
from server.engine.slipnet import Slipnet
from server.engine.workspace import Workspace, WorkspaceString
from server.engine.workspace_objects import Letter
from server.engine.rng import RNG

# Every test here executes arithmetic the numeric substrate owns, so each one runs
# once per backend in the matrix. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def slipnet(meta):
    return Slipnet.from_metadata(meta)


def test_workspace_string_creation(slipnet):
    ws = WorkspaceString("abc", slipnet)
    assert ws.length == 3
    assert len(ws.objects) == 3
    assert isinstance(ws.objects[0], Letter)
    assert ws.objects[0].letter_category.name == "plato-a"
    assert ws.objects[2].letter_category.name == "plato-c"


def test_workspace_creation(slipnet):
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    assert w.initial_string.text == "abc"
    assert w.modified_string.text == "abd"
    assert w.target_string.text == "xyz"
    assert w.answer_string is None


def test_workspace_with_answer(slipnet):
    w = Workspace("abc", "abd", "xyz", "wyz", slipnet)
    assert w.answer_string is not None
    assert w.answer_string.text == "wyz"


def test_all_objects(slipnet):
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    objects = w.all_objects
    # 3 + 3 + 3 = 9 letters total
    assert len(objects) == 9


def test_choose_object(slipnet):
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    rng = RNG(42)
    obj = w.choose_object("intra", rng)
    assert obj is not None
    assert isinstance(obj, Letter)


def test_average_unhappiness_initial(slipnet):
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    # Initially all objects have 100 unhappiness, but importance is 0
    # so weighted average might be different
    w.update_all_object_values()
    unhappiness = w.get_average_unhappiness()
    assert 0 <= unhappiness <= 100


def test_update_object_values(slipnet):
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    w.update_all_object_values()
    for obj in w.all_objects:
        assert 0 <= obj.relative_importance <= 100


# ======================================================================
#  Workspace statistics feeding temperature and codelet posting
#  (Scheme: workspace.ss:541-603, 678-716)
# ======================================================================


def _bridge_everything(w):
    """Give every object of the top and vertical pairs a full-strength bridge."""
    from server.engine.bridges import BRIDGE_TOP, BRIDGE_VERTICAL, Bridge

    for i in range(3):
        for other, kind in (
            (w.modified_string.letters[i], BRIDGE_TOP),
            (w.target_string.letters[i], BRIDGE_VERTICAL),
        ):
            bridge = Bridge(w.initial_string.letters[i], other, kind, [])
            bridge.strength = 100.0
            w.add_bridge(bridge)
    for o in w.all_objects:
        o.update_inter_string_unhappiness()
        o.update_average_unhappiness()


def _settle_the_strings(w):
    """Pretend every string is perfectly bonded, leaving the mappings untouched."""
    for o in w.all_objects:
        o.intra_string_unhappiness = 0.0
        o.update_average_unhappiness()
    w._average_unhappiness = None


def test_average_unhappiness_stays_high_while_nothing_is_mapped(slipnet):
    """Scheme: ``workspace.ss:581-585`` averages each object's *average*
    unhappiness, which carries the mapping deficit.

    A workspace whose strings are perfectly bonded but whose objects have no
    bridges at all is not 0% unhappy: inter-string unhappiness is 100 for every
    unbridged object, so the blend cannot fall below the intra-string half.
    Aggregating intra-string unhappiness alone reported total contentment here,
    and that value is 70% of the temperature.
    """
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    w.update_all_object_values()
    _settle_the_strings(w)

    assert w.get_average_intra_string_unhappiness() == 0
    assert w.get_average_unhappiness() >= 50


def test_average_unhappiness_falls_once_the_mappings_are_built(slipnet):
    """The same workspace, now fully bridged, does reach 0."""
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    w.update_all_object_values()
    _bridge_everything(w)
    _settle_the_strings(w)

    assert w.get_average_unhappiness() == 0


def test_workspace_intra_average_is_importance_weighted_over_all_objects(slipnet):
    """Scheme: ``workspace.ss:557-561`` — one weighted mean over every object,
    not the mean of the per-string means.

    Concentrating all the importance on one string makes the two readings
    disagree: the weighted mean follows that string, the mean-of-means does not.
    """
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    for o in w.all_objects:
        o.relative_importance = 0.0
        o.intra_string_unhappiness = 0.0
    for letter in w.target_string.letters:
        letter.relative_importance = 100.0
        letter.intra_string_unhappiness = 90.0

    # Mean of the three per-string means would be (0 + 0 + 90) / 3 = 30.
    assert w.get_average_intra_string_unhappiness() == 90


def test_weighted_averages_are_zero_when_no_importance_is_assigned(slipnet):
    """``weighted-average`` (``utilities.ss:388-392``) returns 0 on zero weight —
    it does not fall back to an unweighted mean."""
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    for o in w.all_objects:
        o.relative_importance = 0.0
    assert w.get_average_unhappiness() == 0
    assert w.get_average_intra_string_unhappiness() == 0


def test_max_inter_string_unhappiness_reads_the_mapping_deficit(slipnet):
    """Scheme: ``workspace.ss:511-517``.  It is 100 with nothing bridged and 0
    once every mapping is made — and 0 is a legitimate answer, which is why the
    thematic-scout count has no floor."""
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    w.update_all_object_values()
    w.update_average_unhappiness_values()
    assert w.get_max_inter_string_unhappiness() == 100

    _bridge_everything(w)
    w.update_average_unhappiness_values()
    assert w.get_max_inter_string_unhappiness() == 0


def test_min_mapping_strength_includes_the_bottom_pair_when_justifying(slipnet):
    """Scheme: ``workspace.ss:522-528``.  Justifying, a strong top and vertical
    mapping must not hide an absent bottom one from the bridge scouts."""
    w = Workspace("abc", "abd", "xyz", "wyz", slipnet)
    w.update_all_object_values()
    _bridge_everything(w)  # top and vertical only; the bottom pair stays bare
    w.update_average_unhappiness_values()

    # Neither pair has a spanning bridge and only "abc" could hold a spanning
    # group, so both go through the ``tanh`` branch: 100·tanh(100/40) ≈ 99.
    assert w.get_mapping_strength("top") >= 99
    assert w.get_mapping_strength("vertical") >= 99
    assert w.get_min_mapping_strength() == 0


def test_justify_mode_reaches_the_strings_and_their_objects(slipnet):
    """A target-string object maps horizontally onto the answer string only when
    justifying (``workspace-objects.ss:484-487``), and it learns that from its
    string.  The flag was initialised False and set nowhere."""
    plain = Workspace("abc", "abd", "xyz", None, slipnet)
    assert plain.justify_mode is False
    assert all(not s.justify_mode for s in plain.all_strings)

    justifying = Workspace("abc", "abd", "xyz", "wyz", slipnet)
    assert justifying.justify_mode is True
    assert all(s.justify_mode for s in justifying.all_strings)
    assert justifying.target_string.letters[0]._justify_mode() is True


def test_target_object_salience_responds_to_a_bottom_bridge_when_justifying(slipnet):
    """With the flag unset, a target object's horizontal unhappiness stayed frozen
    at its initial 100 for the whole of every justify run, whatever the bottom
    mapping did — and its average salience used the two-term non-justify formula."""
    from server.engine.bridges import BRIDGE_BOTTOM, Bridge

    w = Workspace("abc", "abd", "xyz", "wyz", slipnet)
    w.update_all_object_values()
    target_y = w.target_string.letters[1]
    before = target_y.salience["average"]

    bridge = Bridge(target_y, w.answer_string.letters[1], BRIDGE_BOTTOM, [])
    bridge.strength = 100.0
    w.add_bridge(bridge)
    w.update_all_object_values()

    assert target_y.inter_string_unhappiness["horizontal"] == 0
    assert target_y.salience["average"] < before


def test_check_if_rules_possible_stores_its_verdict(slipnet):
    """Scheme: ``workspace.ss:454-472`` writes ``top-rule-possible?``; three
    consumers read it back.  Petacat computed it and threw it away."""
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    w.check_if_rules_possible()
    assert w.top_rule_possible is False
    assert w.get_possible_rule_types() == []
    assert w.rule_possible("top") is False

    w.top_rule_possible = True
    assert w.get_possible_rule_types() == ["top"]
    assert w.rule_possible("top") is True


def test_rule_factor_wants_a_rule_both_possible_and_supported(slipnet):
    """Scheme: ``formulas.ss:65-75``.  A supported rule alone is not enough — a
    verbatim rule is vacuously supported, and would otherwise take 30 points off
    the temperature the moment it was built."""
    from server.engine.rules import RULE_TOP, Rule

    w = Workspace("abc", "abd", "xyz", None, slipnet)
    rule = Rule(RULE_TOP, [])
    w.add_rule(rule)
    assert w.get_supported_rules(True) == [rule]

    w.top_rule_possible = False
    assert w.rule_established() is False
    w.top_rule_possible = True
    assert w.rule_established() is True


def test_justify_mode_rule_factor_needs_both_pairs(slipnet):
    from server.engine.rules import RULE_BOTTOM, RULE_TOP, Rule

    w = Workspace("abc", "abd", "xyz", "wyz", slipnet)
    w.add_rule(Rule(RULE_TOP, []))
    w.top_rule_possible = True
    w.bottom_rule_possible = True
    assert w.rule_established() is False  # no bottom rule yet

    w.add_rule(Rule(RULE_BOTTOM, []))
    assert w.rule_established() is True


def test_rough_counts_cover_groups_as_well_as_letters(slipnet):
    """``get-rough-num-of-*`` counts over ``get-objects`` — every object of every
    string, letters and groups alike.  The per-string counters it replaced
    filtered to ``isinstance(o, Letter)``."""
    from server.engine.groups import Group
    from server.engine.rng import RNG

    w = Workspace("abc", "abd", "xyz", None, slipnet)
    letters = w.initial_string.letters[:2]
    group = Group(
        string=w.initial_string,
        group_category=slipnet.nodes["plato-succgrp"],
        bond_facet=slipnet.nodes["plato-letter-category"],
        direction=slipnet.nodes["plato-right"],
        objects=letters,
        bonds=[],
    )
    w.initial_string.add_group(group)

    # 9 letters + 1 group = 10 objects; the two inside the group are no longer
    # ungrouped, and the group itself does not span "abc", so it counts.
    ungrouped_count = sum(1 for o in w.all_objects if _is_ungrouped(o))
    assert ungrouped_count == 8

    rng = RNG(3)
    assert w.get_rough_num_of_ungrouped_objects(rng) == "many"


def _is_ungrouped(obj):
    from server.engine.workspace import ungrouped

    return ungrouped(obj)
