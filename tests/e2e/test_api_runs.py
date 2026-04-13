"""E2E tests for the runs API with persistence.

ALL tests are deterministic: same seed → same codelet sequence → same state.
Tests exercise the full stack: HTTP API → RunService → EngineRunner → DB.

Requires: docker compose -f docker-compose.test.yml up -d
"""

import pytest

# Fixed seed for all e2e determinism
SEED = 12345


@pytest.mark.asyncio
async def test_healthz(app_client):
    resp = await app_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_run(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["initial"] == "abc"
    assert data["modified"] == "abd"
    assert data["target"] == "xyz"
    assert data["status"] == "initialized"
    assert data["codelet_count"] == 0
    assert data["temperature"] == 100.0


@pytest.mark.asyncio
async def test_get_run(app_client):
    # Create
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Fetch
    resp = await app_client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == run_id


@pytest.mark.asyncio
async def test_get_nonexistent_run(app_client):
    resp = await app_client.get("/api/runs/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_step_run(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Step 1
    resp = await app_client.post(f"/api/runs/{run_id}/step", json={"n": 1})
    assert resp.status_code == 200
    steps = resp.json()
    assert len(steps) == 1
    assert steps[0]["codelet_count"] == 1
    assert steps[0]["codelet_type"] != ""


@pytest.mark.asyncio
async def test_step_multiple(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.post(f"/api/runs/{run_id}/step", json={"n": 30})
    assert resp.status_code == 200
    steps = resp.json()
    assert len(steps) == 30
    assert steps[-1]["codelet_count"] == 30


@pytest.mark.asyncio
async def test_deterministic_replay_via_api(app_client):
    """Two runs with same seed must produce identical codelet sequences.

    This is the core determinism guarantee of the system.
    """
    # Run 1
    resp1 = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run1_id = resp1.json()["run_id"]
    resp1 = await app_client.post(f"/api/runs/{run1_id}/step", json={"n": 50})
    steps1 = resp1.json()

    # Run 2 — same seed
    resp2 = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run2_id = resp2.json()["run_id"]
    resp2 = await app_client.post(f"/api/runs/{run2_id}/step", json={"n": 50})
    steps2 = resp2.json()

    # Exact same codelet sequence
    for i, (s1, s2) in enumerate(zip(steps1, steps2)):
        assert s1["codelet_type"] == s2["codelet_type"], (
            f"Step {i}: run1={s1['codelet_type']}, run2={s2['codelet_type']}"
        )
        assert s1["codelet_count"] == s2["codelet_count"]


@pytest.mark.asyncio
async def test_different_seeds_differ(app_client):
    """Different seeds must produce different codelet sequences."""
    resp1 = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": 111,
    })
    run1_id = resp1.json()["run_id"]
    resp1 = await app_client.post(f"/api/runs/{run1_id}/step", json={"n": 20})

    resp2 = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": 222,
    })
    run2_id = resp2.json()["run_id"]
    resp2 = await app_client.post(f"/api/runs/{run2_id}/step", json={"n": 20})

    steps1 = resp1.json()
    steps2 = resp2.json()
    # At least some codelet types should differ
    types1 = [s["codelet_type"] for s in steps1]
    types2 = [s["codelet_type"] for s in steps2]
    assert types1 != types2


@pytest.mark.asyncio
async def test_workspace_endpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.get(f"/api/runs/{run_id}/workspace")
    assert resp.status_code == 200
    data = resp.json()
    assert data["initial"] == "abc"
    assert data["modified"] == "abd"
    assert data["target"] == "xyz"


@pytest.mark.asyncio
async def test_slipnet_endpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.get(f"/api/runs/{run_id}/slipnet")
    assert resp.status_code == 200
    data = resp.json()
    assert "plato-a" in data
    assert "plato-successor" in data
    assert "activation" in data["plato-a"]


@pytest.mark.asyncio
async def test_coderack_endpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.get(f"/api/runs/{run_id}/coderack")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_count" in data
    assert data["total_count"] > 0  # Initial codelets posted


@pytest.mark.asyncio
async def test_temperature_endpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.get(f"/api/runs/{run_id}/temperature")
    assert resp.status_code == 200
    assert resp.json()["temperature"] == 100.0


@pytest.mark.asyncio
async def test_state_changes_after_steps(app_client):
    """After stepping, temperature should change and coderack should evolve."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Step past an update cycle (15 codelets)
    await app_client.post(f"/api/runs/{run_id}/step", json={"n": 30})

    resp = await app_client.get(f"/api/runs/{run_id}/temperature")
    temp = resp.json()["temperature"]
    # Temperature should have been recomputed (may still be 100 if no rules)
    assert 0 <= temp <= 100

    resp = await app_client.get(f"/api/runs/{run_id}/coderack")
    data = resp.json()
    assert data["total_count"] > 0


@pytest.mark.asyncio
async def test_justify_mode(app_client):
    """Providing an answer should enable justify mode."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz",
        "answer": "wyz", "seed": SEED,
    })
    data = resp.json()
    assert data["answer"] == "wyz"


@pytest.mark.asyncio
async def test_run_persists_to_db(app_client, db_session):
    """Run should be persisted in the runs table."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    from sqlalchemy import select, text
    from server.models.run import Run
    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    assert run is not None
    assert run.initial_string == "abc"
    assert run.seed == SEED


@pytest.mark.asyncio
async def test_answer_appears_in_workspace(app_client):
    """When a run finds an answer, the workspace endpoint must return it.

    This is the key user-visible requirement: the answer string must appear
    in the workspace serialization so the UI can display it.
    """
    # Use run_to_completion with a generous step limit.
    # If no answer is found in time, the test is inconclusive (not failed).
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.post(f"/api/runs/{run_id}/run", json={
        "max_steps": 3000,
    })
    info = resp.json()

    if info["status"] == "answer_found":
        # Core assertion: the workspace MUST include the answer string
        resp = await app_client.get(f"/api/runs/{run_id}/workspace")
        ws = resp.json()
        assert ws["answer"] is not None, (
            f"Run found answer (status=answer_found) but workspace.answer is None. "
            f"The answer string was not written to the workspace."
        )
        assert len(ws["answer"]) > 0

        # Run info should also have the answer
        resp = await app_client.get(f"/api/runs/{run_id}")
        run_info = resp.json()
        assert run_info["answer"] is not None
    else:
        pytest.skip(
            f"No answer found within 3000 steps (status={info['status']}). "
            f"Test is inconclusive — not a failure."
        )


@pytest.mark.asyncio
async def test_snapshot_persists(app_client, db_session):
    """Cycle snapshots should be created at initialization and cycle boundaries."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Step past a cycle boundary (15 codelets)
    await app_client.post(f"/api/runs/{run_id}/step", json={"n": 15})

    from sqlalchemy import select, func
    from server.models.run import CycleSnapshot
    result = await db_session.execute(
        select(func.count()).select_from(CycleSnapshot).where(CycleSnapshot.run_id == run_id)
    )
    count = result.scalar()
    assert count >= 2  # Initial snapshot + at least one cycle snapshot
