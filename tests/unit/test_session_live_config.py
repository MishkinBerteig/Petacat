"""A live session's own configuration (S3a): ``LiveConfiguration`` and ``LiveEpisodeLog``.

Pure: no database, no engine run.  What is checked is the glue S3 adds to the S1 episode log:
the configuration revision (the entity's counter) kept apart from the episode version, the entries
the Stop write will store (``journal.PendingEntry``), the run-finish entry's order, the after-run
seam's defaults and failure rule, and the immutability of the configuration a run was dispatched
under.
"""

from __future__ import annotations

import pytest

from server.engine.hashing import config_hash as provider_hash
from server.engine.metadata import MetadataProvider
from server.services import config_document as cd
from server.services import journal
from server.services.configuration_admin import reference_document
from server.services.session_episode import StaleBatch
from server.services.session_live_config import ConfigRef, LiveConfiguration

PARAM = "update_cycle_length"


def external(*ops, **extra) -> dict:
    return {"source": "external", "actor": "test", "ops": list(ops), **extra}


def set_param(value) -> dict:
    return {"op": "set_param", "name": PARAM, "to": value}


def adjust_param(by) -> dict:
    return {"op": "adjust_param", "name": PARAM, "by": by}


def param(live: LiveConfiguration):
    return live.provider.get_param(PARAM)


@pytest.fixture
def live() -> LiveConfiguration:
    """A configuration at revision 0, with the episode counter resuming at 5."""
    return LiveConfiguration(
        reference_document(), configuration_id=7, revision=0, episode_version=5,
        base_hash="b" * 64,
    )


def test_a_fresh_live_configuration_is_the_standard_configuration(live):
    ref = live.ref(3)
    assert isinstance(ref, ConfigRef)
    assert (ref.session_id, ref.version, ref.configuration_revision) == (3, 5, 0)
    standard = MetadataProvider.from_standard_configuration("seed_data")
    assert ref.config_hash == provider_hash(standard) == live.config_hash
    assert live.pending_entries() == [] and live.diagnostics == []
    assert live.saved_revision == 0


def test_the_revision_resumes_from_the_stored_one_and_apart_from_the_episode_version():
    stored = LiveConfiguration(
        reference_document(), configuration_id=7, revision=4, episode_version=40,
    )
    assert (stored.revision, stored.version) == (4, 40)
    stored.finish_run(memory_merge=lambda: None)
    assert (stored.revision, stored.version) == (4, 41)  # a memory-only entry: a version, no revision
    out = stored.submit(external(set_param(16)))
    assert out.applied
    assert (stored.revision, stored.version) == (5, 42)
    assert stored.saved_revision == 4
    [pending] = stored.pending_entries()
    assert (pending.revision, pending.episode_version) == (5, 42)
    assert stored.summary()["version"] == 5 and stored.summary()["last_change_version"] == 42


def test_an_external_batch_takes_the_next_version_and_revision(live):
    before = live.ref(1)
    out = live.submit(external(set_param(16)))
    assert out.applied and out.change is not None
    assert (live.revision, live.version) == (1, 6)
    assert param(live) == 16
    report = out.report
    assert report["persisted"] is False and report["batch_id"] is None
    assert (report["version_before"], report["version_after"], report["episode_version"]) == (0, 1, 6)
    assert report["configuration_id"] == 7 and report["ok"] is True
    # a configuration taken at dispatch never changes under the run
    assert before.provider.get_param(PARAM) != 16 and before.config_hash != live.config_hash
    assert before.configuration_revision == 0 and before.version == 5
    assert live.ref(1).configuration_revision == 1


def test_the_held_entry_is_what_the_journal_layer_would_store(live):
    live.submit(external(set_param(16)))
    [entry] = live.pending_entries()
    assert isinstance(entry, journal.PendingEntry)
    assert (entry.source, entry.actor, entry.note, entry.channel, entry.group_id) == (
        "external", "test", "", "", None)
    assert entry.proposed == [set_param(16)]
    assert len(entry.resolved) == len(entry.before) == 1
    assert entry.resolved[0]["op"] == "update" and entry.resolved[0]["table"] == "engine_params"
    assert entry.before[0]["name"] == PARAM and entry.before[0]["value"] != entry.resolved[0]["set"]["value"]
    assert entry.config_hash == live.config_hash and entry.occurred_at is not None
    # the same normalisation the stored path applies, from the document before the batch
    resolved, before = journal.normalize_ops(reference_document(), entry.resolved)
    assert resolved == entry.resolved and before == entry.before


def test_batch_provenance_is_kept_on_the_entry(live):
    live.submit({**external(set_param(16)), "note": "why", "channel": "route", "group_id": "g1"})
    [entry] = live.pending_entries()
    assert (entry.note, entry.channel, entry.group_id) == ("why", "route", "g1")


def test_pending_entries_continue_the_stored_revision_without_a_gap(live):
    live.submit(external(set_param(16)))
    live.finish_run(memory_merge=lambda: None)
    live.submit(external(set_param(17)))
    live.finish_run(memory_merge=lambda: None, batch={"ops": [adjust_param(1)]})
    assert [e.revision for e in live.pending_entries()] == [1, 2, 3]
    assert [e.episode_version for e in live.pending_entries()] == [6, 8, 9]
    assert live.version == 9 and live.revision == 3


def test_a_dry_run_changes_nothing(live):
    out = live.submit(external(set_param(16), dry_run=True))
    assert not out.applied and out.report["dry_run"] is True and out.report["persisted"] is False
    assert (live.revision, live.version) == (0, 5) and param(live) != 16
    assert live.pending_entries() == []


def test_a_batch_that_applies_nothing_takes_no_version(live):
    same = param(live)
    out = live.submit(external(set_param(same)))
    assert not out.applied
    assert (live.revision, live.version) == (0, 5)
    assert live.pending_entries() == []
    assert len(live.log.diagnostics) == 1


def test_strict_is_checked_against_the_revision_not_the_episode_version(live):
    live.finish_run(memory_merge=lambda: None)  # version 6, revision 0
    live.submit(external(set_param(16), base_version=0))  # strict by default: 0 is the revision
    with pytest.raises(StaleBatch):
        live.submit(external(set_param(17), base_version=0))  # the revision is now 1
    assert param(live) == 16
    live.submit(external(set_param(17), base_version=1))
    live.submit(external(set_param(18), base_version=7, base_mode="rebase"))  # rebase never raises
    live.submit(external(set_param(19), base_version="head"))
    assert (live.revision, param(live)) == (4, 19)


def test_a_refused_batch_changes_nothing(live):
    from server.services.change_resolve import ChangeRefused

    with pytest.raises(ChangeRefused):
        live.submit(external({"op": "frobnicate", "name": PARAM}))
    assert (live.revision, live.version) == (0, 5) and live.pending_entries() == []


def test_the_run_finish_entry_is_memory_then_batch_then_one_version(live):
    order = []

    def merge():
        order.append(("memory", live.revision))
        return (2, 1)

    done = live.finish_run(memory_merge=merge, batch={"ops": [set_param(16)]}, run=(4, 9))
    assert order == [("memory", 0)]  # the merge ran before the batch took effect
    assert done.memory == (2, 1) and done.version == 6 and done.applied
    assert (live.revision, live.version) == (1, 6)
    assert done.change is not None and done.change.run == (4, 9)


def test_an_empty_run_finish_still_takes_a_version_and_no_revision(live):
    done = live.finish_run(memory_merge=lambda: None)
    assert (done.version, done.applied, done.change) == (6, False, None)
    assert (live.revision, live.version) == (0, 6)
    assert live.pending_entries() == []


def test_a_learners_batch_is_filled_in_as_the_seam_promises(live):
    live.finish_run(memory_merge=lambda: None)  # a newer episode version than the run started at
    live.submit(external(set_param(20)))  # and a newer revision
    live.finish_run(
        memory_merge=lambda: None, batch={"ops": [adjust_param(2)]}, run=(1, 1),
        started_revision=0, learner="plato",
    )
    entry = live.pending_entries()[-1]
    assert (entry.source, entry.actor) == ("learner", "learner:plato")
    assert param(live) == 22  # rebase: it applied to the current value, not the run's snapshot
    assert entry.proposed == [adjust_param(2)]


def test_two_learner_batches_from_runs_on_one_snapshot_add_up(live):
    start = param(live)
    for _ in range(2):
        live.finish_run(
            memory_merge=lambda: None, batch={"ops": [adjust_param(2)]}, started_revision=0,
        )
    assert param(live) == start + 4


def test_a_learners_batch_that_is_refused_never_fails_its_run(live):
    merged = []
    done = live.finish_run(
        memory_merge=lambda: merged.append(1) or (0, 0),
        batch={"ops": [{"op": "frobnicate", "name": PARAM}]}, run=(2, 3),
    )
    assert merged == [1] and done.version == 6 and not done.applied
    assert done.error is not None and "frobnicate" in done.error
    assert live.diagnostics and live.diagnostics[0]["kind"] == "learner_batch_refused"
    assert live.diagnostics[0]["run"] == (2, 3)
    assert live.pending_entries() == [] and live.revision == 0


def test_a_learners_skipped_op_is_recorded_not_fatal(live):
    stale = {"op": "set_param", "name": PARAM, "to": 30, "expect": 999}
    done = live.finish_run(memory_merge=lambda: None, batch={"ops": [stale]})
    assert not done.applied and done.error is None
    assert param(live) != 30


def test_diagnose_keeps_what_a_failing_learner_did(live):
    live.diagnose("learner_raised", "ValueError: boom", run=(1, 2))
    assert live.diagnostics == [
        {"kind": "learner_raised", "run": (1, 2), "episode_version": 5, "message": "ValueError: boom"}]


def test_the_summary_block(live):
    block = live.summary()
    tables = reference_document().tables
    assert block == {
        "id": 7, "version": 0, "hash": live.config_hash, "base_hash": "b" * 64,
        "nodes": len(tables["slipnet_node_defs"]), "links": len(tables["slipnet_link_defs"]),
        "last_change_version": None, "frozen": False,
    }
    live.submit(external(set_param(16)))
    assert live.summary()["version"] == 1 and live.summary()["last_change_version"] == 6
    assert live.summary()["hash"] != block["hash"]


def test_the_log_maps_a_version_back_to_its_revision(live):
    live.finish_run(memory_merge=lambda: None)          # 6: no change
    live.submit(external(set_param(16)))                # 7: revision 1
    live.finish_run(memory_merge=lambda: None)          # 8
    live.submit(external(set_param(17)))                # 9: revision 2
    assert [live.log.configuration_revision_at(v) for v in range(5, 10)] == [0, 0, 1, 1, 2]


def test_the_provider_follows_the_document_and_is_shared_where_unchanged(live):
    before = live.provider
    live.submit(external(set_param(16)))
    after = live.provider
    assert after is not before and after.get_param(PARAM) == 16
    assert after.slipnet_node_specs is before.slipnet_node_specs  # an untouched field is shared
    assert cd.config_hash(live.document) == provider_hash(after)
