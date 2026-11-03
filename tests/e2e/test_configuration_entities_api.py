"""E2E (C8): the configuration entity routes: list, get, PATCH, rows, export, and the C4 routes
(status, diff, reset, verify) aimed at a Training Mode Session's configuration.

A session and its configuration are made directly through ``create_session_configuration`` (the
session service calls it at creation, S3).  Every test deletes its session at the end, which
removes its configuration by the database cascade.
"""

import pytest
from sqlalchemy import text

from server.models.training_mode_session import TrainingModeSession
from server.services.configurations import create_session_configuration


@pytest.fixture
async def made(db_session):
    """``(session_id, configuration_id)`` of a new session configuration; deleted afterwards."""
    row = TrainingModeSession(name="E2E session", backend="single", policy={})
    db_session.add(row)
    await db_session.flush()
    overrides = [{"op": "insert", "table": "slipnet_node_defs",
                  "row": {"name": "c8-e2e", "short_name": "c8e", "conceptual_depth": 50}}]
    cid = await create_session_configuration(db_session, row.id, "standard", overrides)
    await db_session.commit()
    yield row.id, cid
    await db_session.rollback()
    await db_session.execute(text("DELETE FROM training_mode_sessions WHERE id = :i"), {"i": row.id})
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_has_the_global_configuration_first_then_the_session(app_client, made):
    sid, cid = made
    body = (await app_client.get("/api/configurations")).json()["configurations"]
    assert [c["id"] for c in body] == [1, cid]
    g, s = body
    assert g["name"] == "Metacat Mode: global configuration" and g["mode_label"] == "Metacat Mode"
    assert (s["mode_label"], s["session_state"], s["session_id"]) == ("Training Mode: E2E session", "stopped", sid)
    assert s["differs_from_standard_rows"] == 1 and s["revision"] == 1 and s["last_change"]["source"] == "creation"


@pytest.mark.asyncio
async def test_get_a_configuration_and_unknown_is_404(app_client, made):
    _, cid = made
    got = (await app_client.get(f"/api/configurations/{cid}")).json()
    assert got["id"] == cid and got["kind"] == "session" and got["frozen"] is False
    assert (await app_client.get("/api/configurations/9999")).status_code == 404


@pytest.mark.asyncio
async def test_patch_names_notes_and_freezes_as_a_journaled_revision(app_client, made):
    _, cid = made
    resp = await app_client.patch(f"/api/configurations/{cid}", json={"name": "Renamed", "note": "n", "frozen": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["name"], body["note"], body["frozen"], body["revision"]) == ("Renamed", "n", True, 2)
    assert body["last_change"]["channel"] == "admin_configurations"
    assert (await app_client.patch(f"/api/configurations/{cid}", json={})).status_code == 400
    assert (await app_client.patch(f"/api/configurations/{cid}", json={"name": " "})).status_code == 400
    assert (await app_client.patch("/api/configurations/9999", json={"name": "x"})).status_code == 404
    assert (await app_client.get(f"/api/configurations/{cid}/verify-journal")).json()["ok"]


@pytest.mark.asyncio
async def test_rows_and_export(app_client, made):
    _, cid = made
    tables = (await app_client.get(f"/api/configurations/{cid}/rows")).json()["tables"]
    assert tables["slipnet_node_defs"] >= 1
    rows = (await app_client.get(f"/api/configurations/{cid}/rows", params={"table": "slipnet_node_defs"})).json()
    assert any(r["name"] == "c8-e2e" for r in rows["rows"]) and rows["key_columns"] == ["name"]
    g_rows = (await app_client.get("/api/configurations/1/rows", params={"table": "slipnet_node_defs"})).json()
    assert not any(r["name"] == "c8-e2e" for r in g_rows["rows"])  # Metacat Mode never sees it
    assert (await app_client.get(f"/api/configurations/{cid}/rows", params={"table": "runs"})).status_code == 422
    resp = await app_client.get(f"/api/configurations/{cid}/export")
    assert resp.status_code == 200 and "attachment" in resp.headers["content-disposition"]
    bundle = resp.json()
    assert bundle["configuration"]["id"] == cid and "slipnet_node_defs" in bundle["data"]["tables"]


@pytest.mark.asyncio
async def test_status_diff_reset_and_verify_work_for_the_session_configuration(app_client, made):
    _, cid = made
    st = (await app_client.get(f"/api/configurations/{cid}/status")).json()
    assert st["kind"] == "session" and st["differs_rows"] == 1
    d = (await app_client.get(f"/api/configurations/{cid}/diff")).json()
    assert (d["added"], d["count"]) == (1, 1)
    reset = await app_client.post(f"/api/configurations/{cid}/reset-to-standard", json={"confirm": "reset"})
    assert reset.status_code == 200 and reset.json()["wrote"] and reset.json()["revision"] == 2
    assert (await app_client.get(f"/api/configurations/{cid}/status")).json()["equals_standard"]
    assert (await app_client.get(f"/api/configurations/{cid}/verify-journal")).json()["ok"]
