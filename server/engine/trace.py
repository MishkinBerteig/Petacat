"""Temporal Trace — chronological record of cognitive events.

Records all significant events during a run: bonds built/broken, groups formed,
bridges established, rules discovered, snags encountered, answers found.

Rich event types (AnswerEvent, ClampEvent, SnagEvent) store detailed context
about answers, clamp periods, and snag conditions.  Clamp lifecycle methods
on TemporalTrace manage permission checks, grace periods, progress measurement,
and undo operations.

Scheme source: trace.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.engine.formulas import weighted_average

if TYPE_CHECKING:
    from server.engine.slipnet import Slipnet
    from server.engine.temperature import Temperature
    from server.engine.themes import Themespace


# ---------------------------------------------------------------------------
# Event type string constants (values live in DB event_types table)
# ---------------------------------------------------------------------------
BOND_BUILT = "bond_built"
BOND_BROKEN = "bond_broken"
GROUP_BUILT = "group_built"
GROUP_BROKEN = "group_broken"
BRIDGE_BUILT = "bridge_built"
BRIDGE_BROKEN = "bridge_broken"
RULE_BUILT = "rule_built"
RULE_BROKEN = "rule_broken"
DESCRIPTION_BUILT = "description_built"
ANSWER_FOUND = "answer_found"
SNAG = "snag"
CLAMP_START = "clamp_start"
CLAMP_END = "clamp_end"
JOOTSING = "jootsing"
THEME_ACTIVATED = "theme_activated"
CONCEPT_MAPPING_BUILT = "concept_mapping_built"

# Default grace period (codelets after unclamping before allowing a new clamp).
# Matches Scheme constant %grace-period% in jootsing.ss:252.
GRACE_PERIOD_DEFAULT = 100

# Default max clamp duration (codelets).
# Matches Scheme constant %max-clamp-period% in jootsing.ss:248.
MAX_CLAMP_PERIOD_DEFAULT = 750


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------

class TraceEvent:
    """A single recorded event in the temporal trace."""

    _next_id = 0

    def __init__(
        self,
        event_type: str,
        codelet_count: int,
        temperature: float,
        structures: list[Any] | None = None,
        description: str = "",
        theme_pattern: Any = None,
    ) -> None:
        TraceEvent._next_id += 1
        self.event_number = TraceEvent._next_id
        self.event_type = event_type
        self.codelet_count = codelet_count
        self.temperature = temperature
        self.structures = structures or []
        self.description = description
        self.theme_pattern = theme_pattern

    # Convenience used by progress evaluators
    def get_strength(self) -> float:
        """Return a generic strength metric for progress evaluation."""
        return 0.0

    def __repr__(self) -> str:
        return (
            f"TraceEvent({self.event_type}, "
            f"t={self.codelet_count}, T={self.temperature:.0f})"
        )


# ---------------------------------------------------------------------------
# Rich event types
# ---------------------------------------------------------------------------

class AnswerEvent(TraceEvent):
    """Rich event recording a discovered (or justified) answer.

    Scheme source: trace.ss ``make-answer-event``.
    Stores the problem strings, both rules, supporting structures, theme
    patterns, quality score, and any unjustified slippages.
    """

    def __init__(
        self,
        codelet_count: int,
        temperature: float,
        *,
        initial_string: Any = None,
        modified_string: Any = None,
        target_string: Any = None,
        answer_string: Any = None,
        top_rule: Any = None,
        bottom_rule: Any = None,
        supporting_vertical_bridges: list[Any] | None = None,
        supporting_groups: list[Any] | None = None,
        top_rule_ref_objects: list[Any] | None = None,
        bottom_rule_ref_objects: list[Any] | None = None,
        slippage_log: Any = None,
        unjustified_slippages: list[Any] | None = None,
        theme_pattern: Any = None,
        structures: list[Any] | None = None,
        description: str = "",
    ) -> None:
        super().__init__(
            event_type=ANSWER_FOUND,
            codelet_count=codelet_count,
            temperature=temperature,
            structures=structures,
            description=description,
            theme_pattern=theme_pattern,
        )
        self.initial_string = initial_string
        self.modified_string = modified_string
        self.target_string = target_string
        self.answer_string = answer_string
        self.top_rule = top_rule
        self.bottom_rule = bottom_rule
        self.supporting_vertical_bridges = supporting_vertical_bridges or []
        self.supporting_groups = supporting_groups or []
        self.top_rule_ref_objects = top_rule_ref_objects or []
        self.bottom_rule_ref_objects = bottom_rule_ref_objects or []
        self.slippage_log = slippage_log
        self.unjustified_slippages = unjustified_slippages or []
        self.answer_description: Any = None

    # ------------------------------------------------------------------
    # Quality metrics  (Scheme: trace.ss make-answer-event)
    # ------------------------------------------------------------------

    def get_absolute_quality(self) -> float:
        """Scheme: ``get-absolute-quality``.

        ``weighted-average([top-rule-quality, 100-temperature], [60, 40])``
        """
        rule_quality = _rule_quality(self.top_rule)
        return round(
            weighted_average(
                [rule_quality, 100.0 - self.temperature],
                [60.0, 40.0],
            )
        )

    def get_relative_quality(self) -> float:
        """Scheme: ``get-relative-quality``.

        ``weighted-average([top-rule-relative-quality, 100-temperature], [60, 40])``
        """
        rel_quality = _rule_relative_quality(self.top_rule)
        return round(
            weighted_average(
                [rel_quality, 100.0 - self.temperature],
                [60.0, 40.0],
            )
        )

    def get_quality(self) -> float:
        """Alias for ``get_absolute_quality`` (matches Scheme ``get-quality``)."""
        return self.get_absolute_quality()

    def get_strength(self) -> float:
        """Override — answer strength is its quality."""
        return self.get_quality()

    def is_unjustified(self) -> bool:
        return len(self.unjustified_slippages) > 0

    def __repr__(self) -> str:
        return (
            f"AnswerEvent(t={self.codelet_count}, T={self.temperature:.0f}, "
            f"quality={self.get_quality():.0f})"
        )


class ClampEvent(TraceEvent):
    """Rich event recording the activation of a clamp period.

    Scheme source: trace.ss ``make-clamp-event``.
    Stores clamped patterns (theme, concept, codelet), the supporting rule,
    unifying slippages, and a progress evaluator for measuring effectiveness.
    """

    def __init__(
        self,
        codelet_count: int,
        temperature: float,
        *,
        clamp_type: str = "rule_codelet_clamp",
        clamped_theme_patterns: list[Any] | None = None,
        clamped_concept_patterns: list[Any] | None = None,
        clamped_codelet_patterns: list[Any] | None = None,
        rules: list[Any] | None = None,
        unifying_slippages: list[Any] | None = None,
        progress_focus: str = "rule",
        theme_pattern: Any = None,
        structures: list[Any] | None = None,
        description: str = "",
    ) -> None:
        super().__init__(
            event_type=CLAMP_START,
            codelet_count=codelet_count,
            temperature=temperature,
            structures=structures,
            description=description,
            theme_pattern=theme_pattern,
        )
        self.clamp_type = clamp_type
        self.clamped_theme_patterns = clamped_theme_patterns or []
        self.clamped_concept_patterns = clamped_concept_patterns or []
        self.clamped_codelet_patterns = clamped_codelet_patterns or []
        self.rules = rules or []
        self.unifying_slippages = unifying_slippages or []
        self.progress_focus = progress_focus
        self.progress_achieved: float = 0.0

    # ------------------------------------------------------------------
    # Progress evaluation
    # ------------------------------------------------------------------

    def evaluate_progress(self, event: TraceEvent) -> float:
        """Score a single event for how much progress it represents.

        Scheme: ``progress-evaluator`` lambda in ``make-clamp-event``.
        Returns the event's strength if its type matches ``progress_focus``,
        otherwise 0.
        """
        if event.event_type == self.progress_focus:
            return event.get_strength()
        # Also check by mapping clamp focus to event types
        focus_to_types = {
            "rule": (RULE_BUILT,),
            "answer": (ANSWER_FOUND,),
            "group": (GROUP_BUILT,),
        }
        matching_types = focus_to_types.get(self.progress_focus, ())
        if event.event_type in matching_types:
            return event.get_strength()
        return 0.0

    def get_strength(self) -> float:
        """Override — clamp events are always maximally strong."""
        return 100.0

    # ------------------------------------------------------------------
    # Activate / deactivate  (Scheme: trace.ss clamp-event activate/deactivate)
    # ------------------------------------------------------------------

    def activate(
        self,
        trace: TemporalTrace,
        themespace: Themespace,
        slipnet: Slipnet,
    ) -> None:
        """Activate all clamped patterns.

        Scheme: ``activate`` message on clamp-event.
        Undoes any current snag condition, then clamps theme patterns,
        concept patterns, and codelet patterns.
        """
        trace.undo_snag_condition(themespace, slipnet)

        # Clamp theme patterns
        for pattern in self.clamped_theme_patterns:
            clamp_theme_pattern(pattern, themespace)

        # Clamp concept patterns
        for pattern in self.clamped_concept_patterns:
            clamp_concept_pattern(pattern, slipnet)

    def deactivate(
        self,
        trace: TemporalTrace,
        themespace: Themespace,
        slipnet: Slipnet,
    ) -> None:
        """Deactivate all clamped patterns.

        Scheme: ``deactivate`` message on clamp-event.
        """
        # Unclamp theme patterns
        for pattern in self.clamped_theme_patterns:
            unclamp_theme_pattern(themespace)

        # Unclamp concept patterns
        for pattern in self.clamped_concept_patterns:
            unclamp_concept_pattern(slipnet)

    def __repr__(self) -> str:
        return (
            f"ClampEvent({self.clamp_type}, t={self.codelet_count}, "
            f"progress={self.progress_achieved:.0f})"
        )


class SnagEvent(TraceEvent):
    """Rich event recording a snag (rule-translation failure).

    Scheme source: trace.ss ``make-snag-event``.
    Stores the snag type, the theme pattern at snag time, the failing rule,
    snag objects, and a progress evaluator.
    """

    # Snag type constants (matching Scheme: SWAP, CONFLICT, CHANGE)
    SWAP = "swap"
    CONFLICT = "conflict"
    CHANGE = "change"

    def __init__(
        self,
        codelet_count: int,
        temperature: float,
        *,
        snag_type: str = "change",
        snag_theme_pattern: Any = None,
        snag_concept_pattern: Any = None,
        snag_rule: Any = None,
        translated_rule: Any = None,
        snag_objects: list[Any] | None = None,
        snag_bridges: list[Any] | None = None,
        snag_concept_mappings: list[Any] | None = None,
        supporting_vertical_bridges: list[Any] | None = None,
        slippage_log: Any = None,
        rule_ref_objects: list[Any] | None = None,
        theme_pattern: Any = None,
        structures: list[Any] | None = None,
        description: str = "",
    ) -> None:
        super().__init__(
            event_type=SNAG,
            codelet_count=codelet_count,
            temperature=temperature,
            structures=structures,
            description=description,
            theme_pattern=theme_pattern if theme_pattern is not None else snag_theme_pattern,
        )
        self.snag_type = snag_type
        self.snag_theme_pattern = snag_theme_pattern
        self.snag_concept_pattern = snag_concept_pattern
        self.snag_rule = snag_rule
        self.translated_rule = translated_rule
        self.snag_objects = snag_objects or []
        self.snag_bridges = snag_bridges or []
        self.snag_concept_mappings = snag_concept_mappings or []
        self.supporting_vertical_bridges = supporting_vertical_bridges or []
        self.slippage_log = slippage_log
        self.rule_ref_objects = rule_ref_objects or []
        self.progress_achieved: float = 0.0

    # ------------------------------------------------------------------
    # Progress evaluation
    # ------------------------------------------------------------------

    def evaluate_progress(self, structure: Any) -> float:
        """Score a workspace structure for progress since this snag.

        Scheme: ``progress-evaluator`` in ``make-snag-event``.
        Returns the structure's strength unless it is a bond (returns 0).
        """
        # In the Scheme original, bonds are excluded from progress measurement
        if hasattr(structure, "structure_type") and structure.structure_type == "bond":
            return 0.0
        if hasattr(structure, "get_strength"):
            return structure.get_strength()
        if hasattr(structure, "strength"):
            return float(structure.strength)
        return 0.0

    def get_strength(self) -> float:
        """Override — snag events are always maximally strong."""
        return 100.0

    # ------------------------------------------------------------------
    # Activate / deactivate  (Scheme: trace.ss snag-event activate/deactivate)
    # ------------------------------------------------------------------

    def activate(
        self,
        trace: TemporalTrace,
        slipnet: Slipnet,
    ) -> None:
        """Activate the snag condition.

        Scheme: ``activate`` message on snag-event.
        Undoes the last clamp, clamps salience on snag objects, and clamps
        the snag concept pattern.
        """
        trace.undo_last_clamp_raw()

        # Clamp salience on snag objects
        for obj in self.snag_objects:
            if hasattr(obj, "clamp_salience"):
                obj.clamp_salience()

        # Clamp concept pattern
        if self.snag_concept_pattern is not None:
            clamp_concept_pattern(self.snag_concept_pattern, slipnet)

    def deactivate(self, slipnet: Slipnet) -> None:
        """Deactivate the snag condition.

        Scheme: ``deactivate`` message on snag-event.
        """
        for obj in self.snag_objects:
            if hasattr(obj, "unclamp_salience"):
                obj.unclamp_salience()

        if self.snag_concept_pattern is not None:
            unclamp_concept_pattern(slipnet)

    def __repr__(self) -> str:
        return (
            f"SnagEvent({self.snag_type}, t={self.codelet_count}, "
            f"progress={self.progress_achieved:.0f})"
        )


# ---------------------------------------------------------------------------
# Helpers for quality computation
# ---------------------------------------------------------------------------

def _rule_quality(rule: Any) -> float:
    """Safely extract quality from a rule object."""
    if rule is None:
        return 0.0
    if hasattr(rule, "get_quality"):
        return float(rule.get_quality())
    if hasattr(rule, "quality"):
        return float(rule.quality)
    return 0.0


def _rule_relative_quality(rule: Any) -> float:
    """Safely extract relative quality from a rule object."""
    if rule is None:
        return 0.0
    if hasattr(rule, "get_relative_quality"):
        return float(rule.get_relative_quality())
    if hasattr(rule, "relative_quality"):
        return float(rule.relative_quality)
    return _rule_quality(rule)


# ---------------------------------------------------------------------------
# Pattern clamping utilities
# ---------------------------------------------------------------------------
# These mirror the Scheme functions ``clamp-theme-pattern``,
# ``unclamp-theme-pattern``, ``clamp-concept-pattern``,
# ``unclamp-concept-pattern``, and ``negate-theme-pattern-entry``
# from trace.ss lines 1530-1557.
#
# Pattern structure (matching Scheme):
#
#   theme-pattern  = {"type": <theme_type>, "entries": [{"dimension": d, "relation": r, "activation": a}, ...]}
#                  OR  dict[str, str|float]  (simplified form used by existing code)
#   concept-pattern = {"type": "concepts", "entries": [{"node": <name>, "activation": a}, ...]}
#                   OR  dict[str, float]  (simplified: node_name -> activation)
#
# The functions below accept both structured and simplified forms.
# ---------------------------------------------------------------------------


def clamp_theme_pattern(pattern: Any, themespace: Themespace) -> None:
    """Clamp a theme pattern in the Themespace.

    Scheme: trace.ss ``clamp-theme-pattern`` (line 1530).
    Clears the theme type, imposes the pattern, freezes the type, and
    enables thematic pressure for that type.
    """
    if pattern is None:
        return

    if isinstance(pattern, dict):
        # Structured form: {"type": theme_type, "entries": [...]}
        theme_type = pattern.get("type")
        entries = pattern.get("entries", [])

        if theme_type and entries:
            # Clear existing themes for this type
            for cluster in themespace.clusters:
                if cluster.theme_type == theme_type:
                    cluster.frozen = False
                    for theme in cluster.themes:
                        theme.activation = 0.0
                        theme.positive_activation = 0.0
                        theme.negative_activation = 0.0

            # Impose the pattern entries
            for entry in entries:
                dim = entry.get("dimension")
                rel = entry.get("relation")
                act = entry.get("activation", 100.0)
                if dim is not None:
                    _set_theme_activation(themespace, theme_type, dim, rel, act)

            # Freeze clusters for this type
            for cluster in themespace.clusters:
                if cluster.theme_type == theme_type:
                    cluster.frozen = True
                    for theme in cluster.themes:
                        if theme.activation != 0:
                            theme.frozen = True

        elif not entries:
            # Simple dict: treat remaining keys as dimension -> relation
            for dim, rel in pattern.items():
                if dim == "type":
                    continue
                _set_theme_activation(themespace, theme_type, dim, rel, 100.0)

            for cluster in themespace.clusters:
                if cluster.theme_type == theme_type:
                    cluster.frozen = True
                    for theme in cluster.themes:
                        if theme.activation != 0:
                            theme.frozen = True


def unclamp_theme_pattern(themespace: Themespace) -> None:
    """Remove the current theme pattern clamp.

    Scheme: trace.ss ``unclamp-theme-pattern`` (line 1538).
    Unfreezes all clusters and themes.
    """
    themespace.unclamp_all()


def clamp_concept_pattern(pattern: Any, slipnet: Slipnet) -> None:
    """Clamp concept nodes according to a pattern.

    Scheme: trace.ss ``clamp-concept-pattern`` (line 1547).
    """
    if pattern is None:
        return

    if isinstance(pattern, dict):
        entries = pattern.get("entries", [])
        if entries:
            for entry in entries:
                node_name = entry.get("node")
                activation = entry.get("activation", 100)
                if node_name:
                    node = slipnet.nodes.get(node_name)
                    if node and not node.frozen:
                        node.frozen = True
                        node.activation = float(activation)
        else:
            # Simple dict: node_name -> activation
            for node_name, activation in pattern.items():
                if node_name == "type":
                    continue
                node = slipnet.nodes.get(node_name)
                if node:
                    node.frozen = True
                    node.activation = float(activation)


def unclamp_concept_pattern(slipnet: Slipnet) -> None:
    """Remove the current concept pattern clamp.

    Scheme: trace.ss ``unclamp-concept-pattern`` (line 1554).
    Unfreezes all slipnet nodes.
    """
    for node in slipnet.nodes.values():
        node.frozen = False


def negate_theme_pattern_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Negate a theme pattern entry (for negative/inhibitory clamping).

    Scheme: trace.ss ``negate-theme-pattern-entry`` (line 1432).
    If the entry has an explicit activation, negate it. Otherwise
    use -100 (negative max-theme-activation).
    """
    result = dict(entry)
    if "activation" in result:
        result["activation"] = -result["activation"]
    else:
        result["activation"] = -100.0
    return result


def _set_theme_activation(
    themespace: Themespace,
    theme_type: str,
    dimension: str,
    relation: str | None,
    activation: float,
) -> None:
    """Set activation on a specific theme in the Themespace."""
    for cluster in themespace.clusters:
        if cluster.theme_type == theme_type and cluster.dimension == dimension:
            theme = cluster.get_theme(relation)
            if theme:
                if activation >= 0:
                    theme.positive_activation = activation
                    theme.negative_activation = 0.0
                else:
                    theme.positive_activation = 0.0
                    theme.negative_activation = activation
                theme.activation = theme.positive_activation + theme.negative_activation
            return


# ---------------------------------------------------------------------------
# Clamp progress commentary helpers
# ---------------------------------------------------------------------------

def clamp_progress_amount_phrase(progress: float) -> str:
    """Scheme: trace.ss ``clamp-progress-amount-phrase``."""
    if progress == 0:
        return "zero"
    if progress < 50:
        return "very little"
    if progress < 80:
        return "some"
    return "a lot of"


def clamp_progress_adjective_phrase(progress: float) -> str:
    """Scheme: trace.ss ``clamp-progress-adjective-phrase``."""
    if progress == 0:
        return "a pretty useless"
    if progress < 50:
        return "not such a great"
    if progress < 80:
        return "an okay"
    return "a pretty good"


# ---------------------------------------------------------------------------
# TemporalTrace
# ---------------------------------------------------------------------------

class TemporalTrace:
    """The full temporal trace for a run.

    In addition to basic event recording, provides clamp lifecycle management
    (permission checking, grace periods, progress measurement, undo operations)
    that the self-watching system (progress-watchers and jootsers) depends on.
    """

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self.within_clamp_period: bool = False
        self.within_snag_period: bool = False
        self.last_clamp_time: int = 0
        self.last_unclamp_time: int = 0
        self.clamp_count: int = 0
        self.snag_count: int = 0
        self._last_significant_event_time: int = 0

    # ------------------------------------------------------------------
    # Basic event recording (preserved from original)
    # ------------------------------------------------------------------

    def record_event(self, event: TraceEvent) -> None:
        """Record a new event."""
        self.events.append(event)
        if event.event_type not in (CLAMP_START, CLAMP_END):
            self._last_significant_event_time = event.codelet_count

    def record_clamp_start(self, codelet_count: int, temperature: float) -> None:
        self.within_clamp_period = True
        self.last_clamp_time = codelet_count
        self.clamp_count += 1
        self.record_event(
            TraceEvent(CLAMP_START, codelet_count, temperature)
        )

    def record_clamp_end(self, codelet_count: int, temperature: float) -> None:
        self.within_clamp_period = False
        self.last_unclamp_time = codelet_count
        self.record_event(
            TraceEvent(CLAMP_END, codelet_count, temperature)
        )

    def record_snag(
        self, codelet_count: int, temperature: float, theme_pattern: Any = None
    ) -> None:
        self.within_snag_period = True
        self.snag_count += 1
        self.record_event(
            TraceEvent(
                SNAG,
                codelet_count,
                temperature,
                theme_pattern=theme_pattern,
            )
        )

    # ------------------------------------------------------------------
    # Rich event recording
    # ------------------------------------------------------------------

    def add_answer_event(self, event: AnswerEvent) -> None:
        """Record a rich AnswerEvent."""
        self.record_event(event)

    def add_clamp_event(self, event: ClampEvent) -> None:
        """Record a rich ClampEvent and enter clamp period."""
        self.within_clamp_period = True
        self.last_clamp_time = event.codelet_count
        self.clamp_count += 1
        self.record_event(event)

    def add_snag_event(self, event: SnagEvent) -> None:
        """Record a rich SnagEvent and enter snag period."""
        self.within_snag_period = True
        self.snag_count += 1
        self.record_event(event)

    # ------------------------------------------------------------------
    # Basic queries (preserved from original)
    # ------------------------------------------------------------------

    def get_recent_snags(self, window: int = 0) -> list[TraceEvent]:
        """Return recent snag events, optionally within a time window."""
        snags = [e for e in self.events if e.event_type == SNAG]
        if window > 0 and snags:
            cutoff = snags[-1].codelet_count - window
            snags = [s for s in snags if s.codelet_count >= cutoff]
        return snags

    def get_answer_events(self) -> list[TraceEvent]:
        return [e for e in self.events if e.event_type == ANSWER_FOUND]

    def time_since_last_event(self, codelet_count: int) -> int:
        """How many codelets since the last significant event."""
        return codelet_count - self._last_significant_event_time

    def get_events_by_type(self, event_type: str) -> list[TraceEvent]:
        return [e for e in self.events if e.event_type == event_type]

    def get_theme_overlap(
        self, events: list[TraceEvent]
    ) -> float:
        """Compute theme overlap across a set of events.

        Returns a value 0-1 indicating how similar the theme patterns are.
        Used by jootsing to detect repetitive failure patterns.
        """
        if len(events) < 2:
            return 0.0
        patterns = [e.theme_pattern for e in events if e.theme_pattern is not None]
        if len(patterns) < 2:
            return 0.0
        # Compare each pair of patterns
        total_overlap = 0.0
        count = 0
        for i in range(len(patterns)):
            for j in range(i + 1, len(patterns)):
                overlap = self._pattern_overlap(patterns[i], patterns[j])
                total_overlap += overlap
                count += 1
        return total_overlap / count if count > 0 else 0.0

    def _pattern_overlap(self, p1: Any, p2: Any) -> float:
        """Compute overlap between two theme patterns."""
        if p1 is None or p2 is None:
            return 0.0
        if isinstance(p1, dict) and isinstance(p2, dict):
            shared_keys = set(p1.keys()) & set(p2.keys())
            if not shared_keys:
                return 0.0
            matches = sum(1 for k in shared_keys if p1[k] == p2[k])
            return matches / max(len(p1), len(p2))
        return 0.0

    # ------------------------------------------------------------------
    # Clamp lifecycle — permission and state queries
    # Scheme: trace.ss make-temporal-trace (lines 112-177)
    # ------------------------------------------------------------------

    def permission_to_clamp(
        self,
        self_watching_enabled: bool = True,
        codelet_count: int = 0,
        grace_period: int = GRACE_PERIOD_DEFAULT,
    ) -> bool:
        """Return True if a new clamp period is permitted.

        Scheme: ``permission-to-clamp?`` (line 116).
        Requires self-watching enabled, not within a clamp period, and not
        within the grace period after the last clamp ended.
        """
        return (
            self_watching_enabled
            and not self.within_clamp_period
            and not self.within_grace_period(codelet_count, grace_period)
        )

    def within_grace_period(
        self,
        codelet_count: int = 0,
        grace_period: int = GRACE_PERIOD_DEFAULT,
    ) -> bool:
        """True for N events after the last clamp ended.

        Scheme: ``within-grace-period?`` (line 112).
        """
        return (
            not self.within_clamp_period
            and self.last_unclamp_time > 0
            and codelet_count < self.last_unclamp_time + grace_period
        )

    def clamp_period_expired(
        self,
        codelet_count: int = 0,
        max_clamp_period: int = MAX_CLAMP_PERIOD_DEFAULT,
    ) -> bool:
        """True when the current clamp's duration has elapsed.

        Scheme: ``clamp-period-expired?`` (line 120).
        """
        return (
            self.within_clamp_period
            and codelet_count > self.last_clamp_time + max_clamp_period
        )

    # ------------------------------------------------------------------
    # Clamp lifecycle — undo operations
    # Scheme: trace.ss make-temporal-trace (lines 129-174)
    # ------------------------------------------------------------------

    def undo_last_clamp(
        self,
        themespace: Themespace,
        slipnet: Slipnet,
        codelet_count: int = 0,
    ) -> float:
        """Deactivate the last clamp event and return progress achieved.

        Scheme: ``undo-last-clamp`` (line 129).
        Finds the most recent ClampEvent, computes progress since it was
        created, deactivates its clamped patterns, and exits the clamp period.
        """
        if not self.within_clamp_period:
            return 0.0

        progress = self.progress_since_last_clamp()

        self.within_clamp_period = False
        self.last_unclamp_time = codelet_count

        # Find the last ClampEvent and deactivate it
        last_clamp = self.get_last_event(CLAMP_START)
        if last_clamp is not None and isinstance(last_clamp, ClampEvent):
            last_clamp.progress_achieved = progress
            last_clamp.deactivate(self, themespace, slipnet)

        return progress

    def undo_last_clamp_raw(self) -> None:
        """Exit clamp period without deactivating patterns.

        Used by SnagEvent.activate which calls trace.undo_last_clamp before
        applying its own patterns. This just flips the state flag.
        """
        if self.within_clamp_period:
            self.within_clamp_period = False

    def progress_since_last_clamp(self) -> float:
        """Measure how much progress was made during the last clamp.

        Scheme: ``progress-since-last-clamp`` (line 123).
        Gets events since the last ClampEvent and evaluates each one
        using the clamp's progress evaluator. Returns the maximum.
        """
        last_clamp = self.get_last_event(CLAMP_START)
        if last_clamp is None:
            return 0.0

        new_events = self.get_new_events_since_last(CLAMP_START)

        if isinstance(last_clamp, ClampEvent):
            if not new_events:
                return 0.0
            return max(
                (last_clamp.evaluate_progress(e) for e in new_events),
                default=0.0,
            )

        # Fallback for plain TraceEvents (legacy path)
        if not new_events:
            return 0.0
        return max(
            (e.get_strength() for e in new_events),
            default=0.0,
        )

    def progress_since_last_snag(self) -> float:
        """Measure how much progress was made since the last snag.

        Scheme: ``progress-since-last-snag`` (line 182).
        Gets workspace structures since the last snag and evaluates each one
        using the snag's progress evaluator. Returns the maximum.
        """
        last_snag = self.get_last_event(SNAG)
        if last_snag is None:
            return 0.0

        new_events = self.get_new_events_since_last(SNAG)

        if isinstance(last_snag, SnagEvent):
            if not new_events:
                return 0.0
            # Evaluate each new event's structures
            max_progress = 0.0
            for event in new_events:
                for struct in event.structures:
                    p = last_snag.evaluate_progress(struct)
                    if p > max_progress:
                        max_progress = p
                # Also evaluate the event directly
                p = event.get_strength()
                if p > max_progress:
                    max_progress = p
            return max_progress

        # Fallback for plain TraceEvents (legacy path)
        if not new_events:
            return 0.0
        return max(
            (e.get_strength() for e in new_events),
            default=0.0,
        )

    def undo_snag_condition(
        self,
        themespace: Themespace | None = None,
        slipnet: Slipnet | None = None,
        temperature: Temperature | None = None,
    ) -> None:
        """Exit the snag state and unclamp temperature.

        Scheme: ``undo-snag-condition`` (line 188).
        """
        if not self.within_snag_period:
            return

        self.within_snag_period = False

        last_snag = self.get_last_event(SNAG)
        if last_snag is not None:
            progress = self.progress_since_last_snag()

            if isinstance(last_snag, SnagEvent):
                last_snag.progress_achieved = progress
                if slipnet is not None:
                    last_snag.deactivate(slipnet)

        # Unclamp temperature (Scheme: (set! *temperature-clamped?* #f))
        if temperature is not None:
            temperature.unclamp()

    # ------------------------------------------------------------------
    # Event query methods
    # Scheme: trace.ss (lines 82-95)
    # ------------------------------------------------------------------

    def get_last_event(self, event_type: str | list[str] | None = None) -> TraceEvent | None:
        """Get the most recent event, optionally filtered by type.

        Scheme: ``get-last-event`` (line 82).
        If *event_type* is a list, returns the most recent event matching
        any of the types.
        """
        if event_type is None:
            return self.events[-1] if self.events else None

        if isinstance(event_type, list):
            for event in reversed(self.events):
                if event.event_type in event_type:
                    return event
            return None

        for event in reversed(self.events):
            if event.event_type == event_type:
                return event
        return None

    def get_new_events_since_last(self, event_type: str | list[str]) -> list[TraceEvent]:
        """Return events recorded after the most recent event of the given type.

        Scheme: ``get-new-events-since-last`` (line 89).
        """
        last_event = self.get_last_event(event_type)
        if last_event is None:
            return list(self.events)
        # Return all events after the last matching event
        idx = -1
        for i, e in enumerate(self.events):
            if e is last_event:
                idx = i
                break
        if idx < 0:
            return list(self.events)
        return self.events[idx + 1:]

    def current_answer(self) -> TraceEvent | None:
        """Check if the most recent event is an answer and return it.

        Scheme: ``current-answer?`` (line 175).
        Returns the answer event if the most recent significant event is
        an answer event, otherwise None.
        """
        last_answer = self.get_last_event(ANSWER_FOUND)
        if last_answer is None:
            return None
        # Check that no other significant events happened after it
        # (Scheme checks (zero? (get-elapsed-time 'answer)), meaning
        # the answer was the most recently added event)
        if self.events and self.events[-1] is last_answer:
            return last_answer
        return None

    def immediate_snag_condition(self) -> bool:
        """True if we are in a snag period and the snag just happened.

        Scheme: ``immediate-snag-condition?`` (line 179).
        """
        if not self.within_snag_period:
            return False
        last_snag = self.get_last_event(SNAG)
        if last_snag is None:
            return False
        # True if the snag is the most recent event
        return self.events[-1] is last_snag if self.events else False

    def get_num_of_clamps(self, clamp_type: str) -> int:
        """Count clamp events of a specific type.

        Scheme: ``get-num-of-clamps`` (line 73).
        """
        count = 0
        for event in self.events:
            if isinstance(event, ClampEvent) and event.clamp_type == clamp_type:
                count += 1
            elif event.event_type == CLAMP_START:
                # Also count plain clamp-start events if they have matching description
                if hasattr(event, "clamp_type") and event.clamp_type == clamp_type:
                    count += 1
        return count

    def get_elapsed_time(self, event_type: str, codelet_count: int) -> int:
        """Codelets since the last event of a given type.

        Scheme: ``get-elapsed-time`` (line 104).
        """
        last_event = self.get_last_event(event_type)
        if last_event is not None:
            return codelet_count - last_event.codelet_count
        return codelet_count

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def clear(self) -> None:
        self.events.clear()
        self.within_clamp_period = False
        self.within_snag_period = False
        self.last_clamp_time = 0
        self.last_unclamp_time = 0
        self.clamp_count = 0
        self.snag_count = 0
        self._last_significant_event_time = 0

    def __repr__(self) -> str:
        return f"TemporalTrace({len(self.events)} events, {self.snag_count} snags)"
