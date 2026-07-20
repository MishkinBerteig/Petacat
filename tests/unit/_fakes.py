"""Lightweight deterministic test doubles for engine unit tests.

These fakes let a unit test isolate a single engine class (Description,
ConceptMapping, Bond, Group, ...) by completely replacing its collaborators
(SlipnetNode, SlipnetLink, workspace strings/objects) with hand-rolled stubs.

Design goals:
  * No randomness, no I/O, no database — every attribute is caller-supplied.
  * Only the surface actually consumed by the engine is implemented, so a
    test reads as "these are exactly the inputs this unit depends on".
  * Prefixed with ``_`` so pytest never collects this module as tests.
"""

from __future__ import annotations

from typing import Any


class FakeNode:
    """Stand-in for a slipnet ``SlipnetNode``.

    Only the attributes/methods the workspace structures read are provided.
    ``fully_active`` is an explicit boolean the test controls, so relevance
    logic is deterministic and independent of real activation thresholds.
    """

    def __init__(
        self,
        name: str = "plato-x",
        *,
        short_name: str | None = None,
        conceptual_depth: float = 0.0,
        activation: float = 0.0,
        fully_active: bool = False,
        intrinsic_link_length: int = 0,
    ) -> None:
        self.name = name
        self.short_name = (
            short_name if short_name is not None else name.replace("plato-", "")
        )
        self.conceptual_depth = conceptual_depth
        self.activation = activation
        self.activation_buffer: float = 0.0
        self.intrinsic_link_length = intrinsic_link_length
        self._fully_active = fully_active
        # Link collections consulted by ConceptMapping._find_slipnet_link.
        self.lateral_links: list[FakeLink] = []
        self.lateral_sliplinks: list[FakeLink] = []

    def fully_active(self) -> bool:
        return self._fully_active

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FakeNode({self.name})"


class FakeLink:
    """Stand-in for a slipnet ``SlipnetLink`` with a fixed association degree."""

    def __init__(self, to_node: FakeNode, *, degree: float = 0.0, label_node: FakeNode | None = None) -> None:
        self.to_node = to_node
        self.label_node = label_node
        self._degree = degree

    def degree_of_association(self) -> float:
        return self._degree


class FakeString:
    """Stand-in for a workspace string container.

    ``objects``/``letters``/``groups`` are independent lists so a test can
    populate exactly the collection the unit under test iterates.
    """

    def __init__(
        self,
        *,
        objects: list[Any] | None = None,
        letters: list[Any] | None = None,
        groups: list[Any] | None = None,
    ) -> None:
        self.objects = objects if objects is not None else []
        self.letters = letters if letters is not None else []
        self.groups = groups if groups is not None else []


class FakeObject:
    """Stand-in for a workspace letter/object carrying descriptions.

    Deliberately has NO ``objects`` attribute so containment checks treat it
    as an atomic (non-group) object.  Use :class:`FakeContainer` for groups.
    """

    def __init__(
        self,
        *,
        string: FakeString | None = None,
        descriptions: list[Any] | None = None,
    ) -> None:
        self.string = string
        self.descriptions = descriptions if descriptions is not None else []


class FakeContainer(FakeObject):
    """Stand-in for a group-like object that can contain other objects."""

    def __init__(
        self,
        *,
        string: FakeString | None = None,
        descriptions: list[Any] | None = None,
        objects: list[Any] | None = None,
    ) -> None:
        super().__init__(string=string, descriptions=descriptions)
        self.objects = objects if objects is not None else []

    def nested_member(self, other: Any) -> bool:
        return other in self.objects


class FakeDescription:
    """Stand-in for a Description entry stored on ``object.descriptions``."""

    def __init__(self, description_type: FakeNode, descriptor: FakeNode) -> None:
        self.description_type = description_type
        self.descriptor = descriptor
