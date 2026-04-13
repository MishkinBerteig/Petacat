"""E2E tests for interactive control endpoints.

ALL tests are deterministic: same seed → same results.
Requires: docker compose -f docker-compose.dev.yml up -d
"""

import pytest

SEED = 54321


@pytest.mark.asyncio
async def test_set_and_clear_breakpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Set breakpoint
    resp = await app_client.post(f"/api/runs/{run_id}/breakpoint", json={"codelet_count": 25})
    assert resp.status_code == 200
    assert resp.json()["breakpoint"] == 25

    # Clear breakpoint
    resp = await app_client.delete(f"/api/runs/{run_id}/breakpoint")
    assert resp.status_code == 200
    assert resp.json()["breakpoint"] is None


@pytest.mark.asyncio
async def test_set_step_size(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.put(f"/api/runs/{run_id}/step-size", json={"step_size": 5})
    assert resp.status_code == 200
    assert resp.json()["step_size"] == 5


@pytest.mark.asyncio
async def test_clamp_and_unclamp_temperature(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Clamp temperature
    resp = await app_client.post(f"/api/runs/{run_id}/clamp-temperature", json={
        "value": 50.0, "cycles": 10,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["clamped"] is True
    assert data["temperature"] == 50.0

    # Unclamp
    resp = await app_client.delete(f"/api/runs/{run_id}/clamp-temperature")
    assert resp.status_code == 200
    assert resp.json()["clamped"] is False


@pytest.mark.asyncio
async def test_clamp_and_unclamp_node(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Clamp a slipnet node
    resp = await app_client.post(f"/api/runs/{run_id}/clamp-node", json={
        "node_name": "plato-successor", "cycles": 20,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["clamped"] is True
    assert data["activation"] == 100.0  # Clamped nodes go to max

    # Unclamp
    resp = await app_client.request("DELETE", f"/api/runs/{run_id}/clamp-node",
                                     content='{"node_name": "plato-successor"}',
                                     headers={"content-type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["clamped"] is False


@pytest.mark.asyncio
async def test_clamp_invalid_node(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.post(f"/api/runs/{run_id}/clamp-node", json={
        "node_name": "nonexistent-node", "cycles": 10,
    })
    assert resp.status_code in (400, 404, 422, 500)


@pytest.mark.asyncio
async def test_clamp_and_unclamp_codelets(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Clamp codelet urgency
    resp = await app_client.post(f"/api/runs/{run_id}/clamp-codelets", json={
        "codelet_type": "bottom-up-bond-scout", "urgency": 91,
    })
    assert resp.status_code == 200
    assert resp.json()["clamped"] is True

    # Unclamp
    resp = await app_client.request("DELETE", f"/api/runs/{run_id}/clamp-codelets",
                                     content='{"codelet_type": "bottom-up-bond-scout"}',
                                     headers={"content-type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["clamped"] is False


@pytest.mark.asyncio
async def test_clamp_themes(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.post(f"/api/runs/{run_id}/clamp-themes", json={
        "themes": [{
            "type": "top_bridge",
            "dimension": "plato-direction-category",
            "relation": "identity",
            "activation": 100.0,
        }],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["clamped_themes"]) >= 1

    # Unclamp
    resp = await app_client.delete(f"/api/runs/{run_id}/clamp-themes")
    assert resp.status_code == 200
    assert resp.json()["unclamped"] is True


@pytest.mark.asyncio
async def test_set_and_get_spreading_threshold(app_client):
    """Test the spreading activation threshold control endpoint."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Default should be 100
    resp = await app_client.get(f"/api/runs/{run_id}/spreading-threshold")
    assert resp.status_code == 200
    assert resp.json()["spreading_activation_threshold"] == 100

    # Set to 50
    resp = await app_client.post(f"/api/runs/{run_id}/spreading-threshold",
                                  json={"threshold": 50})
    assert resp.status_code == 200
    assert resp.json()["spreading_activation_threshold"] == 50

    # Verify persistence
    resp = await app_client.get(f"/api/runs/{run_id}/spreading-threshold")
    assert resp.status_code == 200
    assert resp.json()["spreading_activation_threshold"] == 50

    # Set to 0 (most permissive)
    resp = await app_client.post(f"/api/runs/{run_id}/spreading-threshold",
                                  json={"threshold": 0})
    assert resp.status_code == 200
    assert resp.json()["spreading_activation_threshold"] == 0

    # Clamped to valid range
    resp = await app_client.post(f"/api/runs/{run_id}/spreading-threshold",
                                  json={"threshold": 200})
    assert resp.status_code == 200
    assert resp.json()["spreading_activation_threshold"] == 100


@pytest.mark.asyncio
async def test_spreading_threshold_affects_slipnet(app_client):
    """Verify that different thresholds produce different slipnet states."""
    # Run 1: threshold=100 (strict)
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id_strict = resp.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id_strict}/spreading-threshold",
                           json={"threshold": 100})
    await app_client.post(f"/api/runs/{run_id_strict}/step", json={"n": 30})
    resp_strict = await app_client.get(f"/api/runs/{run_id_strict}/slipnet")
    strict_state = resp_strict.json()

    # Run 2: threshold=0 (permissive)
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id_perm = resp.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id_perm}/spreading-threshold",
                           json={"threshold": 0})
    await app_client.post(f"/api/runs/{run_id_perm}/step", json={"n": 30})
    resp_perm = await app_client.get(f"/api/runs/{run_id_perm}/slipnet")
    perm_state = resp_perm.json()

    # The two should produce different slipnet activation patterns
    # (we can't predict exactly how, but they should diverge)
    assert strict_state != perm_state
