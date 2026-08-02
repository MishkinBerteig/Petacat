"""FastAPI router for process-level facts: what is executing, not what was recorded.

A separate module from ``api/docs.py``, which is the obvious other home, for two
reasons that both come down to the database.

``docs.py`` is a *content* router: every route there takes ``Depends(get_session)``
and answers by reading ``help_topics``, ``slipnet_node_defs`` or
``codelet_type_defs``.  Nothing here reads a row.  The numeric substrate is chosen
from the environment and from what is importable in this interpreter, so the answer
lives in the process rather than in Postgres, and giving it a session dependency
would be inventing a reason for it to fail.

The second reason is Fast Run.  Phase 0 §A2 requires a Fast Run to complete with the
database stopped, so the dashboard has to stay legible in that condition — and the
first question a reader asks when the panels are quiet is *what is actually running*.
An endpoint that answered that only while Postgres was up would go dark exactly when
it is needed.  Nothing in this module touches a session, and that is the point of the
module rather than an incidental property of it.

Read-only by construction: no route here has a side effect, and none takes a body.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from server.api.runs import get_run_service
from server.engine import hardware
from server.engine.numeric import (
    BackendUnavailable,
    available_backends,
    configured_backend_name,
    select_backend,
    vectorise_threshold,
)
from server.engine.numeric.backend import gpu_threshold

router = APIRouter(prefix="/api/system", tags=["system"])


#: Which processor a backend's arithmetic actually lands on.  Derived from the
#: registry name rather than from the backend class's ``device`` attribute, because
#: that attribute is an MLX ``Device`` whose ``repr`` ("Device(gpu, 0)") is a detail
#: of a third-party framework and has no business in a stable API response.
_DEVICE_BY_BACKEND = {
    "mlx": "gpu",
    "mlx-cpu": "cpu",
    "numpy": "cpu",
    "python": "cpu",
}

#: Float width each backend computes in.  MLX has no float64 on the GPU, so the GPU
#: path is float32 and does not match the reference bit-for-bit; saying so here is
#: cheaper than having somebody rediscover it from a diverging activation.
_PRECISION_BY_BACKEND = {
    "mlx": "float32",
    "mlx-cpu": "float64",
    "numpy": "float64",
    "python": "float64",
}


class DetectedMachine(BaseModel):
    """The machine this process is running on, as its own probes report it.

    Reported so that a figure recorded on one machine can be read on another and
    still be interpretable: a throughput number, a worker count and a crossover
    threshold all mean something different on a 12-core laptop and a 32-core desktop,
    and this is the part of the answer that says which one produced them.
    """

    platform: str
    #: Marketing name of the processor, when the machine reports one.
    chip: str | None
    logical_cores: int
    #: Cores on the fastest performance level.  Equal to ``logical_cores`` on a
    #: machine that reports a single level.
    performance_cores: int
    efficiency_cores: int
    memory_bytes: int | None
    gpu_name: str | None
    #: GPU cores, when a probe reports them.
    gpu_cores: int | None
    #: True when ``mlx.core`` is importable, which is what puts the Metal backend
    #: within reach.
    metal_available: bool
    #: Which probe answered for the CPU and the GPU, or why it did not.
    cpu_probe: str
    gpu_probe: str


class DerivedSizes(BaseModel):
    """The sizes computed from the detected machine.

    Every one of these follows from :class:`DetectedMachine` by a rule stated in
    ``server/engine/hardware.py``, and every one is overridable by an environment
    variable.  ``overrides`` names the variables actually set in this process.
    """

    #: Free-running worker threads: one per performance core.
    workers: int
    #: Coderack shards: one per worker, floor of two, bounded further by the
    #: capacity a shard needs.
    coderack_shards: int
    #: Processes in a population pool: every logical core but one.
    population_workers: int
    #: GPU cores the Metal dispatch is sized for.
    gpu_cores: int
    #: Threads a Metal dispatch aims for: GPU cores x 1,024, to a power of two.
    gpu_target_threads: int
    overrides: dict[str, str]


class NumericSubstrateResponse(BaseModel):
    """Which implementation of the engine's arithmetic this process is running."""

    #: What ``PETACAT_NUMERIC_BACKEND`` asks for: ``auto``, a backend name, or ``off``.
    policy: str
    #: The backend ``auto`` (or the override) actually resolved to for this Slipnet.
    #: ``null`` means the substrate declined and the engine runs its own loops.
    backend: str | None
    device: str
    precision: str
    #: True when the backend computes in float64 and so matches the reference exactly.
    exact: bool
    #: Registered backends whose dependency is importable here.
    available: list[str]
    #: Node and link counts of the Slipnet the selection was made against.
    slipnet_nodes: int
    slipnet_links: int
    #: The two size gates ``auto`` uses.  ``gpu_threshold`` is 0 by default, which is
    #: why the GPU is selected at today's 59 nodes.
    vectorise_threshold: int
    gpu_threshold: int
    #: The machine the thresholds and the derived sizes are answers for.
    hardware: DetectedMachine
    #: What was computed from it.
    derived: DerivedSizes
    #: One sentence for a tooltip, so the client does not have to reassemble the
    #: above into prose and drift from it.
    summary: str


@router.get("/numeric", response_model=NumericSubstrateResponse)
async def numeric_substrate() -> NumericSubstrateResponse:
    """Report the numeric backend, the device it dispatches to, and the Slipnet size.

    The three together, because none of them means much alone: "mlx" without the node
    count hides that the GPU is being used at a size where it is slower than NumPy,
    and the node count without the backend says nothing about where the work lands.

    The detected machine and the sizes derived from it come with them, so the whole
    answer is self-contained: what the machine is, what was computed from it, and
    which implementation of the arithmetic that produced.
    """
    meta = get_run_service().meta
    n_nodes = len(meta.slipnet_node_specs)

    # The GPU probe shells out to ``system_profiler`` the first time it is asked, so
    # it goes to a thread and leaves the event loop free.  Subsequent calls are cached
    # and return immediately.
    machine = await asyncio.to_thread(hardware.detect)
    derived = await asyncio.to_thread(hardware.derived_sizes)

    try:
        backend = select_backend(n_nodes)
    except BackendUnavailable:
        # An explicit ``PETACAT_NUMERIC_BACKEND`` naming something that is not
        # installed.  Reported as "no substrate" rather than raised: this endpoint
        # exists to say what is running, and a 500 here would say nothing at all.
        backend = None

    name = backend.name if backend is not None else None
    device = _DEVICE_BY_BACKEND.get(name or "", "cpu")
    precision = _PRECISION_BY_BACKEND.get(name or "", "float64")
    exact = backend.exact if backend is not None else True

    machine_phrase = (
        f"{machine.cpu.chip or machine.platform}, "
        f"{machine.cpu.performance_cores}P+{machine.cpu.efficiency_cores}E cores"
        + (f", {machine.gpu.cores}-core GPU" if machine.gpu.cores else "")
    )
    if name is None:
        summary = (
            "No numeric substrate: the engine runs its own loops over "
            f"{n_nodes} Slipnet nodes on {machine_phrase}."
        )
    else:
        where = "the GPU (Metal via MLX)" if device == "gpu" else "the CPU"
        summary = (
            f"Numeric substrate {name!r} on {where}, {precision}, over "
            f"{n_nodes} Slipnet nodes on {machine_phrase}."
        )

    return NumericSubstrateResponse(
        policy=configured_backend_name(),
        backend=name,
        device=device,
        precision=precision,
        exact=exact,
        available=available_backends(),
        slipnet_nodes=n_nodes,
        slipnet_links=len(meta.slipnet_link_specs),
        vectorise_threshold=vectorise_threshold(),
        gpu_threshold=gpu_threshold(),
        hardware=DetectedMachine(
            platform=machine.platform,
            chip=machine.cpu.chip,
            logical_cores=machine.cpu.logical_cores,
            performance_cores=machine.cpu.performance_cores,
            efficiency_cores=machine.cpu.efficiency_cores,
            memory_bytes=machine.cpu.memory_bytes,
            gpu_name=machine.gpu.name,
            gpu_cores=machine.gpu.cores,
            metal_available=machine.gpu.metal_available,
            cpu_probe=machine.cpu.probe,
            gpu_probe=machine.gpu.probe,
        ),
        derived=DerivedSizes(
            **derived, overrides=hardware.overrides_in_force()
        ),
        summary=summary,
    )
