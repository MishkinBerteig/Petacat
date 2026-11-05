"""The speculative coordinator's grant timeout is the only wall-clock influence on a run (ruling 18).

When a worker has not reached the token within ``grant_timeout`` the coordinator takes the step
back and runs the codelet inline.  Forcing it to fire at every grant (a timeout of zero or of a
nanosecond) must change nothing: the record of the run (status, answers, every step, structure and
event, the sink calls, and the final state fingerprint, which holds the RNG state) is the
reference's.  The measurement behind this test is ``agents-workspace/metacat-cleanup/round2/
S3-dead-open/measure_timeout.py`` (180 forced runs; before the fix 4 differed, at 1e-5 s).
"""

import os

import pytest

from server.engine.metadata import MetadataProvider
from server.parallel.speculative.compare import diff, run_record

SEED_DATA = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
#: (problem, seed, workers): the first four are the cases that diverged before the fix, at
#: timeouts of 1e-5 to 1e-4 seconds (the regime where the worker is mid-prefix when the timeout
#: fires).
CASES = [
    (("abc", "abd", "ijk", None), 1, 2),
    (("abc", "abd", "mrrjjj", None), 1, 4),
    (("abc", "abd", "mrrjjj", None), 3, 4),
    (("abc", "abd", "aabbcc", None), 3, 4),
    (("eqe", "qeq", "abbba", None), 2, 2),
]


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(SEED_DATA)


@pytest.mark.parametrize("timeout", [0.0, 1e-5, 3e-5, 1e-4])
def test_a_forced_grant_timeout_changes_nothing(meta, timeout):
    fired = 0
    for _repeat in range(3):
        for problem, seed, workers in CASES:
            ref = run_record(meta, problem, seed, "ssr", max_steps=700)
            spec = run_record(meta, problem, seed, "spec", workers=workers, max_steps=700,
                              grant_timeout=timeout)
            assert diff(ref, spec) == [], (timeout, problem, seed)
            fired += (spec.telemetry or {}).get("timeouts", 0)
    if timeout == 0.0:
        assert fired > 0, "forcing the timeout did not make it fire"
