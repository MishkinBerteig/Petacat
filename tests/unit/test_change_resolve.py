"""C14a: ``resolve`` (the change API's pure core): generic ops, G6 input validation, ``skip``.

The document is the Metacat Standard Configuration, read from the files.  Pinned here:

* the generic ops, ``expect``, ``ok_if_missing`` and a JSON Patch on a JSON column;
* G6: each of the four classes of 3.4(a) is refused with the op named, with the right status;
* a list of changes that must *not* be refused (a role's node, a letter, the whole chain, a
  coefficient, a codelet type, a required parameter, every node);
* ``on_op_failure: skip`` applies the rest and reports each op skipped;
* purity: the document and the batch are untouched, and the output is deterministic;
* the report's shape.
"""

from __future__ import annotations

import copy
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


def after(cfg, *ops, **env):
    resolved, report = run(cfg, *ops, **env)
    return cd.apply_resolved(cfg, resolved), resolved, report


def refused(cfg, *ops, **env) -> ChangeRefused:
    with pytest.raises(ChangeRefused) as info:
        run(cfg, *ops, **env)
    return info.value


def node(**extra):
    return {"name": "x1", "short_name": "x", "conceptual_depth": 10, **extra}


def ins(table, **row):
    return {"op": "insert", "table": table, "row": row}


# --- generic ops ---------------------------------------------------------------


def test_insert_completes_defaults_and_applies(cfg):
    doc, resolved, report = after(cfg, ins("slipnet_node_defs", **node()))
    assert resolved == [
        {"op": "insert", "table": "slipnet_node_defs", "key": {"name": "x1"},
         "row": resolved[0]["row"]}
    ]
    row = resolved[0]["row"]
    assert row["name"] == "x1" and row["glyph"] is None and row["description"] == ""
    assert row["sort_order"] == max(r["sort_order"] for r in cfg.tables["slipnet_node_defs"].values()) + 1
    assert doc.tables["slipnet_node_defs"][("x1",)] == row
    assert report["ok"] is True and report["applied"][0]["before"] is None
    assert report["applied"][0]["after"] == row


def test_posting_rule_key_defaults_to_the_codelet_type(cfg):
    with_rule = {r["codelet_type"] for r in cfg.tables["posting_rules"].values()}
    free = next(k[0] for k in cfg.tables["codelet_type_defs"] if k[0] not in with_rule)
    _, resolved, _ = after(
        cfg,
        ins("posting_rules", codelet_type=free, direction=next(iter(cfg.tables["posting_rules"].values()))["direction"],
            posting_formula="temperature / 100", count_formula="fixed", condition="always"),
    )
    assert resolved[0]["row"]["rule_key"] == free
    assert resolved[0]["key"] == {"rule_key": free}


def test_update_gives_absolute_values_of_the_changed_columns_only(cfg):
    resolved, report = run(cfg, {"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                                 "fields": {"conceptual_depth": 33, "short_name": cfg.tables["slipnet_node_defs"][("plato-a",)]["short_name"]}})
    assert resolved == [{"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                         "set": {"conceptual_depth": 33}}]
    assert report["applied"][0]["before"]["conceptual_depth"] != 33
    assert report["applied"][0]["after"]["conceptual_depth"] == 33


def test_an_update_that_changes_nothing_resolves_to_no_ops(cfg):
    row = cfg.tables["slipnet_node_defs"][("plato-a",)]
    resolved, report = run(cfg, {"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                                 "fields": {"conceptual_depth": row["conceptual_depth"]}})
    assert resolved == [] and report["applied"] == []


def test_update_expect_guards_the_row(cfg):
    depth = cfg.tables["slipnet_node_defs"][("plato-a",)]["conceptual_depth"]
    op = {"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
          "fields": {"conceptual_depth": 5}, "expect": {"conceptual_depth": depth}}
    assert run(cfg, op)[0]
    err = refused(cfg, {**op, "expect": {"conceptual_depth": depth + 1}})
    assert (err.kind, err.status) == ("stale", 409)


def test_expect_is_checked_by_type_and_by_value(cfg):
    depth = cfg.tables["slipnet_node_defs"][("plato-a",)]["conceptual_depth"]
    err = refused(cfg, {"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                        "fields": {"conceptual_depth": 5}, "expect": {"conceptual_depth": float(depth)}})
    assert err.kind == "malformed"  # an integer column's expectation is an integer
    err = refused(cfg, {"op": "set_param", "name": "update_cycle_length", "to": 5, "expect": 5.0})
    assert err.kind == "stale"  # the parameter is an int: 15 is not 5.0


def test_delete_ok_if_missing_is_a_no_op(cfg):
    op = {"op": "delete", "table": "demo_problems", "key": {"name": "nothing"}}
    assert refused(cfg, op).kind == "unknown_reference"
    resolved, _ = run(cfg, {**op, "ok_if_missing": True})
    assert resolved == []


def test_a_json_patch_edits_a_json_column_and_a_json_parameter(cfg):
    key = next(iter(cfg.tables["commentary_templates"]))[0]
    data = cfg.tables["commentary_templates"][(key,)]["template_data"]
    member = next(iter(data)) if isinstance(data, dict) else None
    assert member is not None
    resolved, _ = run(cfg, {"op": "update", "table": "commentary_templates", "key": {"template_key": key},
                            "patch": {"template_data": [{"op": "replace", "path": "/" + member, "value": "new"}]}})
    assert resolved[0]["set"]["template_data"][member] == "new"
    assert {k: v for k, v in resolved[0]["set"]["template_data"].items() if k != member} == {
        k: v for k, v in data.items() if k != member}
    resolved, _ = run(cfg, {"op": "update", "table": "engine_params", "key": {"name": "top_down_slipnodes"},
                            "patch": {"value": [{"op": "add", "path": "/-", "value": "plato-length"}]}})
    assert json.loads(resolved[0]["set"]["value"])[-1] == "plato-length"


def test_a_failed_patch_test_is_stale_and_a_missing_path_is_unknown(cfg):
    key = {"name": "top_down_slipnodes"}
    base = {"op": "update", "table": "engine_params", "key": key}
    assert refused(cfg, {**base, "patch": {"value": [{"op": "test", "path": "/0", "value": "nope"}]}}).kind == "stale"
    assert refused(cfg, {**base, "patch": {"value": [{"op": "remove", "path": "/999"}]}}).kind == "unknown_reference"
    assert refused(cfg, {**base, "patch": {"value": [{"op": "frob", "path": "/0"}]}}).kind == "malformed"
    assert refused(cfg, {"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                         "patch": {"short_name": []}}).kind == "malformed"


def test_a_key_column_update_rekeys_a_plain_table(cfg):
    resolved, _ = run(cfg, {"op": "update", "table": "demo_problems", "key": {"name": next(iter(cfg.tables["demo_problems"]))[0]},
                            "fields": {"name": "renamed-demo"}})
    assert resolved[0]["set"] == {"name": "renamed-demo"}
    err = refused(cfg, {"op": "update", "table": "urgency_levels", "key": {"name": "low"}, "fields": {"name": "high"}})
    assert err.kind == "key_exists"


# --- G6: the four classes, each with the op named --------------------------------


MALFORMED = [
    ("not an object", "not-a-batch"),
    ("ops not a list", {"ops": {}}),
    ("unknown envelope field", {"ops": [], "surprise": 1}),
    ("bad base_mode", {"ops": [], "base_mode": "sideways"}),
    ("bad on_op_failure", {"ops": [], "on_op_failure": "ignore"}),
    ("bad source", {"ops": [], "source": "someone"}),
    ("unknown op", {"ops": [{"op": "upsert", "table": "demo_problems"}]}),
    ("unknown table", {"ops": [{"op": "delete", "table": "runs", "key": {"id": 1}}]}),
    ("enum table not addressable", {"ops": [{"op": "delete", "table": "codelet_phases", "key": {"name": "scout"}}]}),
    ("unknown field", {"ops": [ins("slipnet_node_defs", **node(colour="red"))]}),
    ("missing field", {"ops": [ins("slipnet_node_defs", name="x1", short_name="x")]}),
    ("wrong type", {"ops": [ins("slipnet_node_defs", **node(conceptual_depth="deep"))]}),
    ("bool for int", {"ops": [ins("slipnet_node_defs", **node(conceptual_depth=True))]}),
    ("surrogate id", {"ops": [ins("slipnet_node_defs", **node(id=3))]}),
    ("key incomplete", {"ops": [{"op": "delete", "table": "slipnet_link_defs", "key": {"from_node": "a"}}]}),
    ("value_type unparseable", {"ops": [ins("engine_params", name="p1", value="abc", value_type="int")]}),
    ("rational unparseable", {"ops": [ins("formula_coefficients", name="c1", value="1/0", value_type="rational")]}),
    ("unknown convenience argument", {"ops": [{"op": "remove_node", "name": "plato-a", "force": True}]}),
    ("missing convenience argument", {"ops": [{"op": "rename_node", "old": "plato-a"}]}),
    ("convenience argument type", {"ops": [{"op": "adjust_param", "name": "x", "by": "three"}]}),
    ("list for object", {"ops": [{"op": "add_node", "name": "x1", "fields": []}]}),
]


@pytest.mark.parametrize("label, batch", MALFORMED, ids=[m[0] for m in MALFORMED])
def test_malformed_is_400(cfg, label, batch):
    with pytest.raises(ChangeRefused) as info:
        resolve(cfg, batch)
    assert info.value.kind == "malformed" and info.value.status == 400


def test_malformed_names_the_op_and_the_field(cfg):
    err = refused(cfg, ins("demo_problems", name="d1", initial="a", modified="b", target="c", seed=1),
                  ins("slipnet_node_defs", **node(conceptual_depth="deep")))
    problem = err.problems[0]
    assert problem.op_index == 1 and problem.field == "row.conceptual_depth"
    assert err.as_dict()["problems"][0]["op_index"] == 1


def test_a_malformed_batch_is_refused_under_skip_too(cfg):
    assert refused(cfg, {"op": "upsert"}, on_op_failure="skip").status == 400


def test_unknown_reference_is_422_and_names_the_op(cfg):
    cases = [
        ({"op": "update", "table": "slipnet_node_defs", "key": {"name": "no-such"}, "fields": {"short_name": "q"}}, 0),
        ({"op": "delete", "table": "posting_rules", "key": {"rule_key": "no-such"}}, 0),
        (ins("slipnet_layout", node_name="no-such", grid_row=0, grid_col=0), 0),
        (ins("slipnet_link_defs", from_node="plato-a", to_node="no-such", link_type="lateral", link_length=None, fixed_length=False), 0),
        (ins("slipnet_link_defs", from_node="plato-a", to_node="plato-b", link_type="no-such-kind", link_length=None, fixed_length=False), 0),
        (ins("slipnet_link_defs", from_node="plato-a", to_node="plato-b", link_type="lateral", label_node="no-such", link_length=None, fixed_length=False), 0),
        (ins("slipnet_node_roles", role="no.such.role", ordinal=0, node_name="plato-a"), 0),
        (ins("slipnet_node_roles", role="evaluator.bond", ordinal=0, node_name="plato-a"), 0),
        (ins("codelet_type_roles", role="dimension.length", ordinal=0, codelet_type="rule-scout"), 0),
        (ins("posting_rules", codelet_type="no-such", direction="bottom_up", posting_formula="temperature / 100", count_formula="fixed", condition="always"), 0),
        (ins("codelet_pattern_defs", pattern_name="p", codelet_type="rule-scout", urgency_level="no-such"), 0),
        (ins("posting_rules", codelet_type="rule-scout", direction="bottom_up", posting_formula="temperature / 100", count_formula="fixed", condition="always",
             triggering_slipnodes=["plato-a", "no-such"]), 0),
        ({"op": "rename_node", "old": "no-such", "new": "other"}, 0),
        ({"op": "set_param", "name": "no-such", "to": 1}, 0),
    ]
    direction = next(iter(cfg.tables["posting_rules"].values()))["direction"]
    with_rule = {r["codelet_type"] for r in cfg.tables["posting_rules"].values()}
    free = next(k[0] for k in cfg.tables["codelet_type_defs"] if k[0] not in with_rule)
    for op, index in cases:
        row = op.get("row", {})
        if row.get("direction") == "bottom_up":
            row["direction"] = direction
        if row.get("codelet_type") == "rule-scout" and "triggering_slipnodes" in row:
            row["codelet_type"] = free
        err = refused(cfg, op)
        assert (err.kind, err.status) == ("unknown_reference", 422), op
        assert err.problems[0].op_index == index, op


def test_a_reference_is_checked_once_on_the_resulting_state(cfg):
    # The node and its link in either order.
    link = ins("slipnet_link_defs", from_node="x1", to_node="plato-a", link_type="lateral", link_length=None, fixed_length=False)
    for ops in ([ins("slipnet_node_defs", **node()), link], [link, ins("slipnet_node_defs", **node())]):
        doc, _, _ = after(cfg, *ops)
        assert ("x1", "plato-a", "lateral", "") in doc.tables["slipnet_link_defs"]
    err = refused(cfg, link)
    assert err.problems[0].op_index == 0 and err.problems[0].field == "from_node"


def test_a_reference_the_cascade_removed_is_not_dangling(cfg):
    doc, _, report = after(
        cfg, ins("slipnet_node_defs", **node()),
        ins("slipnet_link_defs", from_node="x1", to_node="plato-a", link_type="lateral", link_length=None, fixed_length=False),
        {"op": "remove_node", "name": "x1"})
    assert ("x1",) not in doc.tables["slipnet_node_defs"] and doc.tables["slipnet_link_defs"] == cfg.tables["slipnet_link_defs"]


CODE = [
    ("codelet body", {"op": "set_codelet_body", "name": "rule-scout", "source": "def ("}, "codelet_body"),
    ("codelet body, generic", {"op": "update", "table": "codelet_type_defs", "key": {"name": "rule-scout"},
                               "fields": {"execute_body": "x = = 1"}}, "codelet_body"),
    ("descriptor predicate", {"op": "set_predicate", "node": "plato-a", "expr": "is_group(obj) and"}, "expression"),
    ("posting formula", {"op": "set_formula", "rule_key": "rule-scout", "column": "posting_formula", "expr": "1 +"}, "expression"),
    ("count formula", {"op": "set_formula", "rule_key": "rule-scout", "column": "count_formula", "expr": "(1"}, "expression"),
    ("condition", {"op": "set_formula", "rule_key": "rule-scout", "column": "condition", "expr": "a b"}, "expression"),
    ("urgency formula", {"op": "set_formula", "rule_key": "rule-scout", "column": "urgency_formula", "expr": "1 +"}, "expression"),
    ("inserted body", ins("codelet_type_defs", name="c1", family="scout", phase="build", execute_body="if:"), "codelet_body"),
]


@pytest.mark.parametrize("label, op, language", CODE, ids=[c[0] for c in CODE])
def test_code_that_does_not_compile_is_422_with_line_and_column(cfg, label, op, language):
    if op["op"] == "insert":
        op["row"]["family"] = next(iter(cfg.tables["codelet_families"]))[0]
        op["row"]["phase"] = next(iter(cfg.tables["codelet_phases"]))[0]
    err = refused(cfg, ins("demo_problems", name="d1", initial="a", modified="b", target="c", seed=1), op)
    p = err.problems[0]
    assert (err.kind, err.status) == ("does_not_compile", 422)
    assert p.op_index == 1 and p.language == language and p.line >= 1 and p.column >= 1


def test_blank_code_compiles(cfg):
    assert run(cfg, {"op": "set_codelet_body", "name": "rule-scout", "source": ""})[0]
    with_predicate = next(r["name"] for r in cfg.tables["slipnet_node_defs"].values() if r.get("descriptor_predicate"))
    assert run(cfg, {"op": "set_predicate", "node": with_predicate, "expr": None})[0]


def test_stale_and_key_exists_are_409(cfg):
    existing = next(iter(cfg.tables["demo_problems"].values()))
    dup = {**existing}
    err = refused(cfg, ins("demo_problems", **dup))
    assert (err.kind, err.status) == ("key_exists", 409)
    glyph_row = {**cfg.tables["slipnet_node_defs"][("plato-a",)], "name": "x1"}
    assert refused(cfg, ins("slipnet_node_defs", **glyph_row)).kind == "key_exists"
    numbered = next(r for r in cfg.tables["slipnet_node_defs"].values() if r.get("numeric_value") is not None)
    assert refused(cfg, ins("slipnet_node_defs", **node(numeric_value=numbered["numeric_value"]))).kind == "key_exists"
    assert refused(cfg, {"op": "add_link", "from": "plato-a", "to": "plato-b", "type": "lateral",
                         "label": "plato-successor", "fixed": False}).kind == "key_exists"
    assert refused(cfg, {"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                         "fields": {"name": "plato-b"}}).kind == "key_exists"
    bound = next(iter(cfg.tables["slipnet_node_roles"].values()))
    other = next(r for r in cfg.tables["slipnet_node_roles"].values() if r["role"] != bound["role"])
    assert refused(cfg, ins("slipnet_node_roles", role=other["role"], ordinal=5, node_name=other["node_name"])).kind == "key_exists"


def test_the_batch_is_refused_whole_under_abort(cfg):
    err = refused(cfg, ins("slipnet_node_defs", **node()),
                  {"op": "update", "table": "slipnet_node_defs", "key": {"name": "no-such"}, "fields": {"short_name": "q"}})
    assert err.problems[0].op_index == 1


# --- changes that must not be refused (3.4(a)) ---------------------------------------


def _node_of(cfg, role):
    return next(r["node_name"] for r in cfg.tables["slipnet_node_roles"].values() if r["role"] == role)


def test_changes_that_must_not_be_refused(cfg):
    letters = [r["name"] for r in cfg.tables["slipnet_node_defs"].values() if r.get("glyph")]
    successor = _node_of(cfg, "group_category.successor")
    cases = {
        "remove a role's node": [{"op": "remove_node", "name": _node_of(cfg, "dimension.length")}],
        "remove a letter": [{"op": "remove_node", "name": letters[3]}],
        "remove the whole chain": [{"op": "remove_node", "name": n} for n in letters],
        "remove every node": [{"op": "remove_node", "name": n} for n in list(r["name"] for r in cfg.tables["slipnet_node_defs"].values())],
        "remove the first-letter marker's node": [{"op": "remove_node", "name": _node_of(cfg, "alphabet.first_marker")}],
        "remove a coefficient": [{"op": "delete", "table": "formula_coefficients", "key": {"name": "sigmoid_divisor"}}],
        "remove a required parameter": [{"op": "delete", "table": "engine_params", "key": {"name": "update_cycle_length"}}],
        "remove an urgency level": [{"op": "delete", "table": "urgency_levels", "key": {"name": "low"}}],
        "remove a codelet type": [{"op": "remove_codelet_type", "name": "rule-scout"}],
        "remove an evaluator role's codelet type": [{"op": "remove_codelet_type", "name": next(r["codelet_type"] for r in cfg.tables["codelet_type_roles"].values() if r["role"] == "evaluator.bond")}],
        "remove every posting rule": [{"op": "remove_posting_rule", "rule_key": k[0]} for k in cfg.tables["posting_rules"]],
        "unbind a role": [{"op": "unbind_role", "role": "dimension.length"}],
        "rename the successor node": [{"op": "rename_node", "old": successor, "new": "renamed-successor"}],
        "merge two letters": [{"op": "merge_nodes", "keep": letters[0], "drop": letters[1]}],
        "remove the label node of every successor link": [{"op": "remove_node", "name": "plato-successor"}],
        "depth outside 0-100": [{"op": "update", "table": "slipnet_node_defs", "key": {"name": letters[0]}, "fields": {"conceptual_depth": 500}}],
        "a coefficient to zero": [{"op": "set_coefficient", "name": "sigmoid_divisor", "to": 0}],
    }
    for label, ops in cases.items():
        resolved, report = run(cfg, *ops)
        cd.apply_resolved(cfg, resolved)  # structurally valid
        assert report["ok"], label


def test_removing_everything_leaves_a_well_formed_empty_slipnet(cfg):
    names = [r["name"] for r in cfg.tables["slipnet_node_defs"].values()]
    doc, _, report = after(cfg, *({"op": "remove_node", "name": n} for n in names))
    for t in ("slipnet_node_defs", "slipnet_link_defs", "slipnet_layout", "slipnet_node_roles", "theme_dimension_defs"):
        assert len(doc.tables[t]) == 0, t
    assert json.loads(doc.tables["engine_params"][("top_down_slipnodes",)]["value"]) == []
    assert json.loads(doc.tables["engine_params"][("intrinsic_link_lengths",)]["value"]) == {}


def test_a_depth_outside_the_range_is_an_advisory_not_a_refusal(cfg):
    _, report = run(cfg, {"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                          "fields": {"conceptual_depth": 500}})
    assert [a["field"] for a in report["advisories"]] == ["conceptual_depth"]
    assert report["advisories"][0]["op"] == 0
    _, report = run(cfg, {"op": "set_param", "name": "initial_temperature", "to": 900})
    assert report["advisories"] and report["advisories"][0]["field"] == "value"


def test_a_label_with_no_intrinsic_length_is_an_advisory(cfg):
    _, report = run(cfg, {"op": "add_node", "name": "x1", "fields": {"short_name": "x", "conceptual_depth": 5}},
                    {"op": "add_link", "from": "plato-a", "to": "plato-b", "type": "lateral", "label": "x1",
                     "fixed": False})
    assert any(a["field"] == "label_node" for a in report["advisories"])


# --- on_op_failure: skip ----------------------------------------------------------------


def test_skip_applies_the_rest_and_lists_each_skipped_op(cfg):
    ops = [
        {"op": "set_param", "name": "initial_temperature", "to": 90},
        {"op": "update", "table": "slipnet_node_defs", "key": {"name": "no-such"}, "fields": {"short_name": "q"}},
        {"op": "set_codelet_body", "name": "rule-scout", "source": "def ("},
        ins("slipnet_node_defs", **node(**{"name": "plato-a"})),
        {"op": "set_coefficient", "name": "sigmoid_divisor", "to": 3, "expect": 12345},
        {"op": "move_layout", "node": "plato-a", "x": 3, "y": 4},
    ]
    doc, resolved, report = after(cfg, *ops, on_op_failure="skip")
    assert [s["op"] for s in report["skipped"]] == [1, 2, 3, 4]
    assert [s["reason"]["error"] for s in report["skipped"]] == [
        "unknown_reference", "does_not_compile", "key_exists", "stale"]
    assert [a["op_index"] for a in report["applied"]] == [0, 5]
    assert doc.tables["slipnet_layout"][("plato-a",)]["grid_col"] == 3


def test_skip_rolls_back_a_convenience_op_that_fails_halfway(cfg):
    # add_node inserts the node, then its link to a node that does not exist.
    doc, resolved, report = after(
        cfg,
        {"op": "add_node", "name": "x1", "fields": {"short_name": "x", "conceptual_depth": 5},
         "links": [{"to": "plato-a", "type": "lateral", "fixed": False},
                   {"to": "no-such", "type": "lateral", "fixed": False}]},
        {"op": "set_param", "name": "initial_temperature", "to": 90},
        on_op_failure="skip")
    assert ("x1",) not in doc.tables["slipnet_node_defs"]
    assert len(doc.tables["slipnet_link_defs"]) == len(cfg.tables["slipnet_link_defs"])
    assert [s["op"] for s in report["skipped"]] == [0]
    assert len(resolved) == 1


def test_skip_skips_the_op_that_wrote_a_dangling_reference_and_reruns(cfg):
    doc, resolved, report = after(
        cfg,
        ins("slipnet_link_defs", from_node="plato-a", to_node="no-such", link_type="lateral", link_length=None, fixed_length=False),
        {"op": "set_param", "name": "initial_temperature", "to": 90},
        on_op_failure="skip")
    assert [s["op"] for s in report["skipped"]] == [0]
    assert report["skipped"][0]["reason"]["error"] == "unknown_reference"
    assert doc.tables["slipnet_link_defs"] == cfg.tables["slipnet_link_defs"]


def test_skip_of_a_node_then_its_link_skips_both(cfg):
    doc, _, report = after(
        cfg,
        ins("slipnet_node_defs", **node(**{"name": "plato-a"})),
        ins("slipnet_link_defs", from_node="plato-a", to_node="plato-b", link_type="lateral", label_node="plato-successor", link_length=None, fixed_length=False),
        on_op_failure="skip")
    assert [s["op"] for s in report["skipped"]] == [0, 1]


# --- purity and determinism -----------------------------------------------------------------


def test_resolve_is_pure_and_deterministic(cfg):
    batch = {"on_op_failure": "skip", "ops": [
        {"op": "remove_node", "name": "plato-successor"},
        {"op": "rename_node", "old": "plato-a", "new": "plato-aa"},
        {"op": "adjust_param", "name": "update_cycle_length", "by": 2},
        {"op": "move_layout", "node": "plato-b", "x": 1, "y": 2},
    ]}
    frozen_batch = copy.deepcopy(batch)
    before = {t: list(rows.items()) for t, rows in cfg.tables.items()}
    first = resolve(cfg, batch)
    second = resolve(cfg, batch)
    assert first == second
    assert batch == frozen_batch
    assert {t: list(rows.items()) for t, rows in cfg.tables.items()} == before


def test_resolve_does_not_share_mutable_state_with_the_document(cfg):
    resolved, report = run(cfg, {"op": "remove_node", "name": "plato-a"})
    for op in resolved:
        if op["op"] == "insert":
            op["row"]["__scribble__"] = 1
    for a in report["applied"]:
        for image in (a["before"], a["after"]):
            if image is not None:
                image["__scribble__"] = 1
    assert all("__scribble__" not in r for t in cfg.tables.values() for r in t.values())


def test_the_report_shape(cfg):
    resolved, report = run(cfg, {"op": "remove_node", "name": "plato-opposite"})
    assert set(report) == {"ok", "applied", "skipped", "cascaded", "dangling", "affected", "effects", "advisories"}
    assert len(report["applied"]) == len(resolved)
    assert [a["op"] for a in report["applied"]] == resolved
    for c in report["cascaded"]:
        assert set(c) == {"cause_op", "table", "key", "op", "reason"}
    assert {c["table"] for c in report["cascaded"]} >= {"slipnet_link_defs"}
    assert resolved[-1] == {"op": "delete", "table": "slipnet_node_defs", "key": {"name": "plato-opposite"}}


def test_apply_resolved_gives_the_document_the_report_describes(cfg):
    resolved, report = run(cfg, {"op": "remove_node", "name": "plato-successor"},
                           {"op": "adjust_param", "name": "update_cycle_length", "by": 1})
    doc = cd.apply_resolved(cfg, resolved)
    for a in report["applied"]:
        op = a["op"]
        key = tuple(op["key"].values())
        if op["op"] == "delete":
            assert key not in doc.tables[op["table"]] and a["after"] is None
        elif op["op"] == "update":
            assert a["after"] == {**a["before"], **op["set"]}
        else:
            assert doc.tables[op["table"]][key] == a["after"] and a["before"] is None
