"""Deterministic Random Number Generator.

Wraps Python's random.Random instance. Every stochastic function
receives the RNG instance explicitly — this is the single source
of all non-determinism in the engine.

Scheme source: utilities.ss (random-pick, stochastic-pick, prob?, ~)

The trace seam
--------------
``TraceSeam`` carries the lockstep harness's hooks (``tests/lockstep/``): where a
decision happened (``trace_unit``, ``trace_about``), the end-of-cycle snapshot
(``trace_snapshot``) and the codelet choice that Metacat logs as one decision
(``composite_choice``).  Here every one of them is a pass-through, so an ordinary run
draws exactly what it drew before the seam existed.
"""

from __future__ import annotations

import math
import random
from typing import Any, Callable, Sequence


class TraceSeam:
    """No-op hooks the lockstep harness overrides; see the module docstring.

    A mixin with no state, shared by ``RNG`` and ``SplittableRNG`` so engine code can
    call the hooks on whichever generator a codelet holds.
    """

    __slots__ = ()

    def trace_unit(self, c: int, ctx: str, who: str, u: int | None = None) -> Any:
        """Enter a unit of work (``init``/``choose``/``codelet``/``update``).

        Returns a token for ``trace_restore``, which resumes the enclosing unit
        (an update cycle can run inside a codelet).
        """
        return None

    def trace_restore(self, token: Any) -> None:
        """Resume the unit ``trace_unit`` returned *token* for."""

    def trace_about(self, about: Any) -> Any:
        """Name the object the following decisions concern; returns the previous one."""
        return None

    def trace_snapshot(self, ctx: Any) -> None:
        """Called at the end of every update cycle with the engine context."""

    def composite_choice(
        self, label: str, build: Callable[[], tuple[list, list, list]],
        pick: Callable[[], Any],
    ) -> Any:
        """One logical choice made in several stages (codelet selection, eviction).

        *build* returns ``(options, weights, stamps)`` for a tracing generator and is
        never called here; *pick* makes the choice with the engine's own draws and
        returns the option.  ``label`` is ``"choose"`` or ``"evict"``.
        """
        return pick()


class RNG(TraceSeam):
    __slots__ = ("_rng", "_seed", "_call_count")

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)
        self._seed = seed
        self._call_count = 0

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def call_count(self) -> int:
        return self._call_count

    # -- Core random calls --

    def random(self) -> float:
        """Return a float in [0.0, 1.0). Replaces Scheme (random 1.0)."""
        self._call_count += 1
        return self._rng.random()

    def randint(self, n: int) -> int:
        """Return an int in [0, n). Replaces Scheme (random n)."""
        if n <= 0:
            return 0
        self._call_count += 1
        return self._rng.randrange(n)

    def prob(self, p: float) -> bool:
        """Return True with probability p. Replaces Scheme prob?."""
        if p >= 1.0:
            return True
        if p <= 0.0:
            return False
        return self.random() < p

    def pick(self, items: Sequence[Any]) -> Any:
        """Pick a uniformly random element. Replaces Scheme random-pick."""
        if not items:
            raise ValueError("Cannot pick from empty sequence")
        return items[self.randint(len(items))]

    def weighted_pick(self, items: Sequence[Any], weights: Sequence[float]) -> Any:
        """Pick an element weighted by weights. Replaces Scheme stochastic-pick.

        Each item is selected with probability proportional to its weight.  The
        first item whose running total *exceeds* the threshold wins — the strict
        ``<`` of ``weighted-index`` (``utilities.ss:507``) — so an item of weight 0
        can never be picked, even by a draw of exactly 0.0.
        """
        if not items:
            raise ValueError("Cannot pick from empty sequence")
        total = sum(weights)
        if total <= 0:
            return self.pick(items)
        threshold = self.random() * total
        cumulative = 0.0
        for item, weight in zip(items, weights):
            cumulative += weight
            if cumulative > threshold:
                return item
        return items[-1]

    def perturb(self, n: float) -> float:
        """Blur ``n`` by a whole number up to about its own square root — Scheme's ``~``.

        ``utilities.ss:468`` (``~``), with ``round`` as redefined at ``:250-252``::

            (define round (lambda (n) (inexact->exact (scheme-round n))))   ; :250-252
            (define ~
              (lambda (n)
                (let ((delta (random (add1 (round (sqrt n))))))
                  (if (prob? 0.5) (+ n delta) (- n delta)))))

        Metacat shadows ``round`` so that it always returns an *exact* integer
        (half-to-even, as Chez's ``round`` does, and as Python's does).  The bound
        ``1 + round(sqrt n)`` is therefore always an exact integer, ``random`` of an
        exact integer returns an exact integer, and the delta is always a whole
        number drawn from ``0 .. round(sqrt n)``.  This used to draw a continuous
        delta whenever ``n`` was not a perfect square (``DISCREPANCIES5.md`` A-1),
        reasoning from Chez's unshadowed ``round`` — which is not the ``round`` the
        reference's ``~`` calls.

        The difference is reachable: ``rough-num-of-objects`` asks
        ``(< count (~ 2))``, and at a count of 2 the whole-number reading answers
        "few" a quarter of the time where the continuous one answered it half.
        """
        if n <= 0:
            return n
        delta = self.randint(self.perturb_bound(n))
        return n + delta if self.prob(0.5) else n - delta

    @staticmethod
    def perturb_bound(n: float) -> int:
        """The exclusive bound ``~`` draws its delta below: ``1 + round(sqrt n)``."""
        return 1 + round(math.sqrt(abs(n)))

    def stochastic_filter(
        self, items: Sequence[Any], prob_fn: Callable[[Any], float]
    ) -> list[Any]:
        """Keep each item with probability prob_fn(item)."""
        return [item for item in items if self.prob(prob_fn(item))]

    # -- State serialization for checkpointing --

    def get_state(self) -> tuple:
        """Return internal PRNG state for DB serialization."""
        return (self._seed, self._call_count, self._rng.getstate())

    def set_state(self, state: tuple) -> None:
        """Restore from a saved state."""
        self._seed, self._call_count, rng_state = state
        self._rng.setstate(rng_state)

    def __repr__(self) -> str:
        return f"RNG(seed={self._seed}, calls={self._call_count})"
