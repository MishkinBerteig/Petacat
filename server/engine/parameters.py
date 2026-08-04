"""The run parameters: what may be set before a Run, and what is derived from it.

A Run's behaviour is fixed by more than its problem and its seed.  Twenty-five entries in
``engine_params.json`` are read by the engine while it thinks — thresholds, periods,
capacities, the update cadence — and until now every one of them was global: editable
only in the Admin panel, applying to every Run at once, and recorded in a Run's row only
indirectly through the config hash.  That makes an experiment awkward to run and a past
Run awkward to interpret, because the parameters it executed under were whatever the
global configuration happened to be at the time.

This module is the catalogue that makes them per-Run.  It exists as data rather than as
scattered validation because three places need the same answer: the API, which must
reject an unknown or out-of-range override; the persistence layer, which stores the
resolved set on the Run; and the interface, which has to render a control of the right
kind with the right bounds and say what the parameter does.

Fixed and derived
-----------------
**Fixed** parameters are inputs: chosen before the first codelet, constant for the whole
Run.  Those are the twenty-five below.

**Derived** values are outputs: the numeric backend that was actually selected, the shard
count sharding actually settled on, the config and memory hashes, the Training Session.
They belong beside the fixed parameters when reading a Run — they are equally part of
"what this Run was" — but they cannot be set, and presenting them as though they could
be would be a lie about how the engine works.

What is deliberately *not* here
-------------------------------
Eighteen further entries in ``engine_params.json`` are not run parameters and are not
offered: display timings (``codelet_highlight_pause``, ``initial_speed``,
``text_scroll_pause``, the flash settings), Scheme-era implementation details
(``garbage_collect_cycles``, ``step_cycles``), and a handful the port reads nowhere at
all (``expiration_period``, ``max_theme_activation``, ``workspace_activation``,
``shrunk_link_lengths``, and others).  Offering a control that changes nothing is worse
than offering none, so membership here is decided by *what the engine actually reads*,
verified against the source rather than assumed.

Formula coefficients and urgency levels stay global.  They are the model's constants
rather than a run's settings — there are fifty-odd of them, they are already editable in
the Admin panel, and the config hash covers them, so a Run that executed under changed
coefficients is still distinguishable in the record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: How a parameter should be presented and validated.
KIND_INT = "int"
KIND_FLOAT = "float"
KIND_BOOL = "bool"
KIND_NODE_LIST = "node_list"
KIND_NODE_MAP = "node_map"

#: Grouping for presentation.  Not semantic — the engine does not care — but a flat list
#: of twenty-five numbers is unreadable, and these are the divisions the architecture
#: itself uses.
GROUP_TEMPERATURE = "Temperature and pacing"
GROUP_SLIPNET = "Slipnet"
GROUP_CODERACK = "Coderack"
GROUP_THEMES = "Themespace"
GROUP_ATTENTION = "Attention thresholds"
GROUP_SELF_WATCHING = "Self-watching"


@dataclass(frozen=True)
class RunParameter:
    """One settable parameter, with everything three layers need to know about it."""

    name: str
    kind: str
    group: str
    label: str
    #: What it does, and what changing it costs. Shown in the interface, so it is written
    #: for someone deciding whether to change it rather than for someone who wrote it.
    description: str
    minimum: float | None = None
    maximum: float | None = None
    #: ``True`` when moving this away from its default makes a Run incomparable with the
    #: dissertation's results, which is a different and stronger warning than "unusual".
    departs_from_original: bool = True

    def validate(self, value: Any) -> Any:
        """Coerce and range-check, or raise ``ValueError`` naming the parameter.

        Coercing rather than rejecting a float where an int belongs, because JSON has one
        number type and a client that sends ``15.0`` for ``update_cycle_length`` means 15.
        """
        if self.kind == KIND_BOOL:
            if not isinstance(value, bool):
                raise ValueError(f"{self.name} must be true or false, got {value!r}")
            return value

        if self.kind == KIND_NODE_LIST:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"{self.name} must be a list of Slipnet node names")
            return list(value)

        if self.kind == KIND_NODE_MAP:
            if not isinstance(value, dict) or not all(
                isinstance(k, str) and isinstance(v, (int, float)) for k, v in value.items()
            ):
                raise ValueError(f"{self.name} must map Slipnet node names to numbers")
            return dict(value)

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{self.name} must be a number, got {value!r}")
        number = int(value) if self.kind == KIND_INT else float(value)
        if self.kind == KIND_INT and float(value) != number:
            raise ValueError(f"{self.name} must be a whole number, got {value!r}")
        if self.minimum is not None and number < self.minimum:
            raise ValueError(f"{self.name} must be at least {self.minimum}, got {number}")
        if self.maximum is not None and number > self.maximum:
            raise ValueError(f"{self.name} must be at most {self.maximum}, got {number}")
        return number


def _p(name, kind, group, label, description, minimum=None, maximum=None,
       departs=True) -> RunParameter:
    return RunParameter(name, kind, group, label, description, minimum, maximum, departs)


#: The twenty-five parameters the engine reads while it runs.  Verified against
#: ``get_param`` call sites in ``server/engine/**`` and in the codelet bodies stored in
#: ``seed_data/codelet_types.json``; a parameter that is only read by the API or the
#: display is not here.
RUN_PARAMETERS: tuple[RunParameter, ...] = (
    # -- Temperature and pacing -------------------------------------------
    _p("initial_temperature", KIND_INT, GROUP_TEMPERATURE, "Initial temperature",
       "Where the run starts on the 100-is-confused scale. Temperature is the inverse "
       "measure of how well the problem has been organised, and it regulates how random "
       "codelet selection is, so starting below 100 makes the run greedy before it has "
       "any structure to be greedy about.", 0, 100),
    _p("update_cycle_length", KIND_INT, GROUP_TEMPERATURE, "Update cycle length",
       "How many codelets run between full recomputations of strengths, saliences, "
       "activations and temperature. A codelet therefore reads values up to this many "
       "codelets stale even in the strictly serial engine. Marshall's source sets it to "
       "15 with no stated reason; note that clamp durations are counted in codelets "
       "while the initial Slipnet clamp is counted in cycles, so changing this silently "
       "changes the relationship between them.", 1, 1000),
    _p("max_activation", KIND_INT, GROUP_SLIPNET, "Maximum activation",
       "The ceiling for Slipnet node activation. Descriptions attached at "
       "initialisation set their descriptors to this value.", 1, 1000),

    # -- Slipnet ------------------------------------------------------------
    _p("spreading_activation_threshold", KIND_INT, GROUP_SLIPNET,
       "Spreading activation threshold",
       "Which nodes are allowed to spread activation. 100 means only fully-active nodes "
       "spread, which is the original's behaviour; 0 means every active node spreads in "
       "proportion, which explores more widely. A run at any other value is not "
       "comparable with the dissertation's results.", 0, 100),
    _p("full_activation_threshold", KIND_INT, GROUP_SLIPNET, "Full-activation threshold",
       "The activation at which a node begins to exert top-down pressure by posting "
       "codelets of its own, and above which it may jump to full activation. Not the "
       "same as being *fully* active: that is exactly 100, and it is what shrinks a "
       "concept's links and makes its descriptions and concept-mappings count as "
       "relevant.", 0, 100),
    _p("initial_slipnode_clamp_cycles", KIND_INT, GROUP_SLIPNET,
       "Initial clamp duration (cycles)",
       "How long the initially-relevant nodes are held at full activation at the start "
       "of a run, in update cycles rather than codelets. The warm-up that stops the run "
       "wandering before it has any structure.", 0, 1000),
    _p("initially_clamped_slipnodes", KIND_NODE_LIST, GROUP_SLIPNET,
       "Initially clamped nodes",
       "Which concepts are held active during the warm-up. Changing this changes what "
       "the run is predisposed to notice first.", ),
    _p("top_down_slipnodes", KIND_NODE_LIST, GROUP_SLIPNET, "Top-down nodes",
       "Which concepts may post codelets of their own once fully active. This is the "
       "channel by which the Slipnet directs perception rather than only recording it."),
    _p("intrinsic_link_lengths", KIND_NODE_MAP, GROUP_SLIPNET, "Intrinsic link lengths",
       "The conceptual distance of each labelled link. Shorter means the two concepts "
       "are closer, so activation spreads more readily and a slippage between them is "
       "cheaper — which is the mechanism by which one concept can stand in for another."),

    # -- Coderack -----------------------------------------------------------
    _p("max_coderack_size", KIND_INT, GROUP_CODERACK, "Coderack capacity",
       "How many codelets may wait at once. The cap is why the codelet mix keeps "
       "tracking the current Workspace instead of drifting: on a typical run the rack "
       "sits at capacity for well over half of all posts, so raising this materially "
       "reduces eviction pressure. Under free-running the capacity is divided across "
       "shards, and a shard below 25 is too small for the jootsing sequence to "
       "complete.", 10, 10_000),
    _p("num_coderack_bins", KIND_INT, GROUP_CODERACK, "Urgency bins",
       "How many urgency levels the rack is divided into. Selection picks a bin with "
       "probability proportional to its count times its urgency weight, then picks "
       "uniformly within it, so this is the resolution of the whole selection "
       "mechanism.", 1, 32),
    _p("verbatim_rule_probability", KIND_FLOAT, GROUP_CODERACK,
       "Verbatim rule probability",
       "The chance a rule scout ignores the bridges and simply describes the answer "
       "string literally, bypassing abstraction. Small by design: it is an escape hatch "
       "from an interpretation that has gone nowhere, not a strategy.", 0.0, 1.0),

    # -- Themespace ---------------------------------------------------------
    _p("theme_boost_amount", KIND_INT, GROUP_THEMES, "Theme boost",
       "How hard a built bridge pushes its themes. Larger makes the self-watching layer "
       "commit to an interpretation faster.", 0, 100),
    _p("theme_decay_amount", KIND_INT, GROUP_THEMES, "Theme decay",
       "How fast theme activation falls when nothing reinforces it. The counterweight "
       "to the boost: together these set how long an interpretation persists without "
       "support.", 0, 100),
    _p("theme_spread_amount", KIND_INT, GROUP_THEMES, "Theme spread",
       "How much activation flows between themes within a cluster — the excitation "
       "between compatible themes and the inhibition between opposing ones.", 0, 100),
    _p("dominant_theme_margin", KIND_INT, GROUP_THEMES, "Dominance margin",
       "How far a theme must exceed its rivals before it counts as dominant and starts "
       "exerting thematic pressure on what gets built.", 0, 200),

    # -- Attention thresholds -----------------------------------------------
    _p("concept_activation_importance_threshold", KIND_INT, GROUP_ATTENTION,
       "Concept-activation event threshold",
       "How important a change in a concept's activation must be before the Temporal "
       "Trace records it. The Trace is the cognitive level — a few dozen events per run "
       "— so lowering this floods it with the micro-events it exists to filter out.",
       0, 200),
    _p("concept_mapping_importance_threshold", KIND_INT, GROUP_ATTENTION,
       "Slippage event threshold",
       "How important a slippage must be to reach the Trace. Importance rises with the "
       "conceptual depth of the concepts involved and the size of the objects.", 0, 200),
    _p("group_importance_threshold", KIND_INT, GROUP_ATTENTION, "Group event threshold",
       "How important a new group must be to reach the Trace. Single-letter and "
       "whole-string groups count as especially important.", 0, 400),
    _p("rule_importance_threshold", KIND_INT, GROUP_ATTENTION, "Rule event threshold",
       "How important a new rule must be to reach the Trace.", 0, 200),

    # -- Self-watching --------------------------------------------------------
    _p("self_watching_enabled_default", KIND_BOOL, GROUP_SELF_WATCHING,
       "Self-watching enabled",
       "Whether the Themespace, progress-watchers and jootsers run at all. Off, Petacat "
       "is closer to Copycat: it can still solve problems but cannot notice that it is "
       "stuck, so it cannot break out of a repeating failure."),
    _p("grace_period", KIND_INT, GROUP_SELF_WATCHING, "Clamp grace period",
       "How long after a clamp is applied before another may be considered, in "
       "codelets. Without it the jootsers would re-clamp before the previous attempt "
       "had a chance to work.", 0, 10_000),
    _p("max_clamp_period", KIND_INT, GROUP_SELF_WATCHING, "Maximum clamp period",
       "The longest a theme clamp may hold, in codelets. Counted in codelets while the "
       "initial Slipnet clamp is counted in update cycles.", 0, 100_000),
    _p("settling_period", KIND_INT, GROUP_SELF_WATCHING, "Settling period",
       "How long the run is left alone after a snag before progress is judged, in "
       "codelets.", 0, 10_000),
    _p("satisfactory_rule_quality", KIND_INT, GROUP_SELF_WATCHING,
       "Satisfactory rule quality",
       "The rule quality above which the jootsers consider the interpretation good "
       "enough not to disturb.", 0, 100),
)

PARAMETERS_BY_NAME: dict[str, RunParameter] = {p.name: p for p in RUN_PARAMETERS}


class UnknownParameter(ValueError):
    """An override named something that is not a run parameter."""


def validate_overrides(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Check a set of overrides, returning the coerced values.

    Rejects unknown names rather than ignoring them.  Ignoring is the tempting choice —
    it keeps old clients working — but a typo in a parameter name would then silently
    produce a Run at the default, and the record would say the override was applied.
    """
    if not overrides:
        return {}
    unknown = sorted(set(overrides) - set(PARAMETERS_BY_NAME))
    if unknown:
        raise UnknownParameter(
            f"not run parameters: {', '.join(unknown)}. "
            f"Settable parameters are: {', '.join(sorted(PARAMETERS_BY_NAME))}"
        )
    return {
        name: PARAMETERS_BY_NAME[name].validate(value)
        for name, value in overrides.items()
    }


def describe_parameters(meta: Any) -> list[dict]:
    """The catalogue plus each parameter's current default, for the interface."""
    return [
        {
            "name": p.name,
            "kind": p.kind,
            "group": p.group,
            "label": p.label,
            "description": p.description,
            "minimum": p.minimum,
            "maximum": p.maximum,
            "departs_from_original": p.departs_from_original,
            "default": meta.get_param(p.name),
        }
        for p in RUN_PARAMETERS
    ]


def resolved_parameters(meta: Any) -> dict[str, Any]:
    """Every run parameter's value under ``meta`` — the set a Run actually executed with.

    Stored whole on Normal and Audit Runs rather than storing only the overrides.  The
    difference matters when the global configuration changes afterwards: overrides alone
    would have to be read against whatever the defaults are *now*, and a Run's record
    would quietly change meaning. The resolved set is self-contained.
    """
    return {p.name: meta.get_param(p.name) for p in RUN_PARAMETERS}
