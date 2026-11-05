"""The speculative executor on a configuration a Training Mode Session evolved (package S8).

``test_speculative_exact.py`` edits a provider's codelet bodies directly.  Here the
configuration is evolved the way a session evolves it: batches through the change API
(``LiveConfiguration``: external batches and a learner's after-run batch, changed parameters and
``set_codelet_body``), and the provider each version produces is run speculatively.  What this
defends (the evolution plan, section 3.12 and item 6c):

* an edited body is a barrier for the speculative engine, whatever the edit, and the run equals
  the stream-serial reference run on the same configuration;
* a body edited then restored to the audited text speculates again (the digest matches);
* the other, unedited types stay audited in the same run, so speculation still happens;
* the decision is per configuration version: the engine of an earlier version is unaffected.
"""

from __future__ import annotations

import json
import os

import pytest

from server.parallel.speculative.compare import diff, run_record
from server.parallel.speculative.engine import SpeculativeEngine
from server.engine.runner import EngineRunner
from server.services import config_document as cd
from server.services.configuration_admin import reference_document
from server.services.session_live_config import LiveConfiguration

SEED_DATA = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
STEPS = 450
WORKERS = 4


def problems() -> list[tuple]:
    with open(os.path.join(SEED_DATA, "demo_problems.json")) as f:
        demo = json.load(f)
    seen, out = set(), []
    for p in demo:
        key = (p["initial"], p["modified"], p["target"], p.get("answer"))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


PROBLEMS = problems()
SAMPLE = [0, 1, 12]


def reference_document_provider():
    return cd.provider(reference_document())


def body_of(live: LiveConfiguration, name: str) -> str:
    return live.document.tables["codelet_type_defs"][(name,)]["execute_body"]


def edit_body(name: str, source: str) -> dict:
    return {"op": "set_codelet_body", "name": name, "source": source}


def external(*ops) -> dict:
    return {"source": "external", "actor": "s8", "base_version": "head", "ops": list(ops)}


@pytest.fixture
def live() -> LiveConfiguration:
    return LiveConfiguration(reference_document(), configuration_id=7, revision=0, episode_version=0)


def barrier(meta, name: str) -> bool:
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEMS[0], seed=1)
    with SpeculativeEngine(runner, WORKERS, use_qos=False) as engine:
        return engine._type_plan(name)[0].barrier


def barriers(meta) -> set[str]:
    """The codelet types the engine runs as barriers under *meta* (audited barriers included)."""
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEMS[0], seed=1)
    with SpeculativeEngine(runner, WORKERS, use_qos=False) as engine:
        return {name for name in meta.codelet_specs if engine._type_plan(name)[0].barrier}


def check(meta, pi: int, seed: int = 1):
    ssr = run_record(meta, PROBLEMS[pi], seed, "ssr", max_steps=STEPS)
    spec = run_record(meta, PROBLEMS[pi], seed, "spec", workers=WORKERS, max_steps=STEPS, use_qos=False)
    assert diff(ssr, spec) == [], (PROBLEMS[pi], seed)
    return ssr, spec


def test_a_session_evolved_configuration_with_edited_bodies_stays_exact(live):
    """Parameters changed by an external batch, then a body edited by a learner's batch and one
    by an external batch: three versions, each run speculatively and equal to the serial run."""
    live.submit(external({"op": "set_param", "name": "update_cycle_length", "to": 12}))
    finished = live.finish_run(memory_merge=None, batch={"ops": [
        edit_body("bond-builder", body_of(live, "bond-builder") + "\n# learner edit\n")]})
    assert finished.applied
    live.submit(external(edit_body("group-evaluator", "fizzle()\n" + body_of(live, "group-evaluator"))))
    assert live.revision == 3
    meta = live.provider
    assert barrier(meta, "bond-builder") and barrier(meta, "group-evaluator")
    # Only the two edited types were demoted; every other type keeps its audited entry.
    standard = barriers(reference_document_provider())
    assert barriers(meta) - standard == {"bond-builder", "group-evaluator"}
    assert standard <= barriers(meta)
    for pi in SAMPLE:
        check(meta, pi)


def test_an_edit_that_is_restored_speculates_again(live):
    audited = body_of(live, "bond-builder")
    live.submit(external(edit_body("bond-builder", audited + "\n# tweak\n")))
    edited = live.provider
    live.submit(external(edit_body("bond-builder", audited)))
    restored = live.provider
    assert barrier(edited, "bond-builder")
    assert not barrier(restored, "bond-builder")
    ssr, spec = check(restored, 0)
    assert spec.telemetry["speculated"] > 0


def test_an_earlier_version_keeps_its_own_decision(live):
    """The audited decision belongs to the configuration version a run starts under."""
    before = live.provider
    live.submit(external(edit_body("bond-builder", body_of(live, "bond-builder") + "\n# later\n")))
    after = live.provider
    assert before is not after
    assert not barrier(before, "bond-builder") and barrier(after, "bond-builder")
    check(before, 0)
    check(after, 0)


def test_a_parameter_only_evolution_does_not_demote_any_type(live):
    live.submit(external({"op": "set_param", "name": "update_cycle_length", "to": 9},
                         {"op": "set_param", "name": "initial_temperature", "to": 80.0}))
    meta = live.provider
    assert cd.config_hash(live.document) == live.config_hash
    assert barriers(meta) == barriers(reference_document_provider())
    ssr, spec = check(meta, 0)
    assert spec.telemetry["speculated"] > 0
