"""Test configurations whose codelet bodies call ``propose_ops``: the v2.0 Base plus one codelet type.

The v2.0 Base's ``consolidator`` proposes a count and links of its own for the symbols a run holds, so the tests of
what a run proposes through ``propose_ops`` use a test configuration, which keeps ``consolidator`` out of the way
(its posting rule is removed): the Base, one extra codelet
type ``noticer`` and a bottom-up posting rule that posts it once in every update cycle, so it runs many
times in a run (a different number of times for each seed).

``PAIR_BODY`` expresses a noticing of the pair ``plato-a`` to ``plato-b`` the way the ``consolidator``
body does: ``add_link`` of the pair at length ``L / r`` and ``scale`` of that link's length by ``r``, where
``r = 1 - s / L`` (``L`` = 90, ``s`` = 1/16).  The first noticing leaves the link at exactly ``L``, and every later one
multiplies it by ``r``.  So after ``N`` noticings, in any order and spread over any runs, the link is
``L * r ** (N - 1)`` long, to the rounding of float multiplication in a different order (the tests allow a relative
error of ``TOLERANCE``).  It approaches 0 and is never 0 or below.
"""

from __future__ import annotations

import math
from typing import Any

from server.services import config_document as cd
from server.services import training_base as tb
from server.services.change_resolve import resolve

LENGTH, STEP = 90, 0.0625
RATIO = 1 - STEP / LENGTH
#: Float multiplication in a different order differs in the last bits; ``N`` is at most a few thousand.
TOLERANCE = 1e-12
PAIR = ("plato-a", "plato-b", "adjacent", "")
PAIR_KEY = {"from_node": "plato-a", "to_node": "plato-b", "link_type": "adjacent", "label_node": ""}

PAIR_BODY = """
key = {'from_node': 'plato-a', 'to_node': 'plato-b', 'link_type': 'adjacent', 'label_node': ''}
ratio = 1 - 0.0625 / 90
propose_ops([
    {'op': 'add_link', 'from': 'plato-a', 'to': 'plato-b', 'type': 'adjacent', 'fixed': True, 'length': 90 / ratio},
    {'op': 'scale', 'table': 'slipnet_link_defs', 'key': key, 'field': 'link_length', 'factor': ratio},
])
"""

#: Every kind of op a body can propose: a link type, a link, a count and a trigger, besides the pair.
ALL_BODY = """
key = {'from_node': 'plato-a', 'to_node': 'plato-b', 'link_type': 'adjacent', 'label_node': ''}
near = {'from_node': 'plato-b', 'to_node': 'plato-c', 'link_type': 'near', 'label_node': ''}
ratio = 1 - 0.0625 / 90
propose_ops([
    {'op': 'add_link_type', 'name': 'near', 'display_label': 'Near'},
    {'op': 'add_link', 'from': 'plato-a', 'to': 'plato-b', 'type': 'adjacent', 'fixed': True, 'length': 90 / ratio},
    {'op': 'scale', 'table': 'slipnet_link_defs', 'key': key, 'field': 'link_length', 'factor': ratio},
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
    """How many times a ``PAIR_BODY`` run noticed the pair: its ``scale`` factor is ``r`` to that power."""
    (factor,) = [p["factor"] for p in outcome.proposals if p["op"] == "scale" and p["field"] == "link_length"]
    count = round(math.log(factor) / math.log(RATIO))
    assert count >= 1 and math.isclose(factor, RATIO ** count, rel_tol=TOLERANCE)
    return count


def expected_length(noticings: int) -> float:
    """``L * r ** (N - 1)``: the pair's link after ``N`` noticings (in any number of runs, in any order)."""
    return LENGTH * RATIO ** (noticings - 1)
