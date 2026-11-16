"""The v2.0 Base with ``consolidator`` posted at every gate pass, for tests of what a noticing does.

The v2.0 Base posts ``consolidator`` in Metacat's top-down form (posting probability ``average_unhappiness / 100``, urgency
``conceptual_depth * activation / 100``), so a run notices a symbol rarely.  A test of the mechanism that
noticings drive (counts, links, a taught session) needs noticings; it uses the Base with the rule's two formulas set to
the earlier ones: probability 1 and urgency half the activation, rounded.  Nothing else changes.
"""

from __future__ import annotations

from server.services import config_document as cd
from server.services.change_resolve import resolve


def every_noticing(document: cd.ConfigDocument) -> cd.ConfigDocument:
    ops, _ = resolve(document, {"ops": [{
        "op": "update", "table": "posting_rules", "key": {"rule_key": "consolidator"},
        "fields": {"urgency_formula": "round(activation / 2)", "posting_formula": "1.0"}}]})
    return cd.apply_resolved(document, ops)
