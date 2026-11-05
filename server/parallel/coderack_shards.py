"""The locked coderack that free-running execution installs (WP4.3).

The Coderack is touched by the runner on every post and every selection, and selection is
not a queue pop.  It is a two-stage draw: pick one of seven urgency bins with probability
proportional to ``count x (1 + bin) ** ((110 - temperature) / 15)``, then pick uniformly
within the bin.  That distribution is the mechanism by which temperature regulates
exploration, so a decomposition that distorts it does not make the engine faster; it makes
it a different engine.

**Locked single rack** (:class:`LockedCoderack`) is the serial engine's rack with a mutex
around it, so its semantics are exactly the serial engine's.  Free-running execution
installs it.  Two sharded candidates (by codelet family, and per worker with work stealing)
were built and measured here (WP4.3), and both were removed: neither is installed by any
run mode, and a per-worker shard draw is not the serial draw.  "Shard by workspace region"
was never buildable, because a codelet does not know its region until it runs.  The
measurements are in ``PHASE 0 PLAN.md``.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from server.engine.coderack import Codelet, Coderack

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG


class LockedCoderack:
    """One rack, one mutex. The control.

    Fidelity is perfect by construction — this is the serial rack — so what it measures
    is the price of perfect fidelity. That matters more than it sounds: if a locked rack
    turns out not to be the bottleneck at eight workers, the more elaborate candidates
    are solving a problem the engine does not have, and the right answer is the simple
    one.

    ``blocking=False`` first, then blocking, so a contended acquisition can be *counted*
    rather than inferred. That is the only reason for the two-step; an uncontended
    ``acquire(False)`` succeeds and costs the same as a plain acquire.
    """

    def __init__(self, meta: MetadataProvider, rack: Coderack | None = None) -> None:
        #: ``rack`` adopts an existing serial rack (and its contents) rather than
        #: building an empty one: this is how the free-running engine installs it.
        self._rack = rack if rack is not None else Coderack(meta)
        self._lock = threading.Lock()
        self.contended_acquisitions = 0
        #: How many times the rack has been emptied.
        self.generation = 0

    @property
    def is_empty(self) -> bool:
        return self.total_count == 0

    def _acquire(self) -> None:
        if not self._lock.acquire(blocking=False):
            self.contended_acquisitions += 1
            self._lock.acquire()

    def post(self, codelet: Codelet, current_time: int | None = None,
             rng: RNG | None = None) -> None:
        self._acquire()
        try:
            self._rack.post(codelet, current_time, rng)
        finally:
            self._lock.release()

    def post_deferred(self, batch: list[Codelet], current_time: int | None = None,
                      rng: RNG | None = None, temperature: float | None = None) -> None:
        self._acquire()
        try:
            self._rack.post_deferred(batch, current_time, rng, temperature)
        finally:
            self._lock.release()

    def choose_and_remove(self, temperature: float, rng: RNG,
                          worker: int | None = None) -> Codelet | None:
        # ``worker`` is accepted and ignored: there is one rack, so there is nothing
        # for a worker to be affine to, and every draw is the serial draw.
        self._acquire()
        try:
            return self._rack.choose_and_remove(temperature, rng)
        finally:
            self._lock.release()

    def clear(self) -> None:
        self._acquire()
        try:
            self.generation += 1
            self._rack.clear()
        finally:
            self._lock.release()

    def _locked(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self._acquire()
        try:
            return getattr(self._rack, name)(*args, **kwargs)
        finally:
            self._lock.release()

    def clamp_codelet_type(self, codelet_type: str, urgency: int) -> None:
        self._locked("clamp_codelet_type", codelet_type, urgency)

    def unclamp_codelet_type(self, codelet_type: str) -> None:
        self._locked("unclamp_codelet_type", codelet_type)

    def clamp_pattern(self, pattern: Any, background: str | None = None) -> None:
        self._locked("clamp_pattern", pattern, background)

    def unclamp_all(self) -> None:
        self._locked("unclamp_all")

    @property
    def total_count(self) -> int:
        return self._rack.total_count

    @property
    def rng(self) -> RNG | None:
        return self._rack.rng

    @rng.setter
    def rng(self, value: RNG | None) -> None:
        self._rack.rng = value

    @property
    def current_time(self) -> int:
        return self._rack.current_time

    @current_time.setter
    def current_time(self, value: int) -> None:
        self._rack.current_time = value

    @property
    def current_temperature(self) -> float:
        return self._rack.current_temperature

    @current_temperature.setter
    def current_temperature(self, value: float) -> None:
        self._rack.current_temperature = value

    def __getattr__(self, name: str) -> Any:
        # Everything else — clamping, type counts, bins for inspection — delegates.
        return getattr(self._rack, name)

    def __repr__(self) -> str:
        return f"LockedCoderack({self.total_count} codelets)"
