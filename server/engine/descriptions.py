"""Description structures attached to workspace objects.

A Description associates a description_type (e.g., plato-letter-category)
with a descriptor (e.g., plato-a) on a workspace object.

Scheme source: descriptions.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.engine.workspace_structures import WorkspaceStructure

if TYPE_CHECKING:
    from server.engine.slipnet import SlipnetNode


def _contains(outer: Any, inner: Any) -> bool:
    """Check if outer object contains inner object (for groups).

    Scheme: workspace-objects.ss — (contains? object other-object).
    A group contains another object if the inner object is a nested member.
    """
    if not hasattr(outer, "objects"):
        return False
    # Check if inner is a direct or nested member of outer
    nested_member = getattr(outer, "nested_member", None)
    if nested_member is not None:
        return nested_member(inner)
    # Fallback: check direct membership
    return inner in getattr(outer, "objects", [])


class Description(WorkspaceStructure):
    """A semantic description attached to a workspace object."""

    def __init__(
        self,
        obj: Any,  # WorkspaceObject
        description_type: SlipnetNode,
        descriptor: SlipnetNode,
    ) -> None:
        super().__init__()
        self.object = obj
        self.description_type = description_type
        self.descriptor = descriptor

    @property
    def descriptor_activation(self) -> float:
        """Activation of the descriptor node."""
        return self.descriptor.activation

    def calculate_internal_strength(self) -> float:
        """Internal strength = descriptor's conceptual depth.

        Scheme: descriptions.ss:82-83.
        """
        return float(self.descriptor.conceptual_depth)

    def calculate_external_strength(self) -> float:
        """External strength = average(local_support, description_type activation).

        Scheme: descriptions.ss:84-86.
        (average (tell self 'calculate-local-support)
                 (tell description-type 'get-activation))
        """
        local = self.calculate_local_support()
        activation = self.description_type.activation
        return (local + activation) / 2.0

    def calculate_local_support(self) -> float:
        """Count of other objects in the string with the same description type.

        Scheme: descriptions.ss:87-101.
        Mapped to 0-100 scale: 0->0, 1->20, 2->60, 3->90, >=4->100.
        Excludes objects that contain or are contained by this object.
        """
        if self.object is None or self.object.string is None:
            return 0.0

        string = self.object.string
        objects = getattr(string, "objects", [])
        count = 0
        for other in objects:
            if other is self.object:
                continue
            # Skip objects where one contains the other
            if _contains(self.object, other) or _contains(other, self.object):
                continue
            # Check if other has a description with the same description_type
            for d in getattr(other, "descriptions", []):
                if d.description_type is self.description_type:
                    count += 1
                    break

        if count == 0:
            return 0.0
        elif count == 1:
            return 20.0
        elif count == 2:
            return 60.0
        elif count == 3:
            return 90.0
        else:
            return 100.0

    @property
    def bond_description(self) -> bool:
        """True if description_type is bond-category or bond-facet.

        Scheme: descriptions.ss:69-71.
        """
        dt_name = getattr(self.description_type, "name", "")
        return dt_name in ("plato-bond-category", "plato-bond-facet")

    def is_relevant(self) -> bool:
        """A description is relevant if its description_type is fully active."""
        return self.description_type.fully_active()

    def is_distinguishing(self) -> bool:
        """A description is distinguishing if not all objects in the string
        share the same descriptor for this description type."""
        if self.object is None or self.object.string is None:
            return True
        string = self.object.string
        objects = getattr(string, "objects", [])
        if len(objects) <= 1:
            return True
        for obj in objects:
            if obj is self.object:
                continue
            has_same = any(
                d.description_type is self.description_type
                and d.descriptor is self.descriptor
                for d in getattr(obj, "descriptions", [])
            )
            if not has_same:
                return True
        return False

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Description):
            return NotImplemented
        return (
            self.description_type is other.description_type
            and self.descriptor is other.descriptor
            and self.object is other.object
        )

    def __hash__(self) -> int:
        return hash((id(self.description_type), id(self.descriptor), id(self.object)))

    def __repr__(self) -> str:
        dt = getattr(self.description_type, "short_name", "?")
        d = getattr(self.descriptor, "short_name", "?")
        return f"Description({dt}:{d})"
