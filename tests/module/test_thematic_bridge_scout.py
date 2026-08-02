"""The thematic-bridge-scout inside an assembled engine (``themes.ss:750-890``).

Real Slipnet, real Workspace, real codelet interpreter; no database and no HTTP.
These exercise the three things the codelet could not do before T2.14 — scout a
*conjunction* of themes, propose a bridge against a reversed reading of a
spanning group, and drag an auxiliary slippage along on a coattail — plus the
description-proposing branch that makes a theme's dimension available in the
first place.
"""

from __future__ import annotations

import os

import pytest

from server.engine.bonds import Bond
from server.engine.bridges import BRIDGE_VERTICAL, Bridge
from server.engine.codelet_dsl.builtins import build_structure, get_builtins
from server.engine.codelet_dsl.interpreter import CodeletInterpreter, CodeletRegistry
from server.engine.concept_mappings import ConceptMapping
from server.engine.descriptions import Description
from server.engine.groups import Group
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.engine.runner import EngineRunner
from server.engine.themes import (
    THEME_VERTICAL_BRIDGE,
    look_for_auxiliary_slippages,
    pick_theme_conjunction,
)

# Every test here executes arithmetic the numeric substrate owns, so each one runs
# once per backend in the matrix. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def engine(meta):
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "cba", seed=42)
    return runner


# --- helpers ---------------------------------------------------------------


def _interpreter(meta):
    interp = CodeletInterpreter(builtins=get_builtins())
    return interp, CodeletRegistry.from_metadata(meta, interp)


class _AlwaysRNG(RNG):
    """An RNG that takes every chance offered.

    Used where the test is about what happens *after* a probabilistic branch —
    winning a fight, making an available slippage — so the branch is reachable
    without pinning the assertion to a seed.
    """

    def prob(self, p: float) -> bool:
        return p > 0.0


def _posted(ctx):
    """Everything currently on the coderack.

    Tests clear the rack before each run rather than diffing it, because the rack
    evicts when it is full and a diff would silently lose exactly the codelets a
    productive scout adds.
    """
    return [c for b in ctx.coderack.bins for c in b.codelets]


def _build_whole_string_group(ctx, string, category: str, direction: str):
    """Bond every adjacent pair and wrap the string in one group.

    Built directly rather than waited for, because the flip branch only exists
    between two *string-spanning groups* (themes.ss:981) and reaching that state
    by running codelets is a matter of luck rather than of the behaviour under
    test.
    """
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


def _clamp_vertical(ctx, pattern: dict[str, str]):
    """Impose a vertical theme pattern, the way §4.2's manual clamping does.

    "The clamping of theme activations in the Themespace automatically turns on
    thematic pressure" — everything not named is clamped to zero, which is the
    Scheme's ``ignore-themes`` (themes.ss:1188-1191), so the conjunction under
    test is the only thing speaking.
    """
    for cluster in ctx.themespace.get_clusters(THEME_VERTICAL_BRIDGE):
        wanted = pattern.get(cluster.dimension)
        for theme in cluster.themes:
            theme.clamp(100.0 if theme.relation == wanted else 0.0)
    ctx.themespace.thematic_pressure_on([THEME_VERTICAL_BRIDGE])


# --- the conjunction -------------------------------------------------------


def test_scout_pursues_a_conjunction_of_themes_across_dimensions(engine, meta):
    """A single codelet scouts for several themes at once.

    §4.1.2: "if the top themes Letter-Category: identity **and** String-Position:
    different are both active, thematic-scout codelets will tend to look for
    potential bridges ... having the same letter-category but different string
    positions."  Scheme: themes.ss:776-781 draws one theme per admitted *cluster*,
    so the result spans dimensions.  Scouting one theme per codelet cannot express
    that conjunction, and the crosswise mapping of §2.4.5 is exactly one.
    """
    ctx = engine.ctx
    _clamp_vertical(
        ctx,
        {
            "plato-letter-category": "identity",
            "plato-string-position-category": "diff",
        },
    )
    picked = pick_theme_conjunction(ctx.themespace, THEME_VERTICAL_BRIDGE, RNG(3))
    assert sorted((t.dimension, t.relation) for t in picked) == [
        ("plato-letter-category", "identity"),
        ("plato-string-position-category", "diff"),
    ]


def test_zeroed_clusters_contribute_nothing_to_the_conjunction(engine):
    """Scheme: themes.ss:777-780 — admission probability is ``(0/100)² = 0``.

    This is what makes a clamped pattern a *pattern*: the dimensions the user (or
    a jootser) did not name stay out of the conjunction entirely, rather than
    joining it at whatever activation they happened to have.
    """
    ctx = engine.ctx
    _clamp_vertical(ctx, {"plato-direction-category": "identity"})
    for _ in range(20):
        picked = pick_theme_conjunction(ctx.themespace, THEME_VERTICAL_BRIDGE, RNG(9))
        assert [t.dimension for t in picked] == ["plato-direction-category"]


# --- flipping a spanning group --------------------------------------------


def test_scout_proposes_a_bridge_against_a_reversed_spanning_group(engine, meta):
    """The scout can reinterpret a whole-string group rather than reject the pair.

    Scheme: ``conditions-for-bridge`` (themes.ss:996-1010) feeding ``propose-bridge``
    (bridges.ss:1085-1105).  ``abc`` as a right-going successor group and ``cba``
    as a left-going one cannot both satisfy Direction: identity as they stand —
    but they can if one is read backwards, and Length: identity survives the
    reversal, so the conjunction is satisfiable only via the flip.  Without this
    the themes simply rule the pairing out, and §2.4.5's crosswise mapping is
    unreachable.
    """
    ctx = engine.ctx
    _build_whole_string_group(ctx, ctx.workspace.initial_string, "successor", "right")
    _build_whole_string_group(ctx, ctx.workspace.target_string, "successor", "left")
    ctx.workspace.update_all_object_values()
    _clamp_vertical(
        ctx,
        {"plato-direction-category": "identity", "plato-length": "identity"},
    )

    interp, registry = _interpreter(meta)
    compiled = registry.get_compiled("thematic-bridge-scout")

    flipped_proposals = []
    for seed in range(200):
        ctx.rng = RNG(seed)
        ctx.coderack.clear()
        interp.execute(compiled, ctx)
        for codelet in _posted(ctx):
            structure = codelet.arguments.get("structure")
            if isinstance(structure, Bridge) and (
                structure.flipped_group1 or structure.flipped_group2
            ):
                flipped_proposals.append(structure)

    assert flipped_proposals, "no bridge was ever proposed against a flipped group"
    bridge = flipped_proposals[0]
    original = bridge.flipped_group1 or bridge.flipped_group2
    reversed_reading = (
        bridge.object1 if bridge.flipped_group1 else bridge.object2
    )
    assert reversed_reading is not original
    assert reversed_reading.direction is not original.direction
    assert reversed_reading.group_category is not original.group_category
    assert reversed_reading.objects == original.objects


def test_building_a_flipped_bridge_swaps_the_group_it_reinterprets(engine, meta):
    """The Workspace ends up holding the reading the bridge is about.

    Scheme: ``build-bridge``'s flip branches (bridges.ss:1322-1345) break the
    original group and its bonds and build the reversed ones in their place.  A
    bridge to a group no string contains would be a mapping onto nothing — and
    ``_premises_still_hold`` would otherwise refuse the build outright, since the
    reversed group was never added to the string.
    """
    ctx = engine.ctx
    original = _build_whole_string_group(
        ctx, ctx.workspace.target_string, "successor", "left"
    )
    initial_group = _build_whole_string_group(
        ctx, ctx.workspace.initial_string, "successor", "right"
    )
    ctx.workspace.update_all_object_values()

    from server.engine.bridges import propose_bridge

    # The bridge has to beat the group it would reinterpret (bridges.ss:1295-1312);
    # this test is about what happens once it has.
    ctx.rng = _AlwaysRNG(0)

    bridge = propose_bridge(
        BRIDGE_VERTICAL,
        initial_group,
        False,
        original,
        True,
        ctx.slipnet.nodes["plato-identity"],
    )
    assert bridge.flipped_group2 is original
    bridge.update_strength()

    assert build_structure(ctx, bridge) is True
    target_groups = ctx.workspace.target_string.groups
    assert original not in target_groups
    assert bridge.object2 in target_groups
    assert bridge.object2.direction is not original.direction
    # The reversed reading's own bonds are what now hold the string together.
    assert all(bond in ctx.workspace.target_string.bonds
               for bond in bridge.object2.group_bonds)
    assert not any(bond in ctx.workspace.target_string.bonds
                   for bond in original.group_bonds)
    # groups.ss:343 — the reversed reading keeps the original's identifier,
    # because it is the same group seen the other way round.
    assert bridge.object2.id == original.id


def test_flipping_a_sameness_group_is_a_no_op(engine):
    """Scheme: ``make-flipped-version`` returns ``self`` for a same-group
    (groups.ss:329-330).

    A sameness group has no direction, so there is no reading to reverse; a bridge
    "against the flipped version" of one is a bridge against the group itself,
    which is why ``propose_bridge`` records no original in that case.
    """
    ctx = engine.ctx
    node = ctx.slipnet.nodes
    letters = ctx.workspace.initial_string.letters
    group = Group(
        string=ctx.workspace.initial_string,
        group_category=node["plato-samegrp"],
        bond_facet=node["plato-letter-category"],
        direction=None,
        objects=list(letters),
        bonds=[],
    )
    assert group.make_flipped_version() is group

    from server.engine.bridges import propose_bridge

    bridge = propose_bridge(
        BRIDGE_VERTICAL, group, True, ctx.workspace.target_string.letters[0], False
    )
    assert bridge.flipped_group1 is None


# --- descriptions proposed for a dimension the object lacks ----------------


def test_scout_proposes_a_description_along_a_theme_it_cannot_yet_judge(engine, meta):
    """A missing description is a reason to look, not a reason to stop.

    Scheme: themes.ss:814-830.  §4.1.2: "situations tend to be perceived in terms
    of the features that one is actively paying attention to."  A theme naming
    Alphabetic-Position, which no letter carries at the start of a run, should
    make the scout propose that description on the object it chose.
    """
    ctx = engine.ctx
    _clamp_vertical(ctx, {"plato-alphabetic-position-category": "identity"})

    interp, registry = _interpreter(meta)
    compiled = registry.get_compiled("thematic-bridge-scout")

    proposed = []
    for seed in range(80):
        ctx.rng = RNG(seed)
        ctx.coderack.clear()
        interp.execute(compiled, ctx)
        for codelet in _posted(ctx):
            structure = codelet.arguments.get("structure")
            if isinstance(structure, Description):
                proposed.append(structure)

    assert proposed, "no description was proposed for the theme's dimension"
    assert all(
        d.description_type.name == "plato-alphabetic-position-category"
        for d in proposed
    )
    assert all(
        d.descriptor.name in ("plato-alphabetic-first", "plato-alphabetic-last")
        for d in proposed
    )


# --- auxiliary (coattail) slippages ----------------------------------------


def _vertical_position_slippage(ctx):
    """An a—z vertical bridge carrying leftmost => rightmost."""
    node = ctx.slipnet.nodes
    a = ctx.workspace.initial_string.letters[0]
    z = ctx.workspace.target_string.letters[-1]
    cm = ConceptMapping(
        node["plato-string-position-category"],
        node["plato-leftmost"],
        node["plato-string-position-category"],
        node["plato-rightmost"],
        label=node["plato-opposite"],
        object1=a,
        object2=z,
    )
    return Bridge(a, z, BRIDGE_VERTICAL, [cm]), a, z


def test_coattail_slippage_first_asks_for_the_description_it_needs(meta):
    """An object cannot carry a slippage in a dimension it has no description in.

    Scheme: themes.ss:933-948 builds the description and *fizzles* — the
    description was the useful work, and a later codelet can find the slippage
    once both ends can be spoken of.  Returning it, rather than building it here,
    is what lets the codelet body decide to stop.
    """
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=1)
    ctx = runner.ctx
    bridge, a, _z = _vertical_position_slippage(ctx)

    description = look_for_auxiliary_slippages(bridge, ctx.slipnet, _AlwaysRNG(1))
    assert isinstance(description, Description)
    assert description.object is a
    assert description.description_type.name == "plato-alphabetic-position-category"
    assert description.descriptor.name == "plato-alphabetic-first"
    assert len(bridge.concept_mappings) == 1  # nothing added yet


def test_coattail_slippage_is_added_once_both_ends_can_be_described(meta):
    """``leftmost => rightmost`` drags ``alphabetic-first => alphabetic-last``.

    Scheme: ``look-for-auxiliary-slippages`` (themes.ss:893-952).  §3.4.1's
    coattail slippage: a slippage on one dimension makes a same-labelled slippage
    on a *neighbouring* dimension available, with probability given by the label's
    degree of association.  This particular pair is the one §2.4.4 turns on — it
    is what lets ``abc -> abd; xyz -> ?`` be answered ``wyz``.
    """
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=1)
    ctx = runner.ctx
    node = ctx.slipnet.nodes
    bridge, a, z = _vertical_position_slippage(ctx)

    for obj, descriptor in (
        (a, node["plato-alphabetic-first"]),
        (z, node["plato-alphabetic-last"]),
    ):
        description = Description(
            obj, node["plato-alphabetic-position-category"], descriptor
        )
        description.proposal_level = description.BUILT
        obj.descriptions.append(description)

    assert look_for_auxiliary_slippages(bridge, ctx.slipnet, _AlwaysRNG(1)) is None
    added = [
        cm
        for cm in bridge.concept_mappings
        if cm.description_type1.name == "plato-alphabetic-position-category"
    ]
    assert len(added) == 1
    assert added[0].descriptor1.name == "plato-alphabetic-first"
    assert added[0].descriptor2.name == "plato-alphabetic-last"
    assert added[0].label.name == "plato-opposite"


def test_no_coattail_slippage_where_the_dimension_cannot_describe_the_objects(meta):
    """Scheme: themes.ss:914-915 — both ``possible-descriptor?`` tests must pass.

    ``b`` is neither the first nor the last letter of the alphabet, so no
    Alphabetic-Position slippage is available however strongly ``opposite`` is
    associated.  A coattail slippage is a real perceptual claim about the objects,
    not a formal consequence of the slippage that suggested it.
    """
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=1)
    ctx = runner.ctx
    node = ctx.slipnet.nodes
    b = ctx.workspace.initial_string.letters[1]
    y = ctx.workspace.target_string.letters[1]
    cm = ConceptMapping(
        node["plato-string-position-category"],
        node["plato-leftmost"],
        node["plato-string-position-category"],
        node["plato-rightmost"],
        label=node["plato-opposite"],
        object1=b,
        object2=y,
    )
    bridge = Bridge(b, y, BRIDGE_VERTICAL, [cm])

    assert look_for_auxiliary_slippages(bridge, ctx.slipnet, _AlwaysRNG(1)) is None
    assert len(bridge.concept_mappings) == 1
