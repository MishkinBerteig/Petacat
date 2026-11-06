"""The four-string frame: how a problem's strings relate, defined once in the configuration.

A problem has four strings (initial, modified, target and, once an answer exists, answer) and
bridges between them.  *Which* bridge type joins which pair of strings, in which orientation,
which theme type it feeds, which rule type describes which pair, and which kind of string is
there from the start are cognition: they decide what each object is asked to map to, which
themes a description speaks for, and what a rule is a rule about.  They were written in six
places.  They are now three tables, and this module derives everything else from them, once
per run (``RunConstants.frame``, resolved at ``init_mcat``):

* ``string_kinds``: the kinds in order (``sort_order`` is the numeric backends' code for the
  kind) and ``exists_at_start``;
* ``bridge_types``: ``from_string_kind``, ``to_string_kind``, ``orientation``, ``theme_type``;
* ``rule_types``: ``bridge_type``, the bridge type whose pair of strings a rule describes.

What is derived (the table of each is below), so none of it can disagree with the tables:

* ``facts(kind)``: ``(maps_horizontal, maps_vertical, horizontal_needs_justify)``.  A kind
  maps in an orientation when a bridge type of that orientation ends in it and the string at
  the other end exists from the start.  It needs justification for the horizontal orientation
  when the string at the other end does not (the target string reaches the answer string only
  when the run justifies).  A name that is none of the kinds maps nowhere.
* ``other_kind(kind, key)``: what ``get-other-string`` answers (``workspace.ss:161-172``).
* ``theme_types``, ``discovery_theme_types``, ``theme_types_of(kind)`` and the maps between a
  bridge type and the theme type it feeds.
* ``orientation_of(bridge_type)``, ``bridge_ends`` and ``rule`` facts.

The engine's *attribute names* (``top_bridges``, ``initial_string``, ``top_mapping_strength``)
are Python names the engine owns (ruling 13); the tables here map the engine's role for a row to
them.  Control flow stays in the engine; the membership is read.

Multi-turn runs (v2.0) will need a different frame between turns; the frame is one record, built
from the provider, so a run that changes its configuration between turns builds another.  Nothing
is built here for that.
"""

from __future__ import annotations

from typing import Any

#: The engine's attribute for each role of the frame (Python names, not vocabulary).
STRING_ATTR = {
    "string_kind.initial": "initial_string",
    "string_kind.modified": "modified_string",
    "string_kind.target": "target_string",
    "string_kind.answer": "answer_string",
}
BRIDGE_LIST_ATTR = {
    "bridge_type.top": "top_bridges",
    "bridge_type.bottom": "bottom_bridges",
    "bridge_type.vertical": "vertical_bridges",
}
BRIDGE_STRENGTH_ATTR = {
    "bridge_type.top": "top_mapping_strength",
    "bridge_type.bottom": "bottom_mapping_strength",
    "bridge_type.vertical": "vertical_mapping_strength",
}
BRIDGE_INTER_ATTR = {
    "bridge_type.top": "average_top_inter_string_unhappiness",
    "bridge_type.bottom": "average_bottom_inter_string_unhappiness",
    "bridge_type.vertical": "average_vertical_inter_string_unhappiness",
}
RULE_POSSIBLE_ATTR = {
    "rule_type.top": "top_rule_possible",
    "rule_type.bottom": "bottom_rule_possible",
}


_MAPS_NOWHERE = (False, False, False)

#: The token ``WorkspaceObject.mapped`` takes for "a horizontal and a vertical bridge" (the engine's own).
BOTH_ORIENTATIONS = "both"


class BridgeFrame:
    """One bridge type of the frame, with everything the engine reads about it."""

    __slots__ = (
        "name", "orientation", "theme_type", "from_kind", "to_kind", "from_attr", "to_attr",
        "list_attr", "strength_attr", "inter_attr", "discovery",
    )

    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


class RuleFrame:
    """One rule type: the bridge type it describes, and what that makes of it."""

    __slots__ = ("name", "bridge", "possible_attr", "needs_justify")

    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


class Frame:
    """The derived frame of one configuration (see the module docstring)."""

    __slots__ = (
        "kind_names", "string_attr", "_facts", "bridges", "bridge", "orientation",
        "theme_types", "discovery_theme_types", "theme_type_for", "bridge_for_theme_type",
        "_theme_types_of", "_all_theme_types", "_partner", "_partner_default", "horizontal_bridge_of",
        "horizontal_partner", "rules", "rule", "going_down_kinds", "vertical_pair", "_unknown_theme_types",
        "justify_bridges", "discovery_bridges", "justify_only_bridge_names", "mapped_tokens",
        "vertical_names", "vertical_kinds", "default_orientation", "rule_theme_types", "default_rule_theme_type",
        "default_mapped_token",
    )

    def __init__(self, meta: Any) -> None:
        v = meta.vocabulary
        kinds = list(meta.string_kinds)
        self.kind_names: tuple[str, ...] = tuple(k.name for k in kinds)
        at_start = {k.name: k.exists_at_start for k in kinds}
        self.string_attr: dict[str, str] = {
            k.name: STRING_ATTR[k.role] for k in kinds if k.role in STRING_ATTR
        }
        horizontal, vertical = v.bridge_orientation_horizontal, v.bridge_orientation_vertical

        bridges: list[BridgeFrame] = []
        for b in meta.bridge_types:
            if (
                b.role not in BRIDGE_LIST_ATTR
                or b.from_string_kind not in at_start
                or b.to_string_kind not in at_start
                or not b.orientation
                or not b.theme_type
            ):
                continue
            bridges.append(BridgeFrame(
                name=b.name, orientation=b.orientation, theme_type=b.theme_type,
                from_kind=b.from_string_kind, to_kind=b.to_string_kind,
                from_attr=self.string_attr.get(b.from_string_kind),
                to_attr=self.string_attr.get(b.to_string_kind),
                list_attr=BRIDGE_LIST_ATTR[b.role], strength_attr=BRIDGE_STRENGTH_ATTR[b.role],
                inter_attr=BRIDGE_INTER_ATTR[b.role],
                discovery=at_start[b.from_string_kind] and at_start[b.to_string_kind],
            ))
        self.bridges: tuple[BridgeFrame, ...] = tuple(bridges)
        self.bridge: dict[str, BridgeFrame] = {b.name: b for b in bridges}
        self.orientation: dict[str, str] = {b.name: b.orientation for b in bridges}
        #: The bridge types of the vertical orientation (a test of "is this bridge vertical" is a
        #: membership test, and a name that is none of the bridge types is not vertical), and the
        #: orientation a name that is none of them is read as (the vertical one: Metacat's ``else``).
        self.vertical_names: frozenset[str] = frozenset(
            b.name for b in bridges if b.orientation == vertical
        )
        self.default_orientation: str = vertical
        #: The bridge types that exist in every run, and those a run has only when it justifies
        #: (the answer string is one end), each in table order.
        self.discovery_bridges: tuple[BridgeFrame, ...] = tuple(b for b in bridges if b.discovery)
        self.justify_bridges: tuple[BridgeFrame, ...] = self.bridges
        self.justify_only_bridge_names: frozenset[str] = frozenset(b.name for b in bridges if not b.discovery)

        # What each kind maps in each orientation, and whether it needs a justification run.
        facts: dict[str, tuple[bool, bool, bool]] = {}
        for name in self.kind_names:
            maps_h = maps_v = needs = False
            for b in bridges:
                if name == b.from_kind:
                    other = b.to_kind
                elif name == b.to_kind:
                    other = b.from_kind
                else:
                    continue
                if b.orientation == horizontal:
                    if at_start[other]:
                        maps_h = True
                    else:
                        needs = True
                elif b.orientation == vertical and at_start[other]:
                    maps_v = True
            facts[name] = (maps_h, maps_v, needs)
        self._facts = facts

        # The theme types, in the order of the bridge types that feed them.
        self.theme_types: tuple[str, ...] = tuple(b.theme_type for b in bridges)
        self.discovery_theme_types: tuple[str, ...] = tuple(b.theme_type for b in self.discovery_bridges)
        self.theme_type_for: dict[str, str] = {}
        self.bridge_for_theme_type: dict[str, str] = {}
        for b in bridges:
            self.theme_type_for[b.name] = b.theme_type
            self.theme_type_for[b.theme_type] = b.theme_type
            self.bridge_for_theme_type[b.theme_type] = b.name
        self._all_theme_types = self.theme_types
        # A kind's theme types: those of the bridge types that end in it.  When the other end is
        # not there from the start the theme type counts only while the Themespace is
        # considering it (justify mode), which is the second tuple.
        theme_types_of: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        for name in self.kind_names:
            always: list[str] = []
            conditional: list[str] = []
            for b in bridges:
                if name not in (b.from_kind, b.to_kind):
                    continue
                other = b.to_kind if name == b.from_kind else b.from_kind
                (always if at_start[other] else conditional).append(b.theme_type)
            theme_types_of[name] = (tuple(always), tuple(conditional))
        self._theme_types_of = theme_types_of
        self._unknown_theme_types = (self._all_theme_types, ())

        # ``get-other-string``: through the bridge types the key names (a bridge type name or an
        # orientation name) that end in the kind; when none does, across the kind's last bridge
        # type in table order (Metacat's ``else`` branch).
        partner: dict[str, dict[str, str]] = {}
        partner_default: dict[str, str] = {}
        keys = [b.name for b in bridges] + sorted({b.orientation for b in bridges})
        for name in self.kind_names:
            touching = [b for b in bridges if name in (b.from_kind, b.to_kind)]
            if not touching:
                continue
            def across(b: BridgeFrame) -> str:
                return b.to_kind if name == b.from_kind else b.from_kind
            table: dict[str, str] = {}
            for key in keys:
                for b in touching:
                    if key == b.name or key == b.orientation:
                        table[key] = across(b)
                        break
            partner[name] = table
            partner_default[name] = across(touching[-1])
        self._partner = partner
        self._partner_default = partner_default

        # The bridge type of each kind's horizontal orientation, and the kind across it.
        self.horizontal_bridge_of: dict[str, str] = {}
        self.horizontal_partner: dict[str, str] = {}
        for name in self.kind_names:
            for b in bridges:
                if b.orientation == horizontal and name in (b.from_kind, b.to_kind):
                    self.horizontal_bridge_of[name] = b.name
                    self.horizontal_partner[name] = b.to_kind if name == b.from_kind else b.from_kind
                    break
        vertical_bridges = [b for b in bridges if b.orientation == vertical]
        #: The two kinds of string the (first) vertical bridge type joins.
        self.vertical_kinds: tuple[str | None, str | None] = (
            (vertical_bridges[0].from_kind, vertical_bridges[0].to_kind) if vertical_bridges else (None, None)
        )
        self.vertical_pair: tuple[str, str] | None = (
            (vertical_bridges[0].from_attr, vertical_bridges[0].to_attr) if vertical_bridges else None
        )

        # ``unmapped?`` (``workspace.ss:708-716``): which bridges an object needs to count as
        # mapped, as the token ``WorkspaceObject.mapped`` takes, without and with justifying.
        tokens: list[dict[str, str]] = [{}, {}]
        for justify in (0, 1):
            for name, (h, vert, needs) in facts.items():
                wants_h = h or (needs and bool(justify))
                tokens[justify][name] = (
                    BOTH_ORIENTATIONS if wants_h and vert else horizontal if wants_h else vertical
                )
        self.mapped_tokens: tuple[dict[str, str], dict[str, str]] = (tokens[0], tokens[1])
        #: A name that is none of the kinds is asked for its horizontal bridge only.
        self.default_mapped_token: str = horizontal

        # Rule types: each describes the pair of strings of one bridge type.
        rules: list[RuleFrame] = []
        for r in meta.rule_types:
            b = self.bridge.get(r.bridge_type or "")
            if b is None or r.role not in RULE_POSSIBLE_ATTR:
                continue
            rules.append(RuleFrame(
                name=r.name, bridge=b, possible_attr=RULE_POSSIBLE_ATTR[r.role],
                needs_justify=not b.discovery,
            ))
        self.rules: tuple[RuleFrame, ...] = tuple(rules)
        self.rule: dict[str, RuleFrame] = {r.name: r for r in rules}
        #: The theme type a rule of each type feeds (its bridge type's); a rule type that is none
        #: of them feeds the last one's (Metacat's ``else``).
        self.rule_theme_types: dict[str, str] = {r.name: r.bridge.theme_type for r in rules}
        self.default_rule_theme_type: str | None = rules[-1].bridge.theme_type if rules else None
        top = self.rule.get(v.rule_type_top)
        #: The kinds of the top rule's pair of strings: a rule translated *from* one of them goes
        #: down to the other pair (``answers.ss:1459-1472``).
        self.going_down_kinds: frozenset[str] = (
            frozenset((top.bridge.from_kind, top.bridge.to_kind)) if top is not None else frozenset()
        )

    # -- the string kinds ------------------------------------------------------------------

    def facts(self, kind: str | None) -> tuple[bool, bool, bool]:
        """``(maps_horizontal, maps_vertical, horizontal_needs_justify)`` of a kind; a name that
        is none of the kinds maps nowhere."""
        return self._facts.get(kind, _MAPS_NOWHERE)

    def other_kind(self, kind: str, key: str) -> str | None:
        """The kind across from *kind* for *key* (a bridge type or orientation name), or ``None``
        for a kind no bridge type ends in."""
        table = self._partner.get(kind)
        if table is None:
            return None
        return table.get(key) or self._partner_default[kind]

    def kind_theme_types(self, kind: str | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """``(always, conditional)``: the theme types a description of an object in a string of
        *kind* speaks to (``get-theme-types``, ``descriptions.ss:54-61``).

        They are the theme types of the bridge types that end in the kind.  A theme type whose
        bridge needs a string that is not there from the start (the target string's bottom
        bridge needs the answer string) is *conditional*: it counts only while the Themespace is
        considering it (justify mode).  A kind that is none of the kinds speaks to every theme
        type.
        """
        return self._theme_types_of.get(kind, self._unknown_theme_types)
