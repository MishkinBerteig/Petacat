"""The vocabulary tables as the change API and the Admin enum editor see them.

The engine names concepts (``server/engine/roles.py``: ``VOCABULARY``, ``LINK_BEHAVIOURS``);
a row of an enum table (or of ``theme_relations``) binds one by holding its name in its
``role`` column (``behaviour`` for ``link_types``).  This module is the one place that says,
per table:

* which column holds the binding and which names it may hold (:data:`VOCABULARY_TABLES`),
* what a write to such a row must satisfy (:func:`role_problem`): the role is a name of the
  table's vocabulary, held by no other row of the table; a link type's behaviour is one of the
  engine's behaviours (several link types may share one),
* that a bound row cannot be deleted (:func:`delete_problem`, ``422 role_bound``): unbind it
  first, by setting its role to null.  This holds for every table with a role: the enum tables
  (whose editors call this function) and ``theme_relations`` (a ``delete`` op).  Removing a
  Slipnet node still deletes the relation rows that name it, bound or not: that is the node's
  removal, and its report lists them.

Adding an unbound row, or leaving a row unbound, is always allowed: the row is inert except
that it becomes a valid value of the columns that reference its table.  The enum tables are
not addressable by generic ops in a batch (``schema`` lists the other tables); the Admin enum
editor and the Database tab's enum path call these functions.  The resolver applies
:func:`role_problem` to ``theme_relations`` (addressable) as well.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from server.engine.roles import LINK_BEHAVIOURS, ROLE_COLUMN, VOCABULARY
from server.services.configuration_input import (
    ROLE_BOUND,
    ROLE_TAKEN,
    UNKNOWN_REFERENCE,
    InputProblem,
)


@dataclass(frozen=True)
class VocabularyTable:
    """One table whose rows can be bound to the engine's names."""

    table: str
    #: ``role`` for every table but ``link_types``, whose column is ``behaviour``.
    column: str
    #: The names the column may hold, in the engine's order.
    roles: tuple[str, ...]
    #: Whether two rows may hold the same name (a behaviour may be shared; a role may not).
    unique: bool

    def as_dict(self) -> dict[str, Any]:
        return {"column": self.column, "roles": list(self.roles), "unique": self.unique}


def _build() -> dict[str, VocabularyTable]:
    out = {
        table: VocabularyTable(
            table, column, tuple(s.name for s in VOCABULARY if s.table == table), True
        )
        for table, column in ROLE_COLUMN.items()
    }
    out["link_types"] = VocabularyTable("link_types", "behaviour", tuple(LINK_BEHAVIOURS), False)
    return out


#: Every table with a role (or behaviour) column, by table name.
VOCABULARY_TABLES: Mapping[str, VocabularyTable] = _build()


def roles_by_table() -> dict[str, dict[str, Any]]:
    """``{table: {"column", "roles", "unique"}}`` for the Admin enum editor's pick list."""
    return {t: v.as_dict() for t, v in VOCABULARY_TABLES.items()}


def bound_value(table: str, row: Mapping[str, Any]) -> str | None:
    """The role (or behaviour) the row holds, or ``None``."""
    v = VOCABULARY_TABLES.get(table)
    return (row.get(v.column) or None) if v is not None else None


def role_problem(
    table: str,
    row: Mapping[str, Any],
    other_rows: Iterable[Mapping[str, Any]],
    *,
    op_index: int | None = None,
    key: Any = None,
) -> InputProblem | None:
    """Why the ``role`` of *row* is refused, or ``None``.

    *other_rows* are the rows of the table other than the one being written.  A null role is
    always accepted.
    """
    v = VOCABULARY_TABLES.get(table)
    if v is None:
        return None
    value = row.get(v.column)
    if value is None or value == "":
        return None
    if value not in v.roles:
        return InputProblem(
            UNKNOWN_REFERENCE,
            f"{table}.{v.column} {value!r} is not in the engine's vocabulary for {table}: "
            f"one of {', '.join(v.roles)}",
            op_index, v.column, table, key)
    if v.unique:
        for other in other_rows:
            if other.get(v.column) == value:
                return InputProblem(
                    ROLE_TAKEN,
                    f"{table}.{v.column} {value!r} is already held by {other.get('name')!r}; "
                    "unbind that row first (set its role to null)",
                    op_index, v.column, table, key)
    return None


def delete_problem(
    table: str, row: Mapping[str, Any], *, op_index: int | None = None
) -> InputProblem | None:
    """``role_bound`` when *row* holds a role (or a behaviour); deleting it is refused."""
    value = bound_value(table, row)
    if value is None:
        return None
    column = VOCABULARY_TABLES[table].column
    return InputProblem(
        ROLE_BOUND,
        f"{table} row {row.get('name')!r} holds the {column} {value!r}: unbind it first "
        f"(set its {column} to null), then delete it",
        op_index, column, table, [row.get("name")])
