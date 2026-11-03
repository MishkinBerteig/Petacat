"""EpisodeLog: the episode layer (S1).  Merge semantics, interleavings, fuzz, reduction to serial."""

from __future__ import annotations

import itertools
import random

import pytest

from server.services import config_document as cd
from server.services.session_episode import EpisodeLog, StaleBatch
from tests.unit._fake_resolve import Refused, fake_resolve

SEED_DIR = "seed_data"
NODE = "slipnet_node_defs"


@pytest.fixture(scope="module")
def base():
    return cd.document_from_standard_files(SEED_DIR)


def real_resolve_or_none():
    try:
        from server.services.change_resolve import resolve
    except ImportError:
        return None
    return resolve


class FakeDialect:
    """Ops over a node's conceptual depth, for the stand-in resolver."""

    resolve = staticmethod(fake_resolve)

    def value(self, cfg):
        return cfg.tables[NODE][("plato-a",)]["conceptual_depth"]

    def adjust(self, by):
        return {"op": "adjust", "table": NODE, "key": {"name": "plato-a"}, "column": "conceptual_depth", "by": by}

    def setv(self, v, expect=None):
        op = {"op": "update", "table": NODE, "key": {"name": "plato-a"}, "set": {"conceptual_depth": v}}
        if expect is not None:
            op["expect"] = {"conceptual_depth": expect}
        return op

    def insert_existing(self, cfg):
        row = dict(cfg.tables[NODE][("plato-a",)])
        return {"op": "insert", "table": NODE, "key": {"name": "plato-a"}, "row": row}

    def remove_target_then_use_it(self, cfg):
        gone = {"op": "delete", "table": NODE, "key": {"name": "plato-b"}}
        use = [self.adjust(1) | {"key": {"name": "plato-b"}}, self.setv(0) | {"key": {"name": "plato-b"}}]
        return gone, use


class RealDialect:
    """The same four needs, in C14a's dialect: a parameter, ``fields`` and ``expect``."""

    PARAM = "update_cycle_length"

    def __init__(self):
        from server.services.change_resolve import resolve

        self.resolve = resolve

    def value(self, cfg):
        return int(cfg.tables["engine_params"][(self.PARAM,)]["value"])

    def adjust(self, by):
        return {"op": "adjust_param", "name": self.PARAM, "by": by}

    def setv(self, v, expect=None):
        op = {"op": "update", "table": "engine_params", "key": {"name": self.PARAM}, "fields": {"value": str(v)}}
        if expect is not None:
            op["expect"] = {"value": str(expect)}
        return op

    def insert_existing(self, cfg):
        return {"op": "insert", "table": "engine_params", "row": dict(cfg.tables["engine_params"][(self.PARAM,)])}

    def remove_target_then_use_it(self, cfg):
        gone = {"op": "delete", "table": "demo_problems", "key": {"name": "run1"}}
        use = [
            {"op": "update", "table": "demo_problems", "key": {"name": "run1"}, "fields": {"target": "x"}},
            {"op": "delete", "table": "demo_problems", "key": {"name": "run1"}},
        ]
        return gone, use


@pytest.fixture(params=["fake", "real"])
def dx(request):
    if request.param == "fake":
        return FakeDialect()
    if real_resolve_or_none() is None:
        pytest.skip("change_resolve not landed")
    return RealDialect()


def depth(cfg, name="plato-a"):
    return cfg.tables[NODE][(name,)]["conceptual_depth"]


def adjust(by, name="plato-a"):
    return {"op": "adjust", "table": NODE, "key": {"name": name}, "column": "conceptual_depth", "by": by}


def set_depth(v, expect=None, name="plato-a"):
    op = {"op": "update", "table": NODE, "key": {"name": name}, "set": {"conceptual_depth": v}}
    if expect is not None:
        op["expect"] = {"conceptual_depth": expect}
    return op


def batch(*ops, **kw):
    return {"ops": list(ops), "source": "learner", "actor": "learner:t", **kw}


def rebase(*ops, **kw):
    return batch(*ops, base_mode="rebase", on_op_failure="skip", **kw)


@pytest.fixture
def log(base):
    return EpisodeLog(base, fake_resolve)


# --- counters and entries -------------------------------------------------------------------


def test_fresh_log_starts_at_the_base(base, log):
    assert log.version == base.version == log.configuration_revision
    assert log.entries == () and log.current is base


def test_empty_run_entry_takes_a_version_and_no_configuration_change(log):
    r = log.finish_run(memory_merge=lambda: "m1")
    assert r.entry.seq == 1 and r.entry.memory == "m1" and not r.applied
    assert log.version == 1 and log.configuration_revision == 0
    assert r.entry.resolved_ops == () and r.entry.configuration_revision == 0


def test_run_entry_with_batch_takes_one_version_for_memory_and_configuration(log):
    order = []
    r = log.finish_run(memory_merge=lambda: order.append("memory") or "mm", batch=rebase(adjust(2)))
    assert order == ["memory"]
    assert (r.entry.seq, r.entry.configuration_revision, log.version) == (1, 1, 1)
    assert r.entry.memory == "mm" and r.applied


def test_memory_merge_runs_before_the_batch_is_resolved(base):
    seen = []

    def resolver(cfg, b):
        seen.append(("resolve", len(order)))
        return fake_resolve(cfg, b)

    order = []
    lg = EpisodeLog(base, resolver)
    lg.finish_run(memory_merge=lambda: order.append(1), batch=rebase(adjust(1)))
    assert seen == [("resolve", 1)]


def test_seq_is_never_below_configuration_revision(log):
    log.finish_run()
    log.submit_batch(rebase(adjust(1)))
    log.finish_run()
    log.finish_run(batch=rebase(adjust(1)))
    assert log.version == 4 and log.configuration_revision == 4
    log.finish_run()
    assert log.version == 5 and log.configuration_revision == 4
    for e in log.entries:
        assert e.seq >= e.configuration_revision


def test_external_batch_with_nothing_applying_takes_no_version(log):
    r = log.submit_batch(batch(set_depth(1, expect=-99), on_op_failure="skip", base_mode="rebase"))
    assert r.entry.seq is None and not r.applied and log.version == 0
    assert log.entries == () and log.diagnostics == (r.entry,)
    assert r.entry.skipped and r.entry.skipped[0]["reason"] == "expect_failed"
    r2 = log.submit_batch(batch(on_op_failure="skip", base_mode="rebase"))  # empty batch
    assert r2.entry.seq is None and len(log.diagnostics) == 2


def test_external_batch_that_applies_takes_the_next_version_with_no_memory(log):
    log.finish_run()
    r = log.submit_batch(rebase(adjust(3)))
    assert r.entry.seq == 2 and r.entry.memory is None and r.entry.kind == "batch"
    assert depth(log.current) == depth(log.base) + 3


def test_dry_run_changes_nothing(log, base):
    r = log.submit_batch(rebase(adjust(5), dry_run=True))
    assert not r.applied and log.version == 0 and log.current is base
    assert log.entries == () and log.diagnostics == ()
    assert r.report["applied"] == 1


def test_preview_changes_nothing(log, base):
    ops, report = log.preview(rebase(adjust(1)))
    assert len(ops) == 1 and report["applied"] == 1 and log.version == 0 and log.current is base


def test_entry_records_proposed_batch_resolved_ops_report_and_hash(log):
    b = rebase(adjust(2))
    r = log.finish_run(batch=b, run="run-1")
    e = r.entry
    assert e.proposed_batch == b and e.run == "run-1"
    assert e.resolved_ops == ({"op": "update", "table": NODE, "key": {"name": "plato-a"},
                               "set": {"conceptual_depth": depth(log.base) + 2}},)
    assert e.report["applied"] == 1
    assert e.config_hash == log.config_hash() != cd.config_hash(log.base)


def test_unchanged_configuration_keeps_the_base_hash(log, base):
    log.finish_run()
    assert log.config_hash() == cd.config_hash(base) == log.entries[0].config_hash


# --- merge semantics ---------------------------------------------------------------------------


def test_relative_ops_commute_two_plus_two_give_plus_four(base, dx):
    lg = EpisodeLog(base, dx.resolve)
    # two runs started from the same cut (revision 0); both add 2
    lg.finish_run(batch=rebase(dx.adjust(2), base_version=0))
    lg.finish_run(batch=rebase(dx.adjust(2), base_version=0))
    assert dx.value(lg.current) == dx.value(base) + 4
    assert [e.seq for e in lg.entries] == [1, 2]


def test_relative_ops_are_independent_of_order(base):
    for order in itertools.permutations([1, 2, 3]):
        lg = EpisodeLog(base, fake_resolve)
        for by in order:
            lg.finish_run(batch=rebase(adjust(by)))
        assert depth(lg.current) == depth(base) + 6


def test_absolute_ops_with_expect_first_merged_wins_and_loser_is_recorded(base, dx):
    d0 = dx.value(base)
    lg = EpisodeLog(base, dx.resolve)
    a = lg.finish_run(batch=rebase(dx.setv(d0 + 1, expect=d0)))
    b = lg.finish_run(batch=rebase(dx.setv(d0 + 2, expect=d0)))
    assert dx.value(lg.current) == d0 + 1
    assert a.applied and not b.applied
    assert b.entry.seq == 2 and b.entry.resolved_ops == ()
    assert len(b.entry.skipped) == 1


def test_loser_with_abort_is_refused_and_for_a_run_recorded_as_an_error(base):
    d0 = depth(base)
    lg = EpisodeLog(base, fake_resolve)
    lg.finish_run(batch=rebase(set_depth(d0 + 1, expect=d0)))
    loser = batch(set_depth(d0 + 2, expect=d0), base_mode="rebase")  # on_op_failure abort
    r = lg.finish_run(memory_merge=lambda: "kept", batch=loser)
    assert r.entry.seq == 2 and r.entry.memory == "kept" and r.entry.error
    assert depth(lg.current) == d0 + 1
    with pytest.raises(Refused):
        lg.submit_batch(loser)
    assert lg.version == 2 and lg.diagnostics == ()


def test_external_refusal_changes_nothing(base):
    lg = EpisodeLog(base, fake_resolve)
    lg.finish_run(batch=rebase(adjust(1)))
    snap = (lg.version, lg.current, len(lg.entries))
    with pytest.raises(StaleBatch):
        lg.submit_batch(batch(adjust(1), base_version=0))  # strict, stale
    assert (lg.version, lg.current, len(lg.entries)) == snap


def test_strict_batch_against_current_revision_applies(log):
    log.finish_run(batch=rebase(adjust(1)))
    assert log.submit_batch(batch(adjust(1), base_version=log.configuration_revision)).applied


def test_base_mode_and_on_op_failure_pass_through_unchanged(base):
    seen = []

    def spy(cfg, b):
        seen.append((b["base_mode"], b["on_op_failure"], b["base_version"]))
        return fake_resolve(cfg, b)

    lg = EpisodeLog(base, spy)
    lg.submit_batch(batch(adjust(1), base_mode="rebase", on_op_failure="skip", base_version="head"))
    lg.finish_run(batch=batch(adjust(1), base_mode="strict", on_op_failure="abort", base_version=1))
    assert seen == [("rebase", "skip", "head"), ("strict", "abort", 1)]


def test_insert_of_an_existing_key_is_a_conflict_not_deduplicated(base, dx):
    ins = dx.insert_existing(base)
    lg = EpisodeLog(base, dx.resolve)
    r = lg.finish_run(batch=rebase(ins))
    assert not r.applied and r.entry.skipped
    with pytest.raises(Exception):
        lg.submit_batch(batch(ins, base_mode="rebase"))  # abort
    assert lg.current is base


def test_two_inserts_of_the_same_new_key_first_wins(base):
    row = dict(base.tables[NODE][("plato-a",)], name="x-new", conceptual_depth=11)
    row2 = dict(row, conceptual_depth=22)
    mk = lambda r: {"op": "insert", "table": NODE, "key": {"name": "x-new"}, "row": r}
    lg = EpisodeLog(base, fake_resolve)
    lg.finish_run(batch=rebase(mk(row)))
    r = lg.finish_run(batch=rebase(mk(row2)))
    assert lg.current.tables[NODE][("x-new",)]["conceptual_depth"] == 11
    assert r.entry.skipped[0]["reason"] == "key_exists"


def test_targets_removed_since_the_snapshot_are_skipped(base, dx):
    gone, use = dx.remove_target_then_use_it(base)
    lg = EpisodeLog(base, dx.resolve)
    lg.submit_batch(rebase(gone))
    r = lg.finish_run(batch=rebase(*use, dx.adjust(1)))
    assert dx.value(lg.current) == dx.value(base) + 1
    assert len(r.entry.skipped) == len(use) and len(r.entry.resolved_ops) == 1


def test_a_skipped_op_does_not_stop_the_rest(base):
    lg = EpisodeLog(base, fake_resolve)
    r = lg.finish_run(batch=rebase(set_depth(1, expect=-1), adjust(5)))
    assert depth(lg.current) == depth(base) + 5 and len(r.entry.skipped) == 1


def test_ops_in_one_batch_see_earlier_ops(log, base):
    log.finish_run(batch=rebase(adjust(1), adjust(1), adjust(1)))
    assert depth(log.current) == depth(base) + 3


def test_determinism_same_inputs_same_log(base):
    def play():
        lg = EpisodeLog(base, fake_resolve)
        lg.finish_run(memory_merge=lambda: "a", batch=rebase(adjust(2)))
        lg.submit_batch(rebase(set_depth(7, expect=depth(base) + 2)))
        lg.finish_run(batch=rebase(adjust(-1)))
        lg.submit_batch(rebase(set_depth(1, expect=-5)))
        return lg

    a, b = play(), play()
    assert [(e.seq, e.resolved_ops, e.config_hash, e.skipped) for e in a.entries] == [
        (e.seq, e.resolved_ops, e.config_hash, e.skipped) for e in b.entries
    ]
    assert a.config_hash() == b.config_hash()


# --- config_at ---------------------------------------------------------------------------------


def test_config_at_every_version_matches_the_entry_hash(base):
    lg = EpisodeLog(base, fake_resolve)
    lg.finish_run(batch=rebase(adjust(1)))
    lg.finish_run()
    lg.submit_batch(rebase(adjust(2)))
    lg.finish_run(batch=rebase(set_depth(0, expect=-1)))
    lg.finish_run(batch=rebase(adjust(3)))
    for e in lg.entries:
        cfg = lg.config_at(e.seq)
        assert cd.config_hash(cfg) == e.config_hash
        assert cfg.version == e.configuration_revision
    assert lg.config_at(0).content_equals(base)
    assert lg.config_at(lg.version).content_equals(lg.current)
    assert depth(lg.config_at(2)) == depth(base) + 1
    assert lg.configuration_revision_at(2) == 1
    with pytest.raises(ValueError):
        lg.config_at(lg.version + 1)
    with pytest.raises(ValueError):
        lg.config_at(-1)


# --- interleavings -------------------------------------------------------------------------------


def _run_batches(base):
    d0 = depth(base)
    return [
        rebase(adjust(2), base_version=0),
        rebase(adjust(3), set_depth(d0 + 10, expect=d0), base_version=0),
        rebase(set_depth(d0 + 20, expect=d0), adjust(-1, name="plato-b"), base_version=0),
    ]


def test_every_interleaving_equals_applying_in_that_order(base):
    """Three runs start from one cut; whatever order they finish in, the result is sequential."""
    batches = _run_batches(base)
    for order in itertools.permutations(range(3)):
        lg = EpisodeLog(base, fake_resolve)
        for i in order:
            lg.finish_run(batch=batches[i], run=i)
        ref = base
        for i in order:  # the reference: each batch resolved against the state it meets
            ops, _ = fake_resolve(ref, batches[i])
            ref = cd.apply_resolved(ref, ops)
        assert ref.content_equals(lg.current), order
        assert [e.run for e in lg.entries] == list(order)
        assert [e.seq for e in lg.entries] == [1, 2, 3]


def test_interleaving_outcomes_by_winner(base):
    d0 = depth(base)
    batches = _run_batches(base)
    for order in itertools.permutations(range(3)):
        lg = EpisodeLog(base, fake_resolve)
        for i in order:
            lg.finish_run(batch=batches[i])
        # run 1's absolute op sets d0+10, run 2's sets d0+20; the first merged wins (expect d0 fails
        # for the other).  Run 0 (+2) and run 1's +3 are relative.  Run 1's +3 comes first in its
        # batch; its set applies after +3 only if expect d0 still holds, which +3 breaks: run 1's
        # set is therefore always skipped, and run 2's wins unless run 0 or run 1 touched the node.
        final = depth(lg.current)
        touched_before_2 = [i for i in order[: order.index(2)] if i in (0, 1)]
        if touched_before_2:
            assert final == d0 + sum({0: 2, 1: 3}[i] for i in order if i in (0, 1))
        else:
            assert final == d0 + 20 + sum({0: 2, 1: 3}[i] for i in order[order.index(2) + 1 :] if i in (0, 1))


def test_external_batches_interleaved_with_runs_enter_at_recorded_positions(base):
    lg = EpisodeLog(base, fake_resolve)
    lg.finish_run(batch=rebase(adjust(1)))
    ext = lg.submit_batch(rebase(adjust(10)))
    lg.finish_run(batch=rebase(adjust(1)))
    assert [e.kind for e in lg.entries] == ["run", "batch", "run"]
    assert ext.entry.seq == 2 and depth(lg.current) == depth(base) + 12


# --- memory-named node removal ---------------------------------------------------------------------


def test_removing_a_node_that_memory_names_succeeds_and_later_runs_still_merge(base):
    memory_names = {"theme": "plato-b"}
    lg = EpisodeLog(base, fake_resolve)
    lg.finish_run(memory_merge=lambda: dict(memory_names))
    delete = {"op": "delete", "table": NODE, "key": {"name": "plato-b"}}
    ext = lg.submit_batch(batch(delete, base_mode="rebase"))
    assert ext.applied and ("plato-b",) not in lg.current.tables[NODE]
    r = lg.finish_run(memory_merge=lambda: dict(memory_names), batch=rebase(adjust(1)))
    assert r.entry.seq == 3 and r.entry.memory == memory_names and r.applied
    # the journal restores the node: config_at before the removal still has it
    assert ("plato-b",) in lg.config_at(1).tables[NODE]
    assert ("plato-b",) not in lg.config_at(2).tables[NODE]


def test_removal_from_a_run_batch_also_succeeds(base):
    lg = EpisodeLog(base, fake_resolve)
    delete = {"op": "delete", "table": NODE, "key": {"name": "plato-c"}}
    r = lg.finish_run(memory_merge=lambda: {"names": ["plato-c"]}, batch=rebase(delete))
    assert r.applied and ("plato-c",) not in lg.current.tables[NODE]


# --- exact reduction to serial ---------------------------------------------------------------------


def test_one_worker_equals_the_serial_reference(base):
    """With one worker each run starts after the previous merged; the stream is a function of inputs."""
    rng = random.Random(7)
    plan = []
    for _ in range(25):
        plan.append((rng.choice([None, "ext"]), rng.randint(-3, 3), rng.randint(0, 2)))

    # reference: a naive loop with a plain current document and a counter
    ref, ver, ref_stream = base, 0, []
    # system under test
    lg = EpisodeLog(base, fake_resolve)
    for ext, by, flavour in plan:
        b = rebase(adjust(by)) if flavour else rebase(set_depth(by, expect=depth(ref)))
        # a run starting now carries the revision it saw
        b = dict(b, base_version=ref.version)
        if ext:
            ops, _ = fake_resolve(ref, b)
            if ops:
                ver += 1
                ref = cd.apply_resolved(ref, ops, version=ver)
                ref_stream.append((ver, cd.config_hash(ref)))
            lg.submit_batch(b)
        else:
            ops, _ = fake_resolve(ref, b)
            ver += 1
            if ops:
                ref = cd.apply_resolved(ref, ops, version=ver)
            ref_stream.append((ver, cd.config_hash(ref)))
            lg.finish_run(batch=b)
    assert [(e.seq, e.config_hash) for e in lg.entries] == ref_stream
    assert lg.version == ver and lg.config_hash() == cd.config_hash(ref)


def test_one_worker_every_batch_applies_in_strict_mode(base):
    """Serial: base_version is always current, so strict batches never go stale."""
    lg = EpisodeLog(base, fake_resolve)
    for k in range(10):
        r = lg.finish_run(batch=batch(adjust(1), base_version=lg.configuration_revision))
        assert r.applied and not r.entry.error
    assert depth(lg.current) == depth(base) + 10


# --- fuzz ------------------------------------------------------------------------------------------


def _random_batch(rng, cfg, seen_rev):
    names = ["plato-a", "plato-b", "plato-c", "plato-d", "ghost"]
    ops = []
    for _ in range(rng.randint(0, 4)):
        n = rng.choice(names)
        k = rng.choice(["adjust", "set", "expect_set", "delete", "insert"])
        if k == "adjust":
            ops.append(adjust(rng.randint(-5, 5), name=n))
        elif k == "set":
            ops.append(set_depth(rng.randint(0, 10), name=n))
        elif k == "expect_set":
            ops.append(set_depth(rng.randint(0, 10), expect=rng.randint(0, 10), name=n))
        elif k == "delete":
            ops.append({"op": "delete", "table": NODE, "key": {"name": n}})
        else:
            row = dict(next(iter(cfg.tables[NODE].values())), name=f"f-{rng.randint(0, 5)}")
            ops.append({"op": "insert", "table": NODE, "key": {"name": row["name"]}, "row": row})
    mode = rng.choice(["rebase", "strict"])
    return {
        "ops": ops,
        "base_mode": mode,
        "on_op_failure": rng.choice(["skip", "abort"]),
        "base_version": seen_rev,
        "source": "learner",
        "actor": "learner:fuzz",
    }


@pytest.mark.parametrize("seed", range(12))
def test_fuzz_invariants_and_replay(base, seed):
    rng = random.Random(seed)
    lg = EpisodeLog(base, fake_resolve)
    in_flight = []  # (batch, revision seen at dispatch)
    for _ in range(40):
        action = rng.choice(["dispatch", "finish", "finish", "external"])
        if action == "dispatch":
            in_flight.append(_random_batch(rng, lg.current, lg.configuration_revision))
        elif action == "finish" and in_flight:
            b = in_flight.pop(rng.randrange(len(in_flight)))
            lg.finish_run(memory_merge=lambda: "m", batch=b if rng.random() < 0.8 else None)
        else:
            try:
                lg.submit_batch(_random_batch(rng, lg.current, lg.configuration_revision))
            except Refused:
                pass
        assert lg.version >= lg.configuration_revision
    # versions are consecutive from 1; each entry's hash is reproducible from the base
    assert [e.seq for e in lg.entries] == list(range(1, lg.version + 1))
    for e in lg.entries:
        assert e.seq >= e.configuration_revision
        assert cd.config_hash(lg.config_at(e.seq)) == e.config_hash
    # replaying only the stored resolved ops from the base reproduces the final configuration
    cfg = base
    for e in lg.entries:
        if e.resolved_ops:
            cfg = cd.apply_resolved(cfg, e.resolved_ops, version=e.seq)
    assert cfg.content_equals(lg.current) and cfg.version == lg.configuration_revision
    # the whole run is deterministic: same seed, same final hash
    rng2 = random.Random(seed)
    lg2 = EpisodeLog(base, fake_resolve)
    in_flight = []
    for _ in range(40):
        action = rng2.choice(["dispatch", "finish", "finish", "external"])
        if action == "dispatch":
            in_flight.append(_random_batch(rng2, lg2.current, lg2.configuration_revision))
        elif action == "finish" and in_flight:
            b = in_flight.pop(rng2.randrange(len(in_flight)))
            lg2.finish_run(memory_merge=lambda: "m", batch=b if rng2.random() < 0.8 else None)
        else:
            try:
                lg2.submit_batch(_random_batch(rng2, lg2.current, lg2.configuration_revision))
            except Refused:
                pass
    assert lg2.config_hash() == lg.config_hash() and lg2.version == lg.version


# --- removal, rename and merge of a node that memory names, through the real resolve ---------------


@pytest.mark.parametrize(
    "op",
    [
        {"op": "remove_node", "name": "plato-opposite"},
        {"op": "rename_node", "old": "plato-opposite", "new": "plato-contrary"},
        {"op": "merge_nodes", "keep": "plato-a", "drop": "plato-b"},
    ],
    ids=["remove", "rename", "merge"],
)
@pytest.mark.parametrize("via", ["run", "external"])
def test_removing_renaming_merging_a_memory_named_node_succeeds_from_either_entry(base, op, via):
    resolve = pytest.importorskip("server.services.change_resolve").resolve
    named = op.get("name") or op.get("old") or op.get("drop")
    lg = EpisodeLog(base, resolve)
    lg.finish_run(memory_merge=lambda: {"names": [named]})
    b = batch(op, base_mode="rebase", on_op_failure="abort")
    r = lg.finish_run(memory_merge=lambda: {"names": [named]}, batch=b) if via == "run" else lg.submit_batch(b)
    assert r.applied and not r.entry.error
    assert (named,) not in lg.current.tables[NODE]
    assert (named,) in lg.config_at(1).tables[NODE]  # the earlier version still has it
    nxt = lg.finish_run(memory_merge=lambda: {"names": [named]})  # the next run's memory still merges
    assert nxt.entry.memory == {"names": [named]} and nxt.entry.seq == lg.version
