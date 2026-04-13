"""WebSocket endpoint for live state push.

Sends periodic state snapshots while a run is active.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/runs/{run_id}")
async def run_websocket(websocket: WebSocket, run_id: int):
    """Live state push for a running Metacat engine.

    Sends periodic JSON snapshots of run state (temperature, codelet count,
    coderack summary, workspace summary) while the connection is open.
    The client can send JSON messages to control the push interval:
        {"set_interval": 1.0}  -- set push interval in seconds
        {"pause": true}        -- pause state push
        {"resume": true}       -- resume state push
    """
    await websocket.accept()

    # Import here to avoid circular imports at module level
    from server.api.runs import _run_service

    if _run_service is None:
        await websocket.send_json({"error": "RunService not initialized"})
        await websocket.close(code=1011)
        return

    runner = _run_service.get_runner(run_id)
    if runner is None:
        await websocket.send_json({"error": f"Run {run_id} not found"})
        await websocket.close(code=1008)
        return

    interval: float = 0.5  # Default push interval in seconds
    paused: bool = False

    async def receive_commands():
        """Listen for client control messages."""
        nonlocal interval, paused
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if "set_interval" in msg:
                    interval = max(0.1, float(msg["set_interval"]))
                if msg.get("pause"):
                    paused = True
                if msg.get("resume"):
                    paused = False
        except WebSocketDisconnect:
            pass

    async def push_state():
        """Periodically push state snapshots."""
        try:
            while True:
                await asyncio.sleep(interval)
                if paused:
                    continue

                # Re-fetch runner in case it changed
                current_runner = _run_service.get_runner(run_id)
                if current_runner is None or current_runner.ctx is None:
                    await websocket.send_json({
                        "run_id": run_id,
                        "status": "not_found",
                    })
                    continue

                ctx = current_runner.ctx
                snapshot = {
                    "run_id": run_id,
                    "status": current_runner.status,
                    "codelet_count": ctx.codelet_count,
                    "temperature": round(ctx.temperature.value, 2),
                    "temperature_clamped": ctx.temperature.clamped,
                    "coderack_count": ctx.coderack.total_count,
                    "trace_event_count": len(ctx.trace.events),
                    "snag_count": ctx.trace.snag_count,
                    "within_clamp_period": ctx.trace.within_clamp_period,
                }
                await websocket.send_json(snapshot)

        except WebSocketDisconnect:
            pass

    # Run both tasks concurrently; when one exits the other is cancelled
    receive_task = asyncio.create_task(receive_commands())
    push_task = asyncio.create_task(push_state())

    try:
        done, pending = await asyncio.wait(
            {receive_task, push_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except Exception:
        receive_task.cancel()
        push_task.cancel()
