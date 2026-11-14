"""The Database tab: a generic browser and editor over every table (configuration plan 3.6).

"The admin UX can examine or change anything in the database" (the user, 2026-10-30).  The
guards below are against accidents, not authorisation (R9: there is no authentication).

Every table is introspected from ``Base.metadata`` and put in one **class**:

* ``configuration``: every table the journal layer writes (the registry, ``link_types`` among
  it, and the 17 enum tables).  An edit is a batch through the change API.
* ``content``: ``help_topics``.  Written directly.
* ``runtime``: runs, Metacat Mode's Episodic Memory rows and the like.  An edit needs expert
  mode and a typed confirmation (the table's name), and an active run's rows are refused.  An
  edit to Metacat Mode's stored Episodic Memory leaves the memory the server holds alone, but
  ``RunService.rehydrate_memory`` loads the edited rows at the next server start.
* ``journal``: ``configurations``, ``configuration_journal`` and the other layer-owned tables.
  Read-only (409 ``journal_read_only``).
* ``session_managed``: a Training Mode Session's tables.  Read-only (409 ``session_managed``).
* ``episodic_memory``: a session's Episodic Memory: ``training_memory_merges``, its
  snapshot ``training_mode_session_memory_snapshots``, a session's journal table, and the run columns ``seq``, ``memory_version``, ``added_answers`` and
  ``added_snags``.  Read-only, and expert mode does not lift it (409
  ``episodic_memory_protected``).

A configuration edit is a batch through :class:`ChangeService` (``source = admin``,
``channel = admin_database``), so it is a journal entry like any other.  The 17 enum tables are
not addressed by the change API (``link_types`` is, like any other configuration table); their edits are resolved ops written by the journal layer
(``write_immediate``), as the Admin enum editor does, and so under the same vocabulary rules
(``change_resolve.vocabulary``: a ``role`` is one of the table's, held once, and a bound row is not
deleted).

A runtime edit is recorded plainly: one ``WARNING`` log line carrying the table, the old and new
row, and the response returns both.  It does not write a ``scope = runtime`` journal entry: that
would add a scope to the configuration journal (a per-configuration revision chain) for tables
that have no configuration.

The read-only SQL box runs one ``SELECT`` or ``WITH`` statement in a read-only transaction, with
a row limit and a statement timeout.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import (
    Date, DateTime, Float, Integer, Numeric, Text, delete, func, insert, or_, select, text, update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session
from server.models.journal import GLOBAL_CONFIGURATION_ID
from server.models.metadata import Base
from server.services import journal
from server.services.config_registry import ENUM_REGISTRY, LAYER_REGISTRY
from server.services.configuration_writer import ChangeError, ChangeService, error_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/db", tags=["database"])

# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

CONFIGURATION = "configuration"
CONTENT = "content"
RUNTIME = "runtime"
JOURNAL = "journal"
SESSION_MANAGED = "session_managed"
EPISODIC_MEMORY = "episodic_memory"

CLASS_LABELS = {
    CONFIGURATION: "configuration",
    CONTENT: "content",
    RUNTIME: "runtime data",
    JOURNAL: "journal (read-only)",
    SESSION_MANAGED: "session-managed (read-only)",
    EPISODIC_MEMORY: "session Episodic Memory (protected)",
}

#: Error codes of the refusals.
SESSION_MANAGED_CODE = "session_managed"
EPISODIC_MEMORY_PROTECTED = "episodic_memory_protected"
JOURNAL_READ_ONLY = "journal_read_only"

#: Tables, and run columns, that are a Training Mode Session's Episodic Memory (3.15).
_EPISODIC_TABLES = frozenset({"training_memory_merges", "training_mode_session_memory_snapshots"})
EPISODIC_RUN_COLUMNS = frozenset({"seq", "memory_version", "added_answers", "added_snags"})
_SESSION_RUNS_TABLE = "training_mode_session_runs"
_SESSIONS_TABLE = "training_mode_sessions"

#: The statuses of a run that is still going (``run_statuses``): its rows are not edited.
ACTIVE_RUN_STATUSES = frozenset({"initialized", "running", "paused"})

BANNERS = {
    CONFIGURATION: (
        "Configuration. An edit here is a batch through the change API and a journal entry, "
        "like any other."
    ),
    CONTENT: "Content (the in-app help). Written directly.",
    RUNTIME: (
        "Runtime data. Editing needs expert mode and a typed confirmation, and an active run's "
        "rows are never edited. An edit to Metacat Mode's stored Episodic Memory "
        "(answer_descriptions, snag_descriptions) does not change the memory the running server "
        "holds, but the next server start loads the edited rows, so later runs are reminded of "
        "the edited answers and snags."
    ),
    JOURNAL: (
        "The journal is the one record of changes and is read-only here: the journal layer "
        "appends to it and nothing updates or deletes an entry."
    ),
    SESSION_MANAGED: (
        "Session-managed and read-only. These are stored rows only: as of the last stop of "
        "each Training Mode Session. A session that is running holds its current state in "
        "memory, so the rows below are not its current state. A stopped session's "
        "configuration is edited through the change API; a session is deleted with "
        "DELETE /api/training-mode/sessions/{id}."
    ),
    EPISODIC_MEMORY: (
        "A Training Mode Session's Episodic Memory is protected. It is never edited and never "
        "cleared; it goes only when the whole session is deleted. Expert mode does not lift "
        "this."
    ),
}

_SQL_ROW_LIMIT_DEFAULT = 200
_SQL_ROW_LIMIT_MAX = 1000
_SQL_TIMEOUT_MS = 5000


def table_class(name: str) -> str:
    """The class of table *name* (by name, so a table added later is classed the day it exists)."""
    if name in LAYER_REGISTRY:
        return CONFIGURATION
    if name == "help_topics":
        return CONTENT
    if name in _EPISODIC_TABLES or (name.startswith("training_mode_session") and "journal" in name):
        return EPISODIC_MEMORY
    if name.startswith("training_mode_session"):
        return SESSION_MANAGED
    if name.startswith("configuration") or "journal" in name:
        return JOURNAL
    return RUNTIME


def _all_tables() -> dict[str, Any]:
    import server.models.journal  # noqa: F401  (registers the journal tables)
    import server.models.run  # noqa: F401
    import server.models.training_mode_session  # noqa: F401

    return dict(sorted(Base.metadata.tables.items()))


def _table(name: str):
    tables = _all_tables()
    if name not in tables:
        raise HTTPException(404, f"no table named {name!r}")
    return tables[name]


def _http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"error": code, "message": message})


def _refuse_by_class(name: str, op: str, values: Optional[dict] = None) -> None:
    """Raise the 409 for a write the table's class never allows (``op``: insert/update/delete)."""
    cls = table_class(name)
    if name == _SESSIONS_TABLE and op == "delete":
        raise _http(
            409, SESSION_MANAGED_CODE,
            "a Training Mode Session is deleted with DELETE /api/training-mode/sessions/{id}, "
            "so that its live state is settled first; the Database tab does not delete "
            "training_mode_sessions rows")
    if name == _SESSION_RUNS_TABLE and (
        op in ("insert", "delete") or EPISODIC_RUN_COLUMNS & set(values or {})
    ):
        raise _http(
            409, EPISODIC_MEMORY_PROTECTED,
            f"a session's run rows carry {sorted(EPISODIC_RUN_COLUMNS)}, which place the run in "
            "its Episodic Memory; the memory is never edited, and expert mode does not lift this")
    if cls == EPISODIC_MEMORY:
        raise _http(
            409, EPISODIC_MEMORY_PROTECTED,
            "a session's Episodic Memory is not configuration and is never edited or cleared; "
            "it goes only when the whole session is deleted. Expert mode does not lift this")
    if cls == SESSION_MANAGED:
        raise _http(
            409, SESSION_MANAGED_CODE,
            f"{name} is session-managed and read-only here: the rows are stored state as of "
            "the last stop of the session. A session's configuration is edited through the "
            "change API")
    if cls == JOURNAL:
        raise _http(
            409, JOURNAL_READ_ONLY,
            f"{name} belongs to the journal layer and is read-only here")


# ---------------------------------------------------------------------------
# Browsing
# ---------------------------------------------------------------------------


def _column_info(table) -> list[dict[str, Any]]:
    return [
        {
            "name": c.name,
            "type": str(c.type),
            "primary_key": bool(c.primary_key),
            "nullable": bool(c.nullable),
            "protected": c.name in EPISODIC_RUN_COLUMNS and table.name == _SESSION_RUNS_TABLE,
        }
        for c in table.columns
    ]


def _key_columns(name: str, table) -> list[str]:
    spec = LAYER_REGISTRY.get(name)
    if spec is not None:
        return list(spec.key)
    return [c.name for c in table.primary_key.columns]


def _row_view(name: str, table, mapping: dict) -> dict[str, Any]:
    values = jsonable_encoder(mapping)
    spec = LAYER_REGISTRY.get(name)
    if spec is not None:
        key = spec.key_of(mapping)
    else:
        key = {c.name: values.get(c.name) for c in table.primary_key.columns}
    return {"values": values, "key": jsonable_encoder(key)}


async def _check_configuration(session: AsyncSession, configuration: int) -> None:
    from server.models.journal import Configuration

    found = (await session.execute(
        select(Configuration.id).where(Configuration.id == configuration)
    )).first()
    if found is None:
        raise HTTPException(404, f"no configuration {configuration}")


@router.get("/tables", summary="List every table with its class (Database tab)")
async def list_tables(
    configuration: int = GLOBAL_CONFIGURATION_ID, session: AsyncSession = Depends(get_session)
):
    """Every table with its class, banner, columns and row count."""
    out = []
    for name, table in _all_tables().items():
        cls = table_class(name)
        count = None
        if cls != CONFIGURATION or configuration == GLOBAL_CONFIGURATION_ID:
            count = (await session.execute(select(func.count()).select_from(table))).scalar_one()
        out.append({
            "name": name,
            "class": cls,
            "class_label": CLASS_LABELS[cls],
            "banner": BANNERS[cls],
            "editable": cls in (CONFIGURATION, CONTENT, RUNTIME),
            "expert_required": cls == RUNTIME,
            "enum": name in ENUM_REGISTRY,
            "rows": count,
            "key_columns": _key_columns(name, table),
            "columns": _column_info(table),
        })
    return out


@router.get("/tables/{name}/rows", summary="Page through a table's rows, with a filter")
async def table_rows(
    name: str,
    configuration: int = GLOBAL_CONFIGURATION_ID,
    limit: int = 50,
    offset: int = 0,
    filter_column: Optional[str] = None,
    filter: Optional[str] = None,  # noqa: A002  (the query parameter's name)
    session: AsyncSession = Depends(get_session),
):
    """A page of rows.  ``filter`` is a case-insensitive substring of ``filter_column`` (or of
    any column when no column is named).  ``configuration`` applies to configuration tables."""
    table = _table(name)
    cls = table_class(name)
    if limit < 1 or limit > 500 or offset < 0:
        raise HTTPException(422, "limit must be 1 to 500 and offset 0 or more")
    if cls == CONFIGURATION and configuration != GLOBAL_CONFIGURATION_ID:
        await _check_configuration(session, configuration)
        raise HTTPException(
            501,
            f"configuration {configuration} is a session's configuration: its rows are read "
            "through GET /api/configurations/{id}/rows, and it is edited through the change API")

    query = select(table)
    if filter:
        needle = f"%{filter}%"
        if filter_column:
            if filter_column not in table.c:
                raise HTTPException(422, f"{name} has no column {filter_column!r}")
            query = query.where(table.c[filter_column].cast(Text).ilike(needle))
        else:
            query = query.where(or_(*[c.cast(Text).ilike(needle) for c in table.columns]))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    order = list(table.primary_key.columns) or list(table.columns)[:1]
    rows = (await session.execute(query.order_by(*order).limit(limit).offset(offset))).mappings().all()
    return {
        "table": name,
        "class": cls,
        "class_label": CLASS_LABELS[cls],
        "banner": BANNERS[cls],
        "configuration": configuration,
        "total": total,
        "limit": limit,
        "offset": offset,
        "key_columns": _key_columns(name, table),
        "columns": _column_info(table),
        "rows": [_row_view(name, table, dict(r)) for r in rows],
    }


# ---------------------------------------------------------------------------
# Configuration edits: a batch through the change API
# ---------------------------------------------------------------------------


class ChangesRequest(BaseModel):
    """A change batch (the shape of the change API) from the row editor.

    ``source``, ``actor`` and ``channel`` are not taken from the client: they are ``admin``,
    ``admin`` and ``admin_database``.
    """

    configuration_id: int = GLOBAL_CONFIGURATION_ID
    ops: list[dict[str, Any]] = Field(min_length=1)
    base_version: Optional[Any] = None
    base_mode: Optional[str] = None
    on_op_failure: Optional[str] = None
    dry_run: bool = False
    note: str = ""


@router.post("/changes", summary="Apply a configuration edit as a journaled batch (channel admin_database)")
async def post_changes(body: ChangesRequest, session: AsyncSession = Depends(get_session)):
    """Apply a batch of configuration edits: the change API, with ``channel = admin_database``."""
    if body.configuration_id != GLOBAL_CONFIGURATION_ID:
        raise _http(
            409, SESSION_MANAGED_CODE,
            "a session's configuration is not edited by the row editor: use the change API")
    known = _all_tables()
    names = [op["table"] for op in body.ops if isinstance(op.get("table"), str)]
    for op in body.ops:
        name = op.get("table")
        if isinstance(name, str) and name in known and table_class(name) != CONFIGURATION:
            _refuse_by_class(name, str(op.get("op")), op.get("row") or op.get("fields"))
            raise HTTPException(
                400, f"{name} is {CLASS_LABELS[table_class(name)]}, not configuration: "
                     "edit it with POST /api/admin/db/edit")
    enum_names = [n for n in names if n in ENUM_REGISTRY]
    if enum_names:
        if len(enum_names) != len(body.ops):
            raise HTTPException(
                400, "a batch edits either the enum tables or the other configuration tables, "
                     "not both")
        return await _write_enum_ops(session, body)

    batch: dict[str, Any] = {
        "configuration_id": body.configuration_id,
        "ops": body.ops,
        "source": "admin",
        "actor": "admin",
        "channel": "admin_database",
        "note": body.note,
        "dry_run": body.dry_run,
    }
    # The editor reads a row and edits it later, so its guard is each op's ``expect`` (the old
    # values the client read), not one revision: without a ``base_version`` the batch is "head".
    batch["base_version"] = body.base_version if body.base_version is not None else "head"
    for field_name in ("base_mode", "on_op_failure"):
        value = getattr(body, field_name)
        if value is not None:
            batch[field_name] = value
    try:
        return await ChangeService.apply(session, batch)
    except ChangeError as exc:
        return error_response(exc)


async def _enum_rows(session: AsyncSession, table: str) -> list[dict]:
    """Every row of an enum table, as plain dicts."""
    result = await session.execute(select(Base.metadata.tables[table]))
    return [dict(r) for r in result.mappings()]


def _check_enum_op(table: str, op: dict, rows: list[dict]) -> None:
    """The vocabulary rules of the Admin enum editor, for an enum op of the row editor: a ``role``
    is a name of the table's vocabulary and held by no other
    row (``role_taken``), and a bound row is not deleted (``role_bound``).  *rows* is the table as
    the earlier ops of the batch left it, and is updated to include this op."""
    from server.services.change_resolve.vocabulary import delete_problem, role_problem

    kind = op.get("op")
    problem = None
    if kind == "insert":
        row = dict(op.get("row") or {})
        problem = role_problem(table, row, rows, key=[row.get("name")])
        if problem is None:
            rows.append(row)
    elif kind == "update":
        key = dict(op.get("key") or {})
        changes = dict(op.get("fields") or op.get("set") or {})
        current = next((r for r in rows if r.get("name") == key.get("name")), None)
        if current is not None:
            merged = {**current, **changes}
            problem = role_problem(
                table, merged, [r for r in rows if r is not current], key=[merged.get("name")])
            if problem is None:
                current.update(changes)
    elif kind == "delete":
        key = dict(op.get("key") or {})
        current = next((r for r in rows if r.get("name") == key.get("name")), None)
        if current is not None:
            problem = delete_problem(table, current)
            if problem is None:
                rows.remove(current)
    if problem is not None:
        raise HTTPException(problem.status, f"{problem.kind}: {problem.message}")


async def _write_enum_ops(session: AsyncSession, body: ChangesRequest):
    """Enum tables are the engine's vocabulary: written by the journal layer, not the change API."""
    if body.dry_run:
        raise HTTPException(400, "a dry run is not available for the enum tables")
    resolved: list[dict] = []
    rows: dict[str, list[dict]] = {}
    for op in body.ops:
        kind, table = op.get("op"), op["table"]
        if table not in rows:
            rows[table] = await _enum_rows(session, table)
        _check_enum_op(table, op, rows[table])
        if kind == "insert":
            row = dict(op.get("row") or {})
            resolved.append({"op": "insert", "table": table, "key": {"name": row.get("name")}, "row": row})
        elif kind == "update":
            resolved.append({"op": "update", "table": table, "key": dict(op.get("key") or {}),
                             "set": dict(op.get("fields") or op.get("set") or {})})
        elif kind == "delete":
            resolved.append({"op": "delete", "table": table, "key": dict(op.get("key") or {})})
        else:
            raise HTTPException(400, f"an enum table edit is an insert, update or delete, not {kind!r}")
    try:
        result = await journal.write_immediate(
            session, ops=resolved, source="admin", actor="admin", channel="admin_database",
            note=body.note)
    except journal.KeyExists as exc:
        raise HTTPException(409, str(exc)) from exc
    except journal.MissingKey as exc:
        raise HTTPException(404, str(exc)) from exc
    except journal.JournalError as exc:
        raise HTTPException(400, str(exc)) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "other rows still refer to this enum value") from exc
    return {
        "ok": True, "persisted": True, "configuration_id": result.configuration_id,
        "version_after": result.revision, "batch_id": result.entry_id, "changed": result.changed,
        "rows": jsonable_encoder(result.rows),
    }


# ---------------------------------------------------------------------------
# Content and runtime edits
# ---------------------------------------------------------------------------


class EditRequest(BaseModel):
    table: str
    op: str = Field(pattern="^(insert|update|delete)$")
    #: The primary key (every primary-key column) of the row to update or delete.
    pk: Optional[dict[str, Any]] = None
    values: Optional[dict[str, Any]] = None
    expert: bool = False
    #: The typed confirmation of a runtime edit: the table's name.
    confirm: str = ""
    note: str = ""


def _coerce(table, values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, value in values.items():
        if name not in table.c:
            raise HTTPException(422, f"{table.name} has no column {name!r}")
        column_type = table.c[name].type
        if isinstance(value, str) and isinstance(column_type, (DateTime, Date)):
            try:
                parsed = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(422, f"{name}: {value!r} is not a date and time") from exc
            if isinstance(column_type, Date):
                parsed = parsed.date()
            elif not column_type.timezone and parsed.tzinfo is not None:
                parsed = parsed.astimezone(_dt.timezone.utc).replace(tzinfo=None)
            value = parsed
        elif isinstance(value, str) and isinstance(column_type, (Integer, Float, Numeric)) and value != "":
            try:
                value = int(value) if isinstance(column_type, Integer) else float(value)
            except ValueError as exc:
                raise HTTPException(422, f"{name}: {value!r} is not a number") from exc
        out[name] = value
    return out


def _pk_clause(table, pk: Optional[dict]):
    cols = list(table.primary_key.columns)
    if not cols:
        raise HTTPException(400, f"{table.name} has no primary key, so a row cannot be addressed")
    if not pk or set(pk) != {c.name for c in cols}:
        raise HTTPException(422, f"pk must give exactly {[c.name for c in cols]}")
    return [c == pk[c.name] for c in cols]


async def _refuse_if_active(session: AsyncSession, table, row: dict) -> None:
    """A runtime row of an active run (a ``runs`` row, or any row with its ``run_id``) is refused."""
    if table.name == "runs":
        active = row.get("status") in ACTIVE_RUN_STATUSES
    elif "run_id" in table.c and row.get("run_id") is not None:
        status = (await session.execute(
            text("SELECT status FROM runs WHERE id = :id"), {"id": row["run_id"]})).scalar_one_or_none()
        active = status in ACTIVE_RUN_STATUSES
    else:
        active = False
    if active:
        raise _http(409, "active_row", "this row belongs to a run that is still going: stop the run first")


@router.post("/edit", summary="Edit one content or runtime row (runtime needs expert mode)")
async def post_edit(body: EditRequest, session: AsyncSession = Depends(get_session)):
    """Insert, update or delete one row of a content or runtime table.

    Configuration tables are edited with ``POST /api/admin/db/changes``; the journal,
    session-managed and Episodic Memory classes refuse (409).
    """
    table = _table(body.table)
    name = table.name
    cls = table_class(name)
    _refuse_by_class(name, body.op, body.values)
    if cls == CONFIGURATION:
        raise HTTPException(
            400, f"{name} is configuration: edit it with POST /api/admin/db/changes (a journaled batch)")
    if cls == RUNTIME:
        if not body.expert:
            raise _http(409, "expert_required", "runtime data is edited only in expert mode")
        if body.confirm != name:
            raise _http(409, "confirmation_required", f"type the table name {name!r} to confirm")

    values = _coerce(table, body.values or {})
    clause = None
    before: Optional[dict] = None
    if body.op != "insert":
        clause = _pk_clause(table, body.pk)
        found = (await session.execute(select(table).where(*clause))).mappings().first()
        if found is None:
            raise HTTPException(404, f"no such row in {name}")
        before = dict(found)
    if cls == RUNTIME:
        if before is not None:
            await _refuse_if_active(session, table, before)
        if body.op != "delete":
            await _refuse_if_active(session, table, {**(before or {}), **values})

    after: Optional[dict] = None
    try:
        if body.op == "insert":
            if not values:
                raise HTTPException(422, "an insert needs values")
            after = dict((await session.execute(
                insert(table).values(**values).returning(table))).mappings().first())
        elif body.op == "update":
            if not values:
                raise HTTPException(422, "an update needs values")
            after = dict((await session.execute(
                update(table).where(*clause).values(**values).returning(table))).mappings().first())
        else:
            await session.execute(delete(table).where(*clause))
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, f"the database refused the change: {exc.orig}") from exc
    except SQLAlchemyError as exc:
        await session.rollback()
        raise HTTPException(422, f"the database refused the change: {getattr(exc, 'orig', exc)}") from exc

    result = {"ok": True, "table": name, "class": cls, "op": body.op,
              "before": jsonable_encoder(before), "after": jsonable_encoder(after)}
    if cls == RUNTIME:
        logger.warning("runtime edit %s", json.dumps(
            {"table": name, "op": body.op, "note": body.note, "before": result["before"],
             "after": result["after"]}, default=str))
    return result


# ---------------------------------------------------------------------------
# The read-only SQL box
# ---------------------------------------------------------------------------


class SqlRequest(BaseModel):
    sql: str
    limit: int = _SQL_ROW_LIMIT_DEFAULT


_WORD = re.compile(r"[A-Za-z_]+")


def _code_only(sql: str) -> str:
    """*sql* with comments and quoted text blanked out, so what is left is its code."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
            out.append(" ")
        elif sql.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if sql.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif sql.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            out.append(" ")
        elif ch in "'\"":
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            i = j + 1
            out.append(" ")
        elif ch == "$" and (m := re.match(r"\$[A-Za-z_]*\$", sql[i:])):
            tag = m.group(0)
            j = sql.find(tag, i + len(tag))
            i = n if j < 0 else j + len(tag)
            out.append(" ")
        else:
            out.append(ch)
            i += 1
    return "".join(out).strip()


def check_read_only_sql(sql: str) -> str:
    """Return the single statement to run, or raise 400.  One ``SELECT`` or ``WITH`` only."""
    code = _code_only(sql)
    body = code[:-1].rstrip() if code.endswith(";") else code
    if not body:
        raise HTTPException(400, "enter a SELECT or WITH statement")
    if ";" in body:
        raise HTTPException(400, "one statement only: a second statement after ';' is refused")
    first = _WORD.match(body)
    if first is None or first.group(0).lower() not in ("select", "with"):
        raise HTTPException(400, "only a SELECT or WITH statement can be run here")
    return sql.strip().rstrip(";").rstrip()


@router.post("/sql", summary="Run one read-only SELECT or WITH statement")
async def post_sql(body: SqlRequest, session: AsyncSession = Depends(get_session)):
    """Run one ``SELECT`` or ``WITH`` statement in a read-only transaction.

    A row limit and a statement timeout apply.  This shows the database, including a
    session's stored rows (which are not a live session's current state).
    """
    statement = check_read_only_sql(body.sql)
    limit = max(1, min(body.limit, _SQL_ROW_LIMIT_MAX))
    # text() reads ":name" as a bind parameter; "\\:" is a literal colon.
    escaped = statement.replace(":", "\\:")
    try:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text(f"SET LOCAL statement_timeout = {_SQL_TIMEOUT_MS}"))
        result = await session.execute(
            text(f"SELECT * FROM (\n{escaped}\n) AS q LIMIT {limit + 1}"))
        columns = list(result.keys())
        rows = [list(r) for r in result.fetchall()]
    except SQLAlchemyError as exc:
        raise HTTPException(
            400, f"the database refused the statement: {getattr(exc, 'orig', exc)}") from exc
    finally:
        await session.rollback()
    return {
        "columns": columns,
        "rows": jsonable_encoder(rows[:limit]),
        "row_count": min(len(rows), limit),
        "truncated": len(rows) > limit,
        "limit": limit,
        "timeout_ms": _SQL_TIMEOUT_MS,
    }
