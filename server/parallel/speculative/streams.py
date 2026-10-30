"""The random streams of a stream-serial run -- what each key is, and why.

The faithful loop (``EngineRunner.run_mcat``) draws every random number from one
Mersenne Twister, so draw *n* depends on every draw before it: the order the draws
happen in is part of the value.  That is exactly what a parallel executor cannot keep.
The stream-serial reference (SSR) therefore replaces the one generator with a *family*
of counter-based generators (:class:`~server.engine.splittable_rng.SplittableRNG`), each
addressed by a key that does not depend on how fast any thread ran.  A speculative
engine that reproduces the same keys draws the same numbers however its threads
interleave -- which is the whole of its exactness argument for randomness.

Every key below is a *label* passed to ``SplittableRNG.split``; the child's stream id is
a hash of ``(seed, parent stream, label)``, so two different keys cannot collide by
arithmetic coincidence.  A stream is rebuilt from scratch by anybody who knows the key,
which is what lets a speculative body that aborts re-execute "with a fresh body stream,
same key, same numbers".

``BODY``      one stream per **codelet id**, not per step.
    ``Codelet.id`` is allocated when the codelet is constructed, i.e. at post time, in
    serial order -- so it names the codelet for as long as it lives.  A step number
    does not: when an earlier-posted codelet with a smaller clock lands ahead of a
    predicted one, the predicted codelet's *step* shifts by one but its *id* does not.
    Keying by id means the speculative work already done for it stays valid; keying by
    step would have thrown it away.  Everything a codelet body draws -- the scout's
    object pick, an evaluator's coin, the density walk inside ``update_strength``, the
    eviction draw of a ``post`` it makes -- comes from this one stream, in body order.

``CLOCK``     one draw per **codelet id**, for the exponential race.
    A codelet's firing time is ``t_now + E / w`` with ``E = -ln(1 - U)``; ``U`` is the
    first draw of the clock stream at counter ``id``.  It is a pure function of
    ``(seed, id)`` -- computed with a single hash and no stream object -- so the clock
    rack never has to remember anything but the codelet id.  A *separate* key from
    ``BODY`` so that how many numbers a body draws can never shift a clock.

``FALLBACK``  one stream per **step**.
    Choosing by the exponential race draws nothing -- except in the degenerate case the
    faithful rack also special-cases, when every bin weight is zero and it falls back
    to "uniform over the non-empty bins, then uniform within the bin".  That fallback
    needs two real draws, and they come from a stream keyed by the step number being
    chosen (``codelet_count + 1``), the only thing that names a choice.

``UPDATE``    one stream per **update-cycle index** ``u``.
    ``EngineRunner._update_cycle`` numbers the cycles 1, 2, ...; cycle *u* draws every
    number it needs -- density walks, the snag-exit coin, slipnet jumps, posting
    probabilities, the deferred-batch eviction -- from this stream.  A cycle run from
    inside a codelet (answer report, snag restart) is still cycle *u* and still binds
    this stream for its duration, then hands back the codelet's own stream.

``LOOP``      one stream per **step**, for the loop's own events.
    ``_step_mcat`` re-posts the opening codelets when the rack is empty, and that
    posting evicts and drops codelets stochastically.  It is bound as the ambient
    stream for the whole step, under the body stream a codelet binds on top of it.

The ``init_mcat`` phase is untouched: it draws from the ``RNG(seed)`` Mersenne Twister
the runner was built with, exactly as in the faithful loop, so the starting state of a
stream-serial run and of a speculative run is the faithful run's own starting state.
"""

from __future__ import annotations

import math
import struct
from hashlib import sha256

from server.engine.splittable_rng import SplittableRNG

_MASK64 = (1 << 64) - 1
_FLOAT_DIVISOR = float(1 << 53)

#: Labels.  Arbitrary distinct small integers; never reuse or renumber them, because a
#: change here changes every stream-serial run.
BODY = 1
CLOCK = 2
FALLBACK = 3
UPDATE = 4
LOOP = 5


class Streams:
    """Derives every stream of one run from the run seed.

    Cheap to build (five hashes) and safe to share between threads: the only mutable
    state in the family is each stream's private counter, and every ``body``/``update``
    call returns a *new* stream object.
    """

    __slots__ = (
        "seed", "_root", "_body", "_clock_stream", "_fallback", "_update", "_loop",
    )

    def __init__(self, seed: int) -> None:
        self.seed = seed
        root = SplittableRNG(seed, 0)
        self._root = root
        self._body = root.split(BODY)
        self._clock_stream = root.split(CLOCK).stream
        self._fallback = root.split(FALLBACK)
        self._update = root.split(UPDATE)
        self._loop = root.split(LOOP)

    # -- keyed streams -------------------------------------------------

    def body(self, codelet_id: int) -> SplittableRNG:
        """A fresh stream for the body of the codelet with this id."""
        return self._body.split(codelet_id)

    def fallback(self, step: int) -> SplittableRNG:
        """The stream the all-zero-weight fallback choice of *step* draws from."""
        return self._fallback.split(step)

    def update(self, cycle: int) -> SplittableRNG:
        """A fresh stream for update cycle *cycle* (1-based)."""
        return self._update.split(cycle)

    def loop(self, step: int) -> SplittableRNG:
        """A fresh stream for the loop's own events while *step* is chosen and run."""
        return self._loop.split(step)

    # -- the clock draw ------------------------------------------------

    def clock_exponential(self, codelet_id: int) -> float:
        """``E = -ln(1 - U)`` for a codelet: a unit-rate exponential, from its id alone.

        ``U`` is the first draw of the CLOCK stream at counter ``codelet_id`` -- the
        same bits ``SplittableRNG(seed, clock_stream, codelet_id).random()`` would
        return, computed with the one hash it takes.  ``1 - U`` is in ``(0, 1]``, so
        the logarithm is always defined and ``E`` is in ``[0, inf)``.
        """
        digest = sha256(
            struct.pack(
                "<QQQ", self.seed & _MASK64, self._clock_stream & _MASK64,
                codelet_id & _MASK64,
            )
        ).digest()
        u = (int.from_bytes(digest[:8], "little") >> 11) / _FLOAT_DIVISOR
        return -math.log1p(-u)
