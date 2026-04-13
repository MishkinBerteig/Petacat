"""Commentary log — dual-voice event-driven commentary accumulator.

Matches the Scheme *comment-window* (commentary-graphics.ss): stores
both an Eliza (conversational) and a technical paragraph for every
cognitive event, so toggling Eliza mode re-renders all text instantly
without regeneration.

Scheme source: commentary-graphics.ss, answers.ss, trace.ss, jootsing.ss
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommentaryParagraph:
    """One commentary entry with dual-voice variants."""

    eliza_text: str
    technical_text: str
    codelet_count: int = 0
    event_type: str = ""


class CommentaryLog:
    """Accumulated commentary paragraphs for a single run.

    Every call to ``add_comment`` stores both an Eliza-voice and a
    technical-voice paragraph.  ``render(eliza_mode)`` concatenates
    the appropriate voice.
    """

    def __init__(self) -> None:
        self._paragraphs: list[CommentaryParagraph] = []

    def add_comment(
        self,
        eliza_text: str,
        technical_text: str,
        codelet_count: int = 0,
        event_type: str = "",
    ) -> None:
        self._paragraphs.append(
            CommentaryParagraph(eliza_text, technical_text, codelet_count, event_type)
        )

    def render(self, eliza_mode: bool = False) -> str:
        parts = []
        for p in self._paragraphs:
            parts.append(p.eliza_text if eliza_mode else p.technical_text)
        return "\n\n".join(parts)

    def get_paragraphs(self) -> list[CommentaryParagraph]:
        return list(self._paragraphs)

    def clear(self) -> None:
        self._paragraphs.clear()

    @property
    def count(self) -> int:
        return len(self._paragraphs)


# ---- Commentary generation helpers ----------------------------------------


def emit_new_problem(
    commentary: CommentaryLog,
    initial: str,
    modified: str,
    target: str,
    answer: str | None,
    justify_mode: bool,
) -> None:
    """Emit the opening 'new problem' commentary.

    Scheme: commentary-graphics.ss:61-83, run.ss:257-258.
    """
    if justify_mode and answer:
        eliza = (
            f'Let\'s see... "{initial}" changes to "{modified}", '
            f'and "{target}" changes to "{answer}".  Hmm...'
        )
        technical = (
            f'Beginning justify run:  "{initial}" changes to "{modified}", '
            f'and "{target}" changes to "{answer}"...'
        )
    else:
        eliza = (
            f'Okay, if "{initial}" changes to "{modified}", '
            f'what does "{target}" change to?  Hmm...'
        )
        technical = (
            f'Beginning run:  If "{initial}" changes to "{modified}", '
            f'what does "{target}" change to?'
        )
    commentary.add_comment(eliza, technical, codelet_count=0, event_type="new_problem")


def emit_answer_discovered(
    commentary: CommentaryLog,
    answer_string: str,
    quality: float,
    quality_phrase: str,
    temperature: float,
    codelet_count: int,
    prior_answer_count: int,
    templates: dict[str, Any],
) -> None:
    """Emit commentary when an answer is discovered (non-justify mode).

    Scheme: answers.ss:61-75.
    """
    also = "also " if prior_answer_count > 0 else ""
    punct = "!" if quality >= 85 else "."

    if quality < 60:
        eliza = (
            f'The answer "{answer_string}" {also}occurs to me, '
            f"but that's {quality_phrase}{punct}"
        )
    else:
        eliza = (
            f'The answer "{answer_string}" {also}occurs to me.  '
            f"I think this answer is {quality_phrase}{punct}"
        )

    technical = (
        f'Found the answer "{answer_string}".  Answer quality = {quality:.0f}.'
    )
    commentary.add_comment(
        eliza, technical, codelet_count=codelet_count, event_type="answer_discovered"
    )


def emit_answer_justified(
    commentary: CommentaryLog,
    quality: float,
    quality_phrase: str,
    codelet_count: int,
    templates: dict[str, Any],
) -> None:
    """Emit commentary when an answer is successfully justified.

    Scheme: answers.ss:47-59.
    """
    if quality < 60:
        eliza = (
            f"Aha!  I see why this answer makes sense, "
            f"but it's a {quality_phrase} answer, in my opinion."
        )
    elif quality >= 85:
        eliza = (
            f"Aha!  I see why this answer makes sense.  "
            f"I think it's a {quality_phrase} answer!"
        )
    else:
        eliza = (
            f"Aha!  I see why this answer makes sense.  "
            f"I think it's a {quality_phrase} answer."
        )
    technical = f"Successfully justified answer.  Answer quality = {quality:.0f}."
    commentary.add_comment(
        eliza, technical, codelet_count=codelet_count, event_type="answer_justified"
    )


def emit_answer_unjustified(
    commentary: CommentaryLog,
    slippage_names: str,
    codelet_count: int,
) -> None:
    """Emit commentary when an answer has unjustified slippages.

    Scheme: answers.ss:36-45.
    """
    eliza = (
        "Okay, I'm stumped.  This answer makes no sense to me.  "
        f"I see no way to make the necessary {slippage_names} slippage(s) here."
    )
    technical = (
        f"Run terminated.  Unable to make the necessary "
        f"{slippage_names} slippage(s)."
    )
    commentary.add_comment(
        eliza, technical, codelet_count=codelet_count, event_type="answer_unjustified"
    )


def emit_snag(
    commentary: CommentaryLog,
    explanation: str,
    snag_count: int,
    codelet_count: int,
) -> None:
    """Emit commentary when a snag is encountered.

    Scheme: answers.ss:1164-1172.
    """
    again = " again" if snag_count > 1 else ""
    eliza = (
        f"Uh-oh, I seem to have run into a little problem{again}.  "
        f"{explanation}."
    )
    another = "another" if snag_count > 1 else "a"
    technical = f"Hit {another} snag:  {explanation}."
    commentary.add_comment(
        eliza, technical, codelet_count=codelet_count, event_type="snag"
    )


def emit_give_up(
    commentary: CommentaryLog,
    codelet_count: int,
) -> None:
    """Emit commentary when the system gives up.

    Scheme: answers.ss:86-92.
    """
    eliza = "Excuse me -- I think I'll go get some more punch."
    technical = "Run terminated."
    commentary.add_comment(
        eliza, technical, codelet_count=codelet_count, event_type="give_up"
    )


def emit_clamp_activate(
    commentary: CommentaryLog,
    clamp_type: str,
    clamp_count: int,
    codelet_count: int,
) -> None:
    """Emit commentary when a clamp is activated.

    Scheme: trace.ss:592-618.
    """
    another = clamp_count > 1

    if clamp_type == "rule_codelet_clamp":
        eliza = "I'll just have to try a little harder..."
        technical = "Clamping rule-codelet pattern..."
    elif clamp_type == "snag_response_clamp":
        eliza = (
            "All right, I've had enough of this!  "
            "Let's try something different for a change..."
        )
        technical = "Clamping snag-response pattern..."
    elif clamp_type == "justify_clamp":
        idea = "another" if another else "an"
        eliza = f"Aha!  I have {idea} idea..."
        technical = "Clamping justify pattern..."
    elif clamp_type == "manual_clamp":
        suggestion = "another interesting" if another else "that"
        eliza = f"Thank you for {suggestion} suggestion!  Let me think about it..."
        technical = "Clamping manual pattern..."
    else:
        eliza = "Hmm, let me reconsider..."
        technical = f"Clamping {clamp_type} pattern..."

    commentary.add_comment(
        eliza, technical, codelet_count=codelet_count, event_type="clamp_activate"
    )


def _progress_amount_phrase(progress: float) -> str:
    """Scheme: trace.ss:212-218."""
    if progress < 10:
        return "no significant"
    elif progress < 30:
        return "a small amount of"
    elif progress < 60:
        return "a moderate amount of"
    elif progress < 80:
        return "a good deal of"
    else:
        return "a great deal of"


def _progress_adjective_phrase(progress: float) -> str:
    """Scheme: trace.ss:220-226."""
    if progress < 10:
        return "a bad"
    elif progress < 30:
        return "a so-so"
    elif progress < 60:
        return "a decent"
    elif progress < 80:
        return "a pretty good"
    else:
        return "an excellent"


def emit_clamp_expired(
    commentary: CommentaryLog,
    clamp_type: str,
    progress: float,
    codelet_count: int,
) -> None:
    """Emit commentary when a clamp period expires.

    Scheme: trace.ss:129-173.
    """
    amount = _progress_amount_phrase(progress)
    adjective = _progress_adjective_phrase(progress)

    if clamp_type == "rule_codelet_clamp":
        eliza = (
            f"Well, my latest effort to think up new rules resulted in "
            f"{amount} progress.  Guess it was {adjective} idea, in retrospect."
        )
    elif clamp_type == "snag_response_clamp":
        eliza = (
            f"My attempt to try a new approach resulted in "
            f"{amount} progress.  Guess it was {adjective} idea, in retrospect."
        )
    elif clamp_type == "manual_clamp":
        eliza = (
            f"That last suggestion of yours resulted in "
            f"{amount} progress.  Guess it was {adjective} idea, in retrospect."
        )
    else:
        eliza = (
            f"That effort resulted in {amount} progress.  "
            f"Guess it was {adjective} idea, in retrospect."
        )

    clamp_label = clamp_type.replace("_", "-").removesuffix("-clamp")
    technical = (
        f"Unclamping patterns.  Progress achieved by {clamp_label} clamp = "
        f"{progress:.0f}."
    )
    commentary.add_comment(
        eliza, technical, codelet_count=codelet_count, event_type="clamp_expired"
    )


def emit_jootsing(
    commentary: CommentaryLog,
    jootsing_type: str,
    codelet_count: int,
) -> None:
    """Emit commentary when jootsing occurs.

    Scheme: jootsing.ss:173-186, 315-325.
    """
    if jootsing_type == "rule_codelet":
        eliza = "I just can't seem to come up with any better rules."
        technical = "Jootsing from unsuccessful rule-codelet clamps."
    elif jootsing_type == "snag_response":
        eliza = "This is getting boring.  I can't think of anything else to try."
        technical = "Jootsing from unsuccessful snag-response clamps."
    elif jootsing_type == "frustrated":
        eliza = (
            "I'm getting frustrated.  I still don't see a good way to "
            "describe how the strings change."
        )
        technical = "No satisfactory rules found for describing the transformation."
    else:
        eliza = "I think I need to try a completely different approach."
        technical = f"Jootsing: {jootsing_type}."

    commentary.add_comment(
        eliza, technical, codelet_count=codelet_count, event_type="jootsing"
    )


def emit_reminding(
    commentary: CommentaryLog,
    answer_text: str,
    problem_text: str,
    strength: float,
    codelet_count: int,
) -> None:
    """Emit commentary when a past answer is reminded.

    Scheme: memory.ss:214-229.
    """
    if strength > 70:
        how = "strongly reminds me"
    elif strength > 30:
        how = "reminds me somewhat"
    else:
        how = "vaguely reminds me"

    eliza = (
        f'This answer {how} of the answer "{answer_text}" '
        f'to the problem "{problem_text}".'
    )
    technical = (
        f'This answer is reminiscent of the answer "{answer_text}" '
        f'to the problem "{problem_text}".  '
        f"Reminding strength = {strength:.0f}."
    )
    commentary.add_comment(
        eliza, technical, codelet_count=codelet_count, event_type="reminding"
    )
