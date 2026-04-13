"""Deterministic Random Number Generator.

Wraps Python's random.Random instance. Every stochastic function
receives the RNG instance explicitly — this is the single source
of all non-determinism in the engine.

Scheme source: utilities.ss (random-pick, stochastic-pick, prob?, ~)
"""

from __future__ import annotations

import math
import random
from typing import Any, Callable, Sequence


class RNG:
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

        Each item is selected with probability proportional to its weight.
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
            if cumulative >= threshold:
                return item
        return items[-1]

    def perturb(self, n: float) -> float:
        """Add random jitter proportional to sqrt(n). Replaces Scheme ~ operator.

        Scheme: delta = random(1 + round(sqrt(n))), direction = 50% chance.
        """
        if n <= 0:
            return n
        delta = self.randint(1 + round(math.sqrt(abs(n))))
        if self.prob(0.5):
            return n + delta
        else:
            return n - delta

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
