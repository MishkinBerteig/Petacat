"""The vertical theme-pattern an answer description is indexed by.

``abstract-answer-description-theme-pattern`` (``answers.ss:155-220``) is not a
readout of the Themespace: it is assembled dimension by dimension, over five
permitted dimensions, from the Temporal Trace's own record of the slippages and
whole-string groups that mattered — with the Themespace consulted for exactly one
entry.  That pattern is the index an answer is stored, reminded and compared under
(``memory.ss:431``), so the recipe is the mechanism.

Real Slipnet, real Workspace, real Trace; no database and no HTTP.  The patterns
below are worked out by hand from the five-branch ``cond`` and then checked against
the port.
"""

from __future__ import annotations

import os

import pytest

from server.engine.answers import _distil_vertical_pattern, create_answer_description
from server.engine.bridges import BRIDGE_VERTICAL, Bridge
from server.engine.concept_mappings import ConceptMapping
from server.engine.groups import Group
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.engine.trace import CONCEPT_MAPPING_BUILT, GROUP_BUILT, TraceEvent

# Every test here reaches the numeric seam through ``init_mcat``'s first
# ``update-workspace-values``, so each runs once per backend. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

ALPH_POS = "plato-alphabetic-position-category"
STRING_POSITION = "plato-string-position-category"
DIRECTION = "plato-direction-category"
GROUP_CATEGORY = "plato-group-category"
BOND_FACET = "plato-bond-facet"

ALLOWED = (ALPH_POS, STRING_POSITION, DIRECTION, GROUP_CATEGORY, BOND_FACET)


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def _engine(meta, initial="abc", modified="abd", target="xyz"):
    runner = EngineRunner(meta)
    runner.init_mcat(initial, modified, target, seed=42)
    return runner.ctx


def _spanning_group(ctx, string, bond_category, direction):
    """A whole-string group over *string*, built into it.

    Assembled directly rather than scouted, because these tests are about what the
    answer description makes of a Workspace state, not about how the state arose.
    """
    nodes = ctx.slipnet.nodes
    group = Group(
        string=string,
        group_category=nodes[bond_category],
        bond_facet=nodes["plato-letter-category"],
        direction=nodes[direction] if direction else None,
        objects=list(string.letters),
        bonds=[],
    )
    group.proposal_level = Group.BUILT
    string.add_group(group)
    return group


def _vertical_bridge(ctx, object1, object2, mappings):
    """A built vertical bridge carrying exactly *mappings*, as ``(dimension, d1, d2)``."""
    nodes = ctx.slipnet.nodes
    bridge = Bridge(
        object1,
        object2,
        BRIDGE_VERTICAL,
        [
            ConceptMapping(
                nodes[dimension],
                nodes[descriptor1],
                nodes[dimension],
                nodes[descriptor2],
                label=ctx.slipnet.get_label(nodes[descriptor1], nodes[descriptor2]),
                object1=object1,
                object2=object2,
            )
            for dimension, descriptor1, descriptor2 in mappings
        ],
    )
    bridge.proposal_level = Bridge.BUILT
    ctx.workspace.add_bridge(bridge)
    object1.vertical_bridge = bridge
    object2.vertical_bridge = bridge
    return bridge


def _slippage_event(ctx, bridge, cm):
    event = TraceEvent(
        event_type=CONCEPT_MAPPING_BUILT,
        codelet_count=ctx.codelet_count,
        temperature=ctx.temperature.value,
        structures=[bridge],
        concept_mapping=cm,
        bridge=bridge,
    )
    ctx.trace.record_event(event)
    return event


def _group_event(ctx, group):
    event = TraceEvent(
        event_type=GROUP_BUILT,
        codelet_count=ctx.codelet_count,
        temperature=ctx.temperature.value,
        structures=[group],
        group=group,
    )
    ctx.trace.record_event(event)
    return event


# ---------------------------------------------------------------------------
# The two worked patterns
# ---------------------------------------------------------------------------


def test_the_crosswise_xyz_pattern_is_built_from_its_slippage_events(meta):
    """The ``xyz -> wyz`` reading: leftmost <=> rightmost, first <=> last, right <=> left.

    Hand-worked over the five dimensions of ``answers.ss:213-218``:

    * **AlphPos** — a slippage event says ``first => last``, so branch 1 takes it as
      ``opposite``.
    * **StringPos** — also a slippage event (``leftmost => rightmost``), branch 1
      again, ``opposite``.  Branch 2 never runs.
    * **Direction** — a slippage event, ``opposite``.
    * **GroupCtgy** — no slippage event, and the spanning vertical bridge maps
      ``succgrp => predgrp``, which is *not* an identity, so branch 4 refuses and the
      dimension is **absent**.
    * **BondFacet** — branch 3 drops it.
    """
    ctx = _engine(meta)
    initial = _spanning_group(ctx, ctx.workspace.initial_string, "plato-succgrp", "plato-right")
    target = _spanning_group(ctx, ctx.workspace.target_string, "plato-predgrp", "plato-left")
    bridge = _vertical_bridge(
        ctx,
        initial,
        target,
        [
            (GROUP_CATEGORY, "plato-succgrp", "plato-predgrp"),
            (DIRECTION, "plato-right", "plato-left"),
        ],
    )
    _group_event(ctx, initial)
    _group_event(ctx, target)

    letter_bridge = _vertical_bridge(
        ctx,
        ctx.workspace.initial_string.letters[2],
        ctx.workspace.target_string.letters[0],
        [
            (STRING_POSITION, "plato-rightmost", "plato-leftmost"),
            (ALPH_POS, "plato-alphabetic-last", "plato-alphabetic-first"),
        ],
    )
    for cm in letter_bridge.concept_mappings:
        _slippage_event(ctx, letter_bridge, cm)
    _slippage_event(ctx, bridge, bridge.concept_mappings[1])

    pattern = _distil_vertical_pattern({}, ctx.workspace, ctx.trace, ALLOWED)

    assert pattern == {
        ALPH_POS: "opposite",
        STRING_POSITION: "opposite",
        DIRECTION: "opposite",
    }


def test_the_plain_abd_pattern_comes_from_the_whole_string_identity_mappings(meta):
    """The literal ``xyz -> xyd`` reading: nothing slipped.

    * No slippage events at all, so branch 1 never fires.
    * **StringPos** — branch 2, and with no Direction entry and no dominant
      String-Position theme it falls to ``identity``: "Always include a string-position
      theme no matter what" (``answers.ss:202``).
    * **Direction** and **GroupCtgy** — branch 4: the spanning vertical bridge between
      the two whole-string groups maps each to itself, so both enter as ``identity``.
    * **AlphPos** — the spanning bridge carries no alphabetic-position mapping, so
      branch 4 refuses and it is absent.
    * **BondFacet** — branch 3 drops it.
    """
    ctx = _engine(meta)
    initial = _spanning_group(ctx, ctx.workspace.initial_string, "plato-succgrp", "plato-right")
    target = _spanning_group(ctx, ctx.workspace.target_string, "plato-succgrp", "plato-right")
    _vertical_bridge(
        ctx,
        initial,
        target,
        [
            (GROUP_CATEGORY, "plato-succgrp", "plato-succgrp"),
            (DIRECTION, "plato-right", "plato-right"),
        ],
    )
    _group_event(ctx, initial)
    _group_event(ctx, target)

    pattern = _distil_vertical_pattern({}, ctx.workspace, ctx.trace, ALLOWED)

    assert pattern == {
        STRING_POSITION: "identity",
        DIRECTION: "identity",
        GROUP_CATEGORY: "identity",
    }


# ---------------------------------------------------------------------------
# The individual branches
# ---------------------------------------------------------------------------


def test_string_position_copies_the_direction_relation_when_one_exists(meta):
    """``answers.ss:190-195`` — "StringPos and Direction themes should agree if
    possible", so a Direction slippage event supplies the String-Position entry."""
    ctx = _engine(meta)
    initial = _spanning_group(ctx, ctx.workspace.initial_string, "plato-succgrp", "plato-right")
    target = _spanning_group(ctx, ctx.workspace.target_string, "plato-predgrp", "plato-left")
    bridge = _vertical_bridge(
        ctx, initial, target, [(DIRECTION, "plato-right", "plato-left")]
    )
    _slippage_event(ctx, bridge, bridge.concept_mappings[0])

    pattern = _distil_vertical_pattern({}, ctx.workspace, ctx.trace, ALLOWED)

    assert pattern[DIRECTION] == "opposite"
    assert pattern[STRING_POSITION] == "opposite"


def test_string_position_falls_back_to_the_dominant_theme(meta):
    """``answers.ss:196-201`` — with no Direction entry, the *dominant* String-Position
    theme is the one place the Themespace enters this pattern at all."""
    ctx = _engine(meta)

    pattern = _distil_vertical_pattern(
        {STRING_POSITION: "opposite", DIRECTION: "opposite", GROUP_CATEGORY: "diff"},
        ctx.workspace,
        ctx.trace,
        ALLOWED,
    )

    # Only String-Position is read off the dominant pattern; the two other dominant
    # themes have no supporting whole-string identity mapping and do not enter.
    assert pattern == {STRING_POSITION: "opposite"}


def test_a_dominant_theme_with_no_workspace_support_does_not_enter(meta):
    """The seeding this replaces: ``pattern = dict(dominant)`` let every dominant
    vertical theme into the index whether or not anything in the Workspace backed it.
    ``answers.ss:206-210`` admits a non-String-Position dimension only through a
    whole-string identity mapping."""
    ctx = _engine(meta)

    pattern = _distil_vertical_pattern(
        {DIRECTION: "identity", GROUP_CATEGORY: "identity", BOND_FACET: "diff"},
        ctx.workspace,
        ctx.trace,
        ALLOWED,
    )

    assert pattern == {STRING_POSITION: "identity"}


def test_bond_facet_identity_is_excluded_but_a_bond_facet_slippage_is_not(meta):
    """``answers.ss:204-205`` drops Bond-Facet — but the branch sits *after* the
    slippage-event branch, so a Bond-Facet slippage the program actually made still
    reaches the pattern.  That is the theme §4.7.2's whole eqe/abbbc analysis turns
    on."""
    ctx = _engine(meta)
    initial = _spanning_group(ctx, ctx.workspace.initial_string, "plato-succgrp", "plato-right")
    target = _spanning_group(ctx, ctx.workspace.target_string, "plato-succgrp", "plato-right")
    bridge = _vertical_bridge(
        ctx, initial, target,
        [(BOND_FACET, "plato-letter-category", "plato-length")],
    )
    _slippage_event(ctx, bridge, bridge.concept_mappings[0])

    with_slippage = _distil_vertical_pattern({}, ctx.workspace, ctx.trace, ALLOWED)
    assert with_slippage[BOND_FACET] == "diff"

    # The same Workspace with the event removed: nothing supplies Bond-Facet, and
    # branch 3 refuses to invent an identity for it.
    ctx.trace.events.clear()
    assert BOND_FACET not in _distil_vertical_pattern(
        {BOND_FACET: "identity"}, ctx.workspace, ctx.trace, ALLOWED
    )


def test_a_rebuilt_bridge_keeps_its_slippage(meta):
    """``relevant-for-answer-description?`` (``trace.ss:783-785``) asks
    ``bridge-present?`` (``workspace.ss:266``), which is *equivalence* — same bridge
    type, equivalent objects — not object identity.

    A bridge broken and rebuilt is how a reading gets confirmed, and an identity test
    threw the slippage of every such bridge out of the answer's index.
    """
    ctx = _engine(meta)
    left_initial = ctx.workspace.initial_string.letters[0]
    right_target = ctx.workspace.target_string.letters[2]
    original = _vertical_bridge(
        ctx, left_initial, right_target,
        [(STRING_POSITION, "plato-leftmost", "plato-rightmost")],
    )
    _slippage_event(ctx, original, original.concept_mappings[0])

    # Break it and build an equivalent one, as the Workspace routinely does.
    ctx.workspace.vertical_bridges.remove(original)
    _vertical_bridge(
        ctx, left_initial, right_target,
        [(STRING_POSITION, "plato-leftmost", "plato-rightmost")],
    )

    pattern = _distil_vertical_pattern({}, ctx.workspace, ctx.trace, ALLOWED)
    assert pattern[STRING_POSITION] == "opposite"


def test_a_slippage_whose_bridge_is_gone_does_not_enter(meta):
    """The converse: a slippage that has since been broken did not contribute to this
    answer, and ``currently-present?`` (``trace.ss:789-790``) is what keeps it out."""
    ctx = _engine(meta)
    left_initial = ctx.workspace.initial_string.letters[0]
    right_target = ctx.workspace.target_string.letters[2]
    bridge = _vertical_bridge(
        ctx, left_initial, right_target,
        [(STRING_POSITION, "plato-leftmost", "plato-rightmost")],
    )
    _slippage_event(ctx, bridge, bridge.concept_mappings[0])
    ctx.workspace.vertical_bridges.remove(bridge)

    pattern = _distil_vertical_pattern({}, ctx.workspace, ctx.trace, ALLOWED)
    # Branch 1 finds nothing, so String-Position falls all the way to identity.
    assert pattern == {STRING_POSITION: "identity"}


def test_an_event_on_a_horizontal_bridge_is_ignored(meta):
    """``relevant-for-answer-description?`` requires ``(eq? bridge-type 'vertical)``
    (``trace.ss:784``): the answer's *vertical* pattern is about how the two rows
    correspond, not about either row's own transformation."""
    from server.engine.bridges import BRIDGE_TOP

    ctx = _engine(meta)
    nodes = ctx.slipnet.nodes
    object1 = ctx.workspace.initial_string.letters[0]
    object2 = ctx.workspace.modified_string.letters[2]
    bridge = Bridge(
        object1,
        object2,
        BRIDGE_TOP,
        [
            ConceptMapping(
                nodes[STRING_POSITION],
                nodes["plato-leftmost"],
                nodes[STRING_POSITION],
                nodes["plato-rightmost"],
                label=nodes["plato-opposite"],
                object1=object1,
                object2=object2,
            )
        ],
    )
    bridge.proposal_level = Bridge.BUILT
    ctx.workspace.add_bridge(bridge)
    _slippage_event(ctx, bridge, bridge.concept_mappings[0])

    pattern = _distil_vertical_pattern({}, ctx.workspace, ctx.trace, ALLOWED)
    assert pattern == {STRING_POSITION: "identity"}


def test_the_description_is_indexed_by_the_distilled_pattern(meta):
    """``memory.ss:431`` hands ``abstract-answer-description-theme-pattern``'s result
    straight to ``make-answer-description``, so the stored ``themes`` — what every
    reminding distance is computed over — is this pattern and not the Themespace's."""
    ctx = _engine(meta)
    initial = _spanning_group(ctx, ctx.workspace.initial_string, "plato-succgrp", "plato-right")
    target = _spanning_group(ctx, ctx.workspace.target_string, "plato-succgrp", "plato-right")
    _vertical_bridge(
        ctx, initial, target,
        [(GROUP_CATEGORY, "plato-succgrp", "plato-succgrp")],
    )
    _group_event(ctx, initial)
    _group_event(ctx, target)

    description = create_answer_description(
        ctx.workspace,
        None,
        None,
        quality=70.0,
        temperature=30.0,
        themes={"vertical_bridge": {DIRECTION: "opposite"}},
        trace=ctx.trace,
        meta=meta,
    )

    assert description.themes == {
        STRING_POSITION: "identity",
        GROUP_CATEGORY: "identity",
    }
    assert description.vertical_themes == description.themes


# ---------------------------------------------------------------------------
# The unjustified pattern  (answers.ss:239-264)
# ---------------------------------------------------------------------------


def _slippage(ctx, dimension, descriptor1, descriptor2):
    nodes = ctx.slipnet.nodes
    return ConceptMapping(
        nodes[dimension],
        nodes[descriptor1],
        nodes[dimension],
        nodes[descriptor2],
        label=ctx.slipnet.get_label(nodes[descriptor1], nodes[descriptor2]),
    )


def test_an_unjustified_bond_facet_brings_group_and_direction_with_it(meta):
    """``answers.ss:245-264``: "Since a BondFacet theme implies the existence of
    groups, add accompanying (unjustified) group-category and direction themes".

    They default to ``identity`` because the Bond-Facet slippage says nothing about
    which.  The augmented pattern is what ``all_themes`` compares and what the
    justification component of the reminding distance counts, so leaving it out
    understated how much two Bond-Facet answers have in common.
    """
    from server.engine.answers import _unjustified_themes

    ctx = _engine(meta)
    themes = _unjustified_themes(
        [_slippage(ctx, BOND_FACET, "plato-letter-category", "plato-length")]
    )

    assert themes == {
        GROUP_CATEGORY: "identity",
        DIRECTION: "identity",
        BOND_FACET: "diff",
    }


def test_the_augmentation_does_not_overwrite_a_slippage_that_is_already_there(meta):
    """``answers.ss:253-260`` takes the *existing* entry when the pattern has one."""
    from server.engine.answers import _unjustified_themes

    ctx = _engine(meta)
    themes = _unjustified_themes(
        [
            _slippage(ctx, BOND_FACET, "plato-letter-category", "plato-length"),
            _slippage(ctx, DIRECTION, "plato-right", "plato-left"),
        ]
    )

    assert themes[DIRECTION] == "opposite"
    assert themes[GROUP_CATEGORY] == "identity"


def test_without_a_bond_facet_slippage_nothing_is_added(meta):
    """``answers.ss:245`` gates the whole augmentation on a Bond-Facet entry."""
    from server.engine.answers import _unjustified_themes

    ctx = _engine(meta)
    themes = _unjustified_themes(
        [_slippage(ctx, STRING_POSITION, "plato-leftmost", "plato-rightmost")]
    )

    assert themes == {STRING_POSITION: "opposite"}
