"""C14a: ``resolve``'s ops are accepted by the journal layer and give the database the
document ``apply_resolved`` predicts.

For each batch: read the document from a scratch database loaded with the Metacat Standard
Configuration, ``resolve`` the batch, write the resolved ops through ``write_immediate`` (so
foreign keys, the re-key refusal and the cascade backstop all apply), read the document back
and compare it with ``apply_resolved(cfg, resolved)``.  Also the journal's own round trip:
``verify_journal`` is clean.  Uses ``C14A_DATABASE_URL`` (default: database ``petacat_c14a`` on
the harness server) and skips when Postgres is unreachable.
"""

from __future__ import annotations

import os
import socket

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from server.services import config_document as cd
from server.services.change_resolve import resolve
from tests.integration.equivalence_harness import SEED_DIR, ensure_database, harness_db_url


def scratch_url() -> str:
    default = harness_db_url().rsplit("/", 1)[0] + "/petacat_c14a"
    return os.environ.get("C14A_DATABASE_URL", default)


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

LOCK_KEY = 0x7E7AC14A


@pytest.fixture
async def loaded():
    import server.models.run  # noqa: F401
    import server.models.training_mode_session  # noqa: F401
    from server.models.metadata import Base
    from server.services.standard_configuration import seed_metadata_from_json

    url = scratch_url()
    await ensure_database(url)
    eng = create_async_engine(url, poolclass=NullPool)
    lock = await eng.connect()
    await lock.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(eng, expire_on_commit=False) as session:
        await seed_metadata_from_json(session, SEED_DIR)
        await session.commit()
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
        await lock.close()
        await eng.dispose()


async def _document(eng) -> cd.ConfigDocument:
    async with AsyncSession(eng, expire_on_commit=False) as session:
        return await cd.document_from_db(session)


async def _apply(eng, batch):
    from server.services.journal import write_immediate

    cfg = await _document(eng)
    resolved, report = resolve(cfg, batch)
    async with AsyncSession(eng, expire_on_commit=False) as session:
        await write_immediate(session, ops=resolved, source="admin", actor="admin")
    return cfg, resolved, report


def _same_rows(a: cd.ConfigDocument, b: cd.ConfigDocument) -> None:
    for name in a.tables:
        if name.endswith("_types") or name in ("codelet_families", "codelet_phases", "posting_directions",
                                               "clause_types", "proposal_levels", "run_statuses",
                                               "rule_types", "theme_types", "bridge_orientations"):
            continue
        assert list(a.tables[name].items()) == list(b.tables[name].items()), name


BATCHES = {
    "rename a node with role bindings and a relation row": [
        {"op": "rename_node", "old": "plato-length", "new": "plato-extent"},
        {"op": "rename_node", "old": "plato-opposite", "new": "plato-reverse"}],
    "rename a codelet type with role bindings": [
        {"op": "update", "table": "codelet_type_defs", "key": {"name": "rule-scout"}, "fields": {"name": "rule-scout-2"}},
        {"op": "update", "table": "codelet_type_defs", "key": {"name": "bottom-up-bond-scout"}, "fields": {"name": "bond-scout-2"}}],
    "rename an urgency level": [{"op": "update", "table": "urgency_levels", "key": {"name": "very_high"}, "fields": {"name": "vh"}}],
    "remove a relation node": [{"op": "remove_node", "name": "plato-opposite"}],
    "remove a role's node and the successor chain": [
        {"op": "remove_node", "name": "plato-length"}, {"op": "remove_node", "name": "plato-successor"},
        {"op": "remove_node", "name": "plato-b", "splice": ["plato-predecessor"]}],
    "remove a codelet type and an urgency level": [
        {"op": "remove_codelet_type", "name": "bottom-up-bond-scout"},
        {"op": "delete", "table": "urgency_levels", "key": {"name": "high"}}],
    "merge two nodes": [{"op": "merge_nodes", "keep": "plato-letter-category", "drop": "plato-length"},
                        {"op": "merge_nodes", "keep": "plato-a", "drop": "plato-b"}],
    "add a node with everything": [
        {"op": "add_node", "name": "x1", "fields": {"short_name": "x", "conceptual_depth": 5},
         "links": [{"to": "plato-a", "type": "lateral", "fixed": False}], "roles": ["rule.dimension_order"],
         "layout": {"grid_row": 8, "grid_col": 8}, "theme_dimension": {"valid_relations": ["identity"]},
         "params": {"top_down_slipnodes": True, "intrinsic_link_lengths": 40}},
        {"op": "add_trigger", "rule_key": "top-down-bond-scout:category", "node": "x1"},
        {"op": "reorder", "table": "slipnet_node_defs", "key": {"name": "x1"}, "before": {"name": "plato-a"}}],
    "remove every node": None,
    "relative ops and a patch": [
        {"op": "adjust_param", "name": "update_cycle_length", "by": 5},
        {"op": "adjust_coefficient", "name": "temp_exponent_base", "by": 0.25},
        {"op": "set_template", "key": "all", "path": "/brand_new", "text": "hi"}],
}


@pytest.mark.parametrize("label", list(BATCHES))
async def test_resolved_ops_write_through_the_journal_and_match_apply_resolved(loaded, label):
    ops = BATCHES[label]
    if ops is None:
        cfg = await _document(loaded)
        ops = [{"op": "remove_node", "name": k[0]} for k in cfg.tables["slipnet_node_defs"]]
    cfg, resolved, report = await _apply(loaded, {"ops": ops})
    assert report["ok"]
    expected = cd.apply_resolved(cfg, resolved)
    _same_rows(await _document(loaded), expected)


async def test_the_journal_round_trips_after_the_batches(loaded):
    from server.services.journal_views import verify_journal

    for label, ops in BATCHES.items():
        if ops is not None and label.startswith(("rename", "remove a relation", "merge")):
            await _apply(loaded, {"ops": ops})
            break
    async with AsyncSession(loaded, expire_on_commit=False) as session:
        report = await verify_journal(session)
        assert report.ok, report.problems
