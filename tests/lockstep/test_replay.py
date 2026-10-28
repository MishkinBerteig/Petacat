"""Tracing, replay, the determinism guards and the fatal paths (spec §6.3-6.4, §7, §10.3).

The reference for these tests is Petacat's own trace: record a run with ``TracingRNG``,
then replay it treating that trace as Metacat's.  Every decision must pair, every pick
must be forced to the same thing, and the end must be the same.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

import pytest

from server.engine.rng import RNG
from tests.lockstep.context import ReplayStop
from tests.lockstep.faithful import REPO_ROOT, run_faithful
from tests.lockstep.replay_rng import BypassedReplay, MetacatTrace, ReplayRNG
from tests.lockstep.run_trace import record_trace, replay_trace
from tests.lockstep.trace_io import TraceWriter, read_records
from tests.lockstep.tracing_rng import TracingRNG

pytestmark = pytest.mark.lockstep

PROBLEM = ("abc", "abd", "xyz")
CAP = 2000


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    out = tmp_path_factory.mktemp("recorded")
    path, outcome = record_trace(PROBLEM, 1, CAP, out)
    return path, outcome


def _normalised(records):
    """A record without its ``pair``, and with the options of a choice as a multiset.

    Codelets that share a name and a time stamp are interchangeable, so replay may take
    a different one of them than the original run did; the rack then lists them in a
    different order, which is a warning-only difference (spec §7.3, "Same order").
    """
    out = []
    for r in records:
        r = dict(r)
        r.pop("pair", None)
        if r.get("kind") == "choice":
            columns = [r.pop("options")]
            for key in ("weights", "stamps"):
                if key in r:
                    columns.append(r.pop(key))
            r["options"] = sorted(zip(*columns), key=repr)
        out.append(r)
    return out


# -- TracingRNG: the §7.1 rules ------------------------------------------------------


def _traced(tmp_path):
    path = tmp_path / "t.jsonl"
    writer = TraceWriter(path)
    return TracingRNG(7, writer), writer, path


def _decisions(path):
    return [r for r in read_records(path) if r["t"] == "decision"]


def test_zero_weights_are_dropped_and_trivial_decisions_are_not_logged(tmp_path):
    rng, writer, path = _traced(tmp_path)
    rng.pick(["only"])                                   # one option: trivial
    rng.weighted_pick(["a", "b", "c"], [0, 5, 0])        # one live option: trivial
    rng.prob(0.0), rng.prob(1.0)                         # certain: trivial
    rng.randint(1)                                       # bound 1: trivial
    rng.perturb(0.1)                                     # bound 1: trivial
    rng.weighted_pick(["a", "b", "c"], [0, 5, 3])        # logged, "a" dropped
    rng.weighted_pick(["a", "b"], [0, 0])                # all zero: uniform over both
    writer.close()
    d = _decisions(path)
    assert [r["kind"] for r in d] == ["choice", "choice"]
    assert d[0]["options"] == ["b", "c"] and d[0]["weights"] == [5.0, 3.0]
    assert d[1]["options"] == ["a", "b"] and "weights" not in d[1]


def test_nested_helpers_log_once(tmp_path):
    rng, writer, path = _traced(tmp_path)
    rng.prob(0.5)                      # prob -> random
    rng.pick(["a", "b", "c"])          # pick -> randint
    rng.weighted_pick(["a", "b"], [1, 1])
    rng.perturb(4)                     # perturb -> randint, prob -> random
    rng.stochastic_filter([1, 2, 3], lambda _: 0.5)   # three separate probs
    writer.close()
    assert [r["kind"] for r in _decisions(path)] == \
        ["prob", "choice", "choice", "perturb", "prob", "prob", "prob"]
    perturb = _decisions(path)[3]
    assert perturb["value"] == 4.0 and perturb["bound"] == 3 and perturb["integer"] is True


def test_a_tracing_rng_draws_exactly_what_a_plain_rng_draws(tmp_path):
    rng, writer, _ = _traced(tmp_path)
    plain = RNG(7)
    for items, weights in ((["a", "b", "c"], [3, 1, 2]), (["x"], [1]), (["p", "q"], [0, 4])):
        assert rng.weighted_pick(items, weights) == plain.weighted_pick(items, weights)
    assert rng.perturb(5) == plain.perturb(5)
    assert rng.prob(0.4) == plain.prob(0.4)
    assert rng.call_count == plain.call_count
    writer.close()


def test_sites_name_the_caller_and_codelet_bodies(recorded):
    path, _ = recorded
    sites = {r["site"] for r in _decisions(path)}
    assert any(s.startswith("server/engine/") for s in sites)
    assert any(s.startswith("<codelet:") for s in sites)
    assert "choose" in sites and any(s.startswith("evict@") for s in sites)


# -- the trace's shape ----------------------------------------------------------------


def test_a_recorded_trace_has_the_spec_shape(recorded):
    path, outcome = recorded
    records = list(read_records(path))
    assert records[0]["t"] == "header" and records[0]["engine"] == "petacat"
    assert records[0]["problem"] == list(PROBLEM) and records[0]["seed"] == 1
    assert records[0]["cap"] == CAP and records[0]["settings"]["numeric_backend"] == "off"
    assert records[-1] == outcome.record() and records[-1]["t"] == "end"
    kinds = {r["t"] for r in records}
    assert kinds == {"header", "decision", "snapshot", "end"}
    first = next(r for r in records if r["t"] == "decision")
    assert (first["c"], first["ctx"], first["kind"]) == (1, "choose", "choice")
    phases = {r["who"] for r in records if r["t"] == "decision" and r["ctx"] == "update"}
    assert phases <= {"rules-possible", "workspace-values", "snag-exit", "clamp-expiry",
                      "themespace", "slipnet", "temperature", "post-bottom-up",
                      "post-top-down", "post-deferred"}
    assert {"slipnet", "post-bottom-up", "post-top-down", "post-deferred"} <= phases
    us = [r["u"] for r in records if r["t"] == "snapshot"]
    assert us == list(range(1, len(us) + 1))


def test_snapshots_use_canonical_names(recorded):
    path, _ = recorded
    snaps = [r for r in read_records(path) if r["t"] == "snapshot"]
    last = snaps[-1]
    assert set(last) == {"t", "u", "c", "temperature", "slipnet", "themes", "coderack",
                         "structures", "trace"}
    assert last["slipnet"]["successor"][1] in (True, False)
    assert all(not name.startswith("plato-") for name in last["slipnet"])
    assert any(row[0].startswith("bond(") for row in last["structures"]["bonds"])
    assert "?" not in json.dumps(last["structures"])


# -- self-replay ----------------------------------------------------------------------


def test_self_replay_pairs_every_decision_and_reproduces_the_run(recorded, tmp_path):
    path, outcome = recorded
    out, replay_outcome, rng = replay_trace(path, tmp_path)
    original = list(read_records(path))
    replayed = list(read_records(out))

    assert rng.surplus == 0, "surplus Petacat calls"
    assert rng.summary()["metacat_unpaired"] == 0, "Metacat records nobody asked for"
    decisions = [r for r in replayed if r["t"] == "decision"]
    assert [r["pair"] for r in decisions] == list(range(len(decisions)))
    assert replay_outcome.fatal is None

    # identical picks, identical options, identical everything but the pair field
    assert _normalised(r for r in replayed if r["t"] == "decision") == \
        _normalised(r for r in original if r["t"] == "decision")
    assert len([r for r in replayed if r["t"] == "snapshot"]) == \
        len([r for r in original if r["t"] == "snapshot"])
    assert all(a["temperature"] == b["temperature"] and a["slipnet"] == b["slipnet"]
               for a, b in zip((r for r in replayed if r["t"] == "snapshot"),
                               (r for r in original if r["t"] == "snapshot")))
    assert replayed[-1] == original[-1] == outcome.record()


# -- Guard 1: nothing bypasses replay ---------------------------------------------------


def test_guard_1_every_rng_reference_is_the_replay_rng(recorded, monkeypatch):
    path, _ = recorded
    from server.engine.codelet_dsl import interpreter
    from server.engine.runner import EngineRunner
    import builtins

    rng = ReplayRNG(1, MetacatTrace(path))
    seen = {"bodies": 0}

    def checking_exec(code, namespace, *args):
        assert namespace["rng"] is rng, "a codelet body holds a different RNG"
        assert namespace["ctx"].rng is rng
        seen["bodies"] += 1
        return builtins.exec(code, namespace, *args)

    monkeypatch.setattr(interpreter, "exec", checking_exec, raising=False)

    outcome = run_faithful(PROBLEM, 1, 300, rng)
    runner: EngineRunner = outcome.runner
    assert runner.ctx.rng is rng and runner.ctx.coderack.rng is rng
    assert seen["bodies"] > 0
    assert outcome.fatal is None and outcome.reason != "error", outcome


def test_guard_1_the_underlying_generator_raises_if_called_directly():
    rng = ReplayRNG(1, MetacatTrace.__new__(MetacatTrace))
    for use in (lambda: rng._rng.random(), lambda: rng._rng.randrange(5),
                lambda: rng._rng.getstate()):
        with pytest.raises(BypassedReplay):
            use()


# -- fatal failures and surplus ------------------------------------------------------------


def _write(tmp_path, name, records):
    path = tmp_path / name
    with TraceWriter(path) as w:
        for r in records:
            w.write(r)
    return path


def test_a_pick_petacat_did_not_offer_is_a_fatal_missing_pick(recorded, tmp_path):
    path, _ = recorded
    records = list(read_records(path))
    target = next(i for i, r in enumerate(records)
                  if r["t"] == "decision" and r["ctx"] == "codelet" and r["kind"] == "choice")
    bad = copy.deepcopy(records)
    bad[target]["picked"] = "nothing-by-this-name"
    ref = _write(tmp_path, "bad.metacat.jsonl", bad)
    out, outcome, rng = replay_trace(ref, tmp_path / "out")
    assert outcome.fatal is not None and outcome.fatal.fatal_class == "missing-pick"
    tail = list(read_records(out))[-3:]
    assert tail[-3]["t"] == "decision" and tail[-3]["picked"] is None
    assert tail[-2]["t"] == "fatal" and tail[-2]["class"] == "missing-pick"
    assert tail[-1]["t"] == "end" and tail[-1]["reason"] == "fatal"
    assert tail[-2]["c"] == tail[-1]["c"] == records[target]["c"]


def test_running_past_metacats_end_is_a_fatal_unit_failure(recorded, tmp_path):
    path, _ = recorded
    records = list(read_records(path))
    keep = [r for r in records if r["t"] in ("header",) or
            (r["t"] in ("decision", "snapshot") and r["c"] <= 50)]
    keep.append({"t": "end", "c": 50, "reason": "cap"})
    ref = _write(tmp_path, "short.metacat.jsonl", keep)
    out, outcome, rng = replay_trace(ref, tmp_path / "out")
    assert outcome.fatal is not None and outcome.fatal.fatal_class == "unit"
    assert "past Metacat's end" in outcome.fatal.detail
    last = list(read_records(out))
    assert last[-2]["t"] == "fatal" and last[-1]["reason"] == "fatal"


def test_a_record_metacat_does_not_have_makes_the_call_surplus_and_stays_deterministic(
        recorded, tmp_path):
    path, _ = recorded
    records = list(read_records(path))
    victim = next(i for i, r in enumerate(records)
                  if r["t"] == "decision" and r["kind"] == "prob" and r["ctx"] == "update")
    cut = records[:victim] + records[victim + 1:]
    ref = _write(tmp_path, "cut.metacat.jsonl", cut)
    first = replay_trace(ref, tmp_path / "a", cap=400)
    second = replay_trace(ref, tmp_path / "b", cap=400)
    assert first[2].surplus >= 1
    surplus = [r for r in read_records(first[0]) if r["t"] == "decision" and r["pair"] is None]
    assert surplus and surplus[0]["kind"] == "prob"
    assert first[0].read_bytes() == second[0].read_bytes()


def test_a_complemented_site_returns_the_opposite_result(recorded, tmp_path):
    path, _ = recorded
    records = list(read_records(path))
    i = next(i for i, r in enumerate(records)
             if r["t"] == "decision" and r["kind"] == "prob" and r["ctx"] == "codelet")
    site = records[i]["site"]
    flipped = copy.deepcopy(records)
    flipped[i]["result"] = not flipped[i]["result"]
    ref = _write(tmp_path, "flip.metacat.jsonl", flipped)
    out, outcome, rng = replay_trace(ref, tmp_path / "out", cap=60,
                                     complemented_sites=(site,))
    index = sum(1 for r in records[:i] if r["t"] == "decision")
    paired = next(r for r in read_records(out) if r["t"] == "decision" and r["pair"] == index)
    # the site is registered: Metacat's (flipped) result is reversed back to the original
    assert paired["kind"] == "prob" and paired["result"] == records[i]["result"]


# -- Guard 2: replays repeat exactly ------------------------------------------------------


@pytest.mark.slow
def test_guard_2_two_fresh_processes_write_byte_identical_traces(recorded, tmp_path):
    path, _ = recorded
    outputs = []
    for hashseed in ("11", "2468"):
        out = tmp_path / f"run{hashseed}"
        env = dict(os.environ, PYTHONHASHSEED=hashseed, PYTHONPATH=str(REPO_ROOT))
        proc = subprocess.run(
            [sys.executable, "-m", "tests.lockstep.run_trace", "replay",
             "--metacat", str(path), "--out", str(out)],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=600,
        )
        assert proc.returncode == 0, proc.stderr
        outputs.append((out / "1.petacat.jsonl.gz").read_bytes())
    assert outputs[0] == outputs[1]
    assert len(outputs[0]) > 1000


# -- The numeric substrate ------------------------------------------------------------


def test_a_committed_metacat_trace_replays_with_the_numeric_substrate_on(tmp_path, monkeypatch):
    """Petacat runs its arithmetic through a numeric backend by default, not through the
    object-graph loops faithful mode uses.  The exact CPU backend must replay a real
    Metacat trace just as well: every decision paired, the same end, and the same state
    at every update cycle (``lockstep_corpus.py --numeric-backend`` does the whole
    corpus, the GPU included)."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import compare_traces as ct
    from server.engine.numeric import python_backend
    from tests.lockstep.faithful import NUMERIC_BACKEND_ENV

    updates = []
    original = python_backend.PythonSlipnetSession.update

    def counted(self, *args, **kwargs):
        updates.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(python_backend.PythonSlipnetSession, "update", counted)
    monkeypatch.setenv(NUMERIC_BACKEND_ENV, "python")
    metacat = REPO_ROOT / "tests" / "lockstep" / "traces" / "abc-abd-xyz" / "1.metacat.jsonl.gz"
    out, outcome, _ = replay_trace(metacat, tmp_path)

    assert next(iter(read_records(out)))["settings"]["numeric_backend"] == "python"
    assert updates, "the backend never ran"
    report = ct.compare(metacat, out)
    assert report.unregistered_error_count == 0
    assert report.reach == report.run_length
    assert report.state_snapshots_differing == 0
