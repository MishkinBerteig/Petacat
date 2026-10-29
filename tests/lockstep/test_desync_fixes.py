"""Metacat runs beyond the lockstep corpus that used to desynchronise Petacat's replay.

Three real engine differences were found by replaying 336 Metacat runs on 28 problems
outside the corpus (DISCREPANCIES5 G-Y1 ... G-Y5).  Each trace here is the shortest
prefix of one such run that reaches the first divergence (a codelet cap, recorded with
``metacat/record.py --cap``); at HEAD before the fixes each replays with errors, now each
replays to its end with none, and with no differing state snapshot.

* ``a-b-xyz`` 1 (cap 260): ``rule-builder`` was never posted at c=226 -- a rule on "the
  rightmost letter" found no object, the letter being both ``single`` and ``rightmost``.
* ``abc-bcd-xyz`` 1 (cap 450): ``answer-finder`` missing at c=416 -- the rule "change the
  letter-category of each letter to successor" was taken for a duplicate of "... of the
  whole group".
* ``aaa-bbb-xyz`` 3 (cap 480): the duplicate branch of ``group-builder`` never ran for a
  proposal whose constituent group had since been broken, so ``whole`` was not copied to
  the incumbent and the Slipnet's ``whole`` and ``identity`` activations drifted.

The fourth and fifth fixes (bridge strength's internal coherence in both orders, and
``get-equivalent-bridge``) are pinned in ``tests/module/test_lockstep_desync_fixes.py``.
"""

from __future__ import annotations

import os

import pytest

from scripts.compare_traces import compare
from tests.lockstep.run_trace import replay_trace

pytestmark = pytest.mark.lockstep

HERE = os.path.dirname(__file__)
TRACES = [
    ("a-b-xyz", 1),
    ("abc-bcd-xyz", 1),
    ("aaa-bbb-xyz", 3),
]


@pytest.mark.parametrize("slug,seed", TRACES, ids=[f"{s}-{n}" for s, n in TRACES])
def test_the_replay_follows_metacat_to_the_end(slug, seed, tmp_path):
    metacat = os.path.join(HERE, "traces-desync", slug, f"{seed}.metacat.jsonl.gz")
    petacat, outcome, _ = replay_trace(metacat, str(tmp_path))
    assert outcome.reason != "fatal", outcome.fatal.detail
    report = compare(metacat, petacat)
    assert report.unregistered_error_count == 0, report.first_error
    assert report.reach == report.run_length
    assert report.state_snapshots_differing == 0, report.state_snapshot_first_diff
