"""Answer finding, reporting, and commentary generation.

Scheme source: answers.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.engine.memory import AnswerDescription

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG
    from server.engine.rules import Rule
    from server.engine.workspace import Workspace


class AnswerResult:
    """Result of an answer-finding attempt."""

    def __init__(
        self,
        answer_string: str | None = None,
        top_rule: Rule | None = None,
        bottom_rule: Rule | None = None,
        quality: float = 0.0,
        temperature: float = 100.0,
        snag: bool = False,
        snag_reason: str = "",
    ) -> None:
        self.answer_string = answer_string
        self.top_rule = top_rule
        self.bottom_rule = bottom_rule
        self.quality = quality
        self.temperature = temperature
        self.snag = snag
        self.snag_reason = snag_reason

    @property
    def found(self) -> bool:
        return self.answer_string is not None

    def __repr__(self) -> str:
        if self.found:
            return f"AnswerResult('{self.answer_string}', quality={self.quality:.0f})"
        return f"AnswerResult(snag={self.snag})"


def compute_answer_quality(
    rule_quality: float,
    temperature: float,
    meta: MetadataProvider,
) -> float:
    """Compute answer quality from rule quality and temperature.

    Scheme: trace.ss:392-402.
    quality = weighted_average([rule_quality, 100-temp], [60, 40])
    """
    rw = meta.get_formula_coeff("answer_quality_rule_weight")  # 60
    tw = meta.get_formula_coeff("answer_quality_temperature_weight")  # 40
    total = rw + tw
    if total == 0:
        return rule_quality
    return round((rule_quality * rw + (100.0 - temperature) * tw) / total)


def get_quality_phrase(quality: float, meta: MetadataProvider) -> str:
    """Get a natural language phrase for the quality level.

    Scheme: answers.ss:95-105.
    """
    phrases = meta.commentary_templates.get("answer_quality_phrases", [])
    for entry in phrases:
        max_q = entry.get("max_quality")
        if max_q is None or quality < max_q:
            return entry.get("phrase", "unknown")
    return "great"


def create_answer_description(
    workspace: Workspace,
    top_rule: Rule | None,
    bottom_rule: Rule | None,
    quality: float,
    temperature: float,
    themes: dict[str, Any],
) -> AnswerDescription:
    """Create an AnswerDescription for episodic memory storage."""
    answer_text = workspace.answer_string.text if workspace.answer_string else ""
    return AnswerDescription(
        problem=(
            workspace.initial_string.text,
            workspace.modified_string.text,
            workspace.target_string.text,
            answer_text,
        ),
        top_rule_description=top_rule.transcribe_to_english() if top_rule else "",
        bottom_rule_description=bottom_rule.transcribe_to_english() if bottom_rule else "",
        top_rule_quality=top_rule.quality if top_rule else 0.0,
        bottom_rule_quality=bottom_rule.quality if bottom_rule else 0.0,
        quality=quality,
        temperature=temperature,
        themes=themes,
        unjustified_slippages=[],
    )
