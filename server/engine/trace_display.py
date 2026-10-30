"""How a Trace event is named, and the picture it redisplays.

Metacat gives every Temporal Trace event two presentations, both defined in
``trace.ss`` and neither of which Petacat had:

* a **print name** -- the short label the Trace window draws for the event
  (``(Id)`` for a concept activation, ``>a-b-c>`` for a group, ``T:a=>b`` for a slippage,
  ``[Top Rule]``, ``[Answer abd]``, ``[Clamp]``, ``[Snag]``), and
* a **display** -- clicking the event redraws the Workspace *as it was at that moment*
  (the structures every event captures in ``make-generic-event``, ``trace.ss:233``)
  under a header, with the event's own structures highlighted, shows the event's concept
  pattern in the Slipnet, blanks the Coderack and shows the event's temperature.

This module is the Petacat form of both.  A *picture* is a JSON-able dict, captured
once, at the moment the event is recorded (the Workspace will have moved on by the time
anyone clicks), stored with the event and served as it is.  It contains

``header``
    the text Metacat's ``draw-event-header`` writes after "Event N:" (``trace.ss:431``).
``workspace``
    a ``WorkspaceState``: the groups, bridges and rules to draw.  Events draw the whole
    Workspace (faded) -- ``display-workspace-state`` (``trace.ss:300-325``); answer and
    snag *descriptions* draw only what supports them (``make-answer-description-pexp``,
    ``trace.ss:466``; ``make-snag-description-pexp``, ``trace.ss:1212``).
``highlights``
    ``groups`` / ``objects`` / ``bridges`` / ``concept_mappings``, each entry with a
    ``role`` the client maps to a colour (``event``, ``top``, ``bottom``, ``vertical``,
    ``snag``, ``theme_cm``, ``vertical_slippage``, ``faded``).
``slipnet``
    the concept pattern to show (``display-patterns``) or ``entries: []`` for a blank
    window, with the title Metacat draws.
``coderack``
    blank ("Coderack") or the clamp's codelet pattern.
``themes``
    the theme patterns to impose over the Themespace.

Nothing here touches the RNG or any engine state: it only reads.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from server.engine.workspace import WorkspaceString

logger = logging.getLogger(__name__)

PICTURE_VERSION = 1

# Roles the client colours.  ``%workspace-event-structure-color%``,
# ``%top-bridge-color%`` & co. in Metacat.
ROLE_EVENT = "event"
ROLE_TOP = "top"
ROLE_BOTTOM = "bottom"
ROLE_VERTICAL = "vertical"
ROLE_SNAG = "snag"
ROLE_THEME_CM = "theme_cm"
ROLE_VERTICAL_SLIPPAGE = "vertical_slippage"
#: ``get-highlight-color`` (``answers.ss:1233``): a slippage that induced a coattail slippage is
#: drawn in its own colour, and every slippage a bridge holds besides the applied one in the
#: dimmed form of its colour.
ROLE_VERTICAL_SLIPPAGE_DIM = "vertical_slippage_dim"
ROLE_COATTAIL_SLIPPAGE = "coattail_slippage"
ROLE_COATTAIL_SLIPPAGE_DIM = "coattail_slippage_dim"
ROLE_FADED = "faded"


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def lowercase_name(node: Any) -> str:
    """``get-lowercase-name``: the node's name less the six characters of ``plato-``."""
    return str(getattr(node, "name", node))[6:].lower()


def uppercase_name(node: Any) -> str:
    """``get-uppercase-name`` (``slipnet.ss:42``)."""
    return lowercase_name(node).upper()


_NUMBER_NODES = {
    "plato-one": 1,
    "plato-two": 2,
    "plato-three": 3,
    "plato-four": 4,
    "plato-five": 5,
}

_FULL_SLIPNODE_NAMES = {
    "plato-alphabetic-position-category": "Alphabetic-Position",
    "plato-bond-facet": "Bond-Facet",
    "plato-object-category": "Object-Category",
    "plato-letter-category": "Letter-Category",
    "plato-length": "Length",
    "plato-bond-category": "Bond-Category",
    "plato-group-category": "Group-Category",
    "plato-direction-category": "Direction",
    "plato-string-position-category": "String-Position",
    "plato-opposite": "Opposite",
    "plato-identity": "Identity",
    "plato-predgrp": "predecessor-group",
    "plato-succgrp": "successor-group",
    "plato-samegrp": "sameness-group",
}


def full_slipnode_name(node: Any) -> str:
    """``full-slipnode-name`` (``trace.ss:1271``)."""
    return _FULL_SLIPNODE_NAMES.get(getattr(node, "name", ""), lowercase_name(node))


def cm_short_name(node: Any) -> str:
    """``get-CM-short-name`` (``slipnet.ss:56``): the letter-category node avoids a clash."""
    if getattr(node, "name", "") == "plato-letter-category":
        return "LettCtgy"
    return str(getattr(node, "short_name", getattr(node, "name", "?")))


def concept_mapping_print_name(cm: Any) -> str:
    """``print-name`` of a concept-mapping (``concept-mappings.ss:35``): ``a=>b``."""
    return f"{cm_short_name(cm.descriptor1)}=>{cm_short_name(cm.descriptor2)}"


def group_event_text(group: Any) -> str:
    """``group-event-pexp-text-string`` (``headless.ss:295``, ``trace-graphics.ss:322``).

    The constituents' descriptors on the group's bond facet, hyphen-joined: letters by
    their lower-case name, groups by their upper-case one, a Length descriptor as its
    number.
    """
    facet = getattr(group, "bond_facet", None)
    parts: list[str] = []
    for obj in getattr(group, "objects", []):
        descriptor = obj.get_descriptor_for(facet) if hasattr(obj, "get_descriptor_for") else None
        if descriptor is None:
            parts.append("?")
        elif getattr(descriptor, "name", "") in _NUMBER_NODES:
            parts.append(str(_NUMBER_NODES[descriptor.name]))
        elif hasattr(obj, "objects"):
            parts.append(uppercase_name(descriptor))
        else:
            parts.append(lowercase_name(descriptor))
    return "-".join(parts)


def group_print_name(group: Any) -> str:
    """``>abc>``, ``<cba<`` or ``[abc]`` by direction (``trace.ss:840-847``)."""
    text = group_event_text(group)
    name = getattr(getattr(group, "direction", None), "name", None)
    if name == "plato-right":
        return f">{text}>"
    if name == "plato-left":
        return f"<{text}<"
    return f"[{text}]"


def print_name(event: Any) -> str:
    """The label Metacat's Temporal Trace window draws for *event*."""
    from server.engine import trace as T

    kind = event.event_type
    if kind == T.CONCEPT_ACTIVATION and event.slipnode is not None:
        return f"({event.slipnode.short_name})"
    if kind == T.GROUP_BUILT and event.group is not None:
        return group_print_name(event.group)
    if kind == T.CONCEPT_MAPPING_BUILT and event.concept_mapping is not None:
        prefix = {"top": "T", "vertical": "V", "bottom": "B"}.get(
            getattr(event.bridge, "bridge_type", ""), "?"
        )
        return f"{prefix}:{concept_mapping_print_name(event.concept_mapping)}"
    if kind == T.RULE_BUILT and event.structures:
        rule = event.structures[0]
        return "[Top Rule]" if getattr(rule, "is_top_rule", True) else "[Bottom Rule]"
    if kind == T.ANSWER_FOUND:
        return f"[Answer {getattr(event, 'answer_string', '') or ''}]"
    if kind == T.SNAG:
        return "[Snag]"
    if kind in (T.CLAMP_START, T.CLAMP_END):
        return "[Clamp]"
    return event.description or kind


def _unflipped_group_name(group: Any) -> str:
    """``unflipped-group-name`` (``trace.ss:1291``)."""
    name = getattr(getattr(group, "group_category", None), "name", "")
    return {"plato-predgrp": "successor-group", "plato-succgrp": "predecessor-group"}.get(
        name, ""
    )


def _full_object_name(obj: Any) -> str:
    """``full-workspace-object-name`` (``trace.ss:1298``)."""
    if not hasattr(obj, "group_category"):
        return "letter"
    return _FULL_SLIPNODE_NAMES.get(getattr(obj.group_category, "name", ""), "")


def header(event: Any, justify_mode: bool = False) -> str:
    """The text after ``Event N:  `` that ``display-workspace`` draws."""
    from server.engine import trace as T

    kind = event.event_type
    if kind == T.CONCEPT_ACTIVATION and event.slipnode is not None:
        return f"Activation of {full_slipnode_name(event.slipnode)} concept"
    if kind == T.GROUP_BUILT and event.group is not None:
        if event.flipped:
            return f"Flipped {_unflipped_group_name(event.group)}"
        return f"Built {_full_object_name(event.group)}"
    if kind == T.CONCEPT_MAPPING_BUILT and event.concept_mapping is not None:
        noun = "slippage" if not event.concept_mapping.is_identity else "concept-mapping"
        return f"Made {concept_mapping_print_name(event.concept_mapping)} {noun}"
    if kind == T.RULE_BUILT and event.structures:
        rule = event.structures[0]
        return f"Built {'translated ' if getattr(rule, 'translated', False) else ''}rule"
    if kind == T.ANSWER_FOUND:
        unjustified = getattr(event, "is_unjustified", lambda: False)()
        return answer_header(justify_mode, unjustified)
    if kind == T.SNAG:
        return "Snag"
    if kind in (T.CLAMP_START, T.CLAMP_END):
        manual = getattr(event, "clamp_type", "") == "manual_clamp"
        return "Manually clamped patterns" if manual else "Clamped patterns"
    return event.description or kind


def answer_header(justify_mode: bool, unjustified: bool) -> str:
    """``trace.ss:431-437``."""
    if not justify_mode:
        return "Found new answer"
    if unjustified:
        return "Settled for unjustified answer"
    return "Justified answer"


# ---------------------------------------------------------------------------
# Picture pieces
# ---------------------------------------------------------------------------

def _string_role(string: Any) -> str:
    return getattr(string, "string_type", "") or ""


def _is_string(obj: Any) -> bool:
    return isinstance(obj, WorkspaceString)


def object_ref(obj: Any, role: str) -> dict:
    """Point at a letter, group or whole string; ``left == -1`` means the string itself."""
    if _is_string(obj):
        return {"string": _string_role(obj), "left": -1, "right": -1, "role": role}
    return {
        "string": _string_role(getattr(obj, "string", None)),
        "left": obj.left_string_pos,
        "right": obj.right_string_pos,
        "role": role,
    }


def bridge_key(bridge: Any) -> str:
    """The key the client rebuilds from a ``BridgeState`` to find this bridge again."""
    return "{}:{}-{}:{}-{}".format(
        bridge.bridge_type,
        bridge.object1.left_string_pos,
        bridge.object1.right_string_pos,
        bridge.object2.left_string_pos,
        bridge.object2.right_string_pos,
    )


def bridge_highlight(bridge: Any, role: str) -> dict:
    return {"key": bridge_key(bridge), "role": role}


def cm_highlight(bridge: Any, cm: Any, role: str) -> dict:
    return {
        "bridge": bridge_key(bridge),
        "from": getattr(cm.descriptor1, "short_name", "?"),
        "to": getattr(cm.descriptor2, "short_name", "?"),
        "role": role,
    }


def highlight_bridges(highlights: dict, bridges: list, role: str) -> None:
    """``highlight-bridges`` (``workspace-graphics.ss:785``): both objects and the bridge."""
    for bridge in bridges:
        highlights["objects"].append(object_ref(bridge.object1, role))
        highlights["bridges"].append(bridge_highlight(bridge, role))
        highlights["objects"].append(object_ref(bridge.object2, role))


def _new_highlights() -> dict:
    return {"groups": [], "objects": [], "bridges": [], "concept_mappings": []}


def _serialize_rule_for_picture(rule: Any, role: str) -> dict:
    from server.engine.serialization import _serialize_rule

    out = _serialize_rule(rule)
    out["role"] = role
    return out


def workspace_picture(
    ctx: Any,
    *,
    groups: list | None = None,
    bridges: dict[str, list] | None = None,
    rules: list[tuple[Any, str]] | None = None,
    answer_text: str | None = None,
) -> dict:
    """A ``WorkspaceState`` for the picture.

    By default the *whole* Workspace (every built group and bridge) -- the state
    ``display-workspace-state`` redraws.  ``groups`` and ``bridges`` narrow it to the
    supporting structures a description draws.
    """
    from server.engine.serialization import _serialize_bridge, _serialize_group

    ws = ctx.workspace
    strings = ws.all_strings
    if groups is None:
        groups = [g for s in strings for g in s.groups if g.is_built]
    if bridges is None:
        bridges = {
            "top": [b for b in ws.top_bridges if b.is_built],
            "vertical": [b for b in ws.vertical_bridges if b.is_built],
            "bottom": [b for b in ws.bottom_bridges if b.is_built],
        }

    groups_by_text: dict[str, list[dict]] = {s.text: [] for s in strings}
    for g in groups:
        text = getattr(getattr(g, "string", None), "text", None)
        if text is not None:
            groups_by_text.setdefault(text, []).append(_serialize_group(g))

    rule_dicts = [_serialize_rule_for_picture(r, role) for r, role in (rules or [])]
    return {
        "initial": ws.initial_string.text,
        "modified": ws.modified_string.text,
        "target": ws.target_string.text,
        "answer": answer_text
        if answer_text is not None
        else (ws.answer_string.text if ws.answer_string else None),
        "num_top_bridges": len(bridges["top"]),
        "num_bottom_bridges": len(bridges["bottom"]),
        "num_vertical_bridges": len(bridges["vertical"]),
        "num_top_rules": sum(1 for r in rule_dicts if r["type"] == "top"),
        "num_bottom_rules": sum(1 for r in rule_dicts if r["type"] == "bottom"),
        "bonds_per_string": {},
        "groups_per_string": {t: len(v) for t, v in groups_by_text.items()},
        "bonds": {},
        "groups": groups_by_text,
        "top_bridges": [_serialize_bridge(b) for b in bridges["top"]],
        "vertical_bridges": [_serialize_bridge(b) for b in bridges["vertical"]],
        "bottom_bridges": [_serialize_bridge(b) for b in bridges["bottom"]],
        "top_rules": [r for r in rule_dicts if r["type"] == "top"],
        "bottom_rules": [r for r in rule_dicts if r["type"] == "bottom"],
    }


def _entries(pattern: Any) -> list[dict]:
    """A concept pattern -- ``[(node, act)]`` or ``{"entries": [...]}`` -- as entries."""
    from server.engine.trace import _concept_pattern_entries

    if isinstance(pattern, (list, tuple)):
        out = []
        for item in pattern:
            node, act = item
            out.append({"node": getattr(node, "name", node), "activation": float(act)})
        return out
    return [
        {"node": name, "activation": act} for name, act in _concept_pattern_entries(pattern)
    ]


def group_concept_pattern(group: Any) -> list[tuple[Any, float]]:
    """``get-concept-pattern`` of a workspace object (``workspace-objects.ss:168``)."""
    out = []
    for description in group.get_all_descriptions():
        relevant = description.is_relevant() if hasattr(description, "is_relevant") else True
        out.append((description.descriptor, description.descriptor.max_activation if relevant else 0.0))
    return out


def _slipnet_block(title: str, patterns: list) -> dict:
    entries: list[dict] = []
    for pattern in patterns:
        entries.extend(_entries(pattern))
    return {"title": title, "entries": entries}


def _blank_slipnet() -> dict:
    return {"title": "Slipnet Activation", "entries": [], "blank": True}


def _blank_coderack() -> dict:
    return {"title": "Coderack", "entries": [], "blank": True}


def rule_reference_objects(ctx: Any, rule: Any) -> list:
    """``get-all-reference-objects`` minus whole strings, on the rule's own string."""
    from server.engine.rules import get_all_reference_objects

    if rule is None:
        return []
    ws = ctx.workspace
    string = ws.initial_string if getattr(rule, "is_top_rule", True) else ws.target_string
    try:
        return list(get_all_reference_objects(rule, string, ctx.slipnet))
    except Exception:  # pragma: no cover - a picture is never worth a crash
        return []


def applied_slippage_highlights(slippage_log: Any) -> list[dict]:
    """``highlight-applied-slippages`` (``workspace-graphics.ss:791``) for a slippage log.

    One concept-mapping highlight per *applied* slippage, in the log's order, on the
    forward slippage ``get-slippage-to-highlight`` picks, coloured by
    ``get-highlight-color``.
    """
    if slippage_log is None:
        return []
    out = []
    for applied in slippage_log.get_applied_slippages():
        bridge = slippage_log.get_bridge(applied)
        shown = slippage_log.get_slippage_to_highlight(applied)
        if bridge is None or shown is None:
            continue
        inducing = slippage_log.coattail_inducing_slippage(applied)
        exact = shown is applied
        if inducing:
            role = ROLE_COATTAIL_SLIPPAGE if exact else ROLE_COATTAIL_SLIPPAGE_DIM
        else:
            role = ROLE_VERTICAL_SLIPPAGE if exact else ROLE_VERTICAL_SLIPPAGE_DIM
        out.append(cm_highlight(bridge, shown, role))
    return out


def cm_ref(cm: Any) -> dict:
    """A concept mapping as plain JSON: its dimension, both concepts and its label."""
    def short(node: Any) -> str | None:
        return None if node is None else cm_short_name(node)

    return {
        "type": short(cm.description_type1),
        "from": short(cm.descriptor1),
        "label": short(cm.label),
        "to": short(cm.descriptor2),
    }


def _object_key(obj: Any) -> str:
    if _is_string(obj):
        return f"{_string_role(obj)}:-1--1"
    return f"{_string_role(getattr(obj, 'string', None))}:{obj.left_string_pos}-{obj.right_string_pos}"


def slippage_log_json(slippage_log: Any) -> dict | None:
    """The slippage log (``answers.ss:1198``) as plain JSON, in the log's own order."""
    if slippage_log is None:
        return None

    def bridge_ref(b: Any) -> str | None:
        return None if b is None else bridge_key(b)

    return {
        "rule_type": slippage_log.rule_type,
        "directly_applied": [cm_ref(s) for s in slippage_log.directly_applied_slippages],
        "coattail": [
            {"slippage": cm_ref(c), "inducing": cm_ref(i)}
            for c, i in slippage_log.coattail_slippage_table
        ],
        "bridges": [bridge_ref(b) for b in slippage_log.get_slippage_bridges()],
        "applied": [cm_ref(s) for s in slippage_log.get_applied_slippages()],
    }


def translation_json(
    *,
    slippage_log: Any,
    supporting_vertical_bridges: list,
    supporting_groups: list | None = None,
    top_ref_objects: list | None = None,
    bottom_ref_objects: list | None = None,
) -> dict:
    """What a rule translation left behind, as kept in a picture: the slippage log, the
    supporting vertical bridges and groups, and the rules' reference objects."""
    out: dict = {
        "slippage_log": slippage_log_json(slippage_log),
        "supporting_vertical_bridges": [bridge_key(b) for b in supporting_vertical_bridges or []],
    }
    if supporting_groups is not None:
        out["supporting_groups"] = [_object_key(g) for g in supporting_groups]
    if top_ref_objects is not None:
        out["top_ref_objects"] = [_object_key(o) for o in top_ref_objects]
    if bottom_ref_objects is not None:
        out["bottom_ref_objects"] = [_object_key(o) for o in bottom_ref_objects]
    return out


def _json_pattern(pattern: Any) -> Any:
    """A list-form theme pattern as plain JSON lists (tuples become lists)."""
    if isinstance(pattern, (list, tuple)):
        return [_json_pattern(p) for p in pattern]
    return pattern


def _theme_patterns_for(event: Any) -> list:
    pattern = getattr(event, "snag_theme_pattern", None) or event.theme_pattern
    return [pattern] if pattern else []


# ---------------------------------------------------------------------------
# The picture of a Trace event
# ---------------------------------------------------------------------------

def build_event_picture(ctx: Any, event: Any) -> dict:
    """Everything ``display`` shows for *event*, taken now (``trace.ss:405-1212``)."""
    from server.engine import trace as T

    ws = ctx.workspace
    highlights = _new_highlights()
    rules: list[tuple[Any, str]] = []
    slipnet = _blank_slipnet()
    coderack = _blank_coderack()
    themes: list = _theme_patterns_for(event)
    temperature = event.temperature
    kind = event.event_type
    answer_text = None

    # ``display-workspace-state`` redraws the clamped rules in every event.
    for rule in ws.get_clamped_rules():
        rules.append((rule, ROLE_FADED))

    if kind == T.GROUP_BUILT and event.group is not None:
        highlights["objects"].append(object_ref(event.group, ROLE_EVENT))
        highlights["groups"].append(object_ref(event.group, ROLE_EVENT))
        slipnet = _slipnet_block("Group Descriptors", [group_concept_pattern(event.group)])

    elif kind == T.CONCEPT_MAPPING_BUILT and event.concept_mapping is not None:
        cm, bridge = event.concept_mapping, event.bridge
        if bridge is not None:
            highlight_bridges(highlights, [bridge], ROLE_EVENT)
            highlights["concept_mappings"].append(cm_highlight(bridge, cm, ROLE_EVENT))
        word = "Slippage" if not cm.is_identity else "Concept-mapping"
        slipnet = _slipnet_block(f"{word} Concepts", [cm.get_concept_pattern()])

    elif kind == T.CONCEPT_ACTIVATION and event.slipnode is not None:
        slipnet = _slipnet_block(
            "Concept Activation", [[(event.slipnode, event.slipnode.max_activation)]]
        )
        themes = []

    elif kind == T.RULE_BUILT and event.structures:
        rule = event.structures[0]
        role = ROLE_TOP if getattr(rule, "is_top_rule", True) else ROLE_BOTTOM
        if getattr(rule, "translated", False) and getattr(rule, "original_rule", None):
            rules.append((rule.original_rule, ROLE_FADED))
        for obj in rule_reference_objects(ctx, rule):
            highlights["objects"].append(object_ref(obj, role))
        highlight_bridges(highlights, list(getattr(rule, "supporting_bridges", []) or []), role)
        rules.append((rule, role))
        slipnet = _slipnet_block(
            "Top Rule Concepts" if role == ROLE_TOP else "Bottom Rule Concepts",
            [rule.get_concept_pattern()],
        )
        # ``(impose-theme-pattern (tell rule 'get-theme-pattern))`` (``trace.ss:976``).
        themes = [_json_pattern(rule.theme_pattern)] if rule.theme_pattern else []

    elif kind == T.SNAG:
        _snag_highlights(ctx, event, highlights, rules)
        slipnet = _slipnet_block("Snag Object Descriptors", [event.snag_concept_pattern])
        temperature = 100.0

    elif kind in (T.CLAMP_START, T.CLAMP_END):
        for rule in getattr(event, "rules", []) or []:
            rules.append((rule, ROLE_FADED))
        themes = list(getattr(event, "clamped_theme_patterns", []) or [])
        slipnet = _slipnet_block(
            "Concept Pattern", list(getattr(event, "clamped_concept_patterns", []) or [])
        )
        coderack = _codelet_pattern_block(ctx, event)

    elif kind == T.ANSWER_FOUND:
        _answer_highlights(ctx, event, highlights, rules)
        themes = []

    picture = {
        "version": PICTURE_VERSION,
        "kind": "event",
        "header": header(event, bool(getattr(ctx, "justify_mode", False))),
        "codelet_count": event.codelet_count,
        "temperature": temperature,
        "faded": True,
        "workspace": workspace_picture(ctx, rules=rules, answer_text=answer_text),
        "highlights": highlights,
        "slipnet": slipnet,
        "coderack": coderack,
        "themes": themes,
        "question_mark": kind == T.SNAG,
    }
    if kind == T.ANSWER_FOUND and event.slippage_log is not None:
        picture["translation"] = answer_translation_json(event)
    elif kind == T.SNAG and event.slippage_log is not None:
        picture["translation"] = snag_translation_json(event)
    return picture


def _codelet_pattern_block(ctx: Any, event: Any) -> dict:
    from server.engine.trace import CLAMP_TYPE_CODELET_BACKGROUNDS

    background = CLAMP_TYPE_CODELET_BACKGROUNDS.get(getattr(event, "clamp_type", ""))
    entries: list[dict] = []
    for pattern in getattr(event, "clamped_codelet_patterns", []) or []:
        if not pattern:
            continue
        try:
            resolved = ctx.coderack.resolve_codelet_pattern(pattern, background)
        except Exception:  # pragma: no cover
            continue
        entries.extend({"type": t, "urgency": u} for t, u in resolved)
    return {"title": "Codelet Pattern", "entries": entries, "blank": not entries}


def _snag_highlights(ctx: Any, event: Any, highlights: dict, rules: list) -> None:
    """``display-workspace`` of a snag (``trace.ss:1190-1211``)."""
    vertical = list(event.supporting_vertical_bridges or [])
    highlight_bridges(highlights, vertical, ROLE_VERTICAL)
    highlights["concept_mappings"].extend(applied_slippage_highlights(event.slippage_log))
    rule = event.snag_rule
    # ``(for* each obj in rule-ref-objects ...)`` (``trace.ss:1200``): the objects ``translate``
    # found for the rule, kept in the event.
    ref_objects = (
        list(event.rule_ref_objects)
        if event.slippage_log is not None
        else rule_reference_objects(ctx, rule)
    )
    for obj in ref_objects:
        highlights["objects"].append(object_ref(obj, ROLE_TOP))
    if rule is not None:
        highlight_bridges(highlights, list(getattr(rule, "supporting_bridges", []) or []), ROLE_TOP)
    for obj in event.snag_objects:
        if not _is_string(obj):
            highlights["objects"].append(object_ref(obj, ROLE_SNAG))
    if rule is not None:
        rules.append((rule, ROLE_TOP))
    if event.translated_rule is not None:
        rules.append((event.translated_rule, ROLE_SNAG))


def _answer_highlights(ctx: Any, event: Any, highlights: dict, rules: list) -> None:
    """``display-workspace`` of an answer (``trace.ss:439-464``)."""
    # ``(tell self 'get-supporting-bridges 'vertical)`` and the slippage log (``trace.ss:447-452``).
    logged = event.slippage_log is not None
    vertical = (
        list(event.supporting_vertical_bridges or [])
        if logged
        else [b for b in ctx.workspace.vertical_bridges if b.is_built]
    )
    highlight_bridges(highlights, vertical, ROLE_VERTICAL)
    highlights["concept_mappings"].extend(applied_slippage_highlights(event.slippage_log))
    refs = {ROLE_TOP: event.top_rule_ref_objects, ROLE_BOTTOM: event.bottom_rule_ref_objects}
    for rule, role in ((event.top_rule, ROLE_TOP), (event.bottom_rule, ROLE_BOTTOM)):
        if rule is None:
            continue
        for obj in (refs[role] if logged else rule_reference_objects(ctx, rule)):
            highlights["objects"].append(object_ref(obj, role))
        highlight_bridges(highlights, list(getattr(rule, "supporting_bridges", []) or []), role)
        rules.append((rule, role))


# ---------------------------------------------------------------------------
# Descriptions kept in Episodic Memory (answers and snags)
# ---------------------------------------------------------------------------

def _theme_supporting(pattern: dict | None, bridges: list) -> list[tuple[Any, Any]]:
    """``get-theme-supporting-concept-mappings`` (``answers.ss:223``).

    The ``(bridge, cm)`` pairs whose ``(dimension, relation)`` the theme pattern names,
    with the whole/single mappings (``remove-whole/single-concept-mappings``) dropped.
    """
    from server.engine.themes import relation_name_for_label

    if not pattern:
        return []
    out = []
    for bridge in bridges:
        for cm in bridge.get_all_concept_mappings():
            names = {getattr(cm.descriptor1, "name", ""), getattr(cm.descriptor2, "name", "")}
            if names == {"plato-whole", "plato-single"}:
                continue
            dimension = getattr(cm.description_type1, "name", "")
            relation = relation_name_for_label(cm.label)
            if pattern.get(dimension) == relation or (
                dimension == "plato-bond-category"
                and pattern.get("plato-group-category") == relation
            ):
                out.append((bridge, cm))
    return out


def _describe(
    ctx: Any,
    *,
    title: str,
    groups: list,
    theme_bridges: list,
    vertical: list,
    top_rule: Any,
    bottom_rule: Any,
    bottom_role: str,
    theme_pattern: dict | None,
    answer_text: str | None,
    temperature: float,
    themes: list,
    top_bridges: list,
    bottom_bridges: list,
    snag_objects: list | None = None,
    question_mark: bool = False,
    slippage_log: Any = None,
    top_refs: list | None = None,
    bottom_refs: list | None = None,
    translation: dict | None = None,
) -> dict:
    """The shared body of ``make-answer-description-pexp`` / ``make-snag-description-pexp``."""
    highlights = _new_highlights()
    rules: list[tuple[Any, str]] = []
    # Theme bridges are drawn with their endpoints, then the vertical mapping is
    # highlighted over them.
    vertical_all: list = []
    for b in list(theme_bridges) + list(vertical):
        if not any(b is x for x in vertical_all):
            vertical_all.append(b)
    highlight_bridges(highlights, list(vertical), ROLE_VERTICAL)
    for bridge, cm in _theme_supporting(theme_pattern, theme_bridges):
        highlights["concept_mappings"].append(cm_highlight(bridge, cm, ROLE_THEME_CM))
    highlights["concept_mappings"].extend(applied_slippage_highlights(slippage_log))
    if top_rule is not None:
        for obj in (top_refs if top_refs is not None else rule_reference_objects(ctx, top_rule)):
            highlights["objects"].append(object_ref(obj, ROLE_TOP))
        highlight_bridges(highlights, top_bridges, ROLE_TOP)
        rules.append((top_rule, ROLE_TOP))
    if bottom_rule is not None:
        if bottom_role != ROLE_SNAG:
            for obj in (
                bottom_refs if bottom_refs is not None else rule_reference_objects(ctx, bottom_rule)
            ):
                highlights["objects"].append(object_ref(obj, ROLE_BOTTOM))
            highlight_bridges(highlights, bottom_bridges, ROLE_BOTTOM)
        rules.append((bottom_rule, bottom_role))
    for obj in snag_objects or []:
        if not _is_string(obj):
            highlights["objects"].append(object_ref(obj, ROLE_SNAG))

    # Nested groups under a supporting group are drawn as well.
    all_groups: list = []
    for g in list(groups) + [
        o for b in vertical_all for o in (b.object1, b.object2) if hasattr(o, "objects")
    ]:
        if not any(g is x for x in all_groups):
            all_groups.append(g)

    return {
        "version": PICTURE_VERSION,
        "kind": "description",
        "header": title,
        "codelet_count": None,
        "temperature": temperature,
        "faded": False,
        "workspace": workspace_picture(
            ctx,
            groups=all_groups,
            bridges={"top": top_bridges, "vertical": vertical_all, "bottom": bottom_bridges},
            rules=rules,
            answer_text=answer_text,
        ),
        "highlights": highlights,
        "slipnet": _blank_slipnet(),
        "coderack": _blank_coderack(),
        "themes": themes,
        "question_mark": question_mark,
        **({"translation": translation} if translation is not None else {}),
    }


def build_answer_description_picture(
    ctx: Any, *, top_rule: Any, bottom_rule: Any, description: Any, unjustified: bool,
    event: Any = None,
) -> dict:
    """``make-answer-description-pexp`` (``trace.ss:466-516``) for the answer just found.

    *event* is the answer event: its supporting vertical bridges, supporting groups, slippage
    log and reference objects are what Metacat draws.  Without one (an older caller) the
    picture falls back to every built vertical bridge and to groups derived from the rules.
    """
    ws = ctx.workspace
    workspace_vertical = [b for b in ws.vertical_bridges if b.is_built]
    logged = event is not None and event.slippage_log is not None
    vertical = list(event.supporting_vertical_bridges) if logged else workspace_vertical
    pattern = dict(description.vertical_themes or {})
    # ``(filter-meth (tell *workspace* 'get-bridges 'vertical) 'supports-theme-pattern? ...)``
    # (``memory.ss:409``): every vertical bridge of the Workspace, not only the supporting ones.
    theme_bridges = [
        b for b in workspace_vertical
        if _theme_supporting(pattern, [b])
    ] or []
    top_bridges = list(getattr(top_rule, "supporting_bridges", []) or [])
    bottom_bridges = list(getattr(bottom_rule, "supporting_bridges", []) or [])
    supporting: list = []
    if logged:
        # ``(for* each g in supporting-groups ...)`` (``trace.ss:479``).
        supporting = list(event.supporting_groups)
    else:
        def add_group(g: Any) -> None:
            if hasattr(g, "objects") and not any(g is x for x in supporting):
                supporting.append(g)
                for sub in g.objects:
                    add_group(sub)

        for obj in rule_reference_objects(ctx, top_rule) + rule_reference_objects(ctx, bottom_rule):
            add_group(obj)
        for b in top_bridges + bottom_bridges + vertical:
            add_group(b.object1)
            add_group(b.object2)
    return jsonable(_describe(
        ctx,
        title="Unjustified Answer Description" if unjustified else "Answer Description",
        groups=supporting,
        theme_bridges=theme_bridges,
        vertical=vertical,
        top_rule=top_rule,
        bottom_rule=bottom_rule,
        bottom_role=ROLE_BOTTOM,
        theme_pattern=pattern,
        answer_text=description.problem[3] if description.problem else None,
        temperature=description.temperature,
        themes=[
            {"type": "vertical_bridge", "entries": description.vertical_themes or description.themes},
            {"type": "top_bridge", "entries": description.top_themes},
            {"type": "bottom_bridge", "entries": description.bottom_themes},
        ],
        top_bridges=top_bridges,
        bottom_bridges=bottom_bridges,
        slippage_log=event.slippage_log if logged else None,
        top_refs=list(event.top_rule_ref_objects) if logged else None,
        bottom_refs=list(event.bottom_rule_ref_objects) if logged else None,
        translation=answer_translation_json(event) if logged else None,
    ))


def answer_translation_json(event: Any) -> dict:
    """The translation block of an answer's pictures (see :func:`translation_json`)."""
    return translation_json(
        slippage_log=event.slippage_log,
        supporting_vertical_bridges=event.supporting_vertical_bridges,
        supporting_groups=event.supporting_groups,
        top_ref_objects=event.top_rule_ref_objects,
        bottom_ref_objects=event.bottom_rule_ref_objects,
    )


def snag_translation_json(event: Any) -> dict | None:
    """The translation block of a snag's pictures; ``None`` for a snag with no log."""
    if event.slippage_log is None:
        return None
    return translation_json(
        slippage_log=event.slippage_log,
        supporting_vertical_bridges=event.supporting_vertical_bridges,
        top_ref_objects=event.rule_ref_objects,
    )


def build_snag_description_picture(
    ctx: Any, *, event: Any, theme_pattern: Any
) -> dict:
    """``make-snag-description-pexp`` (``trace.ss:1212-1250``)."""
    ws = ctx.workspace
    vertical = list(event.supporting_vertical_bridges or [])
    snag_bridges = list(event.snag_bridges or [])
    pattern = {
        entry[0]: entry[1] for entry in (event.snag_theme_pattern or [])[1:]
        if isinstance(entry, (list, tuple)) and len(entry) >= 2
    }
    theme_bridges = snag_bridges or [
        b for b in ws.vertical_bridges if b.is_built and _theme_supporting(pattern, [b])
    ]
    rule = event.snag_rule
    top_bridges = list(getattr(rule, "supporting_bridges", []) or [])
    return jsonable(_describe(
        ctx,
        title="Snag Description",
        groups=[g for s in ws.all_strings for g in s.groups if g.is_built],
        theme_bridges=theme_bridges,
        vertical=vertical,
        top_rule=rule,
        bottom_rule=event.translated_rule,
        bottom_role=ROLE_SNAG,
        theme_pattern=pattern,
        answer_text=None,
        temperature=100.0,
        themes=[theme_pattern] if theme_pattern else [],
        top_bridges=top_bridges,
        bottom_bridges=[],
        snag_objects=list(event.snag_objects or []),
        question_mark=True,
        slippage_log=event.slippage_log,
        top_refs=list(event.rule_ref_objects) if event.slippage_log is not None else None,
        translation=snag_translation_json(event),
    ))


def jsonable(picture: dict) -> dict:
    """The picture as plain JSON, whatever the patterns it was built from held.

    A picture is stored in a JSON column and served as it is, and a clamp's patterns
    are the engine's own (tuples, sometimes nodes).  Anything that is not JSON is
    spelled by ``str``, so a picture can never be the reason a row will not write.
    """
    return json.loads(json.dumps(picture, default=str))


def attach_picture(ctx: Any, event: Any) -> None:
    """Name *event* and capture its picture.  Called as the Trace records it.

    Never raises: a display aid must not be able to stop a run.
    """
    try:
        event.print_name = print_name(event)
    except Exception:  # pragma: no cover
        logger.exception("could not name trace event %s", getattr(event, "event_type", "?"))
        event.print_name = event.description or event.event_type
    if ctx is None:
        return
    try:
        event.picture = jsonable(build_event_picture(ctx, event))
    except Exception:  # pragma: no cover
        logger.exception("could not capture a picture of trace event %s", event.event_type)
        event.picture = None
