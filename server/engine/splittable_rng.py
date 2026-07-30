"""Counter-based per-codelet random streams (WP4.1).

The engine has always drawn every random number from one shared ``random.Random``.
That is exactly right for a serial loop and impossible under free-running: a Mersenne
Twister has 19,937 bits of mutable state that every draw advances, so concurrent
codelets either serialise behind a lock — reintroducing the contention the parallelism
was for — or corrupt it.

The replacement is a **counter-based** generator.  Instead of holding state that
advances, it *computes* the n-th value of a stream from ``(seed, stream, counter)`` by
hashing.  Three consequences, and each one matters here:

- **Streams are independent without coordination.** A codelet takes a stream of its
  own, derived from where it ran rather than from what ran before it, so no two workers
  touch the same state and nothing needs a lock.
- **A stream is reproducible without being sequential.** Stream 500 can be evaluated
  without evaluating streams 0–499, which is what makes a parallel run reproducible at
  all: with a shared generator, reproducing draw *n* requires having made draws 0
  through *n−1* in the same order, and under free-running that order does not exist.
- **Splitting is cheap.** Deriving a substream is a hash, not a reseed, so a codelet
  can have one per execution without the cost mattering.

Why SHA-256 rather than a fast counter-based cipher like Philox or ThreeFry: it is in
the standard library, it is fast enough against ~9 random numbers per codelet at
~13,000 codelets a second, and the engine's demands on distribution quality are modest
— temperature-adjusted probabilities and weighted picks over short lists. Being able to
say the stream derivation has no structure worth worrying about is worth more here than
the throughput of a dedicated counter cipher.

What this is *not* for
----------------------
It is not a way to make parallel runs bit-identical to serial ones. Petacat is
stochastic by design, a different-but-correct run is right behaviour, and the standard
for Phase 0 is expected-range agreement — the *set* of reachable stopping states — not
seeded-run agreement. What per-codelet streams buy is that a parallel run draws from
well-defined independent streams rather than from a race.
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Any, Callable, Sequence

#: Streams are addressed by a pair of 64-bit words, which is ample: the first
#: identifies the drawing site (worker, codelet slot, or a derived substream) and the
#: second counts draws within it.
_MASK64 = (1 << 64) - 1

#: 2**53, the largest integer a float64 represents exactly. Dividing a 53-bit integer
#: by this gives a uniform float in [0, 1) with no rounding bias — taking more bits and
#: dividing by 2**64 would round some values to exactly 1.0.
_FLOAT_DIVISOR = float(1 << 53)


def _hash_words(seed: int, stream: int, counter: int) -> bytes:
    return hashlib.sha256(
        struct.pack("<QQQ", seed & _MASK64, stream & _MASK64, counter & _MASK64)
    ).digest()


class SplittableRNG:
    """A random stream identified by ``(seed, stream)``, counted rather than stateful.

    The public surface deliberately mirrors :class:`server.engine.rng.RNG` method for
    method, so the twelve engine modules that draw random numbers need no change: they
    already take the generator from the context rather than reaching for a global.

    The one piece of mutable state is ``_counter``, and it is *private to this stream*.
    Two codelets holding different streams never touch the same counter, which is what
    removes the need for a lock.
    """

    __slots__ = ("_seed", "_stream", "_counter", "_call_count")

    def __init__(self, seed: int, stream: int = 0, counter: int = 0) -> None:
        self._seed = seed
        self._stream = stream
        self._counter = counter
        self._call_count = 0

    # -- identity ------------------------------------------------------

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def stream(self) -> int:
        return self._stream

    @property
    def counter(self) -> int:
        return self._counter

    @property
    def call_count(self) -> int:
        return self._call_count

    def split(self, label: int) -> SplittableRNG:
        """Derive an independent substream.

        The child's stream id is hashed from the parent's ``(seed, stream, label)``
        rather than being ``parent + label``, so sibling streams are not adjacent and
        two different derivation paths cannot arrive at the same stream by arithmetic
        coincidence — which they easily can when ids are added.

        The child starts at counter 0 and the parent is untouched, so splitting is safe
        to do concurrently from the same parent.
        """
        digest = _hash_words(self._seed, self._stream, ~label & _MASK64)
        child_stream = int.from_bytes(digest[:8], "little")
        return SplittableRNG(self._seed, child_stream)

    def for_codelet(self, worker: int, slot: int) -> SplittableRNG:
        """The stream a codelet should draw from, per the plan's ``(run_seed, worker, slot)``.

        ``slot`` is the codelet's position in the run — its index, not its identity —
        so a codelet's stream depends on *where* it ran rather than on what ran before
        it. That is the property that survives reordering: under free-running the order
        is not determined, and a stream derived from a running count would not be.
        """
        digest = _hash_words(self._seed, worker & _MASK64, slot & _MASK64)
        return SplittableRNG(self._seed, int.from_bytes(digest[:8], "little"))

    # -- core draws ----------------------------------------------------

    def _next_words(self) -> bytes:
        digest = _hash_words(self._seed, self._stream, self._counter)
        self._counter += 1
        self._call_count += 1
        return digest

    def random(self) -> float:
        """A float in [0.0, 1.0)."""
        return (int.from_bytes(self._next_words()[:8], "little") >> 11) / _FLOAT_DIVISOR

    def randint(self, n: int) -> int:
        """An int in [0, n).

        Uses rejection sampling rather than a modulo. A modulo over a 64-bit draw is
        biased towards the low residues whenever ``n`` does not divide 2**64, and while
        the bias is tiny at the sizes used here, the correct version costs one
        comparison that almost never retries.
        """
        if n <= 0:
            return 0
        limit = _MASK64 - (_MASK64 % n)
        while True:
            value = int.from_bytes(self._next_words()[:8], "little")
            if value <= limit:
                return value % n

    def prob(self, p: float) -> bool:
        """True with probability ``p``."""
        if p >= 1.0:
            return True
        if p <= 0.0:
            return False
        return self.random() < p

    def pick(self, items: Sequence[Any]) -> Any:
        if not items:
            raise ValueError("Cannot pick from empty sequence")
        return items[self.randint(len(items))]

    def weighted_pick(self, items: Sequence[Any], weights: Sequence[float]) -> Any:
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
        if n <= 0:
            return n
        delta = self.randint(1 + round(math.sqrt(abs(n))))
        return n + delta if self.prob(0.5) else n - delta

    def stochastic_filter(
        self, items: Sequence[Any], prob_fn: Callable[[Any], float]
    ) -> list[Any]:
        return [item for item in items if self.prob(prob_fn(item))]

    # -- state ---------------------------------------------------------

    def get_state(self) -> tuple:
        """The whole state, in three integers.

        Compare the generator this replaces, whose state is a 625-element tuple that
        has to be pickled to be stored. Being able to write a stream's position as
        ``(seed, stream, counter)`` is a direct consequence of it being counter-based,
        and it makes a capture smaller and readable.
        """
        return (self._seed, self._stream, self._counter)

    def set_state(self, state: tuple) -> None:
        self._seed, self._stream, self._counter = state

    def __repr__(self) -> str:
        return (
            f"SplittableRNG(seed={self._seed}, stream={self._stream}, "
            f"counter={self._counter})"
        )
