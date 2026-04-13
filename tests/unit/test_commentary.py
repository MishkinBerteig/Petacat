"""Unit tests for the CommentaryLog and commentary generation helpers."""

import pytest
from server.engine.commentary import (
    CommentaryLog,
    CommentaryParagraph,
    emit_new_problem,
    emit_answer_discovered,
    emit_answer_justified,
    emit_answer_unjustified,
    emit_snag,
    emit_give_up,
    emit_clamp_activate,
    emit_clamp_expired,
    emit_jootsing,
    emit_reminding,
)


# ---- CommentaryLog core ----


def test_add_and_render_eliza():
    log = CommentaryLog()
    log.add_comment("Hello there!", "Greeting.", codelet_count=0, event_type="test")
    log.add_comment("How are you?", "Status check.", codelet_count=5, event_type="test")
    result = log.render(eliza_mode=True)
    assert "Hello there!" in result
    assert "How are you?" in result
    assert "Greeting." not in result


def test_add_and_render_technical():
    log = CommentaryLog()
    log.add_comment("Hello there!", "Greeting.", codelet_count=0, event_type="test")
    log.add_comment("How are you?", "Status check.", codelet_count=5, event_type="test")
    result = log.render(eliza_mode=False)
    assert "Greeting." in result
    assert "Status check." in result
    assert "Hello there!" not in result


def test_switch_modes():
    log = CommentaryLog()
    log.add_comment("Eliza voice", "Technical voice")
    eliza = log.render(eliza_mode=True)
    technical = log.render(eliza_mode=False)
    assert eliza == "Eliza voice"
    assert technical == "Technical voice"
    assert eliza != technical


def test_clear():
    log = CommentaryLog()
    log.add_comment("test", "test")
    assert log.count == 1
    log.clear()
    assert log.count == 0
    assert log.render() == ""


def test_get_paragraphs():
    log = CommentaryLog()
    log.add_comment("e1", "t1", codelet_count=10, event_type="snag")
    log.add_comment("e2", "t2", codelet_count=20, event_type="answer")
    paras = log.get_paragraphs()
    assert len(paras) == 2
    assert paras[0].eliza_text == "e1"
    assert paras[0].technical_text == "t1"
    assert paras[0].codelet_count == 10
    assert paras[0].event_type == "snag"
    assert paras[1].codelet_count == 20


def test_paragraph_dataclass():
    p = CommentaryParagraph("eliza", "tech", 42, "event")
    assert p.eliza_text == "eliza"
    assert p.technical_text == "tech"
    assert p.codelet_count == 42
    assert p.event_type == "event"


def test_render_joins_with_double_newline():
    log = CommentaryLog()
    log.add_comment("A", "X")
    log.add_comment("B", "Y")
    assert log.render(eliza_mode=True) == "A\n\nB"
    assert log.render(eliza_mode=False) == "X\n\nY"


# ---- emit_new_problem ----


def test_new_problem_discovery():
    log = CommentaryLog()
    emit_new_problem(log, "abc", "abd", "xyz", None, False)
    assert log.count == 1
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert '"abc"' in eliza
    assert '"abd"' in eliza
    assert '"xyz"' in eliza
    assert "Okay" in eliza
    assert "Beginning run" in tech


def test_new_problem_justify():
    log = CommentaryLog()
    emit_new_problem(log, "abc", "abd", "xyz", "xyd", True)
    assert log.count == 1
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert '"xyd"' in eliza
    assert "Let's see" in eliza
    assert "justify" in tech.lower()


# ---- emit_answer_discovered ----


def test_answer_discovered_high_quality():
    log = CommentaryLog()
    emit_answer_discovered(log, "xyd", 90.0, "great", 50.0, 100, 0, {})
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert '"xyd"' in eliza
    assert "great" in eliza
    assert "90" in tech


def test_answer_discovered_low_quality():
    log = CommentaryLog()
    emit_answer_discovered(log, "xyd", 40.0, "really terrible", 80.0, 100, 0, {})
    eliza = log.render(eliza_mode=True)
    assert "really terrible" in eliza


def test_answer_discovered_also():
    """Second answer should include 'also'."""
    log = CommentaryLog()
    emit_answer_discovered(log, "xyd", 85.0, "good", 50.0, 200, 1, {})
    eliza = log.render(eliza_mode=True)
    assert "also" in eliza


# ---- emit_answer_justified ----


def test_answer_justified():
    log = CommentaryLog()
    emit_answer_justified(log, 85.0, "pretty good", 100, {})
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "Aha" in eliza
    assert "pretty good" in eliza
    assert "justified" in tech.lower()


# ---- emit_answer_unjustified ----


def test_answer_unjustified():
    log = CommentaryLog()
    emit_answer_unjustified(log, "leftmost->rightmost", 100)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "stumped" in eliza
    assert "leftmost->rightmost" in eliza
    assert "terminated" in tech.lower()


# ---- emit_snag ----


def test_snag_first():
    log = CommentaryLog()
    emit_snag(log, "The successor of z does not exist", 1, 100)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "Uh-oh" in eliza
    assert "again" not in eliza
    assert "a snag" in tech


def test_snag_repeat():
    log = CommentaryLog()
    emit_snag(log, "Same problem", 3, 200)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "again" in eliza
    assert "another snag" in tech


# ---- emit_give_up ----


def test_give_up():
    log = CommentaryLog()
    emit_give_up(log, 500)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "punch" in eliza
    assert "terminated" in tech.lower()


# ---- emit_clamp_activate ----


def test_clamp_activate_rule_codelet():
    log = CommentaryLog()
    emit_clamp_activate(log, "rule_codelet_clamp", 1, 100)
    eliza = log.render(eliza_mode=True)
    assert "harder" in eliza


def test_clamp_activate_snag_response():
    log = CommentaryLog()
    emit_clamp_activate(log, "snag_response_clamp", 1, 100)
    eliza = log.render(eliza_mode=True)
    assert "different" in eliza


def test_clamp_activate_justify():
    log = CommentaryLog()
    emit_clamp_activate(log, "justify_clamp", 1, 100)
    eliza = log.render(eliza_mode=True)
    assert "idea" in eliza


# ---- emit_clamp_expired ----


def test_clamp_expired_no_progress():
    log = CommentaryLog()
    emit_clamp_expired(log, "rule_codelet_clamp", 5.0, 200)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "no significant" in eliza
    assert "a bad" in eliza
    assert "Unclamping" in tech


def test_clamp_expired_good_progress():
    log = CommentaryLog()
    emit_clamp_expired(log, "rule_codelet_clamp", 75.0, 200)
    eliza = log.render(eliza_mode=True)
    assert "a good deal of" in eliza
    assert "a pretty good" in eliza


# ---- emit_jootsing ----


def test_jootsing_rule_codelet():
    log = CommentaryLog()
    emit_jootsing(log, "rule_codelet", 300)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "better rules" in eliza
    assert "rule-codelet" in tech


def test_jootsing_snag_response():
    log = CommentaryLog()
    emit_jootsing(log, "snag_response", 300)
    eliza = log.render(eliza_mode=True)
    assert "boring" in eliza


def test_jootsing_frustrated():
    log = CommentaryLog()
    emit_jootsing(log, "frustrated", 300)
    eliza = log.render(eliza_mode=True)
    assert "frustrated" in eliza


# ---- emit_reminding ----


def test_reminding_strong():
    log = CommentaryLog()
    emit_reminding(log, "xyd", "abc -> abd; xyz -> ?", 85.0, 100)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "strongly reminds" in eliza
    assert '"xyd"' in eliza
    assert "85" in tech


def test_reminding_weak():
    log = CommentaryLog()
    emit_reminding(log, "xyd", "abc -> abd; xyz -> ?", 20.0, 100)
    eliza = log.render(eliza_mode=True)
    assert "vaguely reminds" in eliza
