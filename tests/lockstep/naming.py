"""Canonical names (spec §4) for everything a decision can be about.

``name_of(thing)`` never raises: a thing it cannot name becomes
``?<kind>:<repr>`` so it shows up in a report instead of crashing a run.  Names are
built from fields both engines have; a slipnet node is its name without ``plato-``.

Imports of engine classes are lazy so this module can be imported before the engine
is (and so that merely naming a plain value costs no import).
"""

from __future__ import annotations

from typing import Any

#: ``string_type`` -> role letter (DECISIONS.md: ``i`` initial, ``m`` modified,
#: ``t`` target, ``a`` answer).
ROLES = {"initial": "i", "modified": "m", "target": "t", "answer": "a"}


def number_name(x: float | int) -> str:
    """Numbers by value in shortest form: ``3``, ``0.5``; an integral float is ``3``."""
    if isinstance(x, float):
        if x != x or x in (float("inf"), float("-inf")):
            return repr(x)
        if x.is_integer():
            return str(int(x))
        return repr(x)
    return str(x)


def node_name(node: Any) -> str:
    """A slipnet node's name without ``plato-``; ``-`` for no node."""
    if node is None:
        return "-"
    name = getattr(node, "name", None)
    if name is None:
        return name_of(node)
    return str(name).removeprefix("plato-")


def _opt(x: Any) -> str:
    """A node, or a plain symbol, or nothing -> ``-``."""
    if x is None:
        return "-"
    if isinstance(x, str):
        return x.removeprefix("plato-")
    return node_name(x)


def string_name(s: Any) -> str:
    return f"string({ROLES.get(s.string_type, s.string_type)})"


def letter_name(o: Any) -> str:
    role = ROLES.get(o.string.string_type, o.string.string_type) if o.string else "?"
    return f"{role}.{o.left_string_pos}"


def group_name(g: Any) -> str:
    role = ROLES.get(g.string.string_type, g.string.string_type) if g.string else "?"
    return (
        f"group({role}.{g.left_string_pos}-{g.right_string_pos},"
        f"{_opt(g.group_category)},{_opt(g.direction)},{_opt(g.bond_facet)})"
    )


def object_name(o: Any) -> str:
    """A letter or a group (or, for an extrinsic reference, a string)."""
    from server.engine.groups import Group
    from server.engine.workspace import WorkspaceString

    if isinstance(o, WorkspaceString):
        return string_name(o)
    if isinstance(o, Group):
        return group_name(o)
    return letter_name(o)


def description_name(d: Any) -> str:
    return f"desc({object_name(d.object)},{_opt(d.description_type)},{_opt(d.descriptor)})"


def bond_name(b: Any) -> str:
    """A bond with no direction (sameness) lists its ends left to right."""
    a, z = b.from_object, b.to_object
    if b.direction is None and a.left_string_pos > z.left_string_pos:
        a, z = z, a
    return (
        f"bond({object_name(a)},{object_name(z)},"
        f"{_opt(b.bond_category)},{_opt(b.bond_facet)})"
    )


def bridge_name(b: Any) -> str:
    return f"bridge({b.bridge_type},{object_name(b.object1)},{object_name(b.object2)})"


def concept_mapping_name(cm: Any) -> str:
    return (
        f"cm({_opt(cm.description_type1)},{_opt(cm.descriptor1)},"
        f"{_opt(cm.label)},{_opt(cm.descriptor2)})"
    )


def theme_name(t: Any) -> str:
    relation = "different" if t.relation in (None, "diff") else t.relation
    return (
        f"theme({str(t.theme_type).replace('_', '-')},"
        f"{_opt(t.dimension)},{relation})"
    )


# -- rules, in Metacat's clause grammar (rules.ss:34-64) ------------------------


def _atom(x: Any) -> str:
    """One element of a clause: a node, a symbol, or ``-``."""
    if x is None:
        return "-"
    if isinstance(x, str):
        return x.removeprefix("plato-")
    if hasattr(x, "name") and hasattr(x, "conceptual_depth"):
        return node_name(x)
    from server.engine.workspace_objects import Letter

    if isinstance(x, Letter):  # a verbatim letter is written as its category
        return _letter_category(x)
    return name_of(x)


def _letter_category(letter: Any) -> str:
    for d in getattr(letter, "descriptions", []):
        if getattr(d.description_type, "name", "") == "plato-letter-category":
            return node_name(d.descriptor)
    return letter_name(letter)


def _object_description(od: Any) -> str:
    """``<object-description> ::= (<object-type> <desc-type> <descriptor>)``."""
    return "(" + " ".join(_atom(x) for x in (od or ())) + ")"


def _change(ch: Any) -> str:
    """``<change> ::= (<scope> <dimension> <descriptor>)``."""
    descriptor = ch.relation if getattr(ch, "relation", None) is not None else ch.to_descriptor
    return f"({ch.referent} {_atom(ch.dimension)} {_atom(descriptor)})"


def clause_name(clause: Any) -> str:
    kind = clause.clause_type
    if kind == "intrinsic":
        changes = " ".join(_change(c) for c in clause.changes)
        return (f"(intrinsic ({_object_description(clause.object_description)}) "
                f"({changes}))")
    if kind == "extrinsic":
        ods = " ".join(_object_description(od) for od in clause.object_descriptions)
        dims = " ".join(_atom(d) for d in clause.dimensions)
        return f"(extrinsic ({ods}) ({dims}))"
    letters = " ".join(_atom(x) for x in (clause.verbatim_letters or ()))
    return f"(verbatim ({letters}))"


def rule_name(r: Any) -> str:
    """``rule(<type>,(<clause> <clause> ...))``.

    The clause list is written as Scheme prints a list, which is what Metacat's
    recorder does with ``'get-rule-clauses`` (``decision-trace.ss`` ``tr-clause``), so
    a one-clause rule has two opening parentheses; the spec's §4 example shows one.
    """
    return f"rule({r.rule_type},({' '.join(clause_name(c) for c in r.clauses)}))"


def codelet_name(c: Any) -> str:
    """``<type>(<argument>)``, or just the type when it has no argument."""
    # The scope a top-down scout is handed is not part of its name; Metacat's
    # recorder logs it in a separate `scope` field (DECISIONS.md).
    args = [v for k, v in (c.arguments or {}).items() if v is not None and k != "scope"]
    if not args:
        return c.codelet_type
    return f"{c.codelet_type}({','.join(name_of(a) for a in args)})"


def name_of(x: Any) -> str:
    """The canonical name of anything a decision can offer or pick."""
    try:
        return _name_of(x)
    except Exception:  # a name must never crash a run
        return f"?{type(x).__name__.lower()}:{_safe_repr(x)}"


def _safe_repr(x: Any) -> str:
    try:
        return repr(x)
    except Exception:
        return "unprintable"


_THEME_TYPE_STRINGS = frozenset({"top_bridge", "bottom_bridge", "vertical_bridge"})


def _name_of(x: Any) -> str:
    if x is None:
        return "-"
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, (int, float)):
        return number_name(x)
    if isinstance(x, str):
        # Theme types are Metacat symbols spelled with hyphens (``themes.ss:750``).
        return x.replace("_", "-") if x in _THEME_TYPE_STRINGS else x
    if isinstance(x, (list, tuple)):
        return "(" + ",".join(name_of(i) for i in x) + ")"

    from server.engine.bonds import Bond
    from server.engine.bridges import Bridge
    from server.engine.concept_mappings import ConceptMapping
    from server.engine.coderack import Codelet, CoderackBin
    from server.engine.descriptions import Description
    from server.engine.groups import Group
    from server.engine.rules import Rule
    from server.engine.slipnet import SlipnetNode
    from server.engine.themes import Theme, ThemeCluster
    from server.engine.workspace import WorkspaceString
    from server.engine.workspace_objects import Letter

    if isinstance(x, SlipnetNode):
        return node_name(x)
    if isinstance(x, Letter):
        return letter_name(x)
    if isinstance(x, Group):  # before Bond/Description: a Group is a structure too
        return group_name(x)
    if isinstance(x, WorkspaceString):
        return string_name(x)
    if isinstance(x, Description):
        return description_name(x)
    if isinstance(x, Bond):
        return bond_name(x)
    if isinstance(x, Bridge):
        return bridge_name(x)
    if isinstance(x, ConceptMapping):
        return concept_mapping_name(x)
    if isinstance(x, Rule):
        return rule_name(x)
    if isinstance(x, Theme):
        return theme_name(x)
    if isinstance(x, ThemeCluster):
        return f"cluster({str(x.theme_type).replace('_', '-')},{_opt(x.dimension)})"
    if isinstance(x, Codelet):
        return codelet_name(x)
    if isinstance(x, CoderackBin):
        return f"bin{x.bin_number}"
    return f"?{type(x).__name__.lower()}:{_safe_repr(x)}"
