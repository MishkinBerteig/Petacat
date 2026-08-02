"""The numeric substrate — the engine's arithmetic, off the object graph.

``server/engine/numeric/`` holds the parts of the engine that are *numbers over
arrays* rather than *decisions over structures*: Slipnet activation spreading,
decay and the probabilistic jump; themespace intra-cluster dynamics; workspace
object values; structure strengths; temperature.  Per the Phase 0 profile these
are about 30% of runtime today, and the first of them is the one that stops being
tractable when the Slipnet grows toward the ~300,000 nodes later phases target.

Three things to know before reading further.

**MLX is optional and the engine does not depend on it.**  ``python`` is the
reference backend, pure standard library, always present; ``numpy`` and ``mlx``
are alternatives selected when they are installed and when the problem is big
enough to pay for them.  With neither installed the engine computes exactly what
it computed before, at exactly the speed it did.

**The default at 59 nodes is to not use this at all.**  Dispatching a
sub-millisecond computation to any vector unit costs more than doing it in place.
``backend.select_backend`` returns ``None`` below a size threshold, and the engine
falls through to its own loops.  This is a deliberate outcome rather than a
limitation: the substrate exists so that the layout, the kernels and the seam are
in place *before* the Slipnet grows, not so that today's Slipnet runs faster.

**Purity.**  Nothing here imports ``sqlalchemy``, ``server.models``, ``server.db``
or ``server.services``, and ``tests/architecture/test_engine_purity.py`` enforces that
automatically for every module in this package.  NumPy and MLX are third-party
imports, which that policy permits and which this package uses only behind
``try: import`` guards, so the engine remains runnable on a checkout with neither.
"""

from server.engine.numeric.backend import (
    DEFAULT_VECTORISE_THRESHOLD,
    Backend,
    BackendUnavailable,
    SlipnetSession,
    available_backends,
    backend_names,
    best_available,
    configured_backend_name,
    get_backend,
    reset_backend_cache,
    select_backend,
    vectorise_threshold,
)
from server.engine.numeric.layout import (
    ObjectValueBatch,
    SlipnetState,
    SlipnetTopology,
    ThemeLayout,
    ThemeParams,
    ThemeState,
    gather_object_values,
    scatter_object_values,
    string_type_code,
)

__all__ = [
    "Backend",
    "BackendUnavailable",
    "DEFAULT_VECTORISE_THRESHOLD",
    "ObjectValueBatch",
    "SlipnetSession",
    "SlipnetState",
    "SlipnetTopology",
    "ThemeLayout",
    "ThemeParams",
    "ThemeState",
    "available_backends",
    "backend_names",
    "best_available",
    "configured_backend_name",
    "gather_object_values",
    "get_backend",
    "reset_backend_cache",
    "scatter_object_values",
    "select_backend",
    "string_type_code",
    "vectorise_threshold",
]
