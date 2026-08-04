"""Coderack eviction: the Scheme's weight, found incrementally (WP1.1, CR-1).

Two things are being held here at once.

**The weight is the reference's.**  ``get-removal-weight`` (``coderack.ss:237-240``)
is::

    (* (- *codelet-count* time-stamp)
       (add1 (- (tell *coderack* 'get-highest-bin-urgency)
                (tell coderack-bin 'get-urgency))))

— an *unfloored* age times a penalty read off the temperature-indexed rounded urgency
table.  So a codelet posted on the current tick weighs 0 and cannot be evicted, and a
high-urgency codelet in a cold run is a million times safer than a low-urgency one.
Petacat used to floor the age at 1 and use a flat ``num_bins - bin`` at every
temperature (DISCREPANCIES2 CR-1); the oracle below writes the Scheme expression out
directly, from the exponential rather than from ``UrgencyValueTable``, so agreement
means the implementation matches the *reference* and not merely its own table.

**The search for it is incremental.**  ``remove_old_codelets`` used to rebuild a
weight for every codelet on the rack on every eviction.  The rack sits at capacity for
most of a run, so that was 35.8% of runtime on ``abc -> abd; mrrjjj?`` — the single
largest cost in the engine.  The replacement weighs each bin in O(1) from running
aggregates and scans only the bin it lands in.  Its correctness claim is stronger than
"same distribution": it is the same codelet, for the same RNG state, as a brute-force
weighted enumeration over the same rack would have chosen, drawing the same number of
random numbers.
"""

from __future__ import annotations

import os
from collections import Counter

import pytest

from server.engine.coderack import Codelet, Coderack, UrgencyValueTable
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

TEMPERATURES = [0.0, 25.0, 50.0, 75.0, 100.0]


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


# --- the oracle: the Scheme expression, brute-forced ------------------------


def scheme_bin_urgency(bin_number: int, temperature: float) -> int:
    """``(round (expt (add1 bin) (/ (+ (100- T) 10) 15.0)))`` — ``coderack.ss:55-61``.

    Written from the Scheme rather than from ``UrgencyValueTable`` on purpose: an
    oracle expressed in terms of the thing under test would only prove
    self-consistency.
    """
    return round((bin_number + 1) ** ((100 - round(temperature) + 10) / 15.0))


def scheme_removal_weight(
    coderack: Coderack, codelet: Codelet, current_time: int, temperature: float
) -> int:
    """``get-removal-weight`` — ``coderack.ss:237-240``, per codelet."""
    highest = scheme_bin_urgency(coderack.num_bins - 1, temperature)
    own = scheme_bin_urgency(coderack._urgency_to_bin(codelet.urgency), temperature)
    return (current_time - codelet.time_stamp) * (1 + highest - own)


def flat_pick_to_remove(
    coderack: Coderack, current_time: int, rng: RNG, temperature: float
):
    """Enumerate every codelet's weight and draw once, as the Scheme does.

    ``stochastic-pick-by-method`` over the whole codelet list (``coderack.ss:438``),
    which falls back to a uniform pick when the weights sum to zero
    (``utilities.ss:443-448``) — exactly what ``RNG.weighted_pick`` does.
    """
    all_codelets = []
    for b in coderack.bins:
        for c in b.codelets:
            weight = scheme_removal_weight(coderack, c, current_time, temperature)
            all_codelets.append((c, b, weight))
    if not all_codelets:
        return None
    items = [x[0] for x in all_codelets]
    weights = [x[2] for x in all_codelets]
    chosen = rng.weighted_pick(items, weights)
    for c, b, _ in all_codelets:
        if c is chosen:
            return c, b
    return None


def _fill(coderack: Coderack, spec: list[tuple[int, int]]) -> None:
    """Post codelets described as ``(urgency, time_stamp)`` pairs, without eviction."""
    for urgency, time_stamp in spec:
        codelet = Codelet("bottom-up-bond-scout", urgency, time_stamp=time_stamp)
        bin_index = coderack._urgency_to_bin(urgency)
        coderack.bins[bin_index].add(codelet)
        coderack._total_count += 1


# --- the urgency table -----------------------------------------------------


@pytest.mark.parametrize(
    "temperature, expected",
    [
        # T=100, exponent 10/15: 1, 2^0.667=1.587, 3^0.667=2.080, 4^0.667=2.520,
        # 5^0.667=2.924, 6^0.667=3.302, 7^0.667=3.659 — rounded.
        (100.0, (1, 2, 2, 3, 3, 3, 4)),
        # T=50, exponent 60/15 = 4 exactly: the fourth powers, no rounding involved.
        (50.0, (1, 16, 81, 256, 625, 1296, 2401)),
        # T=0, exponent 110/15 = 7.333...  Verified to 50 significant digits, and no
        # entry of the whole 7 x 101 table lands within 1e-6 of a half, so Chez's
        # ``round`` and Python's — both ties-to-even — cannot disagree anywhere.
        (0.0, (1, 161, 3154, 26008, 133592, 508677, 1575381)),
    ],
)
def test_the_urgency_table_is_the_rounded_scheme_table(meta, temperature, expected):
    """``%urgency-value-table%`` is rounded to integers (CR-2).

    The port used the same exponential unrounded, which at T=100 gives
    ``[1, 1.587, 2.080, ...]`` — bin 1 weighted 26% lighter than the reference, and
    bins 1/2 and 3/4/5 ordered where the reference ties them.
    """
    assert Coderack(meta).urgency_table.row(temperature) == expected


@pytest.mark.parametrize(
    "temperature, expected",
    [
        (100.0, (4, 3, 3, 2, 2, 2, 1)),
        (50.0, (2401, 2386, 2321, 2146, 1777, 1106, 1)),
        (0.0, (1575381, 1575221, 1572228, 1549374, 1441790, 1066705, 1)),
    ],
)
def test_the_removal_penalty_is_scaled_by_temperature(meta, temperature, expected):
    """``1 + highest-bin-urgency - bin-urgency`` (CR-1).

    Petacat used a flat ``[7,6,5,4,3,2,1]`` at every temperature.  The reference's
    spread grows enormously as the run cools, which is the mechanism by which a cold
    run protects the structures it has committed to.
    """
    assert Coderack(meta).urgency_table.removal_penalties(temperature) == expected


def test_the_table_is_built_once_per_shape(meta):
    """The Scheme builds it at load time; two racks must not each pay for one."""
    assert Coderack(meta).urgency_table is Coderack(meta).urgency_table


@pytest.mark.parametrize("temperature", [-5.0, 0.4, 49.6, 100.0, 137.0])
def test_the_table_index_is_the_rounded_clamped_temperature(temperature):
    """The Scheme's ``*temperature*`` is an integer in [0, 100]; Petacat's is a float."""
    index = UrgencyValueTable.index(temperature)
    assert 0 <= index <= 100
    assert index == min(100, max(0, round(temperature)))


# --- the aggregate ---------------------------------------------------------


@pytest.mark.parametrize(
    "stamps, current_time",
    [
        ([0, 0, 0], 10),
        ([1, 2, 3, 4, 5], 10),
        ([10, 10, 10], 10),           # every codelet posted at the current instant
        ([0, 5, 10], 10),
        ([7], 7),
        ([], 10),
        ([3, 3, 9, 9, 9], 9),
    ],
)
def test_age_sum_matches_the_direct_computation(meta, stamps, current_time):
    """``age_sum`` is the closed form for Σ (t - ts); check it against Σ.

    With the floor gone this is arithmetic rather than a special case, which is the
    point: a same-tick codelet contributes 0, not 1.
    """
    coderack = Coderack(meta)
    _fill(coderack, [(35, ts) for ts in stamps])
    b = coderack.bins[coderack._urgency_to_bin(35)]
    expected = sum(current_time - ts for ts in stamps)
    assert b.age_sum(current_time) == expected


def test_age_sum_is_nonnegative_when_a_stamp_is_ahead_of_the_clock(meta):
    """Nothing in the engine posts into the future, but the guard must hold.

    A negative contribution would make a bin's weight negative and corrupt the draw,
    so the guard floors the individual age at 0 — not at 1, which would resurrect the
    behaviour CR-1 removes.
    """
    coderack = Coderack(meta)
    _fill(coderack, [(35, 50), (35, 10)])
    b = coderack.bins[coderack._urgency_to_bin(35)]
    assert b.age_sum(20) == 0 + (20 - 10)


def test_aggregates_survive_removal(meta):
    coderack = Coderack(meta)
    _fill(coderack, [(35, 3), (35, 8), (35, 8)])
    b = coderack.bins[coderack._urgency_to_bin(35)]

    b.remove(b.codelets[1])
    assert b.age_sum(10) == (10 - 3) + (10 - 8)

    b.remove(b.codelets[-1])
    assert b.age_sum(10) == (10 - 3)


def test_clear_resets_the_aggregates(meta):
    coderack = Coderack(meta)
    _fill(coderack, [(35, 1), (80, 2)])
    coderack.clear()
    for b in coderack.bins:
        assert b.age_sum(10) == 0
        assert b.sum_time_stamp == 0


# --- identical selection ---------------------------------------------------


@pytest.mark.parametrize("temperature", TEMPERATURES)
@pytest.mark.parametrize("seed", range(15))
def test_eviction_picks_the_same_codelet_as_the_flat_scan(meta, seed, temperature):
    """The incremental search reproduces the brute-force draw, at every temperature.

    Two racks are built identically and one pick is taken from each with RNGs at the
    same state.  Same codelet, and the same number of random draws consumed.
    """
    spec = [
        (urgency, time_stamp)
        for urgency in (5, 20, 35, 50, 65, 80, 95)
        for time_stamp in (0, 1, 4, 9, 16, 25, 36)
    ]

    fast = Coderack(meta)
    _fill(fast, spec)
    slow = Coderack(meta)
    _fill(slow, spec)

    fast_rng, slow_rng = RNG(seed), RNG(seed)
    current_time = 40

    fast_choice = fast._pick_codelet_to_remove(current_time, fast_rng, temperature)
    slow_choice = flat_pick_to_remove(slow, current_time, slow_rng, temperature)

    assert fast_choice is not None and slow_choice is not None
    fast_codelet, fast_bin = fast_choice
    slow_codelet, slow_bin = slow_choice

    assert fast_bin.bin_number == slow_bin.bin_number
    assert (fast_codelet.urgency, fast_codelet.time_stamp) == (
        slow_codelet.urgency,
        slow_codelet.time_stamp,
    )
    # Position within the bin, so two codelets with identical fields are still
    # distinguished — otherwise the assertion above could pass on the wrong one.
    assert fast_bin.codelets.index(fast_codelet) == slow_bin.codelets.index(slow_codelet)
    assert fast_rng.call_count == slow_rng.call_count


@pytest.mark.parametrize("temperature", TEMPERATURES)
@pytest.mark.parametrize("seed", range(6))
def test_repeated_eviction_agrees_with_the_flat_scan(meta, seed, temperature):
    """Agreement holds across a whole sequence of removals, not just the first.

    A single pick can agree by luck; a run of thirty cannot, and it also exercises
    the aggregates being maintained correctly as the rack drains.
    """
    spec = [
        (urgency, time_stamp)
        for urgency in (10, 30, 55, 70, 90)
        for time_stamp in (0, 2, 6, 11, 17, 24, 32, 41)
    ]

    fast = Coderack(meta)
    _fill(fast, spec)
    slow = Coderack(meta)
    _fill(slow, spec)

    fast_rng, slow_rng = RNG(seed), RNG(seed)

    for step in range(30):
        current_time = 45 + step
        removed = fast.remove_old_codelets(current_time, 1, fast_rng, temperature)
        slow_choice = flat_pick_to_remove(slow, current_time, slow_rng, temperature)
        assert slow_choice is not None
        slow_codelet, slow_bin = slow_choice
        slow_bin.remove(slow_codelet)
        slow._total_count -= 1

        assert len(removed) == 1
        assert (removed[0].urgency, removed[0].time_stamp) == (
            slow_codelet.urgency,
            slow_codelet.time_stamp,
        )
        assert fast.total_count == slow.total_count
        assert fast_rng.call_count == slow_rng.call_count


@pytest.mark.parametrize("temperature", [100.0, 50.0])
def test_the_eviction_distribution_matches_the_enumerated_weights(meta, temperature):
    """Empirical frequencies against the analytic weights, not against another pick.

    The agreement tests above share a rack with the oracle and are therefore blind to
    a weight that is wrong in the same way on both sides.  This one draws thousands of
    evictions and compares the observed per-bin frequency to
    ``Σ weight(bin) / Σ weight``, computed from the Scheme expression.
    """
    spec = [
        (urgency, time_stamp)
        for urgency in (5, 20, 35, 50, 65, 80, 95)
        for time_stamp in (0, 3, 7, 12, 18, 27, 39)
    ]
    current_time = 45

    rack = Coderack(meta)
    _fill(rack, spec)
    weight_by_bin: Counter = Counter()
    for b in rack.bins:
        for c in b.codelets:
            weight_by_bin[b.bin_number] += scheme_removal_weight(
                rack, c, current_time, temperature
            )
    total_weight = sum(weight_by_bin.values())

    # ``_pick_codelet_to_remove`` chooses without removing, so one rack samples the
    # same distribution every time.
    observed: Counter = Counter()
    rng = RNG(20260803)
    trials = 8000
    for _ in range(trials):
        chosen = rack._pick_codelet_to_remove(current_time, rng, temperature)
        assert chosen is not None
        observed[chosen[1].bin_number] += 1

    for bin_number in range(rack.num_bins):
        expected = weight_by_bin[bin_number] / total_weight
        actual = observed[bin_number] / trials
        assert abs(actual - expected) < 0.02, (
            f"bin {bin_number} at T={temperature}: {actual:.4f} vs {expected:.4f}"
        )


# --- the unfloored age, which is the behaviour CR-1 restores ---------------


@pytest.mark.parametrize("temperature", TEMPERATURES)
def test_a_same_tick_codelet_is_never_evicted_while_an_older_one_exists(
    meta, temperature
):
    """Weight 0 means unevictable, at every temperature and in every bin.

    This is the whole of the ``max(1, age)`` removal: the Scheme's age is
    ``(- *codelet-count* time-stamp)`` outright, so a codelet that has not yet had a
    chance to be selected is not what the rack sheds.  One same-tick codelet is placed
    in each bin — including bin 6, where the penalty is 1 and its weight would
    otherwise be smallest — alongside older ones.
    """
    current_time = 60
    fresh = []
    coderack = Coderack(meta)
    for urgency in (5, 20, 35, 50, 65, 80, 95):
        for time_stamp in (0, 10, 30):
            _fill(coderack, [(urgency, time_stamp)])
        _fill(coderack, [(urgency, current_time)])
        fresh.append(coderack.bins[coderack._urgency_to_bin(urgency)].codelets[-1])

    rng = RNG(4)
    for _ in range(400):
        chosen = coderack._pick_codelet_to_remove(current_time, rng, temperature)
        assert chosen is not None
        assert chosen[0] not in fresh


def test_a_rack_of_only_same_tick_codelets_falls_back_to_a_uniform_pick(meta):
    """Every weight 0 — which the floor used to make unreachable.

    The Scheme's ``stochastic-pick`` defers to ``random-pick`` on a zero weight-sum
    (``utilities.ss:443-448``), so the rack still sheds a codelet rather than
    overflowing; it just has no reason to prefer one.
    """
    coderack = Coderack(meta)
    _fill(coderack, [(urgency, 30) for urgency in (5, 20, 35, 50, 65, 80, 95)])

    seen = set()
    rng = RNG(9)
    for _ in range(200):
        chosen = coderack._pick_codelet_to_remove(30, rng, 50.0)
        assert chosen is not None
        seen.add(id(chosen[0]))
    assert len(seen) == 7


def test_capacity_is_still_enforced_when_every_codelet_is_the_same_age(meta):
    """The rack must not grow past capacity in a posting burst, weights or no weights.

    ``update_everything`` posts many codelets under one codelet count, so a burst that
    fills the rack leaves every candidate weighing 0 — the degenerate case the
    reference resolves with a uniform pick.
    """
    coderack = Coderack(meta)
    coderack.rng = RNG(13)
    for _ in range(coderack.max_size + 40):
        coderack.post(Codelet("bottom-up-bond-scout", 35, time_stamp=500), 500)
    assert coderack.total_count == coderack.max_size


# --- temperature plumbing --------------------------------------------------


def test_eviction_uses_the_temperature_the_rack_was_last_drawn_at(meta):
    """``get-removal-weight`` reads the live ``*temperature*``; Petacat is handed it.

    Every step selects before anything can post, so the remembered value is the one
    the run is at.  An explicit ``temperature=`` argument overrides it.
    """
    coderack = Coderack(meta)
    assert coderack.current_temperature == 100.0
    _fill(coderack, [(35, 0)])
    coderack.choose_and_remove(17.0, RNG(1))
    assert coderack.current_temperature == 17.0


def test_selection_and_eviction_read_the_same_table(meta):
    """CR-1 and CR-2 are one table, as they are one table in the Scheme."""
    coderack = Coderack(meta)
    table = coderack.urgency_table
    for temperature in TEMPERATURES:
        row = table.row(temperature)
        penalties = table.removal_penalties(temperature)
        assert penalties == tuple(1 + row[-1] - value for value in row)
        b = coderack.bins[3]
        _fill(coderack, [(50, 0)])
        assert b.get_urgency_sum(temperature, table) == len(b.codelets) * row[3]
        coderack.clear()


# --- unchanged behaviour ---------------------------------------------------


def test_eviction_of_an_empty_rack_removes_nothing(meta):
    coderack = Coderack(meta)
    assert coderack.remove_old_codelets(10, 3, RNG(1)) == []


def test_eviction_stops_when_the_rack_runs_out(meta):
    coderack = Coderack(meta)
    _fill(coderack, [(35, 0), (35, 1)])
    removed = coderack.remove_old_codelets(10, 5, RNG(1))
    assert len(removed) == 2
    assert coderack.total_count == 0


def test_capacity_is_still_enforced_on_post(meta):
    """The behaviour eviction exists for, unchanged."""
    coderack = Coderack(meta)
    coderack.rng = RNG(7)
    for i in range(coderack.max_size + 40):
        coderack.post(Codelet("bottom-up-bond-scout", 35, time_stamp=i), i)
    assert coderack.total_count == coderack.max_size
    assert sum(len(b.codelets) for b in coderack.bins) == coderack.max_size
