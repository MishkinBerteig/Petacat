"""Stage 4 (F-change-api): the change API and the engine's vocabulary.

* ``rename_enum_value`` renames a row of an enum table (or a theme relation) and rewrites every
  column that names it, keeps the row's role and its place, rewrites the commentary sections
  keyed by the table's names and lists, never rewrites, what still spells the old name;
* the vocabulary rules (a role is a name of the table's vocabulary and held by one row; a bound
  row is not deleted) are one module the editors and the resolver share;
* ``engine_params.refers_to`` is the one declaration of which parameters hold node names,
  codelet type names or an urgency level: the cascades read the configuration's column, and a
  rule-trigger edit changes the parameter whose ``refers_to`` is ``trigger_node_list``.
"""

from __future__ import annotations

import json

import pytest

from server.engine.roles import LINK_BEHAVIOURS, VOCABULARY
from server.services import config_document as cd
from server.services.change_resolve import ChangeRefused, resolve
from server.services.change_resolve.spec import (
    CODELET_TYPE_LIST_PARAMS,
    ENUM_COLUMN_REFERENCES,
    NODE_LIST_PARAMS,
    NODE_MAP_PARAMS,
    REFERENCES,
    REFERS_TO_KINDS,
    RENAMEABLE_TABLES,
)
from server.services.change_resolve.vocabulary import (
    VOCABULARY_TABLES,
    delete_problem,
    role_problem,
    roles_by_table,
)
from server.services.config_registry import ENUM_REGISTRY
from server.services.configuration_input import ROLE_BOUND, ROLE_TAKEN, UNKNOWN_REFERENCE
from tests.integration.equivalence_harness import SEED_DIR


@pytest.fixture(scope="module")
def cfg() -> cd.ConfigDocument:
    return cd.document_from_standard_files(SEED_DIR)


def rename(table, old, new, **env):
    return {"op": "rename_enum_value", "table": table, "old": old, "new": new, **env}


def run(cfg, *ops, **env):
    return resolve(cfg, {"ops": list(ops), **env})


def refused(cfg, *ops):
    with pytest.raises(ChangeRefused) as info:
        run(cfg, *ops)
    return info.value


def bad_references(doc):
    """Every reference (declared, or of an enum table's column) naming a row that is not there."""
    out = []
    t = doc.tables
    for (table, column), (target, many) in {**REFERENCES, **ENUM_COLUMN_REFERENCES}.items():
        if target.startswith("role."):
            continue
        for row in t[table].values():
            value = row.get(column)
            if value in (None, ""):
                continue
            for item in value if many else [value]:
                if (item,) not in t[target]:
                    out.append((table, column, item))
    return out


# --- the tables -----------------------------------------------------------------------------


def test_the_renameable_tables_are_the_enum_tables_and_the_theme_relations():
    assert set(RENAMEABLE_TABLES) == set(ENUM_REGISTRY) | {"theme_relations"}
    assert len(ENUM_REGISTRY) == 18


@pytest.mark.parametrize("table", RENAMEABLE_TABLES)
def test_renaming_the_first_row_of_any_table_leaves_no_reference_to_the_old_name(cfg, table):
    old = next(iter(cfg.tables[table]))[0]
    ops, report = run(cfg, rename(table, old, "renamed-row"))
    assert report["ok"]
    after = cd.apply_resolved(cfg, ops)
    assert (old,) not in after.tables[table] and ("renamed-row",) in after.tables[table]
    assert bad_references(after) == []
    # the row keeps its place and every column but its name
    assert [k[0] for k in after.tables[table]] == [("renamed-row" if k[0] == old else k[0]) for k in cfg.tables[table]]
    assert {k: v for k, v in after.tables[table][("renamed-row",)].items() if k != "name"} == \
        {k: v for k, v in cfg.tables[table][(old,)].items() if k != "name"}
    # the order of every row of every table is what it was, bar the renamed references
    for name in cfg.tables:
        assert len(after.tables[name]) == len(cfg.tables[name]), name


def test_every_role_survives_a_rename_and_the_provider_follows_the_binding(cfg):
    from server.engine.roles import vocabulary_bindings

    for table, v in VOCABULARY_TABLES.items():
        if table == "link_types":
            continue
        for row in list(cfg.tables[table].values()):
            if not row.get(v.column):
                continue
            ops, _ = run(cfg, rename(table, row["name"], "v17"))
            after = cd.apply_resolved(cfg, ops)
            bound = [b for b in cd.provider(after).vocabulary_bindings if b.role == row[v.column]]
            assert [(b.table, b.name) for b in bound] == [(table, "v17")], (table, row["name"])


def test_a_renamed_posting_direction_is_written_into_every_rule_that_has_it(cfg):
    ops, report = run(cfg, rename("posting_directions", "bottom_up", "bu"))
    after = cd.apply_resolved(cfg, ops).tables
    n = sum(1 for r in cfg.tables["posting_rules"].values() if r["direction"] == "bottom_up")
    assert n and not any(r["direction"] == "bottom_up" for r in after["posting_rules"].values())
    assert sum(1 for r in after["posting_rules"].values() if r["direction"] == "bu") == n
    assert after["posting_directions"][("bu",)]["role"] == "posting_direction.bottom_up"
    assert sum(1 for c in report["cascaded"] if c["table"] == "posting_rules") == n
    # a rule's order and key are untouched
    assert list(after["posting_rules"]) == list(cfg.tables["posting_rules"])


def test_a_renamed_link_type_rewrites_the_links_and_keeps_their_keys_distinct(cfg):
    ops, _ = run(cfg, rename("link_types", "lateral", "lat"))
    after = cd.apply_resolved(cfg, ops).tables
    lateral = [r for r in cfg.tables["slipnet_link_defs"].values() if r["link_type"] == "lateral"]
    assert len(lateral) == 84
    assert sum(1 for r in after["slipnet_link_defs"].values() if r["link_type"] == "lat") == 84
    assert after["link_types"][("lat",)]["behaviour"] == "lateral"
    assert [r["from_node"] for r in cfg.tables["slipnet_link_defs"].values()] == \
        [r["from_node"] for r in after["slipnet_link_defs"].values()]


def test_the_columns_of_the_other_enum_tables_that_name_a_row_are_rewritten(cfg):
    ops, _ = run(cfg, rename("codelet_families", "meta", "m2"))
    after = cd.apply_resolved(cfg, ops).tables
    assert not any(r["family"] == "meta" for r in after["codelet_type_defs"].values())
    ops, _ = run(cfg, rename("param_value_types", "json", "js"))
    after = cd.apply_resolved(cfg, ops).tables
    assert not any(r["value_type"] == "json" for r in after["engine_params"].values())
    assert not any(r["value_type"] == "json" for r in after["formula_coefficients"].values())
    focus = next(iter(cfg.tables["progress_focuses"]))[0]
    ops, _ = run(cfg, rename("progress_focuses", focus, "pf"))
    after = cd.apply_resolved(cfg, ops).tables
    assert [r["progress_focus"] for r in after["clamp_types"].values()] == \
        [("pf" if r["progress_focus"] == focus else r["progress_focus"]) for r in cfg.tables["clamp_types"].values()]
    event = next(e for f in cfg.tables["progress_focuses"].values() for e in f["event_types"])
    ops, _ = run(cfg, rename("event_types", event, "ev"))
    after = cd.apply_resolved(cfg, ops).tables
    for before, now in zip(cfg.tables["progress_focuses"].values(), after["progress_focuses"].values()):
        assert now["event_types"] == [("ev" if x == event else x) for x in before["event_types"]]


def test_a_renamed_theme_relation_is_written_into_the_dimensions_that_list_it(cfg):
    ops, _ = run(cfg, rename("theme_relations", "opposite", "opp"))
    after = cd.apply_resolved(cfg, ops).tables
    assert all("opposite" not in r["valid_relations"] for r in after["theme_dimension_defs"].values())
    assert any("opp" in r["valid_relations"] for r in after["theme_dimension_defs"].values())
    assert after["theme_relations"][("opp",)]["role"] == "theme_relation.opposite"


def test_a_renamed_urgency_level_is_written_into_the_clamp_types_that_hold_it(cfg):
    level = next(r["codelet_background_level"] for r in cfg.tables["clamp_types"].values()
                 if r["codelet_background_level"])
    ops, _ = run(cfg, {"op": "update", "table": "urgency_levels", "key": {"name": level},
                       "fields": {"name": "lv-renamed"}})
    after = cd.apply_resolved(cfg, ops).tables
    assert all(r["codelet_background_level"] != level for r in after["clamp_types"].values())
    assert any(r["codelet_background_level"] == "lv-renamed" for r in after["clamp_types"].values())
    ops, report = run(cfg, {"op": "delete", "table": "urgency_levels", "key": {"name": level}})
    assert any(d["table"] == "clamp_types" and d["column"] == "codelet_background_level"
               for d in report["dangling"])


# --- the commentary sections keyed by names ------------------------------------------------------


def test_the_commentary_sections_keyed_by_a_tables_names_are_renamed_with_the_row(cfg):
    ops, report = run(cfg, rename("failure_kinds", "swap", "exchange"))
    after = cd.apply_resolved(cfg, ops).tables
    section = after["commentary_templates"][("all",)]["template_data"]["snag_explanation"]
    assert "exchange" in section and "swap" not in section
    assert any(c["table"] == "commentary_templates" for c in report["cascaded"])
    ops, _ = run(cfg, rename("clamp_types", "justify_clamp", "jc"))
    data = cd.apply_resolved(cfg, ops).tables["commentary_templates"][("all",)]["template_data"]["answer_reporting"]
    assert "jc" in data["clamp_activation"] and "jc" in data["clamp_expiry"]
    assert "justify_clamp" not in data["clamp_activation"]
    ops, _ = run(cfg, rename("theme_relations", "opposite", "opp"))
    data = cd.apply_resolved(cfg, ops).tables["commentary_templates"][("all",)]["template_data"]["theme_phrase_templates"]
    assert "opp" in data["string_position"]["direction"] and "opposite" not in json.dumps(
        list(data["string_position"]["direction"]))


def test_what_still_spells_the_old_name_is_listed_and_left_alone(cfg):
    ops, _ = run(cfg, {"op": "set_codelet_body", "name": "rule-scout", "source": "x = 'top'\n"})
    doc = cd.apply_resolved(cfg, ops)
    ops, report = run(doc, rename("bridge_types", "top", "tp"))
    after = cd.apply_resolved(doc, ops).tables
    listed = {(d["table"], d["key"].get("name") or d["key"].get("rule_key")) for d in report["dangling"]}
    assert ("codelet_type_defs", "rule-scout") in listed
    assert after["codelet_type_defs"][("rule-scout",)]["execute_body"] == "x = 'top'\n"
    # a parameter that spells it
    ops, _ = run(cfg, {"op": "set_param", "name": "default_urgency_level", "to": "bottom_up"})
    doc = cd.apply_resolved(cfg, ops)
    _, report = run(doc, rename("posting_directions", "bottom_up", "bu"))
    assert ("engine_params", "default_urgency_level") in {
        (d["table"], d["key"].get("name")) for d in report["dangling"]}


def test_a_table_the_client_or_the_parser_reads_gets_an_advisory(cfg):
    _, report = run(cfg, rename("run_statuses", "halted", "stopped"))
    assert [a["table"] for a in report["advisories"]] == ["run_statuses"]
    _, report = run(cfg, rename("bridge_types", "top", "tp"))
    assert report["advisories"] == []


# --- refusals --------------------------------------------------------------------------------------


def test_a_rename_that_cannot_be_made_is_refused(cfg):
    assert refused(cfg, rename("bridge_types", "no-such", "x")).kind == "unknown_reference"
    assert refused(cfg, rename("bridge_types", "top", "bottom")).kind == "key_exists"
    assert refused(cfg, rename("slipnet_node_defs", "plato-a", "x")).kind == "malformed"
    assert refused(cfg, rename("no_such_table", "a", "b")).kind == "malformed"
    assert refused(cfg, {"op": "rename_enum_value", "table": "bridge_types", "old": "top"}).kind == "malformed"
    ops, report = run(cfg, rename("bridge_types", "top", "top"))
    assert ops == [] and report["ok"]


def test_the_generic_ops_still_do_not_address_an_enum_table(cfg):
    assert refused(cfg, {"op": "delete", "table": "link_types", "key": {"name": "category"}}).kind == "malformed"


def test_a_batch_may_rename_and_then_use_the_new_name(cfg):
    ops, report = run(cfg, rename("posting_directions", "thematic", "th"), {
        "op": "update", "table": "posting_rules", "key": {"rule_key": next(
            k[0] for k, r in cfg.tables["posting_rules"].items() if r["direction"] == "bottom_up")},
        "fields": {"direction": "th"}})
    assert report["ok"]
    assert refused(cfg, rename("posting_directions", "thematic", "th"), {
        "op": "update", "table": "posting_rules", "key": {"rule_key": "rule-scout"},
        "fields": {"direction": "thematic"}}).kind == "unknown_reference"


# --- Episodic Memory: the same rule as for a node it names ----------------------------------------------


@pytest.mark.parametrize("table,old", [
    ("theme_types", "top_bridge"), ("rule_types", "top"), ("clause_types", "intrinsic"),
    ("theme_relations", "opposite"), ("bridge_types", "vertical"),
])
def test_a_name_that_memory_holds_can_be_renamed_by_every_source(cfg, table, old):
    """Episodic Memory persists these names (theme types in theme patterns, rule and clause types
    in signatures, relations in concept patterns).  As for a node it names, the change API neither
    refuses nor rewrites: the rename is carried out on the configuration, and a session's memory
    keeps the names it stored, so the same ops come out for every source."""
    results = [run(cfg, rename(table, old, "learned-name"), source=s, actor="x")
               for s in ("admin", "external", "learner")]
    assert all(r == results[0] for r in results) and results[0][1]["ok"] and results[0][0]
    assert bad_references(cd.apply_resolved(cfg, results[0][0])) == []


# --- the vocabulary rules -------------------------------------------------------------------------------


def test_the_roles_per_table_are_the_engines_vocabulary_filtered_by_table():
    roles = roles_by_table()
    for table, entry in roles.items():
        expected = tuple(s.name for s in VOCABULARY if s.table == table)
        if table == "link_types":
            assert entry == {"column": "behaviour", "roles": list(LINK_BEHAVIOURS), "unique": False}
        else:
            assert tuple(entry["roles"]) == expected and entry["column"] == "role" and entry["unique"]
    assert set(roles) == {t for t in {s.table for s in VOCABULARY} | {"link_types"}}
    assert "run_statuses" not in roles and "codelet_phases" not in roles


def test_a_role_is_a_name_of_the_tables_vocabulary_held_by_one_row():
    rows = [{"name": "top", "role": "bridge_type.top"}, {"name": "bottom", "role": None}]
    assert role_problem("bridge_types", {"name": "x", "role": None}, rows) is None
    assert role_problem("bridge_types", {"name": "x", "role": "bridge_type.vertical"}, rows) is None
    assert role_problem("bridge_types", {"name": "x", "role": "rule_type.top"}, rows).kind == UNKNOWN_REFERENCE
    taken = role_problem("bridge_types", {"name": "x", "role": "bridge_type.top"}, rows)
    assert taken.kind == ROLE_TAKEN and taken.status == 422
    assert role_problem("run_statuses", {"name": "x", "role": "anything"}, rows) is None
    # a link type's behaviour is one of the engine's, and several types may share one
    links = [{"name": "a", "behaviour": "lateral"}]
    assert role_problem("link_types", {"name": "b", "behaviour": "lateral"}, links) is None
    assert role_problem("link_types", {"name": "b", "behaviour": "slippy"}, links).kind == UNKNOWN_REFERENCE


def test_a_bound_row_is_not_deleted():
    bound = delete_problem("bridge_types", {"name": "top", "role": "bridge_type.top"})
    assert bound.kind == ROLE_BOUND and bound.status == 422
    assert delete_problem("bridge_types", {"name": "spare", "role": None}) is None
    assert delete_problem("link_types", {"name": "lateral", "behaviour": "lateral"}).kind == ROLE_BOUND
    assert delete_problem("run_statuses", {"name": "halted"}) is None


def test_a_theme_relations_role_is_checked_by_the_resolver(cfg):
    base = {"name": "extra", "ordinal": 9, "node_name": None, "abstractness": None, "description": ""}
    err = refused(cfg, {"op": "insert", "table": "theme_relations", "row": {**base, "role": "theme_relation.opposite"}})
    assert err.kind == ROLE_TAKEN and err.status == 422
    err = refused(cfg, {"op": "insert", "table": "theme_relations", "row": {**base, "role": "bridge_type.top"}})
    assert err.kind == UNKNOWN_REFERENCE
    ops, _ = run(cfg, {"op": "insert", "table": "theme_relations", "row": {**base, "role": None}})
    assert ops


# --- engine_params.refers_to ------------------------------------------------------------------------------


def test_the_three_lists_are_derived_from_the_declaration_in_the_seed(cfg):
    refers = {r["name"]: r["refers_to"] for r in cfg.tables["engine_params"].values() if r.get("refers_to")}
    assert set(refers.values()) <= set(REFERS_TO_KINDS)
    assert set(NODE_LIST_PARAMS) == {n for n, k in refers.items() if k in ("node_list", "trigger_node_list")}
    assert set(NODE_MAP_PARAMS) == {n for n, k in refers.items() if k == "node_map"}
    assert set(CODELET_TYPE_LIST_PARAMS) == {n for n, k in refers.items() if k == "codelet_type_list"}
    meta = cd.provider(cfg)
    assert meta.param_refers_to == refers
    assert meta.params_referring_to("urgency_level") == (
        "initial_codelet_urgency", "manual_clamp_background_level", "bridge_recruit_urgency_level",
        "default_urgency_level")


def test_a_rule_trigger_edit_changes_the_parameter_that_lists_the_trigger_nodes(cfg):
    key = "top-down-bond-scout:category"
    ops, report = run(cfg, {"op": "add_trigger", "rule_key": key, "node": "plato-opposite"})
    assert any(a["op"]["table"] == "engine_params" and a["op"]["key"] == {"name": "top_down_slipnodes"}
               for a in report["applied"])
    # the parameter is found by the column, not by its name: move the declaration to another one
    moved = cd.apply_resolved(cfg, [
        {"op": "update", "table": "engine_params", "key": {"name": "top_down_slipnodes"}, "set": {"refers_to": "node_list"}},
        {"op": "update", "table": "engine_params", "key": {"name": "initially_clamped_slipnodes"},
         "set": {"refers_to": "trigger_node_list"}},
    ])
    ops, report = run(moved, {"op": "add_trigger", "rule_key": key, "node": "plato-opposite"})
    touched = {a["op"]["key"]["name"] for a in report["applied"] if a["op"]["table"] == "engine_params"}
    assert touched == {"initially_clamped_slipnodes"}
    # a configuration that declares none leaves every parameter alone
    none = cd.apply_resolved(cfg, [{"op": "update", "table": "engine_params", "key": {"name": "top_down_slipnodes"},
                                    "set": {"refers_to": None}}])
    ops, report = run(none, {"op": "add_trigger", "rule_key": key, "node": "plato-opposite"})
    assert not any(a["op"]["table"] == "engine_params" for a in report["applied"])


def test_a_node_removal_edits_the_parameters_the_column_names(cfg):
    node = "plato-opposite"
    declared = cd.apply_resolved(cfg, [
        {"op": "update", "table": "engine_params", "key": {"name": "max_activation"},
         "set": {"value": json.dumps([node, "plato-a"]), "value_type": "json", "refers_to": "node_list"}}])
    ops, report = run(declared, {"op": "remove_node", "name": node})
    after = cd.apply_resolved(declared, ops).tables["engine_params"]
    assert json.loads(after[("max_activation",)]["value"]) == ["plato-a"]
    undeclared = cd.apply_resolved(declared, [
        {"op": "update", "table": "engine_params", "key": {"name": "max_activation"}, "set": {"refers_to": None}}])
    ops, _ = run(undeclared, {"op": "remove_node", "name": node})
    after = cd.apply_resolved(undeclared, ops).tables["engine_params"]
    assert json.loads(after[("max_activation",)]["value"]) == [node, "plato-a"]


def test_a_refers_to_that_is_not_one_of_the_kinds_is_refused(cfg):
    err = refused(cfg, {"op": "update", "table": "engine_params", "key": {"name": "max_activation"},
                        "fields": {"refers_to": "cat"}})
    assert err.kind == "malformed"
    ops, _ = run(cfg, {"op": "update", "table": "engine_params", "key": {"name": "max_activation"},
                       "fields": {"refers_to": "node_list"}})
    assert ops


def test_the_schema_names_the_op_the_vocabulary_tables_and_the_refers_to_kinds():
    from server.services.change_resolve import schema

    s = schema()
    assert "rename_enum_value" in s["ops"]["convenience"]
    assert s["vocabulary"]["tables"] == list(RENAMEABLE_TABLES)
    assert s["vocabulary"]["roles"]["link_types"]["column"] == "behaviour"
    assert s["refers_to"] == list(REFERS_TO_KINDS)
    names = [t["name"] for t in s["tables"]]
    assert not set(names) & set(ENUM_REGISTRY)  # the enum tables are renamed, not addressed
    column = next(c for t in s["tables"] if t["name"] == "engine_params" for c in t["columns"] if c["name"] == "refers_to")
    assert column["nullable"] and column["type"] == "str"


def test_an_unbound_row_is_inert_but_becomes_a_valid_value_of_the_columns_that_name_its_table(cfg):
    fields = {"family": "newfamily", "phase": next(iter(cfg.tables["codelet_phases"]))[0],
              "execute_body": ""}
    err = refused(cfg, {"op": "add_codelet_type", "name": "extra-type", "fields": fields})
    assert err.kind == UNKNOWN_REFERENCE
    with_family = cd.apply_resolved(cfg, [{
        "op": "insert", "table": "codelet_families", "key": {"name": "newfamily"},
        "row": {"name": "newfamily", "display_label": "New", "sort_order": 99, "description": "",
                "serialised": False}}])
    ops, _ = run(with_family, {"op": "add_codelet_type", "name": "extra-type", "fields": fields})
    assert ops
    # and it changes nothing the engine reads: the provider is the same
    assert cd.config_hash(with_family) == cd.config_hash(cfg)


# --- the manual clamp's background: a level and a list of clampable pattern names -----------------------


def test_the_manual_clamps_background_names_are_declared_by_what_they_name(cfg):
    """``manual_clamp_background_level`` names an urgency level; ``manual_clamp_background_patterns``
    names clampable codelet patterns (``rule``, ``bridge``, ``group``), which are keys of the menu
    ``clampable_codelet_patterns`` -- not progress focuses (``bridge`` is not one)."""
    params = cfg.tables["engine_params"]
    assert params[("manual_clamp_background_level",)]["refers_to"] == "urgency_level"
    assert params[("manual_clamp_background_patterns",)]["refers_to"] == "clampable_pattern_list"
    assert params[("clampable_codelet_patterns",)]["refers_to"] == "clampable_pattern_map"
    menu = json.loads(params[("clampable_codelet_patterns",)]["value"])
    listed = json.loads(params[("manual_clamp_background_patterns",)]["value"])
    focuses = {r["name"] for r in cfg.tables["progress_focuses"].values()}
    assert listed and set(listed) <= set(menu)
    assert not set(listed) <= focuses


def test_a_renamed_urgency_level_reaches_the_manual_clamps_background_level(cfg):
    level = cfg.tables["engine_params"][("manual_clamp_background_level",)]["value"]
    _, report = run(cfg, {"op": "update", "table": "urgency_levels", "key": {"name": level},
                          "fields": {"name": "lv-renamed"}})
    assert any(d["table"] == "engine_params" and d["key"] == {"name": "manual_clamp_background_level"}
               for d in report["dangling"])


def test_a_menu_that_stops_offering_a_pattern_lists_the_background_patterns_that_name_it(cfg):
    menu = json.loads(cfg.tables["engine_params"][("clampable_codelet_patterns",)]["value"])
    renamed = {("grp" if k == "group" else k): v for k, v in menu.items()}
    _, report = run(cfg, {"op": "set_param", "name": "clampable_codelet_patterns", "to": renamed})
    stale = [d for d in report["dangling"] if d["key"] == {"name": "manual_clamp_background_patterns"}]
    assert len(stale) == 1 and "'group'" in stale[0]["reason"]
    # a menu edit that leaves every listed pattern offered reports nothing
    kept = {**menu, "extra": "Extra codelet pattern"}
    _, report = run(cfg, {"op": "set_param", "name": "clampable_codelet_patterns", "to": kept})
    assert not [d for d in report["dangling"] if d["key"] == {"name": "manual_clamp_background_patterns"}]
    # a configuration that declares no menu has nothing to compare with
    undeclared = cd.apply_resolved(cfg, [{"op": "update", "table": "engine_params",
                                          "key": {"name": "clampable_codelet_patterns"},
                                          "set": {"refers_to": None}}])
    _, report = run(undeclared, {"op": "set_param", "name": "clampable_codelet_patterns", "to": renamed})
    assert not [d for d in report["dangling"] if d["key"] == {"name": "manual_clamp_background_patterns"}]
