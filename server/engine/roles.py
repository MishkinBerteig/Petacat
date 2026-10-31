"""The role vocabulary: the names the engine owns for concepts the configuration supplies.

Configuration-source plan, section 3.2.  A *role* is an engine-defined name for a concept
(``dimension.length``, ``position.leftmost``, ``evaluator.bond``).  The configuration binds
each role to a node or codelet type through the ``slipnet_node_roles`` and
``codelet_type_roles`` tables; this module owns only the names, so it contains no node or
codelet-type names at all.

* ``ROLES`` is the vocabulary: ``RoleSpec(name, target_kind, cardinality)``.  A role is never
  required, and the node bound to a role is never checked for looking right.
* ``Roles`` is the frozen record the Slipnet resolves once, at ``Slipnet.from_metadata``.
  ``slipnet.roles.dimension_length`` (the role name with dots turned into underscores) is the
  bound node, or the role's ``Absent`` token when nothing is bound.  An ordered role is a
  tuple of what is bound, in ordinal order (a gap is not in the tuple; nothing bound is
  ``()``).  A role of kind ``codelet_type`` resolves to that type's ``CodeletSpec``.
  ``Roles`` never holds ``None``.
* ``Absent`` is the token for a role nothing holds.  It is frozen, falsy, node-shaped and
  identical only to itself, which keeps ``None is None`` out of role comparisons: with a
  role absent, a missing label (``None``) is not mistaken for the role's node.  There is one
  token per role (``absent(role)``), so two absent roles never compare equal.  Guard with
  ``if roles.x:`` or ``x is not absent(...)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from operator import itemgetter
from typing import Any, Iterable, Mapping

NODE = "node"
CODELET_TYPE = "codelet_type"
ONE = "one"
ORDERED = "ordered"


@dataclass(frozen=True)
class RoleSpec:
    """One name of the vocabulary."""

    name: str
    target_kind: str  # NODE or CODELET_TYPE
    cardinality: str  # ONE or ORDERED

    @property
    def attr(self) -> str:
        """The attribute of ``Roles`` that holds this role: dots become underscores."""
        return self.name.replace(".", "_")


def _one(*names: str, kind: str = NODE) -> tuple[RoleSpec, ...]:
    return tuple(RoleSpec(n, kind, ONE) for n in names)


ROLES: tuple[RoleSpec, ...] = (
    _one(
        "dimension.direction", "dimension.group_category", "dimension.alphabetic_position",
        "dimension.letter_category", "dimension.length", "dimension.object_category",
        "dimension.string_position", "dimension.bond_facet", "dimension.bond_category",
        "position.whole", "position.leftmost", "position.middle", "position.rightmost",
        "position.single",
        "direction.left", "direction.right",
        "object.letter", "object.group",
        "bond_category.sameness",
        "group_category.sameness", "group_category.successor", "group_category.predecessor",
        "alphabet.first_marker", "alphabet.last_marker",
    )
    + (
        RoleSpec("rule.dimension_order", NODE, ORDERED),
        RoleSpec("answer.description_dimension", NODE, ORDERED),
    )
    + _one(
        "evaluator.bond", "evaluator.group", "evaluator.description",
        "recruit.description_scout", "recruit.group_scout_category",
        kind=CODELET_TYPE,
    )
)

ROLE_BY_NAME: Mapping[str, RoleSpec] = {s.name: s for s in ROLES}


class Absent:
    """The Null Object for a role nothing holds: node-shaped, falsy, identical only to itself.

    What has no node is not perceived: activation 0, never active, no links, no related
    node.  The mutators of a node do nothing.  Construct through :func:`absent`; there is
    exactly one per role.
    """

    __slots__ = ("role",)

    # Node-shaped data.  Class attributes, so an instance holds nothing but its role.
    short_name = ""
    conceptual_depth = 0
    descriptor_predicate = None
    activation = 0.0
    activation_buffer = 0.0
    frozen = False
    clamp_cycles_remaining = 0
    category_links: tuple = ()
    instance_links: tuple = ()
    property_links: tuple = ()
    lateral_links: tuple = ()
    lateral_sliplinks: tuple = ()
    incoming_links: tuple = ()
    outgoing_links: tuple = ()
    intrinsic_link_length = None
    roles: frozenset = frozenset()
    category = None
    is_instance = False

    def __init__(self, role: str) -> None:
        object.__setattr__(self, "role", role)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("an Absent role token is frozen")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("an Absent role token is frozen")

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"<Absent {self.role}>"

    def __copy__(self) -> "Absent":
        return self

    def __deepcopy__(self, memo: dict) -> "Absent":
        return self

    def __reduce__(self) -> tuple:
        return (absent, (self.role,))

    @property
    def name(self) -> str:
        return f"<absent:{self.role}>"

    def has_role(self, role: str) -> bool:
        return False

    def fully_active(self, threshold: float | None = None) -> bool:
        return False

    def above_threshold(self, threshold: float | None = None) -> bool:
        return False

    def partially_active(self) -> bool:
        return False

    def get_related_node(self, relation: Any) -> None:
        return None

    def describes(self, obj: Any) -> bool:
        return False

    def description_possible(self, obj: Any) -> bool:
        return False

    def activate_from_workspace(self) -> None:
        return None

    def decay(self) -> None:
        return None

    def clamp(self, cycles: int = 0, activation: float = 100.0) -> None:
        return None

    def unclamp(self) -> None:
        return None

    def tick_clamp(self) -> None:
        return None


_ABSENT: dict[str, Absent] = {}


def absent(role: str) -> Absent:
    """The one ``Absent`` token of ``role``."""
    token = _ABSENT.get(role)
    if token is None:
        token = _ABSENT[role] = Absent(role)
    return token


_LAYOUT = tuple((sp.name, sp.attr, sp.cardinality == ORDERED) for sp in ROLES)
_set = object.__setattr__


class Roles:
    """The resolved roles of one Slipnet: one attribute per role of ``ROLES``, frozen.

    Built with ``Roles(bound)``; ``bound`` maps role name to a node / codelet spec (kind
    ``one``) or to a tuple of them (``ordered``).  A role missing from ``bound`` resolves to
    its ``Absent`` token (``one``) or ``()`` (``ordered``).  ``None`` is never stored.
    """

    __slots__ = tuple(s.attr for s in ROLES)

    def __init__(self, bound: Mapping[str, Any] | None = None) -> None:
        get = (bound or {}).get
        for name, attr, ordered in _LAYOUT:
            value = get(name)
            if value is None:
                value = () if ordered else absent(name)
            _set(self, attr, value)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Roles is frozen")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Roles is frozen")

    def get(self, role: str) -> Any:
        """The resolved value of a role by its name (``dimension.length``)."""
        return getattr(self, ROLE_BY_NAME[role].attr)

    def items(self) -> Iterable[tuple[str, Any]]:
        return ((s.name, getattr(self, s.attr)) for s in ROLES)

    def __repr__(self) -> str:
        return "Roles(" + ", ".join(f"{n}={v!r}" for n, v in self.items()) + ")"


_first = itemgetter(0)


def resolve_roles(
    node_roles: Iterable[Any],
    codelet_roles: Iterable[Any],
    nodes: Mapping[str, Any],
    codelet_specs: Mapping[str, Any],
) -> tuple[Roles, dict[str, frozenset[str]]]:
    """Resolve the bindings against the nodes and codelet types that exist.

    Returns the ``Roles`` record and, for every bound node name, the frozenset of role names
    it holds (the caller stores it as ``SlipnetNode.roles``).

    Unknown names are skipped, like an unresolved link endpoint: a binding whose role is not
    in the vocabulary (or is of the other kind), and a binding to a node or codelet type that
    does not exist, is a reference to something that does not exist.  The change API refuses
    or cascades such a binding at edit time; the builder simply does not bind it and never
    raises.  For a role of cardinality ``one`` with several bindings, the lowest ordinal wins.
    """
    found: dict[str, list[tuple[int, Any]]] = {}
    held: dict[str, list[str]] = {}
    for kind, bindings, targets in (
        (NODE, node_roles, nodes), (CODELET_TYPE, codelet_roles, codelet_specs)
    ):
        get_target = targets.get
        for b in bindings:
            role = b.role
            spec = ROLE_BY_NAME.get(role)
            if spec is None or spec.target_kind != kind:
                continue
            if kind == NODE:
                target_name = b.node_name
                target = get_target(target_name)
                if target is None:
                    continue
                if target_name in held:
                    held[target_name].append(role)
                else:
                    held[target_name] = [role]
            else:
                target = get_target(b.codelet_type)
                if target is None:
                    continue
            if role in found:
                found[role].append((b.ordinal, target))
            else:
                found[role] = [(b.ordinal, target)]
    bound: dict[str, Any] = {}
    for role, entries in found.items():
        if len(entries) > 1:
            entries.sort(key=_first)
        if ROLE_BY_NAME[role].cardinality == ORDERED:
            bound[role] = tuple([t for _, t in entries])
        else:
            bound[role] = entries[0][1]
    return Roles(bound), {n: frozenset(r) for n, r in held.items()}
