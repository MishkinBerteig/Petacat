"""E2E (S6): the Training Mode Session routes of the evolution plan 3.13 that carry a session's
configuration: ``POST /changes`` (the external route), ``GET /journal``, ``GET /configuration``,
``GET /configuration/diff``, ``GET /slipnet`` and ``GET /export?what=configuration|journal``.

The state routes, the summary and run fields and the service-level change behaviour are tested in
``test_training_mode_sessions_api.py``, ``test_session_configuration.py`` and
``test_session_stop_start.py``; this file tests the HTTP surface on top of them.
"""

import pytest

from tests.e2e.test_session_configuration import (  # noqa: F401  (fixtures and helpers)
    PARAM, _stop_default_swarm, create_with, external, manual, sessions, set_param,
)
from tests.e2e.test_training_mode_sessions_api import session_state, stop

BASE = "/api/training-mode/sessions"


async def start_paused(client, tid):
    resp = await client.post(f"{BASE}/{tid}/start", json={"paused": True})
    assert resp.status_code == 200, resp.text
    return resp.json()


def body(*ops, **extra) -> dict:
    """A batch for the route: no ``source``, so the route's default (external) applies."""
    out = external(*ops, **extra)
    del out["source"]
    return out


# ---------------------------------------------------------------------------
# POST /changes: the external route in each state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stopped_session_writes_an_external_batch_at_once(app_client, sessions):
    tid = (await create_with(app_client))["id"]
    resp = await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(16)))
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["persisted"] is True and report["version_before"] == 0 and report["version_after"] == 1
    entries = (await app_client.get(f"{BASE}/{tid}/journal")).json()["entries"]
    assert [(e["source"], e["revision"], e["pending"]) for e in entries] == [("external", 1, False)]
    state = await session_state(app_client, tid)
    assert state["source"] == "stored" and state["configuration"]["version"] == 1


@pytest.mark.asyncio
async def test_a_running_or_paused_session_holds_the_batch_in_memory(app_client, sessions):
    tid = (await create_with(app_client, seeds_per_problem=100000))["id"]
    await start_paused(app_client, tid)
    resp = await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(16)))
    assert resp.status_code == 200 and resp.json()["persisted"] is False
    assert resp.json()["batch_id"] is None and resp.json()["version_after"] == 1
    live = await session_state(app_client, tid)
    assert live["source"] == "live" and live["unsaved"]["configuration_batches"] == 1
    assert live["saved_through"]["configuration_revision"] == 0
    resumed = await app_client.post(f"{BASE}/{tid}/resume")
    assert resumed.status_code == 200
    again = await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(17)))
    assert again.status_code == 200 and again.json()["persisted"] is False and again.json()["version_after"] == 2
    await stop(app_client, tid)
    stored = await session_state(app_client, tid)
    assert stored["source"] == "stored" and stored["configuration"]["version"] == 2
    assert (await app_client.get(f"{BASE}/{tid}/journal")).json()["total"] == 2


@pytest.mark.asyncio
async def test_starting_and_stopping_refuse_a_change_with_409_busy(app_client, sessions):
    tid = (await create_with(app_client))["id"]
    await start_paused(app_client, tid)
    lt = sessions._live[tid]
    lt.status = "stopping"
    resp = await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(16)))
    assert resp.status_code == 409
    assert resp.json()["error"] == "busy" and resp.json()["ok"] is False
    lt.status = "paused"
    sessions._starting.add(tid)
    try:
        resp = await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(16)))
        assert resp.status_code == 409 and resp.json()["error"] == "busy"
    finally:
        sessions._starting.discard(tid)
    assert (await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(16)))).status_code == 200


@pytest.mark.asyncio
async def test_every_learning_source_may_use_the_route_and_the_source_is_recorded(app_client, sessions):
    tid = (await create_with(app_client))["id"]
    for value, source in ((11, "learner"), (12, "admin"), (13, "external")):
        resp = await app_client.post(
            f"{BASE}/{tid}/changes", json={**body(set_param(value)), "source": source})
        assert resp.status_code == 200, resp.text
    entries = (await app_client.get(f"{BASE}/{tid}/journal")).json()["entries"]
    assert [e["source"] for e in entries] == ["external", "admin", "learner"]  # newest first
    configuration = await app_client.get(f"{BASE}/{tid}/configuration", params={"table": "engine_params"})
    assert any(r["name"] == PARAM and r["value"] == "13" for r in configuration.json()["rows"])


@pytest.mark.asyncio
async def test_refusals_have_the_change_apis_shape(app_client, sessions):
    tid = (await create_with(app_client))["id"]
    url = f"{BASE}/{tid}/changes"
    bad = await app_client.post(url, json={"ops": "nope"})
    assert bad.status_code == 400 and bad.json()["ok"] is False and bad.json()["error"] == "malformed"
    unknown_field = await app_client.post(url, json={**body(set_param(16)), "colour": "red"})
    assert unknown_field.status_code == 400
    wrong_config = await app_client.post(url, json={**body(set_param(16)), "configuration_id": 1})
    assert wrong_config.status_code == 400 and wrong_config.json()["error"] == "malformed"
    assert (await app_client.post(f"{BASE}/424242/changes", json=body(set_param(16)))).status_code == 404
    assert (await app_client.post(url, json=body(set_param(16)))).status_code == 200
    stale = await app_client.post(url, json={**body(set_param(17)), "base_version": 0, "base_mode": "strict"})
    assert stale.status_code == 409 and stale.json()["error"] == "stale"
    # a table that is not part of the configuration (an Episodic Memory row, a run) cannot be named
    other = await app_client.post(url, json=body({"op": "delete", "table": "training_mode_session_runs", "key": {"id": 1}}))
    assert 400 <= other.status_code < 500 and other.json()["ok"] is False
    assert (await app_client.get(f"{BASE}/{tid}/journal")).json()["total"] == 1  # only the good one


@pytest.mark.asyncio
async def test_a_dry_run_changes_nothing(app_client, sessions):
    tid = (await create_with(app_client))["id"]
    resp = await app_client.post(f"{BASE}/{tid}/changes", json={**body(set_param(16)), "dry_run": True})
    assert resp.status_code == 200 and resp.json()["dry_run"] is True
    assert (await session_state(app_client, tid))["configuration"]["version"] == 0
    assert (await app_client.get(f"{BASE}/{tid}/journal")).json()["total"] == 0


# ---------------------------------------------------------------------------
# GET /journal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_journal_timeline_filters_and_labels_a_live_sessions_pending_entries(app_client, sessions):
    tid = (await create_with(app_client, seeds_per_problem=100000))["id"]
    await app_client.post(f"{BASE}/{tid}/changes", json={**body(set_param(11)), "source": "admin"})
    await start_paused(app_client, tid)
    await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(12)))
    await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(13)))
    out = (await app_client.get(f"{BASE}/{tid}/journal")).json()
    assert out["source"] == "live" and out["total"] == 3
    assert [(e["revision"], e["pending"], e["label"]) for e in out["entries"]] == [
        (3, True, "not yet saved"), (2, True, "not yet saved"), (1, False, "")]
    assert set(out["entries"][0]) >= {"revision", "source", "actor", "counts", "config_hash", "episode_version"}
    assert out["entries"][0]["counts"]["update"] == 1 and "resolved" not in out["entries"][0]
    assert out["saved_through"]["configuration_revision"] == 1 and out["unsaved"]["configuration_batches"] == 2
    only_admin = (await app_client.get(f"{BASE}/{tid}/journal", params={"source": "admin"})).json()
    assert [e["revision"] for e in only_admin["entries"]] == [1]
    window = (await app_client.get(f"{BASE}/{tid}/journal", params={"from": 2, "to": 2, "detail": True})).json()
    assert [e["revision"] for e in window["entries"]] == [2] and window["entries"][0]["resolved"]
    paged = (await app_client.get(f"{BASE}/{tid}/journal", params={"limit": 1, "offset": 1})).json()
    assert [e["revision"] for e in paged["entries"]] == [2] and paged["total"] == 3
    assert (await app_client.get(f"{BASE}/{tid}/journal", params={"limit": 0})).status_code == 422
    assert (await app_client.get(f"{BASE}/424242/journal")).status_code == 404
    await stop(app_client, tid)
    stored = (await app_client.get(f"{BASE}/{tid}/journal")).json()
    assert stored["source"] == "stored" and [e["pending"] for e in stored["entries"]] == [False] * 3


# ---------------------------------------------------------------------------
# GET /configuration, /configuration/diff, /slipnet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_configuration_at_a_version_stored_and_live(app_client, sessions):
    tid = (await create_with(app_client, seeds_per_problem=100000))["id"]
    await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(21)))
    await start_paused(app_client, tid)
    await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(22)))
    await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(23)))

    def value(rows):
        return int(next(r["value"] for r in rows if r["name"] == PARAM))

    current = (await app_client.get(f"{BASE}/{tid}/configuration")).json()
    assert current["version"] == 2 + 1 and current["source"] == "live" and "tables" in current
    assert current["tables"]["slipnet_node_defs"] > 0
    live_rows = (await app_client.get(f"{BASE}/{tid}/configuration", params={"table": "engine_params"})).json()
    assert value(live_rows["rows"]) == 23 and live_rows["key_columns"] == ["name"]
    stored_v1 = (await app_client.get(f"{BASE}/{tid}/configuration", params={"version": 1, "table": "engine_params"})).json()
    assert stored_v1["version"] == 1 and value(stored_v1["rows"]) == 21
    base = (await app_client.get(f"{BASE}/{tid}/configuration", params={"version": 0})).json()
    assert base["version"] == 0 and base["config_hash"] != current["config_hash"]
    held = await app_client.get(f"{BASE}/{tid}/configuration", params={"version": 2})
    assert held.status_code == 409 and "memory only" in held.json()["detail"]
    assert (await app_client.get(f"{BASE}/{tid}/configuration", params={"version": 9})).status_code == 404
    assert (await app_client.get(f"{BASE}/{tid}/configuration", params={"table": "runs"})).status_code == 422
    assert (await app_client.get(f"{BASE}/{tid}/configuration", params={"version": -1})).status_code == 422
    await stop(app_client, tid)
    at_two = (await app_client.get(f"{BASE}/{tid}/configuration", params={"version": 2, "table": "engine_params"})).json()
    assert at_two["source"] == "stored" and value(at_two["rows"]) == 22


@pytest.mark.asyncio
async def test_the_diff_between_two_versions(app_client, sessions):
    tid = (await create_with(app_client))["id"]
    node = {"op": "insert", "table": "slipnet_node_defs",
            "row": {"name": "s6-extra", "short_name": "s6x", "conceptual_depth": 50}}
    await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(31)))
    await app_client.post(f"{BASE}/{tid}/changes", json=body(node))
    diff = (await app_client.get(f"{BASE}/{tid}/configuration/diff", params={"from": 0})).json()
    assert (diff["from"], diff["to"], diff["added"], diff["changed"], diff["removed"]) == (0, 2, 1, 1, 0)
    assert {(r["table"], r["change"]) for r in diff["rows"]} == {
        ("engine_params", "changed"), ("slipnet_node_defs", "added")}
    one = (await app_client.get(f"{BASE}/{tid}/configuration/diff", params={"from": 1, "to": 2})).json()
    assert one["count"] == 1 and one["rows"][0]["to"]["name"] == "s6-extra" and one["rows"][0]["from"] is None
    back = (await app_client.get(f"{BASE}/{tid}/configuration/diff", params={"from": 2, "to": 1})).json()
    assert back["removed"] == 1
    same = (await app_client.get(f"{BASE}/{tid}/configuration/diff", params={"from": 2, "to": 2})).json()
    assert same["same"] is True and same["rows"] == []
    assert (await app_client.get(f"{BASE}/{tid}/configuration/diff")).status_code == 422
    assert (await app_client.get(f"{BASE}/{tid}/configuration/diff", params={"from": 0, "to": 9})).status_code == 404


@pytest.mark.asyncio
async def test_the_slipnet_projection_at_a_version(app_client, sessions):
    tid = (await create_with(app_client))["id"]
    node = {"op": "insert", "table": "slipnet_node_defs",
            "row": {"name": "s6-extra", "short_name": "s6x", "conceptual_depth": 50}}
    await app_client.post(f"{BASE}/{tid}/changes", json=body(node))
    now = (await app_client.get(f"{BASE}/{tid}/slipnet")).json()
    first = (await app_client.get(f"{BASE}/{tid}/slipnet", params={"version": 0})).json()
    assert now["version"] == 1 and first["version"] == 0 and now["source"] == "stored"
    assert len(now["nodes"]) == len(first["nodes"]) + 1 and len(now["links"]) == len(first["links"]) > 0
    assert len(first["layout"]) > 0 and first["unplaced"] == []
    assert now["unplaced"] == ["s6-extra"]
    assert (await app_client.get(f"{BASE}/424242/slipnet")).status_code == 404


# ---------------------------------------------------------------------------
# GET /export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_the_configuration_and_the_journal(app_client, sessions):
    tid = (await create_with(app_client))["id"]
    await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(41)))
    await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(42)))
    resp = await app_client.get(f"{BASE}/{tid}/export", params={"what": "configuration"})
    assert resp.status_code == 200 and "attachment" in resp.headers["content-disposition"]
    assert resp.headers["content-type"].startswith("application/json")
    bundle = resp.json()
    assert bundle["format"] == "petacat-configuration" and bundle["configuration"]["version"] == 2
    assert bundle["configuration"]["session_id"] == tid and "slipnet_node_defs" in bundle["data"]["tables"]
    old = (await app_client.get(f"{BASE}/{tid}/export", params={"what": "configuration", "version": 1})).json()
    assert old["configuration"]["version"] == 1 and old["configuration"]["config_hash"] != bundle["configuration"]["config_hash"]
    journal = (await app_client.get(f"{BASE}/{tid}/export", params={"what": "journal"})).json()
    assert journal["format"] == "petacat-session-journal" and journal["count"] == 2
    assert [e["revision"] for e in journal["entries"]] == [1, 2]  # oldest first, in full
    assert all(e["resolved"] and e["before"] is not None and e["proposed"] for e in journal["entries"])
    assert (await app_client.get(f"{BASE}/{tid}/export", params={"what": "journal", "format": "csv"})).status_code == 400
    assert (await app_client.get(f"{BASE}/{tid}/export", params={"what": "nonsense"})).status_code == 422
    assert (await app_client.get(f"{BASE}/424242/export", params={"what": "journal"})).status_code == 404
    csv = await app_client.get(f"{BASE}/{tid}/export", params={"what": "problems"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")


@pytest.mark.asyncio
async def test_a_live_sessions_export_says_live_and_holds_pending_entries(app_client, sessions):
    tid = (await create_with(app_client, seeds_per_problem=100000))["id"]
    await start_paused(app_client, tid)
    await app_client.post(f"{BASE}/{tid}/changes", json=body(set_param(51)))
    config = await app_client.get(f"{BASE}/{tid}/export", params={"what": "configuration"})
    assert config.headers["x-export-source"] == "live" and config.json()["configuration"]["version"] == 1
    journal = (await app_client.get(f"{BASE}/{tid}/export", params={"what": "journal"})).json()
    assert journal["source"] == "live" and journal["count"] == 1 and journal["entries"][0]["pending"] is True
    await stop(app_client, tid)
    assert (await app_client.get(f"{BASE}/{tid}/export", params={"what": "journal"})).json()["entries"][0]["pending"] is False


# ---------------------------------------------------------------------------
# The state routes carry persisted / saved_through / unsaved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_routes_label_a_live_session_and_a_stopped_one(app_client, sessions):
    tid = (await create_with(app_client, seeds_per_problem=100000))["id"]
    stopped = await session_state(app_client, tid)
    assert stopped["state"] == "stopped" and stopped["source"] == "stored" and stopped["persisted"] is True
    started = await start_paused(app_client, tid)
    assert started["state"] == "paused" and started["source"] == "live" and started["persisted"] is False
    assert set(started["saved_through"]) == {"stopped_at", "configuration_revision", "episode_version"}
    assert set(started["unsaved"]) >= {"configuration_batches"}
    for route, state in (("resume", "running"), ("pause", "paused")):
        out = (await app_client.post(f"{BASE}/{tid}/{route}")).json()
        assert out["state"] == state and out["persisted"] is False and out["source"] == "live"
    cancelled = (await app_client.post(f"{BASE}/{tid}/cancel")).json()
    assert cancelled["state"] == "paused" and cancelled["persisted"] is False
    listed = (await app_client.get(BASE)).json()["sessions"]
    assert [s["source"] for s in listed if s["id"] == tid] == ["live"]
    done = await stop(app_client, tid)
    assert done["state"] == "stopped" and done["source"] == "stored" and done["persisted"] is True
    assert done["saved_through"]["stopped_at"] is not None
