"""The Stop write and the Start read (S5).

A Training Mode Session writes the database only when it is Stopped.  The Stop write puts, in
one transaction, the session's problems, outcomes, runs, Episodic Memory merges and memory
snapshot, and its configuration's held journal entries and stored current state.  The Start
read loads the session row, the stored configuration state (checked against its stored
``config_hash``), the memory snapshot and the unfinished problems, and **reads no journal row
and no merge**.  Checked here against the service and a scratch database:

* Stop then Start round-trips the live state (configuration hash and revision, Episodic Memory
  digest, run fingerprints, counters) with zero statements touching the journal or the merge log;
* a failed Stop writes nothing (A9: no journal row, no entries, no revision bump, no snapshot),
  returns to Paused with everything intact, and a retry writes all of it (A7: the journal
  replays to the stored state);
* a tampered stored state refuses the Start and names the check;
* a Stopped edit is not mistaken for tampering;
* a graceful shutdown stores every live session's configuration;
* after a Start with a pool of workers, runs complete from the snapshot-based memory and the
  memory still equals a replay of the stored merges.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.models.journal import ConfigurationSnapshot, JournalEntry
from server.models.training_mode_session import (
    SessionMemoryMerge, SessionMemorySnapshot, TrainingModeSession,
)
from server.services import config_document as cd
from server.services import configurations, journal
from server.services import training_mode_session_memory as tm
from server.services import training_mode_session_service as bs
from server.services.configuration_admin import verify_journal
from tests.e2e.test_session_configuration import (  # noqa: F401 - the fixtures
    PARAM, _learner, adjust_param, external, factory_of, journal_count, serial_sessions,
    sessions, set_param, stored_document,
)
from tests.e2e.test_training_mode_sessions_api import (
    _api, create, db_count, make_service, run_key, runs_of, session_state, stop,
    until_state, wait_for,
)

JOURNAL = JournalEntry.__tablename__
MERGES = SessionMemoryMerge.__tablename__


@pytest.fixture(scope="module", autouse=True)
def _stop_default_swarm():
    yield
    from server.parallel.swarm import shutdown_default

    shutdown_default()


class Statements:
    """Every statement the engine runs while it is on (``before_cursor_execute``)."""

    def __init__(self, engine) -> None:
        self.engine, self.seen = engine.sync_engine, []

    def _hook(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.seen.append(statement)

    def __enter__(self) -> "Statements":
        event.listen(self.engine, "before_cursor_execute", self._hook)
        return self

    def __exit__(self, *exc) -> None:
        event.remove(self.engine, "before_cursor_execute", self._hook)

    def touching(self, *tables: str) -> list[str]:
        return [s for s in self.seen if any(t in s for t in tables)]


def fingerprints(runs: list[dict]) -> list[tuple]:
    return [(r["pid"], r["seed"], run_key(r), r["config_hash"], r["configuration_revision"],
             r["episode_version"]) for r in runs]


async def all_runs(client, tid: int, problems: int) -> list[dict]:
    return [{**r, "pid": pid} for pid in range(1, problems + 1) for r in await runs_of(client, tid, pid)]


async def configuration_state(engine, tid: int) -> dict:
    """What the database holds of a session's configuration, without the journal's rows."""
    async with factory_of(engine)() as db:
        row = await configurations.row_for_session(db, tid)
        document = await configurations.current_document(db, row["id"])
        snapshot = (await db.execute(
            select(ConfigurationSnapshot.__table__.c.config_hash, ConfigurationSnapshot.__table__.c.revision)
            .where(ConfigurationSnapshot.__table__.c.configuration_id == row["id"],
                   ConfigurationSnapshot.__table__.c.role == journal.SNAPSHOT_CURRENT))).one()
    return {"id": row["id"], "revision": row["revision"], "row_hash": row["config_hash"],
            "document_hash": cd.config_hash(document), "snapshot": tuple(snapshot),
            "entries": await journal_count(engine, row["id"])}


async def memory_snapshot(engine, tid: int):
    async with factory_of(engine)() as db:
        return (await db.execute(
            select(SessionMemorySnapshot).where(SessionMemorySnapshot.session_id == tid))).scalar_one_or_none()


@pytest.mark.asyncio
async def test_stop_then_start_round_trips_the_live_state_with_zero_journal_reads(
        app_client, serial_sessions, test_engine):
    service = serial_sessions
    made = await create(app_client, 3, seeds_per_problem=2, start=False)
    tid = made["session"]["id"]
    service.set_after_run(tid, _learner)
    await app_client.post(_api(tid, "/start"))
    await until_state(app_client, tid, "finished", timeout=240)
    service.set_after_run(tid, None)
    assert (await service.submit_changes(tid, external(set_param(31))))["ok"] is True
    await app_client.post(_api(tid, "/problems"), json={"problems": [{"initial": "abc", "modified": "abd",
                                                                      "target": "ijk"}]})
    lt = service._live[tid]
    before = {
        "hash": lt.config.config_hash, "revision": lt.config.revision, "version": lt.version,
        "last_change": lt.config.last_change_version, "memory": tm.memory_fingerprint(lt.memory),
        "finished": lt.finished_count, "next_problem_id": lt.next_problem_id,
        "document": lt.config.document,
    }
    assert before["revision"] == 7
    runs_before = fingerprints(await all_runs(app_client, tid, 3))
    await stop(app_client, tid)
    stored = await configuration_state(test_engine, tid)
    assert stored["revision"] == 7 and stored["entries"] >= 7
    assert stored["document_hash"] == stored["row_hash"] == before["hash"]
    snap = await memory_snapshot(test_engine, tid)
    assert snap.version == before["version"] == 6 + 1

    with Statements(test_engine) as seen:
        started = await app_client.post(_api(tid, "/start"), json={"paused": True})
    assert started.status_code == 200, started.text
    assert seen.touching(JOURNAL, MERGES) == []          # no journal row, no merge, read at Start
    assert seen.seen and any("training_mode_session_memory_snapshots" in s for s in seen.seen)
    lt = service._live[tid]
    after = {
        "hash": lt.config.config_hash, "revision": lt.config.revision, "version": lt.version,
        "last_change": lt.config.last_change_version, "memory": tm.memory_fingerprint(lt.memory),
        "finished": lt.finished_count, "next_problem_id": lt.next_problem_id,
        "document": lt.config.document,
    }
    assert {k: v for k, v in after.items() if k != "document"} == {k: v for k, v in before.items() if k != "document"}
    assert after["document"].content_equals(before["document"])
    assert fingerprints(await all_runs(app_client, tid, 3)) == runs_before
    # the queued problem added before the Stop is still queued, and runs once resumed
    assert lt.problems[4].todo and len(lt.problems[4].outcomes) == 0
    await app_client.post(_api(tid, "/resume"))
    done = await until_state(app_client, tid, "finished", timeout=120)
    assert done["problems"]["finished"] == 4 and done["memory_version"] == before["version"] + 2
    # the runs after the Start used the stored configuration (revision 7) and the snapshot memory
    last = (await runs_of(app_client, tid, 4))
    assert {r["configuration_revision"] for r in last} == {7}
    assert {r["config_hash"] for r in last} == {before["hash"]}


@pytest.mark.asyncio
async def test_a_start_after_many_stops_reads_no_journal_and_each_stop_adds_only_its_entries(
        app_client, serial_sessions, test_engine):
    service = serial_sessions
    made = await create(app_client, 0, start=False)
    tid = made["session"]["id"]
    total = 0
    for cycle in range(1, 5):
        await app_client.post(_api(tid, "/start"), json={"paused": True})
        for k in range(cycle):
            assert (await service.submit_changes(tid, external(adjust_param(1))))["ok"] is True
            total += 1
        await stop(app_client, tid)
        state = await configuration_state(test_engine, tid)
        assert state["revision"] == total and state["document_hash"] == state["row_hash"]
        assert state["entries"] == total  # one per batch (a creation with no overrides has none)
    with Statements(test_engine) as seen:
        await app_client.post(_api(tid, "/start"), json={"paused": True})
    assert seen.touching(JOURNAL, MERGES) == []
    assert service._live[tid].config.revision == total == 10


@pytest.mark.asyncio
async def test_a_failed_stop_writes_nothing_returns_to_paused_and_a_retry_writes_everything(
        app_client, serial_sessions, test_engine, monkeypatch):
    """A9: a failure after the journal rows are inserted leaves no journal row, no entries, no
    revision bump, no snapshot; the retry writes all of it, and the journal replays (A7)."""
    service = serial_sessions
    made = await create(app_client, 2, seeds_per_problem=2, start=False)
    tid = made["session"]["id"]
    service.set_after_run(tid, _learner)
    await app_client.post(_api(tid, "/start"))
    done = await until_state(app_client, tid, "finished", timeout=240)
    lt = service._live[tid]
    fingerprint, pending = tm.memory_fingerprint(lt.memory), list(lt.config.pending_entries())
    assert len(pending) == 4 == done["unsaved"]["configuration_batches"]
    stored_before = await configuration_state(test_engine, tid)

    async def fail_after_the_entries(*args, **kwargs):
        raise RuntimeError("injected failure after the journal rows")

    monkeypatch.setattr(journal, "store_current_state", fail_after_the_entries)
    resp = await app_client.post(_api(tid, "/stop"))
    assert resp.status_code == 500 and "Paused" in resp.json()["detail"]
    assert await configuration_state(test_engine, tid) == stored_before      # no entry, no revision bump
    assert await memory_snapshot(test_engine, tid) is None
    assert await db_count(test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == tid) == 0
    paused = await session_state(app_client, tid)
    assert paused["state"] == "paused" and "injected failure" in paused["last_event"]
    assert paused["unsaved"]["configuration_batches"] == 4
    assert service._live[tid] is lt and tm.memory_fingerprint(lt.memory) == fingerprint
    assert list(lt.config.pending_entries()) == pending and lt.config.revision == 4

    monkeypatch.undo()
    stopped = await stop(app_client, tid)
    assert stopped["state"] == "stopped" and stopped["configuration"]["version"] == 4
    state = await configuration_state(test_engine, tid)
    assert state["revision"] == 4 and state["entries"] == stored_before["entries"] + 4
    assert state["document_hash"] == state["row_hash"] == lt.config.config_hash
    snap = await memory_snapshot(test_engine, tid)
    assert snap.version == await db_count(test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == tid) == 4
    assert tm.memory_fingerprint(tm.memory_from_snapshot(snap.data)) == fingerprint
    async with factory_of(test_engine)() as db:       # A7: replay equals the stored state
        report = await verify_journal(db, state["id"])
        top = await configurations.config_at(db, state["id"], 4)
        assert report["ok"], report["problems"]
        assert top.content_equals(await configurations.current_document(db, state["id"]))
        assert top.content_equals(lt.config.document)


@pytest.mark.asyncio
async def test_a_tampered_stored_state_refuses_the_start_and_names_the_check(
        app_client, serial_sessions, test_engine):
    service = serial_sessions
    made = await create(app_client, 1, seeds_per_problem=1, start=False)
    tid = made["session"]["id"]
    await app_client.post(_api(tid, "/start"), json={"paused": True})
    await service.submit_changes(tid, external(set_param(23)))
    await stop(app_client, tid)
    state = await configuration_state(test_engine, tid)
    original = await stored_document(test_engine, tid)
    # change a value in the stored current state, leaving the recorded hash as it was
    async with factory_of(test_engine)() as db:
        table = ConfigurationSnapshot.__table__
        data = (await db.execute(select(table.c.data).where(
            table.c.configuration_id == state["id"], table.c.role == journal.SNAPSHOT_CURRENT))).scalar_one()
        for row in data["tables"]["engine_params"]:
            if row["name"] == PARAM:
                row["value"] = "99"
        await db.execute(update(table).where(
            table.c.configuration_id == state["id"], table.c.role == journal.SNAPSHOT_CURRENT).values(data=data))
        await db.commit()
    resp = await app_client.post(_api(tid, "/start"))
    assert resp.status_code == 409 and "config_hash check failed" in resp.json()["detail"]
    assert tid not in service._live and (await session_state(app_client, tid))["state"] == "stopped"
    # the consistency check finds the same fault (a replay of the journal differs from the stored state)
    async with factory_of(test_engine)() as db:
        report = await verify_journal(db, state["id"])
    assert not report["ok"]
    # put the state back as the Stop wrote it, and the Start is accepted
    async with factory_of(test_engine)() as db:
        await journal.store_current_state(db, state["id"], original, revision=state["revision"],
                                          config_hash=state["row_hash"])
        await db.commit()
    resp = await app_client.post(_api(tid, "/start"))
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_an_edit_made_while_stopped_is_not_tampering(app_client, serial_sessions, test_engine):
    service = serial_sessions
    made = await create(app_client, 1, seeds_per_problem=1, start=False)
    tid = made["session"]["id"]
    await app_client.post(_api(tid, "/start"), json={"paused": True})
    await service.submit_changes(tid, external(set_param(23)))
    await stop(app_client, tid)
    out = await service.submit_changes(tid, external(adjust_param(2)))   # Stopped: written at once
    assert out["persisted"] is True
    started = await app_client.post(_api(tid, "/start"), json={"paused": True})
    assert started.status_code == 200
    config = service._live[tid].config
    assert config.revision == 2 and config.document.tables["engine_params"][(PARAM,)]["value"] == "25"
    assert config.config_hash == (await configuration_state(test_engine, tid))["row_hash"]


@pytest.mark.asyncio
async def test_a_graceful_shutdown_stores_every_live_sessions_configuration(app_client, serial_sessions, test_engine):
    service = serial_sessions
    ids = []
    for n in range(3):
        made = await create(app_client, 1, seeds_per_problem=1, start=False)
        tid = made["session"]["id"]
        await app_client.post(_api(tid, "/start"), json={"paused": bool(n % 2)})
        await service.submit_changes(tid, external(set_param(30 + n)))
        ids.append(tid)
    hashes = {tid: service._live[tid].config.config_hash for tid in ids}
    await service.stop()
    assert not service._live
    second = make_service(test_engine, service.test_meta)
    await second.start()
    bs.set_training_mode_session_service(second)
    try:
        for n, tid in enumerate(ids):
            state = await configuration_state(test_engine, tid)
            assert state["revision"] == 1 and state["document_hash"] == hashes[tid]
            assert (await session_state(app_client, tid))["configuration"]["hash"] == hashes[tid]
            assert (await app_client.post(_api(tid, "/start"), json={"paused": True})).status_code == 200
            assert second._live[tid].config.config_hash == hashes[tid]
            assert second._live[tid].config.document.tables["engine_params"][(PARAM,)]["value"] == str(30 + n)
    finally:
        bs.set_training_mode_session_service(service)
        await second.stop()


@pytest.mark.asyncio
async def test_after_a_start_workers_run_from_the_snapshot_memory_and_it_equals_the_merge_replay(
        app_client, sessions, test_engine):
    made = await create(app_client, 6, seeds_per_problem=4, max_codelets=2500, start=False)
    tid = made["session"]["id"]
    await app_client.post(_api(tid, "/start"))

    async def some():
        return (await session_state(app_client, tid))["runs"]["done"] >= 6

    await wait_for(some, timeout=120)
    await stop(app_client, tid)
    version = (await memory_snapshot(test_engine, tid)).version
    assert version == await db_count(test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == tid) >= 6
    await app_client.post(_api(tid, "/start"))
    done = await until_state(app_client, tid, "finished", timeout=240)
    assert done["runs"]["done"] == 24 and done["runs"]["errors"] == 0 and done["memory_version"] == 24
    fingerprint = tm.memory_fingerprint(sessions.live_memory(tid))
    await stop(app_client, tid)
    async with factory_of(test_engine)() as db:
        replayed = await bs.TrainingModeSessionService.rebuild_memory(db, tid)
    assert tm.memory_fingerprint(replayed) == fingerprint
    snap = await memory_snapshot(test_engine, tid)
    assert snap.version == 24 and tm.memory_fingerprint(tm.memory_from_snapshot(snap.data)) == fingerprint
    # a Stopped session's memory is served from the snapshot
    stored = await sessions.memory_of(tid)
    assert tm.memory_fingerprint(stored) == fingerprint


@pytest.mark.asyncio
async def test_a_session_never_stopped_starts_with_an_empty_memory_and_stores_nothing_until_stop(
        app_client, serial_sessions, test_engine):
    made = await create(app_client, 1, seeds_per_problem=2, start=False)
    tid = made["session"]["id"]
    assert await memory_snapshot(test_engine, tid) is None
    await app_client.post(_api(tid, "/start"))
    await until_state(app_client, tid, "finished", timeout=120)
    assert await memory_snapshot(test_engine, tid) is None            # nothing written while live
    assert await journal_count(test_engine, (await configuration_state(test_engine, tid))["id"]) == 0
    await stop(app_client, tid)
    assert (await memory_snapshot(test_engine, tid)).version == 2
    # a Stop with nothing new writes no new snapshot
    await app_client.post(_api(tid, "/start"), json={"paused": True})
    saved = (await memory_snapshot(test_engine, tid)).saved_at
    await stop(app_client, tid)
    assert (await memory_snapshot(test_engine, tid)).saved_at == saved
