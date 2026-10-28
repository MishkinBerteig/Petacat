"""Comparer tests: hand-made trace pairs with known faults (spec 10.2 "Comparer")."""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import compare_traces as ct  # noqa: E402
import lockstep_corpus as corpus  # noqa: E402

pytestmark = pytest.mark.lockstep

REGISTRY = ct.Registry.load()
HEADER = {"t": "header", "format": 1, "problem": ["abc", "abd", "xyz"], "seed": 1, "cap": 100}


def choice(opts, weights, picked, c=1, who="bond-scout", **kw):
    d = {"t": "decision", "c": c, "ctx": "codelet", "who": who, "n": 0, "kind": "choice",
         "options": opts, "weights": weights, "picked": picked, "site": "m"}
    d.update(kw)
    return d


def prob(p, result=True, c=1, **kw):
    d = {"t": "decision", "c": c, "ctx": "codelet", "who": "bond-evaluator", "n": 0, "kind": "prob",
         "p": p, "result": result, "site": "m"}
    d.update(kw)
    return d


def end(c=10, reason="answer", answer="abd"):
    return {"t": "end", "c": c, "reason": reason, "answer": answer}


def pair_up(meta_decisions, pet_decisions=None, **over):
    """Petacat decisions default to copies of the Metacat ones, paired 0..n-1."""
    pets = pet_decisions if pet_decisions is not None else [dict(d) for d in meta_decisions]
    out = []
    for i, d in enumerate(pets):
        d = dict(d)
        d.setdefault("pair", i)
        out.append(d)
    return out


def run(meta_decs, pet_decs, meta_end=None, pet_end=None, extra_pet=(), **kw):
    meta = ct.Trace.from_records([HEADER, *meta_decs, meta_end or end()])
    pet = ct.Trace.from_records([{**HEADER, "engine": "petacat"}, *pet_decs, *extra_pet, pet_end or end()])
    return ct.compare_traces(meta, pet, kw.pop("registry", REGISTRY))


def test_identical_traces_pass():
    m = [choice(["a", "b"], [1, 3], "a"), prob(0.5)]
    rep = run(m, pair_up(m))
    assert rep.unregistered_error_count == 0 and rep.agreement == 1.0
    assert rep.reach == rep.run_length == 10


def test_missing_option():
    m = [choice(["a", "b", "c"], [1, 1, 1], "a")]
    p = pair_up(m, [choice(["a", "b"], [1, 1], "a")])
    rep = run(m, p)
    assert rep.counts.get("options") == 1
    # b and a still agree after renormalising over the shared names
    assert "rounding-near-threshold?" in rep.first_error.flags


def test_changed_weight():
    m = [choice(["a", "b"], [1, 1], "a")]
    rep = run(m, pair_up(m, [choice(["a", "b"], [1, 2], "a")]))
    assert rep.counts == {"weights": 1}
    assert rep.agreement == 0.0


def test_scaled_weights_pass():
    m = [choice(["a", "b"], [1, 3], "a")]
    rep = run(m, pair_up(m, [choice(["a", "b"], [10, 30], "a")]))
    assert rep.unregistered_error_count == 0


def test_duplicate_names_weights_summed():
    m = [choice(["a", "a", "b"], [1, 1, 2], "a")]
    ok = run(m, pair_up(m, [choice(["a", "b"], [2, 2], "a")]))
    # same multiset is required for options: here it is not, so only options fires
    assert set(ok.counts) == {"options"}
    same_set = pair_up(m, [choice(["a", "b", "a"], [0.5, 2, 1.5], "a")])
    rep = run(m, same_set)
    assert rep.unregistered_error_count == 0 and rep.warning_counts == {"order": 1}


def test_age_multisets():
    m = [choice(["a", "a"], [1, 1], "a", stamps=[3, 5], picked_stamp=3)]
    ok = run(m, pair_up(m, [choice(["a", "a"], [1, 1], "a", stamps=[5, 3], picked_stamp=3)]))
    assert ok.unregistered_error_count == 0
    bad = run(m, pair_up(m, [choice(["a", "a"], [1, 1], "a", stamps=[3, 6], picked_stamp=3)]))
    assert bad.counts == {"age": 1}


SITE_REG = "server/engine/codelet_dsl/builtins.py:506"  # inside evaluate_group
SITE_OTHER = "server/engine/rules.py:10"


def test_complemented_coin_at_registered_site():
    m = [prob(0.9)]
    rep = run(m, pair_up(m, [prob(0.1, site=SITE_REG)]))
    assert rep.unregistered_error_count == 0
    assert rep.registered_counts == {"DISC5:A-4": 1}


def test_complemented_coin_at_registered_codelet_site():
    m = [prob(0.3)]
    rep = run(m, pair_up(m, [prob(0.7, site="<codelet:breaker>:3")]))
    assert rep.unregistered_error_count == 0 and rep.registered_counts == {"DISC5:A-4": 1}


def test_complemented_coin_at_unregistered_site():
    m = [prob(0.9)]
    rep = run(m, pair_up(m, [prob(0.1, site=SITE_OTHER)]))
    assert rep.counts == {"p": 1}
    assert "complemented?" in rep.first_error.flags


def test_registered_site_but_unrelated_p_is_error():
    m = [prob(0.9)]
    assert run(m, pair_up(m, [prob(0.4, site=SITE_REG)])).counts == {"p": 1}


def test_registry_function_resolution():
    assert REGISTRY.resolve_site(SITE_REG)["function"] == "evaluate_group"


def test_reordered_unit_is_warning_only():
    m = [choice(["a", "b"], [1, 1], "a", n=0), choice(["c", "d"], [1, 1], "c", n=1)]
    p = pair_up(m, [dict(m[1], pair=1), dict(m[0], pair=0)])
    rep = run(m, p)
    assert rep.unregistered_error_count == 0
    assert rep.warning_counts == {"order": 1}


def test_surplus_and_missing_records():
    m = [prob(0.5), prob(0.2, c=2)]
    p = [dict(prob(0.5), pair=0), dict(prob(0.7, c=2), pair=None)]
    rep = run(m, p)
    assert rep.counts == {"count": 2}  # one surplus, one missing
    kinds = sorted(f.message.split()[0] for f in rep.errors)
    assert kinds == ["metacat", "surplus"]


def test_missing_pick_is_fatal():
    m = [choice(["a", "b"], [1, 1], "c")]
    rep = run(m, pair_up(m, [choice(["a", "b"], [1, 1], "a")]))
    assert rep.first_fatal.klass == "missing-pick"
    assert rep.reach == 1


def test_replay_fatal_record_sets_reach_and_skips_end_and_tail():
    m = [prob(0.5, c=1), prob(0.5, c=7), prob(0.5, c=9)]
    p = [dict(m[0], pair=0)]
    fatal = {"t": "fatal", "class": "unit", "c": 7, "detail": "no such codelet"}
    rep = run(m, p, extra_pet=[fatal], pet_end=end(c=7, reason="fatal", answer=None))
    assert rep.first_fatal.klass == "unit" and rep.reach == 7
    assert "end" not in rep.counts
    assert rep.counts.get("count") is None  # unreached tail is not "missing"


def test_perturb_bound_and_value():
    base = {"t": "decision", "c": 1, "ctx": "update", "who": "post-bottom-up", "u": 1, "n": 0,
            "kind": "perturb", "value": 4, "bound": 2, "integer": True, "result": 5, "site": "m"}
    rep = run([base], pair_up([base], [dict(base, bound=2.0, integer=False)]))
    assert rep.counts == {"bound": 1}
    rep = run([base], pair_up([base], [dict(base, value=4.5)]))
    assert rep.counts == {"value": 1}


def test_int_bound():
    base = {"t": "decision", "c": 1, "ctx": "codelet", "who": "rule-scout", "n": 0, "kind": "int",
            "bound": 5, "result": 2, "site": "m"}
    assert run([base], pair_up([base], [dict(base, bound=6)])).counts == {"bound": 1}


def test_kind_mismatch():
    m = [prob(0.5)]
    rep = run(m, pair_up(m, [choice(["t", "f"], None, "t", who="bond-evaluator")]))
    assert rep.counts == {"kind": 1}


def test_end_mismatch():
    m = [prob(0.5)]
    rep = run(m, pair_up(m), pet_end=end(c=12, answer="abz"))
    assert rep.counts == {"end": 1}
    assert "answer" in rep.first_error.message and "c:" in rep.first_error.message


def test_snapshot_difference_reported():
    m = [prob(0.5, c=3)]
    snap = lambda act: {"t": "snapshot", "u": 1, "c": 3, "temperature": {"value": 50.0},
                        "slipnet": {"successor": {"activation": act, "frozen": False}}}
    meta = ct.Trace.from_records([HEADER, *m, snap(10.0), end()])
    pet = ct.Trace.from_records([HEADER, *pair_up(m, [prob(0.6, c=3)]), snap(11.0), end()])
    rep = ct.compare_traces(meta, pet, REGISTRY)
    assert rep.first_error.snapshot_diff["path"] == "slipnet.successor.activation"
    assert rep.snapshot_first_diff["u"] == 1 and rep.snapshots_differing == 1
    # within tolerance and set-equality
    assert ct.diff_snapshots(snap(10.0), snap(10.0 + 1e-13)) is None
    other = snap(10.0)
    other["slipnet"]["extra"] = {"activation": 0}
    assert ct.diff_snapshots(snap(10.0), other)[0] == "slipnet.extra"


def test_rounding_flag_absent_when_shared_weights_differ():
    m = [choice(["a", "b", "c"], [1, 1, 1], "a")]
    rep = run(m, pair_up(m, [choice(["a", "b"], [1, 5], "a")]))
    assert "rounding-near-threshold?" not in rep.errors[0].flags
    assert rep.counts == {"options": 1, "weights": 1}


def test_gz_reader_and_cli(tmp_path):
    m = [prob(0.5)]
    mp, pp = tmp_path / "m.jsonl.gz", tmp_path / "p.jsonl"
    with gzip.open(mp, "wt") as fh:
        for r in [HEADER, *m, end()]:
            fh.write(json.dumps(r) + "\n")
    pp.write_text("".join(json.dumps(r) + "\n" for r in [HEADER, *pair_up(m, [prob(0.6)]), end()]))
    out = tmp_path / "r.json"
    r = subprocess.run([sys.executable, str(SCRIPTS / "compare_traces.py"), str(mp), str(pp), "--json", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "FIRST ERROR" in r.stdout
    assert json.loads(out.read_text())["counts"] == {"p": 1}


def test_ratchet_regression_detection():
    old = {"x/1": {"reach": 100, "agreement": 0.9, "unregistered_errors": 3}}
    assert corpus.ratchet_regressions(old, {"x/1": {"reach": 100, "agreement": 0.9, "unregistered_errors": 3}}) == []
    assert corpus.ratchet_regressions(old, {"x/1": {"reach": 150, "agreement": 0.95, "unregistered_errors": 1}}) == []
    assert len(corpus.ratchet_regressions(old, {"x/1": {"reach": 90, "agreement": 0.9, "unregistered_errors": 3}})) == 1
    assert len(corpus.ratchet_regressions(old, {"x/1": {"reach": 100, "agreement": 0.8, "unregistered_errors": 4}})) == 2
    assert corpus.ratchet_regressions(old, {}) != []
