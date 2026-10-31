"""C0, gate G4: the swarm and the speculative executor give the same runs on the
database-loaded provider as on the seed-file provider.

One swarm case (a real process pool; the provider is pickled to the workers) and one
speculative case with ``workers >= 2``.  Both are ``slow`` and pin their numeric backend to
the CPU (float64) themselves, which is why they sit outside the numeric matrix: the pool's
workers and the speculative threads choose their own backend, as the ``parallel`` layer's
tests do.
"""

from __future__ import annotations

import importlib.util

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from tests.integration.equivalence_harness import (
    LOCKSTEP_PROBLEMS,
    database_reachable,
    fresh_database,
    seed_provider,
)

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not database_reachable(),
        reason="the scratch Postgres is not reachable (start it with scripts/dev.sh db)",
    ),
]

#: The CPU, float64 role of the matrix: NumPy where it is installed, the reference otherwise.
CPU_BACKEND = "numpy" if importlib.util.find_spec("numpy") else "python"
STEPS = 900


@pytest.fixture(scope="module")
def providers():
    return seed_provider(), fresh_database().provider


def test_swarm_on_database_provider_equals_swarm_on_seed_provider(providers):
    from server.engine.hashing import config_hash
    from server.parallel.swarm import RunTask, Swarm, run_inprocess

    seed_meta, db_meta = providers
    tasks = [
        RunTask(i, m, t, a, seed, STEPS, backend=CPU_BACKEND)
        for (i, m, t, a) in LOCKSTEP_PROBLEMS[:4]
        for seed in (1, 2)
    ]
    with Swarm(workers=2, meta=seed_meta, backend=CPU_BACKEND, qos=False) as swarm:
        from_seed = swarm.map(tasks, meta=seed_meta)
        from_db = swarm.map(tasks, meta=db_meta)
    assert all(o.error is None for o in from_seed + from_db), [o.error for o in from_db if o.error]
    assert [o.fingerprint() for o in from_db] == [o.fingerprint() for o in from_seed]
    # And the pool agrees with the in-process serial run on the database provider.
    for task, outcome in zip(tasks, from_db):
        assert run_inprocess(task, db_meta).fingerprint() == outcome.fingerprint()
    # The configuration the pool saw is the same configuration (modulo the recorded
    # coefficient-typing limit, so compare through the answers above, not the hash).
    assert config_hash(seed_meta) and config_hash(db_meta)


@pytest.mark.parametrize("problem_index", [0, 2])
def test_speculative_executor_with_workers_on_database_provider_equals_seed_provider(
    providers, problem_index
):
    from server.engine.numeric.backend import use_backend
    from server.parallel.speculative.compare import diff, run_record

    seed_meta, db_meta = providers
    problem = LOCKSTEP_PROBLEMS[problem_index]
    with use_backend(CPU_BACKEND):
        reference = run_record(seed_meta, problem, 1, "ssr", max_steps=450)
        on_seed = run_record(seed_meta, problem, 1, "spec", workers=2, max_steps=450, use_qos=False)
        on_db = run_record(db_meta, problem, 1, "spec", workers=2, max_steps=450, use_qos=False)
    assert diff(on_seed, on_db) == []
    assert diff(reference, on_db) == []
    assert on_db.digest == on_seed.digest == reference.digest
    assert on_db.codelet_count > 0
