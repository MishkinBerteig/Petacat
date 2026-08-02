"""Commentary log — dual-voice event-driven commentary accumulator.

Matches the Scheme *comment-window* (commentary-graphics.ss): stores
both an Eliza (conversational) and a technical paragraph for every
cognitive event, so toggling Eliza mode re-renders all text instantly
without regeneration.

Scheme source: commentary-graphics.ss, answers.ss, trace.ss, jootsing.ss
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from server.engine.answer_comparison import _fill


def _reporting(templates: dict[str, Any] | None, key: str) -> dict[str, Any]:
    """One ``answer_reporting`` block from the seed data.

    Every ``emit_*`` helper below renders from these templates, so the paragraphs a run
    produces are editable in the same place as the comparison prose.  ``templates`` is
    whatever the caller's ``MetadataProvider`` holds — the database, in a served run;
    the seed data serves callers that have no provider.
    """
    from server.engine.metadata import default_commentary_templates

    resolved = templates or default_commentary_templates()
    section = (resolved.get("answer_reporting") or {}).get(key)
    return section if isinstance(section, dict) else {}


@dataclass
class CommentaryParagraph:
    """One commentary entry with dual-voice variants."""

    eliza_text: str
    technical_text: str
    codelet_count: int = 0
    event_type: str = ""


@runtime_checkable
class CommentaryWriter(Protocol):
    """Where commentary goes — an injected dependency.

    Commentary is output: the engine calls ``emit_*``, which calls ``add_comment``.
    ``render``, ``get_paragraphs`` and ``count`` serve the API.

    The engine emits unconditionally. Every mode supplies a real
    :class:`CommentaryLog`, so a Run narrates itself identically in each, and
    ``GET /commentary`` answers with that narration in every mode.
    """

    def add_comment(
        self,
        eliza_text: str,
        technical_text: str,
        codelet_count: int = 0,
        event_type: str = "",
    ) -> None: ...

    def render(self, eliza_mode: bool = False) -> str: ...

    def get_paragraphs(self) -> list[CommentaryParagraph]: ...

    def clear(self) -> None: ...

    @property
    def count(self) -> int: ...


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

    Scheme: answers.ss:61-75.  The exclamation mark is reserved for the two ends of the
    scale — ``(or (< quality 30) (>= quality 85))`` at ``answers.ss:68`` — so the
    program is emphatic about an answer it thinks is terrible as well as one it thinks
    is great.
    """
    section = _reporting(templates, "discovery")
    also = section.get("also", "") if prior_answer_count > 0 else ""
    punctuation = "!" if (quality < 30 or quality >= 85) else "."
    suffix = "quality_suffix_bad" if quality < 60 else "quality_suffix_good"

    eliza = _fill(
        section.get("eliza_prefix", ""), answer=answer_string, also=also
    ) + _fill(
        section.get(suffix, ""),
        quality_phrase=quality_phrase,
        punctuation=punctuation,
    )
    technical = _fill(
        section.get("technical", ""), answer=answer_string, quality=f"{quality:.0f}"
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
    section = _reporting(templates, "justify_success")
    if quality < 60:
        suffix = "quality_suffix_bad"
    elif quality >= 85:
        suffix = "quality_suffix_extreme"
    else:
        suffix = "quality_suffix_normal"

    eliza = section.get("eliza_prefix", "") + _fill(
        section.get(suffix, ""), quality_phrase=quality_phrase
    )
    technical = _fill(section.get("technical", ""), quality=f"{quality:.0f}")
    commentary.add_comment(
        eliza, technical, codelet_count=codelet_count, event_type="answer_justified"
    )


def emit_answer_unjustified(
    commentary: CommentaryLog,
    slippage_names: str,
    codelet_count: int,
    templates: dict[str, Any] | None = None,
    slippage_count: int = 1,
) -> None:
    """Emit commentary when an answer has unjustified slippages.

    Scheme: answers.ss:36-45.  "slippage" is pluralised on the number of slippages.
    """
    section = _reporting(templates, "unjustified_slippages")
    plural = "" if slippage_count == 1 else "s"
    eliza = _fill(
        section.get("eliza", ""), slippage_names=slippage_names, plural=plural
    )
    technical = _fill(
        section.get("technical", ""), slippage_names=slippage_names, plural=plural
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
    templates: dict[str, Any] | None = None,
) -> None:
    """Emit commentary when the system gives up.

    Scheme: answers.ss:86-92.
    """
    section = _reporting(templates, "give_up")
    commentary.add_comment(
        section.get("eliza", ""),
        section.get("technical", ""),
        codelet_count=codelet_count,
        event_type="give_up",
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


# ---------------------------------------------------------------------------
# Answer comparison and explanation  (§4.7.3 – §4.7.4)
#
# "What is interesting is Metacat's deeper capacity to recognize subtle
# similarities and differences between answers on the basis of the common
# themes, the differing themes, the unique themes, the unjustified themes, the
# snag-justified themes, and the rules that constitute answer descriptions."
#
# The English is assembled from seed_data/commentary_templates.json.  The assembly
# itself lives in server/engine/answer_comparison.py, which is the port of
# answers.ss:336-425 and answers.ss:434-882; these two entry points are here because
# this is the module the rest of the program asks for commentary.
# ---------------------------------------------------------------------------


def describe_answer_comparison(
    answer_a: Any,
    answer_b: Any,
    memory: Any = None,
    templates: dict[str, Any] | None = None,
    meta: Any = None,
) -> dict[str, Any]:
    """Explain, in English, how two answers relate and which is preferred.

    Scheme: ``get-answer-comparison-text`` (``answers.ss:434-882``).

    ``memory`` is needed because two of MetaCat's distinctions are not properties of
    the answers at all but of what else the program remembers: whether an unjustified
    theme is snag-justified (§4.7.3) and what the snag was.  Pass it and the caveats
    appear; leave it out and the comparison is the theme-and-rule one.
    """
    from server.engine.answer_comparison import compare_answers_text

    return compare_answers_text(answer_a, answer_b, memory, templates, meta)


def describe_answer(
    answer: Any,
    memory: Any = None,
    templates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Say what a single answer is based on, in both voices.

    Scheme: ``explain`` (``answers.ss:310-333``).  MetaCat offers this alongside
    comparison: it is what the program says about one answer on its own, rendered from
    the seed data's ``answer_explanation`` section.
    """
    from server.engine.answer_comparison import explain_answer

    return explain_answer(answer, memory, templates)
