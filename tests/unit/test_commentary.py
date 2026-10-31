"""The ``CommentaryLog`` and the emit helpers whose English is written in Python."""

from server.engine.commentary import (
    CommentaryLog,
    CommentaryParagraph,
    emit_new_problem,
    emit_snag,
    emit_clamp_activate,
    emit_clamp_expired,
    emit_jootsing,
    emit_reminding,
)


import os as _os

from server.engine.metadata import MetadataProvider as _MetadataProvider

_META = _MetadataProvider.from_standard_configuration(
    _os.path.join(_os.path.dirname(__file__), "..", "..", "seed_data")
)
#: The Metacat Standard Configuration's phrase-templates, from a provider.
T = _META.commentary_templates


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


def test_render_eliza_mode_uses_eliza_voice():
    log = CommentaryLog()
    log.add_comment("Eliza voice", "Technical voice")
    assert log.render(eliza_mode=True) == "Eliza voice"


def test_render_technical_mode_uses_technical_voice():
    log = CommentaryLog()
    log.add_comment("Eliza voice", "Technical voice")
    assert log.render(eliza_mode=False) == "Technical voice"


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


def test_render_joins_eliza_comments_with_double_newline():
    log = CommentaryLog()
    log.add_comment("A", "X")
    log.add_comment("B", "Y")
    assert log.render(eliza_mode=True) == "A\n\nB"


def test_render_joins_technical_comments_with_double_newline():
    log = CommentaryLog()
    log.add_comment("A", "X")
    log.add_comment("B", "Y")
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


# ---- emit_snag ----


def test_snag_first():
    log = CommentaryLog()
    emit_snag(log, "The successor of z does not exist", 1, 100, T)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "Uh-oh" in eliza
    assert "again" not in eliza
    assert "a snag" in tech


def test_snag_repeat():
    log = CommentaryLog()
    emit_snag(log, "Same problem", 3, 200, T)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "again" in eliza
    assert "another snag" in tech


# ---- emit_clamp_activate ----
#
# Expected strings are Metacat's own (trace.ss:592-612), as logged from Metacat 1.2.


def _both(log):
    return log.render(eliza_mode=True), log.render(eliza_mode=False)


def test_clamp_activate_rule_codelet():
    log = CommentaryLog()
    emit_clamp_activate(log, "rule_codelet_clamp", 1, 100, T)
    assert _both(log) == (
        "I'll just have to try a little harder...",
        "Clamping rule-codelet pattern...",
    )


def test_clamp_activate_snag_response():
    log = CommentaryLog()
    emit_clamp_activate(log, "snag_response_clamp", 1, 100, T)
    assert _both(log) == (
        "All right, I've had enough of this!  Let's try something different for a change...",
        "Clamping negative theme pattern...",
    )


def test_clamp_activate_justify_first_and_another():
    log = CommentaryLog()
    emit_clamp_activate(log, "justify_clamp", 1, 100, T)
    assert _both(log) == ("Aha!  I have an idea...", "Clamping theme patterns...")
    log = CommentaryLog()
    emit_clamp_activate(log, "justify_clamp", 2, 100, T)
    assert _both(log)[0] == "Aha!  I have another idea..."


def test_clamp_activate_manual_first_and_another():
    log = CommentaryLog()
    emit_clamp_activate(log, "manual_clamp", 1, 100, T)
    assert _both(log) == (
        "Thank you for that interesting suggestion!  Let me think about it...",
        "Manually clamping patterns...",
    )
    log = CommentaryLog()
    emit_clamp_activate(log, "manual_clamp", 2, 100, T)
    assert _both(log)[0].startswith("Thank you for another interesting suggestion!")


def test_clamp_activate_says_nothing_for_an_unknown_type():
    log = CommentaryLog()
    emit_clamp_activate(log, "mystery_clamp", 1, 100, T)
    assert log.count == 0


# ---- emit_clamp_expired ----
#
# trace.ss:129-170 and the progress phrases at trace.ss:212-226.


def test_clamp_expired_rule_codelet_zero():
    log = CommentaryLog()
    emit_clamp_expired(log, "rule_codelet_clamp", 0, 200, T)
    assert _both(log) == (
        "Well, my latest effort to think up new rules resulted in zero progress."
        "  Guess it was a pretty useless effort, in retrospect.",
        "Unclamping patterns.  Progress achieved by rule-codelet clamp = 0.",
    )


def test_clamp_expired_rule_codelet_a_lot():
    log = CommentaryLog()
    emit_clamp_expired(log, "rule_codelet_clamp", 100, 200, T)
    assert _both(log) == (
        "Well, my latest effort to think up new rules resulted in a lot of progress."
        "  Guess it was a pretty good effort, in retrospect.",
        "Unclamping patterns.  Progress achieved by rule-codelet clamp = 100.",
    )


def test_clamp_expired_snag_response_matches_metacat_log():
    # Logged from Metacat 1.2, abc -> abd, xyz -> ?, seed 2.
    log = CommentaryLog()
    emit_clamp_expired(log, "snag_response_clamp", 79, 1976, T)
    assert _both(log) == (
        "Looks like I made some headway in coming up with new ideas.",
        "Unclamping patterns.  Progress achieved by snag-response clamp = 79.",
    )


def test_clamp_expired_justify_and_manual():
    log = CommentaryLog()
    emit_clamp_expired(log, "justify_clamp", 30, 5, T)
    assert _both(log) == (
        "Looks like that last brilliant idea I had resulted in very little progress."
        "  Guess it was not such a great idea, in retrospect.",
        "Unclamping patterns.  Progress achieved by justify clamp = 30.",
    )
    log = CommentaryLog()
    emit_clamp_expired(log, "manual_clamp", 50, 5, T)
    assert _both(log) == (
        "That last suggestion of yours resulted in some progress."
        "  Guess it was an okay idea, in retrospect.",
        "Unclamping patterns.  Progress achieved by manual clamp = 50.",
    )


def test_clamp_progress_bands_are_metacats():
    from server.engine.commentary import _progress_key

    assert [_progress_key(p) for p in (0, 1, 49, 50, 79, 80, 100)] == [
        "zero", "little", "little", "some", "some", "a_lot", "a_lot",
    ]


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


def test_jootsing_has_no_invented_fallback():
    log = CommentaryLog()
    emit_jootsing(log, "frustrated", 300)
    assert log.count == 0


# ---- emit_frustrated (jootsing.ss:306-325) ----


def test_frustrated_names_the_poor_string_pairs():
    from server.engine.commentary import emit_frustrated

    both = CommentaryLog()
    emit_frustrated(both, "abc", "abd", "xyz", "xyd", True, True, 10, T)
    assert _both(both) == (
        "I'm getting frustrated.  I still don't see a good way to describe either "
        'how "abc" changes to "abd" or how "xyz" changes to "xyd".',
        "No satisfactory rules yet exist for describing either "
        'how "abc" changes to "abd" or how "xyz" changes to "xyd".',
    )
    top = CommentaryLog()
    emit_frustrated(top, "abc", "abd", "xyz", None, True, False, 10, T)
    assert _both(top)[0].endswith('describe how "abc" changes to "abd".')
    bottom = CommentaryLog()
    emit_frustrated(bottom, "abc", "abd", "xyz", "xyd", False, True, 10, T)
    assert _both(bottom)[1].endswith('describing how "xyz" changes to "xyd".')


# ---- emit_reminding ----


def test_reminding_strong():
    log = CommentaryLog()
    emit_reminding(log, "xyd", "abc -> abd, xyz -> ?", 85, 100, T)
    assert _both(log) == (
        'This answer strongly reminds me of the answer xyd to the problem "abc -> abd, xyz -> ?".',
        'This answer is reminiscent of the answer xyd to the problem "abc -> abd, xyz -> ?".'
        "  Reminding strength = 85.",
    )


def test_reminding_weak():
    log = CommentaryLog()
    emit_reminding(log, "xyd", "abc -> abd, xyz -> ?", 20, 100, T)
    eliza = log.render(eliza_mode=True)
    assert "vaguely reminds" in eliza
