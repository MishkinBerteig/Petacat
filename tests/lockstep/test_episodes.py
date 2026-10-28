"""Episodes and justify mode in the lockstep harness (task J).

Petacat side: a short episode recorded with ``TracingRNG`` and replayed from its own
trace, run by run, with one ``EpisodicMemory`` carried across the runs.  Metacat side:
the recorder's driver text and file layout (no Docker needed).
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from tests.lockstep.run_trace import (
    episode_runs, is_episode_run, record_episode, record_trace, replay_episode, replay_trace,
)
from tests.lockstep.trace_io import read_records

pytestmark = pytest.mark.lockstep

PROBLEM = ("abc", "abd", "xyz")
CAP = 1500


def _as_metacat(petacat_paths, out):
    """Copy Petacat traces under Metacat's names, so they serve as the reference."""
    out.mkdir(parents=True, exist_ok=True)
    for p in petacat_paths:
        shutil.copyfile(p, out / p.name.replace(".petacat.", ".metacat."))
    return out


@pytest.fixture(scope="module")
def episode(tmp_path_factory):
    out = tmp_path_factory.mktemp("episode")
    runs = record_episode(PROBLEM, 3, 2, CAP, out / "rec")
    return out, runs


def test_an_episode_records_one_trace_per_run_with_the_collectors_seeds(episode):
    out, runs = episode
    assert [p.name for p, _ in runs] == ["3.r1.petacat.jsonl.gz", "3.r2.petacat.jsonl.gz"]
    heads = [next(iter(read_records(p))) for p, _ in runs]
    assert [(h["seed"], h["episode_run"], h["episode_seed"]) for h in heads] == [(3, 1, 3), (4, 2, 3)]
    assert runs[0][1].reason == "answer"        # seed 3 answers at codelet 602


def test_an_episode_replays_from_its_own_trace_with_memory_carried_over(episode, tmp_path):
    out, runs = episode
    ref = _as_metacat([p for p, _ in runs], out / "ref")
    assert is_episode_run(ref / "3.r2.metacat.jsonl.gz")
    assert [p.name for p in episode_runs(ref / "3.r1.metacat.jsonl.gz")] == \
        ["3.r1.metacat.jsonl.gz", "3.r2.metacat.jsonl.gz"]
    results = replay_episode(ref / "3.r2.metacat.jsonl.gz", tmp_path)
    assert [o.record() for _, o, _ in results] == [o.record() for _, o in runs]
    for _, _, rng in results:
        assert rng.summary()["surplus"] == 0
    # one memory object, holding run 1's answer when run 2 started
    first, second = results[0][1].runner.ctx.memory, results[1][1].runner.ctx.memory
    assert first is second and len(second.answers) >= 1
    heads = [next(iter(read_records(p))) for p, _, _ in results]
    assert heads[1]["memory_in_sync"] is True and heads[1]["episode_run"] == 2


def test_a_fatal_run_leaves_later_runs_not_reached(episode, tmp_path):
    out, runs = episode
    ref = _as_metacat([p for p, _ in runs], out / "ref2")
    # End run 1's reference at codelet 5: Petacat runs past Metacat's end (a fatal).
    import gzip
    import json
    run1 = ref / "3.r1.metacat.jsonl.gz"
    lines = [json.loads(l) for l in gzip.open(run1, "rt").read().splitlines()]
    lines = [r for r in lines if r["t"] != "decision" or r["c"] <= 5]
    lines[-1] = {**lines[-1], "c": 5, "reason": "give-up"}
    with gzip.open(run1, "wt") as f:
        f.write("\n".join(json.dumps(r) for r in lines) + "\n")
    results = replay_episode(run1, tmp_path)
    assert results[0][1].reason == "fatal" and results[1][1] is None
    recs = list(read_records(results[1][0]))
    assert recs[0]["not_reached"] is True and recs[1]["class"] == "not-reached"


def test_justify_mode_replays_in_justify_mode(tmp_path):
    path, outcome = record_trace(PROBLEM, 1, 800, tmp_path / "rec", answer="wyz")
    assert next(iter(read_records(path)))["answer"] == "wyz"
    ref = tmp_path / "ref" / "1.metacat.jsonl.gz"
    ref.parent.mkdir()
    shutil.copyfile(path, ref)
    rep, replayed, rng = replay_trace(ref, tmp_path / "out")
    assert replayed.record() == outcome.record()
    assert replayed.runner.ctx.justify_mode is True
    assert next(iter(read_records(rep)))["answer"] == "wyz"


# -- the Metacat recorder's driver (text only) ---------------------------------------


@pytest.fixture(scope="module")
def recorder():
    path = Path(__file__).parent / "metacat" / "record.py"
    spec = importlib.util.spec_from_file_location("lockstep_record", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_classic_driver_is_unchanged_by_the_new_options(recorder):
    text = recorder.driver_text(["abc", "abd", "xyz"], 7, 100, "rev", True, False, "run")
    assert "(trace-open \"/x/abc-abd-xyz/7.metacat.jsonl\" '(abc abd xyz) 7 100 \"rev\")" in text
    assert "(init-mcat 'abc 'abd 'xyz #f 7)" in text and "justify" not in text


def test_the_episode_driver_clears_memory_once_and_seeds_runs_s_plus_k(recorder):
    text = recorder.driver_text(["abc", "abd", "xyz"], 10, 100, "rev", True, False, "run",
                                None, 3)
    assert text.count("(tell *memory* 'clear)") == 1
    for k, seed in ((1, 10), (2, 11), (3, 12)):
        assert f"/x/episodes/abc-abd-xyz/10.r{k}.metacat.jsonl" in text
        assert f"(init-mcat 'abc 'abd 'xyz #f {seed})" in text
        assert f'\\"episode_run\\":{k},\\"episode_seed\\":10' in text
    assert text.index("(tell *memory* 'clear)") < text.index("(trace-open")


def test_the_justify_driver_sets_the_mode_and_passes_the_answer(recorder):
    text = recorder.driver_text(["abc", "abd", "xyz"], 1, 100, "rev", True, False, "run", "wyz")
    assert "(set! %justify-mode% #t)" in text and "(init-mcat 'abc 'abd 'xyz 'wyz 1)" in text
    assert "/x/justify/abc-abd-xyz-wyz/1.metacat.jsonl" in text
    assert recorder.slug_of(["abc", "abd", "xyz"], "wyz") == "abc-abd-xyz-wyz"


# -- the corpus driver's trace globs ----------------------------------------------------


def test_the_default_corpus_glob_leaves_episodic_and_justify_traces_alone(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import lockstep_corpus as corpus

    for rel in ("abc-abd-xyz/1.metacat.jsonl.gz", "episodes/abc-abd-xyz/2.r1.metacat.jsonl.gz",
                "episodes/abc-abd-xyz/2.r10.metacat.jsonl.gz", "episodes/abc-abd-xyz/2.r2.metacat.jsonl.gz",
                "justify/abc-abd-xyz-wyz/3.metacat.jsonl.gz"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"")
    assert [(s, d) for s, d, _ in corpus.find_traces(tmp_path)] == [("abc-abd-xyz", "1")]
    eps = corpus.find_traces(tmp_path, kind="episodes")
    assert [(s, d) for s, d, _ in eps] == [("episodes/abc-abd-xyz", "2.r1"), ("episodes/abc-abd-xyz", "2.r2"),
                                           ("episodes/abc-abd-xyz", "2.r10")]
    assert corpus.find_traces(tmp_path, seeds=["2"], kind="episodes") == eps      # --seed S: the episode
    assert [(s, d) for s, d, _ in corpus.find_traces(tmp_path, kind="justify")] == \
        [("justify/abc-abd-xyz-wyz", "3")]
