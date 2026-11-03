"""A configuration lacking a declared name stops the run at its start, on every path (EN10).

``server/engine/start_check.py`` lists every parameter, formula coefficient and urgency level
the engine reads.  For each declared name, the Metacat Standard Configuration without it gives a
``check_run_start`` problem naming it; and the run-start check comes first on each path that
starts a run (the engine, a Metacat Mode run, a swarm call, a Training Mode Session dispatch,
a population), so the message is the check's and never a ``KeyError`` or a failed outcome.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from server.engine import start_check as sc
from server.engine.metadata import MetadataProvider
from server.engine.start_check import RunStartError, check_run_start

SEED_DIR = str(Path(__file__).resolve().parents[2] / "seed_data")


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED_DIR)


def _without(meta: MetadataProvider, kind: str, name: str) -> MetadataProvider:
    if kind == "parameter":
        return replace(meta, params={k: v for k, v in meta.params.items() if k != name})
    if kind == "coefficient":
        return replace(
            meta, formula_coefficients={k: v for k, v in meta.formula_coefficients.items() if k != name}
        )
    return replace(meta, urgency_levels={k: v for k, v in meta.urgency_levels.items() if k != name})


def _declared():
    for name, _ in sc.REQUIRED_ENGINE_PARAMETERS:
        yield "parameter", name
    for name, _ in sc.REQUIRED_FORMULA_COEFFICIENTS:
        yield "coefficient", name
    for name, _ in sc.REQUIRED_URGENCY_LEVELS:
        yield "urgency level", name


def test_the_standard_configuration_lacks_nothing(meta) -> None:
    assert check_run_start(meta) == ()


def test_each_declared_name_missing_is_named_by_the_check(meta) -> None:
    for kind, name in _declared():
        problems = check_run_start(_without(meta, kind, name))
        assert any(p.name == name for p in problems), f"{kind} {name!r} was not reported"


def test_every_missing_name_is_reported_in_one_message(meta) -> None:
    lacking = replace(
        meta,
        params={k: v for k, v in meta.params.items() if k not in ("update_cycle_length", "max_clamp_period")},
        formula_coefficients={
            k: v for k, v in meta.formula_coefficients.items() if k != "temp_exponent_base"
        },
    )
    with pytest.raises(RunStartError) as e:
        sc.require_run_start(lacking)
    text = str(e.value)
    assert "update_cycle_length" in text and "max_clamp_period" in text and "temp_exponent_base" in text


def test_a_run_start_error_is_a_value_error(meta) -> None:
    """So the API answers a request that cannot start with a 400 and the message."""
    assert issubclass(RunStartError, ValueError)


#: One of each kind, and the ones that were read with a code default before EN10.
_SAMPLE = [
    ("parameter", "update_cycle_length"),
    ("parameter", "initial_codelet_types"),
    ("parameter", "top_down_slipnodes"),
    ("parameter", "initially_clamped_slipnodes"),
    ("parameter", "max_clamp_period"),
    ("parameter", "snag_clamp_temperature"),
    ("coefficient", "temp_exponent_base"),
    ("coefficient", "low_prob_threshold"),
    ("urgency level", "low"),
]


@pytest.mark.parametrize("kind,name", _SAMPLE)
def test_the_engine_stops_before_the_first_codelet(meta, kind, name) -> None:
    from server.engine.runner import EngineRunner

    runner = EngineRunner(_without(meta, kind, name))
    with pytest.raises(RunStartError, match=name):
        runner.init_mcat("abc", "abd", "xyz", seed=1)
    assert runner.ctx is None or runner.ctx.codelet_count == 0


@pytest.mark.parametrize("kind,name", _SAMPLE)
def test_a_metacat_mode_run_stops_before_it_reads_a_parameter(meta, kind, name) -> None:
    """``RunService.create_run`` reads ``spreading_activation_threshold`` before the engine
    exists; the check comes first, so no session is touched and no ``KeyError`` is raised."""
    from server.services.configuration_store import ConfigurationStore
    from server.services.run_service import RunService

    service = RunService(ConfigurationStore(_without(meta, kind, name)))
    with pytest.raises(RunStartError, match=name):
        asyncio.run(service.create_run(None, "abc", "abd", "xyz", seed=1))  # type: ignore[arg-type]


def test_a_metacat_mode_run_lacking_the_spreading_threshold_gives_the_check_message(meta) -> None:
    from server.services.configuration_store import ConfigurationStore
    from server.services.run_service import RunService

    service = RunService(ConfigurationStore(_without(meta, "parameter", "spreading_activation_threshold")))
    with pytest.raises(RunStartError, match="spreading_activation_threshold"):
        asyncio.run(service.create_run(None, "abc", "abd", "xyz", seed=1))  # type: ignore[arg-type]


def _task():
    from server.parallel.swarm import RunTask

    return RunTask("abc", "abd", "xyz", seed=1, max_steps=50)


@pytest.mark.parametrize("kind,name", _SAMPLE)
def test_a_swarm_call_stops_before_a_pool_exists(meta, kind, name) -> None:
    from server.parallel.swarm import Swarm

    swarm = Swarm(workers=1)
    try:
        with pytest.raises(RunStartError, match=name):
            swarm.run(_task(), meta=_without(meta, kind, name))
        assert swarm._executor is None, "no worker pool was started for a configuration that cannot run"
    finally:
        swarm.shutdown(wait_for_tasks=False)


def test_the_in_process_swarm_reference_gives_the_check_message_not_a_failed_outcome(meta) -> None:
    from server.parallel.swarm import run_inprocess

    with pytest.raises(RunStartError, match="update_cycle_length"):
        run_inprocess(_task(), _without(meta, "parameter", "update_cycle_length"))


def test_a_training_mode_dispatch_stops_at_the_executor(meta) -> None:
    from server.services.training_mode_session_executor import SerialExecutor, SessionTask

    task = SessionTask("abc", "abd", "xyz", None, 1, 50, None, "off")
    executor = SerialExecutor()
    try:
        with pytest.raises(RunStartError, match="update_cycle_length"):
            executor.submit([task], _without(meta, "parameter", "update_cycle_length"))
        assert not executor._pools, "no child process was started"
    finally:
        executor.close()


def test_a_population_stops_before_it_reads_the_update_cycle(meta) -> None:
    from server.parallel.population import run_population_batched

    with pytest.raises(RunStartError, match="update_cycle_length"):
        run_population_batched(
            ("abc", "abd", "xyz"), 2, meta=_without(meta, "parameter", "update_cycle_length")
        )


def test_a_sharded_coderack_stops_before_it_reads_the_capacity(meta) -> None:
    from server.parallel.coderack_shards import FamilyShardedCoderack

    with pytest.raises(RunStartError, match="max_coderack_size"):
        FamilyShardedCoderack(_without(meta, "parameter", "max_coderack_size"), 2)
