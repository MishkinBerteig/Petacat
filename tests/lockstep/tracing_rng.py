"""The tracing RNG (spec §6.3) and the machinery it shares with the replay RNG.

``LockstepBase`` is an ``RNG`` whose public helpers apply the spec's §7.1 rules once,
for both subclasses:

* a call made while another helper is running (``prob`` -> ``random``, ``pick`` ->
  ``randint``, ``perturb`` -> three of them) is nested and not a decision of its own;
* options of weight zero are dropped, and if every weight is zero the choice is
  uniform over all options (the fallback both engines make);
* a decision fixed by its inputs is trivial and is not recorded: a choice with fewer
  than two options left, a ``prob`` with ``p`` at or below 0 or at or above 1, an
  ``int`` with bound 1 or less, a ``perturb`` with bound 1.

What differs is how a non-trivial decision is *made*: ``TracingRNG`` draws it with the
real generator and writes a record; ``ReplayRNG`` (``replay_rng.py``) takes the result
from a Metacat trace.  A decision is recorded when it completes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from server.engine.rng import RNG
from tests.lockstep.context import TraceContext
from tests.lockstep.naming import name_of, number_name  # noqa: F401  (re-export)
from tests.lockstep.trace_io import TraceWriter

REPO_ROOT = Path(__file__).resolve().parents[2]
_HERE = Path(__file__).resolve().parent
#: Source files whose frames are not "the caller" when a ``site`` is worked out.
_SKIP = {str(_HERE / "tracing_rng.py"), str(_HERE / "replay_rng.py"),
         str((REPO_ROOT / "server" / "engine" / "rng.py"))}


def caller_site() -> str:
    """``file:line`` of the first frame outside the RNG machinery.

    Codelet bodies are compiled as ``<codelet:name>`` (``interpreter.py:65``), so they
    appear as ``<codelet:bond-evaluator>:12``.
    """
    frame = sys._getframe(1)
    while frame is not None and frame.f_code.co_filename in _SKIP:
        frame = frame.f_back
    if frame is None:
        return "?"
    filename = frame.f_code.co_filename
    if not filename.startswith("<"):
        try:
            filename = str(Path(filename).resolve().relative_to(REPO_ROOT))
        except ValueError:
            pass
    return f"{filename}:{frame.f_lineno}"


class LockstepBase(RNG):
    """Common front end of the tracing and replaying generators."""

    def __init__(self, seed: int, writer: TraceWriter | None = None) -> None:
        super().__init__(seed)
        self.tc = TraceContext()
        self.writer = writer
        self._depth = 0
        #: How many decisions have been recorded (for reports and tests).
        self.decisions = 0

    # -- the engine's trace seam (TraceSeam in server/engine/rng.py) ----------

    def trace_unit(self, c: int, ctx: str, who: str, u: int | None = None) -> Any:
        return self.tc.enter(c, ctx, who, u)

    def trace_restore(self, token: Any) -> None:
        self.tc.restore(token)

    def trace_about(self, about: Any) -> Any:
        return self.tc.set_about(about)

    def trace_snapshot(self, ctx: Any) -> None:
        if self.writer is not None:
            from tests.lockstep.snapshot import snapshot_record

            self.writer.write(snapshot_record(ctx, self.tc.u, self.tc.c))

    # -- writing ---------------------------------------------------------------

    def write(self, record: dict[str, Any]) -> None:
        if self.writer is not None:
            self.writer.write(record)

    def _record(self, kind: str, fields: dict[str, Any], site: str | None = None) -> dict:
        tc = self.tc
        rec: dict[str, Any] = {
            "t": "decision", "c": tc.c, "ctx": tc.ctx, "who": tc.who,
        }
        if tc.ctx == "update":
            rec["u"] = tc.u
        rec["n"] = tc.next_n()
        if tc.about is not None:
            rec["about"] = tc.about if isinstance(tc.about, str) else name_of(tc.about)
        rec["kind"] = kind
        rec.update(fields)
        rec["site"] = site if site is not None else caller_site()
        self.decisions += 1
        return rec

    def _emit(self, kind: str, fields: dict[str, Any], site: str | None = None) -> dict:
        rec = self._record(kind, fields, site)
        self.write(rec)
        return rec

    # -- running the engine's own draw, without it counting as a decision -----

    def _real(self, fn: Callable[..., Any], *args: Any) -> Any:
        self._depth += 1
        try:
            return fn(self, *args)
        finally:
            self._depth -= 1

    # -- the public helpers ----------------------------------------------------

    def random(self) -> float:
        if self._depth:
            return RNG.random(self)
        return self._decide_random()

    def randint(self, n: int) -> int:
        if self._depth:
            return RNG.randint(self, n)
        if n <= 1:
            return self._trivial_int(n)
        return self._decide_int(n)

    def prob(self, p: float) -> bool:
        if self._depth or p >= 1.0 or p <= 0.0:
            return RNG.prob(self, p)
        return self._decide_prob(p)

    def pick(self, items: Sequence[Any]) -> Any:
        if self._depth:
            return RNG.pick(self, items)
        if len(items) < 2:
            return self._trivial_pick(items)
        return self._decide_choice(items, None, list(range(len(items))), True)

    def weighted_pick(self, items: Sequence[Any], weights: Sequence[float]) -> Any:
        if self._depth:
            return RNG.weighted_pick(self, items, weights)
        if not items:
            raise ValueError("Cannot pick from empty sequence")
        idx, uniform = live_indices(weights)
        if len(idx) < 2:
            return self._trivial_weighted(items, weights, idx)
        return self._decide_choice(items, weights, idx, uniform)

    def perturb(self, n: float) -> float:
        if self._depth or n <= 0:
            return RNG.perturb(self, n)
        bound = RNG.perturb_bound(n)
        if bound <= 1:
            return self._trivial_perturb(n)
        return self._decide_perturb(n, bound)

    def composite_choice(self, label: str, build: Callable[[], tuple], pick: Callable[[], Any]) -> Any:
        if self._depth:
            return pick()
        options, weights, stamps = build()
        idx, uniform = live_indices(weights)
        if len(idx) < 2:
            return self._trivial_composite(options, idx, pick)
        return self._decide_composite(label, options, weights, stamps, idx, uniform, pick)

    def _plain(self, pick: Callable[[], Any]) -> Any:
        self._depth += 1
        try:
            return pick()
        finally:
            self._depth -= 1

    # -- trivial decisions: fixed by their inputs, never recorded ----------------
    # A tracing generator still draws, so it stays draw-for-draw an ``RNG``; a
    # replaying one computes the fixed result and consumes nothing.

    def _trivial_int(self, n: int) -> int:
        return RNG.randint(self, n)

    def _trivial_pick(self, items: Sequence[Any]) -> Any:
        return self._real(RNG.pick, items)

    def _trivial_weighted(self, items: Sequence[Any], weights: Sequence[float],
                          idx: list[int]) -> Any:
        return self._real(RNG.weighted_pick, items, weights)

    def _trivial_perturb(self, n: float) -> float:
        return self._real(RNG.perturb, n)

    def _trivial_composite(self, options: list, idx: list[int],
                           pick: Callable[[], Any]) -> Any:
        return self._plain(pick)

    # -- subclass hooks --------------------------------------------------------

    def _decide_random(self) -> float:
        raise NotImplementedError

    def _decide_int(self, n: int) -> int:
        raise NotImplementedError

    def _decide_prob(self, p: float) -> bool:
        raise NotImplementedError

    def _decide_choice(self, items: Sequence[Any], weights: Sequence[float] | None,
                       idx: list[int], uniform: bool) -> Any:
        raise NotImplementedError

    def _decide_perturb(self, n: float, bound: int) -> float:
        raise NotImplementedError

    def _decide_composite(self, label: str, options: list, weights: list, stamps: list,
                          idx: list[int], uniform: bool, pick: Callable[[], Any]) -> Any:
        raise NotImplementedError


def option_name(x: Any) -> str:
    """Name of one option of a choice.

    Two codelet bodies pass tuples that carry more than the thing chosen, where
    Metacat's option is just the thing: the bridge scouts' ``('top', type, s1, s2)``
    is Metacat's ``top``, and the thematic scout's ``(weight, object, conditions)`` is
    Metacat's ``stochastic-select`` entry, named after its second element.
    """
    if isinstance(x, tuple):
        if len(x) == 4 and x[0] in ("top", "vertical", "bottom") and isinstance(x[0], str):
            return x[0]
        if len(x) == 3 and isinstance(x[0], (int, float)) and not isinstance(x[0], bool):
            return name_of(x[1])
    return name_of(x)


def live_indices(weights: Sequence[float]) -> tuple[list[int], bool]:
    """Indices of options that can be picked (§7.1) and whether the pick is uniform.

    Zero (or negative) weights are dropped; if every weight is zero the choice is
    uniform over all of them, as both engines' fallbacks make it.
    """
    idx = [i for i, w in enumerate(weights) if w > 0]
    if idx:
        return idx, False
    return list(range(len(weights))), True


def choice_fields(items: Sequence[Any], weights: Sequence[float] | None, idx: list[int],
                  uniform: bool) -> dict[str, Any]:
    """``options`` (and ``weights`` unless uniform) of a choice record."""
    fields: dict[str, Any] = {"options": [option_name(items[i]) for i in idx]}
    if not uniform and weights is not None:
        fields["weights"] = [float(weights[i]) for i in idx]
    return fields


class TracingRNG(LockstepBase):
    """Draws exactly as ``RNG`` does and writes a record for each real decision."""

    def _decide_random(self) -> float:
        r = RNG.random(self)
        self._emit("random", {"result": r})
        return r

    def _decide_int(self, n: int) -> int:
        r = self._real(RNG.randint, n)
        self._emit("int", {"bound": n, "result": r})
        return r

    def _decide_prob(self, p: float) -> bool:
        r = self._real(RNG.prob, p)
        self._emit("prob", {"p": float(p), "result": bool(r)})
        return r

    def _decide_choice(self, items, weights, idx, uniform):
        if weights is None:
            r = self._real(RNG.pick, items)
        else:
            r = self._real(RNG.weighted_pick, items, weights)
        fields = choice_fields(items, weights, idx, uniform)
        fields["picked"] = option_name(r)
        self._emit("choice", fields)
        return r

    def _decide_perturb(self, n, bound):
        r = self._real(RNG.perturb, n)
        self._emit("perturb", {"value": _num(n), "bound": bound, "integer": True,
                               "result": _num(r)})
        return r

    def _decide_composite(self, label, options, weights, stamps, idx, uniform, pick):
        r = self._plain(pick)
        fields = choice_fields(options, weights, idx, uniform)
        fields["stamps"] = [stamps[i] for i in idx]
        fields["picked"] = name_of(r)
        fields["picked_stamp"] = r.time_stamp
        fields["picked_weight"] = picked_weight(options, weights, r)
        fields["picked_urgency"] = float(r.urgency)
        fields["picked_original_urgency"] = float(r.original_urgency)
        self._emit("choice", fields, site=label if label == "choose" else f"{label}@{caller_site()}")
        return r


def picked_weight(options, weights, chosen) -> float | None:
    """The chosen codelet's own weight.  Name and stamp do not always identify a
    codelet -- a clamp restamps the codelets it moves to another bin, so a moved one
    and one posted in the same cycle can share both -- and replay uses the weight to
    tell them apart."""
    if weights is None:
        return None
    for option, weight in zip(options, weights):
        if option is chosen:
            return float(weight)
    return None


def _num(x: float | int) -> float:
    """Numbers are written as floats, as Metacat's ``exact->inexact`` does (spec §3)."""
    return float(x)
