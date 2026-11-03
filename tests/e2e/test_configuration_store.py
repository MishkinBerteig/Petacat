"""E2E (C3): the ``ConfigurationStore`` carries every committed global change to the next run.

The store replaces the mark-stale middleware, ``POST /api/admin/reload`` and the direct
``svc.meta`` assignments.  The journal layer calls its ``refresh`` after a global change
commits, so these tests make the edit through the Admin API (or the journal layer) and look
at what the next run, the Training Mode scheduler's provider and the post-commit hook see.

The Training Mode scheduler is handed ``store.current`` (``lifespan``), so asking that
callable is asking what the scheduler would dispatch under: the B4 regression is that it
saw an Admin edit only after a Metacat Mode run had been created.
"""

import pytest
from sqlalchemy import select

from server.engine.hashing import config_hash
from server.models.run import Run

PROBLEM = {"initial": "abc", "modified": "abd", "target": "xyz", "seed": 2006188493}


async def _set_param(client, name: str, value: str) -> None:
    resp = await client.put(f"/api/admin/params/{name}", json={"value": value})
    assert resp.status_code == 200, resp.text


async def _stored_hash(db_session, run_id: int) -> str:
    return (await db_session.execute(select(Run.config_hash).where(Run.id == run_id))).scalar_one()


@pytest.mark.asyncio
async def test_the_training_mode_scheduler_sees_an_admin_edit_with_no_run_between(
    app_client, db_session
):
    """The B4 regression: no Metacat Mode run is created between the edit and the read."""
    from server.services.configuration_store import get_configuration_store

    store = get_configuration_store()
    await store.refresh(db_session)  # the fixture's store starts from the seed files
    scheduler_provider = store.current  # what ``lifespan`` hands the Training Mode scheduler
    before_hash, before_revision = config_hash(scheduler_provider()), store.revision
    await _set_param(app_client, "expiration_period", "80")
    try:
        assert scheduler_provider().get_param("expiration_period") == 80
        assert config_hash(scheduler_provider()) != before_hash
        assert store.revision == before_revision + 1
    finally:
        await _set_param(app_client, "expiration_period", "500")
    assert config_hash(scheduler_provider()) == before_hash
    assert store.revision == before_revision + 2


@pytest.mark.asyncio
async def test_a_run_created_before_an_edit_keeps_its_hash_and_the_next_run_uses_the_new_one(
    app_client, db_session
):
    from server.services.configuration_store import get_configuration_store

    await get_configuration_store().refresh(db_session)  # start from the database's configuration
    first = (await app_client.post("/api/runs", json=PROBLEM)).json()["run_id"]
    old_hash = await _stored_hash(db_session, first)
    await _set_param(app_client, "expiration_period", "80")
    try:
        second = (await app_client.post("/api/runs", json=PROBLEM)).json()["run_id"]
        new_hash = await _stored_hash(db_session, second)
        assert new_hash != old_hash
        assert new_hash == config_hash(get_configuration_store().current())
        assert await _stored_hash(db_session, first) == old_hash
    finally:
        await _set_param(app_client, "expiration_period", "500")


@pytest.mark.asyncio
async def test_an_edit_reaches_the_next_swarm_run_and_the_next_fast_run(app_client):
    body = {"initial": "abc", "modified": "abd", "target": "ijk", "seeds": [1],
            "max_steps": 200, "backend": "numpy"}
    first = (await app_client.post("/api/swarm", json=body)).json()["telemetry"]["config_hash"]
    await _set_param(app_client, "expiration_period", "80")
    try:
        edited = (await app_client.post("/api/swarm", json=body)).json()["telemetry"]["config_hash"]
        fast = await app_client.post("/api/runs", json={**PROBLEM, "mode": "fast"})
        assert fast.status_code == 200, fast.text
        from server.api.runs import get_run_service

        runner = get_run_service()._runners[fast.json()["run_id"]]
        assert runner.ctx.meta.get_param("expiration_period") == 80
    finally:
        await _set_param(app_client, "expiration_period", "500")
    assert edited != first


@pytest.mark.asyncio
async def test_the_hook_runs_only_after_a_committed_change_to_the_global_configuration(db_session):
    from server.services import journal

    calls = []

    async def hook(session):
        calls.append(session)

    journal.set_global_commit_hook(hook)
    try:
        op = {"op": "update", "table": "engine_params", "key": {"name": "expiration_period"}}
        # A change that commits: the hook runs once.
        await journal.write_immediate(
            db_session, ops=[{**op, "set": {"value": "81"}}], source="admin", actor="t"
        )
        assert len(calls) == 1
        # A write that changes nothing, a write that fails, and one left to the caller
        # (commit=False) do not run it.
        await journal.write_immediate(
            db_session, ops=[{**op, "set": {"value": "81"}}], source="admin", actor="t"
        )
        with pytest.raises(journal.MissingKey):
            await journal.write_immediate(
                db_session,
                ops=[{**op, "key": {"name": "no_such_param"}, "set": {"value": "1"}}],
                source="admin", actor="t",
            )
        await journal.write_immediate(
            db_session, ops=[{**op, "set": {"value": "82"}}], source="admin", actor="t",
            commit=False,
        )
        assert len(calls) == 1
        await db_session.rollback()
    finally:
        journal.set_global_commit_hook(None)
        await journal.write_immediate(
            db_session, ops=[{**op, "set": {"value": "500"}}], source="admin", actor="t"
        )


@pytest.mark.asyncio
async def test_a_failed_refresh_keeps_the_previous_provider_and_says_so(app_client, monkeypatch):
    from server.services import journal
    from server.services.configuration_store import get_configuration_store

    store = get_configuration_store()
    before = store.current()

    async def cannot_load(session):
        raise RuntimeError("the configuration cannot be built")

    # the change API refuses a value that is not an int, so the refusal this test needs is
    # made by a hook that cannot load the configuration the (valid) change leaves
    with monkeypatch.context() as patched:
        patched.setattr(journal, "_global_commit_hook", cannot_load)
        resp = await app_client.put(
            "/api/admin/params/expiration_period", json={"value": "501", "value_type": "int"}
        )
    assert resp.status_code == 500
    assert "previous configuration" in resp.json()["detail"]
    assert store.current() is before
    await _set_param(app_client, "expiration_period", "500")
    assert store.current() is not before
