"""Rule structures — transformation descriptions.

A Rule characterizes how one string transforms into another (e.g., how
"abc" becomes "abd"). Rules are built from bridges and contain intrinsic
clauses (changes to individual objects) and extrinsic clauses (group-level
changes). Quality is measured by uniformity, abstractness, and succinctness.

This module also contains the full rule *abstraction* pipeline (extracting
change descriptions from bridges, converting them to rule clause templates,
instantiating templates to rule clauses) and the rule *application* pipeline
(applying a rule to a target string via the image system to produce answer
letters).

Scheme source: rules.ss
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from server.engine.workspace_structures import WorkspaceStructure
from server.engine.formulas import sigmoid, weighted_average
from server.engine.images import (
    ImageFailure,
    StringImage,
    is_platonic_letter,
    is_platonic_number,
    is_platonic_relation,
    get_related_node,
    get_label,
    inverse,
    make_string_image,
    change_length_first,
)

if TYPE_CHECKING:
    from server.engine.bridges import Bridge
    from server.engine.concept_mappings import ConceptMapping
    from server.engine.groups import Group
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG
    from server.engine.slipnet import Slipnet, SlipnetNode
    from server.engine.workspace import Workspace, WorkspaceString
    from server.engine.workspace_objects import WorkspaceObject

# Clause type string constants (values live in DB clause_types table)
CLAUSE_INTRINSIC = "intrinsic"
CLAUSE_EXTRINSIC = "extrinsic"
CLAUSE_VERBATIM = "verbatim"

# Rule type string constants (values live in DB rule_types table)
RULE_TOP = "top"
RULE_BOTTOM = "bottom"

# Scope constants for change descriptions / change templates
SCOPE_SELF = "self"
SCOPE_SUBOBJECTS = "subobjects"

# Dimension ordering for sorting rule dimensions and change templates.
# Matches *rule-dimension-order* in rules.ss:934-943.
_RULE_DIMENSION_ORDER_NAMES: list[str] = [
    "plato-direction-category",
    "plato-group-category",
    "plato-alphabetic-position-category",
    "plato-letter-category",
    "plato-length",
    "plato-object-category",
    "plato-string-position-category",
    "plato-bond-facet",
]


def _dim_sort_key(dim: SlipnetNode) -> int:
    """Sort key for a slipnet dimension node according to the canonical order."""
    name = getattr(dim, "name", "")
    try:
        return _RULE_DIMENSION_ORDER_NAMES.index(name)
    except ValueError:
        return len(_RULE_DIMENSION_ORDER_NAMES)


# ---------------------------------------------------------------------------
# Change Descriptions
#
# These are intermediate representations produced by rule abstraction.  Each
# describes ONE conceptual change observed in one or more horizontal bridges.
# They are later grouped and converted into rule-clause-templates.
#
# Scheme source: rules.ss:948-1062.
# ---------------------------------------------------------------------------


class IntrinsicChangeDescription:
    """Describes a change to a single object (intrinsic).

    Scheme: make-intrinsic-change-description (rules.ss:996-1062).

    Parameters
    ----------
    reference_object : WorkspaceObject | WorkspaceString
        The object (letter or group) whose property changed, or its
        enclosing string.
    scope : str
        SCOPE_SELF or SCOPE_SUBOBJECTS.
    dimension : SlipnetNode
        The conceptual dimension that changed (e.g., plato-letter-category).
    descriptor1 : SlipnetNode | None
        The *from* descriptor (before the change). May be None.
    relation : SlipnetNode | None
        The relationship between descriptor1 and descriptor2 (e.g., successor).
    descriptor2 : SlipnetNode | None
        The *to* descriptor (after the change). May be None.
    """

    def __init__(
        self,
        reference_object: Any,
        scope: str,
        dimension: SlipnetNode,
        descriptor1: SlipnetNode | None,
        relation: SlipnetNode | None,
        descriptor2: SlipnetNode | None,
    ) -> None:
        self.reference_object = reference_object
        self.scope = scope
        self.dimension = dimension
        self.descriptor1 = descriptor1
        self.relation = relation
        self.descriptor2 = descriptor2
        # Combined descriptors list (non-None of relation, descriptor2)
        self.descriptors: list[SlipnetNode] = [
            d for d in [relation, descriptor2] if d is not None
        ]
        self.enclosing_object: Any = self._compute_enclosing_object()

    def _compute_enclosing_object(self) -> Any:
        """Return the enclosing group or string of reference_object."""
        # WorkspaceString objects have no enclosing group
        if _is_workspace_string(self.reference_object):
            return None
        eg = getattr(self.reference_object, "enclosing_group", None)
        if eg is not None:
            return eg
        return getattr(self.reference_object, "string", None)

    # -- predicates (mirror Scheme tell-based methods) ----------------------

    @property
    def is_intrinsic(self) -> bool:
        return True

    def same_change_type(self, other: IntrinsicChangeDescription | ExtrinsicChangeDescription) -> bool:
        return other.is_intrinsic

    def same_scope(self, other: IntrinsicChangeDescription) -> bool:
        return self.scope == other.scope

    def change_self(self) -> bool:
        return self.scope == SCOPE_SELF

    def change_subobjects(self) -> bool:
        return self.scope == SCOPE_SUBOBJECTS

    def is_dimension(self, dim: SlipnetNode) -> bool:
        return self.dimension is dim

    def same_dimension(self, other: IntrinsicChangeDescription) -> bool:
        return self.dimension is other.dimension

    def same_reference_objects(self, other: IntrinsicChangeDescription) -> bool:
        return self.reference_object is other.reference_object

    def encloses(self, other: IntrinsicChangeDescription) -> bool:
        """True if self's reference object is the immediate enclosing object of other's."""
        return self.reference_object is other.enclosing_object

    def encloses_at_any_level(self, other: IntrinsicChangeDescription) -> bool:
        """True if self's reference object encloses other's at any nesting level."""
        return _nested_member(self.reference_object, other.reference_object)

    def is_lettctgy_or_alphposctgy_dimension(self) -> bool:
        name = getattr(self.dimension, "name", "")
        return name in ("plato-letter-category", "plato-alphabetic-position-category")

    def change_to_letter(self) -> bool:
        d2_name = getattr(self.descriptor2, "name", "") if self.descriptor2 else ""
        return d2_name == "plato-letter"

    def same_dimension_as_group_category_medium(self, other: IntrinsicChangeDescription) -> bool:
        """True if self.dimension is the bond-facet of other's reference object."""
        bf = getattr(other.reference_object, "bond_facet", None)
        return bf is not None and self.dimension is bf

    def implied_by_opposite_group_category(self) -> bool:
        from server.engine.groups import Group
        if not isinstance(self.reference_object, Group):
            return False
        # ending letter category of the group
        ending = _get_ending_letter_category(self.reference_object)
        return ending is not None and ending is self.descriptor2

    def get_bond_facet_change(self) -> tuple | None:
        """Scheme: get-BondFacet-change.

        If this is a self GroupCtgy change on a group, return a
        (self, plato-bond-facet, (bond_facet_node,)) change-template entry.
        """
        from server.engine.groups import Group
        if not isinstance(self.reference_object, Group):
            return None
        dim_name = getattr(self.dimension, "name", "")
        if dim_name != "plato-group-category" or self.scope != SCOPE_SELF:
            return None
        bf = getattr(self.reference_object, "bond_facet", None)
        if bf is None:
            return None
        return (SCOPE_SELF, bf, [bf])  # (scope, dimension_node, [descriptors])

    def make_change_template(self) -> tuple:
        """Scheme: make-change-template.

        Returns (scope, dimension, descriptors).
        Disallows literal DirCtgy or GroupCtgy changes.
        """
        dim_name = getattr(self.dimension, "name", "")
        if dim_name in ("plato-direction-category", "plato-group-category"):
            # Remove descriptor2 from descriptors (keep only the relation)
            return (
                self.scope,
                self.dimension,
                [d for d in self.descriptors if d is not self.descriptor2],
            )
        return (self.scope, self.dimension, list(self.descriptors))

    # -- implication heuristics (rules.ss:1194-1231) ------------------------

    def implies(self, other: IntrinsicChangeDescription | ExtrinsicChangeDescription) -> bool:
        """True if *other* is already implicit in self."""
        if other.is_intrinsic:
            return intrinsic_implies_intrinsic(self, other)  # type: ignore[arg-type]
        return False

    def conflicts(self, other: IntrinsicChangeDescription) -> bool:
        return intrinsic_implies_intrinsic(self, other) or intrinsic_implies_intrinsic(other, self)

    def __repr__(self) -> str:
        dim = getattr(self.dimension, "short_name", "?")
        scope = self.scope
        ref = _ascii_name(self.reference_object)
        return f"IntrinsicCD({scope} {dim} of {ref})"


class ExtrinsicChangeDescription:
    """Describes a swap of descriptors among a set of objects (extrinsic).

    Scheme: make-extrinsic-change-description (rules.ss:948-993).

    Parameters
    ----------
    reference_objects : list[WorkspaceObject]
        The objects involved in the swap.
    dimension : SlipnetNode
        The dimension being swapped (e.g., plato-length).
    descriptors : list[SlipnetNode]
        The two descriptor values being swapped.
    """

    def __init__(
        self,
        reference_objects: list[Any],
        dimension: SlipnetNode,
        descriptors: list[SlipnetNode],
    ) -> None:
        self.reference_objects = reference_objects
        self.dimension = dimension
        self.descriptors = descriptors
        self.subobjects_swap: bool = False
        # Build equivalent intrinsic changes for implication checking
        self.equivalent_intrinsic_changes: list[IntrinsicChangeDescription] = []
        for obj in reference_objects:
            desc_for = _get_descriptor_for(obj, dimension)
            if desc_for is descriptors[0]:
                to_desc = descriptors[1] if len(descriptors) > 1 else descriptors[0]
            else:
                to_desc = descriptors[0]
            self.equivalent_intrinsic_changes.append(
                IntrinsicChangeDescription(
                    obj, SCOPE_SELF, dimension, None, None, to_desc
                )
            )

    @property
    def is_intrinsic(self) -> bool:
        return False

    def same_change_type(self, other: IntrinsicChangeDescription | ExtrinsicChangeDescription) -> bool:
        return not other.is_intrinsic

    def same_reference_objects(self, other: ExtrinsicChangeDescription) -> bool:
        return set(id(o) for o in self.reference_objects) == set(
            id(o) for o in other.reference_objects
        )

    def common_reference_object(self, ic: IntrinsicChangeDescription) -> bool:
        return any(o is ic.reference_object for o in self.reference_objects)

    def mark_as_subobjects_swap_if_possible(self) -> None:
        """Scheme: mark-as-subobjects-swap-if-possible."""
        enclosing = _get_enclosing_object(self.reference_objects[0])
        if enclosing is None:
            return
        constituents = _get_constituent_objects(enclosing)
        if _sets_equal_by_id(constituents, self.reference_objects):
            self.subobjects_swap = True

    def get_enclosing_object(self) -> Any:
        return _get_enclosing_object(self.reference_objects[0])

    def get_left_string_pos(self) -> int:
        return min(getattr(o, "left_string_pos", 0) for o in self.reference_objects)

    # -- implication --------------------------------------------------------

    def implies(self, other: IntrinsicChangeDescription | ExtrinsicChangeDescription) -> bool:
        if other.is_intrinsic:
            return extrinsic_implies_intrinsic(self, other)  # type: ignore[arg-type]
        return extrinsic_implies_extrinsic(self, other)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        dim = getattr(self.dimension, "short_name", "?")
        return f"ExtrinsicCD(swap {dim})"


# ---------------------------------------------------------------------------
# Implication heuristics  (rules.ss:1194-1247)
# ---------------------------------------------------------------------------


def intrinsic_implies_intrinsic(
    ic1: IntrinsicChangeDescription, ic2: IntrinsicChangeDescription
) -> bool:
    """Scheme: intrinsic-implies-intrinsic? (rules.ss:1194-1231).

    True if ic2 is already implicit in ic1.  See the extensive comments
    in rules.ss for the full set of heuristic cases.
    """
    # Case 1: Same dimension, same or enclosing ref object
    if ic1.same_dimension(ic2):
        if (ic1.same_reference_objects(ic2) and ic1.same_scope(ic2)):
            return True
        if ic1.encloses(ic2) and ic1.change_subobjects() and ic2.change_self():
            return True

    # Case 2: LettCtgy/AlphPosCtgy interactions
    if ic1.is_lettctgy_or_alphposctgy_dimension() and ic2.is_lettctgy_or_alphposctgy_dimension():
        if ic1.same_reference_objects(ic2):
            # AlphPosCtgy change implies LettCtgy change on same object
            if (ic1.is_dimension_by_name("plato-alphabetic-position-category")
                    and ic2.is_dimension_by_name("plato-letter-category")):
                return True
            # Same dimension: subobjects change is implicit in self change
            if ic1.same_dimension(ic2) and ic2.change_subobjects():
                return True
        if ic1.encloses_at_any_level(ic2):
            return True

    # Case 2.3: Length change on enclosing group implies LettCtgy change
    if (ic1.is_dimension_by_name("plato-length")
            and ic2.is_dimension_by_name("plato-letter-category")
            and ic1.encloses(ic2) and ic1.change_self()):
        return True

    # Case 2.4: GroupCtgy change implies letter changes of group medium
    if (ic1.is_dimension_by_name("plato-group-category") and ic1.change_self()
            and ic2.same_dimension_as_group_category_medium(ic1)):
        if ic1.encloses(ic2):
            return True
        if (ic1.same_reference_objects(ic2)
                and ic2.is_dimension_by_name("plato-letter-category")
                and ic2.implied_by_opposite_group_category()):
            return True

    # Case: StrPosCtgy implies DirCtgy
    if (ic1.is_dimension_by_name("plato-string-position-category")
            and ic2.is_dimension_by_name("plato-direction-category")
            and ic2.encloses(ic1) and ic2.change_self()):
        return True

    # Case 3: ObjCtgy:letter implies Length change
    if ic1.change_to_letter() and ic2.is_dimension_by_name("plato-length"):
        if ic1.same_reference_objects(ic2) and ic1.same_scope(ic2):
            return True
        if (ic1.encloses(ic2) and ic1.change_subobjects() and ic2.change_self()):
            return True

    return False


def extrinsic_implies_intrinsic(
    ec: ExtrinsicChangeDescription, ic: IntrinsicChangeDescription
) -> bool:
    """Scheme: extrinsic-implies-intrinsic? (rules.ss:1234-1236)."""
    return any(eic.conflicts(ic) for eic in ec.equivalent_intrinsic_changes)


def extrinsic_implies_extrinsic(
    ec1: ExtrinsicChangeDescription, ec2: ExtrinsicChangeDescription
) -> bool:
    """Scheme: extrinsic-implies-extrinsic? (rules.ss:1239-1247)."""
    return all(
        any(ic1.implies(ic2) for ic2 in ec2.equivalent_intrinsic_changes)
        for ic1 in ec1.equivalent_intrinsic_changes
    )


# Monkey-patch a convenience for dimension name checking
IntrinsicChangeDescription.is_dimension_by_name = (  # type: ignore[attr-defined]
    lambda self, name: getattr(self.dimension, "name", "") == name
)


# ---------------------------------------------------------------------------
# Helper predicates / accessors used by change descriptions
# ---------------------------------------------------------------------------


def _is_workspace_string(obj: Any) -> bool:
    """Check if obj is a WorkspaceString (not a WorkspaceObject)."""
    from server.engine.workspace import WorkspaceString
    return isinstance(obj, WorkspaceString)


def _ascii_name(obj: Any) -> str:
    """Best-effort short name for a workspace object or string."""
    if hasattr(obj, "text"):
        return f"[{obj.text}]"
    if hasattr(obj, "letter_category"):
        return getattr(obj.letter_category, "short_name", "?")
    return repr(obj)


def _get_descriptor_for(obj: Any, dimension: SlipnetNode) -> SlipnetNode | None:
    """Get the descriptor for a given description type on *obj*.

    Walks obj.descriptions looking for one whose description_type is *dimension*.
    """
    for d in getattr(obj, "descriptions", []):
        if d.description_type is dimension:
            return d.descriptor
    return None


def _get_enclosing_object(obj: Any) -> Any:
    """Return the enclosing group, or the string if no enclosing group."""
    eg = getattr(obj, "enclosing_group", None)
    if eg is not None:
        return eg
    return getattr(obj, "string", None)


def _get_constituent_objects(obj: Any) -> list[Any]:
    """Return the constituent (sub-)objects of a group or string.

    For a group: its direct member objects.
    For a string: its top-level letters/groups (not enclosed in another group).
    """
    if _is_workspace_string(obj):
        from server.engine.workspace_objects import Letter
        return [
            o for o in getattr(obj, "objects", [])
            if getattr(o, "enclosing_group", None) is None
        ]
    return list(getattr(obj, "objects", []))


def _get_ending_letter_category(group: Any) -> SlipnetNode | None:
    """Get the ending letter-category of a group (the last sub-object's letter-category)."""
    objects = getattr(group, "objects", [])
    if not objects:
        return None
    last = objects[-1]
    return getattr(last, "letter_category", None)


def _nested_member(outer: Any, inner: Any) -> bool:
    """True if *outer* encloses *inner* at any nesting level."""
    current = inner
    while current is not None:
        eg = getattr(current, "enclosing_group", None)
        if eg is None:
            s = getattr(current, "string", None)
            if s is outer:
                return True
            return False
        if eg is outer:
            return True
        current = eg
    return False


def _sets_equal_by_id(a: list, b: list) -> bool:
    return set(id(x) for x in a) == set(id(x) for x in b)


def _nesting_level(obj: Any) -> int:
    """Compute the nesting level (0 for letters, 1+ for groups)."""
    level = 0
    current = obj
    while True:
        eg = getattr(current, "enclosing_group", None)
        if eg is None:
            break
        level += 1
        current = eg
    return level


def _disjoint_objects(o1: Any, o2: Any) -> bool:
    """True if o1 and o2 don't overlap in string position."""
    return (
        getattr(o1, "right_string_pos", -1) < getattr(o2, "left_string_pos", 0)
        or getattr(o2, "right_string_pos", -1) < getattr(o1, "left_string_pos", 0)
    )


class RuleChange:
    """A single change within a rule clause."""

    def __init__(
        self,
        dimension: SlipnetNode | None = None,
        from_descriptor: SlipnetNode | None = None,
        to_descriptor: SlipnetNode | None = None,
        relation: SlipnetNode | None = None,
    ) -> None:
        self.dimension = dimension
        self.from_descriptor = from_descriptor
        self.to_descriptor = to_descriptor
        self.relation = relation  # e.g., successor, predecessor

    @property
    def is_relation(self) -> bool:
        """Is this change expressed as a relation rather than literal descriptors?"""
        return self.relation is not None

    def __repr__(self) -> str:
        if self.relation:
            dim = getattr(self.dimension, "short_name", "?")
            rel = getattr(self.relation, "short_name", "?")
            return f"Change({dim}:{rel})"
        frm = getattr(self.from_descriptor, "short_name", "?")
        to = getattr(self.to_descriptor, "short_name", "?")
        return f"Change({frm}->{to})"


class RuleClause:
    """One clause of a rule — describes one aspect of the transformation."""

    def __init__(
        self,
        clause_type: str,
        object_description: tuple | None = None,
        changes: list[RuleChange] | None = None,
        extrinsic_objects: list[tuple] | None = None,
        verbatim_letters: list[Any] | None = None,
    ) -> None:
        self.clause_type = clause_type
        self.object_description = object_description
        self.changes = changes or []
        self.extrinsic_objects = extrinsic_objects
        self.verbatim_letters = verbatim_letters

    @property
    def is_intrinsic(self) -> bool:
        return self.clause_type == CLAUSE_INTRINSIC

    @property
    def is_extrinsic(self) -> bool:
        return self.clause_type == CLAUSE_EXTRINSIC

    @property
    def is_verbatim(self) -> bool:
        return self.clause_type == CLAUSE_VERBATIM

    def __repr__(self) -> str:
        return f"RuleClause({self.clause_type}, {len(self.changes)} changes)"


class Rule(WorkspaceStructure):
    """A transformation rule."""

    def __init__(
        self,
        rule_type: str,
        clauses: list[RuleClause],
    ) -> None:
        super().__init__()
        self.rule_type = rule_type
        self.clauses = clauses
        self.supporting_bridges: list[Any] = []
        self.uniformity: float = 0.0
        self.abstractness: float = 0.0
        self.succinctness: float = 0.0
        self.quality: float = 0.0
        self.english_transcription: str = ""
        # Rule clause templates (the intermediate form before instantiation)
        self.rule_clause_templates: list[tuple] = []
        # Tagged supporting horizontal bridges: list of (unsupported_self_change?, [bridges])
        self.tagged_supporting_horizontal_bridges: list[tuple] = []
        # Theme pattern at creation time (bridge_theme_type, thematic_relations...)
        self.theme_pattern: list | None = None
        # For translated rules: reference to the source rule
        self.original_rule: Rule | None = None
        # Direction of translation (if translated)
        self.translation_direction: str | None = None
        # Whether this rule was produced by translation
        self.translated: bool = False

    @property
    def is_top_rule(self) -> bool:
        return self.rule_type == RULE_TOP

    @property
    def is_bottom_rule(self) -> bool:
        return self.rule_type == RULE_BOTTOM

    @property
    def intrinsic_clauses(self) -> list[RuleClause]:
        return [c for c in self.clauses if c.is_intrinsic]

    @property
    def extrinsic_clauses(self) -> list[RuleClause]:
        return [c for c in self.clauses if c.is_extrinsic]

    @property
    def is_identity_rule(self) -> bool:
        """Rule that changes nothing."""
        return len(self.clauses) == 0

    @property
    def is_verbatim_rule(self) -> bool:
        return any(c.is_verbatim for c in self.clauses)

    @property
    def is_literal_rule(self) -> bool:
        """A rule with at least one literal clause (non-abstract, non-verbatim).

        Scheme: rules.ss:210-211.
        """
        if self.is_verbatim_rule:
            return False
        return any(_literal_clause(c) for c in self.clauses)

    @property
    def is_abstract_rule(self) -> bool:
        """Neither verbatim nor literal."""
        return not self.is_verbatim_rule and not self.is_literal_rule

    @property
    def bridge_theme_type(self) -> str:
        """Theme type based on rule type."""
        return "top-bridge" if self.rule_type == RULE_TOP else "bottom-bridge"

    def get_verbatim_letter_categories(self) -> list[Any]:
        """Scheme: get-verbatim-letter-categories."""
        for c in self.clauses:
            if c.is_verbatim and c.verbatim_letters:
                return c.verbatim_letters
        return []

    def get_concept_pattern(self) -> list[tuple]:
        """Return concept pattern for theme computation.

        Scheme: rules.ss:266-269.
        Returns list of (node, max_activation) for all slipnet nodes in clauses.
        """
        nodes: list[SlipnetNode] = []
        for clause in self.clauses:
            if clause.is_verbatim:
                continue
            if clause.object_description:
                for item in clause.object_description:
                    if hasattr(item, "activation"):
                        nodes.append(item)
            for change in clause.changes:
                for node in [change.dimension, change.from_descriptor,
                             change.to_descriptor, change.relation]:
                    if node is not None and hasattr(node, "activation"):
                        nodes.append(node)
        # Deduplicate
        seen: set[int] = set()
        unique: list[SlipnetNode] = []
        for n in nodes:
            nid = id(n)
            if nid not in seen:
                seen.add(nid)
                unique.append(n)
        return [(n, 100.0) for n in unique]

    def compute_quality(self, meta: MetadataProvider) -> None:
        """Compute rule quality from uniformity, abstractness, succinctness.

        Scheme: rules.ss:1544-1549.
        quality = uniformity * weighted_average([abstractness, succinctness], [3, 2])
        """
        self._compute_uniformity(meta)
        self._compute_abstractness(meta)
        self._compute_succinctness(meta)

        if self.is_identity_rule:
            self.quality = 100.0
            return

        if self.is_verbatim_rule:
            self.quality = 10.0
            return

        abs_weight = meta.get_formula_coeff("rule_abstractness_weight")  # 3
        succ_weight = meta.get_formula_coeff("rule_succinctness_weight")  # 2
        combined = weighted_average(
            [self.abstractness, self.succinctness],
            [abs_weight, succ_weight],
        )
        self.quality = round((self.uniformity / 100.0) * combined)

    def _compute_uniformity(self, meta: MetadataProvider) -> None:
        """Scheme: rules.ss:1552-1596."""
        if len(self.clauses) <= 1:
            self.uniformity = 100.0
            return
        # Simplified: more uniform if clauses share the same type
        clause_types = [c.clause_type for c in self.clauses]
        same_type_ratio = clause_types.count(clause_types[0]) / len(clause_types)
        decay = meta.get_formula_coeff("rule_uniformity_adjusted_decay_constant")  # 4
        import math
        self.uniformity = round(100.0 * math.exp(decay * (same_type_ratio - 1.0)))

    def _compute_abstractness(self, meta: MetadataProvider) -> None:
        """Scheme: rules.ss:1599-1625."""
        if self.is_verbatim_rule:
            self.abstractness = 0.0
            return
        if self.is_identity_rule:
            self.abstractness = 100.0
            return

        # Collect conceptual depths from changes
        depths = []
        for clause in self.clauses:
            for change in clause.changes:
                if change.dimension:
                    depths.append(change.dimension.conceptual_depth)

        if not depths:
            self.abstractness = 50.0
            return

        avg_depth = sum(depths) / len(depths)
        beta = meta.get_formula_coeff("rule_abstractness_sigmoid_beta")  # 3
        mid = meta.get_formula_coeff("rule_abstractness_sigmoid_midpoint")  # 40
        self.abstractness = round(100.0 * sigmoid(avg_depth, beta, mid))

    def _compute_succinctness(self, meta: MetadataProvider) -> None:
        """Scheme: rules.ss:1628-1637."""
        if self.is_identity_rule or self.is_verbatim_rule:
            self.succinctness = 100.0 if self.is_identity_rule else 10.0
            return

        base_cost = meta.get_formula_coeff("rule_succinctness_base_cost")  # 3
        total_cost = 0.0
        for clause in self.clauses:
            if clause.is_extrinsic:
                total_cost += 2.0
            elif clause.object_description and len(clause.object_description) > 2:
                total_cost += 2.0
            else:
                total_cost += 1.0
        self.succinctness = round(100.0 * (base_cost + 1) / (base_cost + total_cost))

    def calculate_internal_strength(self) -> float:
        """Scheme: rules.ss:286 — uses relative quality."""
        return self.get_relative_quality()

    def calculate_external_strength(self) -> float:
        """Scheme: rules.ss:287 — same as internal strength for rules."""
        return self.calculate_internal_strength()

    def get_relative_quality(self, workspace: Workspace | None = None) -> float:
        """Quality relative to other rules of the same type.

        Scheme: rules.ss:244-251.
        rank / total_count * 100.
        """
        if workspace is None:
            return self.quality
        rules = (
            workspace.top_rules if self.is_top_rule else workspace.bottom_rules
        )
        ranked = sorted(rules, key=lambda r: r.quality)
        if self not in ranked:
            return self.quality
        rank = ranked.index(self) + 1
        return round(100.0 * rank / len(ranked))

    def supported(self, workspace: Workspace) -> bool:
        """Check if all supporting bridges still exist.

        Scheme: rules.ss:219-222.
        """
        for b in self.supporting_bridges:
            if not _bridge_present(workspace, b):
                return False
        return True

    def get_degree_of_support(self, workspace: Workspace) -> float:
        """Product of supporting bridge strengths (as fractions).

        Scheme: rules.ss:237-242.
        """
        if not self.supporting_bridges:
            return 0.0
        product = 1.0
        for b in self.supporting_bridges:
            equiv = _get_equivalent_bridge(workspace, b)
            if equiv is not None:
                product *= equiv.strength / 100.0
            else:
                product *= 0.0
        return round(100.0 * product)

    def currently_works(self, workspace: Workspace, slipnet: Slipnet) -> bool:
        """Test if applying this rule to its source string reproduces the target.

        Scheme: rules.ss:224-235.
        For a top rule: apply to initial_string, compare with modified_string.
        For a bottom rule: apply to target_string, compare with answer_string.
        """
        if self.is_top_rule:
            source = workspace.initial_string
            target = workspace.modified_string
        else:
            source = workspace.target_string
            target = workspace.answer_string
        if target is None:
            return False
        try:
            result = apply_rule(self, source, slipnet)
        except (ImageFailure, Exception):
            return False
        if result is None:
            return False
        generated = _generate_image_letters(source, slipnet)
        target_letters = _get_letter_categories(target)
        return generated == target_letters

    def rules_equal(self, other: Rule) -> bool:
        """Structural equality, clause by clause.

        Scheme: rules.ss:364-391.
        """
        return rules_equal(self, other)

    def mark_as_translated(self, original: Rule, direction: str) -> None:
        """Scheme: rules.ss:135-139."""
        self.original_rule = original
        self.translation_direction = direction
        self.translated = True

    def set_abstracted_rule_information(
        self,
        templates: list[tuple],
        themespace: Any = None,
    ) -> None:
        """Store rule-clause templates and supporting bridges after abstraction.

        Scheme: rules.ss:142-162.
        """
        self.rule_clause_templates = templates
        self.tagged_supporting_horizontal_bridges = [
            get_tagged_supporting_horizontal_bridges(t) for t in templates
        ]
        self.supporting_bridges = []
        for tag_bridges in self.tagged_supporting_horizontal_bridges:
            self.supporting_bridges.extend(tag_bridges[1])
        if themespace is not None:
            self.theme_pattern = themespace.get_dominant_theme_pattern(
                self.bridge_theme_type
            )
        else:
            self.theme_pattern = [self.bridge_theme_type]

    def set_verbatim_rule_information(self) -> None:
        """Scheme: rules.ss:189-194."""
        self.rule_clause_templates = []
        self.tagged_supporting_horizontal_bridges = []
        self.supporting_bridges = []
        self.theme_pattern = [self.bridge_theme_type]

    def translate(
        self,
        slippages: list[ConceptMapping],
        direction: str = "top-to-bottom",
    ) -> Rule:
        """Translate this rule by applying conceptual slippages.

        Scheme: rules.ss translate method.
        Returns a new Rule with slipped descriptors.  Each slipnet node in
        the rule clauses is passed through the slippages (using the node's
        apply_slippages method when available for coattail slippage support).

        Parameters
        ----------
        slippages : list[ConceptMapping]
            The vertical bridge concept-mappings to apply.
        direction : str
            Either "top-to-bottom" or "bottom-to-top".
        """
        new_clauses = []
        for clause in self.clauses:
            new_clause = self._translate_clause(clause, slippages)
            new_clauses.append(new_clause)

        new_rule_type = RULE_BOTTOM if self.is_top_rule else RULE_TOP
        translated = Rule(
            rule_type=new_rule_type,
            clauses=new_clauses,
        )
        translated.quality = self.quality
        translated.uniformity = self.uniformity
        translated.abstractness = self.abstractness
        translated.succinctness = self.succinctness
        translated.mark_as_translated(self, direction)
        return translated

    def _translate_clause(
        self,
        clause: RuleClause,
        slippages: list[ConceptMapping],
    ) -> RuleClause:
        """Translate a single clause by applying slippages.

        Each node in the clause is passed through slippages.  For nodes
        that have an ``apply_slippages`` method (SlipnetNodes), we use it
        to support coattail slippages; otherwise we do a simple direct
        match.
        """
        if clause.is_verbatim:
            return clause  # Verbatim clauses don't translate

        new_changes = []
        for change in clause.changes:
            new_change = RuleChange(
                dimension=self._slip(change.dimension, slippages),
                from_descriptor=self._slip(change.from_descriptor, slippages),
                to_descriptor=self._slip(change.to_descriptor, slippages),
                relation=self._slip(change.relation, slippages),
            )
            new_changes.append(new_change)

        new_obj_desc = None
        if clause.object_description:
            new_obj_desc = tuple(
                self._slip(d, slippages)
                if hasattr(d, "name")
                else d
                for d in clause.object_description
            )

        return RuleClause(
            clause_type=clause.clause_type,
            object_description=new_obj_desc,
            changes=new_changes,
        )

    def _slip(self, node: Any, slippages: list[ConceptMapping]) -> Any:
        """Apply slippages to a slipnet node.

        If the node has an ``apply_slippages`` method (i.e., it is a
        SlipnetNode), delegate to that for full coattail slippage support.
        Otherwise do a simple direct-match walk.
        """
        if node is None:
            return None
        # Use the SlipnetNode's own apply_slippages for full coattail support
        if hasattr(node, "apply_slippages"):
            return node.apply_slippages(slippages)
        # Fallback: simple direct match
        for cm in slippages:
            if cm.descriptor1 is node:
                return cm.descriptor2
            if cm.descriptor2 is node:
                return cm.descriptor1
        return node

    def transcribe_to_english(self) -> str:
        """Generate English description of this rule.

        Scheme: answers.ss template-based transcription.
        """
        if self.is_identity_rule:
            return "No change"
        if self.is_verbatim_rule:
            return "Verbatim copy"

        parts = []
        for clause in self.clauses:
            for change in clause.changes:
                dim = getattr(change.dimension, "short_name", "?")
                if change.relation:
                    rel = getattr(change.relation, "short_name", "?")
                    parts.append(f"change {dim} by {rel}")
                elif change.from_descriptor and change.to_descriptor:
                    frm = getattr(change.from_descriptor, "short_name", "?")
                    to = getattr(change.to_descriptor, "short_name", "?")
                    parts.append(f"change {dim} from {frm} to {to}")
        self.english_transcription = "; ".join(parts) if parts else "Unknown transformation"
        return self.english_transcription

    def __repr__(self) -> str:
        rt = "top" if self.is_top_rule else "bottom"
        return f"Rule({rt}, {len(self.clauses)} clauses, quality={self.quality:.0f})"


# ============================================================================
#  Rule Equality
# ============================================================================


def rules_equal(rule1: Rule, rule2: Rule) -> bool:
    """Structural equality of two rules, clause by clause.

    Scheme: rules-equal? (rules.ss:364-391).
    """
    c1 = rule1.clauses
    c2 = rule2.clauses
    if len(c1) != len(c2):
        return False
    return all(_clauses_equal(a, b) for a, b in zip(c1, c2))


def _clauses_equal(c1: RuleClause, c2: RuleClause) -> bool:
    """Scheme: rule-clauses-equal?"""
    if c1.clause_type != c2.clause_type:
        return False
    if c1.is_verbatim:
        return c1.verbatim_letters == c2.verbatim_letters
    # Compare object descriptions
    od1 = c1.object_description or ()
    od2 = c2.object_description or ()
    if len(od1) != len(od2):
        return False
    for d1, d2 in zip(od1, od2):
        if d1 is not d2:
            # Allow group/string interchangeability
            n1 = getattr(d1, "name", d1)
            n2 = getattr(d2, "name", d2)
            if not (_is_group_or_string_name(n1) and _is_group_or_string_name(n2)):
                return False
    # Compare changes
    if len(c1.changes) != len(c2.changes):
        return False
    for ch1, ch2 in zip(c1.changes, c2.changes):
        if not _changes_equal(ch1, ch2):
            return False
    return True


def _changes_equal(ch1: RuleChange, ch2: RuleChange) -> bool:
    return (
        ch1.dimension is ch2.dimension
        and ch1.from_descriptor is ch2.from_descriptor
        and ch1.to_descriptor is ch2.to_descriptor
        and ch1.relation is ch2.relation
    )


def _is_group_or_string_name(name: Any) -> bool:
    return name in ("plato-group", "string")


# ============================================================================
#  Literal-clause detection
# ============================================================================


def _literal_clause(clause: RuleClause) -> bool:
    """Scheme: literal-clause? (rules.ss:841-848).

    A clause is literal if any of its object descriptions or changes
    use literal (non-relational) descriptors.
    """
    if clause.is_verbatim:
        return False
    if clause.object_description:
        if _literal_object_description(clause.object_description):
            return True
    for change in clause.changes:
        if _literal_change(change):
            return True
    if clause.is_extrinsic and clause.extrinsic_objects:
        for od in clause.extrinsic_objects:
            if _literal_object_description(od):
                return True
    return False


def _literal_object_description(od: tuple) -> bool:
    """Scheme: literal-object-description? (rules.ss:851-854).

    An OD is literal if its description-type (2nd element) is one of
    AlphPosCtgy, LettCtgy, or Length.
    """
    if len(od) < 2:
        return False
    dt = od[1]
    dt_name = getattr(dt, "name", "")
    return dt_name in (
        "plato-alphabetic-position-category",
        "plato-letter-category",
        "plato-length",
    )


def _literal_change(change: RuleChange) -> bool:
    """Scheme: literal-change? (rules.ss:857-859).

    A change is literal if its descriptor (relation or to_descriptor) is a
    literal letter/number rather than a relational concept.
    """
    desc = change.relation if change.relation else change.to_descriptor
    if desc is None:
        return False
    return is_platonic_letter(desc) or is_platonic_number(desc)


# ============================================================================
#  Rule Describable Bridge Check
# ============================================================================


def rule_describable_bridge(bridge: Bridge) -> bool:
    """Check whether a horizontal bridge can be used for rule abstraction.

    Scheme: rule-describable-bridge? (rules.ss:528-541).
    """
    from server.engine.groups import Group
    from server.engine.workspace_objects import Letter

    o1, o2 = bridge.object1, bridge.object2
    is_letter1 = isinstance(o1, Letter)
    is_letter2 = isinstance(o2, Letter)
    is_group1 = isinstance(o1, Group)
    is_group2 = isinstance(o2, Group)

    # letter->letter: always ok
    if is_letter1 and is_letter2:
        return True

    # letter->group: only if group is a letter-category sameness group
    if is_letter1 and is_group2:
        bf = getattr(o2, "bond_facet", None)
        gc = getattr(o2, "group_category", None)
        bf_name = getattr(bf, "name", "")
        gc_name = getattr(gc, "name", "")
        return bf_name == "plato-letter-category" and gc_name == "plato-samegrp"

    # group->letter: group must be based on letter-category
    if is_group1 and is_letter2:
        bf = getattr(o1, "bond_facet", None)
        return getattr(bf, "name", "") == "plato-letter-category"

    # group->group: must have same bond-facet and related group categories
    if is_group1 and is_group2:
        bf1 = getattr(o1, "bond_facet", None)
        bf2 = getattr(o2, "bond_facet", None)
        if bf1 is not bf2:
            return False
        gc1 = getattr(o1, "group_category", None)
        gc2 = getattr(o2, "group_category", None)
        if gc1 is None or gc2 is None:
            return False
        # Check if related (same node, or linked)
        if gc1 is gc2:
            return True
        label = get_label(gc1, gc2, _get_slipnet_from_object(o1))
        return label is not None

    return False


def _get_slipnet_from_object(obj: Any) -> Any:
    """Try to get the slipnet reference from a workspace object's string."""
    string = getattr(obj, "string", None)
    if string is not None:
        # WorkspaceString doesn't store slipnet; walk up to workspace if possible
        # Fallback: use images.py helpers (they need slipnet as explicit arg)
        pass
    return None


# ============================================================================
#  Rule Abstraction — the full pipeline
# ============================================================================


def abstract_change_descriptions(
    bridges: list[Bridge],
    rng: RNG | None = None,
) -> list[IntrinsicChangeDescription | ExtrinsicChangeDescription]:
    """Extract change descriptions from a list of horizontal bridges.

    Scheme: abstract-change-descriptions (rules.ss:544-641).

    This is the main entry point for the rule abstraction pipeline.  Given
    a set of describable horizontal bridges, it produces change descriptions
    (both intrinsic and extrinsic) that characterise the transformation.

    Parameters
    ----------
    bridges : list[Bridge]
        Horizontal bridges (already filtered by rule_describable_bridge).
    rng : RNG | None
        Random number generator for probabilistic swap abstraction.

    Returns
    -------
    list
        Combined intrinsic and extrinsic change descriptions.
    """
    all_cds: list[IntrinsicChangeDescription | ExtrinsicChangeDescription] = []

    swap_prob = 0.75
    subobjects_prob = 0.75

    # 1. Intrinsic change descriptions from individual bridge slippages
    for b in bridges:
        slippages = _get_non_symmetric_non_bond_slippages(b)
        for slip in slippages:
            dim = slip.description_type1
            dim_name = getattr(dim, "name", "")
            # Disallow individual StrPosCtgy changes
            if dim_name == "plato-string-position-category":
                continue
            icd = IntrinsicChangeDescription(
                reference_object=b.object1,
                scope=SCOPE_SELF,
                dimension=dim,
                descriptor1=slip.descriptor1,
                relation=slip.label,
                descriptor2=slip.descriptor2,
            )
            all_cds.append(icd)

    # 2. Extrinsic (swap) change descriptions
    if bridges:
        swap_partition = _bounded_random_partition(
            _disjoint_left_objects_pred, bridges,
            rng=rng, max_clusters=len(bridges) + 1,
        )
        for cluster in swap_partition:
            all_swaps = _get_all_swaps(cluster)
            length_swap = _select_swap("plato-length", all_swaps)
            objctgy_swap = _select_swap("plato-object-category", all_swaps)
            remaining = [s for s in all_swaps if s is not length_swap and s is not objctgy_swap]

            # Add Length and ObjCtgy swaps together or not at all
            should_add = (rng is None) or (rng is not None and rng.prob(swap_prob))
            if should_add:
                abstract_subs = (rng is None) or (rng is not None and rng.prob(subobjects_prob))
                if length_swap is not None:
                    ecd = ExtrinsicChangeDescription(
                        length_swap[0], length_swap[1], length_swap[2]
                    )
                    if abstract_subs:
                        ecd.mark_as_subobjects_swap_if_possible()
                    all_cds.append(ecd)
                if objctgy_swap is not None:
                    ecd = ExtrinsicChangeDescription(
                        objctgy_swap[0], objctgy_swap[1], objctgy_swap[2]
                    )
                    if abstract_subs:
                        ecd.mark_as_subobjects_swap_if_possible()
                    all_cds.append(ecd)

            for swap in remaining:
                should_add_remaining = (rng is None) or (rng is not None and rng.prob(swap_prob))
                if should_add_remaining:
                    ecd = ExtrinsicChangeDescription(swap[0], swap[1], swap[2])
                    abstract_subs = (rng is None) or (rng is not None and rng.prob(subobjects_prob))
                    if abstract_subs:
                        ecd.mark_as_subobjects_swap_if_possible()
                    all_cds.append(ecd)

    # 3. Subobject-level abstractions (common schemas across bridge clusters)
    subobjects_partition = _partition_by(
        lambda b1, b2: _same_left_enclosing_objects(b1, b2), bridges
    )
    for cluster in subobjects_partition:
        left_enclosing = _get_left_enclosing_object(cluster)
        if left_enclosing is None:
            continue
        # Skip singleton groups
        if hasattr(left_enclosing, "objects") and len(getattr(left_enclosing, "objects", [])) <= 1:
            continue
        # StrPosCtgy:Opposite => direction reversal abstraction
        if (_spans_left_side(cluster)
                and _count_strposctgy_opposite_slippages(cluster) == 2):
            should_add = (rng is None) or (rng is not None and rng.prob(subobjects_prob))
            if should_add:
                # Find direction-category and opposite nodes
                dir_dim = _find_slipnet_node_in_bridges(cluster, "plato-direction-category")
                opp_rel = _find_slipnet_node_in_bridges(cluster, "plato-opposite")
                if dir_dim is not None and opp_rel is not None:
                    all_cds.append(IntrinsicChangeDescription(
                        left_enclosing, SCOPE_SELF, dir_dim, None, opp_rel, None
                    ))

        # Common change schemas across all bridges in cluster
        common_schemas = _get_common_change_schemas(cluster)
        for schema in common_schemas:
            s_dim, s_desc1, s_rel, s_desc2 = schema
            should_add = (rng is None) or (rng is not None and rng.prob(subobjects_prob))
            if should_add:
                all_cds.append(IntrinsicChangeDescription(
                    left_enclosing, SCOPE_SUBOBJECTS,
                    s_dim, s_desc1, s_rel, s_desc2,
                ))

    return all_cds


def remove_redundant_change_descriptions(
    cds: list[IntrinsicChangeDescription | ExtrinsicChangeDescription],
) -> list[IntrinsicChangeDescription | ExtrinsicChangeDescription]:
    """Remove change descriptions that are implied by others.

    Scheme: remove-redundant-change-descriptions (rules.ss:1067-1073).
    """
    to_remove: set[int] = set()  # indices

    # Pairwise implication
    for i in range(len(cds)):
        for j in range(i + 1, len(cds)):
            if id(i) in to_remove and id(j) in to_remove:
                continue
            if cds[i].implies(cds[j]):
                to_remove.add(j)
            elif cds[j].implies(cds[i]):
                to_remove.add(i)

    # StrPosCtgy swap implications
    str_pos_cds = [
        cd for cd in cds
        if not cd.is_intrinsic and getattr(cd, "dimension", None) is not None
        and getattr(cd.dimension, "name", "") == "plato-string-position-category"
    ]
    intrinsic_cds = [cd for cd in cds if cd.is_intrinsic]
    other_extrinsic = [
        cd for cd in cds
        if not cd.is_intrinsic and cd not in str_pos_cds
    ]
    for sp_cd in str_pos_cds:
        # Other extrinsic CDs with same reference objects are redundant
        for oe in other_extrinsic:
            if hasattr(sp_cd, "same_reference_objects") and sp_cd.same_reference_objects(oe):
                idx = cds.index(oe) if oe in cds else -1
                if idx >= 0:
                    to_remove.add(idx)
        # Symmetric intrinsic changes are redundant
        for i, ic1 in enumerate(intrinsic_cds):
            if not ic1.is_intrinsic:
                continue
            if not (hasattr(sp_cd, "common_reference_object")
                    and sp_cd.common_reference_object(ic1)):
                continue
            for j, ic2 in enumerate(intrinsic_cds):
                if i >= j or not ic2.is_intrinsic:
                    continue
                if not (hasattr(sp_cd, "common_reference_object")
                        and sp_cd.common_reference_object(ic2)):
                    continue
                if (ic1.same_dimension(ic2)
                        and ic1.descriptor1 is ic2.descriptor2
                        and ic1.descriptor2 is ic2.descriptor1):
                    idx1 = cds.index(ic1) if ic1 in cds else -1
                    idx2 = cds.index(ic2) if ic2 in cds else -1
                    if idx1 >= 0:
                        to_remove.add(idx1)
                    if idx2 >= 0:
                        to_remove.add(idx2)

    return [cd for i, cd in enumerate(cds) if i not in to_remove]


# ============================================================================
#  Change Descriptions -> Rule Clause Templates
# ============================================================================


def change_descriptions_to_rule_clause_template(
    change_descriptions: list[IntrinsicChangeDescription | ExtrinsicChangeDescription],
) -> tuple:
    """Convert a group of change descriptions into a rule-clause-template.

    Scheme: change-descriptions->rule-clause-template (rules.ss:793-809).
    """
    first = change_descriptions[0]
    if first.is_intrinsic:
        ref_obj = first.reference_object
        bf_change = first.get_bond_facet_change()
        templates = [cd.make_change_template() for cd in change_descriptions]
        if bf_change is not None:
            templates = [bf_change] + templates
        return (CLAUSE_INTRINSIC, ref_obj, templates)
    else:
        # Extrinsic
        if any(getattr(cd, "subobjects_swap", False) for cd in change_descriptions):
            ref_objects = [first.get_enclosing_object()]
        else:
            ref_objects = sorted(
                first.reference_objects,
                key=lambda o: getattr(o, "left_string_pos", 0),
            )
        dimensions = [cd.dimension for cd in change_descriptions]
        return (CLAUSE_EXTRINSIC, ref_objects, dimensions)


def sort_templates(templates: list[tuple]) -> list[tuple]:
    """Sort rule-clause-templates: intrinsic before extrinsic, by position.

    Scheme: sort-templates (rules.ss:814-826).
    """
    def key(t: tuple) -> tuple:
        is_intrinsic = (t[0] == CLAUSE_INTRINSIC)
        if is_intrinsic:
            pos = getattr(t[1], "left_string_pos", 0)
            level = _nesting_level(t[1])
            return (0, level, pos)
        else:
            # Extrinsic: sort by number of dimensions (more = first)
            return (1, -len(t[2]) if len(t) > 2 else 0, 0)
    return sorted(templates, key=key)


# ============================================================================
#  Reference Object -> Object Description
# ============================================================================


def reference_object_to_object_description(
    ref_object: Any,
    slipnet: Slipnet | None = None,
) -> tuple:
    """Convert a reference object into a rule object-description.

    Scheme: reference-object->object-description (rules.ss:878-886).

    Returns a tuple of (object_type, description_type, descriptor).
    For a string: ('string', plato-string-position-category, plato-whole).
    For an object: (obj_category_descriptor, chosen_desc_type, chosen_descriptor).
    """
    if _is_workspace_string(ref_object):
        # Need plato-string-position-category and plato-whole nodes
        if slipnet is not None:
            str_pos = slipnet.nodes.get("plato-string-position-category")
            whole = slipnet.nodes.get("plato-whole")
            return ("string", str_pos, whole)
        return ("string", None, None)

    # Get object category descriptor
    obj_ctgy = None
    if slipnet is not None:
        obj_ctgy_node = slipnet.nodes.get("plato-object-category")
        if obj_ctgy_node is not None:
            obj_ctgy = _get_descriptor_for(ref_object, obj_ctgy_node)

    # Choose description for rule
    chosen_desc = _choose_description_for_rule(ref_object)
    if chosen_desc is not None:
        return (obj_ctgy, chosen_desc.description_type, chosen_desc.descriptor)

    # Fallback: use first relevant distinguishing description
    for d in getattr(ref_object, "descriptions", []):
        if d.is_relevant() and d.is_distinguishing():
            return (obj_ctgy, d.description_type, d.descriptor)

    # Last resort
    if ref_object.descriptions:
        d = ref_object.descriptions[0]
        return (obj_ctgy, d.description_type, d.descriptor)

    return (obj_ctgy, None, None)


def _choose_description_for_rule(obj: Any) -> Any:
    """Choose the best description for a rule.

    Prefers relevant distinguishing descriptions with highest conceptual depth.
    """
    candidates = []
    for d in getattr(obj, "descriptions", []):
        dt_name = getattr(d.description_type, "name", "")
        # Skip object-category descriptions
        if dt_name == "plato-object-category":
            continue
        if d.is_relevant() and d.is_distinguishing():
            candidates.append(d)
    if not candidates:
        # Fall back to any relevant description
        candidates = [
            d for d in getattr(obj, "descriptions", [])
            if d.is_relevant()
            and getattr(d.description_type, "name", "") != "plato-object-category"
        ]
    if not candidates:
        return None
    # Pick the one with highest conceptual depth
    return max(candidates, key=lambda d: getattr(d.descriptor, "conceptual_depth", 0))


# ============================================================================
#  Instantiate Rule Clause Templates
# ============================================================================


def instantiate_rule_clause_template(
    template: tuple,
    slipnet: Slipnet | None = None,
    rng: RNG | None = None,
    temperature: float = 50.0,
) -> RuleClause:
    """Instantiate a rule-clause-template into a RuleClause.

    Scheme: instantiate-rule-clause-template (rules.ss:862-875).
    """
    clause_type = template[0]
    if clause_type == CLAUSE_INTRINSIC:
        ref_object = template[1]
        change_templates = template[2]
        obj_desc = reference_object_to_object_description(ref_object, slipnet)
        sorted_cts = _sort_change_templates(change_templates)
        changes = [
            _instantiate_change_template(ct, obj_desc, slipnet, rng, temperature)
            for ct in sorted_cts
        ]
        return RuleClause(
            clause_type=CLAUSE_INTRINSIC,
            object_description=obj_desc,
            changes=changes,
        )
    else:
        # Extrinsic
        ref_objects = template[1]
        dimensions = template[2]
        sorted_refs = sorted(ref_objects, key=lambda o: getattr(o, "left_string_pos", 0))
        obj_descs = [reference_object_to_object_description(r, slipnet) for r in sorted_refs]
        sorted_dims = sorted(dimensions, key=_dim_sort_key)
        return RuleClause(
            clause_type=CLAUSE_EXTRINSIC,
            object_description=obj_descs[0] if len(obj_descs) == 1 else None,
            extrinsic_objects=obj_descs if len(obj_descs) > 1 else None,
            changes=[],  # Extrinsic clauses don't have changes in this form
        )


def _instantiate_change_template(
    ct: tuple,
    obj_desc: tuple,
    slipnet: Slipnet | None,
    rng: RNG | None,
    temperature: float,
) -> RuleChange:
    """Instantiate a single change template into a RuleChange.

    Scheme: instantiate-change-template (rules.ss:889-909).

    ct = (scope, dimension, [possible_descriptors])
    """
    scope, dimension, possible_descriptors = ct

    if not possible_descriptors:
        return RuleChange(dimension=dimension)

    # Choose descriptor (by conceptual depth, temperature-weighted)
    if len(possible_descriptors) == 1 or rng is None:
        chosen = possible_descriptors[0]
    else:
        depths = [getattr(d, "conceptual_depth", 50) for d in possible_descriptors]
        # Temperature-adjusted pick
        from server.engine.formulas import temp_adjusted_values as _tav
        from server.engine.metadata import MetadataProvider
        # Simple approximation: use depth as weight
        weights = [max(1, d) for d in depths]
        chosen = rng.weighted_pick(possible_descriptors, weights)

    # If dimension == object_description's desc_type and chosen is a relation,
    # substitute the literal descriptor for the relation.
    if (len(obj_desc) >= 3
            and obj_desc[1] is dimension
            and is_platonic_relation(chosen)):
        base_desc = obj_desc[2]
        if base_desc is not None and slipnet is not None:
            literal = get_related_node(base_desc, chosen, slipnet)
            if literal is not None:
                chosen = literal

    # Determine if this is a relation or a literal descriptor
    if is_platonic_relation(chosen):
        return RuleChange(dimension=dimension, relation=chosen)
    else:
        return RuleChange(dimension=dimension, to_descriptor=chosen)


def _sort_change_templates(change_templates: list[tuple]) -> list[tuple]:
    """Sort change templates by scope + dimension.

    Scheme: sort-change-templates (rules.ss:924-931).
    self < subobjects; within same scope, sort by dimension order.
    """
    def key(ct: tuple) -> tuple:
        scope_key = 0 if ct[0] == SCOPE_SELF else 1
        dim_key = _dim_sort_key(ct[1])
        return (scope_key, dim_key)
    return sorted(change_templates, key=key)


# ============================================================================
#  Supporting Bridges
# ============================================================================


def get_tagged_supporting_horizontal_bridges(template: tuple) -> tuple:
    """Get tagged supporting bridges for a rule-clause-template.

    Scheme: get-tagged-supporting-horizontal-bridges (rules.ss:306-332).
    Returns (unsupported_self_change?, [bridges]).
    """
    clause_type = template[0]
    if clause_type == CLAUSE_EXTRINSIC:
        ref_objects = template[1]
        if len(ref_objects) == 1:
            bridges = _get_subobject_bridges(ref_objects[0], "horizontal")
        else:
            bridges = [_get_bridge(obj, "horizontal") for obj in ref_objects]
            bridges = [b for b in bridges if b is not None]
        return (False, bridges)
    else:
        # Intrinsic
        ref_object = template[1]
        change_templates = template[2]

        self_bridge = None
        if not _is_workspace_string(ref_object):
            self_bridge = _get_bridge(ref_object, "horizontal")

        has_subobject_changes = any(ct[0] == SCOPE_SUBOBJECTS for ct in change_templates)
        subobject_bridges = (
            _get_subobject_bridges(ref_object, "horizontal")
            if has_subobject_changes else []
        )

        has_self_changes = any(ct[0] == SCOPE_SELF for ct in change_templates)

        if has_self_changes:
            if self_bridge is not None:
                supporting = [self_bridge] + subobject_bridges
                return (False, supporting)
            else:
                # Unsupported self change — use subobject bridges instead
                return (True, _get_subobject_bridges(ref_object, "horizontal"))
        else:
            return (False, subobject_bridges)


def _get_bridge(obj: Any, orientation: str) -> Any:
    """Get the bridge of the given orientation on an object."""
    if orientation == "horizontal":
        return getattr(obj, "horizontal_bridge", None)
    return getattr(obj, "vertical_bridge", None)


def _get_subobject_bridges(obj: Any, orientation: str) -> list:
    """Get bridges from all sub-objects of an object."""
    sub_objects = _get_constituent_objects(obj)
    bridges = []
    for sub in sub_objects:
        b = _get_bridge(sub, orientation)
        if b is not None:
            bridges.append(b)
    return bridges


# ============================================================================
#  Rule Application — the full pipeline
# ============================================================================


def apply_rule(
    rule: Rule,
    string: WorkspaceString,
    slipnet: Slipnet,
    failure_action: Any = None,
) -> list[tuple] | None:
    """Apply a rule to a target string via the image system.

    Scheme: apply-rule (rules.ss:1260-1318).

    Returns a list of (object, [transforms]) pairs representing which
    objects were transformed and how, or None if application fails.

    For a verbatim rule, sets the string image's new appearance.
    For other rules, computes extrinsic and intrinsic transforms, checks
    for conflicts, then applies them to the string's images.
    """
    if rule.is_verbatim_rule:
        str_img = _get_or_make_string_image(string, slipnet)
        str_img.new_appearance(rule.get_verbatim_letter_categories())
        return []

    # Reset the string image
    str_img = _get_or_make_string_image(string, slipnet)
    str_img.reset()

    try:
        # Get extrinsic transforms
        extrinsic_transforms = _get_extrinsic_transforms(rule, string, slipnet)

        # Separate StrPosCtgy swaps from other extrinsic transforms
        string_position_swaps = [
            t for t in extrinsic_transforms
            if len(t) == 3 and getattr(t[0], "name", "") == "plato-string-position-category"
        ]
        extrinsic_object_transforms = [
            t for t in extrinsic_transforms if t not in string_position_swaps
        ]

        # Get intrinsic transforms
        intrinsic_transforms = _get_intrinsic_transforms(rule, string, slipnet)

        # Combine all transforms
        all_transforms = extrinsic_object_transforms + intrinsic_transforms

        # Check for conflicts
        _check_for_conflicts(all_transforms)

        # Group transforms by object, sorted deepest-first
        grouped = _group_transforms_by_object(all_transforms)

        # Apply transforms to each object's image (inside-out order)
        for obj, transforms in grouped:
            img = _get_object_image(obj, slipnet)
            if img is not None:
                _apply_transforms(transforms, img, slipnet)

        # Apply string-position swaps
        for swap in string_position_swaps:
            _apply_string_position_swap(swap[1], swap[2])

        return grouped

    except ImageFailure as e:
        if failure_action is not None:
            failure_action(str(e))
        return None
    except Exception:
        return None


def _get_or_make_string_image(string: WorkspaceString, slipnet: Slipnet) -> StringImage:
    """Get or create a StringImage for a workspace string."""
    existing = getattr(string, "image", None)
    if existing is not None:
        return existing
    plato_right = slipnet.nodes.get("plato-right")
    img = make_string_image(string, plato_right, slipnet)
    string.image = img  # type: ignore[attr-defined]
    return img


def _get_object_image(obj: Any, slipnet: Slipnet) -> Any:
    """Get the image for a workspace object."""
    img = getattr(obj, "image", None)
    if img is not None:
        return img
    # For letters, create a letter image
    from server.engine.workspace_objects import Letter
    from server.engine.images import make_letter_image
    if isinstance(obj, Letter):
        lc = getattr(obj, "letter_category", None)
        if lc is not None:
            img = make_letter_image(lc, slipnet)
            obj.image = img  # type: ignore[attr-defined]
            return img
    return None


def _get_extrinsic_transforms(
    rule: Rule, string: WorkspaceString, slipnet: Slipnet,
) -> list[tuple]:
    """Compute extrinsic transforms from the rule's extrinsic clauses.

    Scheme: get-extrinsic-transforms (rules.ss:1419-1480).

    Returns list of (object, (dimension, descriptor)) pairs, plus
    StrPosCtgy swap triples.
    """
    result: list[tuple] = []
    for clause in rule.extrinsic_clauses:
        ref_objects = _get_reference_objects_for_clause(clause, string, slipnet)
        if not ref_objects:
            continue

        # Determine denoted objects
        obj_descs = clause.extrinsic_objects or ([clause.object_description] if clause.object_description else [])
        if len(obj_descs) == 1:
            # Denoted objects = subobjects of the single reference object
            denoted = []
            for r in ref_objects:
                denoted.extend(_get_constituent_objects(r))
        else:
            denoted = ref_objects

        # Get dimensions from extrinsic clause
        # For extrinsic clauses, changes encode the dimensions
        dimensions: list[SlipnetNode] = []
        if clause.changes:
            for ch in clause.changes:
                if ch.dimension is not None:
                    dimensions.append(ch.dimension)

        if len(denoted) < 2:
            continue

        for dim in dimensions:
            dim_name = getattr(dim, "name", "")
            if dim_name == "plato-string-position-category":
                if len(denoted) == 2:
                    result.append((dim, denoted[0], denoted[1]))
                    # Also add StrPosCtgy transforms for each object
                    d1 = _get_descriptor_for(denoted[1], dim)
                    d2 = _get_descriptor_for(denoted[0], dim)
                    if d1 is not None:
                        result.append((denoted[0], (dim, d1)))
                    if d2 is not None:
                        result.append((denoted[1], (dim, d2)))
            else:
                # Regular dimension swap
                descs = [_get_descriptor_for(o, dim) for o in denoted]
                unique_descs = list(set(d for d in descs if d is not None))
                if len(unique_descs) == 2:
                    sd1, sd2 = unique_descs[0], unique_descs[1]
                    for obj, desc in zip(denoted, descs):
                        if desc is sd1:
                            result.append((obj, (dim, sd2)))
                        else:
                            result.append((obj, (dim, sd1)))
                elif len(unique_descs) == 1:
                    # All same descriptor — no swap needed
                    pass

    return result


def _get_intrinsic_transforms(
    rule: Rule, string: WorkspaceString, slipnet: Slipnet,
) -> list[tuple]:
    """Compute intrinsic transforms from the rule's intrinsic clauses.

    Scheme: get-intrinsic-transforms (rules.ss:1520-1538).
    Returns list of (object, (dimension, descriptor)) pairs.
    """
    result: list[tuple] = []
    for clause in rule.intrinsic_clauses:
        ref_objects = _get_reference_objects_for_clause(clause, string, slipnet)
        if not ref_objects:
            continue

        # Separate self vs subobject changes
        self_transforms: list[tuple] = []
        subobject_transforms: list[tuple] = []
        for change in clause.changes:
            dim = change.dimension
            desc = change.relation if change.relation else change.to_descriptor
            if desc is None:
                continue
            transform = (dim, desc)
            # Determine scope from the change
            # In the current RuleChange model, scope is implicit from
            # whether the change was from a self or subobjects template.
            # We encode it through the from_descriptor field as a convention.
            # For now, treat all changes as self transforms.
            self_transforms.append(transform)

        # Cross-product: each ref object gets each self transform
        for r in ref_objects:
            for t in self_transforms:
                result.append((r, t))

        # If there are subobject transforms, apply them to subobjects
        if subobject_transforms:
            for r in ref_objects:
                subs = _get_constituent_objects(r)
                for s in subs:
                    for t in subobject_transforms:
                        result.append((s, t))

    return result


def _get_reference_objects_for_clause(
    clause: RuleClause,
    string: WorkspaceString,
    slipnet: Slipnet,
) -> list[Any]:
    """Find the workspace objects in *string* that match a clause's object description.

    Scheme: get-reference-objects (workspace-strings.ss).
    """
    if clause.is_extrinsic and clause.extrinsic_objects:
        # Multiple object descriptions
        result = []
        for od in clause.extrinsic_objects:
            result.extend(_find_matching_objects(od, string, slipnet))
        return result

    od = clause.object_description
    if od is None:
        return []
    return _find_matching_objects(od, string, slipnet)


def _find_matching_objects(
    od: tuple, string: WorkspaceString, slipnet: Slipnet,
) -> list[Any]:
    """Find objects in *string* matching an object-description tuple.

    An object-description is (object_type, description_type, descriptor).
    """
    if not od or len(od) < 3:
        return []
    obj_type, desc_type, descriptor = od[0], od[1], od[2]

    # "string" or "whole" means the whole string
    if obj_type == "string" or (descriptor is not None
            and getattr(descriptor, "name", "") == "plato-whole"):
        return [string]

    result = []
    from server.engine.groups import Group
    from server.engine.workspace_objects import Letter

    for obj in string.objects:
        # Check object type match
        if obj_type is not None:
            obj_type_name = getattr(obj_type, "name", "")
            if obj_type_name == "plato-letter" and not isinstance(obj, Letter):
                continue
            if obj_type_name == "plato-group" and not isinstance(obj, Group):
                continue

        # Check description match
        if desc_type is not None and descriptor is not None:
            obj_desc = _get_descriptor_for(obj, desc_type)
            if obj_desc is descriptor:
                result.append(obj)

    return result


def _check_for_conflicts(transforms: list[tuple]) -> None:
    """Check for conflicting transforms on the same or related objects.

    Scheme: check-for-conflicts (rules.ss:1321-1338).
    Raises ImageFailure if conflicts found.
    """
    for i in range(len(transforms)):
        for j in range(i + 1, len(transforms)):
            t1 = transforms[i]
            t2 = transforms[j]
            if len(t1) != 2 or len(t2) != 2:
                continue
            obj1, (dim1, _) = t1
            obj2, (dim2, _) = t2
            # Same object, same dimension = conflict
            if obj1 is obj2 and dim1 is dim2:
                raise ImageFailure(
                    f"Conflicting transforms on same object for dimension "
                    f"{getattr(dim1, 'short_name', '?')}"
                )


def _group_transforms_by_object(
    transforms: list[tuple],
) -> list[tuple]:
    """Group transforms by object, sorted deepest-first.

    Scheme: rules.ss:1291-1298.
    Returns list of (object, [(dim, desc), ...]).
    """
    from collections import OrderedDict
    groups: dict[int, tuple] = OrderedDict()
    for t in transforms:
        if len(t) != 2:
            continue
        obj, transform = t
        oid = id(obj)
        if oid not in groups:
            groups[oid] = (obj, [])
        groups[oid][1].append(transform)

    result = list(groups.values())
    # Sort deepest-first
    result.sort(key=lambda x: -_nesting_level(x[0]))
    return result


def _apply_transforms(
    transforms: list[tuple], image: Any, slipnet: Slipnet,
) -> None:
    """Apply a list of transforms to an image.

    Scheme: apply-transforms (rules.ss:1341-1350).
    """
    # Sort transforms by application order
    ordered = sorted(transforms, key=lambda t: _apply_before_key(t, image, slipnet))

    for transform in ordered:
        dim, desc = transform
        _transform_image(image, dim, desc, slipnet, transforms)


def _apply_before_key(
    transform: tuple, image: Any, slipnet: Slipnet,
) -> tuple:
    """Sort key for transform application order.

    Scheme: apply-before? (rules.ss:1391-1399).
    GroupCtgy first, then ObjCtgy:letter, then length (if length-first),
    then everything else.
    """
    dim, desc = transform
    dim_name = getattr(dim, "name", "")
    desc_name = getattr(desc, "name", "")

    if dim_name == "plato-group-category":
        return (0,)
    if desc_name == "plato-letter":
        return (1,)
    if dim_name == "plato-length":
        img_length = getattr(image, "get_length", lambda: None)()
        if change_length_first(desc, img_length, slipnet):
            return (2,)
        return (8,)
    return (5,)


def _transform_image(
    image: Any,
    dimension: SlipnetNode,
    descriptor: SlipnetNode,
    slipnet: Slipnet,
    all_transforms: list[tuple] | None = None,
) -> None:
    """Apply a single transform to an image.

    Scheme: transform-image (rules.ss:1366-1388).
    """
    dim_name = getattr(dimension, "name", "")

    if dim_name == "plato-object-category":
        if getattr(descriptor, "name", "") == "plato-letter":
            image.letter()
        else:
            image.group()

    elif dim_name == "plato-letter-category":
        image.new_start_letter(descriptor)

    elif dim_name == "plato-length":
        image.new_length(descriptor)

    elif dim_name == "plato-direction-category":
        image.reverse_direction()

    elif dim_name == "plato-group-category":
        # GroupCtgy transforms need the bond-facet from a BondFacet "transform"
        medium = None
        if all_transforms:
            for t in all_transforms:
                td, td_desc = t
                if getattr(td, "name", "") == "plato-bond-facet":
                    medium = td_desc
                    break
        if medium is not None:
            image.reverse_medium(medium)

    elif dim_name == "plato-alphabetic-position-category":
        image.new_alpha_position_category(descriptor)

    elif dim_name == "plato-bond-facet":
        pass  # BondFacet "transforms" have no direct effect

    elif dim_name == "plato-string-position-category":
        pass  # StrPosCtgy swaps handled separately


def _apply_string_position_swap(obj1: Any, obj2: Any) -> None:
    """Swap the images of two objects.

    Scheme: apply-string-position-swap (rules.ss:1402-1411).
    """
    img1 = getattr(obj1, "image", None)
    img2 = getattr(obj2, "image", None)
    if img1 is None or img2 is None:
        return
    state1 = img1.get_state()
    state2 = img2.get_state()
    img1.set_state(state2)
    img2.set_state(state1)
    img1.swapped_image = img2
    img2.swapped_image = img1


# ============================================================================
#  Generate Image Letters / Get Letter Categories
# ============================================================================


def _generate_image_letters(string: WorkspaceString, slipnet: Slipnet) -> list[SlipnetNode]:
    """Generate the letter-category list from a string's image.

    Scheme: generate-image-letters.
    """
    str_img = _get_or_make_string_image(string, slipnet)
    return str_img.generate()


def _get_letter_categories(string: WorkspaceString) -> list[SlipnetNode]:
    """Get the letter-category nodes for a string's actual letters.

    Scheme: get-letter-categories.
    """
    from server.engine.workspace_objects import Letter
    letters = sorted(
        [o for o in string.objects if isinstance(o, Letter)],
        key=lambda o: o.left_string_pos,
    )
    return [l.letter_category for l in letters]


# ============================================================================
#  Bridge / Workspace helpers
# ============================================================================


def _bridge_present(workspace: Workspace, bridge: Bridge) -> bool:
    """Check if a bridge (or an equivalent one) exists in the workspace."""
    all_bridges = (
        workspace.top_bridges + workspace.bottom_bridges + workspace.vertical_bridges
    )
    return any(b is bridge for b in all_bridges)


def _get_equivalent_bridge(workspace: Workspace, bridge: Bridge) -> Any:
    """Find an equivalent bridge in the workspace."""
    all_bridges = (
        workspace.top_bridges + workspace.bottom_bridges + workspace.vertical_bridges
    )
    for b in all_bridges:
        if b is bridge:
            return b
        if (b.object1 is bridge.object1 and b.object2 is bridge.object2
                and b.bridge_type == bridge.bridge_type):
            return b
    return None


# ============================================================================
#  Slippage / Schema / Swap helpers for abstraction
# ============================================================================


def _get_non_symmetric_non_bond_slippages(bridge: Bridge) -> list[ConceptMapping]:
    """Get non-identity, non-bond concept mappings from a bridge.

    Scheme: get-non-symmetric-non-bond-slippages.
    Returns slippages (non-identity CMs) that are not bond-category or bond-facet CMs.
    """
    result = []
    for cm in bridge.concept_mappings:
        if cm.is_identity:
            continue
        if cm.bond_concept_mapping:
            continue
        result.append(cm)
    return result


def _partition_by(pred: Any, items: list) -> list[list]:
    """Partition items into clusters where all pairs satisfy pred.

    Simple greedy clustering.
    """
    clusters: list[list] = []
    for item in items:
        placed = False
        for cluster in clusters:
            if all(pred(item, existing) for existing in cluster):
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])
    return clusters


def _bounded_random_partition(
    pred: Any,
    items: list,
    rng: RNG | None = None,
    max_clusters: int = 10,
) -> list[list]:
    """Bounded random partition.

    Scheme: bounded-random-partition (utilities.ss).
    """
    if not items:
        return []
    return _partition_by(pred, items)


def _disjoint_left_objects_pred(b1: Bridge, b2: Bridge) -> bool:
    """Two bridges have disjoint left (object1) objects."""
    return _disjoint_objects(b1.object1, b2.object1)


def _same_left_enclosing_objects(b1: Bridge, b2: Bridge) -> bool:
    """Two bridges have the same left enclosing object."""
    eg1 = _get_enclosing_object(b1.object1)
    eg2 = _get_enclosing_object(b2.object1)
    return eg1 is eg2


def _get_left_enclosing_object(bridges: list[Bridge]) -> Any:
    """Get the enclosing object of the first bridge's object1."""
    if not bridges:
        return None
    return _get_enclosing_object(bridges[0].object1)


def _spans_left_side(bridges: list[Bridge]) -> bool:
    """Check if bridges cover all constituent objects of their enclosing object."""
    enclosing = _get_left_enclosing_object(bridges)
    if enclosing is None:
        return False
    constituents = _get_constituent_objects(enclosing)
    bridge_objects = [b.object1 for b in bridges]
    return _sets_equal_by_id(bridge_objects, constituents)


def _count_strposctgy_opposite_slippages(bridges: list[Bridge]) -> int:
    """Count bridges that have a StrPosCtgy:Opposite slippage."""
    count = 0
    for b in bridges:
        for cm in b.concept_mappings:
            dt_name = getattr(cm.description_type1, "name", "")
            label_name = getattr(cm.label, "name", "") if cm.label else ""
            if dt_name == "plato-string-position-category" and label_name == "plato-opposite":
                count += 1
                break
    return count


def _find_slipnet_node_in_bridges(bridges: list[Bridge], node_name: str) -> SlipnetNode | None:
    """Find a slipnet node by name from any bridge's concept mappings."""
    for b in bridges:
        for cm in b.concept_mappings:
            for node in [cm.description_type1, cm.descriptor1,
                         cm.description_type2, cm.descriptor2, cm.label]:
                if node is not None and getattr(node, "name", "") == node_name:
                    return node
    return None


def _get_all_swaps(cluster: list[Bridge]) -> list[tuple]:
    """Get all swap descriptions from a cluster of bridges.

    Scheme: get-all-swaps (rules.ss:758-778).
    A swap is ([objects], dimension, [desc1, desc2]).
    """
    # Collect all non-symmetric non-bond slippages
    all_slippages = []
    for b in cluster:
        all_slippages.extend(
            [(s, b.object1) for s in _get_non_symmetric_non_bond_slippages(b)]
        )

    # Partition by CM type (dimension)
    dim_groups: dict[int, list[tuple]] = {}
    for slip, obj in all_slippages:
        did = id(slip.description_type1)
        if did not in dim_groups:
            dim_groups[did] = []
        dim_groups[did].append((slip, obj))

    swaps = []
    for group in dim_groups.values():
        from_descs = set()
        to_descs = set()
        objects = []
        dim = group[0][0].description_type1
        for slip, obj in group:
            from_descs.add(id(slip.descriptor1))
            to_descs.add(id(slip.descriptor2))
            objects.append(obj)
        # Swap exists when from_descriptors == to_descriptors and there are exactly 2
        if from_descs == to_descs and len(from_descs) == 2:
            desc_nodes = list(set(
                slip.descriptor1 for slip, _ in group
            ) | set(
                slip.descriptor2 for slip, _ in group
            ))
            if len(desc_nodes) == 2:
                swaps.append((objects, dim, desc_nodes))

    return swaps


def _select_swap(dim_name: str, swaps: list[tuple]) -> tuple | None:
    """Select a swap for a given dimension name."""
    for s in swaps:
        if getattr(s[1], "name", "") == dim_name:
            return s
    return None


def _get_common_change_schemas(cluster: list[Bridge]) -> list[tuple]:
    """Get common change schemas across all bridges in a cluster.

    Scheme: get-common-change-schemas (rules.ss:702-706).
    Returns schemas where the relation is not identity.
    """
    common = _get_common_schemas(cluster)
    identity_names = {"plato-identity"}
    return [
        s for s in common
        if s[2] is not None and getattr(s[2], "name", "") not in identity_names
    ]


def _get_common_schemas(cluster: list[Bridge]) -> list[tuple]:
    """Get common schemas across a cluster of bridges.

    Scheme: get-common-schemas (rules.ss:709-735).
    A schema is (dimension, desc1, relation, desc2).
    """
    num_bridges = len(cluster)
    if num_bridges == 0:
        return []

    # Collect all concept mappings from all bridges
    all_cms = []
    for b in cluster:
        all_cms.extend(b.concept_mappings)

    # Partition by CM type (dimension)
    dim_groups: dict[int, list] = {}
    for cm in all_cms:
        did = id(cm.description_type1)
        if did not in dim_groups:
            dim_groups[did] = []
        dim_groups[did].append(cm)

    schemas = []
    for group in dim_groups.values():
        if len(group) < num_bridges:
            continue
        schema = _concept_mappings_to_schema(group)
        if schema is not None:
            schemas.append(schema)

    return schemas


def _concept_mappings_to_schema(cms: list[ConceptMapping]) -> tuple | None:
    """Convert a list of concept mappings to a schema.

    Scheme: concept-mappings->schema (rules.ss:724-735).
    Returns (dimension, common_desc1, common_relation, common_desc2) or None.
    """
    if not cms:
        return None
    dim = cms[0].description_type1
    labels = [cm.label for cm in cms]
    desc1s = [cm.descriptor1 for cm in cms]
    desc2s = [cm.descriptor2 for cm in cms]

    common_rel = labels[0] if _all_same(labels) else None
    common_d1 = desc1s[0] if _all_same(desc1s) else None
    common_d2 = desc2s[0] if _all_same(desc2s) else None

    if common_rel is not None or common_d2 is not None:
        return (dim, common_d1, common_rel, common_d2)
    return None


def _all_same(items: list) -> bool:
    """True if all items are the same (by identity)."""
    if not items:
        return True
    first = items[0]
    return all(x is first for x in items)


# ============================================================================
#  Possible-to-Instantiate Check
# ============================================================================


def possible_to_instantiate(templates: list[tuple]) -> bool:
    """Check if all rule-clause templates can be instantiated.

    Scheme: possible-to-instantiate? (rules.ss:446-458).
    """
    for t in templates:
        if t[0] == CLAUSE_INTRINSIC:
            if not _object_description_possible(t[1]):
                return False
        elif t[0] == CLAUSE_EXTRINSIC:
            for obj in t[1]:
                if not _object_description_possible(obj):
                    return False
    return True


def _object_description_possible(obj: Any) -> bool:
    """Check if an object can be described for a rule.

    Scheme: object-description-possible? (rules.ss:456-458).
    """
    if _is_workspace_string(obj):
        return True
    descs = getattr(obj, "descriptions", [])
    return len(descs) > 0


# ============================================================================
#  Full Abstraction Pipeline (convenience function)
# ============================================================================


def build_rule_from_bridges(
    rule_type: str,
    bridges: list[Bridge],
    slipnet: Slipnet,
    rng: RNG | None = None,
    temperature: float = 50.0,
    themespace: Any = None,
    meta: MetadataProvider | None = None,
) -> Rule | None:
    """Full rule-abstraction pipeline: bridges -> change descriptions -> rule.

    This is the main entry point called by the rule-scout codelet.

    Parameters
    ----------
    rule_type : str
        RULE_TOP or RULE_BOTTOM.
    bridges : list[Bridge]
        Describable horizontal bridges.
    slipnet : Slipnet
        The slipnet for node lookups.
    rng : RNG | None
        Random number generator.
    temperature : float
        Current temperature.
    themespace : Any
        Themespace for theme pattern extraction.
    meta : MetadataProvider | None
        Metadata for quality computation.

    Returns
    -------
    Rule | None
        The constructed rule, or None if construction fails.
    """
    # Filter to describable bridges
    describable = [b for b in bridges if rule_describable_bridge(b)]
    if not describable:
        return None

    # 1. Abstract change descriptions from bridges
    all_cds = abstract_change_descriptions(describable, rng=rng)

    # 2. Remove redundant change descriptions
    final_cds = remove_redundant_change_descriptions(all_cds)
    if not final_cds:
        # Identity rule
        rule = Rule(rule_type, [])
        if meta:
            rule.compute_quality(meta)
        return rule

    # 3. Partition change descriptions by type and reference objects
    partitioned = _partition_change_descriptions(final_cds)

    # 4. Convert to rule clause templates
    templates = [
        change_descriptions_to_rule_clause_template(group)
        for group in partitioned
    ]
    templates = sort_templates(templates)

    # 5. Check instantiability
    if not possible_to_instantiate(templates):
        return None

    # 6. Instantiate templates to clauses
    clauses = [
        instantiate_rule_clause_template(t, slipnet, rng, temperature)
        for t in templates
    ]

    # 7. Build rule
    rule = Rule(rule_type, clauses)
    rule.set_abstracted_rule_information(templates, themespace)
    if meta:
        rule.compute_quality(meta)

    return rule


def _partition_change_descriptions(
    cds: list[IntrinsicChangeDescription | ExtrinsicChangeDescription],
) -> list[list]:
    """Partition change descriptions by type and reference objects.

    Groups intrinsic CDs with the same reference object, and extrinsic
    CDs with the same reference objects.
    """
    def same_group(c1: Any, c2: Any) -> bool:
        if c1.is_intrinsic != c2.is_intrinsic:
            return False
        return c1.same_change_type(c2) and c1.same_reference_objects(c2)

    return _partition_by(same_group, cds)
