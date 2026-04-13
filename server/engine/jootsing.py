"""Jootsing -- Jumping Out Of The System.

Self-watching codelets that detect and escape repetitive failure patterns.
Progress-watchers monitor whether the system is making progress;
jootsers analyze repeated snags and clamp/negate patterns to force
alternative exploration.

Scheme source: jootsing.ss
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from server.engine.formulas import weighted_average
from server.engine.trace import (
    ANSWER_FOUND,
    CLAMP_START,
    SNAG,
    ClampEvent,
    SnagEvent,
    TraceEvent,
    negate_theme_pattern_entry,
)

if TYPE_CHECKING:
    from server.engine.commentary import CommentaryLog
    from server.engine.coderack import Coderack
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG
    from server.engine.slipnet import Slipnet
    from server.engine.temperature import Temperature
    from server.engine.themes import Themespace
    from server.engine.trace import TemporalTrace
    from server.engine.workspace import Workspace

logger = logging.getLogger(__name__)

# Scheme constants from jootsing.ss
_SATISFACTORY_RULE_QUALITY = 80
_SETTLING_PERIOD = 250
_MAX_CLAMP_PERIOD = 750
_GRACE_PERIOD = 100


# ============================================================================
#  Result types  (backward compatible)
# ============================================================================


class ProgressWatcherResult:
    """Result of a progress-watcher codelet."""

    def __init__(
        self,
        progress_detected: bool = False,
        stall_detected: bool = False,
        action: str = "",
        *,
        progress_value: float = 0.0,
        clamp_event: ClampEvent | None = None,
    ) -> None:
        self.progress_detected = progress_detected
        self.stall_detected = stall_detected
        self.action = action
        self.progress_value = progress_value
        self.clamp_event = clamp_event


class JootserResult:
    """Result of a jootser codelet."""

    def __init__(
        self,
        pattern_detected: bool = False,
        negative_pattern: dict[str, str] | None = None,
        action: str = "",
        give_up: bool = False,
        *,
        clamp_event: ClampEvent | None = None,
    ) -> None:
        self.pattern_detected = pattern_detected
        self.negative_pattern = negative_pattern
        self.action = action
        self.give_up = give_up
        self.clamp_event = clamp_event


# ============================================================================
#  Progress watcher  (Scheme: jootsing.ss progress-watcher codelet, line 255)
# ============================================================================


def check_progress(
    workspace: Workspace,
    trace: TemporalTrace,
    codelet_count: int,
    meta: MetadataProvider,
    commentary: CommentaryLog | None = None,
    *,
    justify_mode: bool = False,
    self_watching_enabled: bool = True,
    rng: RNG | None = None,
    themespace: Themespace | None = None,
    slipnet: Slipnet | None = None,
) -> ProgressWatcherResult:
    """Progress-watcher logic.

    Scheme: jootsing.ss progress-watcher codelet (line 255).
    During clamp periods: check if enough time has elapsed since last event.
    If so, undo the clamp and stochastically post answer-finder/justifier.
    Outside clamp periods: detect stalls and evaluate rule quality.
    """
    if not self_watching_enabled:
        return ProgressWatcherResult(progress_detected=True)

    settling = meta.get_param("settling_period", _SETTLING_PERIOD)
    max_clamp = meta.get_param("max_clamp_period", _MAX_CLAMP_PERIOD)
    satisfactory_quality = meta.get_param(
        "satisfactory_rule_quality", _SATISFACTORY_RULE_QUALITY
    )

    # ── Within a clamp period ──
    if trace.within_clamp_period:
        time_since_last = trace.time_since_last_event(codelet_count)

        if time_since_last <= settling:
            # Too soon to draw conclusions
            return ProgressWatcherResult(progress_detected=True)

        # Enough time has elapsed -- undo the clamp
        last_clamp = trace.get_last_event(CLAMP_START)
        progress = trace.undo_last_clamp(
            themespace, slipnet, codelet_count
        ) if themespace is not None and slipnet is not None else 0.0

        # Stochastically post answer-finder/justifier based on progress
        action = ""
        if rng is not None and progress > 0:
            prob = progress / 100.0
            if rng.prob(prob):
                action = (
                    "post_answer_justifier"
                    if justify_mode
                    else "post_answer_finder"
                )

        return ProgressWatcherResult(
            stall_detected=True,
            action=action if action else "undo_clamp",
            progress_value=progress,
        )

    # ── Outside clamp period: check current activity ──
    activity = workspace.get_activity(codelet_count)

    if activity > 0:
        # Things are still happening, nothing to worry about
        return ProgressWatcherResult(progress_detected=True)

    # Activity is zero -- nothing much is happening
    # Check on current rule quality
    top_rules = workspace.top_rules
    bottom_rules = workspace.bottom_rules

    max_top_quality = (
        max((r.quality for r in top_rules), default=0.0)
        if top_rules
        else 0.0
    )
    max_bottom_quality = (
        max((r.quality for r in bottom_rules), default=0.0)
        if bottom_rules
        else 0.0
    )

    poor_top = max_top_quality < satisfactory_quality
    poor_bottom = justify_mode and max_bottom_quality < satisfactory_quality

    if not poor_top and not poor_bottom:
        # Rules seem to be of decent quality
        return ProgressWatcherResult(
            progress_detected=True,
            action="post_answer_finder" if not justify_mode else "post_answer_justifier",
        )

    # Current rules are not good enough -- attempt to clamp codelet pattern
    if not trace.permission_to_clamp(
        self_watching_enabled=self_watching_enabled,
        codelet_count=codelet_count,
        grace_period=meta.get_param("grace_period", _GRACE_PERIOD),
    ):
        return ProgressWatcherResult(
            stall_detected=True,
            action="clamp_denied",
        )

    # Compute clamp probability based on rule quality
    if justify_mode:
        clamp_probability = 1.0 - min(max_top_quality, max_bottom_quality) / 100.0
    else:
        clamp_probability = 1.0 - max_top_quality / 100.0

    # Stochastic check
    if rng is not None and not rng.prob(clamp_probability):
        return ProgressWatcherResult(
            stall_detected=True,
            action="clamp_attempt_failed",
        )

    # Emit commentary about frustration
    if commentary is not None:
        from server.engine.commentary import emit_clamp_activate

        clamp_count = trace.clamp_count + 1
        emit_clamp_activate(
            commentary, "rule_codelet_clamp", clamp_count, codelet_count
        )

    # Create and activate a rule-codelet clamp
    temperature = getattr(workspace, "temperature", 50.0)
    clamp_event = ClampEvent(
        codelet_count=codelet_count,
        temperature=temperature,
        clamp_type="rule_codelet_clamp",
        clamped_theme_patterns=[],
        clamped_concept_patterns=[],
        clamped_codelet_patterns=[{"type": "rule_codelet_pattern"}],
        rules=[],
        progress_focus="rule",
    )

    trace.add_clamp_event(clamp_event)
    if themespace is not None and slipnet is not None:
        clamp_event.activate(trace, themespace, slipnet)

    return ProgressWatcherResult(
        stall_detected=True,
        action="clamp_rule_pattern",
        clamp_event=clamp_event,
    )


# ============================================================================
#  Jootser  (Scheme: jootsing.ss jootser codelet, line 23)
# ============================================================================


def attempt_jootsing(
    trace: TemporalTrace,
    themespace: Themespace,
    meta: MetadataProvider,
    commentary: CommentaryLog | None = None,
    codelet_count: int = 0,
    *,
    self_watching_enabled: bool = True,
    rng: RNG | None = None,
    slipnet: Slipnet | None = None,
    workspace: Workspace | None = None,
) -> JootserResult:
    """Jootser logic.

    Scheme: jootsing.ss jootser codelet (line 23).
    Checks for recurring clamp/snag patterns. Analyzes theme overlap,
    constructs negative theme pattern, clamps it to force alternatives.
    """
    if not self_watching_enabled:
        return JootserResult(pattern_detected=False)

    # Don't check during a clamp period
    if trace.within_clamp_period:
        return JootserResult(pattern_detected=False)

    # ── Check for recurring clamps ──
    clamps = get_most_recent_event_set(trace, "clamp")
    # Filter out manual clamps
    clamps = [
        c
        for c in clamps
        if isinstance(c, ClampEvent) and c.clamp_type != "manual_clamp"
    ]

    if len(clamps) >= 3:
        clamp_type = clamps[0].clamp_type if isinstance(clamps[0], ClampEvent) else ""
        jootsing_prob = get_clamp_jootsing_probability(clamps, codelet_count)

        if rng is not None and rng.prob(jootsing_prob):
            # Jootsing from clamps
            if clamp_type == "rule_codelet_clamp":
                return joots_from_rule_codelet_clamps(
                    clamps, commentary, codelet_count
                )
            elif clamp_type == "snag_response_clamp":
                return joots_from_snag_response_clamps(
                    clamps, commentary, codelet_count
                )
            elif clamp_type == "justify_clamp":
                return joots_from_justify_clamps(
                    clamps,
                    trace,
                    workspace,
                    slipnet,
                    themespace,
                    rng,
                    commentary,
                    codelet_count,
                )

    # ── Check for recurring snags ──
    snags = get_most_recent_event_set(trace, "snag")

    if len(snags) < 3:
        return JootserResult(pattern_detected=False)

    # Build theme overlap table
    num_snags = len(snags)
    snag_theme_patterns: list[Any] = []
    for s in snags:
        tp = getattr(s, "snag_theme_pattern", None) or getattr(
            s, "theme_pattern", None
        )
        if tp is not None:
            snag_theme_patterns.append(tp)

    if not snag_theme_patterns:
        return JootserResult(pattern_detected=False)

    # Collect all pattern entries and compute overlap
    all_entries = _collect_all_theme_entries(snag_theme_patterns)
    theme_overlap_table = _build_theme_overlap_table(all_entries, num_snags)

    if not theme_overlap_table:
        return JootserResult(pattern_detected=False)

    max_overlap = max(ov for _, ov in theme_overlap_table)

    # Compute jootsing probability from overlap and snag count
    jootsing_probability = (max_overlap / 100.0) * min(
        1.0, 10 * num_snags / 100.0
    )

    # Stochastic check -- note Scheme uses (1 - prob) for "failure to joots"
    if rng is not None and not rng.prob(jootsing_probability):
        return JootserResult(pattern_detected=False)

    # Permission to clamp
    if not trace.permission_to_clamp(
        self_watching_enabled=self_watching_enabled,
        codelet_count=codelet_count,
        grace_period=meta.get_param("grace_period", _GRACE_PERIOD),
    ):
        return JootserResult(pattern_detected=False)

    # Build negative theme pattern stochastically
    all_possible_entries = _unique_entries(all_entries)

    # Gather snag objects and their descriptions for depth computation
    snag_objects = _collect_snag_objects(snags)
    snag_descriptions = _collect_snag_descriptions(snag_objects)

    chosen_entries: list[dict[str, Any]] = []
    for entry in all_possible_entries:
        overlap_val = _lookup_overlap(entry, theme_overlap_table)
        avg_depth = _average_description_depth(
            entry, snag_descriptions, slipnet
        )
        inclusion_prob = (overlap_val / 100.0) * (avg_depth / 100.0)

        if rng is not None:
            if rng.prob(inclusion_prob):
                chosen_entries.append(entry)
        elif inclusion_prob >= 0.5:
            chosen_entries.append(entry)

    if not chosen_entries:
        # Can't make negative theme pattern
        if num_snags > 5:
            if commentary is not None:
                from server.engine.commentary import emit_jootsing, emit_give_up

                emit_jootsing(commentary, "snag_response", codelet_count)
                emit_give_up(commentary, codelet_count)
            return JootserResult(give_up=True, action="give_up")
        return JootserResult(pattern_detected=False)

    # Negate the chosen entries
    negative_entries = [negate_theme_pattern_entry(e) for e in chosen_entries]

    negative_theme_pattern: dict[str, Any] = {
        "type": "vertical_bridge",
        "entries": negative_entries,
    }

    # Also build a bottom-up codelet pattern for the clamp
    bottom_up_pattern: dict[str, Any] = {
        "type": "bottom_up_codelet_pattern"
    }

    # Create and activate the snag-response clamp
    temperature = 50.0
    if workspace is not None:
        temperature = getattr(workspace, "temperature", 50.0)

    clamp_event = ClampEvent(
        codelet_count=codelet_count,
        temperature=temperature,
        clamp_type="snag_response_clamp",
        clamped_theme_patterns=[negative_theme_pattern, bottom_up_pattern],
        clamped_concept_patterns=[],
        clamped_codelet_patterns=[],
        rules=[],
        progress_focus="workspace",
    )

    trace.add_clamp_event(clamp_event)
    if slipnet is not None:
        clamp_event.activate(trace, themespace, slipnet)

    # Emit commentary
    if commentary is not None:
        from server.engine.commentary import emit_jootsing

        emit_jootsing(commentary, "frustrated", codelet_count)

    # Build a simple negative_pattern dict for backward compatibility
    simple_pattern: dict[str, str] = {}
    for entry in chosen_entries:
        dim = entry.get("dimension", "")
        rel = entry.get("relation", "")
        if dim and rel:
            simple_pattern[dim] = rel

    return JootserResult(
        pattern_detected=True,
        negative_pattern=simple_pattern if simple_pattern else None,
        action="clamp_negative_pattern",
        clamp_event=clamp_event,
    )


# ============================================================================
#  get_most_recent_event_set  (Scheme: jootsing.ss line 153)
# ============================================================================


def get_most_recent_event_set(
    trace: TemporalTrace, event_type: str
) -> list[TraceEvent]:
    """Return the most recent set of equivalent events.

    Scheme: jootsing.ss ``get-most-recent-event-set``.
    For snags: get events since last answer.
    For clamps: get all events.
    Then partition into equivalence sets and pick the youngest set.
    """
    if event_type == "snag":
        all_recent = trace.get_new_events_since_last(ANSWER_FOUND)
    else:
        all_recent = list(trace.events)

    # Filter to the requested event type
    type_map = {"snag": SNAG, "clamp": CLAMP_START}
    target_type = type_map.get(event_type, event_type)
    filtered = [e for e in all_recent if e.event_type == target_type]

    if not filtered:
        return []

    # Partition into equivalence sets
    equiv_sets = _partition_events(filtered)

    if not equiv_sets:
        return []

    # Pick the set with the youngest (most recent / smallest age) event
    # Age = codelet_count; most recent = highest codelet_count
    def max_time(events: list[TraceEvent]) -> int:
        return max(e.codelet_count for e in events)

    # Select the most recent set (highest max codelet_count)
    return max(equiv_sets, key=max_time)


# ============================================================================
#  Clamp jootsing probability  (Scheme: jootsing.ss line 122)
# ============================================================================


def get_clamp_jootsing_probability(
    clamps: list[TraceEvent],
    codelet_count: int = 0,
) -> float:
    """Compute jootsing probability from clamp history.

    Scheme: jootsing.ss ``get-clamp-jootsing-probability``.
    Based on: elapsed time since each clamp, average progress of recent
    clamps, clamp type factor, and number of clamps.
    """
    if not clamps:
        return 0.0

    num_clamps = len(clamps)
    clamp_type = ""
    if isinstance(clamps[0], ClampEvent):
        clamp_type = clamps[0].clamp_type

    # Elapsed time weights: proportion of total time when each clamp happened
    elapsed_time_weights: list[float] = []
    for clamp in clamps:
        t = clamp.codelet_count
        if codelet_count > 0:
            elapsed_time_weights.append(100.0 * t / codelet_count)
        else:
            elapsed_time_weights.append(100.0)

    # Progress achieved by each clamp
    progress_values: list[float] = []
    for clamp in clamps:
        p = getattr(clamp, "progress_achieved", 0.0)
        progress_values.append(float(p))

    # Weighted average of progress
    if elapsed_time_weights and progress_values:
        average_progress = round(
            weighted_average(progress_values, elapsed_time_weights)
        )
    else:
        average_progress = 0.0

    # Clamp type factor
    if clamp_type == "justify_clamp":
        # For justify clamps: factor is 1 if the last event was a clamp, else 0
        # This is a simplified check -- the Scheme checks the specific last event
        clamp_type_factor = 1.0
    elif clamp_type == "snag_response_clamp":
        clamp_type_factor = 1.0
    elif clamp_type == "rule_codelet_clamp":
        clamp_type_factor = 0.5
    else:
        clamp_type_factor = 0.5

    # Final probability
    progress_factor = 1.0 - average_progress / 100.0
    count_factor = min(1.0, 10 * num_clamps / 100.0)
    jootsing_probability = progress_factor * count_factor * clamp_type_factor

    return jootsing_probability


# ============================================================================
#  Specific jootsing actions per clamp type
#  (Scheme: jootsing.ss lines 173-235)
# ============================================================================


def joots_from_rule_codelet_clamps(
    clamps: list[TraceEvent],
    commentary: CommentaryLog | None = None,
    codelet_count: int = 0,
) -> JootserResult:
    """Break out of rule codelet clamp patterns.

    Scheme: jootsing.ss ``joots-from-rule-codelet-clamps``.
    The system gives up: "I just can't seem to come up with any better rules."
    """
    if commentary is not None:
        from server.engine.commentary import emit_jootsing, emit_give_up

        emit_jootsing(commentary, "rule_codelet", codelet_count)
        emit_give_up(commentary, codelet_count)

    return JootserResult(
        pattern_detected=True,
        give_up=True,
        action="give_up",
    )


def joots_from_snag_response_clamps(
    clamps: list[TraceEvent],
    commentary: CommentaryLog | None = None,
    codelet_count: int = 0,
) -> JootserResult:
    """Break out of snag response patterns.

    Scheme: jootsing.ss ``joots-from-snag-response-clamps``.
    The system gives up: "This is getting boring."
    """
    if commentary is not None:
        from server.engine.commentary import emit_jootsing, emit_give_up

        emit_jootsing(commentary, "snag_response", codelet_count)
        emit_give_up(commentary, codelet_count)

    return JootserResult(
        pattern_detected=True,
        give_up=True,
        action="give_up",
    )


def joots_from_justify_clamps(
    clamps: list[TraceEvent],
    trace: TemporalTrace | None,
    workspace: Workspace | None,
    slipnet: Slipnet | None,
    themespace: Themespace | None,
    rng: RNG | None,
    commentary: CommentaryLog | None = None,
    codelet_count: int = 0,
) -> JootserResult:
    """Break out of justify clamp patterns.

    Scheme: jootsing.ss ``joots-from-justify-clamps``.
    Attempts to give up by extracting the top and bottom rules from the
    most recent justify clamp, translating the top rule, and checking
    for unjustified slippages.
    """
    if not clamps or not isinstance(clamps[0], ClampEvent):
        return JootserResult(give_up=True, action="give_up")

    most_recent = clamps[0]
    top_rule = None
    bottom_rule = None

    # Extract rules from the most recent justify clamp
    if hasattr(most_recent, "rules") and most_recent.rules:
        for r in most_recent.rules:
            if hasattr(r, "rule_type"):
                if r.rule_type == "top" and top_rule is None:
                    top_rule = r
                elif r.rule_type == "bottom" and bottom_rule is None:
                    bottom_rule = r

    if top_rule is None or bottom_rule is None:
        return JootserResult(give_up=True, action="give_up")

    # Check if rules currently work
    if workspace is not None and slipnet is not None:
        try:
            if not top_rule.currently_works(workspace, slipnet):
                return JootserResult(pattern_detected=False)
            if not bottom_rule.currently_works(workspace, slipnet):
                return JootserResult(pattern_detected=False)
        except Exception:
            return JootserResult(pattern_detected=False)

    # Try to translate top rule
    if workspace is None:
        return JootserResult(give_up=True, action="give_up")

    from server.engine.justify import (
        get_unifying_slippages,
        _translate_rule,
    )

    translation_result = _translate_rule(top_rule, workspace, slipnet)
    if translation_result is None:
        return JootserResult(pattern_detected=False)

    translated_rule, slippages, supporting_vbridges = translation_result

    # Get unjustified slippages between translated rule and bottom rule
    unjustified = get_unifying_slippages(translated_rule, bottom_rule, slipnet)

    if not unjustified:
        # No unjustified slippages -- post answer-justifier
        return JootserResult(
            pattern_detected=True,
            action="post_answer_justifier",
        )

    # Too many unjustified slippages? Stochastic check
    if rng is not None and len(unjustified) > 1:
        give_up_prob = 1.0 - 1.0 / len(unjustified)
        if rng.prob(give_up_prob):
            return JootserResult(pattern_detected=False)

    # Time to give up -- report the answer with unjustified slippages
    return JootserResult(
        pattern_detected=True,
        give_up=True,
        action="report_unjustified_answer",
    )


# ============================================================================
#  Internal helpers
# ============================================================================


def _partition_events(
    events: list[TraceEvent],
) -> list[list[TraceEvent]]:
    """Partition events into equivalence sets.

    Two events are equivalent if they have the same type and their
    theme patterns overlap substantially (or are both None).
    """
    if not events:
        return []

    sets: list[list[TraceEvent]] = []
    for event in events:
        placed = False
        for s in sets:
            if _events_equivalent(s[0], event):
                s.append(event)
                placed = True
                break
        if not placed:
            sets.append([event])

    return sets


def _events_equivalent(e1: TraceEvent, e2: TraceEvent) -> bool:
    """Check if two events are equivalent for jootsing purposes.

    Scheme: (tell ev1 'equal? ev2)
    For ClampEvents: same clamp type.
    For SnagEvents: same snag type.
    Otherwise: same event type.
    """
    if e1.event_type != e2.event_type:
        return False

    if isinstance(e1, ClampEvent) and isinstance(e2, ClampEvent):
        return e1.clamp_type == e2.clamp_type

    if isinstance(e1, SnagEvent) and isinstance(e2, SnagEvent):
        return e1.snag_type == e2.snag_type

    return True


def _collect_all_theme_entries(
    patterns: list[Any],
) -> list[dict[str, Any]]:
    """Collect all theme pattern entries from a list of patterns.

    Handles both dict-form and list-form patterns.
    """
    entries: list[dict[str, Any]] = []
    for pattern in patterns:
        if isinstance(pattern, dict):
            for entry in pattern.get("entries", []):
                entries.append(dict(entry))
            # Also handle simple dim->rel dict form
            if "entries" not in pattern:
                for key, val in pattern.items():
                    if key != "type":
                        entries.append(
                            {"dimension": key, "relation": val}
                        )
        elif isinstance(pattern, list):
            for item in pattern[1:]:  # Skip theme_type prefix
                if isinstance(item, tuple) and len(item) >= 2:
                    entries.append(
                        {"dimension": item[0], "relation": item[1]}
                    )
    return entries


def _build_theme_overlap_table(
    entries: list[dict[str, Any]], num_events: int
) -> list[tuple[dict[str, Any], float]]:
    """Build a theme overlap table: entry -> overlap percentage.

    Scheme: jootsing.ss lines 62-67.
    Partitions entries by equivalence and computes overlap as
    (count / num_events) * 100.
    """
    if not entries or num_events == 0:
        return []

    # Partition entries by equivalence
    equiv_groups: list[list[dict[str, Any]]] = []
    for entry in entries:
        placed = False
        for group in equiv_groups:
            if _theme_entries_equal(group[0], entry):
                group.append(entry)
                placed = True
                break
        if not placed:
            equiv_groups.append([entry])

    table: list[tuple[dict[str, Any], float]] = []
    for group in equiv_groups:
        overlap = 100.0 * len(group) / num_events
        table.append((group[0], overlap))

    return table


def _theme_entries_equal(e1: dict[str, Any], e2: dict[str, Any]) -> bool:
    """Check if two theme pattern entries are equivalent."""
    return (
        e1.get("dimension") == e2.get("dimension")
        and e1.get("relation") == e2.get("relation")
    )


def _unique_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate theme entries."""
    seen: list[dict[str, Any]] = []
    for e in entries:
        if not any(_theme_entries_equal(e, s) for s in seen):
            seen.append(e)
    return seen


def _lookup_overlap(
    entry: dict[str, Any],
    table: list[tuple[dict[str, Any], float]],
) -> float:
    """Look up the overlap value for an entry in the overlap table."""
    for table_entry, overlap in table:
        if _theme_entries_equal(table_entry, entry):
            return overlap
    return 0.0


def _collect_snag_objects(snags: list[TraceEvent]) -> list[Any]:
    """Collect all snag objects from snag events."""
    objects: list[Any] = []
    for snag in snags:
        if hasattr(snag, "snag_objects"):
            objects.extend(snag.snag_objects)
    return objects


def _collect_snag_descriptions(objects: list[Any]) -> list[Any]:
    """Collect all descriptions from snag objects."""
    descriptions: list[Any] = []
    for obj in objects:
        if hasattr(obj, "descriptions"):
            descriptions.extend(obj.descriptions)
        elif hasattr(obj, "get_descriptions"):
            descriptions.extend(obj.get_descriptions())
    return descriptions


def _average_description_depth(
    entry: dict[str, Any],
    descriptions: list[Any],
    slipnet: Slipnet | None,
) -> float:
    """Compute average conceptual depth of descriptions matching an entry's dimension.

    Scheme: jootsing.ss lines 95-98.
    """
    dim = entry.get("dimension", "")

    matching: list[float] = []
    for desc in descriptions:
        desc_type = None
        if hasattr(desc, "description_type"):
            desc_type = desc.description_type
        elif hasattr(desc, "type"):
            desc_type = desc.type

        if desc_type is not None:
            type_name = getattr(desc_type, "name", str(desc_type))
            if type_name == dim:
                depth = 50.0
                if hasattr(desc, "conceptual_depth"):
                    depth = desc.conceptual_depth
                elif hasattr(desc, "get_conceptual_depth"):
                    depth = desc.get_conceptual_depth()
                matching.append(depth)

    if not matching:
        # Default depth when no matching descriptions found
        if slipnet is not None and isinstance(dim, str):
            node = slipnet.nodes.get(dim)
            if node is not None:
                return node.conceptual_depth
        return 50.0

    return sum(matching) / len(matching)
