"""Bond structures between adjacent workspace objects.

A bond represents a relationship (sameness, successor, predecessor)
between two adjacent objects along a facet (letter-category, length).

Scheme source: bonds.ss
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from server.engine.slipnet import opposite_node
from server.engine.workspace_structures import WorkspaceStructure

if TYPE_CHECKING:
    from server.engine.slipnet import SlipnetNode
    from server.engine.workspace_objects import WorkspaceObject


class Bond(WorkspaceStructure):
    """A relationship between adjacent workspace objects."""

    def __init__(
        self,
        from_object: WorkspaceObject,
        to_object: WorkspaceObject,
        bond_category: SlipnetNode,
        bond_facet: SlipnetNode,
        from_descriptor: SlipnetNode,
        to_descriptor: SlipnetNode,
        direction: SlipnetNode | None = None,
    ) -> None:
        super().__init__()
        self.from_object = from_object
        self.to_object = to_object
        self.bond_category = bond_category
        self.bond_facet = bond_facet
        self.from_descriptor = from_descriptor
        self.to_descriptor = to_descriptor
        self.direction = direction

    @property
    def string(self) -> Any:
        return self.from_object.string

    @property
    def left_object(self) -> WorkspaceObject:
        if self.from_object.left_string_pos <= self.to_object.left_string_pos:
            return self.from_object
        return self.to_object

    @property
    def right_object(self) -> WorkspaceObject:
        if self.from_object.left_string_pos > self.to_object.left_string_pos:
            return self.from_object
        return self.to_object

    def calculate_internal_strength(self) -> float:
        """Bond internal strength.

        Scheme: bonds.ss:169-181.
        compatibility_factor * bond_facet_factor * bond_degree_of_assoc
        """
        # Compatibility factor: 1.0 if same object type, 0.7 if different
        from_is_letter = not hasattr(self.from_object, "objects")
        to_is_letter = not hasattr(self.to_object, "objects")
        if from_is_letter == to_is_letter:
            compat = 1.0
        else:
            compat = 0.7

        # Bond facet factor: 1.0 for letter-category, 0.7 for others
        if self.bond_facet.name == "plato-letter-category":
            facet_factor = 1.0
        else:
            facet_factor = 0.7

        assoc = self._bond_degree_of_assoc()

        return round(compat * facet_factor * assoc)

    def _bond_degree_of_assoc(self) -> float:
        """Scaled degree of association for the bond category.

        Scheme: ``bond-degree-of-assoc`` (bonds.ss:490-492) —
        ``(min 100 (round (* 11 (sqrt (tell bond-category 'get-degree-of-assoc)))))``.

        The category's own ``get-degree-of-assoc`` (slipnet.ss:90-91) is
        ``100 - (fully-active? ? shrunk-link-length : intrinsic-link-length)``: a
        fully-active concept **shrinks** its links and so associates what it labels
        more strongly.  This used to read ``intrinsic_link_length`` unconditionally,
        which computed every bond in the system at the unshrunk length — for
        ``succ``, 40 rather than 76, so ``11*sqrt`` gave 70 rather than 96.  On the
        length facet, which carries the 0.7 non-letter-category factor, that is an
        internal strength of 49 rather than 67, and the length bonds that a reading
        like ``mrrjjj`` as one-two-three depends on were dying at the evaluator.
        """
        return min(
            100.0,
            round(11.0 * math.sqrt(max(0.0, self.bond_category.degree_of_assoc()))),
        )

    def calculate_external_strength(self) -> float:
        """Bond external strength = local support.

        Scheme: bonds.ss:182-183, 162-168.
        """
        return self._local_support()

    def _local_support(self) -> float:
        """Support from similar nearby bonds.

        Scheme: bonds.ss:162-168.
        First count truly disjoint supporting bonds, then compute density
        and combine as density_adjustment * number_factor.
        """
        num_supporting = self.get_num_of_local_supporting_bonds()
        if num_supporting == 0:
            return 0.0

        density = self.get_local_density()
        adjusted_density = 100.0 * math.sqrt(density / 100.0)
        number_factor = min(1.0, 0.6 ** (1.0 / max(1, num_supporting ** 3)))
        return round(adjusted_density * number_factor)

    def get_num_of_local_supporting_bonds(self) -> int:
        """Count bonds in the same string with matching category and direction,
        that are disjoint from this bond (don't share objects).

        Scheme: bonds.ss:128-135.
        """
        if self.string is None:
            return 0

        string = self.string
        all_bonds = getattr(string, "bonds", [])
        count = 0
        for other in all_bonds:
            if other is self:
                continue
            if not getattr(other, "is_built", False):
                continue
            # Check disjoint objects (no shared left/right objects)
            if not _disjoint_objects(self.left_object, other.left_object):
                continue
            if not _disjoint_objects(self.right_object, other.right_object):
                continue
            if other.bond_category is not self.bond_category:
                continue
            if other.direction is not self.direction:
                continue
            count += 1
        return count

    def get_local_density(self) -> float:
        """Proper density computation walking neighbors.

        Scheme: bonds.ss:136-160.
        Walk left/right from this bond's objects, counting bond slots and
        similar bonds among the neighbors.
        """
        if self.string is None:
            return 100.0

        left_neighbors = _walk_neighbors(self.left_object, "left")
        right_neighbors = _walk_neighbors(self.right_object, "right")
        num_of_bond_slots = len(left_neighbors) + len(right_neighbors)

        if num_of_bond_slots == 0:
            return 100.0

        num_similar = 0
        # For left neighbors, check their right_bond
        for obj in left_neighbors:
            bond = getattr(obj, "right_bond", None)
            if (
                bond is not None
                and bond.bond_category is self.bond_category
                and bond.direction is self.direction
            ):
                num_similar += 1
        # For right neighbors, check their left_bond
        for obj in right_neighbors:
            bond = getattr(obj, "left_bond", None)
            if (
                bond is not None
                and bond.bond_category is self.bond_category
                and bond.direction is self.direction
            ):
                num_similar += 1

        return round(100.0 * num_similar / num_of_bond_slots)

    def get_incompatible_bonds(self) -> list[Bond]:
        """Bonds that conflict: occupy the same slot (same adjacent objects, different category).

        Scheme: bonds.ss:79-83.
        Returns bonds attached to the left_object's right slot and right_object's left slot.
        """
        result: list[Bond] = []
        left_right = getattr(self.left_object, "right_bond", None)
        if left_right is not None and left_right is not self:
            result.append(left_right)
        right_left = getattr(self.right_object, "left_bond", None)
        if right_left is not None and right_left is not self and right_left not in result:
            result.append(right_left)
        return result

    def bonds_equal(self, other: Bond) -> bool:
        """Structural equality: same from/to objects, same category, same direction.

        Scheme: bonds.ss:436-441.
        """
        return (
            self.from_object is other.from_object
            and self.to_object is other.to_object
            and self.bond_category is other.bond_category
            and self.direction is other.direction
        )

    @property
    def directed(self) -> bool:
        """Whether the bond has a direction (not sameness).

        Scheme: bonds.ss:444-446.
        """
        return self.direction is not None

    def flipped(self) -> Bond:
        """Return a copy with from/to objects swapped and category/direction reversed.

        Scheme: bonds.ss:123-127.
        make-bond(to-object, from-object,
                  (bond-category 'get-related-node opposite),
                  bond-facet, to-descriptor, from-descriptor)
        """
        new_category = opposite_node(self.bond_category)
        new_dir = opposite_node(self.direction)
        return Bond(
            from_object=self.to_object,
            to_object=self.from_object,
            bond_category=new_category,
            bond_facet=self.bond_facet,
            from_descriptor=self.to_descriptor,
            to_descriptor=self.from_descriptor,
            direction=new_dir,
        )

    def __repr__(self) -> str:
        cat = getattr(self.bond_category, "short_name", "?")
        return (
            f"Bond({self.from_object} -> {self.to_object}, {cat}, "
            f"strength={self.strength:.0f})"
        )


def _disjoint_objects(obj1: Any, obj2: Any) -> bool:
    """Two objects are disjoint if their string positions don't overlap.

    Scheme: workspace-objects.ss:644-649.
    """
    return (
        obj1.right_string_pos < obj2.left_string_pos
        or obj1.left_string_pos > obj2.right_string_pos
    )


def _walk_neighbors(obj: Any, direction: str) -> list[Any]:
    """Walk left or right from an object, collecting neighbors.

    Scheme: bonds.ss:139-143. Uses choose-left-neighbor / choose-right-neighbor.
    In the Scheme code, this walks using 'choose-left-neighbor or
    'choose-right-neighbor methods. In the Python port, we walk using
    left_bond/right_bond to find adjacent objects.
    """
    result: list[Any] = []
    current = obj
    while True:
        if direction == "left":
            bond = getattr(current, "left_bond", None)
            if bond is None:
                break
            neighbor = bond.left_object if bond.left_object is not current else bond.right_object
            # Actually, for walking left, we want the left neighbor
            neighbor = bond.left_object
            if neighbor is current:
                break
        else:
            bond = getattr(current, "right_bond", None)
            if bond is None:
                break
            neighbor = bond.right_object
            if neighbor is current:
                break
        result.append(neighbor)
        current = neighbor
    return result


def incompatible_bond_candidates(
    object1: Any, object2: Any, bond_facet: Any, bond_category: Any
) -> bool:
    """Are these two objects the wrong pair to bond on this facet and category?

    Scheme: ``incompatible-bond-candidates?`` (``bonds.ss:538-550``)::

        (cond
          ((eq? bond-facet plato-length)
           (and (directed-group? object1) (directed-group? object2)
                (not (same-group-direction? object1 object2))))
          ((eq? bond-category plato-sameness)
           (or (directed-group? object1) (directed-group? object2)))
          ((and (directed-group? object1) (directed-group? object2))
           (or (not (same-group-category? object1 object2))
               (not (same-group-direction? object1 object2))))
          (else (or (directed-group? object1) (directed-group? object2))))

    Every bond scout consults it before proposing (``bonds.ss:209``, ``254``,
    ``313``); none of the ported scouts did, so the model was free to bond, for
    instance, a successor group to a predecessor group on letter-category.
    """
    from server.engine.groups import Group

    def directed(obj: Any) -> bool:
        # Scheme: ``directed-group?`` (groups.ss:1050-1055).
        if not isinstance(obj, Group):
            return False
        name = getattr(obj.group_category, "name", "")
        return name in ("plato-succgrp", "plato-predgrp")

    d1, d2 = directed(object1), directed(object2)

    if getattr(bond_facet, "name", "") == "plato-length":
        return d1 and d2 and object1.direction is not object2.direction
    if getattr(bond_category, "name", "") == "plato-sameness":
        return d1 or d2
    if d1 and d2:
        return (
            object1.group_category is not object2.group_category
            or object1.direction is not object2.direction
        )
    return d1 or d2
