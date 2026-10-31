"""C0, gate G4, run equivalence: a Metacat Mode run on the database-loaded provider is
identical to the same run on the provider built from the seed files.

Compared per (problem, seed): status, answers, the answer on the Workspace, codelet count,
the number of draws from the run's random stream, the final temperature (as ``repr``), a
hash over every codelet step, structure change, trace event and answer the sink saw, and a
hash over the final shared state.  Bit-identical is the bar.

The module is in the numeric backend matrix (``tests/conftest.py``): both providers run on the
same backend within a case, so equality holds on the GPU half too; the float64 CPU half is the
one that asserts bit-identity down to the draw.  The swarm and the speculative executor are in
``test_db_seed_parallel_equivalence.py``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from tests.integration.equivalence_harness import (
    LOCKSTEP_PROBLEMS,
    RUN_SEEDS,
    database_reachable,
    fresh_database,
    run_signature,
    seed_provider,
)

pytestmark = [
    pytest.mark.numeric_matrix,
    pytest.mark.skipif(
        not database_reachable(),
        reason="the scratch Postgres is not reachable (start it with scripts/dev.sh db)",
    ),
]


@pytest.fixture(scope="module")
def providers():
    return seed_provider(), fresh_database().provider


@pytest.mark.parametrize("seed", RUN_SEEDS)
@pytest.mark.parametrize("problem", LOCKSTEP_PROBLEMS, ids=lambda p: "-".join(x or "" for x in p))
def test_run_on_database_provider_equals_run_on_seed_provider(providers, problem, seed):
    seed_meta, db_meta = providers
    expected = run_signature(seed_meta, problem, seed)
    got = run_signature(db_meta, problem, seed)
    assert got == expected
    assert expected["codelet_count"] > 0 and expected["rng_calls"] > 0  # it really ran


def test_the_signature_notices_a_changed_configuration(providers):
    """The comparison has teeth: a changed urgency table or coefficient changes the signature."""
    seed_meta, _ = providers
    problem = LOCKSTEP_PROBLEMS[0]
    base = run_signature(seed_meta, problem, 1)
    import dataclasses

    # (+3 on one urgency level is within a Coderack bin and changes nothing; these do.)
    levels = {name: 1 for name in seed_meta.urgency_levels}
    coefficients = dict(seed_meta.formula_coefficients)
    coefficients["temp_exponent_base"] += 7
    for changed in (
        dataclasses.replace(seed_meta, urgency_levels=levels),
        dataclasses.replace(seed_meta, formula_coefficients=coefficients),
    ):
        assert run_signature(changed, problem, 1) != base
