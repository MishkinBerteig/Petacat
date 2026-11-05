"""The effects table: what every builtin and every codelet type reads and writes.

A speculative prefix runs against live state while earlier steps commit, so it is only
exact if we know -- conservatively -- which pieces of shared state it may have read
(they must be unchanged when it commits) and which a step may write once it holds the
commit token (their seqlock versions must be bumped around the write).  The unit is a
*component*:

``workspace``     built structures, objects, descriptions, strings' lists and slot arrays,
                  the bridge and rule lists, and the per-object values an update cycle
                  refreshes (everything reachable from ``ctx.workspace``);
``slipnet_act``   what readers read of the Slipnet: activations, clamps, frozen flags;
``slipnet_buf``   ``activation_buffer``: codelets only ever ``+=`` into it and only the
                  update cycle reads it (so it is never a conflict); versioned anyway;
``themespace``, ``trace``, ``memory``, ``temperature``, ``coderack``;
``ids``           the id allocator;
``verbose``       the narration log;
``ctx``           ``ctx`` scalars: pending answer, gave_up, ``last_failure*``, ``run_ended``;
``sink``          output callbacks (written only by code that holds the token).

Anything not listed here is ``WRITE`` of everything: an unclassified builtin can be
called speculatively and is trapped, so a missing entry costs speed, never exactness.

The table is data (``effects_data.json`` beside this file) so that it can be audited and
diffed.  ``tests/parallel/test_effects.py`` checks it against the live builtin registry
and the 27 codelet bodies, and the hidden-write detector checks its READ claims
empirically on real runs.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

READ = "READ"
WRITE = "WRITE"
BARRIER = "BARRIER"

COMPONENTS = (
    "workspace", "slipnet_act", "slipnet_buf", "themespace", "trace", "memory",
    "temperature", "coderack", "ids", "verbose", "ctx", "sink",
)
NCOMP = len(COMPONENTS)
BIT = {name: 1 << i for i, name in enumerate(COMPONENTS)}
ALL = (1 << NCOMP) - 1

_ALIASES = {"ctx_scalars": "ctx", "proposals": None}


def body_digest(source: str) -> str:
    """The digest of a codelet body's source, as stored in ``effects_data.json``.

    The audit of a type's masks is an audit of one body.  Training-Mode learning can edit a
    body under an audited name, so the table is trusted for a type only while the body that is
    about to run has the digest the audit saw (:meth:`Effects.info`).
    """
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def support_digest(meta: Any) -> str:
    """The digest of the configuration's descriptor predicates, as stored in ``effects_data.json``.

    A body digest covers a codelet body only.  A descriptor predicate is a Python expression that
    audited builtins evaluate (``possible_descriptor`` and ``Slipnet.get_possible_descriptors``,
    called from the top-down description scout and from the thematic bridge scout), so what it
    does is part of what the audit saw.  A configuration whose predicates differ from the audited
    ones is not audited (:meth:`Effects.info`).

    Posting, urgency and count formulas and posting conditions are not covered, on purpose: they
    are evaluated only by ``EngineRunner._update_cycle``, the opening posting and the snag
    restart (``runner.py``, ``update_cycle.py``), all of which run on the coordinator with
    nothing in flight, and never inside a speculated codelet prefix.
    """
    h = hashlib.sha256()
    for name in sorted(meta.slipnet_node_specs):
        h.update(json.dumps(["node", name, meta.slipnet_node_specs[name].descriptor_predicate]).encode("utf-8"))
    return h.hexdigest()


def mask(names) -> int:
    m = 0
    for n in names:
        n = _ALIASES.get(n, n)
        if n is None:
            continue
        m |= BIT[n]
    return m


def names(m: int) -> list[str]:
    return [c for c in COMPONENTS if m & BIT[c]]


@dataclass(frozen=True)
class BuiltinEffect:
    kind: str
    reads: int
    writes: int
    why: str = ""


@dataclass(frozen=True)
class TypeInfo:
    name: str
    barrier: bool
    reads: int
    writes: int
    uses_cc: bool
    why: str = ""
    #: False for a type that must not be speculated (it runs inline on the coordinator,
    #: in order, with its ``writes`` bumped) although it is not a barrier.
    speculate: bool = True
    #: False for a type that *could* be speculated but does not pay: its codelet is so
    #: short (measured, ``profitable`` entries in the data) that the hand-off costs more
    #: than the overlap hides.  Like ``speculate`` it only decides who executes a step
    #: and when, never what the step computes; unlike ``speculate`` it is a performance
    #: choice, not a safety classification, so the exactness tests still treat the type
    #: as speculable.
    profitable: bool = True
    #: Digest of the audited body (:func:`body_digest`); ``""`` for the barrier fallback.
    body_digest: str = ""


class Effects:
    def __init__(self, builtins: dict[str, BuiltinEffect], types: dict[str, TypeInfo],
                 support_digest: str = "") -> None:
        self.builtins = builtins
        self.types = types
        #: The digest of the descriptor predicates the audit saw.
        self.support_digest = support_digest
        self._unknown = TypeInfo("?", True, ALL, ALL, True, "unclassified: barrier")

    def info(self, codelet_type: str, body_digest: str, support: str | None = None) -> TypeInfo:
        """The audited entry for *codelet_type*, only if the audit holds for what will run.

        A body that is not the audited one (edited under an audited name, or a name the audit
        never saw) is a barrier: it runs on the coordinator, in order, as a writer of
        everything, which is slower and exact.  So is every type under a configuration whose
        descriptor predicates differ from the audited ones (*support*, the
        :func:`support_digest` of the configuration in force).
        """
        got = self.types.get(codelet_type)
        if got is None or not got.body_digest or got.body_digest != body_digest:
            return self._unknown
        if support is not None and support != self.support_digest:
            return self._unknown
        return got


_DATA = os.path.join(os.path.dirname(__file__), "effects_data.json")
_CACHE: Effects | None = None


def load(path: str | None = None) -> Effects:
    """The effects table (cached for the default path)."""
    global _CACHE
    if path is None and _CACHE is not None:
        return _CACHE
    with open(path or _DATA) as f:
        raw = json.load(f)
    builtins = {
        n: BuiltinEffect(e["kind"], mask(e.get("reads", ())), mask(e.get("writes", ())),
                         e.get("why", ""))
        for n, e in raw["builtins"].items()
    }
    types = {
        n: TypeInfo(n, bool(e["barrier"]), mask(e["reads"]), mask(e["writes"]),
                    bool(e["uses_cc"]), e.get("why", ""),
                    bool(e.get("speculate", True)), bool(e.get("profitable", True)),
                    e.get("body_digest", ""))
        for n, e in raw["types"].items()
    }
    eff = Effects(builtins, types, raw.get("support_digest", ""))
    if path is None:
        _CACHE = eff
    return eff
