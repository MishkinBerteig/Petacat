"""Episodic Memory — stores answer and snag descriptions across runs.

Supports reminding (activating similar past answers), comparison
(analyzing shared vs differing themes), and commentary generation.

Scheme source: memory.ss, answers.ss
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnswerDescription:
    """Rich characterization of a discovered answer."""

    problem: tuple[str, str, str, str]  # initial, modified, target, answer
    top_rule_description: str
    bottom_rule_description: str
    top_rule_quality: float
    bottom_rule_quality: float
    quality: float
    temperature: float
    themes: dict[str, Any]  # dimension -> relation mapping
    unjustified_slippages: list[Any]
    run_id: int | None = None
    answer_id: int = 0

    _next_id: int = 0

    def __post_init__(self) -> None:
        AnswerDescription._next_id += 1
        self.answer_id = AnswerDescription._next_id


@dataclass
class SnagDescription:
    """Record of a failure episode."""

    problem: tuple[str, str, str]  # initial, modified, target
    codelet_count: int
    temperature: float
    theme_pattern: dict[str, Any]
    description: str = ""
    run_id: int | None = None
    snag_id: int = 0

    _next_id: int = 0

    def __post_init__(self) -> None:
        SnagDescription._next_id += 1
        self.snag_id = SnagDescription._next_id


class EpisodicMemory:
    """Cross-run episodic memory.

    Memory is scoped to the user/session, not to individual runs.
    A manual "Clear Memory" action resets it (matching clearmem in Scheme).
    """

    def __init__(self) -> None:
        self.answers: list[AnswerDescription] = []
        self.snags: list[SnagDescription] = []

    def store(self, desc: AnswerDescription) -> None:
        self.answers.append(desc)

    def store_answer(self, desc: AnswerDescription) -> None:
        self.answers.append(desc)

    def store_snag(self, desc: SnagDescription) -> None:
        self.snags.append(desc)

    def find_remindings(
        self,
        new_desc: AnswerDescription,
        distance_threshold: float = 5.0,
    ) -> list[AnswerDescription]:
        """Find past answers with sufficiently similar themes.

        Scheme: memory.ss reminding algorithm.
        """
        remindings = []
        for past in self.answers:
            if past is new_desc:
                continue
            distance = self._theme_distance(new_desc.themes, past.themes)
            if distance <= distance_threshold:
                remindings.append(past)
        return remindings

    def compare_answers(
        self,
        a: AnswerDescription,
        b: AnswerDescription,
    ) -> dict[str, Any]:
        """Compare two answers: shared vs differing themes, rules, quality.

        Scheme: answers.ss comparison logic.
        """
        shared_themes: dict[str, Any] = {}
        a_only_themes: dict[str, Any] = {}
        b_only_themes: dict[str, Any] = {}

        all_dims = set(a.themes.keys()) | set(b.themes.keys())
        for dim in all_dims:
            a_val = a.themes.get(dim)
            b_val = b.themes.get(dim)
            if a_val is not None and b_val is not None:
                if a_val == b_val:
                    shared_themes[dim] = a_val
                else:
                    a_only_themes[dim] = a_val
                    b_only_themes[dim] = b_val
            elif a_val is not None:
                a_only_themes[dim] = a_val
            elif b_val is not None:
                b_only_themes[dim] = b_val

        return {
            "shared_themes": shared_themes,
            "a_only_themes": a_only_themes,
            "b_only_themes": b_only_themes,
            "a_quality": a.quality,
            "b_quality": b.quality,
            "a_rule": a.top_rule_description,
            "b_rule": b.top_rule_description,
        }

    def _theme_distance(
        self,
        themes1: dict[str, Any],
        themes2: dict[str, Any],
    ) -> float:
        """Compute distance between two theme patterns."""
        all_dims = set(themes1.keys()) | set(themes2.keys())
        if not all_dims:
            return 0.0
        differences = 0
        for dim in all_dims:
            v1 = themes1.get(dim)
            v2 = themes2.get(dim)
            if v1 != v2:
                differences += 1
        return float(differences)

    def clear(self) -> None:
        """Delete all answer and snag descriptions. Matches Scheme clearmem."""
        self.answers.clear()
        self.snags.clear()

    def __repr__(self) -> str:
        return f"EpisodicMemory({len(self.answers)} answers, {len(self.snags)} snags)"
