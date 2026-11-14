"""A link length can be a fraction over HTTP, and a node reports how often it has been noticed.

The Admin routes and the change API take a fractional link length and give it back as it is; a whole one is
printed as it always was (``90``, never ``90.0``); ``nan``, ``inf``, ``1e999`` and ``10**400`` are refused on
every route; ``noticings`` is shown on the node, carried by the export only when it is not 0, and changed by the
change API's ``adjust``.  Every test ends by resetting the global configuration to the Metacat Standard
Configuration.
"""

from __future__ import annotations

import json

import pytest

LINK = {"from_node": "plato-a", "to_node": "plato-c", "link_type": "lateral", "label_node": ""}


async def _reset(client):
    resp = await client.post("/api/configurations/1/reset-to-standard", json={"confirm": "reset"})
    assert resp.status_code == 200, resp.text


@pytest.fixture
async def clean(app_client):
    await _reset(app_client)
    yield app_client
    await _reset(app_client)


def batch(*ops, **more):
    return {"source": "admin", "actor": "tester", "base_mode": "rebase", "ops": list(ops), **more}


async def links(client):
    return {(l["from_node"], l["to_node"], l["link_type"]): l for l in (await client.get("/api/admin/slipnet/links")).json()}


@pytest.mark.asyncio
async def test_the_admin_routes_take_a_fractional_link_length_and_print_a_whole_one_as_a_whole_number(clean):
    body = {"from_node": "plato-a", "to_node": "plato-c", "link_type": "lateral", "label_node": None,
            "link_length": 89.875, "fixed_length": True}
    created = await clean.post("/api/admin/slipnet/links", json=body)
    assert created.status_code == 201, created.text
    assert created.json()["link_length"] == 89.875
    assert (await links(clean))[("plato-a", "plato-c", "lateral")]["link_length"] == 89.875
    link_id = created.json()["id"]
    whole = await clean.put(f"/api/admin/slipnet/links/{link_id}", json={**body, "link_length": 90.0})
    assert whole.status_code == 200, whole.text
    assert '"link_length":90,' in whole.text.replace(" ", "")  # 90, never 90.0
    exported = (await clean.get("/api/admin/export")).json()
    ours = next(l for l in exported["slipnet_links"] if (l["from_node"], l["to_node"], l["link_type"]) == (
        "plato-a", "plato-c", "lateral"))
    assert ours["link_length"] == 90 and type(ours["link_length"]) is int
    assert all(type(l["link_length"]) is int for l in exported["slipnet_links"] if l["link_length"] is not None)
    assert (await clean.put(f"/api/admin/slipnet/links/{link_id}", json={**body, "link_length": 0.5})).json()["link_length"] == 0.5


@pytest.mark.asyncio
async def test_the_standard_configurations_export_is_whole_numbers_and_has_no_noticings(clean):
    exported = (await clean.get("/api/admin/export")).json()
    lengths = [l["link_length"] for l in exported["slipnet_links"] if l["link_length"] is not None]
    assert lengths and all(type(x) is int for x in lengths)
    assert all("noticings" not in n for n in exported["slipnet_nodes"])
    nodes = (await clean.get("/api/admin/slipnet/nodes")).json()
    assert {n["noticings"] for n in nodes} == {0}


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "1e999", "1" + "0" * 400])
async def test_a_link_length_that_is_not_finite_is_refused_on_every_route(clean, raw):
    headers = {"content-type": "application/json"}
    payload = ('{"from_node": "plato-a", "to_node": "plato-c", "link_type": "lateral", "label_node": null, '
               f'"link_length": {raw}, "fixed_length": true}}')
    refused = await clean.post("/api/admin/slipnet/links", content=payload, headers=headers)
    assert 400 <= refused.status_code < 500, refused.text
    assert ("plato-a", "plato-c", "lateral") not in await links(clean)
    ok = await clean.post("/api/configurations/1/changes", json=batch(
        {"op": "add_link", "from": "plato-a", "to": "plato-c", "type": "lateral", "fixed": True, "length": 30}))
    assert ok.status_code == 200, ok.text
    route = await clean.post("/api/configurations/1/changes", content=json.dumps(batch(
        {"op": "adjust", "table": "slipnet_link_defs", "key": LINK, "field": "link_length", "by": 0})).replace(
        '"by": 0', f'"by": {raw}'), headers=headers)
    assert 400 <= route.status_code < 500, route.text
    assert (await links(clean))[("plato-a", "plato-c", "lateral")]["link_length"] == 30


@pytest.mark.asyncio
async def test_the_change_api_adds_and_adjusts_a_fraction_and_under_skip_drops_only_the_bad_op(clean):
    resp = await clean.post("/api/configurations/1/changes", headers={"content-type": "application/json"}, content=json.dumps(batch(
        {"op": "add_link", "from": "plato-a", "to": "plato-c", "type": "lateral", "fixed": True, "length": 90.125},
        {"op": "adjust", "table": "slipnet_link_defs", "key": LINK, "field": "link_length", "by": float("nan")},
        {"op": "adjust", "table": "slipnet_link_defs", "key": LINK, "field": "link_length", "by": -0.125},
        {"op": "adjust", "table": "slipnet_node_defs", "key": {"name": "plato-a"}, "field": "noticings", "by": 0.5},
        {"op": "adjust", "table": "slipnet_node_defs", "key": {"name": "plato-a"}, "field": "noticings", "by": 3},
        on_op_failure="skip")))  # json.dumps writes NaN, which a client library may refuse to send
    assert resp.status_code == 200, resp.text
    assert sorted(s["op"] for s in resp.json()["skipped"]) == [1, 3]
    assert (await links(clean))[("plato-a", "plato-c", "lateral")]["link_length"] == 90
    node = {n["name"]: n for n in (await clean.get("/api/admin/slipnet/nodes")).json()}["plato-a"]
    assert node["noticings"] == 3
    exported = {n["name"]: n for n in (await clean.get("/api/admin/export")).json()["slipnet_nodes"]}
    assert exported["plato-a"]["noticings"] == 3 and "noticings" not in exported["plato-b"]
    # a whole-number count is never a fraction, and has no range
    down = await clean.post("/api/configurations/1/changes", json=batch(
        {"op": "adjust", "table": "slipnet_node_defs", "key": {"name": "plato-a"}, "field": "noticings", "by": -10}))
    assert down.status_code == 200
    node = {n["name"]: n for n in (await clean.get("/api/admin/slipnet/nodes")).json()}["plato-a"]
    assert node["noticings"] == -7


@pytest.mark.asyncio
async def test_the_schema_types_a_link_length_as_a_number_and_noticings_as_a_whole_number(clean):
    schema = (await clean.get("/api/configurations/1/schema")).json()
    columns = {t["name"]: {c["name"]: c for c in t["columns"]} for t in schema["tables"]}
    assert columns["slipnet_link_defs"]["link_length"]["type"] == "float"
    assert columns["slipnet_node_defs"]["noticings"]["type"] == "int"
