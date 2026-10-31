"""EN2: what the new schema does, on a freshly loaded scratch database.

Each test works inside a transaction it rolls back, so the database the equivalence
harness shares stays exactly as the Metacat Standard Configuration loaded it.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.equivalence_harness import database_reachable, fresh_database, harness_db_url

pytestmark = pytest.mark.skipif(
    not database_reachable(),
    reason="the scratch Postgres is not reachable (start it with scripts/dev.sh db)",
)


def _in_rolled_back_transaction(body):
    """Run ``await body(session)`` against the freshly loaded database, then roll back."""
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


def test_deleting_a_node_deletes_its_role_bindings_and_relation():
    from server.models.metadata import SlipnetNodeDef, SlipnetNodeRole, ThemeRelation

    async def body(session):
        before = len((await session.execute(select(SlipnetNodeRole))).scalars().all())
        await session.execute(SlipnetNodeDef.__table__.delete().where(
            SlipnetNodeDef.name == "plato-direction-category"))
        roles = (await session.execute(select(SlipnetNodeRole))).scalars().all()
        # one single-node role, and an element of each of the two ordered roles
        assert before - len(roles) == 3
        assert all(r.node_name != "plato-direction-category" for r in roles)
        await session.execute(SlipnetNodeDef.__table__.delete().where(
            SlipnetNodeDef.name == "plato-opposite"))
        names = (await session.execute(select(ThemeRelation.name))).scalars().all()
        assert "opposite" not in names and "diff" in names

    _in_rolled_back_transaction(body)


def test_deleting_a_codelet_type_deletes_its_role_binding():
    from server.models.metadata import CodeletTypeDef, CodeletTypeRole

    async def body(session):
        await session.execute(CodeletTypeDef.__table__.delete().where(
            CodeletTypeDef.name == "bond-evaluator"))
        roles = (await session.execute(select(CodeletTypeRole.role))).scalars().all()
        assert "evaluator.bond" not in roles and len(roles) == 4

    _in_rolled_back_transaction(body)


def test_renaming_a_node_follows_into_its_bindings():
    async def body(session):
        await session.execute(text(
            "UPDATE slipnet_node_defs SET name = 'renamed' WHERE name = 'plato-length'"))
        found = (await session.execute(text(
            "SELECT node_name FROM slipnet_node_roles WHERE role = 'dimension.length'"))).scalars().all()
        assert found == ["renamed"]

    _in_rolled_back_transaction(body)


def test_a_role_has_one_node_per_ordinal_and_a_node_holds_a_role_once():
    from server.models.metadata import SlipnetNodeRole

    async def one(session):
        session.add(SlipnetNodeRole(role="dimension.length", ordinal=0, node_name="plato-a"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def two(session):
        session.add(SlipnetNodeRole(role="rule.dimension_order", ordinal=99, node_name="plato-length"))
        with pytest.raises(IntegrityError):
            await session.flush()

    _in_rolled_back_transaction(one)
    _in_rolled_back_transaction(two)


def test_the_link_key_admits_two_labels_between_the_same_nodes_and_refuses_a_repeat():
    from server.models.metadata import SlipnetLinkDef

    async def body(session):
        first = (await session.execute(
            select(SlipnetLinkDef).order_by(SlipnetLinkDef.id).limit(1))).scalar_one()
        session.add(SlipnetLinkDef(
            from_node=first.from_node, to_node=first.to_node, link_type=first.link_type,
            label_node="plato-predecessor", link_length=None, fixed_length=False))
        await session.flush()  # a different label: allowed
        session.add(SlipnetLinkDef(
            from_node=first.from_node, to_node=first.to_node, link_type=first.link_type,
            label_node=first.label_node, link_length=None, fixed_length=False))
        with pytest.raises(IntegrityError):
            await session.flush()

    _in_rolled_back_transaction(body)


def test_a_link_without_a_label_is_one_key_not_many():
    from server.models.metadata import SlipnetLinkDef

    async def body(session):
        unlabeled = (await session.execute(
            select(SlipnetLinkDef).where(SlipnetLinkDef.label_node.is_(None)).limit(1))).scalar_one()
        session.add(SlipnetLinkDef(
            from_node=unlabeled.from_node, to_node=unlabeled.to_node,
            link_type=unlabeled.link_type, label_node=None, link_length=1, fixed_length=True))
        with pytest.raises(IntegrityError):
            await session.flush()

    _in_rolled_back_transaction(body)


def test_glyph_and_numeric_value_are_unique():
    from server.models.metadata import SlipnetNodeDef

    async def body(session):
        node = await session.get(SlipnetNodeDef, "plato-length")
        node.glyph = "a"
        with pytest.raises(IntegrityError):
            await session.flush()

    async def body2(session):
        node = await session.get(SlipnetNodeDef, "plato-length")
        node.numeric_value = 1
        with pytest.raises(IntegrityError):
            await session.flush()

    _in_rolled_back_transaction(body)
    _in_rolled_back_transaction(body2)


def test_a_row_added_without_an_ordinal_goes_last_and_a_rule_key_defaults_to_its_type():
    from server.models.metadata import EngineParam, PostingRule, SlipnetLinkDef

    async def body(session):
        rule = PostingRule(codelet_type="a-new-codelet-type", direction="bottom_up")
        session.add(rule)
        link = SlipnetLinkDef(from_node="plato-a", to_node="plato-c", link_type="lateral",
                              label_node="plato-successor", link_length=None, fixed_length=False)
        session.add(link)
        param = EngineParam(name="zzz_new", value="1", value_type="int")
        session.add(param)
        await session.flush()
        top_rule = (await session.execute(text("SELECT max(sort_order) FROM posting_rules"))).scalar_one()
        assert rule.sort_order == top_rule == 17
        assert rule.rule_key == "a-new-codelet-type"
        assert link.sort_order == 202
        assert param.sort_order == (await session.execute(
            text("SELECT max(sort_order) FROM engine_params"))).scalar_one()

    _in_rolled_back_transaction(body)


def test_a_create_without_an_explicit_id_succeeds_after_the_first_load():
    """The first load writes explicit ids and then sets each id sequence past them."""
    from server.models.metadata import DemoProblem, PostingRule, SlipnetLinkDef, ThemeDimensionDef

    async def body(session):
        rows = [
            PostingRule(codelet_type="another-new-type", direction="bottom_up"),
            SlipnetLinkDef(from_node="plato-a", to_node="plato-c", link_type="lateral",
                           label_node="plato-successor", link_length=None, fixed_length=False),
            DemoProblem(name="a new demo", initial="abc", modified="abd", target="ijk",
                        seed=1, mode="discovery"),
            ThemeDimensionDef(slipnet_node="plato-length", valid_relations=["identity"]),
        ]
        session.add_all(rows)
        await session.flush()
        assert rows[0].id > 17 and rows[1].id > 202  # sequences consumed by earlier rolled-back tests only move higher
        assert rows[2].id > 0 and rows[3].id > 0

    _in_rolled_back_transaction(body)
