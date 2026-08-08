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
    from server.engine.rng import RNG
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
        object_id = self.id
        WorkspaceStructure.__init__(self)
        # A Group is the one thing that is both a WorkspaceObject and a
        # WorkspaceStructure, so both constructors run — and each assigns ``self.id``
        # from a counter of its own.  ``WorkspaceStructure.__init__`` ran second and
        # won, which left a Group sitting in ``all_objects`` carrying a *structure*
        # number beside Letters carrying *object* numbers.  The two counters advance
        # independently, so they collide: ``abc->abd;mrrjjj`` seed 8 puts
        # ``Group(samegrp, 3 objects)`` and ``Letter(k, pos=3)`` both at 60.
        #
        # ``all_objects`` is the collection ``id`` is read by, so the object identity is
        # the one it keeps.  The structure number stays reachable under its own name for
        # the structure namespace, and is still drawn — a Group really is a structure and
        # skipping the draw would renumber every structure built after the first group.
        self.structure_id = self.id
        self.id = object_id

        self.group_category = group_category
        self.bond_facet = bond_facet
        self.direction = direction
        self.objects = objects
        self.group_bonds = bonds
        self.bond_descriptions: list[Any] = []
        self.left_object = min(objects, key=lambda o: o.left_string_pos)
        self.right_object = max(objects, key=lambda o: o.right_string_pos)

        # ``new-group`` (groups.ss:79) derives the bond category from the *group
        # category*, not from the constituent bonds.  That is what gives a
        # singleton — which has no bonds at all — a bond category, and hence an
        # internal strength (groups.ss:392-398) and a BondCtgy description
        # (groups.ss:30-31) like any other group.
        related = getattr(group_category, "get_related_node", None)
        self.bond_category = related("plato-bond-category") if related else None

        self._attach_initial_descriptions()

    def _attach_initial_descriptions(self) -> None:
        """Describe the group the moment it is created.

        Scheme: ``make-group`` (groups.ss:20-54) plus ``attach-length-description``
        (groups.ss:831-837).  Without these a group is invisible to the bridge
        scouts — no descriptions means no concept-mappings — so problems whose
        answer turns on a whole-string group (``abc -> abcd``, ``abc -> aabbcc``)
        could never get off the ground.
        """
        from server.engine.descriptions import Description

        slipnet = getattr(getattr(self.string, "workspace", None), "slipnet", None)
        if slipnet is None:
            slipnet = getattr(self.string, "slipnet", None)
        if slipnet is None:
            return

        def node(name: str):
            return slipnet.nodes.get(name)

        def describe(type_name: str, descriptor, *, bond_description: bool = False) -> None:
            dt = node(type_name)
            if dt is None or descriptor is None:
                return
            desc = Description(self, dt, descriptor)
            desc.proposal_level = Description.BUILT
            if bond_description:
                self.bond_descriptions.append(desc)
            else:
                self.descriptions.append(desc)

        describe("plato-object-category", node("plato-group"))
        describe("plato-group-category", self.group_category)
        # ``groups.ss:30-31`` attaches the BondCtgy description *unconditionally*,
        # from the category-derived bond category.  Gating it on the presence of
        # constituent bonds left every singleton group without one, so a bridge to
        # a singleton lost its BondCtgy concept-mapping.
        describe("plato-bond-category", self.bond_category, bond_description=True)
        if self.direction is not None:
            describe("plato-direction-category", self.direction)

        # ``make-group`` (groups.ss:34-42) orders these whole -> leftmost ->
        # **middle** -> rightmost, using the object's own position predicates.  The
        # middle branch was missing entirely, so no group could ever be described
        # ``middle`` — closing one of the two avenues by which a middle-to-middle
        # correspondence is reachable.
        if self.spans_whole_string():
            describe("plato-string-position-category", node("plato-whole"))
        elif self.leftmost_in_string():
            describe("plato-string-position-category", node("plato-leftmost"))
        elif self.middle_in_string():
            describe("plato-string-position-category", node("plato-middle"))
        elif self.rightmost_in_string():
            describe("plato-string-position-category", node("plato-rightmost"))

        describe("plato-bond-facet", self.bond_facet, bond_description=True)

        # No Length description here.  ``make-group`` attaches none; the Scheme's
        # single site is ``propose-group`` (groups.ss:816-818), which attaches one
        # with probability ``length-description-probability`` — 0.5^27 for a cold
        # 3-group, i.e. essentially never unless Length is already active.
        # Attaching one to every group made ``plato-one/two/three`` — and through
        # them ``plato-length`` — warm all run, and made every singleton clear the
        # Trace's "singleton with a length description" bar.

        # A letter-category description on a successor/predecessor group is what
        # makes horizontal bridges like [abc] -> [bcd] possible (groups.ss:44-46).
        if getattr(self.bond_facet, "name", "") == "plato-letter-category":
            # ``groups.ss:47`` takes the first object in *direction* order, not the
            # leftmost one.  The difference is the whole point of the description: a
            # leftward group over ``ab`` is the sequence b, a, and its initial letter
            # is ``b``.  Reading the leftmost letter instead hid every relation that
            # runs off the end of a leftward group — including the ``b -> c`` of
            # ``ab -> c``.
            describe("plato-letter-category", self._get_initial_letter_category())

    @property
    def length(self) -> int:
        return len(self.objects)

    def get_all_descriptions(self) -> list[Any]:
        """Return descriptions plus bond descriptions.

        Scheme: workspace-objects.ss:162-165 — groups include bond descriptions.
        """
        return list(self.descriptions) + list(self.bond_descriptions)

    def get_letters(self) -> list[Any]:
        """Every Letter under this group, left to right, at any nesting depth.

        Scheme: ``letters`` in ``new-group`` (groups.ss:83) —
        ``(apply append (tell-all objects 'get-letters))``.
        """
        letters: list[Any] = []
        for obj in self.objects:
            getter = getattr(obj, "get_letters", None)
            if getter is not None:
                letters.extend(getter())
            else:
                letters.append(obj)
        return letters

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
        """Group internal strength: bond factor against length factor, self-weighted.

        Scheme: ``calculate-internal-strength`` (groups.ss:392-410)::

            (bond-factor (* (tell bond-category 'get-degree-of-assoc)
                            (if (eq? group-bond-facet plato-letter-category) 1 1/2)))

        The bond factor is a property of the group's **category**, not of the
        strengths of the bonds it happens to contain: a sameness group is worth 100
        because sameness associates perfectly, whatever its members' bonds are
        currently scoring.  Averaging the constituent bonds' *overall* strength
        instead double-counted everything a bond's strength already folds in —
        facet, compatibility, ``11*sqrt(assoc)``, external support — and, worse,
        left a bond-less singleton with no bond factor at all, so its strength
        collapsed to the bare length factor of 5 and it died at the evaluator.  A
        singleton sameness group scores 92 here, which is what makes the 1-2-3
        reading of ``mrrjjj`` reachable.

        The length-factor table and the 0.98 self-weighting exponent are unchanged.
        """
        assoc = getattr(self.bond_category, "degree_of_assoc", None)
        base = float(assoc()) if assoc is not None else 0.0
        facet_name = getattr(self.bond_facet, "name", "")
        bond_factor = base if facet_name == "plato-letter-category" else base * 0.5

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

    def calculate_external_strength(self, rng: RNG | None = None) -> float:
        """External strength: 100 if spanning, otherwise local support.

        Scheme: groups.ss:411-414.

        *rng* is the drawing codelet's; see :meth:`get_local_density`.
        """
        if self.spans_whole_string():
            return 100.0
        return self._local_support(rng)

    def _local_support(self, rng: RNG | None = None) -> float:
        """Support from similar nearby groups.

        Scheme: groups.ss:384-391.
        First count truly disjoint supporting groups, then compute density
        and combine as density_adjustment * number_factor.
        """
        num_supporting = self.get_num_of_local_supporting_groups()
        if num_supporting == 0:
            return 0.0

        density = self.get_local_density(rng)
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

    def get_local_density(self, rng: RNG | None = None) -> float:
        """Density of similar groups in the local neighborhood.

        Scheme: groups.ss:354-383.
        If spanning, returns 100. Otherwise walks left/right neighbors,
        counting similar groups among them.

        Each step of the walk is a salience-weighted **stochastic** pick, and the
        reference re-rolls it on every strength update.  *rng* is the calling
        codelet's stream, threaded down from
        :meth:`WorkspaceStructure.update_strength`; ``None`` means no run context
        (see ``WorkspaceObject._pick_neighbor``).
        """
        if self.spans_whole_string():
            return 100.0

        if self.string is None:
            return 100.0

        # Walk neighbors in both directions
        left_neighbors = _walk_group_neighbors(self, "left", rng)
        right_neighbors = _walk_group_neighbors(self, "right", rng)
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

    def get_incompatible_bridges(self, bridge_orientation: str) -> list[Any]:
        """Built bridges this group's direction would contradict.

        Scheme: ``get-incompatible-bridges`` (groups.ss:287-293) — nothing at all
        for an undirected group, otherwise one candidate per constituent object.
        """
        if self.direction is None:
            return []
        result: list[Any] = []
        for obj in self.objects:
            bridge = self.get_incompatible_bridge(obj, bridge_orientation)
            if bridge is not None and bridge not in result:
                result.append(bridge)
        return result

    def get_incompatible_bridge(self, obj: Any, bridge_orientation: str) -> Any:
        """Scheme: ``get-incompatible-bridge`` (groups.ss:294-327).

        The mirror image of the bond's test (bonds.ss:89-122).  A *directed* group
        says "this material runs this way"; a bridge off one of its constituents
        says "this object plays the role of the leftmost/rightmost object over
        there".  Where the far object sits at an edge of its own string and
        carries a directed bond, the two claims can contradict — "leftmost maps to
        rightmost, but right maps to right" — and then the group has to beat the
        bridge to be built.
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
        if other_bond is None or not getattr(other_bond, "directed", False):
            return None

        direction_cm = self._direction_concept_mapping(other_bond)
        if direction_cm is None:
            return None

        from server.engine.bridges import _incompatible_cms

        return bridge if _incompatible_cms(direction_cm, string_position_cm) else None

    def _direction_concept_mapping(self, other_bond: Any) -> Any:
        """The ``DirCtgy`` mapping between this group's direction and *other_bond*'s.

        Scheme: the inline ``make-concept-mapping`` of groups.ss:313-320.
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
            slipnet = getattr(getattr(self.string, "workspace", None), "slipnet", None)
            label = getattr(slipnet, "nodes", {}).get("plato-identity") if slipnet else None
        return ConceptMapping(
            description_type1=direction_category,
            descriptor1=self.direction,
            description_type2=direction_category,
            descriptor2=other_bond.direction,
            label=label,
            object1=self,
            object2=other_bond,
        )

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

        Scheme: ``make-flipped-version`` (groups.ss:328-346).  A same-group has no
        direction to reverse and is returned unchanged, exactly as the Scheme
        returns ``self`` for ``plato-samegrp``.

        Reading ``>abc>`` as ``<cba<`` is what lets a thematic scout satisfy a
        Direction: opposite theme without abandoning the group it already has
        (themes.ss:996-1010), and it is how the crosswise mapping of §2.4.5 is
        reached at all.
        """
        from server.engine.slipnet import opposite_node

        # sameness groups have no direction; return self
        if self.direction is None:
            return self

        flipped = Group(
            string=self.string,
            group_category=opposite_node(self.group_category),
            bond_facet=self.bond_facet,
            direction=opposite_node(self.direction),
            objects=self.objects,
            bonds=[bond.flipped() for bond in self.group_bonds],
        )
        # The Scheme keeps the flipped group's id equal to the original's
        # (groups.ss:343) so that bridges to either version land in the same slot
        # of the proposed-bridge table.  Petacat keeps it for the same reason the
        # comment gives — the two are the same group seen two ways — and because
        # the builder has to recognise which existing group a flip replaces.
        flipped.id = self.id
        # groups.ss:344-345 — a Length description is carried across the flip.
        # Now that ``make-group`` no longer attaches one unconditionally (GR-1),
        # this is the only way the reversed reading keeps it.
        length_node = self._node("plato-length")
        if length_node is not None and self.description_type_present(length_node):
            attach_length_description(flipped)
        return flipped

    def _node(self, name: str) -> Any:
        """The Slipnet node called *name*, reached from the group's string."""
        slipnet = getattr(getattr(self.string, "workspace", None), "slipnet", None)
        if slipnet is None:
            slipnet = getattr(self.string, "slipnet", None)
        if slipnet is None:
            return None
        return getattr(slipnet, "nodes", {}).get(name)

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

    def __repr__(self) -> str:
        cat = getattr(self.group_category, "short_name", "?")
        objs = len(self.objects)
        return f"Group({cat}, {objs} objects, strength={self.strength:.0f})"


#: Group length -> the Slipnet node that names it.
#:
#: Scheme: ``*slipnet-numbers*`` (``slipnet.ss:476``), five long — there is no
#: ``plato-six``, so a group of six has no Length descriptor and that is faithful.
#:
#: The one definition.  ``codelet_dsl/builtins.py`` held a second copy of the same
#: five entries, spelled with the ``plato-`` prefix instead of adding it at the use
#: site; it imports this now.
PLATONIC_LENGTH_NODES = {
    1: "plato-one",
    2: "plato-two",
    3: "plato-three",
    4: "plato-four",
    5: "plato-five",
}


def attach_length_description(group: Group) -> bool:
    """Give *group* a Length description, if it can have one and hasn't got one.

    Scheme: ``attach-length-description`` (groups.ss:831-837) — a no-op when the
    group is already described on Length, and when its length is one the Slipnet
    cannot name (there are only ``plato-one`` .. ``plato-five``).

    Deliberately unconditional: *whether* to attach is the caller's decision, and
    the reference makes it in exactly four places — ``propose-group``
    stochastically (groups.ss:816-818), the flip (groups.ss:344-345), and the
    builder's two consolidation branches (groups.ss:732-733, 771).
    """
    length_type = group._node("plato-length")
    descriptor_node = PLATONIC_LENGTH_NODES.get(group.length)
    if length_type is None or descriptor_node is None:
        return False
    if group.description_type_present(length_type):
        return False
    descriptor = group._node(descriptor_node)
    if descriptor is None:
        return False

    from server.engine.descriptions import Description

    description = Description(group, length_type, descriptor)
    description.proposal_level = Description.BUILT
    group.descriptions.append(description)
    return True


def _disjoint_objects(obj1: Any, obj2: Any) -> bool:
    """Two objects are disjoint if their string positions don't overlap.

    Scheme: workspace-objects.ss:644-649.
    """
    return (
        obj1.right_string_pos < obj2.left_string_pos
        or obj1.left_string_pos > obj2.right_string_pos
    )


def _walk_group_neighbors(
    group: Group, direction: str, rng: RNG | None = None
) -> list[Any]:
    """Walk left or right from a group through *positional* neighbours.

    Scheme: the ``neighbors`` letrec inside ``get-local-density``
    (groups.ss:357-366)::

        (lambda (object choose-method)
          (let ((neighbor (tell object choose-method)))
            (if (not (exists? neighbor))
              '()
              (let ((group (tell neighbor 'get-enclosing-group)))
                (if (not (and (letter? neighbor) (exists? group)))
                    (cons neighbor (neighbors neighbor choose-method))
                    (cons group (neighbors group choose-method)))))))

    Two things distinguish it from the bond version (bonds.ss:137-145), and both
    matter.  It starts from the **group itself**, and it substitutes a letter's
    *enclosing group* for the letter — so a walk that steps onto a grouped letter
    continues from the far edge of that group and the group, not the letter, is
    what gets counted.  Otherwise a string already read as ``[m][rr][jjj]``
    would see letters in the denominator that the reference sees as groups, and
    the density that supports a new singleton would come out near zero.

    Following ``left_bond``/``right_bond`` pointers, as this used to, is a
    different walk again: it stops at the first unbonded slot, so a group with no
    bond hanging off its edge scored 100 by walking nowhere.
    """
    method = "choose_left_neighbor" if direction == "left" else "choose_right_neighbor"
    result: list[Any] = []
    current: Any = group

    while True:
        chooser = getattr(current, method, None)
        if chooser is None:
            # A hand-rolled test double rather than a real WorkspaceObject —
            # the same answer as "at the end of the string".
            break
        neighbor = chooser(rng)
        if neighbor is None or neighbor is current:
            break
        enclosing = getattr(neighbor, "enclosing_group", None)
        if enclosing is not None and not isinstance(neighbor, Group):
            neighbor = enclosing
        if neighbor is current:
            break
        result.append(neighbor)
        current = neighbor

    return result
