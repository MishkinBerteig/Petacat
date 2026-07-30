"""Unit tests for engine.memory.EpisodicMemory algorithms.

EpisodicMemory is part of MetaCat's self-watching machinery: it decides when
a new answer is similar enough to a past one to trigger a reminding, and how
two answers compare. These tests drive one path each through the reminding /
theme-distance / comparison logic. The module is pure (no RNG, no I/O), so
determinism is automatic.

Basic store/remind/compare/clear happy paths live in test_answer_description.py;
this file targets the branch structure and the previously-untested snag path.
"""

from server.engine.memory import (
    AnswerDescription,
    EpisodicMemory,
    SnagDescription,
)


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


def _snag(theme_pattern):
    return SnagDescription(
        problem=("abc", "abd", "xyz"),
        codelet_count=100,
        temperature=70.0,
        theme_pattern=theme_pattern,
    )


# --- storage & identity ----------------------------------------------------

def test_store_snag_appends_to_snags_list():
    mem = EpisodicMemory()
    mem.store_snag(_snag({"direction": "left"}))
    assert len(mem.snags) == 1


def test_storing_answers_assigns_incrementing_ids():
    mem = EpisodicMemory()
    first, second = _answer({"a": "1"}), _answer({"a": "1"})
    mem.store_answer(first)
    mem.store_answer(second)
    assert second.answer_id == first.answer_id + 1


def test_storing_snags_assigns_incrementing_ids():
    mem = EpisodicMemory()
    first, second = _snag({"a": "1"}), _snag({"a": "1"})
    mem.store_snag(first)
    mem.store_snag(second)
    assert second.snag_id == first.snag_id + 1


def test_answer_ids_are_scoped_to_the_memory_not_the_process():
    """A fresh memory numbers from 1 again.

    Episodic Memory outlives a run — within a Training Session it accumulates
    answers across many of them — so ``answer_id`` has to be unique within the
    memory: ``/api/memory/compare`` identifies answers by it.  What it must *not*
    depend on is how many answers some earlier, unrelated memory happened to hold,
    which is what the class-level counter it replaced did (WP0.3 / defect D3).
    """
    first_session = EpisodicMemory()
    for _ in range(3):
        first_session.store_answer(_answer({"a": "1"}))

    second_session = EpisodicMemory()
    answer = _answer({"a": "1"})
    second_session.store_answer(answer)
    assert answer.answer_id == 1


def test_unstored_answer_has_no_id():
    """An answer description that was never stored has no place in a memory."""
    assert _answer({"a": "1"}).answer_id == 0


# --- theme distance --------------------------------------------------------

def test_theme_distance_is_zero_for_two_empty_patterns():
    mem = EpisodicMemory()
    assert mem._theme_distance({}, {}) == 0.0


def test_theme_distance_is_zero_for_identical_patterns():
    mem = EpisodicMemory()
    themes = {"direction": "opposite", "position": "rightmost"}
    assert mem._theme_distance(dict(themes), dict(themes)) == 0.0


def test_theme_distance_counts_each_differing_dimension():
    mem = EpisodicMemory()
    a = {"direction": "opposite", "position": "rightmost"}
    b = {"direction": "same", "position": "leftmost"}
    assert mem._theme_distance(a, b) == 2.0


def test_theme_distance_counts_dimension_present_on_only_one_side():
    mem = EpisodicMemory()
    assert mem._theme_distance({"direction": "opposite"}, {}) == 1.0


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
    query = _answer({"direction": "opposite", "position": "leftmost"})  # distance 1
    remindings = mem.find_remindings(query, distance_threshold=2.0)
    assert remindings == [past]


def test_find_remindings_excludes_past_answer_beyond_threshold():
    mem = EpisodicMemory()
    past = _answer({"direction": "same", "position": "leftmost"})
    mem.store_answer(past)
    query = _answer({"direction": "opposite", "position": "rightmost"})  # distance 2
    assert mem.find_remindings(query, distance_threshold=1.0) == []


def test_find_remindings_includes_past_answer_at_exact_threshold():
    mem = EpisodicMemory()
    past = _answer({"direction": "opposite"})
    mem.store_answer(past)
    query = _answer({"direction": "same"})  # distance exactly 1
    assert mem.find_remindings(query, distance_threshold=1.0) == [past]


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
