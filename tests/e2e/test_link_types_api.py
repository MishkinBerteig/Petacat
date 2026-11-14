"""The Admin routes for link types, and the change API's link-type ops on a session's configuration."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_the_global_link_types_are_listed_created_changed_and_removed(app_client):
    listing = (await app_client.get("/api/admin/link-types")).json()
    assert [t["name"] for t in listing] == ["category", "instance", "property", "lateral", "lateral_sliplink"]
    assert {t["name"]: t["behaviour"] for t in listing}["lateral_sliplink"] == "slip"

    created = await app_client.post("/api/admin/link-types", json={"name": "near", "description": "d"})
    assert created.status_code == 201, created.text
    assert created.json()["behaviour"] is None and created.json()["display_label"] == "near"
    assert (await app_client.post("/api/admin/link-types", json={"name": "near"})).status_code == 409
    assert (await app_client.post("/api/admin/link-types", json={"name": "x", "behaviour": "sideways"})).status_code == 422

    changed = await app_client.put("/api/admin/link-types/near", json={"behaviour": "lateral"})
    assert changed.status_code == 200 and changed.json()["behaviour"] == "lateral"
    plain = await app_client.put("/api/admin/link-types/near", json={"behaviour": None})
    assert plain.json()["behaviour"] is None
    assert (await app_client.put("/api/admin/link-types/nope", json={"description": "x"})).status_code == 404

    link = await app_client.post("/api/admin/slipnet/links", json={
        "from_node": "plato-a", "to_node": "plato-c", "link_type": "near", "label_node": None,
        "link_length": 20, "fixed_length": True})
    assert link.status_code == 201, link.text
    refused = await app_client.delete("/api/admin/link-types/near")
    assert refused.status_code == 422 and "still has" in refused.text
    unfixed = await app_client.post("/api/admin/slipnet/links", json={
        "from_node": "plato-b", "to_node": "plato-d", "link_type": "near", "label_node": None,
        "link_length": None, "fixed_length": False})
    assert unfixed.status_code == 422 and "fixed length" in unfixed.text
    assert (await app_client.delete(f"/api/admin/slipnet/links/{link.json()['id']}")).status_code == 200
    assert (await app_client.delete("/api/admin/link-types/near")).status_code == 200
    assert (await app_client.delete("/api/admin/link-types/near")).status_code == 404
    assert "near" not in [t["name"] for t in (await app_client.get("/api/admin/link-types")).json()]


@pytest.mark.asyncio
async def test_link_types_are_no_longer_an_enum_table_in_the_admin_enum_editor(app_client):
    got = (await app_client.get("/api/admin/enums")).json()
    assert "link_types" not in got["tables"] and len(got["tables"]) == 17
    assert got["roles"]["link_types"]["column"] == "behaviour"  # the pick list the link-type editor reads
    assert (await app_client.get("/api/admin/enums/link_types")).status_code in (400, 404)


@pytest.mark.asyncio
async def test_the_schema_lists_link_types_with_its_columns(app_client):
    schema = (await app_client.get("/api/configurations/1/schema")).json()
    table = next(t for t in schema["tables"] if t["name"] == "link_types")
    assert table["key"] == ["name"] and {c["name"] for c in table["columns"]} == {
        "name", "display_label", "sort_order", "description", "behaviour"}
    assert {"add_link_type", "remove_link_type"} <= set(schema["ops"]["convenience"])
    assert "link_types" not in schema["vocabulary"]["tables"]
