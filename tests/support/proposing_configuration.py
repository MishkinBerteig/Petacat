"""Test configurations whose codelet bodies call ``propose_ops``: the v2.0 Base plus one codelet type.

The v2.0 Base's ``consolidator`` proposes a count and links of its own for the symbols a run holds, so the tests of
what a run proposes through ``propose_ops`` use a test configuration, which keeps ``consolidator`` out of the way
(its posting rule is removed): the Base, one extra codelet
type ``noticer`` and a bottom-up posting rule that posts it once in every update cycle, so it runs many
times in a run (a different number of times for each seed).

``PAIR_BODY`` expresses a noticing of the pair ``plato-a`` to ``plato-b`` the way the ``consolidator``
body does: ``add_link`` of the pair at length ``L + s`` (``L`` = 90, ``s`` = 0.125, both exact in binary)
and ``adjust`` of that link's length by ``-s``.  So after ``N`` noticings, in any order and spread over
any runs, the link is ``L - s * (N - 1)`` long.
"""

from __future__ import annotations

from typing import Any

from server.services import config_document as cd
from server.services import training_base as tb
from server.services.change_resolve import resolve

LENGTH, STEP = 90, 0.125
PAIR = ("plato-a", "plato-b", "adjacent", "")
PAIR_KEY = {"from_node": "plato-a", "to_node": "plato-b", "link_type": "adjacent", "label_node": ""}

PAIR_BODY = """
key = {'from_node': 'plato-a', 'to_node': 'plato-b', 'link_type': 'adjacent', 'label_node': ''}
propose_ops([
    {'op': 'add_link', 'from': 'plato-a', 'to': 'plato-b', 'type': 'adjacent', 'fixed': True, 'length': 90.125},
    {'op': 'adjust', 'table': 'slipnet_link_defs', 'key': key, 'field': 'link_length', 'by': -0.125},
])
"""

#: Every kind of op a body can propose: a link type, a link, a count and a trigger, besides the pair.
ALL_BODY = """
key = {'from_node': 'plato-a', 'to_node': 'plato-b', 'link_type': 'adjacent', 'label_node': ''}
near = {'from_node': 'plato-b', 'to_node': 'plato-c', 'link_type': 'near', 'label_node': ''}
propose_ops([
    {'op': 'add_link_type', 'name': 'near', 'display_label': 'Near'},
    {'op': 'add_link', 'from': 'plato-a', 'to': 'plato-b', 'type': 'adjacent', 'fixed': True, 'length': 90.125},
    {'op': 'adjust', 'table': 'slipnet_link_defs', 'key': key, 'field': 'link_length', 'by': -0.125},
    {'op': 'add_link', 'from': 'plato-b', 'to': 'plato-c', 'type': 'near', 'fixed': True, 'length': 12.5},
    {'op': 'adjust', 'table': 'slipnet_node_defs', 'key': {'name': 'plato-b'}, 'field': 'noticings', 'by': 1},
    {'op': 'add_trigger', 'rule_key': 'top-down-description-scout', 'node': 'plato-b'},
])
"""


def noticer_ops(body: str) -> list[dict[str, Any]]:
    return [
        {"op": "add_codelet_type", "name": "noticer", "fields": {
            "family": "description", "phase": "scout", "description": "a test body that proposes",
            "execute_body": body}},
        {"op": "add_posting_rule", "rule_key": "noticer", "fields": {
            "codelet_type": "noticer", "direction": "bottom_up", "urgency_level": "low",
            "posting_formula": "1.0", "count_formula": "fixed", "count_values": {"fixed": 1}, "condition": "True"}},
    ]


def noticer_document(body: str = PAIR_BODY, *more: dict[str, Any]) -> cd.ConfigDocument:
    """The v2.0 Base without ``consolidator``'s posting rule, with the test codelet type (and any *more* ops) applied."""
    doc = tb.resolve_base().document
    resolved, _ = resolve(doc, {"ops": [{"op": "remove_posting_rule", "rule_key": "consolidator"},
                                        *noticer_ops(body), *more]})
    return cd.apply_resolved(doc, resolved)


def noticer_provider(body: str = PAIR_BODY, *more: dict[str, Any]):
    return cd.provider(noticer_document(body, *more))


def noticings_of(outcome) -> int:
    """How many times a ``PAIR_BODY`` run noticed the pair: its ``adjust`` is ``-STEP`` times that."""
    (by,) = [p["by"] for p in outcome.proposals if p["op"] == "adjust" and p["field"] == "link_length"]
    count = by / -STEP
    assert count == int(count) and count >= 1
    return int(count)
