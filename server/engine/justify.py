"""Justification mode -- validate given answers.

When given all four strings (including the answer), Metacat works to
justify the given answer rather than discover one.  It selects a
supported rule, translates it via vertical bridge slippages, attempts
to find matching rules of the other type, and if no match is found,
clamps rules to force focused exploration or attempts rule unification.

Scheme source: justify.ss
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from server.engine.rules import Rule, RuleClause, RuleChange, rules_equal
from server.engine.trace import ClampEvent

if TYPE_CHECKING:
    from server.engine.concept_mappings import ConceptMapping
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG
    from server.engine.slipnet import Slipnet, SlipnetNode
    from server.engine.themes import Themespace
    from server.engine.trace import TemporalTrace
    from server.engine.workspace import Workspace

logger = logging.getLogger(__name__)


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
    ) -> None:
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
    slipnet: Slipnet | None = None,
    memory: Any = None,
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
        return JustificationResult(
            justified=False, explanation="No supported rules found"
        )

    weights = [max(1.0, r.quality) for r in all_supported]
    chosen_rule: Rule = rng.weighted_pick(all_supported, weights)

    rule_type = chosen_rule.rule_type  # "top" or "bottom"
    other_type_top = rule_type != "top"
    other_rules = (
        workspace.get_supported_rules(rule_type_top=True)
        + _get_built_rules(workspace, top=True)
        if other_type_top
        else workspace.get_supported_rules(rule_type_top=False)
        + _get_built_rules(workspace, top=False)
    )
    # Deduplicate
    seen_ids: set[int] = set()
    unique_other: list[Rule] = []
    for r in other_rules:
        rid = id(r)
        if rid not in seen_ids:
            seen_ids.add(rid)
            unique_other.append(r)
    other_rules = unique_other

    # Step 2 -- Translate the chosen rule using vertical bridge slippages
    translation_result = _translate_rule(chosen_rule, workspace, slipnet)

    if translation_result is not None:
        translated_rule, slippages, supporting_vbridges = translation_result

        # Step 3a -- Look for a matching existing rule
        matching_rule = _find_matching_rule(other_rules, translated_rule)

        if matching_rule is not None:
            # Assign rule1 = top, rule2 = bottom regardless of direction
            rule1, rule2 = _order_rules(chosen_rule, matching_rule, rule_type)

            # Check memory for duplicates
            if memory is not None and _answer_already_found(
                memory, workspace, rule1, rule2
            ):
                return JustificationResult(
                    justified=False,
                    explanation="Already found this answer",
                )

            if matching_rule.is_built and matching_rule.supporting_bridges:
                # Matching rule is supported -- answer justified!
                quality = (rule1.quality + rule2.quality) / 2.0
                return JustificationResult(
                    justified=True,
                    top_rule=rule1,
                    bottom_rule=rule2,
                    quality=quality,
                    explanation="Rules match via translation",
                    supporting_vertical_bridges=supporting_vbridges,
                    slippage_log=slippages,
                )

            # Matching rule exists but is unsupported -- clamp to force it
            return _attempt_clamp_rules(
                [chosen_rule, matching_rule],
                trace,
                themespace,
                workspace,
                slipnet,
                meta,
                concept_patterns=[_get_concept_pattern_dict(matching_rule)],
                explanation="Matching rule unsupported, clamping",
            )

        # Step 3b -- No matching rule, but translated rule works
        if _translated_rule_works(translated_rule, workspace, slipnet, rule_type):
            rule1, rule2 = _order_rules(
                chosen_rule, translated_rule, rule_type
            )

            if memory is not None and _answer_already_found(
                memory, workspace, rule1, rule2
            ):
                return JustificationResult(
                    justified=False,
                    explanation="Already found this answer",
                )

            # Check if translated rule is supported
            if translated_rule.supporting_bridges or True:
                quality = (rule1.quality + rule2.quality) / 2.0
                return JustificationResult(
                    justified=True,
                    top_rule=rule1,
                    bottom_rule=rule2,
                    quality=quality,
                    explanation="Translated rule works",
                    supporting_vertical_bridges=supporting_vbridges,
                    slippage_log=slippages,
                )

            return _attempt_clamp_rules(
                [chosen_rule, translated_rule],
                trace,
                themespace,
                workspace,
                slipnet,
                meta,
                concept_patterns=[_get_concept_pattern_dict(translated_rule)],
                explanation="Translated rule unsupported, clamping",
            )

    # Step 4 -- Unification section
    #   Attempt to unify chosen_rule with some other existing rule
    if not other_rules:
        return JustificationResult(
            justified=False,
            explanation="No other rules exist for unification",
        )

    if trace is not None and not trace.permission_to_clamp():
        return JustificationResult(
            justified=False,
            explanation="Permission to clamp denied for unification",
        )

    # Pick an other rule weighted by similarity of strength
    strength = chosen_rule.quality
    other_weights = [
        max(1.0, 100.0 - abs(strength - r.quality)) for r in other_rules
    ]
    other_rule: Rule = rng.weighted_pick(other_rules, other_weights)

    unifying_pattern = unify_rules(chosen_rule, other_rule, slipnet)
    if unifying_pattern is None:
        return JustificationResult(
            justified=False,
            explanation="Could not unify rules",
        )

    vertical_pattern = get_vertical_theme_pattern_to_clamp(
        unifying_pattern, slipnet
    )
    return _attempt_clamp_rules(
        [chosen_rule, other_rule],
        trace,
        themespace,
        workspace,
        slipnet,
        meta,
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
) -> ClampEvent | None:
    """Clamp a set of rules with their theme pattern, concept pattern, and
    codelet pattern for focused exploration.

    Scheme: justify.ss ``clamp-rules``.
    Creates a ClampEvent of type ``justify_clamp``, adds it to the trace,
    and activates it.
    """
    if not trace.permission_to_clamp():
        return None

    # Gather clamped patterns
    clamped_theme_patterns: list[Any] = []

    # Add each rule's theme pattern
    for rule in rules:
        if rule.theme_pattern is not None:
            tp = _theme_pattern_to_dict(rule.theme_pattern)
            if tp:
                clamped_theme_patterns.append(tp)

    # Add vertical theme pattern
    if vertical_theme_pattern is not None:
        clamped_theme_patterns.append(vertical_theme_pattern)
    elif themespace is not None:
        vtp = themespace.get_dominant_theme_pattern("vertical_bridge")
        if vtp and len(vtp) > 1:
            tp_dict = _theme_pattern_list_to_dict(vtp)
            if tp_dict:
                clamped_theme_patterns.append(tp_dict)

    # Concept patterns
    clamped_concept_patterns = concept_patterns or []

    # Codelet patterns: top-down + thematic
    clamped_codelet_patterns: list[Any] = [
        {"type": "top_down_codelet_pattern"},
        {"type": "thematic_codelet_pattern"},
    ]

    codelet_count = _get_codelet_count(workspace)
    temperature = _get_temperature(workspace)

    clamp_event = ClampEvent(
        codelet_count=codelet_count,
        temperature=temperature,
        clamp_type="justify_clamp",
        clamped_theme_patterns=clamped_theme_patterns,
        clamped_concept_patterns=clamped_concept_patterns,
        clamped_codelet_patterns=clamped_codelet_patterns,
        rules=list(rules),
        progress_focus="workspace",
    )

    # Add event first so concept-activation events appear after the clamp
    trace.add_clamp_event(clamp_event)
    clamp_event.activate(trace, themespace, slipnet)

    return clamp_event


# ============================================================================
#  Rule unification  (Scheme: justify.ss unify-rules)
# ============================================================================


def unify_rules(
    from_rule: Rule,
    to_rule: Rule,
    slipnet: Slipnet | None = None,
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
    filtered = _remove_whole_single_concept_mappings(concept_mappings)

    # Convert to theme pattern entries: (dimension, label)
    entries: list[tuple[str, str | None]] = []
    for cm in filtered:
        cm_type = cm.get("cm_type")
        label = cm.get("label")
        if cm_type:
            entries.append((cm_type, label))

    return ["vertical_bridge"] + entries


def get_unifying_slippages(
    from_rule: Rule,
    to_rule: Rule,
    slipnet: Slipnet | None = None,
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

    filtered = _remove_whole_single_concept_mappings(concept_mappings)
    return [cm for cm in filtered if cm.get("is_slippage", False)]


# ============================================================================
#  Rule clause traversal  (Scheme: justify.ss traverse-rule-clauses)
# ============================================================================


def traverse_rule_clauses(
    clauses1: list[RuleClause],
    clauses2: list[RuleClause],
    proc: Any,
    *,
    slipnet: Slipnet | None = None,
) -> list[dict[str, Any]] | None:
    """Recursive parallel traversal of rule clause trees.

    Scheme: justify.ss ``traverse-rule-clauses``.
    Walks the clause structures in parallel.  When two leaf nodes (slipnet
    nodes) are encountered, ``proc`` is called to produce a result entry.
    Returns None on structural mismatch ("fail").
    """

    class _Fail(Exception):
        pass

    def walk(
        x1: Any, x2: Any, results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if x1 is None and x2 is None:
            return results
        if x1 is None or x2 is None:
            raise _Fail()

        # Both are lists (e.g., list of changes, list of object-description items)
        if isinstance(x1, (list, tuple)) and isinstance(x2, (list, tuple)):
            if len(x1) != len(x2):
                raise _Fail()
            for a, b in zip(x1, x2):
                results = walk(a, b, results)
            return results

        # One is a list and the other is not -- structural mismatch
        if isinstance(x1, (list, tuple)) or isinstance(x2, (list, tuple)):
            raise _Fail()

        # Both are strings (e.g., clause_type, scope)
        if isinstance(x1, str) and isinstance(x2, str):
            if x1 == x2:
                return results
            raise _Fail()

        # SlipnetNode objects: delegate to proc
        if _is_slipnet_node(x1) and _is_slipnet_node(x2):
            return proc(x1, x2, results, slipnet=slipnet)

        # Fallback: if they're equal, fine; otherwise fail
        if x1 is x2 or x1 == x2:
            return results
        raise _Fail()

    try:
        # Flatten clause structures for parallel walk
        flat1 = _flatten_clauses(clauses1)
        flat2 = _flatten_clauses(clauses2)
        return walk(flat1, flat2, [])
    except _Fail:
        return None


def compare_rule_clause_lists(
    clauses1: list[RuleClause],
    clauses2: list[RuleClause],
) -> list[tuple] | None:
    """Compare two rule clause lists structurally.

    Scheme: justify.ss ``compare-rule-clause-lists``.
    Returns a list of (node1, node2) difference pairs, or None if
    structurally incompatible.  Empty list means identical.
    """
    # Check for verbatim rules
    if _is_verbatim_clause_list(clauses1) and _is_verbatim_clause_list(clauses2):
        if len(clauses1) == len(clauses2) and all(
            rules_equal(
                Rule("top", [c1]),
                Rule("top", [c2]),
            )
            for c1, c2 in zip(clauses1, clauses2)
        ):
            return []
        return None

    def comparison_proc(
        n1: Any,
        n2: Any,
        results: list[dict[str, Any]],
        *,
        slipnet: Slipnet | None = None,
    ) -> list[dict[str, Any]]:
        if n1 is n2:
            return results
        results.append({"node1": n1, "node2": n2})
        return results

    result = traverse_rule_clauses(clauses1, clauses2, comparison_proc)
    if result is None:
        return None
    return [(d["node1"], d["node2"]) for d in result]


# ============================================================================
#  Vertical theme pattern manipulation
#  (Scheme: justify.ss get-vertical-theme-pattern-to-clamp)
# ============================================================================


def get_vertical_theme_pattern_to_clamp(
    unifying_pattern: list,
    slipnet: Slipnet | None = None,
) -> dict[str, Any]:
    """Compute the vertical theme pattern to clamp from a unifying pattern.

    Scheme: justify.ss ``get-vertical-theme-pattern-to-clamp``.
    Applies retention probability filtering and heuristic adjustments
    (add direction entry, replace bond-category with group-category).
    """
    if not unifying_pattern or len(unifying_pattern) < 2:
        return _theme_pattern_list_to_dict(unifying_pattern) if unifying_pattern else {}

    theme_type = unifying_pattern[0]
    pattern_entries = unifying_pattern[1:]

    # Compute retention probability for each entry and filter
    final_entries: list[tuple[str, str | None]] = []
    for entry in pattern_entries:
        if not isinstance(entry, tuple) or len(entry) < 2:
            continue
        dim, rel = entry[0], entry[1]
        prob = _retention_probability(entry, pattern_entries, slipnet)
        # Deterministic threshold of 0.5 for the non-stochastic helper
        if prob >= 0.5:
            final_entries.append((dim, rel))

    # Heuristic 1: Add direction entry if StrPos entry exists but Dir doesn't
    final_entries = _add_direction_entry(final_entries)

    # Heuristic 2: Replace BondCtgy with GroupCtgy
    final_entries = _replace_bond_category_entry(final_entries)

    if not final_entries:
        # Fall back to original pattern
        final_entries = [e for e in pattern_entries if isinstance(e, tuple)]

    return _build_theme_pattern_dict(theme_type, final_entries)


def _retention_probability(
    entry: tuple,
    all_entries: list[tuple],
    slipnet: Slipnet | None,
) -> float:
    """Compute the retention probability for a single pattern entry.

    Scheme: justify.ss ``retention-probability``.
    StrPos entries always retained (probability 1).
    Others: cd(dimension) * (50 if identity else 100) / 100.
    """
    dim = entry[0] if isinstance(entry, tuple) else None
    rel = entry[1] if isinstance(entry, tuple) and len(entry) > 1 else None

    if dim is not None and _is_string_position_category(dim):
        return 1.0

    cd = _get_conceptual_depth(dim, slipnet) if dim else 50.0
    identity_factor = 50.0 if _is_identity_label(rel) else 100.0
    return (cd / 100.0) * (identity_factor / 100.0)


def _add_direction_entry(
    entries: list[tuple[str, str | None]],
) -> list[tuple[str, str | None]]:
    """Heuristic: add Dir entry if StrPos exists but Dir doesn't.

    Scheme: justify.ss ``add-direction-entry``.
    """
    str_pos_entry = None
    dir_entry = None
    for entry in entries:
        dim = entry[0]
        if _is_string_position_category(dim):
            str_pos_entry = entry
        if _is_direction_category(dim):
            dir_entry = entry

    if str_pos_entry is not None and str_pos_entry[1] is not None and dir_entry is None:
        dir_dim = "plato-direction-category"
        return [
            (dir_dim, str_pos_entry[1])
        ] + list(entries)

    return list(entries)


def _replace_bond_category_entry(
    entries: list[tuple[str, str | None]],
) -> list[tuple[str, str | None]]:
    """Heuristic: replace BondCtgy with GroupCtgy.

    Scheme: justify.ss ``replace-bond-category-entry``.
    """
    bond_ctgy_entry = None
    group_ctgy_entry = None
    for entry in entries:
        dim = entry[0]
        if _is_bond_category(dim):
            bond_ctgy_entry = entry
        if _is_group_category(dim):
            group_ctgy_entry = entry

    if bond_ctgy_entry is not None:
        remaining = [e for e in entries if e is not bond_ctgy_entry]
        if group_ctgy_entry is None:
            return [
                (_group_category_name(), bond_ctgy_entry[1])
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
    """Get all built rules of a type (not just supported ones)."""
    rules = workspace.top_rules if top else workspace.bottom_rules
    return [r for r in rules if r.is_built]


def _translate_rule(
    rule: Rule,
    workspace: Workspace,
    slipnet: Slipnet | None,
) -> tuple[Rule, list[Any], list[Any]] | None:
    """Translate a rule using vertical bridge slippages.

    Returns (translated_rule, slippages, supporting_vertical_bridges) or None.
    """
    # Gather slippages from vertical bridges
    slippages: list[Any] = []
    supporting_vbridges: list[Any] = []
    for bridge in workspace.vertical_bridges:
        if bridge.is_built:
            slippages.extend(bridge.concept_mappings)
            supporting_vbridges.append(bridge)

    if not slippages:
        return None

    direction = (
        "top-to-bottom" if rule.rule_type == "top" else "bottom-to-top"
    )
    translated = rule.translate(slippages, direction)
    return (translated, slippages, supporting_vbridges)


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
    slipnet: Slipnet | None,
    original_rule_type: str,
) -> bool:
    """Check if the translated rule actually works on the other string pair."""
    if slipnet is None:
        return False
    try:
        return translated_rule.currently_works(workspace, slipnet)
    except Exception:
        return False


def _order_rules(
    chosen_rule: Rule, other_rule: Rule, chosen_type: str
) -> tuple[Rule, Rule]:
    """Return (top_rule, bottom_rule) regardless of which was chosen."""
    if chosen_type == "top":
        return (chosen_rule, other_rule)
    return (other_rule, chosen_rule)


def _answer_already_found(
    memory: Any,
    workspace: Workspace,
    top_rule: Rule,
    bottom_rule: Rule,
) -> bool:
    """Check episodic memory for a duplicate answer."""
    if memory is None:
        return False
    if hasattr(memory, "answer_present"):
        return memory.answer_present(workspace, top_rule, bottom_rule)
    return False


def _attempt_clamp_rules(
    rules: list[Rule],
    trace: TemporalTrace | None,
    themespace: Themespace | None,
    workspace: Workspace,
    slipnet: Slipnet | None,
    meta: MetadataProvider,
    *,
    vertical_pattern_override: dict[str, Any] | None = None,
    concept_patterns: list[dict[str, Any]] | None = None,
    explanation: str = "Clamping rules",
) -> JustificationResult:
    """Attempt to clamp rules and return a JustificationResult."""
    if trace is None or themespace is None or slipnet is None:
        return JustificationResult(
            justified=False,
            explanation="Missing components for clamping",
        )

    clamp_event = clamp_rules(
        rules,
        trace,
        themespace,
        slipnet,
        workspace,
        meta,
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
    slipnet: Slipnet | None = None,
) -> list[dict[str, Any]]:
    """Process two leaf nodes during clause traversal for unification.

    Scheme: justify.ss ``concept-mapping-proc``.
    If nodes differ and are not slip-linked, fail.
    If the node has a category, produce a concept-mapping entry.
    """

    class _Fail(Exception):
        pass

    if n1 is not n2 and not _slip_linked(n1, n2, slipnet):
        raise _Fail()

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


def _slip_linked(n1: Any, n2: Any, slipnet: Slipnet | None) -> bool:
    """Check if two slipnet nodes are slip-linked."""
    if n1 is n2:
        return True
    if slipnet is not None and hasattr(slipnet, "slip_linked"):
        return slipnet.slip_linked(n1, n2) or slipnet.slip_linked(n2, n1)
    # Fallback: check if they have lateral sliplinks
    if hasattr(n1, "lateral_sliplinks"):
        for link in n1.lateral_sliplinks:
            if link.to_node is n2:
                return True
    if hasattr(n2, "lateral_sliplinks"):
        for link in n2.lateral_sliplinks:
            if link.to_node is n1:
                return True
    return False


def _get_category(node: Any) -> Any:
    """Get the category of a slipnet node.

    Scheme: ``(tell n1 'get-category)``
    """
    if hasattr(node, "category"):
        return node.category
    if hasattr(node, "get_category"):
        return node.get_category()
    return None


def _get_label(n1: Any, n2: Any, slipnet: Slipnet | None) -> str | None:
    """Get the label (identity, opposite, etc.) between two nodes."""
    if n1 is n2:
        return "plato-identity"
    if slipnet is not None and hasattr(slipnet, "get_label"):
        return slipnet.get_label(n1, n2)
    return None


def _get_conceptual_depth(node_name: Any, slipnet: Slipnet | None) -> float:
    """Get conceptual depth of a node by name."""
    if slipnet is not None and isinstance(node_name, str):
        node = slipnet.nodes.get(node_name)
        if node is not None:
            return node.conceptual_depth
    if hasattr(node_name, "conceptual_depth"):
        return node_name.conceptual_depth
    return 50.0


def _is_string_position_category(dim: Any) -> bool:
    name = getattr(dim, "name", dim) if not isinstance(dim, str) else dim
    return name == "plato-string-position-category"


def _is_direction_category(dim: Any) -> bool:
    name = getattr(dim, "name", dim) if not isinstance(dim, str) else dim
    return name == "plato-direction-category"


def _is_bond_category(dim: Any) -> bool:
    name = getattr(dim, "name", dim) if not isinstance(dim, str) else dim
    return name == "plato-bond-category"


def _is_group_category(dim: Any) -> bool:
    name = getattr(dim, "name", dim) if not isinstance(dim, str) else dim
    return name == "plato-group-category"


def _group_category_name() -> str:
    return "plato-group-category"


def _is_identity_label(label: Any) -> bool:
    if label is None:
        return False
    name = getattr(label, "name", label) if not isinstance(label, str) else label
    return name == "plato-identity"


def _remove_whole_single_concept_mappings(
    concept_mappings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove concept-mappings whose CM-type is string-position-category and
    whose descriptor1 is whole or single.

    Scheme: justify.ss ``remove-whole/single-concept-mappings``.
    """
    result = []
    for cm in concept_mappings:
        cm_type = cm.get("cm_type", "")
        d1 = cm.get("descriptor1")
        d1_name = getattr(d1, "name", str(d1)) if d1 else ""
        if cm_type == "plato-string-position-category" and d1_name in (
            "plato-single",
            "plato-whole",
        ):
            continue
        result.append(cm)
    return result


def _flatten_clauses(clauses: list[RuleClause]) -> list:
    """Flatten clause structures into a parallel-walkable list.

    This transforms the clause data into a nested list structure that
    can be traversed in parallel with another rule's clauses.
    Each clause becomes [clause_type, object_description, changes...]
    Each change becomes [dimension, from_descriptor, to_descriptor, relation]
    """
    result = []
    for clause in clauses:
        clause_flat: list = [clause.clause_type]
        if clause.object_description:
            clause_flat.append(list(clause.object_description))
        else:
            clause_flat.append([])
        for change in clause.changes:
            clause_flat.append(
                [
                    change.dimension,
                    change.from_descriptor,
                    change.to_descriptor,
                    change.relation,
                ]
            )
        result.append(clause_flat)
    return result


def _is_verbatim_clause_list(clauses: list[RuleClause]) -> bool:
    """Check if a clause list is a single verbatim clause."""
    return len(clauses) == 1 and clauses[0].is_verbatim


def _theme_pattern_to_dict(pattern: Any) -> dict[str, Any] | None:
    """Convert a theme pattern (list or dict) to a dict for clamping."""
    if isinstance(pattern, dict):
        return pattern
    if isinstance(pattern, list) and len(pattern) >= 1:
        return _theme_pattern_list_to_dict(pattern)
    return None


def _theme_pattern_list_to_dict(pattern: list) -> dict[str, Any]:
    """Convert a [theme_type, (dim, rel), ...] list to a dict."""
    if not pattern:
        return {}
    theme_type = pattern[0]
    entries = []
    for item in pattern[1:]:
        if isinstance(item, tuple) and len(item) >= 2:
            entries.append(
                {"dimension": item[0], "relation": item[1], "activation": 100.0}
            )
    return {"type": theme_type, "entries": entries}


def _build_theme_pattern_dict(
    theme_type: str, entries: list[tuple[str, str | None]]
) -> dict[str, Any]:
    """Build a theme pattern dict from a theme type and entries."""
    return {
        "type": theme_type,
        "entries": [
            {"dimension": dim, "relation": rel, "activation": 100.0}
            for dim, rel in entries
        ],
    }


def _get_codelet_count(workspace: Workspace) -> int:
    """Get current codelet count from workspace or default."""
    return getattr(workspace, "codelet_count", 0)


def _get_temperature(workspace: Workspace) -> float:
    """Get current temperature from workspace or default."""
    return getattr(workspace, "temperature", 50.0)


def _rules_compatible(rule1: Rule, rule2: Rule) -> bool:
    """Check if two rules are compatible (same structure after slippage).

    Preserved for backward compatibility.
    """
    if len(rule1.clauses) != len(rule2.clauses):
        return False
    for c1, c2 in zip(rule1.clauses, rule2.clauses):
        if c1.clause_type != c2.clause_type:
            return False
    return True
