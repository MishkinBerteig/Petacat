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
    """The Training Session's Episodic Memory — what the program can be reminded of.

    Served from the live memory, not from the rows.  The two differ by exactly the
    answers a **Fast Run** contributed: a Fast Run takes part in the session like any
    other but writes nothing, so reading the rows would show a memory missing answers
    the program is demonstrably using — which is what "Fast Run is not contributing to
    episodic memory" looked like from the UI, even once it was.

    The rows remain the durable record; ``rehydrate_memory`` loads them into this same
    object at startup, so after a restart the live memory is the rows plus whatever the
    session has added since.
    """
    svc = get_run_service()
    return svc.get_memory_state()


@router.delete("")
async def clear_memory(session: AsyncSession = Depends(get_session)):
    """Clear all episodic memory — both the stored rows and the live object."""
    svc = get_run_service()
    removed = await svc.clear_memory(session)
    return {"cleared": True, "removed": removed}


@router.delete("/answers/{answer_id}")
async def forget_answer(
    answer_id: int, session: AsyncSession = Depends(get_session)
):
    """Delete a single answer description.

    MetaCat can forget one answer without forgetting all of them (``memory.ss:42-54``),
    and §5.2.3 depends on it: the experiment there works by manually deleting the
    just-found answer from memory and re-running. With only clear-all, that experiment
    cannot be reproduced — and since ``answer_present`` now keeps the program from
    rediscovering a stored answer, deleting one is also how a user asks for it again.
    """
    svc = get_run_service()
    removed = await svc.forget_answer(session, answer_id)
    if not removed:
        raise HTTPException(404, f"Answer {answer_id} not found")
    return {"forgotten": answer_id}


@router.post("/answers/{answer_id}/display")
async def display_answer(answer_id: int, run_id: int):
    """Impose a stored answer's three theme-patterns over the live Themespace.

    Scheme: ``memory.ss:268-283`` — clicking an answer icon re-enters that episode:
    its Workspace is redrawn and its vertical, top and bottom theme-patterns are
    imposed (``trace.ss:415-420``). Calling again restores the live state, as clicking
    a second time does in MetaCat.

    ``run_id`` says whose Themespace to display it over: an answer outlives the Run
    that found it, so it does not know one of its own.
    """
    svc = get_run_service()
    try:
        return svc.impose_answer(run_id, answer_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None


def _find_answer(answer_id: int):
    from server.services.run_service import _global_memory

    for answer in _global_memory.answers:
        if answer.answer_id == answer_id:
            return answer
    raise HTTPException(404, f"Answer {answer_id} not found")


@router.post("/compare")
async def compare_answers(req: CompareRequest):
    """Compare two answers by their IDs.

    §4.7.3 – §4.7.4.  The prose is rendered from the *live* commentary templates, so an
    edit made through the admin UI shows up in the very next comparison; that is the
    whole point of the templates being data (§4.6: the program's English "is purely an
    illusion arising from a flexible set of phrase-templates").
    """
    from server.services.run_service import _global_memory

    answer_a = _find_answer(req.answer_id_1)
    answer_b = _find_answer(req.answer_id_2)

    from server.engine.commentary import describe_answer_comparison

    svc = get_run_service()
    templates = svc.meta.commentary_templates
    comparison = _global_memory.compare_answers(
        answer_a, answer_b, templates=templates, meta=svc.meta
    )
    return {
        "answer_id_1": req.answer_id_1,
        "answer_id_2": req.answer_id_2,
        "comparison": comparison,
        "commentary": describe_answer_comparison(
            answer_a,
            answer_b,
            memory=_global_memory,
            templates=templates,
            meta=svc.meta,
        ),
    }


@router.get("/answers/{answer_id}/explanation")
async def explain_answer(answer_id: int, eliza_mode: bool = False):
    """What one answer is based on, in the program's own words.

    Scheme: ``explain`` (``answers.ss:310-333``) — "This answer is based on seeing abc
    and xyz as groups of the same type going in the same direction.  Personally, I
    think this answer is pretty good."  MetaCat offers this for a single answer
    alongside the two-answer comparison.

    Both voices are returned: they are isomorphic by construction (§4.6, pp. 183-184),
    so a client can toggle Eliza mode without another request.
    """
    from server.engine.commentary import describe_answer
    from server.services.run_service import _global_memory

    answer = _find_answer(answer_id)
    svc = get_run_service()
    explanation = describe_answer(
        answer, memory=_global_memory, templates=svc.meta.commentary_templates
    )
    return {
        "answer_id": answer_id,
        "problem": list(answer.problem),
        "eliza_mode": eliza_mode,
        "text": (
            explanation["eliza_text"] if eliza_mode else explanation["technical_text"]
        ),
        **explanation,
    }
