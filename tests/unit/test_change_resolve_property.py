"""C14a: property tests of ``resolve``: random op sequences keep the document well-formed.

*Well-formed* is the cascade rules' promise (3.12.5): after any accepted batch, no reference
column names something that does not exist, no node-keyed parameter names a missing node, no
trigger names a missing node, and ``initial_codelet_types`` names no missing codelet type.
(Code that mentions a removed name is listed as ``dangling`` and not part of this.)  Also pinned:

* ``resolve`` is deterministic, and its resolved ops replay (``apply_resolved``) without a
  structural error;
* the document an accepted batch gives never has a duplicate natural key;
* a removal, rename or merge of a node that Episodic Memory names succeeds, whatever else the
  node is (a letter, a role's node, a label, a trigger, a layout cell, a dimension).
"""

from __future__ import annotations

import json
import random

import pytest

from server.services import config_document as cd
from server.services.change_resolve import ChangeRefused, resolve
from server.services.change_resolve.spec import (
    CODELET_TYPE_LIST_PARAMS,
    NODE_LIST_PARAMS,
    NODE_MAP_PARAMS,
    REFERENCES,
    ROLE_NAMES,
)
from tests.integration.equivalence_harness import SEED_DIR


@pytest.fixture(scope="module")
def base() -> cd.ConfigDocument:
    return cd.document_from_standard_files(SEED_DIR)


def dangling_references(doc: cd.ConfigDocument) -> list[str]:
    t = doc.tables
    bad: list[str] = []
    for (table, column), (target, many) in REFERENCES.items():
        for row in t[table].values():
            value = row.get(column)
            if value in (None, ""):
                continue
            for item in value if many else [value]:
                if target.startswith("role."):
                    ok = item in ROLE_NAMES[target.split(".", 1)[1]]
                else:
                    ok = (item,) in t[target]
                if not ok:
                    bad.append(f"{table}.{column} -> {item!r}")
    nodes = t["slipnet_node_defs"]
    for p in NODE_LIST_PARAMS:
        if (p,) in t["engine_params"]:
            bad += [f"{p} -> {x!r}" for x in json.loads(t["engine_params"][(p,)]["value"]) if (x,) not in nodes]
    for p in NODE_MAP_PARAMS:
        if (p,) in t["engine_params"]:
            bad += [f"{p} -> {x!r}" for x in json.loads(t["engine_params"][(p,)]["value"]) if (x,) not in nodes]
    for p in CODELET_TYPE_LIST_PARAMS:
        if (p,) in t["engine_params"]:
            bad += [f"{p} -> {x!r}" for x in json.loads(t["engine_params"][(p,)]["value"]) if (x,) not in t["codelet_type_defs"]]
    return bad


def test_the_standard_configuration_is_well_formed(base):
    assert dangling_references(base) == []


class Gen:
    """Random batches over the current document: mostly valid, sometimes naming a missing thing."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.fresh = 0

    def name(self, prefix: str) -> str:
        self.fresh += 1
        return f"{prefix}-{self.fresh}"

    def pick(self, doc, table, miss=0.05):
        keys = list(doc.tables[table])
        if not keys or self.rng.random() < miss:
            return "no-such"
        return self.rng.choice(keys)[0]

    def op(self, doc: cd.ConfigDocument) -> dict:
        r = self.rng
        t = doc.tables
        kind = r.choice([
            "remove_node", "remove_node", "rename_node", "merge_nodes", "add_node", "add_node",
            "remove_codelet_type", "rename_codelet", "delete_level", "rename_level",
            "remove_link", "add_link", "remove_posting_rule", "add_posting_rule", "add_trigger",
            "remove_trigger", "rebind_role", "unbind_role", "reorder", "list_op", "adjust",
            "delete_param", "move_layout", "add_codelet_type", "delete_layout", "delete_theme_relation",
        ])
        if kind == "remove_node":
            return {"op": "remove_node", "name": self.pick(doc, "slipnet_node_defs"),
                    **({"splice": [self.pick(doc, "slipnet_node_defs")]} if r.random() < 0.2 else {})}
        if kind == "rename_node":
            return {"op": "rename_node", "old": self.pick(doc, "slipnet_node_defs"), "new": self.name("n")}
        if kind == "merge_nodes":
            return {"op": "merge_nodes", "keep": self.pick(doc, "slipnet_node_defs"), "drop": self.pick(doc, "slipnet_node_defs")}
        if kind == "add_node":
            new = self.name("n")
            op = {"op": "add_node", "name": new, "fields": {"short_name": "q", "conceptual_depth": r.randint(0, 100)},
                  "links": [{"to": self.pick(doc, "slipnet_node_defs"), "type": "lateral",
                             **({"label": self.pick(doc, "slipnet_node_defs")} if r.random() < 0.3 else {})}
                            for _ in range(r.randint(0, 3))],
                  "params": {}}
            if r.random() < 0.5:
                op["params"]["top_down_slipnodes"] = True
            if r.random() < 0.5:
                op["params"]["intrinsic_link_lengths"] = r.randint(1, 90)
            if r.random() < 0.5:
                op["layout"] = {"grid_row": r.randint(0, 5), "grid_col": r.randint(0, 5)}
            if r.random() < 0.3:
                op["roles"] = [r.choice(["rule.dimension_order", "answer.description_dimension", "position.single"])]
            return op
        if kind == "remove_codelet_type":
            return {"op": "remove_codelet_type", "name": self.pick(doc, "codelet_type_defs")}
        if kind == "rename_codelet":
            return {"op": "update", "table": "codelet_type_defs", "key": {"name": self.pick(doc, "codelet_type_defs")},
                    "fields": {"name": self.name("c")}}
        if kind == "delete_level":
            return {"op": "delete", "table": "urgency_levels", "key": {"name": self.pick(doc, "urgency_levels")}}
        if kind == "rename_level":
            return {"op": "update", "table": "urgency_levels", "key": {"name": self.pick(doc, "urgency_levels")},
                    "fields": {"name": self.name("lv")}}
        if kind == "remove_link":
            keys = list(t["slipnet_link_defs"])
            if not keys:
                return {"op": "remove_link", "key": {"from_node": "a", "to_node": "b", "link_type": "lateral", "label_node": ""}}
            k = r.choice(keys)
            return {"op": "remove_link", "key": dict(zip(("from_node", "to_node", "link_type", "label_node"), k))}
        if kind == "add_link":
            return {"op": "add_link", "from": self.pick(doc, "slipnet_node_defs"), "to": self.pick(doc, "slipnet_node_defs"),
                    "type": "lateral"}
        if kind == "remove_posting_rule":
            return {"op": "remove_posting_rule", "rule_key": self.pick(doc, "posting_rules")}
        if kind == "add_posting_rule":
            direction = next(iter(t["posting_directions"]))[0]
            return {"op": "add_posting_rule", "rule_key": self.name("rule"),
                    "fields": {"codelet_type": self.pick(doc, "codelet_type_defs"), "direction": direction,
                               "triggering_slipnodes": [self.pick(doc, "slipnet_node_defs") for _ in range(2)]}}
        if kind in ("add_trigger", "remove_trigger"):
            return {"op": kind, "rule_key": self.pick(doc, "posting_rules"), "node": self.pick(doc, "slipnet_node_defs")}
        if kind == "rebind_role":
            role = r.choice(sorted(ROLE_NAMES["node"]))
            return {"op": "rebind_role", "role": role, "node": self.pick(doc, "slipnet_node_defs")}
        if kind == "unbind_role":
            return {"op": "unbind_role", "role": r.choice(sorted(ROLE_NAMES["node"])), "ok_if_missing": True}
        if kind == "reorder":
            table = r.choice(["slipnet_node_defs", "slipnet_link_defs", "codelet_type_defs", "posting_rules"])
            keys = list(t[table])
            if not keys:
                return {"op": "reorder", "table": table, "key": {"name": "x"}}
            from server.services.config_registry import REGISTRY
            key = dict(zip(REGISTRY[table].key, r.choice(keys)))
            op = {"op": "reorder", "table": table, "key": key}
            if r.random() < 0.6:
                op["before"] = dict(zip(REGISTRY[table].key, r.choice(keys)))
            return op
        if kind == "list_op":
            return {"op": r.choice(["list_add", "list_remove"]), "table": "engine_params",
                    "key": {"name": r.choice(NODE_LIST_PARAMS)}, "field": "value",
                    "value": self.pick(doc, "slipnet_node_defs", miss=0.0)}
        if kind == "adjust":
            return {"op": "adjust_param", "name": "update_cycle_length", "by": r.randint(-3, 3)}
        if kind == "delete_param":
            return {"op": "delete", "table": "engine_params", "key": {"name": self.pick(doc, "engine_params")}}
        if kind == "move_layout":
            return {"op": "move_layout", "node": self.pick(doc, "slipnet_node_defs"), "x": r.randint(0, 9), "y": r.randint(0, 9)}
        if kind == "add_codelet_type":
            return {"op": "add_codelet_type", "name": self.name("c"),
                    "fields": {"family": next(iter(t["codelet_families"]))[0], "phase": next(iter(t["codelet_phases"]))[0]}}
        if kind == "delete_layout":
            return {"op": "delete", "table": "slipnet_layout", "key": {"node_name": self.pick(doc, "slipnet_layout")}}
        return {"op": "delete", "table": "theme_relations", "key": {"name": self.pick(doc, "theme_relations")}}


@pytest.mark.parametrize("seed", range(40))
def test_random_op_sequences_keep_the_document_well_formed(base, seed):
    rng = random.Random(seed)
    gen = Gen(rng)
    doc = base
    accepted = refused = 0
    for _ in range(25):
        batch = {"ops": [gen.op(doc) for _ in range(rng.randint(1, 4))],
                 "on_op_failure": rng.choice(["abort", "skip"])}
        try:
            ops, report = resolve(doc, batch)
        except ChangeRefused as exc:
            refused += 1
            assert exc.status in (400, 409, 422)
            continue
        accepted += 1
        again = resolve(doc, batch)
        assert again == (ops, report)  # deterministic
        new = cd.apply_resolved(doc, ops)  # replays without a structural error
        assert dangling_references(new) == [], (seed, batch)
        for name, rows in new.tables.items():
            assert len(rows) == len(set(rows)), name
        applied_ops = [a["op"] for a in report["applied"]]
        assert applied_ops == ops
        doc = new
    assert accepted > 0


@pytest.mark.parametrize("seed", range(8))
def test_a_single_op_at_a_time_gives_the_same_document_as_the_batch(base, seed):
    rng = random.Random(1000 + seed)
    gen = Gen(rng)
    doc = base
    for _ in range(10):
        ops = [gen.op(doc)]
        try:
            resolved, _ = resolve(doc, {"ops": ops})
        except ChangeRefused:
            continue
        doc = cd.apply_resolved(doc, resolved)
    # the whole sequence as one batch needs every op valid in turn: replay what was accepted
    # and check the document equals the sequential one.
    rng = random.Random(1000 + seed)
    gen = Gen(rng)
    doc2, accepted = base, []
    for _ in range(10):
        op = gen.op(doc2)
        try:
            resolved, _ = resolve(doc2, {"ops": [op]})
        except ChangeRefused:
            continue
        accepted.append(op)
        doc2 = cd.apply_resolved(doc2, resolved)
    whole, _ = resolve(base, {"ops": accepted})
    assert cd.apply_resolved(base, whole).content_equals(doc2)


def _memory_named_nodes(doc):
    """The kinds of node a Training Mode Session's Episodic Memory can name: letters, nodes
    bound to a role, relation (label) nodes, dimensions, nodes with triggers, a layout cell."""
    t = doc.tables
    kinds = {
        "a letter": next(r["name"] for r in t["slipnet_node_defs"].values() if r.get("glyph")),
        "a number": next(r["name"] for r in t["slipnet_node_defs"].values() if r.get("numeric_value") is not None),
        "a role's node": next(r["node_name"] for r in t["slipnet_node_roles"].values() if r["role"] == "dimension.length"),
        "a label node": next(r["label_node"] for r in t["slipnet_link_defs"].values() if r.get("label_node")),
        "a dimension": next(iter(t["theme_dimension_defs"].values()))["slipnet_node"],
        "a triggering node": next(x for r in t["posting_rules"].values() for x in (r["triggering_slipnodes"] or [])),
        "a relation's node": next(r["node_name"] for r in t["theme_relations"].values() if r.get("node_name")),
    }
    return kinds


@pytest.mark.parametrize("kind", ["a letter", "a number", "a role's node", "a label node", "a dimension",
                                  "a triggering node", "a relation's node"])
def test_a_node_that_memory_names_can_be_removed_renamed_or_merged(base, kind):
    name = _memory_named_nodes(base)[kind]
    other = next(k[0] for k in base.tables["slipnet_node_defs"] if k[0] != name)
    for batch in (
        [{"op": "remove_node", "name": name}],
        [{"op": "rename_node", "old": name, "new": "learned-concept"}],
        [{"op": "merge_nodes", "keep": other, "drop": name}],
        [{"op": "merge_nodes", "keep": name, "drop": other}],
        [{"op": "delete", "table": "slipnet_node_defs", "key": {"name": name}}],
        [{"op": "update", "table": "slipnet_node_defs", "key": {"name": name}, "fields": {"name": "learned-concept"}}],
    ):
        for source in ("admin", "external", "learner"):
            ops, report = resolve(base, {"ops": batch, "source": source, "actor": "x"})
            assert report["ok"] and ops
            assert dangling_references(cd.apply_resolved(base, ops)) == []


def test_every_source_gets_the_same_ops(base):
    batch = [{"op": "remove_node", "name": "plato-successor"}]
    results = [resolve(base, {"ops": batch, "source": s, "actor": "a", "note": "n"})
               for s in ("admin", "external", "learner", "restore", "import")]
    assert all(r == results[0] for r in results)


def test_rebase_and_strict_resolve_the_same_ops(base):
    batch = [{"op": "adjust_param", "name": "update_cycle_length", "by": 2}]
    assert resolve(base, {"ops": batch, "base_mode": "rebase", "base_version": "head"}) == \
        resolve(base, {"ops": batch, "base_mode": "strict", "base_version": 7})
