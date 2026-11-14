"""C14a: the JSON Patch subset, ``schema(registry)`` and the refusal type."""

from __future__ import annotations

import copy
import json

import pytest

from server.services.change_resolve import ChangeRefused, resolve, schema
from server.services.change_resolve.patch import PatchError, apply_patch
from server.services.config_registry import ENUM_REGISTRY, REGISTRY
from server.services.configuration_input import InputProblem, STATUS


# --- JSON Patch --------------------------------------------------------------------


def test_add_replace_remove_and_test():
    doc = {"a": [1, 2, 3], "b": {"c": 1}}
    frozen = copy.deepcopy(doc)
    out = apply_patch(doc, [
        {"op": "test", "path": "/b/c", "value": 1},
        {"op": "add", "path": "/a/1", "value": 9},
        {"op": "add", "path": "/a/-", "value": 4},
        {"op": "replace", "path": "/b/c", "value": 2},
        {"op": "add", "path": "/b/d", "value": [1]},
        {"op": "remove", "path": "/a/0"},
    ])
    assert out == {"a": [9, 2, 3, 4], "b": {"c": 2, "d": [1]}}
    assert doc == frozen  # never mutated


def test_move_and_pointer_escapes():
    out = apply_patch({"a/b": {"~k": 1}, "x": []}, [{"op": "move", "from": "/a~1b/~0k", "path": "/x/0"}])
    assert out == {"a/b": {}, "x": [1]}
    assert apply_patch({"x": 1}, [{"op": "replace", "path": "", "value": [1]}]) == [1]


@pytest.mark.parametrize("patch, kind", [
    ("nope", "malformed"),
    ([{"op": "copy", "from": "/a", "path": "/b"}], "malformed"),
    ([{"op": "add", "path": "a", "value": 1}], "malformed"),
    ([{"op": "add", "path": "/a"}], "malformed"),
    ([{"op": "remove", "path": ""}], "malformed"),
    ([{"op": "move", "from": "/a", "path": "/a/b"}], "malformed"),
    ([{"op": "remove", "path": "/nope"}], "missing"),
    ([{"op": "replace", "path": "/nope", "value": 1}], "missing"),
    ([{"op": "add", "path": "/l/5", "value": 1}], "missing"),
    ([{"op": "add", "path": "/l/01", "value": 1}], "missing"),
    ([{"op": "test", "path": "/a", "value": 2}], "test"),
])
def test_patch_errors_have_a_kind(patch, kind):
    with pytest.raises(PatchError) as info:
        apply_patch({"a": 1, "l": []}, patch)
    assert info.value.kind == kind


# --- schema ------------------------------------------------------------------------


def test_schema_lists_every_addressable_table_and_no_enum_table():
    s = schema(REGISTRY)
    names = [t["name"] for t in s["tables"]]
    assert names == sorted(REGISTRY) and len(names) == 20 and "link_types" in names
    assert not set(names) & set(ENUM_REGISTRY)
    assert "help_topics" not in names
    assert not any("memory" in n or "run" in n or "journal" in n for n in names)
    json.dumps(s)  # JSON-compatible


def test_schema_states_keys_order_code_and_json_columns():
    tables = {t["name"]: t for t in schema()["tables"]}
    links = tables["slipnet_link_defs"]
    assert links["key"] == ["from_node", "to_node", "link_type", "label_node"]
    assert links["order"] == ["sort_order"]
    columns = {c["name"]: c for c in links["columns"]}
    assert columns["label_node"]["nullable"] and columns["label_node"]["key"]
    assert columns["from_node"]["reference"] == {"target": "slipnet_node_defs", "many": False}
    assert "id" not in columns  # the surrogate id is not part of a row
    body = {c["name"]: c for c in tables["codelet_type_defs"]["columns"]}["execute_body"]
    assert body["code"] and body["language"] == "codelet_body"
    predicate = {c["name"]: c for c in tables["slipnet_node_defs"]["columns"]}["descriptor_predicate"]
    assert predicate["code"] and predicate["language"] == "expression"
    rules = {c["name"]: c for c in tables["posting_rules"]["columns"]}
    assert rules["triggering_slipnodes"]["json"] and rules["triggering_slipnodes"]["reference"]["many"]
    assert all(rules[c]["code"] for c in ("urgency_formula", "posting_formula", "count_formula", "condition"))
    assert {c["name"]: c for c in tables["engine_params"]["columns"]}["value"]["value_type_column"] == "value_type"
    assert tables["slipnet_node_defs"]["unique"] == [["glyph"], ["numeric_value"]]
    assert {c["name"]: c for c in tables["slipnet_node_roles"]["columns"]}["role"]["reference"]["target"] == "role.node"


def test_schema_lists_the_ops_and_the_role_vocabulary():
    s = schema()
    assert s["ops"]["generic"] == ["insert", "update", "delete"]
    assert {"add_node", "remove_node", "rename_node", "merge_nodes", "adjust", "reorder", "list_add",
            "move_layout", "add_trigger", "rebind_role"} <= set(s["ops"]["convenience"])
    assert "dimension.length" in s["roles"]["node"] and "evaluator.bond" in s["roles"]["codelet_type"]
    assert "rational" in s["value_types"]


def test_every_convenience_op_has_a_handler_and_an_argument_list():
    from server.services.change_resolve import checks, core
    names = set(schema()["ops"]["convenience"])
    assert names == set(checks._ARGS)
    assert names - set(core._HANDLERS) == set()


# --- the refusal type --------------------------------------------------------------


@pytest.mark.parametrize("kind", ["malformed", "unknown_reference", "does_not_compile", "stale", "key_exists"])
def test_a_refusal_maps_to_its_http_status(kind):
    exc = ChangeRefused([InputProblem(kind, "why", 3, "f", "t", ["k"])])
    assert exc.kind == kind and exc.status == STATUS[kind]
    assert STATUS[kind] == {"malformed": 400, "unknown_reference": 422, "does_not_compile": 422,
                            "stale": 409, "key_exists": 409}[kind]
    body = exc.as_dict()
    assert body["error"] == kind and body["op_index"] == 3 and body["problems"][0]["table"] == "t"
    assert str(exc) == "why"


def test_a_refusal_from_resolve_carries_every_dangling_reference():
    from server.services import config_document as cd
    from tests.integration.equivalence_harness import SEED_DIR
    cfg = cd.document_from_standard_files(SEED_DIR)
    with pytest.raises(ChangeRefused) as info:
        resolve(cfg, {"ops": [
            {"op": "insert", "table": "slipnet_link_defs",
             "row": {"from_node": "nope-1", "to_node": "nope-2", "link_type": "lateral",
                     "link_length": None, "fixed_length": False}}]})
    assert [p.field for p in info.value.problems] == ["from_node", "to_node"]
    assert info.value.as_dict()["problems"][1]["field"] == "to_node"
