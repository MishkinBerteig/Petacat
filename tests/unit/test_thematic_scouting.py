"""Unit tests for the thematic-bridge-scout's decisions (``themes.ss:750-1030``).

The scout is the third realization of thematic pressure (§4.1.2), and the thing
that makes it more than a filter is that it scouts a **conjunction** of themes:
"if the top themes Letter-Category: identity and String-Position: different are
both active, thematic-scout codelets will tend to look for potential bridges ...
having the same letter-category but different string positions".  Each decision
that conjunction rests on is isolated here — which theme type, which themes,
whether a pairing bears them out, and whether reversing a spanning group would
make it bear them out — with fakes for every collaborator and a scripted RNG, so
the stochastic architecture can be asserted on exactly.
"""

from __future__ import annotations

from typing import Any

from server.engine.slipnet import SlipnetLink, SlipnetNode
from server.engine.themes import (
    THEME_TOP_BRIDGE,
    THEME_VERTICAL_BRIDGE,
    Theme,
    ThemeCluster,
    bridge_type_for_theme_type,
    conditions_for_bridge,
    pick_theme_conjunction,
    pick_theme_type,
    theme_support_tester,
)
from server.engine.workspace_objects import WorkspaceObject


# --- test doubles ----------------------------------------------------------


class _ScriptedRNG:
    """Deterministic stand-in for ``RNG``.

    ``prob`` answers from a fixed script (then falls back to *default*) and
    ``weighted_pick`` takes the heaviest item, so a test asserts on *which*
    branch the code takes rather than on a seed.
    """

    def __init__(self, prob_script: list[bool] | None = None, default: bool = True):
        self.prob_script = list(prob_script or [])
        self.default = default
        self.prob_args: list[float] = []
        self.pick_calls: list[tuple[list, list]] = []

    def prob(self, p: float) -> bool:
        self.prob_args.append(p)
        if self.prob_script:
            return self.prob_script.pop(0)
        return self.default

    def weighted_pick(self, items: list, weights: list[float]) -> Any:
        self.pick_calls.append((list(items), list(weights)))
        return max(zip(items, weights), key=lambda pair: pair[1])[0]


class _Descriptor:
    """A descriptor concept: a name, and the labelled links out of it."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.short_name = name
        self.outgoing_links: list[Any] = []

    def link(self, other: "_Descriptor", label: str | None) -> None:
        label_node = _Descriptor(label) if label else None
        self.outgoing_links.append(
            type("L", (), {"to_node": other, "label_node": label_node})()
        )


class _Desc:
    def __init__(self, obj: Any, description_type: Any, descriptor: Any) -> None:
        self.object = obj
        self.description_type = description_type
        self.descriptor = descriptor


class _Obj:
    """A workspace object as the theme predicates see it.

    ``group`` decides whether it looks like a group at all (the predicates test
    for an ``objects`` attribute), and ``flip_to`` is what ``make_flipped_version``
    hands back — the reversed reading a scout would bridge to instead.
    """

    def __init__(
        self,
        *,
        spanning: bool = False,
        group: bool = False,
        spanning_bridges: int = 0,
        flip_to: "_Obj | None" = None,
    ) -> None:
        self.descriptions: list[_Desc] = []
        self._spanning = spanning
        self._group = group
        self._spanning_bridges = spanning_bridges
        self.flip_to = flip_to
        self.string = None
        if group:
            self.objects: list[Any] = []

    def describe(self, dimension: Any, descriptor: _Descriptor) -> "_Obj":
        # ``check-descriptions`` (themes.ss:1033-1040) pairs descriptions only
        # when the *same* description-type node is on both sides, so tests share
        # one dimension node rather than making one per object.
        self.descriptions.append(_Desc(self, dimension, descriptor))
        return self

    def get_all_descriptions(self) -> list[_Desc]:
        return list(self.descriptions)

    def spans_whole_string(self) -> bool:
        return self._spanning

    def string_spanning_group(self) -> bool:
        return self._group and self._spanning

    def get_num_of_spanning_bridges(self) -> int:
        return self._spanning_bridges

    def make_flipped_version(self) -> "_Obj":
        return self.flip_to if self.flip_to is not None else self


class _FakeWorkspace:
    def __init__(self, strengths: dict[str, float]) -> None:
        self.strengths = strengths

    def get_mapping_strength(self, bridge_type: str) -> float:
        return self.strengths[bridge_type]


DIRECTION = "plato-direction-category"
#: One shared node, because ``check-descriptions`` pairs on node identity.
DIRECTION_NODE = _Descriptor(DIRECTION)


def _direction_pair(name1: str, name2: str, label: str | None):
    """Two direction descriptors, linked so ``get-label`` finds *label*."""
    d1, d2 = _Descriptor(name1), _Descriptor(name2)
    d1.link(d2, label)
    d2.link(d1, label)
    return d1, d2


def _theme(dimension: str, relation: str, activation: float = 100.0) -> Theme:
    theme = Theme(THEME_VERTICAL_BRIDGE, dimension, relation)
    theme.activation = activation
    return theme


def _themespace(clusters: list[ThemeCluster], active: list[str]):
    """The slice of ``Themespace`` the scout's choosers actually consult."""

    class _TS:
        def get_active_bridge_theme_types(self) -> list[str]:
            return list(active)

        def get_max_positive_theme_activation(self, theme_type: str) -> float:
            return max(
                [0.0]
                + [
                    t.activation
                    for c in clusters
                    if c.theme_type == theme_type
                    for t in c.themes
                ]
            )

        def get_clusters(self, theme_type: str) -> list[ThemeCluster]:
            return [c for c in clusters if c.theme_type == theme_type]

    return _TS()


# --- ThemeCluster: which theme a cluster contributes -----------------------


def test_cluster_max_positive_activation_ignores_a_negative_theme():
    """A cluster's "max positive" is over ``(max 0 activation)``.

    Scheme: ``get-max-positive-theme-activation`` (themes.ss:489-490) reads
    ``get-positive-activation``, which is ``(max 0 activation)`` (themes.ss:640).
    It matters because this number is squared into the admission probability: a
    cluster holding only a negatively-clamped theme must score 0, not −100, or the
    arithmetic that inhibits a stuck interpretation would instead invite scouting
    of it.
    """
    cluster = ThemeCluster(THEME_TOP_BRIDGE, DIRECTION, ["identity", "opposite"])
    cluster.themes[0].activation = -100.0
    cluster.themes[1].activation = 30.0
    assert cluster.get_max_positive_theme_activation() == 30.0


def test_cluster_of_only_negative_themes_scores_zero():
    """Scheme: themes.ss:489-490 — a wholly negative cluster is never admitted,
    because ``prob?`` of ``(0/100)²`` is false."""
    cluster = ThemeCluster(THEME_TOP_BRIDGE, DIRECTION, ["identity", "opposite"])
    for theme in cluster.themes:
        theme.activation = -80.0
    assert cluster.get_max_positive_theme_activation() == 0.0


def test_pick_positive_theme_never_returns_a_negative_theme():
    """Only positive themes exert pressure through codelets.

    Scheme: ``pick-positive-theme`` (themes.ss:491-492) weights by positive
    activation, so a negative theme has weight 0.  themes.ss:771-775 explains why:
    scouting for structures that are *not* LettCtgy:identity creates "too many
    spurious bridges".  A real ``RNG`` is used here rather than the scripted one
    precisely because the guarantee has to hold for every draw.
    """
    from server.engine.rng import RNG

    cluster = ThemeCluster(THEME_TOP_BRIDGE, DIRECTION, ["identity", "opposite"])
    cluster.themes[0].activation = 60.0
    cluster.themes[1].activation = -100.0
    rng = RNG(7)
    picked = {cluster.pick_positive_theme(rng).relation for _ in range(200)}
    assert picked == {"identity"}


# --- pick_theme_type -------------------------------------------------------


def test_no_theme_type_is_chosen_without_thematic_pressure():
    """Scheme: themes.ss:755-759 — an empty active list fizzles the codelet.

    Pressure is off in the ordinary case (§4.1.2: "most of the time ... themes
    behave as passive representational structures"), so this is the branch the
    scout takes on nearly every run.
    """
    ts = _themespace([], active=[])
    assert pick_theme_type(ts, _FakeWorkspace({}), _ScriptedRNG()) is None


def test_theme_type_weight_is_activation_times_room_left_in_the_mapping():
    """Scheme: themes.ss:760-768 — ``max-positive-activation × (100 − mapping-strength)``.

    A mapping that is already strong is left alone however loud its themes are:
    that second factor is what stops thematic pressure from re-scouting a
    correspondence the program has already settled on.
    """
    top = ThemeCluster(THEME_TOP_BRIDGE, DIRECTION, ["identity"])
    top.themes[0].activation = 100.0
    vertical = ThemeCluster(THEME_VERTICAL_BRIDGE, DIRECTION, ["identity"])
    vertical.themes[0].activation = 50.0
    ts = _themespace([top, vertical], active=[THEME_TOP_BRIDGE, THEME_VERTICAL_BRIDGE])

    rng = _ScriptedRNG()
    # Top themes are twice as loud, but the top mapping is nearly complete.
    workspace = _FakeWorkspace({"top": 95.0, "vertical": 0.0})
    assert pick_theme_type(ts, workspace, rng) == THEME_VERTICAL_BRIDGE
    assert rng.pick_calls[-1][1] == [100.0 * 5.0, 50.0 * 100.0]


def test_bridge_type_names_match_the_scheme_mapping():
    """Scheme: ``theme-type->bridge-type`` (themes.ss:735-740)."""
    assert bridge_type_for_theme_type(THEME_TOP_BRIDGE) == "top"
    assert bridge_type_for_theme_type(THEME_VERTICAL_BRIDGE) == "vertical"


# --- pick_theme_conjunction ------------------------------------------------


def test_conjunction_draws_one_theme_from_each_admitted_cluster():
    """The scout looks for several themes at once — this is the T2.14 gap.

    Scheme: themes.ss:776-781.  Each cluster is admitted independently and
    contributes at most one theme, so the result is a conjunction across
    *dimensions*, which is what §4.1.2's "same letter-category but different
    string positions" requires.  One theme per codelet could not express it.
    """
    letter = ThemeCluster(THEME_VERTICAL_BRIDGE, "plato-letter-category", ["identity"])
    letter.themes[0].activation = 100.0
    position = ThemeCluster(
        THEME_VERTICAL_BRIDGE, "plato-string-position-category", ["diff"]
    )
    position.themes[0].activation = 100.0
    ts = _themespace([letter, position], active=[THEME_VERTICAL_BRIDGE])

    picked = pick_theme_conjunction(ts, THEME_VERTICAL_BRIDGE, _ScriptedRNG())
    assert [(t.dimension, t.relation) for t in picked] == [
        ("plato-letter-category", "identity"),
        ("plato-string-position-category", "diff"),
    ]


def test_cluster_admission_probability_is_activation_squared():
    """Scheme: themes.ss:777-780 — ``prob? (^2 (% max-positive-activation))``.

    Squaring makes admission steeply selective: a cluster at 50 gets in a quarter
    of the time, so a conjunction is usually short and made of the dimensions that
    are genuinely shouting rather than every dimension with a pulse.
    """
    cluster = ThemeCluster(THEME_VERTICAL_BRIDGE, DIRECTION, ["identity"])
    cluster.themes[0].activation = 50.0
    ts = _themespace([cluster], active=[THEME_VERTICAL_BRIDGE])

    rng = _ScriptedRNG(default=False)
    assert pick_theme_conjunction(ts, THEME_VERTICAL_BRIDGE, rng) == []
    assert rng.prob_args == [0.25]


# --- theme_support_tester --------------------------------------------------


def _pair_supporting_direction_identity():
    # ``get-label`` reports identity only for the *same* concept node, so both
    # objects must be described by one shared descriptor.
    shared = _Descriptor("plato-right")
    return (
        _Obj().describe(DIRECTION_NODE, shared),
        _Obj().describe(DIRECTION_NODE, shared),
    )


def test_support_requires_at_least_one_theme_actually_borne_out():
    """Silence is not support.

    Scheme: ``theme-support-tester`` (themes.ss:1029-1030) is
    ``(and (not (ormap conflicts?)) (ormap supports?))``.  A pairing that says
    nothing about any theme fails the second half, which is what keeps thematic
    pressure a search for evidence rather than a licence to bridge anything that
    does not contradict.
    """
    supported = theme_support_tester([_theme(DIRECTION, "identity")])
    assert supported(_Obj(), _Obj()) is False


def test_support_granted_when_a_theme_is_borne_out():
    """Scheme: themes.ss:1027-1030 — one supporting description pair is enough."""
    object1, object2 = _pair_supporting_direction_identity()
    supported = theme_support_tester([_theme(DIRECTION, "identity")])
    assert supported(object1, object2) is True


def test_a_single_conflicting_theme_vetoes_the_whole_conjunction():
    """Conflict is a veto, not a vote.

    Scheme: themes.ss:1029 — ``(not (ormap conflicts? themes))`` is evaluated over
    *all* themes.  So a conjunction is satisfied only where nothing in it is
    contradicted, which is exactly what makes it a conjunction rather than a
    weighted preference.
    """
    left, right = _direction_pair("plato-left", "plato-right", "plato-opposite")
    object1 = _Obj().describe(DIRECTION_NODE, left)
    object2 = _Obj().describe(DIRECTION_NODE, right)
    themes = [_theme(DIRECTION, "opposite"), _theme(DIRECTION, "identity")]
    assert theme_support_tester(themes)(object1, object2) is False
    # ... while the supported half alone would have passed.
    assert theme_support_tester(themes[:1])(object1, object2) is True


# --- conditions_for_bridge -------------------------------------------------


def test_a_whole_string_paired_with_a_fragment_is_rejected():
    """Scheme: ``lone-spanning-object?`` (themes.ss:980, workspace-objects.ss:653).

    A whole string and part of another are not playing the same role, so no
    conjunction of themes can make the pairing worth proposing.
    """
    conditions = conditions_for_bridge(
        _Obj(spanning=True, group=True), True, [_theme(DIRECTION, "identity")],
        _ScriptedRNG(),
    )
    assert conditions(_Obj(spanning=False)) is None


def test_no_flip_is_asked_for_when_the_themes_already_hold():
    """Scheme: themes.ss:981-983 — an empty condition list means "as they stand"."""
    object1, object2 = _pair_supporting_direction_identity()
    conditions = conditions_for_bridge(
        object1, True, [_theme(DIRECTION, "identity")], _ScriptedRNG()
    )
    assert conditions(object2) == []


def test_flipping_one_spanning_group_is_offered_when_that_satisfies_the_themes():
    """Reading ``>abc>`` as ``<cba<`` is a reinterpretation, not a rival parse.

    Scheme: ``conditions-for-bridge`` (themes.ss:996-999).  Flipping is considered
    only between two string-spanning groups, because only there does reversing one
    cover the same material.  This is how the crosswise mapping of §2.4.5 becomes
    reachable at all: without it a Direction: identity theme simply rules out every
    pairing of an ``abc`` group with a ``cba`` group.
    """
    left, right = _direction_pair("plato-left", "plato-right", "plato-opposite")

    object1 = _Obj(spanning=True, group=True).describe(DIRECTION_NODE, right)
    object2_flipped = _Obj(spanning=True, group=True).describe(DIRECTION_NODE, right)
    object2 = _Obj(spanning=True, group=True, flip_to=object2_flipped).describe(
        DIRECTION_NODE, left
    )

    conditions = conditions_for_bridge(
        object1, True, [_theme(DIRECTION, "identity")], _ScriptedRNG()
    )
    assert conditions(object2) == [object2]


def test_both_groups_are_flipped_when_neither_alone_suffices():
    """Scheme: themes.ss:1000-1001 — the last resort before giving up.

    Both sides reversed is still the same two spans read the other way round, so
    it is offered after each single flip has been tried and failed.
    """
    # Reversed, both sides read as the same concept; as they stand, and in either
    # half-flipped combination, they read as opposites.
    shared = _Descriptor("plato-right")
    down = _Descriptor("plato-down")
    up = _Descriptor("plato-up")
    for other in (down, up):
        other.link(shared, "plato-opposite")
        shared.link(other, "plato-opposite")
    down.link(up, "plato-opposite")
    up.link(down, "plato-opposite")

    object1_flipped = _Obj(spanning=True, group=True).describe(DIRECTION_NODE, shared)
    object2_flipped = _Obj(spanning=True, group=True).describe(DIRECTION_NODE, shared)
    object1 = _Obj(spanning=True, group=True, flip_to=object1_flipped).describe(
        DIRECTION_NODE, down
    )
    object2 = _Obj(spanning=True, group=True, flip_to=object2_flipped).describe(
        DIRECTION_NODE, up
    )

    conditions = conditions_for_bridge(
        object1, True, [_theme(DIRECTION, "identity")], _ScriptedRNG()
    )
    assert conditions(object2) == [object1, object2]


def test_flip_order_is_biased_against_the_more_committed_group():
    """Scheme: themes.ss:986-992 — 20/80/50 on the spanning-bridge counts.

    A group already carrying more spanning bridges is the more expensive one to
    reinterpret, so the coin is weighted towards trying the other one first.  The
    bias is a probability, not a rule: the expensive reading is still reachable,
    which is what "parallel terraced scan" means here.
    """
    seen: list[float] = []

    class _Recorder(_ScriptedRNG):
        def prob(self, p: float) -> bool:
            seen.append(p)
            return True

    left, right = _direction_pair("plato-left", "plato-right", "plato-opposite")
    object1 = _Obj(spanning=True, group=True, spanning_bridges=2).describe(
        DIRECTION_NODE, left
    )
    object2 = _Obj(spanning=True, group=True, spanning_bridges=0).describe(
        DIRECTION_NODE, right
    )
    conditions_for_bridge(
        object1, True, [_theme(DIRECTION, "identity")], _Recorder()
    )(object2)
    assert seen == [0.20]


# --- the object-level predicates the flip decision reads -------------------


def test_only_a_whole_string_object_counts_spanning_bridges():
    """Scheme: ``get-num-of-spanning-bridges`` (workspace-objects.ss:356-359).

    A bridge is "spanning" by virtue of what it joins, so an object that covers
    only part of its string has none however many bridges rest on it.
    """
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=1)
    obj.horizontal_bridge = object()
    obj.vertical_bridge = object()
    assert obj.get_num_of_spanning_bridges() == 0


def test_spanning_bridges_counted_on_both_axes():
    """Scheme: workspace-objects.ss:356-359 — ``(count exists? (list h v))``."""

    class _WholeString:
        length = 2

    obj = WorkspaceObject(string=_WholeString(), left_pos=0, right_pos=1)
    assert obj.get_num_of_spanning_bridges() == 0
    obj.vertical_bridge = object()
    assert obj.get_num_of_spanning_bridges() == 1
    obj.horizontal_bridge = object()
    assert obj.get_num_of_spanning_bridges() == 2


# --- Slipnet support the flip and the coattail slippage rest on ------------


def test_related_node_can_be_asked_for_by_relation_name():
    """Flipping a group has no Slipnet handle to name ``plato-opposite`` with.

    Scheme: ``(tell group-category 'get-related-node plato-opposite)``
    (groups.ss:334-338).  Passing the *name* used to raise ``AttributeError`` into
    a bare ``except`` at both flip call sites, so a "flipped" group silently kept
    its original category and direction — which made the whole of themes.ss:996-1010
    a no-op.
    """
    succgrp = SlipnetNode("plato-succgrp", "succgrp", 50)
    predgrp = SlipnetNode("plato-predgrp", "predgrp", 50)
    opposite = SlipnetNode("plato-opposite", "opp", 90)
    succgrp.lateral_sliplinks.append(
        SlipnetLink(succgrp, predgrp, "lateral_sliplink", opposite)
    )
    assert succgrp.get_related_node("plato-opposite") is predgrp
    assert succgrp.get_related_node(opposite) is predgrp


def test_label_degree_of_assoc_shrinks_when_the_label_is_fully_active():
    """Scheme: ``get-degree-of-assoc`` on a slipnode (slipnet.ss:90-91).

    This is the probability an auxiliary slippage is made with
    (themes.ss:920-924), so an active ``opposite`` makes opposite-labelled
    coattail slippages markedly more likely — the Slipnet's state feeding directly
    into how far one slippage drags others.
    """
    opposite = SlipnetNode("plato-opposite", "opp", 90)
    opposite.intrinsic_link_length = 80
    assert opposite.degree_of_assoc() == 20.0
    opposite.activation = 100.0
    assert opposite.degree_of_assoc() == 68.0  # 100 - round(0.4 * 80)
