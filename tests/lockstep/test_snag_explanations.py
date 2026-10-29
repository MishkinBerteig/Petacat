"""Snag explanations and the snag commentary, replayed against Metacat 1.2's own.

``tests/lockstep/snag_explanations_metacat.tsv`` records what the reference printed for
every snag in eight runs: the snag event's ``get-explanation`` (``trace.ss:1097-1125``)
and the two comment lines ``process-snag`` adds (``answers.ss:1164-1172``).  They were
logged by wrapping ``make-snag-event`` and the comment window in the ``metacat:1.2``
container.  Here each run's recorded decisions are replayed in Petacat (``ReplayRNG``),
which reproduces the same snags at the same codelets, and what Petacat wrote for each
must equal the record, character for character -- the explanation in the trace event,
and both voices of the commentary.

``abc-abd-xyz`` is in the committed corpus; the others are in ``traces-snags/`` and were
chosen as the smallest runs that exercise each shape of failure: a CHANGE to a relation,
to a literal letter and to a length; a CHANGE of a group, and of the whole string; a
group-category reversal; a SWAP of three groups and of three letters; and a CONFLICT.

The wider comparison (28 problems beyond the corpus, 479 snags, 53 SWAP and 29 CONFLICT)
is ``scripts/sweep_snags.py``: the corpus is too large to commit, so only this part is.
The record itself is rebuilt with ``scripts/compare_snags.py --regenerate-fixture``.
"""

from __future__ import annotations

import collections
import os

import pytest

from server.engine.runner import EngineRunner
from server.engine.trace import SNAG
from tests.lockstep.run_trace import replay_trace

pytestmark = pytest.mark.lockstep

HERE = os.path.dirname(__file__)
RECORD = os.path.join(HERE, "snag_explanations_metacat.tsv")


def _record():
    runs = collections.OrderedDict()
    with open(RECORD) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            slug, seed, codelet, kind, explanation, eliza, technical = line.rstrip("\n").split("\t")
            runs.setdefault((slug, seed), []).append(
                (int(codelet), kind, explanation, eliza, technical)
            )
    return runs


RUNS = _record()


def _trace_path(slug, seed):
    for root in ("traces-snags", "traces"):
        path = os.path.join(HERE, root, slug, f"{seed}.metacat.jsonl.gz")
        if os.path.exists(path):
            return path
    raise FileNotFoundError(slug)


@pytest.mark.parametrize("slug,seed", list(RUNS), ids=[f"{s}-{n}" for s, n in RUNS])
def test_petacat_explains_every_snag_as_metacat_did(slug, seed, tmp_path, monkeypatch):
    holder = {}
    original = EngineRunner.init_mcat

    def capture(self, *args, **kwargs):
        holder["runner"] = self
        return original(self, *args, **kwargs)

    monkeypatch.setattr(EngineRunner, "init_mcat", capture)
    _, outcome, _ = replay_trace(_trace_path(slug, seed), str(tmp_path))
    ctx = holder["runner"].ctx

    events = [e for e in ctx.trace.events if e.event_type == SNAG]
    comments = [p for p in ctx.commentary.get_paragraphs() if p.event_type == "snag"]
    expected = RUNS[(slug, seed)]
    # Only the snags before the replay stopped can be compared; a replay that
    # desynchronises (none of these do) would stop short of the record.
    assert outcome.reason != "fatal", outcome.fatal.detail
    assert [(e.codelet_count, e.snag_type.upper(), e.explanation) for e in events] == [
        (c, kind, expl) for c, kind, expl, _, _ in expected
    ]
    assert [(p.codelet_count, p.eliza_text, p.technical_text) for p in comments] == [
        (c, eliza, tech) for c, _, _, eliza, tech in expected
    ]


def test_the_record_covers_every_kind_of_failure():
    kinds = collections.Counter(row[1] for rows in RUNS.values() for row in rows)
    assert set(kinds) == {"CHANGE", "SWAP", "CONFLICT"}
    texts = [row[2] for rows in RUNS.values() for row in rows]
    assert any(t.startswith("reversing the starting and ending") for t in texts)
    assert any(t.startswith("no letter-category swap is possible between") for t in texts)
    assert any(" conflicts with changing " in t for t in texts)
    assert any("to `" in t for t in texts)
