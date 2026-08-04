"""The bridge scouts, builder and incompatibility test inside an assembled engine.

Real Slipnet, real Workspace, real codelet interpreter; no database and no HTTP.
These cover the gates the reference puts between "pick two objects" and "post an
evaluator" (``bridges.ss:895-1057``), the augmentation ``build-bridge`` performs
on the way in (``bridges.ss:1355-1419``), the refinements in
``incompatible-horizontal-bridges?`` (``bridges.ss:1551-1580``), and the answer
codelet a rule build posts (``rules.ss:489-491``).
"""

from __future__ import annotations

import os

import pytest

from server.engine.bonds import Bond
from server.engine.bridges import (
    BRIDGE_TOP,
    Bridge,
    _incompatible_bridges,
    possible_bridge_cms,
    reverse_direction_orientation,
)
from server.engine.codelet_dsl.builtins import build_structure, get_builtins
from server.engine.codelet_dsl.interpreter import CodeletInterpreter, CodeletRegistry
from server.engine.concept_mappings import ConceptMapping
from server.engine.groups import Group
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.engine.runner import EngineRunner

# Every test here reaches the numeric seam through ``init_mcat``'s first
# ``update-workspace-values``, so each runs once per backend. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def _engine(meta, initial, modified, target, seed=42):
    runner = EngineRunner(meta)
    runner.init_mcat(initial, modified, target, seed=seed)
    return runner


def _interpreter(meta):
    interp = CodeletInterpreter(builtins=get_builtins())
    return interp, CodeletRegistry.from_metadata(meta, interp)


def _posted(ctx):
    return [c for b in ctx.coderack.bins for c in b.codelets]


class _RecordingRNG(RNG):
    """Records every ``prob`` argument, and answers each one as told."""

    def __init__(self, seed, answers=None):
        super().__init__(seed)
        self.prob_calls: list[float] = []
        self._answers = list(answers or [])

    def prob(self, p: float) -> bool:
        self.prob_calls.append(p)
        if self._answers:
            return self._answers.pop(0)
        return super().prob(p)


class _NeverRNG(RNG):
    """Refuses every chance offered — every ``stochastic-if*`` falls through."""

    def prob(self, p: float) -> bool:
        return False


def _all_active(slipnet):
    """Put every node at full activation, so nothing is refused for irrelevance."""
    for node in slipnet.nodes.values():
        node.activation = 100.0


# --- BR-1: the slippage-admissibility gate ---------------------------------


def _refusal_probability(ctx, object1, object2, bridge_type=BRIDGE_TOP):
    """The gate's own product, computed the way the scout body computes it.

    ``bridges.ss:928-937`` — ``(product (map 1- slippabilities))`` where each
    slippability has been through ``temp-adjusted-probability``, and ``1-`` is
    ``(lambda (x) (- 1 x))`` (utilities.ss:500), *not* ``x - 1``.
    """
    from server.engine.formulas import temp_adjusted_probability

    cms = possible_bridge_cms(
        bridge_type, object1, object2, ctx.slipnet.nodes["plato-identity"]
    )
    assert cms, "the pair must have mappings for the gate to be about anything"
    refusal = 1.0
    for cm in cms:
        refusal *= 1.0 - temp_adjusted_probability(
            cm.slippability() / 100.0, ctx.temperature.value, ctx.meta
        )
    return refusal


def test_the_slippage_gate_refuses_a_deep_slippage_more_often_when_cold(meta):
    """The gate is temperature-controlled, which is its whole point.

    With only Letter-Category relevant, a bridge from ``a`` to ``d`` rests on
    ``LettCtgy: a=>d`` alone — an *unlinked* slippage, worth the no-link floor
    of 5, so the raw admissibility is 0.05.  ``temp-adjusted-probability``
    (formulas.ss:20-29) interpolates a below-half probability toward one decade
    above itself in proportion to ``(10 - sqrt(100-T))/100``: nothing at all at
    T=0, a tenth of the way at T=100.  So the *refusal* product is highest when
    the run is cold and settled and lowest when it is hot and exploring, which
    is the behaviour §"conceptual slippage" asks for.
    """
    engine = _engine(meta, "abc", "abd", "xyz")
    ctx = engine.ctx
    for node in ctx.slipnet.nodes.values():
        node.activation = 0.0
    ctx.slipnet.nodes["plato-letter-category"].activation = 100.0
    a = ctx.workspace.initial_string.letters[0]
    d = ctx.workspace.modified_string.letters[2]

    ctx.temperature.value = 100.0
    hot = _refusal_probability(ctx, a, d)
    ctx.temperature.value = 0.0
    cold = _refusal_probability(ctx, a, d)

    assert 0.0 < hot < cold <= 1.0
    assert round(hot, 3) == 0.855
    assert round(cold, 3) == 0.950


def test_the_slippage_gate_is_a_no_op_for_identity_mappings_when_cold(meta):
    """Slippability is 100 for an identity mapping, so ``1 - 1 = 0``.

    ``a`` to ``a`` across the top pair is all identities; at T=0
    ``temp-adjusted-probability`` returns 1.0 unchanged, the product collapses
    to zero, and the gate cannot refuse.  (At T=100 it does not: the high branch
    of the adjustment returns ``1 - 0.1``, so even an identity bridge is
    declined a tenth of the time when the run is maximally confused — the
    reference's arithmetic, not a special case.)
    """
    engine = _engine(meta, "abc", "abd", "xyz")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    a_initial = ctx.workspace.initial_string.letters[0]
    a_modified = ctx.workspace.modified_string.letters[0]

    ctx.temperature.value = 0.0
    assert _refusal_probability(ctx, a_initial, a_modified) == 0.0
    ctx.temperature.value = 100.0
    assert _refusal_probability(ctx, a_initial, a_modified) > 0.0


def test_the_bottom_up_scout_consults_the_slippage_gate(meta):
    """The gate is a real ``stochastic-if*`` in the scout, not a derivation.

    Run the codelet with an RNG that records what it is asked and refuses
    everything: the recorded probabilities must include a value in ``[0, 1]``
    that the scout computed from concept-mapping slippabilities.
    """
    engine = _engine(meta, "abc", "abd", "xyz")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    interp, registry = _interpreter(meta)
    ctx.rng = _RecordingRNG(7)

    for _ in range(40):
        interp.execute(registry.get_compiled("bottom-up-bridge-scout"), ctx)

    assert ctx.rng.prob_calls, "the scout made no probabilistic decision at all"
    assert all(0.0 <= p <= 1.0 for p in ctx.rng.prob_calls)


# --- BR-2: the distinguishing identity/opposite requirement ----------------


def test_a_slippage_only_bridge_has_no_distinguishing_identity_or_opposite(meta):
    """``abc -> abcd``, the reference's own example (bridges.ss:942-947).

    ``b``'s mappings to ``d`` are ``ObjCtgy: letter=>letter`` (an identity, but
    not distinguishing — every letter is a letter), ``StrPosCtgy: middle=>rmost``
    and ``LettCtgy: b=>d``.  Neither slippage is an identity or an opposite, so
    the bridge has no a priori justification and the ordinary scouts must
    refuse it.
    """
    engine = _engine(meta, "abc", "abcd", "xyz")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    b = ctx.workspace.initial_string.letters[1]
    d = ctx.workspace.modified_string.letters[3]

    cms = possible_bridge_cms(
        BRIDGE_TOP, b, d, ctx.slipnet.nodes["plato-identity"]
    )
    assert cms
    assert not any(cm.distinguishing_identity_or_opposite() for cm in cms)

    # ...whereas the honest b-b mapping does have one.
    b_modified = ctx.workspace.modified_string.letters[1]
    honest = possible_bridge_cms(
        BRIDGE_TOP, b, b_modified, ctx.slipnet.nodes["plato-identity"]
    )
    assert any(cm.distinguishing_identity_or_opposite() for cm in honest)


def test_the_ordinary_scouts_never_propose_a_slippage_only_bridge(meta):
    """No bridge-evaluator posted by an ordinary scout lacks the justification.

    The thematic scout is the one channel that may propose such a bridge, and it
    is not running here: ``self_watching`` posts it only under pressure, and
    nothing is clamped.
    """
    engine = _engine(meta, "abc", "abcd", "xyz")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    interp, registry = _interpreter(meta)

    proposals = []
    for name in ("bottom-up-bridge-scout", "important-object-bridge-scout"):
        for _ in range(120):
            ctx.coderack.clear()
            interp.execute(registry.get_compiled(name), ctx)
            proposals.extend(
                c.arguments["structure"]
                for c in _posted(ctx)
                if c.codelet_type == "bridge-evaluator"
            )

    assert proposals, "the scouts proposed nothing, so the test proves nothing"
    for bridge in proposals:
        assert any(
            cm.distinguishing_identity_or_opposite()
            for cm in bridge.concept_mappings
        ), f"{bridge} rests on slippages alone"


def test_the_thematic_scout_can_still_reach_a_slippage_only_bridge(meta):
    """§4.1.2: "active horizontal-bridge themes can override this".

    The thematic scout applies no such gate — it proposes whatever the clamped
    conjunction points at — so the division of labour the two gates create is
    intact only if the thematic path is free of them.
    """
    import inspect

    from server.engine import themes

    for name in ("bottom-up-bridge-scout", "important-object-bridge-scout"):
        body = meta.get_codelet_spec(name).execute_body
        assert "distinguishing_identity_or_opposite" in body, name

    thematic = meta.get_codelet_spec("thematic-bridge-scout").execute_body
    assert "distinguishing_identity_or_opposite" not in thematic
    assert "slippability" not in thematic
    # ...and nothing it calls applies one on its behalf.
    assert "distinguishing_identity_or_opposite" not in inspect.getsource(
        themes.look_for_auxiliary_slippages
    )


# --- BR-3: the flipped-bridge proposal -------------------------------------


def _spanning_group(ctx, string, category: str, direction: str) -> Group:
    """Bond every adjacent pair and wrap the string in one directed group."""
    node = ctx.slipnet.nodes
    letters = string.letters
    bonds = []
    for left, right in zip(letters, letters[1:]):
        bond = Bond(
            left,
            right,
            node[f"plato-{category}"],
            node["plato-letter-category"],
            left.letter_category,
            right.letter_category,
            node[f"plato-{direction}"],
        )
        bond.proposal_level = bond.BUILT
        string.add_bond(bond)
        bonds.append(bond)
    group = Group(
        string=string,
        group_category=node[f"plato-{category[:4]}grp"],
        bond_facet=node["plato-letter-category"],
        direction=node[f"plato-{direction}"],
        objects=list(letters),
        bonds=bonds,
    )
    group.proposal_level = group.BUILT
    string.add_group(group)
    return group


def test_reverse_direction_orientation_holds_only_while_opposite_is_cold(meta):
    """``reverse-direction-orientation?`` (bridges.ss:1060-1066), all three conjuncts.

    ``>abc>`` against ``<cba<``: every reversible dimension maps opposite, and a
    Direction mapping exists.  Whether to re-read the second group forwards then
    turns entirely on ``plato-opposite`` — saturated, MetaCat is content to see
    the two as opposites and leaves them alone.
    """
    engine = _engine(meta, "abc", "abd", "cba")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    forwards = _spanning_group(ctx, ctx.workspace.initial_string, "successor", "right")
    backwards = _spanning_group(ctx, ctx.workspace.target_string, "predecessor", "left")

    cms = possible_bridge_cms(
        "vertical", forwards, backwards, ctx.slipnet.nodes["plato-identity"]
    )
    assert any(cm.reversible_cm_type for cm in cms)

    ctx.slipnet.nodes["plato-opposite"].activation = 50.0
    assert reverse_direction_orientation(cms) is True

    ctx.slipnet.nodes["plato-opposite"].activation = 100.0
    assert reverse_direction_orientation(cms) is False


def test_a_spanning_pair_is_proposed_flipped_when_opposite_is_not_saturated(meta):
    """The ordinary scouts route through ``propose_bridge`` with the flip flag.

    Before BR-3 both scouts constructed a ``Bridge`` directly and
    ``make_flipped_version`` was reachable only from the thematic path, so
    re-perceiving a spanning group backwards was unavailable to bottom-up
    processing entirely.
    """
    from server.engine.bridges import propose_bridge

    engine = _engine(meta, "abc", "abd", "cba")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    ctx.slipnet.nodes["plato-opposite"].activation = 50.0
    forwards = _spanning_group(ctx, ctx.workspace.initial_string, "successor", "right")
    backwards = _spanning_group(ctx, ctx.workspace.target_string, "predecessor", "left")

    cms = possible_bridge_cms(
        "vertical", forwards, backwards, ctx.slipnet.nodes["plato-identity"]
    )
    flip = reverse_direction_orientation(cms)
    assert flip is True

    bridge = propose_bridge(
        "vertical", forwards, False, backwards, flip,
        ctx.slipnet.nodes["plato-identity"], ctx,
    )
    assert bridge.flipped_group2 is backwards
    assert bridge.object2 is not backwards
    assert bridge.object2.direction is ctx.slipnet.nodes["plato-right"]

    # The flipped reading shares a Direction mapping with the forward group,
    # which the unflipped pair does not — that is what the flip buys.
    directions = [
        cm
        for cm in bridge.concept_mappings
        if cm.description_type1.name == "plato-direction-category"
    ]
    assert directions and all(cm.is_identity for cm in directions)


# --- BR-5: the build-time concept-mapping augmentation ---------------------


def _proposed_bridge(ctx, object1, object2, bridge_type=BRIDGE_TOP) -> Bridge:
    from server.engine.bridges import propose_bridge

    return propose_bridge(
        bridge_type, object1, False, object2, False,
        ctx.slipnet.nodes["plato-identity"], ctx,
    )


def _built_bridge(ctx, object1, object2, bridge_type=BRIDGE_TOP) -> Bridge:
    bridge = _proposed_bridge(ctx, object1, object2, bridge_type)
    assert build_structure(ctx, bridge) is True
    return bridge


def test_a_letter_to_group_bridge_gains_a_length_mapping_it_had_no_description_for(
    meta,
):
    """``a -> aa``: ``Length: one=>two`` even though neither object is described by length.

    ``build-bridge`` (bridges.ss:1395-1411) adds the mapping from the two
    objects' *platonic* lengths.  Without it the bridge says nothing about
    length having changed, and a rule abstracted from it cannot either — which
    is the difference between "replace a by aa" being expressible and not.
    """
    engine = _engine(meta, "a", "aa", "b")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    a = ctx.workspace.initial_string.letters[0]
    aa = _spanning_group(ctx, ctx.workspace.modified_string, "sameness", "right")

    length = ctx.slipnet.nodes["plato-length"]
    assert a.get_descriptor_for(length) is None
    assert aa.get_descriptor_for(length) is None

    bridge = _built_bridge(ctx, a, aa)

    length_cms = [
        cm for cm in bridge.concept_mappings if cm.description_type1 is length
    ]
    assert len(length_cms) == 1
    cm = length_cms[0]
    assert cm.descriptor1 is ctx.slipnet.nodes["plato-one"]
    assert cm.descriptor2 is ctx.slipnet.nodes["plato-two"]


def test_every_horizontal_bridge_is_guaranteed_an_object_category_mapping(meta):
    """bridges.ss:1365-1381 — relevant or not, so rule abstraction sees no
    accidental asymmetry between ``a -> aa`` and ``b -> bb``."""
    engine = _engine(meta, "a", "aa", "b")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    object_category = ctx.slipnet.nodes["plato-object-category"]
    # Make the dimension irrelevant, so the proposal cannot carry the mapping.
    object_category.activation = 0.0

    a = ctx.workspace.initial_string.letters[0]
    aa = _spanning_group(ctx, ctx.workspace.modified_string, "sameness", "right")
    bridge = _built_bridge(ctx, a, aa)

    assert bridge.cm_type_present(object_category)


def test_a_built_bridge_stores_the_symmetric_version_of_every_slippage(meta):
    """bridges.ss:1383-1385, with the label recomputed (concept-mappings.ss:154-159).

    ``c -> d`` carries ``LettCtgy: c=(succ)=>d``; its stored reverse must be
    ``d=(pred)=>c``.  Carrying the forward label across was latent while nothing
    read the reverses, and stops being latent the moment the coattail search
    does (``themes.ss:896``): the wrong label drags the wrong slippage after it.

    The Length mapping added at build time is deliberately *not* symmetrised —
    the reference adds it after the symmetric loop and gives it no reverse
    (bridges.ss:1395-1411).
    """
    engine = _engine(meta, "abc", "abd", "xyz")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    c = ctx.workspace.initial_string.letters[2]
    d = ctx.workspace.modified_string.letters[2]
    bridge = _built_bridge(ctx, c, d)

    letter_category = ctx.slipnet.nodes["plato-letter-category"]
    forward = [
        cm
        for cm in bridge.get_non_symmetric_slippages()
        if cm.description_type1 is letter_category
    ]
    assert len(forward) == 1
    assert forward[0].label is ctx.slipnet.nodes["plato-successor"]

    reverse = [
        cm
        for cm in bridge.symmetric_slippages
        if cm.description_type1 is letter_category
    ]
    assert len(reverse) == 1
    assert reverse[0].descriptor1 is forward[0].descriptor2
    assert reverse[0].descriptor2 is forward[0].descriptor1
    assert reverse[0].label is ctx.slipnet.nodes["plato-predecessor"]


def test_the_build_time_length_mapping_gets_no_symmetric_slippage(meta):
    """bridges.ss:1395-1411 sits *after* the symmetric loop, and adds no reverse."""
    engine = _engine(meta, "a", "aa", "b")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    a = ctx.workspace.initial_string.letters[0]
    aa = _spanning_group(ctx, ctx.workspace.modified_string, "sameness", "right")
    bridge = _built_bridge(ctx, a, aa)

    length = ctx.slipnet.nodes["plato-length"]
    assert bridge.cm_type_present(length)
    assert not any(
        cm.description_type1 is length for cm in bridge.symmetric_slippages
    )
    # The ObjCtgy slippage, added *before* the loop, does have its reverse.
    object_category = ctx.slipnet.nodes["plato-object-category"]
    reverse = [
        cm for cm in bridge.symmetric_slippages
        if cm.description_type1 is object_category
    ]
    assert len(reverse) == 1
    assert reverse[0].descriptor1 is ctx.slipnet.nodes["plato-group"]
    assert reverse[0].descriptor2 is ctx.slipnet.nodes["plato-letter"]


def test_bond_concept_mappings_stay_out_of_the_main_list(meta):
    """bridges.ss:1386-1393 — a separate list, so they never enter strength,
    incompatibility, support, or rule abstraction."""
    engine = _engine(meta, "aa", "bb", "cc")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    aa = _spanning_group(ctx, ctx.workspace.initial_string, "sameness", "right")
    bb = _spanning_group(ctx, ctx.workspace.modified_string, "sameness", "right")
    bridge = _built_bridge(ctx, aa, bb)

    assert bridge.bond_concept_mappings
    assert all(cm.bond_concept_mapping for cm in bridge.bond_concept_mappings)
    assert not any(cm.bond_concept_mapping for cm in bridge.concept_mappings)
    assert not any(
        cm.bond_concept_mapping for cm in bridge.get_non_symmetric_non_bond_slippages()
    )


# --- BR-8: the incompatibility refinements ---------------------------------


def test_a_spanning_bridge_is_not_incompatible_with_c_to_cc_in_abc_abcc(meta):
    """The reference's own example (bridges.ss:1555-1561).

    The spanning bridge carries ``Length: three=>three``; ``c -> cc`` carries
    ``Length: one=(succ)=>two``.  Those labels differ, so a raw cross-product of
    the two mapping lists calls them incompatible — and the spanning bridge has
    to break the very sub-bridge that justifies it.  Letter-category and length
    *slippages* are exempted from the comparison for exactly this reason.
    """
    engine = _engine(meta, "abc", "abcc", "xyz")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    node = ctx.slipnet.nodes

    abc = _spanning_group(ctx, ctx.workspace.initial_string, "successor", "right")
    c = ctx.workspace.initial_string.letters[2]
    cc = Group(
        string=ctx.workspace.modified_string,
        group_category=node["plato-samegrp"],
        bond_facet=node["plato-letter-category"],
        direction=None,
        objects=list(ctx.workspace.modified_string.letters[2:]),
        bonds=[],
    )
    cc.proposal_level = cc.BUILT
    ctx.workspace.modified_string.add_group(cc)
    abcc = Group(
        string=ctx.workspace.modified_string,
        group_category=node["plato-succgrp"],
        bond_facet=node["plato-letter-category"],
        direction=node["plato-right"],
        objects=list(ctx.workspace.modified_string.letters),
        bonds=[],
    )
    abcc.proposal_level = abcc.BUILT
    ctx.workspace.modified_string.add_group(abcc)

    spanning = Bridge(abc, abcc, BRIDGE_TOP, _length_cms(ctx, "three", "three"))
    local = Bridge(c, cc, BRIDGE_TOP, _length_cms(ctx, "one", "two"))

    assert _incompatible_bridges(spanning, local, "horizontal") is False
    assert _incompatible_bridges(local, spanning, "horizontal") is False


def _length_cms(ctx, name1: str, name2: str) -> list[ConceptMapping]:
    length = ctx.slipnet.nodes["plato-length"]
    d1 = ctx.slipnet.nodes[f"plato-{name1}"]
    d2 = ctx.slipnet.nodes[f"plato-{name2}"]
    return [
        ConceptMapping(
            length, d1, length, d2, label=ctx.slipnet.get_label(d1, d2)
        )
    ]


def test_a_direction_mapping_is_ignored_unless_the_bridge_encloses_the_other(meta):
    """bridges.ss:1562-1580 and 1650-1669.

    Two non-nested bridges each carrying ``DirCtgy: right=>right`` must not be
    made incompatible with a crosswise ``StrPosCtgy: lmost=(opp)=>rmost``: a
    sub-bridge's direction mapping has no standing to speak about the layout of
    the string above it.
    """
    engine = _engine(meta, "abc", "abd", "xyz")
    ctx = engine.ctx
    node = ctx.slipnet.nodes
    initial = ctx.workspace.initial_string.letters
    target = ctx.workspace.target_string.letters

    direction = node["plato-direction-category"]
    position = node["plato-string-position-category"]

    b1 = Bridge(
        initial[0],
        target[0],
        BRIDGE_TOP,
        [
            ConceptMapping(
                direction, node["plato-right"], direction, node["plato-right"],
                label=node["plato-identity"],
            )
        ],
    )
    b2 = Bridge(
        initial[2],
        target[2],
        BRIDGE_TOP,
        [
            ConceptMapping(
                position, node["plato-leftmost"], position, node["plato-rightmost"],
                label=node["plato-opposite"],
            )
        ],
    )
    assert _incompatible_bridges(b1, b2, "horizontal") is False


# --- BR-6: the builder's bond and enclosing-group fights -------------------


def test_a_crosswise_bridge_finds_the_directed_bond_it_contradicts(meta):
    """``get-incompatible-bond`` (bridges.ss:339-361), with both objects at edges.

    ``a`` (leftmost of ``abc``) mapped to ``z`` (rightmost of ``xyz``) carries
    ``StrPosCtgy: lmost=(opp)=>rmost``.  The bond running inward from each — a's
    right bond and z's left bond — are both directed *right*, so the implied
    ``DirCtgy: right=>right`` identity contradicts the opposite position
    mapping, and z's left bond is what has to give.

    The probe mapping is built from ``plato-direction-category`` regardless of
    what the bridge already carries; sourcing that node from an existing
    Direction mapping, as the dead version did, made the method vacuous in
    exactly this case — a crosswise bridge has no Direction mapping.
    """
    engine = _engine(meta, "abc", "abd", "xyz")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    node = ctx.slipnet.nodes

    bonds = {}
    for string in (ctx.workspace.initial_string, ctx.workspace.target_string):
        letters = string.letters
        for left, right in zip(letters, letters[1:]):
            bond = Bond(
                left, right, node["plato-successor"], node["plato-letter-category"],
                left.letter_category, right.letter_category, node["plato-right"],
            )
            bond.proposal_level = bond.BUILT
            string.add_bond(bond)
            bonds[(string.string_type, left.left_string_pos)] = bond

    a = ctx.workspace.initial_string.letters[0]
    z = ctx.workspace.target_string.letters[2]
    position = node["plato-string-position-category"]
    crosswise = Bridge(
        a, z, "vertical",
        [
            ConceptMapping(
                position, node["plato-leftmost"], position, node["plato-rightmost"],
                label=node["plato-opposite"], object1=a, object2=z,
            )
        ],
    )

    assert crosswise.get_incompatible_bond() is bonds[("target", 1)]


def test_the_bridge_builder_fights_that_bond_at_three_to_two(meta):
    """bridges.ss:1259-1276 and 1277-1291 — the bond at 3:2, its group at 1:1."""
    from server.engine.codelet_dsl.builtins import _get_incompatible_structures

    engine = _engine(meta, "abc", "abd", "xyz")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    node = ctx.slipnet.nodes

    target_bonds = []
    for string in (ctx.workspace.initial_string, ctx.workspace.target_string):
        letters = string.letters
        for left, right in zip(letters, letters[1:]):
            bond = Bond(
                left, right, node["plato-successor"], node["plato-letter-category"],
                left.letter_category, right.letter_category, node["plato-right"],
            )
            bond.proposal_level = bond.BUILT
            string.add_bond(bond)
            if string is ctx.workspace.target_string:
                target_bonds.append(bond)

    enclosing = Group(
        string=ctx.workspace.target_string,
        group_category=node["plato-succgrp"],
        bond_facet=node["plato-letter-category"],
        direction=node["plato-right"],
        objects=list(ctx.workspace.target_string.letters),
        bonds=list(target_bonds),
    )
    enclosing.proposal_level = enclosing.BUILT
    ctx.workspace.target_string.add_group(enclosing)
    for bond in target_bonds:
        bond.enclosing_group = enclosing

    a = ctx.workspace.initial_string.letters[0]
    z = ctx.workspace.target_string.letters[2]
    position = node["plato-string-position-category"]
    crosswise = Bridge(
        a, z, "vertical",
        [
            ConceptMapping(
                position, node["plato-leftmost"], position, node["plato-rightmost"],
                label=node["plato-opposite"], object1=a, object2=z,
            )
        ],
    )

    roster = _get_incompatible_structures(ctx, crosswise)
    weights = {id(opponent): (mine, theirs) for opponent, mine, theirs in roster}
    assert weights[id(target_bonds[1])] == (3.0, 2.0)
    assert weights[id(enclosing)] == (1.0, 1.0)


# --- CR-3: the rule build's answer codelet ---------------------------------


def test_building_a_rule_posts_the_answer_finder_at_urgency_91(meta):
    """rules.ss:489-491 — ``%extremely-high-urgency%``, immediately.

    The only other source of an answer attempt is the per-cycle bottom-up post,
    gated by ``(100-T)/100`` at urgency ``100-T``; waiting for it made every
    answer attempt later, rarer and less urgent than the reference's.
    """
    from server.engine.rules import RULE_TOP, Rule, RuleClause
    from server.engine.rules import CLAUSE_VERBATIM

    engine = _engine(meta, "abc", "abd", "xyz")
    ctx = engine.ctx
    interp, registry = _interpreter(meta)

    letters = [ctx.slipnet.nodes[f"plato-{ch}"] for ch in "abd"]
    rule = Rule(RULE_TOP, [RuleClause(clause_type=CLAUSE_VERBATIM, verbatim_letters=letters)])
    rule.set_verbatim_rule_information()
    rule.compute_quality(meta)
    rule.transcribe_to_english()

    ctx.coderack.clear()
    interp.execute(registry.get_compiled("rule-builder"), ctx, structure=rule)

    answer_codelets = [c for c in _posted(ctx) if c.codelet_type == "answer-finder"]
    assert len(answer_codelets) == 1
    assert answer_codelets[0].urgency == meta.get_urgency("extremely_high") == 91


def test_a_justify_mode_rule_build_posts_the_answer_justifier_instead(meta):
    """rules.ss:489-490 — the codelet type follows the mode."""
    from server.engine.rules import RULE_TOP, Rule, RuleClause
    from server.engine.rules import CLAUSE_VERBATIM

    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", answer="xyd", seed=42)
    ctx = runner.ctx
    assert ctx.justify_mode is True
    interp, registry = _interpreter(meta)

    letters = [ctx.slipnet.nodes[f"plato-{ch}"] for ch in "abd"]
    rule = Rule(RULE_TOP, [RuleClause(clause_type=CLAUSE_VERBATIM, verbatim_letters=letters)])
    rule.set_verbatim_rule_information()
    rule.compute_quality(meta)
    rule.transcribe_to_english()

    ctx.coderack.clear()
    interp.execute(registry.get_compiled("rule-builder"), ctx, structure=rule)

    posted = [c for c in _posted(ctx) if c.codelet_type == "answer-justifier"]
    assert len(posted) == 1
    assert posted[0].urgency == 91
    assert not [c for c in _posted(ctx) if c.codelet_type == "answer-finder"]


# --- BR-9: the duplicate-bridge merge --------------------------------------


def test_proposing_an_existing_bridge_gives_it_the_mappings_it_lacks(meta):
    """bridges.ss:1208-1232 — the incumbent accumulates, then the builder fizzles.

    This is how a bridge first drawn while only Letter-Category was warm later
    acquires its String-Position mapping without ever being rebuilt.
    """
    engine = _engine(meta, "abc", "abd", "xyz")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    node = ctx.slipnet.nodes
    a_initial = ctx.workspace.initial_string.letters[0]
    a_modified = ctx.workspace.modified_string.letters[0]

    letter_category = node["plato-letter-category"]
    sparse = Bridge(
        a_initial,
        a_modified,
        BRIDGE_TOP,
        [
            ConceptMapping(
                letter_category, node["plato-a"], letter_category, node["plato-a"],
                label=node["plato-identity"],
                object1=a_initial, object2=a_modified,
            )
        ],
    )
    assert build_structure(ctx, sparse) is True
    before = len(sparse.concept_mappings)

    from server.engine.bridges import propose_bridge

    richer = propose_bridge(
        BRIDGE_TOP, a_initial, False, a_modified, False, node["plato-identity"], ctx
    )
    assert len(richer.concept_mappings) > before
    assert build_structure(ctx, richer) is False, "a duplicate must not be built"

    assert len(sparse.concept_mappings) == len(richer.concept_mappings)
    assert sparse.cm_type_present(node["plato-string-position-category"])
    assert ctx.workspace.top_bridges.count(sparse) == 1
    assert richer not in ctx.workspace.top_bridges


# --- CR-4/CR-5: the deferred batch ------------------------------------------


def test_the_opening_population_is_four_codelets_per_object(meta):
    """run.ss:275-283 — ``2N`` iterations of two posts each.

    36 for ``abc/abd/xyz``, where Petacat used to post 18.
    """
    engine = _engine(meta, "abc", "abd", "xyz")
    ctx = engine.ctx
    posted = _posted(ctx)
    assert len(posted) == 4 * len(ctx.workspace.all_objects) == 36
    kinds = {c.codelet_type for c in posted}
    assert kinds == {"bottom-up-bond-scout", "bottom-up-bridge-scout"}


def test_a_deferred_batch_never_evicts_its_own_members(meta):
    """coderack.ss:389-408 — the overflow is evicted *before* any member lands."""
    from server.engine.coderack import Codelet, Coderack

    rack = Coderack(meta)
    rack.rng = RNG(1)
    for index in range(rack.max_size):
        rack.post(Codelet("breaker", 35, time_stamp=0), current_time=index, rng=RNG(1))
    assert rack.total_count == rack.max_size

    batch = [Codelet("rule-scout", 63, time_stamp=500) for _ in range(10)]
    rack.post_deferred(batch, current_time=500, rng=RNG(1))

    assert rack.total_count == rack.max_size
    survivors = [c for b in rack.bins for c in b.codelets]
    assert sum(1 for c in survivors if c.codelet_type == "rule-scout") == 10


def test_a_batch_at_or_over_capacity_flushes_the_rack(meta):
    """The first regime: drop the excess of the batch, then flush everything else."""
    from server.engine.coderack import Codelet, Coderack

    rack = Coderack(meta)
    rack.rng = RNG(1)
    for index in range(30):
        rack.post(Codelet("breaker", 35, time_stamp=0), current_time=index, rng=RNG(1))

    batch = [Codelet("rule-scout", 63, time_stamp=500) for _ in range(140)]
    rack.post_deferred(batch, current_time=500, rng=RNG(1))

    assert rack.total_count == rack.max_size
    survivors = [c for b in rack.bins for c in b.codelets]
    assert all(c.codelet_type == "rule-scout" for c in survivors)


# --- TH-1: the Themespace boost at build time ------------------------------


def test_building_a_bridge_boosts_its_themes_at_once(meta):
    """``bridges.ss:1348-1352`` — ``boost-themespace-activations`` runs immediately
    after ``build-bridge``, *in addition to* the per-cycle boost of every built bridge.

    Without it a bridge's themes lag up to fifteen codelets behind its construction,
    and a bridge built and broken inside one cycle leaves no thematic residue at all —
    so a dominance readout taken between cycles (rule building, answer descriptions,
    slippage importance) can differ near the 90-point margin.
    """
    engine = _engine(meta, "abc", "abd", "xyz")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    for cluster in ctx.themespace.clusters:
        for theme in cluster.themes:
            theme.activation = 0.0

    proposed = _proposed_bridge(
        ctx,
        ctx.workspace.initial_string.letters[0],
        ctx.workspace.modified_string.letters[0],
    )
    # The evaluator runs before the builder and is what gives a bridge its strength;
    # ``boost-themes`` (bridges.ss:297) reads exactly that value.
    proposed.update_strength()
    assert build_structure(ctx, proposed) is True
    bridge = proposed

    boosted = {
        (c.theme_type, c.dimension, t.relation)
        for c in ctx.themespace.clusters
        for t in c.themes
        if t.activation != 0.0
    }
    assert boosted, "the build must have reached the Themespace"
    # Every boosted theme is one this bridge's own descriptions imply, and all of them
    # belong to the bridge's theme type.
    relations = set(bridge.get_associated_thematic_relations())
    for theme_type, dimension, relation in boosted:
        assert theme_type == bridge.theme_type
        assert (dimension, relation) in relations


def test_the_build_time_boost_is_the_per_cycle_one_applied_early(meta):
    """The immediate boost and the cycle's boost are the same computation, so a bridge
    built and left alone accumulates two of them by the end of its first cycle."""
    engine = _engine(meta, "abc", "abd", "xyz")
    ctx = engine.ctx
    _all_active(ctx.slipnet)
    for cluster in ctx.themespace.clusters:
        for theme in cluster.themes:
            theme.activation = 0.0

    proposed = _proposed_bridge(
        ctx,
        ctx.workspace.initial_string.letters[0],
        ctx.workspace.modified_string.letters[0],
    )
    proposed.update_strength()
    assert build_structure(ctx, proposed) is True
    after_build = {
        id(t): t.activation
        for c in ctx.themespace.clusters
        for t in c.themes
        if t.activation != 0.0
    }

    engine._spread_activation_to_themespace()
    after_cycle = {
        id(t): t.activation
        for c in ctx.themespace.clusters
        for t in c.themes
        if t.activation != 0.0
    }

    assert set(after_build) == set(after_cycle)
    assert all(after_cycle[k] > after_build[k] for k in after_build)
