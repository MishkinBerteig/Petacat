"""A Training Mode Session runs its own evolving configuration (S3).

Each session has its own configuration, starting from its Starting Conceptual State (a base plus
creation overrides) and changed by Training-Mode learning from every learning source.  What is
checked here, against the service and a scratch database:

* creation from each ``configuration_base``, with ``settings.parameters`` folded in once;
* WP-S3: an unedited session on the global base equals today's session run for run, and one
  worker equals the serial episode even while a learner changes the configuration after each run;
* a batch on a running session reaches the next dispatched run and not one already in flight;
* a Stopped session's edit is written at once, a live session's is held (``persisted: false``);
* ``busy`` while Starting or Stopping, and the one door (``ChangeService.apply``) for a live session;
* the held entries are accepted, as they are, by the journal layer's deferred write;
* M1: nothing a session does reaches Metacat Mode's configuration;
* the summary and run fields.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import Future

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.engine.hashing import config_hash as provider_hash
from server.engine.memory import EpisodicMemory
from server.engine.metadata import MetadataProvider
from server.engine.parameters import RUN_PARAMETERS
from server.models.journal import JournalEntry
from server.services import config_document as cd
from server.services import configuration_store as store
from server.services import configurations, journal
from server.services import training_mode_session_memory as tm
from server.services import training_mode_session_service as bs
from server.services.configuration_admin import reference_document, verify_journal
from server.services.configuration_writer import ChangeError, ChangeService
from server.services.session_live_config import LiveConfiguration
from server.services.training_mode_session_executor import (
    SerialExecutor, SessionOutcome, create_executor, run_task, SessionTask, outcome_fingerprint,
)
from tests.e2e.test_training_mode_sessions_api import (
    create, make_service, problem, replay, session_state, stop, stored_runs, until_state, wait_for,
)

PARAM = "update_cycle_length"


@pytest.fixture(scope="module", autouse=True)
def _stop_default_swarm():
    yield
    from server.parallel.swarm import shutdown_default

    shutdown_default()


async def _service(app_client, test_engine, executor=None):
    from server.api.runs import get_run_service

    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM training_mode_sessions"))
    meta = get_run_service().meta
    service = make_service(test_engine, meta, executor=executor)
    await service.start()
    bs.set_training_mode_session_service(service)
    service.test_meta = meta
    service.test_engine = test_engine
    return service


@pytest.fixture
async def sessions(app_client, test_engine):
    service = await _service(app_client, test_engine, create_executor())
    yield service
    bs.set_training_mode_session_service(None)
    await service.stop()
    async with service.test_engine.begin() as conn:  # leave no session (or configuration) behind
        await conn.execute(text("DELETE FROM training_mode_sessions"))


@pytest.fixture
async def serial_sessions(app_client, test_engine):
    service = await _service(app_client, test_engine, SerialExecutor())
    yield service
    bs.set_training_mode_session_service(None)
    await service.stop()
    async with service.test_engine.begin() as conn:  # leave no session (or configuration) behind
        await conn.execute(text("DELETE FROM training_mode_sessions"))


class ManualExecutor:
    """An executor whose runs finish when the test says so: one worker, nothing runs."""

    kind = "manual"
    workers = 1

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    @property
    def in_flight(self) -> int:
        return sum(1 for *_, f in self.calls if not f.done())

    def submit(self, tasks, meta) -> Future:
        future: Future = Future()
        self.calls.append((tasks[0], meta, future))
        return future

    def finish(self, index: int, answer: str = "abd") -> None:
        task, _meta, future = self.calls[index]
        future.set_result([SessionOutcome(
            seed=task.seed, status="answer_found", answer=answer, answers=[answer], codelets=7,
            seconds=0.0, stopping_state=f"answer_found:{answer}", temperature=10.0,
        )])

    def close(self) -> None:
        pass


@pytest.fixture
async def manual(app_client, test_engine):
    executor = ManualExecutor()
    service = await _service(app_client, test_engine, executor)
    service.test_executor = executor
    yield service
    bs.set_training_mode_session_service(None)
    await service.stop()
    async with service.test_engine.begin() as conn:  # leave no session (or configuration) behind
        await conn.execute(text("DELETE FROM training_mode_sessions"))


def external(*ops, **extra) -> dict:
    """A batch as the external route submits it: ``head`` unless the test names a ``base_version``."""
    return {"source": "external", "actor": "test", "base_version": "head", "ops": list(ops), **extra}


def set_param(value, name: str = PARAM) -> dict:
    return {"op": "set_param", "name": name, "to": value}


def adjust_param(by) -> dict:
    return {"op": "adjust_param", "name": PARAM, "by": by}


def factory_of(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def journal_count(engine, configuration_id: int) -> int:
    async with factory_of(engine)() as s:
        return (await s.execute(
            select(func.count()).select_from(JournalEntry.__table__)
            .where(JournalEntry.__table__.c.configuration_id == configuration_id)
        )).scalar_one()


async def create_with(client, **settings) -> dict:
    """A Stopped session with one problem; ``settings`` as the request carries them."""
    # These tests mean the global configuration unless a test names another base.
    body = {"name": "s3", "settings": {"seeds_per_problem": 2, "max_codelets": 300,
                                       "configuration_base": "global", **settings},
            "problems": [problem(0)]}
    resp = await client.post("/api/training-mode/sessions", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["session"]


async def stored_document(engine, session_id: int) -> cd.ConfigDocument:
    async with factory_of(engine)() as s:
        row = await configurations.row_for_session(s, session_id)
        return await configurations.current_document(s, row["id"])


# ---------------------------------------------------------------------------
# Creation: each base, overrides folded once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creation_from_each_base(app_client, sessions, test_engine):
    standard_hash = provider_hash(MetadataProvider.from_standard_configuration("seed_data"))
    factory = factory_of(test_engine)
    changed = "17"
    async with factory() as db:
        original = (await configurations.current_document(db, 1)).tables["engine_params"][(PARAM,)]["value"]
    try:
        async with factory() as db:
            await ChangeService.apply(db, {"source": "admin", "actor": "t", "base_mode": "rebase",
                                           "ops": [set_param(int(changed))]})
        # no base named: the v2.0 Base (the default), which is not a copy of the global configuration
        unnamed = (await app_client.post("/api/training-mode/sessions", json={"name": "unnamed"})).json()["session"]
        assert unnamed["settings"]["configuration_base"] == "training-v2"
        assert unnamed["configuration"]["hash"] != (await app_client.get(
            "/api/configurations/1")).json()["config_hash"]
        default = await create_with(app_client)  # the helper names the global configuration
        assert default["settings"]["configuration_base"] == "global"
        explicit = await create_with(app_client, configuration_base="global")
        standard = await create_with(app_client, configuration_base="standard")
        assert standard["settings"]["configuration_base"] == "standard"
        # global: the edited global configuration as it stands now; standard: the files
        assert (await stored_document(test_engine, default["id"])).tables["engine_params"][(PARAM,)]["value"] == changed
        assert default["configuration"]["hash"] == explicit["configuration"]["hash"]
        assert standard["configuration"]["hash"] == standard_hash != default["configuration"]["hash"]
        assert standard["config_hash"] == standard["configuration"]["hash"]
        assert standard["configuration"]["base_hash"] == standard_hash
        # another session's current configuration: edit one first (Stopped: written at once)
        await sessions.submit_changes(standard["id"], external(set_param(19)))
        child = await create_with(app_client, configuration_base={"session_id": standard["id"]})
        assert child["settings"]["configuration_base"] == {"session_id": standard["id"]}
        doc = await stored_document(test_engine, child["id"])
        assert doc.tables["engine_params"][(PARAM,)]["value"] == "19"
        assert child["configuration"]["version"] == 0
        async with factory() as db:
            row = await configurations.row_for_session(db, child["id"])
            parent = await configurations.row_for_session(db, standard["id"])
        assert (row["created_from_configuration_id"], row["created_from_revision"]) == (parent["id"], 1)
        # the parent was not touched by creating a child of it
        assert (await sessions.summary(standard["id"]))["configuration"]["version"] == 1
    finally:
        async with factory() as db:
            await ChangeService.apply(db, {"source": "admin", "actor": "t", "base_mode": "rebase",
                                           "ops": [set_param(int(original))]})


@pytest.mark.asyncio
async def test_a_bad_configuration_base_is_refused(app_client, sessions):
    for base in ("elsewhere", 3, {"session_id": "1"}, {"session_id": 1, "extra": 2}, {"id": 1}, None):
        resp = await app_client.post("/api/training-mode/sessions", json={
            "name": "x", "settings": {"configuration_base": base}})
        assert resp.status_code == 422, (base, resp.text)
    resp = await app_client.post("/api/training-mode/sessions", json={
        "name": "x", "settings": {"configuration_base": {"session_id": 999999}}})
    assert resp.status_code == 422 and "configuration_base" in resp.json()["detail"]
    assert (await app_client.get("/api/training-mode/sessions")).json()["sessions"] == []


@pytest.mark.asyncio
async def test_creation_overrides_are_checked_against_the_configuration_the_session_starts_from(
        app_client, sessions, test_engine):
    """A reference parameter's shape comes from ``engine_params.refers_to`` of the configuration the
    run executes under, and a session's own configuration is not the global one.

    A session whose ``top_down_slipnodes`` is declared a map of names to numbers is the base of a
    second session: a map is accepted for it and a list is refused, the reverse of the global
    configuration (a list is accepted and a map refused).  Under the global configuration a check
    that ignored the base would answer the other way round.
    """
    name = "top_down_slipnodes"
    node = "plato-opposite"
    as_list, as_map = [node], {node: 3}
    base = await create_with(app_client)
    # the same body, against the global configuration: a list, not a map
    assert (await create_with(app_client, parameters={name: as_list}))["settings"]["parameters"] == {name: as_list}
    refused = await app_client.post("/api/training-mode/sessions", json={
        "name": "x", "settings": {"parameters": {name: as_map}}})
    assert refused.status_code == 400 and name in refused.json()["detail"], refused.text
    # change the base session's own configuration: the parameter now names nodes with numbers
    document = await stored_document(test_engine, base["id"])
    assert document.tables["engine_params"][(name,)]["refers_to"] == "trigger_node_list"
    await sessions.submit_changes(base["id"], external(
        {"op": "update", "table": "engine_params", "key": {"name": name},
         "fields": {"value": json.dumps(as_map), "value_type": "json", "refers_to": "node_map"}}))
    base_of = {"session_id": base["id"]}
    child = await create_with(app_client, configuration_base=base_of, parameters={name: as_map})
    assert child["settings"]["parameters"] == {name: as_map}
    refused = await app_client.post("/api/training-mode/sessions", json={
        "name": "x", "settings": {"configuration_base": base_of, "parameters": {name: as_list}}})
    assert refused.status_code == 400 and name in refused.json()["detail"], refused.text


def _two_overrides() -> dict:
    ints = [p for p in RUN_PARAMETERS if p.kind == "int" and p.name != PARAM]
    floats = [p for p in RUN_PARAMETERS if p.kind == "float"]
    assert ints and floats
    chosen = {PARAM: 16}
    # a value strictly inside each range, different from the default
    for p in (floats[0],):
        chosen[p.name] = round((p.minimum + p.maximum) / 2, 3) if p.minimum is not None and p.maximum is not None else 0.5
    return chosen


@pytest.mark.asyncio
async def test_creation_overrides_are_folded_into_the_starting_conceptual_state(
        app_client, sessions, test_engine):
    overrides = _two_overrides()
    session = await create_with(app_client, parameters=overrides)
    # the record stays; the configuration carries the values; the creation batch is revision 1
    assert session["settings"]["parameters"] == overrides
    assert session["configuration"]["version"] == 1
    async with factory_of(test_engine)() as db:
        row = await configurations.row_for_session(db, session["id"])
        [entry] = (await db.execute(
            select(JournalEntry.__table__).where(JournalEntry.__table__.c.configuration_id == row["id"])
        )).mappings().all()
        document = await configurations.current_document(db, row["id"])
    assert entry["source"] == "creation" and entry["revision"] == 1
    provider = cd.provider(document)
    for name, value in overrides.items():
        assert provider.get_param(name) == value
    # ... exactly what with_overrides gives a run
    meta = sessions.test_meta
    assert provider.params == meta.with_overrides(overrides).params
    # the stored base snapshot is the state after the creation batch: the Starting Conceptual State
    async with factory_of(test_engine)() as db:
        base = await configurations.base_document(db, row["id"])
    assert base.content_equals(document)
    assert session["configuration"]["base_hash"] == cd.config_hash(base)


@pytest.mark.asyncio
async def test_folded_overrides_run_exactly_as_with_overrides_runs(app_client, sessions, test_engine):
    overrides = _two_overrides()
    session = await create_with(app_client, parameters=overrides)
    provider = cd.provider(await stored_document(test_engine, session["id"]))
    meta = sessions.test_meta
    for seed in (1, 2, 3):
        old = run_task(SessionTask("abc", "abd", "ijk", None, seed, 300, overrides, "off"), meta)
        new = run_task(SessionTask("abc", "abd", "ijk", None, seed, 300, None, "off"), provider)
        assert outcome_fingerprint(old) == outcome_fingerprint(new)
        assert old.error is None


@pytest.mark.asyncio
async def test_a_task_carries_no_overrides_and_the_run_uses_the_sessions_configuration(manual, app_client):
    overrides = {PARAM: 16}
    session = await create_with(app_client, parameters=overrides)
    await app_client.post(f"/api/training-mode/sessions/{session['id']}/start")
    ex = manual.test_executor
    await until(lambda: len(ex.calls) >= 1)
    task, meta, _ = ex.calls[0]
    assert task.parameters is None
    assert meta.get_param(PARAM) == 16
    assert provider_hash(meta) == session["configuration"]["hash"]


async def _async(value):
    return value


async def until(condition, timeout: float = 60.0):
    """Wait until the synchronous *condition* is true."""
    await wait_for(lambda: _async(condition()), timeout)


# ---------------------------------------------------------------------------
# WP-S3: an unedited session equals today's session; one worker equals the serial episode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unedited_global_session_equals_todays_session_run_for_run(
        app_client, serial_sessions, test_engine):
    """Base ``global``, no overrides, no edits: the runs are the global configuration's serial
    episode, the configuration is the global one (same hash), and it writes no journal entry."""
    meta = serial_sessions.test_meta
    made = await create(app_client, 3, seeds_per_problem=2)
    tid = made["session"]["id"]
    assert made["session"]["configuration"]["hash"] == provider_hash(meta)
    done = await until_state(app_client, tid, "finished", timeout=180)
    assert done["configuration"]["version"] == 0 and done["configuration"]["last_change_version"] is None
    assert done["unsaved"]["configuration_batches"] == 0
    backend = done["settings"]["backend"]
    await stop(app_client, tid)
    rows = await stored_runs(test_engine, tid)
    reference = EpisodicMemory()
    for r, p in rows:
        status, answer, codelets, quality = replay(meta, reference, p, r.seed, 300, backend)
        assert (r.status, r.answer, r.codelets, r.answer_quality) == (status, answer, codelets, quality)
        assert r.config_hash == provider_hash(meta) and r.configuration_revision == 0
    async with factory_of(test_engine)() as db:
        row = await configurations.row_for_session(db, tid)
    assert row["revision"] == 0 and await journal_count(test_engine, row["id"]) == 0


def _learner(outcome, provider):
    """A deterministic test learner: after every run, one more update-cycle step."""
    return {"ops": [adjust_param(1)]}


@pytest.mark.asyncio
async def test_one_worker_equals_the_serial_episode_with_a_learner(
        app_client, serial_sessions, test_engine):
    """The after-run seam: with one worker every run starts after the previous one merged, so
    the session equals a reference loop that runs each seed under the configuration as the
    previous runs' batches left it -- outcomes, versions, revisions and the final hash."""
    service = serial_sessions
    made = await create(app_client, 3, seeds_per_problem=2, start=False)
    tid = made["session"]["id"]
    service.set_after_run(tid, _learner)
    await app_client.post(f"/api/training-mode/sessions/{tid}/start")
    done = await until_state(app_client, tid, "finished", timeout=240)
    assert done["configuration"]["version"] == 6 and done["unsaved"]["configuration_batches"] == 6
    final_hash = service._live[tid].config.config_hash
    assert done["configuration"]["hash"] == final_hash
    backend = done["settings"]["backend"]
    pending = service._live[tid].config.pending_entries()
    await stop(app_client, tid)
    rows = await stored_runs(test_engine, tid)

    live = LiveConfiguration(reference_document(), configuration_id=0, revision=0, episode_version=0)
    memory = EpisodicMemory()
    for r, p in rows:
        ref = live.ref(tid)
        status, answer, codelets, quality = replay(ref.provider, memory, p, r.seed, 300, backend)
        assert (r.status, r.answer, r.codelets, r.answer_quality) == (status, answer, codelets, quality)
        assert (r.config_hash, r.configuration_revision, r.memory_version) == (
            ref.config_hash, ref.configuration_revision, ref.version)
        live.finish_run(memory_merge=lambda: None, batch=_learner(None, None),
                        started_revision=ref.configuration_revision)
    assert live.config_hash == final_hash and live.revision == 6 and live.version == 6
    assert [e.config_hash for e in live.pending_entries()] == [e.config_hash for e in pending]
    assert [r.configuration_revision for r, _ in rows] == [0, 1, 2, 3, 4, 5]
    assert [r.memory_version for r, _ in rows] == [0, 1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_no_learner_means_nothing_is_computed_or_held(manual, app_client):
    session = await create_with(app_client)
    await app_client.post(f"/api/training-mode/sessions/{session['id']}/start")
    ex = manual.test_executor
    await until(lambda: len(ex.calls) >= 1)
    ex.finish(0)
    await until(lambda: len(ex.calls) >= 2)
    config = manual._live[session["id"]].config
    assert config.pending_entries() == [] and config.diagnostics == []
    assert (config.revision, config.version) == (0, 1)


@pytest.mark.asyncio
async def test_a_learner_that_raises_never_fails_its_run(manual, app_client, test_engine):
    def bad(outcome, provider):
        raise RuntimeError("learner bug")

    session = await create_with(app_client)
    tid = session["id"]
    manual.set_after_run(tid, bad)
    await app_client.post(f"/api/training-mode/sessions/{tid}/start")
    ex = manual.test_executor
    await until(lambda: len(ex.calls) >= 1)
    ex.finish(0)
    await until(lambda: len(ex.calls) >= 2)
    config = manual._live[tid].config
    assert config.version == 1 and config.revision == 0
    assert config.diagnostics[0]["kind"] == "learner_raised" and "learner bug" in config.diagnostics[0]["message"]
    manual.set_after_run(tid, lambda o, p: "not a batch")
    ex.finish(1)
    await until(lambda: config.version == 2)
    assert config.diagnostics[1]["kind"] == "learner_batch_malformed"
    summary = await session_state(app_client, tid)
    assert summary["runs"]["errors"] == 0 and summary["runs"]["done"] == 2


# ---------------------------------------------------------------------------
# A batch reaches the next dispatched run, and not one in flight
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_external_batch_reaches_the_next_run_and_not_one_in_flight(
        manual, app_client, test_engine):
    session = await create_with(app_client, seeds_per_problem=3)
    tid = session["id"]
    await app_client.post(f"/api/training-mode/sessions/{tid}/start")
    ex = manual.test_executor
    await until(lambda: len(ex.calls) >= 1)
    first_task, first_meta, _ = ex.calls[0]
    first_hash = provider_hash(first_meta)
    old_value = first_meta.get_param(PARAM)

    report = await manual.submit_changes(tid, external(set_param(old_value + 5)))
    assert report["persisted"] is False and report["version_after"] == 1 and report["episode_version"] == 1
    await asyncio.sleep(0.2)
    assert len(ex.calls) == 1  # one worker: nothing else was dispatched
    assert ex.calls[0][1] is first_meta and first_meta.get_param(PARAM) == old_value  # in flight: unchanged
    ex.finish(0)
    await until(lambda: len(ex.calls) >= 2)
    second_task, second_meta, _ = ex.calls[1]
    assert second_meta.get_param(PARAM) == old_value + 5 and provider_hash(second_meta) != first_hash
    ex.finish(1)
    await until(lambda: len(ex.calls) >= 3)
    ex.finish(2)
    await until(lambda: manual._live[tid].config.version == 4)
    await stop(app_client, tid)
    rows = [r for r, _ in await stored_runs(test_engine, tid)]
    assert [(r.configuration_revision, r.memory_version, r.seq) for r in rows] == [(0, 0, 2), (1, 2, 3), (1, 3, 4)]
    assert rows[0].config_hash == first_hash and rows[1].config_hash == rows[2].config_hash != first_hash


# ---------------------------------------------------------------------------
# Stopped and live: where a batch is recorded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stopped_sessions_edit_is_written_at_once(app_client, sessions, test_engine):
    session = await create_with(app_client)
    tid = session["id"]
    report = await sessions.submit_changes(tid, external(set_param(16)))
    assert report["persisted"] is True and report["version_before"] == 0 and report["version_after"] == 1
    async with factory_of(test_engine)() as db:
        row = await configurations.row_for_session(db, tid)
    assert row["revision"] == 1 and await journal_count(test_engine, row["id"]) == 1
    summary = await sessions.summary(tid)
    assert summary["source"] == "stored" and summary["configuration"]["version"] == 1
    assert summary["configuration"]["hash"] == summary["config_hash"] == row["config_hash"]
    assert summary["saved_through"]["configuration_revision"] == 1
    # ... and Start loads it: the live configuration is the stored one
    started = (await app_client.post(f"/api/training-mode/sessions/{tid}/start")).json()
    assert started["configuration"]["version"] == 1 and started["configuration"]["hash"] == row["config_hash"]
    assert sessions._live[tid].config.provider.get_param(PARAM) == 16


@pytest.mark.asyncio
async def test_a_live_sessions_edit_is_held_in_memory(app_client, sessions, test_engine):
    session = await create_with(app_client, seeds_per_problem=100000)
    tid = session["id"]
    await app_client.post(f"/api/training-mode/sessions/{tid}/start", json={"paused": True})
    async with factory_of(test_engine)() as db:
        row = await configurations.row_for_session(db, tid)
    report = await sessions.submit_changes(tid, external(set_param(16)))
    assert report["persisted"] is False and report["version_after"] == 1 and report["batch_id"] is None
    assert await journal_count(test_engine, row["id"]) == 0  # nothing in the database
    async with factory_of(test_engine)() as db:
        assert (await configurations.get_row(db, row["id"]))["revision"] == 0
    live = await session_state(app_client, tid)
    assert live["source"] == "live" and live["persisted"] is False
    assert live["configuration"]["version"] == 1 and live["configuration"]["last_change_version"] == 1
    assert live["saved_through"]["configuration_revision"] == 0
    assert live["unsaved"]["configuration_batches"] == 1
    # a dry run asks, and changes nothing
    dry = await sessions.submit_changes(tid, external(set_param(30), dry_run=True))
    assert dry["dry_run"] is True and (await session_state(app_client, tid))["configuration"]["version"] == 1


@pytest.mark.asyncio
async def test_the_one_door_routes_a_live_session_to_memory(app_client, sessions, test_engine):
    session = await create_with(app_client)
    tid = session["id"]
    await app_client.post(f"/api/training-mode/sessions/{tid}/start", json={"paused": True})
    config_id = session["configuration"]["id"]
    async with factory_of(test_engine)() as db:
        report = await ChangeService.apply(db, {**external(set_param(18)), "configuration_id": config_id})
    assert report["persisted"] is False and report["version_after"] == 1
    assert await journal_count(test_engine, config_id) == 0
    assert sessions._live[tid].config.provider.get_param(PARAM) == 18
    # the store reads the live document, labelled
    async with factory_of(test_engine)() as db:
        view = await store.get_configuration_store().provider(db, config_id)
    assert view.source == "live" and view.revision == 1 and view.saved_through == 0 and view.unsaved == 1
    assert view.provider.get_param(PARAM) == 18
    assert store.live_state(tid).pending[0].revision == 1
    # a stale strict batch is 409 stale, from either door
    with pytest.raises(ChangeError) as caught:
        async with factory_of(test_engine)() as db:
            await ChangeService.apply(db, {**external(set_param(19), base_version=0), "configuration_id": config_id})
    assert caught.value.code == "stale" and caught.value.status == 409
    # a Stopped session has no live state: the store answers from the database again
    await stop(app_client, tid)
    assert store.live_state(tid) is None


@pytest.mark.asyncio
async def test_starting_and_stopping_answer_busy(app_client, sessions, test_engine):
    session = await create_with(app_client)
    tid = session["id"]
    config_id = session["configuration"]["id"]
    await app_client.post(f"/api/training-mode/sessions/{tid}/start", json={"paused": True})
    lt = sessions._live[tid]
    lt.status = "stopping"
    for call in (
        lambda: sessions.submit_changes(tid, external(set_param(16))),
        lambda: sessions.apply_live(tid, external(set_param(16))),
    ):
        with pytest.raises(ChangeError) as caught:
            await call()
        assert caught.value.code == "busy" and caught.value.status == 409
    with pytest.raises(ChangeError) as caught:
        async with factory_of(test_engine)() as db:
            await ChangeService.apply(db, {**external(set_param(16)), "configuration_id": config_id})
    assert caught.value.code == "busy"
    lt.status = "paused"
    sessions._starting.add(tid)
    try:
        with pytest.raises(ChangeError) as caught:
            await sessions.submit_changes(tid, external(set_param(16)))
        assert caught.value.code == "busy"
        assert store.live_state(tid).state == "starting" and store.live_state(tid).document is None
    finally:
        sessions._starting.discard(tid)
    assert (await sessions.submit_changes(tid, external(set_param(16))))["version_after"] == 1


@pytest.mark.asyncio
async def test_unknown_sessions_and_mismatched_configurations(app_client, sessions):
    from server.services.configuration_writer import ChangeError as CE

    with pytest.raises(bs.SessionError) as caught:
        await sessions.submit_changes(424242, external(set_param(16)))
    assert caught.value.status == 404
    session = await create_with(app_client)
    with pytest.raises(CE) as caught:
        await sessions.submit_changes(session["id"], {**external(set_param(16)), "configuration_id": 1})
    assert caught.value.code == "malformed"
    with pytest.raises(CE) as caught:
        await sessions.submit_changes(session["id"], {"ops": []})
    assert caught.value.code == "malformed"


# ---------------------------------------------------------------------------
# The Stop write's hand-off, and the live batch equals the stored batch
# ---------------------------------------------------------------------------


BATCHES = [
    [set_param(16)],
    [adjust_param(2), {"op": "set_coefficient", "name": "unhappiness_weight", "to": 71.0}],
    [{"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"}, "fields": {"conceptual_depth": 11}}],
]


@pytest.mark.asyncio
async def test_a_live_batch_is_the_batch_the_stored_path_writes(app_client, sessions, test_engine):
    """The same batches to a live session and to a Stopped twin end in the same configuration, and
    the entries the live session holds are accepted by the journal layer's deferred write and
    verify as a journal: this is the hand-off to the Stop write (S5)."""
    live = await create_with(app_client)
    twin = await create_with(app_client)
    await app_client.post(f"/api/training-mode/sessions/{live['id']}/start", json={"paused": True})
    for ops in BATCHES:
        got = await sessions.submit_changes(live["id"], external(*ops))
        want = await sessions.submit_changes(twin["id"], external(*ops))
        assert got["ok"] is True and want["ok"] is True
        assert got["version_after"] == want["version_after"]
    held = sessions._live[live["id"]].config
    assert held.revision == len(BATCHES) and len(held.pending_entries()) == len(BATCHES)
    stored_twin = await stored_document(test_engine, twin["id"])
    assert held.document.content_equals(stored_twin) and held.config_hash == cd.config_hash(stored_twin)
    # the twin's journal rows are the live session's entries
    async with factory_of(test_engine)() as db:
        twin_row = await configurations.row_for_session(db, twin["id"])
        rows = (await db.execute(
            select(JournalEntry.__table__).where(JournalEntry.__table__.c.configuration_id == twin_row["id"])
            .order_by(JournalEntry.__table__.c.revision))).mappings().all()
    for entry, row in zip(held.pending_entries(), rows):
        assert (entry.revision, entry.source, entry.actor) == (row["revision"], row["source"], row["actor"])
        assert entry.resolved == row["resolved"] and entry.before == row["before"]
        assert entry.proposed == row["proposed"] and entry.config_hash == row["config_hash"]
    # the Stop write's calls, in one transaction, then the journal verifies
    async with factory_of(test_engine)() as db:
        live_row = await configurations.row_for_session(db, live["id"])
        await journal.write_deferred(
            db, configuration_id=live_row["id"], entries=held.pending_entries(), commit=False)
        await journal.store_current_state(
            db, live_row["id"], held.document, revision=held.revision, config_hash=held.config_hash)
        await db.commit()
    async with factory_of(test_engine)() as db:
        report = await verify_journal(db, live_row["id"])
    assert report["ok"], report["problems"]


# ---------------------------------------------------------------------------
# M1: Metacat Mode is untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metacat_modes_configuration_is_untouched_by_a_session(app_client, sessions, test_engine):
    the_store = store.get_configuration_store()
    provider, revision = the_store.current(), the_store.revision
    async with factory_of(test_engine)() as db:
        before_hash = await journal.compute_config_hash(db)
        global_entries = await journal_count(test_engine, 1)
    session = await create_with(app_client, parameters={PARAM: 16})
    tid = session["id"]
    await app_client.post(f"/api/training-mode/sessions/{tid}/start")
    await sessions.submit_changes(tid, external(set_param(21)))
    sessions.set_after_run(tid, _learner)
    await app_client.post(f"/api/training-mode/sessions/{tid}/resume")
    async def two_runs():
        return (await session_state(app_client, tid))["runs"]["done"] >= 2

    await wait_for(two_runs, timeout=120)
    await sessions.submit_changes(tid, external(set_param(22)))
    await stop(app_client, tid)
    await sessions.submit_changes(tid, external(set_param(23)))
    assert the_store.current() is provider and the_store.revision == revision
    assert provider.get_param(PARAM) == sessions.test_meta.get_param(PARAM) != 23
    async with factory_of(test_engine)() as db:
        assert await journal.compute_config_hash(db) == before_hash
        assert (await configurations.get_row(db, 1))["revision"] == revision
        assert await journal_count(test_engine, 1) == global_entries
    # and a session's edit never goes in by the global door
    async with factory_of(test_engine)() as db:
        with pytest.raises(ChangeError) as caught:
            await ChangeService.apply(db, {**external(set_param(24)), "configuration_id": 1})
    assert caught.value.code == "source_refused"


# ---------------------------------------------------------------------------
# Stop and Start, delete, and the summary and run fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_then_start_keeps_the_episode_counter_and_the_stored_configuration(
        app_client, serial_sessions, test_engine):
    made = await create(app_client, 2, seeds_per_problem=2)
    tid = made["session"]["id"]
    done = await until_state(app_client, tid, "finished", timeout=180)
    await stop(app_client, tid)
    again = (await app_client.post(f"/api/training-mode/sessions/{tid}/start")).json()
    assert again["memory_version"] == done["memory_version"] == 4
    config = serial_sessions._live[tid].config
    assert (config.version, config.revision) == (4, 0)
    assert config.config_hash == done["configuration"]["hash"]


@pytest.mark.asyncio
async def test_deleting_a_session_removes_its_live_part_and_configuration(
        app_client, sessions, test_engine):
    session = await create_with(app_client)
    tid, config_id = session["id"], session["configuration"]["id"]
    await app_client.post(f"/api/training-mode/sessions/{tid}/start")
    sessions.set_after_run(tid, _learner)
    assert store.live_state(tid) is not None
    assert (await app_client.delete(f"/api/training-mode/sessions/{tid}")).status_code == 204
    assert store.live_state(tid) is None and tid not in sessions._after_run
    async with factory_of(test_engine)() as db:
        with pytest.raises(configurations.UnknownConfiguration):
            await configurations.get_row(db, config_id)


@pytest.mark.asyncio
async def test_summary_run_and_list_fields(app_client, serial_sessions, test_engine):
    tables = reference_document().tables
    made = await create(app_client, 1, seeds_per_problem=2, start=False)
    tid = made["session"]["id"]
    stopped = made["session"]
    block = stopped["configuration"]
    assert set(block) == {"id", "version", "hash", "base_hash", "nodes", "links", "last_change_version", "frozen"}
    assert block["nodes"] == len(tables["slipnet_node_defs"]) and block["links"] == len(tables["slipnet_link_defs"])
    assert block["version"] == 0 and block["last_change_version"] is None and block["frozen"] is False
    assert block["hash"] == block["base_hash"] == stopped["config_hash"]
    listed = (await app_client.get("/api/training-mode/sessions")).json()
    assert listed["sessions"][0]["configuration"] == block
    await app_client.post(f"/api/training-mode/sessions/{tid}/start")
    await serial_sessions.submit_changes(tid, external(set_param(16)))
    done = await until_state(app_client, tid, "finished", timeout=120)
    live = done["configuration"]
    assert live["version"] == 1 and live["hash"] != block["hash"] and live["base_hash"] == block["base_hash"]
    assert live["last_change_version"] == 1 and done["config_hash"] == live["hash"]
    runs = (await app_client.get(f"/api/training-mode/sessions/{tid}/problems/{made['problem_ids'][0]}/runs")).json()["runs"]
    assert {r["configuration_revision"] for r in runs} == {1} and {r["config_hash"] for r in runs} == {live["hash"]}
    assert [r["episode_version"] for r in runs] == [r["memory_version"] for r in runs] == [1, 2]
    await stop(app_client, tid)
    assert (await session_state(app_client, tid))["source"] == "stored"
    runs = (await app_client.get(f"/api/training-mode/sessions/{tid}/problems/{made['problem_ids'][0]}/runs")).json()["runs"]
    assert {r["configuration_revision"] for r in runs} == {1}  # the run rows were stored with their revision
