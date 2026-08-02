"""The candidate sharded coderacks (WP4.3).

Selection is a two-stage urgency-weighted draw, and that distribution is *how temperature
regulates exploration* — nearly random when hot, greedy when cold.  A decomposition that
distorts it does not make the engine faster; it makes it a different engine.  So fidelity
is the veto here, and contention only decides between the candidates that pass it.

``scripts/bench_shards.py`` is the measurement; these are the properties worth pinning so
the winner cannot regress into one of the losers.
"""

from __future__ import annotations

import os
import threading
from collections import Counter

import pytest

from server.engine.coderack import Codelet, Coderack
from server.engine.coderack_shards import (
    CANDIDATES,
    MIN_SHARD_CAPACITY,
    FamilyShardedCoderack,
    LockedCoderack,
    WorkerShardedCoderack,
    build_candidate,
)
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.engine.runner import EngineRunner

# Every test here executes arithmetic the numeric substrate owns, so each one runs
# once per backend in the matrix. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "seed_data",
)

MIX = [
    ("bottom-up-bond-scout", 20),
    ("bond-evaluator", 45),
    ("rule-evaluator", 60),
    ("answer-finder", 85),
    ("breaker", 5),
]


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


def _fill(rack, count: int, rng: RNG) -> None:
    for index in range(count):
        codelet_type, urgency = MIX[index % len(MIX)]
        rack.post(Codelet(codelet_type, urgency, time_stamp=index % 400), 500, rng)


def _raise_capacity(rack) -> None:
    for inner in getattr(rack, "_racks", None) or []:
        inner.max_size = 10_000
    inner = getattr(rack, "_rack", None)
    if inner is not None:
        inner.max_size = 10_000


# --- the common surface ----------------------------------------------------


@pytest.mark.parametrize("name", sorted(CANDIDATES))
def test_every_candidate_presents_the_coderack_surface(meta, name):
    """The runner must not need to know which is installed.

    That is what lets a candidate be swapped in for measurement, and what will let WP4.4
    change its mind later without touching the engine.
    """
    rack = build_candidate(name, meta, 4)
    _raise_capacity(rack)
    rng = RNG(1)
    rack.rng = rng

    assert rack.is_empty
    _fill(rack, 40, rng)
    assert rack.total_count == 40
    assert not rack.is_empty

    drawn = rack.choose_and_remove(50.0, rng)
    assert isinstance(drawn, Codelet)
    assert rack.total_count == 39

    counts = rack.get_codelet_type_counts()
    assert sum(counts.values()) == 39

    rack.clear()
    assert rack.total_count == 0


def test_an_unknown_candidate_is_rejected(meta):
    with pytest.raises(ValueError, match="unknown coderack candidate"):
        build_candidate("region", meta, 4)


def test_a_drained_rack_returns_none(meta):
    for name in sorted(CANDIDATES):
        rack = build_candidate(name, meta, 4)
        assert rack.choose_and_remove(50.0, RNG(1)) is None


# --- fidelity, which is the veto -------------------------------------------


def _draw_distribution(rack, rng, temperature: float, take: int) -> Counter:
    counts: Counter = Counter()
    for _ in range(take):
        codelet = rack.choose_and_remove(temperature, rng)
        if codelet is None:
            break
        counts[codelet.codelet_type] += 1
    return counts


def _tv(a: Counter, b: Counter) -> float:
    ta, tb = sum(a.values()), sum(b.values())
    if not ta or not tb:
        return 1.0
    return 0.5 * sum(abs(a[k] / ta - b[k] / tb) for k in set(a) | set(b))


def _spread_across_shards(rack, count: int, rng: RNG) -> None:
    """Populate via the rack's own ``post`` from several threads.

    Each candidate must place codelets the way it actually would — family by codelet type,
    worker by posting thread. Filling shards directly would erase family sharding's
    defining property and flatter it.
    """
    per_thread = max(1, count // rack.num_shards)

    def poster(offset: int) -> None:
        local = RNG(500 + offset)
        for step in range(per_thread):
            index = offset * per_thread + step
            codelet_type, urgency = MIX[index % len(MIX)]
            rack.post(Codelet(codelet_type, urgency, time_stamp=index % 400), 500, local)

    threads = [threading.Thread(target=poster, args=(i,)) for i in range(rack.num_shards)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_the_locked_rack_is_exactly_the_serial_rack(meta):
    """Fidelity is perfect by construction, because it *is* the serial rack under a mutex.

    Worth asserting rather than assuming: it is the control everything else is measured
    against, and a control that had drifted would invalidate the comparison.
    """
    reference = Coderack(meta)
    reference.max_size = 10_000
    rng_a = RNG(77)
    reference.rng = rng_a
    _fill(reference, 200, rng_a)

    locked = LockedCoderack(meta)
    _raise_capacity(locked)
    rng_b = RNG(77)
    locked.rng = rng_b
    _fill(locked, 200, rng_b)

    for _ in range(60):
        assert (
            reference.choose_and_remove(40.0, rng_a).codelet_type
            == locked.choose_and_remove(40.0, rng_b).codelet_type
        )


@pytest.mark.parametrize("temperature", [100.0, 10.0])
def test_worker_sharding_preserves_the_selection_distribution(meta, temperature):
    """The winner's central claim.

    Because a codelet's shard is independent of its type and its urgency, each shard's bin
    occupancy is an unbiased sample of the whole rack's — so a shard's two-stage draw has
    the same distribution as the whole rack's in expectation, at any temperature.
    Measured at 0.006-0.016 total-variation distance; the bound here is loose enough not
    to flake and far below family sharding's 0.35.
    """
    population, take, trials = 320, 32, 40
    reference: Counter = Counter()
    observed: Counter = Counter()

    for trial in range(trials):
        plain = Coderack(meta)
        plain.max_size = 10_000
        rng = RNG(900 + trial)
        plain.rng = rng
        _fill(plain, population, rng)
        reference += _draw_distribution(plain, rng, temperature, take)

        sharded = WorkerShardedCoderack(meta, 8)
        _raise_capacity(sharded)
        rng2 = RNG(900 + trial)
        sharded.rng = rng2
        _spread_across_shards(sharded, population, rng2)
        observed += _draw_distribution(sharded, rng2, temperature, take)

    assert _tv(reference, observed) < 0.08


def test_family_sharding_distorts_the_distribution_and_worsens_when_cold(meta):
    """The measured reason family sharding was rejected, pinned so it is not revived.

    Codelet families are *not* evenly spread across urgency bins — bottom-up scouts sit
    at low urgency, answer-finders at ``100 - temperature``. So a family shard's bin
    occupancy is systematically unlike the whole rack's, and a worker confined to one sees
    a different temperature response from the architecture's. The distortion therefore
    grows as the engine cools, which is precisely where selection is supposed to become
    greedy: measured 0.078 at T=100 rising to 0.354 at T=10.
    """
    population, take, trials = 320, 32, 40
    distances = {}

    for temperature in (100.0, 10.0):
        reference: Counter = Counter()
        observed: Counter = Counter()
        for trial in range(trials):
            plain = Coderack(meta)
            plain.max_size = 10_000
            rng = RNG(1500 + trial)
            plain.rng = rng
            _fill(plain, population, rng)
            reference += _draw_distribution(plain, rng, temperature, take)

            sharded = FamilyShardedCoderack(meta, 8)
            _raise_capacity(sharded)
            rng2 = RNG(1500 + trial)
            sharded.rng = rng2
            _spread_across_shards(sharded, population, rng2)
            observed += _draw_distribution(sharded, rng2, temperature, take)
        distances[temperature] = _tv(reference, observed)

    assert distances[10.0] > distances[100.0], distances
    assert distances[10.0] > 0.15, distances


# --- the winner, against the engine ----------------------------------------


def test_the_sharded_rack_drives_a_real_run(meta):
    """Installed in a live runner, at one worker, it must simply work.

    The expected-range check over 13 problems x 100 runs — 0 novel, 0 missing — is the
    real gate and lives in the benchmark script; this is the cheap version that keeps the
    integration honest in the ordinary suite.
    """
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "mrrjjj", seed=42)

    sharded = WorkerShardedCoderack(meta, 8)
    sharded.rng = runner.ctx.rng
    for b in runner.ctx.coderack.bins:
        for codelet in list(b.codelets):
            sharded.post(codelet, 0, runner.ctx.rng)
    runner.ctx.coderack = sharded

    result = runner.run_mcat(max_steps=1500)
    assert result.codelet_count > 0
    assert result.status in {"answer_found", "halted", "gave_up"}


def test_shards_of_one_behave_as_a_single_rack(meta):
    """One shard must degenerate exactly, since that is what a one-worker run is."""
    for name in ("family", "worker"):
        rack = build_candidate(name, meta, 1)
        _raise_capacity(rack)
        rng = RNG(3)
        rack.rng = rng
        _fill(rack, 50, rng)
        assert rack.num_shards == 1
        assert rack.total_count == 50
        assert rack.choose_and_remove(50.0, rng) is not None


def test_work_stealing_empties_the_rack_rather_than_stalling(meta):
    """A worker whose own shard is empty must not report the rack empty.

    Without stealing, a run would stall with work still queued — and the symptom would be
    a run that halts early for no visible reason.
    """
    rack = WorkerShardedCoderack(meta, 8)
    _raise_capacity(rack)
    rng = RNG(11)
    rack.rng = rng
    # Everything into one shard, then drain from a thread affine to a different one.
    for index in range(40):
        rack._racks[3].post(Codelet("bottom-up-bond-scout", 20, time_stamp=index), 500, rng)

    drawn = 0
    while not rack.is_empty:
        codelet = rack.choose_and_remove(50.0, rng, worker=0)
        if codelet is None:
            break
        drawn += 1

    assert drawn == 40
    assert rack.steals > 0


# --- capacity, which turned out to be where the cognition lives ------------


def test_sharding_divides_the_capacity_rather_than_replicating_it(meta):
    """N shards must hold what one rack holds, not N times as much.

    Each ``Coderack`` enforces ``max_coderack_size`` for itself, so shards left alone
    multiply the rack's population by the shard count. The cap is not bookkeeping: it is
    why the codelet mix keeps tracking the current Workspace instead of drifting, and on
    ``mrrjjj`` the rack sits at capacity for 58% of posts, so an eight-fold capacity
    would remove almost all eviction pressure.
    """
    single = Coderack(meta).max_size
    for requested in (1, 2, 4, 8):
        rack = WorkerShardedCoderack(meta, requested)
        assert sum(r.max_size for r in rack._racks) == single


def test_shard_count_is_bounded_by_capacity_not_by_worker_count(meta):
    """A shard below ``MIN_SHARD_CAPACITY`` stops being a coderack.

    Measured on ``eqe -> qeq; abbba?``: at eight shards of twelve, the stopping state
    ``gave_up:`` vanished entirely — 0 in 60 runs, against 23 for the serial engine, and
    it is that problem's most frequent outcome at 38.9%. Giving up is the end of a
    *sequence* — snags accumulate, a clamp is applied, jootsers observe the repetition —
    and each step needs its codelets still on the rack when the next one looks. A shard
    that small evicts them first.

    So more workers than shards is allowed, and costs contention; more shards than the
    capacity supports is not, because it costs cognition.
    """
    capacity = Coderack(meta).max_size
    for requested in (8, 16, 64):
        rack = WorkerShardedCoderack(meta, requested)
        assert rack.num_shards <= capacity // MIN_SHARD_CAPACITY
        for inner in rack._racks:
            assert inner.max_size >= MIN_SHARD_CAPACITY


def test_the_sharded_rack_exposes_seven_bins_however_many_shards(meta):
    """Seven urgency levels, merged — not seven per shard.

    Sharding decides which worker holds a codelet, not what urgency it is, and every
    reader of ``bins`` is asking about urgency. Returning the shards' bins end to end
    made a captured coderack un-restorable, because a restore indexes ``bins[index]`` on
    a plain seven-bin rack.
    """
    plain = Coderack(meta)
    for requested in (1, 2, 4, 8):
        rack = WorkerShardedCoderack(meta, requested)
        _raise_capacity(rack)
        rng = RNG(5)
        rack.rng = rng
        _fill(rack, 60, rng)
        assert len(rack.bins) == plain.num_bins
        assert sum(len(b.codelets) for b in rack.bins) == rack.total_count
        assert [b.bin_number for b in rack.bins] == list(range(plain.num_bins))


def test_the_sharded_rack_can_be_captured(meta):
    """The fields ``state_graph`` reads must exist, or a free-running run cannot be saved.

    Found by wiring free-running into the API: the capture reached for
    ``clamped_urgencies`` and ``max_size`` and the sharded rack had neither, so a
    Normal free-running Run raised at its first boundary capture.
    """
    rack = WorkerShardedCoderack(meta, 4)
    assert isinstance(rack.clamped_urgencies, dict)
    assert rack.max_size == Coderack(meta).max_size
    rack.clamp_codelet_type("breaker", 90)
    assert rack.clamped_urgencies["breaker"] == 90
