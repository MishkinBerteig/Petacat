"""Built-in functions available to codelet Python programs.

These are the primitive operations that codelet execute_body code can call.
Each function takes an EngineContext as its first argument (pre-bound by
the interpreter, so codelets just call e.g. `choose_object("intra")`).

Organized by category:
- Object selection
- Structure proposals
- Structure evaluation and building
- Stochastic decisions
- Slipnet queries
- Workspace queries
- Codelet posting
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.engine.runner import EngineContext

from server.engine.bonds import Bond
from server.engine.bridges import Bridge
from server.engine.coderack import Codelet
from server.engine.concept_mappings import ConceptMapping
from server.engine.descriptions import Description
from server.engine.formulas import temp_adjusted_probability, temp_adjusted_values
from server.engine.groups import Group
from server.engine.rules import Rule
from server.engine.trace import (
    ANSWER_FOUND,
    BOND_BROKEN,
    BOND_BUILT,
    BRIDGE_BROKEN,
    BRIDGE_BUILT,
    CLAMP_END,
    CLAMP_START,
    DESCRIPTION_BUILT,
    GROUP_BROKEN,
    GROUP_BUILT,
    RULE_BROKEN,
    RULE_BUILT,
    SNAG,
    TraceEvent,
)
from server.engine.workspace_objects import Letter


def get_builtins() -> dict[str, Any]:
    """Return the registry of all built-in functions for codelet programs."""
    return {
        # Object selection
        "choose_object": choose_object,
        "choose_string_object": choose_string_object,
        "choose_neighbor": choose_neighbor,
        "choose_string": choose_string,
        # Structure proposals
        "propose_bond": propose_bond,
        "propose_description": propose_description,
        "activate_from_workspace": activate_from_workspace,
        # Structure evaluation
        "evaluate_structure": evaluate_structure,
        "build_structure": build_structure,
        "break_structure": break_structure,
        # Stochastic helpers
        "prob": prob,
        "weighted_pick": weighted_pick,
        "temp_adjusted_prob": _temp_adjusted_prob,
        "temp_adjusted_vals": _temp_adjusted_vals,
        # Slipnet queries
        "get_node": get_node,
        "get_activation": get_activation,
        "fully_active": fully_active,
        "get_bond_category": get_bond_category,
        "object_has_description_type": object_has_description_type,
        "possible_descriptor": possible_descriptor,
        "descriptor_support": descriptor_support,
        "single_letter_group_probability": single_letter_group_probability,
        # Workspace queries
        "get_objects": get_objects,
        "get_string_objects": get_string_objects,
        "get_built_bonds": get_built_bonds,
        "get_built_bridges": get_built_bridges,
        "mapping_strength": mapping_strength,
        "has_supported_rule": has_supported_rule,
        # Codelet posting
        "post_codelet": post_codelet,
        # Trace
        "record_event": record_event,
        "record_snag": record_snag,
        "give_up": give_up,
        # Answer reporting
        "report_answer": report_answer,
        # Rule operations
        "translate_rule": translate_rule,
        "apply_rule": apply_rule,
    }


# ── Object selection ──

def choose_object(ctx: EngineContext, weight_key: str = "intra") -> Any:
    """Choose a workspace object weighted by salience/importance."""
    return ctx.workspace.choose_object(weight_key, ctx.rng)


def choose_string_object(ctx: EngineContext, string: Any, weight_key: str = "intra") -> Any:
    """Choose an object from a specific string."""
    return string.choose_object(weight_key, ctx.rng)


def choose_neighbor(ctx: EngineContext, obj: Any) -> Any:
    """Choose a positionally-adjacent neighbour at the *same level* as *obj*.

    Bonds join adjacent objects, and "adjacent" has to respect the grouping
    hierarchy: a group's neighbour is the next group, not a letter inside it.

    ``get_object_at`` returns the first object covering a position, and letters
    always precede groups in ``string.objects``, so this used to hand back a
    letter every time.  Groups could therefore never be bonded to one another and
    a group *of groups* was unreachable — which is how ``kkjjii`` becomes a
    predecessor group of sameness groups (Fig. 4.2) and ``mrrjjj`` a 1-2-3 length
    group (§5.2.1 Run 1).
    """
    string = getattr(obj, "string", None)
    if string is None:
        return None

    enclosing = getattr(obj, "enclosing_group", None)
    neighbors = [
        o
        for o in getattr(string, "objects", [])
        if o is not obj
        and getattr(o, "enclosing_group", None) is enclosing
        and (
            o.right_string_pos == obj.left_string_pos - 1
            or o.left_string_pos == obj.right_string_pos + 1
        )
    ]
    if not neighbors:
        return None
    weights = [max(0.1, n.salience.get("intra", 1.0)) for n in neighbors]
    return ctx.rng.weighted_pick(neighbors, weights)


def choose_string(ctx: EngineContext, weight_fn: str = "unhappiness") -> Any:
    """Choose a workspace string weighted by unhappiness."""
    strings = ctx.workspace.all_strings
    weights = [max(0.1, s.get_average_intra_string_unhappiness()) for s in strings]
    return ctx.rng.weighted_pick(strings, weights)


# ── Structure proposals ──

def propose_bond(
    ctx: EngineContext,
    from_obj: Any,
    to_obj: Any,
    bond_category: Any,
    bond_facet: Any,
    from_descriptor: Any,
    to_descriptor: Any,
    direction: Any = None,
) -> Bond:
    """Create a proposed bond and post an evaluator.

    Scheme: ``propose-bond`` (bonds.ss:321-337) activates the two object
    descriptors and the bond facet from the Workspace.
    """
    activate_from_workspace(ctx, from_descriptor, to_descriptor, bond_facet)
    bond = Bond(from_obj, to_obj, bond_category, bond_facet,
                from_descriptor, to_descriptor, direction)
    bond.time_stamp = ctx.codelet_count
    urgency = round(bond_category.activation) if hasattr(bond_category, 'activation') else 35
    post_codelet(ctx, "bond-evaluator", urgency, structure=bond)
    return bond


def propose_description(
    ctx: EngineContext,
    obj: Any,
    description_type: Any,
    descriptor: Any,
) -> Description:
    """Create a proposed description and post an evaluator.

    Scheme: ``propose-description`` (descriptions.ss:172-180).
    """
    activate_from_workspace(ctx, descriptor)
    desc = Description(obj, description_type, descriptor)
    desc.time_stamp = ctx.codelet_count
    urgency = round(description_type.activation) if hasattr(description_type, 'activation') else 35
    post_codelet(ctx, "description-evaluator", urgency, structure=desc)
    return desc


def activate_from_workspace(ctx: EngineContext, *nodes: Any) -> None:
    """Jolt each Slipnet node from the Workspace.

    Scheme: ``activate-from-workspace`` (slipnet.ss:171).  Called by proposers,
    evaluators and builders alike — this constant stream of re-activation is
    what keeps the relevant concepts above the relevance threshold, since nodes
    decay steeply between update cycles.
    """
    for node in nodes:
        if node is not None and hasattr(node, "activate_from_workspace"):
            node.activate_from_workspace()


# ── Structure lifecycle ──

def evaluate_structure(ctx: EngineContext, structure: Any) -> bool:
    """Evaluate a proposed structure. Returns True if it passes."""
    structure.update_strength()
    accept_prob = temp_adjusted_probability(
        structure.strength / 100.0,
        ctx.temperature.value,
        ctx.meta,
    )
    if ctx.rng.prob(accept_prob):
        structure.proposal_level = structure.EVALUATED
        return True
    return False


def build_structure(ctx: EngineContext, structure: Any) -> bool:
    """Build an evaluated structure into the workspace.

    For bonds, groups, and bridges: first fight incompatible structures.
    If any fight is lost, the build fails (returns False).
    If all fights are won, break the losers and build.

    Scheme: bonds.ss:354-407, groups.ss:622-771, bridges.ss:1183-1298.
    """
    # Descriptions and rules don't fight
    if isinstance(structure, Description):
        structure.proposal_level = structure.BUILT
        if structure not in structure.object.descriptions:
            structure.object.descriptions.append(structure)
        return True
    elif isinstance(structure, Rule):
        structure.proposal_level = structure.BUILT
        ctx.workspace.add_rule(structure)
        _record_rule_event(ctx, structure)
        return True

    # Don't build a structure the Workspace already has.  Scheme: the builders
    # all check ``bond-present?`` / ``group-present?`` / ``bridge-present?``
    # before doing anything.  Without this the bridge lists filled up with
    # dozens of duplicate a-a bridges, inflating mapping strength.
    if _equivalent_structure_exists(ctx, structure):
        return False

    # For bonds, groups, bridges: fight incompatibles first
    incompatibles = _get_incompatible_structures(ctx, structure)
    for opponent, proposer_weight, opponent_weight in incompatibles:
        if not _wins_fight(ctx, structure, proposer_weight, opponent, opponent_weight):
            return False  # Lost a fight — don't build

    # Won all fights — break incompatibles and build
    for opponent, _, _ in incompatibles:
        break_structure(ctx, opponent)

    structure.proposal_level = structure.BUILT
    if isinstance(structure, Bond):
        structure.string.add_bond(structure)
        return True
    elif isinstance(structure, Group):
        structure.string.add_group(structure)
        _record_group_event(ctx, structure)
        return True
    elif isinstance(structure, Bridge):
        ctx.workspace.add_bridge(structure)
        _record_slippage_events(ctx, structure)
        return True
    return False


# ── Trace: which events are important enough to record ──
#
# §4.4: "each event ... has an importance value associated with it, and only
# those events with an importance value above some threshold get explicitly
# represented in the Trace, allowing Metacat to effectively filter out the
# 'background noise' of a run."  The Trace is the cognitive level — a run is a
# few dozen events, not the hundreds of micro-events the Workspace generates.
# Bonds and descriptions never reach it at all; groups, slippages and rules do,
# but only when they clear their threshold.


def _record_group_event(ctx: EngineContext, group: Group) -> None:
    """Record an important group.  §4.4: importance is a function of a group's
    strength and size, "with single-letter groups and whole-string groups being
    particularly important"."""
    threshold = ctx.meta.get_param("group_importance_threshold", 100)
    size_bonus = 100.0 if (group.spans_whole_string() or group.length == 1) else 50.0
    importance = (group.strength + size_bonus) / 2.0 * 2.0
    if importance >= threshold:
        record_event(
            ctx,
            GROUP_BUILT,
            structures=[group],
            description=f"perceived {group.string.text} group",
        )


def _record_slippage_events(ctx: EngineContext, bridge: Bridge) -> None:
    """Record the important slippages a new bridge rests on.

    §4.4: importance "is normally a function of the conceptual depths of a
    slippage's concepts, and of the size of the Workspace objects involved.  As
    a special case, however, if a slippage is made under the influence of
    thematic pressure and is compatible with the set of clamped themes, it is
    deemed to be of very high importance, regardless of the concepts or objects
    involved."
    """
    from server.engine.trace import CONCEPT_MAPPING_BUILT

    threshold = ctx.meta.get_param("concept_mapping_importance_threshold", 65)
    under_pressure = ctx.themespace.has_thematic_pressure([bridge.theme_type])

    for cm in bridge.concept_mappings:
        if cm.is_identity:
            continue
        importance = cm.conceptual_depth + 10.0 * (
            bridge.object1.span + bridge.object2.span
        )
        if under_pressure and _slippage_matches_active_theme(ctx, bridge, cm):
            importance = 100.0
        if importance >= threshold:
            record_event(
                ctx,
                CONCEPT_MAPPING_BUILT,
                structures=[bridge],
                description=f"slippage {cm}",
            )


def _slippage_matches_active_theme(
    ctx: EngineContext, bridge: Bridge, cm: ConceptMapping
) -> bool:
    from server.engine.themes import relation_name_for_label

    dimension = getattr(cm.description_type1, "name", "")
    relation = relation_name_for_label(cm.label)
    for theme in ctx.themespace.get_active_themes(bridge.theme_type):
        if theme.dimension == dimension and theme.relation == relation:
            return theme.activation > 0
    return False


def _record_rule_event(ctx: EngineContext, rule: Rule) -> None:
    """Record an important rule.  §4.4: importance is "a function of the relative
    quality of a rule with respect to all other rules that already exist"."""
    threshold = ctx.meta.get_param("rule_importance_threshold", 67)
    if rule.get_relative_quality(ctx.workspace) >= threshold:
        record_event(
            ctx,
            RULE_BUILT,
            structures=[rule],
            description=rule.transcribe_to_english(),
        )


def _equivalent_structure_exists(ctx: EngineContext, structure: Any) -> bool:
    """Is a structurally identical, already-built structure present?"""
    if isinstance(structure, Bond):
        return any(
            b is not structure
            and b.is_built
            and b.from_object is structure.from_object
            and b.to_object is structure.to_object
            and b.bond_category is structure.bond_category
            and b.bond_facet is structure.bond_facet
            for b in structure.string.bonds
        )
    if isinstance(structure, Group):
        return any(
            g is not structure
            and g.is_built
            and g.group_category is structure.group_category
            and g.direction is structure.direction
            and g.bond_facet is structure.bond_facet
            and [id(o) for o in g.objects] == [id(o) for o in structure.objects]
            for g in structure.string.groups
        )
    if isinstance(structure, Bridge):
        bridge_lists = {
            "top": ctx.workspace.top_bridges,
            "bottom": ctx.workspace.bottom_bridges,
            "vertical": ctx.workspace.vertical_bridges,
        }
        return any(
            b is not structure
            and b.is_built
            and b.object1 is structure.object1
            and b.object2 is structure.object2
            for b in bridge_lists.get(structure.bridge_type, [])
        )
    return False


def _get_incompatible_structures(
    ctx: EngineContext, structure: Any
) -> list[tuple[Any, float, float]]:
    """Find structures incompatible with the proposed one.

    Returns list of (opponent, proposer_weight, opponent_weight).
    """
    incompatibles: list[tuple[Any, float, float]] = []

    if isinstance(structure, Bond):
        # Incompatible bonds: same object pair, different category
        for bond in structure.string.bonds:
            if not bond.is_built:
                continue
            same_pair = (
                (bond.from_object is structure.from_object and bond.to_object is structure.to_object)
                or (bond.from_object is structure.to_object and bond.to_object is structure.from_object)
            )
            if same_pair and bond.bond_category is not structure.bond_category:
                incompatibles.append((bond, 1.0, 1.0))

        # Incompatible groups that use conflicting bonds
        for group in structure.string.groups:
            if not group.is_built:
                continue
            for gb in group.group_bonds:
                same_pair = (
                    (gb.from_object is structure.from_object and gb.to_object is structure.to_object)
                    or (gb.from_object is structure.to_object and gb.to_object is structure.from_object)
                )
                if same_pair and gb.bond_category is not structure.bond_category:
                    incompatibles.append((group, 1.0, float(group.span)))
                    break

    elif isinstance(structure, Group):
        # Incompatible groups: overlapping span
        for group in structure.string.groups:
            if not group.is_built or group is structure:
                continue
            # Overlap check
            if (structure.left_string_pos <= group.right_string_pos
                    and group.left_string_pos <= structure.right_string_pos):
                if group.group_category is structure.group_category and group.direction is structure.direction:
                    incompatibles.append((group, float(structure.span), float(group.span)))
                else:
                    incompatibles.append((group, 1.0, 1.0))

    elif isinstance(structure, Bridge):
        # Two bridges are incompatible if they share an object, carry
        # incompatible concept-mappings, or conflict at the group level
        # (bridges.ss:1551-1585).  Checking only for an identical object *pair*
        # let contradictory mappings coexist — "abc -> abcd" was ending up with
        # a-a, a-b and a-d bridges all built at once, from which no coherent
        # rule can be abstracted.
        for bridge in structure.get_incompatible_bridges(ctx.workspace):
            if not bridge.is_built or bridge is structure:
                continue
            incompatibles.append(
                (bridge, float(structure.object1.span), float(bridge.object1.span))
            )

    return incompatibles


def _wins_fight(
    ctx: EngineContext,
    proposer: Any,
    proposer_weight: float,
    opponent: Any,
    opponent_weight: float,
) -> bool:
    """Probabilistic fight between proposer and opponent.

    Scheme: workspace-structure-formulas.ss.
    """
    p_strength = max(1.0, proposer.strength * proposer_weight)
    o_strength = max(1.0, opponent.strength * opponent_weight)
    total = p_strength + o_strength
    win_prob = p_strength / total
    return ctx.rng.prob(win_prob)


def break_structure(ctx: EngineContext, structure: Any) -> None:
    """Remove a structure from the workspace.

    The structure also stops reporting itself as built — otherwise a broken
    structure still satisfies ``is_built`` and can be counted as support or as
    an existing duplicate long after it has left the Workspace.
    """
    structure.proposal_level = structure.PROPOSED
    # Breaking a structure is subcognitive: none of the seven Trace event types
    # of §4.4 covers it, and recording them drowned the Trace in noise.
    if isinstance(structure, Bond):
        structure.string.remove_bond(structure)
    elif isinstance(structure, Group):
        structure.string.remove_group(structure)
    elif isinstance(structure, Bridge):
        ctx.workspace.remove_bridge(structure)
    elif isinstance(structure, Rule):
        ctx.workspace.remove_rule(structure)


# ── Stochastic helpers ──

def prob(ctx: EngineContext, p: float) -> bool:
    """Return True with probability p."""
    return ctx.rng.prob(p)


def weighted_pick(ctx: EngineContext, items: list, weights: list[float]) -> Any:
    """Stochastic pick weighted by values."""
    return ctx.rng.weighted_pick(items, weights)


def _temp_adjusted_prob(ctx: EngineContext, p: float) -> float:
    """Adjust probability by temperature."""
    return temp_adjusted_probability(p, ctx.temperature.value, ctx.meta)


def _temp_adjusted_vals(ctx: EngineContext, values: list[float]) -> list[float]:
    """Adjust values by temperature."""
    return temp_adjusted_values(values, ctx.temperature.value, ctx.meta)


# ── Slipnet queries ──

def get_node(ctx: EngineContext, name: str) -> Any:
    """Get a slipnet node by name."""
    return ctx.slipnet.nodes.get(name)


def get_activation(ctx: EngineContext, name: str) -> float:
    """Get a slipnet node's activation."""
    node = ctx.slipnet.nodes.get(name)
    return node.activation if node else 0.0


def fully_active(ctx: EngineContext, name: str) -> bool:
    """Check if a slipnet node is fully active."""
    node = ctx.slipnet.nodes.get(name)
    if node is None:
        return False
    threshold = ctx.meta.get_param("full_activation_threshold", 50)
    return node.fully_active(threshold)


def get_bond_category(ctx: EngineContext, from_desc: Any, to_desc: Any) -> Any:
    """Determine bond category between two descriptors."""
    if from_desc is to_desc:
        return ctx.slipnet.nodes.get("plato-sameness")
    # Look for a labeled link between them
    for link in from_desc.outgoing_links:
        if link.to_node is to_desc and link.label_node is not None:
            return link.label_node
    return None


# ── Workspace queries ──

def object_has_description_type(
    ctx: EngineContext, obj: Any, description_type_name: str
) -> bool:
    """Does *obj* already carry a description along this dimension?"""
    return any(
        getattr(d.description_type, "name", "") == description_type_name
        for d in getattr(obj, "descriptions", [])
    )


def possible_descriptor(
    ctx: EngineContext, obj: Any, description_type_name: str
) -> Any:
    """A descriptor along *description_type_name* that genuinely applies to *obj*.

    Scheme: ``get-possible-descriptors`` (slipnet.ss).  Returns ``None`` when the
    dimension cannot describe the object at all — a letter has no length, a
    non-``a``/``z`` letter has no alphabetic position.  Picking stochastically
    among the applicable descriptors, weighted by activation.
    """
    node = ctx.slipnet.nodes.get(description_type_name)
    if node is None:
        return None
    candidates = node.get_possible_descriptors(obj)
    if not candidates:
        return None
    weights = [max(0.1, c.activation) for c in candidates]
    return ctx.rng.weighted_pick(candidates, weights)


def descriptor_support(ctx: EngineContext, string: Any, descriptor_name: str) -> float:
    """Fraction of the string's groups carrying *descriptor_name*, as 0-100.

    Scheme: ``descriptor-support`` (workspace-structure-formulas.ss:44-55).
    Used to pick which way a new singleton group should face.
    """
    groups = [g for g in getattr(string, "groups", []) if g.is_built]
    if not groups:
        return 0.0
    described = sum(
        1
        for g in groups
        if any(
            getattr(d.descriptor, "name", "") == descriptor_name
            for d in g.get_all_descriptions()
        )
    )
    return 100.0 * described / len(groups)


def single_letter_group_probability(ctx: EngineContext, group: Any) -> float:
    """How likely a lone letter is to be wrapped in a singleton group.

    Scheme: ``single-letter-group-probability``
    (workspace-structure-formulas.ss:32-41) — ``(local_support/100 *
    length_activation/100) ** exponent``, temperature-adjusted, where the
    exponent falls from 4 to 1 as more supporting groups appear.  So singleton
    groups only form once the string already looks group-structured and the
    concept of Length is active, which is exactly the situation in which seeing
    ``mrrjjj`` as 1-2-3 makes sense.
    """
    supporting = group.get_num_of_local_supporting_groups()
    exponent = {1: 4.0, 2: 2.0}.get(supporting, 1.0)
    if supporting == 0:
        exponent = ctx.meta.get_formula_coeff(
            "single_letter_group_exponent_1_supporting"
        )
    length_activation = ctx.slipnet.nodes["plato-length"].activation
    base = (group._local_support() / 100.0) * (length_activation / 100.0)
    return temp_adjusted_probability(
        base ** exponent, ctx.temperature.value, ctx.meta
    )


def get_objects(ctx: EngineContext) -> list:
    """Get all workspace objects."""
    return ctx.workspace.all_objects


def get_string_objects(ctx: EngineContext, string: Any) -> list:
    """Get objects from a specific string."""
    return string.objects


def get_built_bonds(ctx: EngineContext, string: Any) -> list:
    """Get built bonds from a string."""
    return [b for b in string.bonds if b.is_built]


def get_built_bridges(ctx: EngineContext, bridge_type: str = "top") -> list:
    """Get built bridges of a given type."""
    type_map = {
        "top": ctx.workspace.top_bridges,
        "bottom": ctx.workspace.bottom_bridges,
        "vertical": ctx.workspace.vertical_bridges,
    }
    bridges = type_map.get(bridge_type, [])
    return [b for b in bridges if b.is_built]


def mapping_strength(ctx: EngineContext, bridge_type: str) -> float:
    """Get mapping strength for a bridge type."""
    return ctx.workspace.get_mapping_strength(bridge_type)


def has_supported_rule(ctx: EngineContext, top: bool = True) -> bool:
    """Check if supported rules exist."""
    return len(ctx.workspace.get_supported_rules(top)) > 0


# ── Codelet posting ──

def post_codelet(
    ctx: EngineContext,
    codelet_type: str,
    urgency: int,
    **arguments: Any,
) -> None:
    """Post a new codelet to the coderack."""
    ctx.coderack.post(
        Codelet(codelet_type, urgency, arguments=arguments, time_stamp=ctx.codelet_count)
    )


# ── Trace ──

def record_event(
    ctx: EngineContext,
    event_type: str,
    structures: list | None = None,
    description: str = "",
) -> None:
    """Record an event to the temporal trace.

    Also emits commentary for snag and clamp events.
    """
    event = TraceEvent(
        event_type=event_type,
        codelet_count=ctx.codelet_count,
        temperature=ctx.temperature.value,
        structures=structures,
        description=description,
    )
    ctx.trace.record_event(event)

    # Emit commentary for snag events (Scheme: answers.ss:1164-1172)
    if event_type == SNAG:
        from server.engine.commentary import emit_snag
        snag_count = ctx.trace.snag_count
        explanation = description or "The rule could not be applied"
        emit_snag(ctx.commentary, explanation, snag_count, ctx.codelet_count)

    # Emit commentary for clamp events (Scheme: trace.ss:592-618)
    if event_type == CLAMP_START:
        from server.engine.commentary import emit_clamp_activate
        clamp_count = len(ctx.trace.get_events_by_type(CLAMP_START))
        clamp_type = description or "clamp"
        emit_clamp_activate(
            ctx.commentary, clamp_type, clamp_count, ctx.codelet_count,
        )

    if event_type == CLAMP_END:
        from server.engine.commentary import emit_clamp_expired
        clamp_type = description or "clamp"
        emit_clamp_expired(
            ctx.commentary, clamp_type, 0.0, ctx.codelet_count,
        )


def record_snag(ctx: EngineContext, top_rule: Any, translated_rule: Any) -> None:
    """Record a snag as a real ``SnagEvent`` and remember it.

    §4.4 lists snags among the seven Trace event types, and §4.7.2 says a snag
    description holds "the Workspace structures directly involved in the snag",
    a vertical theme-pattern, the top rule, and the translated rule that caused
    it.  A bare TraceEvent carries none of that, so the jootser's snag branch
    could never find two comparable snags and never fired.
    """
    from server.engine.memory import SnagDescription
    from server.engine.trace import SnagEvent

    workspace = ctx.workspace
    theme_pattern = ctx.themespace.get_dominant_theme_pattern("vertical")

    # The objects the translated rule was reaching for are the ones to blame.
    snag_objects = _snag_objects(ctx, translated_rule)

    event = SnagEvent(
        codelet_count=ctx.codelet_count,
        temperature=ctx.temperature.value,
        snag_objects=snag_objects,
        snag_theme_pattern=theme_pattern,
        snag_rule=top_rule,
        translated_rule=translated_rule,
    )
    ctx.trace.add_snag_event(event)

    # Metacat clamps the temperature while it deals with a snag.
    ctx.temperature.clamp(ctx.temperature.value)

    problem = (
        workspace.initial_string.text,
        workspace.modified_string.text,
        workspace.target_string.text,
    )
    if not any(
        s.problem == problem and s.description == top_rule.transcribe_to_english()
        for s in ctx.memory.snags
    ):
        ctx.memory.store_snag(
            SnagDescription(
                problem=problem,
                codelet_count=ctx.codelet_count,
                temperature=ctx.temperature.value,
                theme_pattern=_theme_pattern_dict(theme_pattern),
                description=top_rule.transcribe_to_english(),
            )
        )

    from server.engine.commentary import emit_snag

    emit_snag(
        ctx.commentary,
        f"the rule {top_rule.transcribe_to_english()!r} cannot be applied to "
        f"{workspace.target_string.text}",
        ctx.trace.snag_count,
        ctx.codelet_count,
    )


def _snag_objects(ctx: EngineContext, translated_rule: Any) -> list:
    """Target-string objects the translated rule was trying to change."""
    from server.engine.rules import _get_reference_objects_for_clause

    objects: list = []
    for clause in getattr(translated_rule, "clauses", []):
        try:
            objects.extend(
                _get_reference_objects_for_clause(
                    clause, ctx.workspace.target_string, ctx.slipnet
                )
            )
        except Exception:  # pragma: no cover - a malformed clause is not a crash
            continue
    return objects


def _theme_pattern_dict(pattern: Any) -> dict:
    """Turn a ``[theme_type, (dimension, relation), ...]`` list into a dict."""
    if not isinstance(pattern, list) or not pattern:
        return {}
    return {dim: rel for dim, rel in pattern[1:]}


def give_up(ctx: EngineContext) -> None:
    """Stop, gracefully, having recognised a loop it cannot break out of.

    §4.5.2: "Metacat simply 'gives up' in a graceful manner and stops."
    """
    ctx._gave_up = True  # type: ignore[attr-defined]


# ── Answer reporting ──

def report_answer(
    ctx: EngineContext,
    answer_string: str,
    quality: float,
    top_rule: Any = None,
    bottom_rule: Any = None,
    unjustified_slippages: Any = None,
) -> None:
    """Report a found answer — stores in episodic memory and signals runner.

    Creates the answer WorkspaceString on the workspace (so the UI can display
    it) and sets ctx._pending_answer so step_mcat can detect the answer.
    """
    from server.engine.answers import create_answer_description, get_quality_phrase
    from server.engine.commentary import (
        emit_answer_discovered,
        emit_answer_justified,
        emit_reminding,
    )
    from server.engine.memory import AnswerDescription
    from server.engine.workspace import WorkspaceString

    # Create the answer string on the workspace so it is visible to
    # serialization and the UI.
    if ctx.workspace.answer_string is None or not ctx.justify_mode:
        ctx.workspace.answer_string = WorkspaceString(
            answer_string, ctx.slipnet, string_type="answer"
        )
        ctx.workspace.answer_string.workspace = ctx.workspace

    # Store in episodic memory
    themes = ctx.themespace.get_current_pattern()
    answer_desc = create_answer_description(
        ctx.workspace,
        top_rule,
        bottom_rule,
        quality,
        ctx.temperature.value,
        themes,
        unjustified_slippages=list(unjustified_slippages or []),
        trace=ctx.trace,
        meta=ctx.meta,
    )
    ctx.memory.store(answer_desc)

    from server.engine.trace import AnswerEvent

    ctx.trace.add_answer_event(
        AnswerEvent(
            codelet_count=ctx.codelet_count,
            temperature=ctx.temperature.value,
            initial_string=ctx.workspace.initial_string,
            modified_string=ctx.workspace.modified_string,
            target_string=ctx.workspace.target_string,
            answer_string=answer_string,
            top_rule=top_rule,
            bottom_rule=bottom_rule,
            unjustified_slippages=list(unjustified_slippages or []),
            description=f"Answer '{answer_string}' found with quality {quality:.0f}",
        )
    )

    # Emit commentary (Scheme: answers.ss:36-75)
    quality_phrase = get_quality_phrase(quality, ctx.meta)
    templates = ctx.meta.commentary_templates

    prior_answers = len(ctx.trace.get_events_by_type(ANSWER_FOUND)) - 1
    if ctx.justify_mode:
        emit_answer_justified(
            ctx.commentary, quality, quality_phrase, ctx.codelet_count, templates,
        )
    else:
        emit_answer_discovered(
            ctx.commentary,
            answer_string,
            quality,
            quality_phrase,
            ctx.temperature.value,
            ctx.codelet_count,
            max(0, prior_answers),
            templates,
        )

    # Check for remindings (Scheme: memory.ss:214-229)
    remindings = ctx.memory.find_remindings(answer_desc)
    for past_answer in remindings:
        problem_text = (
            f"{past_answer.problem[0]} -> {past_answer.problem[1]}; "
            f"{past_answer.problem[2]} -> ?"
        )
        # Approximate reminding strength from theme distance
        dist = ctx.memory._theme_distance(answer_desc.themes, past_answer.themes)
        strength = max(0.0, 100.0 - dist * 20.0)
        emit_reminding(
            ctx.commentary,
            past_answer.problem[3],
            problem_text,
            strength,
            ctx.codelet_count,
        )

    # Signal to runner via a pending-answer attribute
    ctx._pending_answer = answer_string  # type: ignore[attr-defined]
    ctx._pending_answer_quality = quality  # type: ignore[attr-defined]


# ── Rule operations ──

def translate_rule(ctx: EngineContext, rule: Any) -> Any:
    """Translate a rule through the vertical mapping.

    Scheme: ``apply-slippages`` (slipnet.ss:257-277).  A slippage whose
    ``descriptor1`` *is* the concept being translated is applied
    unconditionally; the only probabilistic step is the **coattail** slippage,
    whose likelihood is the sliplink's degree of association (§3.4.1).  The
    nondeterminism §3.4 describes comes from which slippages the vertical mapping
    happens to contain at the moment of translation, and from those coattails —
    not from second-guessing the mapping's own slippages.

    This previously dropped each direct slippage with probability
    ``1 - slippability``, which meant deep slippages were discarded most often:
    the ``letter => group`` mapping that lets ``c`` stand for the ``jjj`` group
    survived only about 7% of the time, so ``mrrkkk`` — documented as "by far the
    most common" answer to ``abc => abd; mrrjjj => ?`` — never appeared at all.
    """
    slippages = []
    for bridge in ctx.workspace.vertical_bridges:
        if bridge.is_built:
            slippages.extend(bridge.concept_mappings)

    if not slippages:
        return None

    source_string = (
        ctx.workspace.initial_string
        if rule.is_top_rule
        else ctx.workspace.target_string
    )
    return rule.translate(
        slippages,
        rng=ctx.rng,
        source_string=source_string,
        slipnet=ctx.slipnet,
    )


def apply_rule(ctx: EngineContext, rule: Any, string: Any = None) -> str | None:
    """Apply a rule to *string* (the target string by default) and read off the result.

    Delegates to the image-based ``rules.apply_rule`` (rules.ss:1260-1318), which
    is what lets a rule express the changes the model actually has: length
    changes (``abc -> abcd``), direction reversal (``abc -> cba``), extrinsic
    position and attribute swaps, changes to *all components* of an object, and
    verbatim rules.  The previous letter-substitution implementation could
    express none of those.

    Returns the resulting string, or ``None`` if the rule cannot be applied —
    which is a snag.
    """
    from server.engine.rules import apply_rule as apply_rule_to_string
    from server.engine.rules import _generate_image_letters

    target = string if string is not None else ctx.workspace.target_string

    result = apply_rule_to_string(rule, target, ctx.slipnet)
    if result is None:
        return None

    letters = _generate_image_letters(target, ctx.slipnet)
    if not letters or any(l is None for l in letters):
        return None
    return "".join(getattr(l, "short_name", "?") for l in letters)
