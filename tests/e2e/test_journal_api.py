"""E2E (C13): the journal's views over HTTP.

``GET /api/journal`` (and its filters, one entry, the pending-entry merge), ``GET
/api/configurations/{id}/as-of``, ``GET /api/journal/where-did-name-go``, ``POST
/api/journal/check-names`` and ``POST /api/configurations/{id}/restore``.  Every test that
writes ends by resetting the global configuration to the Metacat Standard Configuration.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from server.models.training_mode_session import TrainingModeSession
from server.services.configuration_store import set_live_source
from server.services.configurations import create_session_configuration


async def _reset(app_client):
    resp = await app_client.post("/api/configurations/1/reset-to-standard", json={"confirm": "reset"})
    assert resp.status_code == 200, resp.text


@pytest.fixture
async def clean(app_client):
    await _reset(app_client)
    yield app_client
    set_live_source(None)
    await _reset(app_client)


def _node(name: str) -> dict:
    return {"op": "insert", "table": "slipnet_node_defs",
            "row": {"name": name, "short_name": name[-4:], "conceptual_depth": 40}}


async def _post(client, *ops, configuration_id=1, **fields):
    body = {"source": "admin", "actor": "tester", "base_mode": "rebase", "ops": list(ops), **fields}
    resp = await client.post(f"/api/configurations/{configuration_id}/changes", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_the_journal_lists_filters_and_shows_one_entry(clean):
    await _post(clean, _node("c13-e2e-a"), note="make a", group_id="e2e-g")
    await _post(clean, {"op": "rename_node", "old": "c13-e2e-a", "new": "c13-e2e-b"}, actor="rita")
    body = (await clean.get("/api/journal", params={"configuration_id": 1, "limit": 2})).json()
    assert [e["actor"] for e in body["entries"]] == ["rita", "tester"]
    assert body["entries"][0]["revision"] > body["entries"][1]["revision"] and body["limit"] == 2
    assert body["entries"][0]["pending"] is False and "resolved" not in body["entries"][0]

    got = (await clean.get("/api/journal", params={"group_id": "e2e-g"})).json()
    assert [e["note"] for e in got["entries"]] == ["make a"]
    keyed = (await clean.get("/api/journal", params={
        "configuration_id": 1, "table": "slipnet_node_defs", "key": '{"name": "c13-e2e-b"}'})).json()
    assert [e["actor"] for e in keyed["entries"]] == ["rita"]
    one = (await clean.get(f"/api/journal/{got['entries'][0]['id']}")).json()
    assert one["proposed"][0]["op"] == "insert" and one["resolved"] and "before" in one

    assert (await clean.get("/api/journal/999999999")).status_code == 404
    assert (await clean.get("/api/journal", params={"configuration_id": 9999})).status_code == 404
    assert (await clean.get("/api/journal", params={"key": '{"name": "x"}'})).status_code == 409
    assert (await clean.get("/api/journal", params={"table": "nope"})).status_code == 409
    assert (await clean.get("/api/journal", params={"table": "slipnet_node_defs", "key": "[1]"})).status_code == 422
    assert (await clean.get("/api/journal", params={"limit": 0})).status_code == 422


@pytest.mark.asyncio
async def test_as_of_by_revision_and_by_time(clean):
    made = await _post(clean, _node("c13-e2e-c"))
    r_made = made["version_after"]
    await _post(clean, {"op": "remove_node", "name": "c13-e2e-c"})
    row = (await clean.get("/api/configurations/1/as-of", params={
        "revision": r_made, "table": "slipnet_node_defs", "key": '{"name": "c13-e2e-c"}'})).json()
    assert row["row"]["conceptual_depth"] == 40 and row["revision"] == r_made
    gone = (await clean.get("/api/configurations/1/as-of", params={
        "revision": r_made + 1, "table": "slipnet_node_defs", "key": '{"name": "c13-e2e-c"}'})).json()
    assert gone["row"] is None
    rows = (await clean.get("/api/configurations/1/as-of", params={
        "revision": r_made, "table": "slipnet_node_defs"})).json()["rows"]
    assert "c13-e2e-c" in {r["name"] for r in rows}
    stamp = next(e for e in (await clean.get("/api/journal", params={"configuration_id": 1})).json()["entries"]
                 if e["revision"] == r_made)["occurred_at"]
    by_time = (await clean.get("/api/configurations/1/as-of", params={
        "time": stamp, "table": "slipnet_node_defs", "key": '{"name": "c13-e2e-c"}'})).json()
    assert by_time["revision"] == r_made and by_time["row"] is not None

    assert (await clean.get("/api/configurations/1/as-of")).status_code == 400
    assert (await clean.get("/api/configurations/1/as-of", params={"revision": 1, "time": stamp})).status_code == 400
    assert (await clean.get("/api/configurations/1/as-of", params={"revision": 10 ** 6})).status_code == 404
    assert (await clean.get("/api/configurations/9999/as-of", params={"revision": 0})).status_code == 404
    assert (await clean.get("/api/configurations/1/as-of", params={"revision": 1, "key": "{}"})).status_code == 400


@pytest.mark.asyncio
async def test_where_did_the_name_go_and_check_names(clean):
    await _post(clean, _node("c13-e2e-d"), _node("c13-e2e-keep"))
    await _post(clean, {"op": "merge_nodes", "keep": "c13-e2e-keep", "drop": "c13-e2e-d"}, actor="mo")
    story = (await clean.get("/api/journal/where-did-name-go", params={"name": "c13-e2e-d"})).json()
    assert [e["event"] for e in story["events"]] == ["created", "merged_into"]
    assert story["resolves"] is False and story["current_name"] == "c13-e2e-keep"
    assert story["restorable"]["table"] == "slipnet_node_defs"
    checked = (await clean.post("/api/journal/check-names", json={
        "configuration_id": 1, "names": ["c13-e2e-d", "c13-e2e-keep", "plato-letter-category"]})).json()
    assert [u["name"] for u in checked["unresolved"]] == ["c13-e2e-d"]
    assert (await clean.get("/api/journal/where-did-name-go", params={"name": "x", "configuration_id": 9999})).status_code == 404
    assert (await clean.post("/api/journal/check-names", json={"names": 5})).status_code == 422


@pytest.mark.asyncio
async def test_restore_and_undo_are_new_entries(clean):
    made = await _post(clean, _node("c13-e2e-e"))
    r_made = made["version_after"]
    gone = await _post(clean, {"op": "remove_node", "name": "c13-e2e-e"}, group_id="e2e-del")
    restored = await clean.post("/api/configurations/1/restore", json={
        "entity": {"table": "slipnet_node_defs", "key": {"name": "c13-e2e-e"}}, "as_of_revision": r_made,
        "note": "back"})
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["changed"] and body["revision"] == gone["version_after"] + 1
    entry = (await clean.get(f"/api/journal/{body['entry_id']}")).json()
    assert (entry["source"], entry["channel"], entry["note"]) == ("restore", "admin_restore", "back")
    nodes = (await clean.get("/api/configurations/1/rows", params={"table": "slipnet_node_defs"})).json()
    assert "c13-e2e-e" in {r["name"] for r in nodes["rows"]}

    # undo the deletion by its group: the node is already back, so the inverse no longer applies
    refused = await clean.post("/api/configurations/1/restore", json={"undo_group": "e2e-del"})
    assert refused.status_code == 409

    undone = await clean.post("/api/configurations/1/restore", json={"undo_batch": restored.json()["entry_id"]})
    assert undone.status_code == 200 and undone.json()["changed"]
    nodes = (await clean.get("/api/configurations/1/rows", params={"table": "slipnet_node_defs"})).json()
    assert "c13-e2e-e" not in {r["name"] for r in nodes["rows"]}
    verify = (await clean.get("/api/configurations/1/verify-journal")).json()
    assert verify["ok"], verify


@pytest.mark.asyncio
async def test_restore_refuses_bad_requests(clean):
    url = "/api/configurations/1/restore"
    assert (await clean.post(url, json={})).status_code == 400
    assert (await clean.post(url, json={"undo_batch": 1, "undo_group": "g"})).status_code == 400
    assert (await clean.post(url, json={"entity": {"table": "slipnet_node_defs", "key": {"name": "x"}}})).status_code == 400
    missing = await clean.post(url, json={
        "entity": {"table": "slipnet_node_defs", "key": {"name": "c13-never"}}, "as_of_revision": 0})
    assert missing.status_code == 404
    assert (await clean.post(url, json={"undo_batch": 999999999})).status_code == 404
    assert (await clean.post("/api/configurations/9999/restore", json={"undo_group": "g"})).status_code == 404


@pytest.fixture
async def made(db_session):
    row = TrainingModeSession(name="C13 session", backend="single", policy={})
    db_session.add(row)
    await db_session.flush()
    cid = await create_session_configuration(db_session, row.id, "standard", None)
    await db_session.commit()
    yield row.id, cid
    set_live_source(None)
    await db_session.rollback()
    await db_session.execute(text("DELETE FROM training_mode_sessions WHERE id = :i"), {"i": row.id})
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_session_configuration_has_history_and_a_live_one_shows_pending(clean, made):
    sid, cid = made
    await _post(clean, _node("c13-e2e-s"), configuration_id=cid, source="external", actor="x")
    listed = (await clean.get("/api/journal", params={"configuration_id": cid})).json()
    assert [e["source"] for e in listed["entries"]] == ["external"] and listed["live"] is None

    from server.services.journal import PendingEntry
    from datetime import datetime, timezone

    pending = [PendingEntry(revision=2, source="learner", actor="l", proposed=[], resolved=[],
                            before=[], occurred_at=datetime.now(timezone.utc), note="in memory")]
    set_live_source(lambda session_id: SimpleNamespace(
        state="running", document=None, revision=2, saved_through=1, unsaved=1, pending=pending))
    live = (await clean.get("/api/journal", params={"configuration_id": cid})).json()
    assert [(e["revision"], e["pending"], e["label"]) for e in live["entries"]] == [
        (2, True, "not yet saved"), (1, False, "")]
    assert live["live"]["unsaved"] == 1 and live["live"]["saved_through"] == 1
    # restore and undo wait for a live session to stop
    refused = await clean.post(f"/api/configurations/{cid}/restore", json={"undo_batch": listed["entries"][0]["id"]})
    assert refused.status_code == 409 and "live" in refused.text
    set_live_source(None)
    ok = await clean.post(f"/api/configurations/{cid}/restore", json={"undo_batch": listed["entries"][0]["id"]})
    assert ok.status_code == 200 and ok.json()["changed"]
    asof = (await clean.get(f"/api/configurations/{cid}/as-of", params={
        "revision": 1, "table": "slipnet_node_defs", "key": '{"name": "c13-e2e-s"}'})).json()
    assert asof["row"] is not None
