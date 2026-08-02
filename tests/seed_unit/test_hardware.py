"""The machine description, and the sizes derived from it.

``server/engine/hardware.py`` is the one place that answers "what is this
machine", and every worker count, shard count and pool size in the engine is
computed from its answer.  Three things have to hold for that to be safe.

**The probes return sane values here.**  A detection module that reports zero
cores sizes every pool at one and nothing fails loudly.

**A probe that cannot answer degrades to a value the caller can still use.**
The GPU core count is read by shelling out to ``system_profiler``, which is
absent on every platform but macOS and can fail on macOS too.  A missing answer
must produce a smaller machine, not an exception and not a zero.

**An environment override wins.**  Sizing that cannot be pinned is sizing that
cannot be measured against, and the benchmarks need to ask for a specific worker
count on a machine that would have chosen a different one.

The tests fake the probes rather than the platform: every probe funnels through
``_sysctl``, ``_system_profiler_gpu``, ``_metal_available`` and
``os.process_cpu_count``, so replacing those four covers a machine that answers
everything, one that answers nothing, and the shapes in between.
"""

from __future__ import annotations

import sys

import pytest

from server.engine import hardware


@pytest.fixture(autouse=True)
def _fresh_probes():
    """Each test starts with nothing cached and leaves nothing cached."""
    hardware.reset()
    yield
    hardware.reset()


@pytest.fixture
def no_overrides(monkeypatch):
    """Clear every environment variable this module reads."""
    for name in (
        hardware.ENV_WORKERS,
        hardware.ENV_SHARDS,
        hardware.ENV_POPULATION_WORKERS,
        hardware.ENV_GPU_CORES,
        hardware.ENV_GPU_THREADS_PER_CORE,
    ):
        monkeypatch.delenv(name, raising=False)


def fake_cpu(monkeypatch, *, logical: int, levels: dict[str, str] | None = None) -> None:
    """Install a CPU that reports ``logical`` cores and the given sysctl keys."""
    monkeypatch.setattr(hardware.os, "process_cpu_count", lambda: logical, raising=False)
    monkeypatch.setattr(hardware.os, "cpu_count", lambda: logical)
    table = dict(levels or {})

    def sysctl(*names: str) -> dict[str, str]:
        return {name: table[name] for name in names if name in table}

    monkeypatch.setattr(hardware, "_sysctl", sysctl)


def fake_gpu(monkeypatch, *, cores, name, probe: str, metal: bool = True) -> None:
    monkeypatch.setattr(
        hardware, "_system_profiler_gpu", lambda: (cores, name, probe)
    )
    monkeypatch.setattr(hardware, "_metal_available", lambda: metal)


# --- This machine -----------------------------------------------------------


def test_it_describes_the_machine_it_is_running_on(no_overrides):
    """Real probes, real values, and every one of them usable as a size."""
    machine = hardware.detect()

    assert machine.platform == sys.platform
    assert machine.cpu.logical_cores >= 1
    assert 1 <= machine.cpu.performance_cores <= machine.cpu.logical_cores
    assert 0 <= machine.cpu.efficiency_cores <= machine.cpu.logical_cores
    assert (
        machine.cpu.performance_cores + machine.cpu.efficiency_cores
        <= machine.cpu.logical_cores
    )
    assert machine.cpu.probe
    assert machine.gpu.probe
    assert isinstance(machine.gpu.metal_available, bool)
    if machine.gpu.cores is not None:
        assert machine.gpu.cores >= 1


@pytest.mark.skipif(sys.platform != "darwin", reason="sysctl perflevels are macOS")
def test_on_macos_it_reads_the_performance_and_efficiency_split(no_overrides):
    """Apple silicon reports both levels, and both come back."""
    cpu = hardware.cpu_info()
    assert cpu.chip
    assert cpu.memory_bytes and cpu.memory_bytes > 0
    assert cpu.performance_cores >= 1


def test_the_derived_sizes_are_all_positive_and_internally_consistent(no_overrides):
    """Every size follows from the machine, and the shard count follows the workers."""
    derived = hardware.derived_sizes()

    assert derived["workers"] == hardware.worker_count()
    assert derived["coderack_shards"] == hardware.shard_count(derived["workers"])
    assert derived["population_workers"] == hardware.population_worker_count()
    assert all(value >= 1 for value in derived.values())
    assert derived["gpu_target_threads"] >= derived["gpu_cores"]


def test_probes_are_cached_so_a_process_pays_for_them_once(no_overrides, monkeypatch):
    """The second call does not shell out again."""
    calls = []

    def counting_probe():
        calls.append(1)
        return 38, "Fake GPU", "fake probe"

    monkeypatch.setattr(hardware, "_system_profiler_gpu", counting_probe)
    hardware.gpu_info()
    hardware.gpu_info()
    hardware.gpu_info()
    assert len(calls) == 1

    hardware.reset()
    hardware.gpu_info()
    assert len(calls) == 2


# --- Rules ------------------------------------------------------------------


def test_workers_follow_the_performance_cores(no_overrides, monkeypatch):
    """A 32-core machine with 24 performance cores runs 24 workers."""
    fake_cpu(
        monkeypatch,
        logical=32,
        levels={
            "hw.nperflevels": "2",
            "hw.perflevel0.logicalcpu": "24",
            "hw.perflevel1.logicalcpu": "8",
        },
    )
    assert hardware.cpu_info().performance_cores == 24
    assert hardware.cpu_info().efficiency_cores == 8
    assert hardware.worker_count() == 24
    assert hardware.population_worker_count() == 31


def test_a_small_machine_is_not_asked_for_more_than_it_has(no_overrides, monkeypatch):
    """The same rule on eight cores asks for what eight cores can give."""
    fake_cpu(
        monkeypatch,
        logical=8,
        levels={
            "hw.nperflevels": "2",
            "hw.perflevel0.logicalcpu": "4",
            "hw.perflevel1.logicalcpu": "4",
        },
    )
    assert hardware.worker_count() == 4
    assert hardware.population_worker_count() == 7


def test_a_single_performance_level_is_all_performance_cores(no_overrides, monkeypatch):
    """A machine that reports one level puts every core in the fast set."""
    fake_cpu(monkeypatch, logical=16, levels={"hw.nperflevels": "1"})
    cpu = hardware.cpu_info()
    assert cpu.performance_cores == 16
    assert cpu.efficiency_cores == 0
    assert hardware.worker_count() == 16


def test_shards_are_one_per_worker_with_a_floor_of_two(no_overrides):
    assert hardware.shard_count(24) == 24
    assert hardware.shard_count(4) == 4
    assert hardware.shard_count(1) == hardware.MIN_SHARDS
    assert hardware.shard_count() == max(hardware.MIN_SHARDS, hardware.worker_count())


def test_the_gpu_thread_target_scales_with_the_gpu(no_overrides, monkeypatch):
    """Cores times 1,024, rounded up to a power of two."""
    fake_gpu(monkeypatch, cores=38, name="Apple M2 Max", probe="fake")
    assert hardware.gpu_target_threads() == 1 << 16

    hardware.reset()
    fake_gpu(monkeypatch, cores=80, name="Apple M3 Ultra", probe="fake")
    assert hardware.gpu_target_threads() == 1 << 17

    hardware.reset()
    fake_gpu(monkeypatch, cores=10, name="Small GPU", probe="fake")
    assert hardware.gpu_target_threads() == 1 << 14


# --- Degrading gracefully ---------------------------------------------------


def test_a_machine_that_answers_nothing_still_produces_usable_sizes(
    no_overrides, monkeypatch
):
    """No sysctl, no system_profiler, no MLX: still a machine, still sized."""
    monkeypatch.setattr(hardware, "_sysctl", lambda *names: {})
    monkeypatch.setattr(
        hardware, "_system_profiler_gpu", lambda: (None, None, "unavailable")
    )
    monkeypatch.setattr(hardware, "_metal_available", lambda: False)
    monkeypatch.setattr(hardware.os, "process_cpu_count", lambda: 6, raising=False)

    machine = hardware.detect()
    assert machine.cpu.logical_cores == 6
    assert machine.cpu.performance_cores == 6
    assert machine.cpu.efficiency_cores == 0
    assert machine.cpu.chip is None
    assert machine.gpu.cores is None
    assert machine.gpu.metal_available is False

    assert hardware.worker_count() == 6
    assert hardware.population_worker_count() == 5
    assert hardware.gpu_core_count() == hardware.FALLBACK_GPU_CORES
    assert hardware.gpu_target_threads() == 1 << 16


def test_a_probe_that_raises_is_not_allowed_to_reach_the_caller(
    no_overrides, monkeypatch
):
    """``sysctl`` refusing to run reports a machine rather than an exception."""

    def explode(*args, **kwargs):
        raise OSError("no such executable")

    monkeypatch.setattr(hardware.subprocess, "run", explode)
    machine = hardware.detect()
    assert machine.cpu.logical_cores >= 1
    assert machine.gpu.cores is None
    assert hardware.worker_count() >= 1


def test_a_probe_that_times_out_degrades_the_same_way(no_overrides, monkeypatch):
    """A hung ``system_profiler`` costs the GPU core count and nothing else."""
    import subprocess

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="system_profiler", timeout=1)

    monkeypatch.setattr(hardware.subprocess, "run", timeout)
    assert hardware.gpu_info().cores is None
    assert hardware.gpu_core_count() == hardware.FALLBACK_GPU_CORES


def test_unparseable_probe_output_is_treated_as_no_answer(no_overrides, monkeypatch):
    """Text where JSON was expected leaves the core count unknown."""

    class Completed:
        stdout = "Graphics/Displays: not JSON"

    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **k: Completed())
    monkeypatch.setattr(sys, "platform", "darwin")
    cores, name, probe = hardware._system_profiler_gpu()
    assert cores is None
    assert name is None
    assert probe


def test_a_perflevel_count_larger_than_the_logical_total_is_clamped(
    no_overrides, monkeypatch
):
    """Derived counts stay inside the machine even when a probe disagrees with itself."""
    fake_cpu(
        monkeypatch,
        logical=4,
        levels={
            "hw.nperflevels": "2",
            "hw.perflevel0.logicalcpu": "99",
            "hw.perflevel1.logicalcpu": "99",
        },
    )
    cpu = hardware.cpu_info()
    assert cpu.performance_cores == 4
    assert cpu.efficiency_cores == 0


# --- Overrides --------------------------------------------------------------


def test_the_worker_count_can_be_pinned_by_the_environment(no_overrides, monkeypatch):
    fake_cpu(monkeypatch, logical=32, levels={"hw.nperflevels": "1"})
    assert hardware.worker_count() == 32

    monkeypatch.setenv(hardware.ENV_WORKERS, "3")
    assert hardware.worker_count() == 3
    # The shard count follows the workers it is given, and can be pinned separately.
    assert hardware.shard_count() == 3
    monkeypatch.setenv(hardware.ENV_SHARDS, "7")
    assert hardware.shard_count() == 7
    assert hardware.shard_count(2) == 7


def test_the_population_pool_and_gpu_sizes_can_be_pinned(no_overrides, monkeypatch):
    monkeypatch.setenv(hardware.ENV_POPULATION_WORKERS, "5")
    assert hardware.population_worker_count() == 5

    monkeypatch.setenv(hardware.ENV_GPU_CORES, "80")
    assert hardware.gpu_info().cores == 80
    assert hardware.gpu_core_count() == 80
    assert hardware.gpu_target_threads() == 1 << 17

    monkeypatch.setenv(hardware.ENV_GPU_THREADS_PER_CORE, "512")
    assert hardware.gpu_target_threads() == 1 << 16


def test_the_gpu_core_override_skips_the_probe(no_overrides, monkeypatch):
    """A pinned core count is taken as given rather than measured."""

    def explode():
        raise AssertionError("the probe ran despite the override")

    monkeypatch.setattr(hardware, "_system_profiler_gpu", explode)
    monkeypatch.setenv(hardware.ENV_GPU_CORES, "42")
    info = hardware.gpu_info()
    assert info.cores == 42
    assert hardware.ENV_GPU_CORES in info.probe


@pytest.mark.parametrize("value", ["", "  ", "not-a-number", "-4", "0"])
def test_an_unusable_override_leaves_the_detected_value_in_place(
    no_overrides, monkeypatch, value
):
    """Only a positive integer overrides; anything else is the machine's answer."""
    fake_cpu(monkeypatch, logical=12, levels={"hw.nperflevels": "1"})
    monkeypatch.setenv(hardware.ENV_WORKERS, value)
    assert hardware.worker_count() == 12


def test_overrides_in_force_reports_exactly_what_is_set(no_overrides, monkeypatch):
    assert hardware.overrides_in_force() == {}
    monkeypatch.setenv(hardware.ENV_WORKERS, "6")
    monkeypatch.setenv(hardware.ENV_GPU_CORES, "80")
    assert hardware.overrides_in_force() == {
        hardware.ENV_WORKERS: "6",
        hardware.ENV_GPU_CORES: "80",
    }


# --- What the rest of the engine gets ---------------------------------------


def test_the_free_running_engine_sizes_itself_from_the_machine(no_overrides):
    """``workers=None`` is the machine's count, and the shards follow it."""
    from server.engine.free_running import FreeRunningEngine
    from server.engine.metadata import MetadataProvider
    from server.engine.runner import EngineRunner
    import os as _os

    seed_dir = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
        "seed_data",
    )
    runner = EngineRunner(MetadataProvider.from_seed_data(seed_dir))
    engine = FreeRunningEngine(runner)
    assert engine.workers == hardware.worker_count()
    assert engine.shards == hardware.shard_count(engine.workers)

    pinned = FreeRunningEngine(runner, workers=2, shards=3)
    assert (pinned.workers, pinned.shards) == (2, 3)


def test_the_machine_serialises_to_a_plain_dict(no_overrides):
    """What the API response and a benchmark record are built from."""
    payload = hardware.detect().as_dict()
    assert set(payload) == {"platform", "cpu", "gpu"}
    assert "performance_cores" in payload["cpu"]
    assert "metal_available" in payload["gpu"]
