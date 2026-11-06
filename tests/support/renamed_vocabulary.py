"""The Metacat Standard Configuration with every bound vocabulary row renamed to an opaque name.

``renamed(docs)`` gives each row of the enum tables the engine binds a role to (event types,
bridge types, orientations, clause types, rule types, theme types, proposal levels, posting
directions, string kinds, rule scopes, failure kinds, clamp types), each link type, and each theme
relation a name like ``v_17`` (with an underscore: the engine's display forms turn a name's
underscores into hyphens, ``top-bridge``, and the test maps ``v-17`` back to ``top-bridge``), and rewrites every place the Standard Configuration names the row:
the row itself, the columns that reference it (a posting rule's ``direction``, a link's
``link_type``, a progress focus's ``event_types``, a theme dimension's ``valid_relations``) and
the configuration data keyed by the name (the commentary sections keyed by a clamp type, an event
type, a relation or a failure kind; the ``theme_relation_labels`` parameter).

Code (codelet bodies, descriptor predicates, posting formulas) is left exactly as shipped:
it reaches the vocabulary through ``role('...')`` and so runs unchanged.  Two rows of different
tables that share a spelling in the Standard Configuration (``top`` is a bridge type and a rule
type) get different opaque names, which is why this rewrites column by column and not by text.

Keys of ``commentary_templates["rule_english"]`` (``swap``, ``change``, ``verbatim``) are the
grammar of the rule-English renderer, which the engine owns, and are not renamed.
"""

from __future__ import annotations

import copy
from typing import Any

from tests.support.configuration_cascade import Documents

#: Enum tables whose bound rows are renamed (link_types: every row, since each has a behaviour).
RENAMED_TABLES = (
    "event_types", "bridge_types", "bridge_orientations", "clause_types", "rule_types",
    "theme_types", "proposal_levels", "posting_directions", "string_kinds", "rule_scopes",
    "failure_kinds", "clamp_types", "link_types",
)


def _maps(docs: Documents) -> dict[str, dict[str, str]]:
    maps: dict[str, dict[str, str]] = {}
    n = 0
    for table in RENAMED_TABLES:
        maps[table] = {}
        for row in docs["enums.json"][table]:
            n += 1
            maps[table][row["name"]] = f"v_{n}"
    maps["theme_relations"] = {}
    for row in docs["theme_relations.json"]:
        n += 1
        maps["theme_relations"][row["name"]] = f"v_{n}"
    return maps


def _rekey(d: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    return {mapping.get(k, k): v for k, v in d.items()}


def renamed(docs: Documents) -> tuple[Documents, dict[str, str]]:
    """A renamed copy of *docs* (not mutated) and the new-to-old name map."""
    docs = copy.deepcopy(docs)
    m = _maps(docs)
    for table in RENAMED_TABLES:
        for row in docs["enums.json"][table]:
            row["name"] = m[table].get(row["name"], row["name"])
    # The frame rows name rows of other tables: a bridge type its two strings, orientation and theme
    # type, a rule type the bridge type it describes.
    for row in docs["enums.json"]["bridge_types"]:
        row["from_string_kind"] = m["string_kinds"].get(row["from_string_kind"], row["from_string_kind"])
        row["to_string_kind"] = m["string_kinds"].get(row["to_string_kind"], row["to_string_kind"])
        row["orientation"] = m["bridge_orientations"].get(row["orientation"], row["orientation"])
        row["theme_type"] = m["theme_types"].get(row["theme_type"], row["theme_type"])
    for row in docs["enums.json"]["rule_types"]:
        row["bridge_type"] = m["bridge_types"].get(row["bridge_type"], row["bridge_type"])
    for row in docs["enums.json"]["progress_focuses"]:
        row["event_types"] = [m["event_types"].get(e, e) for e in row["event_types"]]
    for row in docs["theme_relations.json"]:
        row["name"] = m["theme_relations"].get(row["name"], row["name"])
    for dim in docs["theme_dimensions.json"]["dimensions"]:
        dim["valid_relations"] = [m["theme_relations"].get(r, r) for r in dim["valid_relations"]]
    for link in docs["slipnet_links.json"]:
        link["link_type"] = m["link_types"].get(link["link_type"], link["link_type"])
    for rule in docs["posting_rules.json"]["posting_rules"]:
        rule["direction"] = m["posting_directions"].get(rule["direction"], rule["direction"])
    params = docs["engine_params.json"]
    if "theme_relation_labels" in params:
        params["theme_relation_labels"] = _rekey(params["theme_relation_labels"], m["theme_relations"])
    c = docs["commentary_templates.json"]
    reporting = c["answer_reporting"]
    docs["commentary_templates.json"]["answer_reporting"] = reporting = _rekey(reporting, m["event_types"])
    for section in ("clamp_activation", "clamp_expiry"):
        if section in reporting:
            reporting[section] = _rekey(reporting[section], m["clamp_types"])
    phrases = c["theme_phrase_templates"]

    def rekey_relations(node: Any) -> None:
        if isinstance(node, dict):
            for k in list(node):
                if k in m["theme_relations"]:
                    node[m["theme_relations"][k]] = node.pop(k)
            for v in node.values():
                rekey_relations(v)

    rekey_relations(phrases)
    c["snag_explanation"] = _rekey(c["snag_explanation"], m["failure_kinds"])
    back = {new: old for table in m.values() for old, new in table.items()}
    # The display forms (``top-bridge``) hyphenate a name's underscores.
    back.update({new.replace("_", "-"): old.replace("_", "-") for new, old in list(back.items())})
    return docs, back


def renamed_urgency_tiers(docs: Documents, tiers: dict[str, str]) -> Documents:
    """A copy of *docs* with urgency tiers renamed (``{"low": "lo", "very_low": "vl"}``) in the
    tier rows, every posting rule and codelet pattern that names one, the engine parameters that
    name one, the clamp types' backgrounds and the codelet bodies that read a tier by name (the
    change API lists those bodies as dangling, so a person edits them too)."""
    import re

    docs = copy.deepcopy(docs)
    docs["urgency_levels.json"] = {tiers.get(k, k): v for k, v in docs["urgency_levels.json"].items()}
    posting = docs["posting_rules.json"]
    for rule in posting["posting_rules"]:
        if rule.get("urgency_level") in tiers:
            rule["urgency_level"] = tiers[rule["urgency_level"]]
    for entries in posting["codelet_patterns"].values():
        for entry in entries:
            entry[1] = tiers.get(entry[1], entry[1])
    refs = {r["name"]: r["refers_to"] for r in docs["engine_param_refs.json"]} if isinstance(
        docs.get("engine_param_refs.json"), list) else docs.get("engine_param_refs.json", {})
    for name, kind in refs.items():
        value = docs["engine_params.json"].get(name)
        if kind == "urgency_level" and value in tiers:
            docs["engine_params.json"][name] = tiers[value]
    for row in docs["enums.json"]["clamp_types"]:
        if row.get("codelet_background_level") in tiers:
            row["codelet_background_level"] = tiers[row["codelet_background_level"]]
    for codelet in docs["codelet_types.json"]:
        codelet["execute_body"] = re.sub(
            r"get_urgency\('(\w+)'\)",
            lambda m: f"get_urgency('{tiers.get(m.group(1), m.group(1))}')",
            codelet["execute_body"],
        )
    return docs
