"""Rows that tie on ``sort_order`` or ``ordinal`` have one order, in the database and in a document.

``Slipnet.update_activations`` and the posting pass walk configuration rows in order, and order is
what the random stream is spent on, so a tie must not be left to the database's heap order or to
the order a document happened to be built in.  Every ordered table sorts by its order columns and
then the rest of its natural key (``config_registry.total_order``), with text compared by byte value
and a NULL key part read as ``''``.  The names below are chosen to separate the collations: an
upper-case letter, a hyphen against an underscore, and a name that sorts differently by byte value
than in a locale that ignores punctuation.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from server.models.metadata import EngineParam, ThemeRelation, UrgencyLevel
from server.services import config_document as cd
from server.services.metadata_service import load_rows_from_db
from tests.integration.equivalence_harness import database_reachable, fresh_database, harness_db_url

pytestmark = pytest.mark.skipif(
    not database_reachable(),
    reason="the scratch Postgres is not reachable (start it with scripts/dev.sh db)",
)

TIED = ["Zz-tie", "aa_tie", "aa-tie", "ab", "a-c", "Ba"]


def _in_rolled_back_transaction(body):
    fresh_database()

    async def go():
        engine = create_async_engine(harness_db_url(), poolclass=NullPool)
        try:
            async with AsyncSession(engine) as session:
                async with session.begin():
                    try:
                        return await body(session)
                    finally:
                        await session.rollback()
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_tied_rows_come_out_in_the_same_order_from_the_database_and_a_document():
    async def body(session):
        for name in TIED:
            session.add(EngineParam(name="t_" + name, value="1", value_type="int", sort_order=9999))
            session.add(UrgencyLevel(name="t_" + name, value=1, sort_order=9999))
            session.add(ThemeRelation(name="t_" + name, ordinal=9999))
        await session.flush()
        return await load_rows_from_db(session)

    rows = _in_rolled_back_transaction(body)
    for table, key in (("engine_params", "name"), ("urgency_levels", "name"),
                       ("theme_relations", "name")):
        from_db = [r[key] for r in rows[table] if r[key].startswith("t_")]
        assert len(from_db) == len(TIED)
        # The same rows handed to a document in the opposite order, and in a shuffled one.
        for arrangement in (list(reversed(rows[table])), rows[table][1::2] + rows[table][0::2]):
            doc = cd.from_rows({table: arrangement})
            from_doc = [r[key] for r in doc.tables[table].values() if r[key].startswith("t_")]
            assert from_doc == from_db, (table, from_doc, from_db)
        assert from_db == sorted(from_db, key=lambda n: n.encode("utf-8")), (table, from_db)


# ---------------------------------------------------------------------------
# Every table whose order reaches the engine
# ---------------------------------------------------------------------------

#: table -> (model name, key column for the tied clones, the columns to change per clone).
#: Each clone is the table's first Standard row with a new key and the tie value 9999 in its
#: order column, so every clone ties with every other.
_TIED_TABLES = {
    "slipnet_node_defs": ("SlipnetNodeDef", "name", {"glyph": None, "numeric_value": None}),
    "codelet_type_defs": ("CodeletTypeDef", "name", {}),
    "posting_rules": ("PostingRule", "rule_key", {}),
    "formula_coefficients": ("FormulaCoefficient", "name", {}),
    "codelet_pattern_defs": ("CodeletPatternDef", "pattern_name", {}),
}
_ORDER_COLUMN = {"codelet_pattern_defs": "ordinal"}

#: Links that tie on ``sort_order`` and differ only in their key; two of them differ only in a NULL
#: label against a named one, which is where the database and a document could disagree.
_TIED_LINKS = [
    ("t_nodeZ", "plato-a", None), ("t_nodeZ", "plato-a", "plato-successor"),
    ("t_nodeZ", "plato-b", None), ("t_nodeY", "plato-a", "plato-predecessor"),
    ("t_nodeY", "plato-a", None), ("T_nodeX", "plato-a", None),
]


def _model(name: str):
    from server.models import metadata as models

    return getattr(models, name)


def _clone(session, model, template: dict, **changes) -> None:
    columns = {c.name for c in model.__table__.columns} - {"id"}
    data = {k: v for k, v in template.items() if k in columns}
    data.update(changes)
    session.add(model(**data))


def _add_tied_rows(session, rows: dict) -> list[str]:
    """Add the tied clones to the session; the names of the tables touched."""
    from server.models.metadata import SlipnetLinkDef, SlipnetNodeDef

    for table, (model_name, key, extra) in _TIED_TABLES.items():
        order_column = _ORDER_COLUMN.get(table, "sort_order")
        template = rows[table][0]
        for name in TIED:
            _clone(session, _model(model_name), template, **{key: "t_" + name, order_column: 9999}, **extra)
    link_template = rows["slipnet_link_defs"][0]
    for source, dest, label in _TIED_LINKS:
        _clone(session, SlipnetLinkDef, link_template, from_node=source, to_node=dest,
               label_node=label, sort_order=9999)
    return [*_TIED_TABLES, "slipnet_link_defs"]


def _tie_keys(table: str, rows: list[dict]) -> list[tuple]:
    from server.services.config_registry import LAYER_REGISTRY

    spec = LAYER_REGISTRY[table]
    order_column = spec.order[0]
    return [spec.key_tuple(spec.key_of(r)) for r in rows if r[order_column] == 9999]


async def _database_with_ties(session):
    # The nodes the tied links join must exist; the Standard nodes plato-a/b and the successor and
    # predecessor labels do, and plato-y, plato-z and Plato-x are added as tied nodes' siblings.
    rows = await load_rows_from_db(session)
    from server.models.metadata import SlipnetNodeDef

    for name in ("t_nodeY", "t_nodeZ", "T_nodeX"):
        _clone(session, SlipnetNodeDef, rows["slipnet_node_defs"][0], name=name, sort_order=9999,
               glyph=None, numeric_value=None)
    _add_tied_rows(session, rows)
    await session.flush()
    return await load_rows_from_db(session)


@pytest.mark.parametrize("table", [*_TIED_TABLES, "slipnet_link_defs"])
def test_tied_rows_of_every_engine_ordered_table_come_out_in_the_same_order_on_both_paths(table):
    rows = _in_rolled_back_transaction(_database_with_ties)
    from_db = _tie_keys(table, rows[table])
    expected = {"slipnet_link_defs": len(_TIED_LINKS), "slipnet_node_defs": len(TIED) + 3}
    assert len(from_db) == expected.get(table, len(TIED))
    for arrangement in (list(reversed(rows[table])), rows[table][1::2] + rows[table][0::2]):
        doc = cd.from_rows({table: arrangement})
        from_doc = _tie_keys(table, list(doc.tables[table].values()))
        assert from_doc == from_db, (table, from_doc, from_db)
    if table == "slipnet_link_defs":  # the NULL label sorts as '' (before a named one) on both paths
        unnamed = next(k for k in from_db if k[:2] == ("t_nodeZ", "plato-a") and k[3] == "")
        named = next(k for k in from_db if k[:2] == ("t_nodeZ", "plato-a") and k[3] == "plato-successor")
        assert from_db.index(unnamed) < from_db.index(named)


def test_a_configuration_with_tied_nodes_and_links_gives_one_provider_and_one_run_on_both_paths():
    from tests.integration.equivalence_harness import run_signature

    from server.services.metadata_service import provider_from_tables

    rows = _in_rolled_back_transaction(_database_with_ties)
    db_provider = provider_from_tables(rows)
    # Reverse every table that has order columns; an id-ordered table's order is its insertion order,
    # so the same rows in another order would be another configuration.
    id_ordered = {"commentary_templates", "demo_problems", "theme_dimension_defs"}
    scrambled = {t: (r if t in id_ordered else list(reversed(r))) for t, r in rows.items()}
    doc_provider = cd.provider(cd.from_rows(scrambled))

    def order(meta):
        return (
            list(meta.slipnet_node_specs),
            [(link.from_node, link.to_node, link.link_type, link.label_node) for link in meta.slipnet_link_specs],
            list(meta.codelet_specs),
            [r.rule_key for r in meta.posting_rules],
            list(meta.formula_coefficients),
        )

    assert order(doc_provider) == order(db_provider)
    tied_nodes = [n for n in order(db_provider)[0] if n.lower().startswith("t_")]
    assert tied_nodes == sorted(tied_nodes, key=lambda n: n.encode("utf-8")) and len(tied_nodes) == len(TIED) + 3
    for problem, seed in ((("abc", "abd", "ijk", None), 1), (("abc", "abd", "mrrjjj", None), 2)):
        assert run_signature(doc_provider, problem, seed) == run_signature(db_provider, problem, seed)


# ---------------------------------------------------------------------------
# The id-ordered tables: insertion order on both paths
# ---------------------------------------------------------------------------

_ID_TABLES = {
    "demo_problems": ("DemoProblem", "name"),
    "commentary_templates": ("CommentaryTemplate", "template_key"),
    "theme_dimension_defs": ("ThemeDimensionDef", "slipnet_node"),
}


def _id_row(table: str, name: str, variant: int = 0) -> dict:
    if table == "demo_problems":
        return {"name": name, "section": "", "initial": "abc", "modified": "abd", "target": "ijk",
                "answer": None, "seed": 1, "description": f"v{variant}"}
    if table == "commentary_templates":
        return {"template_key": name, "template_data": {"k": f"v{variant}"}}
    return {"slipnet_node": name, "valid_relations": [f"r{variant}"]}


def _names(table: str, rows) -> list[str]:
    key = _ID_TABLES[table][1]
    return [r[key] for r in rows if r[key].startswith("id_")]


def test_the_id_ordered_tables_keep_one_order_through_edits_export_and_import():
    from sqlalchemy import delete

    plan = [("insert", n) for n in ("id_c", "id_a", "id_b")] + [
        ("update", "id_a"), ("delete", "id_c"), ("insert", "id_c"), ("update", "id_b"),
        ("delete", "id_a"), ("insert", "id_a")]

    async def body(session):
        results = {}
        base_rows = await load_rows_from_db(session)
        doc = cd.from_rows(base_rows)
        for table, (model_name, key) in _ID_TABLES.items():
            model = _model(model_name)
            for step, (verb, name) in enumerate(plan):
                row = _id_row(table, name, step)
                if verb == "insert":
                    session.add(model(**row))
                    op = {"op": "insert", "table": table, "key": {key: name}, "row": row}
                elif verb == "update":
                    await session.execute(model.__table__.update().where(
                        model.__table__.c[key] == name).values(
                        **{k: v for k, v in row.items() if k != key}))
                    op = {"op": "update", "table": table, "key": {key: name},
                          "set": {k: v for k, v in row.items() if k != key}}
                else:
                    await session.execute(model.__table__.delete().where(model.__table__.c[key] == name))
                    op = {"op": "delete", "table": table, "key": {key: name}}
                await session.flush()
                doc = cd.apply_resolved(doc, [op])
        db_rows = await load_rows_from_db(session)
        # Export and re-import: the document through JSON, then written back in document order.
        exported = cd.from_json(cd.to_json(doc))
        for table, (model_name, key) in _ID_TABLES.items():
            model = _model(model_name)
            await session.execute(delete(model))
            for row in exported.tables[table].values():
                session.add(model(**{k: v for k, v in row.items() if k != "id"}))
        await session.flush()
        reimported = await load_rows_from_db(session)
        for table in _ID_TABLES:
            results[table] = (
                _names(table, db_rows[table]),
                _names(table, list(doc.tables[table].values())),
                _names(table, list(exported.tables[table].values())),
                _names(table, reimported[table]),
            )
        return results

    results = _in_rolled_back_transaction(body)
    for table, (from_db, from_doc, from_export, from_reimport) in results.items():
        assert from_db == ["id_b", "id_c", "id_a"], (table, from_db)
        assert from_doc == from_db, (table, from_doc, from_db)
        assert from_export == from_db and from_reimport == from_db, (table, from_export, from_reimport)
