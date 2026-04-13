"""Group structures — collections of letters/subgroups with internal bonds.

A group is a structured collection of objects connected by bonds of the same
category, going in the same direction. Groups are both WorkspaceObjects
(they can participate in bridges) and WorkspaceStructures (they have strength).

Scheme source: groups.ss
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from server.engine.workspace_objects import WorkspaceObject
from server.engine.workspace_structures import WorkspaceStructure

if TYPE_CHECKING:
    from server.engine.bonds import Bond
    from server.engine.slipnet import SlipnetNode


class Group(WorkspaceObject, WorkspaceStructure):
    """A structured collection of workspace objects."""

    def __init__(
        self,
        string: Any,
        group_category: SlipnetNode,
        bond_facet: SlipnetNode,
        direction: SlipnetNode | None,
        objects: list[WorkspaceObject],
        bonds: list[Bond],
    ) -> None:
        # Compute span from objects
        left = min(o.left_string_pos for o in objects)
        right = max(o.right_string_pos for o in objects)
        WorkspaceObject.__init__(self, string, left, right)
        WorkspaceStructure.__init__(self)

        self.group_category = group_category
        self.bond_facet = bond_facet
        self.direction = direction
        self.objects = objects
        self.group_bonds = bonds
        self.bond_descriptions: list[Any] = []
        self.left_object = min(objects, key=lambda o: o.left_string_pos)
        self.right_object = max(objects, key=lambda o: o.right_string_pos)

    @property
    def length(self) -> int:
        return len(self.objects)

    def get_all_descriptions(self) -> list[Any]:
        """Return descriptions plus bond descriptions.

        Scheme: workspace-objects.ss:162-165 — groups include bond descriptions.
        """
        return list(self.descriptions) + list(self.bond_descriptions)

    def nested_member(self, obj: Any) -> bool:
        """True if *obj* is a direct or recursively nested member.

        Scheme: groups.ss:271-273.
        """
        if obj in self.objects:
            return True
        for sub in self.objects:
            if isinstance(sub, Group) and sub.nested_member(obj):
                return True
        return False

    def spans_whole_string(self) -> bool:
        """Does this group cover the entire string?"""
        if self.string is None:
            return False
        string_objects = getattr(self.string, "objects", [])
        if not string_objects:
            return False
        string_left = min(o.left_string_pos for o in string_objects)
        string_right = max(o.right_string_pos for o in string_objects)
        return self.left_string_pos == string_left and self.right_string_pos == string_right

    def calculate_internal_strength(self) -> float:
        """Group internal strength: weighted combination of bond factor and length factor.

        Scheme: groups.ss:392-410.
        """
        # Bond factor
        if not self.group_bonds:
            bond_factor = 0.0
        else:
            avg_strength = sum(b.strength for b in self.group_bonds) / len(self.group_bonds)
            # Bond facet multiplier
            if self.bond_facet.name == "plato-letter-category":
                bond_factor = avg_strength
            else:
                bond_factor = avg_strength * 0.5

        # Length factor
        length_factors = {1: 5, 2: 40, 3: 60}
        length_factor = length_factors.get(self.length, 90)

        # Weighted combination with self-weighting exponent
        if bond_factor <= 0:
            return float(length_factor)

        bf_weight = bond_factor ** 0.98
        lf_weight = 100.0 - bf_weight
        total = bf_weight + lf_weight
        if total == 0:
            return 0.0
        return round((bond_factor * bf_weight + length_factor * lf_weight) / total)

    def calculate_external_strength(self) -> float:
        """External strength: 100 if spanning, otherwise local support.

        Scheme: groups.ss:411-414.
        """
        if self.spans_whole_string():
            return 100.0
        return self._local_support()

    def _local_support(self) -> float:
        """Support from similar nearby groups.

        Scheme: groups.ss:384-391.
        First count truly disjoint supporting groups, then compute density
        and combine as density_adjustment * number_factor.
        """
        num_supporting = self.get_num_of_local_supporting_groups()
        if num_supporting == 0:
            return 0.0

        density = self.get_local_density()
        adjusted_density = 100.0 * math.sqrt(density / 100.0)
        number_factor = min(1.0, 0.6 ** (1.0 / max(1, num_supporting ** 3)))
        return round(adjusted_density * number_factor)

    def get_num_of_local_supporting_groups(self) -> int:
        """Count groups in same string with matching category and direction,
        that are disjoint from this group.

        Scheme: groups.ss:347-353.
        """
        if self.string is None:
            return 0

        all_groups = getattr(self.string, "groups", [])
        count = 0
        for other in all_groups:
            if other is self:
                continue
            if not getattr(other, "is_built", False):
                continue
            if not _disjoint_objects(self, other):
                continue
            if other.group_category is not self.group_category:
                continue
            if other.direction is not self.direction:
                continue
            count += 1
        return count

    def get_local_density(self) -> float:
        """Density of similar groups in the local neighborhood.

        Scheme: groups.ss:354-383.
        If spanning, returns 100. Otherwise walks left/right neighbors,
        counting similar groups among them.
        """
        if self.spans_whole_string():
            return 100.0

        if self.string is None:
            return 100.0

        # Walk neighbors in both directions
        left_neighbors = _walk_group_neighbors(self, "left")
        right_neighbors = _walk_group_neighbors(self, "right")
        other_objects = left_neighbors + right_neighbors
        num_of_objects = len(other_objects)

        if num_of_objects == 0:
            return 100.0

        from server.engine.groups import Group  # noqa: F811 — avoid circular at module level

        num_similar = 0
        for obj in other_objects:
            if (
                isinstance(obj, Group)
                and _disjoint_objects(self, obj)
                and obj.group_category is self.group_category
                and obj.direction is self.direction
            ):
                num_similar += 1

        return round(100.0 * num_similar / num_of_objects)

    def get_incompatible_groups(self) -> list[Group]:
        """Groups that conflict: share constituent objects with this group.

        Scheme: groups.ss:283-286.
        Returns enclosing groups of this group's constituent objects (excluding self).
        """
        result: list[Group] = []
        seen: set[int] = set()
        for obj in self.objects:
            enc = getattr(obj, "enclosing_group", None)
            if enc is not None and enc is not self and id(enc) not in seen:
                seen.add(id(enc))
                result.append(enc)
        return result

    def get_subobject_bridges(self, bridge_orientation: str) -> list[Any]:
        """Bridges on constituent objects matching the given orientation.

        Scheme: groups.ss:243-244.
        Returns non-None bridges of the given orientation from constituent objects.
        """
        result: list[Any] = []
        for obj in self.objects:
            if bridge_orientation == "horizontal":
                bridge = getattr(obj, "horizontal_bridge", None)
            elif bridge_orientation == "vertical":
                bridge = getattr(obj, "vertical_bridge", None)
            else:
                continue
            if bridge is not None:
                result.append(bridge)
        return result

    def make_flipped_version(self) -> Group:
        """Create a direction-reversed copy of this group.

        Scheme: groups.ss:328-346.
        For same-groups (no direction), returns self.
        Otherwise flips the direction and group category to their opposites.
        """
        from server.engine.bonds import Bond

        # sameness groups have no direction; return self
        if self.direction is None:
            return self

        # Try to get opposite group_category and direction
        new_category = self.group_category
        new_direction = self.direction

        opposite_method = getattr(self.group_category, "get_related_node", None)
        if opposite_method is not None:
            try:
                opp = opposite_method("plato-opposite")
                if opp is not None:
                    new_category = opp
            except Exception:
                pass

        opposite_dir_method = getattr(self.direction, "get_related_node", None)
        if opposite_dir_method is not None:
            try:
                opp = opposite_dir_method("plato-opposite")
                if opp is not None:
                    new_direction = opp
            except Exception:
                pass

        # Flip constituent bonds
        flipped_bonds = []
        for bond in self.group_bonds:
            if hasattr(bond, "flipped"):
                flipped_bonds.append(bond.flipped())
            else:
                flipped_bonds.append(bond)

        flipped = Group(
            string=self.string,
            group_category=new_category,
            bond_facet=self.bond_facet,
            direction=new_direction,
            objects=self.objects,
            bonds=flipped_bonds,
        )
        return flipped

    def add_descriptions_for_group(self, slipnet: Any) -> None:
        """Add automatic descriptions when a Group is created.

        Scheme: groups.ss:20-55.
        Adds: object-category (group), group-category, bond-category,
        direction, string-position, bond-facet, and letter-category
        for the initial letter when bond_facet is letter-category.

        This requires slipnet node references. Call after construction
        if the slipnet is available.
        """
        from server.engine.descriptions import Description

        def _get_node(name: str) -> Any:
            """Retrieve a slipnet node by name."""
            if hasattr(slipnet, "get_node"):
                return slipnet.get_node(name)
            if hasattr(slipnet, "nodes"):
                return slipnet.nodes.get(name)
            return None

        # object-category: group
        obj_cat = _get_node("plato-object-category")
        grp = _get_node("plato-group")
        if obj_cat and grp:
            self._add_desc(obj_cat, grp)

        # group-category
        grp_cat = _get_node("plato-group-category")
        if grp_cat and self.group_category:
            self._add_desc(grp_cat, self.group_category)

        # bond-category (as bond description)
        bond_cat_type = _get_node("plato-bond-category")
        bond_cat = getattr(self, "_bond_category_node", None)
        if bond_cat is None and self.group_category is not None:
            # Derive from group_category's related bond-category node
            get_rel = getattr(self.group_category, "get_related_node", None)
            if get_rel:
                try:
                    bond_cat = get_rel("plato-bond-category")
                except Exception:
                    pass
        if bond_cat_type and bond_cat:
            self._add_bond_desc(bond_cat_type, bond_cat)

        # direction
        if self.direction is not None:
            dir_cat = _get_node("plato-direction-category")
            if dir_cat:
                self._add_desc(dir_cat, self.direction)

        # string-position
        str_pos_cat = _get_node("plato-string-position-category")
        if str_pos_cat:
            if self.spans_whole_string():
                whole = _get_node("plato-whole")
                if whole:
                    self._add_desc(str_pos_cat, whole)
            elif self._is_leftmost():
                lmost = _get_node("plato-leftmost")
                if lmost:
                    self._add_desc(str_pos_cat, lmost)
            elif self._is_rightmost():
                rmost = _get_node("plato-rightmost")
                if rmost:
                    self._add_desc(str_pos_cat, rmost)
            elif self._is_middle():
                mid = _get_node("plato-middle")
                if mid:
                    self._add_desc(str_pos_cat, mid)

        # bond-facet (as bond description)
        bond_facet_type = _get_node("plato-bond-facet")
        if bond_facet_type and self.bond_facet:
            self._add_bond_desc(bond_facet_type, self.bond_facet)

        # letter-category for initial letter (when bond_facet is letter-category)
        if self.bond_facet is not None and getattr(self.bond_facet, "name", "") == "plato-letter-category":
            letter_cat_type = _get_node("plato-letter-category")
            if letter_cat_type:
                initial_letcat = self._get_initial_letter_category()
                if initial_letcat is not None:
                    self._add_desc(letter_cat_type, initial_letcat)

    def _add_desc(self, desc_type: Any, descriptor: Any) -> None:
        """Helper to add a non-bond description."""
        from server.engine.descriptions import Description

        d = Description(self, desc_type, descriptor)
        d.proposal_level = self.BUILT
        if d not in self.descriptions:
            self.descriptions.append(d)

    def _add_bond_desc(self, desc_type: Any, descriptor: Any) -> None:
        """Helper to add a bond description."""
        from server.engine.descriptions import Description

        d = Description(self, desc_type, descriptor)
        d.proposal_level = self.BUILT
        if d not in self.bond_descriptions:
            self.bond_descriptions.append(d)

    def _get_initial_letter_category(self) -> Any:
        """Get the letter-category descriptor of the first object in direction order.

        Scheme: groups.ss:77 — (tell (1st ordered-objects) 'get-descriptor-for plato-letter-category)
        """
        ordered = self.objects
        if self.direction is not None and getattr(self.direction, "name", "") == "plato-left":
            ordered = list(reversed(self.objects))
        if not ordered:
            return None
        first = ordered[0]
        # Look for letter-category description
        for d in getattr(first, "descriptions", []):
            if getattr(d.description_type, "name", "") == "plato-letter-category":
                return d.descriptor
        # Fallback for Letter objects
        return getattr(first, "letter_category", None)

    def _is_leftmost(self) -> bool:
        if self.string is None:
            return False
        return self.left_string_pos == 0

    def _is_rightmost(self) -> bool:
        if self.string is None:
            return False
        string_len = len(getattr(self.string, "objects", []))
        return self.right_string_pos == string_len - 1

    def _is_middle(self) -> bool:
        if self.string is None:
            return False
        return not self._is_leftmost() and not self._is_rightmost() and not self.spans_whole_string()

    def __repr__(self) -> str:
        cat = getattr(self.group_category, "short_name", "?")
        objs = len(self.objects)
        return f"Group({cat}, {objs} objects, strength={self.strength:.0f})"


def _disjoint_objects(obj1: Any, obj2: Any) -> bool:
    """Two objects are disjoint if their string positions don't overlap.

    Scheme: workspace-objects.ss:644-649.
    """
    return (
        obj1.right_string_pos < obj2.left_string_pos
        or obj1.left_string_pos > obj2.right_string_pos
    )


def _walk_group_neighbors(group: Group, direction: str) -> list[Any]:
    """Walk left or right from a group, collecting neighboring objects.

    Scheme: groups.ss:358-366.
    Walks using left/right neighbors; when a letter is enclosed in a group,
    uses the enclosing group as the neighbor instead.
    """
    result: list[Any] = []
    current: Any = group

    while True:
        if direction == "left":
            # Get left neighbor: use the left_object's left_bond
            left_obj = getattr(current, "left_object", current)
            bond = getattr(left_obj, "left_bond", None)
            if bond is None:
                break
            neighbor = bond.left_object
            if neighbor is left_obj:
                break
        else:
            right_obj = getattr(current, "right_object", current)
            bond = getattr(right_obj, "right_bond", None)
            if bond is None:
                break
            neighbor = bond.right_object
            if neighbor is right_obj:
                break

        # If the neighbor is a letter enclosed in a group, use the group
        enc = getattr(neighbor, "enclosing_group", None)
        if enc is not None and not hasattr(neighbor, "objects"):
            # neighbor is a letter in a group — use the group
            result.append(enc)
            current = enc
        else:
            result.append(neighbor)
            current = neighbor

    return result
