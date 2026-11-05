"""A person's actions during a Metacat Mode run, applied the way the product applies them.

Metacat's Clamp Themes dialog clamps a theme pattern (``gui.ss:905-926``), its Options menu
clamps a codelet pattern (``gui.ss:1221-1245``), its Control menu undoes the last clamp
(``gui.ss:595-597``) and its "Self-watching mode" check item switches Self-watching on and off in
mid-run (``gui.ss:607-626``).  Petacat offers the same four through
``RunService.clamp_theme_pattern``, ``RunService.clamp_codelet_pattern``,
``RunService.undo_last_clamp`` and ``RunService.set_self_watching``.  This module calls
those very methods, bare, on a stand-in service that holds one runner, so a test applies the code
the API runs and not a copy of it.  The class opens the run's scope around each of them
(``run_service._in_run_scope``).

An intervention is ``{"at": N, "op": "clamp_codelet_pattern", "pattern": "bottom_up"}`` or
``{"at": N, "op": "undo_last_clamp"}`` or ``{"at": N, "op": "set_self_watching", "enabled": false}``: it happens when the run has completed N codelets, before
the next one starts (Metacat: the break at ``*break-time*`` N).  ``schedule`` wraps the runner's
``step_mcat`` so the engine's own ``run_mcat`` loop drives the run unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

PATTERNS = ("top_down", "bottom_up", "group", "bridge", "rule")
OPS = ("clamp_codelet_pattern", "undo_last_clamp", "set_self_watching", "clamp_theme_pattern")


def apply(runner: Any, intervention: dict[str, Any]) -> None:
    """Apply one intervention by calling the product's own ``RunService`` method, bare.

    ``RunService`` opens the run's scope (``EngineContext.scope()``) around every method that
    names a live run, so an event number a clamp takes is the run's own and does not depend on
    what else ran in the process.
    """
    from server.services.run_service import RunService

    service = RunService.__new__(RunService)
    service._runners = {0: runner}
    service._store = SimpleNamespace(current=lambda: runner.meta)
    op = intervention["op"]
    if op == "clamp_codelet_pattern":
        service.clamp_codelet_pattern(0, intervention["pattern"])
    elif op == "undo_last_clamp":
        service.undo_last_clamp(0)
    elif op == "clamp_theme_pattern":
        # one pattern per theme type, in the order the types first appear
        patterns: dict[str, list[dict[str, Any]]] = {}
        for theme in intervention["themes"]:
            patterns.setdefault(theme["type"], []).append(
                {k: theme[k] for k in ("dimension", "relation", "activation")})
        service.clamp_theme_pattern(0, [{"type": t, "themes": ts} for t, ts in patterns.items()])
    elif op == "set_self_watching":
        service.set_self_watching(0, bool(intervention["enabled"]))
    else:
        raise ValueError(f"unknown intervention {op!r}")


def schedule(runner: Any, interventions: list[dict[str, Any]] | None) -> None:
    """Apply each intervention when ``runner`` has completed its ``at`` codelets."""
    if not interventions:
        return
    pending = sorted(interventions, key=lambda iv: iv["at"])
    real_step = runner.step_mcat

    def step_with_interventions() -> Any:
        while pending and runner.ctx.codelet_count >= pending[0]["at"]:
            apply(runner, pending.pop(0))
        return real_step()

    runner.step_mcat = step_with_interventions  # type: ignore[method-assign]
