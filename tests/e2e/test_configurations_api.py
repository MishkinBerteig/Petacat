"""E2E (C4): ``/api/configurations/{id}/...`` status, diff, reset, restore-selected, verify.

Edits go through ``/api/admin`` (journal entries), so the comparison with the Metacat Standard
Configuration is the real one.  Every test ends by resetting, so the shared test database is
left equal to the standard.
"""

import pytest

from server.services.journal_views import read_entries


async def _reset(app_client):
    resp = await app_client.post("/api/configurations/1/reset-to-standard", json={"confirm": "reset"})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
async def clean(app_client):
    await _reset(app_client)
    yield app_client
    await _reset(app_client)


async def _edit(client) -> str:
    """One changed row (a parameter) and one added row (a node)."""
    params = (await client.get("/api/admin/params")).json()
    name = params[0]["name"]
    value = params[0]["value"]
    new_value = "7" if str(value) != "7" else "8"
    resp = await client.put(f"/api/admin/params/{name}", json={"value": new_value})
    assert resp.status_code == 200, resp.text
    node = {"name": "c4-e2e-node", "short_name": "c4e", "conceptual_depth": 40}
    assert (await client.post("/api/admin/slipnet/nodes", json=node)).status_code == 201
    return name


@pytest.mark.asyncio
async def test_status_reports_equality_then_the_difference(clean):
    st = (await clean.get("/api/configurations/1/status")).json()
    assert st["differs_rows"] == 0 and st["equals_standard"]
    assert st["configuration_id"] == 1 and st["kind"] == "global"
    await _edit(clean)
    st2 = (await clean.get("/api/configurations/1/status")).json()
    assert st2["differs_rows"] == 2 and not st2["equals_standard"]
    assert st2["config_hash"] != st["config_hash"]
    assert st2["standard_config_hash"] == st["standard_config_hash"]
    assert st2["revision"] == st["revision"] + 2


@pytest.mark.asyncio
async def test_diff_lists_exactly_the_edited_rows(clean):
    name = await _edit(clean)
    d = (await clean.get("/api/configurations/1/diff")).json()
    assert (d["count"], d["added"], d["removed"], d["changed"]) == (2, 1, 0, 1)
    by = {(r["table"], r["change"]): r for r in d["rows"]}
    assert by[("engine_params", "changed")]["key"] == {"name": name}
    assert by[("slipnet_node_defs", "added")]["key"] == {"name": "c4-e2e-node"}


@pytest.mark.asyncio
async def test_reset_needs_the_typed_confirmation(clean):
    await _edit(clean)
    for body in ({}, {"confirm": ""}, {"confirm": "yes"}):
        resp = await clean.post("/api/configurations/1/reset-to-standard", json=body)
        assert resp.status_code == 400
    assert (await clean.get("/api/configurations/1/status")).json()["differs_rows"] == 2


@pytest.mark.asyncio
async def test_reset_is_a_reset_journal_entry_and_leaves_the_journal_verified(clean, db_session):
    await _edit(clean)
    before = (await clean.get("/api/configurations/1/status")).json()["revision"]
    body = await _reset(clean)
    assert body["wrote"] and body["revision"] == before + 1
    st = (await clean.get("/api/configurations/1/status")).json()
    assert st["equals_standard"] and st["differs_rows"] == 0
    await db_session.rollback()
    last = (await read_entries(db_session, 1))[-1]
    assert (last["source"], last["revision"]) == ("reset", before + 1)
    verify = (await clean.get("/api/configurations/1/verify-journal")).json()
    assert verify["ok"] and verify["problems"] == []


@pytest.mark.asyncio
async def test_restore_selected_restores_only_the_chosen_rows(clean):
    name = await _edit(clean)
    resp = await clean.post("/api/configurations/1/restore-selected", json={
        "rows": [{"table": "engine_params", "key": {"name": name}}]})
    assert resp.status_code == 200 and resp.json()["wrote"]
    d = (await clean.get("/api/configurations/1/diff")).json()
    assert [(r["table"], r["change"]) for r in d["rows"]] == [("slipnet_node_defs", "added")]


@pytest.mark.asyncio
async def test_unknown_rows_and_configurations_are_refused(clean):
    bad = await clean.post("/api/configurations/1/restore-selected", json={
        "rows": [{"table": "engine_params", "key": {"name": "no-such-param"}}]})
    assert bad.status_code == 422
    empty = await clean.post("/api/configurations/1/restore-selected", json={"rows": []})
    assert empty.status_code == 422
    assert (await clean.get("/api/configurations/999/status")).status_code == 404
    assert (await clean.post("/api/configurations/999/reset-to-standard",
                             json={"confirm": "reset"})).status_code == 404


@pytest.mark.asyncio
async def test_the_seed_export_endpoint_is_gone(clean):
    assert (await clean.post("/api/admin/export-to-seed-data")).status_code in (404, 405)
