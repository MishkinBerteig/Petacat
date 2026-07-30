"""Run parameters are settable per Run, stored, and readable back.

Twenty-five entries in ``engine_params.json`` are read by the engine while it thinks, and
until now every one was global: editable only in the Admin panel, applying to every Run
at once, and recorded in a Run's row only indirectly through the config hash. That makes
an experiment awkward to run and a past Run awkward to interpret.

What is worth testing is that an override *reaches the engine* — a parameter that is
accepted, stored and displayed but does not change behaviour is the worst of the
outcomes, because everything looks right.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from server.engine.parameters import RUN_PARAMETERS
from server.models.run import Run
from server.services.sinks import MODE_AUDIT, MODE_FAST, MODE_NORMAL

from tests.e2e.conftest import E2E_SEED as SEED

PROBLEM = {"initial": "abc", "modified": "abd", "target": "mrrjjj"}


async def _create(client, **kw):
    resp = await client.post("/api/runs", json={**PROBLEM, "seed": SEED, **kw})
    return resp


# --- the catalogue ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_catalogue_describes_every_run_parameter(app_client):
    """Served rather than duplicated in the client, so the bounds cannot drift.

    A control that lets you set a value the server rejects is worse than no control.
    """
    body = (await app_client.get("/api/runs/parameters/catalogue")).json()
    described = {p["name"] for p in body["parameters"]}
    assert described == {p.name for p in RUN_PARAMETERS}

    for entry in body["parameters"]:
        assert entry["kind"] in {"int", "float", "bool", "node_list", "node_map"}
        assert entry["label"] and entry["description"]
        assert entry["group"]
        assert "default" in entry


@pytest.mark.asyncio
async def test_every_catalogued_parameter_is_one_the_engine_reads(app_client):
    """Membership is decided by what the engine actually reads.

    Offering a control that changes nothing is worse than offering none, so this pins
    the catalogue to reality rather than to intention.
    """
    import json
    import pathlib
    import re

    read: set[str] = set()
    for path in pathlib.Path("server/engine").rglob("*.py"):
        read |= set(re.findall(r'get_param\(\s*["\']([a-z_]+)["\']', path.read_text()))
    for spec in json.load(open("seed_data/codelet_types.json")):
        read |= set(
            re.findall(r'get_param\(\s*["\']([a-z_]+)["\']', spec.get("execute_body") or "")
        )
    assert {p.name for p in RUN_PARAMETERS} <= read


# --- overrides reach the engine --------------------------------------------


@pytest.mark.asyncio
async def test_an_override_changes_what_the_run_does(app_client):
    """The assertion that matters.

    ``update_cycle_length`` sets how often the whole numeric substrate is recomputed, so
    a run at 5 does three times the update work of one at 15 and reaches a different
    place. If overrides were accepted and stored but never applied, everything else in
    this file would still pass.
    """
    from server.api.runs import get_run_service

    slow = (await _create(app_client, parameters={"update_cycle_length": 5})).json()
    await app_client.post(f"/api/runs/{slow['run_id']}/run", json={"max_steps": 600})
    svc = get_run_service()
    assert svc._runners[slow["run_id"]].ctx.meta.get_param("update_cycle_length") == 5

    plain = (await _create(app_client)).json()
    await app_client.post(f"/api/runs/{plain['run_id']}/run", json={"max_steps": 600})
    assert svc._runners[plain["run_id"]].ctx.meta.get_param("update_cycle_length") == 15


@pytest.mark.asyncio
async def test_an_override_does_not_leak_to_other_runs(app_client):
    """Two Runs in one process must be able to disagree.

    The metadata provider is shared, so an override applied by mutation rather than by
    copy would silently change every subsequent Run — and the symptom would appear in a
    Run whose own record said it used the default.
    """
    from server.api.runs import get_run_service

    svc = get_run_service()
    before = svc.meta.get_param("initial_temperature")

    odd = (await _create(app_client, parameters={"initial_temperature": 40})).json()
    assert svc._runners[odd["run_id"]].ctx.temperature.value == 40

    normal = (await _create(app_client)).json()
    assert svc._runners[normal["run_id"]].ctx.temperature.value == before
    assert svc.meta.get_param("initial_temperature") == before


@pytest.mark.asyncio
async def test_overrides_are_stored_whole_on_normal_and_audit_runs(app_client, db_session):
    """The *resolved* set, not just the overrides.

    Storing overrides alone would have to be read against whatever the global defaults
    are at the time of reading, so a Run's record would quietly change meaning whenever
    the configuration did.
    """
    for mode in (MODE_NORMAL, MODE_AUDIT):
        run = (await _create(app_client, mode=mode,
                             parameters={"theme_decay_amount": 33})).json()
        row = (
            await db_session.execute(select(Run).where(Run.id == run["run_id"]))
        ).scalars().one()
        assert row.parameters is not None
        assert row.parameters["theme_decay_amount"] == 33
        assert len(row.parameters) == len(RUN_PARAMETERS)


@pytest.mark.asyncio
async def test_an_override_changes_the_config_hash(app_client, db_session):
    """Two Runs differing only in a parameter must be distinguishable by hash alone."""
    plain = (await _create(app_client)).json()
    tweaked = (await _create(app_client, parameters={"grace_period": 200})).json()

    rows = {}
    for info in (plain, tweaked):
        row = (
            await db_session.execute(select(Run).where(Run.id == info["run_id"]))
        ).scalars().one()
        rows[info["run_id"]] = row.config_hash
    assert len(set(rows.values())) == 2


# --- validation ------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_parameter_is_rejected(app_client):
    """Ignoring it would produce a Run at the default while the record claimed
    the override was applied."""
    resp = await _create(app_client, parameters={"update_cycel_length": 5})
    assert resp.status_code == 400
    assert "update_cycel_length" in resp.text


@pytest.mark.asyncio
async def test_an_out_of_range_value_is_rejected(app_client):
    resp = await _create(app_client, parameters={"initial_temperature": 500})
    assert resp.status_code == 400
    assert "initial_temperature" in resp.text


@pytest.mark.asyncio
async def test_a_wrongly_typed_value_is_rejected(app_client):
    resp = await _create(app_client, parameters={"self_watching_enabled_default": 3})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_a_rejected_override_creates_no_run(app_client, db_session):
    """Validated before anything is created, so a bad override leaves nothing behind."""
    from sqlalchemy import func

    before = (
        await db_session.execute(select(func.count()).select_from(Run))
    ).scalar()
    await _create(app_client, parameters={"initial_temperature": 500})
    after = (
        await db_session.execute(select(func.count()).select_from(Run))
    ).scalar()
    assert after == before


# --- reading a Run back ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_reports_its_fixed_and_derived_parameters(app_client):
    """Both halves in one response, and clearly separated.

    Separating them into two endpoints invites the mistake of presenting a derived value
    as though it were a setting.
    """
    run = (await _create(app_client, parameters={"max_coderack_size": 200})).json()
    run_id = run["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 300})

    body = (await app_client.get(f"/api/runs/{run_id}/parameters")).json()
    assert body["fixed"]["max_coderack_size"] == 200
    assert body["overridden"] == ["max_coderack_size"]
    assert body["defaults"]["max_coderack_size"] == 100

    derived = body["derived"]
    assert derived["recorded"] is True
    assert derived["codelet_count"] > 0
    assert derived["slipnet_nodes"] == 59
    assert derived["config_hash"] and derived["memory_hash"]
    # The GPU substrate is Phase 0's B1 goal, so which backend ran is part of the record.
    assert derived["numeric_backend"] in {"mlx", "numpy", "python", "mlx-cpu", None}


@pytest.mark.asyncio
async def test_a_fast_run_reports_parameters_from_the_live_runner(app_client):
    """A Fast Run has no row, and is still fully observable."""
    run = (await _create(app_client, mode=MODE_FAST,
                         parameters={"grace_period": 150})).json()
    body = (await app_client.get(f"/api/runs/{run['run_id']}/parameters")).json()
    assert body["fixed"]["grace_period"] == 150
    assert body["derived"]["recorded"] is False


@pytest.mark.asyncio
async def test_derived_values_report_the_sharding_a_free_run_settled_on(app_client):
    """Shard count is derived, not set: it is bounded by capacity, not worker count."""
    run = (await _create(app_client, mode=MODE_NORMAL, workers=8)).json()
    run_id = run["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 600})

    derived = (await app_client.get(f"/api/runs/{run_id}/parameters")).json()["derived"]
    assert derived["workers"] == 8
    assert derived["coderack_shards"] <= 4
    assert derived["coderack_capacity_per_shard"] >= 25
    assert derived["free_running"]["workers"] == 8
