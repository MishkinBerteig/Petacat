"""Configuration-wide actions: status, diff, reset to the Metacat Standard Configuration,
restore-selected and verify-journal (configuration plan 3.6).

``/api/configurations/{id}/...``; ``id`` 1 is the global configuration (Metacat Mode); any other
is a Training Mode Session's configuration.  The entity routes (list, get, ``PATCH``, rows,
export) are C8's.  Reset
and restore are journaled changes (``source = reset`` / ``restore``) written through the
journal layer.  C14b adds the change routes to this router.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session
from server.services import configuration_admin as admin
from server.services import configurations, journal
from server.services.configuration_writer import ChangeError, ChangeService, error_response

router = APIRouter(prefix="/api/configurations", tags=["configurations"])

RESET_CONFIRMATION = "reset"


class ResetRequest(BaseModel):
    #: The typed confirmation: the word ``reset``.
    confirm: str = ""
    note: str = ""


class RowRef(BaseModel):
    table: str
    key: dict[str, Any]


class RestoreRequest(BaseModel):
    rows: list[RowRef] = Field(min_length=1)
    note: str = ""


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, (admin.UnknownConfiguration, configurations.UnknownRevision)):
        return HTTPException(404, str(exc))
    if isinstance(exc, (admin.UnknownRow, configurations.UnknownTable)):
        return HTTPException(422, str(exc))
    if isinstance(exc, configurations.ConfigurationError):
        return HTTPException(400, str(exc))
    if isinstance(exc, journal.JournalError):
        return HTTPException(409, str(exc))
    if isinstance(exc, IntegrityError):
        return HTTPException(
            409, "the change conflicts with other rows (a foreign key): select the rows it "
                 "depends on as well, or reset the whole configuration")
    raise exc


class PatchRequest(BaseModel):
    name: str | None = None
    note: str | None = None
    frozen: bool | None = None


@router.get("")
async def list_configurations(session: AsyncSession = Depends(get_session)):
    """One summary per configuration: the global one (Metacat Mode) then each Training Mode
    Session's (mode badge, revision, ``frozen``, rows differing from the Metacat Standard
    Configuration, last change)."""
    try:
        return {"configurations": await configurations.list_configurations(session)}
    except Exception as exc:
        raise _http(exc)


@router.get("/{configuration_id}")
async def get_configuration(configuration_id: int, session: AsyncSession = Depends(get_session)):
    try:
        return await configurations.summary(session, configuration_id)
    except Exception as exc:
        raise _http(exc)


@router.patch("/{configuration_id}")
async def patch_configuration(
    configuration_id: int, body: PatchRequest, session: AsyncSession = Depends(get_session)
):
    """Name, note and ``frozen``: one journaled entry (no ops) that takes the next revision."""
    if body.name is None and body.note is None and body.frozen is None:
        raise HTTPException(400, "give name, note or frozen")
    try:
        return await configurations.update_meta(
            session, configuration_id, name=body.name, note=body.note, frozen=body.frozen)
    except Exception as exc:
        await session.rollback()
        raise _http(exc)


@router.get("/{configuration_id}/rows")
async def get_rows(
    configuration_id: int, table: str | None = None, session: AsyncSession = Depends(get_session)
):
    """The rows of ``table``; without it, the table names with their row counts."""
    try:
        return await configurations.rows(session, configuration_id, table)
    except Exception as exc:
        raise _http(exc)


@router.get("/{configuration_id}/export")
async def get_export(configuration_id: int, session: AsyncSession = Depends(get_session)):
    """The whole configuration as one JSON bundle (a download)."""
    from fastapi.responses import JSONResponse

    try:
        bundle = await configurations.export(session, configuration_id)
    except Exception as exc:
        raise _http(exc)
    return JSONResponse(
        bundle,
        headers={"Content-Disposition": f'attachment; filename="configuration-{configuration_id}.json"'},
    )


@router.get("/{configuration_id}/status")
async def get_status(configuration_id: int, session: AsyncSession = Depends(get_session)):
    try:
        return await admin.status(session, configuration_id)
    except Exception as exc:
        raise _http(exc)


@router.get("/{configuration_id}/diff")
async def get_diff(configuration_id: int, session: AsyncSession = Depends(get_session)):
    try:
        return await admin.diff(session, configuration_id)
    except Exception as exc:
        raise _http(exc)


@router.post("/{configuration_id}/reset-to-standard")
async def post_reset(
    configuration_id: int, body: ResetRequest, session: AsyncSession = Depends(get_session)
):
    if body.confirm != RESET_CONFIRMATION:
        raise HTTPException(
            400, f'resetting needs the typed confirmation {{"confirm": "{RESET_CONFIRMATION}"}}')
    try:
        return await admin.reset_to_standard(session, configuration_id, note=body.note)
    except Exception as exc:
        raise _http(exc)


@router.post("/{configuration_id}/restore-selected")
async def post_restore_selected(
    configuration_id: int, body: RestoreRequest, session: AsyncSession = Depends(get_session)
):
    try:
        return await admin.restore_selected(
            session, [r.model_dump() for r in body.rows], configuration_id, note=body.note)
    except Exception as exc:
        await session.rollback()
        raise _http(exc)


@router.get("/{configuration_id}/verify-journal")
async def get_verify_journal(configuration_id: int, session: AsyncSession = Depends(get_session)):
    try:
        return await admin.verify_journal(session, configuration_id)
    except Exception as exc:
        raise _http(exc)


# ---------------------------------------------------------------------------
# The change API (C14b): one batch endpoint for every writer, and its schema
# ---------------------------------------------------------------------------


@router.post("/{configuration_id}/changes")
async def post_changes(
    configuration_id: int, body: dict[str, Any], session: AsyncSession = Depends(get_session)
):
    """Submit a batch of changes to configuration ``configuration_id`` (1 is the global one).

    The one change API: the Admin editors, the Database editor, restore, reset, import, the
    external route and an in-worker learner all submit the same batch.  The body is
    ``{source, actor, note, base_version, base_mode, on_op_failure, dry_run, ops}`` (``GET
    .../schema`` lists the fields and the ops).  The answer is the report: ``applied``,
    ``skipped``, ``cascaded``, ``dangling``, ``affected``, ``effects``, ``advisories``, the
    versions and the journal entry's id (``batch_id``); with ``dry_run`` nothing is written.
    A refusal is ``{ok: false, error, status, message, problems}`` where each problem names
    its op by ``op_index``.  The global configuration (Metacat Mode) refuses the sources
    ``learner`` and ``external``.
    """
    batch = dict(body)
    if batch.setdefault("configuration_id", configuration_id) != configuration_id:
        return error_response(ChangeError(
            "malformed", "configuration_id in the batch is not the configuration in the path",
            [{"error": "malformed", "status": 400, "field": "configuration_id",
              "message": "configuration_id in the batch is not the configuration in the path"}],
        ))
    try:
        return await ChangeService.apply(session, batch)
    except ChangeError as exc:
        return error_response(exc)
    except journal.ConfigurationNotAdopted as exc:
        raise HTTPException(500, str(exc))


@router.get("/{configuration_id}/schema")
async def get_schema(configuration_id: int, session: AsyncSession = Depends(get_session)):
    """The registry of tables a batch can address (keys, order, columns, references), the
    ops, and the shape of a batch."""
    from server.models.journal import Configuration
    from server.services import configuration_input as ci
    from server.services.change_resolve import schema

    if await session.get(Configuration, configuration_id) is None:
        raise HTTPException(404, f"no configuration {configuration_id}")
    return {
        **schema(),
        "batch": {
            "fields": {
                "configuration_id": "integer; optional (the path decides)",
                "source": f"one of {list(ci.SOURCES)}; required",
                "actor": "text; optional",
                "note": "text; optional",
                "channel": "text; optional (the finer route, kept in the journal)",
                "group_id": "text; optional (an edit-all's group)",
                "base_version": 'an integer revision or "head"; required under base_mode strict',
                "base_mode": f"one of {list(ci.BASE_MODES)}; default strict",
                "on_op_failure": f"one of {list(ci.ON_OP_FAILURE)}; default abort",
                "dry_run": "true to resolve and report without writing",
                "ops": "a list of ops",
            },
            "generic_ops": {
                "insert": {"op": "insert", "table": "t", "row": {}},
                "update": {
                    "op": "update", "table": "t", "key": {}, "fields": {},
                    "patch": "optional {column: [JSON Patch ops]}",
                    "expect": "optional {column: value} checked first",
                },
                "delete": {
                    "op": "delete", "table": "t", "key": {}, "expect": "optional",
                    "ok_if_missing": "optional",
                },
            },
        },
    }
