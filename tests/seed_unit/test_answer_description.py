"""The EpisodicMemory happy paths: store, remind, compare, clear.

``compare_answers`` takes the commentary templates from the run's ``MetadataProvider``
(here the Metacat Standard Configuration), and ``find_remindings`` reaches it through
``distance``, so the reminding and comparison paths read the provider's phrasing.
"""

import os

from server.engine.memory import AnswerDescription, EpisodicMemory
from server.engine.metadata import MetadataProvider

STRING_POSITION = "plato-string-position-category"
DIRECTION = "plato-direction-category"

_META = MetadataProvider.from_standard_configuration(
    os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
)


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
        top_rule_signature=[], bottom_rule_signature=[],
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
        top_rule_signature=[], bottom_rule_signature=[],
    )
    desc2 = AnswerDescription(
        problem=("rst", "rsu", "xyz", "wyz"),
        top_rule_description="", bottom_rule_description="",
        top_rule_quality=80, bottom_rule_quality=80,
        quality=75, temperature=35,
        themes={"direction": "opposite", "position": "rightmost"},
        unjustified_slippages=[],
        top_rule_signature=[], bottom_rule_signature=[],
    )
    mem.store_answer(desc1)
    remindings = mem.find_remindings(desc2, distance_threshold=5, meta=_META)
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
        themes={STRING_POSITION: "identity"},
        unjustified_slippages=[],
        top_rule_signature=[], bottom_rule_signature=[],
    )
    desc2 = AnswerDescription(
        problem=("abc", "abd", "xyz", "wyz"),
        top_rule_description="change c to d",
        bottom_rule_description="change x to w",
        top_rule_quality=85, bottom_rule_quality=85,
        quality=80, temperature=30,
        themes={STRING_POSITION: "identity", DIRECTION: "opposite"},
        unjustified_slippages=[],
        top_rule_signature=[], bottom_rule_signature=[],
    )
    result = mem.compare_answers(desc1, desc2, meta=_META)
    assert STRING_POSITION in result["common_themes"]
    assert DIRECTION in result["b_unique_themes"]


def test_clear():
    mem = EpisodicMemory()
    mem.store_answer(AnswerDescription(
        problem=("a", "b", "c", "d"),
        top_rule_description="", bottom_rule_description="",
        top_rule_quality=0, bottom_rule_quality=0,
        quality=0, temperature=0,
        themes={}, unjustified_slippages=[],
        top_rule_signature=[], bottom_rule_signature=[],
    ))
    mem.clear()
    assert len(mem.answers) == 0
