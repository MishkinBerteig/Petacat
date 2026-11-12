"""The in-worker learner: a run's ``proposals`` reach the session's configuration through
``finish_run`` as a batch from the learner, ``rebase`` and ``skip``, one op per row."""

from __future__ import annotations

import pickle

from server.parallel.swarm import RunOutcome, proposals_key
from server.services import config_document as cd
from server.services import training_base as tb
from server.services.session_live_config import LiveConfiguration
from server.services.training_mode_session_executor import (
    SessionOutcome, outcome_fingerprint,
)
from server.services.training_mode_session_service import (
    AFTER_RUN_LEARNER, IN_WORKER_LEARNER, TrainingModeSessionService,
)

NODE = {"op": "add_node", "name": "plato-cp-0031", "fields": {
    "short_name": "1", "glyph": "1", "plain_name": "1", "article_an": False, "conceptual_depth": 10}}


def outcome(proposals, seed=1, cls=SessionOutcome):
    return cls(seed=seed, status="answer_found", answer="1", answers=["1"], codelets=5, seconds=0.0,
               stopping_state="answer_found:1", proposals=proposals)


def live() -> LiveConfiguration:
    return LiveConfiguration(tb.resolve_base().document, configuration_id=0, revision=0, episode_version=0)


def test_proposals_are_plain_picklable_dicts_in_both_fingerprints():
    a, b = outcome([NODE]), outcome([])
    assert a.fingerprint() != b.fingerprint() and outcome_fingerprint(a) != outcome_fingerprint(b)
    assert a.fingerprint() == outcome([dict(NODE)]).fingerprint()
    assert pickle.loads(pickle.dumps(a)).proposals == [NODE]
    r = outcome([NODE], cls=RunOutcome)
    assert r.fingerprint() != outcome([], cls=RunOutcome).fingerprint()
    assert outcome_fingerprint(r) == outcome_fingerprint(a)
    assert outcome_fingerprint(r)[-1] == proposals_key([NODE])
    assert outcome([]).fingerprint()[-1] == ()


def test_no_proposals_means_no_batch():
    assert TrainingModeSessionService._proposal_batch(outcome([])) is None
    batch = TrainingModeSessionService._proposal_batch(outcome([NODE], seed=9))
    assert batch["ops"] == [NODE] and "seed 9" in batch["note"]


def test_a_node_that_several_runs_made_is_one_row_and_the_duplicates_are_skipped_cleanly():
    config = live()
    assert "plato-cp-0031" not in {k[0] for k in config.document.tables["slipnet_node_defs"]}
    for seed in (1, 2, 3):
        batch = TrainingModeSessionService._proposal_batch(outcome([NODE], seed=seed))
        config.finish_run(memory_merge=lambda: None, batch=batch, run=(1, seed), started_revision=0,
                          learner=IN_WORKER_LEARNER)
    nodes = [k for k in config.document.tables["slipnet_node_defs"] if k[0] == "plato-cp-0031"]
    assert len(nodes) == 1
    assert len(config.changes) == 1  # the other two applied nothing, so there is one journal entry
    entry = config.changes[0].pending
    assert (entry.source, entry.actor) == ("learner", f"learner:{IN_WORKER_LEARNER}")
    assert [op["table"] for op in entry.resolved] == ["slipnet_node_defs"]
    assert config.version == 3 and config.revision == 1 and config.diagnostics == []


def test_the_after_run_seams_batch_is_its_own_entry_so_the_journal_names_each_source():
    config = live()
    seam = {"ops": [{"op": "adjust_param", "name": "new_node_conceptual_depth", "by": 1}]}
    mine = TrainingModeSessionService._proposal_batch(outcome([NODE]))
    first = config.finish_run(memory_merge=lambda: None, batch=mine, run=(1, 1), started_revision=0,
                              learner=IN_WORKER_LEARNER)
    second = config.finish_run(memory_merge=None, batch=seam, run=(1, 1), started_revision=0,
                               learner=AFTER_RUN_LEARNER)
    assert (first.version, second.version) == (1, 2)
    assert [(c.pending.source, c.pending.actor) for c in config.changes] == [
        ("learner", f"learner:{IN_WORKER_LEARNER}"), ("learner", f"learner:{AFTER_RUN_LEARNER}")]
