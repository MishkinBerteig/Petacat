"""Incremental coderack eviction picks exactly what the flat scan picked (WP1.1).

``remove_old_codelets`` used to rebuild a weight for every codelet on the rack on
every eviction.  The rack sits at capacity for most of a run, so that was 35.8% of
runtime on ``abc -> abd; mrrjjj?`` — the single largest cost in the engine, and the
reason WP1.1 runs before the rest of Phase 0 rather than after it.

The replacement weighs each bin in O(1) from running aggregates and scans only the
bin it lands in.  Its correctness claim is stronger than "same distribution": it is
the same codelet, for the same RNG state, as the flat version would have chosen.
These tests hold it to that, by keeping a literal transcription of the old algorithm
here and requiring the two to agree.

Keeping the old implementation in the test file is deliberate.  An oracle written in
terms of the new aggregates would be testing the aggregates against themselves; this
one is the code that was actually replaced, so agreement means the replacement is
faithful rather than self-consistent.
"""

from __future__ import annotations

import os

import pytest

from server.engine.coderack import Codelet, Coderack
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


# --- the algorithm WP1.1 replaced, kept as the oracle ----------------------


def flat_pick_to_remove(coderack: Coderack, current_time: int, rng: RNG):
    """The pre-WP1.1 selection, transcribed from ``coderack.py`` at 2c5c086.

    Weights are laid out bin-major and handed to ``RNG.weighted_pick``; the
    replacement's cumulative walk has to visit the same weights in the same order.
    """
    all_codelets = []
    for b in coderack.bins:
        for c in b.codelets:
            age = max(1, current_time - c.time_stamp)
            urgency_penalty = (
                1 + (coderack.num_bins - 1) - coderack._urgency_to_bin(c.urgency)
            )
            all_codelets.append((c, b, age * urgency_penalty))
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


# --- the aggregate ---------------------------------------------------------


@pytest.mark.parametrize(
    "stamps, current_time",
    [
        ([0, 0, 0], 10),
        ([1, 2, 3, 4, 5], 10),
        ([10, 10, 10], 10),           # every codelet posted at the current instant
        ([0, 5, 10], 10),             # the clamp bites for one of three
        ([7], 7),
        ([], 10),
        ([3, 3, 9, 9, 9], 9),
    ],
)
def test_age_sum_matches_the_direct_computation(meta, stamps, current_time):
    """``age_sum`` is the closed form for Σ max(1, t - ts); check it against Σ.

    The ``max(1, ...)`` clamp is the whole difficulty: without it the sum is
    ``count * t - Σ ts`` and trivially incremental.  These cases put codelets on
    both sides of the clamp and exactly on it.
    """
    coderack = Coderack(meta)
    _fill(coderack, [(35, ts) for ts in stamps])
    b = coderack.bins[coderack._urgency_to_bin(35)]
    expected = sum(max(1, current_time - ts) for ts in stamps)
    assert b.age_sum(current_time) == expected


def test_age_sum_is_exact_when_a_stamp_is_ahead_of_the_clock(meta):
    """Nothing in the engine posts into the future, but the guard must hold."""
    coderack = Coderack(meta)
    _fill(coderack, [(35, 50), (35, 10)])
    b = coderack.bins[coderack._urgency_to_bin(35)]
    assert b.age_sum(20) == max(1, 20 - 50) + max(1, 20 - 10)


def test_aggregates_survive_removal(meta):
    coderack = Coderack(meta)
    _fill(coderack, [(35, 3), (35, 8), (35, 8)])
    b = coderack.bins[coderack._urgency_to_bin(35)]

    b.remove(b.codelets[1])          # one of the two newest
    assert b.age_sum(10) == max(1, 10 - 3) + max(1, 10 - 8)

    b.remove(b.codelets[-1])         # the last newest
    assert b.age_sum(10) == max(1, 10 - 3)


def test_clear_resets_the_aggregates(meta):
    coderack = Coderack(meta)
    _fill(coderack, [(35, 1), (80, 2)])
    coderack.clear()
    for b in coderack.bins:
        assert b.age_sum(10) == 0
        assert b.sum_time_stamp == 0
        assert b.count_at_newest == 0


# --- identical selection ---------------------------------------------------


@pytest.mark.parametrize("seed", range(25))
def test_eviction_picks_the_same_codelet_as_the_flat_scan(meta, seed):
    """The property that lets seeded runs stay bit-identical across WP1.1.

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

    fast_choice = fast._pick_codelet_to_remove(current_time, fast_rng)
    slow_choice = flat_pick_to_remove(slow, current_time, slow_rng)

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


@pytest.mark.parametrize("seed", range(10))
def test_repeated_eviction_agrees_with_the_flat_scan(meta, seed):
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
        removed = fast.remove_old_codelets(current_time, 1, fast_rng)
        slow_choice = flat_pick_to_remove(slow, current_time, slow_rng)
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
