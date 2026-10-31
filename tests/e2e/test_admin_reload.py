"""E2E tests: an Admin edit takes effect at the start of the next run, with no reload or restart.

The Admin view can change anything in the database, and the requirement is that a change
works for every run started after it (Metacat Mode: a single run, an episodic run, the
one-problem Swarm). These tests make the edit through the Admin API only and then start a
run, never calling ``/api/admin/reload``, so they fail if the server keeps serving the
configuration it loaded at start-up.

``abc -> abd; xyz -> ?`` at seed 2006188493 (fig. 5.11) finishes in 923 codelets on the
shipped ``expiration_period`` of 500 and in 1475 with 80, so the count says which value the
run executed under.
"""

import pytest

PROBLEM = {"initial": "abc", "modified": "abd", "target": "xyz", "seed": 2006188493}
SHIPPED_CODELETS = 923
EXPIRY_80_CODELETS = 1475


async def _run_to_end(client, **extra) -> dict:
    # Episodic runs inherit the Episodic Memory the runs before them left, and a found
    # answer changes the next run's course, so each measured run starts from a cleared one.
    assert (await client.delete("/api/memory")).status_code == 200
    resp = await client.post("/api/runs", json={**PROBLEM, **extra})
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]
    resp = await client.post(f"/api/runs/{run_id}/run", json={"max_steps": 20000})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _set_param(client, name: str, value: str) -> None:
    resp = await client.put(f"/api/admin/params/{name}", json={"value": value})
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_engine_param_edit_reaches_the_next_run(app_client):
    before = await _run_to_end(app_client)
    assert before["codelet_count"] == SHIPPED_CODELETS
    await _set_param(app_client, "expiration_period", "80")
    try:
        after = await _run_to_end(app_client)
        assert after["codelet_count"] == EXPIRY_80_CODELETS
    finally:
        await _set_param(app_client, "expiration_period", "500")
    restored = await _run_to_end(app_client)
    assert restored["codelet_count"] == SHIPPED_CODELETS



@pytest.mark.asyncio
async def test_slipnet_edit_reaches_the_next_run(app_client):
    """Deleting a node in the Admin view builds a Slipnet without it, with no reload."""
    nodes = {n["name"] for n in (await app_client.get("/api/admin/slipnet/nodes")).json()}
    assert "plato-q" in nodes
    snapshot = (await app_client.get("/api/admin/export")).json()
    resp = await app_client.post("/api/runs", json=PROBLEM)
    live_id = resp.json()["run_id"]  # created before the edit: keeps its Slipnet
    try:
        resp = await app_client.delete("/api/admin/slipnet/nodes/plato-q")
        assert resp.status_code == 200, resp.text

        from server.api.runs import get_run_service

        svc = get_run_service()
        assert "plato-q" not in svc.meta.slipnet_node_specs
        runner = svc._runners[live_id]
        assert "plato-q" in runner.ctx.meta.slipnet_node_specs  # a live run is not swapped under

        after = await _run_to_end(app_client)
        assert after["codelet_count"] > 0
        resp = await app_client.post(f"/api/runs/{live_id}/step", json={"n": 5})
        assert resp.status_code == 200, resp.text
    finally:
        # The database is shared by the module, so put the node and its links back.
        resp = await app_client.post("/api/admin/import", json=snapshot)
        assert resp.status_code == 200, resp.text
    assert "plato-q" in get_run_service().meta.slipnet_node_specs


@pytest.mark.asyncio
async def test_swarm_runs_under_the_edited_configuration(app_client):
    body = {"initial": "abc", "modified": "abd", "target": "ijk", "seeds": [1],
            "max_steps": 200, "backend": "numpy"}
    await app_client.post("/api/admin/reload")  # the baseline is the database's configuration
    first = (await app_client.post("/api/swarm", json=body)).json()
    await _set_param(app_client, "expiration_period", "80")
    try:
        edited = (await app_client.post("/api/swarm", json=body)).json()
    finally:
        await _set_param(app_client, "expiration_period", "500")
    restored = (await app_client.post("/api/swarm", json=body)).json()
    assert edited["telemetry"]["config_hash"] != first["telemetry"]["config_hash"]
    assert restored["telemetry"]["config_hash"] == first["telemetry"]["config_hash"]


@pytest.mark.asyncio
async def test_unbuildable_configuration_keeps_the_previous_provider(app_client):
    from server.api.runs import get_run_service

    before = get_run_service().meta
    resp = await app_client.put(
        "/api/admin/params/expiration_period", json={"value": "not a number", "value_type": "int"}
    )
    assert resp.status_code == 500
    assert "previous configuration" in resp.json()["detail"]
    assert get_run_service().meta is before
    assert (await app_client.post("/api/runs", json=PROBLEM)).status_code == 200

    await app_client.put(
        "/api/admin/params/expiration_period", json={"value": "500", "value_type": "int"}
    )
    assert get_run_service().meta is not before


@pytest.mark.asyncio
async def test_a_run_under_way_keeps_the_configuration_it_started_with(app_client):
    resp = await app_client.post("/api/runs", json=PROBLEM)
    run_id = resp.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/step", json={"n": 20})
    await app_client.delete("/api/memory")
    await _set_param(app_client, "expiration_period", "80")
    try:
        resp = await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 20000})
        assert resp.json()["codelet_count"] == SHIPPED_CODELETS
    finally:
        await _set_param(app_client, "expiration_period", "500")
