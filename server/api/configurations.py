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
from server.services import configuration_compare as compare_service
from server.services import configuration_edits as edits
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


@router.get("/compare")
async def get_compare(a: str, b: str, session: AsyncSession = Depends(get_session)):
    """A row-level diff, by table and natural key, of configuration ``a`` against ``b``.

    Either is a configuration id or ``standard`` (the Metacat Standard Configuration).  A row
    is ``added`` when only ``a`` has it, ``removed`` when only ``b`` has it, and ``changed``
    (with the differing columns on both sides) when both do.  Declared before the
    ``/{configuration_id}`` routes so ``compare`` is not read as an id.
    """
    try:
        return await compare_service.compare(session, a, b)
    except Exception as exc:
        raise _http(exc)


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


class ApplyFromRequest(BaseModel):
    #: A configuration id or ``"standard"``.
    source: int | str
    rows: list[RowRef] = Field(min_length=1)
    #: The reason, kept in the journal entry.
    note: str = ""
    #: Resolve and report without writing (the preview).
    dry_run: bool = False


@router.post("/{configuration_id}/apply-from")
async def post_apply_from(
    configuration_id: int, body: ApplyFromRequest, session: AsyncSession = Depends(get_session)
):
    """Make the chosen rows of this configuration equal another's (or the standard's).

    Restore-selected generalised: ``source`` is a configuration id or ``standard``.  It is a
    change batch (``source = restore``, ``actor = admin``) through the change API, so it has a
    preview (``dry_run``), the reason (``note``), a journal entry and a revision.  The answer
    is the change API's report, with ``wrote``, ``ops`` and ``skipped_rows``.
    """
    try:
        return await compare_service.apply_from(
            session, configuration_id, body.source, [r.model_dump() for r in body.rows],
            note=body.note, dry_run=body.dry_run)
    except ChangeError as exc:
        return error_response(exc)
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


# ---------------------------------------------------------------------------
# Edit-all (C12): one edit sent to chosen or all configurations, with a preview
# ---------------------------------------------------------------------------


class EditTargets(BaseModel):
    ids: list[int] | None = None
    all: bool = False


class EditPreviewRequest(BaseModel):
    ops: list[dict[str, Any]]
    targets: EditTargets
    #: The revision the editor read, per configuration id; a target not named is previewed at head.
    base_revisions: dict[int, int] = Field(default_factory=dict)
    note: str = ""


class EditCommitRequest(BaseModel):
    preview_token: str
    #: Configuration ids to re-send without ``expect`` (their result was ``differs``).
    overwrite: list[int] = Field(default_factory=list)
    #: Configuration ids to re-send with only the ops that do apply (``not_applicable``).
    apply_rest: list[int] = Field(default_factory=list)
    all_or_nothing: bool = False
    reason: str = ""


def _edit_http(exc: edits.EditError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


@router.post("/edits/preview")
async def post_edits_preview(body: EditPreviewRequest, session: AsyncSession = Depends(get_session)):
    """Preview one edit on chosen or all configurations: ``dry_run`` on each target.

    ``targets`` is ``{ids: [...]}`` (chosen, sent even when frozen) or ``{all: true}`` (every
    configuration; a ``frozen`` one is ``skipped_by_selection``).  The answer has one result per
    target (``apply``, ``no_change``, ``differs``, ``not_applicable``, ``stale`` or
    ``skipped_by_selection``) and the ``preview_token`` the commit needs.  Nothing is written.
    Editing every configuration is a human Admin action: each batch has ``actor = admin``.
    """
    try:
        return await edits.preview(
            session, body.ops, ids=body.targets.ids, all_=body.targets.all,
            base_revisions=body.base_revisions, note=body.note)
    except edits.EditError as exc:
        raise _edit_http(exc)
    except ChangeError as exc:
        return error_response(exc)


@router.post("/edits")
async def post_edits(body: EditCommitRequest, session: AsyncSession = Depends(get_session)):
    """Commit a previewed edit.  Each reached configuration takes its own batch (own journal
    entry and revision bump, a live session's in memory with ``persisted: false``); all share
    ``group_id``.  A skipped target never blocks another.  ``all_or_nothing`` writes nothing
    unless every reached target applies (3.16.3).  A target whose revision moved since the
    preview is ``stale`` with a fresh ``re_preview`` and is not written."""
    try:
        return await edits.commit(
            session, body.preview_token, overwrite=body.overwrite, apply_rest=body.apply_rest,
            all_or_nothing=body.all_or_nothing, reason=body.reason)
    except edits.EditError as exc:
        raise _edit_http(exc)
    except ChangeError as exc:
        return error_response(exc)
    except journal.ConfigurationNotAdopted as exc:
        raise HTTPException(500, str(exc))
