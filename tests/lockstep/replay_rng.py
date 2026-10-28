"""The replay RNG (spec §6.4, §7.2): Petacat's draws, answered from a Metacat trace.

Every non-trivial call is *paired* with a record of the same kind in the same unit
(content first, then ``about``, then the earliest unused one), and gets Metacat's
result back.  A call with nothing to pair with is surplus and is answered by a fallback
generator seeded by (seed, unit, n), so a replay stays deterministic.  The Petacat trace
this writes is in the same format as Metacat's, with a ``pair`` field on each decision:
the index (among the Metacat trace's ``decision`` records) it was paired with, or
``null`` when surplus.  The comparer never re-pairs; ``pair`` is its authority.

Fatal failures stop the run (``ReplayStop``): ``unit`` (a unit starts out of order, or
Petacat runs past Metacat's end) and ``missing-pick`` (Metacat picked something Petacat
did not offer).  The caller writes the ``fatal`` and ``end`` records.

Guard 1: the underlying ``random.Random`` raises if anything calls it directly, so a
draw that bypasses this class cannot go unnoticed.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from server.engine.rng import RNG
from tests.lockstep.context import ReplayStop
from tests.lockstep.tracing_rng import (
    picked_scope,
    picked_weight,
    LockstepBase, caller_site, choice_fields, name_of, option_name,
)
from tests.lockstep.trace_io import TraceWriter, read_records


class BypassedReplay(AssertionError):
    """Something drew from the replay RNG's underlying generator directly."""


class _ForbiddenRandom:
    """Stands in for ``random.Random``; every use is a Guard 1 failure."""

    def __getattr__(self, name: str) -> Any:
        raise BypassedReplay(
            f"random.Random.{name} was reached directly; every draw must go through "
            "the replay RNG's helpers"
        )


def unit_key(record: dict[str, Any]) -> tuple:
    """The unit a record belongs to (spec §7.2)."""
    if record["ctx"] == "update":
        return ("update", record.get("u"), record["who"])
    return (record["c"], record["ctx"], record["who"])


class MetacatTrace:
    """A reference trace, indexed by unit."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.header: dict[str, Any] = {}
        self.end: dict[str, Any] | None = None
        self.decisions: list[dict[str, Any]] = []
        for rec in read_records(self.path):
            t = rec.get("t")
            if t == "header":
                self.header = rec
            elif t == "decision":
                self.decisions.append(rec)
            elif t == "end":
                self.end = rec
        self.units: dict[tuple, list[int]] = {}
        self.order: dict[tuple, int] = {}
        for i, rec in enumerate(self.decisions):
            key = unit_key(rec)
            self.units.setdefault(key, []).append(i)
            self.order.setdefault(key, len(self.order))
        self._counters: dict[int, Counter] = {}

    def option_counter(self, i: int) -> Counter:
        c = self._counters.get(i)
        if c is None:
            c = self._counters[i] = Counter(self.decisions[i].get("options", ()))
        return c


def close(a: float, b: float, rel: float = 1e-9, abs_: float = 1e-12) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


class ReplayRNG(LockstepBase):
    def __init__(
        self,
        seed: int,
        trace: MetacatTrace,
        writer: TraceWriter | None = None,
        complemented_sites: Iterable[str] = (),
        rel_tol: float = 1e-9,
        abs_tol: float = 1e-12,
    ) -> None:
        super().__init__(seed, writer)
        self._rng = _ForbiddenRandom()  # Guard 1
        self.trace = trace
        self.complemented_sites = set(complemented_sites)
        self.rel_tol, self.abs_tol = rel_tol, abs_tol
        self.used: set[int] = set()
        self.started: set[tuple] = set()
        self.high = -1
        self.paired = 0
        self.surplus = 0

    # -- state (the base class would touch the forbidden generator) -------------

    def get_state(self) -> tuple:
        return (self._seed, self._call_count, None)

    def set_state(self, state: tuple) -> None:
        self._seed, self._call_count, _ = state

    # -- trivial decisions: the fixed result, no draw, no record -----------------

    def _trivial_int(self, n: int) -> int:
        return 0

    def _trivial_pick(self, items: Sequence[Any]) -> Any:
        if not items:
            raise ValueError("Cannot pick from empty sequence")
        return items[0]

    def _trivial_weighted(self, items, weights, idx):
        return items[idx[0]]

    def _trivial_perturb(self, n: float) -> float:
        return n

    def _trivial_composite(self, options, idx, pick):
        if not options:
            return pick()
        return options[idx[0]]

    # -- unit checks and pairing -------------------------------------------------

    def _enter_unit(self) -> tuple:
        key = self.tc.unit_key()
        if key in self.started:
            return key
        self.started.add(key)
        end = self.trace.end
        if end is not None and self.tc.c > end.get("c", self.tc.c):
            raise ReplayStop(
                "unit",
                f"Petacat reached codelet {self.tc.c}, past Metacat's end at "
                f"{end.get('c')} ({end.get('reason')})",
            )
        pos = self.trace.order.get(key)
        if pos is not None:
            if pos < self.high:
                raise ReplayStop(
                    "unit",
                    f"unit {key} starts after a later Metacat unit "
                    f"(position {pos}, already at {self.high})",
                )
            self.high = pos
        return key

    def _about_name(self) -> str | None:
        a = self.tc.about
        if a is None:
            return None
        return a if isinstance(a, str) else name_of(a)

    def _pair(self, kind: str, key: tuple, content: Callable[[int, dict], bool]) -> int | None:
        """Index of the Metacat record to pair with: same about and content, then
        content, then about, then the earliest unused one of the right kind."""
        about = self._about_name()
        best: tuple[int, int] | None = None
        decisions = self.trace.decisions
        for i in self.trace.units.get(key, ()):
            if i in self.used:
                continue
            rec = decisions[i]
            if rec["kind"] != kind:
                continue
            same_content = content(i, rec)
            same_about = rec.get("about") == about
            rank = 0 if (same_content and same_about) else 1 if same_content else \
                2 if same_about else 3
            if rank == 0:
                best = (0, i)
                break
            if best is None or rank < best[0]:
                best = (rank, i)
        if best is None:
            return None
        self.used.add(best[1])
        return best[1]

    def _fallback(self) -> RNG:
        """The generator surplus calls draw from: seeded by (seed, unit, n)."""
        tc = self.tc
        material = f"{self.seed}|{tc.unit_key()}|{tc.n}".encode()
        return RNG(int.from_bytes(hashlib.sha256(material).digest()[:8], "big"))

    def _finish(self, kind: str, fields: dict[str, Any], pair: int | None,
                site: str | None = None) -> dict:
        self._call_count += 1
        rec = self._record(kind, fields, site)
        rec["pair"] = pair
        self.write(rec)
        if pair is None:
            self.surplus += 1
        else:
            self.paired += 1
        return rec

    # -- decisions ---------------------------------------------------------------

    def _decide_random(self) -> float:
        key = self._enter_unit()
        pair = self._pair("random", key, lambda i, r: True)
        if pair is None:
            result = self._fallback().random()
        else:
            result = float(self.trace.decisions[pair]["result"])
        self._finish("random", {"result": result}, pair)
        return result

    def _decide_int(self, n: int) -> int:
        key = self._enter_unit()
        pair = self._pair("int", key, lambda i, r: r.get("bound") == n)
        if pair is None:
            result = self._fallback().randint(n)
        else:
            result = int(self.trace.decisions[pair]["result"])
        self._finish("int", {"bound": n, "result": result}, pair)
        return result

    def _decide_prob(self, p: float) -> bool:
        key = self._enter_unit()
        site = caller_site()

        def content(i: int, r: dict) -> bool:
            q = r.get("p")
            return q is not None and (close(q, p, self.rel_tol, self.abs_tol)
                                      or close(q, 1.0 - p, self.rel_tol, self.abs_tol))

        pair = self._pair("prob", key, content)
        if pair is None:
            result = self._fallback().prob(p)
        else:
            rec = self.trace.decisions[pair]
            result = bool(rec["result"])
            q = rec.get("p")
            matches = q is not None and close(q, p, self.rel_tol, self.abs_tol)
            # A complemented site tests the other half of the same coin (§7.4); an
            # unregistered one whose p matches only 1 - p is flipped the same way and
            # reported by the comparer as "complemented?".
            if site in self.complemented_sites or (
                q is not None and not matches
                and close(q, 1.0 - p, self.rel_tol, self.abs_tol)
            ):
                result = not result
        self._finish("prob", {"p": float(p), "result": result}, pair, site)
        return result

    def _decide_perturb(self, n: float, bound: int) -> float:
        key = self._enter_unit()

        def content(i: int, r: dict) -> bool:
            return (r.get("bound") == bound and r.get("value") is not None
                    and close(r["value"], n, self.rel_tol, self.abs_tol))

        pair = self._pair("perturb", key, content)
        if pair is None:
            result = self._fallback().perturb(n)
        else:
            result = self.trace.decisions[pair]["result"]
            if isinstance(n, int) and float(result).is_integer():
                result = int(result)
        self._finish("perturb", {"value": float(n), "bound": bound, "integer": True,
                                 "result": float(result)}, pair)
        return result

    def _decide_choice(self, items: Sequence[Any], weights, idx: list[int],
                       uniform: bool) -> Any:
        key = self._enter_unit()
        fields = choice_fields(items, weights, idx, uniform)
        names = fields["options"]
        want = Counter(names)
        pair = self._pair("choice", key,
                          lambda i, r: self.trace.option_counter(i) == want)
        if pair is None:
            fb = self._fallback()
            picked = (fb.pick([items[i] for i in idx]) if weights is None or uniform
                      else fb.weighted_pick([items[i] for i in idx],
                                            [weights[i] for i in idx]))
            fields["picked"] = option_name(picked)
            self._finish("choice", fields, None)
            return picked
        target = self.trace.decisions[pair].get("picked")
        found = [k for k, nm in enumerate(names) if nm == target]
        if not found:
            fields["picked"] = None
            self._finish("choice", fields, pair)
            raise ReplayStop(
                "missing-pick",
                f"Metacat picked {target!r}; Petacat offered {names[:12]}"
                f"{'...' if len(names) > 12 else ''}",
            )
        fields["picked"] = target
        self._finish("choice", fields, pair)
        return items[idx[found[0]]]

    def _decide_composite(self, label, options, weights, stamps, idx, uniform, pick):
        key = self._enter_unit()
        fields = choice_fields(options, weights, idx, uniform)
        names = fields["options"]
        fields["stamps"] = [stamps[i] for i in idx]
        want = Counter(names)
        site = label if label == "choose" else f"{label}@{caller_site()}"
        pair = self._pair("choice", key,
                          lambda i, r: self.trace.option_counter(i) == want)
        if pair is None:
            fb = self._fallback()
            live = [options[i] for i in idx]
            chosen = fb.pick(live) if uniform else fb.weighted_pick(
                live, [weights[i] for i in idx])
            fields["picked"] = name_of(chosen)
            fields["picked_stamp"] = chosen.time_stamp
            fields["picked_weight"] = picked_weight(options, weights, chosen)
            fields["picked_urgency"] = float(chosen.urgency)
            fields["picked_original_urgency"] = float(chosen.original_urgency)
            if picked_scope(chosen) is not None:
                fields["picked_scope"] = picked_scope(chosen)
            self._finish("choice", fields, None, site)
            return chosen
        rec = self.trace.decisions[pair]
        target = rec.get("picked")
        found = [k for k, nm in enumerate(names) if nm == target]
        if not found:
            fields["picked"] = None
            fields["picked_stamp"] = None
            self._finish("choice", fields, pair, site)
            raise ReplayStop(
                "missing-pick",
                f"Metacat chose {target!r} (stamp {rec.get('picked_stamp')}); "
                f"it is not on Petacat's coderack",
            )
        stamp = rec.get("picked_stamp")
        exact = [k for k in found if fields["stamps"][k] == stamp]
        candidates = exact or found
        # Among same-name, same-stamp codelets prefer the one whose share of the
        # total weight is closest to the share of the codelet Metacat picked: a
        # clamp restamps the codelets it moves to another bin, so name and stamp
        # alone can match codelets in two different bins.
        # An unclamp restores each codelet's original urgency, so two codelets
        # alike in name, stamp and bin can still differ there: match both
        # urgencies first.
        target_weight = rec.get("picked_weight")
        if len(candidates) > 1 and "picked_scope" in rec:
            same = [j for j in candidates
                    if picked_scope(options[idx[j]]) == rec["picked_scope"]]
            candidates = same or candidates
        if len(candidates) > 1 and "picked_urgency" in rec:
            want = (rec["picked_urgency"], rec.get("picked_original_urgency"))
            same = [j for j in candidates
                    if _close(options[idx[j]].urgency, want[0])
                    and (want[1] is None
                         or _close(options[idx[j]].original_urgency, want[1]))]
            candidates = same or candidates
        # Same name, stamp and urgency can still be two proposals of one structure
        # made at different times (e.g. two bridge-evaluators for the same bridge
        # name); Metacat logs the picked proposal's own time stamp.
        if len(candidates) > 1 and "picked_arg_stamp" in rec:
            same = [j for j in candidates
                    if getattr((options[idx[j]].arguments or {}).get("structure"),
                               "time_stamp", None) == rec["picked_arg_stamp"]]
            candidates = same or candidates
        if len(candidates) > 1 and target_weight is not None and weights is not None \
                and rec.get("weights"):
            want_share = target_weight / sum(rec["weights"])
            total = sum(weights[i] for i in idx)
            candidates = sorted(
                candidates,
                key=lambda j: abs(weights[idx[j]] / total - want_share),
            )
        k = candidates[0] if exact else min(candidates, key=lambda j: fields["stamps"][j])
        chosen = options[idx[k]]
        fields["picked"] = target
        fields["picked_stamp"] = chosen.time_stamp
        fields["picked_weight"] = None if weights is None else float(weights[idx[k]])
        fields["picked_urgency"] = float(chosen.urgency)
        fields["picked_original_urgency"] = float(chosen.original_urgency)
        if picked_scope(chosen) is not None:
            fields["picked_scope"] = picked_scope(chosen)
        self._finish("choice", fields, pair, site)
        return chosen

    # -- summary -----------------------------------------------------------------

    def summary(self) -> dict[str, int]:
        return {
            "decisions": self.decisions,
            "paired": self.paired,
            "surplus": self.surplus,
            "metacat_records": len(self.trace.decisions),
            "metacat_unpaired": len(self.trace.decisions) - len(self.used),
        }


def _close(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(b)))
