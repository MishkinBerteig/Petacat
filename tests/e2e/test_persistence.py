"""E2E tests for persistence: snapshot save/restore, DB metadata round-trip.

ALL tests are deterministic: same seed → same results.

Requires: a local Postgres — start it with `scripts/dev.sh db`.
"""

import pytest

from server.engine.metadata import MetadataProvider
from server.services.metadata_service import load_metadata_from_db

SEED = 12345


@pytest.mark.asyncio
async def test_metadata_db_round_trip(db_session):
    """Metadata loaded from DB should match metadata loaded from seed_data/.

    This verifies the seed migration wrote correct data.
    """
    import os
    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    meta_json = MetadataProvider.from_seed_data(seed_dir)
    meta_db = await load_metadata_from_db(db_session)

    # Same number of nodes
    assert len(meta_db.slipnet_node_specs) == len(meta_json.slipnet_node_specs)

    # Same node names
    assert set(meta_db.slipnet_node_specs.keys()) == set(meta_json.slipnet_node_specs.keys())

    # Same conceptual depths
    for name in meta_json.slipnet_node_specs:
        assert (
            meta_db.slipnet_node_specs[name].conceptual_depth
            == meta_json.slipnet_node_specs[name].conceptual_depth
        ), f"Depth mismatch for {name}"

    # Same number of codelet types
    assert len(meta_db.codelet_specs) == len(meta_json.codelet_specs)

    # Same codelet names
    assert set(meta_db.codelet_specs.keys()) == set(meta_json.codelet_specs.keys())

    # Same urgency levels
    assert meta_db.urgency_levels == meta_json.urgency_levels

    # Same number of theme dimensions
    assert len(meta_db.theme_dimensions) == len(meta_json.theme_dimensions)

    # Same demo problem count
    assert len(meta_db.demo_problems) == len(meta_json.demo_problems)


@pytest.mark.asyncio
async def test_codelet_execute_body_round_trip(db_session):
    """Codelet execute_body stored in DB should compile identically."""
    import os
    from server.engine.codelet_dsl.interpreter import CodeletInterpreter
    from server.engine.codelet_dsl.builtins import get_builtins

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    meta_json = MetadataProvider.from_seed_data(seed_dir)
    meta_db = await load_metadata_from_db(db_session)

    interpreter = CodeletInterpreter(builtins=get_builtins())

    for name in meta_json.codelet_specs:
        json_body = meta_json.codelet_specs[name].execute_body
        db_body = meta_db.codelet_specs[name].execute_body
        assert json_body == db_body, f"execute_body mismatch for {name}"

        # Both should compile without errors
        c_json = interpreter.compile(json_body, name=f"json:{name}")
        c_db = interpreter.compile(db_body, name=f"db:{name}")
        assert c_json.is_empty == c_db.is_empty


@pytest.mark.asyncio
async def test_trace_events_persist_without_mid_run_snapshots(app_client, db_session):
    """The record of a stepped run is its Trace, written in one batch (WP3.3).

    This replaces a test that asserted a ``cycle_snapshots`` row existed after fifteen
    codelets and inspected its seven JSONB columns. Those snapshots are retired: they
    were write-only — nothing ever called the ``restore_*`` functions — and cost
    18-27% of engine time to produce 1-6 MB per run that no code path could read.

    What replaces the assertion is the property that actually matters now: stepping a
    run persists its trace events, and it does so without writing snapshots. The events
    are buffered by the run's sink during the step loop and staged once per API call
    rather than awaited per codelet.
    """
    from sqlalchemy import func, select
    from server.models.run import CycleSnapshot, TraceEventRow

    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Far enough for the run to record trace events of its own.
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 1200})

    snapshots = await db_session.execute(
        select(func.count()).select_from(CycleSnapshot).where(CycleSnapshot.run_id == run_id)
    )
    assert snapshots.scalar() == 0

    events = await db_session.execute(
        select(TraceEventRow)
        .where(TraceEventRow.run_id == run_id)
        .order_by(TraceEventRow.event_number)
    )
    rows = list(events.scalars().all())
    assert rows, "a run of this length must record trace events"

    # Event numbers are per-run and dense (WP0.3), which is what makes them usable as
    # the ordering key they are indexed as.
    assert [r.event_number for r in rows] == list(range(1, len(rows) + 1))
    for row in rows:
        assert row.event_type
        assert row.codelet_count >= 0
        assert 0.0 <= row.temperature <= 100.0

@pytest.mark.asyncio
async def test_deterministic_state_at_checkpoint(app_client):
    """Two identical runs should produce identical snapshot state at the same step.

    This verifies end-to-end determinism through the persistence layer.
    """
    # Run 1
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run1_id = resp.json()["run_id"]
    await app_client.post(f"/api/runs/{run1_id}/step", json={"n": 30})
    resp1 = await app_client.get(f"/api/runs/{run1_id}/slipnet")
    slipnet1 = resp1.json()

    # Run 2 — same seed
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run2_id = resp.json()["run_id"]
    await app_client.post(f"/api/runs/{run2_id}/step", json={"n": 30})
    resp2 = await app_client.get(f"/api/runs/{run2_id}/slipnet")
    slipnet2 = resp2.json()

    # Identical slipnet state
    for node_name in slipnet1:
        assert slipnet1[node_name]["activation"] == slipnet2[node_name]["activation"], (
            f"Activation mismatch for {node_name} at step 30: "
            f"{slipnet1[node_name]['activation']} vs {slipnet2[node_name]['activation']}"
        )
