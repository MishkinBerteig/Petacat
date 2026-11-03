"""E2E (C9a): compare any two configurations and apply rows from one to the other.

``GET /api/configurations/compare?a=&b=`` and ``POST /api/configurations/{id}/apply-from``.
Two Training Mode Sessions' configurations are made directly through
``create_session_configuration`` (the session service does this at creation); every test
deletes its sessions at the end, which removes their configurations by the database cascade.
Metacat Mode's global configuration is only read.
"""

import pytest
from sqlalchemy import text

from server.models.training_mode_session import TrainingModeSession
from server.services.configurations import create_session_configuration

NODE = {"name": "c9a-e2e", "short_name": "c9a", "conceptual_depth": 50}


@pytest.fixture
async def pair(db_session):
    """``(cid_a, cid_b)``: A carries one extra node, B equals the Metacat Standard Configuration."""
    ids: list[int] = []
    cids: list[int] = []
    for name, overrides in (
        ("C9a A", [{"op": "insert", "table": "slipnet_node_defs", "row": NODE}]),
        ("C9a B", []),
    ):
        row = TrainingModeSession(name=name, backend="single", policy={})
        db_session.add(row)
        await db_session.flush()
        ids.append(row.id)
        cids.append(await create_session_configuration(db_session, row.id, "standard", overrides))
    await db_session.commit()
    yield cids[0], cids[1]
    await db_session.rollback()
    for i in ids:
        await db_session.execute(text("DELETE FROM training_mode_sessions WHERE id = :i"), {"i": i})
    await db_session.commit()


@pytest.mark.asyncio
async def test_compare_names_both_sides_and_diffs_by_table_and_key(app_client, pair):
    a, b = pair
    body = (await app_client.get("/api/configurations/compare", params={"a": a, "b": b})).json()
    assert body["a"]["id"] == a and body["b"]["id"] == b
    assert body["a"]["mode_label"] == "Training Mode: C9a A"
    assert (body["count"], body["added"], body["removed"], body["changed"]) == (1, 1, 0, 0)
    row = body["rows"][0]
    assert (row["table"], row["key"], row["change"]) == ("slipnet_node_defs", {"name": "c9a-e2e"}, "added")
    assert row["a"]["short_name"] == "c9a" and row["b"] is None
    flipped = (await app_client.get("/api/configurations/compare", params={"a": b, "b": a})).json()
    assert flipped["removed"] == 1 and flipped["rows"][0]["b"]["short_name"] == "c9a"


@pytest.mark.asyncio
async def test_compare_with_the_standard_and_with_the_global_configuration(app_client, pair):
    a, b = pair
    vs_standard = (await app_client.get("/api/configurations/compare", params={"a": a, "b": "standard"})).json()
    assert vs_standard["b"]["name"] == "Metacat Standard Configuration" and vs_standard["count"] == 1
    same = (await app_client.get("/api/configurations/compare", params={"a": b, "b": "standard"})).json()
    assert same["same"] is True and same["count"] == 0
    vs_global = await app_client.get("/api/configurations/compare", params={"a": a, "b": 1})
    assert vs_global.status_code == 200
    assert vs_global.json()["b"]["mode_label"] == "Metacat Mode"


@pytest.mark.asyncio
async def test_compare_refusals(app_client, pair):
    a, _ = pair
    assert (await app_client.get("/api/configurations/compare", params={"a": a, "b": 99999})).status_code == 404
    assert (await app_client.get("/api/configurations/compare", params={"a": a, "b": "nope"})).status_code == 400
    assert (await app_client.get("/api/configurations/compare", params={"a": a})).status_code == 422


@pytest.mark.asyncio
async def test_apply_from_previews_then_adds_a_row_the_other_side_lacks(app_client, pair):
    a, b = pair
    rows = [{"table": "slipnet_node_defs", "key": {"name": "c9a-e2e"}}]
    before = (await app_client.get(f"/api/configurations/{b}")).json()["revision"]
    preview = await app_client.post(
        f"/api/configurations/{b}/apply-from", json={"source": a, "rows": rows, "dry_run": True})
    assert preview.status_code == 200, preview.text
    assert preview.json()["persisted"] is False and preview.json()["ops"] == 1
    assert (await app_client.get(f"/api/configurations/{b}")).json()["revision"] == before

    done = await app_client.post(
        f"/api/configurations/{b}/apply-from",
        json={"source": a, "rows": rows, "note": "bring the node across"})
    assert done.status_code == 200, done.text
    assert done.json()["wrote"] is True and done.json()["source"] == a
    after = (await app_client.get(f"/api/configurations/{b}")).json()
    assert after["revision"] == before + 1
    assert after["last_change"]["source"] == "restore" and after["last_change"]["actor"] == "admin"
    assert (await app_client.get("/api/configurations/compare", params={"a": a, "b": b})).json()["count"] == 0
    assert (await app_client.get(f"/api/configurations/{b}/verify-journal")).json()["ok"]


@pytest.mark.asyncio
async def test_apply_from_removes_and_updates_and_lists_what_already_matches(app_client, pair):
    a, b = pair
    # B gets a changed node description through the change API, so A and B differ in a column.
    edit = await app_client.post(f"/api/configurations/{b}/changes", json={
        "source": "admin", "actor": "admin", "base_mode": "rebase",
        "ops": [{"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                 "fields": {"description": "changed in B"}}],
    })
    assert edit.status_code == 200, edit.text
    rows = [{"table": "slipnet_node_defs", "key": {"name": "plato-a"}},
            {"table": "slipnet_node_defs", "key": {"name": "c9a-e2e"}},
            {"table": "slipnet_node_defs", "key": {"name": "plato-b"}}]
    # Make B equal A: 'a' is updated back, the node only A has is added, 'b' already matches.
    done = (await app_client.post(
        f"/api/configurations/{b}/apply-from", json={"source": a, "rows": rows})).json()
    assert done["wrote"] is True and done["ops"] == 2
    assert done["skipped_rows"] == [{"table": "slipnet_node_defs", "key": {"name": "plato-b"}}]
    assert (await app_client.get("/api/configurations/compare", params={"a": a, "b": b})).json()["count"] == 0
    # Applying the standard to A removes its extra node (restore-selected, generalised).
    gone = (await app_client.post(
        f"/api/configurations/{a}/apply-from",
        json={"source": "standard", "rows": [{"table": "slipnet_node_defs", "key": {"name": "c9a-e2e"}}]})).json()
    assert gone["wrote"] is True
    assert (await app_client.get(f"/api/configurations/{a}/status")).json()["equals_standard"]


@pytest.mark.asyncio
async def test_apply_from_refusals(app_client, pair):
    a, b = pair
    row = [{"table": "slipnet_node_defs", "key": {"name": "c9a-e2e"}}]
    assert (await app_client.post(f"/api/configurations/{a}/apply-from", json={"source": a, "rows": row})).status_code == 400
    assert (await app_client.post(f"/api/configurations/{a}/apply-from", json={"source": "x", "rows": row})).status_code == 400
    assert (await app_client.post("/api/configurations/99999/apply-from", json={"source": a, "rows": row})).status_code == 404
    unknown = [{"table": "slipnet_node_defs", "key": {"name": "no-such-node"}}]
    assert (await app_client.post(f"/api/configurations/{b}/apply-from", json={"source": a, "rows": unknown})).status_code == 422
    assert (await app_client.post(f"/api/configurations/{b}/apply-from", json={"source": a, "rows": []})).status_code == 422
