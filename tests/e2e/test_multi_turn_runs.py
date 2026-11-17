"""Multi-turn runs in Training Mode Sessions, through the real service and routes (v2.0, increment 4, stage B).

A run of a ``multi_turn`` problem is a chat: each turn is one engine run, a turn that answers makes the run
wait (holding no worker) for the teacher's next input, and the next turn's strings come from the window
(``turn_record.next_window``).  Checked here: the window and what reaches the Workspace; one ``finish_run``
per turn; the turn seed; identical conversations on the serial child, the swarm and in process; a turn with no
answer and the teacher's end; stale input; Stop and Start, Pause and Resume; the teacher's error handling; the
conversation call and the runs listing.
"""

from __future__ import annotations

import asyncio
import pickle

import pytest
from sqlalchemy import select, text

from server.engine.memory import EpisodicMemory
from server.models.training_mode_session import TrainingModeSessionTurn
from server.services import training_mode_session_service as bs
from server.services import turn_record
from server.services.training_mode_session_executor import SerialExecutor
from tests.e2e.test_session_configuration import factory_of
from tests.e2e.test_training_mode_sessions_api import make_service, stop, until_state, wait_for
from tests.support.chat import InProcessExecutor, ScriptedExecutor, conversation_key, series_teacher

PROBLEM = {"initial": "abc", "modified": "abd", "target": "ijk", "multi_turn": True}
SERIES = {"abc": ["xyz", "mno"]}
URL = "/api/training-mode/sessions"


@pytest.fixture(scope="module", autouse=True)
def _stop_default_swarm():
    yield
    from server.parallel.swarm import shutdown_default

    shutdown_default()


async def clean(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM training_mode_sessions"))


async def serve(app_client, test_engine, executor=None):
    """A service on the test database, installed as the process-wide one."""
    from server.api.runs import get_run_service

    await clean(test_engine)
    service = make_service(test_engine, get_run_service().meta, executor=executor or SerialExecutor())
    await service.start()
    bs.set_training_mode_session_service(service)
    service.test_engine = test_engine
    return service


async def release(service) -> None:
    bs.set_training_mode_session_service(None)
    await service.stop()
    await clean(service.test_engine)


@pytest.fixture
async def chat(app_client, test_engine):
    """A service on a scripted executor: every task answers ``<input>!`` at once (the engine's cognition is
    not what these tests are about), proposing a node named for its input."""
    service = await serve(app_client, test_engine, ScriptedExecutor())
    service.drain_timeout = 0.3
    yield service
    await release(service)


@pytest.fixture
async def held(app_client, test_engine):
    """The same, with every task held until the test finishes it (a turn is then in flight)."""
    service = await serve(app_client, test_engine, ScriptedExecutor(hold=True))
    service.drain_timeout = 0.3
    yield service
    await release(service)


async def make(client, problems=None, seeds=1, max_codelets=3000, base="training-v2", start=True, **settings) -> int:
    body = {"name": "chat", "settings": {"seeds_per_problem": seeds, "max_codelets": max_codelets,
                                         "configuration_base": base, "backend": "off", **settings},
            "problems": problems if problems is not None else [dict(PROBLEM)]}
    resp = await client.post(URL, json=body)
    assert resp.status_code == 201, resp.text
    tid = resp.json()["session"]["id"]
    if start:
        assert (await client.post(f"{URL}/{tid}/start")).status_code == 200
    return tid


async def conversation(client, tid, pid=1, seed=1) -> dict:
    resp = await client.get(f"{URL}/{tid}/problems/{pid}/runs/{seed}")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def until_run(client, tid, state, pid=1, seed=1, timeout=240.0) -> dict:
    async def _p():
        c = await conversation(client, tid, pid, seed)
        return c if c["state"] == state else None

    return await wait_for(_p, timeout)


async def say(client, tid, turn, text=None, pid=1, seed=1, **extra):
    body = {"turn": turn, **({"text": text} if text is not None else {}), **extra}
    return await client.post(f"{URL}/{tid}/problems/{pid}/runs/{seed}/input", json=body)


# ---------------------------------------------------------------------------
# The chat, the window, the turn seed and one finish_run per turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_teacher_drives_a_run_to_its_end_and_the_window_slides(chat, app_client):
    tid = await make(app_client, start=False)
    chat.set_teacher(tid, series_teacher(SERIES, label="series over"))
    await app_client.post(f"{URL}/{tid}/start")
    c = await until_run(app_client, tid, "ended")
    assert [t["turn"] for t in c["turns"]] == [1, 2, 3] and c["end_reason"] == "teacher"
    assert c["end_label"] == "series over" and c["waiting_for"] is None and not c["accepts_input"]
    one, two, three = (t["positions"] for t in c["turns"])
    assert (one["context"], one["second"], one["input"], one["response"]) == ("abc", "abd", "ijk", "ijk!")
    # turn 2: the 1st position is turn 1's three strings joined with single spaces, the 2nd is turn 1's response
    assert two == {"context": "abc abd ijk", "second": "ijk!", "input": "xyz", "response": "xyz!"}
    assert three == {"context": "abc abd ijk ijk! xyz", "second": "xyz!", "input": "mno", "response": "mno!"}
    assert [t["supplied_by"]["input"] for t in c["turns"]] == ["problem", "teacher", "teacher"]
    assert c["turns"][1]["supplied_by"] == {
        "context": "window", "second": "petacat", "input": "teacher", "response": "petacat"}
    assert c["turns"][-1]["end_reason"] == "teacher" and c["turns"][0]["end_reason"] is None
    # the executor was given exactly the joined strings, in the three string positions
    sent = [(t.initial, t.modified, t.target) for t, _m, _f in chat.executor.calls]
    assert sent == [("abc", "abd", "ijk"), ("abc abd ijk", "ijk!", "xyz"), ("abc abd ijk ijk! xyz", "xyz!", "mno")]
    # the turn seed: turn 1 runs with the run's seed, later turns with turn_record.turn_seed
    seeds = [t.seed for t, _m, _f in chat.executor.calls]
    assert seeds == [1, turn_record.turn_seed(1, 2), turn_record.turn_seed(1, 3)]
    assert [t["turn_seed"] for t in c["turns"]] == seeds
    # the run is one outcome of its problem: the last turn's answer, the codelets summed
    (run,) = (await app_client.get(f"{URL}/{tid}/problems/1/runs")).json()["runs"]
    assert run["answer"] == "mno!" and run["codelets"] == sum(t["codelets"] for t in c["turns"])
    assert (run["state"], run["turns"], run["end_reason"], run["end_label"]) == ("ended", 3, "teacher", "series over")
    assert (await app_client.get(f"{URL}/{tid}/problems/1")).json()["status"] == "finished"
    await stop(app_client, tid)


@pytest.mark.asyncio
async def test_each_turn_is_one_finish_run_so_a_later_turn_runs_under_what_an_earlier_one_built(chat, app_client):
    tid = await make(app_client, start=False)
    chat.set_teacher(tid, series_teacher(SERIES))
    await app_client.post(f"{URL}/{tid}/start")
    c = await until_run(app_client, tid, "ended")
    live = chat._live[tid]
    entries = [e.pending for e in live.config.changes if e.pending.source == "learner"]
    assert len(entries) == 3  # one learner entry per turn, not one per run
    assert all("the run of seed 1" in e.note for e in entries)  # each names the run's own seed
    assert "turn 2" in entries[1].note and "turn 3" in entries[2].note and "turn" not in entries[0].note
    # each turn was dispatched under the configuration the turn before had changed
    providers = [m for _t, m, _f in chat.executor.calls]
    assert [("plato-chat-ijk" in m.slipnet_node_specs, "plato-chat-xyz" in m.slipnet_node_specs) for m in providers] \
        == [(False, False), (True, False), (True, True)]
    revisions = [t["configuration_revision"] for t in c["turns"]]
    assert revisions[0] < revisions[1] < revisions[2]
    assert [t["episode_version"] for t in c["turns"]] == sorted({t["episode_version"] for t in c["turns"]})
    assert len({t["seq"] for t in c["turns"]}) == 3  # three merges
    await stop(app_client, tid)


# ---------------------------------------------------------------------------
# Waiting: no worker is held, and no one ends the run but the teacher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_nobody_ends_waits_forever_holding_no_worker_and_the_route_drives_it(held, app_client):
    tid = await make(app_client)
    await wait_for(lambda: _async(len(held.executor.calls) == 1))
    held.executor.finish(0)
    c = await until_run(app_client, tid, "waiting")
    assert c["waiting_for"] == 2 and c["accepts_input"] and c["session_state"] == "running"
    assert [t["status"] for t in c["turns"]] == ["answer_found"]
    s = (await app_client.get(f"{URL}/{tid}")).json()
    assert s["state"] == "running" and s["activity"] == "waiting" and s["runs"]["waiting"] == 1
    assert held.executor.in_flight == 0 and not held._live[tid].inflight_subs  # no worker, no run in flight
    assert (await app_client.get(f"{URL}/{tid}/problems/1")).json()["status"] == "running"
    await asyncio.sleep(0.4)  # nobody ends it: it keeps waiting
    assert (await conversation(app_client, tid))["state"] == "waiting" and len(held.executor.calls) == 1
    # the route supplies turn 2; it is dispatched (a turn in flight, no longer waiting)
    resp = await say(app_client, tid, 2, "xyz")
    assert resp.status_code == 200 and resp.json()["state"] == "running"
    assert [t["status"] for t in resp.json()["turns"]] == ["answer_found", "pending"]
    await wait_for(lambda: _async(len(held.executor.calls) == 2))
    s = (await app_client.get(f"{URL}/{tid}")).json()
    assert s["activity"] is None and s["runs"]["waiting"] == 0
    held.executor.finish(1)
    c = await until_run(app_client, tid, "waiting")
    assert c["waiting_for"] == 3 and c["turns"][1]["positions"]["response"] == "xyz!"
    # a duplicate of turn 2's input is stale; the teacher ends the run, with a label
    assert (await say(app_client, tid, 2, "xyz")).status_code == 409
    resp = await say(app_client, tid, 3, end=True, label="that is enough")
    assert resp.status_code == 200 and resp.json()["state"] == "ended"
    assert (resp.json()["end_reason"], resp.json()["end_label"]) == ("teacher", "that is enough")
    s = await until_state(app_client, tid, "finished")
    assert s["activity"] == "idle" and s["runs"]["waiting"] == 0 and s["problems"]["finished"] == 1
    await stop(app_client, tid)


async def _async(value):
    return value


@pytest.mark.asyncio
async def test_a_turn_with_no_answer_ends_the_run_and_its_proposals_still_apply(chat, app_client):
    tid = await make(app_client, start=False)
    chat.set_teacher(tid, series_teacher({"abc": ["NOANSWER", "never"]}))
    await app_client.post(f"{URL}/{tid}/start")
    c = await until_run(app_client, tid, "ended")
    assert [t["status"] for t in c["turns"]] == ["answer_found", "gave_up"]
    assert (c["end_reason"], c["end_label"]) == ("no-answer", None)
    assert c["turns"][1]["positions"]["response"] is None and len(chat.executor.calls) == 2
    assert "plato-chat-NOANSWER" in chat._live[tid].config.document.tables["slipnet_node_defs"] \
        or ("plato-chat-NOANSWER",) in chat._live[tid].config.document.tables["slipnet_node_defs"]
    (run,) = (await app_client.get(f"{URL}/{tid}/problems/1/runs")).json()["runs"]
    assert run["key"] == "*NONE*" and run["state"] == "ended" and run["turns"] == 2
    # an input for a run that has ended is stale
    assert (await say(app_client, tid, 3, "more")).status_code == 409
    await stop(app_client, tid)


@pytest.mark.asyncio
async def test_a_turn_that_raises_ends_the_run_with_the_error(chat, app_client):
    tid = await make(app_client, start=False)
    chat.set_teacher(tid, series_teacher({"abc": ["BOOM"]}))
    await app_client.post(f"{URL}/{tid}/start")
    c = await until_run(app_client, tid, "ended")
    assert c["end_reason"] == "error" and c["turns"][1]["error"] == "scripted failure"
    (run,) = (await app_client.get(f"{URL}/{tid}/problems/1/runs")).json()["runs"]
    assert run["key"] == "*ERROR*" and run["error"] == "scripted failure"
    await stop(app_client, tid)


# ---------------------------------------------------------------------------
# Stale input and the other refusals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_input_is_refused_unless_it_is_the_exact_next_input_of_a_waiting_run(held, app_client):
    problems = [dict(PROBLEM), {"initial": "q", "modified": "q", "target": "q"}]  # the second is single-turn
    tid = await make(app_client, problems=problems, seeds=2)
    await wait_for(lambda: _async(len(held.executor.calls) >= 1))
    # nothing has answered yet: a run in flight is not waiting
    assert (await say(app_client, tid, 2, "x")).status_code == 409
    held.executor.finish(0)
    await until_run(app_client, tid, "waiting")
    detail = (await say(app_client, tid, 3, "x")).json()["detail"]  # the wrong turn
    assert detail.startswith("stale:") and "turn 2" in detail
    assert (await say(app_client, tid, 1, "x")).status_code == 409  # an old turn
    assert (await say(app_client, tid, 2, "x", seed=2)).status_code == 409  # seed 2 has not answered
    assert (await say(app_client, tid, 2, "x", seed=99)).status_code == 404  # no such run
    assert (await say(app_client, tid, 2, "x", pid=99)).status_code == 404  # no such problem
    assert (await say(app_client, tid, 2, "")).status_code == 422  # empty: refused by problem_text, as today
    assert (await say(app_client, tid, 2, "a\x00b")).status_code == 422  # NUL cannot be stored
    assert (await app_client.post(f"{URL}/{tid}/problems/1/runs/1/input", json={"turn": 2})).status_code == 422
    assert (await say(app_client, tid, 2, "x", end=True)).status_code == 422  # both a text and an end
    assert (await say(app_client, tid, 0, "x")).status_code == 422
    assert (await conversation(app_client, tid))["state"] == "waiting"  # none of that changed the run
    assert (await say(app_client, tid, 2, "x")).status_code == 200
    assert (await say(app_client, tid, 2, "x")).status_code == 409  # a duplicate
    # a single-turn problem's run is never waiting
    assert (await say(app_client, tid, 2, "x", pid=2)).status_code == 409
    # the service-level door gives the same refusals, as exceptions
    with pytest.raises(bs.StaleInput) as stale:
        await held.supply_input(tid, 1, 1, 9, "z")
    assert stale.value.status == 409 and stale.value.detail.startswith("stale:")
    await app_client.post(f"{URL}/{tid}/stop")
    assert (await say(app_client, tid, 2, "y")).status_code == 409  # a Stopped session takes no input


# ---------------------------------------------------------------------------
# Stop and Start, Pause and Resume
# ---------------------------------------------------------------------------


async def turn_rows(engine, tid):
    async with factory_of(engine)() as s:
        rows = (await s.execute(select(TrainingModeSessionTurn).where(TrainingModeSessionTurn.session_id == tid)
                                .order_by(TrainingModeSessionTurn.problem_id, TrainingModeSessionTurn.seed,
                                          TrainingModeSessionTurn.turn))).scalars().all()
    return rows


@pytest.mark.asyncio
async def test_a_waiting_run_survives_stop_and_start(chat, app_client, test_engine):
    tid = await make(app_client)
    before = await until_run(app_client, tid, "waiting")
    stopped = await stop(app_client, tid)
    assert stopped["state"] == "stopped" and stopped["runs"]["waiting"] == 1 and stopped["problems"]["queued"] == 1
    (row,) = await turn_rows(test_engine, tid)
    assert (row.turn, row.status, row.end_reason, row.answer, row.input_from) == (1, "answer_found", None, "ijk!", "problem")
    stopped_view = await conversation(app_client, tid)  # a Stopped session is read from its turn rows
    assert stopped_view["state"] == "waiting" and stopped_view["session_state"] == "stopped"
    assert stopped_view["turns"] == before["turns"] and not stopped_view["accepts_input"]
    assert (await say(app_client, tid, 2, "xyz")).status_code == 409  # a Stopped session takes no input
    assert (await app_client.post(f"{URL}/{tid}/start")).status_code == 200
    after = await conversation(app_client, tid)
    assert after["state"] == "waiting" and after["waiting_for"] == 2 and after["accepts_input"]
    assert (await app_client.get(f"{URL}/{tid}")).json()["runs"]["waiting"] == 1
    resp = await say(app_client, tid, 2, "xyz")
    assert resp.status_code == 200 and resp.json()["turns"][1]["positions"]["context"] == "abc abd ijk"
    await until_run(app_client, tid, "waiting")
    assert (await say(app_client, tid, 3, end=True)).status_code == 200
    final = await stop(app_client, tid)
    assert final["problems"]["finished"] == 1 and final["runs"]["waiting"] == 0
    rows = await turn_rows(test_engine, tid)
    assert [(r.turn, r.status, r.end_reason, r.input_from) for r in rows] == [
        (1, "answer_found", None, "problem"), (2, "answer_found", "teacher", "teacher")]


@pytest.mark.asyncio
async def test_a_turn_interrupted_by_stop_runs_again_from_its_stored_input(held, app_client, test_engine):
    tid = await make(app_client)
    await wait_for(lambda: _async(len(held.executor.calls) == 1))
    held.executor.finish(0)
    await until_run(app_client, tid, "waiting")
    assert (await say(app_client, tid, 2, "xyz")).status_code == 200
    await wait_for(lambda: _async(len(held.executor.calls) == 2))  # turn 2 is in flight; Stop will not wait for it
    await stop(app_client, tid)
    rows = await turn_rows(test_engine, tid)
    assert [(r.turn, r.status) for r in rows] == [(1, "answer_found"), (2, "pending")]
    assert (rows[1].context, rows[1].second_string, rows[1].input, rows[1].input_from) == (
        "abc abd ijk", "ijk!", "xyz", "teacher")
    seen = await conversation(app_client, tid)
    assert seen["state"] == "queued" and seen["turns"][1]["status"] == "pending"
    held.executor.finish(1)  # the worker that Stop gave up on finishes later; its outcome is ignored
    held.executor.hold = False
    await app_client.post(f"{URL}/{tid}/start")
    c = await until_run(app_client, tid, "waiting")  # turn 2 ran again from the stored strings
    assert [t["positions"]["context"] for t in c["turns"]] == ["abc", "abc abd ijk"]
    assert c["turns"][1]["turn_seed"] == turn_record.turn_seed(1, 2)
    assert held.executor.calls[-1][0].seed == turn_record.turn_seed(1, 2)
    await stop(app_client, tid)


@pytest.mark.asyncio
async def test_an_input_during_pause_is_kept_and_dispatched_on_resume(chat, app_client):
    tid = await make(app_client)
    await until_run(app_client, tid, "waiting")
    assert (await app_client.post(f"{URL}/{tid}/pause")).status_code == 200
    resp = await say(app_client, tid, 2, "xyz")
    assert resp.status_code == 200 and resp.json()["state"] == "running" and resp.json()["session_state"] == "paused"
    await asyncio.sleep(0.5)
    assert len(chat.executor.calls) == 1  # nothing dispatched while paused
    assert (await say(app_client, tid, 2, "again")).status_code == 409  # and it is not waiting any more
    assert (await app_client.post(f"{URL}/{tid}/resume")).status_code == 200
    c = await until_run(app_client, tid, "waiting")
    assert c["turns"][1]["positions"]["input"] == "xyz" and len(chat.executor.calls) == 2
    await stop(app_client, tid)


@pytest.mark.asyncio
async def test_cancelling_a_problem_ends_its_waiting_runs(chat, app_client, test_engine):
    tid = await make(app_client, seeds=2)
    await wait_for(lambda: _async(len(chat.executor.calls) >= 2))
    await until_run(app_client, tid, "waiting", seed=2)
    assert (await app_client.post(f"{URL}/{tid}/problems/1/cancel")).status_code == 200
    for seed in (1, 2):
        c = await conversation(app_client, tid, seed=seed)
        assert (c["state"], c["end_reason"]) == ("ended", "cancelled")
        assert (await say(app_client, tid, 2, "x", seed=seed)).status_code == 409
    assert (await app_client.get(f"{URL}/{tid}")).json()["runs"]["waiting"] == 0
    await stop(app_client, tid)
    rows = await turn_rows(test_engine, tid)
    assert [r.end_reason for r in rows] == ["cancelled", "cancelled"]


# ---------------------------------------------------------------------------
# The teacher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_teacher_that_fails_leaves_the_run_waiting_and_a_diagnostic(chat, app_client):
    replies = iter([RuntimeError("the teacher broke"), 42, {"end": "yes"}, "", None])

    def teacher(conversation):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    tid = await make(app_client, seeds=5, start=False)
    chat.set_teacher(tid, teacher)
    await app_client.post(f"{URL}/{tid}/start")
    await wait_for(lambda: _async(len(chat.executor.calls) == 5))
    live = chat._live[tid]
    kinds = sorted(d["kind"] for d in live.config.diagnostics)
    assert kinds == ["teacher_malformed", "teacher_malformed", "teacher_raised", "teacher_refused"], kinds
    assert "the teacher broke" in [d["message"] for d in live.config.diagnostics if d["kind"] == "teacher_raised"][0]
    s = (await app_client.get(f"{URL}/{tid}")).json()
    assert s["runs"]["waiting"] == 5 and s["activity"] == "waiting" and s["state"] == "running"  # all still waiting
    for seed in range(1, 6):  # the route still drives them
        assert (await say(app_client, tid, 2, "x", seed=seed)).status_code == 200
    await stop(app_client, tid)


@pytest.mark.asyncio
async def test_a_teacher_is_asked_again_for_a_run_restored_while_waiting(chat, app_client):
    tid = await make(app_client)
    await until_run(app_client, tid, "waiting")
    await stop(app_client, tid)
    asked = []
    chat.set_teacher(tid, series_teacher(SERIES, log=asked))
    await app_client.post(f"{URL}/{tid}/start")
    c = await until_run(app_client, tid, "ended")
    assert asked[0] == (1, 1, 2) and c["end_reason"] == "teacher" and len(c["turns"]) == 3
    chat.set_teacher(tid, None)  # removing it
    await stop(app_client, tid)


# ---------------------------------------------------------------------------
# The conversation call and the runs listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_conversation_and_the_listing_say_what_a_client_needs(chat, app_client):
    problems = [dict(PROBLEM), {"initial": "q", "modified": "q", "target": "q"}]
    tid = await make(app_client, problems=problems, seeds=2)
    await wait_for(lambda: _async(len(chat.executor.calls) == 4))
    c = await conversation(app_client, tid)
    assert c["problem"] == {"initial": "abc", "modified": "abd", "target": "ijk", "tag": None}
    assert (c["session_id"], c["problem_id"], c["seed"], c["multi_turn"]) == (tid, 1, 1, True)
    assert (c["state"], c["waiting_for"], c["accepts_input"], c["turn_count"]) == ("waiting", 2, True, 1)
    (t,) = c["turns"]
    assert set(t) >= {"turn", "positions", "supplied_by", "status", "codelets", "end_reason", "evidence",
                      "proposals", "turn_seed", "episode_version", "configuration_revision"}
    assert t["evidence"] == {"bonds": {}, "groups": {}, "rule": None, "snags": [], "unperceived": 0,
                            "coderack": {"full_posts": 0, "overflowing_batches": 0, "evicted": 0}}
    # a single-turn problem is a conversation of one turn that has ended
    s = await conversation(app_client, tid, pid=2)
    assert (s["multi_turn"], s["state"], s["end_reason"], s["turn_count"]) == (False, "ended", "single-turn", 1)
    # the listing keeps its old fields and gains the state, the turn count and the reason
    runs = (await app_client.get(f"{URL}/{tid}/problems/1/runs")).json()["runs"]
    assert [(r["seed"], r["state"], r["turns"], r["waiting_for"], r["answer"]) for r in runs] == [
        (1, "waiting", 1, 2, "ijk!"), (2, "waiting", 1, 2, "ijk!")]
    single = (await app_client.get(f"{URL}/{tid}/problems/2/runs")).json()["runs"]
    assert {"seq", "memory_version", "episode_version", "configuration_revision", "seed", "status", "key",
            "answer", "answers", "codelets", "seconds", "temperature", "answer_quality", "error", "config_hash",
            "attempts", "memory_added"} <= set(single[0])
    assert [(r["state"], r["turns"], r["end_reason"], r["key"]) for r in single] == [("ended", 1, "single-turn", "q!")] * 2
    assert (await app_client.get(f"{URL}/{tid}/problems/1/runs/9")).status_code == 404
    assert (await app_client.get(f"{URL}/{tid}/problems/9/runs/1")).status_code == 404
    live = await conversation(app_client, tid)
    await stop(app_client, tid)
    stored = await conversation(app_client, tid)
    assert stored["turns"] == live["turns"] and stored["state"] == "waiting" and stored["session_state"] == "stopped"
    stored_runs = (await app_client.get(f"{URL}/{tid}/problems/1/runs")).json()["runs"]
    assert [(r["seed"], r["state"], r["turns"], r["waiting_for"]) for r in stored_runs] == [
        (1, "waiting", 1, 2), (2, "waiting", 1, 2)]
    ended = (await app_client.get(f"{URL}/{tid}/problems/2/runs")).json()["runs"]
    assert [(r["state"], r["end_reason"]) for r in ended] == [("ended", "single-turn")] * 2


@pytest.mark.asyncio
async def test_multi_turn_is_a_per_problem_flag_that_defaults_to_false(chat, app_client):
    tid = await make(app_client, problems=[{"initial": "q", "modified": "q", "target": "q"}], start=False)
    problem = (await app_client.get(f"{URL}/{tid}/problems/1")).json()
    assert problem["multi_turn"] is False
    bad = await app_client.post(f"{URL}/{tid}/problems", json={"problems": [dict(PROBLEM, answer="ijl")]})
    assert bad.status_code == 422 and "multi-turn" in bad.text
    ok = await app_client.post(f"{URL}/{tid}/problems", json={"problems": [dict(PROBLEM)]})
    assert ok.status_code == 201
    assert (await app_client.get(f"{URL}/{tid}/problems/2")).json()["multi_turn"] is True


# ---------------------------------------------------------------------------
# The real engine, on every executor
# ---------------------------------------------------------------------------


async def real_chat(app_client, test_engine, executor, seeds=3):
    """Run the multi-turn problem ``1:1::1`` (a symbol with no node: turn 1 builds it) with inputs ``2`` and ``3``
    on *executor*, through the service and its routes, and return each run's conversation."""
    service = await serve(app_client, test_engine, executor)
    try:
        tid = await make(app_client, problems=[{"initial": "1", "modified": "1", "target": "1", "multi_turn": True},
                                               {"initial": "2", "modified": "2", "target": "2"}],
                         seeds=seeds, max_codelets=1500, start=False)
        service.set_teacher(tid, series_teacher({"1": ["2", "3"]}))
        await app_client.post(f"{URL}/{tid}/start")
        await until_state(app_client, tid, "finished", timeout=600)
        out = {pid: [await conversation(app_client, tid, pid, seed) for seed in range(1, seeds + 1)] for pid in (1, 2)}
        runs = {pid: (await app_client.get(f"{URL}/{tid}/problems/{pid}/runs")).json()["runs"] for pid in (1, 2)}
        document = service._live[tid].config.document
        await stop(app_client, tid)
        return out, runs, document
    finally:
        await release(service)


@pytest.mark.asyncio
async def test_serial_child_swarm_and_in_process_give_identical_conversations_that_build_nodes(app_client, test_engine):
    from server.api.runs import get_run_service
    from server.parallel.swarm import Swarm
    from server.services.training_mode_session_executor import SwarmExecutor

    meta = get_run_service().meta
    results = {}
    for name, executor in (("in-process", InProcessExecutor()), ("serial child", SerialExecutor()),
                           ("swarm", SwarmExecutor(Swarm(workers=1, meta=meta)))):
        results[name] = await real_chat(app_client, test_engine, executor)
        executor.close() if name != "swarm" else executor.swarm.shutdown()
    reference, runs_ref, document = results["in-process"]
    for name, (got, runs, _doc) in results.items():
        assert {pid: [conversation_key(c) for c in cs] for pid, cs in got.items()} \
            == {pid: [conversation_key(c) for c in cs] for pid, cs in reference.items()}, name
        assert [(r["seed"], r["key"], r["codelets"], r["answer"]) for r in runs[1]] \
            == [(r["seed"], r["key"], r["codelets"], r["answer"]) for r in runs_ref[1]], name
    # what was compared is a real chat that built structure: turn 1 made the symbol's node, a later turn saw it
    first = reference[1][0]
    assert first["turns"][0]["status"] == "answer_found" and len(first["turns"]) >= 2
    assert any(p["op"] == "add_node" for c in reference[1] for p in c["turns"][0]["proposals"])
    assert ("plato-cp-0031",) in document.tables["slipnet_node_defs"]
    assert all(c["turns"][0]["evidence"]["unperceived"] >= 0 for c in reference[1])
    # a single-turn problem's runs are a chat of one turn, with the evidence
    assert all(c["turn_count"] == 1 and c["end_reason"] == "single-turn" and c["turns"][0]["evidence"] for c in reference[2])


@pytest.mark.asyncio
async def test_a_single_turn_problem_is_the_run_it_always_was(app_client, test_engine):
    """The run's row, its answer, its codelets and its draws are those of a plain engine run of the same seed on
    the same configuration and memory: here, with one worker, the memory each run starts from is the one the
    runs before it left (checked by replaying them in order)."""
    from server.api.runs import get_run_service
    from server.services import training_mode_session_memory as tm
    from server.services.training_mode_session_executor import SessionTask, run_task

    meta = get_run_service().meta
    service = await serve(app_client, test_engine, InProcessExecutor())
    try:
        tid = await make(app_client, problems=[{"initial": "abc", "modified": "abd", "target": "xyz"}], seeds=4,
                         max_codelets=600, base="global")
        await until_state(app_client, tid, "finished", timeout=300)
        runs = (await app_client.get(f"{URL}/{tid}/problems/1/runs")).json()["runs"]
        memory = tm.copy_for_run(EpisodicMemory())
        for r in runs:
            ref = tm.MemoryRef(tid, "x", 0)
            ref.snapshot = tm.snapshot_blob(memory)
            direct = run_task(SessionTask("abc", "abd", "xyz", None, r["seed"], 600, None, "off", memory=ref), meta)
            assert (r["status"], r["answer"], r["codelets"], r["answer_quality"]) \
                == (direct.status, direct.answer, direct.codelets, direct.answer_quality), r["seed"]
            tm.apply_merge(memory, pickle.loads(direct.additions))
            c = await conversation(app_client, tid, 1, r["seed"])
            assert c["turn_count"] == 1 and c["turns"][0]["turn_seed"] == r["seed"]
            assert c["turns"][0]["evidence"] == direct.evidence
        await stop(app_client, tid)
    finally:
        await release(service)


@pytest.mark.asyncio
async def test_the_joined_strings_pass_through_every_layer_exactly(chat, app_client, test_engine):
    """No layer trims, normalises, lowers or cuts: the route, the service, the executor, the conversation call, the turn
    rows and a Stop and Start all hold the input and the window exactly as given, spaces, tabs, line breaks, emoji, a combining
    sequence and an uppercase letter included."""
    odd = "  Ab\t😀́\r\n ψ "
    tid = await make(app_client, problems=[{"initial": " A ", "modified": "b\n", "target": "ψ", "multi_turn": True}])
    await until_run(app_client, tid, "waiting")
    resp = await say(app_client, tid, 2, odd)
    assert resp.status_code == 200
    await until_run(app_client, tid, "waiting")
    sent = [(t.initial, t.modified, t.target) for t, _m, _f in chat.executor.calls]
    assert sent == [(" A ", "b\n", "ψ"), (" A  b\n ψ", "ψ!", odd)]
    live = await conversation(app_client, tid)
    assert live["turns"][1]["positions"] == {
        "context": " A  b\n ψ", "second": "ψ!", "input": odd, "response": odd + "!"}
    await stop(app_client, tid)
    assert (await conversation(app_client, tid))["turns"] == live["turns"]
    rows = await turn_rows(test_engine, tid)
    assert (rows[1].context, rows[1].second_string, rows[1].input, rows[1].answer) == (" A  b\n ψ", "ψ!", odd, odd + "!")
    await app_client.post(f"{URL}/{tid}/start")
    after = await say(app_client, tid, 3, odd)  # the third turn's window is built from the restored second turn
    assert after.json()["turns"][2]["positions"]["context"] == f" A  b\n ψ ψ! {odd}"
    await stop(app_client, tid)
