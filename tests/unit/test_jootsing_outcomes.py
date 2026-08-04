"""The jootser's outcomes: what counts as the same clamp, and when it gives up.

``jootsing.py`` is the self-watching core, so these stay at the unit layer: plain
engine events and hand-rolled doubles, no seed data and nothing driven.
"""

from __future__ import annotations

from server.engine.jootsing import (
    check_progress,
    get_clamp_jootsing_probability,
    get_most_recent_event_set,
)
from server.engine.rules import CLAUSE_INTRINSIC, Rule, RuleClause
from server.engine.trace import (
    BOND_BUILT,
    ClampEvent,
    SnagEvent,
    TemporalTrace,
    TraceEvent,
)


class _FakeMeta:
    """The three parameters ``jootsing.py`` reads, and nothing else."""

    codelet_patterns: dict = {}

    def get_param(self, name, default=None):
        return {
            "settling_period": 250,
            "max_clamp_period": 750,
            "grace_period": 100,
            "satisfactory_rule_quality": 80,
        }.get(name, default)


class _ScriptedRNG:
    """An RNG whose ``prob`` answers are written down in advance.

    Each branch under test is a separate probabilistic gate, and naming the answers
    in order is what makes "the jootser passed the jootsing gate but chose no pattern
    entries" a statable situation.
    """

    def __init__(self, answers):
        self._answers = list(answers)

    def prob(self, p):
        return self._answers.pop(0) if self._answers else False


class _FakeRule:
    """A rule-shaped object only in so far as ``rule_signature`` reads it."""

    def __init__(self, name):
        self.rule_type = "top"
        self.clauses = [RuleClause(CLAUSE_INTRINSIC, object_description=(name,))]
        self.is_verbatim_rule = False


class _FakeWorkspace:
    def __init__(self, top_qualities, bottom_qualities=()):
        self.top_rules = [_quality_rule(q) for q in top_qualities]
        self.bottom_rules = [_quality_rule(q) for q in bottom_qualities]

    def get_activity(self, codelet_count):
        return 0


def _quality_rule(quality):
    rule = Rule("top", [])
    rule.quality = quality
    return rule


def _justify_clamp(rules, codelet_count):
    return ClampEvent(
        codelet_count=codelet_count,
        temperature=50.0,
        clamp_type="justify_clamp",
        rules=list(rules),
        progress_focus="workspace",
    )


# --- JO-4: clamp equivalence is set equality over the rules -----------------


def test_two_justify_clamps_over_the_same_rule_pair_are_the_same_clamp():
    """``trace.ss:586-590`` compares the rules with ``sets-equal-pred?``.

    A justify clamp stores ``[chosen, other]`` and which of the two was chosen varies
    stochastically, so the same pair arrives in either order.  Comparing the two lists
    positionally split recurring clamps into separate equivalence sets, and the
    three-clamp jootsing threshold under-fired.
    """
    trace = TemporalTrace()
    first, second = _FakeRule("first"), _FakeRule("second")
    for count, rules in ((100, [first, second]), (200, [second, first]), (300, [first, second])):
        trace.record_event(_justify_clamp(rules, count))

    assert len(get_most_recent_event_set(trace, "clamp")) == 3


def test_justify_clamps_over_different_rules_are_different_clamps():
    trace = TemporalTrace()
    first, second, third = _FakeRule("a"), _FakeRule("b"), _FakeRule("c")
    trace.record_event(_justify_clamp([first, second], 100))
    trace.record_event(_justify_clamp([first, third], 200))

    assert len(get_most_recent_event_set(trace, "clamp")) == 1


# --- JO-3: the justify clamp-type factor ------------------------------------


def test_jootsing_from_a_justify_clamp_is_barred_while_the_clamp_is_producing_events():
    """``jootsing.ss:135-139`` — factor 0 unless the clamp is still the last event.

    A clamp that is provoking groups, slippages and rules is working, and the program
    has no business abandoning it.  The factor was hardcoded to 1, which removed the
    condition entirely.
    """
    trace = TemporalTrace()
    clamps = [_justify_clamp([_FakeRule("r")], count) for count in (100, 200, 300)]
    for clamp in clamps:
        trace.record_event(clamp)
    trace.record_event(TraceEvent(BOND_BUILT, codelet_count=350, temperature=50.0))

    assert get_clamp_jootsing_probability(clamps, 400, trace) == 0.0


def test_jootsing_from_a_justify_clamp_is_allowed_when_nothing_followed_it():
    trace = TemporalTrace()
    clamps = [_justify_clamp([_FakeRule("r")], count) for count in (100, 200, 300)]
    for clamp in clamps:
        trace.record_event(clamp)

    assert get_clamp_jootsing_probability(clamps, 400, trace) > 0.0


# --- JO-2: failing to choose pattern entries is a fizzle, not a give-up -----


def test_choosing_no_pattern_entries_fizzles_however_many_snags_there_were():
    """``jootsing.ss:110-112`` — "Couldn't make negative theme pattern. Fizzling."

    There was an added ``num_snags > 5`` branch that ended the run here instead: a
    termination condition with no counterpart in the reference, reached by a
    stochastic failure Metacat simply survives.
    """
    from server.engine.jootsing import attempt_jootsing

    trace = TemporalTrace()
    for count in range(6):
        trace.record_event(
            SnagEvent(
                codelet_count=100 * (count + 1),
                temperature=100.0,
                snag_theme_pattern={
                    "type": "vertical_bridge",
                    "entries": [
                        {"dimension": "plato-direction-category", "relation": "identity"}
                    ],
                },
            )
        )

    result = attempt_jootsing(
        trace,
        themespace=None,
        meta=_FakeMeta(),
        codelet_count=1000,
        # Pass the jootsing gate, then decline every pattern entry.
        rng=_ScriptedRNG([True, False, False, False]),
    )

    assert result.give_up is False
    assert result.pattern_detected is False


# --- JO-5: the progress-watcher's quiescent branch --------------------------


def test_decent_rules_in_a_quiet_workspace_post_nothing():
    """``jootsing.ss:337`` — "The rules seem to be of decent quality. Fizzling."

    Petacat posted an answer-finder here with probability 1, a channel to the answer
    stage the reference does not have and one that bypasses the answer-finder's own
    mapping-strength gate.
    """
    result = check_progress(
        _FakeWorkspace(top_qualities=[95.0]),
        TemporalTrace(),
        codelet_count=500,
        meta=_FakeMeta(),
    )

    assert result.action not in ("post_answer_finder", "post_answer_justifier")


def test_poor_rules_in_a_quiet_workspace_still_reach_the_clamp_attempt():
    """The other side of the same branch: poor rules do provoke a rule-codelet clamp."""
    result = check_progress(
        _FakeWorkspace(top_qualities=[10.0]),
        TemporalTrace(),
        codelet_count=500,
        meta=_FakeMeta(),
        rng=_ScriptedRNG([True]),
    )

    assert result.action == "clamp_rule_pattern"
