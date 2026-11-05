"""E2E (C14b): the change API over HTTP, and the Admin editors as its clients.

``POST /api/configurations/{id}/changes`` and ``GET /api/configurations/{id}/schema``; the G6
classes of refusal with their codes and the op's index; ``dry_run``; ``strict`` against
``rebase``; and the editors' journal entries, whose proposed ops are the editor's own batch.
Every test that writes ends by resetting the global configuration to the Metacat Standard
Configuration, so the shared test database is left equal to it.
"""

import pytest

from server.services.journal_views import read_entries, verify_journal


async def _reset(app_client):
    resp = await app_client.post("/api/configurations/1/reset-to-standard", json={"confirm": "reset"})
    assert resp.status_code == 200, resp.text


@pytest.fixture
async def clean(app_client):
    await _reset(app_client)
    yield app_client
    await _reset(app_client)


async def _revision(client) -> int:
    return (await client.get("/api/configurations/1/status")).json()["revision"]


async def _entries(db_session, after: int = 0) -> list[dict]:
    await db_session.rollback()  # a fresh snapshot: the request committed on its own connection
    return await read_entries(db_session, 1, after=after)


def _batch(*ops, **fields) -> dict:
    return {"source": "admin", "actor": "tester", "base_mode": "rebase", "ops": list(ops), **fields}


# ---------------------------------------------------------------- the changes endpoint


@pytest.mark.asyncio
async def test_a_batch_is_applied_and_reported(clean, db_session):
    start = await _revision(clean)
    resp = await clean.post("/api/configurations/1/changes", json=_batch(
        {"op": "set_param", "name": "expiration_period", "to": 777},
        {"op": "add_node", "name": "c14b-node",
         "fields": {"short_name": "c14", "conceptual_depth": 33}},
        note="two changes",
    ))
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["ok"] and report["persisted"] and not report.get("dry_run")
    assert report["configuration_id"] == 1
    assert (report["version_before"], report["version_after"]) == (start, start + 1)
    assert [a["op_index"] for a in report["applied"]] == list(range(len(report["applied"])))
    for field in ("skipped", "cascaded", "dangling", "affected", "effects", "advisories"):
        assert isinstance(report[field], list)

    (entry,) = await _entries(db_session, after=start)
    assert entry["id"] == report["batch_id"]
    assert (entry["source"], entry["actor"], entry["note"]) == ("admin", "tester", "two changes")
    assert [op["op"] for op in entry["proposed"]] == ["set_param", "add_node"]
    assert (await verify_journal(db_session)).ok


@pytest.mark.asyncio
async def test_dry_run_reports_and_writes_nothing(clean, db_session):
    start = await _revision(clean)
    resp = await clean.post("/api/configurations/1/changes", json=_batch(
        {"op": "set_param", "name": "expiration_period", "to": 778}, dry_run=True))
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["dry_run"] is True and report["persisted"] is False and report["batch_id"] is None
    assert report["version_after"] == start and len(report["applied"]) == 1
    assert await _revision(clean) == start
    assert await _entries(db_session, after=start) == []
    params = {p["name"]: p["value"] for p in (await clean.get("/api/admin/params")).json()}
    assert params["expiration_period"] != "778"


@pytest.mark.asyncio
async def test_strict_refuses_a_stale_base_and_rebase_goes_on(clean):
    start = await _revision(clean)
    set_a = {"op": "set_param", "name": "expiration_period", "to": 701}
    set_b = {"op": "set_param", "name": "expiration_period", "to": 702}
    ok = await clean.post("/api/configurations/1/changes", json=_batch(
        set_a, base_mode="strict", base_version=start))
    assert ok.status_code == 200, ok.text

    stale = await clean.post("/api/configurations/1/changes", json=_batch(
        set_b, base_mode="strict", base_version=start))
    assert stale.status_code == 409 and stale.json()["error"] == "stale"
    assert stale.json()["ok"] is False and stale.json()["problems"]

    missing = await clean.post("/api/configurations/1/changes", json=_batch(set_b, base_mode="strict"))
    assert missing.status_code == 400 and missing.json()["error"] == "malformed"

    rebased = await clean.post("/api/configurations/1/changes", json=_batch(
        set_b, base_mode="rebase", base_version=start))
    assert rebased.status_code == 200, rebased.text
    head = await clean.post("/api/configurations/1/changes", json=_batch(
        {"op": "set_param", "name": "expiration_period", "to": 703},
        base_mode="strict", base_version="head"))
    assert head.status_code == 200, head.text
    assert rebased.json()["version_after"] == start + 2 and head.json()["version_after"] == start + 3


@pytest.mark.asyncio
async def test_expect_makes_a_conflict_stale_whatever_the_base(clean):
    resp = await clean.post("/api/configurations/1/changes", json=_batch(
        {"op": "set_param", "name": "expiration_period", "to": 5, "expect": -1}))
    assert resp.status_code == 409 and resp.json()["error"] == "stale"
    assert resp.json()["problems"][0]["op_index"] == 0


_REFUSALS = [
    # (name, ops, error, status, op_index)
    ("an op that is not an object", ["nope"], "malformed", 400, 0),
    ("an unknown table", [{"op": "insert", "table": "no_such_table", "row": {}}], "malformed", 400, 0),
    ("an unknown op",
     [{"op": "set_param", "name": "expiration_period", "to": 5}, {"op": "frobnicate"}],
     "malformed", 400, 1),
    ("a value of the wrong type",
     [{"op": "set_param", "name": "expiration_period", "to": "not a number"}],
     "malformed", 400, 0),
    ("a node that is not there", [{"op": "remove_node", "name": "no-such-node"}],
     "unknown_reference", 422, 0),
    ("a link to a node that is not there",
     [{"op": "insert", "table": "slipnet_link_defs", "row": {
         "from_node": "plato-a", "to_node": "no-such-node", "link_type": "category",
         "label_node": None, "link_length": 50, "fixed_length": True}}],
     "unknown_reference", 422, 0),
    ("a codelet body that does not compile",
     [{"op": "set_codelet_body", "name": "bond-evaluator", "source": "def (:"}],
     "does_not_compile", 422, 0),
    ("a node that already exists",
     [{"op": "add_node", "name": "plato-a", "fields": {"short_name": "a", "conceptual_depth": 1}}],
     "key_exists", 409, 0),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("ops,error,status,index", [r[1:] for r in _REFUSALS], ids=[r[0] for r in _REFUSALS])
async def test_a_refused_batch_names_its_class_and_the_op_and_writes_nothing(
    clean, ops, error, status, index
):
    start = await _revision(clean)
    resp = await clean.post("/api/configurations/1/changes", json=_batch(*ops))
    body = resp.json()
    assert resp.status_code == status, resp.text
    assert body["ok"] is False and body["error"] == error and body["status"] == status
    assert body["message"] and body["problems"][0]["op_index"] == index
    assert await _revision(clean) == start


@pytest.mark.asyncio
async def test_a_bad_envelope_is_malformed(clean):
    for batch in (
        {"ops": []},                                                    # no source
        {"source": "admin"},                                            # no ops
        {"source": "bogus", "ops": []},
        {"source": "admin", "ops": [], "surprise": 1},
        {"source": "admin", "ops": [], "dry_run": "yes"},
        {"source": "admin", "ops": [], "configuration_id": 2},         # not the path's
    ):
        resp = await clean.post("/api/configurations/1/changes", json=batch)
        assert resp.status_code == 400 and resp.json()["error"] == "malformed", batch


@pytest.mark.asyncio
async def test_skip_applies_the_good_ops_and_reports_the_rest(clean):
    resp = await clean.post("/api/configurations/1/changes", json=_batch(
        {"op": "remove_node", "name": "no-such-node"},
        {"op": "set_param", "name": "expiration_period", "to": 705},
        on_op_failure="skip"))
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert len(report["skipped"]) == 1 and report["skipped"][0]["reason"]["op_index"] == 0
    assert report["persisted"] is True


@pytest.mark.asyncio
async def test_metacat_mode_refuses_the_training_mode_sources(clean):
    for source in ("learner", "external"):
        resp = await clean.post("/api/configurations/1/changes", json={
            "source": source, "ops": [{"op": "set_param", "name": "expiration_period", "to": 5}]})
        assert resp.status_code == 403 and resp.json()["error"] == "source_refused", source
        dry = await clean.post("/api/configurations/1/changes", json={
            "source": source, "dry_run": True,
            "ops": [{"op": "set_param", "name": "expiration_period", "to": 5}]})
        assert dry.status_code == 403


@pytest.mark.asyncio
async def test_an_unknown_configuration_is_404(clean):
    resp = await clean.post("/api/configurations/99999/changes", json=_batch())
    assert resp.status_code == 404 and resp.json()["error"] == "unknown_configuration"


# ---------------------------------------------------------------- the schema endpoint


@pytest.mark.asyncio
async def test_the_schema_lists_the_registry_the_ops_and_the_batch_shape(app_client):
    resp = await app_client.get("/api/configurations/1/schema")
    assert resp.status_code == 200, resp.text
    schema = resp.json()
    names = {t["name"] for t in schema["tables"]}
    assert len(names) == 15
    assert {"slipnet_node_defs", "engine_params", "posting_rules"} <= names
    assert not any("episod" in t or "journal" in t or t == "configurations" for t in names)
    node_table = next(t for t in schema["tables"] if t["name"] == "slipnet_node_defs")
    assert node_table["key"] == ["name"]
    assert schema["ops"]["generic"] == ["insert", "update", "delete"]
    assert {"add_node", "remove_node", "set_param", "merge_nodes"} <= set(schema["ops"]["convenience"])
    assert {"source", "ops", "base_mode", "on_op_failure", "dry_run"} <= set(schema["batch"]["fields"])
    assert set(schema["batch"]["generic_ops"]) == {"insert", "update", "delete"}


@pytest.mark.asyncio
async def test_the_schema_of_an_unknown_configuration_is_404(app_client):
    assert (await app_client.get("/api/configurations/99999/schema")).status_code == 404


# ---------------------------------------------------------------- the editors are clients


@pytest.mark.asyncio
async def test_each_editor_write_journals_the_editors_batch_as_its_proposed_ops(clean, db_session):
    start = await _revision(clean)
    node = {"name": "c14b-editor-node", "short_name": "c14", "conceptual_depth": 40,
            "description": "", "descriptor_predicate": None}
    assert (await clean.post("/api/admin/slipnet/nodes", json=node)).status_code == 201
    assert (await clean.put("/api/admin/slipnet/nodes/c14b-editor-node",
                            json={**node, "conceptual_depth": 41})).status_code == 200
    assert (await clean.put("/api/admin/params/expiration_period", json={"value": "611"})).status_code == 200
    assert (await clean.put("/api/admin/urgency-levels/very_high", json={"value": 99})).status_code == 200
    assert (await clean.delete("/api/admin/slipnet/nodes/c14b-editor-node")).status_code == 200

    entries = await _entries(db_session, after=start)
    assert [e["revision"] for e in entries] == list(range(start + 1, start + 6))
    assert {(e["source"], e["actor"], e["channel"]) for e in entries} == {
        ("admin", "admin", "admin_editor")}
    assert [e["proposed"] for e in entries] == [
        [{"op": "insert", "table": "slipnet_node_defs", "row": node}],
        [{"op": "update", "table": "slipnet_node_defs", "key": {"name": "c14b-editor-node"},
          "fields": {"short_name": "c14", "conceptual_depth": 41, "description": "",
                     "descriptor_predicate": None}}],
        [{"op": "update", "table": "engine_params", "key": {"name": "expiration_period"},
          "fields": {"value": "611"}}],
        [{"op": "update", "table": "urgency_levels", "key": {"name": "very_high"},
          "fields": {"value": 99}}],
        [{"op": "delete", "table": "slipnet_node_defs", "key": {"name": "c14b-editor-node"}}],
    ]
    assert (await verify_journal(db_session)).ok


@pytest.mark.asyncio
async def test_an_editor_refusal_keeps_the_editors_status_and_the_changes_message(clean):
    # a value that is not a number
    resp = await clean.put(
        "/api/admin/params/expiration_period", json={"value": "abc", "value_type": "int"})
    assert resp.status_code == 422 and resp.json()["detail"]
    # a link to a node that is not there
    resp = await clean.post("/api/admin/slipnet/links", json={
        "from_node": "plato-a", "to_node": "no-such-node", "link_type": "category"})
    assert resp.status_code == 422
    # a codelet body that does not compile
    codelet = (await clean.get("/api/admin/codelets")).json()[0]
    resp = await clean.put(f"/api/admin/codelets/{codelet['name']}",
                           json={**codelet, "execute_body": "def (:"})
    assert resp.status_code == 422 and resp.json()["detail"]
    # a delete of a row that is not there
    assert (await clean.delete("/api/admin/slipnet/nodes/no-such-node")).status_code == 404


@pytest.mark.asyncio
async def test_removing_a_node_in_the_editor_cascades_as_the_change_api_does(clean, db_session):
    start = await _revision(clean)
    export = (await clean.get("/api/admin/export")).json()
    bound = export["slipnet_node_roles"][0]["node_name"]
    assert (await clean.delete(f"/api/admin/slipnet/nodes/{bound}")).status_code == 200
    (entry,) = await _entries(db_session, after=start)
    assert entry["proposed"] == [
        {"op": "delete", "table": "slipnet_node_defs", "key": {"name": bound}}]
    assert len(entry["resolved"]) > 1 and entry["resolved"][-1]["table"] == "slipnet_node_defs"


@pytest.mark.asyncio
async def test_an_import_submits_one_batch_with_source_import(clean, db_session):
    start = await _revision(clean)
    export = (await clean.get("/api/admin/export")).json()
    params = [dict(p) for p in export["engine_params"]]
    next(p for p in params if p["name"] == "expiration_period")["value"] = "612"
    resp = await clean.post("/api/admin/import", json={"engine_params": params})
    assert resp.status_code == 200, resp.text
    (entry,) = await _entries(db_session, after=start)
    assert (entry["source"], entry["channel"]) == ("import", "admin_import")
    assert all(op["op"] in ("insert", "update") for op in entry["proposed"])
    changed = next(op for op in entry["proposed"]
                   if op["table"] == "engine_params" and op["key"] == {"name": "expiration_period"})
    assert changed["fields"]["value"] == "612"


@pytest.mark.asyncio
async def test_the_editors_take_a_configuration_and_default_to_the_global_one(clean, db_session):
    start = await _revision(clean)
    resp = await clean.put(
        "/api/admin/params/expiration_period?configuration=1", json={"value": "613"})
    assert resp.status_code == 200
    assert len(await _entries(db_session, after=start)) == 1
    # a configuration that does not exist
    missing = await clean.put(
        "/api/admin/params/expiration_period?configuration=99999", json={"value": "614"})
    assert missing.status_code == 404
    # the lists read the global configuration only
    assert (await clean.get("/api/admin/params?configuration=99999")).status_code == 422
    assert (await clean.get("/api/admin/params?configuration=1")).status_code == 200


# ------------------------------------------------- a Training Mode Session's configuration


@pytest.fixture
async def made(db_session):
    """The configuration id of a new Stopped session's configuration; its session is deleted
    afterwards, which removes the configuration."""
    from sqlalchemy import text

    from server.models.training_mode_session import TrainingModeSession
    from server.services.configurations import create_session_configuration

    row = TrainingModeSession(name="C14b session", backend="single", policy={})
    db_session.add(row)
    await db_session.flush()
    session_id = row.id
    cid = await create_session_configuration(db_session, session_id, "standard", [])
    await db_session.commit()
    yield cid
    await db_session.rollback()
    await db_session.execute(text("DELETE FROM training_mode_sessions WHERE id = :i"), {"i": session_id})
    await db_session.commit()


async def _session_entries(db_session, cid: int, after: int = 0) -> list[dict]:
    await db_session.rollback()
    return await read_entries(db_session, cid, after=after)


@pytest.mark.asyncio
async def test_the_changes_endpoint_writes_a_stopped_sessions_configuration(clean, made, db_session):
    global_start = await _revision(clean)
    resp = await clean.post(f"/api/configurations/{made}/changes", json={
        "source": "external", "actor": "tester", "base_mode": "rebase",
        "ops": [{"op": "set_param", "name": "expiration_period", "to": 4321}]})
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["configuration_id"] == made and report["persisted"]
    (entry,) = await _session_entries(db_session, made, after=report["version_before"])
    assert (entry["source"], entry["configuration_id"]) == ("external", made)
    assert await _revision(clean) == global_start        # Metacat Mode's configuration is untouched
    params = {p["name"]: p["value"] for p in (await clean.get("/api/admin/params")).json()}
    assert params["expiration_period"] != "4321"

    refused = await clean.post(f"/api/configurations/{made}/changes", json={
        "source": "external", "base_mode": "rebase",
        "ops": [{"op": "remove_node", "name": "no-such-node"}]})
    assert refused.status_code == 422 and refused.json()["problems"][0]["op_index"] == 0


@pytest.mark.asyncio
async def test_the_editors_write_a_sessions_configuration_by_natural_key(clean, made, db_session):
    start = (await clean.get(f"/api/configurations/{made}")).json()["revision"]
    global_start = await _revision(clean)
    node = {"name": "c14b-session-node", "short_name": "c14", "conceptual_depth": 40}
    assert (await clean.post(
        f"/api/admin/slipnet/nodes?configuration={made}", json=node)).status_code == 201
    assert (await clean.put(
        f"/api/admin/slipnet/nodes/c14b-session-node?configuration={made}",
        json={**node, "conceptual_depth": 41})).status_code == 200
    assert (await clean.put(
        f"/api/admin/params/expiration_period?configuration={made}",
        json={"value": "4322"})).status_code == 200
    assert (await clean.delete(
        f"/api/admin/slipnet/nodes/c14b-session-node?configuration={made}")).status_code == 200
    assert (await clean.delete(
        f"/api/admin/slipnet/nodes/no-such-node?configuration={made}")).status_code == 404

    entries = await _session_entries(db_session, made, after=start)
    assert [e["revision"] for e in entries] == list(range(start + 1, start + 5))
    assert {(e["source"], e["channel"]) for e in entries} == {("admin", "admin_editor")}
    assert await _revision(clean) == global_start
    nodes = {n["name"] for n in (await clean.get("/api/admin/slipnet/nodes")).json()}
    assert "c14b-session-node" not in nodes


@pytest.mark.asyncio
async def test_a_row_addressed_by_id_or_an_enum_value_is_the_global_configurations_only(clean, made):
    demo = {"name": "c14b-demo", "initial": "abc", "modified": "abd", "target": "ijk"}
    resp = await clean.post(f"/api/admin/demos?configuration={made}", json=demo)
    assert resp.status_code == 422 and "global" in resp.json()["detail"]
    resp = await clean.put(f"/api/admin/demos/1?configuration={made}", json=demo)
    assert resp.status_code == 422
    resp = await clean.post(f"/api/admin/enums/posting_directions?configuration={made}", json={
        "name": "c14b-mode", "display_label": "x"})
    assert resp.status_code == 422
    assert (await clean.post(f"/api/admin/import?configuration={made}", json={})).status_code == 422
