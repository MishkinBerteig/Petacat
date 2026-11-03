"""C10: Metacat Mode is untouched by Training Mode, and the journal is written in one place.

Over HTTP and on a scratch database:

* M1: any amount of session activity (creation from each base, edits from every learning source,
  runs with a learner, pause, Stop, Start, restore, delete, and edit-all aimed at sessions) leaves
  the global configuration's provider, hash, revision and journal as they were, and a Metacat Mode
  run gives the identical result before and after the battery;
* M2: the global configuration refuses the ``learner`` and ``external`` sources, for a batch and
  for a dry run, and a refused batch changes nothing;
* M3: edit-all end to end: every entry of the group is ``actor = admin``, carries the group id
  and sits in exactly one configuration, and a session-only edit never reaches the global
  configuration;
* the audit hook: no journal row is written by a Metacat Mode run, or by a live session and
  its runs; the rows appear at the Stop write.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, func, select, text

from server.models.journal import JournalEntry
from server.services import configuration_store as store
from server.services import journal
from server.services import training_mode_session_service as tms
from tests.e2e.test_configuration_edits_api import (  # noqa: F401  (fixtures and helpers)
    base_value, change, commit, entries, make, preview, revision, start, undo_group,
)
from tests.e2e.test_session_configuration import (  # noqa: F401  (fixtures and helpers)
    PARAM, _learner, _stop_default_swarm, adjust_param, create_with, external, factory_of,
    journal_count, manual, serial_sessions, sessions, set_param,
)
from tests.e2e.test_training_mode_sessions_api import create, session_state, stop, until_state

JOURNAL_TABLES = ("configurations", "configuration_snapshots", "configuration_journal")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def empty_memory(test_engine) -> None:
    """Metacat's Episodic Memory empty, as the e2e suite's autouse fixture does at a test's start."""
    from server.models.run import AnswerDescriptionRow, SnagDescriptionRow
    from sqlalchemy import delete

    from server.services.run_service import _global_memory

    _global_memory.clear()
    async with factory_of(test_engine)() as s:
        for table in (AnswerDescriptionRow, SnagDescriptionRow):
            await s.execute(delete(table))
        await s.commit()


async def metacat_run(client, test_engine, seed: int = 4242) -> dict:
    """One Metacat Mode run from an empty Episodic Memory; everything it produced."""
    await empty_memory(test_engine)
    made = await client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": seed})
    assert made.status_code == 200, made.text
    run_id = made.json()["run_id"]
    done = await client.post(f"/api/runs/{run_id}/run", json={"max_steps": 400})
    assert done.status_code == 200, done.text
    info = {k: v for k, v in done.json().items() if k != "run_id"}
    workspace = (await client.get(f"/api/runs/{run_id}/workspace")).json()
    trace = (await client.get(f"/api/runs/{run_id}/trace", params={"limit": 100000})).json()["events"]
    slipnet = (await client.get(f"/api/runs/{run_id}/slipnet")).json()
    await client.delete(f"/api/runs/{run_id}")
    return {"info": info, "workspace": workspace, "trace": trace, "slipnet": slipnet}


async def global_state(client, test_engine) -> dict:
    """Everything that says what Metacat Mode's configuration is."""
    from server.api.runs import get_run_service

    the_store = store.get_configuration_store()
    row = (await client.get("/api/configurations/1")).json()
    async with factory_of(test_engine)() as db:
        stored_hash = await journal.compute_config_hash(db)
    return {
        "provider": id(the_store.current()), "store_revision": the_store.revision,
        "param": get_run_service().meta.get_param(PARAM),
        "revision": row["revision"], "config_hash": row["config_hash"], "stored_hash": stored_hash,
        "entries": await journal_count(test_engine, 1),
    }


def journal_writes(test_engine):
    """Record every statement that writes a journal table; returns ``(statements, remove)``."""
    seen: list[str] = []
    sync_engine = test_engine.sync_engine

    def listener(conn, cursor, statement, parameters, context, executemany):
        head = statement.lstrip().split(None, 4)
        text_ = " ".join(head).upper()
        for table in JOURNAL_TABLES:
            if text_.startswith((f"INSERT INTO {table.upper()}", f"UPDATE {table.upper()}",
                                 f"DELETE FROM {table.upper()}")):
                seen.append(statement.strip()[:80])

    event.listen(sync_engine, "before_cursor_execute", listener)
    return seen, lambda: event.remove(sync_engine, "before_cursor_execute", listener)


# ---------------------------------------------------------------------------
# M1: a battery of Training Mode activity, and Metacat Mode is as it was
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m1_a_metacat_mode_run_is_identical_after_a_battery_of_session_activity(
        app_client, serial_sessions, test_engine):
    service = serial_sessions
    before = await metacat_run(app_client, test_engine)
    assert before["trace"] and before["info"]["codelet_count"] > 0, "the run did nothing to compare"
    assert before == await metacat_run(app_client, test_engine), "a Metacat Mode run is not repeatable"
    state_before = await global_state(app_client, test_engine)

    # creation from each base, and a session that learns after every run
    made = await create(app_client, 2, seeds_per_problem=2, start=False)
    tid = made["session"]["id"]
    cid = made["session"]["configuration"]["id"]
    standard = await create_with(app_client, configuration_base="standard")
    other = await create_with(app_client, parameters={PARAM: 19})
    service.set_after_run(tid, _learner)
    await app_client.post(f"/api/training-mode/sessions/{tid}/start")
    await until_state(app_client, tid, "finished", timeout=240)
    # every learning source, aimed at the session; edits of live and Stopped configurations
    for source in ("external", "learner", "admin"):
        resp = await app_client.post(f"/api/configurations/{cid}/changes", json={
            "source": source, "actor": "c10", "base_version": "head", "ops": [set_param(23)]})
        assert resp.status_code == 200, (source, resp.text)
    # edit-all aimed at the sessions only, then undone
    pre = await preview(app_client, [set_param(25)], ids=[cid, other["configuration"]["id"]])
    done = await commit(app_client, pre["preview_token"])
    await app_client.post(f"/api/training-mode/sessions/{tid}/pause")
    await stop(app_client, tid)
    for target in (cid, other["configuration"]["id"]):
        await undo_group(app_client, target, done["group_id"])
    await change(app_client, standard["configuration"]["id"], set_param(31))
    await app_client.post(f"/api/training-mode/sessions/{tid}/start", json={"paused": True})
    await stop(app_client, tid)
    assert (await app_client.get(f"/api/configurations/{cid}/verify-journal")).json()["ok"]
    for s in (tid, standard["id"], other["id"]):
        assert (await app_client.delete(f"/api/training-mode/sessions/{s}")).status_code in (200, 204)

    assert await global_state(app_client, test_engine) == state_before
    assert await metacat_run(app_client, test_engine) == before


@pytest.mark.asyncio
async def test_m1_session_edits_never_change_the_global_provider_or_hash(manual, app_client, test_engine):
    state = await global_state(app_client, test_engine)
    stopped_t, stopped_c = await make(app_client, "c10 stopped")
    live_t, live_c = await make(app_client, "c10 live")
    await start(app_client, live_t, paused=False)
    for i, source in enumerate(("external", "learner", "admin", "external", "learner")):
        for cid in (stopped_c, live_c):
            resp = await app_client.post(f"/api/configurations/{cid}/changes", json={
                "source": source, "actor": "c10", "base_version": "head",
                "ops": [set_param(40 + i)]})
            assert resp.status_code == 200, resp.text
        assert await global_state(app_client, test_engine) == state, (i, source)
    assert manual._live[live_t].config.provider.get_param(PARAM) == 44
    assert base_value() == state["param"]


# ---------------------------------------------------------------------------
# M2: the global configuration refuses the Training-Mode sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["learner", "external"])
async def test_m2_the_global_configuration_refuses_learner_and_external(manual, app_client, test_engine, source):
    state = await global_state(app_client, test_engine)
    batch = {"source": source, "actor": "c10", "base_version": "head", "ops": [set_param(9)]}
    for dry_run in (False, True):
        resp = await app_client.post("/api/configurations/1/changes", json={**batch, "dry_run": dry_run})
        assert resp.status_code == 403 and resp.json()["error"] == "source_refused", (source, dry_run)
    assert await global_state(app_client, test_engine) == state
    # the same batch is accepted by a session's configuration
    _, cid = await make(app_client, f"c10 {source}")
    resp = await app_client.post(f"/api/configurations/{cid}/changes", json=batch)
    assert resp.status_code == 200, resp.text
    assert await global_state(app_client, test_engine) == state


# ---------------------------------------------------------------------------
# M3: edit-all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m3_edit_all_end_to_end_one_admin_entry_per_configuration(manual, app_client, test_engine):
    v0 = base_value()
    stopped_t, stopped_c = await make(app_client, "c10 stopped")
    run_t, run_c = await make(app_client, "c10 running")
    pause_t, pause_c = await make(app_client, "c10 paused")
    await start(app_client, run_t, paused=False)
    await start(app_client, pause_t, paused=True)
    revisions = {c: await revision(app_client, c) for c in (1, stopped_c)}

    pre = await preview(app_client, [{"op": "set_param", "name": PARAM, "to": v0 + 3, "expect": v0}],
                        all_=True)
    assert {1, stopped_c, run_c, pause_c} <= set(pre["by_id"])
    assert store.live_state(run_t).unsaved == 0  # a preview writes nothing
    done = await commit(app_client, pre["preview_token"], reason="c10 edit all")
    gid = done["group_id"]
    assert done["committed"] is True and gid

    # stored targets: the global configuration and the Stopped session, at once
    for cid in (1, stopped_c):
        group = await entries(test_engine, cid, gid)
        assert len(group) == 1, cid
        assert (group[0]["actor"], group[0]["group_id"], group[0]["configuration_id"]) == ("admin", gid, cid)
        assert await revision(app_client, cid) == revisions[cid] + 1
    # live targets: held in memory with the same provenance, written by the Stop
    for tid, cid in ((run_t, run_c), (pause_t, pause_c)):
        held = store.live_state(tid).pending
        assert len(held) == 1 and (held[0].actor, held[0].group_id) == ("admin", gid)
        assert await entries(test_engine, cid, gid) == []
        await stop(app_client, tid)
        stored = await entries(test_engine, cid, gid)
        assert len(stored) == 1 and (stored[0]["actor"], stored[0]["configuration_id"]) == ("admin", cid)
    # across the whole journal: the group is one entry in each of four configurations
    async with factory_of(test_engine)() as db:
        rows = (await db.execute(
            select(JournalEntry.__table__.c.configuration_id, JournalEntry.__table__.c.actor)
            .where(JournalEntry.__table__.c.group_id == gid))).all()
    assert sorted(r[0] for r in rows) == sorted({1, stopped_c, run_c, pause_c})
    assert {r[1] for r in rows} == {"admin"}

    for cid in (1, stopped_c, run_c, pause_c):
        await undo_group(app_client, cid, gid)
    assert (await app_client.get("/api/configurations/1/verify-journal")).json()["ok"]
    assert base_value() == v0


@pytest.mark.asyncio
async def test_m3_a_session_only_edit_all_leaves_the_global_configuration_alone(manual, app_client, test_engine):
    state = await global_state(app_client, test_engine)
    _, a = await make(app_client, "c10 a")
    _, b = await make(app_client, "c10 b")
    pre = await preview(app_client, [set_param(state["param"] + 5)], ids=[a, b])
    assert sorted(pre["by_id"]) == sorted([a, b])
    await commit(app_client, pre["preview_token"])
    assert await global_state(app_client, test_engine) == state


# ---------------------------------------------------------------------------
# The audit hook: no journal write in a run or a live session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_journal_row_is_written_by_a_metacat_mode_run(app_client, test_engine, monkeypatch):
    async def refuse(*a, **k):
        raise AssertionError("a run reached a door of the journal layer")

    monkeypatch.setattr(journal, "write_immediate", refuse)
    monkeypatch.setattr(journal, "write_deferred", refuse)
    seen, remove = journal_writes(test_engine)
    try:
        await metacat_run(app_client, test_engine)
    finally:
        remove()
    assert seen == []


@pytest.mark.asyncio
async def test_a_live_session_and_its_runs_write_no_journal_row_until_the_stop_write(
        app_client, serial_sessions, test_engine, monkeypatch):
    service = serial_sessions
    made = await create(app_client, 2, seeds_per_problem=2, start=False)
    tid = made["session"]["id"]
    service.set_after_run(tid, _learner)  # every run changes the configuration, in memory
    real_immediate, real_deferred = journal.write_immediate, journal.write_deferred

    async def refuse(*a, **k):
        raise AssertionError("a live session reached a door of the journal layer")

    seen, remove = journal_writes(test_engine)
    try:
        monkeypatch.setattr(journal, "write_immediate", refuse)
        monkeypatch.setattr(journal, "write_deferred", refuse)
        await app_client.post(f"/api/training-mode/sessions/{tid}/start")
        await until_state(app_client, tid, "finished", timeout=240)
        assert (await session_state(app_client, tid))["runs"]["done"] == 4
        held = service._live[tid].config.pending_entries()
        assert len(held) == 4  # the learner's four batches are held in memory
        assert seen == [], seen
        monkeypatch.setattr(journal, "write_immediate", real_immediate)
        monkeypatch.setattr(journal, "write_deferred", real_deferred)
        await stop(app_client, tid)
    finally:
        remove()
    # the Stop write is where the rows appear (the hook sees the doors' own statements)
    assert any(s.upper().startswith("INSERT INTO CONFIGURATION_JOURNAL") for s in seen), seen
    assert await journal_count(test_engine, made["session"]["configuration"]["id"]) >= 4
