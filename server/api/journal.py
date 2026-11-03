"""The journal's views (configuration plan 3.10.6, 3.11): history, as-of, a name's story, and
restore or undo.

* ``GET /api/journal``: the entries, filtered; a live session's pending entries are merged in
  and labelled "not yet saved".  ``GET /api/journal/{entry_id}`` is one entry in full.
* ``GET /api/journal/where-did-name-go``: a name's story.  ``POST /api/journal/check-names``
  takes the names found in an Episodic Memory and answers the ones the configuration lacks,
  each with its story (the "names that no longer resolve" panels).
* ``GET /api/configurations/{id}/as-of``: the configuration, a table or a row at a revision
  or a time.
* ``POST /api/configurations/{id}/restore``: put an entity back as of a revision, or undo one
  batch or one group.  A restore and an undo are new journal entries, never rewrites.

Everything here reads the journal or writes through the journal layer.  A live Training Mode
Session's configuration is held in memory and written only at Stop; a restore or an undo is
refused for it (409) because the layer's door for a live session is the session service's.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session
from server.models.journal import GLOBAL_CONFIGURATION_ID, KIND_GLOBAL
from server.services import configurations, journal, journal_views
from server.services.configuration_store import live_state

router = APIRouter(tags=["journal"])


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, (configurations.UnknownConfiguration, configurations.UnknownRevision,
                        journal.MissingKey)):
        return HTTPException(404, str(exc))
    if isinstance(exc, configurations.ConfigurationError):
        return HTTPException(400, str(exc))
    if isinstance(exc, journal.SourceRefused):
        return HTTPException(400, str(exc))
    if isinstance(exc, journal.JournalError):
        return HTTPException(409, str(exc))
    if isinstance(exc, IntegrityError):
        return HTTPException(
            409, "the change conflicts with other rows (a foreign key): restore the rows it "
                 "depends on as well")
    raise exc


def _json_object(text: str | None, what: str) -> dict | None:
    if text is None:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        raise HTTPException(422, f"{what} must be a JSON object")
    if not isinstance(value, dict):
        raise HTTPException(422, f"{what} must be a JSON object")
    return value


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@router.get("/api/journal")
async def get_journal(
    configuration_id: int | None = None,
    table: str | None = None,
    key: str | None = Query(None, description='a JSON object, e.g. {"name": "plato-a"}; needs table'),
    source: str | None = None,
    actor: str | None = None,
    group_id: str | None = None,
    revision_from: int | None = Query(None, ge=0),
    revision_to: int | None = Query(None, ge=0),
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    detail: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """Journal entries, newest first: one configuration by revision, several by when they
    happened.  ``table`` keeps entries that touch the table, with ``key`` the row.  For a live
    Training Mode Session the pending entries are included with ``pending: true`` and
    ``label: "not yet saved"``, and ``live`` says where the session stands."""
    try:
        if configuration_id is not None:
            await configurations.get_row(session, configuration_id)
        return await journal_views.list_entries(
            session, configuration_id=configuration_id, table=table,
            key=_json_object(key, "key"), source=source, actor=actor, group_id=group_id,
            revision_from=revision_from, revision_to=revision_to,
            time_from=time_from, time_to=time_to, limit=limit, offset=offset, detail=detail,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _http(exc)


@router.get("/api/journal/where-did-name-go")
async def where_did_name_go(
    name: str,
    configuration_id: int = GLOBAL_CONFIGURATION_ID,
    session: AsyncSession = Depends(get_session),
):
    """A node, theme relation or codelet type name's story: created, renamed, merged,
    deleted, with who and when, whether it resolves now, and the name it carries now."""
    try:
        await configurations.get_row(session, configuration_id)
        return await journal_views.name_story(session, name, configuration_id)
    except Exception as exc:
        raise _http(exc)


class CheckNamesRequest(BaseModel):
    configuration_id: int = GLOBAL_CONFIGURATION_ID
    names: list[str] = Field(default_factory=list)


@router.post("/api/journal/check-names")
async def check_names(body: CheckNamesRequest, session: AsyncSession = Depends(get_session)):
    """Which of ``names`` the configuration lacks, each with its story.  Read-only (POST only
    because the list can be long)."""
    try:
        await configurations.get_row(session, body.configuration_id)
        return await journal_views.check_names(session, body.names, body.configuration_id)
    except Exception as exc:
        raise _http(exc)


@router.get("/api/journal/{entry_id}")
async def get_journal_entry(entry_id: int, session: AsyncSession = Depends(get_session)):
    """One entry in full: proposed ops, resolved ops and before-images."""
    try:
        return await journal_views.get_entry(session, entry_id)
    except Exception as exc:
        raise _http(exc)


@router.get("/api/configurations/{configuration_id}/as-of")
async def get_as_of(
    configuration_id: int,
    revision: int | None = Query(None, ge=0),
    time: datetime | None = None,
    table: str | None = None,
    key: str | None = Query(None, description='a JSON object; needs table'),
    session: AsyncSession = Depends(get_session),
):
    """The configuration as of a revision (or the last revision at a time).  With ``table`` the
    rows of that table; with ``table`` and ``key`` one row (``row: null`` when it did not exist
    then).  Without either, every table's rows.  Stored revisions only."""
    if (revision is None) == (time is None):
        raise HTTPException(400, "give revision or time")
    parsed_key = _json_object(key, "key")
    if parsed_key is not None and table is None:
        raise HTTPException(400, "a key needs its table")
    try:
        row = await configurations.get_row(session, configuration_id)
        if revision is None:
            revision = await journal_views.revision_at_time(session, configuration_id, time)
        if not 0 <= revision <= row["revision"]:
            raise configurations.UnknownRevision(
                f"configuration {configuration_id} has revisions 0 to {row['revision']}, "
                f"not {revision}")
        found = await journal_views.as_of(
            session, configuration_id, revision, table=table, key=parsed_key)
    except Exception as exc:
        raise _http(exc)
    head = {"configuration_id": configuration_id, "revision": revision}
    if table is not None and parsed_key is not None:
        return {**head, "table": table, "key": parsed_key, "row": found}
    if table is not None:
        return {**head, "table": table, "rows": list(found.values())}
    return {**head, "tables": {t: list(rows.values()) for t, rows in found.items()}}


# ---------------------------------------------------------------------------
# Restore and undo
# ---------------------------------------------------------------------------


class EntityRef(BaseModel):
    table: str
    key: dict[str, Any]


class RestoreRequest(BaseModel):
    """One of: ``entity`` with ``as_of_revision``; ``undo_batch`` (a journal entry id);
    ``undo_group`` (a ``group_id``)."""

    entity: EntityRef | None = None
    as_of_revision: int | None = Field(None, ge=0)
    undo_batch: int | None = None
    undo_group: str | None = None
    note: str = ""
    actor: str = "admin"


@router.post("/api/configurations/{configuration_id}/restore")
async def post_restore(
    configuration_id: int, body: RestoreRequest, session: AsyncSession = Depends(get_session)
):
    """Restore an entity as it was at a revision (a deleted node comes back with its
    dependents), or undo a batch or a group.  A new journal entry (``source = restore``);
    ``changed: false`` when the configuration already is that way."""
    modes = [body.entity is not None, body.undo_batch is not None, body.undo_group is not None]
    if sum(modes) != 1:
        raise HTTPException(400, "give entity with as_of_revision, undo_batch, or undo_group")
    if body.entity is not None and body.as_of_revision is None:
        raise HTTPException(400, "an entity restore needs as_of_revision")
    try:
        row = await configurations.get_row(session, configuration_id)
        if row["kind"] != KIND_GLOBAL and live_state(row["session_id"]) is not None:
            raise HTTPException(
                409, "this Training Mode Session is live: its configuration is held in memory "
                     "and written at Stop, so restore and undo wait until it is stopped")
        if body.entity is not None:
            result = await journal_views.restore_entity(
                session, configuration_id, body.entity.table, body.entity.key,
                body.as_of_revision, actor=body.actor, note=body.note)
        elif body.undo_batch is not None:
            result = await journal_views.undo(
                session, configuration_id, entry_id=body.undo_batch, actor=body.actor,
                note=body.note)
        else:
            result = await journal_views.undo(
                session, configuration_id, group_id=body.undo_group, actor=body.actor,
                note=body.note)
    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
        raise _http(exc)
    return {
        "configuration_id": configuration_id, "changed": result.changed,
        "revision": result.revision, "entry_id": result.entry_id,
        "ops": len(result.resolved), "config_hash": result.config_hash,
    }
