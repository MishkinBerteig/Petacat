"""C6: the journal layer (configuration plan 3.11) against a scratch database.

Runs the layer for real: the Metacat Standard Configuration's first load as the global
journal's first entry, ordinary writes, cascades, the round trip (replay equals
before-image reconstruction at every revision), restore, undo, provenance,
``verify_journal``, the two doors and append-only.  Uses ``C6_DATABASE_URL`` (default: the
harness database server, database ``petacat_c6``) and skips when Postgres is unreachable.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.equivalence_harness import SEED_DIR, ensure_database, harness_db_url


def scratch_url() -> str:
    default = harness_db_url().rsplit("/", 1)[0] + "/petacat_c6"
    return os.environ.get("C6_DATABASE_URL", default)


def _reachable() -> bool:
    try:
        authority = scratch_url().split("@")[1].split("/")[0]
        host, _, port = authority.partition(":")
        socket.create_connection((host, int(port or 5432)), timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _reachable(), reason="the scratch Postgres is not reachable (start it with scripts/dev.sh db)"
)

LOCK_KEY = 0x7E7AC006


@pytest.fixture
async def engine():
    """An empty scratch database, held under an advisory lock for the test."""
    import server.models.run  # noqa: F401
    import server.models.training_mode_session  # noqa: F401
    from server.models.metadata import Base

    url = scratch_url()
    await ensure_database(url)
    eng = create_async_engine(url, poolclass=NullPool)
    lock = await eng.connect()
    await lock.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
        await lock.close()
        await eng.dispose()


@pytest.fixture
async def loaded(engine):
    """The scratch database after the Metacat Standard Configuration's first load."""
    from server.services.standard_configuration import seed_metadata_from_json

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await seed_metadata_from_json(session, SEED_DIR)
        await session.commit()
    return engine


def _s(engine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


def _node(name: str, **extra) -> dict:
    return {
        "op": "insert", "table": "slipnet_node_defs", "key": {},
        "row": {"name": name, "short_name": name[:4], "conceptual_depth": 50, **extra},
    }


async def _write(engine, ops, **kw):
    from server.services.journal import write_immediate

    kw.setdefault("source", "admin")
    kw.setdefault("actor", "admin")
    async with _s(engine) as session:
        return await write_immediate(session, ops=ops, **kw)


# ──────────────────────────────────────────────────────────────────
# The first load
# ──────────────────────────────────────────────────────────────────


async def test_first_load_is_the_first_entry_of_the_global_journal(loaded):
    from server.services.journal_views import read_entries, verify_journal

    async with _s(loaded) as session:
        entries = await read_entries(session)
        assert [e["revision"] for e in entries] == [1]
        first = entries[0]
        assert first["source"] == "standard_load" and first["actor"] == "system"
        assert first["configuration_id"] == 1
        assert first["before"] == [None] * len(first["resolved"])
        assert all(op["op"] == "insert" for op in first["resolved"])
        json.dumps(first["resolved"])  # the entry is JSON-compatible
        report = await verify_journal(session)
        assert report.ok, report.problems


async def test_the_load_matches_the_files_and_the_stored_hash(loaded):
    from server.engine.hashing import config_hash
    from server.engine.metadata import MetadataProvider
    from server.models.journal import Configuration
    from server.services.metadata_service import load_metadata_from_db

    async with _s(loaded) as session:
        row = (await session.execute(select(Configuration))).scalars().one()
        assert (row.id, row.kind, row.revision) == (1, "global", 1)
        meta = await load_metadata_from_db(session)
        assert row.config_hash == config_hash(meta)
        assert config_hash(meta) == config_hash(MetadataProvider.from_standard_configuration(SEED_DIR))


# ──────────────────────────────────────────────────────────────────
# Writing: resolved ops, defaults, cascades, atomicity
# ──────────────────────────────────────────────────────────────────


async def test_an_insert_records_absolute_values_and_no_surrogate_id(loaded):
    result = await _write(loaded, [_node("plato-zz")])
    (op,) = result.resolved
    assert op["key"] == {"name": "plato-zz"}
    assert "id" not in op["row"] and result.rows[0]["name"] == "plato-zz"
    assert result.revision == 2 and result.entry_id is not None

    # a column default is resolved into the recorded row: one past the last sort_order
    level = await _write(loaded, [{"op": "insert", "table": "urgency_levels", "key": {},
                                   "row": {"name": "extra", "value": 7}}])
    assert level.resolved[0]["row"]["sort_order"] > 0
    # an id-bearing table: the row given back carries its id, the journal does not
    template = await _write(loaded, [{"op": "insert", "table": "commentary_templates", "key": {},
                                      "row": {"template_key": "kk", "template_data": {}}}])
    assert "id" in template.rows[0] and "id" not in template.resolved[0]["row"]


async def test_a_link_without_a_label_has_the_empty_label_in_its_key(loaded):
    async with _s(loaded) as session:
        from server.models.metadata import SlipnetLinkDef

        one = (await session.execute(select(SlipnetLinkDef).where(SlipnetLinkDef.label_node.is_(None)))).scalars().first()
        assert one is not None
    result = await _write(loaded, [{"op": "delete", "table": "slipnet_link_defs",
                                    "key": {"from_node": one.from_node, "to_node": one.to_node,
                                            "link_type": one.link_type, "label_node": ""}}])
    assert result.resolved[0]["key"]["label_node"] == ""
    assert result.before[0]["label_node"] is None and "id" not in result.before[0]


async def test_an_update_keeps_only_the_changed_columns_and_a_no_op_writes_nothing(loaded):
    from server.services.journal_views import read_entries

    await _write(loaded, [_node("plato-zz")])
    same = await _write(loaded, [{"op": "update", "table": "slipnet_node_defs",
                                  "key": {"name": "plato-zz"},
                                  "set": {"short_name": "plat", "conceptual_depth": 50}}])
    assert not same.changed and same.entry_id is None and same.revision == 2
    result = await _write(loaded, [{"op": "update", "table": "slipnet_node_defs",
                                    "key": {"name": "plato-zz"},
                                    "set": {"short_name": "plat", "conceptual_depth": 77}}])
    assert result.resolved == [{"op": "update", "table": "slipnet_node_defs",
                                "key": {"name": "plato-zz"}, "set": {"conceptual_depth": 77}}]
    assert result.before[0]["conceptual_depth"] == 50
    async with _s(loaded) as session:
        assert [e["revision"] for e in await read_entries(session)] == [1, 2, 3]


async def test_deleting_a_node_lists_the_rows_the_database_cascades_to(loaded):
    """Role bindings and theme relations follow their node; the journal holds them."""
    from server.models.metadata import SlipnetNodeRole

    async with _s(loaded) as session:
        bound = (await session.execute(select(SlipnetNodeRole))).scalars().first()
    result = await _write(loaded, [{"op": "delete", "table": "slipnet_node_defs",
                                    "key": {"name": bound.node_name}}])
    tables = [op["table"] for op in result.resolved]
    assert tables[-1] == "slipnet_node_defs" and "slipnet_node_roles" in tables[:-1]
    assert all(op["op"] == "delete" for op in result.resolved)
    assert len(result.before) == len(result.resolved)


async def test_a_refused_batch_writes_nothing(loaded):
    from server.models.journal import Configuration
    from server.services.journal import KeyExists, MissingKey

    with pytest.raises(KeyExists):
        await _write(loaded, [_node("plato-qq"), _node("plato-qq")])
    with pytest.raises(MissingKey):
        await _write(loaded, [_node("plato-qq"),
                              {"op": "delete", "table": "slipnet_node_defs", "key": {"name": "nope"}}])
    async with _s(loaded) as session:
        assert (await session.execute(select(Configuration.revision))).scalar_one() == 1
        from server.models.metadata import SlipnetNodeDef

        assert await session.get(SlipnetNodeDef, "plato-qq") is None


async def test_a_database_error_rolls_the_whole_batch_back(loaded):
    from sqlalchemy.exc import IntegrityError

    from server.models.journal import Configuration

    bad_link_type = {"op": "insert", "table": "slipnet_link_defs", "key": {},
                     "row": {"from_node": "plato-a", "to_node": "plato-b",
                             "link_type": "no-such-type", "label_node": None}}
    with pytest.raises(IntegrityError):
        await _write(loaded, [_node("plato-qq"), bad_link_type])
    async with _s(loaded) as session:
        assert (await session.execute(select(Configuration.revision))).scalar_one() == 1


async def test_the_global_configuration_refuses_training_mode_sources(loaded):
    from server.services.journal import SourceRefused

    for source, actor in (("learner", "learner:x"), ("external", "external:client")):
        with pytest.raises(SourceRefused):
            await _write(loaded, [_node("plato-zz")], source=source, actor=actor)
    from server.services.journal import JournalError

    with pytest.raises(JournalError):
        await _write(loaded, [_node("plato-zz")], source="made-up")


async def test_rekeying_a_row_with_dependents_is_refused_and_one_without_is_recorded(loaded):
    from server.models.metadata import SlipnetNodeRole
    from server.services.journal import JournalError

    async with _s(loaded) as session:
        bound = (await session.execute(select(SlipnetNodeRole))).scalars().first()
    with pytest.raises(JournalError, match="cascade"):
        await _write(loaded, [{"op": "update", "table": "slipnet_node_defs",
                               "key": {"name": bound.node_name}, "set": {"name": "renamed"}}])
    await _write(loaded, [{"op": "insert", "table": "commentary_templates", "key": {},
                           "row": {"template_key": "k1", "template_data": {"b": 1, "a": 2}}}])
    result = await _write(loaded, [{"op": "update", "table": "commentary_templates",
                                    "key": {"template_key": "k1"}, "set": {"template_key": "k2"}}])
    assert result.resolved[0]["key"] == {"template_key": "k1"}
    assert result.before[0]["template_data"] == {"b": 1, "a": 2}
    assert list(result.before[0]["template_data"]) == ["b", "a"]  # key order survives JSON


# ──────────────────────────────────────────────────────────────────
# The round trip, views, restore and undo
# ──────────────────────────────────────────────────────────────────


async def _history(engine):
    """A mix of inserts, updates, a re-key, a cascading delete and a coefficient edit."""
    from server.models.metadata import SlipnetNodeRole

    async with _s(engine) as session:
        bound = (await session.execute(select(SlipnetNodeRole))).scalars().first()
        coeff = (await session.execute(text("SELECT name FROM formula_coefficients LIMIT 1"))).scalar_one()
    await _write(engine, [_node("plato-zz"), _node("plato-yy")])
    await _write(engine, [{"op": "update", "table": "slipnet_node_defs",
                           "key": {"name": "plato-zz"}, "set": {"conceptual_depth": 12}}])
    await _write(engine, [{"op": "insert", "table": "commentary_templates", "key": {},
                           "row": {"template_key": "k1", "template_data": {"x": [1, 2]}}}])
    await _write(engine, [{"op": "update", "table": "commentary_templates",
                           "key": {"template_key": "k1"}, "set": {"template_key": "k2"}}])
    await _write(engine, [{"op": "delete", "table": "slipnet_node_defs",
                           "key": {"name": bound.node_name}}], group_id="g-delete")
    await _write(engine, [{"op": "update", "table": "formula_coefficients",
                           "key": {"name": coeff}, "set": {"value": "3", "value_type": "int"}}])
    await _write(engine, [{"op": "delete", "table": "slipnet_node_defs",
                           "key": {"name": "plato-yy"}}])
    return bound


async def test_replay_equals_before_image_reconstruction_at_every_revision(loaded):
    from server.services.journal_views import as_of, current_state, read_entries, reconstruct, replay

    await _history(loaded)
    async with _s(loaded) as session:
        entries = await read_entries(session)
        assert [e["revision"] for e in entries] == list(range(1, 9))
        current = await current_state(session)
        for revision in range(0, 9):
            forward = replay(entries, upto=revision)
            backward = reconstruct(current, entries, revision)
            assert forward == backward, f"revision {revision}"
            assert await as_of(session, 1, revision) == forward
        assert replay(entries) == current
        assert (await as_of(session, 1, 3, table="slipnet_node_defs",
                            key={"name": "plato-zz"}))["conceptual_depth"] == 12
        assert await as_of(session, 1, 1, table="slipnet_node_defs", key={"name": "plato-zz"}) is None


async def test_verify_journal_passes_and_catches_a_write_made_outside_the_layer(loaded):
    from server.services.journal_views import verify_journal

    await _history(loaded)
    async with _s(loaded) as session:
        assert (await verify_journal(session)).ok
    # a raw write, as psql would make: no entry records it
    async with _s(loaded) as session:
        await session.execute(text("UPDATE engine_params SET value = value || '0' WHERE name = (SELECT name FROM engine_params LIMIT 1)"))
        await session.commit()
    async with _s(loaded) as session:
        report = await verify_journal(session)
        assert not report.ok
        assert any("replay differs" in p for p in report.problems)


async def test_restore_puts_a_deleted_node_back_with_its_dependents(loaded):
    from server.services.journal_views import current_state, restore_entity, verify_journal

    bound = await _history(loaded)
    async with _s(loaded) as session:
        before = await current_state(session)
        assert (bound.node_name,) not in before["slipnet_node_defs"]
        result = await restore_entity(
            session, 1, "slipnet_node_defs", {"name": bound.node_name}, as_of_revision=1,
            actor="admin", note="put it back",
        )
        assert result.revision == 9
        tables = [op["table"] for op in result.resolved]
        assert tables[0] == "slipnet_node_defs" and "slipnet_node_roles" in tables
        after = await current_state(session)
        assert after["slipnet_node_defs"][(bound.node_name,)]["conceptual_depth"] is not None
        assert (await verify_journal(session)).ok
        from server.services.journal_views import read_entries

        last = (await read_entries(session))[-1]
        assert last["source"] == "restore" and last["note"] == "put it back"


async def test_undo_a_batch_by_group_and_by_entry_is_a_new_entry(loaded):
    from server.services.journal_views import as_of, current_state, read_entries, undo, verify_journal

    bound = await _history(loaded)
    async with _s(loaded) as session:
        entries = await read_entries(session)
        n_before = len(entries)
        deleted = [e for e in entries if e["group_id"] == "g-delete"]
        assert len(deleted) == 1
        undone = await undo(session, 1, group_id="g-delete", actor="admin")
        assert undone.revision == n_before + 1
        # the node and every dependent are back as they were just before the delete
        then = await as_of(session, 1, deleted[0]["revision"] - 1)
        now = await current_state(session)
        for op in deleted[0]["resolved"]:
            kt = tuple(op["key"][c] for c in op["key"])
            assert now[op["table"]][kt] == then[op["table"]][kt]
        assert (bound.node_name,) in now["slipnet_node_defs"]
        # undo one entry by id: the depth edit of revision 3 goes back to 50
        edit = next(e for e in entries if e["revision"] == 3)
        assert (await undo(session, 1, entry_id=edit["id"], actor="admin")).changed
        assert (await current_state(session))["slipnet_node_defs"][("plato-zz",)]["conceptual_depth"] == 50
        assert [e["source"] for e in (await read_entries(session))[-2:]] == ["restore", "restore"]
        assert (await verify_journal(session)).ok


async def test_provenance_says_starting_state_or_who_changed_it(loaded):
    from server.services.journal_views import provenance

    await _write(loaded, [{"op": "update", "table": "engine_params",
                           "key": {"name": await _first(loaded, "engine_params")},
                           "set": {"value": "9", "value_type": "int"}}],
                 actor="admin")
    async with _s(loaded) as session:
        name = await _first(loaded, "engine_params")
        changed = await provenance(session, 1, "engine_params", {"name": name})
        assert not changed["from_starting_conceptual_state"]
        assert changed["text"] == "changed by source admin, actor admin, at version 2"
        other = (await session.execute(text("SELECT name FROM engine_params WHERE name <> :n LIMIT 1"), {"n": name})).scalar_one()
        untouched = await provenance(session, 1, "engine_params", {"name": other})
        assert untouched == {"from_starting_conceptual_state": True,
                             "text": "from the Starting Conceptual State"}


async def _first(engine, table: str) -> str:
    async with _s(engine) as session:
        return (await session.execute(text(f"SELECT name FROM {table} ORDER BY sort_order LIMIT 1"))).scalar_one()


# ──────────────────────────────────────────────────────────────────
# Door 2, and a session's configuration
# ──────────────────────────────────────────────────────────────────


async def _session_configuration(engine) -> int:
    from server.models.journal import Configuration

    async with _s(engine) as session:
        row = Configuration(kind="session", revision=0)
        session.add(row)
        await session.commit()
        return row.id


def _pending(revision: int, occurred_at, **kw):
    from server.services.journal import PendingEntry

    return PendingEntry(
        revision=revision, source=kw.pop("source", "learner"), actor=kw.pop("actor", "learner:x"),
        proposed=[], resolved=[], before=[], occurred_at=occurred_at, **kw,
    )


async def test_write_deferred_keeps_occurred_at_and_stamps_recorded_at(loaded):
    from server.models.journal import Configuration
    from server.services.journal import write_deferred
    from server.services.journal_views import read_entries

    cid = await _session_configuration(loaded)
    t0 = datetime.now(timezone.utc) - timedelta(hours=1)
    entries = [
        _pending(1, t0, episode_version=3, config_hash="h1"),
        _pending(2, t0 + timedelta(minutes=1), episode_version=5, source="admin", actor="admin"),
    ]
    async with _s(loaded) as session:
        ids = await write_deferred(session, configuration_id=cid, entries=entries, commit=True)
        assert len(ids) == 2
    async with _s(loaded) as session:
        stored = await read_entries(session, cid)
        assert [e["revision"] for e in stored] == [1, 2]
        assert stored[0]["occurred_at"] == t0 and stored[0]["recorded_at"] > t0
        assert stored[0]["recorded_at"] == stored[1]["recorded_at"]
        assert [e["episode_version"] for e in stored] == [3, 5]
        cfg = (await session.execute(select(Configuration).where(Configuration.id == cid))).scalars().one()
        assert cfg.revision == 2 and cfg.config_hash == "h1"


async def test_write_deferred_refuses_a_gap_the_global_configuration_and_a_failed_stop_leaves_nothing(loaded):
    from server.services.journal import JournalError, write_deferred
    from server.services.journal_views import read_entries

    cid = await _session_configuration(loaded)
    now = datetime.now(timezone.utc)
    async with _s(loaded) as session:
        with pytest.raises(JournalError, match="does not follow"):
            await write_deferred(session, configuration_id=cid, entries=[_pending(2, now)], commit=True)
    async with _s(loaded) as session:
        with pytest.raises(JournalError, match="Stop write"):
            await write_deferred(session, configuration_id=1, entries=[_pending(2, now)], commit=True)
    async with _s(loaded) as session:
        with pytest.raises(JournalError):
            await write_deferred(session, configuration_id=cid,
                                 entries=[_pending(1, now), _pending(3, now)], commit=True)
    async with _s(loaded) as session:
        assert await read_entries(session, cid) == []


async def test_write_immediate_is_for_the_global_configuration_until_c8(loaded):
    cid = await _session_configuration(loaded)
    with pytest.raises(NotImplementedError):
        await _write(loaded, [_node("plato-zz")], configuration_id=cid)


# ──────────────────────────────────────────────────────────────────
# Append-only
# ──────────────────────────────────────────────────────────────────


async def test_a_journal_entry_cannot_be_updated_or_deleted(loaded):
    from sqlalchemy import delete as sa_delete

    from server.models.journal import JournalEntry, JournalImmutable

    async with _s(loaded) as session:
        entry = (await session.execute(select(JournalEntry))).scalars().first()
        entry.note = "rewritten"
        with pytest.raises(JournalImmutable):
            await session.flush()
        await session.rollback()
    async with _s(loaded) as session:
        with pytest.raises(JournalImmutable):
            await session.execute(update(JournalEntry).values(note="x"))
        await session.rollback()
        with pytest.raises(JournalImmutable):
            await session.execute(sa_delete(JournalEntry))
        await session.rollback()
        entry = (await session.execute(select(JournalEntry))).scalars().first()
        await session.delete(entry)
        with pytest.raises(JournalImmutable):
            await session.flush()
        await session.rollback()
    async with _s(loaded) as session:
        assert (await session.execute(select(JournalEntry.note))).scalars().first() != "rewritten"


async def test_the_layer_module_has_no_way_to_change_an_entry():
    """The layer's public surface adds entries; it has no update or delete of one."""
    from server.services import journal, journal_views

    public = [n for n in dir(journal) + dir(journal_views) if not n.startswith("_")]
    assert not [n for n in public if n.startswith(("update_entry", "delete_entry", "edit_entry", "rewrite"))]
