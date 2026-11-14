"""The table registry: which tables are configuration, and how a row in each is addressed.

Built by introspecting the models in ``server/models/metadata.py`` (the configuration plan,
3.12.2).  Three things are derived and one is declared:

* **derived**: the configuration tables (every metadata model but ``help_topics``, which is
  content), each table's model, its JSON columns and which tables are enum lookup tables;
* **declared** (``_NATURAL_KEYS``, ``_CODE_COLUMNS``): each table's natural key, the columns
  that fix its order and the columns that hold code.  A new configuration table with no
  declaration here stops the application importing this module, so a table is never
  silently unaddressable.

``REGISTRY`` is the tables the change API addresses by generic ops (the 17 enum tables, which
are the engine's vocabulary, are not among them; the change API's ``rename_enum_value`` is the
one op that reads and writes them).  ``link_types`` is addressed, though it has the four enum
columns: the engine names what a link type *does* (its ``behaviour``) and never a link type, so
a configuration may hold link types of its own, created by ``add_link_type`` and removed by
``remove_link_type`` (the one change API every learning source uses).  ``ENUM_REGISTRY`` is the 17
enum tables and ``LAYER_REGISTRY`` is both: the journal layer (``server/services/journal.py``)
writes all of them, because the Metacat Standard Configuration's first load and the Admin enum
editor do.

Resolved ops (3.12.0) are plain dicts naming a table by its database name and a row by its
natural key (``TableSpec.key``)::

    {"op": "insert", "table": t, "key": {...}, "row": {...}}
    {"op": "update", "table": t, "key": {...}, "set": {...}}      # absolute new values
    {"op": "delete", "table": t, "key": {...}}
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from sqlalchemy.dialects.postgresql import JSON, JSONB

#: Metadata tables that are not configuration: content, written by the help-topic sync.
NON_CONFIGURATION_TABLES = frozenset({"help_topics"})

#: The natural key of each addressable table, and the columns that fix its row order
#: (``sort_order`` / ``ordinal``; ``()`` when the order is not behaviour).  A NULL in a key
#: column is read as ``''`` (``slipnet_link_defs.label_node``).
_NATURAL_KEYS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # First, so a link type sorts before the links that name it (``TABLE_NAMES``).  It has the
    # four enum columns but is addressed by the change API, so it is declared here.
    "link_types": (("name",), ("sort_order",)),
    "slipnet_node_defs": (("name",), ("sort_order",)),
    "slipnet_link_defs": (("from_node", "to_node", "link_type", "label_node"), ("sort_order",)),
    "slipnet_layout": (("node_name",), ("sort_order",)),
    "theme_dimension_defs": (("slipnet_node",), ()),
    "theme_relations": (("name",), ("ordinal",)),
    "slipnet_node_roles": (("role", "ordinal"), ("role", "ordinal")),
    "codelet_type_defs": (("name",), ("sort_order",)),
    "codelet_type_roles": (("role", "ordinal"), ("role", "ordinal")),
    "posting_rules": (("rule_key",), ("sort_order",)),
    "codelet_pattern_defs": (("pattern_name", "codelet_type"), ("ordinal",)),
    "engine_params": (("name",), ("sort_order",)),
    "formula_coefficients": (("name",), ("sort_order",)),
    "urgency_levels": (("name",), ("sort_order",)),
    "demo_problems": (("name",), ()),
    "commentary_templates": (("template_key",), ()),
    "initial_description_rules": (("rule_key",), ("ordinal",)),
    "initial_activation_rules": (("rule_key",), ("ordinal",)),
    "input_character_ranges": (("kind", "first"), ("kind", "first")),
    "input_lowering_ranges": (("first",), ("first",)),
}

def total_order(key: tuple[str, ...], order: tuple[str, ...]) -> tuple[str, ...]:
    """The one total order of a table: its declared order columns, then the rest of its key.

    Two rows that tie on ``sort_order`` or ``ordinal`` are ordered by their natural key, so a
    tie has one answer in the database (``ORDER BY``) and in a ``ConfigDocument`` alike.  A table
    with no order columns keeps insertion order (``id`` in the database, insertion in a
    document), which the two paths already agree on: an insert appends, an update keeps the
    row's place, and a delete removes it.
    """
    if not order:
        return ()
    return tuple(order) + tuple(c for c in key if c not in order)


#: Columns that hold code (a Python body, a predicate or a formula), by table.
_CODE_COLUMNS: dict[str, frozenset[str]] = {
    "slipnet_node_defs": frozenset({"descriptor_predicate"}),
    "codelet_type_defs": frozenset({"execute_body"}),
    "posting_rules": frozenset(
        {"urgency_formula", "posting_formula", "count_formula", "condition"}
    ),
}

#: The columns every enum lookup table has (it may add more); its key is ``name`` and its
#: order ``sort_order``.
_ENUM_COLUMNS = frozenset({"name", "display_label", "sort_order", "description"})


@dataclass(frozen=True)
class TableSpec:
    """How one configuration table is addressed."""

    name: str
    model: type
    #: The natural-key columns.  A NULL label in the link key is read as ``''``.
    key: tuple[str, ...]
    #: The columns that fix row order (``sort_order``, ``ordinal``), or ``()``.
    order: tuple[str, ...]
    code_columns: frozenset[str]
    json_columns: frozenset[str]

    @property
    def total_order(self) -> tuple[str, ...]:
        """The order columns followed by the rest of the key (see :func:`total_order`)."""
        return total_order(self.key, self.order)

    def order_by(self) -> list[Any]:
        """``ORDER BY`` clauses for :attr:`total_order`.

        Text columns sort by byte value (``COLLATE "C"``), which is what Python's string order is
        for UTF-8, and a NULL key part sorts as ``''`` (the document reads it that way), so the
        database's order does not depend on its locale or on where it puts NULLs.
        """
        from sqlalchemy import func, literal

        clauses: list[Any] = []
        for name in self.total_order:
            column = self.table.c[name]
            if column.type.python_type is str:
                expr = func.coalesce(column, literal("")) if column.nullable else column
                clauses.append(expr.collate("C"))
            else:
                clauses.append(column)
        return clauses

    @property
    def table(self) -> Any:
        return self.model.__table__

    @property
    def columns(self) -> tuple[str, ...]:
        """Every column of the table, in definition order."""
        return tuple(c.name for c in self.table.columns)

    @property
    def surrogate(self) -> str | None:
        """The integer ``id`` that is not part of the natural key (not stable across
        configurations, so never recorded in a journal), or ``None``."""
        pk = [c.name for c in self.table.primary_key.columns]
        if len(pk) == 1 and pk[0] not in self.key:
            return pk[0]
        return None

    @property
    def stored_columns(self) -> tuple[str, ...]:
        """The columns a journal records: every column but the surrogate ``id``."""
        sid = self.surrogate
        return tuple(c for c in self.columns if c != sid)

    def key_of(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """The natural key of ``row`` (a mapping or an object), a NULL read as ``''``."""
        getter = row.get if isinstance(row, Mapping) else (lambda c: getattr(row, c, None))
        out: dict[str, Any] = {}
        for column in self.key:
            value = getter(column)
            if value is None and self.table.c[column].nullable:
                value = ""
            out[column] = value
        return out

    def key_tuple(self, key: Mapping[str, Any]) -> tuple:
        """A hashable form of a key, in key-column order."""
        return tuple(key[c] if key.get(c) is not None else "" for c in self.key)


def _models_module() -> Any:
    from server.models import metadata

    return metadata


def configuration_models() -> dict[str, type]:
    """Every configuration table's model, by database table name (enum tables included)."""
    module = _models_module()
    return {
        cls.__tablename__: cls
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if getattr(cls, "__module__", "") == module.__name__
        and hasattr(cls, "__tablename__")
        and cls.__tablename__ not in NON_CONFIGURATION_TABLES
    }


def configuration_table_names() -> frozenset[str]:
    """Every table the Metacat Standard Configuration loads into (by model introspection)."""
    return frozenset(configuration_models())


def _is_enum_table(model: type) -> bool:
    """An enum lookup table has the four enum columns (and may add more: ``role``,
    ``behaviour``, ``serialised``, a clamp type's factors ...)."""
    columns = {c.name for c in model.__table__.columns}
    return _ENUM_COLUMNS <= columns and [c.name for c in model.__table__.primary_key.columns] == ["name"]


def _json_columns(model: type) -> frozenset[str]:
    return frozenset(
        c.name for c in model.__table__.columns if isinstance(c.type, (JSON, JSONB))
    )


def _build() -> tuple[dict[str, TableSpec], dict[str, TableSpec]]:
    registry: dict[str, TableSpec] = {}
    enums: dict[str, TableSpec] = {}
    for name, model in sorted(configuration_models().items()):
        if name not in _NATURAL_KEYS and _is_enum_table(model):
            enums[name] = TableSpec(
                name, model, ("name",), ("sort_order",), frozenset(), _json_columns(model)
            )
            continue
        if name not in _NATURAL_KEYS:
            raise RuntimeError(
                f"configuration table {name!r} has no natural key declared in "
                "server/services/config_registry.py (_NATURAL_KEYS); declare it there."
            )
        key, order = _NATURAL_KEYS[name]
        columns = {c.name for c in model.__table__.columns}
        missing = (set(key) | set(order)) - columns
        if missing:
            raise RuntimeError(f"{name}: key or order columns {sorted(missing)} are not columns")
        registry[name] = TableSpec(
            name, model, key, order, _CODE_COLUMNS.get(name, frozenset()), _json_columns(model)
        )
    stale = set(_NATURAL_KEYS) - set(registry)
    if stale:
        raise RuntimeError(f"_NATURAL_KEYS names tables that are not configuration: {sorted(stale)}")
    return registry, enums


_registry, _enums = _build()

#: The tables the change API addresses, by database table name.
REGISTRY: Mapping[str, TableSpec] = MappingProxyType(_registry)

#: The 17 enum lookup tables (the engine's vocabulary): written by the layer, not addressed
#: by the change API's generic ops (``rename_enum_value`` renames a row of one).
ENUM_REGISTRY: Mapping[str, TableSpec] = MappingProxyType(_enums)

#: Every table the journal layer writes: ``REGISTRY`` and ``ENUM_REGISTRY``.
LAYER_REGISTRY: Mapping[str, TableSpec] = MappingProxyType({**_registry, **_enums})

assert set(LAYER_REGISTRY) == configuration_table_names()
