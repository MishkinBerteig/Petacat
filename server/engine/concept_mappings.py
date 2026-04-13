"""Concept mappings between descriptions across strings.

A ConceptMapping connects two descriptions (one from each side of a bridge)
and characterizes how they relate: identity, slippage, or coattail.

Scheme source: concept-mappings.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.engine.slipnet import Slipnet, SlipnetLink, SlipnetNode


# Names of slipnet nodes considered non-distinguishing (generic categories).
# These correspond to plato-letter, plato-group, and the five number nodes
# (*slipnet-numbers*) in the Scheme source.
_NON_DISTINGUISHING_NAMES: set[str] = {
    "plato-letter",
    "plato-group",
    "plato-one",
    "plato-two",
    "plato-three",
    "plato-four",
    "plato-five",
}


class ConceptMapping:
    """A mapping between two conceptual descriptions."""

    def __init__(
        self,
        description_type1: SlipnetNode,
        descriptor1: SlipnetNode,
        description_type2: SlipnetNode,
        descriptor2: SlipnetNode,
        label: SlipnetNode | None = None,
        object1: Any | None = None,
        object2: Any | None = None,
        slipnet: Slipnet | None = None,
    ) -> None:
        self.description_type1 = description_type1
        self.descriptor1 = descriptor1
        self.description_type2 = description_type2
        self.descriptor2 = descriptor2
        self.label = label  # identity, opposite, successor, predecessor, or None
        self.object1 = object1  # workspace object on one side of the bridge
        self.object2 = object2  # workspace object on the other side
        self.slipnet_link: SlipnetLink | None = self._find_slipnet_link()

    @property
    def is_identity(self) -> bool:
        """Both descriptors are the same concept."""
        return self.descriptor1 is self.descriptor2

    @property
    def is_slippage(self) -> bool:
        """Descriptors differ — a conceptual substitution."""
        return not self.is_identity

    def strength(self) -> float:
        """Concept mapping strength.

        Scheme: concept-mappings.ss:130-135.
        - Identity: 100
        - Labeled slippage: degree_of_assoc * (1 + (depth/100)^2)
        - Unlabeled slippage: 5
        """
        if self.is_identity:
            return 100.0

        if self.label is not None:
            # Find the link between descriptor1 and descriptor2
            assoc = self._degree_of_association()
            depth = self.conceptual_depth
            bonus = 1.0 + (depth / 100.0) ** 2
            return min(100.0, round(assoc * bonus))

        return 5.0  # Unlabeled slippage

    def slippability(self) -> float:
        """How likely this mapping is to 'slip'.

        Scheme: concept-mappings.ss:136-141.
        - Identity: 100
        - Slippage: degree_of_assoc * (1 - (depth/100)^2)
        """
        if self.is_identity:
            return 100.0

        assoc = self._degree_of_association()
        depth = self.conceptual_depth
        penalty = 1.0 - (depth / 100.0) ** 2
        return max(0.0, round(assoc * penalty))

    @property
    def conceptual_depth(self) -> float:
        """Average conceptual depth of the two descriptors.

        Scheme: concept-mappings.ss:127-129.
        (average (tell descriptor1 'get-conceptual-depth)
                 (tell descriptor2 'get-conceptual-depth))
        """
        return (
            self.descriptor1.conceptual_depth
            + self.descriptor2.conceptual_depth
        ) / 2.0

    def _find_slipnet_link(self) -> SlipnetLink | None:
        """Find the slipnet link between descriptor1 and descriptor2.

        Scheme: concept-mappings.ss:25-36.
        The link is usually a lateral-sliplink; however, it can be a lateral-link
        in the case of LettCtgy/Length pred/succ "slippages" such as
        LettCtgy:a=(succ)=>b or Length:two=(pred)=>one.
        """
        if self.is_identity:
            return None
        # For letter-category or length description types, look at lateral links
        # (which include successor/predecessor between adjacent letters/numbers).
        # For all other types, look at lateral sliplinks.
        dt1_name = getattr(self.description_type1, "name", "")
        if dt1_name in ("plato-letter-category", "plato-length"):
            links_to_search = getattr(self.descriptor1, "lateral_links", [])
        else:
            links_to_search = getattr(self.descriptor1, "lateral_sliplinks", [])
        for link in links_to_search:
            if link.to_node is self.descriptor2:
                return link
        return None

    def _degree_of_association(self) -> float:
        """Degree of association between the two descriptors.

        Scheme: concept-mappings.ss:119-125.
        - Identity: 100
        - Has slipnet link: link's degree of association
        - Unlabeled slippage (no link): 5
        """
        if self.is_identity:
            return 100.0
        if self.slipnet_link is not None:
            return self.slipnet_link.degree_of_association()
        # Unlabeled LettCtgy/Length "slippage" such as LettCtgy:m=>j
        return 5.0

    def relevant(self) -> bool:
        """True if both description types are fully active in the slipnet.

        Scheme: concept-mappings.ss:107-109.
        """
        return (
            self.description_type1.fully_active()
            and self.description_type2.fully_active()
        )

    def distinguishing(self) -> bool:
        """True if both descriptors distinguish their objects from string-siblings.

        Scheme: concept-mappings.ss:110-113.
        A descriptor is NOT distinguishing if it is a generic category node
        (plato-letter, plato-group, or a number node), or if all sibling
        objects in the string share it.

        Also returns False for identity mappings where descriptor1 is 'whole',
        since spanning-group identity CMs should not be considered distinguishing.

        Requires object1 and object2 to be set.
        """
        if self.object1 is None or self.object2 is None:
            return True  # Conservative default when objects unavailable
        # Identity mapping of 'whole' is not distinguishing
        if self.is_identity and getattr(self.descriptor1, "name", "") == "plato-whole":
            return False
        return (
            self._descriptor_is_distinguishing(self.descriptor1, self.object1)
            and self._descriptor_is_distinguishing(self.descriptor2, self.object2)
        )

    @staticmethod
    def _descriptor_is_distinguishing(descriptor: SlipnetNode, obj: Any) -> bool:
        """Check if a descriptor distinguishes an object from its string-siblings.

        Scheme: workspace-objects.ss:223-244.
        Returns False if the descriptor is a generic category (letter, group,
        or a number node). Otherwise checks whether all sibling objects in the
        same string share the same descriptor.
        """
        desc_name = getattr(descriptor, "name", "")
        if desc_name in _NON_DISTINGUISHING_NAMES:
            return False

        string = getattr(obj, "string", None)
        if string is None:
            return True

        # Gather sibling objects of the same kind (letters vs groups)
        from server.engine.groups import Group

        if isinstance(obj, Group):
            other_objects = [
                g for g in getattr(string, "groups", [])
                if g is not obj
            ]
        else:
            other_objects = [
                ltr for ltr in getattr(string, "letters", getattr(string, "objects", []))
                if ltr is not obj
            ]

        if not other_objects:
            return True  # No siblings to compare against

        # Check if all other objects share this descriptor
        other_descriptors = []
        for other in other_objects:
            for d in getattr(other, "descriptions", []):
                other_descriptors.append(d.descriptor)

        # If all siblings have this descriptor, it's not distinguishing
        # (The Scheme checks: is descriptor NOT a member of other-descriptors)
        all_have_it = all(
            any(
                d.descriptor is descriptor
                for d in getattr(other, "descriptions", [])
            )
            for other in other_objects
        )
        return not all_have_it

    def relevant_distinguishing(self) -> bool:
        """True if this CM is both relevant and distinguishing.

        Scheme: concept-mappings.ss:114-115.
        """
        return self.relevant() and self.distinguishing()

    def symmetric_mapping(self) -> ConceptMapping:
        """Create the reverse mapping (swap descriptor1/descriptor2).

        Scheme: concept-mappings.ss:154-159.
        For identity mappings, returns self (swapping identical descriptors
        is a no-op).
        """
        if self.is_identity:
            return self
        return ConceptMapping(
            description_type1=self.description_type2,
            descriptor1=self.descriptor2,
            description_type2=self.description_type1,
            descriptor2=self.descriptor1,
            label=self.label,
            object1=self.object1,
            object2=self.object2,
        )

    def is_symmetric(self, other: ConceptMapping) -> bool:
        """True if *other* is the symmetric (reversed) version of this CM.

        Scheme: concept-mappings.ss:151-153.
        """
        return (
            other.descriptor1 is self.descriptor2
            and other.descriptor2 is self.descriptor1
        )

    @property
    def opposite_mapping(self) -> bool:
        """True if the label is 'opposite' or this is a whole<->single mapping.

        Scheme: concept-mappings.ss:101-106 (identity/opposite-mapping? includes
        whole/single; opposite-mapping? at line 101 is just label == opposite).
        """
        label_name = getattr(self.label, "name", "") if self.label else ""
        if label_name == "plato-opposite":
            return True
        # whole <-> single is treated as an opposite-like mapping
        d1_name = getattr(self.descriptor1, "name", "")
        d2_name = getattr(self.descriptor2, "name", "")
        if (d1_name == "plato-whole" and d2_name == "plato-single") or (
            d1_name == "plato-single" and d2_name == "plato-whole"
        ):
            return True
        return False

    @property
    def bond_concept_mapping(self) -> bool:
        """True if the description type is bond-category or bond-facet.

        Scheme: concept-mappings.ss:80-82.
        """
        dt_name = getattr(self.description_type1, "name", "")
        return dt_name in ("plato-bond-category", "plato-bond-facet")

    def activate_descriptions(self) -> None:
        """Activate the description-type and descriptor nodes in the slipnet.

        Scheme: concept-mappings.ss:161-164.
        Sets activation to 100 for all four nodes (both description types
        and both descriptors).
        """
        self.description_type1.activation = 100.0
        self.descriptor1.activation = 100.0
        self.description_type2.activation = 100.0
        self.descriptor2.activation = 100.0

    def activate_label(self) -> None:
        """Activate the label node in the slipnet.

        Scheme: concept-mappings.ss:165-171.
        Activates the label node and flushes its activation buffer so the
        activation shows up immediately in the trace before the CM event.
        """
        if self.label is not None:
            # activate-from-workspace: set to full activation
            self.label.activation = 100.0
            # flush-activation-buffer: apply any pending buffer, then clear it
            pending = self.label.activation_buffer
            if pending != 0.0:
                self.label.activation = max(
                    0.0, min(100.0, self.label.activation + pending)
                )
                self.label.activation_buffer = 0.0

    def get_concept_pattern(self) -> list[tuple[SlipnetNode, float]]:
        """Return a concept activation pattern suitable for theme computation.

        Scheme: concept-mappings.ss:142-150.
        Returns a list of (node, max_activation) pairs for the description type,
        both descriptors, and the label (if any).
        """
        max_activation = 100.0
        pattern: list[tuple[SlipnetNode, float]] = [
            (self.description_type1, max_activation),
            (self.descriptor1, max_activation),
            (self.descriptor2, max_activation),
        ]
        if self.label is not None:
            pattern.append((self.label, max_activation))
        return pattern

    def is_compatible(self, other: ConceptMapping) -> bool:
        """Two CMs are compatible if they don't assign conflicting mappings
        to the same description type."""
        if self.description_type1 is other.description_type1:
            return self.descriptor1 is other.descriptor1
        if self.description_type2 is other.description_type2:
            return self.descriptor2 is other.descriptor2
        return True

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ConceptMapping):
            return NotImplemented
        return (
            self.description_type1 is other.description_type1
            and self.descriptor1 is other.descriptor1
            and self.description_type2 is other.description_type2
            and self.descriptor2 is other.descriptor2
        )

    def __hash__(self) -> int:
        return hash((
            id(self.description_type1),
            id(self.descriptor1),
            id(self.description_type2),
            id(self.descriptor2),
        ))

    def __repr__(self) -> str:
        d1 = getattr(self.descriptor1, "short_name", "?")
        d2 = getattr(self.descriptor2, "short_name", "?")
        lbl = getattr(self.label, "short_name", "?") if self.label else "none"
        return f"CM({d1}->{d2}, {lbl})"
