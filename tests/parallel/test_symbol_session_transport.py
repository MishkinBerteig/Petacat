"""A run that creates a node, on every route a session's run can take (v2.0 Base).

The swarm, the serial child and the in-process run give the same outcomes, ``proposals`` included;
a worker that created a node leaves the shipped provider untouched (the next run of the same seed
creates it again); and once the node is in the configuration a run starts with the symbol perceived,
posts no ``symbol-scout`` and proposes nothing.
"""

from __future__ import annotations

import dataclasses

import pytest

from server.engine.codelet_dsl.interpreter import CodeletInterpreter
from server.parallel.swarm import Swarm
from server.services import config_document as cd
from server.services import training_base as tb
from server.services.training_mode_session_executor import (
    SerialExecutor, SessionTask, SwarmExecutor, outcome_fingerprint, run_task,
)

STEPS = 2000
PROBLEMS = [("1", "1", "1"), ("😀", "😀", "😀")]


@pytest.fixture(scope="module")
def base():
    return cd.provider(tb.resolve_base().document)


@pytest.fixture(scope="module")
def swarm_executor(base):
    ex = SwarmExecutor(Swarm(workers=2, meta=base))
    yield ex
    ex.swarm.shutdown()


@pytest.fixture(scope="module")
def serial_executor():
    ex = SerialExecutor()
    yield ex
    ex.close()


def task(seed, problem):
    return SessionTask(*problem, None, seed, STEPS, None, "off")


def test_swarm_serial_child_and_in_process_agree_with_proposals(base, swarm_executor, serial_executor):
    tasks = [task(s, p) for s in (1, 2, 3) for p in PROBLEMS]
    via_swarm = swarm_executor.submit(tasks, base).result(timeout=300)
    via_serial = serial_executor.submit(tasks, base).result(timeout=300)
    local = [run_task(t, base) for t in tasks]
    assert [outcome_fingerprint(o) for o in via_swarm] == [outcome_fingerprint(o) for o in via_serial] \
        == [outcome_fingerprint(o) for o in local]
    assert not any(o.error for o in via_swarm), via_swarm[0].error
    assert all(o.proposals for o in via_swarm)
    assert [o.proposals[0]["name"] for o in via_swarm] == [
        f"plato-cp-{ord(t.initial):04x}" for t in tasks]
    assert [o.answer for o in via_swarm] == [t.initial for t in tasks]


def test_a_worker_that_created_a_node_leaves_the_shipped_provider_alone(base, serial_executor):
    again = [serial_executor.submit([task(1, PROBLEMS[0])], base).result(timeout=300)[0] for _ in range(2)]
    assert outcome_fingerprint(again[0]) == outcome_fingerprint(again[1]) and again[0].proposals
    assert "plato-cp-0031" not in base.slipnet_node_specs


def test_with_the_node_in_the_configuration_the_symbol_is_perceived_at_once(base, monkeypatch):
    spec = type(next(iter(base.slipnet_node_specs.values())))(
        name="plato-cp-0031", short_name="1", conceptual_depth=10, plain_name="1", glyph="1", article_an=False)
    known = dataclasses.replace(base, slipnet_node_specs={**base.slipnet_node_specs, spec.name: spec})
    seen: list[str] = []
    real = CodeletInterpreter.execute

    def record(self, compiled, ctx, **kw):
        seen.append(compiled.name)
        return real(self, compiled, ctx, **kw)

    monkeypatch.setattr(CodeletInterpreter, "execute", record)
    out = run_task(task(1, PROBLEMS[0]), known)
    assert out.proposals == [] and out.answer == "1" and not out.error
    assert "symbol-scout" not in seen and "symbol-builder" not in seen
    seen.clear()
    unknown = run_task(task(1, PROBLEMS[0]), base)
    assert "symbol-scout" in seen and "symbol-builder" in seen and unknown.proposals
    assert unknown.codelets > out.codelets
