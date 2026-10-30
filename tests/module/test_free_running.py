"""Free-running execution across worker threads (WP4.4).

The scaling numbers live in ``scripts/bench_free_running.py`` and need the free-threaded
interpreter to mean anything.  What is worth pinning here is *correctness*, which does not:
the GIL prevents simultaneous execution but not interleaving, so threads still switch
between bytecodes and the logical races are all reachable under either build.

The properties below are the ones whose absence would make the throughput numbers
worthless — a run that loses codelets, double-counts an answer, or lets two workers
allocate the same identifier is not a faster engine.
"""

from __future__ import annotations

import os
import threading

import pytest

from server.parallel.coderack_shards import LockedCoderack
from server.parallel.free_running import FreeRunningEngine, run_free
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.engine.splittable_rng import SplittableRNG
from server.engine.workspace_objects import WorkspaceObject

# Every test here executes arithmetic the numeric substrate owns, so each one runs
# once per backend in the matrix. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "seed_data",
)

PROBLEM = ("abc", "abd", "mrrjjj")


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


def _prepared(meta, seed: int = 42) -> EngineRunner:
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=seed)
    return runner


# --- it runs, and finishes --------------------------------------------------


@pytest.mark.parametrize("workers", [1, 2, 4, 8])
def test_a_free_run_completes_at_every_worker_count(meta, workers):
    result = run_free(_prepared(meta), workers=workers, max_steps=900)
    assert result.codelet_count > 0
    assert result.status in {"answer_found", "halted", "gave_up"}
    assert result.workers == workers


def test_every_worker_does_some_work(meta):
    """A configuration where one worker does everything is not parallel.

    The failure this catches is real and was live: the pool used to be built *while
    the first worker was already executing*, and ``Thread.start()`` ends in
    ``self._started.wait()``.  A worker running interpreted codelet bodies makes no
    call that releases the GIL, so the main thread could lose that handoff for the
    whole run — one ``start()`` measured at 466 ms of a 465 ms run — and threads 2..N
    were never constructed at all.  ``_per_worker`` is preallocated to the requested
    width, so the telemetry read ``[4001, 0, 0, 0]``: three workers reported as idle
    that had never existed.  It failed about 40% of the time, bimodally — either an
    even split or a total monopoly, nothing in between.

    ``FreeRunningEngine._all_started`` now gates the workers until the pool is built,
    which is also what removes this test's old precondition.  It used to require
    ``codelet_count > 2000`` before judging the distribution, because "the last thread
    started can legitimately never be scheduled before the stop flag is set" — true
    when the threads started at different times, and no longer true when they all wait
    for the same Event.  Keeping it would have made the test fail on exactly the runs
    the fix improved: four workers genuinely running answer this problem before 2,000
    codelets more often than one worker did.
    """
    runner = EngineRunner(meta)
    runner.init_mcat("eeqee", "qeeq", "xxixx", seed=42)
    result = run_free(runner, workers=4, max_steps=4000)

    assert len(result.per_worker) == 4
    assert all(count > 0 for count in result.per_worker), result.per_worker
    # And no single worker monopolised it.
    assert max(result.per_worker) < 0.9 * result.codelet_count, result.per_worker


def test_the_codelet_count_is_the_sum_of_what_workers_did(meta):
    """No codelet lost and none counted twice.

    ``codelet_count`` is incremented under a lock and is what the trace, the sink and
    every capture are stamped with, so a lost increment would corrupt the record rather
    than merely miscount.
    """
    result = run_free(_prepared(meta), workers=4, max_steps=900)
    assert sum(result.per_worker) == result.codelet_count


def test_an_answer_is_reported_exactly_once(meta):
    """Several workers can notice the same pending answer.

    Without the guarded hand-off the run would append it once per worker, and Episodic
    Memory would accumulate duplicates of a single discovery.
    """
    for seed in (7, 42, 12345):
        runner = _prepared(meta, seed=seed)
        result = run_free(runner, workers=8, max_steps=3000)
        if result.status == "answer_found":
            assert len(result.answers) == 1, result.answers
            assert result.answers == runner._answers


def test_a_free_run_produces_a_valid_workspace(meta):
    """Structures must be as internally consistent as the serial engine leaves them.

    The commit lock exists because ``build_structure``'s duplicate check and fights are
    read-modify-write sequences over shared lists; if it were not held, this is where the
    corruption would show.

    **The invariants below were chosen by measuring the serial engine, not by intuition.**
    The obvious assertion — that every bond's objects are in their string's ``objects``
    list — is *not* one Petacat has ever satisfied: breaking a group removes it from the
    string while bonds attached to it survive, and a serial run with the numeric substrate
    off produces 86 such bonds out of 1,283 across 200 runs. An earlier version of this
    test asserted it and failed intermittently under free-running, which read as a
    concurrency defect and was not one. What free-running must not do is make the
    Workspace *worse* than serial leaves it, so these are the properties a serial run does
    hold, verified over 200 runs before being asserted here.
    """
    runner = _prepared(meta)
    run_free(runner, workers=8, max_steps=1500)
    ws = runner.ctx.workspace

    for string in ws.all_strings:
        for bond in string.bonds:
            # A bond belongs to the string whose objects it relates, even when one of
            # those objects has since been broken out of the string.
            assert bond.from_object.string is string
            assert bond.to_object.string is string
        for group in string.groups:
            # A group that is still listed as a group is still an object of the string;
            # ``remove_group`` takes it out of both together or neither.
            assert group in string.objects
            assert group.string is string
            for member in group.objects:
                assert member.string is string
        for obj in string.objects:
            assert obj.string is string

    for bridge in ws.top_bridges + ws.bottom_bridges + ws.vertical_bridges:
        assert bridge.object1.string in ws.all_strings
        assert bridge.object2.string in ws.all_strings


def test_identifiers_are_unique_across_workers(meta):
    """Every worker binds the run's allocator for itself.

    The binding is a ``ContextVar``, so a thread that failed to set it would fall back to
    the process-wide allocator and issue identifiers colliding with another worker's —
    the defect WP0.3 removed, reintroduced by threading.
    """
    runner = _prepared(meta)
    run_free(runner, workers=8, max_steps=1500)
    ctx = runner.ctx

    object_ids = [o.id for o in ctx.workspace.all_objects]
    assert len(object_ids) == len(set(object_ids))

    event_numbers = [e.event_number for e in ctx.trace.events]
    assert len(event_numbers) == len(set(event_numbers))
    assert event_numbers == sorted(event_numbers)


def test_the_locked_rack_is_installed_and_drains(meta):
    runner = _prepared(meta)
    engine = FreeRunningEngine(runner, workers=4)
    engine.prepare()
    assert isinstance(runner.ctx.coderack, LockedCoderack)
    # The opening codelets were carried over rather than discarded.
    assert runner.ctx.coderack.total_count > 0


def test_conflicts_are_reported_as_telemetry(meta):
    """The conflict rate is what says how much staleness a configuration produces.

    It is deliberately *telemetry* rather than a rollback: a codelet's writes land as it
    makes them, so validation reports what happened rather than preventing it. Asserted
    as a bounded rate rather than zero, because a nonzero rate under concurrency is the
    expected and correct observation.
    """
    result = run_free(_prepared(meta), workers=8, max_steps=1500)
    assert 0.0 <= result.conflict_rate <= 1.0
    assert result.conflicts <= result.codelet_count


def test_update_cycles_run_without_stopping_the_workers(meta):
    """Roughly one per fifteen codelets, and not a barrier.

    Whichever worker crosses the boundary runs it while the others continue, which is the
    staleness WP0.5 bounded at five codelets.
    """
    result = run_free(_prepared(meta), workers=4, max_steps=900)
    expected = result.codelet_count // 15
    assert result.update_cycles > 0
    # Within a wide band: workers cross boundaries concurrently, so the count is
    # approximate by construction rather than exact.
    assert 0.5 * expected <= result.update_cycles <= 1.5 * expected + 2


# --- every draw inside a codelet comes from that codelet's stream -----------


def test_a_codelet_stream_is_bound_per_thread(meta):
    """``ctx.rng`` resolves per thread while a codelet holds a stream.

    It was a plain attribute, swapped around each codelet and restored afterwards.
    That is shared state: worker A's swap was visible to worker B, so B ran against
    A's stream — or, once A restored, against the run's own ``random.Random``, which
    two threads drawing from concurrently is a data race under the free-threaded
    interpreter rather than merely a reordering.
    """
    runner = _prepared(meta)
    ctx = runner.ctx
    run_rng = ctx.rng

    entered = threading.Event()
    release = threading.Event()
    seen_by_the_other_thread = []

    def holder():
        with ctx.use_codelet_rng(SplittableRNG(1, stream=99)):
            entered.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert entered.wait(5)
    # This thread has bound nothing, so it still sees the run's generator.
    seen_by_the_other_thread.append(ctx.rng)
    release.set()
    thread.join(5)

    assert seen_by_the_other_thread == [run_rng]
    # And the binding leaves nothing behind when it unwinds.
    assert ctx.rng is run_rng


def test_the_density_walk_draws_from_the_codelets_own_stream(meta):
    """The stochastic neighbour walk must not reach past its codelet for randomness.

    Bond and group external strength is local density (``bonds.ss:136-160``,
    ``groups.ss:354-383``), and every step of that walk is a salience-weighted
    stochastic pick, re-rolled on each strength update. The walk used to read an RNG
    hung off the Workspace — the run's single shared generator — which both bypassed
    the per-codelet streams free-running derives from ``(seed, worker, slot)`` and put
    one ``random.Random`` in reach of every worker at once.

    Recorded at the pick itself, and only where a pick is real: a position offering
    one candidate is returned without drawing, so the draws counted here are the ones
    where two or more objects are edged at a walk position — which needs groups, and
    is why the problem is ``mrrjjj``.

    The sharp assertion is the last one. A stream is created by the worker thread
    that is about to run the codelet, so "created on the thread that drew from it"
    says the walk used *this* codelet's stream and not a neighbour's. Measured
    against the mechanism this replaced — a codelet's stream assigned to a shared
    ``ctx.rng`` — 16 of 159 draws at four workers came from another thread's stream.
    """
    runner = _prepared(meta)
    ctx = runner.ctx
    run_rng = ctx.rng

    #: ``id(stream) -> the thread that asked for it``.
    owner: dict[int, int] = {}
    make_stream = SplittableRNG.for_codelet
    original = WorkspaceObject._pick_neighbor
    drawn: list[tuple[bool, object, int]] = []
    lock = threading.Lock()

    def for_codelet(self, worker, slot):
        stream = make_stream(self, worker, slot)
        with lock:
            owner[id(stream)] = threading.get_ident()
        return stream

    def recording(self, neighbors, rng):
        if len(neighbors) > 1:
            # ``access.current`` is per-thread and is set for exactly the span of
            # ``_execute_codelet``, so it says whether this walk is a codelet's or the
            # update cycle's.
            recorder = ctx.access
            inside = recorder is not None and recorder.current is not None
            with lock:
                drawn.append((inside, rng, threading.get_ident()))
        return original(self, neighbors, rng)

    SplittableRNG.for_codelet = for_codelet
    WorkspaceObject._pick_neighbor = recording
    try:
        run_free(runner, workers=4, max_steps=2500)
    finally:
        WorkspaceObject._pick_neighbor = original
        SplittableRNG.for_codelet = make_stream

    inside_a_codelet = [(rng, ident) for inside, rng, ident in drawn if inside]
    assert inside_a_codelet, (
        "no density walk drew inside a codelet, so this test proved nothing; the "
        "problem must build groups for a walk position to offer two candidates"
    )
    assert all(isinstance(rng, SplittableRNG) for rng, _ in inside_a_codelet)
    assert all(rng is not run_rng for rng, _ in inside_a_codelet)
    foreign = [
        rng for rng, ident in inside_a_codelet if owner.get(id(rng), ident) != ident
    ]
    assert not foreign, f"{len(foreign)} draws came from another thread's stream"


def test_one_worker_still_uses_the_parallel_path(meta):
    """A one-worker free run is not the serial loop, and should not be mistaken for it.

    It exercises the same locked rack, the same commit lock and the same per-codelet
    streams, which is what makes it the right control for the multi-worker numbers.
    """
    runner = _prepared(meta)
    result = run_free(runner, workers=1, max_steps=600)
    assert result.workers == 1
    assert isinstance(runner.ctx.coderack, LockedCoderack)
    assert runner.ctx.commit_lock is not None
    assert result.codelet_count > 0


def test_the_serial_loop_is_untouched_by_free_running(meta):
    """Serial execution is the permanent reference mode.

    It must take no commit lock and use no sharded rack — the free-running machinery is a
    wrapper, not a mode the serial loop grew.
    """
    runner = _prepared(meta)
    runner.run_mcat(max_steps=300)
    assert runner.ctx.commit_lock is None
    assert not isinstance(runner.ctx.coderack, LockedCoderack)
    assert runner.ctx.access is None


def test_a_free_run_stores_exactly_one_answer_like_the_serial_loop(meta):
    """Episodic Memory must not gain an entry per racing worker.

    ``_collect_outcome`` de-duplicates the run's *status*, but each worker that reached
    ``report_answer`` had already written its own ``AnswerDescription``.  Across
    episodic runs that memory is shared with every later Run, so the pollution
    outlived the run that caused it — and because ``on_answer`` fires once, the database
    and the live memory silently disagreed about how many answers there were.

    Measured before the guard, at 8 workers: 22 of 40 runs stored 2-5 answers where the
    serial loop stores exactly 1.
    """
    for seed in range(6):
        runner = EngineRunner(meta)
        runner.init_mcat("abc", "abd", "mrrjjj", seed=seed)
        FreeRunningEngine(runner, workers=4).run(max_steps=2500)

        stored = len(runner.ctx.memory.answers)
        assert stored <= 1, (
            f"seed {seed}: {stored} answer descriptions stored for one run"
        )
        # And the run's own answer list agrees with what memory holds.
        assert len(runner._answers) == stored


def test_a_group_and_a_letter_never_share_an_identifier(meta):
    """A Group is the one thing that is both a WorkspaceObject and a WorkspaceStructure.

    Both base constructors run, and both assign ``self.id`` — from *different* counters.
    ``WorkspaceStructure.__init__`` ran second and won, so a Group sitting in
    ``all_objects`` carried a **structure** number while every Letter beside it carried an
    **object** number, and the two counters collide freely.  Observed serially on
    ``abc->abd;mrrjjj`` seed 8: ``Group(samegrp, 3 objects)`` and ``Letter(k, pos=3)``
    both at 60.

    This is not a threading defect — it reproduces under ``run_mcat`` — but the free-run
    identifier test is where it surfaced, because eight workers explore more of the seed
    space per run than one does.
    """
    from server.engine.runner import EngineRunner

    collisions = []
    for seed in range(30):
        runner = EngineRunner(meta)
        runner.init_mcat(*PROBLEM, seed=seed)
        runner.run_mcat(max_steps=1500)
        ids = [o.id for o in runner.ctx.workspace.all_objects]
        if len(ids) != len(set(ids)):
            collisions.append(seed)
    assert collisions == []


# --- what a snag deletes, and what runs whole -------------------------------


def test_the_answer_and_self_watching_codelets_run_under_the_commit_lock(meta):
    """They clamp, snag, give up and report, which rewrites what the update cycle owns.

    Run beside the scheduled update, a jootser that gave up ran a second update over the
    same Slipnet session (on MLX, an abort), and a clamp could land between the update
    reading the Slipnet and writing it back.
    """
    from server.parallel.free_running import SERIALISED_FAMILIES

    runner = _prepared(meta, seed=3)
    engine = FreeRunningEngine(runner, workers=4)
    engine.prepare()
    lock = runner.ctx.commit_lock
    execute = runner._execute_codelet
    held: dict[str, set[bool]] = {}

    def recording(codelet):
        held.setdefault(codelet.codelet_type, set()).add(lock._is_owned())
        return execute(codelet)

    runner._execute_codelet = recording
    engine.run(3000)

    families = {name: spec.family for name, spec in meta.codelet_specs.items()}
    serialised = {t: owned for t, owned in held.items() if families[t] in SERIALISED_FAMILIES}
    assert serialised, "no answer or self-watching codelet ran, so this proves nothing"
    assert all(owned == {True} for owned in serialised.values()), serialised


def test_a_codelet_chosen_before_the_rack_is_emptied_does_not_run(meta):
    """A snag's restart deletes every codelet (``answers.ss:1189``), including one a
    worker has already taken off the rack.  Serially such a codelet never runs; an
    answer-finder that did would report an answer from before the snag at the
    snag's temperature of 100.
    """
    runner = _prepared(meta)
    engine = FreeRunningEngine(runner, workers=2)
    engine.prepare()
    rack = runner.ctx.coderack
    choose = rack.choose_and_remove
    deleted: list = []

    def choose_then_restart(*args, **kwargs):
        codelet = choose(*args, **kwargs)
        if codelet is not None and not deleted:
            # What a snag on another worker does between this choice and its execution.
            deleted.append(codelet)
            rack.clear()
        return codelet

    rack.choose_and_remove = choose_then_restart
    execute = runner._execute_codelet
    ran: list = []
    runner._execute_codelet = lambda codelet: (ran.append(codelet), execute(codelet))[1]

    result = engine.run(600)

    assert deleted
    assert all(codelet is not deleted[0] for codelet in ran)
    assert result.discarded >= 1
    # The discarded codelet is not counted: the count is the codelets that ran.
    assert result.codelet_count == len(ran) == sum(result.per_worker)


@pytest.mark.parametrize("workers", [1, 4])
def test_a_run_stopped_by_its_budget_reports_the_codelets_it_ran(meta, workers):
    """Each worker that reached the budget used to count one codelet it never ran."""
    runner = _prepared(meta, seed=7)
    execute = runner._execute_codelet
    ran: list = []
    runner._execute_codelet = lambda codelet: (ran.append(codelet), execute(codelet))[1]

    result = run_free(runner, workers=workers, max_steps=300)

    if result.status == "halted":
        assert result.codelet_count == 300
    assert result.codelet_count == len(ran) == sum(result.per_worker)


def test_giving_up_runs_its_update_under_the_commit_lock():
    """``give-up`` runs one full update before it stops (``answers.ss:86-91``)."""
    from types import SimpleNamespace

    from server.engine.codelet_dsl.builtins import give_up

    lock = threading.RLock()
    owned: list[bool] = []
    ctx = SimpleNamespace(
        commit_lock=lock, on_update_everything=lambda: owned.append(lock._is_owned())
    )

    give_up(ctx)

    assert owned == [True]
    assert ctx._gave_up is True


# --- the free-running loop does what the serial loop does -------------------


def _record_in_codelet(runner, probe):
    """Wrap ``_execute_codelet`` so *probe* runs, in the worker's thread, just before it."""
    execute = runner._execute_codelet

    def wrapped(codelet):
        probe(codelet)
        return execute(codelet)

    runner._execute_codelet = wrapped


def test_a_codelet_sees_the_count_of_those_finished_before_it(meta):
    """``step-mcat`` runs a codelet and *then* increments (``run.ss:178-183``).

    Free-running incremented first, so every event, clamp and answer a codelet stamped
    was one higher than serially.
    """
    runner = _prepared(meta, seed=7)
    ctx = runner.ctx
    seen: list[tuple[int, int]] = []
    _record_in_codelet(
        runner, lambda c: seen.append((ctx.codelet_count, ctx.coderack.current_time))
    )

    result = run_free(runner, workers=1, max_steps=200)

    n = result.codelet_count
    assert n > 20
    assert [count for count, _ in seen] == list(range(n))
    assert [time for _, time in seen] == list(range(n))
    assert ctx.coderack.current_time == n


def test_structures_built_by_workers_are_stamped_with_the_clock(meta):
    """``set_structure_clock`` is thread-local, so the workers have to set it.

    Left unset, every structure made in a worker had ``time_stamp`` 0 and the
    progress-watcher's activity (the age of the youngest structure) was wrong.
    """
    from server.engine.workspace_structures import _clock

    runner = _prepared(meta, seed=7)
    ctx = runner.ctx
    clocks: list[tuple[int, int]] = []
    _record_in_codelet(
        runner, lambda c: clocks.append((getattr(_clock, "now", 0), ctx.codelet_count))
    )

    run_free(runner, workers=1, max_steps=200)

    assert all(now == count for now, count in clocks)
    assert clocks[-1][0] > 0
    stamps = [s.time_stamp for s in ctx.workspace.all_structures]
    assert stamps and max(stamps) > 0


def test_the_initial_unclamp_time_is_honoured(meta):
    """``run.ss:151-154``: the fixed-time release of the initial clamp, off by default."""
    runner = _prepared(meta, seed=7)
    ctx = runner.ctx
    released: list[int] = []
    runner._initial_unclamp_time = 20
    runner._unclamp_initial_slipnodes = lambda slipnet: released.append(ctx.codelet_count)

    run_free(runner, workers=1, max_steps=80)

    assert released == [20]


def test_a_pending_answer_is_not_collected_by_another_workers_codelet(meta):
    """The hand-off is per codelet: one worker's answer cannot vanish under it.

    ``_collect_outcome`` ran after every codelet and cleared ``ctx._pending_answer``
    whichever worker had set it, so an answer-family codelet that had just reported
    could find it gone while other workers finished their own codelets.
    """
    import time

    from server.parallel.free_running import SERIALISED_FAMILIES

    runner = _prepared(meta, seed=7)
    ctx = runner.ctx
    observed: list = []

    def probe(codelet):
        spec = ctx.meta.codelet_specs.get(codelet.codelet_type)
        if observed or spec is None or spec.family not in SERIALISED_FAMILIES:
            return
        ctx._pending_answer = "zzz"
        ctx._pending_answer_quality = 50
        time.sleep(0.3)  # the other workers keep finishing codelets meanwhile
        observed.append(ctx._pending_answer)

    _record_in_codelet(runner, probe)
    result = run_free(runner, workers=4, max_steps=3000)

    assert observed == ["zzz"]
    assert result.status == "answer_found"
    assert result.answers == ["zzz"]
