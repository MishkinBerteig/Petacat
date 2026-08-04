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
    from server.engine.rng import RNG
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

    def calculate_external_strength(self, rng: RNG | None = None) -> float:
        """Bond external strength = local support.

        Scheme: bonds.ss:182-183, 162-168.

        *rng* is the drawing codelet's; see :meth:`get_local_density`.
        """
        return self._local_support(rng)

    def _local_support(self, rng: RNG | None = None) -> float:
        """Support from similar nearby bonds.

        Scheme: bonds.ss:162-168.
        First count truly disjoint supporting bonds, then compute density
        and combine as density_adjustment * number_factor.
        """
        num_supporting = self.get_num_of_local_supporting_bonds()
        if num_supporting == 0:
            return 0.0

        density = self.get_local_density(rng)
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

    def get_local_density(self, rng: RNG | None = None) -> float:
        """How much of the neighbourhood is bonded the way this bond is.

        Scheme: ``get-local-density`` (bonds.ss:136-160).  The walk steps through
        **positional** neighbours — ``choose-left-neighbor`` /
        ``choose-right-neighbor``, a salience-weighted pick among the adjacent
        letter and the groups edged there — and *every step is a slot*, bonded or
        not.  It stops only at the end of the string, so 100 is reached only when
        there are no slots at all, i.e. the bond already spans the string.

        Following ``left_bond``/``right_bond`` pointers instead, as this used to,
        stopped the walk at the first unbonded object and so kept unbonded slots
        out of the denominator entirely.  ``abcdef`` with only ``a-b`` built and
        ``c-d`` proposed walked nowhere at all and scored 100 — support 60 — where
        the reference counts four slots, finds one similar bond, and scores 25 —
        support 30.  Sparse early bonds were snowballing on a denominator of zero.

        Each step of that walk is a salience-weighted **stochastic** pick, so the
        walk needs a generator and the reference re-rolls it on every strength
        update.  *rng* is the one the calling codelet is drawing from, threaded
        down from :meth:`WorkspaceStructure.update_strength`; ``None`` means no
        run context, and the walk then takes the first candidate at each step
        (see ``WorkspaceObject._pick_neighbor``).
        """
        if self.string is None:
            return 100.0

        left_neighbors = _walk_neighbors(self.left_object, "left", rng)
        right_neighbors = _walk_neighbors(self.right_object, "right", rng)
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

    def leftmost_in_string(self) -> bool:
        """Scheme: bonds.ss:76."""
        return self.left_object.left_string_pos == 0

    def rightmost_in_string(self) -> bool:
        """Scheme: bonds.ss:77-78."""
        string = self.string
        if string is None:
            return False
        return self.right_object.right_string_pos == getattr(string, "length", 1) - 1

    def get_incompatible_bridges(self, bridge_orientation: str) -> list[Any]:
        """Bridges this bond would contradict, on one orientation.

        Scheme: ``get-incompatible-bridges`` (bonds.ss:84-88) — the bridge, if
        any, hanging off each of the bond's two objects.
        """
        result: list[Any] = []
        for obj in (self.left_object, self.right_object):
            bridge = self._get_incompatible_bridge(obj, bridge_orientation)
            if bridge is not None and bridge not in result:
                result.append(bridge)
        return result

    def _get_incompatible_bridge(self, obj: Any, bridge_orientation: str) -> Any:
        """Scheme: ``get-incompatible-bridge`` (bonds.ss:89-122).

        A directed bond at the edge of its string implies a direction mapping
        against whatever bond sits at the corresponding edge on the far side of a
        bridge.  If that implied mapping contradicts the bridge's own
        string-position mapping — "leftmost goes to rightmost, but right goes to
        right" — the bond and the bridge cannot both be right about the string.
        """
        bridge = getattr(
            obj,
            "horizontal_bridge" if bridge_orientation == "horizontal" else "vertical_bridge",
            None,
        )
        if bridge is None:
            return None

        string_position_cm = None
        for cm in getattr(bridge, "concept_mappings", ()):
            if getattr(cm.description_type1, "name", "") == "plato-string-position-category":
                string_position_cm = cm
                break
        if string_position_cm is None:
            return None

        other_object = bridge.object2 if bridge.object1 is obj else bridge.object1
        if not (other_object.leftmost_in_string() or other_object.rightmost_in_string()):
            return None

        other_bond = (
            other_object.right_bond
            if other_object.leftmost_in_string()
            else other_object.left_bond
        )
        if other_bond is None or not other_bond.directed:
            return None

        from server.engine.bridges import _incompatible_cms

        direction_cm = self._direction_concept_mapping(other_bond)
        if direction_cm is None:
            return None
        return bridge if _incompatible_cms(direction_cm, string_position_cm) else None

    def _direction_concept_mapping(self, other_bond: Bond) -> Any:
        """The ``DirCtgy`` mapping between this bond's direction and *other_bond*'s.

        Scheme: the inline ``make-concept-mapping`` of bonds.ss:108-115.
        """
        from server.engine.bridges import _IDENTITY_SENTINEL, _label_node
        from server.engine.concept_mappings import ConceptMapping

        if self.direction is None or other_bond.direction is None:
            return None
        direction_category = getattr(self.direction, "category", None)
        if direction_category is None:
            return None

        label = _label_node(self.direction, other_bond.direction)
        if label is _IDENTITY_SENTINEL:
            # ``_incompatible_cms`` compares labels by identity against the
            # bridge's own concept-mappings, which carry the real Slipnet node.
            label = self._slipnet_node("plato-identity")
        return ConceptMapping(
            description_type1=direction_category,
            descriptor1=self.direction,
            description_type2=direction_category,
            descriptor2=other_bond.direction,
            label=label,
            object1=self,
            object2=other_bond,
        )

    def _slipnet_node(self, name: str) -> Any:
        workspace = getattr(self.string, "workspace", None)
        slipnet = getattr(workspace, "slipnet", None)
        return getattr(slipnet, "nodes", {}).get(name) if slipnet is not None else None

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


def _walk_neighbors(obj: Any, direction: str, rng: RNG | None = None) -> list[Any]:
    """Walk left or right from *obj* through positional neighbours.

    Scheme: ``neighbors`` inside ``get-local-density`` (bonds.ss:137-145) —

        (lambda (object choose-method)
          (let ((neighbor (tell object choose-method)))
            (if (not (exists? neighbor))
              '()
              (cons neighbor (neighbors neighbor choose-method)))))

    Each step is a fresh stochastic pick among the objects edged at the adjacent
    position, drawn from *rng* — the calling codelet's stream — so the walk can
    climb into a group and continue from *its* far edge.  That is what makes it
    terminate: every step moves strictly outwards, and the string is finite.
    """
    method = "choose_left_neighbor" if direction == "left" else "choose_right_neighbor"
    result: list[Any] = []
    current = obj
    while True:
        chooser = getattr(current, method, None)
        if chooser is None:
            # Not a real WorkspaceObject — a hand-rolled test double.  Nothing to
            # walk, which is the same answer as "at the end of the string".
            break
        neighbor = chooser(rng)
        if neighbor is None or neighbor is current:
            break
        result.append(neighbor)
        current = neighbor
    return result


def get_common_groups(object1: Any, object2: Any) -> list[Any]:
    """Built groups of the string that nest *both* objects, at any depth.

    Scheme: ``get-common-groups`` (groups.ss:1026-1033)::

        (filter (lambda (group)
                  (and (tell group 'nested-member? object1)
                       (tell group 'nested-member? object2)))
          (tell (tell object1 'get-string) 'get-groups))

    ``nested-member?`` (groups.ss:271-273) recurses into subgroups, so a group two
    levels up counts.  This is the set a bond has to beat to be built between two
    objects that some group already holds together — a bond running *inside* a
    group contradicts the group's own reading of that material.
    """
    string = getattr(object1, "string", None)
    if string is None:
        return []
    result: list[Any] = []
    for group in getattr(string, "groups", []):
        if not getattr(group, "is_built", False):
            continue
        nested = getattr(group, "nested_member", None)
        if nested is None:
            continue
        if nested(object1) and nested(object2):
            result.append(group)
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
