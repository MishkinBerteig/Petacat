"""English descriptions of rules.

Scheme: ``transcribe-to-english`` and its helpers (``rules.ss:1723-2086``).

Metacat describes every rule in English when the rule is made (``rules.ss:98``) and
stores the result as a *list of lines*: one phrase per clause (or per change, for the
object-category/length/letter-category group), each wrapped at
``%maximum-rule-line-length%`` with a two-space indent on continuation lines.  That
text is what the Workspace shows in the rule boxes, what snag and answer descriptions
keep, and what Episodic Memory displays.  The engine never compares it -- rules are
compared structurally (``rules_equal`` / ``rule_signature``) -- so this module is
display-only.

Names come from the slipnodes: Scheme's ``get-lowercase-name`` is the node's symbol
without its ``plato-`` prefix, lower-cased, which is derived here from ``node.name``.
The two pieces of genuine data -- the line-length limit and the dimension-name table
of ``get-dimension-phrase`` -- are the engine parameters
``maximum_rule_line_length`` and ``rule_english_dimension_phrases``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from server.engine.images import is_platonic_letter

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.rules import Rule, RuleChange, RuleClause


#: ``new-object-phrase``'s ``an-letters`` (``rules.ss:2044``): the letters whose name
#: starts with a vowel sound, so "an `e' group" but "a `b' group".
_AN_LETTERS = frozenset("aefhilmnorsx")


def _param(meta: MetadataProvider | None, name: str, default: Any) -> Any:
    """An engine parameter from the run's provider; ``meta`` is mandatory.

    Raises :class:`~server.engine.metadata.ConfigurationRequired` when there is no
    provider: nothing here reads the Metacat Standard Configuration files.
    """
    from server.engine.metadata import require_meta

    return require_meta(meta, f"rule_english parameter {name!r}").get_param(name, default)


def _lc(node: Any) -> str:
    """Scheme ``get-lowercase-name``: the symbol minus ``plato-``, lower-cased."""
    name = getattr(node, "name", node)
    return str(name)[6:].lower()


def _name(node: Any) -> str | None:
    return getattr(node, "name", None) if node is not None else None


def _is_relation(node: Any) -> bool:
    return _name(node) in (
        "plato-identity",
        "plato-opposite",
        "plato-predecessor",
        "plato-successor",
    )


def _is_literal(node: Any) -> bool:
    return not _is_relation(node)


class _Ctx:
    def __init__(self, string: Any, meta: MetadataProvider | None) -> None:
        self.string = string
        self.phrases: dict[str, list[str]] = _param(
            meta, "rule_english_dimension_phrases", {}
        )
        self.max_line = int(_param(meta, "maximum_rule_line_length", 60))


# --------------------------------------------------------------------------
#  Changes as Scheme's (scope dimension descriptor) triples
# --------------------------------------------------------------------------


def _triple(change: RuleChange) -> tuple[str, Any, Any]:
    return (
        change.referent,
        change.dimension,
        change.relation if change.relation is not None else change.to_descriptor,
    )


def _select_change(dimension: str, scope: str | None, changes: list[tuple]) -> tuple | None:
    for c in changes:
        if _name(c[1]) == dimension and (scope is None or c[0] == scope):
            return c
    return None


def _select_descriptor(dimension: str, scope: str, changes: list[tuple]) -> Any:
    c = _select_change(dimension, scope, changes)
    return c[2] if c is not None else None


# --------------------------------------------------------------------------
#  Object phrases
# --------------------------------------------------------------------------


def _ref_objects(od: tuple, string: Any) -> list[Any]:
    """Scheme ``get-object-description-ref-objects`` (``workspace-strings.ss:494``)."""
    if string is None:
        return []
    object_type, description_type, descriptor = od[0], od[1], od[2]
    groups = list(getattr(string, "groups", []))
    if object_type == "string":
        for g in groups:
            if _has_descriptor(g, "plato-whole"):
                return [g]
        return [string]
    pool = list(getattr(string, "letters", [])) if _name(object_type) == "plato-letter" else groups
    candidates = [o for o in pool if o.descriptor_present(descriptor)]
    if _name(description_type) == "plato-string-position-category" and len(candidates) > 1:
        bridged = [o for o in candidates if getattr(o, "vertical_bridge", None) is not None]
        from server.engine.rules import _lowest_level_object

        return [_lowest_level_object(bridged or candidates)]
    return candidates


def _has_descriptor(obj: Any, name: str) -> bool:
    for d in obj.get_all_descriptions():
        if _name(getattr(d, "descriptor", None)) == name:
            return True
    return False


def _plural_object_phrase(od: tuple, string: Any) -> bool:
    return len(_ref_objects(od, string)) > 1


def _whole_group(string: Any) -> bool:
    if string is None:
        return False
    return any(_has_descriptor(g, "plato-whole") for g in getattr(string, "groups", []))


def _object_phrase(od: tuple, plural: bool, string: Any) -> str:
    object_type, descriptor = od[0], od[2]
    if object_type == "string" or _name(descriptor) == "plato-whole":
        return "whole group" if _whole_group(string) else "string"
    if is_platonic_letter(descriptor):
        if plural:
            return f"all `{_lc(descriptor)}' {_lc(object_type)}s"
        if _name(object_type) == "plato-letter":
            return f"letter `{_lc(descriptor)}'"
        return f"`{_lc(descriptor)}' group"
    if plural:
        return f"all {_lc(descriptor)} {_lc(object_type)}s"
    return f"{_lc(descriptor)} {_lc(object_type)}"


def _dimension_phrase(ctx: _Ctx, dimension: Any, plural: bool) -> str:
    pair = ctx.phrases.get(_name(dimension) or "")
    if not pair:
        return ""
    return pair[1] if plural else pair[0]


def _punctuate(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return "".join(f"{x}, " for x in items[:-1]) + f"and {items[-1]}"


# --------------------------------------------------------------------------
#  Clause phrases
# --------------------------------------------------------------------------


def _verbatim_phrase(letters: list[Any]) -> str:
    return 'Change string to "' + "".join(_lc(x) for x in letters) + '"'


def _swap_phrase(ctx: _Ctx, ods: list[tuple], dims: list[Any]) -> str:
    objects = _punctuate(
        [_object_phrase(od, _plural_object_phrase(od, ctx.string), ctx.string) for od in ods]
    )
    dimensions = _punctuate([_dimension_phrase(ctx, d, True) for d in dims])
    if len(ods) == 1:
        return f"Swap {dimensions} of all objects in {objects}"
    return f"Swap {dimensions} of {objects}"


def _change_phrase(
    ctx: _Ctx, object_phrase: str, plural: bool, bond_facet_change: tuple | None, change: tuple
) -> str:
    scope, dimension, descriptor = change
    dim = _name(dimension)
    subs = scope == "subobjects"
    if dim == "plato-direction-category":
        return "Reverse {} of {}{}".format(
            _dimension_phrase(ctx, dimension, plural or subs),
            "all objects in " if subs else "",
            object_phrase,
        )
    if dim == "plato-group-category":
        if scope == "self":
            facet = _name(bond_facet_change[2]) if bond_facet_change else None
            what = {
                "plato-letter-category": "letter-categories",
                "plato-length": "lengths",
            }.get(facet or "", "")
            return f"Reverse starting and ending {what} of {object_phrase}"
        return f"Reverse starting and ending points of all objects in {object_phrase}"
    to = f"`{_lc(descriptor)}'" if is_platonic_letter(descriptor) else _lc(descriptor)
    return "Change {} of {}{} to {}".format(
        _dimension_phrase(ctx, dimension, plural or subs),
        "all objects in " if subs else "",
        object_phrase,
        to,
    )


def _new_object_phrase(new_type: Any, lett: Any, plural: bool) -> str:
    literal = lett is not None and _is_literal(lett)
    if _name(new_type) == "plato-letter":
        if literal:
            return f"the letter `{_lc(lett)}'"
        return "letters" if plural else "a letter"
    if _name(new_type) == "plato-group":
        if literal:
            if plural:
                return f"`{_lc(lett)}' groups"
            article = "an" if _lc(lett) in _AN_LETTERS and len(_lc(lett)) == 1 else "a"
            return f"{article} `{_lc(lett)}' group"
        return "groups" if plural else "a group"
    return ""


def _change_to_object_type(
    op: str, plural: bool, object_type: Any, lett: Any, subobjects: bool
) -> str:
    return "Change {}{} to {}".format(
        "all objects in " if subobjects else "",
        op,
        _new_object_phrase(object_type, lett, plural or subobjects),
    )


def _change_to_group_of_length(
    op: str, plural: bool, length: Any, lett: Any, subobjects: bool
) -> str:
    return "Change {}{} to {} of length {}".format(
        "all objects in " if subobjects else "",
        op,
        _new_object_phrase(_Group, lett, plural or subobjects),
        _lc(length),
    )


class _GroupMarker:
    name = "plato-group"


_Group = _GroupMarker()


def _change_length_of(
    ctx: _Ctx, op: str, plural: bool, length: Any, subobjects: bool
) -> str:
    dim = _dimension_phrase(ctx, _LengthMarker, plural or subobjects)
    prefix = "all objects in " if subobjects else ""
    n = _name(length)
    if n == "plato-successor":
        return f"Increase {dim} of {prefix}{op} by one"
    if n == "plato-predecessor":
        return f"Decrease {dim} of {prefix}{op} by one"
    return f"Change {dim} of {prefix}{op} to {_lc(length)}"


class _LengthMarker:
    name = "plato-length"


def _objctgy_length_lettctgy_phrases(
    ctx: _Ctx, op: str, plural: bool, changes: list[tuple]
) -> list[str]:
    oc_self = _select_descriptor("plato-object-category", "self", changes)
    oc_subs = _select_descriptor("plato-object-category", "subobjects", changes)
    len_self = _select_descriptor("plato-length", "self", changes)
    len_subs = _select_descriptor("plato-length", "subobjects", changes)
    lc_self = _select_descriptor("plato-letter-category", "self", changes)
    lc_subs = _select_descriptor("plato-letter-category", "subobjects", changes)

    def present(*xs: Any) -> bool:
        return all(x is not None for x in xs)

    class _Letter:
        name = "plato-letter"

    if present(oc_self, len_self):
        if _name(oc_self) == "plato-letter":
            return [_change_to_object_type(op, plural, _Letter, lc_self, False)]
        if _is_relation(len_self):
            return [_change_length_of(ctx, op, plural, len_self, False)]
        return [_change_to_group_of_length(op, plural, len_self, lc_self, False)]
    if present(oc_self):
        return [_change_to_object_type(op, plural, oc_self, lc_self, False)]
    if present(oc_subs, len_self, len_subs):
        first = _change_length_of(ctx, op, plural, len_self, False)
        if _name(oc_subs) == "plato-letter":
            second = _change_to_object_type(op, plural, _Letter, lc_subs, True)
        elif _is_relation(len_subs):
            second = _change_length_of(ctx, op, plural, len_subs, True)
        else:
            second = _change_to_group_of_length(op, plural, len_subs, lc_subs, True)
        return [first, second]
    if present(oc_subs, len_self):
        return [
            _change_length_of(ctx, op, plural, len_self, False),
            _change_to_object_type(op, plural, oc_subs, lc_subs, True),
        ]
    if present(oc_subs, len_subs):
        if _name(oc_subs) == "plato-letter":
            return [_change_to_object_type(op, plural, _Letter, lc_subs, True)]
        if _is_relation(len_subs):
            return [_change_length_of(ctx, op, plural, len_subs, True)]
        return [_change_to_group_of_length(op, plural, len_subs, lc_subs, True)]
    if present(oc_subs):
        return [_change_to_object_type(op, plural, oc_subs, lc_subs, True)]
    if present(len_self, len_subs):
        return [
            _change_length_of(ctx, op, plural, len_self, False),
            _change_length_of(ctx, op, plural, len_subs, True),
        ]
    if present(len_self):
        return [_change_length_of(ctx, op, plural, len_self, False)]
    if present(len_subs):
        return [_change_length_of(ctx, op, plural, len_subs, True)]
    return []


def _remove_lettctgy_change_if_necessary(changes: list[tuple]) -> list[tuple]:
    oc = _select_change("plato-object-category", None, changes)
    if oc is None:
        return changes
    same_lc = _select_change("plato-letter-category", oc[0], changes)
    same_len = _select_change("plato-length", oc[0], changes)
    if (
        same_lc is not None
        and _is_literal(same_lc[2])
        and (
            same_len is None
            or _is_literal(same_len[2])
            or _name(oc[2]) == "plato-letter"
        )
    ):
        return [c for c in changes if c is not same_lc]
    return changes


def _clause_phrases(ctx: _Ctx, clause: RuleClause) -> list[str]:
    if clause.is_verbatim:
        return [_verbatim_phrase(list(clause.verbatim_letters or []))]
    if clause.is_extrinsic:
        return [_swap_phrase(ctx, clause.object_descriptions, clause.dimensions)]
    od = clause.object_descriptions[0]
    plural = _plural_object_phrase(od, ctx.string)
    object_phrase = _object_phrase(od, plural, ctx.string)
    changes = [_triple(c) for c in clause.changes]
    group_phrases = _objctgy_length_lettctgy_phrases(ctx, object_phrase, plural, changes)
    bond_facet_change = _select_change("plato-bond-facet", "self", changes)
    remaining = [
        c
        for c in _remove_lettctgy_change_if_necessary(changes)
        if c is not bond_facet_change
    ]
    others = [
        c
        for c in remaining
        if _name(c[1]) not in ("plato-object-category", "plato-length")
    ]
    other_phrases = [
        _change_phrase(ctx, object_phrase, plural, bond_facet_change, c) for c in others
    ]
    return other_phrases + group_phrases


# --------------------------------------------------------------------------
#  Line wrapping and entry point
# --------------------------------------------------------------------------


def _find_next_space(s: str, i: int) -> int:
    j = s.find(" ", i)
    return len(s) if j < 0 else j


def _separate_into_multiple_lines(s: str, max_length: int, indent: str) -> list[str]:
    lines: list[str] = []
    while True:
        nxt = _find_next_space(s, max_length)
        if nxt == len(s):
            lines.append(s)
            return lines
        lines.append(s[:nxt])
        s = indent + s[nxt:]


def transcribe_rule_to_english_lines(
    rule: Rule, meta: MetadataProvider | None = None
) -> list[str]:
    """Scheme ``transcribe-to-english`` (``rules.ss:1723``): the rule's lines."""
    workspace = getattr(rule, "workspace", None)
    string = None
    if workspace is not None:
        string = workspace.initial_string if rule.is_top_rule else workspace.target_string
    ctx = _Ctx(string, meta)
    if not rule.clauses:
        clause_strings = ["Don't change anything"]
    else:
        clause_strings = []
        for clause in rule.clauses:
            clause_strings.extend(_clause_phrases(ctx, clause))
    adjusted = []
    for s in clause_strings:
        n = len(s)
        adjusted.append(math.ceil(n / math.ceil(n / ctx.max_line)) if n else 0)
    if not adjusted:
        # A clause with no changes: the Scheme would take the maximum of an empty
        # list; the engine never builds such a clause, so say nothing rather than fail.
        return []
    max_len = max(adjusted)
    lines: list[str] = []
    for s in clause_strings:
        lines.extend(_separate_into_multiple_lines(s, max_len, "  "))
    return lines
