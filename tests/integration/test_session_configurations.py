"""C8: a Training Mode Session's configuration as an entity (configuration plan 3.10, 3.14).

Against a scratch database (``C8_DATABASE_URL``; default: the harness server, database
``petacat_c8``), skipped when Postgres is unreachable.  Covers creating a session's
configuration from the Metacat Standard Configuration, the global configuration and another
session; the creation overrides (journaled, ``source = creation``); the Starting Conceptual
State and provenance; editing a Stopped session's configuration through ``ChangeService`` and
reading every revision back through ``ConfigurationStore.provider``; M1 and M2; the meta edit;
status, diff, reset, restore and verify for a session; the live source; and the delete cascade.
"""

from __future__ import annotations

import os
import socket

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.equivalence_harness import SEED_DIR, ensure_database, harness_db_url


def scratch_url() -> str:
    default = harness_db_url().rsplit("/", 1)[0] + "/petacat_c8"
    return os.environ.get("C8_DATABASE_URL", default)


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

LOCK_KEY = 0x7E7AC008


@pytest.fixture
async def engine():
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
    from server.services.configuration_startup import first_load

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await first_load(session, SEED_DIR)
        await session.commit()
    return engine


def _s(engine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


async def new_session_row(engine, name: str = "S") -> int:
    from server.models.training_mode_session import TrainingModeSession

    async with _s(engine) as session:
        row = TrainingModeSession(name=name, backend="single", policy={}, max_codelets=20000)
        session.add(row)
        await session.commit()
        return row.id


async def make_config(engine, name="S", base="global", overrides=None, **kw) -> tuple[int, int]:
    """``(session_id, configuration_id)`` of a new session with its configuration."""
    from server.services.configurations import create_session_configuration

    sid = await new_session_row(engine, name)
    async with _s(engine) as session:
        cid = await create_session_configuration(session, sid, base, overrides, **kw)
        await session.commit()
    return sid, cid


def node(name: str, **extra) -> dict:
    return {
        "op": "insert", "table": "slipnet_node_defs",
        "row": {"name": name, "short_name": name[:4], "conceptual_depth": 50, **extra},
    }


def param(name: str, value) -> dict:
    return {"op": "update", "table": "engine_params", "key": {"name": name}, "fields": {"value": value}}


def batch(*ops, configuration_id: int, **envelope) -> dict:
    return {"source": "admin", "actor": "admin", "base_version": "head", "ops": list(ops),
            "configuration_id": configuration_id, **envelope}


async def apply(engine, b):
    from server.services.configuration_writer import ChangeService

    async with _s(engine) as session:
        return await ChangeService.apply(session, b)


async def doc(engine, cid, revision=None):
    from server.services import configurations

    async with _s(engine) as session:
        return await configurations.config_at(session, cid, revision)


async def global_state(engine):
    """``(revision, config_hash, document tables as dicts)`` of the global configuration."""
    from server.services import config_document as cd

    async with _s(engine) as session:
        row = (await session.execute(text("SELECT revision, config_hash FROM configurations WHERE id = 1"))).one()
        d = await cd.document_from_db(session)
    return row[0], row[1], {t: dict(d.tables[t]) for t in cd.TABLE_NAMES}


async def a_param(engine) -> tuple[str, object]:
    d = await doc(engine, 1)
    name, row = next(iter(d.tables["engine_params"].items()))
    return name[0], row["value"]


# ---------------------------------------------------------------------------
# Creating a session's configuration
# ---------------------------------------------------------------------------


async def test_create_from_standard_is_a_replica_of_the_metacat_standard_configuration(loaded):
    from server.services import config_document as cd
    from server.services.configuration_admin import reference_document
    from server.services.configurations import get_row

    sid, cid = await make_config(loaded, "Alpha", base="standard")
    assert cid != 1
    d = await doc(loaded, cid)
    assert d.content_equals(reference_document())
    async with _s(loaded) as session:
        row = await get_row(session, cid)
    assert (row["kind"], row["session_id"], row["name"], row["revision"], row["frozen"]) == (
        "session", sid, "Alpha", 0, False)
    assert row["config_hash"] == row["base_snapshot_hash"] == cd.config_hash(reference_document())
    assert (row["created_from_configuration_id"], row["created_from_revision"]) == (None, None)


async def test_create_from_global_copies_the_global_configuration_as_it_is_now(loaded):
    name, value = await a_param(loaded)
    new_value = "7" if str(value) != "7" else "8"
    await apply(loaded, batch(param(name, new_value), configuration_id=1))
    g_rev, g_hash, g_tables = await global_state(loaded)
    sid, cid = await make_config(loaded, "FromGlobal")  # base defaults to 'global'
    d = await doc(loaded, cid)
    assert {t: dict(d.tables[t]) for t in g_tables} == g_tables
    from server.services.configurations import get_row

    async with _s(loaded) as session:
        row = await get_row(session, cid)
    assert (row["created_from_configuration_id"], row["created_from_revision"]) == (1, g_rev)
    assert row["config_hash"] == g_hash


async def test_create_from_another_session_copies_its_current_configuration(loaded):
    _, first = await make_config(loaded, "First", base="standard")
    await apply(loaded, batch(node("c8-copied"), configuration_id=first, source="external", actor="x"))
    sid2, second = await make_config(loaded, "Second", base={"session_id": (await _sid_of(loaded, first))})
    d2, d1 = await doc(loaded, second), await doc(loaded, first)
    assert d2.content_equals(d1)
    from server.services.configurations import get_row

    async with _s(loaded) as session:
        row = await get_row(session, second)
    assert (row["created_from_configuration_id"], row["created_from_revision"]) == (first, 1)
    # the copy is its own: editing the first leaves the second alone
    await apply(loaded, batch(node("c8-later"), configuration_id=first))
    assert ("c8-later",) not in (await doc(loaded, second)).tables["slipnet_node_defs"]


async def _sid_of(engine, cid) -> int:
    async with _s(engine) as session:
        return (await session.execute(text("SELECT session_id FROM configurations WHERE id = :i"), {"i": cid})).scalar_one()


async def test_a_bad_base_or_a_missing_session_is_refused_and_writes_nothing(loaded):
    from server.services.configurations import BadBase, UnknownConfiguration, create_session_configuration

    sid = await new_session_row(loaded)
    for base, error in (("nope", BadBase), ({"session_id": 999}, UnknownConfiguration),
                        ({"session_id": True}, BadBase)):
        async with _s(loaded) as session:
            with pytest.raises(error):
                await create_session_configuration(session, sid, base)
    async with _s(loaded) as session:
        assert (await session.execute(select(func.count()).select_from(text("configurations")))).scalar_one() == 1


async def test_creation_overrides_are_one_journaled_batch_with_source_creation(loaded):
    from server.services import config_document as cd
    from server.services.configuration_admin import reference_document
    from server.services.configurations import base_document, get_row
    from server.services.journal_views import provenance, read_entries

    name, value = await a_param(loaded)
    new_value = "7" if str(value) != "7" else "8"
    overrides = [param(name, new_value), node("c8-start")]
    sid, cid = await make_config(loaded, "Over", base="standard", overrides=overrides, actor="creator")
    async with _s(loaded) as session:
        entries = await read_entries(session, cid)
        row = await get_row(session, cid)
        base = await base_document(session, cid)
        assert [(e["revision"], e["source"], e["actor"]) for e in entries] == [(1, "creation", "creator")]
        assert entries[0]["proposed"] == overrides
        assert [op["op"] for op in entries[0]["resolved"]] == ["update", "insert"]
        # the base snapshot is the Starting Conceptual State: the state AFTER the creation batch
        assert row["revision"] == 1 and base.version == 1
        assert row["base_snapshot_hash"] == row["config_hash"] == cd.config_hash(base)
        current = await doc(loaded, cid)
        assert current.content_equals(base)
        assert ("c8-start",) in current.tables["slipnet_node_defs"]
        # provenance: untouched rows and the overridden rows are both "from the Starting Conceptual State"
        for table, key in (("engine_params", {"name": name}), ("slipnet_node_defs", {"name": "c8-start"}),
                           ("slipnet_node_defs", {"name": "plato-a"})):
            got = await provenance(session, cid, table, key)
            assert got["from_starting_conceptual_state"], (table, key)
    # revision 0 is the plain base with the creation batch undone
    zero = await doc(loaded, cid, 0)
    assert zero.content_equals(reference_document())
    # a later change is "changed by source ..."
    await apply(loaded, batch(param(name, "5"), configuration_id=cid, source="learner", actor="learner:t"))
    async with _s(loaded) as session:
        got = await provenance(session, cid, "engine_params", {"name": name})
    assert not got["from_starting_conceptual_state"]
    assert "source learner" in got["text"] and "actor learner:t" in got["text"]


async def test_a_refused_override_raises_and_leaves_no_configuration(loaded):
    from server.services.configuration_writer import ChangeError

    bad = {"op": "update", "table": "engine_params", "key": {"name": "no-such-param"}, "fields": {"value": "1"}}
    sid = await new_session_row(loaded)
    from server.services.configurations import create_session_configuration

    async with _s(loaded) as session:
        with pytest.raises(ChangeError):
            await create_session_configuration(session, sid, "standard", [bad])
        await session.rollback()
    async with _s(loaded) as session:
        assert (await session.execute(text("SELECT count(*) FROM configurations WHERE kind = 'session'"))).scalar_one() == 0


# ---------------------------------------------------------------------------
# Writes to a Stopped session's configuration, and reading every revision
# ---------------------------------------------------------------------------


async def test_a_stopped_sessions_configuration_is_edited_and_read_back_at_each_revision(loaded):
    from server.services import config_document as cd
    from server.services.configuration_store import ConfigurationStore
    from server.services.metadata_service import load_metadata_from_db

    sid, cid = await make_config(loaded, "Edit", base="standard")
    name, value = await a_param(loaded)
    seen = {0: await doc(loaded, cid)}
    for i, op in enumerate([node("c8-a"), param(name, "9"), node("c8-b")], start=1):
        report = await apply(loaded, batch(op, configuration_id=cid, source="learner" if i == 2 else "admin",
                                           actor="learner:t" if i == 2 else "admin"))
        assert report["persisted"] and report["version_before"] == i - 1 and report["version_after"] == i
        seen[i] = await doc(loaded, cid)
    async with _s(loaded) as session:
        store = ConfigurationStore(await load_metadata_from_db(session), 1)
        for revision, expected in seen.items():
            view = await store.provider(session, cid, revision)
            assert view.revision == revision and view.source == "stored"
            assert view.config_hash == cd.config_hash(expected)
            assert view.provider.slipnet_node_specs == cd.provider(expected).slipnet_node_specs
        # the stored current state is config_at at the current revision, and "now" is the same
        stored = await doc(loaded, cid)
        assert stored.content_equals(seen[3])
        current = await store.provider(session, cid)
        assert current.revision == 3 and current.config_hash == cd.config_hash(seen[3])
        assert ("c8-a",) in seen[1].tables["slipnet_node_defs"] and ("c8-a",) not in seen[0].tables["slipnet_node_defs"]
        assert seen[2].tables["engine_params"][(name,)]["value"] == "9"
        assert seen[1].tables["engine_params"][(name,)]["value"] == value
        with pytest.raises(Exception, match="revisions 0 to 3"):
            await store.provider(session, cid, 4)


async def test_config_at_by_episode_version(loaded):
    sid, cid = await make_config(loaded, "Epi", base="standard")
    from server.services.configurations import config_at
    from server.services.journal import write_immediate

    for version, n in ((10, "c8-v10"), (20, "c8-v20")):
        async with _s(loaded) as session:
            await write_immediate(session, ops=[node(n)], source="learner", actor="learner:t",
                                  configuration_id=cid, episode_version=version)
    async with _s(loaded) as session:
        at15 = await config_at(session, cid, episode_version=15)
        at25 = await config_at(session, cid, episode_version=25)
        at5 = await config_at(session, cid, episode_version=5)
    assert ("c8-v10",) in at15.tables["slipnet_node_defs"] and ("c8-v20",) not in at15.tables["slipnet_node_defs"]
    assert ("c8-v20",) in at25.tables["slipnet_node_defs"]
    assert ("c8-v10",) not in at5.tables["slipnet_node_defs"]


async def test_the_session_path_writes_what_the_global_path_writes(loaded):
    """The same batch on the global configuration and on a replica gives the same resolved ops,
    before-images and ``config_hash`` (inserts completed with defaults, deletes with cascades)."""
    from server.services.journal_views import read_entries

    sid, cid = await make_config(loaded, "Same", base="global")
    ops = [
        node("c8-new"),
        {"op": "insert", "table": "engine_params", "row": {"name": "c8-p", "value": "1", "value_type": "int"}},
        {"op": "delete", "table": "slipnet_node_defs", "key": {"name": "plato-a"}},
    ]
    g = await apply(loaded, batch(*ops, configuration_id=1))
    s = await apply(loaded, batch(*ops, configuration_id=cid))
    assert g["persisted"] and s["persisted"]
    async with _s(loaded) as session:
        ge = (await read_entries(session, 1))[-1]
        se = (await read_entries(session, cid))[-1]
    assert se["resolved"] == ge["resolved"] and se["before"] == ge["before"]
    assert se["config_hash"] == ge["config_hash"]
    assert len(se["resolved"]) > len(ops)  # the cascade of the node's links is in the entry


async def test_verify_journal_status_diff_reset_and_restore_work_for_a_session(loaded):
    from server.services import configuration_admin as admin

    sid, cid = await make_config(loaded, "Admin", base="standard", overrides=[node("c8-start")])
    name, value = await a_param(loaded)
    await apply(loaded, batch(param(name, "9"), node("c8-extra"), configuration_id=cid))
    async with _s(loaded) as session:
        st = await admin.status(session, cid)
        assert st["kind"] == "session" and st["revision"] == 2 and not st["equals_standard"]
        assert st["differs_rows"] == 3 and st["standard_hash"] is None
        diff = await admin.diff(session, cid)
        assert (diff["added"], diff["changed"], diff["removed"]) == (2, 1, 0)
        verify = await admin.verify_journal(session, cid)
        assert verify["ok"], verify["problems"]
    async with _s(loaded) as session:
        part = await admin.restore_selected(session, [{"table": "engine_params", "key": {"name": name}}], cid)
        assert part["wrote"] and part["revision"] == 3
    async with _s(loaded) as session:
        assert (await admin.diff(session, cid))["count"] == 2
        done = await admin.reset_to_standard(session, cid)
        assert done["wrote"] and done["revision"] == 4
        again = await admin.reset_to_standard(session, cid)
        assert not again["wrote"]
        st = await admin.status(session, cid)
        assert st["equals_standard"] and st["differs_rows"] == 0
        assert (await admin.verify_journal(session, cid))["ok"]
    # the global configuration was not touched by any of it
    async with _s(loaded) as session:
        assert (await admin.status(session, 1))["revision"] == 1


async def test_a_tampered_stored_state_is_found_by_verify_journal(loaded):
    from server.services import configuration_admin as admin

    sid, cid = await make_config(loaded, "Tamper", base="standard")
    await apply(loaded, batch(node("c8-t"), configuration_id=cid))
    async with _s(loaded) as session:
        data = (await session.execute(text(
            "SELECT data FROM configuration_snapshots WHERE configuration_id = :c AND role = 'current'"),
            {"c": cid})).scalar_one()
        data["tables"]["slipnet_node_defs"] = [r for r in data["tables"]["slipnet_node_defs"] if r["name"] != "c8-t"]
        import json
        await session.execute(text(
            "UPDATE configuration_snapshots SET data = CAST(:d AS json) WHERE configuration_id = :c AND role = 'current'"),
            {"d": json.dumps(data), "c": cid})
        await session.commit()
    async with _s(loaded) as session:
        verify = await admin.verify_journal(session, cid)
        assert not verify["ok"] and verify["problems"]


# ---------------------------------------------------------------------------
# M1, M2, M3
# ---------------------------------------------------------------------------


async def test_m1_the_global_configuration_is_unchanged_by_any_number_of_session_edits(loaded):
    from server.services.configuration_store import ConfigurationStore
    from server.services.metadata_service import load_metadata_from_db

    sid, cid = await make_config(loaded, "M1", base="global")
    before = await global_state(loaded)
    async with _s(loaded) as session:
        store = ConfigurationStore(await load_metadata_from_db(session), before[0])
        held = store.current()
        hash_before = (await store.provider(session, 1)).config_hash
    name, _ = await a_param(loaded)
    for i in range(6):
        await apply(loaded, batch(node(f"c8-m1-{i}"), param(name, str(20 + i)), configuration_id=cid,
                                  source="learner", actor="learner:t"))
    assert await global_state(loaded) == before
    async with _s(loaded) as session:
        again = await store.provider(session, 1)
        assert again.provider is held and again.config_hash == hash_before
        assert (await store.provider(session, 1, before[0])).config_hash == hash_before
        entries = (await session.execute(text("SELECT count(*) FROM configuration_journal WHERE configuration_id = 1"))).scalar_one()
        assert entries == 1  # still just the Metacat Standard Configuration's load


async def test_m2_a_session_takes_learner_and_external_changes_and_the_global_refuses_them(loaded):
    from server.services.configuration_writer import ChangeError

    sid, cid = await make_config(loaded, "M2", base="standard")
    for source in ("learner", "external", "admin", "import", "restore", "reset"):
        report = await apply(loaded, batch(node(f"c8-{source}"), configuration_id=cid, source=source,
                                           actor="learner:t" if source == "learner" else "a"))
        assert report["persisted"]
    for source in ("learner", "external"):
        with pytest.raises(ChangeError) as caught:
            await apply(loaded, batch(node("c8-no"), configuration_id=1, source=source, actor="x"))
        assert caught.value.code == "source_refused"


async def test_a_dry_run_on_a_session_writes_nothing(loaded):
    sid, cid = await make_config(loaded, "Dry", base="standard")
    report = await apply(loaded, batch(node("c8-dry"), configuration_id=cid, dry_run=True))
    assert report["persisted"] is False and report["version_after"] == 0
    assert ("c8-dry",) not in (await doc(loaded, cid)).tables["slipnet_node_defs"]


async def test_a_stale_base_on_a_session_is_409_stale(loaded):
    from server.services.configuration_writer import ChangeError

    sid, cid = await make_config(loaded, "Stale", base="standard")
    await apply(loaded, batch(node("c8-s1"), configuration_id=cid))
    with pytest.raises(ChangeError) as caught:
        await apply(loaded, batch(node("c8-s2"), configuration_id=cid, base_version=0))
    assert caught.value.code == "stale"


# ---------------------------------------------------------------------------
# The meta edit, the list, rows and export
# ---------------------------------------------------------------------------


async def test_name_note_and_frozen_are_a_journaled_entry_with_no_ops(loaded):
    from server.services import configuration_admin as admin
    from server.services import configurations
    from server.services.journal_views import read_entries

    sid, cid = await make_config(loaded, "Meta", base="standard")
    async with _s(loaded) as session:
        out = await configurations.update_meta(session, cid, name="Renamed", frozen=True)
        assert (out["name"], out["frozen"], out["revision"]) == ("Renamed", True, 1)
        entry = (await read_entries(session, cid))[-1]
        assert entry["resolved"] == [] and entry["before"] == [] and entry["source"] == "admin"
        assert entry["proposed"] == {"meta": {"name": "Renamed", "frozen": True},
                                     "was": {"name": "Meta", "frozen": False}}
        same = await configurations.update_meta(session, cid, name="Renamed")
        assert same["revision"] == 1  # nothing changed: nothing written
        with pytest.raises(configurations.ConfigurationError):
            await configurations.update_meta(session, cid, name="  ")
        assert (await admin.verify_journal(session, cid))["ok"]
        # the configuration itself is unchanged by it
        assert (await doc(loaded, cid)).content_equals(await doc(loaded, cid, 0))
        # the global configuration's name
        g = await configurations.summary(session, 1)
        assert g["name"] == "Metacat Mode: global configuration" and g["mode_label"] == "Metacat Mode"


async def test_the_list_has_the_manager_fields_and_orders_global_first(loaded):
    from server.services import configurations

    sid, cid = await make_config(loaded, "Listed", base="standard", overrides=[node("c8-l")])
    async with _s(loaded) as session:
        listed = await configurations.list_configurations(session)
    assert [c["id"] for c in listed] == [1, cid]
    g, s = listed
    assert (g["mode"], g["session_id"], g["session_state"], g["equals_standard"]) == ("Metacat Mode", None, None, True)
    assert (s["mode"], s["mode_label"], s["session_id"], s["session_state"]) == (
        "Training Mode", "Training Mode: Listed", sid, "stopped")
    assert s["differs_from_standard_rows"] == 1 and not s["equals_standard"] and s["revision"] == 1
    assert s["last_change"]["source"] == "creation" and s["frozen"] is False and s["source"] == "stored"
    assert s["base_snapshot_hash"] == s["config_hash"]


async def test_rows_and_export(loaded):
    from server.services import configurations

    sid, cid = await make_config(loaded, "Rows", base="standard", overrides=[node("c8-r")])
    async with _s(loaded) as session:
        counts = await configurations.rows(session, cid)
        assert counts["tables"]["slipnet_node_defs"] == (await configurations.rows(session, 1))["tables"]["slipnet_node_defs"] + 1
        nodes = await configurations.rows(session, cid, "slipnet_node_defs")
        assert nodes["key_columns"] == ["name"] and any(r["name"] == "c8-r" for r in nodes["rows"])
        with pytest.raises(configurations.UnknownTable):
            await configurations.rows(session, cid, "training_mode_sessions")
        bundle = await configurations.export(session, cid)
        assert bundle["format"] == "petacat-configuration" and bundle["configuration"]["id"] == cid
        from server.services import config_document as cd

        assert cd.from_data(bundle["data"]).content_equals(await doc(loaded, cid))


# ---------------------------------------------------------------------------
# The live source, and the global store
# ---------------------------------------------------------------------------


async def test_a_registered_live_source_answers_for_a_live_session_and_marks_it(loaded):
    from server.services import config_document as cd
    from server.services.configuration_store import ConfigurationStore, LiveState, set_live_source
    from server.services.metadata_service import load_metadata_from_db

    sid, cid = await make_config(loaded, "Live", base="standard")
    stored = await doc(loaded, cid)
    resolved_insert = {"op": "insert", "table": "engine_params", "key": {"name": "c8-live"},
                       "row": {"name": "c8-live", "value": "1", "value_type": "int", "sort_order": 999}}
    memory = cd.apply_resolved(stored, [resolved_insert], version=4)
    set_live_source(lambda session_id: LiveState("running", memory, 4, saved_through=0, unsaved=4)
                    if session_id == sid else None)
    try:
        async with _s(loaded) as session:
            store = ConfigurationStore(await load_metadata_from_db(session), 1)
            view = await store.provider(session, cid)
            assert (view.source, view.revision, view.saved_through, view.unsaved) == ("live", 4, 0, 4)
            assert view.config_hash == cd.config_hash(memory) != cd.config_hash(stored)
            # an earlier revision is always the database's
            assert (await store.provider(session, cid, 0)).source == "stored"
            from server.services import configurations

            summary = await configurations.summary(session, cid)
            assert (summary["session_state"], summary["source"], summary["unsaved"]) == ("running", "live", 4)
    finally:
        set_live_source(None)
    async with _s(loaded) as session:
        assert (await store.provider(session, cid)).source == "stored"


async def test_the_global_provider_at_an_earlier_revision_is_reconstructed(loaded):
    from server.services import config_document as cd
    from server.services.configuration_store import ConfigurationStore
    from server.services.metadata_service import load_metadata_from_db

    name, value = await a_param(loaded)
    first = await doc(loaded, 1)
    await apply(loaded, batch(param(name, "9" if str(value) != "9" else "8"), configuration_id=1))
    async with _s(loaded) as session:
        store = ConfigurationStore(await load_metadata_from_db(session), 2)
        old = await store.provider(session, 1, 1)
        assert old.revision == 1 and old.config_hash == cd.config_hash(first)
        assert (await store.provider(session, 1, 2)).config_hash != old.config_hash


# ---------------------------------------------------------------------------
# Deleting a session
# ---------------------------------------------------------------------------


async def test_deleting_a_session_removes_its_configuration_snapshots_and_journal(loaded):
    from server.models.training_mode_session import TrainingModeSession

    keep_sid, keep = await make_config(loaded, "Keep", base="standard", overrides=[node("c8-k")])
    sid, cid = await make_config(loaded, "Gone", base="standard", overrides=[node("c8-g")])
    await apply(loaded, batch(node("c8-g2"), configuration_id=cid, source="learner", actor="learner:t"))

    async def counts():
        async with _s(loaded) as session:
            out = {}
            for table, column in (("configurations", "id"), ("configuration_snapshots", "configuration_id"),
                                  ("configuration_journal", "configuration_id")):
                for label, value in (("gone", cid), ("keep", keep), ("global", 1)):
                    out[(table, label)] = (await session.execute(
                        text(f"SELECT count(*) FROM {table} WHERE {column} = :v"), {"v": value})).scalar_one()
        return out

    before = await counts()
    assert before[("configuration_journal", "gone")] == 2 and before[("configuration_snapshots", "gone")] == 2
    async with _s(loaded) as session:
        row = await session.get(TrainingModeSession, sid)
        await session.delete(row)  # what the session service does; the database cascades
        await session.commit()
    after = await counts()
    assert [after[(t, "gone")] for t in ("configurations", "configuration_snapshots", "configuration_journal")] == [0, 0, 0]
    assert after[("configuration_journal", "keep")] == before[("configuration_journal", "keep")]
    assert after[("configuration_snapshots", "keep")] == 2
    assert after[("configuration_journal", "global")] == before[("configuration_journal", "global")] >= 1
    assert after[("configurations", "global")] == 1


async def test_a_journal_entry_is_still_immutable_to_the_orm(loaded):
    from server.models.journal import JournalEntry, JournalImmutable

    sid, cid = await make_config(loaded, "Imm", base="standard", overrides=[node("c8-i")])
    async with _s(loaded) as session:
        entry = (await session.execute(select(JournalEntry).where(JournalEntry.configuration_id == cid))).scalars().first()
        await session.delete(entry)
        with pytest.raises(JournalImmutable):
            await session.flush()
        await session.rollback()


async def test_a_meta_edit_of_the_global_configuration_keeps_the_store_in_step(loaded):
    from server.services import configurations
    from server.services.configuration_store import ConfigurationStore, set_configuration_store
    from server.services.metadata_service import load_metadata_from_db

    async with _s(loaded) as session:
        store = ConfigurationStore(await load_metadata_from_db(session), 1)
    set_configuration_store(store)
    try:
        held = store.current()
        async with _s(loaded) as session:
            out = await configurations.update_meta(session, 1, note="the Metacat Mode configuration")
        assert out["revision"] == 2 and store.revision == 2
        assert store.current() is not held  # reloaded; the content is the same
        async with _s(loaded) as session:
            from server.services import config_document as cd

            assert (await store.provider(session, 1)).config_hash == cd.config_hash(await doc(loaded, 1, 1))
    finally:
        set_configuration_store(None)
