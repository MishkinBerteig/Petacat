"""S0: ``ConfigDocument`` and its pure functions (no database).

The document is built from the Metacat Standard Configuration files.  What is pinned here:

* the provider and the hash a document gives equal the ones the files give (identity);
* order is kept, and a table with order columns stays sorted by them;
* the codecs round trip, ``int`` and ``float`` keep their types and rationals stay exact;
* ``apply_resolved`` agrees with a naive reference model on random op sequences (the replay
  property), touches only the tables the ops name, and shares the rest by reference;
* the incremental hash equals the whole-document hash, and untouched provider fields are
  shared with the previous version;
* ``diff`` then ``apply_resolved`` gives the target.
"""

from __future__ import annotations

import copy
import json
import random
from fractions import Fraction

import pytest

from server.engine import hashing
from server.engine.metadata import MetadataProvider
from server.services import config_document as cd
from server.services.metadata_service import PROVIDER_FIELD_TABLES, provider_from_tables
from tests.integration.equivalence_harness import SEED_DIR, provider_differences, seed_provider


@pytest.fixture(scope="module")
def base() -> cd.ConfigDocument:
    return cd.document_from_standard_files(SEED_DIR)


@pytest.fixture(scope="module")
def reference() -> MetadataProvider:
    return seed_provider()


def fresh(doc: cd.ConfigDocument) -> cd.ConfigDocument:
    """The same content as *doc* with no cache at all (through the JSON codec)."""
    return cd.from_json(cd.to_json(doc))


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_provider_from_files_document_equals_the_files_provider(base, reference):
    assert provider_differences(reference, cd.provider(base)) == {}


def test_config_hash_equals_the_engine_hash_of_the_provider(base, reference):
    assert cd.config_hash(base) == hashing.config_hash(cd.provider(base))
    assert cd.config_hash(base) == hashing.config_hash(reference)


def test_every_provider_field_is_fed_by_known_tables_and_every_table_feeds_a_field():
    fed = {t for tables in PROVIDER_FIELD_TABLES.values() for t in tables}
    assert fed == set(cd.TABLE_NAMES)
    assert set(PROVIDER_FIELD_TABLES) == {f.name for f in __import__("dataclasses").fields(MetadataProvider)}


def test_hashed_fields_are_the_engines(reference):
    assert list(cd.HASHED_FIELDS) == hashing.hashed_field_names(reference)


def test_tables_registry_keys_agree_when_the_registry_exists():
    registry = pytest.importorskip("server.services.config_registry")
    for name, spec in registry.REGISTRY.items():
        if name in cd.TABLE_NAMES:
            assert tuple(spec.key) == cd.key_columns(name), name


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


def test_node_link_codelet_param_and_rule_order_are_the_files_order(base):
    def names(path):
        with open(f"{SEED_DIR}/{path}") as f:
            return json.load(f)

    assert [k[0] for k in base.tables["slipnet_node_defs"]] == [n["name"] for n in names("slipnet_nodes.json")]
    assert [k[0] for k in base.tables["codelet_type_defs"]] == [n["name"] for n in names("codelet_types.json")]
    assert [k[0] for k in base.tables["engine_params"]] == list(names("engine_params.json"))
    assert [r["rule_key"] for r in base.tables["posting_rules"].values()] == [
        r.get("rule_key", r["codelet_type"]) for r in names("posting_rules.json")["posting_rules"]
    ]
    links = [(l["from_node"], l["to_node"], l["link_type"], l.get("label_node") or "") for l in names("slipnet_links.json")]
    assert list(base.tables["slipnet_link_defs"]) == links


def test_an_insert_into_an_ordered_table_lands_by_its_order_column(base):
    first = next(iter(base.tables["slipnet_node_defs"].values()))
    row = {**first, "name": "new-node", "sort_order": 3}
    new = cd.apply_resolved(base, [{"op": "insert", "table": "slipnet_node_defs", "key": {"name": "new-node"}, "row": row}])
    order = [r["sort_order"] for r in new.tables["slipnet_node_defs"].values()]
    assert order == sorted(order)
    keys = [k[0] for k in new.tables["slipnet_node_defs"]]
    assert keys.index("new-node") == 4  # sort_orders 0, 1, 2, 3 are before it; its tie goes after
    assert [k for k in keys if k != "new-node"] == [k[0] for k in base.tables["slipnet_node_defs"]]


def test_updating_an_order_column_moves_the_row(base):
    keys = [k[0] for k in base.tables["engine_params"]]
    new = cd.apply_resolved(
        base, [{"op": "update", "table": "engine_params", "key": {"name": keys[0]}, "set": {"sort_order": 10_000}}]
    )
    assert [k[0] for k in new.tables["engine_params"]] == keys[1:] + [keys[0]]
    assert list(cd.provider(new).params) == keys[1:] + [keys[0]]


def test_an_unordered_table_appends_in_insertion_order(base):
    ops = [
        {"op": "insert", "table": "theme_dimension_defs", "key": {"slipnet_node": f"n{i}"},
         "row": {"slipnet_node": f"n{i}", "valid_relations": ["a"]}}
        for i in (3, 1, 2)
    ]
    new = cd.apply_resolved(base, ops)
    assert [k[0] for k in new.tables["theme_dimension_defs"]][-3:] == ["n3", "n1", "n2"]


def test_a_null_link_label_is_read_as_empty_in_the_key(base):
    link = next(r for r in base.tables["slipnet_link_defs"].values() if r["label_node"] is None)
    key = {"from_node": link["from_node"], "to_node": link["to_node"], "link_type": link["link_type"], "label_node": ""}
    new = cd.apply_resolved(base, [{"op": "delete", "table": "slipnet_link_defs", "key": key}])
    assert len(new.tables["slipnet_link_defs"]) == len(base.tables["slipnet_link_defs"]) - 1


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_apply_resolved_shares_untouched_tables_and_does_not_change_the_input(base):
    before = cd.to_json(base)
    op = {"op": "update", "table": "urgency_levels", "key": {"name": "high"}, "set": {"value": 99}}
    new = cd.apply_resolved(base, [op])
    assert cd.to_json(base) == before
    for t in cd.TABLE_NAMES:
        assert (new.tables[t] is base.tables[t]) == (t != "urgency_levels"), t
    assert new.version == base.version + 1
    assert cd.provider(new).urgency_levels["high"] == 99
    assert cd.provider(base).urgency_levels["high"] != 99


def test_apply_with_no_ops_changes_nothing_and_keeps_the_version(base):
    new = cd.apply_resolved(base, [])
    assert new.version == base.version and new.content_equals(base)
    assert cd.apply_resolved(base, [], version=7).version == 7


@pytest.mark.parametrize(
    "op",
    [
        {"op": "insert", "table": "urgency_levels", "key": {"name": "high"}, "row": {"name": "high", "value": 1, "sort_order": 0}},
        {"op": "delete", "table": "urgency_levels", "key": {"name": "nope"}},
        {"op": "update", "table": "urgency_levels", "key": {"name": "nope"}, "set": {"value": 1}},
        {"op": "delete", "table": "no_such_table", "key": {"name": "x"}},
        {"op": "frobnicate", "table": "urgency_levels", "key": {"name": "high"}},
    ],
)
def test_ops_that_cannot_be_applied_raise(base, op):
    with pytest.raises(cd.ConfigDocumentError):
        cd.apply_resolved(base, [op])


def test_rekeying_update_keeps_the_rows_place(base):
    keys = [k[0] for k in base.tables["urgency_levels"]]
    new = cd.apply_resolved(
        base, [{"op": "update", "table": "urgency_levels", "key": {"name": keys[1]}, "set": {"name": "renamed"}}]
    )
    assert [k[0] for k in new.tables["urgency_levels"]] == [keys[0], "renamed", *keys[2:]]


# ---------------------------------------------------------------------------
# Codecs
# ---------------------------------------------------------------------------


def test_json_round_trip_is_content_equal_with_the_same_provider_and_hash(base):
    again = cd.from_json(cd.to_json(base))
    assert again.content_equals(base)
    assert cd.config_hash(again) == cd.config_hash(base)
    assert provider_differences(cd.provider(base), cd.provider(again)) == {}
    assert cd.from_data(cd.to_data(base)).content_equals(base)


def test_codec_keeps_int_float_and_exact_rationals():
    rows = cd.to_data(cd.document_from_standard_files(SEED_DIR))["tables"]
    rows["formula_coefficients"] = [
        {"name": "a", "sort_order": 0, "value": "5", "value_type": "int"},
        {"name": "b", "sort_order": 1, "value": "5.0", "value_type": "float"},
        {"name": "c", "sort_order": 2, "value": "2/3", "value_type": "rational"},
    ]
    rows["engine_params"] = [
        {"name": "i", "sort_order": 0, "value": "3", "value_type": "int"},
        {"name": "f", "sort_order": 1, "value": "3.0", "value_type": "float"},
        {"name": "t", "sort_order": 2, "value": "true", "value_type": "bool"},
    ]
    doc = cd.from_json(json.dumps({"version": 4, "tables": rows}))
    meta = cd.provider(doc)
    coeffs = meta.formula_coefficients
    assert [type(v) for v in coeffs.values()] == [int, float, Fraction] and coeffs["c"] == Fraction(2, 3)
    assert [type(v) for v in meta.params.values()] == [int, float, bool]
    again = cd.from_json(cd.to_json(doc))
    assert again.version == 4 and again.content_equals(doc)
    assert [type(v) for v in cd.provider(again).formula_coefficients.values()] == [int, float, Fraction]


def test_row_values_keep_json_number_types_through_the_codec(base):
    ops = [{"op": "update", "table": "posting_rules", "key": {"rule_key": next(iter(base.tables["posting_rules"]))[0]},
            "set": {"count_values": {"x": 1, "y": 1.0, "z": 0.5}}}]
    doc = cd.apply_resolved(base, ops)
    again = cd.from_json(cd.to_json(doc))
    values = next(iter(again.tables["posting_rules"].values()))["count_values"]
    assert [type(v) for v in values.values()] == [int, float, float]


def test_from_rows_rejects_unknown_tables_and_duplicate_keys():
    with pytest.raises(cd.ConfigDocumentError):
        cd.from_rows({"help_topics": []})
    with pytest.raises(cd.ConfigDocumentError):
        cd.from_rows({"urgency_levels": [{"name": "a", "value": 1, "sort_order": 0}, {"name": "a", "value": 2, "sort_order": 1}]})


# ---------------------------------------------------------------------------
# Random ops: a naive reference model, replay, incremental hash, diff
# ---------------------------------------------------------------------------

_RANDOM_TABLES = ("engine_params", "slipnet_link_defs", "theme_dimension_defs", "codelet_pattern_defs", "slipnet_node_roles", "urgency_levels")


class Reference:
    """A naive model of a document: a list of rows per table, ops applied by linear search."""

    def __init__(self, doc: cd.ConfigDocument):
        self.rows = {t: [dict(r) for r in doc.tables[t].values()] for t in cd.TABLE_NAMES}

    def key(self, table, row):
        return tuple("" if row.get(c) is None else row[c] for c in cd.key_columns(table))

    def apply(self, op):
        t, rows = op["table"], self.rows[op["table"]]
        order = cd.order_columns(t)
        if op["op"] == "insert":
            rows.append(dict(op["row"]))
        else:
            i = next(i for i, r in enumerate(rows) if self.key(t, r) == self.key(t, op["key"]))
            if op["op"] == "delete":
                del rows[i]
            else:
                rows[i] = {**rows[i], **op["set"]}
        if order:
            rows.sort(key=lambda r: tuple(r[c] for c in order))


def random_ops(doc: cd.ConfigDocument, rng: random.Random, n: int) -> list[dict]:
    """*n* valid resolved ops against a document (tracking the rows as they change)."""
    ref = Reference(doc)
    ops: list[dict] = []
    for _ in range(n):
        table = rng.choice(_RANDOM_TABLES)
        rows = ref.rows[table]
        kind = rng.choice(("insert", "insert", "update", "update", "delete")) if rows else "insert"
        counter = rng.getrandbits(40)
        if kind == "insert":
            row = copy.deepcopy(rng.choice(rows)) if rows else {}
            row = _fresh_row(table, row, counter, rng, rows)
            op = {"op": "insert", "table": table, "key": dict(zip(cd.key_columns(table), ref.key(table, row))), "row": row}
        else:
            target = rng.choice(rows)
            key = dict(zip(cd.key_columns(table), ref.key(table, target)))
            if kind == "delete":
                op = {"op": "delete", "table": table, "key": key}
            else:
                op = {"op": "update", "table": table, "key": key, "set": _changes(table, target, rng)}
        ref.apply(op)
        ops.append(op)
    return ops


def _fresh_row(table, template, counter, rng, rows):
    row = dict(template)
    order = cd.order_columns(table)
    for c in cd.key_columns(table):
        if c == "ordinal":
            row[c] = counter
        elif c == "label_node":
            row[c] = rng.choice([None, f"lab{counter}"])
        elif isinstance(row.get(c), str) or c not in row:
            row[c] = f"{c}{counter}"
    if table == "engine_params":
        row.update(value=str(counter), value_type="int")
    if table == "urgency_levels":
        row.update(value=counter)
    if "sort_order" in order:
        row["sort_order"] = rng.randrange(0, 400)
    if "ordinal" in order:
        row["ordinal"] = rng.randrange(0, 400)
    if table == "theme_dimension_defs":
        row["valid_relations"] = [f"r{counter}"]
    if table in ("slipnet_node_roles", "codelet_type_roles"):
        row["role"] = f"role{counter % 5}"
        row["ordinal"] = counter
    return row


def _changes(table, row, rng):
    options = {
        "engine_params": ({"value": str(rng.randrange(100)), "value_type": "int"}, {"sort_order": rng.randrange(400)}),
        "slipnet_link_defs": ({"link_length": rng.randrange(100)}, {"sort_order": rng.randrange(400)}, {"fixed_length": rng.random() < 0.5}),
        "theme_dimension_defs": ({"valid_relations": ["x", str(rng.randrange(9))]},),
        "codelet_pattern_defs": ({"urgency_level": "high"}, {"ordinal": rng.randrange(500)}),
        "slipnet_node_roles": ({"node_name": f"node{rng.randrange(9)}"},),
        "urgency_levels": ({"value": rng.randrange(100)}, {"sort_order": rng.randrange(400)}),
    }[table]
    return rng.choice(options)


@pytest.mark.parametrize("seed", range(12))
def test_replay_equals_direct_construction(base, seed):
    rng = random.Random(seed)
    ops = random_ops(base, rng, 40)
    ref = Reference(base)
    for op in ops:
        ref.apply(op)
    direct = cd.from_rows(ref.rows)
    one_batch = cd.apply_resolved(base, ops)
    one_by_one = base
    for op in ops:
        one_by_one = cd.apply_resolved(one_by_one, [op])
    assert one_batch.content_equals(direct)
    assert one_by_one.content_equals(direct)
    assert one_by_one.version == base.version + len(ops)


@pytest.mark.parametrize("seed", range(12))
def test_incremental_hash_equals_whole_document_hash(base, seed):
    rng = random.Random(1000 + seed)
    doc = cd.from_json(cd.to_json(base))
    cd.config_hash(doc)  # warm the digests
    for _ in range(6):
        previous = doc
        doc = cd.apply_resolved(doc, random_ops(doc, rng, rng.randrange(1, 6)))
        incremental = cd.config_hash(doc, previous)
        whole = hashing.config_hash(provider_from_tables(fresh(doc).tables))
        assert incremental == whole
        assert cd.config_hash(fresh(doc)) == whole


def test_unchanged_fields_are_shared_with_the_previous_version(base):
    doc = cd.from_json(cd.to_json(base))
    before = cd.provider(doc)
    cd.config_hash(doc)
    new = cd.apply_resolved(doc, [{"op": "update", "table": "engine_params", "key": {"name": next(iter(doc.tables["engine_params"]))[0]},
                                   "set": {"value": "123", "value_type": "int"}}])
    after = cd.provider(new, doc)
    for f in PROVIDER_FIELD_TABLES:
        assert (getattr(after, f) is getattr(before, f)) == (f != "params"), f
    assert new.digests.keys() == {f for f in doc.digests if f != "params"}
    assert after is not before


def test_provider_previous_shares_fields_when_the_new_document_was_not_made_by_apply(base):
    a = cd.from_json(cd.to_json(base))
    b = cd.from_json(cd.to_json(a))  # equal content, different table objects: nothing is shared
    pa, pb = cd.provider(a), cd.provider(b, a)
    assert pa.params is not pb.params
    c = cd.apply_resolved(a, [])  # tables are the same objects
    assert cd.provider(c, a).params is pa.params


@pytest.mark.parametrize("seed", range(12))
def test_diff_then_apply_gives_the_target(base, seed):
    rng = random.Random(2000 + seed)
    a = cd.apply_resolved(base, random_ops(base, rng, 15))
    b = cd.apply_resolved(a, random_ops(a, rng, 25))
    ops = cd.diff(a, b)
    assert cd.apply_resolved(a, ops).content_equals(b)
    assert cd.config_hash(cd.apply_resolved(a, ops)) == cd.config_hash(b)
    assert cd.diff(a, b) == ops


def test_diff_of_equal_documents_is_empty(base):
    assert cd.diff(base, base) == []
    assert cd.diff(base, fresh(base)) == []


def test_diff_reproduces_a_reordering_of_an_unordered_table(base):
    rows = cd.to_data(base)["tables"]
    rows["theme_dimension_defs"] = list(reversed(rows["theme_dimension_defs"]))
    b = cd.from_rows(rows)
    ops = cd.diff(base, b)
    assert ops and {o["table"] for o in ops} == {"theme_dimension_defs"}
    assert cd.apply_resolved(base, ops).content_equals(b)


def test_diff_sets_only_the_changed_columns(base):
    key = next(iter(base.tables["urgency_levels"]))
    new = cd.apply_resolved(base, [{"op": "update", "table": "urgency_levels", "key": {"name": key[0]}, "set": {"value": 12345}}])
    assert cd.diff(base, new) == [{"op": "update", "table": "urgency_levels", "key": {"name": key[0]}, "set": {"value": 12345}}]
