"""E2E tests for the system endpoints — what is executing, not what was recorded.

``GET /api/system/numeric`` exists because Phase 0's Workstream B put the numeric
substrate on the GPU at every Slipnet size, and nothing in the running system said
so.  A GPU build and a checkout with MLX missing behave identically until something
is slow or a float32 rounding difference surfaces, which is a poor way to find out.

The claims that matter here are about *consistency*: the endpoint must agree with the
selection policy rather than restate a guess about it, so the assertions compare it
against ``server.engine.numeric`` rather than against a hard-coded backend name.  A
test that demanded "mlx" would fail on any machine without Metal and would be
measuring the hardware rather than the endpoint.

Requires: a local Postgres — start it with `scripts/dev.sh db`.  The endpoint itself
needs none, which is the subject of the last test in this file.
"""

import pytest

from server.engine import hardware
from server.engine.numeric import available_backends, select_backend


@pytest.mark.asyncio
async def test_numeric_substrate_reports_the_selected_backend(app_client):
    """Whatever the policy resolved to for this Slipnet, said out loud."""
    resp = await app_client.get("/api/system/numeric")
    assert resp.status_code == 200
    data = resp.json()

    expected = select_backend(data["slipnet_nodes"])
    assert data["backend"] == (expected.name if expected is not None else None)
    assert data["available"] == available_backends()
    assert data["policy"] == "auto"


@pytest.mark.asyncio
async def test_it_reports_the_slipnet_it_selected_against(app_client):
    """59 nodes and 202 links — the size the policy's answer is an answer *for*.

    Pinned rather than merely non-zero: the whole point of the GPU threshold being 0
    is that it applies at this size, and a Slipnet that had silently failed to load
    would make the backend choice meaningless while still looking plausible.
    """
    data = (await app_client.get("/api/system/numeric")).json()
    assert data["slipnet_nodes"] == 59
    assert data["slipnet_links"] == 202


@pytest.mark.asyncio
async def test_device_and_precision_agree_with_the_backend(app_client):
    """The three fields describe one thing and cannot be allowed to disagree.

    ``gpu`` implies MLX's GPU stream, which is float32-only and therefore not exact
    against the float64 reference.  A response claiming a GPU device and exact
    arithmetic would be describing a backend that does not exist.
    """
    data = (await app_client.get("/api/system/numeric")).json()

    if data["device"] == "gpu":
        assert data["backend"] == "mlx"
        assert data["precision"] == "float32"
        assert data["exact"] is False
    else:
        assert data["precision"] == "float64"
        assert data["exact"] is True

    assert data["summary"]
    if data["backend"] is not None:
        assert data["backend"] in data["summary"]


@pytest.mark.asyncio
async def test_the_gpu_threshold_is_zero_so_the_substrate_actually_runs(app_client):
    """Phase 0 §B1 asks for the numeric work on the GPU cores.

    ``auto`` declining below a node count would satisfy that on paper and never on
    this machine, since 59 nodes is the only size the engine currently runs at.  The
    endpoint reports the threshold so that a reader can see which regime they are in;
    this pins the default it reports.
    """
    data = (await app_client.get("/api/system/numeric")).json()
    assert data["gpu_threshold"] == 0
    assert data["vectorise_threshold"] > 0


@pytest.mark.asyncio
async def test_it_reports_the_machine_the_thresholds_are_answers_for(app_client):
    """A figure measured on one machine is only legible beside the machine.

    Worker counts, shard counts and the numeric crossovers are all answers for a
    particular CPU and GPU, so the endpoint states which one this process detected
    rather than leaving a reader to infer it from a hostname.
    """
    data = (await app_client.get("/api/system/numeric")).json()
    machine = data["hardware"]

    assert machine["platform"]
    assert machine["logical_cores"] >= 1
    assert 1 <= machine["performance_cores"] <= machine["logical_cores"]
    assert machine["efficiency_cores"] >= 0
    # Every probe says where it got its answer, including when it got none.
    assert machine["cpu_probe"]
    assert machine["gpu_probe"]
    assert isinstance(machine["metal_available"], bool)


@pytest.mark.asyncio
async def test_the_derived_sizes_agree_with_the_engine_that_uses_them(app_client):
    """Reported and used are the same numbers, not two statements of one intent."""
    data = (await app_client.get("/api/system/numeric")).json()
    derived = data["derived"]

    assert derived["workers"] == hardware.worker_count()
    assert derived["coderack_shards"] == hardware.shard_count(derived["workers"])
    assert derived["population_workers"] == hardware.population_worker_count()
    assert derived["gpu_target_threads"] == hardware.gpu_target_threads()
    assert derived["overrides"] == hardware.overrides_in_force()
    assert data["summary"]


@pytest.mark.asyncio
async def test_a_run_can_ask_for_the_machines_own_worker_count(app_client):
    """``workers: 0`` means "the cores you have", and the Run records the number."""
    data = (await app_client.get("/api/system/numeric")).json()
    expected = data["derived"]["workers"]

    created = await app_client.post(
        "/api/runs",
        json={
            "initial": "abc",
            "modified": "abd",
            "target": "ijk",
            "seed": 11,
            "mode": "fast",
            "workers": 0,
        },
    )
    assert created.status_code == 200
    run_id = created.json()["run_id"]

    parameters = (await app_client.get(f"/api/runs/{run_id}/parameters")).json()
    assert parameters["derived"]["workers"] == expected


@pytest.mark.asyncio
async def test_it_answers_without_a_database_session(app_client):
    """No route in this module takes ``Depends(get_session)``, and that is the point.

    A Fast Run is required to complete with Postgres stopped (§A2), so the dashboard
    has to stay legible in that condition — and "what is actually running?" is the
    first question a reader asks when the panels go quiet.  Checked structurally
    rather than by stopping the database, which no test here can do.
    """
    from server.api import system

    for route in system.router.routes:
        for param in route.dependant.dependencies:
            assert "session" not in (param.name or ""), (
                f"{route.path} acquired a database dependency; "
                "the system endpoints must answer with Postgres stopped"
            )
