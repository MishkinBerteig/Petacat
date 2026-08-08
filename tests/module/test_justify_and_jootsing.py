"""Justify mode's verdicts and the jootser's justify outcomes.

Real Slipnet, real Workspace, real codelet interpreter; no database and no HTTP.

Two things are under test here, and both were inverted before this phase.

``joots-from-justify-clamps`` (``jootsing.ss:189-235``) has exactly two outcomes and
both *produce* something: with no unjustified slippages it posts an answer-justifier
at extremely-high urgency, and otherwise it reports the answer carrying the slippages
it could not account for — "Settled for unjustified answer" (``trace.ss:435``).  The
jootser body dispatched on neither, so the first outcome did nothing at all and the
second terminated the run with no answer.

The answer-justifier (``justify.ss:94-130``) reports a justified answer only when the
Workspace materially supports the translated rule, and clamps otherwise.  The support
test read ``if translated_rule.supporting_bridges or True``, which declared every
working translation justified and left the clamp branch unreachable.
"""

from __future__ import annotations

import os

import pytest

from server.engine.bridges import BRIDGE_BOTTOM, BRIDGE_VERTICAL, Bridge
from server.engine.codelet_dsl.builtins import get_builtins
from server.engine.codelet_dsl.interpreter import CodeletInterpreter, CodeletRegistry
from server.engine.concept_mappings import ConceptMapping
from server.engine.jootsing import JootserResult, joots_from_justify_clamps
from server.engine.justify import attempt_justification
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.engine.rules import (
    CLAUSE_INTRINSIC,
    RULE_BOTTOM,
    RULE_TOP,
    Rule,
    RuleChange,
    RuleClause,
)
from server.engine.runner import EngineRunner
from server.engine.trace import ANSWER_FOUND, ClampEvent

# Every fixture here runs ``init_mcat``, which reaches the numeric seam.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
SEED = 42


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def engine(meta):
    """``abc -> abd; xyz -> wyz`` — four strings, so a justify run."""
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", "wyz", seed=SEED)
    return runner


class _NoCoattailRNG(RNG):
    """An RNG that declines every probabilistic offer.

    Translation drags an auxiliary slippage along on a *coattail* with a probability
    set by the original slippage's label activation (§3.4.1).  These tests are about
    what happens to a translation once it exists, so the coattail is switched off and
    the translated rule is exactly the slippages the test supplied.
    """

    def prob(self, p: float) -> bool:
        return False


# --- helpers ---------------------------------------------------------------


def _letter_rule(slipnet, rule_type: str, position: str, relation: str) -> Rule:
    """"Replace the letter-category of the <position> letter by its <relation>"."""
    nodes = slipnet.nodes
    return Rule(
        rule_type,
        [
            RuleClause(
                CLAUSE_INTRINSIC,
                object_description=(
                    nodes["plato-letter"],
                    nodes["plato-string-position-category"],
                    nodes[position],
                ),
                changes=[
                    RuleChange(
                        dimension=nodes["plato-letter-category"],
                        relation=nodes[relation],
                    )
                ],
            )
        ],
    )


def _concept_mapping(slipnet, dimension: str, from_name: str, to_name: str, label: str):
    nodes = slipnet.nodes
    return ConceptMapping(
        nodes[dimension],
        nodes[from_name],
        nodes[dimension],
        nodes[to_name],
        label=nodes[label],
        slipnet=slipnet,
    )


def _vertical_bridge(workspace, slipnet, concept_mappings) -> Bridge:
    """A built vertical bridge from ``c`` to ``x`` carrying the given slippages."""
    bridge = Bridge(
        object1=workspace.initial_string.letters[2],
        object2=workspace.target_string.letters[0],
        bridge_type=BRIDGE_VERTICAL,
        concept_mappings=list(concept_mappings),
    )
    bridge.proposal_level = bridge.BUILT
    workspace.add_bridge(bridge)
    return bridge


def _justify_clamp(top_rule: Rule, bottom_rule: Rule, codelet_count: int) -> ClampEvent:
    return ClampEvent(
        codelet_count=codelet_count,
        temperature=50.0,
        clamp_type="justify_clamp",
        rules=[top_rule, bottom_rule],
        progress_focus="workspace",
    )


def _interpreter(meta):
    interp = CodeletInterpreter(builtins=get_builtins())
    return interp, CodeletRegistry.from_metadata(meta, interp)


# ═══════════════════════════════════════════════════════════════════════
# The jootser's two justify outcomes
# ═══════════════════════════════════════════════════════════════════════


def test_a_fully_unifying_translation_asks_for_one_more_answer_justifier(engine):
    """``jootsing.ss:216-219`` — no unjustified slippages, so post an answer-justifier.

    The vertical mapping supplies both slippages the top rule needs, so the translated
    top rule *is* the bottom rule and there is nothing left to account for.
    """
    workspace, slipnet = engine.ctx.workspace, engine.ctx.slipnet
    top = _letter_rule(slipnet, RULE_TOP, "plato-rightmost", "plato-successor")
    bottom = _letter_rule(slipnet, RULE_BOTTOM, "plato-leftmost", "plato-predecessor")
    _vertical_bridge(
        workspace,
        slipnet,
        [
            _concept_mapping(
                slipnet,
                "plato-string-position-category",
                "plato-rightmost",
                "plato-leftmost",
                "plato-opposite",
            ),
            _concept_mapping(
                slipnet,
                "plato-bond-category",
                "plato-successor",
                "plato-predecessor",
                "plato-opposite",
            ),
        ],
    )

    result = joots_from_justify_clamps(
        [_justify_clamp(top, bottom, 500)],
        engine.ctx.trace,
        workspace,
        slipnet,
        engine.ctx.themespace,
        _NoCoattailRNG(SEED),
        None,
        500,
        memory=engine.ctx.memory,
    )

    assert result.action == "post_answer_justifier"
    assert result.give_up is False


def test_a_partly_unjustified_translation_settles_for_the_answer(engine):
    """``jootsing.ss:223-235`` — report the answer, carrying what it cannot justify.

    The vertical mapping supplies only the string-position slippage, so the translated
    top rule still says "successor" where the bottom rule says "predecessor".  That
    leftover is an unjustified slippage, and Metacat settles for the answer rather
    than halting.
    """
    workspace, slipnet = engine.ctx.workspace, engine.ctx.slipnet
    top = _letter_rule(slipnet, RULE_TOP, "plato-rightmost", "plato-successor")
    top.quality = 80.0
    bottom = _letter_rule(slipnet, RULE_BOTTOM, "plato-leftmost", "plato-predecessor")
    _vertical_bridge(
        workspace,
        slipnet,
        [
            _concept_mapping(
                slipnet,
                "plato-string-position-category",
                "plato-rightmost",
                "plato-leftmost",
                "plato-opposite",
            )
        ],
    )

    result = joots_from_justify_clamps(
        [_justify_clamp(top, bottom, 500)],
        engine.ctx.trace,
        workspace,
        slipnet,
        engine.ctx.themespace,
        _NoCoattailRNG(SEED),
        None,
        500,
        memory=engine.ctx.memory,
    )

    assert result.action == "report_unjustified_answer"
    assert result.give_up is False
    assert result.top_rule is top and result.bottom_rule is bottom
    assert len(result.unjustified_slippages) == 1
    # ``trace.ss:392-396`` — the top rule's quality, not the mean of both rules.
    assert result.answer_quality == 80.0


def test_an_answer_already_in_memory_stops_the_jootser_settling_for_it_again(engine):
    """``jootsing.ss:193-197`` — the memory guard the function had no trace of."""
    workspace, slipnet = engine.ctx.workspace, engine.ctx.slipnet
    top = _letter_rule(slipnet, RULE_TOP, "plato-rightmost", "plato-successor")
    bottom = _letter_rule(slipnet, RULE_BOTTOM, "plato-leftmost", "plato-predecessor")
    _vertical_bridge(
        workspace,
        slipnet,
        [
            _concept_mapping(
                slipnet,
                "plato-string-position-category",
                "plato-rightmost",
                "plato-leftmost",
                "plato-opposite",
            )
        ],
    )

    class _MemoryHoldingThisAnswer:
        def answer_present(self, problem, top_rule, bottom_rule):
            return True

    result = joots_from_justify_clamps(
        [_justify_clamp(top, bottom, 500)],
        engine.ctx.trace,
        workspace,
        slipnet,
        engine.ctx.themespace,
        _NoCoattailRNG(SEED),
        None,
        500,
        memory=_MemoryHoldingThisAnswer(),
    )

    assert result.action == ""
    assert result.pattern_detected is False


# ═══════════════════════════════════════════════════════════════════════
# The jootser codelet body dispatches on both outcomes
# ═══════════════════════════════════════════════════════════════════════


def test_the_jootser_body_posts_the_answer_justifier_it_is_asked_for(
    engine, meta, monkeypatch
):
    """The ``post_answer_justifier`` outcome matched no branch, so nothing happened."""
    import server.engine.jootsing as jootsing

    monkeypatch.setattr(
        jootsing,
        "attempt_jootsing",
        lambda *a, **k: JootserResult(
            pattern_detected=True, action="post_answer_justifier"
        ),
    )
    interp, registry = _interpreter(meta)
    before = sum(bin_.count for bin_ in engine.ctx.coderack.bins)

    interp.execute(registry.get_compiled("jootser"), engine.ctx)

    posted = [
        codelet
        for bin_ in engine.ctx.coderack.bins
        for codelet in bin_.codelets
        if codelet.codelet_type == "answer-justifier"
    ]
    assert sum(bin_.count for bin_ in engine.ctx.coderack.bins) == before + 1
    assert len(posted) == 1
    # ``%extremely-high-urgency%`` (``jootsing.ss:218``).
    assert posted[0].urgency == meta.get_urgency("extremely_high")


def test_the_jootser_body_reports_the_unjustified_answer_instead_of_halting(
    engine, meta, monkeypatch
):
    """The ``report_unjustified_answer`` outcome used to call ``give_up()``."""
    import server.engine.jootsing as jootsing

    slipnet = engine.ctx.slipnet
    top = _letter_rule(slipnet, RULE_TOP, "plato-rightmost", "plato-successor")
    top.quality = 80.0
    bottom = _letter_rule(slipnet, RULE_BOTTOM, "plato-leftmost", "plato-predecessor")
    slippage = _concept_mapping(
        slipnet, "plato-bond-category", "plato-successor", "plato-predecessor",
        "plato-opposite",
    )
    monkeypatch.setattr(
        jootsing,
        "attempt_jootsing",
        lambda *a, **k: JootserResult(
            pattern_detected=True,
            action="report_unjustified_answer",
            top_rule=top,
            bottom_rule=bottom,
            unjustified_slippages=[slippage],
            answer_quality=80.0,
        ),
    )
    interp, registry = _interpreter(meta)

    interp.execute(registry.get_compiled("jootser"), engine.ctx)

    assert getattr(engine.ctx, "_gave_up", False) is False
    assert getattr(engine.ctx, "_pending_answer", None) is not None
    answer_events = [
        event for event in engine.ctx.trace.events if event.event_type == ANSWER_FOUND
    ]
    assert len(answer_events) == 1
    assert answer_events[0].unjustified_slippages == [slippage]


def test_the_jootser_body_still_gives_up_on_a_recurring_rule_codelet_clamp(
    engine, meta, monkeypatch
):
    """The legitimate give-up path (``jootsing.ss:173-178``) is untouched."""
    import server.engine.jootsing as jootsing

    monkeypatch.setattr(
        jootsing,
        "attempt_jootsing",
        lambda *a, **k: JootserResult(
            pattern_detected=True, give_up=True, action="give_up"
        ),
    )
    interp, registry = _interpreter(meta)

    interp.execute(registry.get_compiled("jootser"), engine.ctx)

    assert getattr(engine.ctx, "_gave_up", False) is True


# ═══════════════════════════════════════════════════════════════════════
# The answer-justifier's support test
# ═══════════════════════════════════════════════════════════════════════


def _prepare_translation(engine):
    """A top rule that translates into a working bottom rule the Workspace lacks.

    Returns the chosen top rule.  The vertical mapping carries both slippages, so the
    translated rule is "replace the leftmost letter by its predecessor", which applied
    to ``xyz`` really does give ``wyz`` — the translation *works*.  Whether the
    Workspace supports it is the separate question these two tests separate.
    """
    workspace, slipnet = engine.ctx.workspace, engine.ctx.slipnet
    top = _letter_rule(slipnet, RULE_TOP, "plato-rightmost", "plato-successor")
    top.quality = 80.0
    top.proposal_level = top.BUILT
    workspace.add_rule(top)
    _vertical_bridge(
        workspace,
        slipnet,
        [
            _concept_mapping(
                slipnet,
                "plato-string-position-category",
                "plato-rightmost",
                "plato-leftmost",
                "plato-opposite",
            ),
            _concept_mapping(
                slipnet,
                "plato-bond-category",
                "plato-successor",
                "plato-predecessor",
                "plato-opposite",
            ),
        ],
    )
    return top


def test_a_working_translation_the_workspace_does_not_support_goes_to_the_clamp(
    engine, meta
):
    """``justify.ss:112-130`` — ``supported?`` fails, so clamp rather than report.

    The Workspace has no bottom bridges at all, so nothing in it relates ``xyz`` to
    ``wyz`` the way the translated rule says it does.  The ``or True`` guard reported
    this as a justified answer and left the clamp branch dead.
    """
    _prepare_translation(engine)
    assert engine.ctx.workspace.bottom_bridges == []

    result = attempt_justification(
        engine.ctx.workspace,
        meta,
        _NoCoattailRNG(SEED),
        trace=engine.ctx.trace,
        themespace=engine.ctx.themespace,
        slipnet=engine.ctx.slipnet,
        memory=engine.ctx.memory,
        codelet_count=300,
        temperature=engine.ctx.temperature.value,
        coderack=engine.ctx.coderack,
        temperature_control=engine.ctx.temperature,
    )

    assert result.justified is False
    assert result.action == "clamp_rules"
    assert result.clamp_event is not None
    assert result.clamp_event.clamp_type == "justify_clamp"


def test_a_translation_the_workspace_does_support_is_reported_as_justified(
    engine, meta
):
    """``justify.ss:112-121`` — with the bottom mapping in place, report the answer."""
    workspace, slipnet = engine.ctx.workspace, engine.ctx.slipnet
    top = _prepare_translation(engine)
    # Bridge every target letter to the answer letter standing in its place: this is
    # the Workspace saying, on its own account, that ``xyz`` becomes ``wyz`` the way
    # the translated rule claims.
    for target_letter, answer_letter in zip(
        workspace.target_string.letters, workspace.answer_string.letters
    ):
        bridge = Bridge(
            object1=target_letter,
            object2=answer_letter,
            bridge_type=BRIDGE_BOTTOM,
            concept_mappings=[],
        )
        bridge.proposal_level = bridge.BUILT
        workspace.add_bridge(bridge)

    result = attempt_justification(
        workspace,
        meta,
        _NoCoattailRNG(SEED),
        trace=engine.ctx.trace,
        themespace=engine.ctx.themespace,
        slipnet=slipnet,
        memory=engine.ctx.memory,
        codelet_count=300,
        temperature=engine.ctx.temperature.value,
        coderack=engine.ctx.coderack,
        temperature_control=engine.ctx.temperature,
    )

    assert result.justified is True
    assert result.top_rule is top
    # ``trace.ss:392-396`` — the top rule's quality alone.
    assert result.quality == 80.0


def test_the_translated_rule_gains_the_bridges_and_theme_pattern_it_implies(
    engine, meta
):
    """``rules.ss:164-189`` via ``make-translated-string`` (``justify.ss:107-109``).

    Without ``set_translated_rule_information`` a translated rule rests on nothing, so
    ``supported?`` is vacuously true of it whatever the Workspace looks like.
    """
    _prepare_translation(engine)

    attempt_justification(
        engine.ctx.workspace,
        meta,
        _NoCoattailRNG(SEED),
        trace=engine.ctx.trace,
        themespace=engine.ctx.themespace,
        slipnet=engine.ctx.slipnet,
        memory=engine.ctx.memory,
        codelet_count=300,
        temperature=engine.ctx.temperature.value,
        coderack=engine.ctx.coderack,
        temperature_control=engine.ctx.temperature,
    )

    translated = [r for r in engine.ctx.workspace.bottom_rules if r.translated]
    assert len(translated) == 1
    assert translated[0].supporting_bridges != []
    assert translated[0].theme_pattern is not None
    assert translated[0].theme_pattern[0] == "bottom_bridge"


def test_the_justify_clamp_carries_the_real_codelet_patterns(engine, meta):
    """``justify.ss:167-172`` — top-down *and* thematic, as urgency lists.

    They were stored as inert ``{"type": ...}`` markers and the coderack was never
    handed to ``activate``, so a justify clamp froze themes and concepts and left the
    Coderack running the search that had already stalled.
    """
    _prepare_translation(engine)

    result = attempt_justification(
        engine.ctx.workspace,
        meta,
        _NoCoattailRNG(SEED),
        trace=engine.ctx.trace,
        themespace=engine.ctx.themespace,
        slipnet=engine.ctx.slipnet,
        memory=engine.ctx.memory,
        codelet_count=300,
        temperature=engine.ctx.temperature.value,
        coderack=engine.ctx.coderack,
        temperature_control=engine.ctx.temperature,
    )

    assert result.clamp_event is not None
    patterns = result.clamp_event.clamped_codelet_patterns
    assert patterns == [
        meta.codelet_patterns["top-down-codelet-pattern"],
        meta.codelet_patterns["thematic-codelet-pattern"],
    ]
    # The clamp reached the Coderack: the thematic scout is pinned at 91.
    assert engine.ctx.coderack.clamped_urgencies.get("thematic-bridge-scout") == 91


def test_a_justify_clamp_is_denied_only_inside_the_real_grace_period(engine, meta):
    """``trace.ss:112-119`` — the grace period is measured against the codelet count.

    Called with the default ``codelet_count=0`` the comparison
    ``0 < last_unclamp_time + 100`` is true forever once any clamp has been undone, so
    every justify clamp after the first unclamp of a run was denied.
    """
    _prepare_translation(engine)
    engine.ctx.trace.last_unclamp_time = 100

    denied = attempt_justification(
        engine.ctx.workspace, meta, _NoCoattailRNG(SEED),
        trace=engine.ctx.trace, themespace=engine.ctx.themespace,
        slipnet=engine.ctx.slipnet, memory=engine.ctx.memory,
        codelet_count=150,
        temperature=engine.ctx.temperature.value,
        coderack=engine.ctx.coderack,
        temperature_control=engine.ctx.temperature,
    )
    assert denied.clamp_event is None

    granted = attempt_justification(
        engine.ctx.workspace, meta, _NoCoattailRNG(SEED),
        trace=engine.ctx.trace, themespace=engine.ctx.themespace,
        slipnet=engine.ctx.slipnet, memory=engine.ctx.memory,
        codelet_count=250,
        temperature=engine.ctx.temperature.value,
        coderack=engine.ctx.coderack,
        temperature_control=engine.ctx.temperature,
    )
    assert granted.clamp_event is not None


# --- the snag-jootser's per-entry inclusion weight (jootsing.ss:88-100) -------
#
# The weight of a theme-pattern entry is ``(% overlap) * (% average-description-depth)``,
# and the second factor was wrong in three separate ways at once, all of which pushed it
# *up* — so the negative theme pattern was built 75.8% of the time against Metacat's
# 43.8%, roughly doubling the rate at which runs reach the three snag-response clamps
# that a give-up is made of.


class _Depth:
    """A Slipnet node stand-in that carries only what the weight reads."""

    def __init__(self, name: str, conceptual_depth: float) -> None:
        self.name = name
        self.conceptual_depth = conceptual_depth


class _Desc:
    """A Description stand-in: the depth lives on the *descriptor*, as in descriptions.ss:68."""

    def __init__(self, description_type: _Depth, descriptor: _Depth) -> None:
        self.description_type = description_type
        self.descriptor = descriptor


def test_the_depth_of_a_description_is_its_descriptors_depth():
    """``(tell descriptor 'get-conceptual-depth)`` — ``descriptions.ss:68``.

    ``Description`` has neither ``conceptual_depth`` nor ``get_conceptual_depth``, so both
    ``hasattr`` probes missed and every matching description was scored at the hardcoded
    default of 50 regardless of what it actually described.  On ``abc->abd;xyz`` the two
    entries that matter describe the snagged ``z`` as ``plato-letter`` (depth 20) and
    ``plato-rightmost`` (depth 40); scoring both at 50 raised the chance that at least one
    entry survived the stochastic filter from 0.52 to 0.75.
    """
    from server.engine.jootsing import _average_description_depth

    objctgy = _Depth("plato-object-category", 90.0)
    descriptions = [
        _Desc(objctgy, _Depth("plato-letter", 20.0)),
        _Desc(objctgy, _Depth("plato-rightmost", 40.0)),
    ]
    depth = _average_description_depth(
        {"dimension": "plato-object-category"}, descriptions, None
    )
    assert depth == 30.0  # (20 + 40) / 2 -- from the descriptors, not from a constant


def test_a_dimension_no_description_matches_weighs_nothing():
    """``(average '())`` is ``0`` — ``utilities.ss:422-425``.

    Returning the *dimension node's own* depth instead gave unmatched entries a weight
    they have no right to: 80 for group-category, 70 for direction, 60 for length, where
    the reference gives every one of them 0 and drops it from the pattern outright.
    """
    from server.engine.jootsing import _average_description_depth

    class _Slipnet:
        nodes = {"plato-group-category": _Depth("plato-group-category", 80.0)}

    depth = _average_description_depth(
        {"dimension": "plato-group-category"},
        [_Desc(_Depth("plato-object-category", 90.0), _Depth("plato-letter", 20.0))],
        _Slipnet(),
    )
    assert depth == 0.0


def test_the_same_description_reached_twice_is_counted_once():
    """``remq-duplicates`` — ``jootsing.ss:86-88``.

    Snags overlap: two snags naming the same object contribute that object's descriptions
    twice, and an unweighted mean over the duplicated list is not the mean the reference
    takes.  ``remq`` is ``eq?``-based, so this is identity, not equality.
    """
    from server.engine.jootsing import _collect_snag_descriptions

    objctgy = _Depth("plato-object-category", 90.0)
    shared = _Desc(objctgy, _Depth("plato-letter", 20.0))
    other = _Desc(objctgy, _Depth("plato-group", 80.0))

    class _Obj:
        def __init__(self, descriptions):
            self.descriptions = descriptions

    # The same object reached through two snags, and a second object repeating one of
    # its descriptions -- which must survive at its *later* position.
    first = _Obj([shared, other])
    second = _Obj([shared])
    collected = _collect_snag_descriptions([first, second])

    assert [id(d) for d in collected] == [id(other), id(shared)]
