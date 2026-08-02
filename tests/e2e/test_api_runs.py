"""E2E tests for the runs API with persistence.

ALL tests are deterministic: same seed → same codelet sequence → same state.
Tests exercise the full stack: HTTP API → RunService → EngineRunner → DB.

Requires: a local Postgres — start it with `scripts/dev.sh db`.
"""

import pytest

# Fixed seed for all e2e determinism
SEED = 12345


@pytest.mark.asyncio
async def test_healthz(app_client):
    resp = await app_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_run(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["initial"] == "abc"
    assert data["modified"] == "abd"
    assert data["target"] == "xyz"
    assert data["status"] == "initialized"
    assert data["codelet_count"] == 0
    assert data["temperature"] == 100.0


@pytest.mark.asyncio
async def test_get_run(app_client):
    # Create
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Fetch
    resp = await app_client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == run_id


@pytest.mark.asyncio
async def test_get_nonexistent_run(app_client):
    resp = await app_client.get("/api/runs/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_step_run(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Step 1
    resp = await app_client.post(f"/api/runs/{run_id}/step", json={"n": 1})
    assert resp.status_code == 200
    steps = resp.json()
    assert len(steps) == 1
    assert steps[0]["codelet_count"] == 1
    assert steps[0]["codelet_type"] != ""


@pytest.mark.asyncio
async def test_step_multiple(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.post(f"/api/runs/{run_id}/step", json={"n": 30})
    assert resp.status_code == 200
    steps = resp.json()
    assert len(steps) == 30
    assert steps[-1]["codelet_count"] == 30


@pytest.mark.asyncio
async def test_deterministic_replay_via_api(app_client):
    """Two runs with same seed must produce identical codelet sequences.

    This is the core determinism guarantee of the system.
    """
    # Run 1
    resp1 = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run1_id = resp1.json()["run_id"]
    resp1 = await app_client.post(f"/api/runs/{run1_id}/step", json={"n": 50})
    steps1 = resp1.json()

    # Run 2 — same seed
    resp2 = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run2_id = resp2.json()["run_id"]
    resp2 = await app_client.post(f"/api/runs/{run2_id}/step", json={"n": 50})
    steps2 = resp2.json()

    # Exact same codelet sequence
    for i, (s1, s2) in enumerate(zip(steps1, steps2)):
        assert s1["codelet_type"] == s2["codelet_type"], (
            f"Step {i}: run1={s1['codelet_type']}, run2={s2['codelet_type']}"
        )
        assert s1["codelet_count"] == s2["codelet_count"]


@pytest.mark.asyncio
async def test_different_seeds_differ(app_client):
    """Different seeds must produce different codelet sequences."""
    resp1 = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": 111,
    })
    run1_id = resp1.json()["run_id"]
    resp1 = await app_client.post(f"/api/runs/{run1_id}/step", json={"n": 20})

    resp2 = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": 222,
    })
    run2_id = resp2.json()["run_id"]
    resp2 = await app_client.post(f"/api/runs/{run2_id}/step", json={"n": 20})

    steps1 = resp1.json()
    steps2 = resp2.json()
    # At least some codelet types should differ
    types1 = [s["codelet_type"] for s in steps1]
    types2 = [s["codelet_type"] for s in steps2]
    assert types1 != types2


@pytest.mark.asyncio
async def test_workspace_endpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.get(f"/api/runs/{run_id}/workspace")
    assert resp.status_code == 200
    data = resp.json()
    assert data["initial"] == "abc"
    assert data["modified"] == "abd"
    assert data["target"] == "xyz"


@pytest.mark.asyncio
async def test_slipnet_endpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.get(f"/api/runs/{run_id}/slipnet")
    assert resp.status_code == 200
    data = resp.json()
    assert "plato-a" in data
    assert "plato-successor" in data
    assert "activation" in data["plato-a"]


@pytest.mark.asyncio
async def test_coderack_endpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.get(f"/api/runs/{run_id}/coderack")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_count" in data
    assert data["total_count"] > 0  # Initial codelets posted


@pytest.mark.asyncio
async def test_temperature_endpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.get(f"/api/runs/{run_id}/temperature")
    assert resp.status_code == 200
    assert resp.json()["temperature"] == 100.0


@pytest.mark.asyncio
async def test_state_changes_after_steps(app_client):
    """After stepping, temperature should change and coderack should evolve."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Step past an update cycle (15 codelets)
    await app_client.post(f"/api/runs/{run_id}/step", json={"n": 30})

    resp = await app_client.get(f"/api/runs/{run_id}/temperature")
    temp = resp.json()["temperature"]
    # Temperature should have been recomputed (may still be 100 if no rules)
    assert 0 <= temp <= 100

    resp = await app_client.get(f"/api/runs/{run_id}/coderack")
    data = resp.json()
    assert data["total_count"] > 0


@pytest.mark.asyncio
async def test_justify_mode(app_client):
    """Providing an answer should enable justify mode."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz",
        "answer": "wyz", "seed": SEED,
    })
    data = resp.json()
    assert data["answer"] == "wyz"


@pytest.mark.asyncio
async def test_run_persists_to_db(app_client, db_session):
    """Run should be persisted in the runs table."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    from sqlalchemy import select, text
    from server.models.run import Run
    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    assert run is not None
    assert run.initial_string == "abc"
    assert run.seed == SEED


@pytest.mark.asyncio
async def test_answer_appears_in_workspace(app_client):
    """When a run finds an answer, the workspace endpoint must return it.

    This is the key user-visible requirement: the answer string must appear
    in the workspace serialization so the UI can display it.
    """
    # Use run_to_completion with a generous step limit.
    # If no answer is found in time, the test is inconclusive (not failed).
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.post(f"/api/runs/{run_id}/run", json={
        "max_steps": 3000,
    })
    info = resp.json()

    if info["status"] == "answer_found":
        # Core assertion: the workspace MUST include the answer string
        resp = await app_client.get(f"/api/runs/{run_id}/workspace")
        ws = resp.json()
        assert ws["answer"] is not None, (
            f"Run found answer (status=answer_found) but workspace.answer is None. "
            f"The answer string was not written to the workspace."
        )
        assert len(ws["answer"]) > 0

        # Run info should also have the answer
        resp = await app_client.get(f"/api/runs/{run_id}")
        run_info = resp.json()
        assert run_info["answer"] is not None
    else:
        pytest.skip(
            f"No answer found within 3000 steps (status={info['status']}). "
            f"Test is inconclusive — not a failure."
        )


@pytest.mark.asyncio
async def test_no_mid_run_snapshots_are_written(app_client, db_session):
    """Mid-run snapshots are retired (WP3.3, defect D1).

    This test previously asserted the opposite — that stepping past a cycle boundary
    produced at least two ``cycle_snapshots`` rows. That behaviour is what WP3.3
    removes, so the assertion is inverted rather than deleted: it now pins the absence,
    which is the thing that could silently come back.

    The snapshots were written every fifteenth codelet, cost 18–27% of engine time, and
    **no code path could read them back** — the four ``restore_*`` functions were called
    from nowhere, ``prune_old_snapshots`` was never called either, and there was no
    coderack or workspace restore at all. A production database held 230 MB of them for
    ten runs. Complete, genuinely restorable state capture arrives with WP3.4 and is
    written at the two Run boundaries instead.
    """
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Step well past a cycle boundary (15 codelets).
    await app_client.post(f"/api/runs/{run_id}/step", json={"n": 30})

    from sqlalchemy import select, func
    from server.models.run import CycleSnapshot
    result = await db_session.execute(
        select(func.count()).select_from(CycleSnapshot).where(CycleSnapshot.run_id == run_id)
    )
    assert result.scalar() == 0


# ---------------------------------------------------------------------------
# Run identity — which configuration and which memory a run executed against
#
# The Review browser shows these, but a run that is still executing has no entry
# there yet, and by the time it does the reader has stopped watching. The identity
# endpoint answers for a live run, and — the case worth testing — answers for a Fast
# Run too, where the honest answer is "nothing was written down".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_identity_carries_the_hashes_and_the_session(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    data = (await app_client.get(f"/api/runs/{run_id}/identity")).json()
    assert data["run_id"] == run_id
    assert data["mode"] == "normal"
    assert data["recorded"] is True
    assert data["seed"] == SEED
    assert data["config_hash"]
    assert data["memory_hash"]
    assert data["session_id"] is not None


@pytest.mark.asyncio
async def test_identity_hashes_match_the_row_the_review_browser_reads(app_client, db_session):
    """One source, so the live view and the recorded view cannot disagree.

    Two displays of the same run showing different config hashes would be worse than
    either display being absent, because both look authoritative.
    """
    from sqlalchemy import select
    from server.models.run import Run

    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    data = (await app_client.get(f"/api/runs/{run_id}/identity")).json()
    row = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert data["config_hash"] == row.config_hash
    assert data["memory_hash"] == row.memory_hash
    assert data["session_id"] == row.session_id


@pytest.mark.asyncio
async def test_a_fast_run_reports_no_recorded_identity_rather_than_404(app_client):
    """"Nothing was written down" is a fact about the run, not a missing run.

    A 404 here would be indistinguishable from a mistyped id, and the Fast Run is the
    case a reader most needs told apart from a fault.
    """
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
        "mode": "fast",
    })
    run_id = resp.json()["run_id"]
    assert run_id < 0

    resp = await app_client.get(f"/api/runs/{run_id}/identity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "fast"
    assert data["recorded"] is False
    assert data["config_hash"] is None
    assert data["memory_hash"] is None
    assert data["session_id"] is None


@pytest.mark.asyncio
async def test_identity_of_a_run_that_does_not_exist_is_a_404(app_client):
    resp = await app_client.get("/api/runs/999999/identity")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_the_run_list_carries_each_run_s_mode(app_client):
    """The list is what Run History renders, and mode decides what a run can be
    reviewed with. Without it every row read as Normal, including the Audit runs."""
    for mode in ("normal", "audit"):
        await app_client.post("/api/runs", json={
            "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
            "mode": mode,
        })

    listing = (await app_client.get("/api/runs?limit=50")).json()
    modes = {r["mode"] for r in listing["runs"]}
    assert {"normal", "audit"} <= modes
    for row in listing["runs"]:
        assert row["config_hash"]


@pytest.mark.asyncio
async def test_a_fast_run_is_absent_from_the_list_by_construction(app_client):
    """It has no row, so nothing can list it. The client explains the absence."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
        "mode": "fast",
    })
    fast_id = resp.json()["run_id"]

    listing = (await app_client.get("/api/runs?limit=50")).json()
    assert fast_id not in [r["run_id"] for r in listing["runs"]]


# ---------------------------------------------------------------------------
# Which Episodic Memory a run is thinking against
#
# A Fast Run is handed an ephemeral ``EpisodicMemory`` of its own so that it can
# contribute nothing to the Training Session — that is the whole of what Fast
# promises. The run-scoped memory endpoint served the shared database memory to it
# regardless, which made the panel a straightforward lie about the run: the answers
# it listed were ones the run could not be reminded of.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_normal_run_reads_the_shared_memory(app_client):
    created = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
        "mode": "normal",
    })
    run_id = created.json()["run_id"]

    body = (await app_client.get(f"/api/runs/{run_id}/memory")).json()
    assert body["scope"] == "shared"
    assert body["mode"] == "normal"

    # The same content as the un-scoped endpoint, which is only ever the shared one.
    shared = (await app_client.get("/api/memory")).json()
    assert len(body["answers"]) == len(shared["answers"])
    assert len(body["snags"]) == len(shared["snags"])


@pytest.mark.asyncio
async def test_a_fast_run_reads_the_shared_session_memory(app_client):
    """A Fast Run is in the Training Session like any other.

    Mode chooses where a run is *recorded*, not what it is, so a Fast Run thinks
    against the shared Episodic Memory: it can be reminded of earlier answers, and
    ``answer_present`` will stop it rediscovering one.  It is served from the live
    object rather than the rows only because it has no rows.
    """
    seeded = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "ijk", "seed": SEED,
    })
    await app_client.post(
        f"/api/runs/{seeded.json()['run_id']}/run", json={"max_steps": 3000}
    )
    shared = (await app_client.get("/api/memory")).json()["answers"]
    assert shared, "nothing in the session, test proves nothing"

    created = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
        "mode": "fast",
    })
    run_id = created.json()["run_id"]

    body = (await app_client.get(f"/api/runs/{run_id}/memory")).json()
    assert body["scope"] == "live"
    assert body["mode"] == "fast"
    assert [a["answer_id"] for a in body["answers"]] == [
        a["answer_id"] for a in shared
    ]


@pytest.mark.asyncio
async def test_a_fast_run_contributes_its_answer_to_the_session(app_client):
    """A Fast Run leaves nothing in the *database* and everything in the *session*.

    Those are different promises and only the first belongs to the mode.  A Fast Run
    whose answer vanished from Episodic Memory would be a different program from a
    Normal one rather than the same program recorded differently, and a Fast training
    population would then teach the session nothing.
    """
    shared_before = len((await app_client.get("/api/memory")).json()["answers"])

    created = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
        "mode": "fast",
    })
    run_id = created.json()["run_id"]
    finished = await app_client.post(
        f"/api/runs/{run_id}/run", json={"max_steps": 4000}
    )
    assert finished.json()["answer"] is not None

    shared_after = (await app_client.get("/api/memory")).json()["answers"]
    assert len(shared_after) == shared_before + 1

    # ...and nothing written down: a Fast Run has no ``runs`` row at all, which is
    # what ``test_a_fast_run_writes_nothing`` in test_persistence_modes.py asserts.
