"""The clock coderack must choose exactly as the faithful two-stage draw does, in law.

What these defend
-----------------
* ``test_first_choice_matches_two_stage_law`` -- the per-step choice distribution of the
  exponential race equals the faithful draw (bin by ``count x row[bin]``, then uniform in
  the bin), by a chi-square test over many independent trials, at several temperatures and
  with and without urgency clamps.  This is the claim the whole speculative design rests on.
* ``test_second_choice_after_posting_and_cooling`` -- memorylessness: after a first choice,
  a codelet is posted and the temperature changes (every residual is rescaled), and the
  *joint* law of the two choices still equals the faithful sequential law.
* ``test_larger_clock_never_changes_minimum`` -- inserting a codelet whose clock is larger
  never changes the current minimum (the cheap validation the engine relies on).
* ``test_bins_heap_stay_consistent`` -- eviction, posting, deferred posting, clamping and
  choosing keep the bins, the total, the clocks and the heap in agreement.
* ``test_all_zero_weight_fallback`` -- the degenerate branch reproduces the faithful
  fallback (uniform over non-empty bins, then uniform within the bin).
* ``test_clock_depends_only_on_id`` -- a codelet's clock is a pure function of its id.
"""

from __future__ import annotations

import math
import os
import random
from collections import Counter

import pytest

from server.engine.coderack import Codelet, Coderack
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.parallel.speculative.clock_rack import ClockCoderack
from server.parallel.speculative.streams import Streams

SEED_DATA = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DATA)


# -- a small chi-square, since scipy is not a dependency ------------------------------


def _gamma_q(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x) (Numerical Recipes gser/gcf)."""
    if x <= 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1.0:
        ap, total, delta = a, 1.0 / a, 1.0 / a
        for _ in range(1000):
            ap += 1.0
            delta *= x / ap
            total += delta
            if abs(delta) < abs(total) * 1e-14:
                break
        return 1.0 - total * math.exp(-x + a * math.log(x) - gln)
    b = x + 1.0 - a
    c = 1.0 / 1e-300
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def chi_square_p(observed: dict, expected_prob: dict, n: int) -> float:
    """p-value of the Pearson chi-square of *observed* counts against *expected_prob*."""
    stat, cells = 0.0, 0
    pooled_o = pooled_e = 0.0
    for key, p in expected_prob.items():
        e = p * n
        o = observed.get(key, 0)
        if e < 5:  # pool the sparse tail
            pooled_o += o
            pooled_e += e
            continue
        stat += (o - e) ** 2 / e
        cells += 1
    if pooled_e >= 5:
        stat += (pooled_o - pooled_e) ** 2 / pooled_e
        cells += 1
    assert set(observed) <= set(expected_prob), "an outcome with zero expected probability"
    return _gamma_q((cells - 1) / 2.0, stat / 2.0)


# -- helpers ---------------------------------------------------------------------------

#: (type, urgency) multiset: spans bins 0, 1, 3, 5, 6 so weights differ strongly.
MIX = (
    [("alpha", 5)] * 6 + [("beta", 20)] * 4 + [("gamma", 45)] * 3
    + [("delta", 70)] * 2 + [("alpha", 95)] * 2 + [("epsilon", 99)]
)


def build(meta, seed: int, mix=MIX) -> ClockCoderack:
    rack = ClockCoderack(meta, Streams(seed))
    for t, u in mix:
        rack.post(Codelet(t, u))
    return rack


def faithful_type_probs(rack: Coderack, temperature: float) -> dict[str, float]:
    return rack.get_type_selection_probabilities(temperature)


# -- the law -----------------------------------------------------------------------------


@pytest.mark.parametrize("temperature", [100.0, 70.0, 35.0, 10.0])
@pytest.mark.parametrize("clamped", [False, True])
def test_first_choice_matches_two_stage_law(meta, temperature, clamped):
    n = 6000
    counts: Counter = Counter()
    expected = None
    for trial in range(n):
        rack = build(meta, 10_000 + trial)
        if clamped:
            rack.clamp_codelet_type("alpha", 90)
            rack.clamp_codelet_type("beta", 2)
        if expected is None:
            expected = faithful_type_probs(rack, temperature)
        codelet = rack.choose_and_remove(temperature, None)
        counts[codelet.codelet_type] += 1
    p = chi_square_p(counts, expected, n)
    assert p > 1e-4, (temperature, clamped, dict(counts), expected, p)


def test_matches_faithful_rack_empirically(meta):
    """The faithful rack, sampled, agrees with the same analytic law (sanity of the law)."""
    n = 6000
    counts: Counter = Counter()
    rng = RNG(5)
    expected = None
    for _ in range(n):
        rack = Coderack(meta)
        for t, u in MIX:
            rack.post(Codelet(t, u))
        if expected is None:
            expected = rack.get_type_selection_probabilities(50.0)
        counts[rack.choose_and_remove(50.0, rng).codelet_type] += 1
    assert chi_square_p(counts, expected, n) > 1e-4


def test_second_choice_after_posting_and_cooling(meta):
    """Joint law of (first, second) with a post and a temperature change in between."""
    mix = [("a", 5)] * 3 + [("b", 45)] * 2 + [("c", 95)] * 2
    t1, t2 = 80.0, 30.0
    post = ("d", 70)
    n = 12000
    counts: Counter = Counter()
    for trial in range(n):
        rack = build(meta, 77_000 + trial, mix)
        first = rack.choose_and_remove(t1, None)
        rack.post(Codelet(*post))
        second = rack.choose_and_remove(t2, None)
        counts[(first.codelet_type, second.codelet_type)] += 1

    # Exact joint under the faithful sequential draw.
    probe = build(meta, 1, mix)
    p1 = probe.get_type_selection_probabilities(t1)
    expected: dict = {}
    for first_type, pf in p1.items():
        rack = Coderack(meta)
        removed = False
        for t, u in mix:
            if t == first_type and not removed:
                removed = True
                continue
            rack.post(Codelet(t, u))
        rack.post(Codelet(*post))
        for second_type, ps in rack.get_type_selection_probabilities(t2).items():
            expected[(first_type, second_type)] = pf * ps
    assert chi_square_p(counts, expected, n) > 1e-4, (dict(counts), expected)


def test_all_zero_weight_fallback(meta):
    """If every weight is zero the choice is uniform over non-empty bins, then in the bin."""
    n = 6000
    counts: Counter = Counter()
    for trial in range(n):
        rack = ClockCoderack(meta, Streams(900 + trial), step_source=lambda: 7)
        # A table whose row is all zeros: a stand-in for a fully-starved rack.
        rack.urgency_table = _ZeroTable(rack.urgency_table)
        for t, u in [("lo", 5)] * 3 + [("hi", 95)]:
            rack.post(Codelet(t, u))
        counts[rack.choose_and_remove(50.0, None).codelet_type] += 1
        assert rack.fallbacks == 1
    # Faithful fallback: bin uniformly among the 2 non-empty ones, then a codelet uniformly.
    expected = {"lo": 0.5, "hi": 0.5}
    assert chi_square_p(counts, expected, n) > 1e-4, dict(counts)


class _ZeroTable:
    def __init__(self, real):
        self._real = real
        self.num_bins = real.num_bins

    def row(self, temperature):
        return (0,) * self.num_bins

    def __getattr__(self, name):
        return getattr(self._real, name)


# -- structure ------------------------------------------------------------------------


def test_larger_clock_never_changes_minimum(meta):
    rack = build(meta, 4242)
    temperature = 60.0
    for i in range(300):
        top = rack.predict(temperature, 1)[0]
        f_top = rack._clock[top.id][0]
        newcomer = Codelet(random.Random(i).choice(["a", "b", "c"]), random.Random(i * 3).randrange(100))
        rack.post(newcomer)
        f_new = rack._clock[newcomer.id][0]
        now_top = rack.predict(temperature, 1)[0]
        if f_new > f_top:
            assert now_top is top
        else:
            assert now_top is newcomer
        rack.check_consistency()
        # keep the rack bounded and moving
        rack.choose_and_remove(temperature, None)


def test_clock_depends_only_on_id():
    s = Streams(31337)
    for cid in (1, 2, 99, 12345):
        assert s.clock_exponential(cid) == Streams(31337).clock_exponential(cid)
        assert s.clock_exponential(cid) >= 0.0
    assert s.clock_exponential(1) != s.clock_exponential(2)
    assert Streams(1).clock_exponential(5) != Streams(2).clock_exponential(5)


def test_predict_matches_choose_order(meta):
    rack = build(meta, 99)
    order = rack.predict(55.0, 12)
    got = [rack.choose_and_remove(55.0, None) for _ in range(12)]
    assert [c.id for c in order] == [c.id for c in got]


def test_predict_with_changed_temperature_matches_and_does_not_mutate(meta):
    rack = build(meta, 100)
    rack.choose_and_remove(90.0, None)
    snapshot = dict(rack._clock)
    order = rack.predict(20.0, 8)
    assert rack._clock == snapshot, "predict() must not reweight the rack"
    got = [rack.choose_and_remove(20.0, None) for _ in range(8)]
    assert [c.id for c in order] == [c.id for c in got]


def test_cached_prediction_is_exact_until_a_post_passes_it(meta):
    """The engine reuses one prediction for a whole epoch.  ``predict_entries`` records the
    urgency row and restarts ``floor_f``; while ``gen`` is unchanged, the entries with
    ``F < floor_f`` that are still on the rack must be exactly the next choices, in order,
    whatever was posted, evicted or chosen since."""
    rng = random.Random(77)
    rack = ClockCoderack(meta, Streams(5), rng_source=lambda: ev_rng)
    ev_rng = RNG(9)
    types = ["a", "b", "c", "d", "e"]
    temperature = 60.0
    for _ in range(40):
        rack.post(Codelet(rng.choice(types), rng.randrange(0, 101)))
    checked = 0
    for step in range(1500):
        entries = rack.predict_entries(temperature, 10)
        gen0 = rack.gen
        for _ in range(rng.randrange(1, 12)):
            op = rng.random()
            if op < 0.45:
                rack.post(Codelet(rng.choice(types), rng.randrange(0, 101)))
            elif op < 0.55:
                rack.post_deferred(
                    [Codelet(rng.choice(types), rng.randrange(0, 101)) for _ in range(5)],
                    step, ev_rng)
            elif op < 0.8:
                rack.choose_and_remove(temperature, None)
            elif op < 0.9:
                # The engine drops its cache whenever the temperature moves (it only
                # moves in an update cycle), so a cache is never read across this.
                temperature = float(rng.randrange(0, 101))
                break
            elif op < 0.95:
                rack.clamp_codelet_type(rng.choice(types), rng.randrange(0, 101))
            else:
                rack.unclamp_all()
            if rack.gen != gen0:
                break
            valid = []
            for f, cid in entries:
                if f >= rack.floor_f:
                    break
                if cid in rack._by_id:
                    valid.append(cid)
            if valid:
                truth = rack.predict(temperature, len(valid))
                assert [c.id for c in truth] == valid
                checked += 1
        while rack.total_count > 80:
            rack.choose_and_remove(temperature, None)
        if rack.total_count < 20:
            for _ in range(30):
                rack.post(Codelet(rng.choice(types), rng.randrange(0, 101)))
    assert checked > 500


def test_sync_row_is_the_choices_own_reweighting(meta):
    """``sync_row`` does early exactly what the next ``choose_and_remove`` would do first."""
    cods = [Codelet(t, u) for t, u in MIX]  # clocks are keyed by id: share the codelets
    a, b = ClockCoderack(meta, Streams(41)), ClockCoderack(meta, Streams(41))
    for rack in (a, b):
        for c in cods:
            rack.post(c)
    a.choose_and_remove(95.0, None)
    b.choose_and_remove(95.0, None)
    a.sync_row(30.0)
    assert a._row != b._row
    ca, cb = a.choose_and_remove(30.0, None), b.choose_and_remove(30.0, None)
    # (The two racks hold different Codelet objects, so compare what the clocks say.)
    assert ca.id == cb.id and a._row == b._row and a.t_now == b.t_now
    assert a._clock == b._clock
    assert [c.id for c in a.predict(30.0, 6)] == [c.id for c in b.predict(30.0, 6)]


def test_bins_heap_stay_consistent(meta):
    """Random operations (incl. eviction past capacity, clamps, deferred batches)."""
    rng = random.Random(2024)
    streams = Streams(7)
    rack = ClockCoderack(meta, streams, rng_source=lambda: ev_rng)
    ev_rng = RNG(3)
    temperature = 100.0
    types = ["a", "b", "c", "d", "e"]
    clock = 0
    for step in range(2500):
        op = rng.random()
        if op < 0.55:
            rack.post(Codelet(rng.choice(types), rng.randrange(0, 101), time_stamp=clock), clock)
        elif op < 0.65:
            batch = [
                Codelet(rng.choice(types), rng.randrange(0, 101), time_stamp=clock)
                for _ in range(rng.randrange(1, 25))
            ]
            rack.post_deferred(batch, clock, ev_rng)
        elif op < 0.9:
            if rack.choose_and_remove(temperature, None) is not None:
                clock += 1
        elif op < 0.93:
            temperature = float(rng.randrange(0, 101))
        elif op < 0.96:
            rack.clamp_codelet_type(rng.choice(types), rng.randrange(0, 101))
        elif op < 0.98:
            rack.unclamp_all()
        else:
            if rng.random() < 0.3:
                rack.clear()
        assert rack.total_count <= max(rack.max_size, 125)
        rack.check_consistency()
    assert rack.rescales > 0


def test_adopt_keeps_bins_and_order(meta):
    plain = Coderack(meta)
    for i, (t, u) in enumerate(MIX):
        plain.post(Codelet(t, u, time_stamp=i))
    before = [[c.id for c in b.codelets] for b in plain.bins]
    clock = ClockCoderack.adopt(plain, Streams(1))
    assert [[c.id for c in b.codelets] for b in clock.bins] == before
    assert clock.total_count == len(MIX)
    clock.check_consistency()
    # A second adoption of the same rack gives the same clocks (deterministic in rack order).
    again = ClockCoderack.adopt(plain, Streams(1))
    assert again._clock == clock._clock
