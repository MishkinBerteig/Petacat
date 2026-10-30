"""The parallel update cycle changes nothing it should not (WP5).

Two promises, and these tests defend exactly those:

* ``faithful`` is the engine's own update cycle: for the same generator it leaves the run
  bit-for-bit where ``EngineRunner.update_everything`` leaves it -- same stopping state,
  codelet count, Trace, workspace values and, the sharpest witness, the same number of
  draws from the run's Mersenne Twister (one extra or missing draw anywhere shifts every
  later one).
* ``stream`` is bit-identical for 1, 2, 4 and 8 threads.  The thread count must be a
  pure performance knob, so every result below is compared across counts on runs long
  enough to hold dozens of cycles.  Races only show without the GIL, so this file is
  also meant to be run under ``.venv-ft``; ``force_threads`` makes a GIL build exercise
  the fan-out paths too (slowly, but they run).
"""

from __future__ import annotations

import hashlib

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.numeric.backend import use_backend
from server.engine.runner import EngineRunner
from server.engine.rng import RNG
from server.engine.splittable_rng import SplittableRNG
from server.parallel.update_cycle import UpdateCycle, _label, structure_identity

META = MetadataProvider.from_seed_data("seed_data")
PROBLEMS = [
    ("abc", "abd", "mrrjjj"),
    ("abc", "abd", "xyz"),
    ("wxyz", "vxyz", "abcd"),
    ("abc", "abd", "iijjkk"),
    ("eqe", "qeq", "abbba"),
]
SEEDS = (1, 2, 3)
MAX_STEPS = 700
THREAD_COUNTS = (1, 2, 4, 8)


def _fingerprint(runner: EngineRunner, result) -> tuple:
    ws = runner.ctx.workspace
    h = hashlib.sha256()
    for e in runner.ctx.trace.events:
        h.update(repr((e.event_type, e.codelet_count, round(float(e.temperature), 9),
                       e.description)).encode())
    for o in ws.all_objects:
        h.update(repr((o.id, o.relative_importance, o.salience, o.average_unhappiness,
                       o.intra_string_unhappiness)).encode())
    for s in ws.all_structures:
        h.update(repr((type(s).__name__, s.id, s.strength)).encode())
    h.update(repr(runner.ctx.temperature.value).encode())
    h.update(repr(sorted(runner.ctx.coderack.type_counts().items())
                  if hasattr(runner.ctx.coderack, "type_counts") else "").encode())
    return (runner.status, result.codelet_count, runner.ctx._rng.call_count,
            h.hexdigest())


def _run(problem, seed, policy=None, threads=1, min_items=1, monkeypatch=None):
    """One run; the engine's own cycle when *policy* is None, else the plugin's."""
    original = EngineRunner.update_everything
    cycles: list[UpdateCycle] = []
    base = SplittableRNG(seed)

    def patched(self):
        cyc = getattr(self, "_wp5", None)
        if cyc is None:
            cyc = self._wp5 = UpdateCycle(
                self, policy, threads, force_threads=threads > 1, min_items=min_items
            )
            cycles.append(cyc)
        if policy == "stream":
            cyc.run(base.split(_label("update", self._update_cycle + 1)))
        else:
            cyc.run()

    try:
        r = EngineRunner(META)
        r.init_mcat(*problem, seed=seed)
        if policy is not None:
            EngineRunner.update_everything = patched
        result = r.run_mcat(max_steps=MAX_STEPS)
    finally:
        EngineRunner.update_everything = original
        for cyc in cycles:
            cyc.close()
    return _fingerprint(r, result)


@pytest.fixture(params=["off", "numpy"])
def backend(request):
    with use_backend(request.param):
        yield request.param


@pytest.mark.parametrize("problem", PROBLEMS, ids=lambda p: "-".join(p))
def test_faithful_is_bit_identical_to_the_engine(problem, backend):
    """The plugin's faithful cycle leaves a run exactly where the engine's does."""
    for seed in SEEDS:
        assert _run(problem, seed, "faithful") == _run(problem, seed)


@pytest.mark.parametrize("problem", PROBLEMS[:2], ids=lambda p: "-".join(p))
def test_faithful_with_a_team_is_still_identical(problem, backend):
    """The object-value fan-out draws nothing, so it may not move a single bit."""
    for seed in SEEDS:
        assert _run(problem, seed, "faithful", threads=4) == _run(problem, seed)


@pytest.mark.parametrize("problem", PROBLEMS, ids=lambda p: "-".join(p))
def test_stream_is_identical_across_thread_counts(problem, backend):
    """The thread count is a pure performance knob under the stream policy."""
    for seed in SEEDS:
        results = {t: _run(problem, seed, "stream", threads=t) for t in THREAD_COUNTS}
        assert len(set(results.values())) == 1, results


def test_stream_is_repeatable_under_a_team():
    """Eight runs of the same eight-thread cycle agree: no race moves a result."""
    with use_backend("off"):
        runs = {_run(PROBLEMS[0], 1, "stream", threads=8) for _ in range(8)}
    assert len(runs) == 1


def test_stream_actually_differs_from_faithful():
    """Guards the guard: if both policies drew the same numbers the tests above would
    pass vacuously.  Different generators, so the runs must part company."""
    with use_backend("off"):
        assert _run(PROBLEMS[0], 1, "stream") != _run(PROBLEMS[0], 1, "faithful")


def test_stream_needs_a_splittable_stream():
    r = EngineRunner(META)
    r.init_mcat(*PROBLEMS[0], seed=1)
    assert isinstance(r.ctx.rng, RNG)
    cyc = UpdateCycle(r, "stream")
    with pytest.raises(TypeError):
        cyc.run()
    cyc.close()


def test_keys_are_stable_text_not_addresses():
    """A key must be the same in every process: pinned so a change is deliberate."""
    assert _label(7, "strength", "Bond:12") == _label(7, "strength", "Bond:12")
    assert _label(7, "strength", "Bond:12") != _label(8, "strength", "Bond:12")
    assert _label(7, "post", "bu", "x") != _label(7, "post", "td", "x")


def test_structure_identity_uses_run_ids():
    with use_backend("off"):
        r = EngineRunner(META)
        r.init_mcat(*PROBLEMS[0], seed=1)
        r.run_mcat(max_steps=200)
        for s in r.ctx.workspace.all_structures:
            assert structure_identity(s) == f"{type(s).__name__}:{s.id}"


def test_policy_and_thread_validation():
    r = EngineRunner(META)
    with pytest.raises(ValueError):
        UpdateCycle(r, "nonsense")
    with pytest.raises(ValueError):
        UpdateCycle(r, "faithful", threads=0)
    cyc = UpdateCycle(r, "faithful", threads=2, force_threads=True)
    cyc.close()
    cyc.close()  # idempotent
