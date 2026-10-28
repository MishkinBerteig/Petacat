"""Faithful mode (spec §6.1): one problem and seed, run the way the trace compares.

Sequential ``EngineRunner`` (no free-running, shards or splittable RNG), the numeric
backend off (the engine's own float64 object-graph loops) unless
``PETACAT_LOCKSTEP_NUMERIC_BACKEND`` names one, fresh episodic memory, the
standard ``RNG`` interface (a tracing or replaying subclass is passed in), Metacat's
codelet cap, and the decision-changing mechanisms that have a switch set to Metacat's
value.  Defaults the spec says to keep (spreading threshold 100, staleness delay 0,
access tracking off, self-watching on) are simply left alone.
"""

from __future__ import annotations

import functools
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.lockstep.context import ReplayStop

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = REPO_ROOT / "seed_data"

#: Metacat's cap (``run.ss:28``: none by default; the driver sets 100,000).
DEFAULT_CAP = 100_000

#: Parameter overrides faithful mode applies.  ``initial_clamp_fixed_time`` makes the
#: initial slipnode clamp lapse at Metacat's fixed codelet count (``run.ss:151-154``)
#: instead of on an update-cycle countdown.
FAITHFUL_PARAMETERS: dict[str, Any] = {"initial_clamp_fixed_time": True}

#: Names the numeric backend a faithful run uses instead of ``off`` (``python``,
#: ``numpy``, ``mlx``, ``mlx-cpu``).  ``scripts/lockstep_corpus.py --numeric-backend``
#: sets it, so the substrate Petacat runs by default is replayed against Metacat too.
NUMERIC_BACKEND_ENV = "PETACAT_LOCKSTEP_NUMERIC_BACKEND"


def numeric_backend() -> str:
    return os.environ.get(NUMERIC_BACKEND_ENV) or "off"


def faithful_settings() -> dict[str, Any]:
    """The values recorded in a trace header's ``settings`` (informational)."""
    return {
        "runner": "EngineRunner",
        "rng": "RNG",
        "numeric_backend": numeric_backend(),
        "memory": "fresh",  # an episode carries one memory across its runs
        "parameters": dict(FAITHFUL_PARAMETERS),
        "spreading_activation_threshold": 100,
        "staleness_delay": 0,
        "access_tracking": False,
        "self_watching": True,
    }


@functools.lru_cache(maxsize=1)
def git_revision() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        return out or "unknown"
    except Exception:
        return "unknown"


@functools.lru_cache(maxsize=1)
def _metadata() -> Any:
    from server.engine.metadata import MetadataProvider

    return MetadataProvider.from_seed_data(str(SEED_DIR))


def header_record(problem: tuple[str, str, str], seed: int, cap: int,
                  answer: str | None = None, **extra: Any) -> dict[str, Any]:
    from tests.lockstep.trace_io import FORMAT

    rec: dict[str, Any] = {
        "t": "header", "format": FORMAT, "engine": "petacat",
        "revision": git_revision(), "problem": list(problem), "seed": seed,
        "cap": cap, "settings": faithful_settings(),
    }
    if answer:
        rec["answer"] = answer  # justify mode (after "cap", as Metacat's header has it)
    rec.update(extra)
    return rec


@dataclass
class Outcome:
    """How a faithful run ended; becomes the trace's ``end`` record."""

    reason: str  # answer | give-up | cap | error | fatal
    c: int
    answer: str | None = None
    error: str | None = None
    fatal: ReplayStop | None = None
    #: The runner, for tests that look at the finished workspace.
    runner: Any = field(default=None, repr=False)

    def record(self) -> dict[str, Any]:
        rec: dict[str, Any] = {"t": "end", "c": self.c, "reason": self.reason}
        if self.answer is not None:
            rec["answer"] = self.answer
        if self.error is not None:
            rec["error"] = self.error
        return rec


def run_faithful(problem: tuple[str, str, str], seed: int, cap: int, rng: Any,
                 answer: str | None = None, memory: Any = None) -> Outcome:
    """Run ``problem`` with ``rng`` in faithful mode and say how it ended.

    ``answer`` selects justify mode (``init_mcat``'s fourth argument); ``memory`` is
    the episode's ``EpisodicMemory`` carried over from earlier runs (fresh when None).

    ``rng`` is installed as ``ctx.rng``, ``ctx.coderack.rng`` and every codelet body's
    ``rng`` by ``init_mcat(..., rng=rng)``.
    """
    from server.engine.memory import EpisodicMemory
    from server.engine.numeric.backend import use_backend
    from server.engine.runner import (
        STATUS_ANSWER_FOUND, STATUS_GAVE_UP, EngineRunner,
    )

    runner = EngineRunner(_metadata())
    with use_backend(numeric_backend()):
        try:
            runner.init_mcat(
                *problem, answer=answer, seed=seed,
                memory=memory if memory is not None else EpisodicMemory(),
                parameters=dict(FAITHFUL_PARAMETERS), rng=rng,
            )
            result = runner.run_mcat(max_steps=cap)
        except ReplayStop as stop:
            c = runner.ctx.codelet_count if runner.ctx else 0
            return Outcome("fatal", rng.tc.c if hasattr(rng, "tc") else c,
                           fatal=stop, runner=runner)
        except Exception as exc:  # a crash like those in KNOWN-FAILURES.md
            # Metacat's c for an error is the codelet it died inside: count + 1.
            c = runner.ctx.codelet_count + 1 if runner.ctx else 0
            return Outcome("error", c, error=f"{type(exc).__name__}: {exc}",
                           runner=runner)
    c = runner.ctx.codelet_count
    if runner.status == STATUS_ANSWER_FOUND:
        return Outcome("answer", c, answer=(result.answers or [None])[-1],
                       runner=runner)
    if runner.status == STATUS_GAVE_UP:
        return Outcome("give-up", c, runner=runner)
    return Outcome("cap", c, runner=runner)
