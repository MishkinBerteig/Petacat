"""Configuration-wide actions: status, diff, reset to the Metacat Standard Configuration,
restore-selected and verify-journal (configuration plan 3.6).

``/api/configurations/{id}/...``; ``id`` 1 is the global configuration (Metacat Mode).  Reset
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
from server.services import journal

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
    if isinstance(exc, admin.UnknownConfiguration):
        return HTTPException(404, str(exc))
    if isinstance(exc, admin.NotYetSupported):
        return HTTPException(501, str(exc))
    if isinstance(exc, admin.UnknownRow):
        return HTTPException(422, str(exc))
    if isinstance(exc, journal.JournalError):
        return HTTPException(409, str(exc))
    if isinstance(exc, IntegrityError):
        return HTTPException(
            409, "the change conflicts with other rows (a foreign key): select the rows it "
                 "depends on as well, or reset the whole configuration")
    raise exc


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
