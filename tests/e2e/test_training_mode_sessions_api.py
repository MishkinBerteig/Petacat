"""E2E tests for ``/api/training-mode/sessions`` -- many problems over many seeds, extendable while running.

A session's promise is the swarm's: every run is the serial run with that seed, started from
the Training Mode Session's Episodic Memory as of the run's ``memory_version``.  So the tests compare stored
runs against a replay of that memory rather than against remembered numbers, and they check
what is specific to sessions: every Training Mode Session has an Episodic Memory that no route clears; it
is created Stopped and started, paused, resumed, stopped and started again; a live session
writes nothing to the database until it is Stopped, a problem finishes exactly once with a
contiguous ``finished_seq``, problems can be added in any state but starting and stopping, and a
restart (after which every Training Mode Session is Stopped) reruns what was cut off to the identical result.

The scheduler is started by the application's lifespan, which the test client does not
run, so the ``training_mode_sessions`` fixture builds a ``TrainingModeSessionService`` on the test database and
installs it as the process-wide service for the duration of a test.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.models.training_mode_session import TrainingModeSession, SessionMemoryMerge, TrainingModeSessionProblem, TrainingModeSessionRun
from server.services import training_mode_session_service as bs
from server.services.training_mode_session_executor import create_executor

STEPS = 300


@pytest.fixture(scope="module", autouse=True)
def _stop_default_swarm():
    yield
    from server.parallel.swarm import shutdown_default

    shutdown_default()


def make_service(test_engine, meta, executor=None) -> bs.TrainingModeSessionService:
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    return bs.TrainingModeSessionService(factory, lambda: meta, executor=executor or create_executor())


@pytest.fixture
async def sessions(app_client, test_engine):
    """A running session service on the test database; every session row starts out gone."""
    from server.api.runs import get_run_service

    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM training_mode_sessions"))
    meta = get_run_service().meta
    service = make_service(test_engine, meta)
    await service.start()
    bs.set_training_mode_session_service(service)
    service.test_meta = meta
    service.test_engine = test_engine
    yield service
    bs.set_training_mode_session_service(None)
    await service.stop()


@pytest.fixture
async def serial_sessions(app_client, test_engine):
    """Like ``training_mode_sessions`` with one worker: each run starts after the previous one merged, so
    two Training Mode Sessions given the same problems produce identical runs."""
    from server.api.runs import get_run_service
    from server.services.training_mode_session_executor import SerialExecutor

    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM training_mode_sessions"))
    meta = get_run_service().meta
    service = make_service(test_engine, meta, executor=SerialExecutor())
    await service.start()
    bs.set_training_mode_session_service(service)
    service.test_meta = meta
    service.test_engine = test_engine
    yield service
    bs.set_training_mode_session_service(None)
    await service.stop()


def problem(i: int, **extra) -> dict:
    """Distinct small problems: ``abc -> abd`` with the target a window of the alphabet."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    if i < 24:
        target = letters[i:i + 3]
    else:
        target = letters[(i - 24):(i - 24) + 4]
    return {"initial": "abc", "modified": "abd", "target": target, **extra}


async def wait_for(predicate, timeout=60.0, interval=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(interval)
    raise AssertionError("timed out waiting for the condition")


async def session_state(client, bid: int) -> dict:
    return (await client.get(f"/api/training-mode/sessions/{bid}")).json()


def _is(b: dict, want: str) -> bool:
    """The Training Mode Session's state, or for ``idle`` / ``finished`` / ``stalled`` / ``running`` its
    activity inside Running (``finished`` is ``idle``: nothing is left to run)."""
    if want in ("stopped", "paused"):
        return b["state"] == want
    if want in ("idle", "finished"):
        return b["state"] == "running" and b["activity"] == "idle"
    if want == "stalled":
        return b["state"] == "running" and b["activity"] == "stalled"
    if want == "running":
        return b["state"] == "running" and b["activity"] is None
    raise AssertionError(want)


async def until_state(client, bid: int, state: str, timeout=90.0) -> dict:
    async def _p():
        b = await session_state(client, bid)
        return b if _is(b, state) else None

    return await wait_for(_p, timeout)


def _runs(b: dict) -> tuple:
    r = b["runs"]
    return (r["total"], r["done"], r["errors"])


async def create(client, n: int = 0, policy=None, name="test session", start=True, **settings) -> dict:
    """Create a Training Mode Session (Stopped) and, unless ``start`` is false, start it."""
    settings.setdefault("seeds_per_problem", 2)
    settings.setdefault("max_codelets", STEPS)
    settings.setdefault("configuration_base", "global")  # these tests mean the global configuration
    body = {"name": name, "settings": settings, "problems": [problem(i) for i in range(n)]}
    if policy is not None:
        body["policy"] = policy
    resp = await client.post("/api/training-mode/sessions", json=body)
    assert resp.status_code == 201, resp.text
    made = resp.json()
    assert made["session"]["state"] == "stopped"
    if start:
        started = await client.post(f"/api/training-mode/sessions/{made['session']['id']}/start")
        assert started.status_code == 200, started.text
        made["session"] = started.json()
    return made


async def stop(client, bid: int) -> dict:
    """Stop the session: the one write of a live session.  Returns the Stopped summary."""
    resp = await client.post(f"/api/training-mode/sessions/{bid}/stop")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def runs_of(client, bid: int, pid: int) -> list[dict]:
    return (await client.get(f"/api/training-mode/sessions/{bid}/problems/{pid}/runs")).json()["runs"]


async def stored_runs_replay(engine, meta, tid: int, codelets: int, backend: str) -> list:
    """Check every stored run of a Training Mode Session against a replay: the serial run with its seed,
    started from the Episodic Memory as of its ``memory_version`` rebuilt from the stored merges."""
    rows = await stored_runs(engine, tid)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    cache: dict[int, EpisodicMemory] = {}
    async with factory() as s:
        for version in sorted({r.memory_version for r, _ in rows}):
            cache[version] = await bs.TrainingModeSessionService.rebuild_memory(s, tid, upto=version)
    for r, p in rows:
        copy = tm.copy_for_run(cache[r.memory_version])
        status, answer, got, quality = replay(meta, copy, p, r.seed, codelets, backend)
        assert (r.status, r.answer, r.codelets, r.answer_quality) == (status, answer, got, quality), \
            (p.target, r.seed, r.memory_version)
    return rows


def run_key(r: dict) -> tuple:
    return (r["seed"], r["status"], r["answer"], r["codelets"], r["answer_quality"], r["temperature"])


async def db_count(engine, model, *where) -> int:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        return (await s.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


@pytest.mark.asyncio
async def test_every_stored_run_is_the_serial_run(app_client, sessions, test_engine):
    made = await create(app_client, 4, seeds_per_problem=3, seed_start=5)
    bid = made["session"]["id"]
    assert made["added"] == 4 and len(made["problem_ids"]) == 4
    done = await until_state(app_client, bid, "finished")
    assert done["problems"]["finished"] == 4 and _runs(done) == (12, 12, 0)
    backend = done["settings"]["backend"]
    assert backend in {"off", "numpy", "python", "mlx"}
    for pid in made["problem_ids"]:
        assert [r["seed"] for r in await runs_of(app_client, bid, pid)] == [5, 6, 7]
    assert await db_count(test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid) == 0
    await stop(app_client, bid)  # the Stop write stores the runs
    rows = await stored_runs_replay(test_engine, sessions.test_meta, bid, STEPS, backend)
    assert len(rows) == 12


@pytest.mark.asyncio
async def test_the_user_scenario_start_with_25_and_add_5_whenever_5_finish(app_client, serial_sessions):
    sessions = serial_sessions
    made = await create(app_client, 25)
    bid = made["session"]["id"]
    total, cursor, seen, unreplaced = 25, 0, [], 0
    started = time.monotonic()
    while total < 40:
        assert time.monotonic() - started < 120
        data = (await app_client.get(
            f"/api/training-mode/sessions/{bid}/finished", params={"after": cursor, "wait": 10})).json()
        cursor = data["cursor"]
        seen += [p["finished_seq"] for p in data["problems"]]
        unreplaced += len(data["problems"])
        while unreplaced >= 5 and total < 40:
            resp = await app_client.post(f"/api/training-mode/sessions/{bid}/problems", json={
                "problems": [problem(total + k) for k in range(5)]})
            assert resp.status_code == 201 and resp.json()["added"] == 5
            total += 5
            unreplaced -= 5
    done = await until_state(app_client, bid, "finished")
    assert done["problems"] == {"total": 40, "queued": 0, "running": 0, "finished": 40, "cancelled": 0}
    assert _runs(done) == (80, 80, 0)

    # Every problem finished exactly once, with a unique, contiguous finished_seq.
    tail = (await app_client.get(f"/api/training-mode/sessions/{bid}/finished", params={"after": cursor})).json()
    seen += [p["finished_seq"] for p in tail["problems"]]
    assert seen == list(range(1, 41))
    assert done["finished_cursor"] == 40
    listing = (await app_client.get(f"/api/training-mode/sessions/{bid}/problems", params={"limit": 100})).json()
    assert listing["total"] == 40
    assert sorted(p["finished_seq"] for p in listing["problems"]) == list(range(1, 41))
    assert {p["status"] for p in listing["problems"]} == {"finished"}
    assert await db_count(sessions.test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid) == 0
    await stop(app_client, bid)
    assert await db_count(sessions.test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid) == 80
    assert sorted(p["id"] for p in listing["problems"]) == list(range(1, 41))  # ordinals, live and stored alike

    # The same problems and seeds in another session give the identical runs.
    again = await create(app_client, 5)
    await until_state(app_client, again["session"]["id"], "finished")
    for pid_a, pid_b in zip(made["problem_ids"][:5], again["problem_ids"]):
        a = await runs_of(app_client, bid, pid_a)
        b = await runs_of(app_client, again["session"]["id"], pid_b)
        assert [run_key(r) for r in a] == [run_key(r) for r in b]


@pytest.mark.asyncio
async def test_long_poll_returns_when_a_problem_finishes_and_wait_zero_returns_at_once(app_client, sessions):
    made = await create(app_client, 0)
    bid = made["session"]["id"]
    t0 = time.monotonic()
    empty = (await app_client.get(f"/api/training-mode/sessions/{bid}/finished", params={"wait": 0})).json()
    assert empty == {"cursor": 0, "problems": []} and time.monotonic() - t0 < 1.0

    waiter = asyncio.create_task(
        app_client.get(f"/api/training-mode/sessions/{bid}/finished", params={"after": 0, "wait": 30}))
    await asyncio.sleep(0.3)
    assert not waiter.done()  # nothing to report yet: it is waiting
    t1 = time.monotonic()
    await app_client.post(f"/api/training-mode/sessions/{bid}/problems", json={"problems": [problem(0)]})
    data = (await waiter).json()
    assert time.monotonic() - t1 < 25
    assert [p["finished_seq"] for p in data["problems"]] == [1] and data["cursor"] == 1
    assert data["problems"][0]["status"] == "finished" and data["problems"][0]["runs_done"] == 2

    t2 = time.monotonic()
    timed = (await app_client.get(f"/api/training-mode/sessions/{bid}/finished", params={"after": 1, "wait": 1})).json()
    assert timed == {"cursor": 1, "problems": []} and 0.8 < time.monotonic() - t2 < 5


@pytest.mark.asyncio
async def test_start_pause_resume_stop_and_start_again(app_client, sessions):
    made = await create(app_client, 0, start=False)
    bid = made["session"]["id"]
    t = made["session"]
    assert t["state"] == "stopped" and t["activity"] is None and "status" not in t
    assert t["stopped_at"] is None and t["stopped_from"] is None and t["stop_reason"] is None
    # A Stopped Training Mode Session accepts problems, stores them, and runs nothing.
    resp = await app_client.post(f"/api/training-mode/sessions/{bid}/problems", json={"problems": [problem(0), problem(1)]})
    assert resp.status_code == 201 and resp.json()["session"]["state"] == "stopped"
    await asyncio.sleep(1.0)
    b = await session_state(app_client, bid)
    assert b["state"] == "stopped" and b["problems"]["queued"] == 2 and b["runs"]["done"] == 0
    # pause and resume need a live Training Mode Session.
    assert (await app_client.post(f"/api/training-mode/sessions/{bid}/pause")).status_code == 409
    assert (await app_client.post(f"/api/training-mode/sessions/{bid}/resume")).status_code == 409
    # Start, then pause: nothing is dispatched while it is paused.
    started = (await app_client.post(f"/api/training-mode/sessions/{bid}/start", json={"paused": True})).json()
    assert started["state"] == "paused"
    await app_client.post(f"/api/training-mode/sessions/{bid}/problems", json={"problems": [problem(2)]})
    await asyncio.sleep(1.5)  # a running scheduler would have started them by now
    b = await session_state(app_client, bid)
    assert b["state"] == "paused" and b["problems"]["queued"] == 3 and b["runs"]["done"] == 0
    assert (await app_client.post(f"/api/training-mode/sessions/{bid}/start")).json()["state"] == "paused"  # unchanged
    resumed = (await app_client.post(f"/api/training-mode/sessions/{bid}/resume")).json()
    assert resumed["state"] == "running"
    done = await until_state(app_client, bid, "idle")
    assert done["problems"]["finished"] == 3 and done["runs"]["done"] == 6
    # Stop: Stopped again, the memory kept, and the Training Mode Session starts again.
    stopped = (await app_client.post(f"/api/training-mode/sessions/{bid}/stop")).json()
    assert stopped["state"] == "stopped" and stopped["stopped_from"] == "running"
    assert stopped["stop_reason"] == "user" and stopped["stopped_at"]
    assert stopped["memory"] == done["memory"] and stopped["memory_version"] == done["memory_version"] == 6
    assert (await app_client.post(f"/api/training-mode/sessions/{bid}/stop")).json()["state"] == "stopped"
    assert "status" not in stopped and "closed_at" not in stopped
    resp = await app_client.post(f"/api/training-mode/sessions/{bid}/problems", json={"problems": [problem(3)]})
    assert resp.status_code == 201  # no state refuses problems
    again = (await app_client.post(f"/api/training-mode/sessions/{bid}/start")).json()
    assert again["state"] == "running" and again["memory_version"] >= 6
    done = await until_state(app_client, bid, "idle")
    assert done["problems"]["finished"] == 4 and done["memory_version"] == 8
    assert (await app_client.post(f"/api/training-mode/sessions/{bid}/pause")).json()["state"] == "paused"
    paused_stop = (await app_client.post(f"/api/training-mode/sessions/{bid}/stop")).json()
    assert paused_stop["stopped_from"] == "paused" and paused_stop["stop_reason"] == "user"
    # No state called closed or cancelled, and no close route.
    assert (await app_client.post(f"/api/training-mode/sessions/{bid}/close")).status_code in (404, 405)


async def partial_session(client, seeds=40000, extra=0) -> tuple[int, int]:
    """A session whose first problem is long, paused while it is mid-way."""
    body = {"name": "partial", "settings": {"seeds_per_problem": seeds, "max_codelets": STEPS,
                                            "configuration_base": "global"},
            "problems": [problem(0)] + [problem(1 + i) for i in range(extra)]}
    made = (await client.post("/api/training-mode/sessions", json=body)).json()
    await client.post(f"/api/training-mode/sessions/{made['session']['id']}/start")
    bid, pid = made["session"]["id"], made["problem_ids"][0]

    async def _midway():
        p = (await client.get(f"/api/training-mode/sessions/{bid}/problems/{pid}")).json()
        return p if p["runs_done"] >= 3 else None

    await wait_for(_midway)
    await client.post(f"/api/training-mode/sessions/{bid}/pause")
    return bid, pid


@pytest.mark.asyncio
async def test_a_live_session_holds_its_work_in_memory_until_stop(app_client, sessions):
    bid, pid = await partial_session(app_client)
    p = (await app_client.get(f"/api/training-mode/sessions/{bid}/problems/{pid}")).json()
    assert p["status"] == "running" and 0 < p["runs_done"] < 40000 and p["finished_seq"] is None
    assert p["top"] and p["started_at"]
    # Mid-way: progress is reported from memory, and nothing is in the database.
    assert await db_count(sessions.test_engine, TrainingModeSessionRun, TrainingModeSessionRun.problem_id == pid) == 0
    factory = async_sessionmaker(sessions.test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        row = await s.get(TrainingModeSessionProblem, (bid, pid))
        assert row.status == "queued" and row.runs_done == 0 and row.finished_seq is None
    mid_runs = await runs_of(app_client, bid, pid)
    assert len(mid_runs) >= 3  # served from memory while the problem runs
    b = await session_state(app_client, bid)
    assert b["problems"]["running"] == 1 and b["runs"]["done"] > 0
    assert b["persisted"] is False and b["source"] == "live"
    assert b["unsaved"]["runs"] == b["runs"]["done"] == b["unsaved"]["merges"]
    # Stop is the write: the runs are stored, and the problem stays queued with them.
    stopped = await stop(app_client, bid)
    assert await db_count(sessions.test_engine, TrainingModeSessionRun, TrainingModeSessionRun.problem_id == pid) == stopped["runs"]["done"]
    assert stopped["persisted"] is True and stopped["unsaved"] is None
    await app_client.post(f"/api/training-mode/sessions/{bid}/cancel")


@pytest.mark.asyncio
async def test_cancelling_a_problem_keeps_its_finished_runs_and_stores_them_at_stop(app_client, sessions):
    bid, pid = await partial_session(app_client, extra=2)
    await wait_for(lambda: _idle(sessions))
    before = (await app_client.get(f"/api/training-mode/sessions/{bid}/problems/{pid}")).json()["runs_done"]
    resp = await app_client.post(f"/api/training-mode/sessions/{bid}/problems/{pid}/cancel")
    assert resp.status_code == 200
    row = resp.json()
    assert row["status"] == "cancelled" and row["runs_done"] == before and row["finished_seq"] == 1
    assert await db_count(sessions.test_engine, TrainingModeSessionRun, TrainingModeSessionRun.problem_id == pid) == 0
    again = (await app_client.post(f"/api/training-mode/sessions/{bid}/problems/{pid}/cancel")).json()
    assert again["status"] == "cancelled"
    runs = await runs_of(app_client, bid, pid)
    assert [r["seed"] for r in runs] == list(range(1, before + 1))
    b = await session_state(app_client, bid)
    assert b["problems"]["cancelled"] == 1
    assert b["runs"]["total"] == 2 * 40000  # cancelled problems leave the totals
    await stop(app_client, bid)
    assert await db_count(sessions.test_engine, TrainingModeSessionRun, TrainingModeSessionRun.problem_id == pid) == before
    stored = (await app_client.get(f"/api/training-mode/sessions/{bid}/problems/{pid}")).json()
    assert stored["status"] == "cancelled" and stored["finished_seq"] == 1 and stored["runs_done"] == before
    assert [r["seed"] for r in await runs_of(app_client, bid, pid)] == list(range(1, before + 1))
    await app_client.post(f"/api/training-mode/sessions/{bid}/cancel")


async def _idle(service) -> bool:
    return service.executor.in_flight == 0


@pytest.mark.asyncio
async def test_cancel_is_an_action_and_delete_removes_everything(app_client, sessions):
    bid, pid = await partial_session(app_client, extra=5)
    await wait_for(lambda: _idle(sessions))
    done_runs = (await app_client.get(f"/api/training-mode/sessions/{bid}/problems/{pid}")).json()["runs_done"]
    cancelled = (await app_client.post(f"/api/training-mode/sessions/{bid}/cancel")).json()
    assert cancelled["state"] == "paused"  # cancel changes no state
    assert cancelled["problems"] == {"total": 6, "queued": 0, "running": 0, "finished": 0, "cancelled": 6}
    assert await db_count(sessions.test_engine, TrainingModeSessionRun, TrainingModeSessionRun.problem_id == pid) == 0  # live: memory only
    # It still accepts problems, and runs them once resumed.
    resp = await app_client.post(f"/api/training-mode/sessions/{bid}/problems", json={"problems": [problem(9)]})
    assert resp.status_code == 201
    await app_client.post(f"/api/training-mode/sessions/{bid}/resume")
    assert (await app_client.get(f"/api/training-mode/sessions/{bid}")).json()["state"] == "running"

    resp = await app_client.delete(f"/api/training-mode/sessions/{bid}")
    assert resp.status_code == 204
    assert (await app_client.get(f"/api/training-mode/sessions/{bid}")).status_code == 404
    assert bid not in sessions._live
    assert await db_count(sessions.test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid) == 0
    assert await db_count(sessions.test_engine, TrainingModeSessionProblem, TrainingModeSessionProblem.session_id == bid) == 0
    assert await db_count(sessions.test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == bid) == 0
    assert (await app_client.delete(f"/api/training-mode/sessions/{bid}")).status_code == 404

    # Deleting a running session settles it first and leaves nothing behind.
    made = await create(app_client, 10, seeds_per_problem=50)
    other = made["session"]["id"]
    assert (await app_client.delete(f"/api/training-mode/sessions/{other}")).status_code == 204
    await asyncio.sleep(0.5)
    assert await db_count(sessions.test_engine, TrainingModeSessionProblem, TrainingModeSessionProblem.session_id == other) == 0
    assert await db_count(sessions.test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == other) == 0
    assert await db_count(sessions.test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == other) == 0
    assert await db_count(sessions.test_engine, TrainingModeSession, TrainingModeSession.id == other) == 0

    # So does deleting a Stopped one (its stored memory goes with it).
    made = await create(app_client, 3)
    stopped_id = made["session"]["id"]
    await until_state(app_client, stopped_id, "idle")
    await app_client.post(f"/api/training-mode/sessions/{stopped_id}/stop")
    assert await db_count(sessions.test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == stopped_id) == 6
    assert (await app_client.delete(f"/api/training-mode/sessions/{stopped_id}")).status_code == 204
    assert await db_count(sessions.test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == stopped_id) == 0
    assert await db_count(sessions.test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == stopped_id) == 0


@pytest.mark.asyncio
async def test_a_restart_reruns_what_was_cut_off_to_the_identical_result(app_client, serial_sessions, test_engine):
    sessions = serial_sessions
    n = 24
    made = await create(app_client, n, seeds_per_problem=4, max_codelets=1500)
    bid = made["session"]["id"]

    async def _some():
        return (await session_state(app_client, bid))["finished_cursor"] >= 2

    await wait_for(_some)
    await sessions.stop()  # the server goes down mid-way
    mid = await session_state_via_db(test_engine, bid)
    assert 2 <= mid["finished"] < n and mid["queued"] > 0

    from server.services.training_mode_session_executor import SerialExecutor

    second = make_service(test_engine, sessions.test_meta, executor=SerialExecutor())
    await second.start()
    bs.set_training_mode_session_service(second)
    try:
        # After a restart every Training Mode Session is Stopped; the shutdown is on the record.
        b = await session_state(app_client, bid)
        assert b["state"] == "stopped" and b["stopped_from"] == "running" and b["stop_reason"] == "shutdown"
        assert b["problems"]["finished"] == mid["finished"]
        await app_client.post(f"/api/training-mode/sessions/{bid}/start")
        done = await until_state(app_client, bid, "finished", timeout=180)
        assert done["problems"]["finished"] == n and _runs(done) == (n * 4, n * 4, 0)
        await stop(app_client, bid)
        assert await db_count(test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid) == n * 4  # no duplicates
        cursor = (await app_client.get(f"/api/training-mode/sessions/{bid}/finished", params={"limit": 1000})).json()
        assert sorted(p["finished_seq"] for p in cursor["problems"]) == list(range(1, n + 1))

        # An uninterrupted session of the same problems gives identical runs.
        clean = await create(app_client, n, seeds_per_problem=4, max_codelets=1500)
        cid = clean["session"]["id"]
        await until_state(app_client, cid, "finished", timeout=180)
        for pa, pb in zip(made["problem_ids"], clean["problem_ids"]):
            assert [run_key(r) for r in await runs_of(app_client, bid, pa)] == \
                   [run_key(r) for r in await runs_of(app_client, cid, pb)]
    finally:
        bs.set_training_mode_session_service(sessions)
        await second.stop()


@pytest.mark.asyncio
async def test_stop_then_start_resumes_from_what_the_stop_wrote(app_client, serial_sessions, test_engine):
    """Stop keeps every run and merge committed in memory (even mid-problem); start continues
    from them, and the whole equals an uninterrupted Training Mode Session."""
    sessions = serial_sessions
    made = await create(app_client, 6, seeds_per_problem=6, max_codelets=1500)
    bid = made["session"]["id"]

    async def _midway():
        b = await session_state(app_client, bid)
        return b if b["runs"]["done"] >= 8 and b["problems"]["running"] == 1 else None

    await wait_for(_midway)
    await app_client.post(f"/api/training-mode/sessions/{bid}/pause")
    stopped = (await app_client.post(f"/api/training-mode/sessions/{bid}/stop")).json()
    assert stopped["state"] == "stopped" and stopped["stopped_from"] == "paused"
    assert stopped["runs"]["done"] >= 8 and stopped["memory_version"] == stopped["runs"]["done"]
    assert stopped["problems"]["running"] == 0  # nothing runs while Stopped
    stored = await db_count(test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid)
    assert stored == stopped["runs"]["done"]  # the Stop wrote the runs of the unfinished problem
    assert await db_count(test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == bid) == stored
    await app_client.post(f"/api/training-mode/sessions/{bid}/start")
    done = await until_state(app_client, bid, "finished", timeout=180)
    assert _runs(done) == (36, 36, 0) and done["memory_version"] == 36
    await stored_runs_replay(test_engine, sessions.test_meta, bid, 1500, done["settings"]["backend"])
    clean = await create(app_client, 6, seeds_per_problem=6, max_codelets=1500)
    await until_state(app_client, clean["session"]["id"], "finished", timeout=180)
    for pa, pb in zip(made["problem_ids"], clean["problem_ids"]):
        assert [run_key(r) for r in await runs_of(app_client, bid, pa)] == \
               [run_key(r) for r in await runs_of(app_client, clean["session"]["id"], pb)]


async def session_state_via_db(engine, bid: int) -> dict:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        rows = (await s.execute(
            select(TrainingModeSessionProblem.status, func.count()).where(TrainingModeSessionProblem.session_id == bid)
            .group_by(TrainingModeSessionProblem.status))).all()
    return {status: n for status, n in rows}


def _external(*ops, **extra) -> dict:
    """A change batch as the external route submits it."""
    return {"source": "external", "actor": "test", "ops": list(ops), **extra}


@pytest.mark.asyncio
async def test_a_configuration_that_cannot_start_a_run_stalls_the_session_and_resumes(
        app_client, sessions):
    """With ``on_config_change`` gone nothing pauses or adopts: a session stalls only while its own
    configuration cannot start a run (the run-start check), and carries on when a change restores it.
    The change is a batch to the live session, held in memory."""
    made = await create(app_client, 1, seeds_per_problem=60000)
    tid = made["session"]["id"]
    table = sessions._live[tid].config.document.tables["engine_params"]
    row = dict(table[("update_cycle_length",)])
    report = await sessions.submit_changes(tid, _external(
        {"op": "delete", "table": "engine_params", "key": {"name": "update_cycle_length"}}))
    assert report["persisted"] is False and report["effects"], report
    stalled = await until_state(app_client, tid, "stalled")
    assert "update_cycle_length" in stalled["stalled_reason"] and "stalled" in stalled["last_event"]
    done_while_stalled = stalled["runs"]["done"]
    await asyncio.sleep(0.5)
    assert (await session_state(app_client, tid))["runs"]["done"] == done_while_stalled
    # The configuration is repaired: the stalled session carries on (the scheduler's own timer notices).
    row.pop("id", None)
    await sessions.submit_changes(tid, _external({"op": "insert", "table": "engine_params", "row": row}))
    resumed = await until_state(app_client, tid, "running", timeout=30)
    assert resumed["stalled_reason"] is None and resumed["last_event"].startswith("resumed")
    await app_client.post(f"/api/training-mode/sessions/{tid}/cancel")


@pytest.mark.asyncio
async def test_listing_filtering_and_the_executor_report(app_client, sessions):
    made = await create(app_client, 6)
    bid = made["session"]["id"]
    await until_state(app_client, bid, "finished")
    top = (await app_client.get("/api/training-mode/sessions")).json()
    assert top["sessions"][0]["id"] == bid
    assert top["executor"]["kind"] in ("swarm", "serial") and top["executor"]["workers"] >= 1
    assert top["limits"] == {"max_problems_per_request": 10000, "max_seeds_per_problem": 100000, "max_codelets": 200000}
    q = (await app_client.get(f"/api/training-mode/sessions/{bid}/problems", params={"q": "efg"})).json()
    assert q["total"] == 1 and q["problems"][0]["target"] == "efg"
    s = (await app_client.get(f"/api/training-mode/sessions/{bid}/problems",
                              params={"sort": "finished_seq", "order": "desc", "limit": 2})).json()
    assert s["total"] == 6 and [p["finished_seq"] for p in s["problems"]] == [6, 5]
    assert (await app_client.get(f"/api/training-mode/sessions/{bid}/problems", params={"status": "queued"})).json()["total"] == 0
    detail = (await app_client.get(f"/api/training-mode/sessions/{bid}/problems/{made['problem_ids'][0]}")).json()
    assert sum(d["count"] for d in detail["distribution"]) == 2 and detail["first_error"] is None
    assert abs(sum(d["fraction"] for d in detail["distribution"]) - 1) < 1e-9


@pytest.mark.asyncio
async def test_tag_justification_and_per_problem_seeds(app_client, sessions):
    body = {"name": "tags", "settings": {"seeds_per_problem": 2, "max_codelets": STEPS,
                                         "configuration_base": "global"}, "problems": [
        {**problem(0), "answer": "abd", "tag": {"job": 7}, "seeds": 3}, problem(1)]}
    made = (await app_client.post("/api/training-mode/sessions", json=body)).json()
    bid = made["session"]["id"]
    await app_client.post(f"/api/training-mode/sessions/{bid}/start")
    await until_state(app_client, bid, "finished")
    p0 = (await app_client.get(f"/api/training-mode/sessions/{bid}/problems/{made['problem_ids'][0]}")).json()
    assert p0["tag"] == {"job": 7} and p0["answer"] == "abd" and p0["seeds"] == 3 and p0["runs_done"] == 3
    p1 = (await app_client.get(f"/api/training-mode/sessions/{bid}/problems/{made['problem_ids'][1]}")).json()
    assert p1["seeds"] == 2 and p1["tag"] is None and p1["answer"] is None


@pytest.mark.asyncio
async def test_validation_errors(app_client, sessions):
    post = app_client.post
    ok = problem(0)
    for bad in (
        {"problems": [{**ok, "initial": ""}]},
        {"problems": [{**ok, "target": ""}]},
        {"problems": [{**ok, "answer": ""}]},          # an answer is null (discovery) or non-empty
        {"problems": [{**ok, "initial": "a\x00b"}]},    # U+0000 cannot be stored as text
        {"problems": [{**ok, "seeds": 0}]},
        {"problems": [{**ok, "seeds": 100001}]},
        {"problems": [ok] * 10001},
        {"problems": [{"initial": "abc"}]},
        {"settings": {"seeds_per_problem": 0}},
        {"settings": {"seeds_per_problem": 100001}},
        {"settings": {"max_codelets": 200001}},
        {"settings": {"max_codelets": 0}},
        {"settings": {"memory": "shared"}},       # memory is not a setting: every Training Mode Session has an Episodic Memory
        {"settings": {"memory": "independent"}},
        {"memory": "independent"},
        {"memory": "shared"},
        {"settings": {"nonsense": 1}},
        {"name": ""},
        {"name": "a\x00b"},                          # U+0000 cannot be stored as text
        {},
    ):
        bad = {"name": "v", **bad} if "name" not in bad and bad != {} else bad
        resp = await post("/api/training-mode/sessions", json=bad)
        assert resp.status_code == 422, (bad if len(str(bad)) < 200 else "big", resp.text)
        assert isinstance(resp.json()["detail"], str)
    # A lone surrogate is not UTF-8 text; httpx's own ``json=`` cannot even send one, so it goes as escapes.
    resp = await post("/api/training-mode/sessions", content='{"name": "v", "problems": [{"initial": "a", "modified": "b", "target": "c", "answer": "\\ud800"}]}', headers={"Content-Type": "application/json"})
    assert resp.status_code == 422 and "answer" in resp.json()["detail"], resp.text
    for bad in (
        {"settings": {"parameters": {"no_such_parameter": 1}}},
        {"settings": {"backend": "no-such-backend"}},
        {"policy": {"on_run_error": "explode"}},
        {"policy": {"no_such_field": 1}},
        {"policy": {"max_retries": -1}},
        {"policy": {"max_errors_total": 0}},
    ):
        resp = await post("/api/training-mode/sessions", json={"name": "v", **bad})
        assert resp.status_code == 400 and isinstance(resp.json()["detail"], str)
    made = await create(app_client, 1)
    bid = made["session"]["id"]
    assert (await post(f"/api/training-mode/sessions/{bid}/problems", json={"problems": [{**ok, "initial": ""}]})).status_code == 422
    assert (await app_client.get(f"/api/training-mode/sessions/{bid}/problems", params={"limit": 5000})).status_code == 422
    assert (await app_client.get(f"/api/training-mode/sessions/{bid}/problems", params={"sort": "bogus"})).status_code == 422
    assert (await app_client.get(f"/api/training-mode/sessions/{bid}/finished", params={"wait": 61})).status_code == 422
    for path in ("", "/problems", "/finished", "/export"):
        assert (await app_client.get(f"/api/training-mode/sessions/987654{path}")).status_code == 404
    assert (await app_client.get(f"/api/training-mode/sessions/{bid}/problems/987654")).status_code == 404
    assert (await app_client.get(f"/api/training-mode/sessions/{bid}/problems/987654/runs")).status_code == 404
    assert (await post(f"/api/training-mode/sessions/{bid}/problems/987654/cancel")).status_code == 404
    for action in ("start", "pause", "resume", "stop", "cancel"):
        assert (await post(f"/api/training-mode/sessions/987654/{action}")).status_code == 404
    assert (await post("/api/training-mode/sessions/987654/problems", json={"problems": []})).status_code == 404
    await post(f"/api/training-mode/sessions/{bid}/cancel")
    assert (await post(f"/api/training-mode/sessions/{bid}/problems", json={"problems": [ok]})).status_code == 201  # no state refuses problems
    # A problem of another session is not found through this one (identifiers are per-session ordinals).
    other = await create(app_client, 4)
    assert (await app_client.get(f"/api/training-mode/sessions/{bid}/problems/{other['problem_ids'][3]}")).status_code == 404


@pytest.mark.asyncio
async def test_parameters_and_backend_are_stored_and_used(app_client, sessions):
    made = await create(app_client, 1, backend="off", parameters=None)
    assert made["session"]["settings"]["backend"] == "off"
    made2 = await create(app_client, 0)
    assert made2["session"]["settings"]["backend"]  # resolved at creation, never null
    assert made2["session"]["config_hash"]


@pytest.mark.asyncio
async def test_export_csv_and_json(app_client, sessions):
    made = await create(app_client, 3)
    bid = made["session"]["id"]
    await until_state(app_client, bid, "finished")

    r = await app_client.get(f"/api/training-mode/sessions/{bid}/export", params={"what": "problems", "format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == f'attachment; filename="session-{bid}-problems.csv"'
    lines = r.text.strip().split("\n")
    assert lines[0].startswith("id,initial,modified,target") and len(lines) == 4

    r = await app_client.get(f"/api/training-mode/sessions/{bid}/export", params={"what": "runs", "format": "csv"})
    lines = r.text.strip().split("\n")
    assert r.headers["content-disposition"] == f'attachment; filename="session-{bid}-runs.csv"'
    assert lines[0].startswith("problem_id,initial,modified,target,problem_answer,seed") and len(lines) == 1 + 6
    seeds = [(int(l.split(",")[0]), int(l.split(",")[5])) for l in lines[1:]]
    assert seeds == sorted(seeds)  # problem, then seed order

    r = await app_client.get(f"/api/training-mode/sessions/{bid}/export", params={"what": "runs", "format": "json"})
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert r.headers["content-disposition"].endswith('.ndjson"')
    rows = [json.loads(l) for l in r.text.strip().split("\n")]
    assert len(rows) == 6 and {"problem_id", "seed", "status", "answer", "codelets"} <= set(rows[0])

    r = await app_client.get(f"/api/training-mode/sessions/{bid}/export", params={"what": "problems", "format": "json"})
    assert r.headers["content-type"].startswith("application/json")
    data = r.json()
    assert len(data) == 3 and data[0]["status"] == "finished"

    r = await app_client.get(f"/api/training-mode/sessions/{bid}/export", params={"what": "distribution", "format": "csv"})
    lines = r.text.strip().split("\n")
    assert lines[0].startswith("problem_id,initial,modified,target,answer_key,count") and len(lines) >= 4
    r = await app_client.get(f"/api/training-mode/sessions/{bid}/export", params={"what": "distribution", "format": "json"})
    assert sum(d["count"] for d in r.json()) == 6

    empty = await create(app_client, 0)
    r = await app_client.get(f"/api/training-mode/sessions/{empty['session']['id']}/export", params={"what": "runs", "format": "csv"})
    assert r.status_code == 200 and len(r.text.strip().split("\n")) == 1
    r = await app_client.get(f"/api/training-mode/sessions/{empty['session']['id']}/export", params={"what": "problems", "format": "json"})
    assert r.json() == []


@pytest.mark.asyncio
async def test_sessions_share_the_cores_fairly(app_client, sessions):
    """A small session added after a huge one still finishes soon (round-robin across sessions)."""
    huge = await create(app_client, 1, seeds_per_problem=60000)
    small = await create(app_client, 2)
    sid = small["session"]["id"]
    done = await until_state(app_client, sid, "finished", timeout=60)
    assert done["runs"]["done"] == 4
    await app_client.delete(f"/api/training-mode/sessions/{huge['session']['id']}")


# ---------------------------------------------------------------------------
# The Episodic Memory, the error policy, the configuration policy
# ---------------------------------------------------------------------------

from server.engine.memory import EpisodicMemory  # noqa: E402
from server.engine.numeric.backend import use_backend  # noqa: E402
from server.engine.runner import EngineRunner  # noqa: E402
from server.services import training_mode_session_memory as tm  # noqa: E402
from server.services.training_mode_session_executor import SerialExecutor  # noqa: E402

SHARED_PROBLEMS = [("abc", "abd", "xyz"), ("abc", "abd", "ijk"), ("abc", "abd", "mrrjjj")]


async def create_shared(client, seeds=5, codelets=2500, problems=SHARED_PROBLEMS, **extra) -> dict:
    body = {"name": "episode", "settings": {"seeds_per_problem": seeds, "max_codelets": codelets,
                                            "configuration_base": "global"},
            "problems": [{"initial": i, "modified": m, "target": t} for i, m, t in problems], **extra}
    resp = await client.post("/api/training-mode/sessions", json=body)
    assert resp.status_code == 201, resp.text
    made = resp.json()
    await client.post(f"/api/training-mode/sessions/{made['session']['id']}/start")
    return made


async def stored_runs(engine, tid: int) -> list:
    """Every run of a Training Mode Session with its problem, in merge order."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        rows = (await s.execute(
            select(TrainingModeSessionRun, TrainingModeSessionProblem)
            .join(TrainingModeSessionProblem,
                  (TrainingModeSessionProblem.session_id == TrainingModeSessionRun.session_id)
                  & (TrainingModeSessionProblem.problem_id == TrainingModeSessionRun.problem_id))
            .where(TrainingModeSessionRun.session_id == tid).order_by(TrainingModeSessionRun.seq))).all()
    return [(r, p) for r, p in rows]


def replay(meta, memory, problem, seed, codelets, backend):
    """The reference: one run started from *memory* (a copy of it), as any run is."""
    base = len(memory.answers)
    runner = EngineRunner(meta)
    with use_backend(backend):
        runner.init_mcat(problem.initial, problem.modified, problem.target, problem.answer,
                         seed=seed, memory=memory)
        runner.run_mcat(max_steps=codelets)
    quality = float(memory.answers[0].quality) if len(memory.answers) > base else None
    ans = runner.ctx.workspace.answer_string
    return runner.status, (ans.text if ans else ""), runner.ctx.codelet_count, quality


@pytest.mark.asyncio
async def test_one_worker_is_a_serial_episode(app_client, sessions, test_engine):
    """One worker: each run starts after the previous merged, which is Metacat's serial
    episode -- the runs, in merge order, equal one memory object carried run to run."""
    serial = make_service(test_engine, sessions.test_meta, executor=SerialExecutor())
    await serial.start()
    bs.set_training_mode_session_service(serial)
    try:
        made = await create_shared(app_client, seeds=4)
        tid = made["session"]["id"]
        done = await until_state(app_client, tid, "finished", timeout=180)
        assert done["problems"]["finished"] == 3 and done["memory_version"] == 12
        live_fingerprint = tm.memory_fingerprint(serial.live_memory(tid))
        await stop(app_client, tid)
        rows = await stored_runs(test_engine, tid)
        assert [r.seq for r, _ in rows] == list(range(1, 13))
        assert [r.memory_version for r, _ in rows] == list(range(0, 12))  # each saw all before it
        reference = EpisodicMemory()
        backend = done["settings"]["backend"]
        for r, p in rows:
            status, answer, codelets, quality = replay(sessions.test_meta, reference, p, r.seed, 2500, backend)
            assert (r.status, r.answer, r.codelets, r.answer_quality) == (status, answer, codelets, quality)
        assert live_fingerprint == tm.memory_fingerprint(reference)
        assert done["memory"] == {"answers": len(reference.answers), "snags": len(reference.snags)}
        assert any(r.added_answers for r, _ in rows)
    finally:
        bs.set_training_mode_session_service(sessions)
        await serial.stop()


@pytest.mark.asyncio
async def test_many_workers_replay_from_the_merge_log(app_client, sessions, test_engine):
    """Whatever the interleaving, a run is reproduced by the memory as of its version,
    rebuilt from the stored merges alone."""
    made = await create_shared(app_client, seeds=6)
    tid = made["session"]["id"]
    done = await until_state(app_client, tid, "finished", timeout=180)
    n = done["runs"]["done"]
    assert n == 18 and done["memory_version"] == n
    mem = sessions.live_memory(tid)
    await stop(app_client, tid)
    rows = await stored_runs(test_engine, tid)
    assert [r.seq for r, _ in rows] == list(range(1, n + 1))
    assert all(0 <= r.memory_version < r.seq for r, _ in rows)
    backend = done["settings"]["backend"]
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    cache: dict[int, EpisodicMemory] = {}
    async with factory() as s:
        for version in sorted({r.memory_version for r, _ in rows}):
            cache[version] = await bs.TrainingModeSessionService.rebuild_memory(s, tid, upto=version)
    for r, p in rows:
        copy = tm.copy_for_run(cache[r.memory_version])
        status, answer, codelets, quality = replay(sessions.test_meta, copy, p, r.seed, 2500, backend)
        assert (r.status, r.answer, r.codelets, r.answer_quality) == (status, answer, codelets, quality), \
            (p.target, r.seed, r.memory_version)
    # The episode never holds the same description twice.
    keys = [(tuple(a.problem), repr(a.top_rule_signature), repr(a.bottom_rule_signature)) for a in mem.answers]
    assert len(keys) == len(set(keys))
    assert len(mem.answers) == sum(r.added_answers for r, _ in rows)
    assert len(mem.snags) == sum(r.added_snags for r, _ in rows)
    # Merges are stored once each, in order.
    assert await db_count(test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == tid) == n


@pytest.mark.asyncio
async def test_a_restart_rebuilds_the_memory_exactly(app_client, sessions, test_engine):
    made = await create_shared(app_client, seeds=4)
    tid = made["session"]["id"]
    await until_state(app_client, tid, "finished", timeout=180)
    before = tm.memory_fingerprint(sessions.live_memory(tid))
    summary = await session_state(app_client, tid)
    await sessions.stop()
    second = make_service(test_engine, sessions.test_meta)
    await second.start()
    bs.set_training_mode_session_service(second)
    try:
        # Stopped after the restart: the memory is the stored one, served and counted from the database.
        assert second.live_memory(tid) is None
        stopped = await session_state(app_client, tid)
        assert stopped["state"] == "stopped"
        assert stopped["memory_version"] == summary["memory_version"] and stopped["memory"] == summary["memory"]
        assert stopped["runs"] == summary["runs"]
        stored = (await app_client.get(f"/api/training-mode/sessions/{tid}/memory")).json()
        assert len(stored["answers"]) == summary["memory"]["answers"]
        # Started, it is rebuilt from the stored merges exactly.
        await app_client.post(f"/api/training-mode/sessions/{tid}/start")
        assert tm.memory_fingerprint(second.live_memory(tid)) == before
        again = await session_state(app_client, tid)
        assert again["memory_version"] == summary["memory_version"] and again["memory"] == summary["memory"]
        listing = (await app_client.get(f"/api/training-mode/sessions/{tid}/memory")).json()
        assert len(listing["answers"]) == summary["memory"]["answers"]
    finally:
        bs.set_training_mode_session_service(sessions)
        await second.stop()


@pytest.mark.asyncio
async def test_the_memory_endpoint_serves_the_api_memory_shape(app_client, sessions):
    made = await create_shared(app_client, seeds=4, problems=SHARED_PROBLEMS[:1])
    tid = made["session"]["id"]
    await until_state(app_client, tid, "finished", timeout=120)
    mem = (await app_client.get(f"/api/training-mode/sessions/{tid}/memory")).json()
    assert mem["answers"]
    assert {"problem", "quality", "temperature", "top_rule_description", "bottom_rule_description"} <= set(mem["answers"][0])
    ids = [a["answer_id"] for a in mem["answers"]]
    assert ids == sorted(ids, reverse=True)  # newest first
    if mem["snags"]:
        assert {"problem", "codelet_count", "temperature", "description", "explanation"} <= set(mem["snags"][0])
    fresh = await create(app_client, 0, start=False)  # every Training Mode Session has one, empty at first
    assert (await app_client.get(f"/api/training-mode/sessions/{fresh['session']['id']}/memory")).json() == {"answers": [], "snags": []}
    assert fresh["session"]["memory"] == {"answers": 0, "snags": 0} and fresh["session"]["memory_version"] == 0
    assert (await app_client.get("/api/training-mode/sessions/987654/memory")).status_code == 404


@pytest.mark.asyncio
async def test_no_route_clears_a_sessions_memory_and_memory_is_refused(app_client, sessions):
    made = await create_shared(app_client, seeds=4, problems=SHARED_PROBLEMS[:1])
    tid = made["session"]["id"]
    done = await until_state(app_client, tid, "finished", timeout=120)
    before = (await app_client.get(f"/api/training-mode/sessions/{tid}/memory")).json()
    assert before["answers"] and done["memory"]["answers"] == len(before["answers"])
    for method in ("delete", "post", "put", "patch"):
        resp = await getattr(app_client, method)(f"/api/training-mode/sessions/{tid}/memory")
        assert resp.status_code in (404, 405), (method, resp.status_code)
    for action in ("clear", "reset", "memory/clear"):
        assert (await app_client.post(f"/api/training-mode/sessions/{tid}/{action}")).status_code in (404, 405)
    # Metacat Mode's clear route takes no Training Mode Session argument and does not touch it.
    await app_client.delete("/api/memory")
    # Neither does stopping, starting again or cancelling.
    await app_client.post(f"/api/training-mode/sessions/{tid}/cancel")
    await app_client.post(f"/api/training-mode/sessions/{tid}/stop")
    await app_client.post(f"/api/training-mode/sessions/{tid}/start")
    after = (await app_client.get(f"/api/training-mode/sessions/{tid}/memory")).json()
    assert after == before
    # A request that sends memory is refused (422) and creates nothing.
    count = len((await app_client.get("/api/training-mode/sessions")).json()["sessions"])
    for body in ({"name": "m", "memory": "independent"}, {"name": "m", "settings": {"memory": "independent"}}):
        resp = await app_client.post("/api/training-mode/sessions", json=body)
        assert resp.status_code == 422 and isinstance(resp.json()["detail"], str)
    assert len((await app_client.get("/api/training-mode/sessions")).json()["sessions"]) == count
    # Only deleting the whole Training Mode Session removes its memory.
    assert (await app_client.delete(f"/api/training-mode/sessions/{tid}")).status_code == 204
    assert (await app_client.get(f"/api/training-mode/sessions/{tid}/memory")).status_code == 404
    assert await db_count(sessions.test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == tid) == 0


@pytest.mark.asyncio
async def test_defaults_patch_and_settings_are_fixed(app_client, sessions):
    top = (await app_client.get("/api/training-mode/sessions")).json()
    d = top["defaults"]
    assert "memory" not in d["settings"] and d["settings"]["seeds_per_problem"] == 100
    assert d["settings"]["max_codelets"] == 20000 and d["settings"]["backend"]
    assert d["policy"] == {"on_run_error": "record", "max_errors_per_problem": None,
                           "max_errors_total": None, "on_worker_failure": "retry", "max_retries": 3}
    made = (await app_client.post("/api/training-mode/sessions", json={"name": "bare"})).json()  # all defaults
    t = made["session"]
    assert "memory" not in t["settings"] and t["policy"] == d["policy"] and t["name"] == "bare"
    assert t["state"] == "stopped" and t["memory"] == {"answers": 0, "snags": 0}
    tid = t["id"]
    patched = (await app_client.patch(f"/api/training-mode/sessions/{tid}", json={
        "name": "renamed", "note": "n", "policy": {"max_errors_total": 5}})).json()
    assert patched["name"] == "renamed" and patched["note"] == "n"
    assert patched["policy"]["max_errors_total"] == 5 and patched["policy"]["on_run_error"] == "record"
    assert (await app_client.patch(f"/api/training-mode/sessions/{tid}", json={"settings": {"seeds_per_problem": 1}})).status_code == 422
    assert (await app_client.patch(f"/api/training-mode/sessions/{tid}", json={"memory": "independent"})).status_code == 422
    assert (await app_client.patch(f"/api/training-mode/sessions/{tid}", json={"policy": {"on_run_error": "x"}})).status_code == 400
    assert (await app_client.patch(f"/api/training-mode/sessions/{tid}", json={"name": ""})).status_code == 422
    assert (await app_client.patch("/api/training-mode/sessions/987654", json={"name": "x"})).status_code == 404
    assert (await session_state(app_client, tid))["name"] == "renamed"


def fault_on(sessions, fn):
    sessions.fault_hook = fn


@pytest.mark.asyncio
async def test_policy_record_keeps_the_error_and_carries_on(app_client, sessions):
    fault_on(sessions, lambda lp, seed, failures: "error" if seed == 2 else None)
    made = await create(app_client, 1, seeds_per_problem=3, policy={"on_run_error": "record"})
    tid, pid = made["session"]["id"], made["problem_ids"][0]
    done = await until_state(app_client, tid, "finished")
    assert done["runs"]["errors"] == 1 and done["runs"]["done"] == 3 and done["state"] == "running"
    runs = await runs_of(app_client, tid, pid)
    bad = [r for r in runs if r["seed"] == 2][0]
    assert bad["key"] == "*ERROR*" and bad["status"] == "error" and "injected fault" in bad["error"]
    detail = (await app_client.get(f"/api/training-mode/sessions/{tid}/problems/{pid}")).json()
    assert detail["errors"] == 1 and "injected fault" in detail["first_error"]
    assert {d["answer"] for d in detail["distribution"]} >= {"*ERROR*"}


@pytest.mark.asyncio
async def test_policy_skip_problem_pause_and_cancel(app_client, sessions):
    fault_on(sessions, lambda lp, seed, failures: "error" if lp.initial == "abc" and lp.target == "abc" and seed == 1 else None)
    # skip_problem: the failing problem is cancelled, the other finishes.
    made = await create(app_client, 2, seeds_per_problem=40, policy={"on_run_error": "skip_problem"})
    tid = made["session"]["id"]
    done = await until_state(app_client, tid, "finished", timeout=120)
    assert done["problems"]["cancelled"] == 1 and done["problems"]["finished"] == 1
    assert "skip_problem" in done["last_event"]
    # pause: the Training Mode Session pauses with an event.
    made = await create(app_client, 1, seeds_per_problem=200, policy={"on_run_error": "pause"})
    tid = made["session"]["id"]
    paused = await until_state(app_client, tid, "paused")
    assert paused["state"] == "paused" and "on_run_error = pause" in paused["last_event"]
    # cancel: every problem is cancelled; cancel is an action, so the Training Mode Session stays running.
    made = await create(app_client, 1, seeds_per_problem=200, policy={"on_run_error": "cancel"})
    tid = made["session"]["id"]

    async def _cancelled():
        b = await session_state(app_client, tid)
        return b if b["problems"]["cancelled"] == 1 else None

    cancelled = await wait_for(_cancelled)
    assert "on_run_error = cancel" in cancelled["last_event"] and cancelled["state"] == "running"


@pytest.mark.asyncio
async def test_policy_error_limits(app_client, sessions):
    fault_on(sessions, lambda lp, seed, failures: "error" if lp.target == "abc" else None)
    made = await create(app_client, 1, seeds_per_problem=60, policy={"max_errors_per_problem": 3})
    tid, pid = made["session"]["id"], made["problem_ids"][0]
    async def _cancelled():
        p = (await app_client.get(f"/api/training-mode/sessions/{tid}/problems/{pid}")).json()
        return p if p["status"] == "cancelled" else None
    p = await wait_for(_cancelled)
    assert p["errors"] >= 3 and "max_errors_per_problem" in (await session_state(app_client, tid))["last_event"]

    made = await create(app_client, 1, seeds_per_problem=60, policy={"max_errors_total": 2})
    paused = await until_state(app_client, made["session"]["id"], "paused")
    assert "max_errors_total" in paused["last_event"]
    # The pause is effective at once and its runs are persisted right after it, so under
    # load the persisted error count can trail the pause by a moment.
    async def _errors_persisted():
        b = await session_state(app_client, made["session"]["id"])
        return b if b["runs"]["errors"] >= 2 else None
    await wait_for(_errors_persisted)
    await app_client.post(f"/api/training-mode/sessions/{made['session']['id']}/cancel")


@pytest.mark.asyncio
async def test_policy_worker_failure_retries_exactly_then_pauses(app_client, sessions, test_engine):
    # A worker is killed on the first attempt of one run: the run is retried and is exact.
    fault_on(sessions, lambda lp, seed, failures: "kill" if seed == 2 and failures == 0 else None)
    made = await create(app_client, 2, seeds_per_problem=3)
    tid = made["session"]["id"]
    done = await until_state(app_client, tid, "finished", timeout=120)
    assert done["runs"]["done"] == 6 and done["runs"]["errors"] == 0 and done["runs"]["retries"] >= 2
    backend = done["settings"]["backend"]
    await stop(app_client, tid)
    await stored_runs_replay(test_engine, sessions.test_meta, tid, STEPS, backend)  # the retry is exact
    for pid in made["problem_ids"]:
        assert [r["attempts"] for r in await runs_of(app_client, tid, pid)][1] >= 2

    # Always failing: after max_retries the Training Mode Session pauses, the run is not lost, and a fix + resume finishes it.
    fault_on(sessions, lambda lp, seed, failures: "kill" if seed == 1 else None)
    made = await create(app_client, 1, seeds_per_problem=2, policy={"max_retries": 1})
    tid = made["session"]["id"]
    paused = await until_state(app_client, tid, "paused", timeout=120)
    assert "max_retries" in paused["last_event"]
    fault_on(sessions, None)
    await app_client.post(f"/api/training-mode/sessions/{tid}/resume")
    done = await until_state(app_client, tid, "finished", timeout=120)
    assert done["runs"]["done"] == 2 and done["runs"]["errors"] == 0

    # on_worker_failure = pause: pause at once.
    fault_on(sessions, lambda lp, seed, failures: "kill" if seed == 1 and failures == 0 else None)
    made = await create(app_client, 1, seeds_per_problem=2, policy={"on_worker_failure": "pause"})
    paused = await until_state(app_client, made["session"]["id"], "paused", timeout=120)
    assert "on_worker_failure = pause" in paused["last_event"]


@pytest.mark.asyncio
async def test_a_killed_serial_child_is_retried(app_client, sessions, test_engine):
    serial = make_service(test_engine, sessions.test_meta, executor=SerialExecutor())
    await serial.start()
    bs.set_training_mode_session_service(serial)
    serial.fault_hook = lambda lp, seed, failures: "kill" if seed == 1 and failures == 0 else None
    try:
        made = await create(app_client, 1, seeds_per_problem=2)
        done = await until_state(app_client, made["session"]["id"], "finished", timeout=120)
        assert done["runs"]["done"] == 2 and done["runs"]["retries"] >= 1 and done["runs"]["errors"] == 0
    finally:
        bs.set_training_mode_session_service(sessions)
        await serial.stop()


@pytest.mark.asyncio
async def test_on_config_change_is_gone_and_a_run_records_the_configuration_it_ran_under(
        app_client, sessions):
    """No policy field decides what a configuration change does (config plan 3.9).  Nothing pauses
    or adopts: the next run simply starts under the session's configuration as it then stands and
    records its hash, its configuration revision and its episode version."""
    for body in ({"on_config_change": "adopt"}, {"on_config_change": "pause"}):
        resp = await app_client.post("/api/training-mode/sessions", json={"name": "x", "policy": body})
        assert resp.status_code == 400 and "on_config_change" in resp.json()["detail"]
    made = await create(app_client, 1, seeds_per_problem=60000)
    tid, pid = made["session"]["id"], made["problem_ids"][0]
    assert "on_config_change" not in made["session"]["policy"]
    first_hash = made["session"]["configuration"]["hash"]
    await app_client.post(f"/api/training-mode/sessions/{tid}/pause")
    await asyncio.sleep(0.5)
    await sessions.submit_changes(tid, _external({"op": "set_param", "name": "update_cycle_length", "to": 16}))
    await app_client.post(f"/api/training-mode/sessions/{tid}/resume")

    async def _both():
        seen = {(r["config_hash"], r["configuration_revision"]) for r in await runs_of(app_client, tid, pid)}
        return seen if len({h for h, _ in seen}) == 2 else None

    seen = await wait_for(_both)
    now = await session_state(app_client, tid)
    assert {h for h, _ in seen} == {first_hash, now["configuration"]["hash"]}
    assert {rev for _, rev in seen} == {0, 1}
    assert now["state"] == "running" and now["activity"] is None  # it never paused or stalled
    await app_client.post(f"/api/training-mode/sessions/{tid}/cancel")


# ---------------------------------------------------------------------------
# Review fixes: seed range, a policy pause is not lost, isolating a culprit, live counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_ranges_must_fit_the_database(app_client, sessions):
    post = app_client.post
    ok = problem(0)
    for settings in (
        {"seed_start": 3_000_000_000},
        {"seed_start": -1},
        {"seed_start": 2_147_483_600, "seeds_per_problem": 100},
    ):
        resp = await post("/api/training-mode/sessions", json={"name": "r", "settings": settings})
        assert resp.status_code == 422 and isinstance(resp.json()["detail"], str), settings
    resp = await post("/api/training-mode/sessions", json={
        "name": "r", "settings": {"seed_start": 2_147_483_600, "seeds_per_problem": 2},
        "problems": [{**ok, "seeds": 100}]})
    assert resp.status_code == 422
    made = await create(app_client, 0, seed_start=2_147_483_600, seeds_per_problem=2)
    tid = made["session"]["id"]
    assert (await post(f"/api/training-mode/sessions/{tid}/problems", json={"problems": [{**ok, "seeds": 100}]})).status_code == 422
    assert (await post(f"/api/training-mode/sessions/{tid}/problems", json={"problems": [{**ok, "seeds": 2}]})).status_code == 201
    await app_client.post(f"/api/training-mode/sessions/{tid}/cancel")


@pytest.mark.asyncio
async def test_a_policy_pause_is_not_lost_to_a_user_change(app_client, sessions, test_engine):
    made = await create(app_client, 1, seeds_per_problem=60000)
    tid = made["session"]["id"]
    lt = sessions._live[tid]
    await wait_for(lambda: _started(lt))
    sessions._trigger_pause(lt, "paused: injected policy pause")
    summary = await sessions.update(tid, note="edited")  # a user change right after the policy's pause
    assert summary["state"] == "paused" and lt.status == "paused" and summary["note"] == "edited"
    assert summary["last_event"] == "paused: injected policy pause"
    assert summary["unsaved"]["edits"] == 1 and summary["persisted"] is False
    # Nothing is dispatched while it is paused.
    await wait_for(lambda: _drained(lt))
    done_before = (await session_state(app_client, tid))["runs"]["done"]
    await asyncio.sleep(0.5)
    assert (await session_state(app_client, tid))["runs"]["done"] == done_before
    resumed = await sessions.resume(tid)
    assert resumed["state"] == "running" and lt.status == "running"
    # Both survive a Stop: the event and the edit are written with it.
    await app_client.post(f"/api/training-mode/sessions/{tid}/pause")
    stopped = await stop(app_client, tid)
    assert stopped["note"] == "edited" and stopped["last_event"] == "paused: injected policy pause"
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        row = await s.get(TrainingModeSession, tid)
        assert row.note == "edited" and row.last_event == "paused: injected policy pause"
    await app_client.post(f"/api/training-mode/sessions/{tid}/cancel")


async def _drained(lt) -> bool:
    """No run in flight and every finished one merged (a run leaves ``inflight_subs`` as it merges)."""
    return not lt.inflight_subs


async def _started(lt) -> bool:
    return any(lp.started for lp in lt.active.values())


@pytest.mark.asyncio
async def test_only_the_culprit_is_charged_when_a_run_breaks_the_pool(app_client, sessions, test_engine):
    culprit = problem(0)["target"]
    fault_on(sessions, lambda lp, seed, failures: "kill" if lp.target == culprit and seed == 2 else None)
    made = await create(app_client, 2, seeds_per_problem=24, policy={"max_retries": 1})
    tid, culprit_pid = made["session"]["id"], made["problem_ids"][0]
    paused = await until_state(app_client, tid, "paused", timeout=180)
    assert f"problem {culprit_pid} seed 2" in paused["last_event"] and "max_retries" in paused["last_event"]
    assert paused["runs"]["retries"] == 0  # innocent runs carry no attempts but their own
    for pid in made["problem_ids"]:
        runs = await runs_of(app_client, tid, pid)
        assert all(r["attempts"] == 1 for r in runs), [(r["seed"], r["attempts"]) for r in runs if r["attempts"] != 1]
        assert 2 not in [r["seed"] for r in runs if pid == culprit_pid]
    # Without the fault the rest completes, and the culprit's run is exact.
    fault_on(sessions, None)
    await app_client.post(f"/api/training-mode/sessions/{tid}/resume")
    done = await until_state(app_client, tid, "finished", timeout=180)
    assert done["runs"]["done"] == 48 and done["runs"]["errors"] == 0
    await stop(app_client, tid)
    await stored_runs_replay(test_engine, sessions.test_meta, tid, STEPS, done["settings"]["backend"])  # the culprit's run is exact


@pytest.mark.asyncio
async def test_live_counts_never_step_backwards(app_client, sessions):
    made = await create(app_client, 30, seeds_per_problem=4)
    tid = made["session"]["id"]
    last = (0, 0, 0)
    for _ in range(150):
        t = await session_state(app_client, tid)
        now = (t["runs"]["done"], t["problems"]["finished"], t["codelets"])
        assert all(n >= o for n, o in zip(now, last)), (last, now)
        assert t["problems"]["total"] == 30 and t["runs"]["total"] == 120
        last = now
        if t["problems"]["finished"] == 30:
            break
        await asyncio.sleep(0.03)
    done = await until_state(app_client, tid, "idle")
    assert done["runs"]["done"] == 120


# ---------------------------------------------------------------------------
# S13: deferred writes, the live side of the Stopped rule
# ---------------------------------------------------------------------------

from sqlalchemy import event  # noqa: E402


class Recorder:
    """Records every statement and every commit the test engine sees while ``on`` is set."""

    def __init__(self, engine) -> None:
        self.on = False
        self.statements: list[str] = []
        self.commits = 0
        self._sync = engine.sync_engine
        event.listen(self._sync, "before_cursor_execute", self._statement)
        event.listen(self._sync, "commit", self._commit)

    def _statement(self, conn, cursor, statement, parameters, context, executemany) -> None:
        if self.on:
            self.statements.append(statement.strip())

    def _commit(self, conn) -> None:
        if self.on:
            self.commits += 1

    def reset(self) -> None:
        self.statements.clear()
        self.commits = 0

    def writes(self) -> list[str]:
        return [x for x in self.statements if x.split(None, 1)[0].upper() not in ("SELECT", "WITH")]

    def close(self) -> None:
        event.remove(self._sync, "before_cursor_execute", self._statement)
        event.remove(self._sync, "commit", self._commit)


@pytest.fixture
def recorder(test_engine):
    rec = Recorder(test_engine)
    yield rec
    rec.close()


def _api(bid: int, tail: str = "") -> str:
    return f"/api/training-mode/sessions/{bid}{tail}"


@pytest.mark.asyncio
async def test_a_live_session_issues_no_database_write_until_stop(app_client, sessions, recorder):
    """The user's decision: a session only writes to the database when it is Stopped.  No statement
    but a read is issued by a live session, and the scheduler's own work issues none at all."""
    made = await create(app_client, 6, seeds_per_problem=3)  # created (a write) and started (reads)
    bid = made["session"]["id"]
    lt = sessions._live[bid]
    recorder.reset()
    recorder.on = True

    # The hot path -- dispatch, merge, problem completion, the finished cursor -- touches nothing.
    async def _idle_in_memory():
        return sessions._live_summary(lt)["activity"] == "idle"

    await wait_for(_idle_in_memory)
    assert recorder.statements == [] and recorder.commits == 0

    # Every API use of a live session: reads, and every mutation.
    get = app_client.get
    for path, params in (
        ("", None), ("/problems", None), ("/problems", {"q": "abc", "status": "finished", "sort": "top_fraction"}),
        (f"/problems/{made['problem_ids'][0]}", None), (f"/problems/{made['problem_ids'][0]}/runs", None),
        ("/finished", {"after": 0}), ("/memory", None),
        ("/export", {"what": "problems", "format": "csv"}), ("/export", {"what": "runs", "format": "json"}),
        ("/export", {"what": "distribution", "format": "json"}),
    ):
        resp = await get(_api(bid, path), params=params)
        assert resp.status_code == 200, (path, resp.text)
    assert (await get("/api/training-mode/sessions")).status_code == 200
    post, patch = app_client.post, app_client.patch
    # Paused BEFORE the problems are added: a running session dispatches an added problem at once, and
    # whether its three runs have finished by the time of the cancel below is a race (a finished problem's
    # cancel is a no-op that keeps its runs: 24 runs unsaved instead of 21; a problem cut off mid-way keeps
    # the runs that had finished).  Paused, the first added problem is still queued when it is cancelled.
    assert (await post(_api(bid, "/pause"))).status_code == 200
    added = await post(_api(bid, "/problems"), json={"problems": [problem(10), problem(11)]})
    assert added.status_code == 201 and added.json()["persisted"] is False
    assert (await patch(_api(bid), json={"name": "live name", "note": "live note", "policy": {"max_retries": 7}})).status_code == 200
    assert (await post(_api(bid, f"/problems/{added.json()['problem_ids'][0]}/cancel"))).status_code == 200
    assert (await post(_api(bid, "/resume"))).status_code == 200
    await until_state(app_client, bid, "idle")
    assert (await post(_api(bid, "/start"))).status_code == 200  # already live: unchanged
    assert (await post(_api(bid, "/cancel"))).status_code == 200
    assert recorder.writes() == [] and recorder.commits == 0, recorder.writes()
    assert recorder.statements and all(x.upper().startswith("SELECT") for x in recorder.statements)

    # Nothing of it is stored yet ...
    recorder.on = False
    assert await db_count(sessions.test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid) == 0
    assert await db_count(sessions.test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == bid) == 0
    live = await session_state(app_client, bid)
    assert live["unsaved"]["runs"] == 21 and live["unsaved"]["merges"] == 21 and live["unsaved"]["edits"] == 1  # 7 problems of 3 seeds

    # ... and Stop writes all of it in ONE transaction.
    recorder.reset()
    recorder.on = True
    stopped = await stop(app_client, bid)
    recorder.on = False
    assert recorder.commits == 1, recorder.commits
    kinds = {x.split(None, 1)[0].upper() for x in recorder.writes()}
    assert kinds == {"INSERT", "UPDATE"}
    assert await db_count(sessions.test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid) == 21
    assert await db_count(sessions.test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == bid) == 21
    assert stopped["name"] == "live name" and stopped["note"] == "live note" and stopped["policy"]["max_retries"] == 7
    assert stopped["persisted"] is True and stopped["unsaved"] is None and stopped["source"] == "stored"
    assert stopped["problems"]["total"] == 8 and stopped["runs"]["done"] == 21


@pytest.mark.asyncio
async def test_a_stopped_session_is_a_record_written_at_once(app_client, sessions, test_engine):
    made = await create(app_client, 0, start=False)
    bid = made["session"]["id"]
    assert made["persisted"] is True and made["session"]["persisted"] is True and made["session"]["source"] == "stored"
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def row():
        async with factory() as s:
            return await s.get(TrainingModeSession, bid)

    patched = await app_client.patch(_api(bid), json={"name": "stopped name", "policy": {"max_retries": 9}})
    assert patched.json()["persisted"] is True
    assert (await row()).name == "stopped name" and (await row()).policy["max_retries"] == 9
    added = (await app_client.post(_api(bid, "/problems"), json={"problems": [problem(0), problem(1)]})).json()
    assert added["persisted"] is True and added["problem_ids"] == [1, 2]
    assert await db_count(test_engine, TrainingModeSessionProblem, TrainingModeSessionProblem.session_id == bid) == 2
    assert (await row()).next_problem_id == 3
    cancelled = (await app_client.post(_api(bid, "/problems/1/cancel"))).json()
    assert cancelled["status"] == "cancelled"
    async with factory() as s:
        assert (await s.get(TrainingModeSessionProblem, (bid, 1))).status == "cancelled"
    # The same edits to a live session are in memory only until it is stopped.
    await app_client.post(_api(bid, "/start"), json={"paused": True})
    live = (await app_client.patch(_api(bid), json={"name": "live name"})).json()
    assert live["persisted"] is False and live["source"] == "live" and live["name"] == "live name"
    assert (await row()).name == "stopped name"
    assert (await app_client.post(_api(bid, "/problems"), json={"problems": [problem(2)]})).json()["problem_ids"] == [3]
    assert (await row()).next_problem_id == 3
    await stop(app_client, bid)
    assert (await row()).name == "live name" and (await row()).next_problem_id == 4


@pytest.mark.asyncio
async def test_live_summaries_carry_persisted_saved_through_and_unsaved(app_client, sessions):
    made = await create(app_client, 3, seeds_per_problem=2, start=False)
    bid = made["session"]["id"]
    s0 = made["session"]
    assert s0["persisted"] is True and s0["unsaved"] is None
    assert s0["saved_through"] == {"stopped_at": None, "configuration_revision": 0, "episode_version": 0}
    started = (await app_client.post(_api(bid, "/start"))).json()
    assert started["source"] == "live" and started["persisted"] is False
    assert started["unsaved"] == {"runs": 0, "merges": 0, "problems": 0, "outcomes": 0, "edits": 0,
                                  "configuration_batches": 0}
    done = await until_state(app_client, bid, "idle")
    assert done["unsaved"]["runs"] == 6 and done["unsaved"]["merges"] == 6 and done["unsaved"]["outcomes"] == 3
    assert done["saved_through"]["episode_version"] == 0 and done["saved_through"]["stopped_at"] is None
    added = (await app_client.post(_api(bid, "/problems"), json={"problems": [problem(5)]})).json()
    assert added["persisted"] is False and added["session"]["persisted"] is False
    assert added["session"]["unsaved"]["problems"] == 1
    stopped = await stop(app_client, bid)
    assert stopped["saved_through"]["episode_version"] == stopped["memory_version"] == 6
    assert stopped["saved_through"]["stopped_at"] == stopped["stopped_at"]
    again = (await app_client.post(_api(bid, "/start"))).json()
    assert again["saved_through"]["episode_version"] == 6 and again["saved_through"]["stopped_at"]
    assert again["unsaved"]["runs"] == 0
    listing = (await app_client.get("/api/training-mode/sessions")).json()["sessions"]
    row = next(t for t in listing if t["id"] == bid)
    assert row["source"] == "live" and row["persisted"] is False
    await stop(app_client, bid)


BUSY_REQUESTS = (
    ("post", "/problems", {"problems": [problem(0)]}),
    ("patch", "", {"name": "x"}),
    ("post", "/pause", None),
    ("post", "/resume", None),
    ("post", "/cancel", None),
    ("post", "/problems/1/cancel", None),
    ("delete", "", None),
)


async def assert_busy(client, bid: int, also: tuple[str, ...]) -> None:
    for method, tail, body in BUSY_REQUESTS:
        kwargs = {"json": body} if body is not None else {}
        resp = await getattr(client, method)(_api(bid, tail), **kwargs)
        assert resp.status_code == 409 and resp.json()["detail"].startswith("busy"), (method, tail, resp.text)
    for action in also:
        resp = await client.post(_api(bid, f"/{action}"))
        assert resp.status_code == 409 and resp.json()["detail"].startswith("busy"), (action, resp.text)
    # Reads are never refused.
    for tail in ("", "/problems", "/finished", "/memory", "/problems/1", "/problems/1/runs"):
        assert (await client.get(_api(bid, tail))).status_code == 200, tail


@pytest.mark.asyncio
async def test_starting_refuses_every_mutation_with_busy_and_ends_running(app_client, sessions, monkeypatch):
    made = await create(app_client, 2, start=False)
    bid = made["session"]["id"]
    entered, gate = asyncio.Event(), asyncio.Event()
    real = sessions._load_one

    async def slow_load(s, t):
        entered.set()
        await gate.wait()
        return await real(s, t)

    monkeypatch.setattr(sessions, "_load_one", slow_load)
    starter = asyncio.create_task(app_client.post(_api(bid, "/start")))
    await asyncio.wait_for(entered.wait(), 30)
    state = await session_state(app_client, bid)
    assert state["state"] == "starting" and state["activity"] is None
    listed = (await app_client.get("/api/training-mode/sessions")).json()["sessions"]
    assert next(t for t in listed if t["id"] == bid)["state"] == "starting"
    await assert_busy(app_client, bid, also=("start", "stop"))
    assert bid not in sessions._live
    gate.set()
    resp = await starter
    assert resp.status_code == 200 and resp.json()["state"] == "running"
    assert (await session_state(app_client, bid))["state"] in ("running",)
    await until_state(app_client, bid, "idle")


@pytest.mark.asyncio
async def test_stopping_refuses_every_mutation_with_busy_and_reads_come_from_memory(app_client, sessions, monkeypatch):
    made = await create(app_client, 2, seeds_per_problem=2)
    bid = made["session"]["id"]
    await until_state(app_client, bid, "idle")
    entered, gate = asyncio.Event(), asyncio.Event()
    real = sessions._write_stop

    async def slow_write(lt, **kwargs):
        entered.set()
        await gate.wait()
        return await real(lt, **kwargs)

    monkeypatch.setattr(sessions, "_write_stop", slow_write)
    stopper = asyncio.create_task(app_client.post(_api(bid, "/stop")))
    await asyncio.wait_for(entered.wait(), 30)
    state = await session_state(app_client, bid)
    assert state["state"] == "stopping" and state["activity"] is None and state["source"] == "live"
    assert state["runs"]["done"] == 4 and state["persisted"] is False
    await assert_busy(app_client, bid, also=("start", "stop"))
    gate.set()
    resp = await stopper
    assert resp.status_code == 200 and resp.json()["state"] == "stopped"
    assert resp.json()["runs"]["done"] == 4


@pytest.mark.asyncio
async def test_a_failed_start_leaves_the_session_stopped_and_it_can_start_again(app_client, sessions, test_engine, monkeypatch):
    made = await create(app_client, 2, start=False)
    bid = made["session"]["id"]
    before = await session_state(app_client, bid)
    real = sessions._load_one

    async def failing_load(s, t):
        raise RuntimeError("injected load failure")

    monkeypatch.setattr(sessions, "_load_one", failing_load)
    resp = await app_client.post(_api(bid, "/start"))
    assert resp.status_code == 500 and "still Stopped" in resp.json()["detail"]
    assert bid not in sessions._live and bid not in sessions._starting
    after = await session_state(app_client, bid)
    assert after == before and after["state"] == "stopped"
    assert (await app_client.post(_api(bid, "/problems"), json={"problems": [problem(5)]})).status_code == 201
    monkeypatch.setattr(sessions, "_load_one", real)
    assert (await app_client.post(_api(bid, "/start"))).json()["state"] == "running"
    done = await until_state(app_client, bid, "idle")
    assert done["problems"]["finished"] == 3


@pytest.mark.asyncio
async def test_a_failed_stop_returns_to_paused_with_the_memory_intact_and_may_be_retried(
        app_client, sessions, test_engine, monkeypatch):
    made = await create(app_client, 4, seeds_per_problem=3)
    bid = made["session"]["id"]
    done = await until_state(app_client, bid, "idle")
    lt = sessions._live[bid]
    fingerprint = tm.memory_fingerprint(lt.memory)
    unsaved = dict(done["unsaved"])
    real = sessions._write_stop

    async def failing_write(lt_, **kwargs):
        raise RuntimeError("injected write failure")

    monkeypatch.setattr(sessions, "_write_stop", failing_write)
    resp = await app_client.post(_api(bid, "/stop"))
    assert resp.status_code == 500 and "Paused" in resp.json()["detail"]
    paused = await session_state(app_client, bid)
    assert paused["state"] == "paused" and paused["source"] == "live"
    assert "stop failed" in paused["last_event"] and "injected write failure" in paused["last_event"]
    assert paused["unsaved"] == unsaved and paused["runs"]["done"] == 12
    assert sessions._live[bid] is lt and tm.memory_fingerprint(lt.memory) == fingerprint
    assert await db_count(test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid) == 0
    assert await db_count(test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == bid) == 0
    assert (await session_state(app_client, bid))["stopped_at"] is None
    # Everything still works in memory: add a problem, resume, finish it.
    assert (await app_client.post(_api(bid, "/problems"), json={"problems": [problem(9)]})).status_code == 201
    await app_client.post(_api(bid, "/resume"))
    await until_state(app_client, bid, "idle")
    # The retry succeeds and writes everything, including what happened after the failure.
    monkeypatch.setattr(sessions, "_write_stop", real)
    stopped = await stop(app_client, bid)
    assert stopped["state"] == "stopped" and stopped["stopped_from"] == "running" and stopped["stop_reason"] == "user"
    assert stopped["runs"]["done"] == 15 and stopped["problems"]["finished"] == 5
    assert await db_count(test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid) == 15
    assert await db_count(test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == bid) == 15


@pytest.mark.asyncio
async def test_stop_discards_the_runs_still_in_flight_and_their_seeds_run_again(app_client, serial_sessions, test_engine):
    sessions = serial_sessions
    sessions.drain_timeout = 0.0  # nothing is waited for: whatever is in flight is discarded
    made = await create(app_client, 1, seeds_per_problem=30, max_codelets=1500)
    bid = made["session"]["id"]

    async def _some():
        return (await session_state(app_client, bid))["runs"]["done"] >= 3

    await wait_for(_some)
    stopped = await stop(app_client, bid)
    stored = await db_count(test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid)
    merges = await db_count(test_engine, SessionMemoryMerge, SessionMemoryMerge.session_id == bid)
    assert stored == merges == stopped["runs"]["done"] == stopped["memory_version"] and 3 <= stored < 30
    assert sessions._inflight_runs >= 0
    await app_client.post(_api(bid, "/start"))
    done = await until_state(app_client, bid, "idle", timeout=180)
    assert done["runs"]["done"] == 30 and done["memory_version"] == 30
    assert [r["seed"] for r in await runs_of(app_client, bid, 1)] == list(range(1, 31))
    # The whole equals an uninterrupted serial session.
    clean = await create(app_client, 1, seeds_per_problem=30, max_codelets=1500)
    await until_state(app_client, clean["session"]["id"], "idle", timeout=180)
    assert [run_key(r) for r in await runs_of(app_client, bid, 1)] == \
           [run_key(r) for r in await runs_of(app_client, clean["session"]["id"], 1)]


@pytest.mark.asyncio
async def test_stop_waits_for_runs_in_flight_up_to_the_drain_timeout(app_client, serial_sessions, test_engine):
    sessions = serial_sessions
    sessions.drain_timeout = 60.0
    made = await create(app_client, 1, seeds_per_problem=40, max_codelets=1500)
    bid = made["session"]["id"]

    async def _flying():
        return sessions._live[bid].inflight_subs and (await session_state(app_client, bid))["runs"]["done"] >= 2

    await wait_for(_flying)
    stopped = await stop(app_client, bid)
    # The run in flight finished and merged before the write: every merged run is stored.
    stored = await db_count(test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid)
    assert stored == stopped["runs"]["done"] == stopped["memory_version"]
    assert not sessions._live and sessions._inflight_runs == 0


@pytest.mark.asyncio
async def test_a_graceful_shutdown_stops_every_live_session(app_client, test_engine):
    from server.api.runs import get_run_service

    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM training_mode_sessions"))
    meta = get_run_service().meta
    service = make_service(test_engine, meta)
    await service.start()
    bs.set_training_mode_session_service(service)
    try:
        running = await create(app_client, 3, seeds_per_problem=40)
        paused = await create(app_client, 2, seeds_per_problem=2)
        await app_client.post(_api(paused["session"]["id"], "/pause"))
        idle = await create(app_client, 1, seeds_per_problem=1)
        await until_state(app_client, idle["session"]["id"], "idle")
        resting = await create(app_client, 1, start=False)
        await service.stop()
        assert not service._live
        with pytest.raises(bs.SessionError) as refused:  # a Start during shutdown is refused
            await service.start_session(resting["session"]["id"])
        assert refused.value.status == 409 and refused.value.detail.startswith("busy")
    finally:
        bs.set_training_mode_session_service(None)
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        rows = {t.id: t for t in (await s.execute(select(TrainingModeSession))).scalars()}
        for made, from_ in ((running, "running"), (paused, "paused"), (idle, "running")):
            row = rows[made["session"]["id"]]
            assert row.stop_reason == "shutdown" and row.stopped_from == from_ and row.stopped_at
        assert rows[resting["session"]["id"]].stopped_at is None  # never live: not touched
        for made in (running, paused, idle):
            sid = made["session"]["id"]
            runs = (await s.execute(select(func.count()).select_from(TrainingModeSessionRun)
                                    .where(TrainingModeSessionRun.session_id == sid))).scalar_one()
            merges = (await s.execute(select(func.count()).select_from(SessionMemoryMerge)
                                      .where(SessionMemoryMerge.session_id == sid))).scalar_one()
            assert runs == merges
    # Whatever was running starts again after the restart, from what the Stop stored.
    second = make_service(test_engine, meta)
    await second.start()
    bs.set_training_mode_session_service(second)
    try:
        sid = paused["session"]["id"]
        assert (await session_state(app_client, sid))["state"] == "stopped"
        await app_client.post(_api(sid, "/start"))
        done = await until_state(app_client, sid, "idle")
        assert done["problems"]["finished"] == 2 and done["runs"]["done"] == 4
    finally:
        bs.set_training_mode_session_service(None)
        await second.stop()


@pytest.mark.asyncio
async def test_a_shutdown_that_cannot_finish_abandons_the_session_to_its_last_stop(app_client, test_engine, monkeypatch, caplog):
    from server.api.runs import get_run_service

    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM training_mode_sessions"))
    service = make_service(test_engine, get_run_service().meta)
    await service.start()
    bs.set_training_mode_session_service(service)
    try:
        made = await create(app_client, 2, seeds_per_problem=2)
        bid = made["session"]["id"]
        await until_state(app_client, bid, "idle")

        async def hang(lt, **kwargs):
            await asyncio.Event().wait()

        monkeypatch.setattr(service, "_write_stop", hang)
        service.shutdown_stop_timeout = 0.5
        started = time.monotonic()
        with caplog.at_level("ERROR", logger="petacat.session"):
            await service.stop()
        assert time.monotonic() - started < 20
        assert any(f"session {bid} was not stopped" in r.message and "runs" in r.message for r in caplog.records)
    finally:
        bs.set_training_mode_session_service(None)
    assert await db_count(test_engine, TrainingModeSessionRun, TrainingModeSessionRun.session_id == bid) == 0
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        assert (await s.get(TrainingModeSession, bid)).stopped_at is None  # as if the process had died


@pytest.mark.asyncio
async def test_problem_ids_are_per_session_ordinals_the_same_live_and_stored(app_client, sessions, test_engine):
    a = await create(app_client, 3, start=False, seeds_per_problem=2)
    b = await create(app_client, 2, start=False, seeds_per_problem=2)
    assert a["problem_ids"] == [1, 2, 3] and b["problem_ids"] == [1, 2]  # (session, ordinal) is the key
    aid, bid = a["session"]["id"], b["session"]["id"]
    await app_client.post(_api(aid, "/start"))
    live_add = (await app_client.post(_api(aid, "/problems"), json={"problems": [problem(3), problem(4)]})).json()
    assert live_add["problem_ids"] == [4, 5]  # handed out in memory, before any row exists
    assert await db_count(test_engine, TrainingModeSessionProblem, TrainingModeSessionProblem.session_id == aid) == 3
    await until_state(app_client, aid, "idle")
    live_view = {p["id"]: p for p in (await app_client.get(_api(aid, "/problems"))).json()["problems"]}
    live_runs = {pid: await runs_of(app_client, aid, pid) for pid in range(1, 6)}
    assert sorted(live_view) == [1, 2, 3, 4, 5]
    await stop(app_client, aid)
    stored_view = {p["id"]: p for p in (await app_client.get(_api(aid, "/problems"))).json()["problems"]}
    assert stored_view == live_view  # the same identifiers, the same rows
    for pid in range(1, 6):
        assert await runs_of(app_client, aid, pid) == live_runs[pid]
    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        keys = (await s.execute(select(TrainingModeSessionProblem.session_id, TrainingModeSessionProblem.problem_id))).all()
        assert len(keys) == len(set(keys)) == 7
        assert (await s.get(TrainingModeSession, aid)).next_problem_id == 6
    # The numbering goes on across Stops, in both directions of adding.
    assert (await app_client.post(_api(aid, "/problems"), json={"problems": [problem(5)]})).json()["problem_ids"] == [6]
    await app_client.post(_api(aid, "/start"))
    assert (await app_client.post(_api(aid, "/problems"), json={"problems": [problem(6)]})).json()["problem_ids"] == [7]
    # A problem of another session is not found through this one.
    assert (await app_client.get(_api(bid, "/problems/3"))).status_code == 404
    assert (await app_client.get(_api(bid, "/problems/2"))).status_code == 200
    await app_client.post(_api(aid, "/cancel"))


def _comparable(summary: dict) -> dict:
    keep = ("id", "name", "note", "settings", "policy", "config_hash", "problems", "runs", "memory",
            "codelets", "memory_version", "finished_cursor", "created_at")
    return {k: summary[k] for k in keep}


@pytest.mark.asyncio
async def test_live_summaries_problems_and_runs_equal_the_stored_ones(app_client, serial_sessions):
    """What a live session reports from memory is what the database reports after the Stop."""
    made = await create(app_client, 6, seeds_per_problem=3, max_codelets=1500)
    bid = made["session"]["id"]
    await until_state(app_client, bid, "idle")
    await app_client.post(_api(bid, "/pause"))
    extra = (await app_client.post(_api(bid, "/problems"), json={"problems": [problem(10), problem(11), problem(12)]})).json()
    await app_client.post(_api(bid, f"/problems/{extra['problem_ids'][2]}/cancel"))  # queued, never run: cancelled
    await app_client.post(_api(bid, f"/problems/{made['problem_ids'][0]}/cancel"))  # already finished: unchanged
    live = {
        "summary": _comparable(await session_state(app_client, bid)),
        "list": (await app_client.get(_api(bid, "/problems"), params={"limit": 1000})).json(),
        "details": [(await app_client.get(_api(bid, f"/problems/{pid}"))).json() for pid in range(1, 10)],
        "runs": [await runs_of(app_client, bid, pid) for pid in range(1, 10)],
        "finished": (await app_client.get(_api(bid, "/finished"), params={"limit": 1000})).json(),
        "export": (await app_client.get(_api(bid, "/export"), params={"what": "problems", "format": "json"})).json(),
        "distribution": (await app_client.get(_api(bid, "/export"), params={"what": "distribution", "format": "json"})).json(),
    }
    assert live["summary"]["problems"] == {"total": 9, "queued": 2, "running": 0, "finished": 6, "cancelled": 1}
    stopped = await stop(app_client, bid)
    assert stopped["source"] == "stored" and _comparable(stopped) == live["summary"]
    assert (await app_client.get(_api(bid, "/problems"), params={"limit": 1000})).json() == live["list"]
    assert [(await app_client.get(_api(bid, f"/problems/{pid}"))).json() for pid in range(1, 10)] == live["details"]
    assert [await runs_of(app_client, bid, pid) for pid in range(1, 10)] == live["runs"]
    assert (await app_client.get(_api(bid, "/finished"), params={"limit": 1000})).json() == live["finished"]
    assert (await app_client.get(_api(bid, "/export"), params={"what": "problems", "format": "json"})).json() == live["export"]
    assert (await app_client.get(_api(bid, "/export"), params={"what": "distribution", "format": "json"})).json() == live["distribution"]


@pytest.mark.asyncio
async def test_a_live_listing_merges_stored_rows_with_memory_in_every_sort(app_client, sessions):
    made = await create(app_client, 5, seeds_per_problem=2)
    bid = made["session"]["id"]
    await until_state(app_client, bid, "idle")
    await stop(app_client, bid)  # five finished problems are now stored rows
    await app_client.post(_api(bid, "/start"))
    await app_client.post(_api(bid, "/pause"))
    added = (await app_client.post(_api(bid, "/problems"), json={"problems": [problem(i) for i in range(5, 9)]})).json()
    await app_client.post(_api(bid, "/resume"))
    await until_state(app_client, bid, "idle")
    await app_client.post(_api(bid, f"/problems/{added['problem_ids'][-1]}/cancel"))  # finished: unchanged
    queries = []
    for sort in ("id", "runs_done", "top_fraction", "none_fraction", "distinct", "errors", "mean_codelets", "finished_seq"):
        for order in ("asc", "desc"):
            for offset in (0, 4):
                queries.append({"sort": sort, "order": order, "offset": offset, "limit": 4})
    queries += [{"status": "finished"}, {"status": "queued"}, {"status": "running"}, {"status": "cancelled"},
                {"q": "efg"}, {"q": "ZZ"}, {"status": "finished", "q": "d", "sort": "finished_seq", "order": "desc"}]
    live = [(await app_client.get(_api(bid, "/problems"), params=q)).json() for q in queries]
    assert live[0]["total"] == 9 and [p["id"] for p in live[0]["problems"]] == [1, 2, 3, 4]
    assert live[1]["problems"][0]["id"] == 5  # offset 4
    await stop(app_client, bid)
    stored = [(await app_client.get(_api(bid, "/problems"), params=q)).json() for q in queries]
    for q, a, b in zip(queries, live, stored):
        assert a == b, q


@pytest.mark.asyncio
async def test_the_export_of_a_live_session_says_it_ends_with_a_tail_from_memory(app_client, sessions):
    made = await create(app_client, 3, seeds_per_problem=2)
    bid = made["session"]["id"]
    await until_state(app_client, bid, "idle")
    live = await app_client.get(_api(bid, "/export"), params={"what": "runs", "format": "json"})
    assert live.headers["x-export-source"] == "stored+live-tail" and len(live.text.strip().split("\n")) == 6
    await stop(app_client, bid)
    stored = await app_client.get(_api(bid, "/export"), params={"what": "runs", "format": "json"})
    assert "x-export-source" not in stored.headers and stored.text == live.text


# ---------------------------------------------------------------------------
# Start must not finish a problem whose runs the scheduler has already dispatched
# ---------------------------------------------------------------------------


class _SchedulerRunsAfterTheLoad:
    """Stands for ``TrainingModeSessionService._factory`` and lets the scheduler run in the gap.

    ``start_session`` makes the session live inside its ``async with self._factory()`` block and
    leaves the block by awaiting the database session's close, which yields to the event loop.  A
    scheduler that is busy (with another session, say) takes that turn.  This exit does exactly
    that, deterministically: after the real exit it runs one ``_fill`` pass, which dispatches the
    new session's seeds out of ``lp.todo`` into in-flight runs.  Only the first use does it, so
    only the Start under test is affected.
    """

    def __init__(self, service, real_factory):
        self.service, self.real, self.fired = service, real_factory, False

    def __call__(self):
        outer, inner = self, self.real()

        class _Block:
            async def __aenter__(self):
                return await inner.__aenter__()

            async def __aexit__(self, *exc):
                result = await inner.__aexit__(*exc)
                if not outer.fired:
                    outer.fired = True
                    await outer.service._fill()
                return result

        return _Block()


async def _assert_every_problem_finished_with_all_its_runs(app_client, bid: int, problems: int, seeds: int):
    done = await until_state(app_client, bid, "idle")
    assert done["problems"]["finished"] == problems
    assert done["runs"]["done"] == problems * seeds
    # What the problem list says for each problem is what its runs say, and Stop stores that.
    for _ in range(2):
        listing = (await app_client.get(_api(bid, "/problems"), params={"limit": 50})).json()["problems"]
        assert [p["runs_done"] for p in listing] == [seeds] * problems, listing
        await stop(app_client, bid)


@pytest.mark.asyncio
async def test_a_start_whose_seeds_the_scheduler_dispatches_before_it_returns_still_tallies_every_run(
    app_client, sessions
):
    """Start leaves its ``async with`` block, which yields; the scheduler may dispatch the new
    session's only seed of a problem in that gap.  An empty ``lp.todo`` then does not mean every
    seed was stored, and finishing the problem there froze a tally of zero runs."""
    made = await create(app_client, 2, seeds_per_problem=1, start=False)
    bid = made["session"]["id"]
    sessions._factory = gap = _SchedulerRunsAfterTheLoad(sessions, sessions._factory)
    started = await app_client.post(_api(bid, "/start"))
    assert started.status_code == 200 and gap.fired
    await _assert_every_problem_finished_with_all_its_runs(app_client, bid, 2, 1)


@pytest.mark.asyncio
async def test_a_session_started_again_after_a_stop_is_not_finished_early_by_the_same_gap(app_client, sessions):
    """Resuming after a restart or a Stop is another Start (``test_a_graceful_shutdown_stops_every_live_session``
    saw two problems finished with one run each of two)."""
    made = await create(app_client, 2, seeds_per_problem=2, start=False)
    bid = made["session"]["id"]
    await app_client.post(_api(bid, "/start"), json={"paused": True})
    await stop(app_client, bid)
    sessions._factory = gap = _SchedulerRunsAfterTheLoad(sessions, sessions._factory)
    assert (await app_client.post(_api(bid, "/start"))).status_code == 200 and gap.fired
    await _assert_every_problem_finished_with_all_its_runs(app_client, bid, 2, 2)
