"""Group structures — collections of letters/subgroups with internal bonds.

A group is a structured collection of objects connected by bonds of the same
category, going in the same direction. Groups are both WorkspaceObjects
(they can participate in bridges) and WorkspaceStructures (they have strength).

Scheme source: groups.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.engine.formulas import pow_exact
from server.engine.slipnet import holds_role
from server.engine.workspace_objects import WorkspaceObject
from server.engine.run_binding import constants, current
from server.engine.workspace_structures import WorkspaceStructure
from server.engine.concept_mappings import ConceptMapping
from server.engine.descriptions import Description

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
        #
        # The relation is the link labelled with the node that plays ``dimension.bond_category``;
        # with no such dimension a group has no bond category.
        related = getattr(group_category, "get_related_node_by_role", None)
        self.bond_category = related("dimension.bond_category") if related else None

        self._attach_initial_descriptions()

    def _attach_initial_descriptions(self) -> None:
        """Describe the group the moment it is created.

        Scheme: ``make-group`` (groups.ss:20-54) plus ``attach-length-description``
        (groups.ss:831-837).  Without these a group is invisible to the bridge
        scouts — no descriptions means no concept-mappings — so problems whose
        answer turns on a whole-string group (``abc -> abcd``, ``abc -> aabbcc``)
        could never get off the ground.
        """
        slipnet = _slipnet_of(self)
        if slipnet is None:
            return
        # The program is configuration: the ``group`` rules of ``initial_description_rules`` (object
        # category, group category, bond category, direction, the position cascade of
        # ``groups.ss:34-42`` whole -> leftmost -> middle -> rightmost, bond facet, and the letter
        # category of a letter-category facet), applied in ``ordinal`` order (``initial_program.py``).
        #
        # No Length description is given here.  ``make-group`` attaches none; the Scheme's single
        # site is ``propose-group`` (groups.ss:816-818), which attaches one with probability
        # ``length-description-probability`` (0.5^27 for a cold 3-group).  Attaching one to every
        # group made ``plato-one/two/three`` -- and through them ``plato-length`` -- warm all run,
        # and made every singleton clear the Trace's "singleton with a length description" bar.
        from server.engine.initial_program import describe_group

        describe_group(self, slipnet, current().meta)

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
        # One pass for both extremes (WP9): the same ``min`` and ``max`` over the same
        # positions, without two generator expressions.
        it = iter(string_objects)
        first = next(it)
        string_left = first.left_string_pos
        string_right = first.right_string_pos
        for o in it:
            p = o.left_string_pos
            if p < string_left:
                string_left = p
            p = o.right_string_pos
            if p > string_right:
                string_right = p
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
        rc = constants()
        base = float(assoc()) if assoc is not None else rc.group_bond_factor_no_category
        letter_facet = holds_role(self.bond_facet, "dimension.letter_category")
        bond_factor = (
            base if letter_facet else base * rc.group_bond_facet_other_multiplier
        )

        # Length factor: a step table (1, 2, 3) with a tail (4 or more)
        length = self.length
        if length == 1:
            length_factor = rc.group_length_factor_1
        elif length == 2:
            length_factor = rc.group_length_factor_2
        elif length == 3:
            length_factor = rc.group_length_factor_3
        else:
            length_factor = rc.group_length_factor_4_plus

        # Weighted combination with self-weighting exponent
        if bond_factor <= 0:
            return float(length_factor)

        bf_weight = bond_factor ** rc.group_bond_factor_weight_exponent
        lf_weight = 100.0 - bf_weight
        total = bf_weight + lf_weight
        if total == 0:
            return 0.0
        return round((bond_factor * bf_weight + length_factor * lf_weight) / total)

    def calculate_external_strength(self, rng: RNG) -> float:
        """External strength: 100 if spanning, otherwise local support.

        Scheme: groups.ss:411-414.

        *rng* is the drawing codelet's; see :meth:`get_local_density`.
        """
        if self.spans_whole_string():
            return constants().group_spanning_external_strength
        return self._local_support(rng)

    def _local_support(self, rng: RNG) -> float:
        """Support from similar nearby groups.

        Scheme: groups.ss:384-391.
        First count truly disjoint supporting groups, then compute density
        and combine as density_adjustment * number_factor.
        """
        rc = constants()
        num_supporting = self.get_num_of_local_supporting_groups()
        if num_supporting == 0:
            return rc.group_local_support_unsupported

        density = self.get_local_density(rng)
        adjusted_density = 100.0 * pow_exact(density / 100.0, rc.local_support_density_exponent)
        number_factor = min(
            rc.local_support_number_factor_ceiling,
            rc.local_support_number_factor_base
            ** (1.0 / max(rc.local_support_number_denominator_floor, num_supporting ** rc.local_support_number_exponent)),
        )
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

    def get_local_density(self, rng: RNG) -> float:
        """Density of similar groups in the local neighborhood.

        Scheme: groups.ss:354-383.
        If spanning, returns 100. Otherwise walks left/right neighbors,
        counting similar groups among them.

        Each step of the walk is a salience-weighted **stochastic** pick, and the
        reference re-rolls it on every strength update.  *rng* is the calling
        codelet's stream, threaded down from
        :meth:`WorkspaceStructure.update_strength`.
        """
        rc = constants()
        if self.spans_whole_string():
            return rc.group_local_density_spanning

        if self.string is None:
            return rc.group_local_density_no_string

        # Walk neighbors in both directions
        # Trace seam: the walk's draws concern this group (lockstep spec §5.3).
        previous = rng.trace_about(self)
        left_neighbors = _walk_group_neighbors(self, "left", rng)
        right_neighbors = _walk_group_neighbors(self, "right", rng)
        rng.trace_about(previous)
        other_objects = left_neighbors + right_neighbors
        num_of_objects = len(other_objects)

        if num_of_objects == 0:
            return rc.group_local_density_no_neighbours

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
        # ``remq-duplicates`` keeps the LAST occurrence of a repeated group
        # (utilities.ss:915-927), and the order is the fight order.
        encs = [
            enc
            for enc in (getattr(obj, "enclosing_group", None) for obj in self.objects)
            if enc is not None
        ]
        result: list[Group] = []
        seen: set[int] = set()
        for enc in reversed(encs):
            if id(enc) not in seen:
                seen.add(id(enc))
                result.append(enc)
        result.reverse()
        return [g for g in result if g is not self]

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
            "horizontal_bridge"
            if bridge_orientation == constants().vocab.bridge_orientation_horizontal
            else "vertical_bridge",
            None,
        )
        if bridge is None:
            return None

        string_position_cm = None
        for cm in getattr(bridge, "concept_mappings", ()):
            if holds_role(cm.description_type1, "dimension.string_position"):
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
        from server.engine.bridges import _label_node
        if self.direction is None or other_bond.direction is None:
            return None
        direction_category = getattr(self.direction, "category", None)
        if direction_category is None:
            return None

        # ``_incompatible_cms`` compares labels by identity against the bridge's own
        # concept-mappings; ``_label_node`` hands back the real identity node.
        label = _label_node(self.direction, other_bond.direction)
        return ConceptMapping(
            description_type1=direction_category,
            descriptor1=self.direction,
            description_type2=direction_category,
            descriptor2=other_bond.direction,
            label=label,
            object1=self,
            object2=other_bond,
        )

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
        flipped.id_num = self.id_num  # groups.ss:343
        # groups.ss:344-345 — a Length description is carried across the flip.
        # Now that ``make-group`` no longer attaches one unconditionally,
        # this is the only way the reversed reading keeps it.
        slipnet = _slipnet_of(self)
        length_node = slipnet.roles.dimension_length if slipnet is not None else None
        if length_node and self.description_type_present(length_node):
            attach_length_description(flipped)
        return flipped

    def _get_initial_letter_category(self) -> Any:
        """Get the letter-category descriptor of the first object in direction order.

        Scheme: groups.ss:77 — (tell (1st ordered-objects) 'get-descriptor-for plato-letter-category)
        """
        ordered = self.objects
        if holds_role(self.direction, "direction.left"):
            ordered = list(reversed(self.objects))
        if not ordered:
            return None
        first = ordered[0]
        # Look for letter-category description
        for d in getattr(first, "descriptions", []):
            if holds_role(d.description_type, "dimension.letter_category"):
                return d.descriptor
        # Fallback for Letter objects
        return getattr(first, "letter_category", None)

    def __repr__(self) -> str:
        cat = getattr(self.group_category, "short_name", "?")
        objs = len(self.objects)
        return f"Group({cat}, {objs} objects, strength={self.strength:.0f})"


def _slipnet_of(group: Any) -> Any:
    """The Slipnet reached from the group's string, or ``None``."""
    slipnet = getattr(getattr(group.string, "workspace", None), "slipnet", None)
    if slipnet is None:
        slipnet = getattr(group.string, "slipnet", None)
    return slipnet


def attach_length_description(group: Group) -> bool:
    """Give *group* a Length description, if it can have one and hasn't got one.

    Scheme: ``attach-length-description`` (groups.ss:831-837) — a no-op when the
    group is already described on Length, and when its length is one the Slipnet
    cannot name (the ladder has no node with that ``numeric_value``).

    Deliberately unconditional: *whether* to attach is the caller's decision, and
    the reference makes it in exactly four places — ``propose-group``
    stochastically (groups.ss:816-818), the flip (groups.ss:344-345), and the
    builder's two consolidation branches (groups.ss:732-733, 771).
    """
    # A letter's platonic length is ``plato-one`` (workspace-objects.ss:57); callers
    # such as the translated-rule pass may hand one in (answers.ss:1090-1091).
    slipnet = _slipnet_of(group)
    length_type = slipnet.roles.dimension_length if slipnet is not None else None
    # The node whose ``numeric_value`` is the group's length; none (a gapped ladder, or a
    # group longer than the ladder) means no Length description.
    descriptor = (
        slipnet.alphabet.number_for(group.length) if slipnet is not None else None
    )
    if not length_type or descriptor is None:
        return False
    if group.description_type_present(length_type):
        return False

    description = Description(group, length_type, descriptor)
    description.proposal_level = constants().vocab.proposal_level_built
    group.descriptions.insert(0, description)
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
    group: Group, direction: str, rng: RNG
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
        neighbor = getattr(current, method)(rng)
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
