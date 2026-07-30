"""Counter-based per-codelet random streams (WP4.1).

Three claims are worth testing, because free-running rests on all three: that separate
streams are genuinely independent, that a stream can be evaluated without evaluating
the ones before it, and that concurrent use needs no lock.

Distribution quality is tested loosely and deliberately so. The engine uses these for
temperature-adjusted probabilities and weighted picks over short lists; what matters is
the absence of gross bias, not a statistical certification. Tests that pin a
distribution tightly fail on sampling noise and get deleted, which is worse than a
loose test that keeps working.
"""

from __future__ import annotations

import threading
from collections import Counter

import pytest

from server.engine.splittable_rng import SplittableRNG


# --- reproducibility without sequentiality ---------------------------------


def test_a_stream_is_reproducible():
    a = SplittableRNG(seed=42, stream=7)
    b = SplittableRNG(seed=42, stream=7)
    assert [a.random() for _ in range(20)] == [b.random() for _ in range(20)]


def test_a_stream_can_be_evaluated_without_evaluating_earlier_ones():
    """The property a stateful generator cannot offer.

    Reproducing draw *n* from a Mersenne Twister requires having made draws 0..n-1 in
    the same order. Under free-running that order does not exist, which is precisely
    why the shared generator had to go.
    """
    sequential = SplittableRNG(seed=1, stream=3)
    values = [sequential.random() for _ in range(50)]

    direct = SplittableRNG(seed=1, stream=3, counter=49)
    assert direct.random() == values[49]


def test_different_seeds_give_different_streams():
    a = SplittableRNG(seed=1, stream=0)
    b = SplittableRNG(seed=2, stream=0)
    assert [a.random() for _ in range(10)] != [b.random() for _ in range(10)]


def test_state_round_trips():
    rng = SplittableRNG(seed=5, stream=9)
    for _ in range(13):
        rng.random()
    saved = rng.get_state()
    expected = [rng.random() for _ in range(5)]

    resumed = SplittableRNG(seed=0)
    resumed.set_state(saved)
    assert [resumed.random() for _ in range(5)] == expected


def test_state_is_three_integers():
    """Small enough to store readably, which the 625-element MT state was not."""
    state = SplittableRNG(seed=3, stream=4).get_state()
    assert len(state) == 3
    assert all(isinstance(x, int) for x in state)


# --- independence -----------------------------------------------------------


def test_adjacent_streams_do_not_correlate():
    """Neighbouring stream ids must not produce neighbouring sequences.

    This is the failure a naive derivation gives — seeding stream *n* with ``base + n``
    leaves consecutive workers drawing near-identical sequences, which under
    free-running means every worker making the same decision at the same moment.
    """
    first = [SplittableRNG(seed=99, stream=n).random() for n in range(200)]
    second = [SplittableRNG(seed=99, stream=n + 1).random() for n in range(200)]
    matches = sum(1 for a, b in zip(first, second) if abs(a - b) < 0.001)
    assert matches < 5, f"{matches} of 200 adjacent streams produced near-equal draws"


def test_split_produces_an_independent_substream():
    parent = SplittableRNG(seed=11, stream=2)
    child_a = parent.split(1)
    child_b = parent.split(2)

    assert child_a.stream != child_b.stream
    assert child_a.stream != parent.stream
    assert [child_a.random() for _ in range(10)] != [child_b.random() for _ in range(10)]


def test_split_does_not_disturb_the_parent():
    """Splitting has to be safe to do concurrently from one parent."""
    parent = SplittableRNG(seed=11, stream=2)
    before = parent.get_state()
    parent.split(1)
    parent.split(2)
    assert parent.get_state() == before


def test_split_is_deterministic():
    assert SplittableRNG(seed=7, stream=1).split(5).stream == (
        SplittableRNG(seed=7, stream=1).split(5).stream
    )


def test_codelet_streams_depend_on_position_not_history():
    """A codelet's stream comes from ``(seed, worker, slot)``.

    Deriving it from a running count would not survive reordering, and under
    free-running the order is exactly what is not determined.
    """
    root = SplittableRNG(seed=123)
    a = root.for_codelet(worker=0, slot=500)
    b = root.for_codelet(worker=0, slot=500)
    c = root.for_codelet(worker=1, slot=500)
    d = root.for_codelet(worker=0, slot=501)

    assert a.stream == b.stream
    assert a.stream != c.stream
    assert a.stream != d.stream


def test_codelet_streams_across_workers_are_distinct():
    """8 workers x 500 slots, all distinct — collisions would silently couple workers."""
    root = SplittableRNG(seed=2024)
    streams = {
        root.for_codelet(worker=w, slot=s).stream
        for w in range(8)
        for s in range(500)
    }
    assert len(streams) == 8 * 500


# --- distribution -----------------------------------------------------------


def test_random_stays_in_range():
    rng = SplittableRNG(seed=1)
    assert all(0.0 <= rng.random() < 1.0 for _ in range(5000))


def test_random_is_roughly_uniform():
    rng = SplittableRNG(seed=1)
    buckets = Counter(int(rng.random() * 10) for _ in range(20000))
    assert set(buckets) == set(range(10))
    assert all(1600 < count < 2400 for count in buckets.values()), buckets


@pytest.mark.parametrize("n", [1, 2, 3, 7, 10, 64, 100])
def test_randint_covers_its_range_without_exceeding_it(n):
    rng = SplittableRNG(seed=n)
    draws = [rng.randint(n) for _ in range(max(2000, n * 50))]
    assert all(0 <= d < n for d in draws)
    assert len(set(draws)) == n


def test_randint_is_not_modulo_biased():
    """Rejection sampling rather than a modulo.

    A modulo over a 64-bit draw favours the low residues whenever the bound does not
    divide 2**64. The bias is small at these sizes, but the correct version costs one
    comparison that almost never retries, so there is no reason to accept it.
    """
    rng = SplittableRNG(seed=17)
    counts = Counter(rng.randint(3) for _ in range(30000))
    assert all(9200 < c < 10800 for c in counts.values()), counts


def test_prob_matches_its_argument():
    rng = SplittableRNG(seed=8)
    hits = sum(rng.prob(0.25) for _ in range(20000))
    assert 4500 < hits < 5500


def test_prob_handles_the_certain_cases_without_drawing():
    rng = SplittableRNG(seed=8)
    before = rng.call_count
    assert rng.prob(1.0) is True
    assert rng.prob(0.0) is False
    assert rng.call_count == before


def test_weighted_pick_follows_the_weights():
    rng = SplittableRNG(seed=3)
    counts = Counter(rng.weighted_pick(["a", "b"], [3.0, 1.0]) for _ in range(8000))
    assert 5600 < counts["a"] < 6400


def test_weighted_pick_falls_back_to_uniform_on_zero_weights():
    rng = SplittableRNG(seed=3)
    counts = Counter(rng.weighted_pick(["a", "b"], [0.0, 0.0]) for _ in range(4000))
    assert 1800 < counts["a"] < 2200


def test_empty_sequences_raise():
    rng = SplittableRNG(seed=1)
    with pytest.raises(ValueError):
        rng.pick([])
    with pytest.raises(ValueError):
        rng.weighted_pick([], [])


# --- concurrency ------------------------------------------------------------


def test_separate_streams_need_no_lock():
    """The point of the exercise.

    Eight threads draw from eight streams simultaneously and must get exactly what they
    would have got alone. A shared generator cannot promise this without serialising,
    which is the contention the parallelism exists to avoid.
    """
    root = SplittableRNG(seed=555)
    expected = {
        w: [root.for_codelet(worker=w, slot=0).random() for _ in range(1)][0]
        for w in range(8)
    }

    observed: dict[int, list[float]] = {}

    def worker(index: int) -> None:
        rng = root.for_codelet(worker=index, slot=0)
        observed[index] = [rng.random() for _ in range(2000)]

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(observed) == 8
    for index, values in observed.items():
        assert values[0] == expected[index]

    # No two workers drew the same sequence.
    assert len({tuple(v[:20]) for v in observed.values()}) == 8
