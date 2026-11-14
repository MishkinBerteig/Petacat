"""``propose_ops`` under the speculative executor: the run is the stream-serial reference's, proposals included.

The effects table declares ``propose_ops`` a WRITE with no component, so a body that calls it runs in order under the
commit token and never in a speculated prefix that is discarded and run again (which would add an ``adjust`` twice).
The speculative executor's support for nodes created in a run is not built, and not tested here.
"""

from __future__ import annotations

import json

import pytest

from server.engine.runner import EngineRunner
from server.parallel.speculative.compare import diff, run_record
from tests.support import proposing_configuration as pc

PROBLEM = ("abc", "abd", "xyz", None)
STEPS = 450


@pytest.fixture(scope="module")
def meta():
    return pc.noticer_provider(pc.ALL_BODY)


def proposals_of(meta, mode, seed, workers=1, **options):
    """The record of a run, and what its run proposed (``run_record`` does not keep the context)."""
    from server.parallel.speculative.engine import SpeculativeEngine
    from server.parallel.speculative.reference import StreamSerial

    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=seed)
    if mode == "ssr":
        ref = StreamSerial(runner)
        try:
            ref.run(STEPS)
        finally:
            ref.close()
    else:
        engine = SpeculativeEngine(runner, workers, use_qos=False, **options)
        try:
            engine.run(STEPS)
        finally:
            engine.close()
    return json.dumps(runner.ctx.proposals, sort_keys=True), runner.ctx.rng.call_count, runner.ctx.codelet_count


@pytest.mark.parametrize("workers", [2, 4])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_run_that_proposes_equals_the_stream_serial_reference_proposals_included(meta, seed, workers):
    ssr = run_record(meta, PROBLEM, seed, "ssr", max_steps=STEPS)
    spec = run_record(meta, PROBLEM, seed, "spec", workers=workers, max_steps=STEPS, use_qos=False)
    assert diff(ssr, spec) == []
    reference = proposals_of(meta, "ssr", seed)
    assert proposals_of(meta, "spec", seed, workers) == reference
    ops = json.loads(reference[0])
    assert [p["op"] for p in ops][:3] == ["add_link_type", "add_link", "adjust"] and len(ops) == 6
    assert next(p for p in ops if p["op"] == "adjust" and p["field"] == "link_length")["by"] < 0


def test_forced_aborts_never_record_an_op_twice(meta):
    """``chaos`` forces otherwise-valid speculations to abort and run again: the summed ``adjust`` is the same."""
    reference = proposals_of(meta, "ssr", 2)
    assert proposals_of(meta, "spec", 2, 4, chaos=0.5) == reference
