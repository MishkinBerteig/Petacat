"""S0: a run under ``provider(ConfigDocument)`` is the same run as under the files' provider.

The document is built from the Metacat Standard Configuration files; an evolved document
(an edit applied by ``apply_resolved``) runs the same as the provider evolved by hand.
Compared by the equivalence harness's run signature: answer, codelet count, random draws,
temperature and the hashes of the trace and the final state.  The module is in the numeric
backend matrix.
"""

from __future__ import annotations

import dataclasses

import pytest

from server.services import config_document as cd
from tests.integration.equivalence_harness import (
    LOCKSTEP_PROBLEMS,
    RUN_SEEDS,
    SEED_DIR,
    run_signature,
    seed_provider,
)

pytestmark = pytest.mark.numeric_matrix


@pytest.fixture(scope="module")
def doc():
    return cd.document_from_standard_files(SEED_DIR)


@pytest.mark.parametrize("seed", RUN_SEEDS)
@pytest.mark.parametrize("problem", LOCKSTEP_PROBLEMS[:3], ids=lambda p: "-".join(x or "" for x in p))
def test_unedited_document_runs_like_the_files_provider(doc, problem, seed):
    expected = run_signature(seed_provider(), problem, seed)
    assert run_signature(cd.provider(doc), problem, seed) == expected
    assert expected["codelet_count"] > 0 and expected["rng_calls"] > 0


@pytest.mark.parametrize("seed", RUN_SEEDS)
def test_evolved_document_runs_like_the_hand_evolved_provider(doc, seed):
    problem = LOCKSTEP_PROBLEMS[0]
    meta = seed_provider()
    new_value = meta.formula_coefficients["temp_exponent_base"] + 7  # (+3 on an urgency level changes nothing)
    evolved = cd.apply_resolved(
        doc,
        [{"op": "update", "table": "formula_coefficients", "key": {"name": "temp_exponent_base"},
          "set": {"value": str(new_value)}}],
    )
    by_hand = dataclasses.replace(
        meta, formula_coefficients={**meta.formula_coefficients, "temp_exponent_base": new_value}
    )
    got = run_signature(cd.provider(evolved, doc), problem, seed)
    assert got == run_signature(by_hand, problem, seed)
    assert got != run_signature(meta, problem, seed)  # the edit is visible
