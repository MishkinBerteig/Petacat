"""E2E tests for ``/api/trainings`` -- many problems over many seeds, extendable while running.

A training's promise is the swarm's: every run is the serial run with that seed.  So the
tests compare stored runs against ``run_inprocess`` rather than against remembered numbers,
and they check what is specific to trainings: the database is written only at milestones, a
problem finishes exactly once with a contiguous ``finished_seq``, problems can be added
while the training runs, and a restart reruns what was cut off to the identical result.

The scheduler is started by the application's lifespan, which the test client does not
run, so the ``trainings`` fixture builds a ``TrainingService`` on the test database and
installs it as the process-wide service for the duration of a test.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.models.training import TrainingProblem, TrainingRun
from server.parallel.swarm import RunTask, run_inprocess
from server.services import training_service as bs
from server.services.training_executor import create_executor

STEPS = 300


@pytest.fixture(scope="module", autouse=True)
def _stop_default_swarm():
    yield
    from server.parallel.swarm import shutdown_default

    shutdown_default()


def make_service(test_engine, meta, executor=None) -> bs.TrainingService:
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    return bs.TrainingService(factory, lambda: meta, executor=executor or create_executor())


@pytest.fixture
async def trainings(app_client, test_engine):
    """A running training service on the test database; every training row starts out gone."""
    from server.api.runs import get_run_service

    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM trainings"))
    meta = get_run_service().meta
    service = make_service(test_engine, meta)
    await service.start()
    bs.set_training_service(service)
    service.test_meta = meta
    service.test_engine = test_engine
    yield service
    bs.set_training_service(None)
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


async def training_state(client, bid: int) -> dict:
    return (await client.get(f"/api/trainings/{bid}")).json()


async def until_state(client, bid: int, state: str, timeout=90.0) -> dict:
    async def _p():
        b = await training_state(client, bid)
        return b if b["state"] == state else None

    return await wait_for(_p, timeout)


def _runs(b: dict) -> tuple:
    r = b["runs"]
    return (r["total"], r["done"], r["errors"])


async def create(client, n: int = 0, policy=None, name="test training", **settings) -> dict:
    """Independent memory by default: runs are then a function of problem and seed alone."""
    settings.setdefault("memory", "independent")
    settings.setdefault("seeds_per_problem", 2)
    settings.setdefault("max_codelets", STEPS)
    body = {"name": name, "settings": settings, "problems": [problem(i) for i in range(n)]}
    if policy is not None:
        body["policy"] = policy
    resp = await client.post("/api/trainings", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def runs_of(client, bid: int, pid: int) -> list[dict]:
    return (await client.get(f"/api/trainings/{bid}/problems/{pid}/runs")).json()["runs"]


def run_key(r: dict) -> tuple:
    return (r["seed"], r["status"], r["answer"], r["codelets"], r["answer_quality"], r["temperature"])


async def db_count(engine, model, *where) -> int:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        return (await s.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


@pytest.mark.asyncio
async def test_every_stored_run_is_the_serial_run(app_client, trainings):
    made = await create(app_client, 4, seeds_per_problem=3, seed_start=5)
    bid = made["training"]["id"]
    assert made["added"] == 4 and len(made["problem_ids"]) == 4
    await app_client.post(f"/api/trainings/{bid}/close")
    done = await until_state(app_client, bid, "finished")
    assert done["problems"]["finished"] == 4 and _runs(done) == (12, 12, 0)
    backend = done["settings"]["backend"]
    assert backend in {"off", "numpy", "python", "mlx"}
    meta = trainings.test_meta
    for pid, i in zip(made["problem_ids"], range(4)):
        runs = await runs_of(app_client, bid, pid)
        assert [r["seed"] for r in runs] == [5, 6, 7]
        for r in runs:
            want = run_inprocess(
                RunTask("abc", "abd", problem(i)["target"], None, r["seed"], STEPS, backend=backend), meta)
            assert f"{r['status']}:{r['answer']}" == want.stopping_state
            assert r["codelets"] == want.codelets
            assert r["answer_quality"] == want.answer_quality
            assert r["answers"] == want.answers


@pytest.mark.asyncio
async def test_the_user_scenario_start_with_25_and_add_5_whenever_5_finish(app_client, trainings):
    made = await create(app_client, 25)
    bid = made["training"]["id"]
    total, cursor, seen, unreplaced = 25, 0, [], 0
    started = time.monotonic()
    while total < 40:
        assert time.monotonic() - started < 120
        data = (await app_client.get(
            f"/api/trainings/{bid}/finished", params={"after": cursor, "wait": 10})).json()
        cursor = data["cursor"]
        seen += [p["finished_seq"] for p in data["problems"]]
        unreplaced += len(data["problems"])
        while unreplaced >= 5 and total < 40:
            resp = await app_client.post(f"/api/trainings/{bid}/problems", json={
                "problems": [problem(total + k) for k in range(5)]})
            assert resp.status_code == 201 and resp.json()["added"] == 5
            total += 5
            unreplaced -= 5
    await app_client.post(f"/api/trainings/{bid}/close")
    done = await until_state(app_client, bid, "finished")
    assert done["problems"] == {"total": 40, "queued": 0, "running": 0, "finished": 40, "cancelled": 0}
    assert _runs(done) == (80, 80, 0)

    # Every problem finished exactly once, with a unique, contiguous finished_seq.
    tail = (await app_client.get(f"/api/trainings/{bid}/finished", params={"after": cursor})).json()
    seen += [p["finished_seq"] for p in tail["problems"]]
    assert seen == list(range(1, 41))
    assert done["finished_cursor"] == 40
    listing = (await app_client.get(f"/api/trainings/{bid}/problems", params={"limit": 100})).json()
    assert listing["total"] == 40
    assert sorted(p["finished_seq"] for p in listing["problems"]) == list(range(1, 41))
    assert {p["status"] for p in listing["problems"]} == {"finished"}
    assert await db_count(trainings.test_engine, TrainingRun, TrainingRun.training_id == bid) == 80

    # The same problems and seeds in another training give the identical runs.
    again = await create(app_client, 5)
    await app_client.post(f"/api/trainings/{again['training']['id']}/close")
    await until_state(app_client, again["training"]["id"], "finished")
    for pid_a, pid_b in zip(made["problem_ids"][:5], again["problem_ids"]):
        a = await runs_of(app_client, bid, pid_a)
        b = await runs_of(app_client, again["training"]["id"], pid_b)
        assert [run_key(r) for r in a] == [run_key(r) for r in b]


@pytest.mark.asyncio
async def test_long_poll_returns_when_a_problem_finishes_and_wait_zero_returns_at_once(app_client, trainings):
    made = await create(app_client, 0)
    bid = made["training"]["id"]
    t0 = time.monotonic()
    empty = (await app_client.get(f"/api/trainings/{bid}/finished", params={"wait": 0})).json()
    assert empty == {"cursor": 0, "problems": []} and time.monotonic() - t0 < 1.0

    waiter = asyncio.create_task(
        app_client.get(f"/api/trainings/{bid}/finished", params={"after": 0, "wait": 30}))
    await asyncio.sleep(0.3)
    assert not waiter.done()  # nothing to report yet: it is waiting
    t1 = time.monotonic()
    await app_client.post(f"/api/trainings/{bid}/problems", json={"problems": [problem(0)]})
    data = (await waiter).json()
    assert time.monotonic() - t1 < 25
    assert [p["finished_seq"] for p in data["problems"]] == [1] and data["cursor"] == 1
    assert data["problems"][0]["status"] == "finished" and data["problems"][0]["runs_done"] == 2

    t2 = time.monotonic()
    timed = (await app_client.get(f"/api/trainings/{bid}/finished", params={"after": 1, "wait": 1})).json()
    assert timed == {"cursor": 1, "problems": []} and 0.8 < time.monotonic() - t2 < 5


@pytest.mark.asyncio
async def test_pause_resume_close(app_client, trainings):
    made = await create(app_client, 0)
    bid = made["training"]["id"]
    assert made["training"]["state"] == "idle" and made["training"]["status"] == "open"
    paused = (await app_client.post(f"/api/trainings/{bid}/pause")).json()
    assert paused["status"] == "paused" and paused["state"] == "paused"
    await app_client.post(f"/api/trainings/{bid}/problems", json={"problems": [problem(0), problem(1)]})
    await asyncio.sleep(1.5)  # a running scheduler would have started them by now
    b = await training_state(app_client, bid)
    assert b["state"] == "paused" and b["problems"]["queued"] == 2 and b["runs"]["done"] == 0
    resumed = (await app_client.post(f"/api/trainings/{bid}/resume")).json()
    assert resumed["status"] == "open"
    closed = (await app_client.post(f"/api/trainings/{bid}/close")).json()
    assert closed["status"] == "closed" and closed["closed_at"]
    resp = await app_client.post(f"/api/trainings/{bid}/problems", json={"problems": [problem(2)]})
    assert resp.status_code == 409 and isinstance(resp.json()["detail"], str)
    done = await until_state(app_client, bid, "finished")
    assert done["problems"]["finished"] == 2 and done["runs"]["done"] == 4


async def partial_training(client, seeds=40000, extra=0) -> tuple[int, int]:
    """A training whose first problem is long, paused while it is mid-way."""
    body = {"name": "partial", "settings": {"memory": "independent", "seeds_per_problem": seeds, "max_codelets": STEPS},
            "problems": [problem(0)] + [problem(1 + i) for i in range(extra)]}
    made = (await client.post("/api/trainings", json=body)).json()
    bid, pid = made["training"]["id"], made["problem_ids"][0]

    async def _midway():
        p = (await client.get(f"/api/trainings/{bid}/problems/{pid}")).json()
        return p if p["runs_done"] >= 3 else None

    await wait_for(_midway)
    await client.post(f"/api/trainings/{bid}/pause")
    return bid, pid


@pytest.mark.asyncio
async def test_the_database_is_written_only_when_a_problem_finishes(app_client, trainings):
    bid, pid = await partial_training(app_client)
    p = (await app_client.get(f"/api/trainings/{bid}/problems/{pid}")).json()
    assert p["status"] == "running" and 0 < p["runs_done"] < 40000 and p["finished_seq"] is None
    assert p["top"] and p["started_at"]
    # Mid-way: progress is reported from memory, and nothing is in the database.
    assert await db_count(trainings.test_engine, TrainingRun, TrainingRun.problem_id == pid) == 0
    factory = async_sessionmaker(trainings.test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        row = await s.get(TrainingProblem, pid)
        assert row.status == "queued" and row.runs_done == 0 and row.finished_seq is None
    mid_runs = await runs_of(app_client, bid, pid)
    assert len(mid_runs) >= 3  # served from memory while the problem runs
    b = await training_state(app_client, bid)
    assert b["problems"]["running"] == 1 and b["runs"]["done"] > 0
    await app_client.post(f"/api/trainings/{bid}/cancel")


@pytest.mark.asyncio
async def test_cancelling_a_problem_keeps_its_finished_runs_and_writes_them_once(app_client, trainings):
    bid, pid = await partial_training(app_client, extra=2)
    await wait_for(lambda: _idle(trainings))
    before = (await app_client.get(f"/api/trainings/{bid}/problems/{pid}")).json()["runs_done"]
    resp = await app_client.post(f"/api/trainings/{bid}/problems/{pid}/cancel")
    assert resp.status_code == 200
    row = resp.json()
    assert row["status"] == "cancelled" and row["runs_done"] == before and row["finished_seq"] == 1
    assert await db_count(trainings.test_engine, TrainingRun, TrainingRun.problem_id == pid) == before
    again = (await app_client.post(f"/api/trainings/{bid}/problems/{pid}/cancel")).json()
    assert again["status"] == "cancelled"
    assert await db_count(trainings.test_engine, TrainingRun, TrainingRun.problem_id == pid) == before
    runs = await runs_of(app_client, bid, pid)
    assert [r["seed"] for r in runs] == list(range(1, before + 1))
    b = await training_state(app_client, bid)
    assert b["problems"]["cancelled"] == 1
    assert b["runs"]["total"] == 2 * 40000  # cancelled problems leave the totals
    await app_client.post(f"/api/trainings/{bid}/cancel")


async def _idle(service) -> bool:
    return service.executor.in_flight == 0


@pytest.mark.asyncio
async def test_cancel_and_delete_a_training(app_client, trainings):
    bid, pid = await partial_training(app_client, extra=5)
    await wait_for(lambda: _idle(trainings))
    done_runs = (await app_client.get(f"/api/trainings/{bid}/problems/{pid}")).json()["runs_done"]
    cancelled = (await app_client.post(f"/api/trainings/{bid}/cancel")).json()
    assert cancelled["status"] == "cancelled" and cancelled["state"] == "cancelled"
    assert cancelled["problems"] == {"total": 6, "queued": 0, "running": 0, "finished": 0, "cancelled": 6}
    assert await db_count(trainings.test_engine, TrainingRun, TrainingRun.problem_id == pid) == done_runs
    assert await db_count(trainings.test_engine, TrainingProblem, TrainingProblem.training_id == bid,
                          TrainingProblem.status == "queued") == 0
    resp = await app_client.post(f"/api/trainings/{bid}/problems", json={"problems": [problem(9)]})
    assert resp.status_code == 409

    resp = await app_client.delete(f"/api/trainings/{bid}")
    assert resp.status_code == 204
    assert (await app_client.get(f"/api/trainings/{bid}")).status_code == 404
    assert await db_count(trainings.test_engine, TrainingRun, TrainingRun.training_id == bid) == 0
    assert await db_count(trainings.test_engine, TrainingProblem, TrainingProblem.training_id == bid) == 0
    assert (await app_client.delete(f"/api/trainings/{bid}")).status_code == 404

    # Deleting a running training cancels it first.
    made = await create(app_client, 10, seeds_per_problem=50)
    other = made["training"]["id"]
    assert (await app_client.delete(f"/api/trainings/{other}")).status_code == 204
    await asyncio.sleep(0.5)
    assert await db_count(trainings.test_engine, TrainingProblem, TrainingProblem.training_id == other) == 0
    assert await db_count(trainings.test_engine, TrainingRun, TrainingRun.training_id == other) == 0


@pytest.mark.asyncio
async def test_a_restart_reruns_what_was_cut_off_to_the_identical_result(app_client, trainings, test_engine):
    n = 40
    made = await create(app_client, n, seeds_per_problem=4, max_codelets=1500)
    bid = made["training"]["id"]

    async def _some():
        return (await training_state(app_client, bid))["finished_cursor"] >= 2

    await wait_for(_some)
    await trainings.stop()  # the server goes down mid-way
    mid = await training_state_via_db(test_engine, bid)
    assert 2 <= mid["finished"] < n and mid["queued"] > 0

    second = make_service(test_engine, trainings.test_meta)
    await second.start()
    bs.set_training_service(second)
    try:
        await app_client.post(f"/api/trainings/{bid}/close")
        done = await until_state(app_client, bid, "finished", timeout=180)
        assert done["problems"]["finished"] == n and _runs(done) == (n * 4, n * 4, 0)
        assert await db_count(test_engine, TrainingRun, TrainingRun.training_id == bid) == n * 4  # no duplicates
        cursor = (await app_client.get(f"/api/trainings/{bid}/finished", params={"limit": 1000})).json()
        assert sorted(p["finished_seq"] for p in cursor["problems"]) == list(range(1, n + 1))

        # An uninterrupted training of the same problems gives identical runs.
        clean = await create(app_client, n, seeds_per_problem=4, max_codelets=1500)
        cid = clean["training"]["id"]
        await app_client.post(f"/api/trainings/{cid}/close")
        await until_state(app_client, cid, "finished", timeout=180)
        for pa, pb in zip(made["problem_ids"], clean["problem_ids"]):
            assert [run_key(r) for r in await runs_of(app_client, bid, pa)] == \
                   [run_key(r) for r in await runs_of(app_client, cid, pb)]
    finally:
        bs.set_training_service(trainings)
        await second.stop()


async def training_state_via_db(engine, bid: int) -> dict:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        rows = (await s.execute(
            select(TrainingProblem.status, func.count()).where(TrainingProblem.training_id == bid)
            .group_by(TrainingProblem.status))).all()
    return {status: n for status, n in rows}


@pytest.mark.asyncio
async def test_a_changed_configuration_stalls_the_training(app_client, trainings, test_engine):
    made = await create(app_client, 2)
    bid = made["training"]["id"]
    await trainings.stop()
    async with test_engine.begin() as conn:
        await conn.execute(text("UPDATE trainings SET config_hash = 'deadbeef' WHERE id = :i"), {"i": bid})
        await conn.execute(text("UPDATE training_problems SET status='queued' WHERE training_id = :i"), {"i": bid})
    second = make_service(test_engine, trainings.test_meta)
    await second.start()
    bs.set_training_service(second)
    try:
        await asyncio.sleep(1.0)
        b = await training_state(app_client, bid)
        assert b["state"] == "stalled" and "configuration" in b["stalled_reason"]
        assert b["runs"]["done"] == 0
    finally:
        bs.set_training_service(trainings)
        await second.stop()


@pytest.mark.asyncio
async def test_listing_filtering_and_the_executor_report(app_client, trainings):
    made = await create(app_client, 6)
    bid = made["training"]["id"]
    await app_client.post(f"/api/trainings/{bid}/close")
    await until_state(app_client, bid, "finished")
    top = (await app_client.get("/api/trainings")).json()
    assert top["trainings"][0]["id"] == bid
    assert top["executor"]["kind"] in ("swarm", "serial") and top["executor"]["workers"] >= 1
    assert top["limits"] == {"max_problems_per_request": 10000, "max_seeds_per_problem": 100000, "max_codelets": 200000}
    q = (await app_client.get(f"/api/trainings/{bid}/problems", params={"q": "efg"})).json()
    assert q["total"] == 1 and q["problems"][0]["target"] == "efg"
    s = (await app_client.get(f"/api/trainings/{bid}/problems",
                              params={"sort": "finished_seq", "order": "desc", "limit": 2})).json()
    assert s["total"] == 6 and [p["finished_seq"] for p in s["problems"]] == [6, 5]
    assert (await app_client.get(f"/api/trainings/{bid}/problems", params={"status": "queued"})).json()["total"] == 0
    detail = (await app_client.get(f"/api/trainings/{bid}/problems/{made['problem_ids'][0]}")).json()
    assert sum(d["count"] for d in detail["distribution"]) == 2 and detail["first_error"] is None
    assert abs(sum(d["fraction"] for d in detail["distribution"]) - 1) < 1e-9


@pytest.mark.asyncio
async def test_tag_justification_and_per_problem_seeds(app_client, trainings):
    body = {"name": "tags", "settings": {"memory": "independent", "seeds_per_problem": 2, "max_codelets": STEPS}, "problems": [
        {**problem(0), "answer": "abd", "tag": {"job": 7}, "seeds": 3}, problem(1)]}
    made = (await app_client.post("/api/trainings", json=body)).json()
    bid = made["training"]["id"]
    await app_client.post(f"/api/trainings/{bid}/close")
    await until_state(app_client, bid, "finished")
    p0 = (await app_client.get(f"/api/trainings/{bid}/problems/{made['problem_ids'][0]}")).json()
    assert p0["tag"] == {"job": 7} and p0["answer"] == "abd" and p0["seeds"] == 3 and p0["runs_done"] == 3
    p1 = (await app_client.get(f"/api/trainings/{bid}/problems/{made['problem_ids'][1]}")).json()
    assert p1["seeds"] == 2 and p1["tag"] is None and p1["answer"] is None


@pytest.mark.asyncio
async def test_validation_errors(app_client, trainings):
    post = app_client.post
    ok = problem(0)
    for bad in (
        {"problems": [{**ok, "initial": ""}]},
        {"problems": [{**ok, "initial": "ab1"}]},
        {"problems": [{**ok, "target": "x" * 65}]},
        {"problems": [{**ok, "answer": "a b"}]},
        {"problems": [{**ok, "seeds": 0}]},
        {"problems": [{**ok, "seeds": 100001}]},
        {"problems": [ok] * 10001},
        {"problems": [{"initial": "abc"}]},
        {"settings": {"seeds_per_problem": 0}},
        {"settings": {"seeds_per_problem": 100001}},
        {"settings": {"max_codelets": 200001}},
        {"settings": {"max_codelets": 0}},
        {"settings": {"memory": "sometimes"}},
        {"settings": {"nonsense": 1}},
        {"name": ""},
        {"name": "x" * 201},
        {},
    ):
        bad = {"name": "v", **bad} if "name" not in bad and bad != {} else bad
        resp = await post("/api/trainings", json=bad)
        assert resp.status_code == 422, (bad if len(str(bad)) < 200 else "big", resp.text)
        assert isinstance(resp.json()["detail"], str)
    for bad in (
        {"settings": {"parameters": {"no_such_parameter": 1}}},
        {"settings": {"backend": "no-such-backend"}},
        {"policy": {"on_run_error": "explode"}},
        {"policy": {"no_such_field": 1}},
        {"policy": {"max_retries": -1}},
        {"policy": {"max_errors_total": 0}},
    ):
        resp = await post("/api/trainings", json={"name": "v", **bad})
        assert resp.status_code == 400 and isinstance(resp.json()["detail"], str)
    made = await create(app_client, 1)
    bid = made["training"]["id"]
    assert (await post(f"/api/trainings/{bid}/problems", json={"problems": [{**ok, "initial": "1"}]})).status_code == 422
    assert (await app_client.get(f"/api/trainings/{bid}/problems", params={"limit": 5000})).status_code == 422
    assert (await app_client.get(f"/api/trainings/{bid}/problems", params={"sort": "bogus"})).status_code == 422
    assert (await app_client.get(f"/api/trainings/{bid}/finished", params={"wait": 61})).status_code == 422
    for path in ("", "/problems", "/finished", "/export"):
        assert (await app_client.get(f"/api/trainings/987654{path}")).status_code == 404
    assert (await app_client.get(f"/api/trainings/{bid}/problems/987654")).status_code == 404
    assert (await app_client.get(f"/api/trainings/{bid}/problems/987654/runs")).status_code == 404
    assert (await post(f"/api/trainings/{bid}/problems/987654/cancel")).status_code == 404
    for action in ("pause", "resume", "close", "cancel"):
        assert (await post(f"/api/trainings/987654/{action}")).status_code == 404
    assert (await post("/api/trainings/987654/problems", json={"problems": []})).status_code == 404
    await post(f"/api/trainings/{bid}/cancel")
    assert (await post(f"/api/trainings/{bid}/problems", json={"problems": [ok]})).status_code == 409
    # A problem of another training is not found through this one.
    other = await create(app_client, 1)
    assert (await app_client.get(f"/api/trainings/{bid}/problems/{other['problem_ids'][0]}")).status_code == 404


@pytest.mark.asyncio
async def test_parameters_and_backend_are_stored_and_used(app_client, trainings):
    made = await create(app_client, 1, backend="off", parameters=None)
    assert made["training"]["settings"]["backend"] == "off"
    made2 = await create(app_client, 0)
    assert made2["training"]["settings"]["backend"]  # resolved at creation, never null
    assert made2["training"]["config_hash"]


@pytest.mark.asyncio
async def test_export_csv_and_json(app_client, trainings):
    made = await create(app_client, 3)
    bid = made["training"]["id"]
    await app_client.post(f"/api/trainings/{bid}/close")
    await until_state(app_client, bid, "finished")

    r = await app_client.get(f"/api/trainings/{bid}/export", params={"what": "problems", "format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == f'attachment; filename="training-{bid}-problems.csv"'
    lines = r.text.strip().split("\n")
    assert lines[0].startswith("id,initial,modified,target") and len(lines) == 4

    r = await app_client.get(f"/api/trainings/{bid}/export", params={"what": "runs", "format": "csv"})
    lines = r.text.strip().split("\n")
    assert r.headers["content-disposition"] == f'attachment; filename="training-{bid}-runs.csv"'
    assert lines[0].startswith("problem_id,initial,modified,target,problem_answer,seed") and len(lines) == 1 + 6
    seeds = [(int(l.split(",")[0]), int(l.split(",")[5])) for l in lines[1:]]
    assert seeds == sorted(seeds)  # problem, then seed order

    r = await app_client.get(f"/api/trainings/{bid}/export", params={"what": "runs", "format": "json"})
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert r.headers["content-disposition"].endswith('.ndjson"')
    rows = [json.loads(l) for l in r.text.strip().split("\n")]
    assert len(rows) == 6 and {"problem_id", "seed", "status", "answer", "codelets"} <= set(rows[0])

    r = await app_client.get(f"/api/trainings/{bid}/export", params={"what": "problems", "format": "json"})
    assert r.headers["content-type"].startswith("application/json")
    data = r.json()
    assert len(data) == 3 and data[0]["status"] == "finished"

    r = await app_client.get(f"/api/trainings/{bid}/export", params={"what": "distribution", "format": "csv"})
    lines = r.text.strip().split("\n")
    assert lines[0].startswith("problem_id,initial,modified,target,answer_key,count") and len(lines) >= 4
    r = await app_client.get(f"/api/trainings/{bid}/export", params={"what": "distribution", "format": "json"})
    assert sum(d["count"] for d in r.json()) == 6

    empty = await create(app_client, 0)
    r = await app_client.get(f"/api/trainings/{empty['training']['id']}/export", params={"what": "runs", "format": "csv"})
    assert r.status_code == 200 and len(r.text.strip().split("\n")) == 1
    r = await app_client.get(f"/api/trainings/{empty['training']['id']}/export", params={"what": "problems", "format": "json"})
    assert r.json() == []


@pytest.mark.asyncio
async def test_trainings_share_the_cores_fairly(app_client, trainings):
    """A small training added after a huge one still finishes soon (round-robin across trainings)."""
    huge = await create(app_client, 1, seeds_per_problem=60000)
    small = await create(app_client, 2)
    sid = small["training"]["id"]
    await app_client.post(f"/api/trainings/{sid}/close")
    done = await until_state(app_client, sid, "finished", timeout=60)
    assert done["runs"]["done"] == 4
    await app_client.delete(f"/api/trainings/{huge['training']['id']}")


# ---------------------------------------------------------------------------
# The episode memory, the error policy, the configuration policy
# ---------------------------------------------------------------------------

from server.engine.memory import EpisodicMemory  # noqa: E402
from server.engine.numeric.backend import use_backend  # noqa: E402
from server.engine.runner import EngineRunner  # noqa: E402
from server.models.training import TrainingMemoryMerge  # noqa: E402
from server.services import training_memory as tm  # noqa: E402
from server.services.training_executor import SerialExecutor  # noqa: E402

SHARED_PROBLEMS = [("abc", "abd", "xyz"), ("abc", "abd", "ijk"), ("abc", "abd", "mrrjjj")]


async def create_shared(client, seeds=5, codelets=2500, problems=SHARED_PROBLEMS, **extra) -> dict:
    body = {"name": "shared", "settings": {"memory": "shared", "seeds_per_problem": seeds,
                                           "max_codelets": codelets},
            "problems": [{"initial": i, "modified": m, "target": t} for i, m, t in problems], **extra}
    resp = await client.post("/api/trainings", json=body)
    assert resp.status_code == 201, resp.text
    made = resp.json()
    await client.post(f"/api/trainings/{made['training']['id']}/close")
    return made


async def stored_runs(engine, tid: int) -> list:
    """Every run of a Training with its problem, in merge order."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        rows = (await s.execute(
            select(TrainingRun, TrainingProblem)
            .join(TrainingProblem, TrainingProblem.id == TrainingRun.problem_id)
            .where(TrainingRun.training_id == tid).order_by(TrainingRun.seq))).all()
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
async def test_shared_memory_with_one_worker_is_a_serial_episode(app_client, trainings, test_engine):
    """One worker: each run starts after the previous merged, which is Metacat's serial
    episode -- the runs, in merge order, equal one memory object carried run to run."""
    serial = make_service(test_engine, trainings.test_meta, executor=SerialExecutor())
    await serial.start()
    bs.set_training_service(serial)
    try:
        made = await create_shared(app_client, seeds=4)
        tid = made["training"]["id"]
        done = await until_state(app_client, tid, "finished", timeout=180)
        assert done["problems"]["finished"] == 3 and done["memory_version"] == 12
        rows = await stored_runs(test_engine, tid)
        assert [r.seq for r, _ in rows] == list(range(1, 13))
        assert [r.memory_version for r, _ in rows] == list(range(0, 12))  # each saw all before it
        reference = EpisodicMemory()
        backend = done["settings"]["backend"]
        for r, p in rows:
            status, answer, codelets, quality = replay(trainings.test_meta, reference, p, r.seed, 2500, backend)
            assert (r.status, r.answer, r.codelets, r.answer_quality) == (status, answer, codelets, quality)
        assert tm.memory_fingerprint(serial.live_memory(tid)) == tm.memory_fingerprint(reference)
        assert done["memory"] == {"answers": len(reference.answers), "snags": len(reference.snags)}
        assert any(r.added_answers for r, _ in rows)
    finally:
        bs.set_training_service(trainings)
        await serial.stop()


@pytest.mark.asyncio
async def test_shared_memory_with_many_workers_replays_from_the_merge_log(app_client, trainings, test_engine):
    """Whatever the interleaving, a run is reproduced by the memory as of its version,
    rebuilt from the stored merges alone."""
    made = await create_shared(app_client, seeds=6)
    tid = made["training"]["id"]
    done = await until_state(app_client, tid, "finished", timeout=180)
    n = done["runs"]["done"]
    assert n == 18 and done["memory_version"] == n
    rows = await stored_runs(test_engine, tid)
    assert [r.seq for r, _ in rows] == list(range(1, n + 1))
    assert all(0 <= r.memory_version < r.seq for r, _ in rows)
    backend = done["settings"]["backend"]
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    cache: dict[int, EpisodicMemory] = {}
    async with factory() as s:
        for version in sorted({r.memory_version for r, _ in rows}):
            cache[version] = await bs.TrainingService.rebuild_memory(s, tid, upto=version)
    for r, p in rows:
        copy = tm.copy_for_run(cache[r.memory_version])
        status, answer, codelets, quality = replay(trainings.test_meta, copy, p, r.seed, 2500, backend)
        assert (r.status, r.answer, r.codelets, r.answer_quality) == (status, answer, codelets, quality), \
            (p.target, r.seed, r.memory_version)
    # The episode never holds the same description twice.
    mem = trainings.live_memory(tid)
    keys = [(tuple(a.problem), repr(a.top_rule_signature), repr(a.bottom_rule_signature)) for a in mem.answers]
    assert len(keys) == len(set(keys))
    assert len(mem.answers) == sum(r.added_answers for r, _ in rows)
    assert len(mem.snags) == sum(r.added_snags for r, _ in rows)
    # Merges are stored once each, in order.
    assert await db_count(test_engine, TrainingMemoryMerge, TrainingMemoryMerge.training_id == tid) == n


@pytest.mark.asyncio
async def test_a_restart_rebuilds_the_memory_exactly(app_client, trainings, test_engine):
    made = await create_shared(app_client, seeds=4)
    tid = made["training"]["id"]
    await until_state(app_client, tid, "finished", timeout=180)
    before = tm.memory_fingerprint(trainings.live_memory(tid))
    summary = await training_state(app_client, tid)
    await trainings.stop()
    second = make_service(test_engine, trainings.test_meta)
    await second.start()
    bs.set_training_service(second)
    try:
        assert tm.memory_fingerprint(second.live_memory(tid)) == before
        again = await training_state(app_client, tid)
        assert again["memory_version"] == summary["memory_version"] and again["memory"] == summary["memory"]
        listing = (await app_client.get(f"/api/trainings/{tid}/memory")).json()
        assert len(listing["answers"]) == summary["memory"]["answers"]
    finally:
        bs.set_training_service(trainings)
        await second.stop()


@pytest.mark.asyncio
async def test_the_memory_endpoint_serves_the_api_memory_shape(app_client, trainings):
    made = await create_shared(app_client, seeds=4, problems=SHARED_PROBLEMS[:1])
    tid = made["training"]["id"]
    await until_state(app_client, tid, "finished", timeout=120)
    mem = (await app_client.get(f"/api/trainings/{tid}/memory")).json()
    assert mem["answers"]
    assert {"problem", "quality", "temperature", "top_rule_description", "bottom_rule_description"} <= set(mem["answers"][0])
    ids = [a["answer_id"] for a in mem["answers"]]
    assert ids == sorted(ids, reverse=True)  # newest first
    if mem["snags"]:
        assert {"problem", "codelet_count", "temperature", "description", "explanation"} <= set(mem["snags"][0])
    flat = await create(app_client, 1)
    assert (await app_client.get(f"/api/trainings/{flat['training']['id']}/memory")).status_code == 409
    assert (await app_client.get("/api/trainings/987654/memory")).status_code == 404
    assert flat["training"]["memory"] is None and flat["training"]["memory_version"] is None


@pytest.mark.asyncio
async def test_defaults_patch_and_settings_are_fixed(app_client, trainings):
    top = (await app_client.get("/api/trainings")).json()
    d = top["defaults"]
    assert d["settings"]["memory"] == "shared" and d["settings"]["seeds_per_problem"] == 100
    assert d["settings"]["max_codelets"] == 20000 and d["settings"]["backend"]
    assert d["policy"] == {"on_run_error": "record", "max_errors_per_problem": None,
                           "max_errors_total": None, "on_worker_failure": "retry", "max_retries": 3,
                           "on_config_change": "pause"}
    made = (await app_client.post("/api/trainings", json={"name": "bare"})).json()  # all defaults
    t = made["training"]
    assert t["settings"]["memory"] == "shared" and t["policy"] == d["policy"] and t["name"] == "bare"
    tid = t["id"]
    patched = (await app_client.patch(f"/api/trainings/{tid}", json={
        "name": "renamed", "note": "n", "policy": {"max_errors_total": 5}})).json()
    assert patched["name"] == "renamed" and patched["note"] == "n"
    assert patched["policy"]["max_errors_total"] == 5 and patched["policy"]["on_run_error"] == "record"
    assert (await app_client.patch(f"/api/trainings/{tid}", json={"settings": {"memory": "independent"}})).status_code == 422
    assert (await app_client.patch(f"/api/trainings/{tid}", json={"policy": {"on_run_error": "x"}})).status_code == 400
    assert (await app_client.patch(f"/api/trainings/{tid}", json={"name": ""})).status_code == 422
    assert (await app_client.patch("/api/trainings/987654", json={"name": "x"})).status_code == 404
    assert (await training_state(app_client, tid))["name"] == "renamed"


def fault_on(trainings, fn):
    trainings.fault_hook = fn


@pytest.mark.asyncio
async def test_policy_record_keeps_the_error_and_carries_on(app_client, trainings):
    fault_on(trainings, lambda lp, seed, failures: "error" if seed == 2 else None)
    made = await create(app_client, 1, seeds_per_problem=3, policy={"on_run_error": "record"})
    tid, pid = made["training"]["id"], made["problem_ids"][0]
    await app_client.post(f"/api/trainings/{tid}/close")
    done = await until_state(app_client, tid, "finished")
    assert done["runs"]["errors"] == 1 and done["runs"]["done"] == 3 and done["status"] == "closed"
    runs = await runs_of(app_client, tid, pid)
    bad = [r for r in runs if r["seed"] == 2][0]
    assert bad["key"] == "*ERROR*" and bad["status"] == "error" and "injected fault" in bad["error"]
    detail = (await app_client.get(f"/api/trainings/{tid}/problems/{pid}")).json()
    assert detail["errors"] == 1 and "injected fault" in detail["first_error"]
    assert {d["answer"] for d in detail["distribution"]} >= {"*ERROR*"}


@pytest.mark.asyncio
async def test_policy_skip_problem_pause_and_cancel(app_client, trainings):
    fault_on(trainings, lambda lp, seed, failures: "error" if lp.initial == "abc" and lp.target == "abc" and seed == 1 else None)
    # skip_problem: the failing problem is cancelled, the other finishes.
    made = await create(app_client, 2, seeds_per_problem=40, policy={"on_run_error": "skip_problem"})
    tid = made["training"]["id"]
    await app_client.post(f"/api/trainings/{tid}/close")
    done = await until_state(app_client, tid, "finished", timeout=120)
    assert done["problems"]["cancelled"] == 1 and done["problems"]["finished"] == 1
    assert "skip_problem" in done["last_event"]
    # pause: the Training pauses with an event.
    made = await create(app_client, 1, seeds_per_problem=200, policy={"on_run_error": "pause"})
    tid = made["training"]["id"]
    paused = await until_state(app_client, tid, "paused")
    assert paused["status"] == "paused" and "on_run_error = pause" in paused["last_event"]
    # cancel: the Training is cancelled.
    made = await create(app_client, 1, seeds_per_problem=200, policy={"on_run_error": "cancel"})
    tid = made["training"]["id"]
    cancelled = await until_state(app_client, tid, "cancelled")
    assert "on_run_error = cancel" in cancelled["last_event"]


@pytest.mark.asyncio
async def test_policy_error_limits(app_client, trainings):
    fault_on(trainings, lambda lp, seed, failures: "error" if lp.target == "abc" else None)
    made = await create(app_client, 1, seeds_per_problem=60, policy={"max_errors_per_problem": 3})
    tid, pid = made["training"]["id"], made["problem_ids"][0]
    async def _cancelled():
        p = (await app_client.get(f"/api/trainings/{tid}/problems/{pid}")).json()
        return p if p["status"] == "cancelled" else None
    p = await wait_for(_cancelled)
    assert p["errors"] >= 3 and "max_errors_per_problem" in (await training_state(app_client, tid))["last_event"]

    made = await create(app_client, 1, seeds_per_problem=60, policy={"max_errors_total": 2})
    paused = await until_state(app_client, made["training"]["id"], "paused")
    assert "max_errors_total" in paused["last_event"] and paused["runs"]["errors"] >= 2
    await app_client.post(f"/api/trainings/{made['training']['id']}/cancel")


@pytest.mark.asyncio
async def test_policy_worker_failure_retries_exactly_then_pauses(app_client, trainings):
    # A worker is killed on the first attempt of one run: the run is retried and is exact.
    fault_on(trainings, lambda lp, seed, failures: "kill" if seed == 2 and failures == 0 else None)
    made = await create(app_client, 2, seeds_per_problem=3)
    tid = made["training"]["id"]
    await app_client.post(f"/api/trainings/{tid}/close")
    done = await until_state(app_client, tid, "finished", timeout=120)
    assert done["runs"]["done"] == 6 and done["runs"]["errors"] == 0 and done["runs"]["retries"] >= 2
    meta, backend = trainings.test_meta, done["settings"]["backend"]
    for pid, i in zip(made["problem_ids"], range(2)):
        for r in await runs_of(app_client, tid, pid):
            want = run_inprocess(RunTask("abc", "abd", problem(i)["target"], None, r["seed"], STEPS, backend=backend), meta)
            assert (f"{r['status']}:{r['answer']}", r["codelets"]) == (want.stopping_state, want.codelets)
        assert [r["attempts"] for r in await runs_of(app_client, tid, pid)][1] >= 2

    # Always failing: after max_retries the Training pauses, the run is not lost, and a fix + resume finishes it.
    fault_on(trainings, lambda lp, seed, failures: "kill" if seed == 1 else None)
    made = await create(app_client, 1, seeds_per_problem=2, policy={"max_retries": 1})
    tid = made["training"]["id"]
    paused = await until_state(app_client, tid, "paused", timeout=120)
    assert "max_retries" in paused["last_event"]
    fault_on(trainings, None)
    await app_client.post(f"/api/trainings/{tid}/resume")
    await app_client.post(f"/api/trainings/{tid}/close")
    done = await until_state(app_client, tid, "finished", timeout=120)
    assert done["runs"]["done"] == 2 and done["runs"]["errors"] == 0

    # on_worker_failure = pause: pause at once.
    fault_on(trainings, lambda lp, seed, failures: "kill" if seed == 1 and failures == 0 else None)
    made = await create(app_client, 1, seeds_per_problem=2, policy={"on_worker_failure": "pause"})
    paused = await until_state(app_client, made["training"]["id"], "paused", timeout=120)
    assert "on_worker_failure = pause" in paused["last_event"]


@pytest.mark.asyncio
async def test_a_killed_serial_child_is_retried(app_client, trainings, test_engine):
    serial = make_service(test_engine, trainings.test_meta, executor=SerialExecutor())
    await serial.start()
    bs.set_training_service(serial)
    serial.fault_hook = lambda lp, seed, failures: "kill" if seed == 1 and failures == 0 else None
    try:
        made = await create(app_client, 1, seeds_per_problem=2)
        await app_client.post(f"/api/trainings/{made['training']['id']}/close")
        done = await until_state(app_client, made["training"]["id"], "finished", timeout=120)
        assert done["runs"]["done"] == 2 and done["runs"]["retries"] >= 1 and done["runs"]["errors"] == 0
    finally:
        bs.set_training_service(trainings)
        await serial.stop()


@pytest.mark.asyncio
async def test_config_change_policy_pause_stalls_adopt_records_hash(app_client, trainings, test_engine):
    original = trainings.test_meta
    changed = original.with_overrides({"update_cycle_length": 16})
    from server.engine.hashing import config_hash

    assert config_hash(changed) != config_hash(original)
    current = {"meta": original}
    svc = bs.TrainingService(
        async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False),
        lambda: current["meta"], executor=create_executor())
    await svc.start()
    bs.set_training_service(svc)
    try:
        pause_t = await create(app_client, 1, seeds_per_problem=60000)  # on_config_change = pause
        adopt_t = await create(app_client, 1, seeds_per_problem=60000, policy={"on_config_change": "adopt"})
        current["meta"] = changed
        svc.wake()
        stalled = await until_state(app_client, pause_t["training"]["id"], "stalled")
        assert "configuration" in stalled["stalled_reason"] and "stalled" in stalled["last_event"]
        done = await wait_for(lambda: _adopted(app_client, adopt_t["training"]["id"], config_hash(changed)))
        assert done["last_event"].startswith("adopted")
        # The configuration returns: the stalled Training carries on.
        current["meta"] = original  # no wake: the scheduler's own timer notices
        resumed = await until_state(app_client, pause_t["training"]["id"], "running", timeout=30)
        assert resumed["stalled_reason"] is None
        for t in (pause_t, adopt_t):
            await app_client.post(f"/api/trainings/{t['training']['id']}/cancel")
    finally:
        bs.set_training_service(trainings)
        await svc.stop()


async def _adopted(client, tid, new_hash):
    t = await training_state(client, tid)
    return t if t["config_hash"] == new_hash else None


@pytest.mark.asyncio
async def test_adopted_runs_record_their_config_hash(app_client, trainings, test_engine):
    original = trainings.test_meta
    changed = original.with_overrides({"update_cycle_length": 16})
    from server.engine.hashing import config_hash

    current = {"meta": original}
    svc = bs.TrainingService(
        async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False),
        lambda: current["meta"], executor=create_executor())
    await svc.start()
    bs.set_training_service(svc)
    try:
        made = await create(app_client, 1, seeds_per_problem=60000, policy={"on_config_change": "adopt"})
        tid, pid = made["training"]["id"], made["problem_ids"][0]
        await app_client.post(f"/api/trainings/{tid}/pause")
        await asyncio.sleep(0.5)
        current["meta"] = changed
        await app_client.post(f"/api/trainings/{tid}/resume")

        async def _both():
            hashes = {r["config_hash"] for r in await runs_of(app_client, tid, pid)}
            return hashes if len(hashes) == 2 else None

        hashes = await wait_for(_both)
        assert hashes == {config_hash(original), config_hash(changed)}
        await app_client.post(f"/api/trainings/{tid}/cancel")
    finally:
        bs.set_training_service(trainings)
        await svc.stop()


# ---------------------------------------------------------------------------
# Review fixes: seed range, a policy pause is not lost, isolating a culprit, live counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_ranges_must_fit_the_database(app_client, trainings):
    post = app_client.post
    ok = problem(0)
    for settings in (
        {"seed_start": 3_000_000_000},
        {"seed_start": -1},
        {"seed_start": 2_147_483_600, "seeds_per_problem": 100},
    ):
        resp = await post("/api/trainings", json={"name": "r", "settings": settings})
        assert resp.status_code == 422 and isinstance(resp.json()["detail"], str), settings
    resp = await post("/api/trainings", json={
        "name": "r", "settings": {"seed_start": 2_147_483_600, "seeds_per_problem": 2},
        "problems": [{**ok, "seeds": 100}]})
    assert resp.status_code == 422
    made = await create(app_client, 0, seed_start=2_147_483_600, seeds_per_problem=2)
    tid = made["training"]["id"]
    assert (await post(f"/api/trainings/{tid}/problems", json={"problems": [{**ok, "seeds": 100}]})).status_code == 422
    assert (await post(f"/api/trainings/{tid}/problems", json={"problems": [{**ok, "seeds": 2}]})).status_code == 201
    await app_client.post(f"/api/trainings/{tid}/cancel")


@pytest.mark.asyncio
async def test_a_policy_pause_is_not_lost_to_a_user_status_change(app_client, trainings, test_engine):
    made = await create(app_client, 1, seeds_per_problem=60000)
    tid = made["training"]["id"]
    lt = trainings._live[tid]
    await wait_for(lambda: _started(lt))
    trainings._trigger_pause(lt, "paused: injected policy pause")
    summary = await trainings.close(tid)  # arrives before the policy's own write
    assert summary["status"] == "paused" and lt.status == "paused"
    assert summary["last_event"] == "paused: injected policy pause" and summary["closed_at"]
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    from server.models.training import Training

    async def _db_status():
        async with factory() as s:
            return (await s.get(Training, tid)).status
    await asyncio.sleep(0.3)
    assert await _db_status() == "paused"
    # Nothing is dispatched while it is paused.
    await wait_for(lambda: _idle(trainings))
    done_before = (await training_state(app_client, tid))["runs"]["done"]
    await asyncio.sleep(0.5)
    assert (await training_state(app_client, tid))["runs"]["done"] == done_before
    resumed = await trainings.resume(tid)
    assert resumed["status"] == "closed" and lt.status == "closed" and await _db_status() == "closed"
    await app_client.post(f"/api/trainings/{tid}/cancel")


async def _started(lt) -> bool:
    return any(lp.started for lp in lt.active.values())


@pytest.mark.asyncio
async def test_only_the_culprit_is_charged_when_a_run_breaks_the_pool(app_client, trainings):
    culprit = problem(0)["target"]
    fault_on(trainings, lambda lp, seed, failures: "kill" if lp.target == culprit and seed == 2 else None)
    made = await create(app_client, 2, seeds_per_problem=24, policy={"max_retries": 1})
    tid, culprit_pid = made["training"]["id"], made["problem_ids"][0]
    paused = await until_state(app_client, tid, "paused", timeout=180)
    assert f"problem {culprit_pid} seed 2" in paused["last_event"] and "max_retries" in paused["last_event"]
    assert paused["runs"]["retries"] == 0  # innocent runs carry no attempts but their own
    for pid in made["problem_ids"]:
        runs = await runs_of(app_client, tid, pid)
        assert all(r["attempts"] == 1 for r in runs), [(r["seed"], r["attempts"]) for r in runs if r["attempts"] != 1]
        assert 2 not in [r["seed"] for r in runs if pid == culprit_pid]
    # Without the fault the rest completes, and the culprit's run is exact.
    fault_on(trainings, None)
    await app_client.post(f"/api/trainings/{tid}/resume")
    await app_client.post(f"/api/trainings/{tid}/close")
    done = await until_state(app_client, tid, "finished", timeout=180)
    assert done["runs"]["done"] == 48 and done["runs"]["errors"] == 0
    seed2 = [r for r in await runs_of(app_client, tid, culprit_pid) if r["seed"] == 2][0]
    want = run_inprocess(RunTask("abc", "abd", culprit, None, 2, STEPS, backend=done["settings"]["backend"]), trainings.test_meta)
    assert (f"{seed2['status']}:{seed2['answer']}", seed2["codelets"]) == (want.stopping_state, want.codelets)


@pytest.mark.asyncio
async def test_live_counts_never_step_backwards(app_client, trainings):
    made = await create(app_client, 30, seeds_per_problem=4)
    tid = made["training"]["id"]
    last = (0, 0, 0)
    for _ in range(150):
        t = await training_state(app_client, tid)
        now = (t["runs"]["done"], t["problems"]["finished"], t["codelets"])
        assert all(n >= o for n, o in zip(now, last)), (last, now)
        assert t["problems"]["total"] == 30 and t["runs"]["total"] == 120
        last = now
        if t["problems"]["finished"] == 30:
            break
        await asyncio.sleep(0.03)
    done = await until_state(app_client, tid, "idle")
    assert done["runs"]["done"] == 120


@pytest.mark.asyncio
async def test_a_summary_takes_its_finished_cursor_from_the_snapshot_of_its_counts(app_client, trainings):
    """Training Mode: the caller's Training row may be older than the counts' snapshot.  A summary
    that counts every problem finished must then still report the matching finished_cursor."""
    made = await create(app_client, 3)
    bid = made["training"]["id"]
    await app_client.post(f"/api/trainings/{bid}/close")
    await until_state(app_client, bid, "finished")
    async with trainings._factory() as s:
        stale = await trainings._get_training(s, bid)
        s.expunge(stale)
        stale.finished_count = 0  # the row as loaded before the last milestone writes
        summary = (await trainings._summaries(s, [stale]))[0]
    assert summary["state"] == "finished" and summary["problems"]["finished"] == 3
    assert summary["finished_cursor"] == 3
