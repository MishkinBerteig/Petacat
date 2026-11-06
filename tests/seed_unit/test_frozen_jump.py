"""Proposed test: a frozen node never jumps, on every backend; the coin is still drawn for it.
Run: cd <tree> && PYTHONPATH=<tree> pytest -q <this file> -p no:cacheprovider --rootdir=<tree>"""
import dataclasses
import pytest
from server.engine.numeric import available_backends, get_backend
from server.engine.numeric.layout import SlipnetState, SlipnetTopology
from tests.support.standard_configuration import standard_activation

BACKENDS = [b for b in available_backends()]

@pytest.mark.parametrize("backend_name", BACKENDS)
@pytest.mark.parametrize("ceiling", [100.0, 120.0])
def test_a_frozen_node_in_the_jump_window_does_not_jump(backend_name, ceiling):
    acts = [10.0, 55.0, 60.0, 75.0, 99.0, ceiling, 0.0, 80.0]
    frozen = [False, True, False, True, False, True, True, False]
    n = len(acts)
    topology = SlipnetTopology(
        node_names=tuple(f"n{i}" for i in range(n)), decay_percent=(0.0,) * n,
        conceptual_depth=(50.0,) * n, in_indptr=(0,) * (n + 1), in_source=(), in_weight=(), in_dest=(),
        activation=dataclasses.replace(standard_activation(), max_activation=ceiling))
    session = get_backend(backend_name).open_slipnet(topology)
    session.load(SlipnetState(activation=list(acts), buffer=[0.0] * n, frozen=list(frozen)))
    indices, _ = session.jump_candidates()
    # frozen candidates are still offered: the reference draws their coin before the refusal
    assert indices == [1, 2, 3, 4, 7]
    session.apply_jumps(indices)
    out = session.store().activation
    assert out[1] == 55.0 and out[3] == 75.0                       # frozen, inside the window: unchanged
    assert out[2] == ceiling and out[4] == ceiling and out[7] == ceiling
    assert out[5] == ceiling and out[6] == 0.0
