"""No layer but the three that build structures directly gets a run bound around its tests.

``tests/conftest.py`` binds an ambient run (the standard configuration, a fresh allocator) for
``unit``, ``seed_unit`` and ``module`` tests, which construct bonds, bridges and trace events
without an engine around them.  If the same fixture also wrapped ``e2e``, ``parallel``,
``lockstep`` or ``integration``, a real server path that forgot to open its run's scope would
find the fixture's run and pass, then raise ``NoRunBound`` in production.  So those layers run
with nothing bound, and this holds the fixture to that.
"""

from __future__ import annotations

import contextvars

import pytest

from tests.conftest import AMBIENT_RUN_LAYERS, LAYERS, _layer_of


def test_only_the_layers_that_build_structures_directly_have_an_ambient_run():
    assert AMBIENT_RUN_LAYERS == ("unit", "seed_unit", "module")
    assert set(AMBIENT_RUN_LAYERS) <= set(LAYERS)
    for layer in ("e2e", "parallel", "lockstep", "integration", "architecture"):
        assert layer not in AMBIENT_RUN_LAYERS


def test_a_test_outside_those_layers_finds_no_run_bound(request):
    from server.engine.run_binding import NoRunBound, current

    assert _layer_of(request.node.nodeid) == "integration"
    with pytest.raises(NoRunBound):
        current()


def test_the_e2e_guard_exists():
    """The e2e layer's own check (``tests/e2e/test_two_runs_over_http.py``) is where the
    fixture would be seen to leak into an async test; keep it from being deleted quietly."""
    import inspect

    from tests.e2e import test_two_runs_over_http as e2e

    assert "no_run_is_bound_around_an_e2e_test" in "".join(
        name for name, _ in inspect.getmembers(e2e, inspect.iscoroutinefunction)
    )
