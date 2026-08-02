"""Unit tests for engine.memory.EpisodicMemory algorithms.

EpisodicMemory is part of MetaCat's self-watching machinery: it decides when
a new answer is similar enough to a past one to trigger a reminding, and how
two answers compare. These tests drive one path each through the identifier,
theme-distance and ``answer_present`` logic, over answers built in the test, so
determinism is automatic.

Reminding and comparison resolve the seeded commentary templates, and are
covered in ``tests/seed_unit/test_episodic_memory.py`` alongside the
store/remind/compare/clear happy paths in
``tests/seed_unit/test_answer_description.py``.
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


# --- answer_present: the one place memory reaches back into cognition -------


def _stored(problem, top_sig, bottom_sig=None):
    return AnswerDescription(
        problem=problem,
        top_rule_description="",
        bottom_rule_description="",
        top_rule_quality=0.0,
        bottom_rule_quality=0.0,
        quality=0.0,
        temperature=0.0,
        themes={},
        unjustified_slippages=[],
        top_rule_signature=top_sig,
        bottom_rule_signature=bottom_sig,
    )


class _FakeRule:
    """Stands in for a Rule with a known signature.

    ``answer_present`` calls ``rule_signature``, which reads ``clauses``; an empty
    clause list gives the empty signature, so the fakes carry explicit ones through a
    module-level patch instead.
    """

    def __init__(self, signature):
        self.signature = signature
        self.clauses = []


def _patched_signature(monkeypatch):
    import server.engine.rules as rules_module

    monkeypatch.setattr(
        rules_module,
        "rule_signature",
        lambda rule: getattr(rule, "signature", None) if rule is not None else None,
    )


def test_answer_present_is_true_for_the_same_answer_by_the_same_rules(monkeypatch):
    """``answers.ss:982`` fizzles on a hit so the search moves to a *different* answer."""
    _patched_signature(monkeypatch)
    mem = EpisodicMemory()
    mem.store_answer(_stored(("abc", "abd", "xyz", "xyd"), [["intrinsic"]], None))

    assert mem.answer_present(
        ("abc", "abd", "xyz", "xyd"), _FakeRule([["intrinsic"]]), None
    )


def test_answer_present_is_false_for_the_same_answer_by_a_different_rule(monkeypatch):
    """``memory.ss:190-196`` compares the rules too.

    The same answer string reached a different way is a different idea, and MetaCat
    stores it as a separate episode rather than suppressing it.
    """
    _patched_signature(monkeypatch)
    mem = EpisodicMemory()
    mem.store_answer(_stored(("abc", "abd", "xyz", "xyd"), [["intrinsic"]], None))

    assert not mem.answer_present(
        ("abc", "abd", "xyz", "xyd"), _FakeRule([["verbatim"]]), None
    )


def test_answer_present_is_false_for_a_different_problem(monkeypatch):
    _patched_signature(monkeypatch)
    mem = EpisodicMemory()
    mem.store_answer(_stored(("abc", "abd", "xyz", "xyd"), [["intrinsic"]], None))

    assert not mem.answer_present(
        ("abc", "abd", "ijk", "ijl"), _FakeRule([["intrinsic"]]), None
    )


def test_clearing_memory_resets_the_identifier_counter():
    """Otherwise ids drift out of step with the rows they were written from, and
    ``/api/memory/compare`` resolves an id to the wrong answer."""
    mem = EpisodicMemory()
    mem.store_answer(_stored(("abc", "abd", "xyz", "xyd"), None))
    mem.store_answer(_stored(("abc", "abd", "xyz", "wyz"), None))
    assert [a.answer_id for a in mem.answers] == [1, 2]

    mem.clear()
    mem.store_answer(_stored(("abc", "abd", "xyz", "xyd"), None))
    assert [a.answer_id for a in mem.answers] == [1]
