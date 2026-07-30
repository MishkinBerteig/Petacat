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

from fastapi import APIRouter
from pydantic import BaseModel

from server.api.runs import get_run_service
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
    #: One sentence for a tooltip, so the client does not have to reassemble the
    #: above into prose and drift from it.
    summary: str


@router.get("/numeric", response_model=NumericSubstrateResponse)
async def numeric_substrate() -> NumericSubstrateResponse:
    """Report the numeric backend, the device it dispatches to, and the Slipnet size.

    The three together, because none of them means much alone: "mlx" without the node
    count hides that the GPU is being used at a size where it is slower than NumPy,
    and the node count without the backend says nothing about where the work lands.
    """
    meta = get_run_service().meta
    n_nodes = len(meta.slipnet_node_specs)

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

    if name is None:
        summary = (
            "No numeric substrate: the engine runs its own loops over "
            f"{n_nodes} Slipnet nodes."
        )
    else:
        where = "the GPU (Metal via MLX)" if device == "gpu" else "the CPU"
        summary = (
            f"Numeric substrate {name!r} on {where}, {precision}, over "
            f"{n_nodes} Slipnet nodes."
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
        summary=summary,
    )
