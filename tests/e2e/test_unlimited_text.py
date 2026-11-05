"""User-typed text has no length cap and no character restriction, end to end.

Session names and notes, configuration names and notes, journal actor / channel / group / note,
and the configuration text columns (node names, glyphs, descriptions, codelet types, help
titles) take any text of any length and give it back exactly: long strings, a multi-character
glyph (a ZWJ family emoji), and non-Latin text.  The only refusals are the two things a
database cannot hold as text, U+0000 and a lone surrogate: a 4xx that names the field, never a 500.

Every test that writes to the global configuration ends by resetting it to the Metacat Standard
Configuration, so the shared test database is left equal to it.
"""

import json

import pytest
from sqlalchemy import select

from server.models.journal import JournalEntry
from server.models.metadata import CodeletTypeDef, HelpTopic, SlipnetNodeDef
from server.services.journal_views import read_entries
from tests.e2e.test_session_configuration import serial_sessions, sessions  # noqa: F401 - the fixtures

FAMILY = "👨‍👩‍👧"
LONG = "長" * 700 + " é" + "x" * 300  # far over every old cap (16 to 256)
SESSIONS = "/api/training-mode/sessions"


async def post_ascii(client, path: str, body: dict, method: str = "post"):
    """Send JSON with ``\\uXXXX`` escapes: a lone surrogate can only travel that way."""
    return await getattr(client, method)(
        path, content=json.dumps(body), headers={"Content-Type": "application/json"})


async def _reset(app_client):
    resp = await app_client.post("/api/configurations/1/reset-to-standard", json={"confirm": "reset"})
    assert resp.status_code == 200, resp.text


@pytest.fixture
async def clean(app_client):
    await _reset(app_client)
    yield app_client
    await _reset(app_client)


def _batch(*ops, **fields) -> dict:
    return {"source": "admin", "actor": "tester", "base_mode": "rebase", "ops": list(ops), **fields}


def _node(name: str, **extra) -> dict:
    return {"name": name, "short_name": "s" * 40, "conceptual_depth": 5, "description": "d",
            "descriptor_predicate": None, **extra}


# ---------------------------------------------------------------- session name and note


@pytest.mark.asyncio
async def test_a_session_name_and_note_of_any_length_and_script_are_stored_and_returned_exactly(app_client, sessions):
    name = "名前 " + LONG
    note = FAMILY + " " + ("Ж" * 20_000)  # over the old 10,000 cap
    resp = await app_client.post(SESSIONS, json={"name": name, "note": note})
    assert resp.status_code == 201, resp.text
    tid = resp.json()["session"]["id"]
    try:
        got = (await app_client.get(f"{SESSIONS}/{tid}")).json()
        assert (got["name"], got["note"]) == (name.strip(), note)
        name2, note2 = "ab" * 300, "\n" + FAMILY * 5000
        resp = await app_client.patch(f"{SESSIONS}/{tid}", json={"name": name2, "note": note2})
        assert resp.status_code == 200, resp.text
        got = (await app_client.get(f"{SESSIONS}/{tid}")).json()
        assert (got["name"], got["note"]) == (name2, note2)
    finally:
        await app_client.delete(f"{SESSIONS}/{tid}")


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["name", "note"])
@pytest.mark.parametrize("bad, word", [("a\x00b", "U+0000"), ("a\ud800b", "surrogate")])
async def test_a_session_name_or_note_the_database_cannot_hold_is_a_422_naming_the_field(app_client, sessions, field, bad, word):
    body = {"name": "ok", "note": "ok", field: bad}
    resp = await post_ascii(app_client, SESSIONS, body)
    assert resp.status_code == 422, resp.text
    # (pydantic itself may refuse a lone surrogate in a string field first; it names the field too)
    assert field in resp.text and (word in resp.text or "valid string" in resp.text)
    made = await app_client.post(SESSIONS, json={"name": "ok"})
    tid = made.json()["session"]["id"]
    try:
        resp = await post_ascii(app_client, f"{SESSIONS}/{tid}", {field: bad}, method="patch")
        assert resp.status_code == 422, resp.text
        assert field in resp.text and (word in resp.text or "valid string" in resp.text)
    finally:
        await app_client.delete(f"{SESSIONS}/{tid}")


# ---------------------------------------------------------------- configuration name and note


@pytest.mark.asyncio
async def test_a_configuration_name_and_note_of_any_length_are_stored_and_returned_exactly(clean):
    name, note = "設定 " + LONG, FAMILY + ("ы" * 20_000)
    resp = await clean.patch("/api/configurations/1", json={"name": name, "note": note})
    assert resp.status_code == 200, resp.text
    got = (await clean.get("/api/configurations/1")).json()
    assert (got["name"], got["note"]) == (name, note)
    assert (await clean.patch("/api/configurations/1", json={"name": "   "})).status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["name", "note"])
@pytest.mark.parametrize("bad, word", [("a\x00b", "U+0000"), ("a\ud800b", "surrogate")])
async def test_a_configuration_name_or_note_the_database_cannot_hold_is_a_400_naming_the_field(clean, field, bad, word):
    resp = await post_ascii(clean, "/api/configurations/1", {field: bad}, method="patch")
    assert resp.status_code == 400, resp.text
    assert field in resp.text and word in resp.text


# ---------------------------------------------------------------- the change API and the journal


@pytest.mark.asyncio
async def test_configuration_text_of_any_length_and_a_multi_character_glyph_round_trip_through_the_change_api(clean, db_session):
    name = "節点-" + "n" * 300
    row = _node(name, short_name="s" * 90, plain_name="p" * 200 + "é", full_name=LONG,
                cm_short_name="c" * 40, glyph=FAMILY)
    resp = await clean.post("/api/configurations/1/changes", json=_batch(
        {"op": "insert", "table": "slipnet_node_defs", "row": row}))
    assert resp.status_code == 200, resp.text
    await db_session.rollback()
    got = (await db_session.execute(select(SlipnetNodeDef).where(SlipnetNodeDef.name == name))).scalar_one()
    assert (got.short_name, got.plain_name, got.full_name, got.cm_short_name, got.glyph) == (
        row["short_name"], row["plain_name"], row["full_name"], row["cm_short_name"], FAMILY)
    # edit the glyph to another multi-character sequence
    resp = await clean.post("/api/configurations/1/changes", json=_batch(
        {"op": "update", "table": "slipnet_node_defs", "key": {"name": name}, "fields": {"glyph": "🇨🇦é"}}))
    assert resp.status_code == 200, resp.text
    # the Admin view's listing and the configuration's export carry it
    rows = (await clean.get("/api/configurations/1/rows?table=slipnet_node_defs")).json()["rows"]
    assert {r["glyph"] for r in rows if r["name"] == name} == {"🇨🇦é"}


@pytest.mark.asyncio
async def test_codelet_type_and_help_topic_text_columns_hold_any_length(clean, db_session):
    base = (await db_session.execute(select(CodeletTypeDef).limit(1))).scalar_one()
    db_session.add(CodeletTypeDef(
        name="タイプ" + "t" * 300, family=base.family, phase=base.phase, source_file="f" * 200 + "é",
        description=LONG))
    db_session.add(HelpTopic(topic_type="glossary", topic_key="k" * 300, title=LONG))
    await db_session.commit()
    ct = (await db_session.execute(select(CodeletTypeDef).where(CodeletTypeDef.name == "タイプ" + "t" * 300))).scalar_one()
    ht = (await db_session.execute(select(HelpTopic).where(HelpTopic.topic_key == "k" * 300))).scalar_one()
    assert (ct.source_file, ct.description, ht.title) == ("f" * 200 + "é", LONG, LONG)
    await db_session.delete(ct)
    await db_session.delete(ht)
    await db_session.commit()


@pytest.mark.asyncio
async def test_journal_actor_channel_group_and_note_of_any_length_are_stored_exactly(clean, db_session):
    actor, channel, group, note = "學習者-" + "a" * 200, FAMILY + "c" * 100, "g" * 300, LONG
    resp = await clean.post("/api/configurations/1/changes", json=_batch(
        {"op": "set_param", "name": "expiration_period", "to": 779},
        actor=actor, channel=channel, group_id=group, note=note))
    assert resp.status_code == 200, resp.text
    await db_session.rollback()
    entry = (await db_session.execute(
        select(JournalEntry).where(JournalEntry.configuration_id == 1)
        .order_by(JournalEntry.revision.desc()).limit(1))).scalar_one()
    assert (entry.actor, entry.channel, entry.group_id, entry.note) == (actor, channel, group, note)
    entries = await read_entries(db_session, 1, after=entry.revision - 1)
    assert entries[0]["actor"] == actor


@pytest.mark.asyncio
@pytest.mark.parametrize("bad, word", [("a\x00b", "U+0000"), ("a\ud800b", "surrogate")])
async def test_unstorable_text_in_a_change_batch_is_a_400_naming_the_field(clean, bad, word):
    set_param = {"op": "set_param", "name": "expiration_period", "to": 5}
    for fields in (
        {"actor": bad}, {"channel": bad}, {"group_id": bad}, {"note": bad},
    ):
        resp = await post_ascii(clean, "/api/configurations/1/changes", _batch(set_param, **fields))
        assert resp.status_code == 400, (fields, resp.text)
        (field,) = fields
        assert field in resp.text and word in resp.text
    for ops in (
        [{"op": "insert", "table": "slipnet_node_defs", "row": _node("bad", glyph=bad)}],
        [{"op": "insert", "table": "slipnet_node_defs", "row": _node("b" + bad)}],
        [{"op": "update", "table": "engine_params", "key": {"name": "expiration_period"},
          "fields": {"value": [{"nested": bad}]}}],
        [{"op": "update", "table": "engine_params", "key": {"name": "expiration_period"},
          "fields": {"value": {bad: 1}}}],
    ):
        resp = await post_ascii(clean, "/api/configurations/1/changes", _batch(*ops))
        assert resp.status_code == 400, (ops, resp.text)
        assert "ops" in resp.text and word in resp.text


@pytest.mark.asyncio
async def test_a_caller_value_for_a_fixed_vocabulary_column_is_checked_first_a_4xx_never_a_500(clean, sessions):
    """A bad value for a fixed vocabulary column is refused, not a database error."""
    demo = {"name": "v", "initial": "a", "modified": "b", "target": "c"}
    for field in ("name", "section", "description"):
        resp = await post_ascii(clean, "/api/admin/demos", {**demo, field: "a\x00b"})
        assert 400 <= resp.status_code < 500, (field, resp.text)
    resp = await clean.post("/api/runs", json={"initial": "a", "modified": "b", "target": "c", "mode": "bogus"})
    assert 400 <= resp.status_code < 500, resp.text
    resp = await clean.post(SESSIONS, json={"name": "v", "settings": {"backend": "bogus"}})
    assert 400 <= resp.status_code < 500, resp.text
    resp = await clean.post("/api/configurations/1/changes", json=_batch(
        {"op": "set_param", "name": "expiration_period", "to": 5}, source="bogus"))
    assert resp.status_code == 400, resp.text
