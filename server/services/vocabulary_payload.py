"""The run's bound vocabulary, as the client receives it.

The engine owns the *roles* (``bridge_type.top``); the run's configuration binds each to the
name of an enum-table row.  The client compares the names it receives (a trace event's
``event_type``, a bridge's kind, a theme cluster's ``theme_type``, a string's kind ...) through
this payload instead of against literal names, so renaming a bound row in the configuration
cannot break a display.

Published once per run, with the run's own creation / load response (``RunResponse``) and the
recorded-run summary of review::

    {"vocabulary": {"bridge_type.top": "top", ...},
     "link_behaviours": {"lateral_sliplink": "slip", ...}}

``link_behaviours`` maps every link type's name to its behaviour; a link type with no behaviour
maps to ``None`` (JSON null).  The client compares a link by behaviour, never by name.
"""

from __future__ import annotations

from typing import Any


def vocabulary_payload(meta: Any) -> dict[str, Any]:
    """The two maps for a run whose own configuration is *meta* (a ``MetadataProvider``)."""
    return {
        "vocabulary": {str(b.role): str(b.name) for b in meta.vocabulary_bindings},
        "link_behaviours": {str(s.name): s.behaviour for s in meta.link_types},
    }


def run_vocabulary_payload(service: Any, run_id: int) -> dict[str, Any]:
    """The payload for run *run_id*: from the run's own provider while its runner is loaded.

    A run whose runner is gone (it ended and was evicted, or the server restarted) has no
    provider in memory; the configuration store's current one answers, which is the best the
    server holds for it.
    """
    runner = service.get_runner(run_id)
    ctx = getattr(runner, "ctx", None)
    meta = getattr(ctx, "meta", None)
    return vocabulary_payload(meta if meta is not None else service.meta)
