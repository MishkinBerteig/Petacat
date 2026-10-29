"""The commentary of a replayed run, against Metacat 1.2's own, line for line.

``commentary_metacat.tsv`` records every paragraph the reference's comment window received
for a set of runs -- both voices and the codelet count it was added at -- logged by
``metacat/record_comments.py``.  Each run's recorded decisions are replayed in Petacat
(``ReplayRNG``), which reproduces the same run, and the paragraphs Petacat's commentary
holds must equal the record, character for character.  The opening "Beginning run"
paragraph is not part of it.

The runs cover what the reference says about a run: snags, the three clamps that jootsing
and the justifier make and their undoing with the progress each achieved, the
progress-watcher's "I'm getting frustrated" (top, bottom and both string pairs), the
justifier's "Aha!  I have another idea", answers (found, justified, and "Okay, I'm
stumped") and give-ups.  ``abc-abd-xyz`` and the snag corpus are committed; the rest
need the uncommitted corpora and are skipped without them.  The wider comparison, over
every corpus and the remindings of episodes, is ``scripts/compare_commentary.py``.
"""

from __future__ import annotations

import collections
import os

import pytest

from server.engine.runner import EngineRunner
from tests.lockstep.run_trace import replay_trace

pytestmark = pytest.mark.lockstep

HERE = os.path.dirname(__file__)


def _record():
    runs = collections.OrderedDict()
    with open(os.path.join(HERE, "commentary_metacat.tsv"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            corpus, slug, key, codelet, eliza, technical = line.rstrip("\n").split("\t")
            runs.setdefault((corpus, slug, key), []).append((codelet, eliza, technical))
    return runs


RUNS = _record()


@pytest.mark.parametrize("corpus,slug,key", list(RUNS), ids=[f"{c}/{s}-{k}" for c, s, k in RUNS])
def test_petacat_says_what_metacat_said(corpus, slug, key, tmp_path, monkeypatch):
    trace = os.path.join(HERE, *corpus.split("/"), slug, f"{key}.metacat.jsonl.gz")
    if not os.path.exists(trace):
        pytest.skip(f"{corpus}/{slug}/{key} is in an uncommitted corpus")
    holder = {}
    original = EngineRunner.init_mcat

    def capture(self, *args, **kwargs):
        holder["runner"] = self
        return original(self, *args, **kwargs)

    monkeypatch.setattr(EngineRunner, "init_mcat", capture)
    replay_trace(trace, str(tmp_path))

    said = [
        (str(p.codelet_count), p.eliza_text, p.technical_text)
        for p in holder["runner"].ctx.commentary.get_paragraphs()
        if p.event_type != "new_problem"
    ]
    assert said == RUNS[(corpus, slug, key)]
