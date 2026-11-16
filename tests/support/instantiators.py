"""Helpers for tests that run an instantiator codelet by hand, outside a run's own loop."""

from __future__ import annotations

from server.engine.coderack import Codelet
from server.engine.runner import EngineRunner

INSTANTIATORS = ("adjacent-instantiator", "category-instantiator", "instance-of-instantiator")


def on_rack(runner: EngineRunner, *types: str) -> list[Codelet]:
    """The codelets of the named types (any instantiator by default) on the Coderack, in the order they were posted."""
    wanted = types or INSTANTIATORS
    found = [c for b in runner.ctx.coderack.bins for c in b.codelets if c.codelet_type in wanted]
    return sorted(found, key=lambda c: c.id)


def run_instantiators(runner: EngineRunner, *types: str) -> list[Codelet]:
    """Take every instantiator off the Coderack, in the order posted, and run it (as the run's loop would
    when it chose them).  Returns the codelets run."""
    ran = on_rack(runner, *types)
    rack = runner.ctx.coderack
    for codelet in ran:
        bin_ = rack._bin_of(codelet)
        bin_.remove(codelet)
        rack._total_count -= 1
        runner._execute_codelet(codelet)
    return ran
