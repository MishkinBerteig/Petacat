"""Base class for workspace objects (letters, groups).

Scheme source: workspace-objects.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.engine.descriptions import Description
    from server.engine.rng import RNG

# Names of slipnet nodes considered non-distinguishing for the
# ``distinguishing_descriptor`` predicate.  Matches *slipnet-numbers*
# plus plato-letter and plato-group in the Scheme source.
_NON_DISTINGUISHING_NAMES: set[str] = {
    "plato-letter",
    "plato-group",
    "plato-one",
    "plato-two",
    "plato-three",
    "plato-four",
    "plato-five",
}


class WorkspaceObject:
    """Base class for letters and groups in the workspace."""

    _next_id = 0

    def __init__(
        self,
        string: Any,  # WorkspaceString
        left_pos: int,
        right_pos: int,
    ) -> None:
        WorkspaceObject._next_id += 1
        self.id = WorkspaceObject._next_id
        self.string = string
        self.left_string_pos = left_pos
        self.right_string_pos = right_pos

        self.raw_importance: float = 0.0
        self.relative_importance: float = 0.0
        self.descriptions: list[Any] = []
        self.outgoing_bonds: list[Any] = []
        self.incoming_bonds: list[Any] = []
        self.left_bond: Any = None
        self.right_bond: Any = None
        self.horizontal_bridge: Any = None
        self.vertical_bridge: Any = None
        self.enclosing_group: Any = None
        self.salience_clamped: bool = False

        self.intra_string_unhappiness: float = 100.0
        self.inter_string_unhappiness: dict[str, float] = {
            "horizontal": 100.0,
            "vertical": 100.0,
        }
        self.average_unhappiness: float = 100.0
        self.salience: dict[str, float] = {
            "intra": 100.0,
            "horizontal_inter": 100.0,
            "vertical_inter": 100.0,
            "average": 100.0,
        }

    @property
    def span(self) -> int:
        return self.right_string_pos - self.left_string_pos + 1

    # ------------------------------------------------------------------
    #  Neighbor finding  (Scheme: workspace-objects.ss:375-423)
    # ------------------------------------------------------------------

    def get_all_left_neighbors(self) -> list[WorkspaceObject]:
        """All objects immediately to the left, including groups ending at
        the adjacent position.

        Scheme: workspace-objects.ss:375-380.
        """
        if self.leftmost_in_string():
            return []
        left_pos = self.left_string_pos - 1
        neighbors: list[WorkspaceObject] = []
        # The letter at left_pos
        string = self.string
        if string is not None:
            letters = getattr(string, "letters", None)
            if letters is None:
                letters = [o for o in getattr(string, "objects", []) if isinstance(o, Letter)]
            if 0 <= left_pos < len(letters):
                neighbors.append(letters[left_pos])
            # Groups whose right edge is at left_pos
            for g in getattr(string, "groups", []):
                if g.right_string_pos == left_pos:
                    neighbors.append(g)
        return neighbors

    def get_all_right_neighbors(self) -> list[WorkspaceObject]:
        """All objects immediately to the right, including groups starting at
        the adjacent position.

        Scheme: workspace-objects.ss:382-387.
        """
        if self.rightmost_in_string():
            return []
        right_pos = self.right_string_pos + 1
        neighbors: list[WorkspaceObject] = []
        string = self.string
        if string is not None:
            letters = getattr(string, "letters", None)
            if letters is None:
                letters = [o for o in getattr(string, "objects", []) if isinstance(o, Letter)]
            if 0 <= right_pos < len(letters):
                neighbors.append(letters[right_pos])
            # Groups whose left edge is at right_pos
            for g in getattr(string, "groups", []):
                if g.left_string_pos == right_pos:
                    neighbors.append(g)
        return neighbors

    def get_ungrouped_left_neighbor(self) -> WorkspaceObject | None:
        """Left neighbor not enclosed in a group that excludes *self*.

        Scheme: workspace-objects.ss:389-394.
        """
        for n in self.get_all_left_neighbors():
            eg = n.enclosing_group
            if eg is None or (hasattr(eg, "nested_member") and eg.nested_member(self)):
                return n
        return None

    def get_ungrouped_right_neighbor(self) -> WorkspaceObject | None:
        """Right neighbor not enclosed in a group that excludes *self*.

        Scheme: workspace-objects.ss:396-401.
        """
        for n in self.get_all_right_neighbors():
            eg = n.enclosing_group
            if eg is None or (hasattr(eg, "nested_member") and eg.nested_member(self)):
                return n
        return None

    def choose_neighbor(self, rng: RNG) -> WorkspaceObject | None:
        """Stochastically pick a neighbor weighted by intra-string salience.

        Scheme: workspace-objects.ss:417-423.
        """
        neighbors = self.get_all_left_neighbors() + self.get_all_right_neighbors()
        if not neighbors:
            return None
        weights = [max(0.1, n.salience.get("intra", 1.0)) for n in neighbors]
        return rng.weighted_pick(neighbors, weights)

    # ------------------------------------------------------------------
    #  Description management  (Scheme: workspace-objects.ss:161-268)
    # ------------------------------------------------------------------

    def add_description(self, description: Description) -> None:
        """Add a description to this object.

        Scheme: workspace-objects.ss:293-301.
        """
        self.descriptions.append(description)

    def get_descriptions(self) -> list[Any]:
        """Return all descriptions.  For groups this includes bond
        descriptions; for letters just the regular descriptions.

        Scheme: workspace-objects.ss:162-165.
        """
        # Groups override via get_all_descriptions in their own class;
        # for the base/letter case, just return descriptions.
        return list(self.descriptions)

    def get_all_descriptions(self) -> list[Any]:
        """Return all descriptions including bond descriptions for groups.

        Scheme: workspace-objects.ss:162-165.
        """
        return list(self.descriptions)

    def description_type_present(self, desc_type: Any) -> bool:
        """Check if a description of the given type exists.

        Scheme: workspace-objects.ss:277-279.
        """
        for d in self.get_all_descriptions():
            if getattr(d, "description_type", None) is desc_type:
                return True
        return False

    def descriptor_present(self, descriptor: Any) -> bool:
        """Check if a descriptor is attached to any description.

        Scheme: workspace-objects.ss:284-286.
        """
        for d in self.get_all_descriptions():
            if getattr(d, "descriptor", None) is descriptor:
                return True
        return False

    def get_relevant_descriptions(self) -> list[Any]:
        """Descriptions whose description_type is fully active in the slipnet.

        Scheme: workspace-objects.ss:247-248.
        """
        return [d for d in self.descriptions if _description_is_relevant(d)]

    def _is_distinguishing_descriptor(self, descriptor: Any) -> bool:
        """True if *descriptor* distinguishes this object from others in
        the same string.

        Scheme: workspace-objects.ss:223-245.
        """
        name = getattr(descriptor, "name", "")
        if name in _NON_DISTINGUISHING_NAMES:
            return False

        string = self.string
        if string is None:
            return True

        # Determine the relevant set of "other objects" to compare with
        from server.engine.groups import Group
        if isinstance(self, Letter):
            other_objects = [o for o in getattr(string, "objects", [])
                            if isinstance(o, Letter) and o is not self]
        elif isinstance(self, Group):
            supergroup = self.enclosing_group
            subgroups = [o for o in getattr(self, "objects", []) if isinstance(o, Group)]
            other_objects = [
                g for g in getattr(string, "groups", [])
                if g is not self and g is not supergroup and g not in subgroups
            ]
        else:
            other_objects = [o for o in getattr(string, "objects", []) if o is not self]

        # Collect descriptors from other objects
        other_descriptors: set[int] = set()
        for obj in other_objects:
            for d in getattr(obj, "descriptions", []):
                other_descriptors.add(id(getattr(d, "descriptor", None)))
        return id(descriptor) not in other_descriptors

    def get_distinguishing_descriptions(self) -> list[Any]:
        """Descriptions whose descriptor distinguishes this object from
        others in the same string.

        Scheme: workspace-objects.ss:250-254.
        """
        return [
            d for d in self.descriptions
            if self._is_distinguishing_descriptor(getattr(d, "descriptor", None))
        ]

    def get_relevant_distinguishing_descriptions(self) -> list[Any]:
        """Descriptions that are both relevant and distinguishing.

        Scheme: workspace-objects.ss:256-258.
        """
        return [
            d for d in self.get_distinguishing_descriptions()
            if _description_is_relevant(d)
        ]

    # ------------------------------------------------------------------
    #  Bond tracking  (Scheme: workspace-objects.ss:193-212)
    # ------------------------------------------------------------------

    def add_outgoing_bond(self, bond: Any) -> None:
        """Scheme: workspace-objects.ss:193-197."""
        self.outgoing_bonds.append(bond)
        # Sameness bonds are symmetric
        if _is_sameness_bond(bond):
            self.incoming_bonds.append(bond)

    def add_incoming_bond(self, bond: Any) -> None:
        """Scheme: workspace-objects.ss:198-201."""
        self.incoming_bonds.append(bond)
        if _is_sameness_bond(bond):
            self.outgoing_bonds.append(bond)

    def remove_outgoing_bond(self, bond: Any) -> None:
        """Scheme: workspace-objects.ss:202-205."""
        if bond in self.outgoing_bonds:
            self.outgoing_bonds.remove(bond)
        if _is_sameness_bond(bond) and bond in self.incoming_bonds:
            self.incoming_bonds.remove(bond)

    def remove_incoming_bond(self, bond: Any) -> None:
        """Scheme: workspace-objects.ss:206-209."""
        if bond in self.incoming_bonds:
            self.incoming_bonds.remove(bond)
        if _is_sameness_bond(bond) and bond in self.outgoing_bonds:
            self.outgoing_bonds.remove(bond)

    def get_incident_bonds(self) -> list[Any]:
        """All bonds connected to this object (left and/or right).

        Scheme: workspace-objects.ss:166.
        """
        result = []
        if self.left_bond is not None:
            result.append(self.left_bond)
        if self.right_bond is not None:
            result.append(self.right_bond)
        return result

    # ------------------------------------------------------------------
    #  Spanning / position predicates  (Scheme: workspace-objects.ss:347-373)
    # ------------------------------------------------------------------

    def spans_whole_string(self) -> bool:
        """Does this object span the entire string?

        Scheme: workspace-objects.ss:350-351.
        """
        string = self.string
        if string is None:
            return False
        return self.span == getattr(string, "length", 0)

    def leftmost_in_string(self) -> bool:
        """Scheme: workspace-objects.ss:361-362."""
        return self.left_string_pos == 0

    def middle_in_string(self) -> bool:
        """True if this object is flanked by an object that is leftmost
        and an object that is rightmost.

        Scheme: workspace-objects.ss:364-370.
        """
        left_n = self.get_ungrouped_left_neighbor()
        right_n = self.get_ungrouped_right_neighbor()
        if left_n is None or right_n is None:
            return False
        return left_n.leftmost_in_string() and right_n.rightmost_in_string()

    def rightmost_in_string(self) -> bool:
        """Scheme: workspace-objects.ss:372-373."""
        string = self.string
        if string is None:
            return False
        return self.right_string_pos == getattr(string, "length", 1) - 1

    def get_nesting_level(self) -> int:
        """For groups, recursive nesting depth.

        Scheme: workspace-objects.ss:342-345.
        """
        if self.enclosing_group is not None:
            return 1 + self.enclosing_group.get_nesting_level()
        return 0

    # ------------------------------------------------------------------
    #  Bridge predicate  (Scheme: workspace-objects.ss:179-183)
    # ------------------------------------------------------------------

    def mapped(self, bridge_type: str) -> bool:
        """Has a bridge of the given orientation?

        *bridge_type* is ``"horizontal"``, ``"vertical"``, or ``"both"``.

        Scheme: workspace-objects.ss:179-183.
        """
        if bridge_type == "vertical":
            return self.vertical_bridge is not None
        if bridge_type == "horizontal":
            return self.horizontal_bridge is not None
        if bridge_type == "both":
            return (self.horizontal_bridge is not None
                    and self.vertical_bridge is not None)
        return False

    def in_string(self, string: Any) -> bool:
        """Is this object in the given string?

        Scheme: workspace-objects.ss:151.
        """
        return self.string is string

    # ------------------------------------------------------------------
    #  Importance / unhappiness / salience updates
    #  (Scheme: workspace-objects.ss:425-601)
    # ------------------------------------------------------------------

    def update_importance(self, max_raw: float = 300.0, enclosed_factor: float = 0.667) -> None:
        """Scheme: workspace-objects.ss:425-433 (update-raw-importance)."""
        total = sum(
            getattr(d, "descriptor_activation", 0) for d in self.get_relevant_descriptions()
        )
        raw = min(max_raw, total)
        if self.enclosing_group is not None:
            raw *= enclosed_factor
        self.raw_importance = raw

    def update_intra_string_unhappiness(self) -> None:
        """Scheme: workspace-objects.ss:440-454."""
        if self.spans_whole_string():
            self.intra_string_unhappiness = 0.0
            return
        if self.enclosing_group is not None:
            self.intra_string_unhappiness = 100.0 - getattr(
                self.enclosing_group, "strength", 0
            )
            return

        bonds = self.get_incident_bonds()
        if not bonds:
            self.intra_string_unhappiness = 100.0
        elif self.leftmost_in_string() or self.rightmost_in_string():
            self.intra_string_unhappiness = 100.0 - round(
                getattr(bonds[0], "strength", 0) / 3
            )
        else:
            total = sum(getattr(b, "strength", 0) for b in bonds)
            self.intra_string_unhappiness = 100.0 - round(total / 6)

    def update_inter_string_unhappiness(self) -> None:
        """Compute inter-string unhappiness for horizontal and vertical
        orientations based on bridges and enclosing-group bridges.

        Scheme: workspace-objects.ss:457-489.
        """
        h_weakness = self._bridge_weakness("horizontal")
        v_weakness = self._bridge_weakness("vertical")

        stype = self._string_type()
        if stype == "initial":
            self.inter_string_unhappiness["horizontal"] = h_weakness
            self.inter_string_unhappiness["vertical"] = v_weakness
        elif stype == "modified":
            self.inter_string_unhappiness["horizontal"] = h_weakness
        elif stype == "target":
            self.inter_string_unhappiness["vertical"] = v_weakness
            # In justify mode, target also has horizontal bridges
            if self._justify_mode():
                self.inter_string_unhappiness["horizontal"] = h_weakness
        elif stype == "answer":
            self.inter_string_unhappiness["horizontal"] = h_weakness

    def update_average_unhappiness(self) -> None:
        """Combine intra and inter-string unhappiness.

        Scheme: workspace-objects.ss:492-517.
        """
        intra = self.intra_string_unhappiness
        h = self.inter_string_unhappiness["horizontal"]
        v = self.inter_string_unhappiness["vertical"]

        stype = self._string_type()
        if stype == "initial":
            self.average_unhappiness = round(_average(intra, h, v))
        elif stype == "modified":
            self.average_unhappiness = round(_average(intra, h))
        elif stype == "target":
            if self._justify_mode():
                self.average_unhappiness = round(_average(intra, v, h))
            else:
                self.average_unhappiness = round(_average(intra, v))
        elif stype == "answer":
            self.average_unhappiness = round(_average(intra, h))
        else:
            self.average_unhappiness = round(intra)

    def update_intra_string_salience(self) -> None:
        """Scheme: workspace-objects.ss:524-530."""
        if self.salience_clamped:
            self.salience["intra"] = 100
        else:
            self.salience["intra"] = round(
                0.8 * self.intra_string_unhappiness
                + 0.2 * self.relative_importance
            )

    def update_inter_string_salience(self) -> None:
        """Per-string-type inter-string salience.

        Scheme: workspace-objects.ss:532-559.
        """
        if self.salience_clamped:
            self.salience["horizontal_inter"] = 100
            self.salience["vertical_inter"] = 100
            return

        h = self.inter_string_unhappiness["horizontal"]
        v = self.inter_string_unhappiness["vertical"]
        ri = self.relative_importance

        stype = self._string_type()
        if stype == "initial":
            self.salience["horizontal_inter"] = round(0.2 * h + 0.8 * ri)
            self.salience["vertical_inter"] = round(0.2 * v + 0.8 * ri)
        elif stype == "modified":
            self.salience["horizontal_inter"] = round(0.2 * h + 0.8 * ri)
        elif stype == "target":
            self.salience["vertical_inter"] = round(0.2 * v + 0.8 * ri)
            if self._justify_mode():
                self.salience["horizontal_inter"] = round(0.2 * h + 0.8 * ri)
        elif stype == "answer":
            self.salience["horizontal_inter"] = round(0.2 * h + 0.8 * ri)

    def update_average_salience(self) -> None:
        """Combine intra and inter-string salience.

        Scheme: workspace-objects.ss:562-587.
        """
        intra = self.salience["intra"]
        h = self.salience["horizontal_inter"]
        v = self.salience["vertical_inter"]

        stype = self._string_type()
        if stype == "initial":
            self.salience["average"] = round(_average(intra, h, v))
        elif stype == "modified":
            self.salience["average"] = round(_average(intra, h))
        elif stype == "target":
            if self._justify_mode():
                self.salience["average"] = round(_average(intra, v, h))
            else:
                self.salience["average"] = round(_average(intra, v))
        elif stype == "answer":
            self.salience["average"] = round(_average(intra, h))
        else:
            self.salience["average"] = round(intra)

    def update_description_strengths(self) -> None:
        """Update strength of all descriptions.

        Scheme: workspace-objects.ss:589-592.
        """
        for d in self.descriptions:
            if hasattr(d, "update_strength"):
                d.update_strength()

    def update_object_values(self) -> None:
        """Full update of unhappiness, salience, and description strengths.

        Scheme: workspace-objects.ss:594-601.
        Called after raw-importance and relative-importance have already been
        set by the string-level ``update_object_values``.
        """
        self.update_intra_string_unhappiness()
        self.update_inter_string_unhappiness()
        self.update_average_unhappiness()
        self.update_intra_string_salience()
        self.update_inter_string_salience()
        self.update_average_salience()
        self.update_description_strengths()

    # ------------------------------------------------------------------
    #  Legacy compatibility shim — old update_salience alias
    # ------------------------------------------------------------------

    def update_salience(
        self,
        unhappiness_w_intra: float = 80.0,
        importance_w_intra: float = 20.0,
        unhappiness_w_inter: float = 20.0,
        importance_w_inter: float = 80.0,
    ) -> None:
        """Legacy method kept for backward compatibility with existing tests.

        Equivalent to calling update_intra_string_salience +
        update_inter_string_salience, but without per-string-type logic.
        """
        self.salience["intra"] = round(
            (unhappiness_w_intra / 100) * self.intra_string_unhappiness
            + (importance_w_intra / 100) * self.relative_importance
        )
        for key in ("horizontal_inter", "vertical_inter"):
            bridge_key = key.replace("_inter", "")
            unhappiness = self.inter_string_unhappiness.get(bridge_key, 100.0)
            self.salience[key] = round(
                (unhappiness_w_inter / 100) * unhappiness
                + (importance_w_inter / 100) * self.relative_importance
            )

    # ------------------------------------------------------------------
    #  Internal helpers
    # ------------------------------------------------------------------

    def _string_type(self) -> str:
        """Return the string type name (initial/modified/target/answer)."""
        return getattr(self.string, "string_type", "initial")

    def _justify_mode(self) -> bool:
        """Return True if the engine is in justify mode.

        This is a heuristic check: if the string has a ``justify_mode``
        attribute it uses that, otherwise defaults to False.
        """
        return getattr(self.string, "justify_mode", False)

    def _bridge_weakness(self, orientation: str) -> float:
        """Compute bridge-based weakness for a given orientation.

        Scheme: workspace-objects.ss:459-477.
        """
        bridge = (self.horizontal_bridge if orientation == "horizontal"
                  else self.vertical_bridge)
        if bridge is not None:
            return 100.0 - getattr(bridge, "strength", 0)
        # Check enclosing group's bridge
        if self.enclosing_group is not None:
            eg_bridge = (getattr(self.enclosing_group, "horizontal_bridge", None)
                         if orientation == "horizontal"
                         else getattr(self.enclosing_group, "vertical_bridge", None))
            if eg_bridge is not None:
                return 100.0 - 0.5 * getattr(eg_bridge, "strength", 0)
        return 100.0

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id}, pos={self.left_string_pos}-{self.right_string_pos})"


# ======================================================================
#  Module-level helpers
# ======================================================================

def _average(*values: float) -> float:
    """Simple average of the given values."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _description_is_relevant(d: Any) -> bool:
    """True if the description's type node is fully active."""
    if hasattr(d, "is_relevant"):
        return d.is_relevant()
    dt = getattr(d, "description_type", None)
    if dt is not None and hasattr(dt, "fully_active"):
        return dt.fully_active()
    return False


def _is_sameness_bond(bond: Any) -> bool:
    """True if the bond's category is sameness."""
    cat = getattr(bond, "bond_category", None)
    return getattr(cat, "name", "") == "plato-sameness"


class Letter(WorkspaceObject):
    """A single letter in a workspace string."""

    def __init__(
        self,
        string: Any,
        position: int,
        letter_category: Any,  # SlipnetNode for the letter (plato-a, etc.)
    ) -> None:
        super().__init__(string, position, position)
        self.letter_category = letter_category

    def __repr__(self) -> str:
        name = getattr(self.letter_category, "short_name", "?")
        return f"Letter({name}, pos={self.left_string_pos})"
