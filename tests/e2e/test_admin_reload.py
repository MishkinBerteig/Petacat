"""E2E tests: an Admin edit takes effect at the start of the next run, with no reload or restart.

The Admin view can change anything in the database, and the requirement is that a change
works for every run started after it (Metacat Mode: a single run, an episodic run, the
one-problem Swarm). These tests make the edit through the Admin API only and then start a
run, with no reload route to call (there is none), so they fail if the server keeps serving
the configuration it loaded at start-up.

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
async def test_swarm_runs_under_the_edited_configuration(app_client, db_session):
    from server.services.configuration_store import get_configuration_store

    # The fixture's store starts from the seed files; the baseline is the database's.
    await get_configuration_store().refresh(db_session)
    body = {"initial": "abc", "modified": "abd", "target": "ijk", "seeds": [1],
            "max_steps": 200, "backend": "numpy"}
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
async def test_a_value_the_change_api_refuses_keeps_the_previous_provider(app_client):
    from server.api.runs import get_run_service

    before = get_run_service().meta
    resp = await app_client.put(
        "/api/admin/params/expiration_period", json={"value": "not a number", "value_type": "int"}
    )
    # the change API refuses a value that is not an int before anything is written, so the
    # provider is never rebuilt
    assert resp.status_code == 422
    assert get_run_service().meta is before
    assert (await app_client.post("/api/runs", json=PROBLEM)).status_code == 200

    for value in ("501", "500"):  # a real change rebuilds the provider; put the value back
        resp = await app_client.put(
            "/api/admin/params/expiration_period", json={"value": value, "value_type": "int"}
        )
        assert resp.status_code == 200, resp.text
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


async def _coefficient(client, name: str) -> dict:
    rows = (await client.get("/api/admin/formula-coefficients")).json()
    return next(r for r in rows if r["name"] == name)


@pytest.mark.asyncio
async def test_a_rational_coefficient_edit_reaches_the_next_run_exactly(app_client):
    name = "enclosed_group_importance_factor"
    assert await _coefficient(app_client, name) == {
        "name": name, "value": "2/3", "value_type": "rational",
    }
    first = await _run_to_end(app_client)
    assert first["codelet_count"] == SHIPPED_CODELETS
    resp = await app_client.put(f"/api/admin/formula-coefficients/{name}", json={"value": "1/2"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"name": name, "value": "1/2", "value_type": "rational"}
    try:
        edited = await _run_to_end(app_client)
        assert edited["codelet_count"] != SHIPPED_CODELETS
    finally:
        # Written another way, stored and shown in lowest terms.
        resp = await app_client.put(f"/api/admin/formula-coefficients/{name}", json={"value": "4/6"})
        assert resp.status_code == 200, resp.text
    assert (await _coefficient(app_client, name))["value"] == "2/3"
    assert (await _run_to_end(app_client))["codelet_count"] == SHIPPED_CODELETS


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["1/0", "0.5", "2", "1/-3", "x/y", ""])
async def test_a_coefficient_that_is_not_a_rational_is_refused_with_a_message(app_client, bad):
    name = "edge_object_bond_factor"
    resp = await app_client.put(f"/api/admin/formula-coefficients/{name}", json={"value": bad})
    assert resp.status_code == 422
    assert "n/m" in resp.json()["detail"]
    assert (await _coefficient(app_client, name))["value"] == "1/3"


@pytest.mark.asyncio
async def test_a_plain_coefficient_keeps_its_kind_and_a_rational_param_is_checked(app_client):
    name = "bond_degree_of_assoc_scale"
    before = await _coefficient(app_client, name)
    assert before["value_type"] == "float"
    resp = await app_client.put(f"/api/admin/formula-coefficients/{name}", json={"value": "abc"})
    assert resp.status_code == 422
    assert await _coefficient(app_client, name) == before

    resp = await app_client.post(
        "/api/admin/params", json={"name": "zz_rational", "value": "1/0", "value_type": "rational"}
    )
    assert resp.status_code == 422
    resp = await app_client.post(
        "/api/admin/params", json={"name": "zz_rational", "value": "4/6", "value_type": "rational"}
    )
    try:
        assert resp.status_code == 201 and resp.json()["value"] == "2/3"
    finally:
        await app_client.delete("/api/admin/params/zz_rational")
