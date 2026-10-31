"""The four input-check classes of 3.4(a), as pure library functions (C0).

No database, no engine, no routes: ``server/services/configuration_input.py`` only.  The
tables here are a small stand-in for the registry C14 will supply; what is tested is the
checking, which does not depend on which tables exist.
"""

from __future__ import annotations

import copy

import pytest

from server.services.configuration_input import (
    DOES_NOT_COMPILE,
    KEY_EXISTS,
    MALFORMED,
    STALE,
    UNKNOWN_REFERENCE,
    ColumnSpec,
    Reference,
    TableSpec,
    apply_ops_to_copy,
    check_base_version,
    check_code,
    check_code_in_ops,
    check_malformed,
    check_param_value,
    check_references,
    parse_param_value,
    validate_batch,
)

TABLES = {
    "nodes": TableSpec(
        "nodes", ("name",),
        {
            "name": ColumnSpec("str"),
            "depth": ColumnSpec("int"),
            "predicate": ColumnSpec("code_eval", nullable=True, required=False),
            "weight": ColumnSpec("float", required=False),
        },
    ),
    "links": TableSpec(
        "links", ("from_node", "to_node"),
        {
            "from_node": ColumnSpec("str", reference=Reference("nodes")),
            "to_node": ColumnSpec("str", reference=Reference("nodes")),
            "kind": ColumnSpec("str", reference=Reference("link_kinds")),
            "label_node": ColumnSpec("str", nullable=True, required=False, reference=Reference("nodes")),
        },
    ),
    "rules": TableSpec(
        "rules", ("rule_key",),
        {
            "rule_key": ColumnSpec("str"),
            "triggers": ColumnSpec("json", nullable=True, required=False,
                                   reference=Reference("nodes", many=True)),
            "formula": ColumnSpec("code_eval", required=False),
        },
    ),
    "codelets": TableSpec(
        "codelets", ("name",),
        {"name": ColumnSpec("str"), "body": ColumnSpec("code_exec", required=False)},
    ),
    "params": TableSpec(
        "params", ("name",),
        {
            "name": ColumnSpec("str"),
            "value": ColumnSpec("str", value_type_column="value_type"),
            "value_type": ColumnSpec("str"),
        },
    ),
}
VOCAB = {"link_kinds": {"category", "lateral"}}


def state():
    return {
        "nodes": {("a",): {"name": "a", "depth": 10, "predicate": None},
                  ("b",): {"name": "b", "depth": 20, "predicate": None}},
        "links": {("a", "b"): {"from_node": "a", "to_node": "b", "kind": "lateral", "label_node": None}},
        "rules": {}, "codelets": {}, "params": {},
    }


def batch(*ops, **envelope):
    return {"base_version": 3, "ops": list(ops), **envelope}


def ins(table, **row):
    return {"op": "insert", "table": table, "row": row}


def validate(b, st=None):
    return validate_batch(b, st if st is not None else state(), TABLES, current_version=3, vocabularies=VOCAB)


# --- malformed (400) --------------------------------------------------------


@pytest.mark.parametrize(
    "bad, field",
    [
        ("not an object", None),
        ({"ops": "x"}, "ops"),
        ({"ops": [], "surprise": 1}, "surprise"),
        ({"ops": [], "base_mode": "sideways"}, "base_mode"),
        ({"ops": [], "on_op_failure": "ignore"}, "on_op_failure"),
        ({"ops": [], "source": "someone"}, "source"),
        ({"ops": [], "dry_run": "yes"}, "dry_run"),
        ({"ops": ["x"]}, "op"),
        ({"ops": [{"op": "upsert", "table": "nodes"}]}, "op"),
        ({"ops": [{"op": "insert", "table": "enum_table", "row": {}}]}, "table"),
        ({"ops": [{"op": "insert", "table": "nodes"}]}, "row"),
        ({"ops": [{"op": "insert", "table": "nodes", "row": {"name": "c"}}]}, "row.depth"),
        ({"ops": [{"op": "insert", "table": "nodes", "row": {"name": "c", "depth": 1, "colour": 1}}]}, "row.colour"),
        ({"ops": [{"op": "insert", "table": "nodes", "row": {"name": "c", "depth": "deep"}}]}, "row.depth"),
        ({"ops": [{"op": "insert", "table": "nodes", "row": {"name": "c", "depth": True}}]}, "row.depth"),
        ({"ops": [{"op": "insert", "table": "nodes", "row": {"name": None, "depth": 1}}]}, "row.name"),
        ({"ops": [{"op": "update", "table": "nodes", "key": {"nom": "a"}, "fields": {}}]}, "key"),
        ({"ops": [{"op": "update", "table": "nodes", "key": {"name": "a"}}]}, "fields"),
        ({"ops": [{"op": "update", "table": "nodes", "key": {"name": "a"}, "fields": [1]}]}, "fields"),
        ({"ops": [{"op": "delete", "table": "nodes", "key": {"name": "a"}, "ok_if_missing": "yes"}]}, "ok_if_missing"),
        ({"ops": [{"op": "delete", "table": "nodes", "key": {"name": "a"}, "extra": 1}]}, "extra"),
        ({"ops": [ins("rules", rule_key="r", triggers="a")]}, "row.triggers"),
        ({"ops": [ins("rules", rule_key="r", triggers=[1])]}, "row.triggers"),
    ],
)
def test_malformed_requests_are_400_and_name_the_field(bad, field):
    problems = check_malformed(bad, TABLES)
    assert problems and all(p.kind == MALFORMED and p.status == 400 for p in problems)
    if field is not None:
        assert any(p.field == field for p in problems), [p.as_dict() for p in problems]


def test_a_table_outside_the_target_configurations_set_is_malformed():
    problems = check_malformed(batch(ins("help_topics", topic_key="x")), TABLES)
    assert problems[0].kind == MALFORMED and problems[0].field == "table" and problems[0].op_index == 0
    # The same batch is fine against a table set that has it.
    wider = {**TABLES, "help_topics": TableSpec("help_topics", ("topic_key",), {"topic_key": ColumnSpec("str")})}
    assert check_malformed(batch(ins("help_topics", topic_key="x")), wider) == []


def test_the_op_index_is_named():
    problems = check_malformed(batch(ins("nodes", name="c", depth=1), {"op": "nope"}), TABLES)
    assert [(p.kind, p.op_index) for p in problems] == [(MALFORMED, 1)]


def test_a_well_formed_batch_is_clean():
    ok = batch(
        ins("nodes", name="c", depth=30),
        {"op": "update", "table": "nodes", "key": {"name": "a"}, "fields": {"depth": 11}, "expect": {"depth": 10}},
        {"op": "delete", "table": "nodes", "key": {"name": "b"}, "ok_if_missing": True},
        base_mode="strict", on_op_failure="abort", source="external", dry_run=False, actor="x", note="n",
        configuration_id=1,
    )
    assert check_malformed(ok, TABLES) == []


@pytest.mark.parametrize(
    "text, value_type, good",
    [
        ("12", "int", True), ("1.5", "int", False), ("x", "int", False),
        ("1.5", "float", True), ("3", "float", True), ("one", "float", False),
        ("true", "bool", True), ("False", "bool", True), ("yes", "bool", False),
        ('{"a": [1]}', "json", True), ("{nope", "json", False),
        ("anything at all", "string", True),
    ],
)
def test_value_type_must_parse(text, value_type, good):
    assert parse_param_value(text, value_type)[0] is good
    problem = check_param_value(text, value_type)
    assert (problem is None) is good
    if not good:
        assert problem.kind == MALFORMED


def test_unknown_value_type_and_value_type_in_a_row_are_malformed():
    assert check_param_value("1", "complex").kind == MALFORMED
    bad = batch(ins("params", name="p", value="1.5", value_type="int"))
    problems = check_malformed(bad, TABLES)
    assert problems and problems[0].kind == MALFORMED and problems[0].op_index == 0
    assert check_malformed(batch(ins("params", name="p", value="15", value_type="int")), TABLES) == []


# --- code that does not compile (422) -----------------------------------------


def test_code_that_compiles_is_accepted():
    assert check_code("expression", "obj.length > 2 and not obj.is_letter") is None
    assert check_code("codelet_body", "x = 1\nif x:\n    fizzle()\n") is None
    assert check_code("codelet_body", "") is None  # the defined no-op
    assert check_code("expression", "   ") is None


def test_an_expression_that_does_not_parse_names_line_and_column():
    problem = check_code("expression", "1 +", op_index=2, field="formula", table="rules")
    assert problem.kind == DOES_NOT_COMPILE and problem.status == 422
    assert problem.language == "expression" and problem.op_index == 2
    assert problem.line == 1 and problem.column is not None and problem.column >= 1


def test_a_codelet_body_error_reports_its_line():
    problem = check_code("codelet_body", "x = 1\ny = (2\nz = 3\n")
    assert problem.kind == DOES_NOT_COMPILE and problem.language == "codelet_body"
    assert problem.line >= 2


def test_a_statement_is_not_an_expression_and_a_null_byte_does_not_compile():
    assert check_code("expression", "x = 1").kind == DOES_NOT_COMPILE
    assert check_code("codelet_body", "x = 1\x00").kind == DOES_NOT_COMPILE


def test_code_is_never_run():
    marker = []
    check_code("codelet_body", "import os\nos.system('exit 1')\nraise SystemExit")
    assert marker == []  # nothing to observe: compile only (a SystemExit would have ended the test)


def test_code_columns_in_ops_are_compiled_and_named_by_op_and_field():
    ops = [
        ins("nodes", name="c", depth=1, predicate="obj.x >"),
        ins("codelets", name="k", body="def"),
        {"op": "update", "table": "rules", "key": {"rule_key": "r"}, "fields": {"formula": "1 +"}},
        ins("codelets", name="ok", body="pass"),
    ]
    problems = check_code_in_ops(ops, TABLES)
    assert [(p.op_index, p.field) for p in problems] == [(0, "predicate"), (1, "body"), (2, "formula")]
    assert {p.kind for p in problems} == {DOES_NOT_COMPILE}


# --- stale or conflicting (409) -----------------------------------------------


def test_stale_base_version_is_refused_only_under_strict():
    assert check_base_version(3, 3) is None
    stale = check_base_version(2, 3)
    assert stale.kind == STALE and stale.status == 409
    assert check_base_version(2, 3, "rebase") is None
    assert check_base_version("head", 3) is None
    assert check_base_version(None, 3).kind == MALFORMED


def test_a_stale_batch_is_refused_whole_and_rebase_is_not():
    v = validate(batch(ins("nodes", name="c", depth=1), base_version=2) | {"base_version": 2})
    assert not v.ok and v.status == 409 and v.problems[0].kind == STALE
    assert validate(batch(ins("nodes", name="c", depth=1), base_mode="rebase") | {"base_version": 2}).ok


def test_expect_that_differs_from_the_row_is_stale():
    op = {"op": "update", "table": "nodes", "key": {"name": "a"}, "fields": {"depth": 11}, "expect": {"depth": 99}}
    v = validate(batch(op))
    assert v.status == 409 and v.problems[0].kind == STALE and v.problems[0].op_index == 0


def test_expect_distinguishes_five_from_five_point_zero():
    st = state()
    st["nodes"][("a",)]["weight"] = 5
    op = {"op": "update", "table": "nodes", "key": {"name": "a"}, "fields": {"weight": 6}, "expect": {"weight": 5}}
    assert validate(batch(op), st).ok
    op["expect"] = {"weight": 5.0}
    assert validate(batch(op), st).problems[0].kind == STALE


def test_insert_of_an_existing_key_is_key_exists():
    v = validate(batch(ins("nodes", name="a", depth=1)))
    assert v.status == 409 and v.problems[0].kind == KEY_EXISTS
    # An insert of a key an earlier op of the same batch deleted is fine.
    again = batch({"op": "delete", "table": "links", "key": {"from_node": "a", "to_node": "b"}},
                  {"op": "delete", "table": "nodes", "key": {"name": "a"}},
                  ins("nodes", name="a", depth=1))
    assert validate(again).ok


def test_a_rekey_onto_an_existing_key_is_key_exists():
    op = {"op": "update", "table": "nodes", "key": {"name": "a"}, "fields": {"name": "b"}}
    assert validate(batch(op)).problems[0].kind == KEY_EXISTS


# --- reference to something missing (422) -------------------------------------


def test_update_or_delete_of_a_missing_key_is_unknown_reference():
    for op in (
        {"op": "update", "table": "nodes", "key": {"name": "zz"}, "fields": {"depth": 1}},
        {"op": "delete", "table": "nodes", "key": {"name": "zz"}},
    ):
        v = validate(batch(op))
        assert v.status == 422 and v.problems[0].kind == UNKNOWN_REFERENCE and v.problems[0].key == ["zz"]
    assert validate(batch({"op": "delete", "table": "nodes", "key": {"name": "zz"}, "ok_if_missing": True})).ok


def test_a_field_naming_something_missing_is_unknown_reference():
    v = validate(batch(ins("links", from_node="a", to_node="zz", kind="lateral")))
    assert v.problems[0].kind == UNKNOWN_REFERENCE and v.problems[0].field == "to_node"
    v = validate(batch(ins("links", from_node="b", to_node="a", kind="sideways")))  # vocabulary
    assert v.problems[0].kind == UNKNOWN_REFERENCE and v.problems[0].field == "kind"
    v = validate(batch(ins("rules", rule_key="r", triggers=["a", "nope"])))  # list-valued
    assert v.problems[0].kind == UNKNOWN_REFERENCE and "nope" in v.problems[0].message
    v = validate(batch(ins("links", from_node="b", to_node="a", kind="lateral", label_node="gone")))
    assert v.problems[0].field == "label_node"


def test_references_are_checked_on_the_resulting_state_so_order_is_free():
    link_first = batch(ins("links", from_node="a", to_node="c", kind="lateral"), ins("nodes", name="c", depth=1))
    assert validate(link_first).ok
    # ... and a reference the batch itself removes is dangling.
    removes = batch(ins("links", from_node="a", to_node="c", kind="lateral"), ins("nodes", name="c", depth=1),
                    {"op": "delete", "table": "nodes", "key": {"name": "c"}})
    assert validate(removes).problems[0].kind == UNKNOWN_REFERENCE


def test_a_reference_removed_by_the_cascade_is_not_dangling():
    """The resolved batch carries the cascade's deletions; the survivors point at nothing removed."""
    resolved = batch(
        {"op": "delete", "table": "links", "key": {"from_node": "a", "to_node": "b"}},
        {"op": "delete", "table": "nodes", "key": {"name": "b"}},
    )
    assert validate(resolved).ok


def test_rows_the_batch_did_not_write_are_not_blamed():
    st = state()
    st["links"][("a", "b")]["to_node"] = "long-gone"  # dangling already, e.g. left by an earlier removal
    assert validate(batch(ins("nodes", name="c", depth=1)), st).ok
    assert check_references(st, TABLES, vocabularies=VOCAB)[0].kind == UNKNOWN_REFERENCE  # whole-state check sees it


def test_a_reference_into_a_table_outside_the_configuration_cannot_resolve():
    tables = {"links": TABLES["links"]}
    st = {"links": {}}
    v = validate_batch(batch(ins("links", from_node="a", to_node="b", kind="lateral")), st, tables,
                       current_version=3, vocabularies=VOCAB)
    assert v.problems[0].kind == UNKNOWN_REFERENCE


# --- the walk: order, atomicity, skip -----------------------------------------


def test_an_update_sees_what_an_earlier_op_inserted():
    ok = batch(ins("nodes", name="c", depth=1),
               {"op": "update", "table": "nodes", "key": {"name": "c"}, "fields": {"depth": 2}, "expect": {"depth": 1}})
    v = validate(ok)
    assert v.ok and v.state["nodes"][("c",)]["depth"] == 2


def test_validation_never_modifies_the_state_it_is_given():
    st = state()
    before = copy.deepcopy(st)
    validate(batch(ins("nodes", name="c", depth=1), {"op": "delete", "table": "nodes", "key": {"name": "a"}}), st)
    assert st == before
    apply_ops_to_copy(st, TABLES, [ins("nodes", name="d", depth=1)])
    assert st == before


def test_abort_reports_the_first_failing_op():
    v = validate(batch(ins("nodes", name="c", depth=1),
                       {"op": "update", "table": "nodes", "key": {"name": "zz"}, "fields": {"depth": 1}},
                       ins("nodes", name="a", depth=1)))
    assert [p.op_index for p in v.problems] == [1]


def test_skip_applies_the_rest_and_reports_each_skipped_op_with_its_reason():
    b = batch(
        ins("nodes", name="c", depth=1),                                                        # 0 applies
        {"op": "update", "table": "nodes", "key": {"name": "zz"}, "fields": {"depth": 1}},      # 1 missing key
        {"op": "update", "table": "nodes", "key": {"name": "a"}, "fields": {"depth": 11}, "expect": {"depth": 0}},  # 2 expect
        ins("nodes", name="b", depth=1),                                                         # 3 key exists
        ins("nodes", name="bad", depth=1, predicate="1 +"),                                     # 4 does not compile
        ins("links", from_node="a", to_node="nowhere", kind="lateral"),                          # 5 missing reference
        ins("nodes", name="d", depth=4),                                                         # 6 applies
        on_op_failure="skip",
    )
    v = validate(b)
    assert v.ok
    assert [(i, p.kind) for i, p in v.skipped] == [
        (1, UNKNOWN_REFERENCE), (2, STALE), (3, KEY_EXISTS), (4, DOES_NOT_COMPILE), (5, UNKNOWN_REFERENCE),
    ]
    assert set(v.state["nodes"]) == {("a",), ("b",), ("c",), ("d",)}
    assert v.state["nodes"][("a",)]["depth"] == 10


def test_skip_follows_a_skipped_insert_to_the_op_that_needed_it():
    b = batch(ins("nodes", name="bad", depth=1, predicate="1 +"),
              ins("links", from_node="a", to_node="bad", kind="lateral"),
              on_op_failure="skip")
    v = validate(b)
    assert v.ok and [i for i, _ in v.skipped] == [0, 1]
    assert ("a", "bad") not in v.state["links"]


def test_skip_does_not_forgive_a_malformed_batch_or_a_stale_base_version():
    assert validate(batch({"op": "nope"}, on_op_failure="skip")).problems[0].kind == MALFORMED
    assert validate(batch(ins("nodes", name="c", depth=1), on_op_failure="skip") | {"base_version": 1}).problems[0].kind == STALE


# --- what is never refused (3.4(a)) -------------------------------------------


@pytest.mark.parametrize(
    "ops",
    [
        # remove a node that "looks essential", and the chain around it
        [{"op": "delete", "table": "links", "key": {"from_node": "a", "to_node": "b"}},
         {"op": "delete", "table": "nodes", "key": {"name": "a"}},
         {"op": "delete", "table": "nodes", "key": {"name": "b"}}],
        # a depth outside 0-100 (advisory only)
        [{"op": "update", "table": "nodes", "key": {"name": "a"}, "fields": {"depth": 100000}}],
        [{"op": "update", "table": "nodes", "key": {"name": "a"}, "fields": {"depth": -5}}],
        # a codelet body that posts an unknown type
        [ins("codelets", name="k", body='post_codelet("no-such-type")')],
        # a parameter with an absurd value
        [ins("params", name="p", value="-1e308", value_type="float")],
    ],
)
def test_changes_are_not_refused_for_what_they_do(ops):
    assert validate(batch(*ops), state()).ok
