"""The read side of a Training Mode Session's configuration, for its API (S6).

Every function takes the :class:`TrainingModeSessionService` and a session id, and answers what
``/api/training-mode/sessions/{id}/configuration``, ``/configuration/diff``, ``/slipnet``,
``/journal`` and ``/export?what=configuration|journal`` serve.  A **version** is a configuration
revision: the same number as ``configuration.version`` in the summary and ``revision`` in the
journal.

* A Stopped session is read from the database ("stored").
* A live session (Running, Paused or Stopping) at its current version is read from memory
  ("live"), and every read says so with the summary's ``saved_through`` and ``unsaved``.  A
  version that is held in memory only and is not the current one cannot be rebuilt: it is a 409
  naming the saved and current versions.  A version the session never had is a 404.
* A session that is Starting has no live document yet, so it is read as stored.

Nothing here writes.
"""

from __future__ import annotations

from typing import Any

from server.services import config_document as cd
from server.services import configuration_admin as admin
from server.services import configurations, journal_views
from server.services.training_mode_session_service import SessionError, TrainingModeSessionService

#: The slipnet projection's tables: nodes, links and the layout the graph view places them with.
SLIPNET_TABLES = {"nodes": "slipnet_node_defs", "links": "slipnet_link_defs", "layout": "slipnet_layout"}


async def _configuration_row(service: TrainingModeSessionService, db: Any, session_id: int) -> dict:
    await service._get_session(db, session_id)  # 404 SessionError for an unknown session
    try:
        return await configurations.row_for_session(db, session_id)
    except configurations.ConfigurationError as exc:
        raise SessionError(404, str(exc)) from exc


async def _label(service: TrainingModeSessionService, session_id: int) -> dict[str, Any]:
    """The labels every read carries: stored or live, and where the database stands."""
    summary = await service.summary(session_id)
    return {
        "session_id": session_id,
        "state": summary["state"],
        "source": summary["source"],
        "saved_through": summary["saved_through"],
        "unsaved": summary["unsaved"],
    }


async def _document(
    service: TrainingModeSessionService, db: Any, row: dict, session_id: int, version: int | None
) -> tuple[cd.ConfigDocument, int]:
    """``(document, version)``: the session's configuration at *version* (the current one when
    ``None``).  A live document's own ``version`` is the Training episode version, so the
    configuration revision is returned beside it."""
    from server.services.configuration_store import live_state

    live = live_state(session_id)
    if live is not None and live.document is not None:
        if version is None or version == live.revision:
            return live.document, live.revision
        if version > live.revision or version < 0:
            raise SessionError(
                404, f"session {session_id}'s configuration has versions 0 to {live.revision}, "
                     f"not {version}")
        if version > live.saved_through:
            raise SessionError(
                409, f"version {version} is held in memory only (saved through version "
                     f"{live.saved_through}, current version {live.revision}); read the current "
                     "version, or stop the session to store it")
    try:
        document = await configurations.config_at(db, row["id"], version)
        return document, document.version
    except configurations.UnknownRevision as exc:
        raise SessionError(404, str(exc)) from exc


async def configuration(
    service: TrainingModeSessionService, session_id: int, version: int | None, table: str | None
) -> dict[str, Any]:
    """The configuration at a version: the table row counts, or one table's rows."""
    async with service.database() as db:
        row = await _configuration_row(service, db, session_id)
        document, number = await _document(service, db, row, session_id, version)
    out: dict[str, Any] = {
        "configuration_id": row["id"], "version": number,
        "config_hash": cd.config_hash(document), **await _label(service, session_id),
    }
    if table is None:
        return {**out, "tables": {t: len(document.tables[t]) for t in cd.TABLE_NAMES}}
    if table not in cd.TABLE_NAMES:
        raise SessionError(422, f"{table!r} is not a configuration table")
    listed = [dict(r) for r in document.tables[table].values()]
    return {**out, "table": table, "key_columns": list(cd.key_columns(table)),
            "count": len(listed), "rows": listed}


async def diff(
    service: TrainingModeSessionService, session_id: int, from_version: int, to_version: int | None
) -> dict[str, Any]:
    """Rows added, removed or changed going from one version to another (``to`` defaults to the
    current version)."""
    async with service.database() as db:
        row = await _configuration_row(service, db, session_id)
        before, from_number = await _document(service, db, row, session_id, from_version)
        after, to_number = await _document(service, db, row, session_id, to_version)
    rows = [
        {"table": i["table"], "key": i["key"], "change": i["change"], "from": i["standard"],
         "to": i["current"], "columns": i["columns"]}
        for i in admin.compare(after, before)
    ]
    return {
        "configuration_id": row["id"], "from": from_number, "to": to_number,
        "same": not rows, "count": len(rows),
        "added": sum(r["change"] == admin.CHANGE_ADDED for r in rows),
        "removed": sum(r["change"] == admin.CHANGE_REMOVED for r in rows),
        "changed": sum(r["change"] == admin.CHANGE_CHANGED for r in rows),
        "rows": rows, **await _label(service, session_id),
    }


async def slipnet(
    service: TrainingModeSessionService, session_id: int, version: int | None
) -> dict[str, Any]:
    """The Slipnet graph at a version: ``nodes``, ``links`` and ``layout`` rows (a node with no
    layout row is unplaced; the view places it)."""
    async with service.database() as db:
        row = await _configuration_row(service, db, session_id)
        document, number = await _document(service, db, row, session_id, version)
    out = {key: [dict(r) for r in document.tables[table].values()]
           for key, table in SLIPNET_TABLES.items()}
    placed = {r["node_name"] for r in out["layout"]}
    return {
        "configuration_id": row["id"], "version": number,
        "config_hash": cd.config_hash(document), **out,
        "unplaced": [n["name"] for n in out["nodes"] if n["name"] not in placed],
        **await _label(service, session_id),
    }


async def journal(
    service: TrainingModeSessionService, session_id: int, *, from_version: int | None,
    to_version: int | None, source: str | None, actor: str | None, limit: int, offset: int,
    detail: bool,
) -> dict[str, Any]:
    """The session's journal timeline, newest first.  A live session's entries held in memory
    are included with ``pending: true`` and the label "not yet saved"."""
    async with service.database() as db:
        row = await _configuration_row(service, db, session_id)
        try:
            listed = await journal_views.list_entries(
                db, configuration_id=row["id"], source=source, actor=actor,
                revision_from=from_version, revision_to=to_version, limit=limit, offset=offset,
                detail=detail)
        except journal_views.JournalError as exc:
            raise SessionError(400, str(exc)) from exc
    return {"session_id": session_id, **listed, **await _label(service, session_id)}


async def export_configuration(
    service: TrainingModeSessionService, session_id: int, version: int | None
) -> dict[str, Any]:
    """The configuration at a version as one bundle (the shape of ``GET /api/configurations/{id}/export``)."""
    async with service.database() as db:
        row = await _configuration_row(service, db, session_id)
        document, number = await _document(service, db, row, session_id, version)
        head = await configurations.summary(db, row["id"])
    head.update(await _label(service, session_id), version=number,
                config_hash=cd.config_hash(document))
    return {"format": "petacat-configuration", "configuration": head, "data": cd.to_data(document)}


async def export_journal(service: TrainingModeSessionService, session_id: int) -> dict[str, Any]:
    """Every journal entry in full (proposed, resolved and before-images), oldest first."""
    entries: list[dict[str, Any]] = []
    first = await journal(service, session_id, from_version=None, to_version=None, source=None,
                          actor=None, limit=1000, offset=0, detail=True)
    entries.extend(first["entries"])
    while len(entries) < first["total"]:
        page = await journal(service, session_id, from_version=None, to_version=None, source=None,
                             actor=None, limit=1000, offset=len(entries), detail=True)
        if not page["entries"]:
            break
        entries.extend(page["entries"])
    entries.reverse()
    return {"format": "petacat-session-journal", "session_id": session_id,
            "count": len(entries), "entries": entries,
            **{k: first[k] for k in ("state", "source", "saved_through", "unsaved", "live")}}
