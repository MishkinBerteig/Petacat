"""Verbose mode's narration of a replayed run, against Metacat 1.2's own, line for line.

``verbose_metacat.txt.gz`` is what Metacat printed to its console with Verbose mode on
(``%verbose%``), for nine runs: six discovery runs of five problems and three justify-mode
runs.  ``metacat/record_verbose.py`` switches ``%verbose%`` on after ``init-mcat`` and logs
everything the run prints, so the dashed line and ``In <type> codelet...`` of every codelet,
every ``say``, ``vprintf`` and ``vprint`` are in it.  Each run's recorded decisions are
replayed in Petacat (``ReplayRNG``), which reproduces the same run, and the narration
Petacat's ``VerboseLog`` holds must equal the record, line for line.

The record runs only to what the corpus's trace covers; the runs of an uncommitted corpus
are skipped without it, as ``test_commentary`` does.  The wider comparison, over every
corpus, is ``scripts/compare_verbose.py``.

Verbose mode must also change nothing: the same run replayed with it off must write the same
trace.  That is the second test.
"""

from __future__ import annotations

import collections
import gzip
import os

import pytest

from server.engine.runner import EngineRunner
from tests.lockstep.run_trace import replay_trace

pytestmark = pytest.mark.lockstep

HERE = os.path.dirname(__file__)


def _record():
    runs = collections.OrderedDict()
    with gzip.open(os.path.join(HERE, "verbose_metacat.txt.gz"), "rt", encoding="utf-8") as f:
        current = None
        for line in f.read().split("\n"):
            if line.startswith("#") and current is None:
                continue
            if line.startswith("@@RUN\t"):
                _, corpus, slug, key = line.split("\t")
                current = runs.setdefault((corpus, slug, key), [])
            elif line == "@@END":
                current = None
            elif current is not None:
                current.append(line)
    return runs


RUNS = _record()
IDS = [f"{c}/{s}-{k}" for c, s, k in RUNS]


def _trace(corpus: str, slug: str, key: str) -> str:
    path = os.path.join(HERE, *corpus.split("/"), slug, f"{key}.metacat.jsonl.gz")
    if not os.path.exists(path):
        pytest.skip(f"{corpus}/{slug}/{key} is in an uncommitted corpus")
    return path


def _replay(trace, tmp_path, monkeypatch, verbose):
    holder = {}
    original = EngineRunner.init_mcat

    def capture(self, *args, **kwargs):
        holder["runner"] = self
        self.verbose_mode = verbose
        result = original(self, *args, **kwargs)
        # Unbounded here: the run's whole narration is what is compared.
        holder["log"] = self.ctx.verbose_log
        holder["log"]._lines = collections.deque()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(EngineRunner, "init_mcat", capture)
        path, outcome, rng = replay_trace(trace, str(tmp_path))
    return path, holder["log"].since(0)["lines"]


@pytest.mark.parametrize("corpus,slug,key", list(RUNS), ids=IDS)
def test_petacat_narrates_what_metacat_printed(corpus, slug, key, tmp_path, monkeypatch):
    trace = _trace(corpus, slug, key)
    _, said = _replay(trace, tmp_path, monkeypatch, verbose=True)
    expected = RUNS[(corpus, slug, key)]
    assert len(said) == len(expected)
    for number, (got, want) in enumerate(zip(said, expected)):
        assert got == want, f"line {number}"


def test_verbose_mode_changes_no_decision(tmp_path, monkeypatch):
    """The replayed trace is the same with Verbose mode on and off."""
    corpus, slug, key = "traces", "abc-abd-xyz", "4"
    trace = _trace(corpus, slug, key)

    def records(path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return f.read().split("\n")[1:]  # the header names the file it was written to

    on_dir, off_dir = tmp_path / "on", tmp_path / "off"
    on_dir.mkdir()
    off_dir.mkdir()
    on_path, narrated = _replay(trace, on_dir, monkeypatch, verbose=True)
    off_path, silent = _replay(trace, off_dir, monkeypatch, verbose=False)
    assert narrated and silent == []
    assert records(on_path) == records(off_path)
