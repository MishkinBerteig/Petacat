"""Structure fights: ``wins-fight?`` and the builders' weights.

``wins-fight?`` (``workspace-structures.ss:70-78``)::

    (tell challenger 'update-strength)
    (tell defender 'update-strength)
    (stochastic-pick '(#t #f)
      (temp-adjusted-values
        (list (* challenger-weight (tell challenger 'get-strength))
              (* defender-weight (tell defender 'get-strength)))))

Both strengths are recomputed at fight time, the contest is temperature-adjusted
(``formulas.ss:32-35``), and a weight of 0 is probability 0
(``utilities.ss:443-448``) — no floors.

The *weights* are the builders' own and are not all 1-vs-1.  One test per fight
the builders currently stage, each asserting the weight pair
``_get_incompatible_structures`` produces and then the probability that weight
pair implies at T=100 and T=0.  Probabilities are hand-computed in the comment
above each; the exponent is ``(100 - T)/30 + 0.5`` and every adjusted value is
rounded, exactly as ``temp-adjusted-values`` does.

Fakes: the metadata provider down to the two exponent coefficients, the slipnet
down to the ``.nodes`` mapping ``WorkspaceString`` reads, the engine context down
to the four attributes the two functions under test touch, and — for the
probability half of each test — a structure that is nothing but a strength.
"""

import pytest

from server.engine.bonds import Bond
from server.engine.bridges import BRIDGE_TOP, Bridge
from server.engine.codelet_dsl.builtins import (
    _get_incompatible_structures,
    _wins_fight,
)
from server.engine.groups import Group
from server.engine.rng import RNG
from server.engine.workspace import WorkspaceString
from server.engine.workspace_structures import WorkspaceStructure

from tests.unit._fakes import FakeNode


class _FakeMeta:
    """The two formula coefficients ``temp_adjusted_values`` reads."""

    def __init__(self, scale=30.0, base=0.5):
        self._coeffs = {"temp_exponent_scale": scale, "temp_exponent_base": base}

    def get_formula_coeff(self, name):
        return self._coeffs[name]


class _FakeSlipnet:
    def __init__(self):
        self.nodes = {}


class _FakeTemperature:
    def __init__(self, value):
        self.value = value


class _FakeWorkspace:
    """Only the three bridge lists ``_get_bridges_of_type`` consults."""

    def __init__(self, top_bridges=None):
        self.top_bridges = top_bridges if top_bridges is not None else []
        self.bottom_bridges = []
        self.vertical_bridges = []


class _FakeCtx:
    """The four attributes ``_get_incompatible_structures``/``_wins_fight`` read."""

    def __init__(self, *, workspace=None, temperature=50.0, seed=0):
        self.workspace = workspace if workspace is not None else _FakeWorkspace()
        self.temperature = _FakeTemperature(temperature)
        self.meta = _FakeMeta()
        self.rng = RNG(seed)


class _FixedStrength:
    """A structure that is nothing but a strength.

    ``update_strength`` is a no-op so the strength the test supplies is the
    strength the fight sees; recomputation is exercised separately below.
    """

    def __init__(self, strength):
        self.strength = strength
        self.updated = 0

    def update_strength(self):
        self.updated += 1


def _win_rate(proposer_weight, opponent_weight, p_strength, o_strength, temperature,
              trials=2000):
    wins = 0
    for seed in range(trials):
        ctx = _FakeCtx(temperature=temperature, seed=seed)
        if _wins_fight(
            ctx,
            _FixedStrength(p_strength),
            proposer_weight,
            _FixedStrength(o_strength),
            opponent_weight,
        ):
            wins += 1
    return wins / trials


def _string(text="abcd"):
    return WorkspaceString(text, _FakeSlipnet(), "initial")


def _bond(frm, to, category, direction=None):
    return Bond(
        from_object=frm,
        to_object=to,
        bond_category=category,
        bond_facet=FakeNode("plato-letter-category"),
        from_descriptor=FakeNode("plato-a"),
        to_descriptor=FakeNode("plato-b"),
        direction=direction,
    )


def _group(objs, string, category, direction=None, bonds=None):
    return Group(
        string=string,
        group_category=category,
        bond_facet=FakeNode("plato-letter-category"),
        direction=direction,
        objects=objs,
        bonds=bonds if bonds is not None else [],
    )


def _built(structure):
    structure.proposal_level = WorkspaceStructure.BUILT
    return structure


# ═══════════════════════════════════════════════════════════════════════════
# wins-fight? itself — workspace-structures.ss:70-78
# ═══════════════════════════════════════════════════════════════════════════

def test_fight_recomputes_both_strengths():
    """``(tell challenger 'update-strength)`` / ``(tell defender 'update-strength)``.

    A structure's strength moves with the themes and with everything built since
    it was evaluated; the fight is decided on what the two are worth now.
    """
    ctx = _FakeCtx(temperature=50.0)
    proposer, opponent = _FixedStrength(50.0), _FixedStrength(50.0)
    _wins_fight(ctx, proposer, 1.0, opponent, 1.0)
    assert proposer.updated == 1
    assert opponent.updated == 1


def test_zero_strength_challenger_never_wins():
    """``stochastic-pick`` gives a weight of 0 probability exactly 0.

    The linear form floored both sides at 1.0, so a worthless challenger still
    took roughly one fight in three against a strength-50 incumbent.
    """
    assert _win_rate(1.0, 1.0, 0.0, 50.0, 100.0, trials=500) == 0.0
    assert _win_rate(1.0, 1.0, 0.0, 50.0, 0.0, trials=500) == 0.0


def test_zero_strength_defender_always_loses():
    assert _win_rate(1.0, 1.0, 50.0, 0.0, 100.0, trials=500) == 1.0


def test_two_worthless_structures_are_a_coin_flip():
    """``(if (zero? weight-sum) (random-pick l))`` — the only uniform fallback."""
    assert _win_rate(1.0, 1.0, 0.0, 0.0, 50.0) == pytest.approx(0.5, abs=0.05)


# ═══════════════════════════════════════════════════════════════════════════
# One test per fight the builders stage
# ═══════════════════════════════════════════════════════════════════════════

# bonds.ss:370-376 — 1 vs 1.
#
#   strengths 60 / 40, weights 1 / 1
#   T=100  round(60**0.5) = 8    round(40**0.5) = 6      p = 8/14  = 0.571429
#   T=0    round(60**3.833333) = 6550078
#          round(40**3.833333) = 1384299                 p = 0.825531
def test_bond_versus_incompatible_bond_is_one_to_one():
    string = _string("abcd")
    a, b = string.objects[0], string.objects[1]
    sameness = FakeNode("plato-sameness")
    successor = FakeNode("plato-successor")
    string.bonds.append(_built(_bond(a, b, sameness)))
    proposed = _bond(a, b, successor)

    incompatibles = _get_incompatible_structures(_FakeCtx(), proposed)
    assert [(w1, w2) for _, w1, w2 in incompatibles] == [(1.0, 1.0)]

    assert _win_rate(1.0, 1.0, 60.0, 40.0, 100.0) == pytest.approx(0.571429, abs=0.04)
    assert _win_rate(1.0, 1.0, 60.0, 40.0, 0.0) == pytest.approx(0.825531, abs=0.04)


# bonds.ss:377-384 — 1 vs ``(maximum (tell-all incompatible-groups
# 'get-letter-span))``: ONE shared defender weight, the widest group's letter
# span, applied to every group in the set.  Each group's own span was wrong.
#
#   strengths 80 / 50, weights 1 / 3
#   T=100  round(80**0.5) = 9    round(150**0.5) = 12    p = 9/21  = 0.428571
#   T=0    round(80**3.833333)  =  19732326
#          round(150**3.833333) = 219625701              p = 0.082439
def test_bond_versus_incompatible_groups_shares_one_max_span_weight():
    string = _string("abcd")
    a, b, c = string.objects[0], string.objects[1], string.objects[2]
    sameness = FakeNode("plato-sameness")
    successor = FakeNode("plato-successor")
    samegrp = FakeNode("plato-same-group")

    conflicting = _bond(a, b, sameness)
    narrow = _built(_group([a, b], string, samegrp, bonds=[conflicting]))
    wide = _built(_group([a, b, c], string, samegrp, bonds=[conflicting]))
    string.groups.extend([narrow, wide])

    proposed = _bond(a, b, successor)
    incompatibles = _get_incompatible_structures(_FakeCtx(), proposed)

    assert narrow.span == 2 and wide.span == 3
    # Both groups defend with the *widest* group's span, not their own.
    assert [(w1, w2) for _, w1, w2 in incompatibles] == [(1.0, 3.0), (1.0, 3.0)]

    assert _win_rate(1.0, 3.0, 80.0, 50.0, 100.0) == pytest.approx(0.428571, abs=0.04)
    assert _win_rate(1.0, 3.0, 80.0, 50.0, 0.0) == pytest.approx(0.082439, abs=0.03)


# groups.ss:665-680 — a rival reading of the same material (same category *and*
# direction) is weighted by ``get-group-length``, the constituent count
# (groups.ss:80,242), not by letter span.
#
#   strengths 60 / 60, weights 3 / 2
#   T=100  round(180**0.5) = 13  round(120**0.5) = 11    p = 13/24 = 0.541667
#   T=0    round(180**3.833333) = 441785309
#          round(120**3.833333) =  93367295              p = 0.825531
def test_group_versus_same_category_group_is_weighted_by_group_length():
    string = _string("abcd")
    a, b, c, d = string.objects[:4]
    succgrp = FakeNode("plato-successor-group")
    right = FakeNode("plato-right")

    # Two subgroups make a group of *length 2* spanning all four letters.
    left_pair = _group([a, b], string, succgrp, right)
    right_pair = _group([c, d], string, succgrp, right)
    incumbent = _built(_group([left_pair, right_pair], string, succgrp, right))
    string.groups.append(incumbent)

    # A rival of *length 3* spanning only three of them.
    proposed = _group([a, b, c], string, succgrp, right)

    incompatibles = _get_incompatible_structures(_FakeCtx(), proposed)
    # Span would have said 3 vs 4 — the opposite ordering.
    assert (proposed.span, incumbent.span) == (3, 4)
    assert (proposed.length, incumbent.length) == (3, 2)
    assert [(w1, w2) for _, w1, w2 in incompatibles] == [(3.0, 2.0)]

    assert _win_rate(3.0, 2.0, 60.0, 60.0, 100.0) == pytest.approx(0.541667, abs=0.04)
    assert _win_rate(3.0, 2.0, 60.0, 60.0, 0.0) == pytest.approx(0.825531, abs=0.04)


# groups.ss:678-680 — any *other* incompatible group is a flat 1 vs 1.
def test_group_versus_differently_categorised_group_is_one_to_one():
    string = _string("abcd")
    a, b, c = string.objects[:3]
    succgrp = FakeNode("plato-successor-group")
    samegrp = FakeNode("plato-same-group")
    right = FakeNode("plato-right")

    incumbent = _built(_group([a, b], string, samegrp, None))
    string.groups.append(incumbent)
    proposed = _group([a, b, c], string, succgrp, right)

    incompatibles = _get_incompatible_structures(_FakeCtx(), proposed)
    assert [(w1, w2) for _, w1, w2 in incompatibles] == [(1.0, 1.0)]

    assert _win_rate(1.0, 1.0, 60.0, 40.0, 100.0) == pytest.approx(0.571429, abs=0.04)
    assert _win_rate(1.0, 1.0, 60.0, 40.0, 0.0) == pytest.approx(0.825531, abs=0.04)


# bridges.ss:1249-1254 — both sides are weighted by the *bridge's* letter span,
# ``object1 span + object2 span`` (bridges.ss:178-180).  Weighting by object1
# alone made the far side of the mapping count for nothing.
#
#   strengths 50 / 50, weights 4 / 2
#   T=100  round(200**0.5) = 14  round(100**0.5) = 10    p = 14/24 = 0.583333
#   T=0    round(200**3.833333) = 661629687
#          round(100**3.833333) =  46415888              p = 0.934445
def test_bridge_versus_bridge_is_weighted_by_both_objects_spans():
    initial = _string("abc")
    modified = WorkspaceString("abc", _FakeSlipnet(), "modified")
    a = initial.objects[0]
    samegrp = FakeNode("plato-same-group")
    far_group = _group(modified.objects[:3], modified, samegrp, None)
    far_letter = modified.objects[0]

    incumbent = _built(Bridge(a, far_letter, BRIDGE_TOP, []))
    workspace = _FakeWorkspace(top_bridges=[incumbent])
    # Shares object1, so the two are incompatible (bridges.ss:1551-1585).
    proposed = Bridge(a, far_group, BRIDGE_TOP, [])

    incompatibles = _get_incompatible_structures(
        _FakeCtx(workspace=workspace), proposed
    )
    assert (a.span, far_group.span, far_letter.span) == (1, 3, 1)
    # object1 alone would have said 1 vs 1.
    assert [(w1, w2) for _, w1, w2 in incompatibles] == [(4.0, 2.0)]

    assert _win_rate(4.0, 2.0, 50.0, 50.0, 100.0) == pytest.approx(0.583333, abs=0.04)
    assert _win_rate(4.0, 2.0, 50.0, 50.0, 0.0) == pytest.approx(0.934445, abs=0.03)


# bridges.ss:1292-1312 — a bridge resting on a reversed reading of a group has to
# beat the group it would replace, at even odds.
def test_bridge_versus_flipped_group_is_one_to_one():
    initial = _string("abc")
    modified = WorkspaceString("abc", _FakeSlipnet(), "modified")
    samegrp = FakeNode("plato-same-group")
    original = _built(_group(initial.objects[:3], initial, samegrp, None))

    proposed = Bridge(initial.objects[0], modified.objects[0], BRIDGE_TOP, [])
    proposed.flipped_group1 = original

    incompatibles = _get_incompatible_structures(_FakeCtx(), proposed)
    assert [(w1, w2) for _, w1, w2 in incompatibles] == [(1.0, 1.0)]

    assert _win_rate(1.0, 1.0, 60.0, 40.0, 100.0) == pytest.approx(0.571429, abs=0.04)
    assert _win_rate(1.0, 1.0, 60.0, 40.0, 0.0) == pytest.approx(0.825531, abs=0.04)
