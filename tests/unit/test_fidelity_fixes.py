"""Fidelity fixes of stage F: each was a divergence from Metacat found by the extended golden.

* A rule's degree of support is an exact product (``rules.ss:237-242``).
* Self-watching mode off means ``add-theme`` adds nothing unless a past episode is on display
  (``themes.ss:374-375``), and the justify clamps ask ``permission-to-clamp?`` with the real flag (``trace.ss:116``).
"""

from __future__ import annotations

import pytest

from server.engine import rules as rules_module
from server.engine.memory import EpisodicMemory
from server.engine.numeric.backend import use_backend
from server.engine.rng import RNG
from server.engine.rules import Rule
from server.engine.runner import EngineRunner
from server.engine.themes import Themespace
from server.engine.trace import TemporalTrace
from tests.support import golden_baseline as gb

pytestmark = pytest.mark.numeric_matrix


class _Bridge:
    def __init__(self, strength):
        self.strength = strength


def _degree(monkeypatch, *strengths) -> int:
    rule = Rule.__new__(Rule)
    rule.supporting_bridges = [_Bridge(s) for s in strengths]
    monkeypatch.setattr(rules_module, "_get_equivalent_bridge", lambda workspace, b: b)
    return rule.get_degree_of_support(None)


def test_degree_of_support_rounds_an_exact_product_half_to_even(monkeypatch) -> None:
    """``ly -> yl; cbaii`` seed 1, codelet 339: bridges of strength 75 and 74.  Metacat's
    ``(% 75)`` and ``(% 74)`` are exact rationals, the product is exactly 111/200 and ``100*``
    rounds 111/2 to 56.  The float product ``0.75 * 0.74 * 100`` is 55.49999999999999."""
    assert _degree(monkeypatch, 75, 74) == 56
    assert _degree(monkeypatch, 85) == 85
    assert _degree(monkeypatch) == 100  # no supporting bridge: the empty product is 1


def test_a_themespace_adds_no_theme_while_self_watching_is_off() -> None:
    meta = gb.load_meta()
    themespace = Themespace(meta)
    dimension = themespace.clusters[0].dimension
    assert themespace.add_theme("top_bridge", dimension, "identity", True) is not None
    themespace.self_watching_enabled = False
    assert themespace.add_theme("top_bridge", dimension, "identity", True) is None  # even the existing one
    assert themespace.add_theme("vertical_bridge", dimension, "identity", False) is None
    themespace.self_watching_enabled = True
    assert themespace.add_theme("top_bridge", dimension, "identity", True) is not None


def test_a_past_pattern_is_shown_with_self_watching_off_and_goes_when_the_display_ends() -> None:
    """``add-theme`` refuses only outside display mode (``themes.ss:374``), so an event's pattern
    still shows while Self-watching mode is off.  Restoring leaves display mode first
    (``restore-current-state`` redraws the Workspace, which clears ``*display-mode?*``), so a
    theme saved before Self-watching was switched off does not come back."""
    meta = gb.load_meta()
    themespace = Themespace(meta)
    dimension = themespace.clusters[0].dimension
    themespace.set_theme_activation("top_bridge", dimension, "identity", 100.0)
    themespace.self_watching_enabled = False

    themespace.save_current_state()
    themespace.delete_everything()
    themespace.set_theme_activation("vertical_bridge", dimension, "identity", 100.0)
    assert themespace.get_theme("vertical_bridge", dimension, "identity") is not None

    assert themespace.restore_current_state()
    assert not themespace.displaying_past_state
    assert themespace.all_themes == []
    assert themespace.add_theme("top_bridge", dimension, "identity", True) is None


def test_the_context_keeps_the_themespace_in_step_with_self_watching() -> None:
    meta = gb.load_meta()
    runner = EngineRunner(meta)
    with use_backend("off"):
        runner.init_mcat("abc", "abd", "xyz", seed=1, memory=EpisodicMemory(), rng=RNG(1),
                         parameters={"self_watching_enabled_default": False})
        assert runner.ctx.self_watching_enabled is False
        assert runner.ctx.themespace.self_watching_enabled is False
        runner.run_mcat(max_steps=400)
    assert runner.ctx.themespace.all_themes == []  # nothing maintains the Themespace
    runner.ctx.self_watching_enabled = True
    assert runner.ctx.themespace.self_watching_enabled is True


def test_permission_to_clamp_has_no_default_for_self_watching() -> None:
    trace = TemporalTrace()
    with pytest.raises(TypeError):
        trace.permission_to_clamp(codelet_count=10, grace_period=100)  # type: ignore[call-arg]
    assert trace.permission_to_clamp(False, codelet_count=10, grace_period=100) is False
    assert trace.permission_to_clamp(True, codelet_count=10, grace_period=100) is True


def test_an_unavailable_backend_says_why(monkeypatch) -> None:
    """The MLX probe swallowed whatever it raised and answered "not available"; a swarm worker whose
    Metal start-up failed then reported only that.  The reason is kept and named."""
    from server.engine.numeric import backend

    class Never:
        @classmethod
        def is_available(cls) -> bool:
            return False

    monkeypatch.setattr(backend, "_classes", lambda: {"never": Never})
    monkeypatch.setitem(backend.UNAVAILABLE_REASONS, "never", "the Metal probe raised RuntimeError('boom')")
    with pytest.raises(backend.BackendUnavailable, match=r"not available \(the Metal probe raised RuntimeError\('boom'\)\)"):
        backend.get_backend("never")
    monkeypatch.delitem(backend.UNAVAILABLE_REASONS, "never")
    with pytest.raises(backend.BackendUnavailable, match="not available;"):
        backend.get_backend("never")
