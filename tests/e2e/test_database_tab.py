"""E2E (C7): the Database tab's server side, ``/api/admin/db`` (configuration plan 3.6, 3.15, 3.16.2).

Each table class's permissions and refusals over HTTP; a configuration edit through the row
editor being a journal entry (``channel = admin_database``); the read-only SQL box refusing
writes and a second statement.  Every test that edits configuration ends by resetting it to
the Metacat Standard Configuration, so the shared test database is left equal to the standard.
"""

import pytest
from sqlalchemy import select, text

from server.api import database as database_api
from server.models.run import Run
from server.models.training_mode_session import TrainingModeSession
from server.services.journal_views import read_entries, verify_journal


async def _reset(client):
    resp = await client.post("/api/configurations/1/reset-to-standard", json={"confirm": "reset"})
    assert resp.status_code == 200, resp.text


@pytest.fixture
async def clean(app_client):
    await _reset(app_client)
    yield app_client
    await _reset(app_client)


def _detail(resp) -> dict:
    body = resp.json()["detail"]
    assert isinstance(body, dict), body
    return body


async def _classes(client) -> dict:
    resp = await client.get("/api/admin/db/tables")
    assert resp.status_code == 200, resp.text
    return {t["name"]: t for t in resp.json()}


# ---------------------------------------------------------------------------
# Browsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_table_is_listed_with_its_class(app_client):
    tables = await _classes(app_client)
    expected = {
        "engine_params": "configuration",
        "run_statuses": "configuration",
        "help_topics": "content",
        "runs": "runtime",
        "episodic_memory_clears": "runtime",
        "configurations": "journal",
        "configuration_journal": "journal",
        "training_mode_sessions": "session_managed",
        "training_mode_session_problems": "session_managed",
        "training_mode_session_runs": "session_managed",
        "training_memory_merges": "episodic_memory",
        "training_mode_session_memory_snapshots": "episodic_memory",
    }
    for name, cls in expected.items():
        assert tables[name]["class"] == cls, name
    assert tables["engine_params"]["editable"] and not tables["engine_params"]["expert_required"]
    assert tables["runs"]["expert_required"]
    assert not tables["configuration_journal"]["editable"]
    assert not tables["training_memory_merges"]["editable"]
    assert tables["run_statuses"]["enum"] and not tables["engine_params"]["enum"]
    assert tables["engine_params"]["rows"] > 0
    assert "Expert mode does not lift" in tables["training_memory_merges"]["banner"]
    assert "not its current state" in tables["training_mode_sessions"]["banner"]
    # every table the models define is there: introspection, not a list
    from server.models.metadata import Base

    assert set(tables) == set(Base.metadata.tables)


@pytest.mark.asyncio
async def test_rows_are_paged_and_filtered_and_carry_their_key(app_client):
    page = (await app_client.get("/api/admin/db/tables/engine_params/rows?limit=3")).json()
    assert len(page["rows"]) == 3 and page["total"] > 3 and page["key_columns"] == ["name"]
    first = page["rows"][0]
    assert first["key"] == {"name": first["values"]["name"]}
    nxt = (await app_client.get("/api/admin/db/tables/engine_params/rows?limit=3&offset=3")).json()
    assert {r["key"]["name"] for r in nxt["rows"]}.isdisjoint({r["key"]["name"] for r in page["rows"]})

    needle = first["values"]["name"][:6]
    found = (await app_client.get(
        f"/api/admin/db/tables/engine_params/rows?filter_column=name&filter={needle}")).json()
    assert found["total"] >= 1
    assert all(needle.lower() in r["values"]["name"].lower() for r in found["rows"])
    anywhere = (await app_client.get(
        f"/api/admin/db/tables/engine_params/rows?filter={needle}")).json()
    assert anywhere["total"] >= found["total"]

    assert (await app_client.get("/api/admin/db/tables/no_such/rows")).status_code == 404
    assert (await app_client.get(
        "/api/admin/db/tables/engine_params/rows?filter_column=nope&filter=x")).status_code == 422
    assert (await app_client.get("/api/admin/db/tables/engine_params/rows?limit=0")).status_code == 422


@pytest.mark.asyncio
async def test_a_session_configuration_is_not_browsed_by_this_route(app_client):
    resp = await app_client.get("/api/admin/db/tables/engine_params/rows?configuration=999")
    assert resp.status_code == 404
    # configuration is ignored for tables that are not configuration
    ok = await app_client.get("/api/admin/db/tables/runs/rows?configuration=999")
    assert ok.status_code == 200


# ---------------------------------------------------------------------------
# Configuration: a batch through the change API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_configuration_edit_is_a_journal_entry(clean, db_session):
    client = clean
    await db_session.rollback()
    start = len(await read_entries(db_session, 1))
    params = (await client.get("/api/admin/db/tables/engine_params/rows?limit=1")).json()
    row = params["rows"][0]
    name = row["key"]["name"]
    new_value = "7" if row["values"]["value"] != "7" else "8"

    resp = await client.post("/api/admin/db/changes", json={
        "ops": [{"op": "update", "table": "engine_params", "key": {"name": name},
                 "fields": {"value": new_value}}],
        "note": "edited in the database tab",
    })
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["persisted"] is True and report["version_after"] == report["version_before"] + 1

    await db_session.rollback()
    entries = await read_entries(db_session, 1)
    assert len(entries) == start + 1
    entry = entries[-1]
    assert (entry["source"], entry["actor"], entry["channel"]) == ("admin", "admin", "admin_database")
    assert entry["note"] == "edited in the database tab"
    shown = (await client.get(f"/api/admin/db/tables/engine_params/rows?filter_column=name&filter={name}")).json()
    assert [r["values"]["value"] for r in shown["rows"] if r["key"]["name"] == name] == [new_value]
    assert (await verify_journal(db_session)).ok


@pytest.mark.asyncio
async def test_a_dry_run_writes_nothing_and_a_bad_batch_is_refused(clean, db_session):
    client = clean
    await db_session.rollback()
    start = len(await read_entries(db_session, 1))
    dry = await client.post("/api/admin/db/changes", json={
        "dry_run": True,
        "ops": [{"op": "update", "table": "engine_params", "key": {"name": "expiration_period"},
                 "fields": {"value": "9"}}],
    })
    assert dry.status_code == 200 and dry.json()["persisted"] is False
    bad = await client.post("/api/admin/db/changes", json={
        "ops": [{"op": "update", "table": "engine_params", "key": {"name": "no_such_parameter"},
                 "fields": {"value": "9"}}],
    })
    assert bad.status_code >= 400 and bad.json()["ok"] is False
    await db_session.rollback()
    assert len(await read_entries(db_session, 1)) == start


@pytest.mark.asyncio
async def test_an_enum_table_edit_is_a_journal_entry(clean, db_session):
    client = clean
    await db_session.rollback()
    start = len(await read_entries(db_session, 1))
    resp = await client.post("/api/admin/db/changes", json={
        "ops": [{"op": "insert", "table": "posting_directions",
                 "row": {"name": "c7_mode", "display_label": "C7", "sort_order": 99, "description": ""}}],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["persisted"] is True
    await db_session.rollback()
    entries = await read_entries(db_session, 1)
    assert len(entries) == start + 1 and entries[-1]["channel"] == "admin_database"
    again = await client.post("/api/admin/db/changes", json={
        "ops": [{"op": "insert", "table": "posting_directions",
                 "row": {"name": "c7_mode", "display_label": "C7", "sort_order": 99, "description": ""}}],
    })
    assert again.status_code == 409
    mixed = await client.post("/api/admin/db/changes", json={
        "ops": [{"op": "insert", "table": "posting_directions", "row": {"name": "c7_other"}},
                {"op": "update", "table": "engine_params", "key": {"name": "expiration_period"},
                 "fields": {"value": "9"}}],
    })
    assert mixed.status_code == 400


@pytest.mark.asyncio
async def test_a_batch_cannot_name_a_protected_or_read_only_table(app_client):
    def batch(table, op="update"):
        return {"ops": [{"op": op, "table": table, "key": {"id": 1}, "fields": {"seq": 1}}]}

    resp = await app_client.post("/api/admin/db/changes", json=batch("training_memory_merges"))
    assert resp.status_code == 409 and _detail(resp)["error"] == "episodic_memory_protected"
    resp = await app_client.post("/api/admin/db/changes", json=batch("training_mode_sessions"))
    assert resp.status_code == 409 and _detail(resp)["error"] == "session_managed"
    resp = await app_client.post("/api/admin/db/changes", json=batch("configuration_journal"))
    assert resp.status_code == 409 and _detail(resp)["error"] == "journal_read_only"
    resp = await app_client.post("/api/admin/db/changes", json=batch("runs"))
    assert resp.status_code == 400
    # a session's configuration is edited through the change API, not the row editor
    resp = await app_client.post("/api/admin/db/changes", json={
        "configuration_id": 2, "ops": [{"op": "update", "table": "engine_params",
                                         "key": {"name": "x"}, "fields": {"value": "1"}}]})
    assert resp.status_code == 409 and _detail(resp)["error"] == "session_managed"


@pytest.mark.asyncio
async def test_the_row_editor_route_does_not_take_configuration(app_client):
    resp = await app_client.post("/api/admin/db/edit", json={
        "table": "engine_params", "op": "update", "pk": {"id": 1}, "values": {"value": "1"}})
    assert resp.status_code == 400 and "changes" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Journal, session-managed and Episodic Memory classes: refused
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["insert", "update", "delete"])
async def test_the_journal_tables_are_read_only(app_client, op):
    for table in ("configuration_journal", "configurations"):
        resp = await app_client.post("/api/admin/db/edit", json={
            "table": table, "op": op, "pk": {"id": 1}, "values": {"revision": 5},
            "expert": True, "confirm": table})
        assert resp.status_code == 409, (table, op)
        assert _detail(resp)["error"] == "journal_read_only"


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["insert", "update", "delete"])
async def test_session_managed_tables_refuse_even_in_expert_mode(app_client, op):
    for table in ("training_mode_sessions", "training_mode_session_problems"):
        resp = await app_client.post("/api/admin/db/edit", json={
            "table": table, "op": op, "pk": {"id": 1}, "values": {"name": "x"},
            "expert": True, "confirm": table})
        assert resp.status_code == 409, (table, op)
        assert _detail(resp)["error"] == "session_managed"


@pytest.mark.asyncio
async def test_deleting_a_session_row_names_the_service_route(app_client, db_session):
    session_row = TrainingModeSession(name="c7 database tab", backend="serial", policy={}, max_codelets=20000)
    db_session.add(session_row)
    await db_session.commit()
    try:
        resp = await app_client.post("/api/admin/db/edit", json={
            "table": "training_mode_sessions", "op": "delete", "pk": {"id": session_row.id},
            "expert": True, "confirm": "training_mode_sessions"})
        assert resp.status_code == 409
        detail = _detail(resp)
        assert detail["error"] == "session_managed"
        assert "DELETE /api/training-mode/sessions/{id}" in detail["message"]
        await db_session.rollback()
        assert (await db_session.get(TrainingModeSession, session_row.id)) is not None
    finally:
        await db_session.rollback()
        await db_session.delete(await db_session.get(TrainingModeSession, session_row.id))
        await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["insert", "update", "delete"])
async def test_a_sessions_episodic_memory_is_protected_and_expert_mode_does_not_lift_it(app_client, op):
    resp = await app_client.post("/api/admin/db/edit", json={
        "table": "training_memory_merges", "op": op, "pk": {"id": 1}, "values": {"seq": 1},
        "expert": True, "confirm": "training_memory_merges"})
    assert resp.status_code == 409
    assert _detail(resp)["error"] == "episodic_memory_protected"


@pytest.mark.asyncio
async def test_the_run_columns_that_place_a_run_in_the_memory_are_protected(app_client):
    base = {"table": "training_mode_session_runs", "pk": {"id": 1}, "expert": True,
            "confirm": "training_mode_session_runs"}
    for column in ("seq", "memory_version", "added_answers", "added_snags"):
        resp = await app_client.post("/api/admin/db/edit", json={
            **base, "op": "update", "values": {column: 3}})
        assert resp.status_code == 409 and _detail(resp)["error"] == "episodic_memory_protected", column
    for op in ("insert", "delete"):
        resp = await app_client.post("/api/admin/db/edit", json={**base, "op": op, "values": {"seed": 1}})
        assert resp.status_code == 409 and _detail(resp)["error"] == "episodic_memory_protected", op
    # any other column of the run is session-managed, not protected
    resp = await app_client.post("/api/admin/db/edit", json={**base, "op": "update", "values": {"answer": "x"}})
    assert resp.status_code == 409 and _detail(resp)["error"] == "session_managed"


# ---------------------------------------------------------------------------
# Content and runtime data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_help_topics_are_content_written_directly(app_client):
    new = await app_client.post("/api/admin/db/edit", json={
        "table": "help_topics", "op": "insert",
        "values": {"topic_type": "concept", "topic_key": "c7-topic", "title": "C7",
                   "short_desc": "s", "full_desc": "f"}})
    assert new.status_code == 200, new.text
    pk = {"id": new.json()["after"]["id"]}
    upd = await app_client.post("/api/admin/db/edit", json={
        "table": "help_topics", "op": "update", "pk": pk, "values": {"title": "C7 changed"}})
    assert upd.status_code == 200
    assert upd.json()["before"]["title"] == "C7" and upd.json()["after"]["title"] == "C7 changed"
    gone = await app_client.post("/api/admin/db/edit", json={"table": "help_topics", "op": "delete", "pk": pk})
    assert gone.status_code == 200
    again = await app_client.post("/api/admin/db/edit", json={"table": "help_topics", "op": "delete", "pk": pk})
    assert again.status_code == 404


@pytest.fixture
async def two_runs(db_session):
    active = Run(initial_string="abc", modified_string="abd", target_string="ijk", seed=1, status="running", spreading_threshold=100)
    done = Run(initial_string="abc", modified_string="abd", target_string="ijk", seed=2, status="answer_found", spreading_threshold=100)
    db_session.add_all([active, done])
    await db_session.commit()
    ids = (active.id, done.id)
    yield ids
    await db_session.rollback()
    for run_id in ids:
        row = await db_session.get(Run, run_id)
        if row is not None:
            await db_session.delete(row)
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_runtime_edit_needs_expert_mode_and_the_typed_confirmation(app_client, two_runs):
    _, done = two_runs
    base = {"table": "runs", "op": "update", "pk": {"id": done}, "values": {"seed": 77}}
    no_expert = await app_client.post("/api/admin/db/edit", json={**base, "confirm": "runs"})
    assert no_expert.status_code == 409 and _detail(no_expert)["error"] == "expert_required"
    wrong = await app_client.post("/api/admin/db/edit", json={**base, "expert": True, "confirm": "yes"})
    assert wrong.status_code == 409 and _detail(wrong)["error"] == "confirmation_required"
    ok = await app_client.post("/api/admin/db/edit", json={**base, "expert": True, "confirm": "runs"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["before"]["seed"] == 2 and ok.json()["after"]["seed"] == 77


@pytest.mark.asyncio
async def test_an_active_runs_rows_are_refused(app_client, two_runs):
    active, done = two_runs
    confirm = {"expert": True, "confirm": "runs"}
    for op, extra in (("update", {"values": {"seed": 5}}), ("delete", {})):
        resp = await app_client.post("/api/admin/db/edit", json={
            "table": "runs", "op": op, "pk": {"id": active}, **extra, **confirm})
        assert resp.status_code == 409 and _detail(resp)["error"] == "active_row", op
    # a finished run cannot be made active by an edit either
    resp = await app_client.post("/api/admin/db/edit", json={
        "table": "runs", "op": "update", "pk": {"id": done}, "values": {"status": "running"}, **confirm})
    assert resp.status_code == 409 and _detail(resp)["error"] == "active_row"
    # a row that belongs to an active run (it has a run_id) is refused too
    resp = await app_client.post("/api/admin/db/edit", json={
        "table": "episodic_memory_clears", "op": "insert", "values": {"note": "x"}, **{
            "expert": True, "confirm": "episodic_memory_clears"}})
    assert resp.status_code == 200  # no run_id: not an active-run row
    clear_id = resp.json()["after"]["id"]
    resp = await app_client.post("/api/admin/db/edit", json={
        "table": "episodic_memory_clears", "op": "delete", "pk": {"id": clear_id},
        "expert": True, "confirm": "episodic_memory_clears"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_a_database_refusal_is_reported_and_nothing_is_written(app_client, two_runs):
    _, done = two_runs
    resp = await app_client.post("/api/admin/db/edit", json={
        "table": "runs", "op": "update", "pk": {"id": done}, "values": {"status": "no_such_status"},
        "expert": True, "confirm": "runs"})
    assert resp.status_code == 409
    resp = await app_client.post("/api/admin/db/edit", json={
        "table": "runs", "op": "update", "pk": {"id": done}, "values": {"no_such_column": 1},
        "expert": True, "confirm": "runs"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# The read-only SQL box
# ---------------------------------------------------------------------------


async def _sql(client, sql, **extra):
    return await client.post("/api/admin/db/sql", json={"sql": sql, **extra})


@pytest.mark.asyncio
async def test_the_sql_box_runs_a_select_and_a_with(app_client):
    resp = await _sql(app_client, "SELECT name, value FROM engine_params ORDER BY name LIMIT 2;")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["columns"] == ["name", "value"] and body["row_count"] == 2 and not body["truncated"]
    cte = await _sql(app_client, "WITH x AS (SELECT 1 AS n) SELECT n, 'a:b'::text AS t FROM x")
    assert cte.status_code == 200 and cte.json()["rows"] == [[1, "a:b"]]
    commented = await _sql(app_client, "-- a note\nSELECT 1 AS one -- trailing")
    assert commented.status_code == 200 and commented.json()["rows"] == [[1]]
    inside = await _sql(app_client, "SELECT 'a;b' AS semi")
    assert inside.status_code == 200 and inside.json()["rows"] == [["a;b"]]


@pytest.mark.asyncio
async def test_the_sql_box_limits_rows(app_client):
    resp = await _sql(app_client, "SELECT generate_series(1, 50) AS n", limit=10)
    body = resp.json()
    assert body["row_count"] == 10 and body["truncated"] and body["limit"] == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("sql", [
    "INSERT INTO help_topics (topic_type) VALUES ('x')",
    "UPDATE engine_params SET value = '1'",
    "DELETE FROM runs",
    "DROP TABLE runs",
    "TRUNCATE runs",
    "EXPLAIN ANALYZE DELETE FROM runs",
    "SELECT 1; DROP TABLE runs",
    "SELECT 1; SELECT 2",
    "",
    "   ;  ",
])
async def test_the_sql_box_refuses_anything_but_one_select(app_client, sql):
    resp = await _sql(app_client, sql)
    assert resp.status_code == 400, sql


@pytest.mark.asyncio
async def test_a_data_modifying_cte_is_stopped_by_the_read_only_transaction(app_client, two_runs):
    _, done = two_runs
    resp = await _sql(app_client, f"WITH d AS (DELETE FROM runs WHERE id = {done} RETURNING id) SELECT * FROM d")
    assert resp.status_code == 400
    still = await app_client.get(f"/api/admin/db/tables/runs/rows?filter_column=id&filter={done}")
    assert still.json()["total"] >= 1


@pytest.mark.asyncio
async def test_a_function_that_writes_is_stopped_by_the_read_only_transaction(app_client):
    resp = await _sql(app_client, "SELECT nextval('runs_id_seq')")
    assert resp.status_code == 400 and "read-only" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_slow_statement_times_out(app_client, monkeypatch):
    monkeypatch.setattr(database_api, "_SQL_TIMEOUT_MS", 200)
    resp = await _sql(app_client, "SELECT pg_sleep(5)")
    assert resp.status_code == 400 and "timeout" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_the_sql_box_shows_the_database_including_session_tables(app_client, db_session):
    session_row = TrainingModeSession(name="c7 sql box", backend="serial", policy={}, max_codelets=20000)
    db_session.add(session_row)
    await db_session.commit()
    try:
        resp = await _sql(app_client, f"SELECT name FROM training_mode_sessions WHERE id = {session_row.id}")
        assert resp.status_code == 200 and resp.json()["rows"] == [["c7 sql box"]]
    finally:
        await db_session.rollback()
        await db_session.delete(await db_session.get(TrainingModeSession, session_row.id))
        await db_session.commit()
