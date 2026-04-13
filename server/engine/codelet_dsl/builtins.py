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
    """Choose a neighbor of the given object."""
    neighbors = []
    if obj.left_string_pos > 0:
        left = obj.string.get_object_at(obj.left_string_pos - 1)
        if left:
            neighbors.append(left)
    right_pos = obj.right_string_pos + 1
    if right_pos < obj.string.length:
        right = obj.string.get_object_at(right_pos)
        if right:
            neighbors.append(right)
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
    """Create a proposed bond and post an evaluator."""
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
    """Create a proposed description and post an evaluator."""
    desc = Description(obj, description_type, descriptor)
    desc.time_stamp = ctx.codelet_count
    urgency = round(description_type.activation) if hasattr(description_type, 'activation') else 35
    post_codelet(ctx, "description-evaluator", urgency, structure=desc)
    return desc


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
            record_event(ctx, DESCRIPTION_BUILT, structures=[structure])
        return True
    elif isinstance(structure, Rule):
        structure.proposal_level = structure.BUILT
        ctx.workspace.add_rule(structure)
        record_event(ctx, RULE_BUILT, structures=[structure])
        return True

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
        record_event(ctx, BOND_BUILT, structures=[structure])
        return True
    elif isinstance(structure, Group):
        structure.string.add_group(structure)
        record_event(ctx, GROUP_BUILT, structures=[structure])
        return True
    elif isinstance(structure, Bridge):
        ctx.workspace.add_bridge(structure)
        record_event(ctx, BRIDGE_BUILT, structures=[structure])
        return True
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
        # Incompatible bridges: same object pair, different mappings
        bridge_lists = {
            "top": ctx.workspace.top_bridges,
            "bottom": ctx.workspace.bottom_bridges,
            "vertical": ctx.workspace.vertical_bridges,
        }
        bridges = bridge_lists.get(structure.bridge_type, [])
        for bridge in bridges:
            if not bridge.is_built or bridge is structure:
                continue
            if bridge.object1 is structure.object1 and bridge.object2 is structure.object2:
                incompatibles.append((bridge, float(structure.object1.span), float(bridge.object1.span)))

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
    """Remove a structure from the workspace."""
    if isinstance(structure, Bond):
        structure.string.remove_bond(structure)
        record_event(ctx, BOND_BROKEN, structures=[structure])
    elif isinstance(structure, Group):
        structure.string.remove_group(structure)
        record_event(ctx, GROUP_BROKEN, structures=[structure])
    elif isinstance(structure, Bridge):
        ctx.workspace.remove_bridge(structure)
        record_event(ctx, BRIDGE_BROKEN, structures=[structure])
    elif isinstance(structure, Rule):
        ctx.workspace.remove_rule(structure)
        record_event(ctx, RULE_BROKEN, structures=[structure])


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


# ── Answer reporting ──

def report_answer(
    ctx: EngineContext,
    answer_string: str,
    quality: float,
    top_rule: Any = None,
    bottom_rule: Any = None,
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
    ctx.workspace.answer_string = WorkspaceString(answer_string, ctx.slipnet)

    # Store in episodic memory
    themes = ctx.themespace.get_current_pattern()
    answer_desc = create_answer_description(
        ctx.workspace,
        top_rule,
        bottom_rule,
        quality,
        ctx.temperature.value,
        themes,
    )
    ctx.memory.store(answer_desc)

    record_event(
        ctx,
        ANSWER_FOUND,
        description=f"Answer '{answer_string}' found with quality {quality:.0f}",
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
    """Translate a top rule via vertical bridge concept-mappings.

    Gathers all concept-mappings from vertical bridges and uses them
    as slippages to translate rule clause descriptors.
    Returns (translated_rule, unjustified_slippages) or None on snag.
    """
    slippages = []
    for bridge in ctx.workspace.vertical_bridges:
        if bridge.is_built:
            slippages.extend(bridge.concept_mappings)

    if not slippages:
        return None

    translated = rule.translate(slippages)
    return translated


def apply_rule(ctx: EngineContext, rule: Any) -> str | None:
    """Apply a translated rule to the target string to produce answer letters.

    Scheme: answers.ss — apply rule changes to the target string.
    Returns the answer string, or None if application fails (snag).
    """
    target = ctx.workspace.target_string
    target_letters = list(target.text)

    for clause in rule.clauses:
        if clause.is_verbatim:
            continue

        for change in clause.changes:
            # Find target object matching the object description
            target_pos = _find_target_position(clause, target, ctx)
            if target_pos is None:
                return None  # Snag: no matching object

            if change.relation is not None:
                # Relational change: apply successor/predecessor
                current_letter = target_letters[target_pos]
                new_letter = _apply_relational_change(
                    current_letter, change.relation, ctx
                )
                if new_letter is None:
                    return None  # Snag: e.g., successor of 'z'
                target_letters[target_pos] = new_letter
            elif change.to_descriptor is not None:
                # Literal change
                new_letter = getattr(change.to_descriptor, "short_name", None)
                if new_letter and len(new_letter) == 1:
                    target_letters[target_pos] = new_letter

    return "".join(target_letters)


def _find_target_position(clause: Any, target: Any, ctx: EngineContext) -> int | None:
    """Find which position in the target string a clause applies to."""
    if clause.object_description is None:
        return None

    # Object description is (description_type, descriptor) or similar
    for obj in target.objects:
        if not isinstance(obj, Letter):
            continue
        for desc in obj.descriptions:
            obj_desc = clause.object_description
            if len(obj_desc) >= 2:
                if desc.description_type is obj_desc[0] and desc.descriptor is obj_desc[1]:
                    return obj.left_string_pos

    # Fallback: if the object description mentions rightmost, find it
    for obj in target.objects:
        if not isinstance(obj, Letter):
            continue
        for desc in obj.descriptions:
            for od in (clause.object_description or []):
                if hasattr(od, "name") and od.name == "plato-rightmost":
                    # Find the rightmost letter
                    rightmost_pos = max(
                        o.left_string_pos
                        for o in target.objects
                        if isinstance(o, Letter)
                    )
                    return rightmost_pos
    return None


def _apply_relational_change(
    letter: str, relation: Any, ctx: EngineContext
) -> str | None:
    """Apply a relational change (successor/predecessor) to a letter."""
    rel_name = getattr(relation, "name", "")
    node_name = f"plato-{letter}"
    node = ctx.slipnet.nodes.get(node_name)
    if node is None:
        return None

    if rel_name == "plato-successor":
        # Find successor link
        for link in node.lateral_links:
            if link.label_node and link.label_node.name == "plato-successor":
                return link.to_node.short_name
        return None  # Snag: no successor (e.g., 'z')

    if rel_name == "plato-predecessor":
        for link in node.lateral_links:
            if link.label_node and link.label_node.name == "plato-predecessor":
                return link.to_node.short_name
        return None  # Snag: no predecessor (e.g., 'a')

    return None
