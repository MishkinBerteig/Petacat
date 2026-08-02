"""What machine this is, and the sizes derived from it.

Petacat spreads work two ways: codelets across CPU cores, and the numeric
substrate across GPU cores.  Both need a number — how many worker threads, how
many coderack shards, how many processes in a population pool, how many GPU
threads a dispatch should aim for — and every one of those numbers is a property
of the machine the process is running on.  This module is where the machine is
described and where those numbers are computed from the description.

Standard library only, plus a deferred ``mlx`` import inside :func:`gpu_info`,
so the engine keeps its independence from the database layer and from every
optional dependency.

Probes
------
``cpu_info`` reads ``sysctl`` for the performance/efficiency split that Apple
silicon exposes through ``hw.perflevelN.*``, and ``os.process_cpu_count`` for the
logical total.  It is cheap — a few milliseconds — and is cached for the life of
the process.

``gpu_info`` reads ``system_profiler -json SPDisplaysDataType`` for the GPU core
count and checks whether ``mlx.core`` is importable.  ``system_profiler`` costs
about a quarter of a second, so it runs at most once per process and only when
something asks for a GPU-derived size.

Every probe returns a value or ``None``.  A machine that answers none of them
still gets a :class:`Machine` with a logical core count and the derived sizes
that follow from it.

Derived sizes
-------------
Each rule is stated with the reasoning that produces it, and each is overridable
by an environment variable so a particular run can be pinned:

``PETACAT_WORKERS``
    Free-running worker threads.  Default: the performance core count.  A codelet
    body is interpreted Python and CPU-bound, and a worker holds the commit lock
    for the duration of its mutation, so the workers are placed where the cores
    are fastest.

``PETACAT_CODERACK_SHARDS``
    Coderack shards under free-running.  Default: one per worker, floor of two.
    The rack's capacity is divided across shards rather than replicated, so the
    effective count is additionally bounded by
    ``server.engine.coderack_shards.MIN_SHARD_CAPACITY``.

``PETACAT_POPULATION_WORKERS``
    Processes in a population pool.  Default: every logical core but one.  The
    runs are independent and share nothing, so efficiency cores contribute real
    throughput; the reserved core leaves the parent process and the OS somewhere
    to run.

``PETACAT_GPU_CORES``
    The GPU core count, taken as given rather than probed.

``PETACAT_GPU_THREADS_PER_CORE``
    Threads per GPU core a Metal dispatch aims to have in flight.  Default 1,024.
    Multiplied by the core count and rounded up to a power of two, this is the
    thread target that decides how widely a Slipnet row is split across lanes
    (``server.engine.numeric.metal_kernels``).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from dataclasses import asdict, dataclass

# -- environment variable names ---------------------------------------------

ENV_WORKERS = "PETACAT_WORKERS"
ENV_SHARDS = "PETACAT_CODERACK_SHARDS"
ENV_POPULATION_WORKERS = "PETACAT_POPULATION_WORKERS"
ENV_GPU_CORES = "PETACAT_GPU_CORES"
ENV_GPU_THREADS_PER_CORE = "PETACAT_GPU_THREADS_PER_CORE"

#: Threads per GPU core a dispatch aims to have in flight.  A GPU core runs many
#: threads concurrently to hide memory latency, and this is the multiple that
#: keeps the Slipnet kernel supplied on Apple silicon.
DEFAULT_GPU_THREADS_PER_CORE = 1024

#: GPU core count assumed when the probe returns nothing.  Sized so that the
#: thread target lands at 65,536 — the value measured as best across Slipnet
#: sizes from 1,000 to 300,000 nodes on a 38-core GPU.
FALLBACK_GPU_CORES = 64

#: How many logical cores a population pool leaves free for the parent process
#: and the operating system.
POPULATION_RESERVED_CORES = 1

#: Fewest shards a free-running rack is divided into.
MIN_SHARDS = 2

_SYSCTL_TIMEOUT_SECONDS = 5.0
_SYSTEM_PROFILER_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class CpuInfo:
    """The CPU as the operating system describes it."""

    #: Logical cores this process may schedule on.
    logical_cores: int
    #: Cores on the fastest performance level.  Equal to ``logical_cores`` on a
    #: machine that reports a single level.
    performance_cores: int
    #: Cores on the remaining, slower levels.
    efficiency_cores: int
    #: Marketing name of the processor, e.g. ``Apple M2 Max``.
    chip: str | None
    #: Bytes of system (on Apple silicon, unified) memory.
    memory_bytes: int | None
    #: Where each field came from, or why it fell back.
    probe: str


@dataclass(frozen=True)
class GpuInfo:
    """The GPU as the operating system and MLX describe it."""

    #: GPU cores, when a probe reports them.
    cores: int | None
    #: Marketing name of the GPU, e.g. ``Apple M2 Max``.
    name: str | None
    #: True when ``mlx.core`` is importable, which is what puts the numeric
    #: substrate's Metal backend within reach.
    metal_available: bool
    #: Where each field came from, or why it fell back.
    probe: str


@dataclass(frozen=True)
class Machine:
    """One machine, CPU and GPU together."""

    platform: str
    cpu: CpuInfo
    gpu: GpuInfo

    def as_dict(self) -> dict:
        """A plain nested dict, for an API response or a benchmark record."""
        return {"platform": self.platform, "cpu": asdict(self.cpu), "gpu": asdict(self.gpu)}


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def _sysctl(*names: str) -> dict[str, str]:
    """Read sysctl keys by name.  Returns only the keys that answered."""
    if not names:
        return {}
    try:
        completed = subprocess.run(
            ["sysctl", *names],
            capture_output=True,
            text=True,
            timeout=_SYSCTL_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    return values


def _as_int(text: str | None) -> int | None:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def _logical_cores() -> int:
    """Cores this process may schedule on, floored at one.

    ``os.process_cpu_count`` respects CPU affinity and the ``-X cpu_count``
    override, so it is the count that describes what this process actually has.
    """
    counter = getattr(os, "process_cpu_count", None)
    count = counter() if counter is not None else None
    if not count:
        count = os.cpu_count()
    return max(1, int(count or 1))


def _perflevel_split(logical: int) -> tuple[int, int, str]:
    """``(performance, efficiency, probe)`` from the ``hw.perflevelN`` keys.

    Apple silicon reports ``hw.nperflevels`` levels, level 0 being the fastest.
    A machine reporting one level, or none, is all performance cores.
    """
    values = _sysctl("hw.nperflevels")
    levels = _as_int(values.get("hw.nperflevels"))
    if not levels or levels < 2:
        return logical, 0, "single performance level"

    keys = [f"hw.perflevel{index}.logicalcpu" for index in range(levels)]
    counts = _sysctl(*keys)
    performance = _as_int(counts.get("hw.perflevel0.logicalcpu"))
    if not performance:
        return logical, 0, "perflevel counts unavailable"

    others = sum(
        _as_int(counts.get(f"hw.perflevel{index}.logicalcpu")) or 0
        for index in range(1, levels)
    )
    performance = max(1, min(performance, logical))
    return performance, max(0, min(others, logical - performance)), "sysctl hw.perflevel"


_CPU_INFO: CpuInfo | None = None


def cpu_info(refresh: bool = False) -> CpuInfo:
    """Describe the CPU.  Cached for the life of the process."""
    global _CPU_INFO
    if _CPU_INFO is not None and not refresh:
        return _CPU_INFO

    logical = _logical_cores()
    performance, efficiency, probe = _perflevel_split(logical)
    details = _sysctl("machdep.cpu.brand_string", "hw.memsize")

    _CPU_INFO = CpuInfo(
        logical_cores=logical,
        performance_cores=performance,
        efficiency_cores=efficiency,
        chip=details.get("machdep.cpu.brand_string") or None,
        memory_bytes=_as_int(details.get("hw.memsize")),
        probe=probe,
    )
    return _CPU_INFO


def _system_profiler_gpu() -> tuple[int | None, str | None, str]:
    """``(cores, name, probe)`` from ``system_profiler SPDisplaysDataType``.

    The JSON form is read rather than the text form: ``sppci_cores`` is a stable
    key, where the human-readable output is prose that varies by macOS release.
    """
    if sys.platform != "darwin":
        return None, None, f"no GPU core probe on {sys.platform}"
    try:
        completed = subprocess.run(
            ["system_profiler", "-json", "SPDisplaysDataType"],
            capture_output=True,
            text=True,
            timeout=_SYSTEM_PROFILER_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None, "system_profiler unavailable"

    import json

    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        return None, None, "system_profiler returned no JSON"

    for entry in payload.get("SPDisplaysDataType") or []:
        if not isinstance(entry, dict):
            continue
        cores = _as_int(entry.get("sppci_cores"))
        name = entry.get("sppci_model") or entry.get("_name")
        if cores:
            return cores, name, "system_profiler SPDisplaysDataType"
    return None, None, "system_profiler reported no core count"


def _metal_available() -> bool:
    """Whether ``mlx.core`` is importable in this interpreter.

    Answered from the module finder rather than by importing, so a process that
    only wants to size a thread pool does not pay for loading a GPU framework.
    """
    try:
        return importlib.util.find_spec("mlx.core") is not None
    except (ImportError, ValueError):
        return False


_GPU_INFO: GpuInfo | None = None


def gpu_info(refresh: bool = False) -> GpuInfo:
    """Describe the GPU.  Cached for the life of the process.

    ``PETACAT_GPU_CORES`` takes the core count as given and skips the probe.
    """
    global _GPU_INFO
    if _GPU_INFO is not None and not refresh:
        return _GPU_INFO

    override = _int_from_environment(ENV_GPU_CORES, 0)
    if override > 0:
        _GPU_INFO = GpuInfo(
            cores=override,
            name=None,
            metal_available=_metal_available(),
            probe=f"{ENV_GPU_CORES}={override}",
        )
        return _GPU_INFO

    cores, name, probe = _system_profiler_gpu()
    _GPU_INFO = GpuInfo(
        cores=cores, name=name, metal_available=_metal_available(), probe=probe
    )
    return _GPU_INFO


def detect(refresh: bool = False) -> Machine:
    """The whole machine.  Runs the GPU probe, so call it when the answer is wanted."""
    return Machine(
        platform=sys.platform, cpu=cpu_info(refresh), gpu=gpu_info(refresh)
    )


def reset() -> None:
    """Discard the cached probes so the next call measures again."""
    global _CPU_INFO, _GPU_INFO
    _CPU_INFO = None
    _GPU_INFO = None


# ---------------------------------------------------------------------------
# Derived sizes
# ---------------------------------------------------------------------------


def _int_from_environment(name: str, default: int) -> int:
    """A non-negative integer from the environment, or ``default``."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return max(0, value)


def worker_count() -> int:
    """Free-running worker threads for this machine.

    The performance core count.  Codelet bodies are interpreted Python and
    CPU-bound, and a worker holds the commit lock while it mutates the Workspace,
    so every worker is placed on a core that finishes its turn quickly.
    """
    override = _int_from_environment(ENV_WORKERS, 0)
    if override > 0:
        return override
    return max(1, cpu_info().performance_cores)


def shard_count(workers: int | None = None) -> int:
    """Coderack shards for a run with ``workers`` workers.

    One shard per worker, floor of two, so a worker draws from a rack of its own.
    ``server.engine.coderack_shards`` bounds this further by the capacity a shard
    needs to hold a full jootsing sequence.
    """
    override = _int_from_environment(ENV_SHARDS, 0)
    if override > 0:
        return override
    return max(MIN_SHARDS, workers if workers is not None else worker_count())


def worker_ladder(maximum: int | None = None) -> list[int]:
    """Worker counts a scaling measurement should sample on this machine.

    Powers of two from one up to ``maximum`` — the machine's worker count by
    default — with that figure last.  A machine with 8 workers is measured at
    1, 2, 4, 8; one with 24 at 1, 2, 4, 8, 16, 24.
    """
    top = max(1, maximum if maximum is not None else worker_count())
    ladder: list[int] = []
    step = 1
    while step < top:
        ladder.append(step)
        step *= 2
    ladder.append(top)
    return ladder


def population_worker_count() -> int:
    """Processes for a population of independent runs.

    Every logical core but one.  The runs share nothing, so efficiency cores add
    throughput in proportion to their speed, and the reserved core leaves the
    parent process and the operating system somewhere to run.
    """
    override = _int_from_environment(ENV_POPULATION_WORKERS, 0)
    if override > 0:
        return override
    return max(1, cpu_info().logical_cores - POPULATION_RESERVED_CORES)


def _next_power_of_two(value: float) -> int:
    n = 1
    while n < value:
        n <<= 1
    return n


def gpu_core_count() -> int:
    """GPU cores to size a dispatch for, falling back when the probe is silent."""
    return gpu_info().cores or FALLBACK_GPU_CORES


def gpu_target_threads() -> int:
    """Threads a Metal dispatch aims for before it stops splitting rows further.

    ``GPU cores x threads per core``, rounded up to a power of two.  Two GPUs of
    different sizes therefore get thread targets in proportion to their cores,
    and the Slipnet kernel splits each row across as many lanes as the larger one
    can keep busy.
    """
    per_core = _int_from_environment(
        ENV_GPU_THREADS_PER_CORE, DEFAULT_GPU_THREADS_PER_CORE
    )
    per_core = per_core or DEFAULT_GPU_THREADS_PER_CORE
    return _next_power_of_two(gpu_core_count() * per_core)


def derived_sizes() -> dict:
    """Every size this module computes, with the workers figure they follow from.

    One call so a report of the machine and a report of what was derived from it
    cannot drift apart.
    """
    workers = worker_count()
    return {
        "workers": workers,
        "coderack_shards": shard_count(workers),
        "population_workers": population_worker_count(),
        "gpu_cores": gpu_core_count(),
        "gpu_target_threads": gpu_target_threads(),
    }


def overrides_in_force() -> dict[str, str]:
    """Environment variables from this module that are set, with their values."""
    names = (
        ENV_WORKERS,
        ENV_SHARDS,
        ENV_POPULATION_WORKERS,
        ENV_GPU_CORES,
        ENV_GPU_THREADS_PER_CORE,
    )
    return {name: os.environ[name] for name in names if os.environ.get(name)}
