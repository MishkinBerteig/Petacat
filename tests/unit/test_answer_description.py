"""Tests for EpisodicMemory."""

from server.engine.memory import AnswerDescription, EpisodicMemory


def test_store_and_retrieve():
    mem = EpisodicMemory()
    desc = AnswerDescription(
        problem=("abc", "abd", "xyz", "wyz"),
        top_rule_description="change rightmost letter by successor",
        bottom_rule_description="change rightmost letter by predecessor",
        top_rule_quality=85.0,
        bottom_rule_quality=85.0,
        quality=80.0,
        temperature=30.0,
        themes={"direction": "opposite"},
        unjustified_slippages=[],
    )
    mem.store_answer(desc)
    assert len(mem.answers) == 1


def test_reminding():
    mem = EpisodicMemory()
    desc1 = AnswerDescription(
        problem=("abc", "abd", "xyz", "wyz"),
        top_rule_description="", bottom_rule_description="",
        top_rule_quality=85, bottom_rule_quality=85,
        quality=80, temperature=30,
        themes={"direction": "opposite", "position": "rightmost"},
        unjustified_slippages=[],
    )
    desc2 = AnswerDescription(
        problem=("rst", "rsu", "xyz", "wyz"),
        top_rule_description="", bottom_rule_description="",
        top_rule_quality=80, bottom_rule_quality=80,
        quality=75, temperature=35,
        themes={"direction": "opposite", "position": "rightmost"},
        unjustified_slippages=[],
    )
    mem.store_answer(desc1)
    remindings = mem.find_remindings(desc2, distance_threshold=5)
    assert len(remindings) == 1
    assert remindings[0] is desc1


def test_comparison():
    mem = EpisodicMemory()
    desc1 = AnswerDescription(
        problem=("abc", "abd", "xyz", "xyd"),
        top_rule_description="change c to d",
        bottom_rule_description="change z to d",
        top_rule_quality=60, bottom_rule_quality=50,
        quality=55, temperature=50,
        themes={"position": "rightmost"},
        unjustified_slippages=[],
    )
    desc2 = AnswerDescription(
        problem=("abc", "abd", "xyz", "wyz"),
        top_rule_description="change c to d",
        bottom_rule_description="change x to w",
        top_rule_quality=85, bottom_rule_quality=85,
        quality=80, temperature=30,
        themes={"position": "rightmost", "direction": "opposite"},
        unjustified_slippages=[],
    )
    result = mem.compare_answers(desc1, desc2)
    assert "position" in result["shared_themes"]
    assert "direction" in result["b_only_themes"]


def test_clear():
    mem = EpisodicMemory()
    mem.store_answer(AnswerDescription(
        problem=("a", "b", "c", "d"),
        top_rule_description="", bottom_rule_description="",
        top_rule_quality=0, bottom_rule_quality=0,
        quality=0, temperature=0,
        themes={}, unjustified_slippages=[],
    ))
    mem.clear()
    assert len(mem.answers) == 0
