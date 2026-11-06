"""A run's fingerprint: everything a run decided, hashed, for "this change moved a run" tests.

Status, answers, codelet count, RNG draws (total and per codelet), codelet types, the final state and
the Trace.  Two runs with the same fingerprint did the same thing.  The same ingredients as
``tests/seed_unit/test_every_moved_value_reaches_its_site_a.py``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def fingerprint(meta: Any, problem: tuple[str, str, str], seed: int, answer: str | None = None,
                backend: str = "numpy", cap: int | None = None) -> str:
    from server.engine.memory import EpisodicMemory
    from tests.support import golden_baseline as gb

    runner, rng, draws, types, _ = gb.run_observed(
        meta, tuple(problem), seed, answer, EpisodicMemory(), False, backend=backend, cap=cap
    )
    ctx = runner.ctx
    return hashlib.sha256(
        json.dumps([
            runner.status, list(runner._answers), ctx.codelet_count, rng.call_count,
            ",".join(map(str, draws)), ",".join(types), gb.state_digest(ctx),
            gb.canonical(gb._trace_summary(ctx.trace.events)),
        ]).encode()
    ).hexdigest()
