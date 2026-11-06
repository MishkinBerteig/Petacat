"""Justification mode -- validate given answers.

When given all four strings (including the answer), Metacat works to
justify the given answer rather than discover one.  It selects a
supported rule, translates it via vertical bridge slippages, attempts
to find matching rules of the other type, and if no match is found,
clamps rules to force focused exploration or attempts rule unification.

Scheme source: justify.ss
"""

from __future__ import annotations

from server.engine.verbose import round_to_100ths

import logging
from typing import TYPE_CHECKING, Any

from server.engine.images import ImageFailure
from server.engine.metadata import require_meta
from server.engine.roles import Absent
from server.engine.run_binding import constants
from server.engine.rules import (
    Rule, RuleClause, RuleChange, _TranslationFailure, rules_equal,
)
from server.engine.run_binding import vocab
from server.engine.trace import ClampEvent, clamp_type_codelet_patterns

if TYPE_CHECKING:
    from server.engine.concept_mappings import ConceptMapping
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG
    from server.engine.slipnet import Slipnet, SlipnetNode
    from server.engine.themes import Themespace
    from server.engine.trace import TemporalTrace
    from server.engine.workspace import Workspace

logger = logging.getLogger(__name__)

#: What justify mode treats as "this rule cannot be carried over": the engine's own failures
#: (a rule that cannot be applied, a translation that cannot be made).  Anything else is a bug
#: and is raised, not read as an ordinary "could not translate".
_ENGINE_FAILURES = (ImageFailure, _TranslationFailure)


def _log_failure(what: str, slipnet: Slipnet, error: Exception) -> None:
    """Say why a rule could not be carried over, naming the roles the configuration lacks
    (a missing role is the usual reason a clause cannot be built)."""
    unbound = [name for name, bound in slipnet.roles.items() if not bound]
    logger.info(
        "justify: %s failed (%s: %s); roles unbound in this configuration: %s",
        what, type(error).__name__, error, ", ".join(unbound) or "none",
    )


# ============================================================================
#  Public result types  (backward compatible with existing code)
# ============================================================================


class JustificationResult:
    """Result of a justification attempt."""

    def __init__(
        self,
        justified: bool = False,
        top_rule: Rule | None = None,
        bottom_rule: Rule | None = None,
        quality: float = 0.0,
        explanation: str = "",
        *,
        supporting_vertical_bridges: list[Any] | None = None,
        supporting_groups: list[Any] | None = None,
        slippage_log: list[Any] | None = None,
        unjustified_slippages: list[Any] | None = None,
        action: str = "",
        clamp_event: ClampEvent | None = None,
        translation: Any = None,
    ) -> None:
        #: The ``TranslationResult`` of the translation this justification rests on
        #: (``justify.ss:46-50``): its slippage log, supporting vertical bridges,
        #: vertical-mapping groups and the reference objects of both rules.
        self.translation = translation
        self.justified = justified
        self.top_rule = top_rule
        self.bottom_rule = bottom_rule
        self.quality = quality
        self.explanation = explanation
        self.supporting_vertical_bridges = supporting_vertical_bridges or []
        self.supporting_groups = supporting_groups or []
        self.slippage_log = slippage_log or []
        self.unjustified_slippages = unjustified_slippages or []
        self.action = action
        self.clamp_event = clamp_event

    def __repr__(self) -> str:
        if self.justified:
            return f"Justified(quality={self.quality:.0f})"
        return f"NotJustified(action={self.action!r})"


# ============================================================================
#  Main justification entry point
#  Scheme: answer-justifier codelet in justify.ss
# ============================================================================


def attempt_justification(
    workspace: Workspace,
    meta: MetadataProvider,
    rng: RNG,
    *,
    trace: TemporalTrace | None = None,
    themespace: Themespace | None = None,
    slipnet: Slipnet,
    memory: Any = None,
    codelet_count: int = 0,
    temperature: float,
    self_watching_enabled: bool,
    coderack: Any = None,
    temperature_control: Any = None,
    vlog: Any = None,
) -> JustificationResult:
    """Attempt to justify the answer by finding matching rules.

    Scheme: justify.ss answer-justifier codelet.
    Selects a supported rule, translates it using slippages from vertical
    bridges, and attempts to find or build a matching rule for the other
    string pair.  When no immediate match is found, clamps rules for
    focused exploration or attempts rule unification.
    """
    # Step 1 -- Gather all supported rules and pick one by strength
    all_supported = _get_all_supported_rules(workspace)
    if not all_supported:
        if vlog is not None:
            vlog.say("could-not-find-supported-rule")
        return JustificationResult(
            justified=False, explanation="No supported rules found"
        )

    # No floor: ``stochastic-pick-by-method ... 'get-strength`` (justify.ss:26-27)
    # leaves a worthless rule unchosen (``utilities.ss:443-448``).  A rule's strength
    # is its rank-relative quality as of the last update cycle (``rules.ss:286``,
    # ``workspace-structures.ss:40``), not its raw quality (G-J1).
    weights = [r.strength for r in all_supported]
    chosen_rule: Rule = rng.weighted_pick(all_supported, weights)
    if vlog is not None:
        vlog.say("chose-rule")
        vlog.print_object(chosen_rule)

    v = vocab()
    rule_type = chosen_rule.rule_type  # the top or the bottom rule type's name
    rule_is_top = rule_type == v.rule_type_top
    other_type_top = not rule_is_top
    # ``(tell *workspace* 'get-rules (if (eq? rule-type 'top) 'bottom 'top))``
    # (justify.ss:44-45): every rule of the other type, in list order, supported or
    # not.  (The old supported-then-built concatenation reordered the list the
    # stochastic picks draw from.)
    other_rules = _get_built_rules(workspace, top=other_type_top)

    # Step 2 -- Translate the chosen rule using vertical bridge slippages
    translation_result = _translate_rule(
        chosen_rule, workspace, slipnet, rng=rng, meta=meta
    )

    if translation_result is None and vlog is not None:
        vlog.say("could-not-translate-chosen-rule-justify")
    if translation_result is not None:
        translated_rule, slippages, supporting_vbridges = translation_result
        if vlog is not None:
            vlog.say("chosen-rule-translated")
            vlog.print_object(translated_rule, level="unscored")

        # ``justify.ss:50-51``: ref-objs1 is always the *initial*-string side and
        # ref-objs2 the target side, whichever rule was chosen.  ref-objs1 is what the
        # vacuous-translation guard below tests.
        from_string = (
            workspace.initial_string if rule_is_top else workspace.target_string
        )
        to_string = (
            workspace.target_string if rule_is_top else workspace.initial_string
        )
        from_ref_objects = _reference_objects(chosen_rule, from_string, slipnet)
        to_ref_objects = _reference_objects(translated_rule, to_string, slipnet)
        ref_objects1 = from_ref_objects if rule_is_top else to_ref_objects

        # Step 3a -- Look for a matching existing rule
        matching_rule = _find_matching_rule(other_rules, translated_rule)

        if matching_rule is not None:
            if vlog is not None:
                vlog.say("found-matching-rule")
                vlog.print_object(matching_rule)
            # Assign rule1 = top, rule2 = bottom regardless of direction
            rule1, rule2 = _order_rules(chosen_rule, matching_rule, rule_type)

            # Check memory for duplicates
            if memory is not None and _answer_already_found(
                memory, workspace, rule1, rule2
            ):
                if vlog is not None:
                    vlog.say("already-found-answer")
                return JustificationResult(
                    justified=False,
                    explanation="Already found this answer",
                )

            # ``rules.ss:219-222``: ``supported?`` is an ``andmap`` over the rule's
            # supporting bridges, so a rule resting on none is vacuously supported.
            # Requiring the list to be non-empty inverted the test for exactly those
            # rules and sent them down the clamp branch instead.
            if matching_rule.supported(workspace):
                # Matching rule is supported -- answer justified!
                return JustificationResult(
                    justified=True,
                    top_rule=rule1,
                    bottom_rule=rule2,
                    # ``trace.ss:392-396``: an answer's quality comes from the *top*
                    # rule's quality alone, weighted against the temperature by the
                    # caller.  Averaging both rules made a strong top rule and a weak
                    # bottom rule indistinguishable from two middling ones.
                    quality=rule1.quality,
                    explanation="Rules match via translation",
                    supporting_vertical_bridges=supporting_vbridges,
                    slippage_log=slippages,
                    translation=translated_rule.translation,
                )

            # Matching rule exists but is unsupported -- clamp to force it
            if vlog is not None:
                vlog.say("matching-rule-not-supported")
            return _attempt_clamp_rules(
                [chosen_rule, matching_rule],
                trace,
                themespace,
                workspace,
                slipnet,
                meta,
                codelet_count=codelet_count,
                temperature=temperature,
                self_watching_enabled=self_watching_enabled,
                coderack=coderack,
                temperature_control=temperature_control,
                concept_patterns=[_get_concept_pattern_dict(matching_rule)],
                explanation="Matching rule unsupported, clamping",
                vlog=vlog,
            )

        if vlog is not None:
            vlog.say("could-not-find-matching-rule")

        # Step 3b -- No matching rule, but translated rule works.
        #
        # ``justify.ss:88-95``: the ref-objects test is not decoration.  A bottom rule
        # can translate into a top rule that works *vacuously* — the Scheme's own
        # example is ``xqd -> xqd; mrrjjj -> mrrjjjj``, where "increase the length of
        # the j group by one" translates to "increase the length of letter j by one",
        # which applies to ``xqd -> xqd`` without referring to anything in it.
        if _translated_rule_works(
            translated_rule, workspace, slipnet, rule_type
        ) and ref_objects1:
            if vlog is not None:
                vlog.say("translated-rule-works")
            rule1, rule2 = _order_rules(
                chosen_rule, translated_rule, rule_type
            )

            if memory is not None and _answer_already_found(
                memory, workspace, rule1, rule2
            ):
                if vlog is not None:
                    vlog.say("already-found-answer")
                return JustificationResult(
                    justified=False,
                    explanation="Already found this answer",
                )

            # ``justify.ss:104-111``.  These four steps are what give the translated
            # rule anything to be supported *by*: without them ``supported?`` is asked
            # of a rule that rests on no bridges and is vacuously true — which is what
            # the ``or True`` here used to say out loud.
            translated_rule.compute_quality(meta)
            _build_translated_string(
                translated_rule, to_string, workspace, slipnet
            )
            workspace.add_rule(translated_rule)
            _monitor_new_rule(
                translated_rule, workspace, trace, meta, codelet_count, temperature
            )

            if translated_rule.supported(workspace):
                return JustificationResult(
                    justified=True,
                    top_rule=rule1,
                    bottom_rule=rule2,
                    quality=rule1.quality,
                    explanation="Translated rule works",
                    supporting_vertical_bridges=supporting_vbridges,
                    slippage_log=slippages,
                    translation=translated_rule.translation,
                )

            if vlog is not None:
                vlog.say("translated-rule-not-supported")
            return _attempt_clamp_rules(
                [chosen_rule, translated_rule],
                trace,
                themespace,
                workspace,
                slipnet,
                meta,
                codelet_count=codelet_count,
                temperature=temperature,
                self_watching_enabled=self_watching_enabled,
                coderack=coderack,
                temperature_control=temperature_control,
                concept_patterns=[_get_concept_pattern_dict(translated_rule)],
                explanation="Translated rule unsupported, clamping",
                vlog=vlog,
            )
        if vlog is not None:
            vlog.say("translated-rule-does-not-work")

    # Step 4 -- Unification section
    #   Attempt to unify chosen_rule with some other existing rule
    if vlog is not None:
        vlog.say("attempting-to-unify")
    if not other_rules:
        if vlog is not None:
            vlog.say("no-other-rules")
        return JustificationResult(
            justified=False,
            explanation="No other rules exist for unification",
        )

    # ``trace.ss:112-119``: the grace period is ``codelet-count < last-unclamp-time +
    # 100``, so the real codelet count has to be passed (a count of 0 would make the
    # comparison true forever once any clamp had been undone).
    if trace is not None and not trace.permission_to_clamp(
        self_watching_enabled=self_watching_enabled,
        codelet_count=codelet_count,
        grace_period=meta.get_param("grace_period"),
    ):
        if vlog is not None:
            vlog.say("permission-to-clamp-patterns-denied")
        return JustificationResult(
            justified=False,
            explanation="Permission to clamp denied for unification",
        )

    # Pick an other rule weighted by similarity of strength.  No floor:
    # ``(100- (abs (- strength ...)))`` (justify.ss:142-146) is used raw, so a
    # rule 100 away in quality is not a unification candidate at all
    # (``utilities.ss:443-448``).
    # ``(tell r 'get-strength)``: the stored, rank-relative strength (G-J1).
    strength = chosen_rule.strength
    other_weights = [100.0 - abs(strength - r.strength) for r in other_rules]
    other_rule: Rule = rng.weighted_pick(other_rules, other_weights)
    if vlog is not None:
        vlog.say("chose-rule-for-unification")
        vlog.print_object(other_rule)

    unifying_pattern = unify_rules(chosen_rule, other_rule, slipnet)
    if unifying_pattern is None:
        if vlog is not None:
            vlog.say("could-not-unify-rules")
        return JustificationResult(
            justified=False,
            explanation="Could not unify rules",
        )
    if vlog is not None:
        vlog.say("rules-can-be-unified")

    vertical_pattern = get_vertical_theme_pattern_to_clamp(
        unifying_pattern, slipnet, rng=rng, vlog=vlog, meta=meta
    )
    return _attempt_clamp_rules(
        [chosen_rule, other_rule],
        trace,
        themespace,
        workspace,
        slipnet,
        meta,
        codelet_count=codelet_count,
        temperature=temperature,
        self_watching_enabled=self_watching_enabled,
        coderack=coderack,
        temperature_control=temperature_control,
        vertical_pattern_override=vertical_pattern,
        concept_patterns=[
            _get_concept_pattern_dict(chosen_rule),
            _get_concept_pattern_dict(other_rule),
        ],
        explanation="Unification possible, clamping",
    )


# ============================================================================
#  Clamp rules  (Scheme: justify.ss clamp-rules)
# ============================================================================


def clamp_rules(
    rules: list[Rule],
    trace: TemporalTrace,
    themespace: Themespace,
    slipnet: Slipnet,
    workspace: Workspace,
    meta: MetadataProvider,
    *,
    vertical_theme_pattern: dict[str, Any] | None = None,
    concept_patterns: list[dict[str, Any]] | None = None,
    codelet_count: int,
    temperature: float,
    self_watching_enabled: bool,
    coderack: Any = None,
    temperature_control: Any = None,
) -> ClampEvent | None:
    """Clamp a set of rules with their theme pattern, concept pattern, and
    codelet pattern for focused exploration.

    Scheme: justify.ss ``clamp-rules``.
    Creates a ClampEvent of type ``justify_clamp``, adds it to the trace,
    and activates it.
    """
    # ``trace.ss:112-119`` again — see the note at the unification gate.
    if not trace.permission_to_clamp(
        self_watching_enabled=self_watching_enabled,
        codelet_count=codelet_count,
        grace_period=meta.get_param("grace_period"),
    ):
        return None

    # Gather clamped patterns
    clamped_theme_patterns: list[Any] = []

    # Add each rule's theme pattern
    for rule in rules:
        if rule.theme_pattern is not None:
            tp = _theme_pattern_to_dict(rule.theme_pattern, meta)
            if tp:
                clamped_theme_patterns.append(tp)

    # Add vertical theme pattern
    if vertical_theme_pattern is not None:
        clamped_theme_patterns.append(vertical_theme_pattern)
    elif themespace is not None:
        # justify.ss:163-170 clamps the vertical pattern whatever it holds: a bare
        # ``(vertical-bridge)`` still clamps the vertical theme type and switches
        # its thematic pressure on (trace.ss:1530-1536) (G-J2).
        vtp = themespace.get_dominant_theme_pattern(vocab().theme_type_vertical_bridge)
        if vtp:
            tp_dict = _theme_pattern_list_to_dict(vtp, meta)
            if tp_dict:
                clamped_theme_patterns.append(tp_dict)

    # Concept patterns.  A rule with no Slipnet nodes to speak of (an identity or
    # verbatim rule) yields an empty pattern, which clamps nothing; it is dropped here
    # rather than passed on, because ``_concept_pattern_entries`` (``trace.py``) reads a
    # dict whose ``entries`` list is empty as the *other* spelling — node name to
    # activation — and then tries to make a float of the empty list.
    clamped_concept_patterns = [
        pattern
        for pattern in (concept_patterns or [])
        if pattern and pattern.get("entries")
    ]

    # Codelet patterns: top-down + thematic (``justify.ss:167-172``).  The real urgency
    # lists, not placeholder dicts naming them: a ``{"type": ...}`` marker is inert, so
    # a justify clamp froze themes and concepts and then left the Coderack running the
    # very search that had stalled — where the whole point of the clamp is to redirect
    # it.  The thematic pattern posts thematic-bridge-scouts at 91, which is how the
    # clamped themes get acted on at all.
    clamped_codelet_patterns: list[Any] = [
        pattern
        for pattern in clamp_type_codelet_patterns(meta, vocab().clamp_type_justify)
        if pattern
    ]

    # The caller supplies these.  They used to be read off the Workspace, which has
    # neither attribute, so every justify clamp stamped ``codelet_count = 0`` and
    # ``temperature = 50``.  A clamp timestamped 0 is already older than
    # ``%max-clamp-period%`` (750) the instant it is made, so justify clamps expired
    # after 2–14 codelets instead of lasting up to 750 — the reorganisation Figure 4.13
    # depends on had no time to happen.
    clamp_event = ClampEvent(
        codelet_count=codelet_count,
        temperature=temperature,
        clamp_type=vocab().clamp_type_justify,
        clamped_theme_patterns=clamped_theme_patterns,
        clamped_concept_patterns=clamped_concept_patterns,
        clamped_codelet_patterns=clamped_codelet_patterns,
        rules=list(rules),
        slipnet=slipnet,
        max_activation=float(meta.get_param("max_activation")),
    )

    # Add event first so concept-activation events appear after the clamp
    trace.add_clamp_event(clamp_event)
    if temperature_control is not None:
        clamp_event.activate(
            trace, themespace, slipnet, coderack, temperature_control, workspace
        )

    return clamp_event


# ============================================================================
#  Rule unification  (Scheme: justify.ss unify-rules)
# ============================================================================


def unify_rules(
    from_rule: Rule,
    to_rule: Rule,
    slipnet: Slipnet,
) -> list | None:
    """Attempt to unify two rules by parallel traversal of clauses.

    Scheme: justify.ss ``unify-rules``.
    Returns a theme pattern list ``["vertical_bridge", (dim, rel), ...]``
    or None if unification fails.
    """
    if from_rule.is_verbatim_rule or to_rule.is_verbatim_rule:
        return None

    from_clauses = from_rule.clauses
    to_clauses = to_rule.clauses

    concept_mappings = traverse_rule_clauses(
        from_clauses,
        to_clauses,
        _concept_mapping_proc,
        slipnet=slipnet,
    )
    if concept_mappings is None:
        return None

    # Filter out whole/single concept mappings
    filtered = _remove_whole_single_concept_mappings(concept_mappings, slipnet)

    # Convert to theme pattern entries: (dimension, label)
    entries: list[tuple[str, str | None]] = []
    for cm in filtered:
        cm_type = cm.get("cm_type")
        label = cm.get("label")
        if cm_type:
            entries.append((cm_type, label))

    return [vocab().theme_type_vertical_bridge] + entries


def get_unifying_slippages(
    from_rule: Rule,
    to_rule: Rule,
    slipnet: Slipnet,
) -> list[dict[str, Any]]:
    """Extract slippages needed for unification.

    Scheme: justify.ss ``get-unifying-slippages``.
    Returns a list of slippage dicts representing concept-mappings that are
    slippages (non-identity) between the two rules.
    Assumes the rules can be unified.
    """
    concept_mappings = traverse_rule_clauses(
        from_rule.clauses,
        to_rule.clauses,
        _concept_mapping_proc,
        slipnet=slipnet,
    )
    if concept_mappings is None:
        return []

    filtered = _remove_whole_single_concept_mappings(concept_mappings, slipnet)
    return [cm for cm in filtered if cm.get("is_slippage", False)]


# ============================================================================
#  Rule clause traversal  (Scheme: justify.ss traverse-rule-clauses)
# ============================================================================


class _TraversalFailure(Exception):
    """Structural mismatch while walking two rule clause trees in parallel.

    Module-level on purpose: ``traverse_rule_clauses`` and the ``proc`` callbacks
    it dispatches to used to define their own local ``_Fail`` classes, so a raise
    from ``_concept_mapping_proc`` was a *different* exception type and escaped
    the traversal's ``except`` entirely — crashing the answer-justifier codelet.
    """


def traverse_rule_clauses(
    clauses1: list[RuleClause],
    clauses2: list[RuleClause],
    proc: Any,
    *,
    slipnet: Slipnet,
) -> list[dict[str, Any]] | None:
    """Recursive parallel traversal of rule clause trees.

    Scheme: justify.ss ``traverse-rule-clauses``.
    Walks the clause structures in parallel.  When two leaf nodes (slipnet
    nodes) are encountered, ``proc`` is called to produce a result entry.
    Returns None on structural mismatch ("fail").
    """

    def walk(
        x1: Any, x2: Any, results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if x1 is None and x2 is None:
            return results
        if x1 is None or x2 is None:
            raise _TraversalFailure()

        # Both are lists (e.g., list of changes, list of object-description items)
        if isinstance(x1, (list, tuple)) and isinstance(x2, (list, tuple)):
            if len(x1) != len(x2):
                raise _TraversalFailure()
            for a, b in zip(x1, x2):
                results = walk(a, b, results)
            return results

        # One is a list and the other is not -- structural mismatch
        if isinstance(x1, (list, tuple)) or isinstance(x2, (list, tuple)):
            raise _TraversalFailure()

        # Both are strings (e.g., clause_type, scope)
        if isinstance(x1, str) and isinstance(x2, str):
            if x1 == x2:
                return results
            raise _TraversalFailure()

        # ``justify.ss:243-244``: the special object-type ``string`` unifies with
        # the group object type.  Figure 3.2's ``*string*`` object-description and a
        # string-spanning group name the same thing from two sides — "the whole of it" —
        # and the Scheme lets one rule's reading of it match the other's.  Without this
        # case any rule phrased about the string failed to unify with one phrased about
        # its spanning group, and the pair went to the clamp branch instead.
        if x1 == "string" or x2 == "string":
            other = x2 if x1 == "string" else x1
            if "object.group" in getattr(other, "roles", ()):
                return results
            raise _TraversalFailure()

        # SlipnetNode objects: delegate to proc
        if _is_slipnet_node(x1) and _is_slipnet_node(x2):
            return proc(x1, x2, results, slipnet=slipnet)

        # Fallback: if they're equal, fine; otherwise fail
        if x1 is x2 or x1 == x2:
            return results
        raise _TraversalFailure()

    try:
        # Flatten clause structures for parallel walk
        flat1 = _flatten_clauses(clauses1)
        flat2 = _flatten_clauses(clauses2)
        return walk(flat1, flat2, [])
    except _TraversalFailure:
        return None


# ============================================================================
#  Vertical theme pattern manipulation
#  (Scheme: justify.ss get-vertical-theme-pattern-to-clamp)
# ============================================================================


def get_vertical_theme_pattern_to_clamp(
    unifying_pattern: list,
    slipnet: Slipnet,
    *,
    rng: RNG,
    vlog: Any = None,
    meta: Any = None,
) -> dict[str, Any]:
    """Compute the vertical theme pattern to clamp from a unifying pattern.

    Scheme: justify.ss ``get-vertical-theme-pattern-to-clamp``.
    Applies retention probability filtering and heuristic adjustments
    (add direction entry, replace bond-category with group-category).

    The retention filter is a *sample* per entry (``justify.ss:296`` —
    ``(filter (compose prob? get-probability) pattern-entries)``), not a threshold.
    Deciding it deterministically at 0.5 made the clamped pattern a function of the
    conceptual depths alone: shallow entries were never retained and deep ones always
    were, so the same unification always clamped the same pattern.
    """
    if not unifying_pattern or len(unifying_pattern) < 2:
        return _theme_pattern_list_to_dict(unifying_pattern, meta) if unifying_pattern else {}

    theme_type = unifying_pattern[0]
    # A Themespace relation is the bare name (``identity``, ``opposite``); the entries a
    # unification yields carry the label *node*, which names no theme, so the clamp
    # silently created none of them (G-J3).
    pattern_entries = [
        (e[0], _relation_name(e[1])) + tuple(e[2:]) if isinstance(e, tuple) and len(e) >= 2 else e
        for e in unifying_pattern[1:]
    ]

    # Compute retention probability for each entry and filter
    final_entries: list[tuple[str, str | None]] = []
    retention: list[float] = []
    identity_percent = require_meta(meta, "justify retention probability").get_param(
        "justify_retention_identity_percent"
    )
    for entry in pattern_entries:
        if not isinstance(entry, tuple) or len(entry) < 2:
            continue
        dim, rel = entry[0], entry[1]
        prob = _retention_probability(entry, pattern_entries, slipnet, identity_percent)
        retention.append(prob)
        retained = rng.prob(prob)
        if retained:
            final_entries.append((dim, rel))
    if vlog is not None:
        # justify.ss:301-309 -- "Final pattern:" is followed by "None." whenever the
        # final pattern *exists*, which is always: the Scheme's test is inverted.
        vlog.say("unification-banner")
        vlog.say("rule-unification-possible")
        vlog.say("retention-probabilities", [round_to_100ths(p) for p in retention])
        vlog.say("final-pattern")
        vlog.say("final-pattern-none")
        vlog.say("unification-banner")

    # ``justify.ss:297-299`` nests ``add-direction-entry`` *around*
    # ``replace-bond-category-entry``: the bond-category swap happens first.
    # Heuristic 2: Replace BondCtgy with GroupCtgy
    final_entries = _replace_bond_category_entry(final_entries, slipnet)

    # Heuristic 1: Add direction entry if StrPos entry exists but Dir doesn't
    final_entries = _add_direction_entry(final_entries, slipnet)

    if not final_entries:
        # Fall back to original pattern
        final_entries = [e for e in pattern_entries if isinstance(e, tuple)]

    return _build_theme_pattern_dict(theme_type, final_entries, meta)


def _relation_name(relation: Any) -> Any:
    """A label node, or a relation name, as the Themespace spells a relation.

    A label node knows the relation it is (``node.relation``, from ``theme_relations``); a
    node that is no relation keeps its name, and a string is already the Themespace's
    spelling.
    """
    if isinstance(relation, str):
        return relation
    name = getattr(relation, "relation", None)
    if name is not None:
        return name
    return getattr(relation, "name", relation)


def _retention_probability(
    entry: tuple,
    all_entries: list[tuple],
    slipnet: Slipnet,
    identity_percent: float,
) -> float:
    """Compute the retention probability for a single pattern entry.

    Scheme: justify.ss ``retention-probability``.
    StrPos entries are retained with ``justify_retention_string_position`` (1 in the Metacat
    Standard Configuration).  Others: cd(dimension) * (``justify_retention_identity_percent``
    if identity else ``justify_retention_non_identity_percent``) / 100.
    """
    k = constants()
    dim = entry[0] if isinstance(entry, tuple) else None
    rel = entry[1] if isinstance(entry, tuple) and len(entry) > 1 else None

    if dim is not None and _plays(dim, "dimension.string_position", slipnet):
        return k.justify_retention_string_position

    cd = _get_conceptual_depth(dim, slipnet)
    identity_factor = (
        float(identity_percent)
        if _is_identity_label(rel)
        else k.justify_retention_non_identity_percent
    )
    return (cd / 100.0) * (identity_factor / 100.0)


def _add_direction_entry(
    entries: list[tuple[str, str | None]],
    slipnet: Slipnet,
) -> list[tuple[str, str | None]]:
    """Heuristic: add Dir entry if StrPos exists but Dir doesn't.

    Scheme: justify.ss ``add-direction-entry``.
    """
    str_pos_entry = None
    dir_entry = None
    for entry in entries:
        dim = entry[0]
        if _plays(dim, "dimension.string_position", slipnet):
            str_pos_entry = entry
        if _plays(dim, "dimension.direction", slipnet):
            dir_entry = entry

    # With no direction dimension in the configuration there is none to add.
    dir_node = slipnet.roles.dimension_direction
    if (
        dir_node
        and str_pos_entry is not None
        and str_pos_entry[1] is not None
        and dir_entry is None
    ):
        return [
            (dir_node.name, str_pos_entry[1])
        ] + list(entries)

    return list(entries)


def _replace_bond_category_entry(
    entries: list[tuple[str, str | None]],
    slipnet: Slipnet,
) -> list[tuple[str, str | None]]:
    """Heuristic: replace BondCtgy with GroupCtgy.

    Scheme: justify.ss ``replace-bond-category-entry``.
    """
    bond_ctgy_entry = None
    group_ctgy_entry = None
    for entry in entries:
        dim = entry[0]
        if _plays(dim, "dimension.bond_category", slipnet):
            bond_ctgy_entry = entry
        if _plays(dim, "dimension.group_category", slipnet):
            group_ctgy_entry = entry

    # With no group-category dimension in the configuration there is nothing to replace
    # the bond category with, and the entry is left as it is.
    group_node = slipnet.roles.dimension_group_category
    if bond_ctgy_entry is not None and group_node:
        remaining = [e for e in entries if e is not bond_ctgy_entry]
        if group_ctgy_entry is None:
            return [
                (group_node.name, bond_ctgy_entry[1])
            ] + remaining
        return remaining

    return list(entries)


# ============================================================================
#  Internal helpers
# ============================================================================


def _get_all_supported_rules(workspace: Workspace) -> list[Rule]:
    """Get all supported rules (both top and bottom)."""
    return workspace.get_supported_rules(
        rule_type_top=True
    ) + workspace.get_supported_rules(rule_type_top=False)


def _get_built_rules(workspace: Workspace, *, top: bool) -> list[Rule]:
    """Every rule of a type, in list order (``get-rules``, ``workspace.ss:432-435``).

    No built-ness test: a rule joins the list only when it is added to the Workspace
    (``workspace.ss:479-483``), and a translated rule that justify mode adds itself
    (``justify.ss:109``) never has its proposal level set, so filtering on
    ``is_built`` silently dropped it from every later pick of a rule to unify with.
    """
    rules = workspace.top_rules if top else workspace.bottom_rules
    return list(rules)


def _translate_rule(
    rule: Rule,
    workspace: Workspace,
    slipnet: Slipnet,
    *,
    rng: RNG,
    meta: Any,
) -> tuple[Rule, list[Any], list[Any]] | None:
    """Translate a rule using vertical bridge slippages.

    Returns (translated_rule, slippage_log, supporting_vertical_bridges) or None.

    ``rng`` is what lets a translation drag an auxiliary slippage along on a coattail
    (``slipnet.py:446-447``) and draws the per-dimension ignore at p=0.4
    (``answers.ss:1364-1371``).  The Scheme uses one ``translate`` in both modes, so a
    justify-mode translation is exactly as free as an answer-finding one.
    """
    # No early exit when there are no slippages: ``translate`` (``answers.ss:1281-1342``)
    # fails only on a missing reference object or an invalid clause.  A clause whose
    # objects carry no vertical bridge passes through unchanged
    # (``answers.ss:1442-1448``), so with no vertical bridges at all the rule still
    # translates to its literal counterpart.
    rule_is_top = rule.rule_type == vocab().rule_type_top
    from_string = workspace.initial_string if rule_is_top else workspace.target_string
    to_string = workspace.target_string if rule_is_top else workspace.initial_string
    translated = rule.translate(
        from_string, to_string, slipnet, rng=rng, meta=meta
    )
    if translated is None:
        return None
    # ``(list translated-rule supporting-vertical-bridges slippage-log ...)``
    # (answers.ss:1334-1340): the slippages are the ones the translation *applied*, and
    # the bridges the ones that gave rise to them or join the rules' reference objects.
    translation = translated.translation
    return (translated, translation.slippage_log, translation.supporting_vertical_bridges)


def _reference_objects(
    rule: Rule,
    string: Any,
    slipnet: Slipnet,
) -> list[Any]:
    """The objects of *string* that *rule* refers to, Workspace strings excluded.

    Scheme: ``(filter-out workspace-string? (tell <string> 'get-all-reference-objects
    <rule>))`` (``answers.ss:1311-1315``).
    """
    from server.engine.rules import get_all_reference_objects

    if string is None:
        return []
    try:
        return get_all_reference_objects(rule, string, slipnet)
    except _ENGINE_FAILURES as error:
        _log_failure("finding the reference objects", slipnet, error)
        return []


def _build_translated_string(
    translated_rule: Rule,
    source_string: Any,
    workspace: Workspace,
    slipnet: Slipnet,
) -> Any:
    """Build the string the translated rule implies and hand its bridges to the rule.

    Scheme: ``justify.ss:107-109``.  ``make-translated-string`` is what sets the
    translated rule's supporting horizontal bridges and its theme pattern
    (``rules.ss:164-189``), so this is the step that makes the ``supported?`` test
    below a real question rather than a formality.

    The bridges are deliberately *not* filed in the Workspace: in justify mode the
    answer string already exists, and registering a hypothetical translation's bridges
    would both overwrite the real objects' horizontal bridges and make the rule
    trivially supported by its own translation.
    """
    from server.engine.answers import make_translated_string

    if source_string is None:
        return None
    try:
        return make_translated_string(
            translated_rule,
            source_string,
            slipnet,
            workspace,
            register_bridges=False,
        )
    except _ENGINE_FAILURES as error:
        _log_failure("building the translated string", slipnet, error)
        return None


def _monitor_new_rule(
    rule: Rule,
    workspace: Workspace,
    trace: TemporalTrace | None,
    meta: MetadataProvider,
    codelet_count: int,
    temperature: float,
) -> None:
    """Record the translated rule in the Trace if it is important enough.

    Scheme: ``monitor-new-rules`` (``trace.ss:1338-1343``) with ``rule-importance``
    (``trace.ss:1359-1363``) — a perfectly uniform rule is maximally important whatever
    its relative quality; otherwise importance *is* the relative quality.
    """
    from server.engine.trace import TraceEvent

    if trace is None:
        return
    relative_quality = rule.get_relative_quality(workspace)
    importance = (
        meta.get_param("uniform_rule_importance")
        if rule.uniformity == meta.get_param("perfect_rule_uniformity")
        else float(relative_quality)
    )
    if importance < meta.get_param("rule_importance_threshold"):
        return
    trace.record_event(
        TraceEvent(
            event_type=vocab().event_type_rule_built,
            codelet_count=codelet_count,
            temperature=temperature,
            structures=[rule],
            description=rule.transcribe_to_english(meta),
            strength=float(relative_quality),
        )
    )


def _find_matching_rule(
    rules: list[Rule], translated_rule: Rule
) -> Rule | None:
    """Find a rule in the list that is structurally equal to translated_rule."""
    for r in rules:
        if rules_equal(r, translated_rule):
            return r
    return None


def _translated_rule_works(
    translated_rule: Rule,
    workspace: Workspace,
    slipnet: Slipnet,
    original_rule_type: str,
) -> bool:
    """Check if the translated rule actually works on the other string pair."""
    try:
        return translated_rule.currently_works(workspace, slipnet)
    except _ENGINE_FAILURES as error:
        _log_failure("testing the translated rule", slipnet, error)
        return False


def _order_rules(
    chosen_rule: Rule, other_rule: Rule, chosen_type: str
) -> tuple[Rule, Rule]:
    """Return (top_rule, bottom_rule) regardless of which was chosen."""
    if chosen_type == vocab().rule_type_top:
        return (chosen_rule, other_rule)
    return (other_rule, chosen_rule)


def _answer_already_found(
    memory: Any,
    workspace: Workspace,
    top_rule: Rule,
    bottom_rule: Rule,
) -> bool:
    """Check episodic memory for a duplicate answer.

    Scheme: ``justify.ss:62`` and ``justify.ss:99`` — "Already justified this answer."

    This previously guarded on ``hasattr(memory, "answer_present")`` for a method
    ``EpisodicMemory`` did not have, so it returned ``False`` unconditionally and the
    guard never fired.  The method now exists (``memory.py``); the ``hasattr`` is gone
    because a missing method should be an error rather than a silently disabled check.
    """
    if memory is None:
        return False
    answer = getattr(workspace.answer_string, "text", "") or ""
    problem = (
        workspace.initial_string.text,
        workspace.modified_string.text,
        workspace.target_string.text,
        answer,
    )
    return memory.answer_present(problem, top_rule, bottom_rule)


def _attempt_clamp_rules(
    rules: list[Rule],
    trace: TemporalTrace | None,
    themespace: Themespace | None,
    workspace: Workspace,
    slipnet: Slipnet,
    meta: MetadataProvider,
    *,
    vertical_pattern_override: dict[str, Any] | None = None,
    concept_patterns: list[dict[str, Any]] | None = None,
    explanation: str = "Clamping rules",
    codelet_count: int,
    temperature: float,
    self_watching_enabled: bool,
    coderack: Any = None,
    temperature_control: Any = None,
    vlog: Any = None,
) -> JustificationResult:
    """Attempt to clamp rules and return a JustificationResult."""
    if trace is None or themespace is None:
        return JustificationResult(
            justified=False,
            explanation="Missing components for clamping",
        )
    if vlog is not None and explanation != "Clamping rules":
        # justify.ss:77-85, 122-130: both clamp branches say this much first.
        vlog.say("attempting-to-clamp-rules")
        if trace.permission_to_clamp(
            self_watching_enabled=self_watching_enabled,
            codelet_count=codelet_count,
            grace_period=meta.get_param("grace_period"),
        ):
            vlog.say("permission-granted-clamping-rules")

    clamp_event = clamp_rules(
        rules,
        trace,
        themespace,
        slipnet,
        workspace,
        meta,
        codelet_count=codelet_count,
        temperature=temperature,
        self_watching_enabled=self_watching_enabled,
        coderack=coderack,
        temperature_control=temperature_control,
        vertical_theme_pattern=vertical_pattern_override,
        concept_patterns=concept_patterns,
    )

    if clamp_event is not None:
        return JustificationResult(
            justified=False,
            explanation=explanation,
            action="clamp_rules",
            clamp_event=clamp_event,
        )

    return JustificationResult(
        justified=False,
        explanation="Permission to clamp denied",
    )


def _get_concept_pattern_dict(rule: Rule) -> dict[str, Any]:
    """Convert a rule's concept pattern to a dict for clamping."""
    entries = []
    for node, activation in rule.get_concept_pattern():
        name = getattr(node, "name", str(node))
        entries.append({"node": name, "activation": activation})
    return {"type": "concepts", "entries": entries}


def _concept_mapping_proc(
    n1: Any,
    n2: Any,
    results: list[dict[str, Any]],
    *,
    slipnet: Slipnet,
) -> list[dict[str, Any]]:
    """Process two leaf nodes during clause traversal for unification.

    Scheme: justify.ss ``concept-mapping-proc``.
    If nodes differ and are not slip-linked, fail.
    If the node has a category, produce a concept-mapping entry.
    """

    if n1 is not n2 and not _slip_linked(n1, n2, slipnet):
        raise _TraversalFailure()

    category = _get_category(n1)
    if category is None:
        return results

    label = _get_label(n1, n2, slipnet)
    cm_type_name = getattr(category, "name", str(category))

    results.append(
        {
            "cm_type": cm_type_name,
            "label": label,
            "descriptor1": n1,
            "descriptor2": n2,
            "is_slippage": n1 is not n2,
        }
    )
    return results


# ============================================================================
#  Slipnet / concept helpers
# ============================================================================


def _is_slipnet_node(obj: Any) -> bool:
    """Check if an object is a slipnet node."""
    return hasattr(obj, "activation") and hasattr(obj, "conceptual_depth")


def _slip_linked(n1: Any, n2: Any, slipnet: Slipnet) -> bool:
    """Check if two slipnet nodes are slip-linked."""
    if n1 is n2:
        return True
    return slipnet.slip_linked(n1, n2) or slipnet.slip_linked(n2, n1)


def _get_category(node: Any) -> Any:
    """Get the category of a slipnet node.

    Scheme: ``(tell n1 'get-category)``
    """
    if hasattr(node, "category"):
        return node.category
    if hasattr(node, "get_category"):
        return node.get_category()
    return None


def _get_label(n1: Any, n2: Any, slipnet: Slipnet) -> str | None:
    """Get the label (identity, opposite, etc.) between two nodes."""
    if n1 is n2:
        # The identity relation is spelled as the Themespace does.  A configuration
        # without it labels no mapping identity (the mapping is a slippage, "different").
        identity = vocab().theme_relation_identity
        if not slipnet.relation(identity):
            return None
        return identity
    return slipnet.get_label(n1, n2)


def _get_conceptual_depth(node_name: Any, slipnet: Slipnet) -> float:
    """Get conceptual depth of a node by name, or of a node object.

    A name no node holds, or ``None``, is no node: it has the depth of the engine's Null
    Object (``Absent.conceptual_depth``, 0 -- what has no node is not perceived), so its
    retention probability is 0.  No literal depth is written here.
    """
    if isinstance(node_name, str):
        node = slipnet.nodes.get(node_name)
        if node is not None:
            return node.conceptual_depth
    return getattr(node_name, "conceptual_depth", Absent.conceptual_depth)


def _plays(dim: Any, role: str, slipnet: Slipnet) -> bool:
    """True if *dim*, a dimension node or the name of one (theme patterns hold names),
    is the node that plays the dimension *role*.  A role nothing holds is played by none."""
    node = slipnet.roles.get(role)
    if not node:
        return False
    return dim is node or dim == node.name


def _is_identity_label(label: Any) -> bool:
    """True for the identity relation: its name in the Themespace's spelling, or its node."""
    if label is None:
        return False
    identity = vocab().theme_relation_identity
    if isinstance(label, str):
        return label == identity
    return getattr(label, "relation", None) == identity


def _remove_whole_single_concept_mappings(
    concept_mappings: list[dict[str, Any]],
    slipnet: Slipnet,
) -> list[dict[str, Any]]:
    """Remove the concept-mapping whose CM-type is string-position-category and
    whose descriptor1 is whole or single.

    Scheme: ``remove-whole/single-concept-mappings`` (``justify.ss:220-229``) is
    ``(remq (select pred cms) cms)``: ``select`` returns the *first* match and ``remq``
    drops that one element.  Removing every match discarded StrPos mappings the Scheme
    keeps, and with them theme-pattern entries the clamp is built from.
    """
    result = list(concept_mappings)
    for index, cm in enumerate(result):
        cm_type = cm.get("cm_type", "")
        d1 = cm.get("descriptor1")
        roles = getattr(d1, "roles", ()) if d1 else ()
        if _plays(cm_type, "dimension.string_position", slipnet) and (
            "position.single" in roles or "position.whole" in roles
        ):
            del result[index]
            break
    return result


def _flatten_clauses(clauses: list[RuleClause]) -> list:
    """The clause lists in the Scheme's own shape, for the parallel walk.

    Scheme: ``rules.ss:36-60``.  A clause is ``(intrinsic (<object-description>)
    (<change> ...))``, ``(extrinsic (<object-description> ...) (<dimension> ...))`` or
    ``(verbatim (<letter-category> ...))``, and a change is ``(<scope> <dimension>
    <descriptor>)`` whose one descriptor slot holds the relation *or* the literal node
    that was substituted for it (``rules.ss:889-909``).

    The earlier flattening dropped each change's scope and an extrinsic clause's
    dimension list, so two extrinsic clauses over ``(string StringPos whole)``
    unified to an empty pattern and a rule that swaps Bond-Facet descriptors clamped no
    theme at all.
    """
    result = []
    for clause in clauses:
        clause_flat: list = [clause.clause_type]
        if clause.is_verbatim:
            clause_flat.append(list(clause.verbatim_letters or []))
        elif clause.is_extrinsic:
            clause_flat.append([list(od) for od in clause.object_descriptions])
            clause_flat.append(list(clause.dimensions))
        else:
            clause_flat.append([list(od) for od in clause.object_descriptions])
            clause_flat.append(
                [
                    [
                        change.referent,
                        change.dimension,
                        next(
                            (
                                d
                                for d in (
                                    change.relation,
                                    change.to_descriptor,
                                    change.from_descriptor,
                                )
                                if d is not None
                            ),
                            None,
                        ),
                    ]
                    for change in clause.changes
                ]
            )
        result.append(clause_flat)
    return result


def _theme_pattern_to_dict(pattern: Any, meta: Any) -> dict[str, Any] | None:
    """Convert a theme pattern (list or dict) to a dict for clamping."""
    if isinstance(pattern, dict):
        return pattern
    if isinstance(pattern, list) and len(pattern) >= 1:
        return _theme_pattern_list_to_dict(pattern, meta)
    return None


def _theme_pattern_list_to_dict(pattern: list, meta: Any) -> dict[str, Any]:
    """Convert a [theme_type, (dim, rel), ...] list to a dict, each entry at ``max_theme_activation``."""
    if not pattern:
        return {}
    theme_type = pattern[0]
    entries = []
    for item in pattern[1:]:
        if isinstance(item, tuple) and len(item) >= 2:
            entries.append(
                {
                    "dimension": item[0],
                    "relation": _theme_relation(item[1]),
                    "activation": float(meta.get_param("max_theme_activation")),
                }
            )
    return {"type": theme_type, "entries": entries}


def _theme_relation(relation: Any) -> Any:
    """A pattern entry's relation as a Themespace theme spells it.

    An unlabelled concept mapping (``#f``, e.g. object-category letter=>group) is the
    *different* relation (the vocabulary's ``theme_relation.diff``); left as ``None`` the
    clamp created no theme for the entry at all.
    """
    return vocab().theme_relation_diff if relation is None else relation


def _build_theme_pattern_dict(
    theme_type: str, entries: list[tuple[str, str | None]], meta: Any
) -> dict[str, Any]:
    """Build a theme pattern dict from a theme type and entries, each at ``max_theme_activation``."""
    return {
        "type": theme_type,
        "entries": [
            {
                "dimension": dim,
                "relation": _theme_relation(rel),
                "activation": float(meta.get_param("max_theme_activation")),
            }
            for dim, rel in entries
        ],
    }



