"""A throwaway pure cascade over the standard-configuration documents (EN0).

The change API's ``resolve`` (work package C14, plan 3.12.5) will cascade removals over a
configuration.  Until it lands, the reduced-configuration fixtures
(``reduced_configurations.py``) need the same thing over the seed files, so this module
does it directly, with the rules of 3.12.5 for what the seed files hold today.  It is
replaced by a call to ``resolve`` in C14 and then deleted.

A configuration here is the dict ``{file name: parsed JSON}`` of ``seed_data/*.json``
(see ``load_documents``).  Functions mutate the dict they are given and return a
``Report``; copy first (``load_documents`` returns a fresh deep copy each time).

Rules implemented (3.12.5):

* removing a node deletes every link with it as ``from_node`` or ``to_node``, and every
  link it *labels*; its layout row; its theme-dimension row; its keys in the node-keyed
  parameter maps (``intrinsic_link_lengths``, ``theme_dimension_labels``,
  ``rule_english_dimension_phrases``) and its elements in the node lists
  (``initially_clamped_slipnodes``, ``top_down_slipnodes``,
  ``answer_description_theme_types``); its entry in every posting rule's
  ``triggering_slipnodes``; its role bindings and its theme relation (EN2: the database
  deletes both with the node).  Codelet bodies and predicates that mention the name cannot
  be rewritten and are reported as ``dangling``, as are demo problems that use a removed
  letter.
* removing a codelet type deletes its posting rules, its entries in every codelet
  pattern and its element in ``initial_codelet_types``.  Bodies that post it by name are
  ``dangling``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = REPO_ROOT / "seed_data"

Documents = dict[str, Any]

#: Node-keyed maps and node lists inside ``engine_params.json``.
PARAM_NODE_MAPS = ("intrinsic_link_lengths", "theme_dimension_labels", "rule_english_dimension_phrases")
PARAM_NODE_LISTS = ("initially_clamped_slipnodes", "top_down_slipnodes")


def load_documents(seed_dir: Path = SEED_DIR) -> Documents:
    """The seed files as parsed JSON, a fresh deep copy on every call."""
    return {p.name: json.loads(p.read_text()) for p in sorted(seed_dir.glob("*.json"))}


@dataclass
class Report:
    """What a removal changed: the shape of the change API's result, kept small."""

    cascaded: list[tuple[str, str, str]] = field(default_factory=list)  # (table, key, cause)
    dangling: list[tuple[str, str, str]] = field(default_factory=list)  # left alone
    removed_nodes: list[str] = field(default_factory=list)
    removed_codelet_types: list[str] = field(default_factory=list)

    def merge(self, other: "Report") -> None:
        self.cascaded += other.cascaded
        self.dangling += other.dangling
        self.removed_nodes += other.removed_nodes
        self.removed_codelet_types += other.removed_codelet_types

    def count(self, table: str) -> int:
        return sum(1 for t, _, _ in self.cascaded if t == table)


def node_names(docs: Documents) -> list[str]:
    return [n["name"] for n in docs["slipnet_nodes.json"]]


def codelet_type_names(docs: Documents) -> list[str]:
    return [c["name"] for c in docs["codelet_types.json"]]


def link_key(link: dict[str, Any]) -> str:
    return f"{link['from_node']}->{link['to_node']}[{link.get('label_node')}]"


def remove_node(docs: Documents, name: str) -> Report:
    """Remove a node with its cascade.  Raises ``KeyError`` for a node that does not exist."""
    nodes = docs["slipnet_nodes.json"]
    if name not in node_names(docs):
        raise KeyError(name)
    cause = f"remove_node {name}"
    report = Report(removed_nodes=[name])
    report.cascaded.append(("slipnet_nodes", name, cause))
    docs["slipnet_nodes.json"] = [n for n in nodes if n["name"] != name]

    kept = []
    for link in docs["slipnet_links.json"]:
        if link["from_node"] == name or link["to_node"] == name:
            report.cascaded.append(("slipnet_links", link_key(link), f"{cause}: endpoint"))
        elif link.get("label_node") == name:
            report.cascaded.append(("slipnet_links", link_key(link), f"{cause}: label"))
        else:
            kept.append(link)
    docs["slipnet_links.json"] = kept

    positions = docs["slipnet_layout.json"].get("node_positions", {})
    if name in positions:
        del positions[name]
        report.cascaded.append(("slipnet_layout", name, cause))

    theme = docs["theme_dimensions.json"]
    rows = theme.get("dimensions", [])
    kept_rows = [r for r in rows if r["slipnet_node"] != name]
    if len(kept_rows) != len(rows):
        report.cascaded.append(("theme_dimensions", name, cause))
        theme["dimensions"] = kept_rows
    listed = theme.get("answer_description_theme_types")
    if listed and name in listed:
        theme["answer_description_theme_types"] = [x for x in listed if x != name]
        report.cascaded.append(("theme_dimensions.answer_description_theme_types", name, cause))

    roles = docs["roles.json"]
    bound = roles.get("node_roles", [])
    left = [r for r in bound if r["node_name"] != name]
    if len(left) != len(bound):
        for r in bound:
            if r["node_name"] == name:
                report.cascaded.append(("slipnet_node_roles", f"{r['role']}[{r['ordinal']}]", cause))
        roles["node_roles"] = left
    relations = docs["theme_relations.json"]
    for r in relations:
        if r.get("node_name") == name:
            report.cascaded.append(("theme_relations", r["name"], cause))
    docs["theme_relations.json"] = [r for r in relations if r.get("node_name") != name]

    params = docs["engine_params.json"]
    for key in PARAM_NODE_MAPS:
        if name in params.get(key, {}):
            del params[key][name]
            report.cascaded.append((f"engine_params.{key}", name, cause))
    for key in PARAM_NODE_LISTS:
        if name in params.get(key, []):
            params[key] = [x for x in params[key] if x != name]
            report.cascaded.append((f"engine_params.{key}", name, cause))

    for rule in docs["posting_rules.json"]["posting_rules"]:
        trig = rule.get("triggering_slipnodes")
        if trig and name in trig:
            rule["triggering_slipnodes"] = [x for x in trig if x != name]
            report.cascaded.append(("posting_rules.triggering_slipnodes", rule["codelet_type"], cause))

    for c in docs["codelet_types.json"]:
        if name in c.get("execute_body", ""):
            report.dangling.append(("codelet_types.execute_body", c["name"], f"{cause}: body names it"))
    for n in docs["slipnet_nodes.json"]:
        if name in (n.get("descriptor_predicate") or ""):
            report.dangling.append(("slipnet_nodes.descriptor_predicate", n["name"], f"{cause}: predicate names it"))
    glyph = name[len("plato-"):] if name.startswith("plato-") else None
    if glyph and len(glyph) == 1:
        for d in docs["demo_problems.json"]:
            if any(glyph in (d.get(f) or "") for f in ("initial", "modified", "target", "answer")):
                report.dangling.append(("demo_problems", d["name"], f"{cause}: uses the letter"))
    return report


def remove_codelet_type(docs: Documents, name: str) -> Report:
    """Remove a codelet type with its cascade.  Raises ``KeyError`` if it does not exist."""
    if name not in codelet_type_names(docs):
        raise KeyError(name)
    cause = f"remove_codelet_type {name}"
    report = Report(removed_codelet_types=[name])
    report.cascaded.append(("codelet_types", name, cause))
    docs["codelet_types.json"] = [c for c in docs["codelet_types.json"] if c["name"] != name]

    posting = docs["posting_rules.json"]
    kept = []
    for rule in posting["posting_rules"]:
        if rule["codelet_type"] == name:
            report.cascaded.append(("posting_rules", f"{name}/{rule['direction']}", cause))
        else:
            kept.append(rule)
    posting["posting_rules"] = kept
    for pattern, entries in posting["codelet_patterns"].items():
        left = [e for e in entries if e[0] != name]
        if len(left) != len(entries):
            report.cascaded.append(("codelet_patterns", pattern, cause))
            posting["codelet_patterns"][pattern] = left

    roles = docs["roles.json"]
    bound = roles.get("codelet_roles", [])
    for r in bound:
        if r["codelet_type"] == name:
            report.cascaded.append(("codelet_type_roles", f"{r['role']}[{r['ordinal']}]", cause))
    roles["codelet_roles"] = [r for r in bound if r["codelet_type"] != name]

    params = docs["engine_params.json"]
    if name in params.get("initial_codelet_types", []):
        params["initial_codelet_types"] = [x for x in params["initial_codelet_types"] if x != name]
        report.cascaded.append(("engine_params.initial_codelet_types", name, cause))

    for c in docs["codelet_types.json"]:
        if f'"{name}"' in c.get("execute_body", "") or f"'{name}'" in c.get("execute_body", ""):
            report.dangling.append(("codelet_types.execute_body", c["name"], f"{cause}: body posts it"))
    return report


def dangling_node_references(docs: Documents, names: list[str]) -> list[str]:
    """Where, outside code, a removed node is still named: the well-formedness check.

    Walks every key and string value of every document except the two code fields that
    cannot be rewritten (codelet bodies and descriptor predicates, which are reported as
    ``dangling`` instead) and the free text of demo problems.
    """
    gone = set(names)
    found: list[str] = []

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in gone:
                    found.append(f"{path}/{k} (key)")
                if k in ("execute_body", "descriptor_predicate"):
                    continue
                walk(v, f"{path}/{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        elif isinstance(obj, str) and obj in gone:
            found.append(f"{path} = {obj}")

    for fname, doc in docs.items():
        if fname in ("help_topics.en.json", "commentary_templates.json", "demo_problems.json"):
            continue
        walk(doc, fname)
    return found


def dangling_codelet_references(docs: Documents, names: list[str]) -> list[str]:
    gone = set(names)
    found: list[str] = []
    for rule in docs["posting_rules.json"]["posting_rules"]:
        if rule["codelet_type"] in gone:
            found.append(f"posting rule {rule['codelet_type']}")
    for pattern, entries in docs["posting_rules.json"]["codelet_patterns"].items():
        found += [f"pattern {pattern}: {e[0]}" for e in entries if e[0] in gone]
    found += [f"initial_codelet_types: {x}"
              for x in docs["engine_params.json"].get("initial_codelet_types", []) if x in gone]
    return found


def clone(docs: Documents) -> Documents:
    return copy.deepcopy(docs)
