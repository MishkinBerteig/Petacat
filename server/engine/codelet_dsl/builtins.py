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

from server.engine.access import AccessSet
from server.engine.bonds import Bond
from server.engine.bridges import Bridge
from server.engine.coderack import Codelet
from server.engine.concept_mappings import ConceptMapping
from server.engine.descriptions import Description
from server.engine.formulas import temp_adjusted_probability, temp_adjusted_values
from server.engine.groups import Group
from server.engine.rules import Rule
from server.engine.sink import STRUCTURE_BROKEN, STRUCTURE_BUILT
from server.engine.staleness import current_view
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
        "answer_present": answer_present,
        # Rule operations
        "translate_rule": translate_rule,
        "apply_rule": apply_rule,
    }


# ── Read/write-set tracking (WP4.2) ──
#
# Two one-line helpers rather than tracking calls scattered inline, because the sites
# are numerous and the guard has to be identical at every one of them.  Both are no-ops
# unless tracking is on, which is what keeps serial execution — the permanent reference
# mode — free of the cost.


class _committing:
    """Hold the commit lock, if there is one.

    A null context manager when serial, which is the common case and must stay free.
    Used by the builtins that mutate shared containers — building and breaking
    structures, recording trace events, storing to memory — because those are
    read-modify-write sequences over shared lists: running two concurrently corrupts the
    list rather than producing a conflict the model could interpret as a fizzle.
    """

    __slots__ = ("_lock",)

    def __init__(self, ctx: EngineContext) -> None:
        self._lock = getattr(ctx, "commit_lock", None)

    def __enter__(self):
        if self._lock is not None:
            self._lock.acquire()
        return self

    def __exit__(self, *exc) -> None:
        if self._lock is not None:
            self._lock.release()


def _read(ctx: EngineContext, *entities: Any) -> None:
    if ctx.track_access and ctx.access is not None:
        ctx.access.read(*entities)


def _wrote(ctx: EngineContext, *entities: Any) -> None:
    if ctx.track_access and ctx.access is not None:
        ctx.access.write(*entities)


def _wrote_component(ctx: EngineContext, name: str) -> None:
    if ctx.track_access and ctx.access is not None:
        ctx.access.write_component(name)


# ── Object selection ──

def choose_object(ctx: EngineContext, weight_key: str = "intra") -> Any:
    """Choose a workspace object weighted by salience/importance.

    Scheme: ``choose-object`` (``workspace.ss:499-502``) — a ``stochastic-pick``
    over ``temp-adjusted-values``, so the choice sharpens as temperature falls.
    """
    view = current_view(ctx)
    chosen = (
        _choose_from_view(ctx, view, view.all_objects, weight_key)
        if view is not None
        else ctx.workspace.choose_object(
            weight_key, ctx.rng, ctx.temperature.value, ctx.meta
        )
    )
    _read(ctx, chosen)
    return chosen


def choose_string_object(ctx: EngineContext, string: Any, weight_key: str = "intra") -> Any:
    """Choose an object from a specific string.

    Scheme: ``choose-object`` (``workspace-strings.ss:340-343``) — a
    ``stochastic-pick`` over ``temp-adjusted-values``.
    """
    view = current_view(ctx)
    chosen = (
        _choose_from_view(ctx, view, view.string_objects(string), weight_key)
        if view is not None
        else string.choose_object(weight_key, ctx.rng, ctx.temperature.value, ctx.meta)
    )
    _read(ctx, chosen)
    return chosen


def _choose_from_view(
    ctx: EngineContext, view: Any, objects: Any, weight_key: str
) -> Any:
    """Salience-weighted choice over a stale view (WP0.5).

    Deliberately one ``weighted_pick`` call over one weight list, matching the live
    path, so that switching staleness on shifts *which* object is chosen without
    changing how many random numbers the choice consumes.  The temperature
    adjustment is read live, not from the view: staleness is a model of reading
    the *Workspace* late, and temperature is not in the Workspace.
    """
    if not objects:
        return None
    weights = temp_adjusted_values(
        [view.object_weight(o, weight_key) for o in objects],
        ctx.temperature.value,
        ctx.meta,
    )
    return ctx.rng.weighted_pick(objects, weights)


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
    # Raw intra-string salience, *not* temperature-adjusted: ``choose-neighbor``
    # (``workspace-objects.ss:417-423``) is a bare ``stochastic-pick-by-method``,
    # unlike ``choose-object``.  And no floor — ``stochastic-pick``
    # (``utilities.ss:443-448``) gives a weight-0 neighbour probability 0.
    weights = [n.salience.get("intra", 1.0) for n in neighbors]
    chosen = ctx.rng.weighted_pick(neighbors, weights)
    # The object *and* the one it neighbours: a bond scout's decision depends on both,
    # so a change to either invalidates it. This is the locality the plan relies on to
    # bound the blast radius — two adjacent objects, not the string.
    _read(ctx, obj, chosen)
    return chosen


def choose_string(ctx: EngineContext, weight_fn: str = "unhappiness") -> Any:
    """Choose a workspace string weighted by unhappiness.

    A bare ``stochastic-pick`` in the Scheme (the top-down scouts'
    string choice, ``bonds.ss:221-239``): no temperature adjustment and no
    floor, so a perfectly happy string is not chosen at all
    (``utilities.ss:443-448``).
    """
    strings = ctx.workspace.all_strings
    weights = [s.get_average_intra_string_unhappiness() for s in strings]
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
    # The proposal rests on both objects; the bond itself is new and so cannot conflict.
    _read(ctx, from_obj, to_obj)
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
    _read(ctx, structure)
    if ctx.rng.prob(accept_prob):
        structure.proposal_level = structure.EVALUATED
        _wrote(ctx, structure)
        return True
    return False


def build_structure(ctx: EngineContext, structure: Any) -> bool:
    """Build an evaluated structure into the workspace.

    For bonds, groups, and bridges: first fight incompatible structures.
    If any fight is lost, the build fails (returns False).
    If all fights are won, break the losers and build.

    Scheme: bonds.ss:354-407, groups.ss:622-771, bridges.ss:1183-1298.
    """
    with _committing(ctx):
        return _build_structure_locked(ctx, structure)


def _premises_still_hold(ctx: EngineContext, structure: Any) -> bool:
    """Are the objects this structure relates still in the Workspace?

    Conflict -> fizzle, applied at the one place it has to be: a codelet decides outside
    the commit lock and commits inside it, so between the two another worker may have
    broken a group the decision rested on.  Committing anyway leaves a bond pointing at
    an object no string contains — observed under free-running as
    ``Bond(Group -> Group)`` where the second group had been removed.

    Checked here rather than relying on WP4.2's read-set validation because that
    validation runs *after* the codelet has finished and reports rather than prevents.
    This is the cheap, targeted version: re-read the premises while holding the lock that
    makes the answer stable, and decline if they have moved.  Returning ``False`` makes
    the builder fizzle, which is an outcome the architecture already has.

    Costs a handful of identity comparisons on the commit path and nothing at all when
    serial, where the answer is always yes.
    """
    for obj in _structure_objects(structure):
        if obj is None:
            continue
        # A bridge proposed against a reversed reading of a spanning group points
        # at a group that was never in the string — the premise is the *original*
        # it replaces (bridges.ss:1085-1105).
        obj = _flip_original(structure, obj) or obj
        string = getattr(obj, "string", None)
        if string is None:
            continue
        if obj not in string.objects:
            return False
    return True


def _flip_original(structure: Any, obj: Any) -> Any:
    """The group *obj* is a flipped reading of, if it is one.

    Scheme: ``get-original-group1`` / ``get-original-group2`` (bridges.ss:183-192).
    """
    if not isinstance(structure, Bridge):
        return None
    if obj is structure.object1:
        return structure.flipped_group1
    if obj is structure.object2:
        return structure.flipped_group2
    return None


def _build_structure_locked(ctx: EngineContext, structure: Any) -> bool:
    """The body of ``build_structure``, run with the commit lock held.

    Split out rather than indented in place so the lock's extent is unmistakable: it
    covers the duplicate check and the fights as well as the mutation, because those read
    the same lists the mutation writes.
    """
    if not _premises_still_hold(ctx, structure):
        return False
    # Descriptions and rules don't fight
    if isinstance(structure, Description):
        structure.proposal_level = structure.BUILT
        if structure not in structure.object.descriptions:
            structure.object.descriptions.append(structure)
        ctx.sink.on_structure_change(ctx, structure, STRUCTURE_BUILT)
        _wrote(ctx, structure, structure.object)
        return True
    elif isinstance(structure, Rule):
        structure.proposal_level = structure.BUILT
        ctx.workspace.add_rule(structure)
        _record_rule_event(ctx, structure)
        ctx.sink.on_structure_change(ctx, structure, STRUCTURE_BUILT)
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

    if isinstance(structure, Bridge):
        _apply_group_flips(ctx, structure)

    structure.proposal_level = structure.BUILT
    if isinstance(structure, Bond):
        structure.string.add_bond(structure)
    elif isinstance(structure, Group):
        structure.string.add_group(structure)
        # Scheme: ``build-group`` (groups.ss:929-930) jolts every description's
        # *descriptor* from the Workspace as the group goes in.  Without it the
        # concepts a group is made of never warm: ``plato-two`` and ``plato-three``
        # stay cold, so ``plato-length`` — which they are instances of — never rises,
        # and the length facet cannot compete with letter-category in
        # ``choose-bond-facet``.  That is the facet ``mrrjjj`` needs to be read as
        # one-two-three, so the reading was unreachable.
        for description in structure.descriptions:
            descriptor = getattr(description, "descriptor", None)
            if descriptor is not None and hasattr(descriptor, "activate_from_workspace"):
                descriptor.activate_from_workspace()
        _record_group_event(ctx, structure)
    elif isinstance(structure, Bridge):
        ctx.workspace.add_bridge(structure)
        _record_slippage_events(ctx, structure)
    else:
        return False
    # Emitted after the structure is in the Workspace, so a sink that reads the
    # context sees the state the change produced rather than the one before it.
    ctx.sink.on_structure_change(ctx, structure, STRUCTURE_BUILT)
    # The structure and every object it now relates: building a bond changes what its
    # two objects are, which is what another codelet reading them must notice.
    _wrote(ctx, structure, *_structure_objects(structure))
    return True


def _apply_group_flips(ctx: EngineContext, bridge: Bridge) -> None:
    """Put the reversed reading of a spanning group into the Workspace.

    Scheme: the two flip branches of ``build-bridge`` (bridges.ss:1322-1345).  The
    original group has already lost its fight and been broken along with the rest
    of the incompatibles; what is left is to break the bonds that held it together
    and build the reversed ones in their place, so that the Workspace holds the
    reading the bridge is about rather than the one it displaced.

    Reading ``>abc>`` as ``<cba<`` is not a different parse of the string — the
    same letters, the same span — so it is a *replacement*, not a competitor.
    """
    for new_group, original in (
        (bridge.object1, bridge.flipped_group1),
        (bridge.object2, bridge.flipped_group2),
    ):
        if original is None:
            continue
        for bond in list(getattr(original, "group_bonds", ())):
            break_structure(ctx, bond)
        for bond in getattr(new_group, "group_bonds", ()):
            bond.proposal_level = bond.BUILT
            new_group.string.add_bond(bond)
            ctx.sink.on_structure_change(ctx, bond, STRUCTURE_BUILT)
        new_group.proposal_level = new_group.BUILT
        new_group.string.add_group(new_group)
        _record_group_event(ctx, new_group, flipped=True)
        ctx.sink.on_structure_change(ctx, new_group, STRUCTURE_BUILT)
        _wrote(ctx, new_group, *getattr(new_group, "objects", ()))


# ── Trace: which events are important enough to record ──
#
# §4.4: "each event ... has an importance value associated with it, and only
# those events with an importance value above some threshold get explicitly
# represented in the Trace, allowing Metacat to effectively filter out the
# 'background noise' of a run."  The Trace is the cognitive level — a run is a
# few dozen events, not the hundreds of micro-events the Workspace generates.
# Bonds and descriptions never reach it at all; groups, slippages and rules do,
# but only when they clear their threshold.


def _has_length_description(ctx: EngineContext, group: Group) -> bool:
    """Does this group carry a Length description?

    ``trace.ss:1355`` — a *singleton* group only counts as important when it has been
    described by its length, because that is what makes "a group of one" an idea rather
    than a bare letter.
    """
    node = ctx.slipnet.get_node("plato-length")
    present = getattr(group, "description_type_present", None)
    return bool(present(node)) if present is not None else False


def _record_group_event(
    ctx: EngineContext, group: Group, flipped: bool = False
) -> None:
    """Record an important group.

    Scheme: ``group-importance`` (``trace.ss:1350-1357``)::

        (if (or flipped?
                (tell group 'spans-whole-string?)
                (and (tell group 'singleton-group?)
                     (tell group 'description-type-present? plato-length)))
          100
          (tell group 'get-strength))

    §4.4: importance is a function of a group's strength and size, "with single-letter
    groups and whole-string groups being particularly important" — and a **flip** is
    maximally important whatever its strength, because re-perceiving a string in the
    opposite direction is one of the twelve milestones Figure 4.12 records.
    """
    threshold = ctx.meta.get_param("group_importance_threshold", 100)
    singleton_with_length = group.length == 1 and _has_length_description(ctx, group)
    if flipped or group.spans_whole_string() or singleton_with_length:
        importance = 100.0
    else:
        importance = float(group.strength)
    if importance >= threshold:
        record_event(
            ctx,
            GROUP_BUILT,
            structures=[group],
            description=(
                # ``trace.ss:904-907`` titles a flipped group event differently: the
                # event records a *re-perception*, not a first perception.
                f"flipped {group.string.text} group"
                if flipped
                else f"perceived {group.string.text} group"
            ),
            # ``trace.ss:880`` — a group event's strength is the group's own.
            strength=float(group.strength),
        )


def _slippage_importance(ctx: EngineContext, bridge: Bridge, cm: Any) -> float:
    """Scheme: ``concept-mapping-importance`` (``trace.ss:1365-1385``).

    A weighted average over four terms — the mapping's own dimension, whether the
    bridge spans a whole string, the depth of the two descriptors, and the depth of
    the label (50 when unlabelled) — at weights 4, 2, 2, 3.

    Bond-category slippages score **0** outright: they say something about how two
    strings are bonded, not about how their objects correspond, and §4.4 is about the
    latter.  The previous form (depth + 10x span) had no spanning term, no label term,
    no bond-category exclusion, and was unbounded above 100.
    """
    cm_type = getattr(cm, "description_type1", None)
    cm_type_name = getattr(cm_type, "name", "")
    if cm_type_name == "plato-bond-category":
        return 0.0

    def depth(node: Any) -> float:
        return float(getattr(node, "conceptual_depth", 0) or 0)

    label = getattr(cm, "label", None)
    spanning = 100.0 if _bridge_is_spanning(bridge) else 0.0
    values = [
        depth(cm_type),
        spanning,
        (depth(getattr(cm, "descriptor1", None)) + depth(getattr(cm, "descriptor2", None))) / 2.0,
        depth(label) if label is not None else 50.0,
    ]
    weights = [4.0, 2.0, 2.0, 3.0]
    return round(sum(v * w for v, w in zip(values, weights)) / sum(weights))


def _bridge_is_spanning(bridge: Bridge) -> bool:
    """Does this bridge join two objects that each span their whole string?"""
    for obj in (bridge.object1, bridge.object2):
        spans = getattr(obj, "spans_whole_string", None)
        if spans is None or not spans():
            return False
    return True


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
        importance = _slippage_importance(ctx, bridge, cm)
        if under_pressure and _slippage_matches_active_theme(ctx, bridge, cm):
            importance = 100.0
        if importance >= threshold:
            record_event(
                ctx,
                CONCEPT_MAPPING_BUILT,
                structures=[bridge],
                description=f"slippage {cm}",
                # ``trace.ss:796`` — a concept-mapping event's strength is the
                # concept-mapping's own.  ``strength`` is a method here, not a property.
                strength=float(cm.strength()),
            )


def _slippage_matches_active_theme(
    ctx: EngineContext, bridge: Bridge, cm: ConceptMapping
) -> bool:
    """Whether a slippage is supported by an active theme.

    Scheme: ``supported-by-active-theme?`` (``themes.ss:166-173``).  Three conjuncts:
    the theme exists, its type is under thematic pressure, and the theme is *dominant*
    in its cluster.  Dominance is the operative one — a theme carrying some activation
    confers no support; only the theme its cluster has settled on does.
    """
    from server.engine.themes import relation_name_for_label

    dimension = getattr(cm.description_type1, "name", "")
    relation = relation_name_for_label(cm.label)
    themespace = ctx.themespace
    if bridge.theme_type not in themespace.active_theme_types:
        return False
    margin = themespace.meta.get_param("dominant_theme_margin", 90)
    for cluster in themespace.clusters:
        if cluster.theme_type != bridge.theme_type or cluster.dimension != dimension:
            continue
        dominant = cluster.get_dominant_theme(margin)
        return dominant is not None and dominant.relation == relation
    return False


def _record_rule_event(ctx: EngineContext, rule: Rule) -> None:
    """Record an important rule.  §4.4: importance is "a function of the relative
    quality of a rule with respect to all other rules that already exist"."""
    threshold = ctx.meta.get_param("rule_importance_threshold", 67)
    relative_quality = rule.get_relative_quality(ctx.workspace)
    # ``trace.ss:1359-1363``: a perfectly uniform rule is maximally important whatever
    # its relative quality — uniformity is what makes a rule say one thing about the
    # whole string rather than several things about its parts.
    importance = 100.0 if rule.uniformity == 100 else float(relative_quality)
    if importance >= threshold:
        record_event(
            ctx,
            RULE_BUILT,
            structures=[rule],
            description=rule.transcribe_to_english(),
            # ``trace.ss:965`` — a rule event's strength is its relative quality.
            strength=float(relative_quality),
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

    The weights are the Scheme builders' own, and they are not all 1-vs-1; each
    one is cited at its site below.  A weight multiplies a party's *strength*
    inside ``wins-fight?`` (``workspace-structures.ss:70-78``), so it says how
    much a structure of that kind is worth relative to its opponent regardless
    of how strong either happens to be.

    Three fights the Scheme has are still missing here — bond vs incompatible
    bridge (``bonds.ss:385-398``, 2 vs 3), group vs bonds-to-be-flipped
    (``groups.ss:652-664``, letter-span vs 1) and bridge vs incompatible bond
    (``bridges.ss:1259-1276``, 3 vs 2) with its enclosing group
    (``bridges.ss:1277-1292``, 1 vs 1).  They are tracked separately as BD-3,
    GR-7 and BR-6.
    """
    incompatibles: list[tuple[Any, float, float]] = []

    if isinstance(structure, Bond):
        # bonds.ss:370-376 — 1 vs 1 against each incompatible bond.
        for bond in structure.string.bonds:
            if not bond.is_built:
                continue
            same_pair = (
                (bond.from_object is structure.from_object and bond.to_object is structure.to_object)
                or (bond.from_object is structure.to_object and bond.to_object is structure.from_object)
            )
            if same_pair and bond.bond_category is not structure.bond_category:
                incompatibles.append((bond, 1.0, 1.0))

        # bonds.ss:377-384 — 1 vs ``(maximum (tell-all incompatible-groups
        # 'get-letter-span))``.  One *shared* defender weight, the widest group's
        # letter span, applied to every group in the set: a bond that would break
        # into a wide group is fought off as hard by the narrow groups beside it.
        conflicting_groups: list[Any] = []
        for group in structure.string.groups:
            if not group.is_built:
                continue
            for gb in group.group_bonds:
                same_pair = (
                    (gb.from_object is structure.from_object and gb.to_object is structure.to_object)
                    or (gb.from_object is structure.to_object and gb.to_object is structure.from_object)
                )
                if same_pair and gb.bond_category is not structure.bond_category:
                    conflicting_groups.append(group)
                    break
        if conflicting_groups:
            shared_weight = float(max(g.span for g in conflicting_groups))
            incompatibles.extend(
                (group, 1.0, shared_weight) for group in conflicting_groups
            )

    elif isinstance(structure, Group):
        # groups.ss:665-682 — a group of the same category *and* direction is a
        # rival reading of the same material, so the two are weighted by **group
        # length** (constituent count, ``get-group-length``, groups.ss:80,242),
        # not letter span: a group of three subgroups outweighs a group of two
        # however many letters each covers.  Any other incompatible group is 1-1.
        for group in structure.string.groups:
            if not group.is_built or group is structure:
                continue
            # Overlap check
            if (structure.left_string_pos <= group.right_string_pos
                    and group.left_string_pos <= structure.right_string_pos):
                if group.group_category is structure.group_category and group.direction is structure.direction:
                    incompatibles.append(
                        (group, float(structure.length), float(group.length))
                    )
                else:
                    incompatibles.append((group, 1.0, 1.0))

    elif isinstance(structure, Bridge):
        # Two bridges are incompatible if they share an object, carry
        # incompatible concept-mappings, or conflict at the group level
        # (bridges.ss:1551-1585).  Checking only for an identical object *pair*
        # let contradictory mappings coexist — "abc -> abcd" was ending up with
        # a-a, a-b and a-d bridges all built at once, from which no coherent
        # rule can be abstracted.
        #
        # bridges.ss:1249-1254 weights both sides by the *bridge's* letter span,
        # which is ``object1 span + object2 span`` (bridges.ss:178-180, 572-574).
        # Weighting by object1 alone made the far side of the mapping count for
        # nothing, so a letter-to-group bridge was fought as if it were
        # letter-to-letter.
        proposer_span = float(structure.object1.span + structure.object2.span)
        for bridge in structure.get_incompatible_bridges(ctx.workspace):
            if not bridge.is_built or bridge is structure:
                continue
            incompatibles.append(
                (
                    bridge,
                    proposer_span,
                    float(bridge.object1.span + bridge.object2.span),
                )
            )

        # A bridge proposed against a reversed reading of a spanning group has to
        # beat the group it would replace, at even odds (bridges.ss:1292-1312).
        # The group is doing no wrong: the bridge is asking to reinterpret it.
        for original in (structure.flipped_group1, structure.flipped_group2):
            if original is not None and original.is_built:
                incompatibles.append((original, 1.0, 1.0))

    return incompatibles


def _wins_fight(
    ctx: EngineContext,
    proposer: Any,
    proposer_weight: float,
    opponent: Any,
    opponent_weight: float,
) -> bool:
    """Probabilistic fight between proposer and opponent.

    Scheme: ``wins-fight?`` (``workspace-structures.ss:70-78``)::

        (tell challenger 'update-strength)
        (tell defender 'update-strength)
        (stochastic-pick '(#t #f)
          (temp-adjusted-values
            (list (* challenger-weight (tell challenger 'get-strength))
                  (* defender-weight (tell defender 'get-strength)))))

    Three things the linear form got wrong.  Both parties' strengths are
    **recomputed at fight time** — a structure's strength moves with the themes
    and with everything built since it was evaluated, and a fight is decided on
    what the two are worth *now*.  The contest is then **temperature-adjusted**
    (``formulas.ss:32-35``), so 60-vs-40 is 8/14 = 0.571 for the stronger side at
    T=100 (each adjusted value is *rounded*, as in the Scheme) and 0.826 at T=0:
    at low temperature MetaCat locks in a strong interpretation
    rather than overturning it at the linear rate.  And there is **no floor** —
    ``stochastic-pick`` (``utilities.ss:443-448``) gives a strength-0 challenger
    probability exactly 0, falling back to a coin flip only when *both* sides
    weigh 0.
    """
    proposer.update_strength()
    opponent.update_strength()
    weights = temp_adjusted_values(
        [
            proposer_weight * proposer.strength,
            opponent_weight * opponent.strength,
        ],
        ctx.temperature.value,
        ctx.meta,
    )
    return bool(ctx.rng.weighted_pick([True, False], weights))


def break_structure(ctx: EngineContext, structure: Any) -> None:
    """Remove a structure from the workspace.

    The structure also stops reporting itself as built — otherwise a broken
    structure still satisfies ``is_built`` and can be counted as support or as
    an existing duplicate long after it has left the Workspace.
    """
    with _committing(ctx):
        return _break_structure_locked(ctx, structure)


def _break_structure_locked(ctx: EngineContext, structure: Any) -> None:
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
    _wrote(ctx, structure, *_structure_objects(structure))
    # Subcognitive for the Trace, but not for Audit: reconstructing an intermediate
    # Workspace in forward order needs removals as much as additions.
    ctx.sink.on_structure_change(ctx, structure, STRUCTURE_BROKEN)


# ── Stochastic helpers ──

def _structure_objects(structure: Any) -> tuple:
    """The workspace objects a structure relates, for write-set purposes.

    Building or breaking a structure changes the objects at both ends as much as the
    structure itself — a letter that has just acquired a bond is not the letter a
    concurrent scout read a moment ago.
    """
    for names in (("from_object", "to_object"), ("object1", "object2"), ("object",)):
        values = tuple(getattr(structure, n) for n in names if hasattr(structure, n))
        if values:
            return values
    return tuple(getattr(structure, "objects", ()) or ())


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
    """Whether a slipnet node is at maximum activation.

    ``fully-active?`` (``slipnet.ss:392-394``) is ``(= activation
    %max-activation%)`` — exactly 100, not the 50 of
    ``%full-activation-threshold%``.  That threshold belongs to
    ``above-threshold?`` (``slipnet.ss:397-399``), whose single Scheme call site
    is top-down codelet posting; a codelet asking whether a concept is *fully*
    active is asking the stricter question.
    """
    node = ctx.slipnet.nodes.get(name)
    if node is None:
        return False
    return node.fully_active()


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
    # No floor: ``stochastic-pick-by-method ... 'get-activation``
    # (``descriptions.ss:138``, ``themes.ss:962``) leaves a dormant descriptor
    # unreachable (``utilities.ss:443-448``).
    weights = [c.activation for c in candidates]
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
    view = current_view(ctx)
    if view is not None:
        return list(view.all_objects)
    return ctx.workspace.all_objects


def get_string_objects(ctx: EngineContext, string: Any) -> list:
    """Get objects from a specific string."""
    view = current_view(ctx)
    if view is not None:
        return list(view.string_objects(string))
    return string.objects


def get_built_bonds(ctx: EngineContext, string: Any) -> list:
    """Get built bonds from a string."""
    view = current_view(ctx)
    if view is not None:
        return list(view.string_bonds(string))
    return [b for b in string.bonds if b.is_built]


def get_built_bridges(ctx: EngineContext, bridge_type: str = "top") -> list:
    """Get built bridges of a given type."""
    view = current_view(ctx)
    if view is not None:
        return list(view.bridges(bridge_type))
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
    # The coderack has no useful sub-identity and is contended by every post and every
    # selection, which is why WP4.3 shards it rather than versioning it finely.
    _wrote_component(ctx, "coderack")


# ── Trace ──

def record_event(
    ctx: EngineContext,
    event_type: str,
    structures: list | None = None,
    description: str = "",
    strength: float = 0.0,
) -> None:
    """Record an event to the temporal trace.

    ``strength`` is what a clamp's progress-evaluator reads (§4.5.1); group, rule and
    slippage events supply it.  Also emits commentary for snag and clamp events.
    """
    event = TraceEvent(
        event_type=event_type,
        codelet_count=ctx.codelet_count,
        temperature=ctx.temperature.value,
        structures=structures,
        description=description,
        strength=strength,
    )
    with _committing(ctx):
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

    # The objects the rule application actually failed on are the ones to blame
    # (Scheme: ``make-snag-event``, ``trace.ss:1055-1059``, reads them off the
    # failure-result).  Only when the failure reported none — a rule that could not
    # be turned into transforms at all — fall back to everything it mentioned.
    snag_objects = list(getattr(ctx, "last_failure_objects", []) or [])
    if not snag_objects:
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

def answer_present(
    ctx: EngineContext,
    answer_string: str,
    top_rule: Any = None,
    bottom_rule: Any = None,
) -> bool:
    """Is this answer, reached by these rules, already in Episodic Memory?

    Scheme: ``answers.ss:982`` consults ``memory.ss:90`` *before* reporting and fizzles
    on a hit — "Already found this answer" — so the search carries on toward a different
    answer instead of rediscovering one already stored.

    This is the single point at which Episodic Memory influences cognition rather than
    merely recording it: every other memory read (reminding, snag comparison) only
    produces commentary.  The author documents the observable consequence in
    ``Metacat/help.txt:29`` — rerunning with the same seed after an answer will not
    produce that answer again, because it already exists in memory.
    """
    ws = ctx.workspace
    problem = (
        ws.initial_string.text,
        ws.modified_string.text,
        ws.target_string.text,
        answer_string,
    )
    return ctx.memory.answer_present(problem, top_rule, bottom_rule)


def report_answer(
    ctx: EngineContext,
    answer_string: str,
    quality: float,
    top_rule: Any = None,
    bottom_rule: Any = None,
    unjustified_slippages: Any = None,
) -> None:
    with _committing(ctx):
        return _report_answer_locked(ctx, answer_string, quality, top_rule, bottom_rule, unjustified_slippages)


def _report_answer_locked(
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

    # Free-running lets two workers reach ``report_answer`` before either result has
    # been collected (WP4.4).  ``FreeRunningEngine._collect_outcome`` de-duplicates the
    # run's *status*, but by then each worker has already written its own
    # ``AnswerDescription`` — and under a Training Session that memory is shared with
    # every later Run, so the pollution outlives the run that caused it.  Measured at 8
    # workers before this guard: 22 of 40 runs stored 2–5 answers where the serial loop
    # stores exactly 1.
    #
    # A queued-but-uncollected answer, or an ending already claimed, means the run is
    # over and this result is an artefact of parallelism rather than a second cognitive
    # result.  Both checks are needed: two workers can report before either is collected
    # (``_pending_answer`` still set), and a worker can report after the ending has been
    # collected and the queue cleared (``run_ended``).  Serially ``_pending_answer`` is
    # always collected before the next codelet runs and ``run_ended`` is cleared at every
    # start and resume, so neither fires and the reference mode is unchanged.
    if getattr(ctx, "_pending_answer", None) is not None or ctx.run_ended:
        return

    # Create the answer string on the workspace so it is visible to
    # serialization and the UI.
    if ctx.workspace.answer_string is None or not ctx.justify_mode:
        # Built with the structure the translated rule implies, not as bare letters:
        # ``make-translated-string`` (``answers.ss:991``) carries the target's
        # perceptual reading across to the answer, so ``mrrjjj`` seen as three sameness
        # groups yields ``mrrkkk`` seen as three sameness groups.  A row of unconnected
        # letters would say the program had no reading of its own answer.
        translated_string = None
        if bottom_rule is not None:
            from server.engine.answers import make_translated_string

            translated_string = make_translated_string(
                bottom_rule, ctx.workspace.target_string, ctx.slipnet, ctx.workspace
            )
        if translated_string is None:
            translated_string = WorkspaceString(
                answer_string, ctx.slipnet, string_type="answer"
            )
        ctx.workspace.answer_string = translated_string
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
        # The reminding strength *is* the activation ``find_remindings`` just stored
        # (``memory.ss:210-217`` computes one number and reports that same number).
        # Recomputing a second figure from a different distance made the Memory panel,
        # which renders activation, disagree with the commentary, which quoted this.
        strength = past_answer.activation
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
    with _committing(ctx):
        return _translate_rule_locked(ctx, rule)


def _translate_rule_locked(ctx: EngineContext, rule: Any) -> Any:
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
    with _committing(ctx):
        return _apply_rule_locked(ctx, rule, string)


def _apply_rule_locked(ctx: EngineContext, rule: Any, string: Any = None) -> str | None:
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

    # Scheme: ``apply-rule`` is handed a snag-action (``answers.ss``), and
    # ``make-snag-event`` (``trace.ss:1055-1059``) takes the snag objects from the
    # failure-result it carries.  Stash them so the ``record_snag`` that follows
    # names what actually failed rather than re-resolving every clause.
    ctx.last_failure_objects = []

    def _remember(failure: Any) -> None:
        ctx.last_failure_objects = list(getattr(failure, "objects", []) or [])

    result = apply_rule_to_string(rule, target, ctx.slipnet, failure_action=_remember)
    if result is None:
        return None

    letters = _generate_image_letters(target, ctx.slipnet)
    if not letters or any(l is None for l in letters):
        return None
    return "".join(getattr(l, "short_name", "?") for l in letters)
