"""How a Training Mode Session's configuration reaches the workers (package S4).

The pools are bound once and a task carries the configuration it runs under, as a
``ConfigShip``: the pickled provider, named by a key and cached by key in the worker.  What
these defend:

* a run's outcome is the same on the swarm, on the serial child and in process, on evolved
  configurations (changed parameters, an edited codelet body), run for run;
* a configuration change never touches a pool: ``Swarm.rebinds == 0`` and one serial child
  across many versions and two alternating sessions, with no configuration hashed per submit;
* a worker that dies costs the runs it held and nothing else: the next submit runs, exactly;
* the worker cache: a key is unpickled once, the cache is bounded, a fallback provider is used
  only when the task ships none;
* Metacat Mode's calls (a provider passed with the call, bound by hash) are unchanged and can
  share a swarm with session tasks.
"""

from __future__ import annotations

import dataclasses
import pickle
from concurrent.futures.process import BrokenProcessPool

import pytest

from server.engine.hashing import config_hash
from server.engine.metadata import MetadataProvider
from server.parallel import swarm as swarm_module
from server.parallel.swarm import SEED_DIR, RunTask, Swarm, run_inprocess
from server.services import training_mode_session_memory as tm
from server.services.training_mode_session_executor import (
    SerialExecutor,
    SessionTask,
    SwarmExecutor,
    _Shipper,
    outcome_fingerprint,
    run_task,
)
from tests.support.settled import wait_until_settled

STEPS = 400
PROBLEM = ("abc", "abd", "xyz")
OTHER = ("abc", "abd", "ijk")


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED_DIR)


def evolved(meta: MetadataProvider, n: int) -> MetadataProvider:
    """Version *n* of an evolving configuration: a changed parameter and an edited body."""
    out = meta.with_overrides({"update_cycle_length": 10 + n % 7, "initial_temperature": 100.0 - n % 5})
    if n % 2:
        specs = dict(out.codelet_specs)
        spec = specs["bond-builder"]
        specs["bond-builder"] = dataclasses.replace(spec, execute_body=spec.execute_body + f"\n# v{n}\n")
        out = dataclasses.replace(out, codelet_specs=specs)
    return out


def task(seed: int, problem=PROBLEM, steps: int = STEPS, **kw) -> SessionTask:
    return SessionTask(*problem, None, seed, steps, None, "off", **kw)


@pytest.fixture(scope="module")
def swarm_executor(meta):
    ex = SwarmExecutor(Swarm(workers=2, meta=meta))
    yield ex
    ex.swarm.shutdown()


@pytest.fixture(scope="module")
def serial_executor():
    ex = SerialExecutor()
    yield ex
    ex.close()


def fps(outcomes):
    return [outcome_fingerprint(o) for o in outcomes]


# -- swarm == serial == in process, on evolved configurations --------------------------


def test_swarm_serial_and_in_process_agree_on_evolved_configurations(meta, swarm_executor, serial_executor):
    for n in (0, 1, 2, 3, 6):
        cfg = evolved(meta, n)
        tasks = [task(s, p) for s in (1, 2) for p in (PROBLEM, OTHER)]
        via_swarm = swarm_executor.submit(tasks, cfg).result(timeout=300)
        via_serial = serial_executor.submit(tasks, cfg).result(timeout=300)
        local = [run_task(t, cfg) for t in tasks]
        assert fps(via_swarm) == fps(via_serial) == fps(local), n
        assert not any(o.error for o in via_swarm), via_swarm[0].error


def test_a_session_task_equals_the_plain_run_on_the_same_configuration(meta, swarm_executor):
    """The shipped configuration is the configuration: a task run through a pool equals the
    in-process ``run_inprocess`` of a task naming that provider directly."""
    cfg = evolved(meta, 3)
    got = swarm_executor.submit([task(5)], cfg).result(timeout=300)[0]
    ref = run_inprocess(RunTask(*PROBLEM, None, 5, STEPS, backend="off"), cfg)
    assert (got.status, got.codelets, got.answers, got.temperature) == (
        ref.status, ref.codelets, ref.answers, ref.temperature)


def test_two_configurations_give_different_runs_so_the_equivalence_is_not_vacuous(meta, swarm_executor):
    a = swarm_executor.submit([task(1, steps=2500)], evolved(meta, 0)).result(timeout=300)[0]
    b = swarm_executor.submit([task(1, steps=2500)], meta.with_overrides({"update_cycle_length": 3})).result(timeout=300)[0]
    assert (a.codelets, a.temperature, a.answers) != (b.codelets, b.temperature, b.answers)


def test_a_task_with_memory_runs_on_the_shipped_configuration(meta, swarm_executor, serial_executor):
    ref = tm.MemoryRef(77, "epoch-t", 0, 0, [])
    cfg = evolved(meta, 2)
    s = swarm_executor.submit([task(2, memory=ref)], cfg).result(timeout=300)[0]
    c = serial_executor.submit([task(2, memory=ref)], cfg).result(timeout=300)[0]
    assert outcome_fingerprint(s) == outcome_fingerprint(c) == outcome_fingerprint(run_task(task(2, memory=ref), cfg))
    assert s.additions is not None and s.additions == c.additions
    tm.forget_worker_cache()


# -- pool churn -------------------------------------------------------------------------


def _forbid_hashing(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("a configuration was hashed per submit")

    monkeypatch.setattr(swarm_module, "config_hash", boom)


def test_the_swarm_never_rebinds_across_many_versions_and_two_alternating_sessions(meta, monkeypatch):
    with Swarm(workers=2, meta=meta) as sw:
        ex = SwarmExecutor(sw)
        bound = sw.config_hash()
        ex.submit([task(1, steps=30)], meta).result(timeout=300)  # warm
        _forbid_hashing(monkeypatch)
        futures = []
        for version in range(150):
            for session in (0, 1):  # two sessions alternate: different configurations, one pool
                cfg = evolved(meta, 2 * version + session)
                futures.append(ex.submit([task(version, steps=30)], cfg))
            if len(futures) >= 8:  # some jobs are always in flight, some submits find it idle
                for f in futures:
                    f.result(timeout=300)
                futures = []
        for f in futures:
            f.result(timeout=300)
        assert sw.rebinds == 0
        assert sw.config_hash() == bound
        wait_until_settled(sw, ex)  # both counts are lowered by done-callbacks, after result() returns
        assert sw.status()["inflight_jobs"] == 0 and ex.in_flight == 0


def test_the_serial_executor_keeps_one_child_across_many_versions(meta, monkeypatch):
    ex = SerialExecutor()
    try:
        first = ex.submit([task(1, steps=30)], meta).result(timeout=300)[0]
        monkeypatch.setattr("server.engine.hashing.config_hash", lambda *_a, **_k: pytest.fail("hashed"))
        pids = {first.worker_pid}
        for version in range(60):
            for session in (0, 1):
                out = ex.submit([task(version, steps=30)], evolved(meta, 2 * version + session)).result(timeout=300)[0]
                assert not out.error, out.error
                pids.add(out.worker_pid)
        assert len(pids) == 1
        assert len(ex._pools) == 1
    finally:
        ex.close()


def test_the_pool_binds_to_the_first_provider_when_given_no_base_and_only_once(meta):
    sw = Swarm(workers=2)
    ex = SwarmExecutor(sw)
    try:
        assert not sw.bound
        ex.submit([task(1, steps=30)], evolved(meta, 1)).result(timeout=300)
        assert sw.bound and sw.rebinds == 0
        bound = sw.config_hash()
        ex.submit([task(1, steps=30)], evolved(meta, 2)).result(timeout=300)
        assert sw.config_hash() == bound and sw.rebinds == 0
    finally:
        sw.shutdown()


def test_binding_an_unbound_pool_is_not_a_rebind_and_a_second_configuration_is(meta):
    sw = Swarm(workers=2)
    try:
        assert sw.configure(meta) is True and sw.rebinds == 0
        assert sw.configure(meta.with_overrides({"update_cycle_length": 9})) is True and sw.rebinds == 1
    finally:
        sw.shutdown()


# -- worker death -----------------------------------------------------------------------


def test_a_dead_swarm_worker_costs_its_run_and_nothing_else(meta):
    with Swarm(workers=2, meta=meta) as sw:
        ex = SwarmExecutor(sw)
        cfg = evolved(meta, 3)
        before = ex.submit([task(4)], cfg).result(timeout=300)[0]
        with pytest.raises(BrokenProcessPool):
            ex.submit([task(4, fault="kill")], cfg).result(timeout=300)
        after = ex.submit([task(4)], cfg).result(timeout=300)[0]  # a fresh pool; the task brings its configuration
        assert outcome_fingerprint(before) == outcome_fingerprint(after)
        other = ex.submit([task(4)], evolved(meta, 4)).result(timeout=300)[0]
        assert not other.error
        assert sw.rebinds == 0


def test_a_dead_serial_child_is_replaced_and_the_next_run_is_exact(meta):
    ex = SerialExecutor()
    try:
        cfg = evolved(meta, 5)
        before = ex.submit([task(2)], cfg).result(timeout=300)[0]
        with pytest.raises(BrokenProcessPool):
            ex.submit([task(2, fault="kill")], cfg).result(timeout=300)
        after = ex.submit([task(2)], cfg).result(timeout=300)[0]
        assert outcome_fingerprint(before) == outcome_fingerprint(after)
        assert after.worker_pid != before.worker_pid and len(ex._pools) == 1
    finally:
        ex.close()


def test_an_injected_error_is_one_failed_outcome(meta, swarm_executor):
    out = swarm_executor.submit([task(1, fault="error"), task(1)], meta).result(timeout=300)
    assert out[0].status == "error" and out[1].status != "error"


# -- the worker cache and the shipper -----------------------------------------------------


def test_the_shipper_pickles_a_provider_object_once(meta):
    shipper = _Shipper()
    cfg = evolved(meta, 1)
    first = shipper.ship(cfg)
    assert shipper.ship(cfg) is first
    assert pickle.loads(first.blob).codelet_specs.keys() == cfg.codelet_specs.keys()
    other = shipper.ship(evolved(meta, 2))
    assert other.key != first.key


def test_the_shipper_is_bounded_and_a_dropped_provider_is_shipped_again_under_a_new_key(meta):
    shipper = _Shipper()
    cfgs = [evolved(meta, n) for n in range(_Shipper.LIMIT + 3)]
    ships = [shipper.ship(c) for c in cfgs]
    assert len({s.key for s in ships}) == len(ships)
    assert len(shipper._by_id) == _Shipper.LIMIT
    again = shipper.ship(cfgs[0])
    assert again.key not in {s.key for s in ships}


def test_a_worker_unpickles_a_key_once_and_keeps_a_bounded_cache(meta):
    tm.forget_worker_cache()
    shipper = _Shipper()
    ship = shipper.ship(evolved(meta, 1))
    got = tm.worker_provider(ship)
    assert tm.worker_provider(ship) is got
    for n in range(2, 2 + tm.PROVIDER_CACHE_LIMIT + 2):
        tm.worker_provider(shipper.ship(evolved(meta, n)))
    assert len(tm._PROVIDERS) == tm.PROVIDER_CACHE_LIMIT
    assert ship.key not in tm._PROVIDERS  # least recently used went first
    tm.forget_worker_cache()
    assert not tm._PROVIDERS


def test_begin_run_composes_memory_and_provider(meta):
    tm.forget_worker_cache()
    ship = _Shipper().ship(evolved(meta, 1))
    memory, a, s, provider = tm.begin_run(None, ship, meta)
    assert memory is None and (a, s) == (0, 0) and provider is not meta
    memory, a, s, provider = tm.begin_run(tm.MemoryRef(5, "e", 0, 0, []), None, meta)
    assert memory is not None and provider is meta  # no shipped configuration: the fallback
    with pytest.raises(tm.NeedSnapshot):
        tm.begin_run(tm.MemoryRef(5, "e-unknown", 3, 2, []), ship, meta)
    tm.forget_worker_cache()


# -- Metacat Mode is unchanged ------------------------------------------------------------


def test_metacat_mode_calls_still_bind_by_hash_and_share_a_pool_with_session_tasks(meta):
    other = meta.with_overrides({"update_cycle_length": 11})
    plain = RunTask(*PROBLEM, None, 3, STEPS, backend="off")
    with Swarm(workers=2, meta=meta) as sw:
        ex = SwarmExecutor(sw)
        sess = ex.submit([task(3)], evolved(meta, 1)).result(timeout=300)[0]
        assert sw.run(plain).fingerprint() == run_inprocess(plain, meta).fingerprint()
        assert sw.rebinds == 0
        # An idle pool still re-initialises on a Metacat-Mode call that names another configuration.
        assert sw.run(plain, meta=other).fingerprint() == run_inprocess(plain, other).fingerprint()
        assert sw.config_hash() == config_hash(other) and sw.rebinds == 1
        again = ex.submit([task(3)], evolved(meta, 1)).result(timeout=300)[0]
        assert outcome_fingerprint(sess) == outcome_fingerprint(again)
        assert sw.rebinds == 1  # session tasks added none


def test_a_run_task_has_no_configuration_unless_a_session_gives_it_one():
    assert RunTask("a", "b", "c", None, 0, 1).config is None
    assert SessionTask("a", "b", "c", None, 1, 10, None, "off").config is None
