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
from server.engine.ids import KIND_TRACE_EVENT, next_id

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
CONCEPT_ACTIVATION = "concept_activation"

# The seven event types the Trace records (§4.4).  Everything else the Workspace
# does is below the cognitive level and is deliberately filtered out.
COGNITIVE_EVENT_TYPES = (
    CONCEPT_ACTIVATION,
    GROUP_BUILT,
    CONCEPT_MAPPING_BUILT,  # slippage events
    RULE_BUILT,
    ANSWER_FOUND,
    SNAG,
    CLAMP_START,
)

#: ``answer_quality_rule_weight`` / ``answer_quality_temperature_weight``, the
#: shipped 60/40.  The fallback for an event asked for its quality without a
#: ``MetadataProvider``; the coefficients are the value in force.
DEFAULT_ANSWER_QUALITY_WEIGHTS = (60.0, 40.0)


def _answer_quality_weights(meta: Any) -> list[float]:
    if meta is None:
        return list(DEFAULT_ANSWER_QUALITY_WEIGHTS)
    return [
        meta.get_formula_coeff("answer_quality_rule_weight"),
        meta.get_formula_coeff("answer_quality_temperature_weight"),
    ]


# Default grace period (codelets after unclamping before allowing a new clamp).
# Matches Scheme constant %grace-period% in jootsing.ss:252.
GRACE_PERIOD_DEFAULT = 100

# Default max clamp duration (codelets).
# Matches Scheme constant %max-clamp-period% in jootsing.ss:248.
MAX_CLAMP_PERIOD_DEFAULT = 750

#: The urgency level each clamp type puts its codelet pattern *against* — the Scheme's
#: ``against-background`` (``trace.ss:1578-1581``), applied at the clamp site rather
#: than baked into the pattern.
#:
#: One clamp uses it.  ``jootsing.ss:326-327`` builds the rule-codelet clamp from
#: ``(against-background %very-low-urgency% %rule-codelet-pattern%)``: the three rule
#: types at 77/91/91 **and all 24 other types at 21**, which — with the posting
#: override in ``Coderack.clamped_posting_probability`` — throttles their posting to
#: 0.21.  The clamp starves everything but rule work.  Petacat had no complement
#: mechanism at all, so the stall-escape ("I still don't see a good way to describe…")
#: was a mild boost to rule codelets instead of a redirection of the whole rack.
CLAMP_TYPE_CODELET_BACKGROUNDS: dict[str, str] = {
    "rule_codelet_clamp": "very_low",
}


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------

class TraceEvent:
    """A single recorded event in the temporal trace."""

    def __init__(
        self,
        event_type: str,
        codelet_count: int,
        temperature: float,
        structures: list[Any] | None = None,
        description: str = "",
        theme_pattern: Any = None,
        strength: float = 0.0,
        concept_mapping: Any = None,
        bridge: Any = None,
        group: Any = None,
        slipnode: Any = None,
    ) -> None:
        self.event_number = next_id(KIND_TRACE_EVENT)
        self.event_type = event_type
        self.codelet_count = codelet_count
        self.temperature = temperature
        self.structures = structures or []
        self.description = description
        self.theme_pattern = theme_pattern
        #: The *particular* slippage a concept-mapping event records, and the bridge it
        #: was made on (``trace.ss:750-800``).  The Scheme's event closes over one
        #: concept-mapping and reports a one-entry theme pattern built from it
        #: (``trace.ss:763-766``); reading every non-identity mapping back off the
        #: bridge instead — as this used to — attributes to the event slippages it
        #: never recorded, and those go straight into the answer's index.
        self.concept_mapping = concept_mapping
        self.bridge = bridge
        #: The group a group event records (``trace.ss:871``), needed because
        #: ``abstract-answer-description-theme-pattern`` asks a whole-string group event
        #: for its group (``answers.ss:173, 177``).
        self.group = group
        #: The Slipnet node a concept-activation event records (``trace.ss:718``).
        self.slipnode = slipnode
        #: How strong the thing this event records was, at the moment it happened.
        #: §4.5.1 measures a clamp by "the strengths of the most important Workspace
        #: structures that get built in the aftermath of the clamp ... recorded in the
        #: Temporal Trace, in the form of group events, slippage events, and rule
        #: events", so these three carry a real value: relative rule quality
        #: (``trace.ss:965``), group strength (``trace.ss:880``) and concept-mapping
        #: strength (``trace.ss:796``).  It was previously hard-zero for every event,
        #: which made every clamp record ``progress_achieved = 0.0``.
        self.strength = strength

    # Convenience used by progress evaluators
    def get_strength(self) -> float:
        """Return a generic strength metric for progress evaluation."""
        return self.strength

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

    def get_absolute_quality(self, meta: Any = None) -> float:
        """Scheme: ``get-absolute-quality``.

        ``weighted-average([top-rule-quality, 100-temperature], [60, 40])``

        The weights are ``answer_quality_rule_weight`` and
        ``answer_quality_temperature_weight``, which ``answers.compute_answer_quality``
        reads for the engine's own copy of this formula.  They were written here as
        ``[60.0, 40.0]`` — a third record of the same two numbers.  *meta* is optional
        because this path is the event's own reporting rather than cognition, and its
        callers are ``__repr__`` and the summary line; without it the shipped weights
        stand in and are named rather than typed as a bare pair.
        """
        rule_quality = _rule_quality(self.top_rule)
        return round(
            weighted_average(
                [rule_quality, 100.0 - self.temperature],
                _answer_quality_weights(meta),
            )
        )

    def get_relative_quality(self, meta: Any = None) -> float:
        """Scheme: ``get-relative-quality``.  Weights as in
        :meth:`get_absolute_quality`."""
        rel_quality = _rule_relative_quality(self.top_rule)
        return round(
            weighted_average(
                [rel_quality, 100.0 - self.temperature],
                _answer_quality_weights(meta),
            )
        )

    def get_quality(self, meta: Any = None) -> float:
        """Alias for ``get_absolute_quality`` (matches Scheme ``get-quality``)."""
        return self.get_absolute_quality(meta)

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
        # ``make-clamp-event`` (``trace.ss:526-530``) does not just store the concept
        # patterns it was handed: it *derives* one from every theme pattern and clamps
        # those too.  That derivation is the theme pattern's grip on the Slipnet, and
        # it was missing entirely — every clamp carrying themes left the Slipnet alone.
        self.clamped_concept_patterns = list(clamped_concept_patterns or []) + [
            get_associated_concept_pattern(p) for p in self.clamped_theme_patterns
        ]
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
            # ``'workspace'`` is the Scheme's pseudo-type: group events, rule events
            # and concept-mapping events all answer ``(type? 'workspace)``
            # (``trace.ss:780, 860, 958``).  Both the snag-response clamp and the
            # justify clamp use this focus, so without it neither could ever measure
            # any progress at all.
            "workspace": (GROUP_BUILT, RULE_BUILT, CONCEPT_MAPPING_BUILT),
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
        coderack: Any,
        temperature: Temperature,
        workspace: Any = None,
        monitor: Any = None,
    ) -> None:
        """Activate all clamped patterns.

        Scheme: ``activate`` message on clamp-event (``trace.ss:619-640``).
        Undoes any current snag condition, then clamps theme patterns, concept
        patterns, and codelet patterns.

        ``coderack`` and ``temperature`` are **required**.  Both were reachable-but-
        unpassed before, and both mattered:

        * ``coderack`` — the third kind of pattern was stored and forgotten, so the
          rack composition during a clamp was whatever it would have been anyway.
        * ``temperature`` — ``undo-snag-condition`` (``trace.ss:188-196``)
          unconditionally clears ``*temperature-clamped?*``, and Petacat's version
          only does so when handed a temperature.  ``activate`` did not hand it one,
          so once any clamp activated during a snag period the temperature stayed
          frozen for the rest of the run: the temperature system was permanently
          disabled after a snag-then-jootsing sequence.

        ``workspace`` is used only to stamp the ending snag's ``progress_achieved``
        readout; see :meth:`TemporalTrace.undo_snag_condition`.  ``monitor`` is
        forwarded to :func:`clamp_concept_pattern`.
        """
        trace.undo_snag_condition(themespace, slipnet, temperature, workspace)

        # Clamp theme patterns
        for pattern in self.clamped_theme_patterns:
            clamp_theme_pattern(pattern, themespace)

        # Clamp concept patterns
        for pattern in self.clamped_concept_patterns:
            clamp_concept_pattern(pattern, slipnet, monitor)

        # Clamp codelet patterns (``trace.ss:636-640``), against this clamp type's own
        # background (:data:`CLAMP_TYPE_CODELET_BACKGROUNDS`).
        if coderack is not None:
            background = CLAMP_TYPE_CODELET_BACKGROUNDS.get(self.clamp_type)
            for pattern in self.clamped_codelet_patterns:
                if pattern:
                    coderack.clamp_pattern(pattern, background)

    def deactivate(
        self,
        trace: TemporalTrace,
        themespace: Themespace,
        slipnet: Slipnet,
        coderack: Any = None,
    ) -> None:
        """Deactivate all clamped patterns.

        Scheme: ``deactivate`` message on clamp-event (``trace.ss:641-665``).
        """
        # Unclamp theme patterns
        for pattern in self.clamped_theme_patterns:
            unclamp_theme_pattern(pattern, themespace)

        # Unclamp concept patterns
        for pattern in self.clamped_concept_patterns:
            unclamp_concept_pattern(pattern, slipnet)

        # Unclamp codelet patterns (``trace.ss:656-664``).  Without this a rule-codelet
        # clamp pinned rule-scout/evaluator/builder urgencies for the rest of the run.
        if coderack is not None and self.clamped_codelet_patterns:
            coderack.unclamp_all()

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
        workspace_structures: list[Any] | None = None,
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
        #: The Workspace's structure list as it stood when the snag happened.
        #:
        #: ``make-generic-event`` (``trace.ss:333-338``) snapshots
        #: ``(tell *workspace* 'get-structures)`` on every event, and
        #: ``get-new-structures-since-last`` (``trace.ss:96-103``) subtracts that
        #: snapshot from the live list.  That subtraction is what
        #: ``progress-since-last-snag`` measures: every new bridge, group or rule
        #: counts at its live strength.  Petacat measured over *Trace events* instead,
        #: which sees only the handful of structures important enough to have been
        #: recorded — and counted the events' own ``get_strength()``, so a
        #: post-snag clamp event (strength 100) made the snag exit certain.
        self.workspace_structures = list(workspace_structures or [])
        self.progress_achieved: float = 0.0

    # ------------------------------------------------------------------
    # Progress evaluation
    # ------------------------------------------------------------------

    def evaluate_progress(self, structure: Any) -> float:
        """Score a workspace structure for progress since this snag.

        Scheme: ``progress-evaluator`` in ``make-snag-event``
        (``trace.ss:1069-1073``) — the structure's strength unless it is a bond,
        which scores 0.
        """
        from server.engine.bonds import Bond

        # The old test was ``hasattr(structure, "structure_type")``, and no structure
        # class in the port has that attribute — so bonds were never excluded.
        if isinstance(structure, Bond):
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
        themespace: Themespace,
        slipnet: Slipnet,
        coderack: Any,
        codelet_count: int,
        monitor: Any = None,
    ) -> None:
        """Activate the snag condition.

        Scheme: ``activate`` on snag-event (``trace.ss:1155-1162``) — three actions,
        none of which happened in Petacat because nothing ever called this:

        1. ``(tell *trace* 'undo-last-clamp)``.  Note this is the **full** undo, not
           a flag flip: a snag arriving mid-clamp deactivates that clamp's patterns
           and records the progress it achieved.  Petacat's ``undo_last_clamp_raw``
           only cleared ``within_clamp_period``, which would have left the clamp's
           themes frozen and its codelet urgencies pinned forever.
        2. ``clamp-salience`` on each snag object, so attention returns to the site
           of the failure.
        3. ``clamp-concept-pattern`` on the snag concept pattern, pinning the snag
           objects' descriptors at max activation.
        """
        trace.undo_last_clamp(themespace, slipnet, codelet_count, coderack)

        # Clamp salience on snag objects
        for obj in self.snag_objects:
            if hasattr(obj, "clamp_salience"):
                obj.clamp_salience()

        # Clamp concept pattern
        if self.snag_concept_pattern is not None:
            clamp_concept_pattern(self.snag_concept_pattern, slipnet, monitor)

    def deactivate(self, slipnet: Slipnet) -> None:
        """Deactivate the snag condition.

        Scheme: ``deactivate`` message on snag-event (``trace.ss:1163-1169``).
        """
        for obj in self.snag_objects:
            if hasattr(obj, "unclamp_salience"):
                obj.unclamp_salience()

        if self.snag_concept_pattern is not None:
            unclamp_concept_pattern(self.snag_concept_pattern, slipnet)

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
    """Safely extract relative quality from a rule object.

    ``get_relative_quality`` ranks the rule against its Workspace's other rules of
    the same type (``rules.ss:244-251``), so it needs that Workspace; a rule the
    engine built carries the reference.  A rule with none — a translated rule, or
    one a test constructed by hand — has no peers to rank against and scores its
    raw quality, which is the Scheme's own answer when ``(member? self
    ranked-rules)`` is false.
    """
    if rule is None:
        return 0.0
    workspace = getattr(rule, "workspace", None)
    if workspace is not None and hasattr(rule, "get_relative_quality"):
        return float(rule.get_relative_quality(workspace))
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

    Scheme: trace.ss ``clamp-theme-pattern`` (line 1530), which is four steps:

        (tell *themespace* 'delete-theme-type theme-type)
        (impose-theme-pattern theme-pattern)
        (tell *themespace* 'freeze-theme-type theme-type)
        (tell *themespace* 'thematic-pressure-on theme-type)

    The fourth was missing, and it is the one that makes the other three matter.
    §4.2: "the clamping of theme activations in the Themespace automatically turns on
    thematic pressure."  Without it ``get_active_themes`` returns ``[]``
    (thematic pressure is off by default — §4.1.2, "most of the time themes behave as
    passive representational structures"), so all three of §4.1.2's top-down channels
    stay inert however hard the program clamps: theme→Slipnet spreading, the theme
    contribution to bridge and description strength, and Thematic-bridge-scout posting.
    Measured before this fix: 57 clamp activations, ``active_theme_types`` empty after
    every one.
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

        elif "entries" not in pattern:
            # Simple dict: treat remaining keys as dimension -> relation.  Keyed on
            # ``"entries"`` being *absent* rather than empty: a structured pattern that
            # happens to name no entries clamps nothing, and reading its emptiness as
            # "this is the other spelling" made the literal key ``"entries"`` a
            # dimension name.
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

        # Step four of ``clamp-theme-pattern``: a clamped pattern turns thematic
        # pressure on for its own theme type.  Guarded on the type actually naming a
        # cluster, so a pattern of some other kind that reaches here cannot switch
        # pressure on for a theme type that does not exist.
        if theme_type and any(c.theme_type == theme_type for c in themespace.clusters):
            themespace.thematic_pressure_on([theme_type])


def unclamp_theme_pattern(pattern: Any, themespace: Themespace) -> None:
    """Release the clamp *this* pattern imposed.

    Scheme: ``unclamp-theme-pattern`` (``trace.ss:1538-1542``)::

        (let ((theme-type (1st theme-pattern)))
          (tell *themespace* 'unfreeze-theme-type theme-type)
          (tell *themespace* 'thematic-pressure-off theme-type))

    Per theme *type*, not globally: the pattern names one, and the other two are none
    of this clamp's business.  Releasing everything meant the end of one clamp episode
    silently ended every other — which is reachable, since justify-mode's rule
    unification clamps the top and bottom patterns as separate entries of the same
    clamp event, and a manual clamp can be laid on top of a live snag-response one.

    A pattern with no readable type falls back to releasing everything, which is what
    the previous behaviour was for every pattern.
    """
    theme_type = pattern.get("type") if isinstance(pattern, dict) else None
    if theme_type:
        themespace.unclamp_theme_type(theme_type)
    else:
        themespace.unclamp_all()


def _concept_pattern_entries(pattern: Any) -> list[tuple[str, float]]:
    """``(node_name, activation)`` pairs out of either concept-pattern spelling.

    Which spelling a pattern is in is decided by whether ``"entries"`` is *present*,
    not by whether it is non-empty.  An empty list is a perfectly good pattern — it is
    what ``get_snag_concept_pattern`` returns for a snag whose objects carry no
    descriptions — and reading its absence off truthiness sent it down the
    ``node -> activation`` branch, where the key ``"entries"`` became a node name and
    ``float([])`` raised.  That reached the engine through
    ``undo_snag_condition -> SnagEvent.deactivate -> unclamp_concept_pattern``.
    """
    if not pattern or not isinstance(pattern, dict):
        return []
    if "entries" in pattern:
        out = []
        for entry in pattern["entries"]:
            node_name = entry.get("node")
            if node_name:
                out.append((node_name, float(entry.get("activation", 100.0))))
        return out
    # Simple dict: node_name -> activation
    return [
        (name, float(activation))
        for name, activation in pattern.items()
        if name != "type"
    ]


def clamp_concept_pattern(
    pattern: Any, slipnet: Slipnet, monitor: Any = None
) -> None:
    """Clamp concept nodes according to a pattern.

    Scheme: ``clamp-concept-pattern`` (``trace.ss:1547-1552``), which sends each node
    ``(tell node 'clamp act)`` — and ``clamp`` (``slipnet.ss:138-145``) applies
    *unconditionally*.  Petacat skipped any node that happened to be frozen already,
    which silently dropped entries whenever a clamp landed during the initial
    slipnode clamp period or on top of an earlier concept pattern.

    ``monitor``, when given, is called with ``(node, before, after)`` for every node
    the clamp moves.  ``slipnet.ss:139-140`` calls
    ``monitor-slipnode-activation-change`` from inside ``clamp``, so a clamp can
    itself put concept-activation events into the Trace — which is where Figure
    4.12's ``(Opposite)`` events come from, and which the Scheme relies on for event
    ordering (``justify.ss:172-174``).  Sampling activations at cycle boundaries, as
    the runner does, nets a clamp's delta out against the decay that follows it.
    """
    for node_name, activation in _concept_pattern_entries(pattern):
        node = slipnet.nodes.get(node_name)
        if node is None:
            continue
        before = node.activation
        node.clamp(0, activation)
        if monitor is not None and before != node.activation:
            monitor(node, before, node.activation)


def unclamp_concept_pattern(pattern: Any, slipnet: Slipnet) -> None:
    """Unfreeze the nodes *this* pattern froze.

    Scheme: ``unclamp-concept-pattern`` (``trace.ss:1554-1557``) — ``(tell (1st entry)
    'unfreeze)`` for each entry of the pattern, and nothing else.  Petacat unfroze
    every node in the Slipnet, so ending one clamp released every other clamp in
    force, including the run's initial slipnode clamp.
    """
    for node_name, _activation in _concept_pattern_entries(pattern):
        node = slipnet.nodes.get(node_name)
        if node is not None:
            node.unclamp()


def theme_pattern_entries(pattern: Any) -> list[tuple[str, str | None, float]]:
    """``(dimension, relation, activation)`` triples out of either pattern spelling.

    Petacat carries theme patterns in two shapes — the structured dict
    ``{"type": t, "entries": [{"dimension", "relation", "activation"}]}`` and the
    Scheme-shaped list ``[t, (dimension, relation), ...]`` returned by
    ``get_dominant_theme_pattern``.  Everything that has to *read* a pattern rather
    than clamp it goes through here, so a new reader cannot silently understand only
    one of them.  The default activation is ``%max-theme-activation%``, matching
    ``trace.ss:1509`` (a two-element entry means "at full activation").
    """
    if not pattern:
        return []
    if isinstance(pattern, dict):
        out: list[tuple[str, str | None, float]] = []
        for entry in pattern.get("entries", []):
            if isinstance(entry, dict):
                dim = entry.get("dimension")
                if dim is None:
                    continue
                out.append(
                    (dim, entry.get("relation"), float(entry.get("activation", 100.0)))
                )
            elif len(entry) >= 2:
                act = float(entry[2]) if len(entry) > 2 else 100.0
                out.append((entry[0], entry[1], act))
        return out
    if isinstance(pattern, (list, tuple)):
        out = []
        for entry in pattern[1:]:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                act = float(entry[2]) if len(entry) > 2 else 100.0
                out.append((entry[0], entry[1], act))
        return out
    return []


def get_associated_concept_pattern(theme_pattern: Any) -> dict[str, Any]:
    """The concept pattern a theme pattern drags into the Slipnet with it.

    Scheme: ``get-associated-concept-pattern`` (``trace.ss:1503-1516``).  For every
    entry, the theme's **dimension node** is pinned at ``%max-activation%``; and when
    the relation is ``opposite``, ``plato-opposite`` is pinned at 100 for a positive
    theme and at **0** for a negative one — a negative snag-response clamp does not
    merely stop favouring "opposite", it actively suppresses the concept.

    Without this, clamping a theme pattern left the Slipnet untouched, and a whole
    channel of the clamp's influence (§4.2) simply did not exist.
    """
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()

    def add(node_name: str, activation: float) -> None:
        key = (node_name, activation)
        if key in seen:
            return
        seen.add(key)
        entries.append({"node": node_name, "activation": activation})

    for dimension, relation, activation in theme_pattern_entries(theme_pattern):
        add(dimension, 100.0)
        if relation == "opposite":
            add("plato-opposite", 100.0 if activation > 0 else 0.0)
    return {"type": "concepts", "entries": entries}


def get_snag_theme_pattern(concept_mappings: list[Any]) -> list[Any]:
    """The vertical theme pattern a snag rested on.

    Scheme: ``get-snag-theme-pattern`` (``trace.ss:1031-1039``) — one entry per
    distinct ``(CM-type, label)`` of the concept-mappings on the snag objects'
    vertical bridges, in the Scheme's list spelling
    ``[theme_type, (dimension, relation), ...]``.

    This is *not* the Themespace's dominant vertical pattern, which is what Petacat
    recorded.  Dominance requires a cluster lead of more than 90 points, so a cluster
    with two live themes contributes nothing and the pattern is routinely empty —
    and the jootser's snag-overlap table then compares empty patterns and never
    fires.  What the failed interpretation actually rested on is the complete set of
    (dimension, relation) pairs its mappings assert, dominant or not.
    """
    from server.engine.themes import THEME_VERTICAL_BRIDGE, relation_name_for_label

    entries: list[tuple[str, str]] = []
    for cm in concept_mappings:
        dimension = getattr(getattr(cm, "description_type1", None), "name", None)
        if dimension is None:
            continue
        entry = (dimension, relation_name_for_label(getattr(cm, "label", None)))
        if entry not in entries:
            entries.append(entry)
    return [THEME_VERTICAL_BRIDGE, *entries]


def get_snag_concept_pattern(snag_objects: list[Any]) -> dict[str, Any]:
    """Every descriptor of every snag object, pinned at max activation.

    Scheme: ``get-snag-concept-pattern`` (``trace.ss:1042-1048``).  Clamped by
    ``SnagEvent.activate``, this is what holds the impasse's own concepts up while
    the program searches for a way around it.
    """
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for obj in snag_objects:
        for description in getattr(obj, "descriptions", []):
            name = getattr(getattr(description, "descriptor", None), "name", None)
            if name is None or name in seen:
                continue
            seen.add(name)
            entries.append({"node": name, "activation": 100.0})
    return {"type": "concepts", "entries": entries}


def concept_activation_importance(node: Any, before: float, after: float) -> float:
    """How much a change in a node's activation matters — ``trace.ss:1345-1348``.

    ``(100* (* (% (abs delta)) (% (cd slipnode))))`` — the **product** of the
    magnitude of the change and the concept's depth, over the **absolute** change.
    """
    return abs(after - before) * node.conceptual_depth / 100.0


def make_concept_activation_monitor(
    trace: TemporalTrace,
    codelet_count: int,
    temperature: float,
    threshold: float,
) -> Any:
    """A ``clamp_concept_pattern`` monitor that records concept-activation events.

    ``slipnet.ss:139-140``: ``clamp`` calls ``monitor-slipnode-activation-change``,
    so clamping a concept can itself put an event into the Trace.  The Scheme relies
    on that for event *ordering* (``justify.ss:172-174``), and it is where Figure
    4.12's ``(Opposite)`` events come from.  Petacat sampled activations only at
    update-cycle boundaries, where a clamp's delta nets out against the decay that
    follows it, so a clamp never produced one.
    """

    def monitor(node: Any, before: float, after: float) -> None:
        if concept_activation_importance(node, before, after) >= threshold:
            trace.record_event(
                TraceEvent(
                    event_type=CONCEPT_ACTIVATION,
                    codelet_count=codelet_count,
                    temperature=temperature,
                    description=(
                        f"the concept of {node.short_name} became active"
                    ),
                    # ``trace.ss:718, 720`` — the node itself, and its conceptual depth
                    # as the event's strength.
                    slipnode=node,
                    strength=float(node.conceptual_depth),
                )
            )

    return monitor


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
                theme.activation = activation
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
        # Every event counts, clamp events included.  §4.5.1: the progress-watcher
        # "examines the most recent event in the Trace (which may or may not be the most
        # recent clamp event) in order to determine how much time has elapsed since the
        # event occurred" — the parenthesis is explicit that a clamp qualifies, and
        # ``jootsing.ss:262`` asks for ``(get-elapsed-time 'any)``.  Excluding clamps
        # meant a clamp made long after the last structure event was born already older
        # than the 250-codelet settling period, so the next progress-watcher tore it
        # down immediately.
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
        coderack: Any = None,
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
            last_clamp.deactivate(self, themespace, slipnet, coderack)

        return progress

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

    def progress_since_last_snag(self, workspace: Any) -> float:
        """How much has been rebuilt since the last snag.

        Scheme: ``progress-since-last-snag`` (``trace.ss:182-187``) — the snag's
        progress evaluator applied to ``get-new-structures-since-last 'snag``
        (``trace.ss:96-103``), which is the *live Workspace structure list* minus the
        snapshot the snag event took, maximum over the result, 0 when empty.

        Every new bridge, group or rule counts at its live strength; bonds score 0.
        This is the whole of the stochastic snag exit's input (``run.ss:299-302``:
        leave the snag period with probability ``progress/100`` per update cycle), so
        measuring it over Trace events instead — which is what Petacat did — made
        ordinary rebuilding invisible while making any post-snag clamp event an
        instant exit.
        """
        last_snag = self.get_last_event(SNAG)
        if last_snag is None:
            return 0.0

        if isinstance(last_snag, SnagEvent):
            snapshot = {id(s) for s in last_snag.workspace_structures}
            return max(
                (
                    last_snag.evaluate_progress(structure)
                    for structure in workspace.all_structures
                    if id(structure) not in snapshot
                ),
                default=0.0,
            )

        # Fallback for plain TraceEvents (``record_snag`` on the trace, used by tests
        # and by the legacy persistence path): nothing was snapshotted, so there is no
        # "since" to measure against.
        new_events = self.get_new_events_since_last(SNAG)
        if not new_events:
            return 0.0
        return max((e.get_strength() for e in new_events), default=0.0)

    def undo_snag_condition(
        self,
        themespace: Themespace | None,
        slipnet: Slipnet | None,
        temperature: Temperature,
        workspace: Any = None,
    ) -> None:
        """Exit the snag state and unclamp temperature.

        Scheme: ``undo-snag-condition`` (``trace.ss:188-196``).  ``temperature`` is
        required: the Scheme's ``(set! *temperature-clamped?* #f)`` is unconditional,
        and making it conditional on an optional argument is how the temperature came
        to stay clamped for the rest of any run in which a clamp activated during a
        snag period.

        ``workspace`` is optional and feeds only the ``progress_achieved`` readout the
        commentary prints; the *decision* to leave the snag period is the runner's
        (``run.ss:299-302``) and it always has a Workspace.  Left out, the snag keeps
        whatever figure it already carried.
        """
        if not self.within_snag_period:
            return

        self.within_snag_period = False

        last_snag = self.get_last_event(SNAG)
        if isinstance(last_snag, SnagEvent):
            if workspace is not None:
                last_snag.progress_achieved = self.progress_since_last_snag(workspace)
            if slipnet is not None:
                last_snag.deactivate(slipnet)

        # Unclamp temperature (Scheme: (set! *temperature-clamped?* #f))
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
