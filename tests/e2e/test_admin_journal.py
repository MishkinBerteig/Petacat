"""E2E (C6): every Admin write to the configuration is a journal entry, written by the layer.

Each ``/api/admin`` route that writes configuration builds resolved ops and calls
``write_immediate``: one entry and one revision per request, ``source = admin``,
``actor = admin``.  The journal then replays to the current tables (``verify_journal``).
"""

import pytest

from server.services.journal_views import current_state, read_entries, undo, verify_journal


async def _entries(db_session, after: int = 0) -> list[dict]:
    # a fresh transaction each time: the session's snapshot would hide the request's commit
    await db_session.rollback()
    return await read_entries(db_session, 1, after=after)


async def _revision(db_session) -> int:
    entries = await _entries(db_session)
    return entries[-1]["revision"] if entries else 0


@pytest.mark.asyncio
async def test_a_create_update_delete_each_write_one_admin_entry(app_client, db_session):
    start = await _revision(db_session)
    node = {"name": "plato-journal-test", "short_name": "jt", "conceptual_depth": 40}
    assert (await app_client.post("/api/admin/slipnet/nodes", json=node)).status_code == 201
    assert (await app_client.put(
        "/api/admin/slipnet/nodes/plato-journal-test", json={**node, "conceptual_depth": 41}
    )).status_code == 200
    assert (await app_client.delete("/api/admin/slipnet/nodes/plato-journal-test")).status_code == 200

    new = await _entries(db_session, after=start)
    assert [e["revision"] for e in new] == [start + 1, start + 2, start + 3]
    assert {(e["source"], e["actor"], e["channel"]) for e in new} == {("admin", "admin", "admin_editor")}
    assert [op["op"] for e in new for op in e["resolved"]] == ["insert", "update", "delete"]
    assert new[1]["resolved"][0]["set"] == {"conceptual_depth": 41}
    assert new[1]["before"][0]["conceptual_depth"] == 40
    assert (await verify_journal(db_session)).ok


@pytest.mark.asyncio
async def test_an_unchanged_update_writes_no_entry(app_client, db_session):
    name = "expiration_period"
    params = {p["name"]: p for p in (await app_client.get("/api/admin/params")).json()}
    before = await _revision(db_session)
    resp = await app_client.put(
        f"/api/admin/params/{name}", json={"value": params[name]["value"]}
    )
    assert resp.status_code == 200
    assert await _revision(db_session) == before


@pytest.mark.asyncio
async def test_a_refused_request_writes_nothing_and_keeps_its_status(app_client, db_session):
    before = await _revision(db_session)
    missing = await app_client.put("/api/admin/params/no_such_parameter", json={"value": "1"})
    assert missing.status_code == 404
    duplicate = await app_client.post(
        "/api/admin/urgency-levels", json={"name": "very_high", "value": 1}
    )
    assert duplicate.status_code == 409
    assert await _revision(db_session) == before


@pytest.mark.asyncio
async def test_deleting_a_node_journals_the_rows_that_follow_it_and_undo_restores_them(
    app_client, db_session
):
    export = (await app_client.get("/api/admin/export")).json()
    bound = export["slipnet_node_roles"][0]["node_name"]
    start = await _revision(db_session)
    state_before = await current_state(db_session)
    assert (await app_client.delete(f"/api/admin/slipnet/nodes/{bound}")).status_code == 200

    (entry,) = await _entries(db_session, after=start)
    assert entry["resolved"][-1] == {
        "op": "delete", "table": "slipnet_node_defs", "key": {"name": bound}
    }
    assert "slipnet_node_roles" in {op["table"] for op in entry["resolved"]}

    await db_session.rollback()
    await undo(db_session, 1, entry_id=entry["id"], actor="admin")
    await db_session.rollback()
    assert await current_state(db_session) == state_before
    assert (await verify_journal(db_session)).ok


@pytest.mark.asyncio
async def test_an_import_is_one_entry_with_source_import(app_client, db_session):
    export = (await app_client.get("/api/admin/export")).json()
    start = await _revision(db_session)
    changed = [dict(p) for p in export["engine_params"]]
    target = next(p for p in changed if p["name"] == "expiration_period")
    original = target["value"]
    target["value"] = "501"
    resp = await app_client.post("/api/admin/import", json={"engine_params": changed})
    assert resp.status_code == 200, resp.text
    try:
        (entry,) = await _entries(db_session, after=start)
        assert entry["source"] == "import" and entry["channel"] == "admin_import"
        assert entry["resolved"] == [{
            "op": "update", "table": "engine_params", "key": {"name": "expiration_period"},
            "set": {"value": "501"},
        }]
    finally:
        target["value"] = original
        assert (await app_client.post("/api/admin/import", json={"engine_params": changed})).status_code == 200
    assert (await verify_journal(db_session)).ok
