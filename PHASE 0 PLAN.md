# Phase 0 Plan — Execution Substrate

**Goal.** Database modes and parallelism. **No semantic changes to how Petacat
works.** This phase introduces no new cognition; it establishes the execution
structure every later phase runs inside.

**Depends on.** Nothing. This is the floor.

**Permanence.** Both workstreams are permanent architecture, not scaffolding.
Audit mode in particular remains serial *forever*, and the serial reference mode it
provides is what every later phase validates against.

**Code baseline.** All measurements and code references in this document were taken
against commit `2c5c086` ("Bring Petacat to functional parity with Metacat"), on an
**Apple M2 Max** (8 performance + 4 efficiency cores, 38 GPU cores, 96 GB unified
memory). Engine: 29 modules, 16,619 LOC. Seed data: 59 slipnet nodes, 202 links, 27
codelet types. Test suite: **590 passing**, 2 skipped (28 unit + 4 integration + 8
module files run locally; 9 e2e files currently require Docker, which WP3.1 removes).

---

## Terminology — Run and Training Session

- **Run** — a UI-initiated letter-analogy problem plus Petacat's response. **Mode is a
  property of a Run.**
- **Training Session** — a sequence of Runs, which may mix the three modes in any
  order.

**A Training Session carries the Episodic Memory across Run boundaries, and in Phase 0
that is all it carries.** This matches Metacat and the current port; Phase 0 preserves
it exactly. Verified against `init_mcat` (`runner.py:109–170`):

| Component | Across a Run boundary |
|---|---|
| `EpisodicMemory` | **Carried over**, via injection — the reminding substrate |
| `Slipnet` | Rebuilt from metadata; activations reset |
| `Themespace` | Rebuilt; theme activations reset |
| `Workspace` | Rebuilt — it *is* the new problem |
| `Coderack` | Rebuilt |
| `TemporalTrace` | Rebuilt |
| `Temperature` | Reset to `initial_temperature` |
| `CommentaryLog` | Rebuilt |
| `RNG` | Reseeded from the Run's seed |

**A Training Session is reset from the Admin panel** via `POST /api/memory/clear`
(`api/memory.py:42`), which clears the persisted rows and the in-process
`_global_memory`.

All three modes carry the same thing forward and differ only in what is written down.
Since only Episodic Memory crosses a Run boundary, a Run's starting state is largely
derivable from `(problem, seed, config-hash, memory-hash)`; Normal persists it
literally so the record is self-contained, but the substantive capture is the
**Run-end state**, which drives WP2.4.

---

## What "no semantic changes" means here

**Conceptual level, not technical level.** Many technical details change: the RNG
becomes splittable, codelets are reconceptualised as read-phase-plus-delta, state
mutation moves behind a commit discipline. What must *not* change is behaviour at the
level of **solving letter-string analogy problems**.

**The bar is correct behaviour, not exact reproduction.** Petacat is stochastic by
design; a different-but-correct run is right behaviour. Two levels of agreement, used
deliberately:

| Level | Meaning | Use |
|---|---|---|
| **Expected-range agreement** | The set of reachable stopping states is unchanged; frequencies are not compared | **The standard**, for every change in the phase (WP0.1) |
| **Seeded-run agreement** | Same seed, problem and config give the same run | Development spot-checking; breaks legitimately when the RNG call pattern changes, never a gate |

Audit mode supplies the serial reference expected-range agreement is measured against.

**All parallelism lives here, including the stale-state problem.** Later phases
inherit a parallel engine and do not touch scheduling.

---

## Workstream A — Persistence modes

### A1. Where the database is

**The engine is database-free.** All 29 modules of `server/engine/` (16,619 LOC)
contain **zero** SQLAlchemy imports, zero session handling, and zero awaited I/O.
`EngineRunner(meta)` plus `MetadataProvider.from_seed_data(seed_dir)` runs a complete
problem with no Postgres, no Docker, and no FastAPI — every measurement below was taken
on a checkout where SQLAlchemy is not installed.

Phase 0 makes that property **explicit, enforced, and switchable** rather than
incidental.

The database boundary is confined to twelve files:

| Module | Role at the boundary |
|--------|----------------------|
| `server/db.py` | Async engine + session factory |
| `server/main.py` | Lifespan: `create_all`, JSON→DB seeding, help-topic sync |
| `server/services/run_service.py` | **The only writer of run state** |
| `server/services/snapshot_service.py` | State serializers + `save_cycle_snapshot` |
| `server/services/metadata_service.py` | DB → `MetadataProvider` |
| `server/models/{run,metadata}.py` | ORM definitions |
| `server/api/{runs,admin,memory,docs,controls}.py` | 76 endpoints taking `Depends(get_session)` |

`server/api/ws.py` takes **no session at all**, and `controls.py` takes one only for
`POST /spreading-threshold` — a deliberate choice, since the threshold changes what
the run *does* and so belongs in the record of that run. Breakpoints, clamping, and
step-size remain pure in-memory operations.

#### What actually happens during a run — precisely

It matters to separate three things that are easy to conflate: a **call**, an **ORM
staging**, and a **database round-trip**. Measured against `mrrjjj` (2,229 codelets,
18 trace events, 148 update cycles):

| Frequency | What happens | Is it database traffic? |
|---|---|---|
| **Every codelet** (2,229×) | `len(ctx.trace.events)`, then `await _persist_new_trace_events(...)` (`:171`, `:372`), which slices `events[trace_start:]`. The slice is **empty ~99.2% of the time**. `run_to_completion` adds `await asyncio.sleep(0)` (`:387`). | **No.** Coroutine + slice overhead only. |
| **Per new trace event** (18×) | `session.add(TraceEventRow(...))` (`:568`), plus a `SnagDescriptionRow` on snags (`:584`). | **No.** ORM staging into the identity map; becomes SQL at the next flush. |
| **Every 15 codelets** (148×) | `save_cycle_snapshot` (`:181`, `:382`) builds the **full ~43 KB JSON blob** via seven `serialize_*` calls (~0.4 ms), then `session.add()` **and `await session.flush()`** (`snapshot_service.py:266`). | **Yes.** `flush()` emits the pending INSERTs — 148 round-trips per run. |
| **Once per API call** | `update(Run)` + `session.commit()` (`:196–201`, `:391–403`). | **Yes.** |

**The actual database traffic during a run is the 148
snapshot flushes plus one commit** — which is a further argument for retiring snapshots
(WP2.4), since removing them removes essentially all in-run DB traffic.

#### Measured cost

| Problem (seed) | Codelets | Engine wall | Rate | Trace rows | Snapshots | JSONB written |
|---|---|---|---|---|---|---|
| `abc→abd; ijk?` (1) | 392 | 45 ms | 8,657/s | 6 | 26 | ~1.1 MB |
| `abc→abd; xyz?` (7) | 740 | 87 ms | 8,518/s | 4 | 49 | ~2.1 MB |
| `abc→abd; xyz?` (42) | 797 | 82 ms | 9,774/s | 8 | 53 | ~2.3 MB |
| `abc→abd; iijjkk?` (42) | 1,416 | 203 ms | 6,994/s | 14 | 94 | ~4.0 MB |
| `abc→abd; mrrjjj?` (42) | 2,229 | 292 ms | 7,641/s | 18 | 148 | ~6.3 MB |

Metadata loads from JSON in **2 ms**. Serialising one snapshot costs
**0.37–0.46 ms**, so the 148 snapshots of the `mrrjjj` run cost ~55 ms against 292 ms
of engine time — **18–27%** across the suite. Snapshots are **~43 KB and constant** in
size: 39% themespace, 24% coderack, 16% slipnet, 12% rng, 8% workspace.

Each run therefore writes **1–6 MB of JSONB that no code path can read back**. Fast
Run is worth roughly a **1.2–1.4× CPU saving before I/O**.

#### Defects to fix rather than inherit

- **D1 — Snapshots are still write-only.** `restore_slipnet_state`,
  `restore_trace_state`, `restore_runner_state`, and `restore_rng_state`
  (`snapshot_service.py:271–308`) are **called from nowhere**; there is still no
  `restore_coderack_state` or `restore_workspace_state` at all.
  `prune_old_snapshots` (`:309`) is likewise never called, so rows accumulate without
  bound. The largest write in the system remains unreadable.
- **D2 — Pure serializers are welded to the ORM.** `snapshot_service.py:13–17` mixes
  side-effect-free serialization with `sqlalchemy` and `server.models.run` imports, so
  reading engine state requires importing the database layer. Hit directly while
  measuring: the pure functions had to be extracted textually to be callable.
- **D3 — Process-global ID counters make identifiers depend on process history.**
  Five classes carry class-level counters incremented with a non-atomic
  read-modify-write: `Codelet` (`coderack.py:23`), `WorkspaceStructure`
  (`workspace_structures.py:24`), `WorkspaceObject` (`workspace_objects.py:31`),
  `TraceEvent` (`trace.py:75`), and `AnswerDescription`/`SnagDescription`
  (`memory.py:46,85`). The same `(problem, seed)` run three times in one process gives
  identical cognition and `event_number` sequences starting at 1, 19 and 41.
  `TraceEvent._next_id` sets `event_number`, which is persisted to
  `TraceEventRow.event_number` and used as the ordering key in
  `get_trace_events_from_db`. Under free-threaded Python these are also data races —
  `Codelet._next_id` reached 18,241 after four runs.

### A2. The three modes

Persistence mode is a property **of a run**, chosen at creation — not a global
setting — because later phases will want a Fast corpus-training population and a
Normal live dialogue in the same process.

| | **Fast Run** | **Normal** | **Audit** |
|---|---|---|---|
| **Purpose** | Rapid iterative testing; Runs are discarded | Ordinary operation; human-inspectable, reproducible | Total verification; scrubbable trace |
| **What is persisted** | **nothing, ever** | the **complete Petacat state** at Run start, and the **complete Petacat state** at Run end | **every state-changing action** during the Run |
| **When it is written** | never | twice: Run start, Run end | buffered in memory during the Run; **flushed at Run end** |
| **DB attached** | **no** | yes | yes |
| **Execution** | full parallelism | full parallelism | **serial** |
| **Expected cost** | full engine rate (7k–9.8k codelets/s today) | two state captures per Run | extremely slow, by design |

**Fast and Normal differ in exactly one thing.** Not in cadence, not in detail level,
not in what the engine does: Normal captures the **complete state at the two Run
boundaries** and Fast captures nothing. Everything else about the two modes is
identical. Stating it that narrowly is deliberate — it makes Normal cheap (two
captures, not 148) and it makes the mode-equivalence test meaningful, because there is
nothing else that could differ.

**Why complete state, and not the problem plus the seed.** Because of the Training
Session invariant: a Run inherits Slipnet activation, Themespace activation, and the
Temporal Trace from whatever preceded it. `(problem, seed)` does not determine a Run's
behaviour; `(complete starting state, problem, seed)` does. This is also what makes
Normal *reproducible by re-execution*: reload the recorded start state, re-run, and
the recorded end state must follow.

**Fast Run performs no persistence work of any kind — not deferred, not buffered, not
built-and-discarded.** Two requirements:

1. **Zero database activity during the run and at its end.** No connection, no
   session, no staging, no final flush, no summary row, no answer record.
2. **Zero construction of anything storable.** No JSON blob is built, not even to be
   written later, and no list of records accumulates in memory for the end of the run.
   If a representation exists only because something might persist it, Fast Run must
   not create it.

Requirement 2 is why sink methods take the **live context** rather than a payload
(§A4), and why the fast sink must be a no-op rather than a collector.

It also draws a line inside the engine, between accumulation cognition depends on and
accumulation that is pure output:

| Structure | Read by cognition? | Fast Run |
|---|---|---|
| `ctx.trace.events` | **Yes** — `jootsing.py:460`, `runner.py:420`, `builtins.py:718,893` | **Keep.** Engine state, not persistence; the `TraceEventRow` is the artefact and is never constructed |
| `ctx.commentary` | **No** — the engine only calls `emit_*`; `render`/`get_paragraphs`/`count` are API-only | **Must not accumulate** |

Commentary therefore becomes a sink concern (WP2.10): `ctx.commentary` is an injected
writer, the engine calls `emit_*` unconditionally, and in Fast Run those calls land on
a discarding writer.

**Normal records complete state at the two Run boundaries — nothing in between.**
Reproducibility is **by re-execution, not by replay**: reload the start state, re-run,
and arrive at the recorded end state. Mid-Run detail is deliberately not kept; that is
Audit's job.

**Audit records every state-changing action during the Run, and may buffer.** The
requirement is **completeness**, not contemporaneity of writing: Audit may accumulate
records in memory and flush once at Run end.

Fast Run forbids the buffering Audit permits: the fast sink is a no-op, not a
collector.

**Audit mode is also the serial reference mode** — a serial, fully-recorded execution
is the artefact fidelity cross-validation against Marshall's semantics needs.

**Audit cannot show concurrency-dependent behaviour**, since it removes concurrency,
and no journal of commit order is kept (§B3). A defect that only appears under
free-running is diagnosed by reasoning and targeted instrumentation.

### A3. Review UX — a Phase 0 deliverable

Normal and Audit exist to be *looked at*, and today nothing looks at them. Phase 0
must ship the review surfaces alongside the writers, or it repeats the write-only
mistake it was convened to fix. Two surfaces:

- **Normal review** — a Training Session browser: list sessions, open one, see its
  sequence of Runs and each Run's mode, and for a Normal Run compare its recorded
  start state against its end state. Coarse-grained and fast to scan.
- **Audit review** — a tick-level inspector, **forward-stepping only in Phase 0**: step
  through a Run and at any tick see the codelet that ran, the structures that changed,
  and the activation and temperature state at that instant. Backwards scrubbing is
  deferred, with the record format kept open to it (WP2.8).

Both build on the existing client (`WorkspaceView`, `SlipnetView`, `TraceView`,
`ThemespaceView`) rendering *recorded* state rather than live state.

### A4. The mechanism: one code path, three sinks

A `RunSink` port with methods the engine calls at defined moments
(`on_run_created`, `on_codelet`, `on_trace_event`, `on_structure_change`,
`on_turn_end`, `on_answer`, `on_valence`), and three implementations: fast, normal,
audit.

- **The engine never learns its mode.** No `if mode == "fast"` anywhere in
  `server/engine/`.
- **Serialisation happens *inside* the sink**, from the live context, never a
  pre-built payload.
- **The fast sink is a no-op, not a collector** — no accumulation, no formatting, no
  storable representation.
- **Mode must not change results.**
- **The DB-free property becomes an enforced invariant** — a test that fails if
  anything under `server/engine/**` imports SQLAlchemy.

### A5. Consequences

- **Mid-run snapshots are retired.**
- **Reproducibility is by re-execution** from (complete Run-start state, config-hash,
  memory-hash).
- **Metadata gets a config-hash.** `Run.spreading_threshold` (`models/run.py:42`)
  already sets the precedent.
- **Episodic memory becomes a named, versioned input** with a recorded `memory-hash`;
  Fast Run defaults to an ephemeral in-process memory.
- **Serializers split from the ORM.**
- **The API keeps working in every mode.** `ws.py` and most of `controls.py` are
  already session-free — Fast means *not written down*, not *not observable*.

---

## Workstream B — Parallelism

### B1. The constraint

Petacat targets **Apple M-series silicon only.** The implementation must achieve
**true parallelism**: codelets executing simultaneously across multiple **CPU cores**,
and the system's numeric work executing on the **GPU cores**.

Apple silicon's **unified memory architecture** lets CPU and GPU address the same
physical memory with no copy.

**This phase removes the containerisation completely.** The engine runs natively on
macOS.

### B2. The profile

Per-phase timings for `abc→abd; mrrjjj?` (seed 42, 2,229 codelets, 148 update
cycles). Instrumentation lowers the total to 280 ms from the 292 ms measured above;
percentages are of the instrumented run:

| Phase | Time | % of run |
|---|---|---|
| `coderack.post` (including eviction) | 104.4 ms | **37.3%** |
| └ `remove_old_codelets` | 100.1 ms | **35.8%** |
| **Codelet execution** | 76.9 ms | **27.5%** |
| posting: bottom-up | 64.8 ms | 23.2% |
| posting: top-down | 53.6 ms | 19.2% |
| numeric: object values | 29.3 ms | 10.5% |
| numeric: structure strengths | 21.7 ms | 7.8% |
| `coderack.choose_and_remove` | 8.3 ms | 3.0% |
| numeric: themespace spread | 7.0 ms | 2.5% |
| numeric: temperature | 0.2 ms | 0.1% |
| **[numeric substrate total]** | **58.2 ms** | **20.8%** |

*(The posting rows overlap `coderack.post`: bottom-up and top-down posting are what
call it.)*

Three conclusions follow:

**(a) The single largest cost is one function, and the fix is algorithmic rather than
parallel.** `remove_old_codelets` (`coderack.py:172`) is **35.8% of runtime**. It is
called from `post()` whenever the rack is at capacity — and the rack sits at capacity
essentially always (measured occupancy 94–98 of `max_size` 100). Each call rebuilds
the entire candidate list across all seven bins, computing an age × urgency-penalty
weight per codelet, then rescans to remove the chosen one. That is O(n) per eviction
with n ≈ 100, invoked 3,184 times, producing **323,883 `_urgency_to_bin` calls**.
Making eviction incremental is worth more than perfect codelet parallelism.

**(b) Amdahl's law caps codelet-only parallelism at 1.38×.** Codelet execution is
27.5% of runtime, so making it infinitely parallel yields at most
`1/(1−0.275) = 1.38×`. Including the numeric substrate (48.3% combined) raises the
ceiling only to **1.94×**. **The serial remainder is dominated by coderack
maintenance**, which is runner work, not codelet work. Any parallelism plan that
addresses only codelets will disappoint, and this is the arithmetic that says so
before the effort is spent.

**(c) The coderack is the hottest contended structure.** It is touched by the
*runner* on every post and every selection, and is simultaneously the largest serial
fraction — which makes **coderack sharding a prerequisite for parallelism paying
off**, not an optimisation.

### B3. The target: free-running

Continuous codelet execution across CPU cores with no global barrier, a sharded
coderack, and the numeric substrate on GPU cores. Three mechanisms get there:
splittable per-codelet RNG, read/write-set discipline in the builtins, and a coderack
that is not a single hot queue. Each is verified serially before concurrency is
enabled; **worker count is the bisection axis** if the expected range moves.

Two properties of the architecture do most of the work:

- **Conflict → fizzle.** `fizzle` is already a native codelet outcome, so a codelet
  that loses a race fizzles for the same reason it fizzles when its structure is too
  weak. Under contention the fizzle rate rises, which reads correctly as the workspace
  being busy.
- **The proposal lifecycle is already a staged commit.** `%proposed%` → `%evaluated%`
  → `%built%`. Reconceptualising codelets as *pure read-phase plus a proposed delta*
  makes explicit a structure already present.

**A free-running run is not recoverable after the fact.** No journal of commit order is
kept. The cost is to **sample efficiency**, not validity: a free-running run is one
draw, so evolutionary fitness needs more runs per configuration; population parallelism
pays for that. Where a specific run needs explaining, re-run it under Audit.

### B4. Resolving stale state

Three mechanisms, already latent in the architecture:

- **Conflict → fizzle** turns a lost race into an outcome the model already
  understands, so most staleness needs only to be *detected*.
- **The proposal lifecycle** becomes the commit protocol: a codelet's read-set is
  validated at commit, and a structure whose premises moved is re-evaluated or fizzles.
- **Locality** bounds the blast radius: a bond scout touches two adjacent objects.

**Read-set granularity** is the open question — too fine and everything fizzles on
false conflicts, too coarse and structures build on moved premises. Empirical tuning
against the serial reference.

**The coderack resists all three.** It is not local, it is touched by every post and
every selection, and per B2(c) it dominates the serial fraction. It needs **sharding**
— per-worker racks with work-stealing — which changes selection semantics, since
urgency-weighted probabilistic selection across seven bins is not trivially
decomposable. **The hardest single problem in Phase 0.**

---

## The technical plan

Work packages, in dependency order. Each names the files it touches and how it is
verified. Stage 0 makes everything afterwards measurable and attributable; **Stage 1
is where the largest measured win is**, and it runs early so that every later profile
and every parallelism decision is taken against a realistic engine; Stages 2–3 are the
persistence and platform prerequisites; Stage 4 is concurrency and the GPU substrate.

### Stage 0 — Baseline and guardrails

Nothing here changes behaviour. It exists so that everything afterwards is measurable
and attributable.

**WP0.1 — The expected-range oracle (solution-set baseline).**
The regression oracle is the **set of valid stopping states** each problem can reach —
not a seeded run, and not a frequency distribution. Set membership survives what this
phase changes: reordering codelets changes which answer
a seed produces and how often each occurs, not which answers are reachable.

**Scope.** Every unique `(initial, modified, target)` triple across the demo problems,
run in discovery mode — 34 demos reduce to **13 problems**. Demos catalogued as
justification contribute their triple with the supplied answer dropped. Stopping states
are answer strings plus non-answer outcomes (`gave_up`, halted).

**Stopping rule.** Sample until the Good-Turing missing-mass estimate `f₁/N` lands in
**0.00006 < f₁/N ≤ 0.0001** (f₁ = states seen exactly once). `f₁ = 0` counts as
saturated only at N ≥ 10,000, below which it cannot distinguish a complete set from an
under-sampled one. Problems vary widely — `abc→abd; xyz?` needs 25,000 runs to reach 35
states, `a→b; z?` reaches 2 in 10,000 — so size each by the statistic, not a fixed
count.

**Checking a change.** ~100 runs per problem, comparing set membership:

- A stopping state outside the expected range means **investigate**: re-run that
  problem deeply, and if the state proves old-but-rare, add it to the range.
  Investigation may include human review and supervised learning. At `f₁/N` = 0.0001 a
  novel state appears ~1% of the time per problem, ≈0.1 per 13-problem cycle.
- **Assert presence for the most-frequent states summing to ≥50%**, which the baseline
  records. At n=100 a 57%-frequency state's absence is decisive (p ≈ 10⁻³⁶); the tail
  carries no signal.

**Built:** `scripts/build_expected_range.py` and the baseline it produced,
`tests/fixtures/expected_range.json` — 13 problems, 410,000 runs, all saturated. The
script appends, so a new problem is sampled without resampling the rest.

*Files:* new `tests/module/test_expected_range.py` (the routine check).
*Cost, measured:* ~44–55 runs/s across 11 workers. The routine check (1,300 runs) is
under a minute.
*Verify:* a second saturation run of a problem discovers no state outside the first
run's set.
*Note:* multi-core execution is what makes this affordable, so the concurrency work is
testing infrastructure as much as training infrastructure.

**WP0.2 — Engine purity invariant.**
A test that fails if anything under `server/engine/**` imports `sqlalchemy`,
`server.models`, `server.db`, or `server.services`. True today by discipline; make it
true by construction so every later phase inherits it.
*Files:* new `tests/unit/test_engine_purity.py`.
*Verify:* passes now; fails if an import is deliberately added.

**WP0.3 — Per-run identifier counters (fixes D3).**
Replace the five class-level `_next_id` counters with per-run counters owned by
`EngineContext` (or an `IdAllocator` it holds), injected at construction. This removes
process-history dependence *and* the read-modify-write races that free-threading would
expose.
*Files:* `engine/coderack.py:23`, `engine/workspace_structures.py:24`,
`engine/workspace_objects.py:31`, `engine/trace.py:75`, `engine/memory.py:46,85`;
`engine/runner.py` (context construction).
*Verify:* identifiers depend only on the Run, never on what ran before it in the
process — the property that fails today. Numbering restarts per Run rather than
continuing from process-wide state.
*Note:* touches five modules and every object constructor. Do it before parallelism,
not during; it is a mechanical change now and a merge nightmare later.

**WP0.4 — Benchmark harness, checked in.**
The per-phase instrumentation used to produce the B2 table, as a repeatable script:
codelets/s, per-phase timings, Amdahl fractions, snapshot size and serialisation cost.
*Files:* new `scripts/bench_engine.py`.
*Verify:* reproduces the B2 table within noise. Every subsequent work package reports
its effect through this script.

**WP0.5 — Staleness tolerance.**
Serial execution, but each codelet reads state as it was N codelets ago. One flag, no
threads. Answers the central risk of the concurrency work before any of it is written.
*Files:* `engine/runner.py`, `engine/codelet_dsl/builtins.py`.
*Verify:* expected range at N = 1, 5, 15, 50. The N at which the set moves bounds how
much staleness free-running can tolerate.

### Stage 1 — The algorithmic prerequisite

Runs before the persistence work so that every later measurement, and the Amdahl
fractions shaping Stage 4, are taken against an engine without a fixable bottleneck.

**WP1.1 — Incremental coderack eviction.**
`remove_old_codelets` (`coderack.py:172`) rebuilds the entire candidate list on every
eviction. Measured on `mrrjjj`: the rack is at capacity for **58% of posts** (median
occupancy 100 of 100), triggering **3,184 evictions**, each scanning all ~100 codelets
to compute `age × urgency_penalty`, then scanning again to remove the chosen object —
**100 inspections per codelet removed, 318,400 in total, 35.8% of runtime.**

`urgency_penalty` is fixed for a codelet's life and `age` moves only with
`current_time`, so a bin's total weight has a closed form:

    bin_weight = penalty × (count × current_time − Σ time_stamp)

`count` and `Σ time_stamp` are O(1) to maintain on add and remove. Eviction picks a bin
from 7 aggregates and scans only within it (~14 codelets) — roughly 21 inspections
rather than 100, with the **same probability distribution**.

*Wrinkle:* `age = max(1, current_time − time_stamp)` clamps, so a codelet posted at the
current instant has age 0 → 1. That breaks the closed form for those codelets and they
must be accounted for separately.

*Files:* `engine/coderack.py:106,111,172`.
*Verify:* the **expected range is unchanged** (WP0.1); the weighting is preserved by
construction. Prefer a refactor that leaves the RNG call pattern untouched, keeping
seeded spot-checks usable. Benchmark shows the 35.8% share collapse.

**WP1.2 — Re-baseline and recompute the Amdahl fractions.**
Re-run WP0.4. Removing serial work **raises the parallelisable fraction**. If eviction
drops from ~100 ms to ~10 ms (280 ms → ~190 ms):

| Parallelising… | Before | After WP1.1 |
|---|---|---|
| Codelet execution only | 27.5% → **1.38×** | 40.5% → **1.68×** |
| Codelets + numeric substrate | 48.3% → **1.94×** | 71% → **3.46×** |

**Do not design the concurrency work against the pre-WP1.1 profile.**

### Stage 2 — Persistence modes

**WP2.0 — Name the Training Session; keep its semantics unchanged.**
Session continuity is **already correct** — Episodic Memory carries across Runs, the
rest is rebuilt — so this package adds no state-continuity behaviour. It gives the
existing concept a first-class representation so Runs can be grouped, reviewed, and
compared: a `training_sessions` row, `Run.session_id`, and the Admin reset
(`POST /api/memory/clear`) recorded as the session boundary it already is.
*Files:* `models/run.py` (`training_sessions` table, `Run.session_id`), migration,
`services/run_service.py`, `api/memory.py:42` (record the reset as a session boundary),
`client/` (session grouping in the review UI).
*Verify:* Runs group under sessions; a memory clear starts a new session; **cognition
is untouched** — this package must not modify `init_mcat` at all.

**WP2.1 — Split serializers from the ORM (fixes D2).**
Move the pure `serialize_*` functions into `server/engine/serialization.py` with **no
database imports**; leave persistence in `server/services/snapshot_repository.py`.
*Files:* `services/snapshot_service.py` → split; callers in `run_service.py`,
`tests/unit/test_codelet_behaviours.py:920`.
*Verify:* WP0.2's purity test extended to assert the serialization module imports no
SQLAlchemy; existing tests green.

**WP2.2 — Define the `RunSink` port.**
Protocol with `on_run_created`, `on_codelet`, `on_trace_event`,
`on_structure_change`, `on_turn_end`, `on_answer`, `on_valence`. Methods take the live
`EngineContext`, never a pre-serialised payload.
*Files:* new `server/engine/sink.py` (protocol only — no implementations, so the
engine stays pure).
*Verify:* engine compiles and runs with the fast sink; no behavioural change.

**WP2.3 — Thread the sink through the runner; take persistence out of the step loop.**
`run_service.step` and `run_to_completion` stop calling `_persist_new_trace_events`
and `save_cycle_snapshot` inline; they attach a sink instead. Also removes the
per-codelet `await` and list-slice, and the `await asyncio.sleep(0)` in
`run_to_completion` (`:387`) — which alone costs ~16 µs per codelet.
*Files:* `engine/runner.py`, `services/run_service.py:160–205, 355–405`.
*Verify:* expected range unchanged; the 148 snapshot flushes and the per-codelet
coroutine overhead both gone; benchmark harness shows the step loop doing engine work
only.

**WP2.4 — Complete, restorable state capture (fixes D1).**
Normal mode needs a complete Petacat state, written at a Run boundary and **loadable
back**. Nothing existing does this: `serialize_coderack_state` discards every
object-valued codelet argument (`{k: str(v) … if not hasattr(v, '__dict__')}`),
`serialize_workspace_state` is documented "for display" — built structures as counts,
no proposal levels, descriptions, or object identity — and
`restore_coderack_state`/`restore_workspace_state` do not exist.

The work is an object-graph serializer with stable identity covering Workspace
(objects, descriptions, bonds, groups, bridges, rules, with proposal levels and
strengths), Coderack (codelets *with* their object-valued arguments), Slipnet,
Themespace, Trace, Temperature, Memory and RNG. The graph has cross-string references
and cycles, so identity is explicit rather than structural. **Format: id-based graph**,
inspectable and versionable, and directly renderable by the review UI (WP2.9).

The per-15-codelet snapshot, `prune_old_snapshots` and the partial `restore_*` set go.
*Files:* `services/snapshot_service.py` → new `engine/serialization.py` +
`services/state_repository.py`, `models/run.py:57+`, `services/run_service.py`,
migration, `tests/e2e/test_persistence.py`, `tests/e2e/test_api_runs.py:286`.
*Verify:* **round-trip fidelity** — capture state mid-Run, restore into a fresh
process, continue, and reach the same end state as an uninterrupted Run.

**WP2.5 — Named, versioned inputs: config-hash and memory-hash.**
Hash the `MetadataProvider` contents; make `EpisodicMemory` an explicit argument at run
creation with a recorded hash. The engine is already correct here —
`init_mcat(memory=…)` (`runner.py:112`) takes it as an injected dependency — so this
removes the `_global_memory` module global from the service layer only. Sharing stays
available; what changes is that *which* memory a run saw becomes part of the run's
identity, which matters once Phase 1 puts the concept vocabulary in episodic memory and
Phase 2 writes love-born concepts.
*Files:* `engine/metadata.py`, `services/run_service.py:33,130,454,540,662,724,738`,
`api/memory.py:52`, `main.py:508`, `models/run.py` (+2 columns), Alembic migration.
*Verify:* two runs with the same seed and different memory-hashes are distinguishable
in the record; `rehydrate_memory` becomes idempotent.

**WP2.6 — Fast Run.**
Fast sink; ephemeral in-process episodic memory; no session, no engine, no connection;
**and no construction of any storable representation** (§A2 requirement 2).
*Files:* `services/run_service.py`, `api/runs.py`.
*Verify:* three separate tests, because the two requirements fail differently —
 (a) a Fast run completes normally with **the database stopped**;
 (b) the async engine / session factory is **never constructed** during a Fast run;
 (c) an allocation probe over a Fast run shows **no `serialize_*` call, no `json.dumps`,
 and no growth in any record buffer** — the check that catches a well-meaning
 "buffer now, write later" implementation.

**WP2.7 — Normal mode.**
Two complete-state captures per Run, via WP2.4: one at Run start, one at Run end.
Nothing else — no mid-Run records, no per-cycle anything.
*Files:* `services/run_service.py`, `models/run.py` (Run-boundary state rows),
migration.
*Verify:* reload a recorded Run-start state, re-execute the Run, and reach the
recorded Run-end state exactly. Additionally: a Normal Run placed **after** other Runs
in a Training Session records a start state whose Episodic Memory reflects them — the
check that the one thing which does cross Run boundaries is actually captured.

**WP2.8 — Audit mode.**
Record every state-changing action during the Run as a **forward log**. Buffering in
memory and flushing once at Run end is permitted. Forces serial execution.
*Files:* `services/run_service.py`, `models/run.py`, migration.
*Verify:* from the recorded actions plus the Run-start state, every intermediate state
can be reconstructed **in forward order**; the mode refuses to start if a parallel
scheduler is configured.
*Scope — forward only in Phase 0.* Backwards scrubbing constrains the record format,
not merely the UI. **The format should not foreclose it:** record enough before-state
that actions could be inverted later, but do not build the inverse-replay machinery.

**WP2.9 — Review UX.**
Normal session/Run browser and Audit action-scrubber, reusing the existing views
against recorded state.
*Files:* `client/src/components/` (new review components), `client/src/api/client.ts`,
new read endpoints in `api/runs.py`.
*Verify:* a run recorded in each mode can be reconstructed and inspected in the UI.

**WP2.10 — Commentary becomes a sink concern.**
`CommentaryLog` accumulates output that no part of cognition reads back — the engine
only calls `emit_*` → `add_comment`; `render`, `get_paragraphs` and `count` are
API-only. Replace `ctx.commentary` with an injected writer: the engine calls `emit_*`
unconditionally, and in Fast Run those calls land on a discarding writer.
*Files:* `engine/commentary.py`, `engine/runner.py` (context construction),
`engine/jootsing.py`, `engine/codelet_dsl/builtins.py`, `services/run_service.py`
(`get_commentary`).
*Verify:* expected range unchanged; commentary unaffected by mode; **zero paragraphs
allocated in Fast Run**; the `eliza_mode` re-render path still works.

### Stage 3 — Native macOS

**WP3.1 — Remove containerisation.**
Native macOS execution for the engine, API, client and Postgres, on a single Python
version.
*Files:* delete `docker-compose.yml`, `docker-compose.dev.yml`, `Dockerfile`,
`Dockerfile.dev`; update `pyproject.toml`, `TESTING.md`, `README.md`, and
`scripts/` (a native dev runner).
*Verify:* full suite green natively, including e2e.

**WP3.2 — Free-threaded CPython.**
Install `python-freethreading` (3.14.6, available via Homebrew) and run the suite under
it, before any threading work is designed.
*Verify:* suite green under the free-threaded build; benchmark reports single-threaded
overhead versus the standard build.
*Risk:* SQLAlchemy/asyncpg free-threading readiness.

### Stage 4 — Concurrency and the numeric substrate

Two workstreams run together: codelet concurrency (WP4.1–4.4) and the GPU numeric
substrate (WP4.5–4.6). Neither blocks the other.

**WP4.1 — Splittable RNG.**
Replace the single shared `random.Random` with counter-based per-codelet streams
derived deterministically from `(run_seed, worker, slot)`.
*Files:* `engine/rng.py`, and the twelve engine modules that call `rng.*`
(`rules.py`, `builtins.py`, `jootsing.py`, `coderack.py`, `runner.py`, `workspace.py`,
`themes.py`, `slipnet.py`, `justify.py`, `workspace_objects.py`, `formulas.py`).
*Verify:* **the expected range is unchanged** — the first real test of the oracle's
claim that changing the random stream changes which answer a seed produces, not which
answers are reachable. A moving set here is a finding about the oracle, to be
understood before Stage 4 continues.

**WP4.2 — Read-set / write-set discipline in the builtins.**
`codelet_dsl/builtins.py` (998 LOC, 45 top-level functions) is where codelets mutate
shared state. Classify each mutating builtin (`propose_bond`, `build_structure`,
`break_structure`, `post_codelet`, `record_event`, `activate_from_workspace`, …) and
introduce the delta-and-commit split the commit protocol needs.
*Files:* `engine/codelet_dsl/builtins.py`, `engine/workspace_structures.py`.
*Verify:* serial behaviour unchanged; read/write sets recorded and inspectable.

**WP4.3 — Coderack sharding.**
Per-worker racks with work-stealing — the hardest problem in the phase, since
urgency-weighted probabilistic selection across seven bins is not trivially
decomposable. Options: shard by codelet family, shard by workspace region, or one rack
behind a lock-free structure.
*Files:* `engine/coderack.py`, `engine/runner.py`.
*Verify:* expected range unchanged at one worker.

**WP4.4 — Free-running.**
Continuous execution, no global barrier, conflict → fizzle.
*Files:* `engine/runner.py`.
*Verify:* expected range unchanged; scale 1→2→4→8 workers; fizzle-rate telemetry and
throughput per worker count. Read-set granularity tuned here (B4).

**WP4.5 — GPU numeric substrate.**
Slipnet activation spreading, salience/importance/unhappiness, structure strengths,
themespace dynamics and temperature on Metal via MLX, with hand-written kernels where
MLX cannot express a traversal. **Sized for the target Slipnet, not the current one:**
later phases grow it toward **~300,000 nodes**, LLM-vocabulary scale, at which sparse
activation spreading is the dominant numeric cost. Data layout is chosen for that scale
from the start.
*Files:* new `engine/numeric/`, `engine/slipnet.py`, `engine/workspace.py`,
`engine/themes.py`, `engine/temperature.py`, `pyproject.toml` (mlx).
*Verify:* expected range unchanged; kernel timings at 59, 10³, 10⁴ and 10⁵ synthetic
nodes, so the scaling curve is known before the Slipnet grows into it.

**WP4.6 — Population batching.**
Batch K independent runs so the GPU sees fat batched kernels — what Phase 4 corpus
training, Phase 6 evolution and the expected-range oracle all need.
*Verify:* runs/second at K = 1, 8, 32, 128 against the CPU-only baseline.

---

## Acceptance criteria

- Episodic Memory carries across Run boundaries; `init_mcat` unchanged.
- A mode-mixed Training Session matches an all-Fast one, cognitively.
- Persisted identifiers depend only on the Run (WP0.3).
- Fast Run completes with the database stopped, allocating only engine state (WP2.6).
- Normal Runs re-execute from recorded start state to recorded end state, including
  mid-session Runs.
- Audit Runs step forwards over every state-changing action, on a format that admits
  backwards scrubbing later.
- Normal and Audit review UX shipped and usable.
- The engine-purity test passes.
- Native macOS execution on a single Python version.
- Coderack eviction incremental (WP1.1); Amdahl fractions recomputed (WP1.2).
- Free-running at 8 workers, reaching the same expected range as serial across the
  demo suite.
- The numeric substrate on GPU, with kernel scaling measured to 10⁵ nodes.

## Open questions

1. **Sink event vocabulary** — the exact `RunSink` call sites, and how much of the
   live client can be reused for recorded-state review.
2. **Coderack sharding strategy** (WP4.3) — by family, by region, or lock-free single
   rack; and how urgency-weighted probabilistic selection is preserved across shards.
   The hardest open question in the phase.
3. **Read-set granularity** (B4) — the coarse/fine tradeoff between false conflicts and
   missed conflicts, tuned empirically against the serial reference.
4. **Staleness tolerance** (WP0.5) — how much stale state cognition absorbs before the
   expected range moves.

## Glossary

| Term | Meaning |
|------|---------|
| **Fast Run / Normal / Audit** | The three persistence modes: nothing ever / complete state at both Run boundaries / every state-changing action, buffered and flushed at Run end |
| **Run** | A UI-initiated letter-analogy problem plus Petacat's response; the unit that carries a persistence mode |
| **Training Session** | A sequence of Runs of arbitrary mixed modes, sharing Episodic Memory across Run boundaries; reset from the Admin panel |
| **`RunSink`** | The port the engine emits events to; mode is which implementation is attached, and the engine never knows which |
| **Config-hash** | Hash of the `MetadataProvider` a run executed under |
| **Memory-hash** | Identifier of the episodic memory state a run executed against |
| **Expected range** | The saturated set of valid stopping states a problem can reach — the oracle for every work package; membership, never frequency |
| **Symbolic layer** | The codelets — irregular, branchy, concurrent across CPU cores |
| **Numeric substrate** | Activation, salience, structure strengths, temperature — 20.8% of runtime, sized for a Slipnet growing toward ~300,000 nodes |
| **Free-running** | The parallelism goal: continuous barrier-free execution, sharded coderack |
| **Conflict → fizzle** | A codelet that loses a race fizzles — reusing an outcome the architecture already has |
| **Serial reference mode** | Permanently retained one-codelet-at-a-time execution — delivered by Audit mode |
| **Seeded-run agreement** | Same seed/problem/config gives the same run — a development convenience, never a gate |
| **Expected-range agreement** | The set of reachable stopping states is unchanged — the standard for every change in the phase |
| **Good-Turing missing mass** | `f₁/N` — estimates unseen states; certifies the baseline is saturated *and* predicts the check's false-alarm rate |
| **Correct behaviour** | Petacat perceives and solves the way Metacat does — what the phase is for |
| **Amdahl ceiling** | The measured cap on parallel speedup: 1.38× for codelets alone, 1.94× including the numeric substrate — before WP1.1 |
