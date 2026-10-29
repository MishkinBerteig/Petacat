"""Trace event print names and headers, replayed against Metacat 1.2's own.

``tests/lockstep/event_names_metacat.tsv`` records what the reference reported for every
Temporal Trace event in eight runs: the event's ``print-name`` (``trace.ss``: ``(Id)``,
``>a-b-c>``, ``T:a=>b``, ``[Top Rule]``, ``[Answer ijl]``, ``[Clamp]``, ``[Snag]``) and
the header its ``display-workspace`` sends to ``draw-event-header`` ("Built
successor-group", "Flipped predecessor-group", "Made b=>c slippage", "Built translated
rule", "Justified answer", "Settled for unjustified answer", ...).  They were logged by
running the ``metacat:1.2`` container headless and, after each run, asking each event of
``*trace*`` for both.

Here each run's recorded decisions are replayed in Petacat (``ReplayRNG``), which
reproduces the same events at the same codelets, and what Petacat named and headed each
event must equal the record, character for character.  The eight runs were chosen as the
smallest that between them contain every kind of event the Trace records, all three
group directions, flipped groups of both kinds, slippages on all three bridges, and the
three answer headers.

The wider comparison (the whole committed corpus, 190 discovery runs and 85 justify runs,
4,000 events) is ``scripts/compare_events.py --corpus``; the same script regenerates the
record (``--table``), see ``tests/lockstep/metacat/README.md``.
"""

from __future__ import annotations

import collections
import os

import pytest

from server.engine.runner import EngineRunner
from tests.lockstep.run_trace import replay_trace

pytestmark = pytest.mark.lockstep

HERE = os.path.dirname(__file__)
RECORD = os.path.join(HERE, "event_names_metacat.tsv")

#: The record's event types are Metacat's; the trace's are Petacat's.
TYPES = {
    "concept_activation": "concept_activation",
    "group_built": "group_built",
    "concept_mapping_built": "concept_mapping_built",
    "rule_built": "rule_built",
    "answer_found": "answer_found",
    "snag": "snag",
    "clamp_start": "clamp_start",
}


def _record():
    runs = collections.OrderedDict()
    with open(RECORD) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            kind, slug, seed, _n, etype, codelet, name, header = line.rstrip("\n").split("\t")
            runs.setdefault((kind, slug, seed), []).append((etype, int(codelet), name, header))
    return runs


RUNS = _record()


def _trace_path(kind, slug, seed):
    sub = ("traces", "justify") if kind == "justify" else ("traces",)
    return os.path.join(HERE, *sub, slug, f"{seed}.metacat.jsonl.gz")


@pytest.mark.parametrize(
    "kind,slug,seed", list(RUNS), ids=[f"{k}-{s}-{n}" for k, s, n in RUNS]
)
def test_petacat_names_and_heads_every_event_as_metacat_did(kind, slug, seed, tmp_path, monkeypatch):
    holder = {}
    original = EngineRunner.init_mcat

    def capture(self, *args, **kwargs):
        holder["runner"] = self
        return original(self, *args, **kwargs)

    monkeypatch.setattr(EngineRunner, "init_mcat", capture)
    replay_trace(_trace_path(kind, slug, seed), str(tmp_path))
    events = holder["runner"].ctx.trace.events

    got = [
        (e.event_type, e.codelet_count, e.print_name, e.picture["header"]) for e in events
    ]
    expected = RUNS[(kind, slug, seed)]
    # Metacat's process runs a few codelets past the answer before its driver's suspend
    # lands; the replay stops at the answer, so compare what the replay reached.
    reached = got[-1][1] if got else 0
    expected = [e for e in expected if e[1] <= reached]
    assert got == expected


def test_the_record_covers_every_kind_of_event_and_header():
    seen = {e[0] for run in RUNS.values() for e in run}
    assert seen == set(TYPES)
    headers = {e[3] for run in RUNS.values() for e in run}
    for needed in (
        "Built successor-group",
        "Built predecessor-group",
        "Built sameness-group",
        "Flipped successor-group",
        "Flipped predecessor-group",
        "Built rule",
        "Built translated rule",
        "Clamped patterns",
        "Snag",
        "Found new answer",
        "Justified answer",
        "Settled for unjustified answer",
    ):
        assert needed in headers, needed
    assert any(h.startswith("Made ") and h.endswith(" slippage") for h in headers)
    assert any(h.startswith("Activation of ") and h.endswith(" concept") for h in headers)
    names = {e[2] for run in RUNS.values() for e in run}
    assert {"[Top Rule]", "[Snag]", "[Clamp]"} <= names
    assert any(n.startswith(">") and n.endswith(">") for n in names)
    assert any(n.startswith("<") and n.endswith("<") for n in names)
    assert any(n.startswith("[") and n.endswith("]") and "Rule" not in n and "Answer" not in n
               and n not in ("[Snag]", "[Clamp]") for n in names)
    assert any(n.startswith("[Answer ") for n in names)
    assert {n[0] for n in names if n[1:2] == ":"} == {"T", "V", "B"}
