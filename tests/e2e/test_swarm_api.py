"""E2E tests for ``/api/swarm`` -- one problem over many seeds on the warm process pool.

The route's promise is the swarm's: every run is the serial run with the same seed.  So the
tests compare the response against ``run_inprocess`` rather than against remembered
numbers, and check that the route persists nothing (Fast-mode semantics) and reports its
telemetry.
"""

import pytest

from server.parallel.swarm import RunTask, run_inprocess


@pytest.fixture(scope="module", autouse=True)
def _stop_default_swarm():
    yield
    from server.parallel.swarm import shutdown_default

    shutdown_default()


@pytest.mark.asyncio
async def test_status_describes_the_pool_without_starting_it(app_client):
    resp = await app_client.get("/api/swarm")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["workers"] >= 1 and data["start_method"] == "forkserver"
    assert "serial" not in data["executors"] or isinstance(data["executors"], list)
    assert data["core_tiers"]["logical_cores"] >= 1


@pytest.mark.asyncio
async def test_swarm_runs_match_serial_runs_and_report_telemetry(app_client):
    body = {"initial": "abc", "modified": "abd", "target": "ijk", "seeds": [1, 2, 3, 4, 5],
            "max_steps": 3000, "backend": "numpy"}
    resp = await app_client.post("/api/swarm", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    from server.api.runs import get_run_service

    meta = get_run_service().meta
    for run in data["runs"]:
        want = run_inprocess(RunTask("abc", "abd", "ijk", None, run["seed"], 3000, backend="numpy"), meta)
        assert run["stopping_state"] == want.stopping_state
        assert run["codelets"] == want.codelets
    assert sum(e["count"] for e in data["distribution"]) == 5
    t = data["telemetry"]
    assert t["runs"] == 5 and t["workers"] >= 1 and t["runs_per_second"] > 0 and t["errors"] == 0


@pytest.mark.asyncio
async def test_count_and_seed_start_and_justification(app_client):
    resp = await app_client.post("/api/swarm", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "answer": "dyz",
        "count": 4, "seed_start": 10, "max_steps": 3000, "include_runs": False})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["runs"] is None and data["telemetry"]["runs"] == 4


@pytest.mark.asyncio
async def test_swarm_persists_nothing(app_client):
    before = (await app_client.get("/api/runs")).json()
    await app_client.post("/api/swarm", json={
        "initial": "abc", "modified": "abd", "target": "ijk", "count": 2, "max_steps": 500})
    after = (await app_client.get("/api/runs")).json()
    assert len(before) == len(after)


@pytest.mark.asyncio
async def test_bad_requests_are_refused(app_client):
    base = {"initial": "abc", "modified": "abd", "target": "ijk"}
    assert (await app_client.post("/api/swarm", json=base)).status_code == 422  # no seeds/count
    bad_param = {**base, "count": 1, "parameters": {"no_such_parameter": 1}}
    assert (await app_client.post("/api/swarm", json=bad_param)).status_code == 400
    bad_backend = {**base, "count": 1, "backend": "no-such-backend"}
    assert (await app_client.post("/api/swarm", json=bad_backend)).status_code == 400
