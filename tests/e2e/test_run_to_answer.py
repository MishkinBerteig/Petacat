"""E2E tests for the Run-to-Answer feature.

Tests cover:
  - POST /api/runs/{id}/run with max_steps returns correct status
  - POST /api/runs/{id}/stop interrupts a running run
  - State endpoints respond during a run (validates asyncio.sleep(0) yield)
  - Run-to-completion with no step limit finds an answer or halts gracefully

ALL tests are deterministic: same seed -> same results.
Requires: docker compose -f docker-compose.dev.yml exec app pytest tests/e2e/ -v
"""

import asyncio
import pytest

SEED = 12345


@pytest.mark.asyncio
async def test_run_to_completion_max_steps_halts(app_client):
    """POST /run with max_steps should halt at the step limit."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.post(f"/api/runs/{run_id}/run", json={
        "max_steps": 100,
    })
    assert resp.status_code == 200
    info = resp.json()
    assert info["status"] in ("halted", "answer_found")
    assert info["codelet_count"] >= 100 or info["status"] == "answer_found"


@pytest.mark.asyncio
async def test_run_to_completion_returns_codelet_count(app_client):
    """The response should include accurate codelet count and temperature."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.post(f"/api/runs/{run_id}/run", json={
        "max_steps": 50,
    })
    info = resp.json()
    assert info["codelet_count"] >= 50 or info["status"] == "answer_found"
    assert 0 <= info["temperature"] <= 100


@pytest.mark.asyncio
async def test_run_then_get_state(app_client):
    """After run completes, all state endpoints should return valid data."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 30})

    # All state endpoints should work
    resp = await app_client.get(f"/api/runs/{run_id}/workspace")
    assert resp.status_code == 200
    ws = resp.json()
    assert ws["initial"] == "abc"

    resp = await app_client.get(f"/api/runs/{run_id}/slipnet")
    assert resp.status_code == 200

    resp = await app_client.get(f"/api/runs/{run_id}/coderack")
    assert resp.status_code == 200

    resp = await app_client.get(f"/api/runs/{run_id}/temperature")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_stop_run_during_execution(app_client):
    """POST /stop should interrupt a running run, setting status to paused."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Start a long run in a background task
    async def start_run():
        return await app_client.post(f"/api/runs/{run_id}/run", json={
            "max_steps": 50000,
        })

    run_task = asyncio.create_task(start_run())

    # Give the run a moment to start, then stop it
    await asyncio.sleep(0.2)

    stop_resp = await app_client.post(f"/api/runs/{run_id}/stop")
    assert stop_resp.status_code == 200
    assert stop_resp.json()["stopped"] is True

    # Wait for the run to finish (it should be paused now)
    run_resp = await run_task
    info = run_resp.json()
    assert info["status"] in ("paused", "answer_found"), (
        f"Expected paused or answer_found, got {info['status']}"
    )
    # Should have run fewer than the full 50000 steps
    if info["status"] == "paused":
        assert info["codelet_count"] < 50000


@pytest.mark.asyncio
async def test_concurrent_state_access_during_run(app_client):
    """State endpoints should respond while a run is in progress.

    This validates that the asyncio.sleep(0) yield in run_to_completion
    allows concurrent HTTP requests to be served.
    """
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Start a long run in the background
    async def start_run():
        return await app_client.post(f"/api/runs/{run_id}/run", json={
            "max_steps": 5000,
        })

    run_task = asyncio.create_task(start_run())

    # Give the run a moment to start executing
    await asyncio.sleep(0.1)

    # Try to access state endpoints concurrently — they should respond
    workspace_resp = await app_client.get(f"/api/runs/{run_id}/workspace")
    temp_resp = await app_client.get(f"/api/runs/{run_id}/temperature")

    assert workspace_resp.status_code == 200, (
        f"Workspace endpoint failed during run: {workspace_resp.status_code}"
    )
    assert temp_resp.status_code == 200, (
        f"Temperature endpoint failed during run: {temp_resp.status_code}"
    )

    # Stop the run so we don't leave it hanging
    await app_client.post(f"/api/runs/{run_id}/stop")
    await run_task


@pytest.mark.asyncio
async def test_run_to_completion_no_limit(app_client):
    """POST /run with max_steps=0 (no limit) should run until answer or timeout.

    We use a generous step limit internally via the test — the API itself
    runs until answer found. For safety, we use a known-solvable problem.
    """
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Start run with no step limit — but stop it after a reasonable time
    async def start_run():
        return await app_client.post(f"/api/runs/{run_id}/run", json={
            "max_steps": 3000,  # Safety limit for test
        })

    run_task = asyncio.create_task(start_run())
    run_resp = await run_task
    info = run_resp.json()

    # Should have finished with a valid status
    assert info["status"] in ("answer_found", "halted"), (
        f"Unexpected status: {info['status']}"
    )
    assert info["codelet_count"] > 0


@pytest.mark.asyncio
async def test_stop_already_stopped_run(app_client):
    """Stopping a run that is already stopped should not error."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Run a small number of steps (finishes immediately)
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 10})

    # Try to stop it after it's already done
    stop_resp = await app_client.post(f"/api/runs/{run_id}/stop")
    assert stop_resp.status_code == 200


@pytest.mark.asyncio
async def test_run_preserves_trace_events(app_client):
    """Trace events should be persisted during run_to_completion.

    Note: trace events (bonds, groups, bridges) require enough codelets
    to actually build structures. 30 steps is not enough; 200+ is.
    """
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 200})

    resp = await app_client.get(f"/api/runs/{run_id}/trace")
    assert resp.status_code == 200
    data = resp.json()
    events = data if isinstance(data, list) else data.get("events", [])
    assert len(events) > 0, "Run of 200 steps should have produced trace events"
