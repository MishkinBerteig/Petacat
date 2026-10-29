"""Slippage logs and supporting structure, replayed against Metacat 1.2's own.

``tests/lockstep/translation_log_metacat.tsv`` records, for every answer and snag in six
runs, what the reference held when the event was made: the slippage log translating the
rule produced (``make-slippage-log``, ``answers.ss:1198``: the directly applied
slippages, the coattail slippages with the slippage that induced each, the bridges they
came from, and the applied list), the supporting vertical bridges, the rules' reference
objects and, for an answer, the supporting groups (``trace.ss:335``).  They were read
off the events in the ``metacat:1.2`` container.  Each run's recorded decisions are
replayed in Petacat (``ReplayRNG``), and the translation block of each answer and snag
picture must equal the record.

The six runs are the smallest that between them have a coattail slippage (``a-b-z`` 6 and
22, and a justify-mode run), directly applied slippages, a snag with an applied slippage,
and an answer whose supporting groups are nested.

The comparison over the whole corpus (development, held-out and justify mode: 1,044 answers
and snags in 570 + 85 runs) was run with scripts in the task's scratchpad: the corpus is
too large to commit.  The one thing it does not match is the *order* of the supporting
groups of some answers (``DISCREPANCIES5.md`` G-Z1); none of the six runs here is one.
"""

from __future__ import annotations

import collections
import json
import os

import pytest

from server.engine.runner import EngineRunner
from tests.lockstep.run_trace import replay_trace

pytestmark = pytest.mark.lockstep

HERE = os.path.dirname(__file__)
RECORD = os.path.join(HERE, "translation_log_metacat.tsv")
TYPES = {"answer": "answer_found", "snag": "snag"}


def _record():
    runs = collections.OrderedDict()
    with open(RECORD) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            slug, seed, codelet, kind, payload = line.rstrip("\n").split("\t")
            runs.setdefault((slug, seed), []).append((int(codelet), kind, json.loads(payload)))
    return runs


RUNS = _record()


@pytest.mark.parametrize("slug,seed", list(RUNS), ids=[f"{s}-{n}" for s, n in RUNS])
def test_petacat_logs_every_translation_as_metacat_did(slug, seed, tmp_path, monkeypatch):
    holder = {}
    original = EngineRunner.init_mcat

    def capture(self, *args, **kwargs):
        holder["runner"] = self
        return original(self, *args, **kwargs)

    monkeypatch.setattr(EngineRunner, "init_mcat", capture)
    path = os.path.join(HERE, "traces-translation", slug, f"{seed}.metacat.jsonl.gz")
    replay_trace(path, str(tmp_path))
    events = [
        e for e in holder["runner"].ctx.trace.events if e.event_type in TYPES.values()
    ]
    expected = RUNS[(slug, seed)]
    assert len(events) == len(expected), "the replay found different answers and snags"

    for event, (codelet, kind, want) in zip(events, expected):
        assert event.event_type == TYPES[kind]
        assert event.codelet_count == codelet
        got = event.picture["translation"]
        got["slippage_log"].pop("rule_type")
        assert got == want


def test_the_fixtures_cover_a_coattail_slippage_and_a_snag_with_an_applied_slippage():
    """The comparison above proves something only if some of it is non-empty."""
    every = [payload for events in RUNS.values() for _, _, payload in events]
    assert any(p["slippage_log"]["coattail"] for p in every)
    assert any(
        p["slippage_log"]["directly_applied"] and "supporting_groups" not in p for p in every
    )
    assert any(p.get("supporting_groups") for p in every)
