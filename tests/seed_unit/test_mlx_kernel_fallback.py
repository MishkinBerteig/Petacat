"""The fused Metal kernel builds its library on first use; when macOS's compiler service is unreachable
(``Unable to reach MTLCompilerService``, seen under load) the update must not fail the run: the session
redoes that update with the composed MLX operations, which compute the same result, and says so once."""

from __future__ import annotations

import logging

import pytest

from server.engine.numeric import metal_kernels
from server.engine.numeric.backend import available_backends, get_backend
from server.engine.numeric.layout import SlipnetState, SlipnetTopology
from tests.seed_unit.test_numeric_backends import meta, real_slipnet  # noqa: F401 - the fixtures

pytestmark = pytest.mark.skipif("mlx" not in available_backends(), reason="the MLX GPU backend is not available here")


def _run(session, state, steps=3):
    session.load(state)
    for _ in range(steps):
        session.update(50.0, 1.0)
    return session.store().activation


def test_an_unreachable_compiler_service_falls_back_to_the_composed_update(real_slipnet, monkeypatch, caplog):  # noqa: F811
    topology = SlipnetTopology.from_slipnet(real_slipnet)
    state = SlipnetState.from_slipnet(real_slipnet)
    expected = _run(get_backend("mlx-cpu").open_slipnet(topology), state)  # composed, never the kernel

    def broken():
        raise RuntimeError("[metal::Device] Unable to build metal library from source\n"
                           "Unable to reach MTLCompilerService.")

    monkeypatch.setattr(metal_kernels, "slipnet_update_kernel", broken)
    monkeypatch.setattr(metal_kernels, "_DISABLED", [])
    with caplog.at_level(logging.WARNING):
        session = get_backend("mlx").open_slipnet(topology)
        assert session.use_kernel
        got = _run(session, state)
    assert got == expected
    assert not session.use_kernel and "MTLCompilerService" in metal_kernels.disabled_reason()
    assert sum("fused Metal kernel is unavailable" in r.message for r in caplog.records) == 1
    # a session opened afterwards does not try the kernel again
    assert not get_backend("mlx").open_slipnet(topology).use_kernel


def test_any_other_kernel_error_is_a_fault_and_is_not_hidden(real_slipnet, monkeypatch):  # noqa: F811 - the fixture
    topology = SlipnetTopology.from_slipnet(real_slipnet)
    state = SlipnetState.from_slipnet(real_slipnet)

    def broken():
        raise RuntimeError("[METAL] Command buffer execution failed: Internal Error")

    monkeypatch.setattr(metal_kernels, "slipnet_update_kernel", broken)
    monkeypatch.setattr(metal_kernels, "_DISABLED", [])
    session = get_backend("mlx").open_slipnet(topology)
    with pytest.raises(RuntimeError, match="Command buffer"):
        _run(session, state)
    assert session.use_kernel and not metal_kernels.disabled_reason()
