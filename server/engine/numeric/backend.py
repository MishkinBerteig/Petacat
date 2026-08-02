"""The numeric backend seam: one protocol, three implementations, one policy.

The engine's numeric work — activation spreading, decay, the probabilistic jump,
structure strengths, object values, themespace dynamics, temperature — is roughly
30% of runtime and is the part that will not survive the Slipnet growing toward
~300,000 nodes in its present form.  This module is where an alternative
implementation of that work is chosen.

Three implementations, and why all three exist
----------------------------------------------
``python``
    The reference.  Pure Python, no third-party import, always available.  It is
    a transcription of the loops in ``slipnet.py``, ``themes.py`` and
    ``workspace_objects.py`` onto the flat layouts, and it is what defines
    "correct" for the other two.  It also means the engine keeps running with
    neither NumPy nor MLX installed, which is not a hypothetical: this checkout
    had no NumPy until this work package added it as an *optional* dependency.

``numpy``
    Vectorised float64 on the CPU.  Same precision as the reference, so its
    agreement with the reference is exact rather than approximate for everything
    except one identified case (see ``python_backend.spread``).  It is also the
    honest CPU baseline for the scaling curve — comparing a GPU against a
    *Python-loop* CPU would measure interpreter overhead and call it a GPU win.

``mlx`` / ``mlx-cpu``
    Metal via MLX.  ``mlx`` runs on the GPU stream, ``mlx-cpu`` on MLX's CPU
    stream; having both separates "MLX framework overhead" from "GPU dispatch
    overhead", which are different costs and get confused if only one is measured.

The constraint that shapes the MLX backend: **MLX does not support float64 on the
GPU.**  Every GPU array is float32.  Activations live in [0, 100] and per-edge
contributions are rounded to integers before they are summed, so float32 carries
about 7 significant digits where the reference carries 16.  That is a real
difference and it is not hidden: ``mlx`` reports ``exact = False`` and the tests
assert agreement within a measured tolerance rather than bit-for-bit.

Selection
---------
Availability alone does not decide, and the reason is worth stating because it is
the single most counter-intuitive result of this work package: **the fastest
available backend is the wrong choice at three of the four sizes measured.**  At
59 nodes the substrate costs well under a millisecond per update cycle and any
dispatch costs more than the work it replaces; at a thousand nodes vectorising
pays but the GPU still does not, because a Metal dispatch costs ~0.2 ms whether it
is asked to touch 200 edges or 340,000 and NumPy finishes the whole update in
0.03 ms.  The default policy is therefore size-aware in two stages — reference
loops, then vectorised CPU, then GPU — with both thresholds taken from the
measured curve rather than guessed.  That keeps today's engine exactly as fast and
exactly as behaved as it was, while the substrate takes over automatically as the
Slipnet grows into the regime it was built for.

The policy is overridable, and the override is what the tests and the benchmarks
use:

``PETACAT_NUMERIC_BACKEND``
    ``auto`` (default), ``python``, ``numpy``, ``mlx``, ``mlx-cpu``, or ``off``.
    Anything other than ``auto``/``off`` forces that backend regardless of size —
    which is how the expected-range check exercises the substrate on a 59-node
    Slipnet, where the size policy would otherwise never engage it.  ``off``
    disables the substrate entirely, including for a large Slipnet.

``PETACAT_NUMERIC_MIN_NODES``
    The size at which ``auto`` starts vectorising at all.

``PETACAT_NUMERIC_MIN_GPU_NODES``
    The size at which ``auto`` prefers the GPU to vectorised CPU.  **Zero by default:
    the GPU runs at every size**, because Phase 0 B1 requires the numeric work to
    execute on the GPU cores and a threshold above 59 would mean it never did.  Raise
    it to reinstate size-gated selection — ~10^4 is the measured crossover — when
    profiling the CPU path is what you actually want.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from server.engine.numeric.layout import (
        ObjectValueBatch,
        SlipnetState,
        SlipnetTopology,
        ThemeLayout,
        ThemeParams,
        ThemeState,
    )

# Both thresholds below come from ``scripts/bench_numeric.py`` on a 12-core CPU
# (8 performance, 4 efficiency) with a 38-core GPU, milliseconds per update cycle,
# fastest of 25 repeats.  Two tables, because the substrate has two costs and they
# cross at different sizes.
#
# A crossover is a property of the machine it was measured on: it sits where the
# CPU's time on the work first exceeds the fixed cost of the alternative, so a
# faster CPU or a wider memory bus moves it up and a slower one moves it down.
# Re-run ``scripts/bench_numeric.py`` on a new machine and set the two environment
# variables below from what it reports.  ``GET /api/system/numeric`` states the
# machine that was detected alongside the thresholds in force, so a recorded run
# says which machine's numbers it used.
#
# *Kernel only*, with the state resident on the device:
#
#      nodes    edges   python    numpy      mlx
#         59      202  0.011ms  0.007ms  0.187ms
#      1,000    3,424  0.245ms  0.029ms  0.178ms
#     10,000   34,237   2.76ms  0.245ms  0.298ms
#    100,000  342,373  43.10ms   2.54ms  0.324ms
#
# *Round trip*, which is what today's engine pays: load the state from the object
# graph, update, resolve the jump candidates on the host, apply, store back.
#
#      nodes   python    numpy      mlx
#         59  0.015ms  0.018ms  0.413ms
#      1,000  0.309ms  0.136ms  0.489ms
#     10,000   3.36ms   1.32ms   1.69ms
#    100,000  45.13ms  15.50ms  10.95ms
#
# The GPU column of the first table is nearly flat across three orders of
# magnitude — 0.18 to 0.32 ms — which says the kernel is still dispatch-bound at
# 342,000 edges and has not begun to do measurable work.  The second table is
# where the engine lives, and there the GPU only pulls ahead once the round trip
# it forces is small next to the work it saves.
#
# The GPU column is also the one that moves between runs: it is latency, and
# latency is what other work on the machine perturbs.  Two runs of this script an
# hour apart put the kernel's crossover against NumPy on either side of 10,000
# nodes (0.82× and 1.22× there).  The 100,000-node ratio was 7.9× and 14.8× — the
# same conclusion at both, which is why the thresholds are set from the bracket
# rather than from a single measurement.

#: Slipnet size at or above which ``auto`` vectorises at all.
#:
#: At 59 nodes the reference loop wins outright on the round-trip table; by 1,000
#: NumPy is 2.3× ahead of it.  512 sits between the two measured points, and the
#: curve is smooth enough through that region that the exact value does not need
#: to be right to the node.
DEFAULT_VECTORISE_THRESHOLD = 512

#: Slipnet size at or above which ``auto`` prefers the GPU to NumPy.
#:
#: Taken from the *round-trip* crossover rather than the kernel one, because that
#: is the cost the engine incurs.  The kernel crosses around 10,000 nodes; the
#: round trip crosses between 10,000 and 100,000 — consistently, in both runs —
#: because the host synchronisation the probabilistic jump forces, and the
#: marshalling through Python lists, both scale with the node count and neither is
#: GPU work.  32,768 is the geometric midpoint of that bracket.
#:
#: The gap between the two crossovers is the clearest statement of what remains to
#: be done: it is entirely the object-graph adapter, and it disappears when the
#: flat layout becomes the primary representation rather than a projection of a
#: graph of Python objects.
# Zero: the GPU is used at every Slipnet size under ``auto``.  Kept as a knob rather
# than deleted because the measured crossover (~10^4 nodes) is a real property of the
# hardware and someone profiling on a small Slipnet has a legitimate reason to reinstate
# it; what it must not be is the default, which would leave the GPU substrate unexecuted
# at the only size the engine currently runs at.
DEFAULT_GPU_THRESHOLD = 0

ENV_BACKEND = "PETACAT_NUMERIC_BACKEND"
ENV_MIN_NODES = "PETACAT_NUMERIC_MIN_NODES"
ENV_MIN_GPU_NODES = "PETACAT_NUMERIC_MIN_GPU_NODES"


class BackendUnavailable(RuntimeError):
    """A backend was named explicitly but its dependency is not installed."""


class SlipnetSession(ABC):
    """A backend's residency for one Slipnet's activation state.

    The session exists so that the topology is uploaded once and the mutable state
    can *stay* on the device across update cycles.  At 59 nodes that hardly
    matters; at 300,000 it is the whole game, because copying six arrays of
    300,000 elements through Python lists every cycle would cost far more than the
    spreading itself.

    Two usage patterns, both supported deliberately:

    * The engine calls ``load`` before an update and ``store`` after it, because
      codelets mutate ``activation_buffer`` through the object graph between
      cycles and the object graph remains the authority.
    * A Slipnet with no object graph behind it — the synthetic ones the scaling
      curve is measured on, and eventually the real one — calls ``load`` once and
      then only ``update``, never crossing the host boundary at all.
    """

    @abstractmethod
    def load(self, state: SlipnetState) -> None:
        """Copy host state in.  Cheap for the CPU backends, a real upload for MLX."""

    @abstractmethod
    def store(self) -> SlipnetState:
        """Materialise the current state back into plain Python lists."""

    @abstractmethod
    def update(self, threshold: float, scale: float) -> None:
        """One decay → spread → flush pass.

        Fused into a single call rather than three, because the three are one
        traversal of the same data and splitting them would triple the dispatch
        count for no benefit.  ``slipnet.ss:377-389`` performs them in this order
        and never clears the buffer up front; the buffer arrives already carrying
        whatever the codelets and the Themespace poured into it.
        """

    @abstractmethod
    def jump_candidates(self) -> tuple[list[int], list[float]]:
        """Nodes eligible for the probabilistic jump, with their probabilities.

        Returned to the host rather than resolved on the device, because the
        comparison consumes the engine's RNG and the RNG stream must be identical
        to the reference's — same draws, same order, same count.  The reference
        (``slipnet.ss:388-389``) draws for a node when ``activation > 0`` and the
        probability ``(activation/100)**3`` is strictly between 0 and 1; a node at
        exactly 100 short-circuits to True inside ``RNG.prob`` and consumes no
        draw.  Only nodes that would consume a draw are returned, in index order.
        """

    @abstractmethod
    def apply_jumps(self, indices: Sequence[int]) -> None:
        """Set the given nodes to full activation."""


class Backend(ABC):
    """One implementation of the engine's numeric substrate."""

    #: Registry key, and what ``PETACAT_NUMERIC_BACKEND`` accepts.
    name: str = "abstract"

    #: True when the backend computes in float64 and therefore matches the
    #: reference's arithmetic.  False for the GPU, which is float32-only.
    exact: bool = True

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Whether this backend's dependencies are importable *and* usable."""

    @abstractmethod
    def open_slipnet(self, topology: SlipnetTopology) -> SlipnetSession: ...

    @abstractmethod
    def spread_themes(
        self, layout: ThemeLayout, state: ThemeState, params: ThemeParams
    ) -> None:
        """Intra-cluster theme dynamics, in place on ``state``."""

    @abstractmethod
    def combine_object_values(self, batch: ObjectValueBatch) -> None:
        """Relative importance, average unhappiness and the three saliences."""

    @abstractmethod
    def structure_strengths(
        self,
        internal: Sequence[float],
        external: Sequence[float],
        compatibility: Sequence[float],
    ) -> list[int]:
        """The arithmetic tail of ``WorkspaceStructure.update_strength``."""

    @abstractmethod
    def average_unhappiness(
        self, intra: Sequence[float], relative_importance: Sequence[float]
    ) -> int:
        """Importance-weighted mean intra-string unhappiness (workspace.ss:581-585)."""

    @abstractmethod
    def temperature(
        self,
        avg_unhappiness: float,
        rule_factor: float,
        unhappiness_weight: float,
        rule_weight: float,
    ) -> int:
        """Two-term weighted average (formulas.ss:62-79).

        A scalar, and it stays a scalar: there is nothing to vectorise in a single
        weighted average of two numbers, and dispatching it to a GPU would be
        slower than computing it by a factor of several thousand.  It is part of
        the protocol so that the substrate covers every numeric phase the profile
        names, and so that a future population-batched run (WP4.6), where this
        becomes one temperature per member of a batch of K runs, has a place to
        put the batched version.
        """


# ---------------------------------------------------------------------------
# Registry and selection
# ---------------------------------------------------------------------------

#: Preference order below ``DEFAULT_GPU_THRESHOLD`` — vectorised, but on the CPU,
#: because a GPU dispatch costs ~0.2 ms whatever it is asked to do and NumPy is
#: doing the whole job in 0.03 ms at a thousand nodes.
_CPU_PREFERENCE = ("numpy", "python")

#: Preference order at and above it.
_GPU_PREFERENCE = ("mlx", "numpy", "python")

_INSTANCES: dict[str, Backend] = {}
_CLASSES: dict[str, type[Backend]] = {}


def _classes() -> dict[str, type[Backend]]:
    """Import the backend classes lazily.

    Lazily because importing ``numpy_backend`` or ``mlx_backend`` at module import
    time would drag NumPy and MLX into every process that touches the engine,
    including the expected-range oracle's worker pool, which starts a fresh
    interpreter per core and would pay ~150 ms of MLX import for a backend it may
    never use.
    """
    if _CLASSES:
        return _CLASSES
    from server.engine.numeric.python_backend import PythonBackend

    _CLASSES["python"] = PythonBackend
    try:
        from server.engine.numeric.numpy_backend import NumpyBackend

        _CLASSES["numpy"] = NumpyBackend
    except ImportError:
        pass
    try:
        from server.engine.numeric.mlx_backend import MlxBackend, MlxCpuBackend

        _CLASSES["mlx"] = MlxBackend
        _CLASSES["mlx-cpu"] = MlxCpuBackend
    except ImportError:
        pass
    return _CLASSES


def backend_names() -> list[str]:
    """Every registered backend name, whether or not its dependency is present."""
    return ["python", "numpy", "mlx", "mlx-cpu"]


def available_backends() -> list[str]:
    """Registered backends whose dependencies are importable and usable."""
    classes = _classes()
    return [
        name
        for name in backend_names()
        if name in classes and classes[name].is_available()
    ]


def get_backend(name: str) -> Backend:
    """Return the named backend, or raise ``BackendUnavailable``.

    Instances are cached because MLX backends compile Metal kernels on first use
    and there is no reason to do that twice in a process.
    """
    if name in _INSTANCES:
        return _INSTANCES[name]
    classes = _classes()
    cls = classes.get(name)
    if cls is None or not cls.is_available():
        raise BackendUnavailable(
            f"numeric backend {name!r} is not available; available backends are "
            f"{available_backends()}. Install the optional dependency "
            f"(`pip install petacat[gpu]`) or choose another backend."
        )
    instance = cls()
    _INSTANCES[name] = instance
    return instance


def configured_backend_name() -> str:
    """What ``PETACAT_NUMERIC_BACKEND`` says, normalised. ``auto`` if unset."""
    return (os.environ.get(ENV_BACKEND) or "auto").strip().lower()


def _int_from_environment(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def vectorise_threshold() -> int:
    return _int_from_environment(ENV_MIN_NODES, DEFAULT_VECTORISE_THRESHOLD)


def gpu_threshold() -> int:
    return _int_from_environment(ENV_MIN_GPU_NODES, DEFAULT_GPU_THRESHOLD)


#: Cached ``(backend name, vectorise threshold, gpu threshold)``.
#: ``select_backend`` is on the update-cycle path and is consulted several times
#: per cycle; reading three environment variables each time is about 0.3 µs a
#: lookup, which is small but is charged to a hot path in a benchmark whose whole
#: purpose is to detect small changes.  Anything that changes the environment must
#: call ``reset_backend_cache``, and ``use_backend`` below does.
_POLICY: tuple[str, int, int] | None = None


def _policy() -> tuple[str, int, int]:
    global _POLICY
    if _POLICY is None:
        _POLICY = (configured_backend_name(), vectorise_threshold(), gpu_threshold())
    return _POLICY


def best_available(n_nodes: int | None = None) -> Backend:
    """The fastest *installed* backend for a problem of this size.  Never raises.

    Size is a parameter because the answer genuinely depends on it: a GPU dispatch
    costs about 0.2 ms whether it does 200 edges of work or 340,000, so below the
    measured GPU crossover the right answer is vectorised-on-the-CPU and above it
    the right answer is the GPU.  ``None`` asks for the largest-problem answer,
    which is what a caller with no size in hand almost always means.
    """
    threshold = _policy()[2] if n_nodes is not None else 0
    preference = _CPU_PREFERENCE if (n_nodes or 0) < threshold else _GPU_PREFERENCE
    classes = _classes()
    for name in preference:
        cls = classes.get(name)
        if cls is not None and cls.is_available():
            return get_backend(name)
    return get_backend("python")  # pragma: no cover - python is unconditional


def select_backend(n_nodes: int) -> Backend | None:
    """Choose the backend for a Slipnet of ``n_nodes``.

    **``auto`` means the GPU whenever the GPU exists**, at every size, and that is a
    requirement rather than a tuning choice.  Section B1 of the Phase 0 plan states
    what the phase is *for*: "codelets executing simultaneously across multiple CPU
    cores, and the system's numeric work executing on the GPU cores."  A policy that
    declines the GPU below some node count does not satisfy that at today's 59 nodes,
    which is the only size the engine currently runs at — it would ship a GPU substrate
    that never executes.

    This costs throughput now and the cost is documented rather than hidden: a Metal
    dispatch is ~0.2 ms whether it carries 200 edges or 340,000, so at 59 nodes the
    dispatch dominates work that vectorised CPU finishes in 0.007 ms.  That is a fact
    about the Slipnet as it stands, not about the one being built.  The measured
    crossover is ~10^4 nodes and later phases target ~300,000, at which point the same
    policy is simply correct; ``PETACAT_NUMERIC_MIN_GPU_NODES`` remains available for
    anyone who needs the old size-gated behaviour on a given run.

    ``None`` means "run the engine's own loops", and is now reached only by asking for
    it (``off``) or by there being no vectorised backend installed at all.
    """
    configured, _threshold, gpu_threshold_nodes = _policy()
    if configured == "off":
        return None
    if configured != "auto":
        return get_backend(configured)

    # The GPU first, unconditionally, unless a threshold has been set deliberately.
    mlx = _classes().get("mlx")
    if mlx is not None and mlx.is_available() and n_nodes >= gpu_threshold_nodes:
        return get_backend("mlx")
    return best_available(n_nodes)


def reset_backend_cache() -> None:
    """Forget cached instances, classes and the selection policy.

    Only tests and the benchmarks need this: they manipulate
    ``PETACAT_NUMERIC_BACKEND`` and, in one case, make MLX unimportable to prove
    the engine still runs without it, which requires the lazy class registry to be
    re-evaluated.
    """
    global _POLICY
    _INSTANCES.clear()
    _CLASSES.clear()
    _POLICY = None


@contextmanager
def use_backend(name: str | None, threshold: int | None = None) -> Iterator[None]:
    """Force a backend for the duration of a block, then restore.

    The way the substrate is exercised on a 59-node Slipnet.  Under ``auto`` the
    size policy would never engage it there, so without an override the
    expected-range check and the agreement tests would verify the reference path
    against itself.

    ``name=None`` restores ``auto``.  Backend instances are cleared on both entry
    and exit, because an engine object that resolved its backend under the old
    policy must not keep it.
    """
    previous_backend = os.environ.get(ENV_BACKEND)
    previous_threshold = os.environ.get(ENV_MIN_NODES)
    if name is None:
        os.environ.pop(ENV_BACKEND, None)
    else:
        os.environ[ENV_BACKEND] = name
    if threshold is None:
        os.environ.pop(ENV_MIN_NODES, None)
    else:
        os.environ[ENV_MIN_NODES] = str(threshold)
    reset_backend_cache()
    try:
        yield
    finally:
        for key, value in (
            (ENV_BACKEND, previous_backend),
            (ENV_MIN_NODES, previous_threshold),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_backend_cache()
