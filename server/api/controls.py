"""FastAPI router for interactive run controls.

Breakpoints, step size, theme/codelet/temperature/node clamping.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.api.runs import get_run_service

router = APIRouter(prefix="/api/runs/{run_id}", tags=["controls"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------


class SetBreakpointRequest(BaseModel):
    codelet_count: int


class SetStepSizeRequest(BaseModel):
    step_size: int


class ThemeClampItem(BaseModel):
    type: str
    dimension: str
    relation: str | None = None
    activation: float = 100.0


class ClampThemesRequest(BaseModel):
    themes: list[ThemeClampItem]


class ClampCodeletsRequest(BaseModel):
    codelet_type: str
    urgency: int


class UnclampCodeletsRequest(BaseModel):
    codelet_type: str


class ClampTemperatureRequest(BaseModel):
    value: float
    cycles: int = 0


class ClampNodeRequest(BaseModel):
    node_name: str
    cycles: int = 0


class UnclampNodeRequest(BaseModel):
    node_name: str


class SetSpreadingThresholdRequest(BaseModel):
    threshold: int


# ------------------------------------------------------------------
# Spreading activation threshold
# ------------------------------------------------------------------


@router.post("/spreading-threshold")
async def set_spreading_threshold(run_id: int, req: SetSpreadingThresholdRequest):
    """Set the spreading activation threshold (0–100).

    At 100 (default), only fully-active nodes spread — matching the original
    Scheme implementation. At 0, all active nodes spread.
    """
    svc = get_run_service()
    try:
        result = svc.set_spreading_threshold(run_id, req.threshold)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.get("/spreading-threshold")
async def get_spreading_threshold(run_id: int):
    """Get the current spreading activation threshold."""
    svc = get_run_service()
    try:
        result = svc.get_spreading_threshold(run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


# ------------------------------------------------------------------
# Breakpoints & execution control
# ------------------------------------------------------------------


@router.post("/breakpoint")
async def set_breakpoint(run_id: int, req: SetBreakpointRequest):
    """Set a breakpoint at a given codelet count."""
    svc = get_run_service()
    try:
        result = svc.set_breakpoint(run_id, req.codelet_count)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.delete("/breakpoint")
async def clear_breakpoint(run_id: int):
    """Clear the breakpoint for a run."""
    svc = get_run_service()
    try:
        result = svc.clear_breakpoint(run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.put("/step-size")
async def set_step_size(run_id: int, req: SetStepSizeRequest):
    """Set the step size for a run."""
    svc = get_run_service()
    try:
        result = svc.set_step_size(run_id, req.step_size)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


# ------------------------------------------------------------------
# Theme clamping
# ------------------------------------------------------------------


@router.post("/clamp-themes")
async def clamp_themes(run_id: int, req: ClampThemesRequest):
    """Clamp themes in the themespace."""
    svc = get_run_service()
    try:
        result = svc.clamp_themes(
            run_id,
            [t.model_dump() for t in req.themes],
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.delete("/clamp-themes")
async def unclamp_themes(run_id: int):
    """Unclamp all themes in the themespace."""
    svc = get_run_service()
    try:
        result = svc.unclamp_themes(run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


# ------------------------------------------------------------------
# Codelet clamping
# ------------------------------------------------------------------


@router.post("/clamp-codelets")
async def clamp_codelets(run_id: int, req: ClampCodeletsRequest):
    """Clamp a codelet type to a minimum urgency."""
    svc = get_run_service()
    try:
        result = svc.clamp_codelets(run_id, req.codelet_type, req.urgency)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.delete("/clamp-codelets")
async def unclamp_codelets(run_id: int, req: UnclampCodeletsRequest):
    """Unclamp a codelet type."""
    svc = get_run_service()
    try:
        result = svc.unclamp_codelets(run_id, req.codelet_type)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


# ------------------------------------------------------------------
# Temperature clamping
# ------------------------------------------------------------------


@router.post("/clamp-temperature")
async def clamp_temperature(run_id: int, req: ClampTemperatureRequest):
    """Clamp temperature to a fixed value."""
    svc = get_run_service()
    try:
        result = svc.clamp_temperature(run_id, req.value, req.cycles)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.delete("/clamp-temperature")
async def unclamp_temperature(run_id: int):
    """Unclamp temperature."""
    svc = get_run_service()
    try:
        result = svc.unclamp_temperature(run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


# ------------------------------------------------------------------
# Slipnet node clamping
# ------------------------------------------------------------------


@router.post("/clamp-node")
async def clamp_node(run_id: int, req: ClampNodeRequest):
    """Clamp a slipnet node to full activation."""
    svc = get_run_service()
    try:
        result = svc.clamp_node(run_id, req.node_name, req.cycles)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.delete("/clamp-node")
async def unclamp_node(run_id: int, req: UnclampNodeRequest):
    """Unclamp a slipnet node."""
    svc = get_run_service()
    try:
        result = svc.unclamp_node(run_id, req.node_name)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result
