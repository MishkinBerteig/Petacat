"""Episodic Memory — stores answer and snag descriptions across runs.

Supports reminding (activating similar past answers), comparison
(analyzing shared vs differing themes), and commentary generation.

Scheme source: memory.ss, answers.ss
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.engine.ids import KIND_ANSWER, KIND_SNAG, IdAllocator


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
    themes: dict[str, Any]  # the vertical theme pattern (answers are compared on it)
    unjustified_slippages: list[Any]
    run_id: int | None = None
    answer_id: int = 0

    # §4.7.1: an answer description keeps the top, vertical and bottom theme
    # patterns separately, plus a pattern for the slippages it never justified.
    top_themes: dict[str, Any] = field(default_factory=dict)
    vertical_themes: dict[str, Any] = field(default_factory=dict)
    bottom_themes: dict[str, Any] = field(default_factory=dict)
    unjustified_themes: dict[str, Any] = field(default_factory=dict)

    top_rule_abstractness: float = 0.0
    bottom_rule_abstractness: float = 0.0

    # §4.7.5: "Every answer description stored in memory has an associated
    # activation level ranging from 0 to 100 ... the activation level of an
    # answer reflects how strongly the program is reminded of it."
    activation: float = 0.0

    def __post_init__(self) -> None:
        # ``answer_id`` is stamped by :meth:`EpisodicMemory.store_answer`, not here.
        # It numbers an answer's place in a memory, and a description that has not
        # been stored has no place in one yet.  See ``server/engine/ids.py``.
        if not self.vertical_themes:
            self.vertical_themes = dict(self.themes)

    @property
    def is_coherent(self) -> bool:
        """Do the rule and the themes sit at the same level of abstraction?

        §4.7.3: dyz "involves themes based on the abstract concept of opposite,
        but depends on a literal-minded interpretation of abc => abd.  This
        'dissonance' is the reason that Metacat considers dyz to be incoherent."
        """
        # With no themes, or no measured rule abstractness, there is nothing to
        # be dissonant *with*, so the question doesn't arise.
        if not self.themes or self.top_rule_abstractness <= 0.0:
            return True
        abstract_themes = sum(
            1 for rel in self.themes.values() if rel in ("opposite", "identity")
        )
        theme_abstractness = 100.0 * abstract_themes / len(self.themes)
        return abs(theme_abstractness - self.top_rule_abstractness) <= 50.0


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


class EpisodicMemory:
    """Cross-run episodic memory.

    Memory is scoped to the user/session, not to individual runs.
    A manual "Clear Memory" action resets it (matching clearmem in Scheme).

    Because it outlives a run, it is also the right owner of answer and snag
    numbering.  ``POST /api/memory/compare`` identifies answers by ``answer_id``
    across every run in a Training Session, so those identifiers have to be unique
    within the *memory*; per-run numbering would give two answers found in two runs
    of one session the same id.  A fresh ``EpisodicMemory`` starts again at 1, which
    is what removes the process-history dependence WP0.3 is about.
    """

    def __init__(self) -> None:
        self.answers: list[AnswerDescription] = []
        self.snags: list[SnagDescription] = []
        self.ids = IdAllocator()

    def store(self, desc: AnswerDescription) -> None:
        self.store_answer(desc)

    def store_answer(self, desc: AnswerDescription) -> None:
        desc.answer_id = self.ids.next(KIND_ANSWER)
        self.answers.append(desc)

    def store_snag(self, desc: SnagDescription) -> None:
        desc.snag_id = self.ids.next(KIND_SNAG)
        self.snags.append(desc)

    def find_remindings(
        self,
        new_desc: AnswerDescription,
        distance_threshold: float = 5.0,
    ) -> list[AnswerDescription]:
        """Reactivate past answers close enough to the new one to come to mind.

        §4.7.5: "each answer description computes the distance between itself and
        the new answer description ..., updating its level of activation
        according to the distance.  If the activation level exceeds some
        threshold, Metacat will be reminded of the answer, to the extent that
        the threshold is exceeded."
        """
        remindings = []
        for past in self.answers:
            if past is new_desc:
                continue
            distance = self.distance(new_desc, past)
            past.activation = max(0.0, 100.0 - distance * 10.0)
            if distance <= distance_threshold:
                remindings.append(past)
        new_desc.activation = 100.0
        remindings.sort(key=lambda a: a.activation, reverse=True)
        return remindings

    def distance(self, a: AnswerDescription, b: AnswerDescription) -> float:
        """How far apart two answers are.

        §4.7.5 defines distance over five components:

        1. the number of differing and unique themes;
        2. structural and conceptual differences between the rules;
        3. the difference in abstractness of the rules;
        4. themes justified for one answer but not the other;
        5. whether the answers agree in coherence.
        """
        comparison = self.compare_answers(a, b)

        # 1. Differing + unique themes.
        distance = float(
            len(comparison["differing_themes"])
            + len(comparison["a_unique_themes"])
            + len(comparison["b_unique_themes"])
        )

        # 2. Rule differences, structural and conceptual.
        if a.top_rule_description != b.top_rule_description:
            distance += 1.0
        if a.bottom_rule_description != b.bottom_rule_description:
            distance += 1.0

        # 3. Disparity in rule abstractness.
        distance += abs(a.top_rule_abstractness - b.top_rule_abstractness) / 50.0

        # 4. Themes justified for one but not the other.
        only_a = set(a.unjustified_themes) - set(b.unjustified_themes)
        only_b = set(b.unjustified_themes) - set(a.unjustified_themes)
        distance += float(len(only_a) + len(only_b))

        # 5. Coherence mismatch.
        if a.is_coherent != b.is_coherent:
            distance += 1.0

        return distance

    def compare_answers(
        self,
        a: AnswerDescription,
        b: AnswerDescription,
    ) -> dict[str, Any]:
        """Classify how two answers relate.

        §4.7.3 distinguishes three kinds of theme relationship, which the old
        single "a_only / b_only" split conflated:

        * **common** — identical themes shared by both answers;
        * **differing** — same category, different relation (identity vs opposite);
        * **unique** — a theme one answer has and the other does not mention.

        On top of that, an **unjustified** theme is reclassified as
        **snag-justified** when a stored snag description shows the idea is what
        lets the answer avoid a snag.
        """
        common: dict[str, Any] = {}
        differing: dict[str, tuple[Any, Any]] = {}
        a_unique: dict[str, Any] = {}
        b_unique: dict[str, Any] = {}

        for dim in set(a.themes) | set(b.themes):
            a_val, b_val = a.themes.get(dim), b.themes.get(dim)
            if a_val is not None and b_val is not None:
                if a_val == b_val:
                    common[dim] = a_val
                else:
                    differing[dim] = (a_val, b_val)
            elif a_val is not None:
                a_unique[dim] = a_val
            else:
                b_unique[dim] = b_val

        return {
            "common_themes": common,
            "differing_themes": differing,
            "a_unique_themes": a_unique,
            "b_unique_themes": b_unique,
            "a_unjustified_themes": self._classify_unjustified(a),
            "b_unjustified_themes": self._classify_unjustified(b),
            "a_coherent": a.is_coherent,
            "b_coherent": b.is_coherent,
            "a_quality": a.quality,
            "b_quality": b.quality,
            "a_rule": a.top_rule_description,
            "b_rule": b.top_rule_description,
            "a_abstractness": a.top_rule_abstractness,
            "b_abstractness": b.top_rule_abstractness,
            "preferred": self._preferred_answer(a, b),
        }

    def _classify_unjustified(
        self, answer: AnswerDescription
    ) -> dict[str, str]:
        """Split an answer's unjustified themes into unjustified / snag-justified.

        §4.7.3: "the presence of a snag description in memory involving exactly
        the same letter-strings and rule as some answer description indicates
        that the program has tried this problem on its own before — using
        exactly the same rule — and run into a snag."  That is what makes
        ``aaabccc`` justified-after-all while ``aaabaaa`` is not.
        """
        problem = answer.problem[:3]
        snag_seen = any(
            tuple(s.problem) == problem
            and s.description == answer.top_rule_description
            for s in self.snags
        )
        verdict = "snag_justified" if snag_seen else "unjustified"
        return {dim: verdict for dim in answer.unjustified_themes}

    def _preferred_answer(
        self, a: AnswerDescription, b: AnswerDescription
    ) -> dict[str, Any]:
        """Which answer the program prefers, and why.

        §4.7.4 gives the reasons in priority order: no unjustified ideas, then
        coherence, then a richer set of ideas, then quality.
        """
        if len(a.unjustified_themes) != len(b.unjustified_themes):
            winner = a if len(a.unjustified_themes) < len(b.unjustified_themes) else b
            return {"answer": winner.problem[3], "reason": "fewer_unjustified"}
        if a.is_coherent != b.is_coherent:
            winner = a if a.is_coherent else b
            return {"answer": winner.problem[3], "reason": "one_incoherent"}
        if len(a.themes) != len(b.themes):
            winner = a if len(a.themes) > len(b.themes) else b
            return {"answer": winner.problem[3], "reason": "richer_ideas"}
        if a.quality != b.quality:
            winner = a if a.quality > b.quality else b
            return {"answer": winner.problem[3], "reason": "different_quality"}
        return {"answer": None, "reason": "same_quality"}

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
