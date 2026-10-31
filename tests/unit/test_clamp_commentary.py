"""A clamp says so when it is activated and when it is undone (``trace.ss:129-170, 592-612``).

The strings are Metacat's, as logged from Metacat 1.2 by the commentary comparison
(``tests/lockstep``): "I'll just have to try a little harder...", "Looks like I made a
lot of headway in coming up with new ideas." and the technical "Unclamping patterns.
Progress achieved by snag-response clamp = 85."
"""

from server.engine.commentary import CommentaryLog, emit_comparing_answers
from server.engine.concept_mappings import slippage_english_name
from server.engine.trace import (
    ClampEvent,
    RULE_BUILT,
    TemporalTrace,
    TraceEvent,
)


import os as _os

from server.engine.metadata import MetadataProvider as _MetadataProvider

_META = _MetadataProvider.from_seed_data(
    _os.path.join(_os.path.dirname(__file__), "..", "..", "seed_data")
)
#: The Metacat Standard Configuration's phrase-templates, from a provider.
T = _META.commentary_templates


def _trace() -> tuple[TemporalTrace, CommentaryLog]:
    trace = TemporalTrace()
    log = CommentaryLog()
    trace.commentary = log
    trace.commentary_templates = T
    return trace, log


def _clamp(trace: TemporalTrace, clamp_type: str, focus: str = "rule") -> ClampEvent:
    event = ClampEvent(100, 50.0, clamp_type=clamp_type, progress_focus=focus)
    trace.add_clamp_event(event)
    event.activate(trace, None, None, None, None)
    return event


def _strength_event(strength: float, at: int = 150) -> TraceEvent:
    event = TraceEvent(RULE_BUILT, at, 40.0)
    event.get_strength = lambda: strength  # type: ignore[method-assign]
    return event


def _lines(log: CommentaryLog) -> list[tuple[str, str]]:
    return [(p.eliza_text, p.technical_text) for p in log.get_paragraphs()]


def test_every_clamp_type_announces_itself():
    trace, log = _trace()
    _clamp(trace, "rule_codelet_clamp")
    assert _lines(log)[-1] == (
        "I'll just have to try a little harder...",
        "Clamping rule-codelet pattern...",
    )
    trace.undo_last_clamp(None, None, 200)

    _clamp(trace, "snag_response_clamp")
    assert _lines(log)[-1][1] == "Clamping negative theme pattern..."
    trace.undo_last_clamp(None, None, 300)

    # The third clamp event in the Trace: a justify clamp says "another" once there
    # is more than one clamp event of any type (``trace.ss:603``).
    _clamp(trace, "justify_clamp")
    assert _lines(log)[-1] == ("Aha!  I have another idea...", "Clamping theme patterns...")


def test_manual_clamp_counts_only_manual_clamps_for_another():
    trace, log = _trace()
    _clamp(trace, "rule_codelet_clamp")
    trace.undo_last_clamp(None, None, 200)
    _clamp(trace, "manual_clamp")
    assert _lines(log)[-1][0] == (
        "Thank you for that interesting suggestion!  Let me think about it..."
    )
    trace.undo_last_clamp(None, None, 300)
    _clamp(trace, "manual_clamp")
    assert _lines(log)[-1][0].startswith("Thank you for another interesting suggestion!")


def test_undoing_a_clamp_reports_the_progress_it_achieved():
    trace, log = _trace()
    _clamp(trace, "snag_response_clamp", focus="workspace")
    trace.record_event(_strength_event(85))

    progress = trace.undo_last_clamp(None, None, 400)

    assert progress == 85
    assert _lines(log)[-1] == (
        "Looks like I made a lot of headway in coming up with new ideas.",
        "Unclamping patterns.  Progress achieved by snag-response clamp = 85.",
    )


def test_undoing_with_no_clamp_in_force_says_nothing():
    trace, log = _trace()
    assert trace.undo_last_clamp(None, None, 400) == 0.0
    assert log.count == 0


def test_a_bare_trace_is_silent():
    trace = TemporalTrace()
    event = ClampEvent(100, 50.0, clamp_type="rule_codelet_clamp")
    trace.add_clamp_event(event)
    event.activate(trace, None, None, None, None)
    trace.undo_last_clamp(None, None, 200)


def test_a_slippage_is_named_from_its_two_descriptors():
    class Node:
        def __init__(self, name):
            self.name = name

    assert (
        slippage_english_name(
            {"descriptor1": Node("plato-letter-category"), "descriptor2": Node("plato-length")}
        )
        == "letter-category <=> length"
    )


def test_comparing_answers_starts_with_lets_see():
    log = CommentaryLog()
    emit_comparing_answers(log, 0, T)
    assert _lines(log) == [("Let's see...", "Comparing answers...")]


# ---- remindings (memory.ss:99-104, 212-229) ----


def _stored(memory, answer: str):
    from server.engine.memory import AnswerDescription

    desc = AnswerDescription(
        problem=("abc", "abd", "mrrjjj", answer), top_rule_description="",
        bottom_rule_description="", top_rule_quality=0.0, bottom_rule_quality=0.0,
        quality=50.0, temperature=10.0, themes={}, unjustified_slippages=[],
    )
    memory.store(desc)
    return desc


def test_remindings_come_newest_first_with_a_whole_number_strength(monkeypatch):
    from server.engine.memory import EpisodicMemory

    memory = EpisodicMemory()
    oldest, middle, newest = (_stored(memory, a) for a in ("mrrjjk", "mrrkkk", "mrrjjjj"))
    # distance / threshold: 0.7 and 3.1 of 5 -> 100- (100* 0.14) = 86 and 100- 62 = 38.
    distances = {id(oldest): 0.7, id(middle): 3.1}
    monkeypatch.setattr(memory, "distance", lambda new, past, meta=None: distances[id(past)])

    reminded = memory.find_remindings(newest, 5, meta=_META)

    assert [r.problem[3] for r in reminded] == ["mrrkkk", "mrrjjk"]
    assert [r.activation for r in reminded] == [38, 86]
    assert all(isinstance(r.activation, int) for r in reminded)


def test_a_distance_of_the_threshold_or_more_reminds_of_nothing(monkeypatch):
    from server.engine.memory import EpisodicMemory

    memory = EpisodicMemory()
    far = _stored(memory, "mrrjjk")
    new = _stored(memory, "mrrjjjj")
    monkeypatch.setattr(memory, "distance", lambda new, past, meta=None: 5.0)

    assert memory.find_remindings(new, 5, meta=_META) == []
    assert far.activation == 0


# ---- the helpers the answer commentary is built from ----


def test_slippages_are_punctuated_as_metacat_does():
    from server.engine.codelet_dsl.builtins import _punctuate

    assert _punctuate(["a <=> b"]) == "a <=> b"
    assert _punctuate(["a <=> b", "c <=> d"]) == "a <=> b and c <=> d"
    assert _punctuate(["a <=> b", "c <=> d", "e <=> f"]) == "a <=> b, c <=> d, and e <=> f"


def test_the_problem_is_named_with_a_comma():
    from server.engine.codelet_dsl.builtins import problem_print_name

    assert problem_print_name(("abc", "abd", "mrrjjj", "mrrjjk")) == "abc -> abd, mrrjjj -> ?"


def test_an_unjustified_answer_is_stumped_in_both_voices():
    from server.engine.commentary import emit_answer_unjustified

    log = CommentaryLog()
    emit_answer_unjustified(log, "letter-category <=> length", 10, T, 1)
    assert _lines(log) == [(
        "Okay, I'm stumped.  This answer makes no sense to me.  I see no way to make "
        "the necessary letter-category <=> length slippage here.",
        "Run terminated.  Unable to make the necessary letter-category <=> length slippage.",
    )]
    log = CommentaryLog()
    emit_answer_unjustified(log, "a <=> b and c <=> d", 10, T, 2)
    assert _lines(log)[0][1].endswith("a <=> b and c <=> d slippages.")
