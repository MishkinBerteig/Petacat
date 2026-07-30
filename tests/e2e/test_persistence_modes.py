"""The three persistence modes (WP3.6, WP3.7, WP3.8).

Fast writes nothing ever, Normal writes the complete state at the two Run boundaries,
Audit writes every state-changing action.  The claims that matter are negative ones —
what a mode does *not* do — and negative claims need tests that would notice.

So Fast Run is checked three ways, because its two requirements fail differently: the
database being untouched, the async engine never being constructed, and no storable
representation being built.  A sink that dutifully buffered records for a writer that is
never called would pass the first two and fail the third, and that is the plausible way
to get Fast Run wrong.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from server.models.run import (
    AuditAction,
    Run,
    RunStateCapture,
    TraceEventRow,
    TrainingSession,
)
from server.services.sinks import MODE_AUDIT, MODE_FAST, MODE_NORMAL

from tests.e2e.conftest import E2E_SEED as SEED

PROBLEM = {"initial": "abc", "modified": "abd", "target": "xyz"}


async def _create(client, mode: str, **kw):
    resp = await client.post("/api/runs", json={**PROBLEM, "seed": SEED, "mode": mode, **kw})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Fast Run
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fast_run_writes_no_rows_anywhere(app_client, db_session):
    """Requirement 1: zero database activity during the run and at its end."""
    before = {
        model: (await db_session.execute(select(func.count()).select_from(model))).scalar()
        for model in (Run, TraceEventRow, RunStateCapture, AuditAction)
    }

    run = await _create(app_client, MODE_FAST)
    await app_client.post(f"/api/runs/{run['run_id']}/run", json={"max_steps": 800})

    for model, count in before.items():
        now = (await db_session.execute(select(func.count()).select_from(model))).scalar()
        assert now == count, f"{model.__tablename__} gained rows during a Fast Run"


@pytest.mark.asyncio
async def test_a_fast_run_has_no_database_identifier(app_client):
    """It cannot: there is no row to take one from.

    The id is negative, which a ``runs.id`` autoincrement can never be — so a Fast
    Run's id cannot be mistaken for a persisted one, and a lookup with it cannot
    accidentally find somebody else's run.
    """
    run = await _create(app_client, MODE_FAST)
    assert run["run_id"] < 0
    assert run["mode"] == MODE_FAST


@pytest.mark.asyncio
async def test_a_fast_run_is_still_fully_observable(app_client):
    """Fast means *not written down*, not *not observable*."""
    run = await _create(app_client, MODE_FAST)
    run_id = run["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 1500})

    info = (await app_client.get(f"/api/runs/{run_id}")).json()
    assert info["codelet_count"] > 0
    assert info["status"] in {"answer_found", "halted", "paused", "gave_up"}

    # The API surface answers in every mode, and answers Fast with nothing.
    commentary = await app_client.get(f"/api/runs/{run_id}/commentary")
    assert commentary.status_code == 200
    assert commentary.json().get("paragraph_count", 0) == 0


@pytest.mark.asyncio
async def test_fast_run_builds_no_storable_representation(app_client):
    """Requirement 2, and the one a well-meaning implementation fails.

    "Buffer now, write later" satisfies "no rows are written" while still formatting
    and holding everything. The sink is inspected directly: it must have no instance
    dictionary to accumulate into at all.
    """
    from server.api.runs import get_run_service

    run = await _create(app_client, MODE_FAST)
    run_id = run["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 800})

    sink = get_run_service()._sinks[run_id]
    with pytest.raises(AttributeError):
        sink.records = []
    assert not hasattr(sink, "__dict__")


@pytest.mark.asyncio
async def test_fast_run_leaves_the_shared_memory_alone(app_client, db_session):
    """A Fast Run gets an ephemeral memory: leaving answers behind is leaving
    something behind, which is exactly what the mode promises not to do."""
    from server.api.runs import get_run_service
    from server.services.run_service import _global_memory

    before = len(_global_memory.answers)
    run = await _create(app_client, MODE_FAST)
    await app_client.post(f"/api/runs/{run['run_id']}/run", json={"max_steps": 2000})

    assert len(_global_memory.answers) == before
    assert get_run_service()._runners[run["run_id"]].ctx.memory is not _global_memory


# ─────────────────────────────────────────────────────────────────────────────
# Normal
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_normal_run_writes_exactly_two_state_captures(app_client, db_session):
    """Two, at the boundaries — not 148, and not one per cycle.

    Fast and Normal differ in exactly one thing, and this is it. Stating it that
    narrowly is what makes Normal cheap and the mode comparison meaningful.
    """
    run = await _create(app_client, MODE_NORMAL)
    run_id = run["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 1500})

    result = await db_session.execute(
        select(RunStateCapture)
        .where(RunStateCapture.run_id == run_id)
        .order_by(RunStateCapture.boundary)
    )
    captures = list(result.scalars().all())
    assert [c.boundary for c in captures] == ["end", "start"]

    start = next(c for c in captures if c.boundary == "start")
    end = next(c for c in captures if c.boundary == "end")
    assert start.codelet_count == 0
    assert end.codelet_count > 0
    assert start.state["format_version"] == end.state["format_version"]


@pytest.mark.asyncio
async def test_a_normal_run_re_executes_from_its_recorded_start_state(app_client, db_session):
    """Reproducibility by re-execution — the promise Normal mode makes.

    Reload the recorded start state into a fresh runner, run it on, and it must reach
    the recorded end state. Not "an equivalent answer": the same structures, the same
    coderack, the same trace, the same activations.
    """
    from server.engine.state_graph import restore_run_state
    from server.engine.runner import EngineRunner
    from server.api.runs import get_run_service

    run = await _create(app_client, MODE_NORMAL)
    run_id = run["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 1200})

    result = await db_session.execute(
        select(RunStateCapture).where(RunStateCapture.run_id == run_id)
    )
    captures = {c.boundary: c.state for c in result.scalars().all()}
    assert set(captures) == {"start", "end"}

    svc = get_run_service()
    replay = EngineRunner(svc.meta)
    replay.init_mcat(PROBLEM["initial"], PROBLEM["modified"], PROBLEM["target"], seed=SEED)
    restore_run_state(replay, captures["start"])
    replay.run_mcat(max_steps=1200)

    recorded_end = captures["end"]
    assert replay.ctx.codelet_count == recorded_end["runner"]["codelet_count"]
    assert round(replay.ctx.temperature.value, 6) == round(
        recorded_end["temperature"]["value"], 6
    )
    assert [e.event_number for e in replay.ctx.trace.events] == [
        e["fields"]["event_number"]
        for ref in recorded_end["trace"]["events"]
        for e in [recorded_end["graph"][ref["$ref"]]]
    ]


@pytest.mark.asyncio
async def test_a_mid_session_normal_run_records_the_memory_it_inherited(
    app_client, db_session
):
    """The one thing that crosses Run boundaries must actually be captured.

    A Normal Run placed *after* other Runs in a Training Session inherits their
    answers, and its start-state capture has to contain them — otherwise "re-execute
    from the recorded start state" would silently start from a different memory.
    """
    first = await _create(app_client, MODE_NORMAL, seed=SEED)
    await app_client.post(f"/api/runs/{first['run_id']}/run", json={"max_steps": 2500})

    second = await _create(app_client, MODE_NORMAL, seed=SEED + 1)
    await app_client.post(f"/api/runs/{second['run_id']}/run", json={"max_steps": 400})

    result = await db_session.execute(
        select(RunStateCapture).where(
            RunStateCapture.run_id == second["run_id"],
            RunStateCapture.boundary == "start",
        )
    )
    start = result.scalars().one().state

    from server.services.run_service import _global_memory
    if not _global_memory.answers:
        pytest.skip("the first run found no answer, so there is nothing to inherit")
    assert len(start["memory"]["answers"]) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Audit
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_records_every_state_changing_action(app_client, db_session):
    """Completeness is the requirement; contemporaneity of writing is not.

    Audit may buffer and flush once at Run end, and does. What it may not do is miss an
    action, because any intermediate state is reconstructed by replaying forward from
    the Run-start capture.
    """
    run = await _create(app_client, MODE_AUDIT)
    run_id = run["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 900})

    result = await db_session.execute(
        select(AuditAction)
        .where(AuditAction.run_id == run_id)
        .order_by(AuditAction.sequence)
    )
    actions = list(result.scalars().all())
    assert actions, "an audit run must record actions"

    # Dense and ordered — the replay order.
    assert [a.sequence for a in actions] == list(range(1, len(actions) + 1))
    assert all(
        earlier.codelet_count <= later.codelet_count
        for earlier, later in zip(actions, actions[1:])
    )

    kinds = {a.action_type for a in actions}
    assert "codelet" in kinds
    assert {"structure_built", "structure_broken"} & kinds


@pytest.mark.asyncio
async def test_audit_records_the_run_start_state_to_replay_from(app_client, db_session):
    """Forward reconstruction needs a starting point as well as the actions."""
    run = await _create(app_client, MODE_AUDIT)
    run_id = run["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 600})

    result = await db_session.execute(
        select(RunStateCapture).where(RunStateCapture.run_id == run_id)
    )
    boundaries = {c.boundary for c in result.scalars().all()}
    assert boundaries == {"start", "end"}


@pytest.mark.asyncio
async def test_audit_actions_carry_before_state_for_later_inversion(app_client, db_session):
    """Phase 0 ships forward stepping only, but backwards scrubbing constrains the
    *format*, not merely the UI — so the format admits it now."""
    run = await _create(app_client, MODE_AUDIT)
    run_id = run["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 600})

    result = await db_session.execute(
        select(AuditAction).where(
            AuditAction.run_id == run_id,
            AuditAction.action_type.like("structure_%"),
        )
    )
    changes = list(result.scalars().all())
    assert changes
    assert all(c.before is not None for c in changes)


# ─────────────────────────────────────────────────────────────────────────────
# Across the modes
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mode_does_not_change_the_run(app_client):
    """The rule the whole design rests on.

    Same problem, same seed, three modes: identical cognition. If this failed, every
    comparison between a Fast training population and a Normal recorded run would be
    meaningless, and the modes would not be modes but three different programs.
    """
    outcomes = []
    for mode in (MODE_FAST, MODE_NORMAL, MODE_AUDIT):
        run = await _create(app_client, mode, seed=4242)
        resp = await app_client.post(
            f"/api/runs/{run['run_id']}/run", json={"max_steps": 1500}
        )
        body = resp.json()
        outcomes.append((body["status"], body["codelet_count"], body["answer"]))

    assert outcomes[0] == outcomes[1] == outcomes[2], outcomes


@pytest.mark.asyncio
async def test_an_unknown_mode_is_rejected(app_client):
    """Defaulting would give a Fast Run to someone who asked for Audit, and the
    missing record would only be noticed when they tried to review it."""
    resp = await app_client.post(
        "/api/runs", json={**PROBLEM, "seed": SEED, "mode": "audti"}
    )
    assert resp.status_code == 400
    assert "audti" in resp.text


@pytest.mark.asyncio
async def test_runs_are_grouped_into_a_training_session(app_client, db_session):
    """WP3.0: the concept already worked; this gives it a representation."""
    run = await _create(app_client, MODE_NORMAL)
    result = await db_session.execute(select(Run).where(Run.id == run["run_id"]))
    row = result.scalars().one()
    assert row.session_id is not None

    sessions = await db_session.execute(
        select(TrainingSession).where(TrainingSession.id == row.session_id)
    )
    assert sessions.scalars().one().ended_at is None


@pytest.mark.asyncio
async def test_config_and_memory_hashes_are_recorded(app_client, db_session):
    """Which configuration and which memory a run saw is part of its identity (WP3.5)."""
    first = await _create(app_client, MODE_NORMAL, seed=99)
    result = await db_session.execute(select(Run).where(Run.id == first["run_id"]))
    row = result.scalars().one()
    assert row.config_hash and len(row.config_hash) == 32
    assert row.memory_hash and len(row.memory_hash) == 32


# ─────────────────────────────────────────────────────────────────────────────
# Session and cleanup lifecycle
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clearing_the_memory_ends_the_training_session(app_client, db_session):
    """A memory clear is the session boundary — and must actually close the row.

    WP3.0 says so and the review UI tells the user so, but nothing was writing
    ``ended_at``: every Run in the database therefore belonged to a single session that
    had been open since the first one, which makes the grouping useless exactly when it
    starts to matter. The symptom was invisible — a session list with one entry looks
    plausible.
    """
    from sqlalchemy import func

    first = await _create(app_client, MODE_NORMAL)
    row = (await db_session.execute(select(Run).where(Run.id == first["run_id"]))).scalars().one()
    original_session = row.session_id
    assert original_session is not None

    # ``DELETE /api/memory``, not the ``POST /api/memory/clear`` the plan text names —
    # the plan is out of date on the route, not the behaviour.
    resp = await app_client.delete("/api/memory")
    assert resp.status_code == 200, resp.text

    closed = (
        await db_session.execute(
            select(TrainingSession).where(TrainingSession.id == original_session)
        )
    ).scalars().one()
    assert closed.ended_at is not None, "the memory clear did not end the session"

    # And the next Run starts a new one.
    second = await _create(app_client, MODE_NORMAL)
    row2 = (await db_session.execute(select(Run).where(Run.id == second["run_id"]))).scalars().one()
    assert row2.session_id != original_session

    open_sessions = (
        await db_session.execute(
            select(func.count())
            .select_from(TrainingSession)
            .where(TrainingSession.ended_at.is_(None))
        )
    ).scalar()
    assert open_sessions == 1


@pytest.mark.asyncio
async def test_deleting_a_run_removes_its_captures_and_audit_log(app_client, db_session):
    """Otherwise a deleted run leaves rows keyed to an id that no longer exists.

    Migration 009 declares no foreign keys — the runtime tables in this schema never
    have — so nothing at the database level would have caught it, and nothing would ever
    have read or cleaned up the orphans.
    """
    from sqlalchemy import func

    run = await _create(app_client, MODE_AUDIT)
    run_id = run["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 400})

    def count(model):
        return db_session.execute(
            select(func.count()).select_from(model).where(model.run_id == run_id)
        )

    assert (await count(RunStateCapture)).scalar() > 0
    assert (await count(AuditAction)).scalar() > 0

    resp = await app_client.delete(f"/api/runs/{run_id}")
    assert resp.status_code in (200, 204)

    assert (await count(RunStateCapture)).scalar() == 0
    assert (await count(AuditAction)).scalar() == 0


# ─────────────────────────────────────────────────────────────────────────────
# Free-running through the API (WP4.4)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_run_can_be_executed_free_running(app_client):
    """The capability has to be *reachable*, not merely implemented.

    `FreeRunningEngine` was built and benchmarked while nothing in the service layer
    drove a run through it, so the whole of Workstream B was unreachable from the
    product. This is the path that makes it real.
    """
    resp = await app_client.post(
        "/api/runs", json={**PROBLEM, "seed": SEED, "mode": MODE_NORMAL, "workers": 4}
    )
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    done = await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 3000})
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["codelet_count"] > 0
    assert body["status"] in {"answer_found", "halted", "gave_up", "paused"}

    telemetry = (await app_client.get(f"/api/runs/{run_id}/telemetry")).json()
    assert telemetry["free_running"] is True
    assert telemetry["workers"] == 4
    assert sum(telemetry["per_worker"]) == telemetry["codelets"]
    assert 0.0 <= telemetry["conflict_rate"] <= 1.0


@pytest.mark.asyncio
async def test_a_free_running_run_is_persisted_like_any_other(app_client, db_session):
    """The ``RunSink`` port's payoff: no mode had to learn about concurrency.

    The engine emits the same events in the same order whether one worker or eight
    produced them, so a free-running Normal run must leave exactly the record a serial
    Normal run leaves.
    """
    resp = await app_client.post(
        "/api/runs", json={**PROBLEM, "seed": 4242, "mode": MODE_NORMAL, "workers": 4}
    )
    run_id = resp.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 3000})

    captures = await db_session.execute(
        select(RunStateCapture).where(RunStateCapture.run_id == run_id)
    )
    assert {c.boundary for c in captures.scalars().all()} == {"start", "end"}

    row = (await db_session.execute(select(Run).where(Run.id == run_id))).scalars().one()
    assert row.status in {"answer_found", "halted", "gave_up"}
    assert row.codelet_count > 0


@pytest.mark.asyncio
async def test_audit_refuses_to_run_free(app_client):
    """Audit is serial by definition, and says so rather than quietly going serial.

    Its forward log reconstructs intermediate states by replay, and under free-running
    the order it records is not the order things happened in. Silently downgrading to
    one worker would produce a correct record of a run the caller did not ask for.
    """
    resp = await app_client.post(
        "/api/runs", json={**PROBLEM, "seed": SEED, "mode": MODE_AUDIT, "workers": 4}
    )
    assert resp.status_code == 400
    assert "serial" in resp.text.lower()


@pytest.mark.asyncio
async def test_one_worker_is_still_the_serial_loop(app_client):
    """The default must not quietly become the parallel path."""
    resp = await app_client.post(
        "/api/runs", json={**PROBLEM, "seed": SEED, "mode": MODE_NORMAL}
    )
    run_id = resp.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 500})
    telemetry = (await app_client.get(f"/api/runs/{run_id}/telemetry")).json()
    assert telemetry["free_running"] is False
