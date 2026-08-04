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

    # §4.7.1 / ``memory.ss:117``: an answer description stores the rules' *clause
    # lists*, not just their English transcription.  They are what ``answer-present?``
    # (``memory.ss:190-196``) compares, so without them the duplicate-answer guard
    # cannot be written.  ``server/engine/rules.py:rule_signature`` produces them in a
    # form that survives being persisted and read back.
    top_rule_signature: list | None = None
    bottom_rule_signature: list | None = None

    #: ``average-theme-abstractness`` (``answers.ss:885-892``), computed when the
    #: description is built because it needs the Slipnet's conceptual depths, which a
    #: stored description no longer has access to.
    theme_abstractness: float = 0.0

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

        Scheme: ``answer-incoherent?`` (``answers.ss:909-916``)::

            (and (> theme-abstractness 50)
                 (< rule-abstractness theme-abstractness)
                 (> abstractness-difference 25))

        The test is **asymmetric** and **directional**: an answer is incoherent only
        when its themes are abstract and its rule is markedly *more literal*.  A
        previous version counted ``identity`` as maximally abstract (the Scheme scores
        it 0, the least abstract of all) and compared with ``abs(...) <= 50``, which
        made the canonical *coherent* literal answer ``xyd`` come out incoherent and
        could call an answer incoherent for having too abstract a rule.
        """
        theme_abstractness = self.theme_abstractness
        rule_abstractness = self.top_rule_abstractness
        # With no themes there is nothing to be dissonant *with*.
        if theme_abstractness <= 0.0:
            return True
        incoherent = (
            theme_abstractness > 50.0
            and rule_abstractness < theme_abstractness
            and (theme_abstractness - rule_abstractness) > 25.0
        )
        return not incoherent


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

    # ``memory.ss:289-291`` stores the snag's **rule clause lists**, and ``equal?``
    # (``memory.ss:336-340``) compares them with ``rule-clause-lists-equal?`` — the
    # three problem strings plus a *structural* comparison of the rule.  Petacat
    # compared the rule's English transcription, which collides two ways: two
    # structurally different rules can transcribe to the same prose, and every rule
    # that fails to transcribe reads "Unknown transformation" and so matches every
    # other such rule.  ``rules.py:rule_signature`` documents exactly that hazard for
    # answers; the snag path had it open.
    rule_signature: list | None = None
    translated_rule_signature: list | None = None

    def equal(
        self, problem: tuple[str, str, str], signature: list | None
    ) -> bool:
        """Scheme: ``equal?`` on a snag description (``memory.ss:336-340``).

        A ``None`` signature means the clause list was never recorded rather than that
        the rule was empty, and two unrecorded rules are not thereby the same rule —
        the same reservation :meth:`EpisodicMemory._answers_equal` makes.
        """
        if tuple(self.problem) != tuple(problem):
            return False
        if self.rule_signature is None or signature is None:
            return False
        return self.rule_signature == signature


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

    def snag_present(
        self, problem: tuple[str, str, str], rule: Any = None
    ) -> bool:
        """Has this rule already run aground on this problem?

        Scheme: ``snag-present?`` (``memory.ss:78-83``) — the three problem strings and
        the rule's clause list, compared structurally.  Consulted before a snag
        description is stored, so one impasse is recorded once however many times the
        run rediscovers it.
        """
        from server.engine.rules import rule_signature

        signature = rule_signature(rule)
        return any(snag.equal(problem, signature) for snag in self.snags)

    def answer_present(
        self,
        problem: tuple[str, str, str, str],
        top_rule: Any = None,
        bottom_rule: Any = None,
    ) -> bool:
        """Has this exact answer, reached this exact way, already been found?

        Scheme: ``memory.ss:90-97`` / ``memory.ss:190-196``.  Two answers are the same
        episode when the three problem strings agree, the answer letters agree, **and**
        both rules' clause lists agree structurally.  The rules matter: the same answer
        string reached by a different rule is a different idea, and MetaCat stores it
        as a separate episode.

        This is the one place where Episodic Memory reaches back into cognition.
        ``answers.ss:982`` consults it before reporting and fizzles on a hit — "Already
        found this answer" — so the search carries on toward a *different* answer
        instead of rediscovering one already in memory.  The author documents the
        consequence in ``Metacat/help.txt:29``: rerunning with the same seed after an
        answer will not produce that answer again.
        """
        from server.engine.rules import rule_signature

        top_sig = rule_signature(top_rule)
        bottom_sig = rule_signature(bottom_rule)
        for past in self.answers:
            if tuple(past.problem) != tuple(problem):
                continue
            if past.top_rule_signature != top_sig:
                continue
            if past.bottom_rule_signature != bottom_sig:
                continue
            return True
        return False

    def find_remindings(
        self,
        new_desc: AnswerDescription,
        distance_threshold: float = 5.0,
        meta: Any = None,
    ) -> list[AnswerDescription]:
        """Reactivate past answers close enough to the new one to come to mind.

        §4.7.5: "each answer description computes the distance between itself and
        the new answer description ..., updating its level of activation
        according to the distance.  If the activation level exceeds some
        threshold, Metacat will be reminded of the answer, to the extent that
        the threshold is exceeded."
        """
        remindings = []
        threshold = distance_threshold or 5.0
        for past in self.answers:
            if past is new_desc:
                continue
            distance = self.distance(new_desc, past, meta=meta)
            # ``memory.ss:212``: ``(100- (100* (min 1 (/ distance %distance-threshold%))))``
            # — reaches zero *at* the threshold rather than crossing it linearly.
            past.activation = max(
                0.0, 100.0 * (1.0 - min(1.0, distance / threshold))
            )
            # ``memory.ss:214`` reports a reminding only for a non-zero activation.
            if past.activation > 0.0:
                remindings.append(past)
        new_desc.activation = 100.0
        remindings.sort(key=lambda a: a.activation, reverse=True)
        return remindings

    def distance(
        self, a: AnswerDescription, b: AnswerDescription, meta: Any = None
    ) -> float:
        """How far apart two answers are.

        Scheme: ``calculate-answer-distance`` (``memory.ss:494-583``), which is the same
        classification ``get-answer-comparison-text`` performs (``answers.ss:455-620``)
        read as a number instead of as English.  Both are computed here from one
        :class:`~server.engine.answer_comparison.AnswerComparison`, so the distance and
        the prose can never disagree about what the two answers share.

        Five components, and the Scheme's own weights:

        1. **themes** — ``differing-dimensions + 2·unique1 + 2·unique2``
           (``memory.ss:552-555``).  A dimension both answers hold with *different*
           relations counts once; an idea one answer has and the other does not mention
           at all counts twice.
        2. **the top rule** — twice the number of concept pairs that differ *and* differ
           in conceptual depth (``memory.ss:556-565, 571``).  There is no bottom-rule
           term: ``memory.ss:558-559`` passes ``get-top-rule-clauses`` for both answers,
           and the comparison at ``answers.ss:598-599`` does the same.  The bottom rule
           is the *translation* of the top one into the target's terms, so counting it
           would count the same disagreement twice over.
        3. **abstractness**, but only as the rule term's alternative
           (``memory.ss:568-571``): when the clause lists cannot be aligned at all there
           are no pairs to count, and ``round(|Δabstractness| / 10)`` stands in.
        4. **justification** — ideas *common* to both answers that only one of them
           could justify (``memory.ss:572-574``), after the snag-justified ones have
           been subtracted and the ones already charged as differing themes excluded.
        5. **coherence** — 1 when the answers disagree about whether they hang together
           (``memory.ss:575-578``).

        The base of 1 (``memory.ss:580``) guarantees the invariant the Scheme documents
        at ``memory.ss:490-493``: two identical answers are 0 apart and two non-identical
        answers are always at least 1 apart.

        ``meta`` supplies the conceptual depths component 2 filters on.  With none, the
        depths come from ``seed_data/slipnet_nodes.json`` — the filter is not optional,
        because without it ``leftmost`` against ``rightmost`` would read as a difference
        in level when the two sit at the same depth.
        """
        from server.engine.answer_comparison import AnswerComparison

        # ``memory.ss:496-497``: identical answers are zero apart, before anything else
        # is computed.
        if self._answers_equal(a, b):
            return 0.0

        comparison = AnswerComparison(a, b, self, None, meta)

        distance = 1.0

        # 1. Differing themes count once; themes unique to one side count double.
        distance += float(
            len(comparison.differing_dimensions)
            + 2 * len(comparison.unique1)
            + 2 * len(comparison.unique2)
        )

        # 2/3. The *top* rules, and abstractness only as their alternative.
        # ``comparison.num_rule_differences`` is ``count_rule_differences`` over
        # ``compare_rule_signatures``, so it is already depth-filtered and already −1
        # for clause lists that cannot be aligned.
        if comparison.num_rule_differences == -1:
            # Python's ``round`` breaks ties to even, as Chez's does on the exact
            # rational ``(/ (abs (- a1 a2)) 10)``: a gap of 25 is 2, not 3.
            distance += float(
                round(abs(a.top_rule_abstractness - b.top_rule_abstractness) / 10.0)
            )
        else:
            distance += 2.0 * comparison.num_rule_differences

        # 4. Ideas common to both answers that only one of them could justify.
        distance += float(
            len(comparison.common_a_only_unjustified)
            + len(comparison.common_b_only_unjustified)
        )

        # 5. Coherence mismatch.
        if a.is_coherent != b.is_coherent:
            distance += 1.0

        return distance

    @staticmethod
    def _answers_equal(a: AnswerDescription, b: AnswerDescription) -> bool:
        """Scheme: ``answers-equal?`` (``memory.ss:182-196``).

        The four strings and *both* rules' clause lists.  A ``None`` signature means the
        clause list was never recorded rather than that the rule was empty, and two
        unrecorded rules are not thereby known to be the same rule — so an answer whose
        top rule was not captured is never declared identical to another.
        """
        if tuple(a.problem) != tuple(b.problem):
            return False
        if a.top_rule_signature is None or b.top_rule_signature is None:
            return False
        return (
            a.top_rule_signature == b.top_rule_signature
            and a.bottom_rule_signature == b.bottom_rule_signature
        )

    def get_equivalent_snag(
        self, answer: AnswerDescription
    ) -> SnagDescription | None:
        """The snag episode this answer's own attempt ran into, if there was one.

        Scheme: ``get-equivalent-snag`` (``memory.ss``), consulted from
        ``answers.ss:290`` and ``answers.ss:304``.  §4.7.3: "the presence of a snag
        description in memory involving exactly the same letter-strings and rule as
        some answer description indicates that the program has tried this problem on
        its own before — using exactly the same rule — and run into a snag."
        """
        problem = tuple(answer.problem[:3])
        for snag in self.snags:
            # ``memory.ss:84-89`` passes ``get-top-rule-clauses``, so the match is the
            # same structural one ``snag_present`` makes — not the English prose.
            if snag.equal(problem, answer.top_rule_signature):
                return snag
        return None

    def compare_answers(
        self,
        a: AnswerDescription,
        b: AnswerDescription,
        templates: dict[str, Any] | None = None,
        meta: Any = None,
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

        The classification is delegated to
        :class:`server.engine.answer_comparison.AnswerComparison`, which is the port of
        ``get-answer-comparison-text``'s ``let*`` block (``answers.ss:455-543``).  The
        English MetaCat speaks *is* this classification, so the prose and the structured
        comparison read the same variables.

        Note that the themes compared are the answer's **justified and unjustified
        themes together** (``answers.ss:456-464``): an idea the program could not justify
        is still an idea the answer rests on, and §4.7.3's ``aaabccc``/``aaabaaa``
        example turns entirely on comparing two answers whose *unjustified* themes are
        what they share.
        """
        from server.engine.answer_comparison import AnswerComparison, _lookup
        from server.engine.metadata import default_commentary_templates

        comparison = AnswerComparison(
            a, b, self, templates or default_commentary_templates(), meta
        )
        verdict = comparison.verdict()

        return {
            "common_themes": dict(comparison.common_themes),
            "differing_themes": {
                dimension: (
                    (_lookup(dimension, comparison.all_themes1) or (dimension, None))[1],
                    (_lookup(dimension, comparison.all_themes2) or (dimension, None))[1],
                )
                for dimension in comparison.differing_dimensions
            },
            "a_unique_themes": dict(comparison.unique1),
            "b_unique_themes": dict(comparison.unique2),
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
            "preferred": {
                "answer": verdict.get("answer"),
                "reason": verdict.get("criterion", ""),
            },
        }

    def _classify_unjustified(
        self, answer: AnswerDescription
    ) -> dict[str, str]:
        """Split an answer's unjustified themes into unjustified / snag-justified.

        §4.7.3: what makes ``aaabccc`` justified-after-all while ``aaabaaa`` is not is
        not merely that *a* snag exists, but that the answer holds an idea the snag
        episode did not — "the differences between the themes involved in the snag and
        the themes involved in the answer provide a strong clue as to how ... the snag
        is avoided".  ``get-snag-justified-themes`` (``answers.ss:285-299``) subtracts
        the snag's own theme-pattern before intersecting with the unjustified themes, so
        only an idea the snag episode lacked counts as having avoided it.
        """
        from server.engine.answer_comparison import snag_justified_themes

        snag_justified = {
            dimension for dimension, _ in snag_justified_themes(answer, self)
        }
        return {
            dimension: (
                "snag_justified" if dimension in snag_justified else "unjustified"
            )
            for dimension in answer.unjustified_themes
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

    def clear_activations(self) -> None:
        """Zero every stored answer's reminding activation.

        Scheme: ``clear-activations`` (``memory.ss``), called from ``init-mcat``
        (``run.ss:212``).  An activation says how strongly *this* run is reminded of a
        past answer, so a new run starts reminded of nothing.
        """
        for answer in self.answers:
            answer.activation = 0.0

    def clear(self) -> None:
        """Delete all answer and snag descriptions. Matches Scheme clearmem.

        The identifier counters reset too.  Leaving them running meant that after a
        clear the next answer took an id that no longer lined up with anything, and a
        rehydrate-after-clear produced a memory whose ids disagreed with the rows they
        came from — so ``/api/memory/compare`` could resolve an id to the wrong answer.
        """
        self.answers.clear()
        self.snags.clear()
        self.ids = IdAllocator()

    def __repr__(self) -> str:
        return f"EpisodicMemory({len(self.answers)} answers, {len(self.snags)} snags)"
