"""Backend placement: which numeric backend a parallel executor should run on (WP6).

The question this module answers is narrow and the answer was measured, not argued:
*given that Petacat's Slipnet has 59 nodes and 202 links, where should the numeric
substrate of a run execute when many runs, or many threads, are in flight?*  The
executors (``swarm``, ``speculative``) ask here instead of each inventing a rule, and
the rule is overridable by environment variables in the style of
``server.engine.hardware``.

The short answer: **on the CPU, with the substrate switched off.**  Every number below
is from the M5 Max (6 Super + 12 Performance cores, 40-core GPU, 128 GB) on 2026-10-29,
on a machine shared with other agents' tests, so absolute figures are noisy and the
ratios are what to trust.  The raw data and scripts are in
``agents-workspace/wp6-gpu-ane/`` (``FINDINGS.md`` is the report).

What was measured
-----------------
Single run, ``abc -> abd; mrrjjj``, ten seeds, 9,397 codelets, codelets per second:

====================  ======  ======  ======  ======  ========
backend               off     python  numpy   mlx-cpu mlx (GPU)
====================  ======  ======  ======  ======  ========
codelets / s          13,328  13,206  11,621  6,109   2,712
====================  ======  ======  ======  ======  ========

``auto`` -- the engine's own default -- resolves to ``mlx`` at *every* Slipnet size
(``DEFAULT_GPU_THRESHOLD = 0`` in ``server/engine/numeric/backend.py``), so an
unconfigured process runs **4.9x slower than ``off``**.  Executors must therefore never
rely on the engine's default: they pass a backend explicitly (:func:`worker_environment`).

Why the GPU cannot win at 59 nodes.  Everything the GPU could take (every
``NumpyBackend`` and session method) is 11% of a numpy run's wall time at most; the
Slipnet update itself is 2.2%.  A Metal dispatch costs 160-200 microseconds against
about 10 microseconds for the whole numpy Slipnet update, and the run makes five
kernels' worth of calls per 15-codelet cycle.  Even a free GPU kernel could not return
more than ~1.12x over numpy, which is itself slower than ``off``.  The remaining time is
interpreted Python walking the object graph (codelet bodies 44%, loops 6%, the
traversals that precede each numeric pass), which no accelerator reaches.

Swarm (N forkserver workers, each running whole runs; total runs per second, same
problem, six-second windows, noisy host)::

    workers      1     2     4     6     8    12    16    17
    off       11.9  23.6  37.0  56.1  64.9  75.6  86.1  87.0
    numpy     10.5  20.3  37.8  50.4  60.5  62.9  77.9  84.3
    mlx        2.3   5.9   7.9   8.3   8.9   4.4  FAIL  FAIL

``mlx`` collapses: it never exceeds 8.9 runs/s (7x below ``off``), falls at 12 workers,
and at 16 or more workers Metal itself fails -- ``RuntimeError: [metal::Device] Unable
to load kernel ... Unable to reach MTLCompilerService`` -- because many processes
compiling kernels at once overwhelm the single system compiler service.  A probe that
started N processes simultaneously saw failures at N = 4, 8, 12 (one each), 16 (5), 24 (13)
and 32 (21).  The engine's ``is_available`` swallows that exception and reports "mlx not
available", so the swarm would die with ``BackendUnavailable`` mid-run.  That is a
reliability argument as much as a speed one.

Bit-identity.  Over 290 runs (all 29 distinct demo problems x 10 seeds), ``off``,
``python`` and ``numpy`` produced identical stopping states, codelet counts, RNG call
counts and Trace sha256: 0 differences.  ``mlx`` and ``mlx-cpu`` also matched on a
30-run sample, but float32 can only be *statistically* equivalent, not bit-identical,
and the sample is too small to promise more.  Since ``off`` is as fast as anything and
bit-exact by construction, the swarm default is ``off``.

Batched GPU numerics (K lockstepped runs in one ``[K, N]`` dispatch) were prototyped in
``scripts/bench_gpu_batch.py``.  One batched update beats K separate numpy updates from
K ~ 30 (0.18 ms against 0.19 ms) and is bit-identical on integer-valued test states, but
a float64 batched CPU update beats the GPU until K ~ 256, and the whole GPU-addressable
numeric work is ~11% of a run, so an end-to-end gain is bounded at ~1.05x over numpy,
i.e. at best parity with ``off``.  ``server/parallel/gpu_batch.py`` was therefore *not*
built; :func:`gpu_worthwhile` goes True for ``batch > 1`` automatically if that module
ever appears.

Threads (the speculative engine).  MLX streams and the lazy arrays built on them belong
to the thread that created them ("There is no Stream(gpu, 0) in current thread"), and a
single ``mx.compile``d function called from several free-threaded threads sometimes
fails with ``mutex lock failed``.  Dispatch from many threads each owning a stream does
scale (6k to 50k tiny evals/s from 1 to 16 threads) but no engine thread can afford a
0.2 ms wait inside a commit window.  :func:`speculative_backend` therefore never
returns an MLX backend unless asked by name, and :func:`thread_safe` says why.

Fork.  ``os.fork`` after Metal initialises crashed the child with SIGSEGV, and a fork
after merely importing MLX failed to load kernels in the child.  :func:`start_method`
returns ``forkserver`` whenever MLX has been imported or may be used, and executors must
start MLX workers by ``forkserver`` or ``spawn`` and never inherit a Metal context.

Environment variables
---------------------
``PETACAT_SWARM_BACKEND``
    Force the swarm's per-worker numeric backend (``off``, ``python``, ``numpy``,
    ``mlx``, ``mlx-cpu``).  Default: the policy below.
``PETACAT_SPECULATIVE_BACKEND``
    Force the speculative engine's backend.  Default: ``off``.
``PETACAT_GPU_PLACEMENT``
    ``auto`` (default), ``on`` (always say the GPU is worthwhile) or ``off`` (never).
``PETACAT_GPU_MIN_NODES``
    Slipnet size below which :func:`gpu_worthwhile` says no.  Default 32,768, the
    round-trip crossover recorded in ``server/engine/numeric/backend.py``.
``PETACAT_GPU_DISPATCH_US``
    The cost of one Metal dispatch assumed by the cost model.  Default 200.

``PETACAT_NUMERIC_BACKEND`` (the engine's own switch) is honoured as a fallback when set
to something other than ``auto``: a user who pinned a backend for the whole process gets
that backend in the executors too, except that ``mlx`` is demoted to ``numpy`` on the
thread path (:func:`speculative_backend`) because it is unsafe there.
"""

from __future__ import annotations

import importlib.util
import os
import sys

ENV_SWARM_BACKEND = "PETACAT_SWARM_BACKEND"
ENV_SPECULATIVE_BACKEND = "PETACAT_SPECULATIVE_BACKEND"
ENV_GPU_PLACEMENT = "PETACAT_GPU_PLACEMENT"
ENV_GPU_MIN_NODES = "PETACAT_GPU_MIN_NODES"
ENV_GPU_DISPATCH_US = "PETACAT_GPU_DISPATCH_US"
ENV_NUMERIC_BACKEND = "PETACAT_NUMERIC_BACKEND"

#: Every backend name the engine knows (``server.engine.numeric.backend.backend_names``)
#: plus ``off``, which runs the engine's own loops.
BACKENDS = ("off", "python", "numpy", "mlx", "mlx-cpu")

#: Backends that use MLX, and so inherit its thread and fork constraints.
MLX_BACKENDS = frozenset({"mlx", "mlx-cpu"})

#: The Slipnet size from which the engine's numpy path starts to beat its own loops
#: (``DEFAULT_VECTORISE_THRESHOLD`` in ``server/engine/numeric/backend.py``).
VECTORISE_MIN_NODES = 512

#: Slipnet size at which one run's GPU round trip first beats numpy on this host: the
#: geometric midpoint of the 10^4 - 10^5 bracket measured by ``scripts/bench_numeric.py``.
DEFAULT_GPU_MIN_NODES = 32_768

#: One Metal dispatch, microseconds.  Measured 160-200 on the M5 Max (WP6 and WP4.5).
DEFAULT_GPU_DISPATCH_US = 200

#: Numpy cost per Slipnet node of one round-trip update, microseconds.  From the
#: round-trip table (1.32 ms at 10,000 nodes; 15.5 ms at 100,000 nodes).
CPU_US_PER_NODE = 0.14

#: A GPU path must beat the CPU by this factor in the model to be called worthwhile,
#: so noise in the constants cannot flip the answer at the margin.
GPU_MARGIN = 2.0


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip().lower()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return max(0, int(raw.strip()))
    except ValueError:
        return default


def _valid(name: str) -> str | None:
    return name if name in BACKENDS else None


def _pinned_engine_backend() -> str | None:
    """The engine-wide ``PETACAT_NUMERIC_BACKEND`` when it names a concrete backend."""
    name = _env(ENV_NUMERIC_BACKEND)
    return _valid(name) if name and name != "auto" else None


def thread_safe(backend: str) -> bool:
    """Whether *backend* may be called from several threads of one process.

    The CPU backends hold no cross-call state beyond per-run sessions.  MLX does not:
    a stream, and every lazy array built on it, is bound to the creating thread, and a
    shared ``mx.compile`` function fails intermittently under free-threading.
    """
    return backend not in MLX_BACKENDS


def swarm_backend(n_nodes: int | None = None) -> str:
    """Numeric backend for each process of a swarm.

    * An explicit ``PETACAT_SWARM_BACKEND`` wins, then a pinned
      ``PETACAT_NUMERIC_BACKEND``.
    * Below the vectorise threshold (today's 59 nodes): ``off``.  It is the fastest
      and exact, and ``mlx`` collapses to 7x slower and fails to start under 16
      workers.
    * From 512 nodes: ``numpy``, which is exact in float64 and the measured winner
      until the GPU crossover.
    * The GPU is never chosen automatically: it is one shared device, each worker
      pays dispatch latency while the others queue behind it, and Metal start-up
      fails when many workers compile kernels at once.  A caller that has a Slipnet
      beyond the GPU crossover *and* few workers may force it with
      ``PETACAT_SWARM_BACKEND=mlx``.
    """
    forced = _valid(_env(ENV_SWARM_BACKEND)) or _pinned_engine_backend()
    if forced:
        return forced
    if n_nodes is not None and n_nodes >= VECTORISE_MIN_NODES:
        return "numpy"
    return "off"


def speculative_backend(n_nodes: int | None = None, workers: int = 1) -> str:
    """Numeric backend for the in-process threads of the speculative engine.

    ``off`` at today's size, ``numpy`` from the vectorise threshold, never MLX unless
    ``PETACAT_SPECULATIVE_BACKEND`` names it.  The pinned engine-wide backend is
    honoured except that an MLX choice is demoted to ``numpy`` (see :func:`thread_safe`).
    """
    explicit = _valid(_env(ENV_SPECULATIVE_BACKEND))
    if explicit:
        return explicit
    pinned = _pinned_engine_backend()
    if pinned:
        return "numpy" if pinned in MLX_BACKENDS else pinned
    if n_nodes is not None and n_nodes >= VECTORISE_MIN_NODES:
        return "numpy"
    return "off"


def gpu_worthwhile(
    n_nodes: int,
    batch: int = 1,
    concurrent_gpu_users: int = 1,
    threaded: bool = False,
) -> bool:
    """Would the GPU make a numeric update faster here?

    A cost model fitted to the measurements in the module docstring.  CPU time for the
    update is ``CPU_US_PER_NODE * n_nodes * batch``; GPU time is one dispatch (they are
    amortised across a batch) multiplied by the processes queueing for the device.  The
    GPU must win by ``GPU_MARGIN``.  Always False when the node count is below
    ``PETACAT_GPU_MIN_NODES`` for an unbatched run, when called for threads
    (``threaded=True``, because MLX is not thread-safe), or when MLX is not installed.

    ``batch > 1`` only counts if a batched executor exists (``server.parallel.gpu_batch``);
    today it does not, because even at K = 1024 the whole-run gain at 59 nodes is bounded
    near 1.05x, so such a batch is treated as ``batch = 1``.
    """
    mode = _env(ENV_GPU_PLACEMENT)
    if mode == "off":
        return False
    if mode == "on":
        return True
    if threaded or not _mlx_installed():
        return False
    if batch > 1 and not _batching_implemented():
        batch = 1
    if batch <= 1 and n_nodes < _env_int(ENV_GPU_MIN_NODES, DEFAULT_GPU_MIN_NODES):
        return False
    dispatch = _env_int(ENV_GPU_DISPATCH_US, DEFAULT_GPU_DISPATCH_US)
    gpu_us = dispatch * max(1, concurrent_gpu_users)
    cpu_us = CPU_US_PER_NODE * max(0, n_nodes) * max(1, batch)
    return cpu_us >= GPU_MARGIN * gpu_us


def start_method(backend: str | None = None) -> str:
    """The multiprocessing start method a pool must use for *backend*.

    ``forkserver`` always on macOS-style hosts that may use MLX: ``fork`` after Metal
    initialises is unsafe (SIGSEGV in the child), and ``forkserver`` lets the server
    preload the read-only metadata once so workers share it copy-on-write.  A pool of
    CPU-only workers could fork, but a parent that has imported ``mlx.core`` cannot, so
    the answer is ``forkserver`` unless the platform lacks it.
    """
    if sys.platform == "win32":
        return "spawn"
    return "forkserver"


def safe_to_fork() -> bool:
    """False once this process has imported ``mlx.core`` (and so possibly Metal)."""
    return "mlx.core" not in sys.modules


def worker_environment(backend: str) -> dict[str, str]:
    """Environment entries a worker must carry so the engine uses *backend*.

    The engine caches its selection policy at first use, so these must be set before
    the worker imports an engine module that selects a backend.  ``off`` and the others
    are passed explicitly; leaving the engine on ``auto`` would select ``mlx``.
    """
    if backend not in BACKENDS:
        raise ValueError(f"unknown numeric backend {backend!r}; expected one of {BACKENDS}")
    return {ENV_NUMERIC_BACKEND: backend}


def describe(n_nodes: int | None = None) -> dict:
    """The policy as it stands for this environment, for logs and ``/api/system``."""
    return {
        "swarm_backend": swarm_backend(n_nodes),
        "speculative_backend": speculative_backend(n_nodes),
        "gpu_worthwhile": gpu_worthwhile(n_nodes or 0),
        "start_method": start_method(),
        "gpu_min_nodes": _env_int(ENV_GPU_MIN_NODES, DEFAULT_GPU_MIN_NODES),
        "batching_implemented": _batching_implemented(),
    }


def _mlx_installed() -> bool:
    try:
        return importlib.util.find_spec("mlx.core") is not None
    except (ImportError, ValueError):
        return False


def _batching_implemented() -> bool:
    try:
        return importlib.util.find_spec("server.parallel.gpu_batch") is not None
    except (ImportError, ValueError):
        return False
