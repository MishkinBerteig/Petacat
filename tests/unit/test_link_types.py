"""``add_link_type`` and ``remove_link_type``, and the link types of a configuration.

``link_types`` is a configuration table the change API addresses (no longer one of the enum tables):
a configuration may hold link types of its own.  A type with no ``behaviour`` is plain, and a plain
link needs a fixed length.  Journaling is by before-image, so undo, restore and ``config_at`` work.
"""

from __future__ import annotations

import pytest

from server.engine.roles import LINK_BEHAVIOURS
from server.services import config_document as cd
from server.services import config_registry as reg
from server.services import journal, journal_views
from server.services.change_resolve import ChangeRefused, resolve
from server.services.change_resolve import spec
from tests.integration.equivalence_harness import SEED_DIR


@pytest.fixture(scope="module")
def cfg() -> cd.ConfigDocument:
    return cd.document_from_standard_files(SEED_DIR)


def add_type(name="near", **kw):
    return {"op": "add_link_type", "name": name, **kw}


def link(frm="plato-a", to="plato-c", type_="near", **kw):
    return {"op": "add_link", "from": frm, "to": to, "type": type_, **kw}


def applied(cfg, *ops, **envelope):
    resolved, report = resolve(cfg, {"ops": list(ops), **envelope})
    return cd.apply_resolved(cfg, resolved), resolved, report


def refused(cfg, *ops, **envelope) -> ChangeRefused:
    with pytest.raises(ChangeRefused) as info:
        resolve(cfg, {"ops": list(ops), **envelope})
    return info.value


# -- where the table lives ---------------------------------------------------------------------------


def test_link_types_is_a_registry_table_and_the_enum_tables_are_seventeen():
    assert "link_types" in reg.REGISTRY and "link_types" not in reg.ENUM_REGISTRY
    assert len(reg.ENUM_REGISTRY) == 17 and "link_types" in reg.LAYER_REGISTRY
    assert "link_types" not in spec.RENAMEABLE_TABLES
    assert reg.REGISTRY["link_types"].key == ("name",) and reg.REGISTRY["link_types"].order == ("sort_order",)
    assert "link_types" in cd.TABLE_NAMES and cd.TABLE_NAMES.index("link_types") < cd.TABLE_NAMES.index("slipnet_link_defs")
    assert {"add_link_type", "remove_link_type"} <= set(spec.CONVENIENCE_OPS)


def test_the_standard_configuration_has_its_five_types_in_the_document(cfg):
    assert [k[0] for k in cfg.tables["link_types"]] == [
        "category", "instance", "property", "lateral", "lateral_sliplink"]


def test_rename_enum_value_no_longer_applies_to_link_types(cfg):
    error = refused(cfg, {"op": "rename_enum_value", "table": "link_types", "old": "lateral", "new": "side"})
    assert error.problems[0].kind == "malformed"


def test_the_schema_lists_link_types_as_an_addressable_table():
    names = {t["name"] for t in spec.schema()["tables"]}
    assert "link_types" in names
    assert "link_types" not in spec.schema()["vocabulary"]["tables"]


# -- add_link_type -------------------------------------------------------------------------------------


def test_it_adds_a_plain_type_last_with_a_label_that_defaults_to_the_name(cfg):
    doc, resolved, _ = applied(cfg, add_type())
    row = doc.tables["link_types"][("near",)]
    assert row["behaviour"] is None and row["display_label"] == "near" and row["description"] == ""
    assert row["sort_order"] == max(r["sort_order"] for r in cfg.tables["link_types"].values()) + 1
    assert list(doc.tables["link_types"])[-1] == ("near",)
    assert [(o["op"], o["table"]) for o in resolved] == [("insert", "link_types")]
    assert ("near",) not in cfg.tables["link_types"]  # the input is not mutated


@pytest.mark.parametrize("behaviour", LINK_BEHAVIOURS)
def test_it_takes_each_behaviour_the_engine_knows(cfg, behaviour):
    doc, _, _ = applied(cfg, add_type("kind", behaviour=behaviour, display_label="Kind", description="d"))
    row = doc.tables["link_types"][("kind",)]
    assert (row["behaviour"], row["display_label"], row["description"]) == (behaviour, "Kind", "d")


def test_an_empty_behaviour_is_a_plain_type(cfg):
    doc, _, _ = applied(cfg, add_type(behaviour=""))
    assert doc.tables["link_types"][("near",)]["behaviour"] is None


def test_it_refuses_a_behaviour_the_engine_does_not_know(cfg):
    error = refused(cfg, add_type(behaviour="sideways"))
    assert error.problems[0].kind == "unknown_reference" and "sideways" in error.problems[0].message


def test_it_refuses_a_name_that_exists(cfg):
    for name in ("lateral", "near"):
        batch = [add_type(name)] if name == "lateral" else [add_type(), add_type()]
        assert refused(cfg, *batch).problems[0].kind == "key_exists"


def test_it_needs_a_name_and_takes_no_other_argument(cfg):
    assert refused(cfg, {"op": "add_link_type"}).problems[0].kind == "malformed"
    assert refused(cfg, add_type(colour="red")).problems[0].kind == "malformed"


def test_a_type_made_in_a_batch_is_there_for_the_links_after_it(cfg):
    doc, _, _ = applied(cfg, add_type("kin", behaviour="lateral"), link(type_="kin", fixed=True, length=40))
    assert doc.tables["slipnet_link_defs"][("plato-a", "plato-c", "kin", "")]["link_length"] == 40


def test_a_link_of_a_type_the_configuration_lacks_is_still_refused(cfg):
    error = refused(cfg, link(type_="missing", fixed=True, length=40))
    assert error.problems[0].kind == "unknown_reference"


# -- remove_link_type ----------------------------------------------------------------------------------


def test_it_removes_a_type_no_link_has(cfg):
    doc, resolved, _ = applied(cfg, add_type(), {"op": "remove_link_type", "name": "near"})
    assert ("near",) not in doc.tables["link_types"]
    assert doc.content_equals(cfg) or cd.config_hash(doc) == cd.config_hash(cfg)


def test_it_refuses_while_a_link_has_the_type_and_says_which(cfg):
    error = refused(cfg, {"op": "remove_link_type", "name": "lateral"})
    problem = error.problems[0]
    assert problem.kind == "unknown_reference" and "still has" in problem.message and "remove_link" in problem.message


def test_it_removes_a_type_once_its_links_are_removed_in_the_same_batch(cfg):
    ops = [add_type(), link(fixed=True, length=40), {"op": "remove_link", "key": {
        "from_node": "plato-a", "to_node": "plato-c", "link_type": "near", "label_node": ""}},
        {"op": "remove_link_type", "name": "near"}]
    doc, _, _ = applied(cfg, *ops)
    assert cd.config_hash(doc) == cd.config_hash(cfg)


def test_it_refuses_a_type_that_does_not_exist(cfg):
    assert refused(cfg, {"op": "remove_link_type", "name": "nope"}).problems[0].kind == "unknown_reference"


def test_removing_a_standard_type_whose_links_are_gone_is_allowed_whatever_its_behaviour(cfg):
    standard_links = [r for r in cfg.tables["slipnet_link_defs"].values() if r["link_type"] == "property"]
    ops = [{"op": "remove_link", "key": {k: r[k] for k in ("from_node", "to_node", "link_type", "label_node")}}
           for r in standard_links]
    ops = [{**o, "key": {**o["key"], "label_node": o["key"]["label_node"] or ""}} for o in ops]
    doc, _, _ = applied(cfg, *ops, {"op": "remove_link_type", "name": "property"})
    assert ("property",) not in doc.tables["link_types"]


# -- journaling: undo, restore, config_at ----------------------------------------------------------------


def test_add_link_type_is_an_insert_with_no_before_image_so_undo_works(cfg):
    ops = resolve(cfg, {"ops": [add_type("near", behaviour="lateral")]})[0]
    resolved, before = journal.normalize_ops(cfg, ops)
    assert [op["op"] for op in resolved] == ["insert"] and before == [None]
    after = cd.apply_resolved(cfg, resolved)
    entry = {"revision": 1, "resolved": resolved, "before": before}
    undone = cd.apply_resolved(after, journal_views.inverse_ops([entry]))
    assert cd.config_hash(undone) == cd.config_hash(cfg)


def test_remove_link_type_has_a_before_image_so_undo_brings_the_row_back(cfg):
    with_type, _, _ = applied(cfg, add_type("near", behaviour="lateral", description="kept"))
    ops = resolve(with_type, {"ops": [{"op": "remove_link_type", "name": "near"}]})[0]
    resolved, before = journal.normalize_ops(with_type, ops)
    assert [op["op"] for op in resolved] == ["delete"] and before[0]["description"] == "kept"
    gone = cd.apply_resolved(with_type, resolved)
    assert ("near",) not in gone.tables["link_types"]
    undone = cd.apply_resolved(gone, journal_views.inverse_ops([{"revision": 2, "resolved": resolved, "before": before}]))
    assert cd.config_hash(undone) == cd.config_hash(with_type)


def test_a_link_type_changes_the_configuration_hash_and_the_provider(cfg):
    doc, _, _ = applied(cfg, add_type("near"), add_type("kin", behaviour="lateral"))
    assert cd.config_hash(doc) != cd.config_hash(cfg)
    types = {t.name: t.behaviour for t in cd.provider(doc).link_types}
    assert types["near"] is None and types["kin"] == "lateral" and types["lateral"] == "lateral"
    assert "near" not in {t.name for t in cd.provider(cfg).link_types}


# -- the generic ops address the table, with the vocabulary rule --------------------------------------------


def test_the_generic_ops_address_link_types_and_check_the_behaviour(cfg):
    doc, _, _ = applied(cfg, {"op": "insert", "table": "link_types", "row": {
        "name": "g", "display_label": "G", "behaviour": "instance"}})
    assert doc.tables["link_types"][("g",)]["behaviour"] == "instance"
    bad = {"op": "insert", "table": "link_types", "row": {"name": "h", "display_label": "H", "behaviour": "x"}}
    assert refused(cfg, bad).problems[0].kind == "unknown_reference"
    doc2, _, _ = applied(cfg, {"op": "update", "table": "link_types", "key": {"name": "instance"},
                              "fields": {"description": "changed"}})
    assert doc2.tables["link_types"][("instance",)]["description"] == "changed"


# -- a plain link needs a fixed length -------------------------------------------------------------------------


def test_a_plain_link_without_a_fixed_length_is_refused_with_a_clear_message(cfg):
    # (a link that leaves ``fixed_length`` out is refused earlier, by the row's shape: it is required)
    assert refused(cfg, add_type(), link()).problems[0].kind == "malformed"
    for kw in ({"fixed": True}, {"fixed": False, "length": 40}, {"fixed": False}):
        error = refused(cfg, add_type(), link(**kw))
        problem = error.problems[0]
        assert problem.kind == "malformed" and "needs a fixed length" in problem.message
        assert "full association" in problem.message and problem.field == "fixed_length"


def test_a_plain_link_with_a_fixed_length_is_accepted_and_a_zero_length_counts(cfg):
    for length in (40, 0):
        doc, _, _ = applied(cfg, add_type(), link(fixed=True, length=length))
        assert doc.tables["slipnet_link_defs"][("plato-a", "plato-c", "near", "")]["link_length"] == length


def test_a_link_of_a_type_with_a_behaviour_may_leave_its_length_to_its_label(cfg):
    doc, _, _ = applied(cfg, add_type("kin", behaviour="lateral"), link(type_="kin", label="plato-successor", fixed=False))
    assert doc.tables["slipnet_link_defs"][("plato-a", "plato-c", "kin", "plato-successor")]["fixed_length"] is False


def test_the_plain_link_rule_holds_for_a_link_inside_add_node_and_for_an_update(cfg):
    node = {"op": "add_node", "name": "plato-new", "fields": {"short_name": "n", "conceptual_depth": 10},
            "links": [{"to": "plato-a", "type": "near"}]}
    assert refused(cfg, add_type(), node).problems[0].kind == "malformed"
    ok, _, _ = applied(cfg, add_type(), link(fixed=True, length=40))
    bad = {"op": "update", "table": "slipnet_link_defs",
           "key": {"from_node": "plato-a", "to_node": "plato-c", "link_type": "near", "label_node": ""},
           "fields": {"fixed_length": False}}
    with pytest.raises(ChangeRefused):
        resolve(ok, {"ops": [bad]})
    retyped = {"op": "update", "table": "slipnet_link_defs",
               "key": {"from_node": "plato-a", "to_node": "plato-b", "link_type": "lateral", "label_node": "plato-successor"},
               "fields": {"link_type": "near"}}
    assert refused(ok, retyped).problems[0].kind == "malformed"


def test_a_type_cannot_become_plain_while_a_link_of_it_has_no_fixed_length(cfg):
    error = refused(cfg, {"op": "update", "table": "link_types", "key": {"name": "lateral"},
                          "fields": {"behaviour": None}})
    assert error.problems[0].kind == "malformed" and "needs a fixed length" in error.problems[0].message
    # a type none of whose links lacks a fixed length can
    doc, _, _ = applied(cfg, add_type("kin", behaviour="lateral"), link(type_="kin", fixed=True, length=30),
                        {"op": "update", "table": "link_types", "key": {"name": "kin"}, "fields": {"behaviour": None}})
    assert doc.tables["link_types"][("kin",)]["behaviour"] is None


def test_under_skip_the_refused_link_is_dropped_and_the_type_stays(cfg):
    resolved, report = resolve(cfg, {"ops": [add_type(), link()], "on_op_failure": "skip"})
    doc = cd.apply_resolved(cfg, resolved)
    assert ("near",) in doc.tables["link_types"] and len(report["skipped"]) == 1
    assert not any(k[2] == "near" for k in doc.tables["slipnet_link_defs"])
