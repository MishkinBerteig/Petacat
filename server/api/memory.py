"""FastAPI router for cross-run episodic memory.

Provides access to the shared episodic memory (answer + snag descriptions)
that persists across runs, backed by the database.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.runs import get_run_service
from server.db import get_session

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------


class CompareRequest(BaseModel):
    answer_id_1: int
    answer_id_2: int


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get("")
async def list_memory(session: AsyncSession = Depends(get_session)):
    """List all stored answer and snag descriptions (from DB)."""
    svc = get_run_service()
    return await svc.get_memory_state_from_db(session)


@router.delete("")
async def clear_memory():
    """Clear all episodic memory."""
    from server.services.run_service import _global_memory

    _global_memory.clear()
    return {"cleared": True}


@router.post("/compare")
async def compare_answers(req: CompareRequest):
    """Compare two answers by their IDs."""
    from server.services.run_service import _global_memory

    # Find the two answer descriptions
    answer_a = None
    answer_b = None
    for a in _global_memory.answers:
        if a.answer_id == req.answer_id_1:
            answer_a = a
        if a.answer_id == req.answer_id_2:
            answer_b = a

    if answer_a is None:
        raise HTTPException(404, f"Answer {req.answer_id_1} not found")
    if answer_b is None:
        raise HTTPException(404, f"Answer {req.answer_id_2} not found")

    comparison = _global_memory.compare_answers(answer_a, answer_b)
    return {
        "answer_id_1": req.answer_id_1,
        "answer_id_2": req.answer_id_2,
        "comparison": comparison,
    }
