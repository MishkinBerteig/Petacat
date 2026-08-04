"""Deliberate staleness — a serial probe for the central risk of the parallel work.

Free-running execution (WP4.4) lets codelets run without a global barrier, so a
codelet decides on a Workspace that has moved on by the time it commits.  How much
of that cognition tolerates is the question the concurrency work turns on, and it is
much cheaper to answer *before* writing the concurrency than to discover afterwards
that the answer is "none".

So this module answers it serially.  One codelet runs at a time, in the ordinary
loop, but each reads the Workspace as it stood ``staleness_delay`` codelets ago.  No
threads, no locks, no scheduler changes — and the expected-range oracle (WP0.1) then
says at what delay the set of reachable stopping states starts to move.  That N is an
upper bound on the staleness free-running can afford.

What is made stale
------------------
The snapshot covers what a codelet *enumerates and selects over*:

- which objects exist in each string, and in the Workspace as a whole;
- which bonds, groups, bridges and rules are **built** — built-ness is captured, not
  read live, so a structure that has since been built is invisible and one since
  broken is still visible;
- the salience and importance values object choice is weighted by.

What is left live, and why
--------------------------
Slipnet activations, Themespace activations and temperature are not delayed.  They
are recomputed once per update cycle — every 15 codelets — so at the delays of
interest they are already coarser-grained than the structural state, and they are a
shared numeric substrate rather than something individual codelets race on.  A
codelet's own writes are also not delayed: it proposes and builds against live state.
The model is therefore "reads lag writes", which is the shape staleness takes under
free-running, rather than a full multi-version workspace.

This is a measuring instrument, not a semantic change.  With ``staleness_delay`` at
its default of 0 nothing here runs and the engine behaves exactly as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.engine.runner import EngineContext


class StaleView:
    """The Workspace as it stood at one particular codelet count.

    Structures are held as plain tuples of the objects themselves, already filtered
    to the built ones.  Holding the objects rather than copies is deliberate: the
    question is which structures a codelet can *see*, not what their fields contained,
    and copying the graph every codelet would cost more than the experiment is worth.
    The one exception is the object weights, which are copied, because object choice
    is weighted by salience and salience moves every update cycle.
    """

    __slots__ = (
        "codelet_count",
        "all_objects",
        "by_string",
        "top_bridges",
        "bottom_bridges",
        "vertical_bridges",
        "top_rules",
        "bottom_rules",
        "object_weights",
    )

    def __init__(self, ctx: EngineContext) -> None:
        ws = ctx.workspace
        self.codelet_count = ctx.codelet_count
        self.all_objects = tuple(ws.all_objects)
        self.by_string = {
            id(s): (
                tuple(s.objects),
                tuple(b for b in s.bonds if b.is_built),
                tuple(g for g in s.groups if g.is_built),
            )
            for s in ws.all_strings
        }
        self.top_bridges = tuple(b for b in ws.top_bridges if b.is_built)
        self.bottom_bridges = tuple(b for b in ws.bottom_bridges if b.is_built)
        self.vertical_bridges = tuple(b for b in ws.vertical_bridges if b.is_built)
        self.top_rules = tuple(r for r in ws.top_rules if r.is_built)
        self.bottom_rules = tuple(r for r in ws.bottom_rules if r.is_built)
        self.object_weights = {
            id(o): (
                getattr(o, "relative_importance", 0.0),
                dict(getattr(o, "salience", {}) or {}),
            )
            for o in self.all_objects
        }

    # -- Queries mirroring the live Workspace API ------------------------

    def string_objects(self, string: Any) -> tuple:
        entry = self.by_string.get(id(string))
        return entry[0] if entry else ()

    def string_bonds(self, string: Any) -> tuple:
        entry = self.by_string.get(id(string))
        return entry[1] if entry else ()

    def string_groups(self, string: Any) -> tuple:
        entry = self.by_string.get(id(string))
        return entry[2] if entry else ()

    def bridges(self, bridge_type: str) -> tuple:
        return {
            "top": self.top_bridges,
            "bottom": self.bottom_bridges,
            "vertical": self.vertical_bridges,
        }.get(bridge_type, ())

    def object_weight(self, obj: Any, weight_key: str) -> float:
        """The weight ``obj`` carried when this view was captured.

        Mirrors ``workspace._object_weight``: *weight_key* names either a numeric
        attribute or an entry in the object's ``salience`` dict, with no floor
        (``utilities.ss:443-448``).  Objects that postdate the view have no
        recorded weight; they cannot be reached through it, so the fallback is
        only a guard.
        """
        entry = self.object_weights.get(id(obj))
        if entry is None:
            return 1.0
        relative_importance, salience = entry
        if weight_key == "relative_importance":
            return relative_importance
        return salience.get(weight_key, 1.0)

    def __repr__(self) -> str:
        return f"StaleView(at_codelet={self.codelet_count}, objects={len(self.all_objects)})"


def current_view(ctx: EngineContext) -> StaleView | None:
    """The view codelets should read from, or ``None`` when running live.

    ``None`` is the answer both when staleness is switched off and during the
    warm-up before enough history exists, so every caller's fallback is the ordinary
    live path and the default configuration executes no extra branch of substance.
    """
    if not getattr(ctx, "staleness_delay", 0):
        return None
    history = ctx.view_history
    return history[0] if history else None
