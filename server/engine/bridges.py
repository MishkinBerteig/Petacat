"""Bridge structures — mappings between objects across strings.

Bridges carry concept-mappings that describe how descriptions correspond
(identity, slippage, coattail). Three bridge orientations: top (initial<->modified),
bottom (target<->answer), vertical (initial<->target, modified<->answer).

Scheme source: bridges.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.engine.workspace_structures import WorkspaceStructure

if TYPE_CHECKING:
    from server.engine.bonds import Bond
    from server.engine.concept_mappings import ConceptMapping
    from server.engine.slipnet import SlipnetNode
    from server.engine.workspace_objects import WorkspaceObject

# Bridge type string constants (values live in DB bridge_types table)
BRIDGE_TOP = "top"
BRIDGE_BOTTOM = "bottom"
BRIDGE_VERTICAL = "vertical"

# Bridge orientation string constants (values live in DB bridge_orientations table)
ORIENTATION_HORIZONTAL = "horizontal"
ORIENTATION_VERTICAL = "vertical"


class Bridge(WorkspaceStructure):
    """A mapping between objects in different strings."""

    def __init__(
        self,
        object1: WorkspaceObject,
        object2: WorkspaceObject,
        bridge_type: str,
        concept_mappings: list[ConceptMapping],
    ) -> None:
        super().__init__()
        self.object1 = object1
        self.object2 = object2
        self.bridge_type = bridge_type
        self.concept_mappings = concept_mappings
        self.spanning: bool = False
        self.group_spanning: bool = False

    @property
    def orientation(self) -> str:
        if self.bridge_type in (BRIDGE_TOP, BRIDGE_BOTTOM):
            return ORIENTATION_HORIZONTAL
        return ORIENTATION_VERTICAL

    @property
    def is_horizontal(self) -> bool:
        return self.orientation == ORIENTATION_HORIZONTAL

    @property
    def is_vertical(self) -> bool:
        return self.orientation == ORIENTATION_VERTICAL

    def get_relevant_concept_mappings(self) -> list[ConceptMapping]:
        """Return CMs where both description types are relevant (fully active).

        Scheme: bridges.ss:248 (horizontal), 652 (vertical).
        """
        return [cm for cm in self.concept_mappings if cm.relevant()]

    def get_distinguishing_concept_mappings(self) -> list[ConceptMapping]:
        """Return CMs where both descriptors are distinguishing.

        Scheme: bridges.ss:249-250 (horizontal), 653-654 (vertical).
        """
        return [cm for cm in self.concept_mappings if cm.distinguishing()]

    def distinguishing_concept_mappings(self) -> list[ConceptMapping]:
        """Alias for get_distinguishing_concept_mappings for backward compat."""
        return self.get_distinguishing_concept_mappings()

    def get_relevant_distinguishing_concept_mappings(self) -> list[ConceptMapping]:
        """CMs that are both relevant and distinguishing.

        Scheme: bridges.ss:251-252 (horizontal), 655-656 (vertical).
        """
        return [cm for cm in self.concept_mappings if cm.relevant_distinguishing()]

    def calculate_internal_strength(self) -> float:
        """Bridge internal strength from concept mappings.

        Scheme: bridges.ss:377-399 (horizontal), 775-793 (vertical).
        avg_cm_strength * num_cm_factor * coherence_factor [* singleton_factor]
        Uses relevant-distinguishing CMs; if none, returns 0.
        """
        rel_dist_cms = self.get_relevant_distinguishing_concept_mappings()
        if not rel_dist_cms:
            return 0.0

        avg_strength = sum(cm.strength() for cm in rel_dist_cms) / len(rel_dist_cms)

        # Number-of-CMs factor
        n = len(rel_dist_cms)
        if n == 1:
            num_factor = 0.8
        elif n == 2:
            num_factor = 1.2
        else:
            num_factor = 1.6

        # Internal coherence factor
        coherent = self._is_internally_coherent()
        coherence_factor = 2.5 if coherent else 1.0

        result = avg_strength * num_factor * coherence_factor

        # Singleton factor (horizontal only)
        if self.is_horizontal:
            result *= self._singleton_factor()

        return min(100.0, round(result))

    def _is_internally_coherent(self) -> bool:
        """Check if CMs support each other.

        Scheme: bridges.ss:362-370 (horizontal), 765-773 (vertical).
        True if any pair of relevant-distinguishing CMs are supporting.
        Supporting CMs: equal, or share related descriptors with same label.
        """
        rel_dist_cms = self.get_relevant_distinguishing_concept_mappings()
        for i, cm1 in enumerate(rel_dist_cms):
            for cm2 in rel_dist_cms[i + 1:]:
                if _supporting_cms(cm1, cm2):
                    return True
        return False

    def _singleton_factor(self) -> float:
        """Penalize bridges between mismatched object types involving singletons.

        Scheme: bridges.ss:808-815.
        """
        obj1_is_letter = not hasattr(self.object1, "objects")
        obj2_is_letter = not hasattr(self.object2, "objects")
        if obj1_is_letter == obj2_is_letter:
            return 1.0
        return 0.1

    def calculate_external_strength(self) -> float:
        """External strength from supporting bridges.

        Scheme: bridges.ss:400-410, 794-804.
        """
        # Check for spanning singleton letter
        if self._is_spanning_singleton():
            return 100.0
        # Sum of supporting bridge strengths, capped at 100
        support = self._get_supporting_bridge_strength()
        return min(100.0, round(support))

    def _is_spanning_singleton(self) -> bool:
        """Is this a bridge between singleton letters spanning whole strings?"""
        obj1_is_letter = not hasattr(self.object1, "objects")
        obj2_is_letter = not hasattr(self.object2, "objects")
        if not (obj1_is_letter and obj2_is_letter):
            return False
        s1 = self.object1.string
        s2 = self.object2.string
        if s1 is None or s2 is None:
            return False
        s1_len = len(getattr(s1, "objects", []))
        s2_len = len(getattr(s2, "objects", []))
        return s1_len == 1 and s2_len == 1

    def _get_supporting_bridge_strength(self) -> float:
        """Sum strength of supporting bridges in the same orientation.

        Scheme: bridges.ss:400-410 (horizontal), 794-804 (vertical).
        Supporting bridges are those in the same bridge_type that are not
        incompatible and share at least one supporting CM pair.
        """
        workspace = self._find_workspace()
        if workspace is None:
            return 0.0

        same_type_bridges = _get_bridges_of_type(workspace, self.bridge_type)
        total = 0.0
        for other in same_type_bridges:
            if other is self:
                continue
            if _supporting_bridges(self, other, self.orientation):
                total += other.strength
        return total

    def get_theme_pattern(self) -> dict[str, Any]:
        """Extract the theme pattern from this bridge's CMs.

        Used by Themespace to track dominant perceptual interpretations.
        """
        pattern: dict[str, Any] = {}
        for cm in self.concept_mappings:
            dim = getattr(cm.description_type1, "name", None)
            if dim and cm.label:
                rel = getattr(cm.label, "name", None)
                if rel:
                    pattern[dim] = rel
        return pattern

    def get_incompatible_bridges(self, workspace: Any = None) -> list[Bridge]:
        """Find bridges that conflict with this one.

        Scheme: bridges.ss:324-338 (horizontal), 728-741 (vertical).
        Incompatible bridges share an object with this bridge or have
        incompatible concept mappings.
        """
        ws = workspace or self._find_workspace()
        if ws is None:
            return []

        same_type_bridges = _get_bridges_of_type(ws, self.bridge_type)
        result: list[Bridge] = []
        for other in same_type_bridges:
            if other is self:
                continue
            if _incompatible_bridges(other, self, self.orientation):
                result.append(other)

        # Also check group-incompatible bridges
        result.extend(_group_incompatible_bridges(
            self.orientation, self.object1, self.object2
        ))

        # Remove duplicates
        seen: set[int] = set()
        unique: list[Bridge] = []
        for b in result:
            if id(b) not in seen:
                seen.add(id(b))
                unique.append(b)
        return unique

    def get_incompatible_bond(self) -> Any:
        """Find bonds incompatible with this bridge's CMs.

        Scheme: bridges.ss:339-361 (horizontal), 742-764 (vertical).
        Checks if bonds adjacent to both bridged objects have directions
        that create incompatible concept mappings with this bridge.
        """
        obj1 = self.object1
        obj2 = self.object2

        # Get the relevant bond from each object
        bond1 = _get_edge_bond(obj1)
        bond2 = _get_edge_bond(obj2)

        if bond1 is None or bond2 is None:
            return None

        # Both must be directed
        if not getattr(bond1, "directed", False) or not getattr(bond2, "directed", False):
            return None

        # Check if the direction CM is incompatible with this bridge's CMs
        dir1 = bond1.direction
        dir2 = bond2.direction
        if dir1 is None or dir2 is None:
            return None

        from server.engine.concept_mappings import ConceptMapping

        # Create a direction-category CM between the two bonds' directions
        # Look for a plato-direction-category node from the existing CMs
        dir_cat_node = None
        for cm in self.concept_mappings:
            if getattr(cm.description_type1, "name", "") == "plato-direction-category":
                dir_cat_node = cm.description_type1
                break

        if dir_cat_node is None:
            return None

        direction_cm = ConceptMapping(
            description_type1=dir_cat_node,
            descriptor1=dir1,
            description_type2=dir_cat_node,
            descriptor2=dir2,
            object1=bond1,
            object2=bond2,
        )

        # Check if this direction CM is incompatible with any of the bridge's CMs
        for cm in self.concept_mappings:
            if _incompatible_cms(direction_cm, cm):
                return bond2

        return None

    def supports_theme_pattern(self, pattern: dict[str, Any]) -> bool:
        """Check if bridge's theme pattern supports a given pattern.

        Scheme: bridges.ss:239-246 (horizontal), 643-650 (vertical).
        True if any entry in the pattern matches a CM's type and label,
        excluding whole/single CMs.
        """
        # Filter out whole/single CMs
        filtered_cms = [
            cm for cm in self.concept_mappings
            if not _is_whole_or_single_cm(cm)
        ]

        for dim, rel in pattern.items():
            for cm in filtered_cms:
                cm_type_name = getattr(cm.description_type1, "name", "")
                cm_label_name = getattr(cm.label, "name", "") if cm.label else ""
                if cm_type_name == dim and cm_label_name == rel:
                    return True
        return False

    def _find_workspace(self) -> Any:
        """Try to find the workspace from the bridged objects."""
        for obj in (self.object1, self.object2):
            string = getattr(obj, "string", None)
            if string is not None:
                ws = getattr(string, "workspace", None)
                if ws is not None:
                    return ws
        return None

    def add_concept_mapping(self, cm: ConceptMapping) -> None:
        """Add a new concept mapping to this bridge."""
        if cm not in self.concept_mappings:
            self.concept_mappings.append(cm)

    def __repr__(self) -> str:
        n_cms = len(self.concept_mappings)
        return (
            f"Bridge({self.bridge_type}, {self.object1}->{self.object2}, "
            f"{n_cms} CMs, strength={self.strength:.0f})"
        )


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------


def _supporting_cms(cm1: ConceptMapping, cm2: ConceptMapping) -> bool:
    """Two CMs support each other if they are equal or share related descriptors
    with the same label.

    Scheme: bridges.ss:1593-1600 (supporting-horizontal-CMs?), 1681-1688 (vertical).
    Both horizontal and vertical use the same logic.
    """
    # Equal CMs always support
    if cm1 == cm2:
        return True

    # Both must have labels
    if cm1.label is None or cm2.label is None:
        return False
    if cm1.label is not cm2.label:
        return False

    # Check related descriptors
    related1 = _nodes_related(cm1.descriptor1, cm2.descriptor1)
    related2 = _nodes_related(cm1.descriptor2, cm2.descriptor2)
    return related1 or related2


def _incompatible_cms(cm1: ConceptMapping, cm2: ConceptMapping) -> bool:
    """Two CMs are incompatible if they have related descriptors but different labels,
    and the label relationship differs between the descriptor pairs.

    Scheme: bridges.ss:1603-1615 (horizontal), 1691-1703 (vertical).
    """
    # Both must have labels
    if cm1.label is None or cm2.label is None:
        return False
    if cm1.label is cm2.label:
        return False

    # Check related descriptors
    related1 = _nodes_related(cm1.descriptor1, cm2.descriptor1)
    related2 = _nodes_related(cm1.descriptor2, cm2.descriptor2)
    if not (related1 or related2):
        return False

    # Check that the label relationship between the descriptor pairs differs
    # (i.e., get-label(cm1-desc1, cm2-desc1) != get-label(cm1-desc2, cm2-desc2))
    label_1 = _get_label(cm1.descriptor1, cm2.descriptor1)
    label_2 = _get_label(cm1.descriptor2, cm2.descriptor2)
    return label_1 is not label_2


def _nodes_related(node1: Any, node2: Any) -> bool:
    """Two nodes are related if they are the same or linked.

    Scheme: slipnet.ss:352-354.
    """
    if node1 is node2:
        return True
    # Check if linked via any outgoing link
    for link in getattr(node1, "outgoing_links", []):
        if link.to_node is node2:
            return True
    return False


def _get_label(node1: Any, node2: Any) -> Any:
    """Get the label (relationship) between two slipnet nodes.

    Returns the label node if the two nodes are linked, None otherwise.
    For identity (same node), returns the identity concept.
    """
    if node1 is node2:
        # Return a sentinel for identity
        return node1  # identity: same node
    for link in getattr(node1, "outgoing_links", []):
        if link.to_node is node2:
            return getattr(link, "label_node", None)
    return None


def _incompatible_bridges(b1: Bridge, b2: Bridge, orientation: str) -> bool:
    """Two bridges are incompatible if they share an object or have
    incompatible CM lists.

    Scheme: bridges.ss:1551-1585 (horizontal), 1641-1674 (vertical).
    """
    # Shared objects => incompatible
    if b1.object1 is b2.object1 or b1.object2 is b2.object2:
        return True

    # Check CM-level incompatibility
    b1_cms = b1.concept_mappings
    b2_cms = b2.concept_mappings

    for cm1 in b1_cms:
        for cm2 in b2_cms:
            if _incompatible_cms(cm1, cm2):
                return True
    return False


def _supporting_bridges(b1: Bridge, b2: Bridge, orientation: str) -> bool:
    """Two bridges support each other if not incompatible and have at least
    one pair of supporting distinguishing CMs.

    Scheme: bridges.ss:1542-1548 (horizontal), 1632-1638 (vertical).
    """
    if _incompatible_bridges(b1, b2, orientation):
        return False

    b1_dist_cms = b1.get_distinguishing_concept_mappings()
    b2_dist_cms = b2.get_distinguishing_concept_mappings()

    for cm1 in b1_dist_cms:
        for cm2 in b2_dist_cms:
            if _supporting_cms(cm1, cm2):
                return True
    return False


def _get_bridges_of_type(workspace: Any, bridge_type: str) -> list[Bridge]:
    """Get all bridges of a given type from the workspace."""
    # Try different workspace interfaces
    bridges = getattr(workspace, "bridges", {})
    if isinstance(bridges, dict):
        return bridges.get(bridge_type, [])
    # Fallback: iterate all bridges
    all_bridges = []
    for attr in ("top_bridges", "bottom_bridges", "vertical_bridges"):
        all_bridges.extend(getattr(workspace, attr, []))
    return [b for b in all_bridges if getattr(b, "bridge_type", "") == bridge_type]


def _group_incompatible_bridges(
    orientation: str, object1: Any, object2: Any
) -> list[Bridge]:
    """Find bridges on subobjects or enclosing groups that are incompatible.

    Scheme: bridges.ss:826-866 (group-incompatible-bridges).
    """
    result: list[Bridge] = []

    # Check subobject bridges for group objects
    for obj, other in ((object1, object2), (object2, object1)):
        if hasattr(obj, "objects"):  # It's a group
            bridge_attr = "horizontal_bridge" if orientation == "horizontal" else "vertical_bridge"
            for sub in getattr(obj, "objects", []):
                bridge = getattr(sub, bridge_attr, None)
                if bridge is not None:
                    # If other is a letter, all subobject bridges are incompatible
                    # If other is a group, only if the bridge's other object is not a
                    # top-level member of the other group
                    if not hasattr(other, "objects"):
                        result.append(bridge)
                    else:
                        other_obj = bridge.object2 if bridge.object1 is sub else bridge.object1
                        if other_obj not in getattr(other, "objects", []):
                            result.append(bridge)

    # Check enclosing group bridges
    for obj, other_obj in ((object1, object2), (object2, object1)):
        enc = getattr(obj, "enclosing_group", None)
        if enc is not None:
            bridge_attr = "horizontal_bridge" if orientation == "horizontal" else "vertical_bridge"
            group_bridge = getattr(enc, bridge_attr, None)
            if group_bridge is not None:
                # Incompatible if the other side's enclosing group doesn't match
                other_enc = getattr(other_obj, "enclosing_group", None)
                bridge_other = group_bridge.object2 if group_bridge.object1 is enc else group_bridge.object1
                if other_enc is None or other_enc is not bridge_other:
                    result.append(group_bridge)

    return result


def _get_edge_bond(obj: Any) -> Any:
    """Get the bond adjacent to this object at the edge of its string.

    Scheme: bridges.ss:340-345.
    If leftmost, get right bond; if rightmost (or default), get left bond.
    """
    if getattr(obj, "left_string_pos", -1) == 0:
        return getattr(obj, "right_bond", None)
    return getattr(obj, "left_bond", None)


def _is_whole_or_single_cm(cm: ConceptMapping) -> bool:
    """Check if a CM involves plato-whole or plato-single for string-position.

    Scheme: justify.ss:220-229 (remove-whole/single-concept-mappings).
    """
    dt_name = getattr(cm.description_type1, "name", "")
    if dt_name != "plato-string-position-category":
        return False
    d1_name = getattr(cm.descriptor1, "name", "")
    return d1_name in ("plato-whole", "plato-single")
