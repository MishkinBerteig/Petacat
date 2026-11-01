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

Names come from the slipnodes: Scheme's ``get-lowercase-name`` is the node's plain name
(the ``plain_name`` column, lower-cased) and the article before a letter is its
``article_an`` column; no node name is parsed.
The two pieces of genuine data -- the line-length limit and the dimension-name table
of ``get-dimension-phrase`` -- are the engine parameters
``maximum_rule_line_length`` and ``rule_english_dimension_phrases``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from server.engine.images import is_platonic_letter
from server.engine.answer_comparison import _fill
from server.engine.slipnet import article_of, holds_role, lowercase_name as _lc

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.rules import Rule, RuleChange, RuleClause


def _param(meta: MetadataProvider | None, name: str, default: Any) -> Any:
    """An engine parameter from the run's provider; ``meta`` is mandatory.

    Raises :class:`~server.engine.metadata.ConfigurationRequired` when there is no
    provider: nothing here reads the Metacat Standard Configuration files.
    """
    from server.engine.metadata import require_meta

    return require_meta(meta, f"rule_english parameter {name!r}").get_param(name, default)


def _name(node: Any) -> str | None:
    return getattr(node, "name", None) if node is not None else None


# The roles the grammar reads (``server/engine/roles.py``); a role nothing holds is never
# matched, so the phrase that needs it falls to the generic one the code already has.
_DIM_DIRECTION = "dimension.direction"
_DIM_GROUP_CATEGORY = "dimension.group_category"
_DIM_LETTER_CATEGORY = "dimension.letter_category"
_DIM_LENGTH = "dimension.length"
_DIM_OBJECT_CATEGORY = "dimension.object_category"
_DIM_STRING_POSITION = "dimension.string_position"
_DIM_BOND_FACET = "dimension.bond_facet"
_POS_WHOLE = "position.whole"
_OBJECT_LETTER = "object.letter"
_OBJECT_GROUP = "object.group"


def _is_relation(node: Any) -> bool:
    """A node that is a relation (identity, opposite, successor, predecessor ...): it knows
    the ``theme_relations`` row it is (``node.relation``)."""
    return getattr(node, "relation", None) is not None


def _is_literal(node: Any) -> bool:
    return not _is_relation(node)


class _Ctx:
    def __init__(self, string: Any, meta: MetadataProvider | None) -> None:
        self.string = string
        self.phrases: dict[str, list[str]] = _param(
            meta, "rule_english_dimension_phrases", {}
        )
        self.max_line = int(_param(meta, "maximum_rule_line_length", 60))
        # The grammar: ``commentary_templates["rule_english"]``.  A template the
        # configuration lacks makes the text it produces empty (ABSENCE-BEHAVIOUR 2.6).
        templates = getattr(meta, "commentary_templates", None) or {}
        section = templates.get("rule_english")
        self.templates: dict[str, str] = section if isinstance(section, dict) else {}

    def say(self, key: str, **values: Any) -> str:
        """The template *key* with its ``{slots}`` filled."""
        return _fill(self.templates.get(key, ""), **values)


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
    """The first change whose dimension plays the role *dimension*, in *scope*."""
    for c in changes:
        if holds_role(c[1], dimension) and (scope is None or c[0] == scope):
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
            if _has_descriptor(g, _POS_WHOLE):
                return [g]
        return [string]
    pool = list(getattr(string, "letters", [])) if holds_role(object_type, _OBJECT_LETTER) else groups
    candidates = [o for o in pool if o.descriptor_present(descriptor)]
    if holds_role(description_type, _DIM_STRING_POSITION) and len(candidates) > 1:
        bridged = [o for o in candidates if getattr(o, "vertical_bridge", None) is not None]
        from server.engine.rules import _lowest_level_object

        return [_lowest_level_object(bridged or candidates)]
    return candidates


def _has_descriptor(obj: Any, role: str) -> bool:
    """Does one of *obj*'s descriptions have a descriptor that plays *role*?"""
    for d in obj.get_all_descriptions():
        if holds_role(getattr(d, "descriptor", None), role):
            return True
    return False


def _plural_object_phrase(od: tuple, string: Any) -> bool:
    return len(_ref_objects(od, string)) > 1


def _whole_group(string: Any) -> bool:
    if string is None:
        return False
    return any(_has_descriptor(g, _POS_WHOLE) for g in getattr(string, "groups", []))


def _descriptor_text(ctx: _Ctx, descriptor: Any) -> str:
    """A descriptor as the English names it: a letter is quoted, anything else is its name."""
    if is_platonic_letter(descriptor):
        return ctx.say("quoted_letter", name=_lc(descriptor))
    return _lc(descriptor)


def _object_phrase(ctx: _Ctx, od: tuple, plural: bool) -> str:
    object_type, descriptor = od[0], od[2]
    if object_type == "string" or holds_role(descriptor, _POS_WHOLE):
        return ctx.say("whole_group" if _whole_group(ctx.string) else "string")
    text = _descriptor_text(ctx, descriptor)
    if plural:
        return ctx.say("plural_object", descriptor=text, type=_lc(object_type))
    if is_platonic_letter(descriptor) and holds_role(object_type, _OBJECT_LETTER):
        return ctx.say("letter_object", descriptor=text)
    return ctx.say("single_object", descriptor=text, type=_lc(object_type))


def _dimension_phrase(ctx: _Ctx, dimension: Any, plural: bool) -> str:
    pair = ctx.phrases.get(_name(dimension) or "")
    if not pair:
        return ""
    return pair[1] if plural else pair[0]


def _punctuate(ctx: _Ctx, items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return ctx.say("list_pair", first=items[0], second=items[1])
    return "".join(f"{x}, " for x in items[:-1]) + ctx.say("list_last", last=items[-1])


def _scope_prefix(ctx: _Ctx, subobjects: bool) -> str:
    return ctx.say("all_objects_in") if subobjects else ""


# --------------------------------------------------------------------------
#  Clause phrases
# --------------------------------------------------------------------------


def _verbatim_phrase(ctx: _Ctx, letters: list[Any]) -> str:
    return ctx.say("verbatim", letters="".join(_lc(x) for x in letters))


def _swap_phrase(ctx: _Ctx, ods: list[tuple], dims: list[Any]) -> str:
    objects = _punctuate(
        ctx, [_object_phrase(ctx, od, _plural_object_phrase(od, ctx.string)) for od in ods]
    )
    dimensions = _punctuate(ctx, [_dimension_phrase(ctx, d, True) for d in dims])
    if len(ods) == 1:
        return ctx.say("swap_all_objects", dimensions=dimensions, objects=objects)
    return ctx.say("swap", dimensions=dimensions, objects=objects)


def _change_phrase(
    ctx: _Ctx, object_phrase: str, plural: bool, bond_facet_change: tuple | None, change: tuple
) -> str:
    scope, dimension, descriptor = change
    subs = scope == "subobjects"
    if holds_role(dimension, _DIM_DIRECTION):
        return ctx.say(
            "reverse",
            dimension=_dimension_phrase(ctx, dimension, plural or subs),
            scope=_scope_prefix(ctx, subs),
            object=object_phrase,
        )
    if holds_role(dimension, _DIM_GROUP_CATEGORY):
        if scope == "self":
            # The medium's plural, from the dimension phrases (no second copy of the words).
            what = _dimension_phrase(ctx, bond_facet_change[2], True) if bond_facet_change else ""
            return ctx.say("reverse_ends", facet=what, object=object_phrase)
        return ctx.say("reverse_ends_all", object=object_phrase)
    return ctx.say(
        "change",
        dimension=_dimension_phrase(ctx, dimension, plural or subs),
        scope=_scope_prefix(ctx, subs),
        object=object_phrase,
        to=_descriptor_text(ctx, descriptor),
    )


def _object_kind(node: Any) -> str | None:
    """The object-type role *node* plays (letter or group), or ``None``."""
    for role in (_OBJECT_LETTER, _OBJECT_GROUP):
        if holds_role(node, role):
            return role
    return None


def _new_object_phrase(ctx: _Ctx, new_type: Any, lett: Any, plural: bool) -> str:
    """The new object type a change turns objects into: the node that plays the object
    type, or the name of that role."""
    kind = new_type if isinstance(new_type, str) else _object_kind(new_type)
    literal = lett is not None and _is_literal(lett)
    if kind == _OBJECT_LETTER:
        if literal:
            return ctx.say("new_letter_literal", descriptor=_descriptor_text(ctx, lett))
        return ctx.say("new_letters" if plural else "new_letter")
    if kind == _OBJECT_GROUP:
        if literal:
            if plural:
                return ctx.say("new_groups_literal", descriptor=_descriptor_text(ctx, lett))
            return ctx.say(
                "new_group_literal",
                article=article_of(lett),
                descriptor=_descriptor_text(ctx, lett),
            )
        return ctx.say("new_groups" if plural else "new_group")
    return ""


def _change_to_object_type(
    ctx: _Ctx, op: str, plural: bool, object_type: Any, lett: Any, subobjects: bool
) -> str:
    return ctx.say(
        "change_to",
        scope=_scope_prefix(ctx, subobjects),
        op=op,
        new=_new_object_phrase(ctx, object_type, lett, plural or subobjects),
    )


def _change_to_group_of_length(
    ctx: _Ctx, op: str, plural: bool, length: Any, lett: Any, subobjects: bool
) -> str:
    return ctx.say(
        "change_to_length",
        scope=_scope_prefix(ctx, subobjects),
        op=op,
        new=_new_object_phrase(ctx, _OBJECT_GROUP, lett, plural or subobjects),
        length=_lc(length),
    )


def _change_length_of(
    ctx: _Ctx, op: str, plural: bool, length_dim: Any, length: Any, subobjects: bool
) -> str:
    fields = {
        "dimension": _dimension_phrase(ctx, length_dim, plural or subobjects),
        "scope": _scope_prefix(ctx, subobjects),
        "op": op,
    }
    relation = getattr(length, "relation", None)
    if relation == "successor":
        return ctx.say("increase_length", **fields)
    if relation == "predecessor":
        return ctx.say("decrease_length", **fields)
    return ctx.say("change_length", length=_lc(length), **fields)


def _objctgy_length_lettctgy_phrases(
    ctx: _Ctx, op: str, plural: bool, changes: list[tuple]
) -> list[str]:
    """The object-category / length / letter-category group of phrases."""
    oc_self = _select_descriptor(_DIM_OBJECT_CATEGORY, "self", changes)
    oc_subs = _select_descriptor(_DIM_OBJECT_CATEGORY, "subobjects", changes)
    len_self = _select_descriptor(_DIM_LENGTH, "self", changes)
    len_subs = _select_descriptor(_DIM_LENGTH, "subobjects", changes)
    lc_self = _select_descriptor(_DIM_LETTER_CATEGORY, "self", changes)
    lc_subs = _select_descriptor(_DIM_LETTER_CATEGORY, "subobjects", changes)
    length_change = _select_change(_DIM_LENGTH, None, changes)
    ldim = length_change[1] if length_change is not None else None

    def present(*xs: Any) -> bool:
        return all(x is not None for x in xs)

    if present(oc_self, len_self):
        if holds_role(oc_self, _OBJECT_LETTER):
            return [_change_to_object_type(ctx, op, plural, oc_self, lc_self, False)]
        if _is_relation(len_self):
            return [_change_length_of(ctx, op, plural, ldim, len_self, False)]
        return [_change_to_group_of_length(ctx, op, plural, len_self, lc_self, False)]
    if present(oc_self):
        return [_change_to_object_type(ctx, op, plural, oc_self, lc_self, False)]
    if present(oc_subs, len_self, len_subs):
        first = _change_length_of(ctx, op, plural, ldim, len_self, False)
        if holds_role(oc_subs, _OBJECT_LETTER):
            second = _change_to_object_type(ctx, op, plural, oc_subs, lc_subs, True)
        elif _is_relation(len_subs):
            second = _change_length_of(ctx, op, plural, ldim, len_subs, True)
        else:
            second = _change_to_group_of_length(ctx, op, plural, len_subs, lc_subs, True)
        return [first, second]
    if present(oc_subs, len_self):
        return [
            _change_length_of(ctx, op, plural, ldim, len_self, False),
            _change_to_object_type(ctx, op, plural, oc_subs, lc_subs, True),
        ]
    if present(oc_subs, len_subs):
        if holds_role(oc_subs, _OBJECT_LETTER):
            return [_change_to_object_type(ctx, op, plural, oc_subs, lc_subs, True)]
        if _is_relation(len_subs):
            return [_change_length_of(ctx, op, plural, ldim, len_subs, True)]
        return [_change_to_group_of_length(ctx, op, plural, len_subs, lc_subs, True)]
    if present(oc_subs):
        return [_change_to_object_type(ctx, op, plural, oc_subs, lc_subs, True)]
    if present(len_self, len_subs):
        return [
            _change_length_of(ctx, op, plural, ldim, len_self, False),
            _change_length_of(ctx, op, plural, ldim, len_subs, True),
        ]
    if present(len_self):
        return [_change_length_of(ctx, op, plural, ldim, len_self, False)]
    if present(len_subs):
        return [_change_length_of(ctx, op, plural, ldim, len_subs, True)]
    return []


def _remove_lettctgy_change_if_necessary(changes: list[tuple]) -> list[tuple]:
    oc = _select_change(_DIM_OBJECT_CATEGORY, None, changes)
    if oc is None:
        return changes
    same_lc = _select_change(_DIM_LETTER_CATEGORY, oc[0], changes)
    same_len = _select_change(_DIM_LENGTH, oc[0], changes)
    if (
        same_lc is not None
        and _is_literal(same_lc[2])
        and (
            same_len is None
            or _is_literal(same_len[2])
            or holds_role(oc[2], _OBJECT_LETTER)
        )
    ):
        return [c for c in changes if c is not same_lc]
    return changes


def _clause_phrases(ctx: _Ctx, clause: RuleClause) -> list[str]:
    if clause.is_verbatim:
        return [_verbatim_phrase(ctx, list(clause.verbatim_letters or []))]
    if clause.is_extrinsic:
        return [_swap_phrase(ctx, clause.object_descriptions, clause.dimensions)]
    od = clause.object_descriptions[0]
    plural = _plural_object_phrase(od, ctx.string)
    object_phrase = _object_phrase(ctx, od, plural)
    changes = [_triple(c) for c in clause.changes]
    group_phrases = _objctgy_length_lettctgy_phrases(ctx, object_phrase, plural, changes)
    bond_facet_change = _select_change(_DIM_BOND_FACET, "self", changes)
    remaining = [
        c
        for c in _remove_lettctgy_change_if_necessary(changes)
        if c is not bond_facet_change
    ]
    others = [
        c
        for c in remaining
        if not (holds_role(c[1], _DIM_OBJECT_CATEGORY) or holds_role(c[1], _DIM_LENGTH))
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
        clause_strings = [ctx.say("no_change")]
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
