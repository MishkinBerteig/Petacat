"""C14a: every convenience op of 3.12.4 equals its expansion into generic ops, and the cascades.

Part one pins, for each convenience op, that ``resolve`` gives the same resolved ops as the
generic ops the plan says it expands to (and so the same document).  Part two pins the
cascade rules of 3.12.5 (what a removal removes, what it lists as ``dangling`` and
``affected``, what a rename rewrites and what a merge moves) and the relative ops.
"""

from __future__ import annotations

import json

import pytest

from server.services import config_document as cd
from server.services.change_resolve import ChangeRefused, resolve
from tests.integration.equivalence_harness import SEED_DIR


@pytest.fixture(scope="module")
def cfg() -> cd.ConfigDocument:
    return cd.document_from_standard_files(SEED_DIR)


def run(cfg, *ops, **env):
    return resolve(cfg, {"ops": list(ops), **env})


def refused(cfg, *ops):
    with pytest.raises(ChangeRefused) as info:
        run(cfg, *ops)
    return info.value


def upd(table, key, **fields):
    return {"op": "update", "table": table, "key": key, "fields": fields}


def ins(table, **row):
    return {"op": "insert", "table": table, "row": row}


def dele(table, key):
    return {"op": "delete", "table": table, "key": key}


def param(cfg, name):
    return cfg.tables["engine_params"][(name,)]


NEW = {"short_name": "x", "conceptual_depth": 5}


def pairs(cfg):
    """``[(id, convenience ops, generic ops)]`` over the standard configuration."""
    t = cfg.tables
    rule_key = "top-down-bond-scout:category"
    triggers = t["posting_rules"][(rule_key,)]["triggering_slipnodes"]
    top_down = json.loads(param(cfg, "top_down_slipnodes")["value"])
    template = t["commentary_templates"][("all",)]["template_data"]
    member = next(iter(template))
    link_key = {"from_node": "plato-a", "to_node": "plato-b", "link_type": "lateral", "label_node": "plato-successor"}
    a_link = next(r for r in t["slipnet_link_defs"].values())
    first_layout = next(iter(t["slipnet_layout"].values()))
    second = list(t["slipnet_node_defs"])[1][0]
    family = next(iter(t["codelet_families"]))[0]
    phase = next(iter(t["codelet_phases"]))[0]
    direction = next(iter(t["posting_directions"]))[0]
    ordered = {r["node_name"] for r in t["slipnet_node_roles"].values() if r["role"] == "rule.dimension_order"}
    unbound = next(k[0] for k in t["slipnet_node_defs"] if k[0] not in ordered)
    others = any(triggers[0] in (r["triggering_slipnodes"] or []) for k, r in t["posting_rules"].items() if k != (rule_key,))
    remove_trigger = [upd("posting_rules", {"rule_key": rule_key}, triggering_slipnodes=triggers[1:])]
    if not others and triggers[0] in top_down:
        remove_trigger.append(upd("engine_params", {"name": "top_down_slipnodes"},
                                  value=json.dumps([x for x in top_down if x != triggers[0]])))
    return [
        ("add_node",
         [{"op": "add_node", "name": "x1", "fields": NEW,
           "links": [{"to": "plato-a", "type": "lateral"}],
           "layout": {"grid_row": 7, "grid_col": 8},
           "theme_dimension": {"valid_relations": ["identity"]},
           "params": {"top_down_slipnodes": True}}],
         [ins("slipnet_node_defs", name="x1", **NEW),
          ins("slipnet_link_defs", from_node="x1", to_node="plato-a", link_type="lateral"),
          ins("slipnet_layout", node_name="x1", grid_row=7, grid_col=8),
          ins("theme_dimension_defs", slipnet_node="x1", valid_relations=["identity"]),
          upd("engine_params", {"name": "top_down_slipnodes"}, value=json.dumps(top_down + ["x1"]))]),
        ("add_node, an ordered role is appended",
         [{"op": "add_node", "name": "x1", "fields": NEW, "roles": ["rule.dimension_order"]}],
         [ins("slipnet_node_defs", name="x1", **NEW),
          ins("slipnet_node_roles", role="rule.dimension_order", ordinal=8, node_name="x1")]),
        ("remove_node", [{"op": "remove_node", "name": "plato-a"}], [dele("slipnet_node_defs", {"name": "plato-a"})]),
        ("rename_node", [{"op": "rename_node", "old": "plato-a", "new": "plato-aa"}],
         [upd("slipnet_node_defs", {"name": "plato-a"}, name="plato-aa")]),
        ("add_link", [{"op": "add_link", "from": "plato-a", "to": "plato-c", "type": "lateral",
                       "label": "plato-predecessor", "length": 60, "fixed": False}],
         [ins("slipnet_link_defs", from_node="plato-a", to_node="plato-c", link_type="lateral",
              label_node="plato-predecessor", link_length=60, fixed_length=False)]),
        ("remove_link", [{"op": "remove_link", "key": link_key}], [dele("slipnet_link_defs", link_key)]),
        ("set_param", [{"op": "set_param", "name": "update_cycle_length", "to": 20, "expect": 15}],
         [upd("engine_params", {"name": "update_cycle_length"}, value="20")]),
        ("set_param, a new type", [{"op": "set_param", "name": "update_cycle_length", "to": 2.5, "value_type": "float"}],
         [upd("engine_params", {"name": "update_cycle_length"}, value="2.5", value_type="float")]),
        ("adjust_param", [{"op": "adjust_param", "name": "update_cycle_length", "by": -3}],
         [upd("engine_params", {"name": "update_cycle_length"}, value="12")]),
        ("set_coefficient", [{"op": "set_coefficient", "name": "temp_exponent_base", "to": 0.75}],
         [upd("formula_coefficients", {"name": "temp_exponent_base"}, value="0.75")]),
        ("adjust_coefficient", [{"op": "adjust_coefficient", "name": "temp_exponent_base", "by": 0.25}],
         [upd("formula_coefficients", {"name": "temp_exponent_base"}, value="0.75")]),
        ("set_urgency_level", [{"op": "set_urgency_level", "name": "low", "to": 40, "expect": 35}],
         [upd("urgency_levels", {"name": "low"}, value=40)]),
        ("adjust", [{"op": "adjust", "table": "urgency_levels", "key": {"name": "low"}, "field": "value", "by": 5}],
         [upd("urgency_levels", {"name": "low"}, value=40)]),
        ("adjust, a parameter's value", [{"op": "adjust", "table": "engine_params", "key": {"name": "update_cycle_length"},
                                          "field": "value", "by": 1}],
         [upd("engine_params", {"name": "update_cycle_length"}, value="16")]),
        ("list_add", [{"op": "list_add", "table": "engine_params", "key": {"name": "top_down_slipnodes"},
                       "field": "value", "value": "plato-a"}],
         [upd("engine_params", {"name": "top_down_slipnodes"}, value=json.dumps(top_down + ["plato-a"]))]),
        ("list_add is idempotent", [{"op": "list_add", "table": "engine_params", "key": {"name": "top_down_slipnodes"},
                                     "field": "value", "value": top_down[0]}], []),
        ("list_remove", [{"op": "list_remove", "table": "engine_params", "key": {"name": "top_down_slipnodes"},
                          "field": "value", "value": top_down[0]}],
         [upd("engine_params", {"name": "top_down_slipnodes"}, value=json.dumps(top_down[1:]))]),
        ("list_add on a JSON column", [{"op": "list_add", "table": "theme_dimension_defs", "key": {"slipnet_node": "plato-letter-category"},
                                        "field": "valid_relations", "value": "opposite"}],
         [upd("theme_dimension_defs", {"slipnet_node": "plato-letter-category"},
              valid_relations=t["theme_dimension_defs"][("plato-letter-category",)]["valid_relations"] + ["opposite"])]),
        ("reorder to the end", [{"op": "reorder", "table": "slipnet_node_defs", "key": {"name": second}}],
         None),
        ("move_layout", [{"op": "move_layout", "node": first_layout["node_name"], "x": 9, "y": 4}],
         [upd("slipnet_layout", {"node_name": first_layout["node_name"]}, grid_col=9, grid_row=4)]),
        ("add_trigger", [{"op": "add_trigger", "rule_key": rule_key, "node": "plato-length"}],
         [upd("posting_rules", {"rule_key": rule_key}, triggering_slipnodes=triggers + ["plato-length"])]),
        ("add_trigger keeps top_down_slipnodes in step", [{"op": "add_trigger", "rule_key": rule_key, "node": "plato-opposite"}],
         [upd("posting_rules", {"rule_key": rule_key}, triggering_slipnodes=triggers + ["plato-opposite"]),
          upd("engine_params", {"name": "top_down_slipnodes"}, value=json.dumps(top_down + ["plato-opposite"]))]),
        ("remove_trigger", [{"op": "remove_trigger", "rule_key": rule_key, "node": triggers[0]}],
         remove_trigger),
        ("rebind_role", [{"op": "rebind_role", "role": "dimension.length", "node": "plato-letter-category"}],
         [upd("slipnet_node_roles", {"role": "dimension.length", "ordinal": 0}, node_name="plato-letter-category")]),
        ("rebind_role of an ordered role appends", [{"op": "rebind_role", "role": "rule.dimension_order", "node": unbound}],
         [ins("slipnet_node_roles", role="rule.dimension_order", ordinal=8, node_name=unbound)]),
        ("rebind_role of a codelet role", [{"op": "rebind_role", "role": "evaluator.bond", "codelet_type": "rule-scout"}],
         [upd("codelet_type_roles", {"role": "evaluator.bond", "ordinal": 0}, codelet_type="rule-scout")]),
        ("unbind_role", [{"op": "unbind_role", "role": "dimension.length"}],
         [dele("slipnet_node_roles", {"role": "dimension.length", "ordinal": 0})]),
        ("add_codelet_type", [{"op": "add_codelet_type", "name": "c1", "fields": {"family": family, "phase": phase}}],
         [ins("codelet_type_defs", name="c1", family=family, phase=phase)]),
        ("remove_codelet_type", [{"op": "remove_codelet_type", "name": "rule-scout"}],
         [dele("codelet_type_defs", {"name": "rule-scout"})]),
        ("set_codelet_body", [{"op": "set_codelet_body", "name": "rule-scout", "source": "fizzle()"}],
         [upd("codelet_type_defs", {"name": "rule-scout"}, execute_body="fizzle()")]),
        ("set_predicate", [{"op": "set_predicate", "node": "plato-one", "expr": "False"}],
         [upd("slipnet_node_defs", {"name": "plato-one"}, descriptor_predicate="False")]),
        ("set_formula", [{"op": "set_formula", "rule_key": "rule-scout", "column": "posting_formula", "expr": "0.5"}],
         [upd("posting_rules", {"rule_key": "rule-scout"}, posting_formula="0.5")]),
        ("set_template", [{"op": "set_template", "key": "all", "path": "/" + member, "text": "hello"}],
         [{"op": "update", "table": "commentary_templates", "key": {"template_key": "all"}, "fields": {},
           "patch": {"template_data": [{"op": "replace", "path": "/" + member, "value": "hello"}]}}]),
        ("add_posting_rule", [{"op": "add_posting_rule", "rule_key": "r1", "fields": {"codelet_type": "rule-scout", "direction": direction}}],
         [ins("posting_rules", rule_key="r1", codelet_type="rule-scout", direction=direction)]),
        ("remove_posting_rule", [{"op": "remove_posting_rule", "rule_key": "rule-scout"}],
         [dele("posting_rules", {"rule_key": "rule-scout"})]),
        ("add_demo_problem", [{"op": "add_demo_problem", "name": "d1", "fields": {
            "initial": "abc", "modified": "abd", "target": "ijk", "seed": 1}}],
         [ins("demo_problems", name="d1", initial="abc", modified="abd", target="ijk", seed=1)]),
    ]


def _case_ids():
    return [p[0] for p in pairs(cd.document_from_standard_files(SEED_DIR))]


@pytest.mark.parametrize("index", range(len(_case_ids())), ids=_case_ids())
def test_a_convenience_op_equals_its_expansion(cfg, index):
    label, convenience, generic = pairs(cfg)[index]
    if label == "reorder to the end":
        expected_order = [k for k in cfg.tables["slipnet_node_defs"] if k != ("plato-letter-category",)]
        generic = None
    got_ops, got_report = run(cfg, *convenience)
    if generic is None:
        doc = cd.apply_resolved(cfg, got_ops)
        order = [k[0] for k in doc.tables["slipnet_node_defs"]]
        moved = convenience[0]["key"]["name"]
        assert order[-1] == moved and sorted(order) == sorted(k[0] for k in cfg.tables["slipnet_node_defs"])
        assert all(op["op"] == "update" and set(op["set"]) == {"sort_order"} for op in got_ops)
        return
    want_ops, _ = run(cfg, *generic)
    assert got_ops == want_ops, label
    assert cd.apply_resolved(cfg, got_ops).content_equals(cd.apply_resolved(cfg, want_ops))


def test_reorder_before_puts_the_row_just_before_the_other(cfg):
    names = [k[0] for k in cfg.tables["slipnet_node_defs"]]
    ops, _ = run(cfg, {"op": "reorder", "table": "slipnet_node_defs", "key": {"name": names[5]}, "before": {"name": names[1]}})
    doc = cd.apply_resolved(cfg, ops)
    order = [k[0] for k in doc.tables["slipnet_node_defs"]]
    assert order == [names[0], names[5], names[1], *names[2:5], *names[6:]]
    assert refused(cfg, {"op": "reorder", "table": "demo_problems", "key": {"name": "x"}}).kind == "malformed"


def test_reorder_posting_rules_changes_the_order_the_engine_reads(cfg):
    keys = [k[0] for k in cfg.tables["posting_rules"]]
    ops, _ = run(cfg, {"op": "reorder", "table": "posting_rules", "key": {"rule_key": keys[0]}})
    doc = cd.apply_resolved(cfg, ops)
    assert [k[0] for k in doc.tables["posting_rules"]] == keys[1:] + keys[:1]


# --- relative ops ----------------------------------------------------------------------------


def test_relative_ops_read_the_current_value_so_sums_commute(cfg):
    a = {"op": "adjust_param", "name": "update_cycle_length", "by": 2}
    ops1, _ = run(cfg, a)
    doc1 = cd.apply_resolved(cfg, ops1)
    ops2, _ = run(doc1, a)
    assert doc1.tables["engine_params"][("update_cycle_length",)]["value"] == "17"
    assert cd.apply_resolved(doc1, ops2).tables["engine_params"][("update_cycle_length",)]["value"] == "19"
    both, _ = run(cfg, a, a)
    assert cd.apply_resolved(cfg, both).tables["engine_params"][("update_cycle_length",)]["value"] == "19"
    assert "expect" not in json.dumps(both)


def test_a_relative_op_is_not_clamped(cfg):
    ops, report = run(cfg, {"op": "adjust", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                            "field": "conceptual_depth", "by": 1000})
    assert ops[0]["set"]["conceptual_depth"] > 1000 and report["advisories"]
    ops, _ = run(cfg, {"op": "adjust", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                       "field": "conceptual_depth", "by": -1000})
    assert ops[0]["set"]["conceptual_depth"] < -900


def test_adjust_needs_a_number_and_keeps_an_integer_integral(cfg):
    assert refused(cfg, {"op": "adjust", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                         "field": "short_name", "by": 1}).kind == "malformed"
    assert refused(cfg, {"op": "adjust_param", "name": "update_cycle_length", "by": 0.5}).kind == "malformed"
    assert refused(cfg, {"op": "adjust_param", "name": "top_down_slipnodes", "by": 1}).kind == "malformed"


def test_adjust_a_rational_coefficient_stays_exact(cfg):
    rational = next((r for r in cfg.tables["formula_coefficients"].values() if r["value_type"] == "rational"), None)
    if rational is None:
        pytest.skip("no rational coefficient in the standard configuration")
    ops, _ = run(cfg, {"op": "adjust_coefficient", "name": rational["name"], "by": 1})
    assert "/" in ops[0]["set"]["value"]


# --- cascades (3.12.5) -------------------------------------------------------------------------


def cascaded(report, table):
    return [c for c in report["cascaded"] if c["table"] == table]


def test_removing_a_node_removes_everything_that_depends_on_it(cfg):
    doc_ops, report = run(cfg, {"op": "remove_node", "name": "plato-successor"})
    doc = cd.apply_resolved(cfg, doc_ops)
    t = doc.tables
    for lk in t["slipnet_link_defs"].values():
        assert "plato-successor" not in (lk["from_node"], lk["to_node"], lk.get("label_node"))
    assert len(cascaded(report, "slipnet_link_defs")) == len(cfg.tables["slipnet_link_defs"]) - len(t["slipnet_link_defs"])
    assert ("plato-successor",) not in t["slipnet_layout"]
    for rule in t["posting_rules"].values():
        assert "plato-successor" not in (rule["triggering_slipnodes"] or [])
    for name in ("top_down_slipnodes", "initially_clamped_slipnodes"):
        assert "plato-successor" not in json.loads(t["engine_params"][(name,)]["value"])
    for name in ("intrinsic_link_lengths", "theme_dimension_labels", "rule_english_dimension_phrases"):
        assert "plato-successor" not in json.loads(t["engine_params"][(name,)]["value"])
    assert all(c["reason"] for c in report["cascaded"]) and all(c["cause_op"] == 0 for c in report["cascaded"])


def test_removing_a_relation_node_removes_the_links_it_labels(cfg):
    labelled = [l for l in cfg.tables["slipnet_link_defs"].values() if l.get("label_node") == "plato-opposite"]
    assert labelled
    ops, report = run(cfg, {"op": "remove_node", "name": "plato-opposite"})
    removed = {tuple(c["key"].values()) for c in cascaded(report, "slipnet_link_defs")}
    for l in labelled:
        assert (l["from_node"], l["to_node"], l["link_type"], "plato-opposite") in removed
    assert any("label" in c["reason"] for c in cascaded(report, "slipnet_link_defs"))
    assert any(c["table"] == "theme_relations" for c in report["cascaded"])


def test_removing_a_node_removes_its_role_bindings_and_theme_rows(cfg):
    node = next(r["node_name"] for r in cfg.tables["slipnet_node_roles"].values() if r["role"] == "dimension.length")
    ops, report = run(cfg, {"op": "remove_node", "name": node})
    doc = cd.apply_resolved(cfg, ops)
    assert all(r["node_name"] != node for r in doc.tables["slipnet_node_roles"].values())
    assert (node,) not in doc.tables["theme_dimension_defs"]
    assert cascaded(report, "slipnet_node_roles")
    # the dependents go before the node itself, so a foreign key never sees an orphan
    assert ops[-1] == {"op": "delete", "table": "slipnet_node_defs", "key": {"name": node}}


def test_removing_a_node_lists_the_code_and_demo_problems_that_name_it(cfg):
    t = cfg.tables
    # the standard configuration's bodies name no node (CB), so an earlier op in the batch writes one
    _, report = run(cfg, {"op": "set_codelet_body", "name": "rule-scout", "source": "x = 'plato-opposite'"},
                    {"op": "set_predicate", "node": "plato-one", "expr": "obj == 'plato-opposite'"},
                    {"op": "set_formula", "rule_key": "rule-scout", "column": "posting_formula", "expr": "0.5 if 'plato-opposite' else 1"},
                    {"op": "remove_node", "name": "plato-opposite"})
    found = {(d["table"], d["column"]) for d in report["dangling"]}
    assert found == {("codelet_type_defs", "execute_body"), ("slipnet_node_defs", "descriptor_predicate"),
                     ("posting_rules", "posting_formula")}
    assert all(d["cause_op"] == 3 for d in report["dangling"])
    letter = next(r for r in t["slipnet_node_defs"].values() if r.get("glyph"))
    _, report = run(cfg, {"op": "remove_node", "name": letter["name"]})
    assert any(a["table"] == "demo_problems" for a in report["affected"])
    # a word boundary: removing 'plato-a' is not a mention of 'plato-alphabetic-position-category'
    _, report = run(cfg, {"op": "remove_node", "name": "plato-a"})
    assert not any("alphabetic" in json.dumps(d) for d in report["dangling"])


def test_removing_a_codelet_type_cascades_its_rules_patterns_roles_and_list_entry(cfg):
    t = cfg.tables
    name = "bottom-up-bond-scout"
    ops, report = run(cfg, {"op": "remove_codelet_type", "name": name})
    doc = cd.apply_resolved(cfg, ops)
    assert all(r["codelet_type"] != name for r in doc.tables["posting_rules"].values())
    assert all(r["codelet_type"] != name for r in doc.tables["codelet_pattern_defs"].values())
    assert name not in json.loads(doc.tables["engine_params"][("initial_codelet_types",)]["value"])
    bound = next(iter(t["codelet_type_roles"].values()))["codelet_type"]
    ops, report = run(cfg, {"op": "remove_codelet_type", "name": bound})
    assert cascaded(report, "codelet_type_roles")


def test_a_post_codelet_literal_naming_a_removed_type_is_dangling(cfg):
    _, report = run(cfg, {"op": "set_codelet_body", "name": "rule-scout", "source": "post_codelet('rule-evaluator')"},
                    {"op": "remove_codelet_type", "name": "rule-evaluator"})
    assert [(d["table"], d["key"]) for d in report["dangling"]] == [("codelet_type_defs", {"name": "rule-scout"})]


def test_removing_an_urgency_level_deletes_pattern_entries_and_lists_scalars(cfg):
    ops, report = run(cfg, {"op": "delete", "table": "urgency_levels", "key": {"name": "very_high"}})
    doc = cd.apply_resolved(cfg, ops)
    assert all(e["urgency_level"] != "very_high" for e in doc.tables["codelet_pattern_defs"].values())
    assert cascaded(report, "codelet_pattern_defs")
    assert any(e["kind"] == "run_start" and e["name"] == "very_high" for e in report["effects"])
    ops, report = run(cfg, {"op": "delete", "table": "urgency_levels", "key": {"name": "very_low"}})
    assert any(d["table"] == "engine_params" and d["key"] == {"name": "initial_codelet_urgency"} for d in report["dangling"])


def test_removing_a_parameter_or_coefficient_reports_the_run_start_effect(cfg):
    _, report = run(cfg, {"op": "delete", "table": "engine_params", "key": {"name": "update_cycle_length"}})
    assert report["cascaded"] == []
    (effect,) = report["effects"]
    assert effect["name"] == "update_cycle_length" and "stop at its start" in effect["message"] and effect["ops"] == [0]
    _, report = run(cfg, {"op": "delete", "table": "formula_coefficients", "key": {"name": "sigmoid_divisor"}})
    assert [e["name"] for e in report["effects"]] == ["sigmoid_divisor"]
    _, report = run(cfg, {"op": "delete", "table": "engine_params", "key": {"name": "clampable_codelet_patterns"}})
    assert report["effects"] == []  # optional: its absence is defined


def test_removing_every_initial_codelet_type_reports_the_opening_coderack(cfg):
    names = json.loads(param(cfg, "initial_codelet_types")["value"])
    _, report = run(cfg, *({"op": "remove_codelet_type", "name": n} for n in names))
    assert any(e["what"] == "opening_coderack" for e in report["effects"])


def test_removing_a_link_posting_rule_theme_relation_or_layout_row_cascades_nothing(cfg):
    for op in (
        {"op": "remove_link", "key": {"from_node": "plato-a", "to_node": "plato-b", "link_type": "lateral", "label_node": "plato-successor"}},
        {"op": "remove_posting_rule", "rule_key": "rule-scout"},
        dele("theme_relations", {"name": "identity"}),
        dele("slipnet_layout", {"node_name": "plato-a"}),
        dele("theme_dimension_defs", {"slipnet_node": "plato-letter-category"}),
        dele("slipnet_node_roles", {"role": "dimension.length", "ordinal": 0}),
    ):
        ops, report = run(cfg, op)
        assert len(ops) == 1 and report["cascaded"] == [] and report["dangling"] == [], op


def test_remove_node_splice_joins_the_neighbours_by_the_named_relation(cfg):
    ops, report = run(cfg, {"op": "remove_node", "name": "plato-b", "splice": ["plato-successor"]})
    doc = cd.apply_resolved(cfg, ops)
    assert ("plato-a", "plato-c", "lateral", "plato-successor") in doc.tables["slipnet_link_defs"]
    assert any(c["op"] == "insert" and "splice" in c["reason"] for c in report["cascaded"])
    plain, _ = run(cfg, {"op": "remove_node", "name": "plato-b"})
    assert ("plato-a", "plato-c", "lateral", "plato-successor") not in cd.apply_resolved(cfg, plain).tables["slipnet_link_defs"]


# --- rename and merge ---------------------------------------------------------------------------


def test_rename_node_rewrites_every_reference_and_lists_code_as_dangling(cfg):
    old = "plato-successor"
    ops, report = run(cfg, {"op": "rename_node", "old": old, "new": "plato-next"})
    doc = cd.apply_resolved(cfg, ops)
    t = doc.tables
    assert (old,) not in t["slipnet_node_defs"] and ("plato-next",) in t["slipnet_node_defs"]
    # the node keeps its place
    assert [k[0] for k in t["slipnet_node_defs"]] == [("plato-next" if k[0] == old else k[0]) for k in cfg.tables["slipnet_node_defs"]]
    texts = json.dumps([list(map(str, rows.values())) for name, rows in t.items() if name not in ("codelet_type_defs", "commentary_templates", "demo_problems", "help_topics")])
    assert old not in texts
    assert len(t["slipnet_link_defs"]) == len(cfg.tables["slipnet_link_defs"])
    top = json.loads(t["engine_params"][("top_down_slipnodes",)]["value"])
    assert top == [("plato-next" if x == old else x) for x in json.loads(param(cfg, "top_down_slipnodes")["value"])]
    assert all(c["op"] in ("update",) for c in report["cascaded"])
    assert {c["table"] for c in report["cascaded"]} >= {"slipnet_node_defs", "slipnet_link_defs"}


def test_rename_node_lists_dependents_so_foreign_keys_never_see_a_rekey(cfg):
    node = next(r["node_name"] for r in cfg.tables["slipnet_node_roles"].values() if r["role"] == "dimension.length")
    ops, report = run(cfg, {"op": "rename_node", "old": node, "new": "renamed"})
    positions = {(o["op"], o["table"]): n for n, o in enumerate(ops) if o["table"] in ("slipnet_node_roles", "slipnet_node_defs") and o["op"] != "update"}
    names = [(o["op"], o["table"]) for o in ops]
    first_delete = names.index(("delete", "slipnet_node_roles"))
    rekey = next(n for n, o in enumerate(ops) if o["table"] == "slipnet_node_defs" and o["op"] == "update")
    reinsert = names.index(("insert", "slipnet_node_roles"))
    assert first_delete < rekey < reinsert
    doc = cd.apply_resolved(cfg, ops)
    assert any(r["node_name"] == "renamed" and r["role"] == "dimension.length" for r in doc.tables["slipnet_node_roles"].values())
    assert [(k) for k in doc.tables["slipnet_node_roles"]] == [k for k in cfg.tables["slipnet_node_roles"]]


def test_rename_node_lists_code_that_mentions_the_old_name(cfg):
    _, report = run(cfg, {"op": "set_codelet_body", "name": "rule-scout", "source": "x = 'plato-opposite'"},
                    {"op": "rename_node", "old": "plato-opposite", "new": "renamed"})
    assert {"name": "rule-scout"} in [d["key"] for d in report["dangling"] if d["table"] == "codelet_type_defs"]


def test_rename_to_an_existing_name_is_key_exists(cfg):
    assert refused(cfg, {"op": "rename_node", "old": "plato-a", "new": "plato-b"}).kind == "key_exists"
    assert run(cfg, {"op": "rename_node", "old": "plato-a", "new": "plato-a"})[0] == []


def test_rename_codelet_type_and_urgency_level_rewrite_their_references(cfg):
    ops, report = run(cfg, {"op": "update", "table": "codelet_type_defs", "key": {"name": "bottom-up-bond-scout"},
                            "fields": {"name": "bond-scout-2"}})
    doc = cd.apply_resolved(cfg, ops)
    assert all(r["codelet_type"] != "bottom-up-bond-scout" for t in ("posting_rules", "codelet_pattern_defs", "codelet_type_roles") for r in doc.tables[t].values())
    assert "bond-scout-2" in json.loads(doc.tables["engine_params"][("initial_codelet_types",)]["value"])
    ops, report = run(cfg, {"op": "update", "table": "urgency_levels", "key": {"name": "very_high"}, "fields": {"name": "vh"}})
    doc = cd.apply_resolved(cfg, ops)
    assert all(e["urgency_level"] != "very_high" for e in doc.tables["codelet_pattern_defs"].values())
    assert report["dangling"] == [] or all(d["table"] != "codelet_pattern_defs" for d in report["dangling"])
    _, report = run(cfg, {"op": "update", "table": "urgency_levels", "key": {"name": "very_low"}, "fields": {"name": "vl"}})
    assert any(d["key"] == {"name": "initial_codelet_urgency"} for d in report["dangling"])


def test_merge_nodes_moves_what_it_can_and_reports_every_choice(cfg):
    keep, drop = "plato-a", "plato-b"
    ops, report = run(cfg, {"op": "merge_nodes", "keep": keep, "drop": drop})
    doc = cd.apply_resolved(cfg, ops)
    t = doc.tables
    assert (drop,) not in t["slipnet_node_defs"] and (keep,) in t["slipnet_node_defs"]
    for lk in t["slipnet_link_defs"].values():
        assert drop not in (lk["from_node"], lk["to_node"], lk.get("label_node"))
        assert lk["from_node"] != lk["to_node"]
    keys = list(t["slipnet_link_defs"])
    assert len(keys) == len(set(keys))
    assert report["cascaded"] and all(c["reason"] for c in report["cascaded"])
    assert any("self-link" in c["reason"] for c in report["cascaded"])
    assert ops[-1] == {"op": "delete", "table": "slipnet_node_defs", "key": {"name": drop}}


def test_merge_nodes_roles_params_and_one_row_tables(cfg):
    t = cfg.tables
    held = next(r["node_name"] for r in t["slipnet_node_roles"].values() if r["role"] == "dimension.length")
    keep = next(r["node_name"] for r in t["slipnet_node_roles"].values() if r["role"] == "dimension.direction")
    ops, report = run(cfg, {"op": "merge_nodes", "keep": keep, "drop": held})
    doc = cd.apply_resolved(cfg, ops)
    assert any(r["role"] == "dimension.length" and r["node_name"] == keep for r in doc.tables["slipnet_node_roles"].values())
    assert (keep,) in doc.tables["theme_dimension_defs"]  # keep already had one; drop's is removed
    assert (held,) not in doc.tables["theme_dimension_defs"] and (held,) not in doc.tables["slipnet_layout"]
    top = json.loads(doc.tables["engine_params"][("top_down_slipnodes",)]["value"])
    assert held not in top and len(top) == len(set(top))
    assert refused(cfg, {"op": "merge_nodes", "keep": "plato-a", "drop": "plato-a"}).kind == "malformed"
    assert refused(cfg, {"op": "merge_nodes", "keep": "plato-a", "drop": "nope"}).kind == "unknown_reference"


def test_merge_nodes_in_an_ordered_role_does_not_list_a_node_twice(cfg):
    t = cfg.tables
    order = [r for r in t["slipnet_node_roles"].values() if r["role"] == "rule.dimension_order"]
    keep, drop = order[0]["node_name"], order[1]["node_name"]
    ops, _ = run(cfg, {"op": "merge_nodes", "keep": keep, "drop": drop})
    doc = cd.apply_resolved(cfg, ops)
    bound = [r["node_name"] for r in doc.tables["slipnet_node_roles"].values() if r["role"] == "rule.dimension_order"]
    assert len(bound) == len(set(bound)) == len(order) - 1


def test_rebind_and_unbind_role_errors(cfg):
    assert refused(cfg, {"op": "rebind_role", "role": "no.such", "node": "plato-a"}).kind == "unknown_reference"
    assert refused(cfg, {"op": "rebind_role", "role": "dimension.length"}).kind == "malformed"
    assert refused(cfg, {"op": "rebind_role", "role": "dimension.length", "node": "nope"}).kind == "unknown_reference"
    assert refused(cfg, {"op": "unbind_role", "role": "position.single", "ordinal": 3}).kind == "unknown_reference"
    assert run(cfg, {"op": "unbind_role", "role": "position.single", "ordinal": 3, "ok_if_missing": True})[0] == []
    ops, _ = run(cfg, {"op": "unbind_role", "role": "rule.dimension_order"})
    assert len(ops) == 8


def test_trigger_ops_keep_the_top_down_list_in_step(cfg):
    rule_key = "top-down-bond-scout:direction"
    triggers = cfg.tables["posting_rules"][(rule_key,)]["triggering_slipnodes"]
    ops, _ = run(cfg, {"op": "remove_trigger", "rule_key": rule_key, "node": triggers[0]})
    # another rule may still trigger on it, so the list stays
    other = any(triggers[0] in (r["triggering_slipnodes"] or []) for k, r in cfg.tables["posting_rules"].items() if k != (rule_key,))
    changed_top_down = any(o["table"] == "engine_params" for o in ops)
    assert changed_top_down == (not other)
    assert refused(cfg, {"op": "add_trigger", "rule_key": rule_key, "node": "nope"}).kind == "unknown_reference"
    assert refused(cfg, {"op": "add_trigger", "rule_key": "nope", "node": "plato-a"}).kind == "unknown_reference"


def test_set_template_adds_a_missing_member(cfg):
    ops, _ = run(cfg, {"op": "set_template", "key": "all", "path": "/brand_new", "text": "hi"})
    assert ops[0]["set"]["template_data"]["brand_new"] == "hi"
    assert refused(cfg, {"op": "set_template", "key": "all", "path": "brand_new", "text": "hi"}).kind == "malformed"


def test_set_formula_takes_only_the_formula_columns(cfg):
    assert refused(cfg, {"op": "set_formula", "rule_key": "rule-scout", "column": "direction", "expr": "x"}).kind == "malformed"


def test_add_node_roles_params_and_layout(cfg):
    ops, _ = run(cfg, {"op": "add_node", "name": "x1", "fields": NEW, "roles": [{"role": "position.single", "ordinal": 2}],
                       "layout": {"grid_row": 1, "grid_col": 2}, "params": {"intrinsic_link_lengths": 33, "initially_clamped_slipnodes": True}})
    doc = cd.apply_resolved(cfg, ops)
    assert json.loads(doc.tables["engine_params"][("intrinsic_link_lengths",)]["value"])["x1"] == 33
    assert json.loads(doc.tables["engine_params"][("initially_clamped_slipnodes",)]["value"])[-1] == "x1"
    assert doc.tables["slipnet_layout"][("x1",)]["sort_order"] == len(cfg.tables["slipnet_layout"])
    assert refused(cfg, {"op": "add_node", "name": "x1", "fields": {**NEW, "name": "other"}}).kind == "malformed"
    assert refused(cfg, {"op": "add_node", "name": "x1", "fields": NEW, "params": {"nope": 1}}).kind == "unknown_reference"
    assert refused(cfg, {"op": "add_node", "name": "x1", "fields": NEW, "links": [{"to": "nope", "type": "lateral"}]}).kind == "unknown_reference"


# --- a posting rule names a tier of the urgency levels (stage W) -----------------------------------


def _rules_naming(doc, tier):
    return sorted(r["rule_key"] for r in doc.tables["posting_rules"].values() if r.get("urgency_level") == tier)


def _outcome(meta):
    from server.engine.runner import EngineRunner

    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", None, seed=1)
    runner.run_mcat(max_steps=600)
    return runner.status, runner.ctx.codelet_count, runner.ctx.rng.call_count


@pytest.mark.numeric_matrix
def test_renaming_a_tier_rewrites_the_rules_that_name_it_and_the_run_matches(cfg):
    from server.engine.start_check import check_run_start

    assert _rules_naming(cfg, "medium") == ["jootser", "progress-watcher"]
    ops, report = run(cfg, upd("urgency_levels", {"name": "medium"}, name="middling"))
    doc = cd.apply_resolved(cfg, ops)
    assert _rules_naming(doc, "medium") == [] and _rules_naming(doc, "middling") == ["jootser", "progress-watcher"]
    assert cascaded(report, "posting_rules")
    assert not [d for d in report["dangling"] if d["table"] == "posting_rules"]
    assert check_run_start(cd.provider(doc)) == ()
    assert _outcome(cd.provider(doc)) == _outcome(cd.provider(cfg))


def test_renaming_low_rewrites_its_six_rules(cfg):
    assert len(_rules_naming(cfg, "low")) == 6
    ops, report = run(cfg, upd("urgency_levels", {"name": "low"}, name="lo"))
    doc = cd.apply_resolved(cfg, ops)
    assert _rules_naming(doc, "low") == [] and len(_rules_naming(doc, "lo")) == 6
    # the engine and a codelet body still read the tier ``low`` by name, so the run-start report says so
    assert any(e["kind"] == "run_start" and e["name"] == "low" for e in report["effects"])


def test_removing_a_tier_that_rules_name_is_reported_and_the_run_is_refused(cfg):
    from server.engine.start_check import RunStartError, require_run_start

    ops, report = run(cfg, {"op": "delete", "table": "urgency_levels", "key": {"name": "extremely_low"}})
    assert [(d["table"], d["key"], d["column"]) for d in report["dangling"] if d["table"] == "posting_rules"] == [
        ("posting_rules", {"rule_key": "breaker"}, "urgency_level")]
    assert any(e["kind"] == "run_start" and e["name"] == "extremely_low"
               and "posting rule 'breaker'" in e["message"] for e in report["effects"])
    doc = cd.apply_resolved(cfg, ops)
    # the rule is neither deleted nor quietly sent to ``low``
    assert doc.tables["posting_rules"][("breaker",)]["urgency_level"] == "extremely_low"
    with pytest.raises(RunStartError, match="urgency level 'extremely_low' \\(posting rule 'breaker'\\)"):
        require_run_start(cd.provider(doc))


@pytest.mark.numeric_matrix
def test_removing_a_tier_no_rule_names_is_allowed_and_a_run_starts(cfg):
    from server.engine.start_check import check_run_start

    ops, report = run(cfg, {"op": "delete", "table": "urgency_levels", "key": {"name": "very_high"}},
                      {"op": "delete", "table": "urgency_levels", "key": {"name": "high"}})
    assert not [d for d in report["dangling"] if d["table"] == "posting_rules"]
    # a tier only rules name is not a read of the engine: removing it and repointing its rule is allowed
    ops2, report2 = run(cfg, upd("posting_rules", {"rule_key": "breaker"}, urgency_level="very_low"),
                        {"op": "delete", "table": "urgency_levels", "key": {"name": "extremely_low"}})
    doc = cd.apply_resolved(cfg, ops2)
    assert check_run_start(cd.provider(doc)) == ()
    assert _outcome(cd.provider(doc))[0] in {"answer_found", "gave_up", "halted", "running"}


def test_a_rule_naming_an_unknown_tier_is_refused_by_the_reference_check(cfg):
    err = refused(cfg, upd("posting_rules", {"rule_key": "breaker"}, urgency_level="no-such-tier"))
    assert err.kind == "unknown_reference"
    err = refused(cfg, ins("posting_rules", rule_key="new-rule", codelet_type="rule-scout", direction="bottom_up", urgency_level="no-such-tier"))
    assert err.kind == "unknown_reference"
