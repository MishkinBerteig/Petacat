"""The Metacat Standard Configuration with its role-bound, letter and number nodes renamed to
opaque names (plan 4.2, "Rename invariance").

``renamed(docs)`` gives every node that plays a role, is a relation, is a letter (has a
``glyph``) or is a number (has a ``numeric_value``) a name like ``n17`` and rewrites every
document that names it: node rows, links, role bindings, relation rows, layouts, parameter
maps, posting rules, and the names spelled inside code strings (codelet bodies and
descriptor predicates; a rename does not rewrite code in the change API, the test does
so that only the engine's own reading of names is tested).  The display columns
(``plain_name``, ``full_name``, ``cm_short_name``, ``short_name``) keep the old text.
"""

from __future__ import annotations

import re
from typing import Any

from tests.support.configuration_cascade import Documents

#: Keys whose text is prose, never a node name.
PROSE_KEYS = {"description", "plain_name", "full_name", "cm_short_name", "short_name", "text"}


def _renamed_names(docs: Documents) -> dict[str, str]:
    chosen: set[str] = set()
    for row in docs["roles.json"]["node_roles"]:
        chosen.add(row["node_name"])
    for row in docs["theme_relations.json"]:
        if row.get("node_name"):
            chosen.add(row["node_name"])
    for node in docs["slipnet_nodes.json"]:
        if node.get("glyph") is not None or node.get("numeric_value") is not None:
            chosen.add(node["name"])
    order = [n["name"] for n in docs["slipnet_nodes.json"]]
    return {name: f"n{order.index(name)}" for name in order if name in chosen}


#: Code that builds a node name from data cannot be rewritten by a rename.  The one such
#: line in the Metacat Standard Configuration is in the ``rule-scout`` body (the verbatim
#: rule's letters, ``get_node('plato-' + ch)``); a renamed copy reads the same letters
#: through the alphabet.  The body itself is the configuration's, not the engine's.
CODE_PATCHES = {
    "rule-scout": (
        "get_node('plato-' + ch)",
        "slipnet.alphabet.glyph_nodes.get(ch)",
    ),
}


def renamed(docs: Documents) -> tuple[Documents, dict[str, str]]:
    """A renamed copy of *docs* (not mutated) and the old-to-new name map."""
    import copy

    docs = copy.deepcopy(docs)
    mapping = _renamed_names(docs)
    pattern = re.compile(
        "(?<![A-Za-z0-9_-])(" + "|".join(re.escape(n) for n in sorted(mapping, key=len, reverse=True))
        + ")(?![A-Za-z0-9_-])"
    )

    def sub(text: str) -> str:
        return pattern.sub(lambda m: mapping[m.group(1)], text)

    def walk(value: Any, key: str | None = None) -> Any:
        if isinstance(value, dict):
            return {
                (sub(k) if isinstance(k, str) else k): walk(v, k if isinstance(k, str) else None)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if isinstance(value, str) and key not in PROSE_KEYS:
            return sub(value)
        return value

    for row in docs["codelet_types.json"]:
        patch = CODE_PATCHES.get(row["name"])
        if patch:
            assert patch[0] in row["execute_body"]
            row["execute_body"] = row["execute_body"].replace(*patch)

    out: Documents = {}
    for fname, doc in docs.items():
        if fname in ("demo_problems.json", "help_topics.en.json", "enums.json"):
            out[fname] = doc
        else:
            out[fname] = walk(doc)
    return out, mapping
