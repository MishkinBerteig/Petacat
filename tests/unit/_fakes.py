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


def _msc_tables() -> tuple[dict[str, frozenset[str]], dict[str, str]]:
    """The Metacat Standard Configuration's role bindings and relation rows by node name, so
    a fake named like an MSC node plays the roles and the relation that node plays."""
    import json
    from pathlib import Path

    seed = Path(__file__).resolve().parents[2] / "seed_data"
    roles: dict[str, set[str]] = {}
    for row in json.loads((seed / "roles.json").read_text())["node_roles"]:
        roles.setdefault(row["node_name"], set()).add(row["role"])
    relations = {
        row["node_name"]: row["name"]
        for row in json.loads((seed / "theme_relations.json").read_text())
        if row.get("node_name")
    }
    return {k: frozenset(v) for k, v in roles.items()}, relations


_MSC_ROLES, _MSC_RELATIONS = _msc_tables()


class FakeNode:
    """Stand-in for a slipnet ``SlipnetNode``.

    Only the attributes/methods the workspace structures read are provided.
    ``fully_active`` is an explicit boolean the test controls, so relevance
    logic is deterministic and independent of real activation thresholds.
    """

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def __init__(
        self,
        name: str = "plato-x",
        *,
        short_name: str | None = None,
        conceptual_depth: float = 0.0,
        activation: float = 0.0,
        fully_active: bool = False,
        intrinsic_link_length: int = 0,
        related: dict[str, FakeNode] | None = None,
        max_activation: float = 100.0,
        roles: frozenset[str] | set[str] = frozenset(),
        numeric_value: int | None = None,
    ) -> None:
        self.name = name
        # A fake named like an MSC node plays that node's roles and relation (the engine reads
        # roles and relations, never names).
        self.roles = frozenset(roles) | _MSC_ROLES.get(name, frozenset())
        self.relation = _MSC_RELATIONS.get(name)
        #: The Slipnet's relation nodes by name; a test that wants identity labels sets it.
        self.relations: dict[str, FakeNode] = {}
        self.numeric_value = numeric_value
        #: Relation name -> neighbour, for ``get_related_node``.  A Group derives
        #: its bond category from its group category this way (groups.ss:79).
        self.related: dict[str, FakeNode] = dict(related) if related else {}
        self.short_name = (
            short_name if short_name is not None else name.replace("plato-", "")
        )
        self.conceptual_depth = conceptual_depth
        self.activation = activation
        self.activation_buffer: float = 0.0
        self.intrinsic_link_length = intrinsic_link_length
        #: ``%max-activation%``.  A real node resolves this from the run's metadata
        #: (``ActivationParams``); a fake takes the shipped value unless a test says
        #: otherwise.  Read by ``ConceptMapping.build_concept_pattern``.
        self.max_activation = max_activation
        self._fully_active = fully_active
        # Link collections consulted by ConceptMapping._find_slipnet_link.
        self.lateral_links: list[FakeLink] = []
        self.lateral_sliplinks: list[FakeLink] = []
        self.frozen = False

    def degree_of_assoc(self) -> float:
        """Scheme: ``get-degree-of-assoc`` on a slipnode (slipnet.ss:90-91) —
        ``100 - (fully-active? ? shrunk-link-length : intrinsic-link-length)``,
        with the shrunk length 40% of the intrinsic one (slipnet.ss:191)."""
        if self.intrinsic_link_length is None:
            return 0.0
        if self.fully_active():
            return max(0.0, 100.0 - round(0.4 * self.intrinsic_link_length))
        return max(0.0, 100.0 - self.intrinsic_link_length)

    def fully_active(self) -> bool:
        return self._fully_active

    def get_related_node(self, relation: Any) -> FakeNode | None:
        """Scheme: ``get-related-node`` (slipnet.ss:114-129), reduced to a lookup."""
        name = relation if isinstance(relation, str) else getattr(relation, "name", "")
        if name == "plato-identity":
            return self
        return self.related.get(name)

    def get_related_node_by_role(self, role: str) -> FakeNode | None:
        """``get_related_node`` with the link label named by its role: the fake's ``related``
        is keyed by node name, and the role names the MSC node that plays it."""
        for name, node in self.related.items():
            if role in _MSC_ROLES.get(name, ()):
                return node
        return None

    def activate_from_workspace(self) -> None:
        """Mirror ``SlipnetNode.activate_from_workspace``.

        The jolt is ``%workspace-activation%``, which a real node takes from the run's
        metadata.  A fake has none, so it uses its own ceiling — the two share the
        shipped value of 100 — rather than writing a fifth copy of the number.
        """
        if not self.frozen:
            self.activation_buffer += self.max_activation

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
    populate exactly the collection the unit under test iterates. ``length``,
    ``string_type`` and ``justify_mode`` mirror the fields workspace objects
    read for spanning / string-type-dependent logic.
    """

    def __init__(
        self,
        *,
        objects: list[Any] | None = None,
        letters: list[Any] | None = None,
        groups: list[Any] | None = None,
        length: int = 0,
        string_type: str = "initial",
        justify_mode: bool = False,
    ) -> None:
        self.objects = objects if objects is not None else []
        self.letters = letters if letters is not None else []
        self.groups = groups if groups is not None else []
        self.length = length
        self.string_type = string_type
        self.justify_mode = justify_mode


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
