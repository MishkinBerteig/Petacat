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

import sys
from dataclasses import dataclass
from operator import itemgetter
from typing import Any, Iterable, Mapping

NODE = "node"
CODELET_TYPE = "codelet_type"
#: A role bound to a *row of an enum table*: its value is the row's name (a string).
ENUM_ROW = "enum_row"
ONE = "one"
ORDERED = "ordered"


@dataclass(frozen=True)
class RoleSpec:
    """One name of the vocabulary."""

    name: str
    target_kind: str  # NODE, CODELET_TYPE or ENUM_ROW
    cardinality: str  # ONE or ORDERED
    #: For an ``ENUM_ROW`` role, the table whose row the role is bound to.
    table: str | None = None

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
    #: No node, no ceiling: a share of it is 0 (``formulas.share_of_ceiling``).
    max_activation = 0.0
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

    def description_possible(self, obj: Any) -> bool:
        return False

    def activate_from_workspace(self) -> None:
        return None

    def decay(self) -> None:
        return None

    def clamp(self, cycles: int = 0, activation: float | None = None) -> None:
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


# ---------------------------------------------------------------------------
# The vocabulary: roles bound to the rows of the enum tables (NAME-DESIGN 4.2)
# ---------------------------------------------------------------------------
#
# The engine owns the *concepts* (a bridge joins the top strings, a clamp holds the rack
# against a background ...); the configuration owns the *names* it calls them.  An enum
# table row carries a ``role`` (``behaviour`` for ``link_types``); the engine reads the row
# bound to each role once per run and compares against that name, never against a literal.
# ``tests/architecture/test_vocabulary_literals.py`` fails when a bound name is written as a
# literal in ``server/engine/`` or ``server/parallel/``.

#: Each enum table the engine names rows of, with the column that holds the role and the roles
#: (role names are ``<singular>.<suffix>``).
_VOCABULARY_TABLES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("event_types", "role", "event_type", (
        "group_built", "rule_built", "answer_found", "snag", "clamp_start",
        "concept_mapping_built", "concept_activation",
    )),
    ("bridge_types", "role", "bridge_type", ("top", "bottom", "vertical")),
    ("bridge_orientations", "role", "bridge_orientation", ("horizontal", "vertical")),
    ("clause_types", "role", "clause_type", ("intrinsic", "extrinsic", "verbatim")),
    ("rule_types", "role", "rule_type", ("top", "bottom")),
    ("theme_types", "role", "theme_type", ("top_bridge", "bottom_bridge", "vertical_bridge")),
    ("proposal_levels", "role", "proposal_level", ("proposed", "evaluated", "built")),
    ("posting_directions", "role", "posting_direction", ("bottom_up", "top_down", "thematic")),
    ("theme_relations", "role", "theme_relation", (
        "identity", "opposite", "successor", "predecessor", "diff",
    )),
    ("string_kinds", "role", "string_kind", ("initial", "modified", "target", "answer")),
    ("rule_scopes", "role", "rule_scope", ("self", "subobjects")),
    ("failure_kinds", "role", "failure_kind", ("swap", "conflict", "change")),
    ("clamp_types", "role", "clamp_type", ("rule_codelet", "snag_response", "justify", "manual")),
)

VOCABULARY: tuple[RoleSpec, ...] = tuple(
    RoleSpec(f"{prefix}.{suffix}", ENUM_ROW, ONE, table)
    for table, _column, prefix, suffixes in _VOCABULARY_TABLES
    for suffix in suffixes
)
VOCABULARY_BY_NAME: Mapping[str, RoleSpec] = {s.name: s for s in VOCABULARY}

#: The column of each enum table that holds its role.
ROLE_COLUMN: Mapping[str, str] = {table: column for table, column, _p, _s in _VOCABULARY_TABLES}

#: What the engine does with a link of a type (``link_types.behaviour``); the configuration
#: says which type has which.  A behaviour is the engine's name, as a role is.
LINK_BEHAVIOURS: tuple[str, ...] = ("category", "instance", "property", "lateral", "slip")


class AbsentName(str):
    """The name counterpart of :class:`Absent`: the value of a vocabulary role nothing holds.

    A falsy ``str`` equal only to itself, so ``x == vocabulary.rule_type_top`` is false for
    every ``x`` while the role is unbound, and nothing is mistaken for a match.  One per role
    (:func:`absent_name`).
    """

    __slots__ = ()

    def __new__(cls, role: str) -> "AbsentName":
        return super().__new__(cls, f"<absent:{role}>")

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        return self is other

    def __ne__(self, other: object) -> bool:
        return self is not other

    def __hash__(self) -> int:
        return id(self)

    def __reduce__(self) -> tuple:
        return (absent_name, (str.__str__(self)[len("<absent:"):-1],))

    def __copy__(self) -> "AbsentName":
        return self

    def __deepcopy__(self, memo: dict) -> "AbsentName":
        return self


_ABSENT_NAMES: dict[str, AbsentName] = {}


def absent_name(role: str) -> AbsentName:
    """The one :class:`AbsentName` of *role*."""
    token = _ABSENT_NAMES.get(role)
    if token is None:
        token = _ABSENT_NAMES[role] = AbsentName(role)
    return token


_VOCAB_LAYOUT = tuple((sp.name, sp.attr) for sp in VOCABULARY)


class Vocabulary:
    """The resolved vocabulary of one run: one attribute per role of ``VOCABULARY``, frozen.

    ``vocabulary.bridge_type_top`` (the role name with dots turned into underscores) is the
    interned *name* of the row bound to ``bridge_type.top``, or that role's
    :class:`AbsentName`.  Built with ``Vocabulary(bound)``, ``bound`` mapping a role name to
    a row name.  Structures store the object they were given, so a comparison is a pointer
    compare in the ordinary case.
    """

    __slots__ = tuple(s.attr for s in VOCABULARY)

    def __init__(self, bound: Mapping[str, str] | None = None) -> None:
        get = (bound or {}).get
        for name, attr in _VOCAB_LAYOUT:
            value = get(name)
            _set(self, attr, sys.intern(value) if value is not None else absent_name(name))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Vocabulary is frozen")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Vocabulary is frozen")

    def get(self, role: str) -> str:
        """The name bound to *role* (``bridge_type.top``), or its :class:`AbsentName`."""
        return getattr(self, VOCABULARY_BY_NAME[role].attr)

    def items(self) -> Iterable[tuple[str, str]]:
        return ((s.name, getattr(self, s.attr)) for s in VOCABULARY)

    def bound(self) -> dict[str, str]:
        """``{role: name}`` of the roles that are bound."""
        return {r: n for r, n in self.items() if type(n) is str}

    def __reduce__(self) -> tuple:
        return (Vocabulary, (self.bound(),))

    def __repr__(self) -> str:
        return "Vocabulary(" + ", ".join(f"{n}={v!r}" for n, v in self.items()) + ")"


@dataclass(frozen=True)
class VocabularyBinding:
    """One row of an enum table bound to a role: part of the provider, so it is hashed."""

    role: str
    table: str
    name: str


def vocabulary_bindings(tables: Mapping[str, Iterable[Mapping[str, Any]]]) -> tuple[VocabularyBinding, ...]:
    """The bindings the enum tables' ``role`` columns state, ordered by role name.

    *tables* maps a table name to its rows (mappings).  A row whose role is empty, or is
    not in the vocabulary for that table, binds nothing.  A role held by several rows binds
    the first (the schema makes the column unique, so this is for tables built by hand).
    """
    found: dict[str, VocabularyBinding] = {}
    for table, column, _prefix, _suffixes in _VOCABULARY_TABLES:
        for row in tables.get(table, ()):
            role = row.get(column)
            spec = VOCABULARY_BY_NAME.get(role) if role else None
            if spec is None or spec.table != table or role in found:
                continue
            found[role] = VocabularyBinding(role, table, row["name"])
    return tuple(found[r] for r in sorted(found, key=lambda r: r.encode()))
