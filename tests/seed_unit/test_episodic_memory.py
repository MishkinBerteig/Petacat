"""Reminding and comparison, which render against the phrasing in ``seed_data/``.

``compare_answers`` resolves the commentary templates when none are supplied, so the
distance calculation and the comparison both read what the seed data holds.
``find_remindings`` reaches the same code through ``distance``.
"""

from server.engine.memory import AnswerDescription, EpisodicMemory


def _answer(themes, *, quality=80.0, top_rule="top-rule"):
    return AnswerDescription(
        problem=("abc", "abd", "xyz", "xyd"),
        top_rule_description=top_rule,
        bottom_rule_description="",
        top_rule_quality=0.0,
        bottom_rule_quality=0.0,
        quality=quality,
        temperature=0.0,
        themes=themes,
        unjustified_slippages=[],
    )


# --- find_remindings -------------------------------------------------------

def test_find_remindings_excludes_the_query_answer_itself():
    mem = EpisodicMemory()
    desc = _answer({"direction": "opposite"})
    mem.store_answer(desc)
    # Querying with the very answer that is stored must not remind of itself.
    assert mem.find_remindings(desc, distance_threshold=5.0) == []


def test_find_remindings_returns_past_answer_within_threshold():
    mem = EpisodicMemory()
    past = _answer({"direction": "opposite", "position": "rightmost"})
    mem.store_answer(past)
    # One differing dimension, plus ``calculate-answer-distance``'s base of 1.
    query = _answer({"direction": "opposite", "position": "leftmost"})  # distance 2
    remindings = mem.find_remindings(query, distance_threshold=5.0)
    assert remindings == [past]


def test_find_remindings_excludes_past_answer_beyond_threshold():
    mem = EpisodicMemory()
    past = _answer({"direction": "same", "position": "leftmost"})
    mem.store_answer(past)
    query = _answer({"direction": "opposite", "position": "rightmost"})  # distance 3
    assert mem.find_remindings(query, distance_threshold=2.0) == []


def test_find_remindings_excludes_past_answer_at_exact_threshold():
    """At the threshold the activation is zero, and zero is not a reminding.

    ``memory.ss:212`` drives activation to 0 exactly *at* ``%distance-threshold%``,
    and ``memory.ss:214`` reports a reminding only when the activation exceeds 0.
    """
    mem = EpisodicMemory()
    past = _answer({"direction": "opposite"})
    mem.store_answer(past)
    query = _answer({"direction": "same"})  # distance exactly 2
    assert mem.find_remindings(query, distance_threshold=2.0) == []
    # One step inside the threshold it is remembered, with a graded activation.
    assert mem.find_remindings(query, distance_threshold=4.0) == [past]
    assert past.activation == 50.0


# --- compare_answers -------------------------------------------------------

def test_compare_answers_reports_shared_theme_with_equal_value():
    mem = EpisodicMemory()
    a = _answer({"position": "rightmost"})
    b = _answer({"position": "rightmost"})
    result = mem.compare_answers(a, b)
    assert result["common_themes"] == {"position": "rightmost"}


def test_compare_answers_splits_dimension_with_differing_values():
    mem = EpisodicMemory()
    a = _answer({"direction": "opposite"})
    b = _answer({"direction": "same"})
    result = mem.compare_answers(a, b)
    # Same category, different relation -> a *differing* theme, not two uniques.
    assert result["differing_themes"]["direction"] == ("opposite", "same")


def test_compare_answers_reports_dimension_present_only_in_a():
    mem = EpisodicMemory()
    a = _answer({"position": "rightmost", "direction": "opposite"})
    b = _answer({"position": "rightmost"})
    result = mem.compare_answers(a, b)
    assert result["a_unique_themes"] == {"direction": "opposite"}


def test_compare_answers_includes_quality_and_rule_fields():
    mem = EpisodicMemory()
    a = _answer({"position": "rightmost"}, quality=80.0, top_rule="rule-a")
    b = _answer({"position": "rightmost"}, quality=55.0, top_rule="rule-b")
    result = mem.compare_answers(a, b)
    assert result["a_quality"] == 80.0
    assert result["b_quality"] == 55.0
    assert result["a_rule"] == "rule-a"
    assert result["b_rule"] == "rule-b"
