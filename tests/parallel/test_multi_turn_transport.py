"""A multi-turn run's turns on every route and every numeric backend (v2.0, increment 4, stage B).

A turn is one engine run, a pure function of the configuration it is dispatched under, the strings of its four
positions, the run's seed and the turn number.  A chat of two turns that builds Slipnet structure (a symbol with no
node gets one in turn 1, and turn 2 starts under it) is driven the way the service drives it (each turn's
proposals land in the configuration before the next turn is dispatched) on the serial child, the swarm and in
process, on the numeric backends ``off``, ``python`` and ``numpy``.  The conversations are identical: every turn's
answer, codelets, random draws (through the turn's outcome), proposals and evidence.  Also: the joined strings reach
the Workspace exactly, and a space is an object perceived through its own node once the configuration has one.
"""

from __future__ import annotations

import pytest

from server.engine.runner import EngineRunner
from server.parallel.swarm import Swarm
from server.services import config_document as cd
from server.services import training_base as tb
from server.services import training_mode_session_memory as tm
from server.services import turn_record
from server.services.session_live_config import LiveConfiguration
from server.services.training_mode_session_executor import (
    SerialExecutor, SessionTask, SwarmExecutor, outcome_fingerprint, run_task,
)
from server.services.training_mode_session_service import IN_WORKER_LEARNER, TrainingModeSessionService

pytestmark = pytest.mark.numeric_matrix

STEPS = 1500
PROBLEM = ("1", "1", "1")
INPUTS = ("2", "3")
BACKENDS = ["off", "python", "numpy"]
#: A Training Mode Session's memory, empty: every session task carries one, and a run reports its evidence only then
#: (Metacat Mode's runs never read it).
MEMORY = tm.MemoryRef(4242, "epoch-multi-turn", 0, 0, [])


@pytest.fixture(scope="module")
def swarm_executor():
    ex = SwarmExecutor(Swarm(workers=2, meta=cd.provider(tb.resolve_base().document)))
    yield ex
    ex.swarm.shutdown()


@pytest.fixture(scope="module")
def serial_executor():
    ex = SerialExecutor()
    yield ex
    ex.close()


def live() -> LiveConfiguration:
    return LiveConfiguration(tb.resolve_base().document, configuration_id=0, revision=0, episode_version=0)


def chat(submit, backend: str, seed: int, problem=PROBLEM, inputs=INPUTS):
    """Drive one run as the service does: a turn is dispatched under the configuration as it is, its proposals
    land (one ``finish_run``) before the next turn, a turn with no answer ends the run, and the teacher gives the
    next input until its inputs are used up.  Returns each turn's strings and outcome fingerprint."""
    config = live()
    context, second, input_text = problem
    record = []
    for turn in range(1, len(inputs) + 2):
        task = SessionTask(context, second, input_text, None, turn_record.turn_seed(seed, turn), STEPS, None, backend,
                           memory=MEMORY)
        outcome = submit(task, cd.provider(config.document))
        record.append(((context, second, input_text), outcome_fingerprint(outcome)))
        assert outcome.error is None, outcome.error
        batch = TrainingModeSessionService._proposal_batch(outcome, seed=seed, turn=turn)
        if batch is not None:
            config.finish_run(memory_merge=lambda: None, batch=batch, run=(1, seed), started_revision=0,
                              learner=IN_WORKER_LEARNER)
        if not outcome.answer or turn > len(inputs):
            break
        context, second, input_text = turn_record.next_window(context, second, input_text, outcome.answer, inputs[turn - 1])
    return record, config


def routes(swarm_executor, serial_executor):
    return {
        "in-process": lambda task, meta: run_task(task, meta),
        "serial child": lambda task, meta: serial_executor.submit([task], meta).result(timeout=300)[0],
        "swarm": lambda task, meta: swarm_executor.submit([task], meta).result(timeout=300)[0],
    }


@pytest.mark.parametrize("seed", [1, 2])
def test_a_chat_that_builds_structure_is_identical_on_every_route_and_backend(seed, swarm_executor, serial_executor):
    seen = {}
    for backend in BACKENDS:
        for name, submit in routes(swarm_executor, serial_executor).items():
            seen[backend, name], config = chat(submit, backend, seed)
    first = seen["off", "in-process"]
    assert len(first) >= 2, "the chat should have run at least two turns"
    for key, got in seen.items():
        assert got == first, key
    # turn 1 met symbols with no node and built them; turn 2 was dispatched under that
    nodes = {k[0] for k in config.document.tables["slipnet_node_defs"]}
    assert "plato-cp-0031" in nodes  # the symbol `1`, perceived through a node of its own
    # turn 2's strings are the window of turn 1's
    (c1, s1, i1), fp1 = first[0][0], first[0][1]
    answer = fp1[2]
    assert first[1][0] == (f"{c1} {s1} {i1}", answer, INPUTS[0])
    assert first[1][0][0] == "1 1 1"


def test_turn_one_is_the_run_before_turns_existed(serial_executor):
    """Turn 1 uses the run's seed, so a single-turn run is bit-identical to a plain run of that seed."""
    meta = cd.provider(tb.resolve_base().document)
    direct = run_task(SessionTask(*PROBLEM, None, 7, STEPS, None, "off"), meta)
    via_turn = run_task(SessionTask(*PROBLEM, None, turn_record.turn_seed(7, 1), STEPS, None, "off"), meta)
    assert outcome_fingerprint(direct) == outcome_fingerprint(via_turn)
    again = run_task(SessionTask(*PROBLEM, None, turn_record.turn_seed(7, 2), STEPS, None, "off"), meta)
    assert again.seed == turn_record.turn_seed(7, 2) != 7


def _letters(meta, text):
    runner = EngineRunner(meta)
    runner.init_mcat(text, "ijl", "xyz", None, seed=1)
    workspace, dimension = runner.ctx.workspace, runner.ctx.slipnet.roles.dimension_letter_category
    string = workspace.initial_string
    return string.text, [getattr(o.get_descriptor_for(dimension), "name", None) for o in string.objects]


def test_the_joined_strings_reach_the_workspace_exactly_and_a_space_is_perceived_through_its_own_node():
    config = live()
    joined = "abc abd ijk"
    text, perceived = _letters(cd.provider(config.document), joined)
    assert text == joined and len(perceived) == len(joined)  # exactly, spaces and all
    assert perceived[3] is None and perceived[7] is None  # no node for the space yet: not perceived
    task = SessionTask("a b", "a b", "a b", None, 1, 5000, None, "off")
    outcome = run_task(task, cd.provider(config.document))  # a run that meets a space builds its node
    assert [p["name"] for p in outcome.proposals if p["op"] == "add_node"] == ["plato-cp-0020"]
    config.finish_run(memory_merge=lambda: None, batch=TrainingModeSessionService._proposal_batch(outcome),
                      run=(1, 1), started_revision=0, learner=IN_WORKER_LEARNER)
    text, perceived = _letters(cd.provider(config.document), joined)
    assert text == joined and perceived[3] == perceived[7] == "plato-cp-0020"
    assert [p for i, p in enumerate(perceived) if joined[i] != " "] == [
        "plato-" + ch for ch in "abcabdijk"]  # the letters keep their own nodes; nothing treats the space as a boundary
    # any text passes through untouched, whatever it holds
    odd = "  a\t😀́ \n"
    assert _letters(cd.provider(config.document), odd)[0] == odd


def test_evidence_tells_a_turn_blocked_on_perception_from_a_cognitive_give_up():
    meta = cd.provider(tb.resolve_base().document)
    blocked = run_task(SessionTask("a b", "a b", "a b", None, 1, 30, None, "off", memory=MEMORY), meta)  # space unperceived
    assert blocked.evidence["unperceived"] > 0 and blocked.evidence["rule"] is None
    answered = run_task(SessionTask("abc", "abd", "ijk", None, 1, STEPS, None, "off", memory=MEMORY), meta)
    assert answered.status == "answer_found" and answered.evidence["unperceived"] == 0
    assert answered.evidence["rule"]["top_rule"] and answered.evidence["bonds"] and answered.evidence["groups"]
    assert set(answered.evidence) == {"bonds", "groups", "rule", "snags", "unperceived", "coderack"}
    assert set(answered.evidence["coderack"]) == {"full_posts", "overflowing_batches", "evicted"}
    # the evidence is in the fingerprint, so two routes that disagree on it disagree
    assert outcome_fingerprint(answered) != outcome_fingerprint(blocked)
    # a task with no Training Mode Session memory (as no session sends) reports none
    assert run_task(SessionTask("abc", "abd", "ijk", None, 1, STEPS, None, "off"), meta).evidence is None


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_turns_coderack_pressure_is_the_same_on_every_route(backend, swarm_executor, serial_executor):
    """The evidence's ``coderack`` (full posts, overflowing batches, evicted) through the serial child, the swarm and in
    process: whole numbers, identical, and more than zero for a run long enough to fill the rack."""
    pressure = {}
    for name, submit in routes(swarm_executor, serial_executor).items():
        task = SessionTask("abc", "abd", "ijk", None, 1, STEPS, None, backend, memory=MEMORY)
        outcome = submit(task, cd.provider(live().document))
        assert outcome.error is None, outcome.error
        pressure[name] = outcome.evidence["coderack"]
    first = pressure["in-process"]
    assert all(type(v) is int and v >= 0 for v in first.values())
    assert first["evicted"] > 0
    assert pressure["serial child"] == first and pressure["swarm"] == first
