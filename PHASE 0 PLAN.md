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
memory). Engine: 28 modules, 16,619 LOC — modules counted as the `.py` files under
`server/engine/` other than the empty `__init__.py` package markers, which is the
count every engine-size figure in this document uses. Seed data: 59 slipnet nodes,
202 links, 27 codelet types. Test suite: **590 passing**, 2 skipped (28 unit + 4
integration + 8 module files run locally; 9 e2e files currently require Docker, which
WP2.1 removes).

> **As built.** `server/engine/` holds 51 modules and 34,005 lines.

---

## Terminology — Run and Training Session

- **Run** — a UI-initiated letter-analogy problem plus Petacat's response. **Mode is a
  property of a Run.**
- **Training Session** — a sequence of Runs, which may mix the three modes in any
  order.

**A Training Session carries the Episodic Memory across Run boundaries, and in Phase 0
that is all it carries.** This matches Metacat and the current port; Phase 0 preserves
it exactly. Verified against `init_mcat` (`runner.py:109–170`):

> **As built.** That memory shapes the Runs that inherit it. `EpisodicMemory.answer_present`
> is consulted before an answer is reported, and a Run declines an answer the memory
> already holds for the same problem and the same rules (`answers.ss:982`). Repeating a
> problem within a Session therefore reaches a different answer each time, and a Run's
> `memory-hash` is part of what identifies it.

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

**A Training Session is reset from the Admin panel** via `DELETE /api/memory`
(`api/memory.py:42`), which clears the persisted rows and the in-process
`_global_memory`.

All three modes carry the same thing forward and differ only in what is written down.
Since only Episodic Memory crosses a Run boundary, a Run's starting state is largely
derivable from `(problem, seed, config-hash, memory-hash)`; Normal persists it
literally so the record is self-contained, but the substantive capture is the
**Run-end state**, which drives WP3.4.

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

**The engine is database-free.** All 28 modules of `server/engine/` (16,619 LOC)
contain **zero** SQLAlchemy imports, zero session handling, and zero awaited I/O.
`EngineRunner(meta)` plus `MetadataProvider.from_seed_data(seed_dir)` runs a complete
problem with no Postgres, no Docker, and no FastAPI — every measurement below was taken
on a checkout where SQLAlchemy is not installed.

Phase 0 makes that property **explicit, enforced, and switchable** rather than
incidental.

The database boundary is confined to twelve files:

> **As built.** The database boundary spans `api/`, `services/`, `models/` and `db.py`,
> with 93 endpoints taking `Depends(get_session)`.

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
(WP3.4), since removing them removes essentially all in-run DB traffic.

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
| **Expected cost** | full engine rate (7k–9.8k codelets/s at the code baseline) | two state captures per Run | extremely slow, by design |

**Measured as built**, `abc→abd; mrrjjj?` seed 42, end to end through the service
layer, on the Apple M2 Max named in the code baseline, fastest of five runs per cell.
Two conditions, because the numeric substrate dominates the total while the cost of
recording does not depend on it: the default policy, which puts the arithmetic on the
Metal GPU, and `PETACAT_NUMERIC_BACKEND=off`, which runs the engine's own loops.

| | Fast | Normal | Audit |
|---|---|---|---|
| Codelets / answer | 2,255 / `mrrjjk` | 2,255 / `mrrjjk` | 2,255 / `mrrjjk` |
| Wall time, `PETACAT_NUMERIC_BACKEND=off` | **192 ms** | 227 ms | 329 ms |
| Relative to Fast, substrate off | 1.00× | 1.18× | 1.72× |
| Wall time, default backend (`mlx`, Metal GPU) | **1,308 ms** | 1,348 ms | 1,481 ms |
| Relative to Fast, default backend | 1.00× | 1.03× | 1.13× |
| Rows written | none | 2 captures + 6 trace + 1 answer | 2 captures + 6 trace + 1 answer + 2,313 actions |
| Bytes written | **0** | **155 KB** | 413 KB |

Bytes are the summed `octet_length` of the JSON payloads the Run leaves in Postgres.
The codelet count is the same figure the run-parameters table quotes, and it is the
same on both conditions.

Three things this says.

**Cognition is identical across the modes** — same codelet count, same answer, under
both conditions. That is the rule the whole design rests on, and it is checked rather
than assumed.

**Normal writes 155 KB where the retired snapshot system wrote ~6,300 KB** for the same
run: a **41× reduction**, and the 155 KB can actually be read back, which the 6.3 MB
could not.

**Audit is not "extremely slow" — it is 1.72× with the substrate off and 1.13× on the
GPU.** The plan expected worse. Buffering the actions in memory and flushing once at
Run end is what makes the difference: the cost is in writing 2,313 rows at the end,
not in interrupting 2,255 codelets. Recording costs a fixed number of milliseconds
rather than a fixed multiple — Normal adds 35 ms with the substrate off and 40 ms on
the GPU, Audit adds 137 ms and 173 ms — so the multiple is a property of the pair,
which is why both conditions are given.

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
(§A4), and why the fast sink is a no-op.

It also draws a line inside the engine, between accumulation cognition depends on and
accumulation that is pure output:

| Structure | Read by cognition? | Fast Run |
|---|---|---|
| `ctx.trace.events` | **Yes** — `jootsing.py:460`, `runner.py:420`, `builtins.py:718,893` | **Keep.** Engine state, not persistence; the `TraceEventRow` is the artefact and is never constructed |
| `ctx.commentary` | **No** — the engine only calls `emit_*`; `render`/`get_paragraphs`/`count` are API-only | **Injected** |

> **As built.** Every mode supplies a real `CommentaryLog`. A run narrates itself
> identically in each, and `GET /commentary` answers with that narration in every mode.

Commentary therefore becomes a sink concern (WP3.10): `ctx.commentary` is an injected
writer and the engine calls `emit_*` unconditionally.

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
  deferred, with the record format kept open to it (WP3.8).

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
- **Episodic memory becomes a named, versioned input** with a recorded `memory-hash`.

  > **As built.** Every mode shares the Training Session's Episodic Memory. Mode
  > governs persistence alone.
- **Serializers split from the ORM.**
- **The API keeps working in every mode.** `ws.py` and most of `controls.py` are
  already session-free, and a Fast Run stays fully observable through them.

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
and every parallelism decision is taken against a realistic engine; Stage 2 moves the
whole system onto native macOS; Stage 3 is persistence; Stage 4 is concurrency and the
GPU substrate.

**Note on ordering.** Native macOS was originally scheduled after persistence and has
been moved ahead of it. The reason is verification: most of the persistence work is
judged against a database, and today the nine e2e files reach one only through Docker.
Doing the platform move first means Stage 3 is verified natively throughout — including
WP3.6's requirement that a Fast Run completes *with the database stopped*, which is an
awkward thing to arrange through a container stack and a natural one against a local
Postgres. Work-package numbers follow their stage, so the packages once numbered WP2.x
are now WP3.x and vice versa; earlier commits use the old numbering.

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
*Files:* new `tests/architecture/test_engine_purity.py`.
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
*Files:* `engine/runner.py`, `engine/codelet_dsl/builtins.py`, new
`engine/staleness.py` (the delayed view — a separate module because `builtins.py`
consumes it and cannot import `runner.py` without a cycle).
*Verify:* expected range at N = 1, 5, 15, 50. The N at which the set moves bounds how
much staleness free-running can tolerate.

**Measured, via `scripts/measure_staleness.py`** — 13 problems × 150 runs × 5 delays,
9,750 runs. N=0 is a control: same code path, mechanism off.

| Delay | Novel states | Frequent states lost | What appeared |
|---|---|---|---|
| 0 (control) | 0 | 0 | — |
| 1 | 0 | 0 | — |
| 5 | 0 | 0 | — |
| 15 | 2 | 0 | `halted:` on `abc→abd; glz?` and `abc→abd; mrrjjj?` |
| 50 | 3 | 0 | the same two, plus **`answer_found:ikj`** on `abc→abd; ijk?` |

**Read it in two parts, because the two novel-state kinds mean different things.**
Up to N=5 nothing moves at all. At N=15 the only new states are `halted:` — runs that
failed to reach an answer inside the 6,000-codelet cap. That is not a new perception;
it is the same cognition converging more slowly, which is exactly what staleness
should cost. At N=50 a genuinely new answer appears, which is the reachable set
actually moving.

**No absence-check state was lost at any delay**, so the frequent answers stay
reachable throughout — staleness degrades convergence well before it removes anything.

**The bound for WP4.4: keep effective staleness at or below ~5 codelets.** Between 5
and 15 lies the onset of slower convergence, and by 50 the answer set has moved.
Read-set granularity (B4) should be tuned to hold worker read-lag inside that budget,
and fizzle-rate telemetry is the proxy to watch, since a rising fizzle rate and a
lengthening read-lag are the same phenomenon.

*Caveat:* 150 runs per problem bounds the sensitivity — this locates the onset, not a
sharp threshold. The signal is monotone in N, which is the reason to trust the
direction.

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
Re-run WP0.4. Removing serial work **raises the parallelisable fraction**.

**Measured, via `scripts/bench_engine.py`.** The prediction below was that eviction
would drop from ~100 ms to ~10 ms; it dropped to **9.5 ms**, and the recomputed
fractions land within a percentage point of the predicted ones:

| Parallelising… | Before | Predicted after | **Measured after** |
|---|---|---|---|
| Codelet execution only | 27.5% → **1.38×** | 40.5% → 1.68× | **40.1% → 1.67×** |
| Codelets + numeric substrate | 48.3% → **1.94×** | 71% → 3.46× | **69.9% → 3.32×** |

Supporting counters, same problem and seed as B2:

| | Before (B2) | After WP1.1 |
|---|---|---|
| `remove_old_codelets` | 100.1 ms (35.8%) | **9.5 ms (5.4%)** |
| `_urgency_to_bin` calls | 323,883 | **5,483** — one per post, none per eviction |
| Evictions | 3,184 | 3,184 — *unchanged, as it must be* |
| Posts at capacity | 58.1% | 58.1% — unchanged |
| Whole-run throughput | 7,641/s | **12,946/s** |

The eviction and occupancy rows being unchanged is the point: WP1.1 changed how the
victim is found, not which victim is found. Runs are bit-identical across the change
— same codelet counts, same RNG call counts, same answers (`tests/seed_unit/test_coderack_eviction.py`).

*Caveat on the throughput row.* Part of that gain is WP0.3, not WP1.1: replacing the
class-level `_next_id` counters removed a type-version-tag invalidation on every
`Codelet()` construction, which was de-specialising the ~318,000 attribute loads
`remove_old_codelets` performed. Measured separately at ~9% of runtime. The two
changes compound because they both land on the same hot loop.

**Do not design the concurrency work against the pre-WP1.1 profile.**

### Stage 2 — Native macOS

**WP2.1 — Remove containerisation.**
Native macOS execution for the engine, API, client and Postgres, on a single Python
version.
*Files:* delete `docker-compose.yml`, `docker-compose.dev.yml`, `Dockerfile`,
`Dockerfile.dev`; update `pyproject.toml`, `TESTING.md`, `README.md`, and
`scripts/` (a native dev runner).
*Verify:* full suite green natively, including e2e.

**Done.** Homebrew `postgresql@17` on `localhost:5432`, Python 3.14.5 in a project
venv, Node 26, and `scripts/dev.sh` in place of `docker compose up`.

*Result:* **797 passed, 0 skipped, ~96 s** — all four tiers in one command, measured on
the checkout at which WP2.1 landed. Before, the 93 e2e tests were reachable only
through `docker compose exec` and were skipped on every local run; the suite as
normally executed was 590 passed, 2 skipped. `TESTING.md` carries the size of the
suite as it now stands, and the suite reports it in its own per-layer summary.

Three things the move turned up that the container stack had been hiding:

- **The project was not installable.** `pip install -e .` failed outright: hatchling
  cannot infer the wheel contents of a root-level `server/` beside `client/` and
  `tests/`, and it had never been exercised because the container installed the
  dependency list directly and bind-mounted the source.
- **The client proxied to `http://app:8000`** — the Compose service name. Off Docker
  every API call from the GUI returned 500 (`getaddrinfo ENOTFOUND app`), so nothing in
  the interface worked. Now `127.0.0.1:${PORT ?? 8100}`, reading the same variable
  `scripts/dev.sh` reads so the two cannot drift.
- **The e2e test database URL in `pyproject.toml` had never been right** — port 5433
  and password `test`, matching neither the container stack (5434, `dev`) nor anything
  else. pytest reported the table as an unknown option and ignored it, so the wrong
  value never surfaced. The default now sits in `tests/e2e/conftest.py` beside the code
  that reads it.

*Migration:* the container database held a live Training Session — 10 runs, 16 answers,
48 snags, 831 trace events — which was dumped and restored into the native `petacat`
rather than discarded. The dump was **230 MB for 10 runs**, essentially all of it
`cycle_snapshots`: a direct measurement of defect D1, since `prune_old_snapshots` is
never called and nothing can read the rows back. The container volumes are left in
place as a fallback.

**WP2.2 — Free-threaded CPython.**
Install `python-freethreading` (3.14.6, available via Homebrew) and run the suite under
it, before any threading work is designed.
*Verify:* suite green under the free-threaded build; benchmark reports single-threaded
overhead versus the standard build.
*As built:* `PYTHON_GIL=0 .venv-ft/bin/python -m pytest tests/ -q` is green, the slow
tests included. The oracle's worker pool resolves its backend from a candidate list, so
an interpreter without NumPy runs it on the pure-Python reference.
*Risk:* SQLAlchemy/asyncpg free-threading readiness.

**Done.** `python3.14t` (3.14.6, `Py_GIL_DISABLED=1`) with a parallel venv at
`.venv-ft`. Suite green: **797 passed** under free-threading, on the checkout at which
WP2.2 landed.

*The risk was real, and the engine-purity invariant is what defuses it.* Importing
SQLAlchemy **re-enables the GIL at runtime** — `sqlalchemy.cyextension.collections` has
not declared free-threaded safety, and CPython silently switches the GIL back on when
it loads. But importing the *entire engine* leaves the GIL off, because the engine
imports nothing beyond the standard library and itself. That is precisely the property
WP0.2 enforces, and it means Stage 4's codelet parallelism gets a genuinely GIL-free
interpreter while only the API process pays. `PYTHON_GIL=0` overrides the re-enable and
SQLAlchemy still works, so the whole suite can be run with the GIL truly off.

*Single-threaded overhead, measured:*

| Problem | Standard | Free-threaded | Overhead |
|---|---|---|---|
| `abc→abd; ijk?` (1) | 27.7 ms | 30.3 ms | +9.4% |
| `abc→abd; xyz?` (7) | 51.4 ms | 54.7 ms | +6.4% |
| `abc→abd; xyz?` (42) | 56.6 ms | 62.2 ms | +9.9% |
| `abc→abd; iijjkk?` (42) | 115.3 ms | 122.8 ms | +6.5% |
| `abc→abd; mrrjjj?` (42) | 170.9 ms | 191.0 ms | +11.8% |

Codelet counts are identical on both builds, so this is the interpreter's cost and not
different cognition. **Roughly 9% is the toll Stage 4 must beat**, against a recomputed
ceiling of 1.67× for codelets alone and 3.32× including the numeric substrate — so the
toll is repaid well before two workers.

*A failure that was not what it looked like.* One full-suite run under free-threading
produced two e2e failures — `relation "runs" does not exist` — which no later run
reproduced. Read as a free-threading defect, it was not one. `setup_db` drops and
recreates every table at session scope, so **two pytest sessions sharing
`petacat_test` destroy each other's schema mid-run**; the free-threaded run had simply
overlapped another suite. Reproduced deliberately on the *standard* build by launching
two e2e sessions at once: identical errors, in the same test file, while the other
session passed.

Fixed in `tests/e2e/conftest.py` with a Postgres advisory lock held on a dedicated
connection for the session, so concurrent sessions serialise instead of interleaving.
Verified with three simultaneous suites across both interpreter builds: 93 passed in
each. Worth recording because Phase 0 runs the suite constantly while agents work in
parallel, and because the symptom points nowhere near the cause.

### Stage 3 — Persistence modes

**WP3.0 — Name the Training Session; keep its semantics unchanged.**
Session continuity is **already correct** — Episodic Memory carries across Runs, the
rest is rebuilt — so this package adds no state-continuity behaviour. It gives the
existing concept a first-class representation so Runs can be grouped, reviewed, and
compared: a `training_sessions` row, `Run.session_id`, and the Admin reset
(`DELETE /api/memory`) recorded as the session boundary it already is.
*Files:* `models/run.py` (`training_sessions` table, `Run.session_id`), migration,
`services/run_service.py`, `api/memory.py:42` (record the reset as a session boundary),
`client/` (session grouping in the review UI).
*Verify:* Runs group under sessions; a memory clear starts a new session; **cognition
is untouched** — this package must not modify `init_mcat` at all.

**Done.** A `training_sessions` row and `Run.session_id`. Sessions are not created by
the user; a session is the span between memory clears, which is already how the concept
worked, so the service opens one lazily when a Run needs one. `init_mcat` was not
touched.

**WP3.1 — Split serializers from the ORM (fixes D2).**
Move the pure `serialize_*` functions into `server/engine/serialization.py` with **no
database imports**; leave persistence in `server/services/snapshot_repository.py`.
*Files:* `services/snapshot_service.py` → split; callers in `run_service.py`,
`tests/module/test_codelet_behaviours.py:920`.
*Verify:* WP0.2's purity test extended to assert the serialization module imports no
SQLAlchemy; existing tests green.

**WP3.2 — Define the `RunSink` port.**
Protocol with `on_run_created`, `on_codelet`, `on_trace_event`,
`on_structure_change`, `on_turn_end`, `on_answer`, `on_valence`. Methods take the live
`EngineContext`, never a pre-serialised payload.
*Files:* new `server/engine/sink.py` (protocol only — no implementations, so the
engine stays pure).
*Verify:* engine compiles and runs with the fast sink; no behavioural change.

**WP3.3 — Thread the sink through the runner; take persistence out of the step loop.**
`run_service.step` and `run_to_completion` stop calling `_persist_new_trace_events`
and `save_cycle_snapshot` inline; they attach a sink instead. Also removes the
per-codelet `await` and list-slice, and the `await asyncio.sleep(0)` in
`run_to_completion` (`:387`) — which alone costs ~16 µs per codelet.
*Files:* `engine/runner.py`, `services/run_service.py:160–205, 355–405`.
*Verify:* expected range unchanged; the 148 snapshot flushes and the per-codelet
coroutine overhead both gone; benchmark harness shows the step loop doing engine work
only.

**Done.** Persistence lives in `server/services/sinks.py`; the step loop is engine work
only. In-run database traffic is now **zero** — the 148 snapshot flushes are gone, and
trace events and answers are buffered by the sink and staged once per API call instead
of awaited per codelet.

*Throughput, end to end across Stage 0–3 so far:* `abc→abd; mrrjjj?` runs at
**13,627 codelets/s** against the plan's 7,641/s baseline — **1.78×**, with cognition
bit-identical.

*One deviation, deliberate.* The plan asks for the per-codelet `await asyncio.sleep(0)`
in `run_to_completion` to be removed outright. Removing it entirely makes a run
**uninterruptible**: the stop flag and the breakpoint are set by *other* HTTP requests,
and a loop that never yields never lets them be served. It now yields once per update
cycle instead of once per codelet — fourteen fifteenths of the cost removed, pause and
stop still responsive to within about a millisecond.

**WP3.4 — Complete, restorable state capture (fixes D1).**
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
inspectable and versionable, and directly renderable by the review UI (WP3.9).

The per-15-codelet snapshot, `prune_old_snapshots` and the partial `restore_*` set go.
*Files:* `services/snapshot_service.py` → new `engine/serialization.py` +
`services/state_repository.py`, `models/run.py:57+`, `services/run_service.py`,
migration, `tests/e2e/test_persistence.py`, `tests/e2e/test_api_runs.py:286`.
*Verify:* **round-trip fidelity** — capture state mid-Run, restore into a fresh
process, continue, and reach the same end state as an uninterrupted Run.

**Done**, as `server/engine/state_graph.py`. Round-trip fidelity holds at four capture
points — 15, 150, 450 and 1,100 codelets — each restored into a fresh runner through
JSON and run on, reaching a state identical to the uninterrupted run across structures,
coderack, trace, slipnet and themespace activations, RNG call count and identifier
counters.

**Fields are captured reflectively, from `vars(obj)`, rather than enumerated per
class.** Enumeration is precisely how the display serializer rotted: a field added to a
structure is simply absent from a hand-written list and *nothing fails*, so the capture
quietly stops being complete. Reflection makes "captured" the default and an
unrepresentable value an error, so forgetting is not an available mistake. That paid
for itself immediately — the walk refused two types the design had missed
(`SlipnetLink` held by a concept-mapping, and `StringImage`), both of which a
hand-written list would have dropped in silence.

Three kinds of thing are referenced rather than copied, and the distinction is the
design: Slipnet nodes and links by name (configuration, not state — only their
activations are captured), Workspace strings by role, and the environment
(`MetadataProvider`, `Slipnet`, the string→Workspace back-reference, the coderack's
RNG) re-linked on restore.

*The identifier counters travel with the state*, because they are not derivable from
it: a structure that was proposed, took an id and then fizzled leaves nothing behind,
so a restored run recounting from surviving objects would re-issue ids it had used.

*Retired as promised:* the per-15-codelet snapshot, `prune_old_snapshots`, and the four
write-only `restore_*` functions are gone.

**WP3.5 — Named, versioned inputs: config-hash and memory-hash.**
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

**Done**, as `server/engine/hashing.py`. Both are content hashes over a canonical JSON
encoding, so they are stable across processes — anything derived from object identity or
insertion order would make an unchanged configuration look different on every restart,
and a field that reports spurious change stops being trusted.

The config hash covers what changes what the engine *does*: Slipnet nodes and links,
codelet sources, posting rules, parameters, urgency levels, formula coefficients, theme
dimensions. It deliberately excludes the demo catalogue, the display layout, the
commentary templates and the enum tables — editing a demo problem or moving a node on
screen does not change how any run thinks.

The memory hash is taken **before** the run executes: it identifies the memory the run
*inherited*, not the one it left behind.

**WP3.6 — Fast Run.**
Fast sink; no session, no engine, no connection; **and no construction of any storable
representation** (§A2 requirement 2).

> **As built.** The Episodic Memory and the commentary are shared with every mode.
*Files:* `services/run_service.py`, `api/runs.py`.
*Verify:* three separate tests, because the two requirements fail differently —
 (a) a Fast run completes normally with **the database stopped**;
 (b) the async engine / session factory is **never constructed** during a Fast run;
 (c) an allocation probe over a Fast run shows **no `serialize_*` call, no `json.dumps`,
 and no growth in any record buffer** — the check that catches a well-meaning
 "buffer now, write later" implementation.

**Done**, and stricter than "no writes": a Fast Run **never touches the session at all,
including at creation**. It has no `runs` row, so it has no database identifier either —
it takes a negative one from an in-process counter, which a positive autoincrement column
can never collide with.

> **As built.** A Fast Run takes full part in the Training Session: the Episodic Memory is
> the shared one and the commentary is real. Its answers are available to the runs that
> follow, and `answer_present` stops them being rediscovered.

Creation had to be included. A run that inserted a row and then wrote nothing more would
still fail with the database stopped, which is the condition the mode is verified under.

Requirement 2 is enforced structurally rather than by inspection: `FastSink` subclasses
the engine's `NullSink` and inherits its empty `__slots__`, so there is nowhere for a
"buffer now, write later" implementation to accumulate. The test asserts the sink has no
instance dictionary at all.

**WP3.7 — Normal mode.**
Two complete-state captures per Run, via WP3.4: one at Run start, one at Run end.
Nothing else — no mid-Run records, no per-cycle anything.
*Files:* `services/run_service.py`, `models/run.py` (Run-boundary state rows),
migration.
*Verify:* reload a recorded Run-start state, re-execute the Run, and reach the
recorded Run-end state exactly. Additionally: a Normal Run placed **after** other Runs
in a Training Session records a start state whose Episodic Memory reflects them — the
check that the one thing which does cross Run boundaries is actually captured.

**Done.** Exactly two `run_state_captures` rows per Run, and re-execution from the
recorded start state reaches the recorded end state. Both checks above are tested,
including the mid-session one.

*A bug the re-execution test caught, which nothing else would have.*
`Themespace.active_theme_types` is a **list** that `thematic_pressure_on` appends to;
restoring it as a set raised `'set' object has no attribute 'append'` — but only later,
and only on runs that got as far as clamping a negative theme pattern. A restore that
merely *looked* right would have shipped it.

**WP3.8 — Audit mode.**
Record every state-changing action during the Run as a **forward log**. Buffering in
memory and flushing once at Run end is permitted. Forces serial execution.
*Files:* `services/run_service.py`, `models/run.py`, migration.
*Verify:* from the recorded actions plus the Run-start state, every intermediate state
can be reconstructed **in forward order**; the mode refuses to start if a parallel
scheduler is configured.
*Scope — forward only in Phase 0.* Backwards scrubbing constrains the record format,
not merely the UI. **The format should not foreclose it:** record enough before-state
that actions could be inverted later, but do not build the inverse-replay machinery.

**Done.** `audit_actions` rows with a dense `sequence`, plus the two boundary captures to
replay forward from. Each structure change carries a `before` field sufficient to invert
it; the inverse-replay machinery is deliberately not built.

**WP3.9 — Review UX.**
Normal session/Run browser and Audit action-scrubber, reusing the existing views
against recorded state.
*Files:* `client/src/components/` (new review components), `client/src/api/client.ts`,
new read endpoints in `api/runs.py`.
*Verify:* a run recorded in each mode can be reconstructed and inspected in the UI.

**Done.** A `server/api/review.py` router and a `ReviewPanel` component tree: a Training
Session browser, a start-vs-end comparison, boundary states rendered through the
existing views, and a forward-only Audit inspector. Verified against the real stack —
a Normal run, an Audit run and a Fast run created over HTTP, then the actual component
tree rendered against the live API and driven by clicks.

*The existing views were refactored to pure props rather than copied* —
`WorkspaceDiagram`, `ThemespaceGrid`, `TraceList`, `CoderackBars` — with thin
store-reading wrappers keeping live behaviour unchanged. `SlipnetGraphView` resisted
the split and was left alone with `readOnly` props instead: it is an interactive surface
whose right-click clamps a node, and clamping is meaningless on a recording.

*The comparison shows a summary, not two blobs.* Two captures are ~110 KB each and
nearly identical; the comparison is ~7 KB — codelets, temperature delta, structures
built by string and bridge kind, the rules the run ended holding with their English, the
top Slipnet activation changes, the themes that moved and which were **dominant at the
end**, and what the run added to the Training Session's Episodic Memory.

*The Audit inspector re-executes rather than reads.* The action log holds the codelet
and the temperature at each tick but not Slipnet or Themespace activation, and the plan
asks for those, so the inspector restores the Run-start capture and walks a real engine
forward — the reconstruction mechanism WP3.8 names. That is only legitimate if the
reconstruction *is* the recorded run, so it is checked: the first 25 recorded actions
must match the reconstruction's codelet type and temperature at every tick.

**Two defects in WP3.4 that this package found**, both now fixed with tests that would
have caught them:

- **`GRAPH_TYPES` listed `TraceEvent` but none of its three subclasses.** `isinstance`
  matches the base on capture, so capturing worked; the reader keys on the concrete type
  name, so **restoring failed on any run that answered, snagged or clamped** — nearly
  every interesting Normal run, and exactly the end-of-run capture. Two things hid it:
  the round-trip tests use `abc→abd; mrrjjj` and stop before any rich event type
  appears, and the mode tests restore only the *start* capture, where the trace is empty
  by construction. There is now a structural guard as well as a round-trip test, so a
  *new* event subclass cannot reopen it.
- **A run that answered has created an answer string** which a runner freshly
  initialised in discovery mode does not have, and references to it resolve by role. The
  restore now builds it the way `report_answer` does.

**WP3.10 — Commentary becomes a sink concern.**
`CommentaryLog` accumulates output that no part of cognition reads back — the engine
only calls `emit_*` → `add_comment`; `render`, `get_paragraphs` and `count` are
API-only. Replace `ctx.commentary` with an injected writer, so the engine calls
`emit_*` unconditionally and the writer decides what becomes of the paragraphs.
*Files:* `engine/commentary.py`, `engine/runner.py` (context construction),
`engine/jootsing.py`, `engine/codelet_dsl/builtins.py`, `services/run_service.py`
(`get_commentary`).
*Verify:* expected range unchanged; commentary unaffected by mode; the `eliza_mode`
re-render path still works.

**Done.** `CommentaryWriter` is a protocol and `CommentaryLog` implements it. The
engine emits unconditionally. Confirmed the plan's premise first: the engine only ever
calls `emit_*` → `add_comment`, and `render`/`get_paragraphs`/`count` are read solely by
`run_service.get_commentary`.

> **As built.** Every mode is given a real `CommentaryLog`. `GET /commentary` is served
> in every mode, and `tests/module/test_commentary_writer.py` holds the arrangement:
> the injected writer receives the run's commentary, both construction paths build a
> real log, and the engine exposes one writer.

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

**Done**, as `server/engine/splittable_rng.py`. **The set did not move**: 13 problems ×
150 runs under a completely different generator gave **0 novel states and 0 missing
states**. That is a strong validation of the oracle itself, not only of the RNG — it was
the sharpest available test of the premise the whole verification strategy rests on.

*Why counter-based.* A Mersenne Twister has 19,937 bits of state that every draw
advances, so concurrent codelets either serialise behind a lock — reintroducing the
contention the parallelism is for — or corrupt it. A counter-based generator *computes*
the n-th value of a stream from `(seed, stream, counter)` instead of holding state that
advances, which buys three things free-running needs: streams independent without
coordination, a stream evaluable without evaluating the ones before it, and splitting
cheap enough to do per codelet.

The second is the one that matters most and is easy to miss. Reproducing draw *n* from a
stateful generator requires having made draws 0…*n*−1 **in the same order**, and under
free-running that order does not exist. Counter-based streams are addressable.

*Substream derivation is hashed rather than added.* Seeding stream *n* with `base + n`
leaves consecutive workers drawing near-identical sequences — under free-running, every
worker making the same decision at the same instant. Tested directly: fewer than 5 of
200 adjacent streams produce near-equal first draws.

*No engine module needed changing.* The engine already takes its generator from the
context rather than reaching for a global, so an API-compatible surface was enough — the
swap is two assignments. The twelve modules the plan lists as callers were untouched.

*State is three integers* — `(seed, stream, counter)` — against the 625-element tuple
that had to be pickled to be stored, which makes a WP3.4 capture both smaller and
readable.

**WP4.2 — Read-set / write-set discipline in the builtins.**
`codelet_dsl/builtins.py` (998 LOC, 45 top-level functions) is where codelets mutate
shared state. Classify each mutating builtin (`propose_bond`, `build_structure`,
`break_structure`, `post_codelet`, `record_event`, `activate_from_workspace`, …) and
introduce the delta-and-commit split the commit protocol needs.
*Files:* `engine/codelet_dsl/builtins.py`, `engine/workspace_structures.py`.
*Verify:* serial behaviour unchanged; read/write sets recorded and inspectable.

> **As built.** `builtins.py` holds 2,761 lines across 91 top-level functions.

**Done**, as `server/engine/access.py`. Ten of the 33 public builtins mutate state; each
now records what it read and what it wrote, and each codelet is validated at its own
commit point.

*Optimistic validation rather than locking.* Locking the objects a codelet touches would
serialise exactly the contention the parallelism is for, and it invites deadlock — a
bridge scout takes objects in two strings, and two scouts taking them in opposite orders
is the textbook case. Versioned validation has neither problem, and it suits this engine
unusually well because a fizzle is not a retry-with-backoff here but a **normal outcome
the temperature already accounts for**.

*Granularity is a policy in one function*, `AccessSet.key_for`, since the plan flags it
as an open question. It is currently per object, per structure and per Slipnet node —
matching how codelets actually work, since a bond scout touches two adjacent objects
rather than a string. Coarsening it is a change to one function.

**A design bug the serial test caught, which would have broken free-running
completely.** A codelet very often reads an object and then writes it — a bond builder
reads the two objects it is bonding and then changes both — so its own write bumped the
version its own read-set was validated against. Serially, where the answer must be zero,
it recorded **49 self-conflicts in 800 codelets**. Under free-running every such codelet
would have fizzled, and the symptom would have read as "cognition cannot tolerate
concurrency" rather than as an arithmetic error. Writes are now counted per key, so
expected = version read + bumps I made, and anything beyond that is somebody else.

*Serial behaviour is unchanged* — same status, answers, codelet count, RNG call count
and trace — and a serial run records **zero conflicts**, because nothing runs between a
codelet's reads and its commit. That is what makes turning tracking on a no-op for
behaviour and a source of telemetry for WP4.4.

**WP4.3 — Coderack sharding.**
Per-worker racks with work-stealing — the hardest problem in the phase, since
urgency-weighted probabilistic selection across seven bins is not trivially
decomposable. Options: shard by codelet family, shard by workspace region, or one rack
behind a lock-free structure.
*Files:* `engine/coderack.py`, `engine/runner.py`.
*Verify:* expected range unchanged at one worker.

**Done.** All three candidates were built (`server/engine/coderack_shards.py`) and
measured (`scripts/bench_shards.py`), rather than one being chosen on argument.
**The winner is per-worker racks with work stealing.**

*Fidelity — total-variation distance from the unsharded rack's selection distribution,
by codelet type:*

| candidate | T=100 | T=70 | T=40 | T=10 |
|---|---|---|---|---|
| locked single rack | 0.000 | 0.000 | 0.000 | 0.000 |
| **shard by family** | 0.078 | 0.234 | 0.316 | **0.354** |
| **per-worker + stealing** | 0.016 | 0.013 | 0.006 | **0.014** |

**Family sharding fails, and fails worst exactly where it matters most.** Codelet
families are not evenly spread across urgency bins — bottom-up scouts sit at low urgency,
answer-finders at `100 − temperature` — so a family shard's bin occupancy is
systematically unlike the whole rack's, and a worker confined to one sees a different
temperature response from the architecture's. At T=10, where selection is supposed to
become greedy, **35% of draws go to the wrong codelet type**. That is not a slower engine;
it is a different one.

Per-worker sharding holds at 0.006–0.016 at every temperature, for a structural reason:
a codelet's shard is independent of its type *and* its urgency, so each shard's bin
occupancy is an unbiased sample of the whole rack's and the two-stage draw keeps its
distribution in expectation.

*Contention and throughput, free-threaded, 8 shards, GIL genuinely off:*

| candidate | 1 worker | 2 | 4 | 8 | contention @8 |
|---|---|---|---|---|---|
| locked single rack | 278k/s | 202k | 142k | 102k | 0.76 |
| shard by family | 201k | 169k | 132k | 103k | 0.87 |
| **per-worker + stealing** | 217k | **260k** | 226k | **152k** | **0.61** |

Per-worker sharding is the only candidate that *gains* from a second worker, and it is
**1.50× the locked rack at eight**.

**Expected range unchanged**: 13 problems × 100 runs with the sharded rack installed —
**0 novel, 0 missing**.

*Two things the measurement corrected in my own first draft*, both worth recording because
they were invisible until measured:

- The first sharded implementation was **slower than a single locked rack**, because it had
  a shared round-robin cursor behind a lock on every post and sorted every shard by
  occupancy on every steal. Both are global serialisation points, so the sharding bought
  nothing. Thread-local shard assignment and a rotating steal probe fixed it.
- The first fidelity harness scored every candidate a perfect 0.000, which was the
  *measurement* being wrong: draining and refilling a rack means eventually drawing
  everything in it, so observed frequencies converge on the posted mix regardless of
  selection order. Selection preference is only visible while something remains unchosen.

*"Shard by workspace region", the plan's third option, cannot be built as stated.* **A
codelet does not know its region until it runs.** A bottom-up bond scout chooses its
object during execution, by salience-weighted draw over the whole Workspace — that choice
is the first thing it does. Only top-down codelets carry a triggering slipnode, and even
they do not name a string. Partitioning by region would require deciding each codelet's
region before the codelet has decided it, which is not a scheduling problem but a
contradiction.

*An honest limit on the contention numbers.* Throughput still declines beyond two workers
for every candidate. The microbenchmark's workers do nothing but rack operations, so it is
a pure contention test; in the real engine a codelet does substantial work between draws,
which is what WP4.4 measures.

**WP4.4 — Free-running.**
Continuous execution, no global barrier, conflict → fizzle.
*Files:* `engine/runner.py`, new `engine/free_running.py`.
*Verify:* expected range unchanged; scale 1→2→4→8 workers; fizzle-rate telemetry and
throughput per worker count. Read-set granularity tuned here (B4).

**Done**, as `server/engine/free_running.py` plus `scripts/bench_free_running.py`.
Free-running is a *wrapper* around a prepared runner rather than a mode the serial loop
grew, so the permanent reference mode keeps exactly the shape it has and cannot acquire
concurrency bugs by proximity.

*Throughput, free-threaded, best of 3, against the serial loop:*

| problem | serial | 1w | 2w | 4w | 8w |
|---|---|---|---|---|---|
| `abc→abd; mrrjjj?` | 11,988/s | 0.85× | 0.97× | 1.23× | **1.33×** |
| `abc→abd; iijjkk?` | 11,148/s | 0.93× | 1.19× | **1.35×** | 1.31× |
| `abc→abd; xyz?` | 13,454/s | 0.75× | 1.09× | 1.20× | 1.14× |

**Against a ceiling of 1.67× (WP1.2) less ~9% free-threading overhead (WP2.2), the
realistic maximum is about 1.52×, so 1.35× is roughly 89% of what parallelising codelets
*can* give.** The remainder is the serial fraction the plan identified from the start:
coderack maintenance and the numeric substrate. Conflict rate 0.000–0.006.

*What is serialised, and why that is the design rather than a compromise avoided.* A
codelet is a long read-and-decide followed by a short mutation. The update cycle is **not**
stopped for — whichever worker crosses the boundary runs it while the others continue,
which is precisely the staleness WP0.5 bounded. Committing a structure **is** serialised,
because `build_structure`'s duplicate check and its fights are read-modify-write sequences
over shared lists: running two concurrently corrupts the lists rather than producing a
conflict the model could interpret as a fizzle.

**This is not deferred-commit optimistic concurrency.** A codelet's writes land as it makes
them, so validation reports a moved read-set as *telemetry* rather than rolling anything
back. Deferring writes into a delta and applying it atomically is the next step, and
WP4.2's discipline is the groundwork for it. Stated plainly because the difference is easy
to overclaim.

**Three concurrency defects found and fixed, each invisible to the one before it:**

- **Self-deadlock.** `build_structure` takes the commit lock, then calls `break_structure`
  for each opponent it defeats and `record_event` for the group, slippage and rule events
  a build produces — all of which take the same lock. With a plain `Lock` the first codelet
  that won a fight deadlocked against itself, and the symptom was **a run producing no
  output at all** rather than an error.
- **A single answer recorded twice** at eight workers (`['mrrjjk', 'mrrjjk']`). Two
  answer-finders can each reach an answer before either is collected, so clearing the
  pending slot is not enough on its own — the run has to refuse a second answer once it
  has one.
- **`gave_up:b` — two terminal outcomes racing.** `report_answer` sets both the pending
  answer and `workspace.answer_string`; a jootser sets `_gave_up`; the collector checked
  give-up first. The run was recorded as having given up while the Workspace still held
  the answer it had found, and the pending answer was left queued and never collected.
  Serially this is impossible: the runner collects the answer before any other codelet
  executes. The terminal outcome is now claimed once, atomically, and **an answer wins** —
  both events happened, but they are not symmetrical, since an answer is a positive result
  the program produced while giving up is the claim that none was found.

**Reachable from the API**, not merely implemented. `POST /api/runs` takes `workers`,
defaulting to 1 — the serial loop, which stays the reference mode — and above 1 the Run
executes free-running. Audit **refuses** anything above 1 rather than quietly going
serial, because its forward log reconstructs by replay and under free-running the order it
records is not the order things happened in. `GET /api/runs/{id}/telemetry` reports the
worker split and the conflict rate, which cannot be reconstructed from the run's record
afterwards. Persistence is unchanged: the sink collected throughout and is flushed once,
exactly as for a serial Run — the payoff of the `RunSink` port is that no mode had to
learn about concurrency.

**Wiring it in immediately exposed three defects that benchmarking never could**, which is
the argument for connecting a capability rather than only measuring it:

- The state capture reached for `coderack.clamped_urgencies` and `max_size`; the sharded
  rack had neither, so a Normal free-running Run raised at its first boundary capture.
- `bins` returned the shards' bins end to end — `7 x num_shards` — making a captured
  coderack **un-restorable**, since a restore indexes `bins[index]` on a plain seven-bin
  rack. Sharding decides which worker holds a codelet, not what urgency it is, so the
  seven levels are now merged across shards.
- **Sharding was multiplying the rack's capacity by the shard count.** Each `Coderack`
  enforces `max_coderack_size` for itself, so eight shards held 800 codelets rather than
  100. That is not bookkeeping: the cap is why the codelet mix keeps tracking the current
  Workspace, and the rack sits at capacity for 58% of posts.

**And correcting the capacity broke the oracle, which is how the real finding was
found.** With the capacity properly divided, eight shards of twelve made the stopping
state `gave_up:` **disappear entirely** from `eqe->qeq; abbba?` — 0 occurrences in 60 runs
against 23 for the serial engine, on that problem's *most frequent* outcome (38.9%). The
`missing` signal is the one the oracle exists for, and it fired.

The cause is not the answer-wins rule and not float32; it is that **a twelve-codelet shard
is too small to be a coderack**. Giving up is the end of a sequence — snags accumulate, a
clamp is applied, jootsers observe the repetition — and each step needs its codelets still
on the rack when the next one looks. Measured directly:

| configuration | `gave_up:` in 60 runs | answered |
|---|---|---|
| 1 worker, 1 shard (serial-equivalent) | 23 | 27 |
| 4 workers, 4 shards (25 each) | 14 | 36 |
| **8 workers, 8 shards (12 each)** | **0** | 56 |
| 8 workers, 4 shards (25 each) | 19 | 30 |
| 8 workers, 2 shards (50 each) | 27 | 29 |

So shard count is now bounded by **capacity**, not by worker count: `MIN_SHARD_CAPACITY`
is 25, giving at most four shards at today's rack size. More workers than shards is
allowed and costs contention; more shards than the capacity supports costs *cognition*,
and that is not a trade worth making. With the floor in place both 4 and 8 workers are
clean.

*Expected range, bisected on worker count as the plan prescribes:*

| workers | novel states | frequent states lost |
|---|---|---|
| 1 | 0 | 0 |
| 2 | 0–1 | 0 |
| 4 | 0–1 | 0 |
| 8 | 0 | 0 |

(measured after the shard-capacity floor; before it, 8 workers lost `gave_up:` on two
problems)

**No frequent state was ever lost at any worker count.** Before the three fixes above,
4 workers produced 5 novel states per 780-run sweep against a false-alarm expectation of
~0.01; afterwards it is 0–1. Seven of those states were reviewed and **admitted to the
baseline as valid stopping states** rather than defects — recorded per problem under
`admitted_states`, with `build_expected_range.py` taught to carry them through a rebuild,
since `expected_range` is otherwise reconstructed from the saturation counts and they would
be silently dropped. `gave_up:b` was the one rejected, and it was a real bug.

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

**Done**, as `server/engine/numeric/` plus `scripts/bench_numeric.py`. Four backends —
pure-Python reference, NumPy float64, MLX GPU float32, MLX CPU float64 — behind a
size-aware selection policy.

*Kernel timings, ms per update cycle, M2 Max, fastest of 25:*

| nodes | edges | python | numpy | **mlx (GPU)** | mlx-cpu |
|---|---|---|---|---|---|
| 59 | 202 | 0.011 | 0.007 | 0.187 | 0.050 |
| 10³ | 3,424 | 0.245 | 0.029 | 0.178 | 0.131 |
| 10⁴ | 34,237 | 2.76 | 0.245 | 0.298 | 1.13 |
| 10⁵ | 342,373 | 43.10 | 2.54 | **0.324** | 9.70 |

**The crossover is ~10⁴ nodes for the kernel, and between 10⁴ and 10⁵ for the round
trip.** By 10⁵ the GPU is 7.9–14.8× ahead of vectorised float64 CPU. The GPU column is
almost **flat from 59 to 100,000 nodes** (0.18 → 0.32 ms) — still dispatch-bound at
342,000 edges — so the headroom toward the ~300,000-node target is large.

**The GPU runs at every size, and that is a requirement rather than a tuning choice.**
B1 states what the phase is for — "the system's numeric work executing on the **GPU
cores**" — and 59 nodes is the only size the engine currently runs at, so a policy that
declined the GPU below some threshold would ship a substrate that never executed. `auto`
therefore selects the GPU whenever MLX is available, at 59 nodes as at 300,000.

*An earlier version of this work gated selection by size* — reference loops below 512
nodes, vectorised CPU to 32,768, GPU above — on the reasoning that the fastest backend is
the wrong choice at three of the four sizes. That reasoning is correct about throughput
and wrong about the goal. The gating is retained as
`PETACAT_NUMERIC_MIN_GPU_NODES`, defaulting to 0, for anyone who needs the CPU path while
profiling.

**The cost is real and is documented rather than avoided: ~9× at 59 nodes.** A Metal
dispatch is ~0.2 ms whether it carries 200 edges or 340,000, while vectorised CPU finishes
the whole update in 0.007 ms, so the dispatch is the entire cost. That is a fact about the
Slipnet as it stands, not the one being built — at the measured crossover of ~10⁴ nodes it
reverses, and by 10⁵ the GPU is 7.9–14.8× ahead.

*Two optimisations that followed from making it always-on*, neither of which would have
been worth finding while the substrate never ran:

| | host syncs per `mrrjjj` run |
|---|---|
| as first written | 1,671 |
| `average_unhappiness` fused to one sync | 557 |
| plus caching it per update cycle | **148** |

The cost of the substrate at this size is dominated by reading scalars back to the host,
not by arithmetic. `average_unhappiness` is the most-dispatched operation in the engine —
557 calls in a 2,229-codelet run, because the temperature update and the description
scouts' posting probability both ask for it — and it was reading `total` back to *decide
which branch to take* and then reading the branch's result. Expressing the branch in the
graph makes it one sync. Caching then exploits the fact that nothing between those two
call sites can change the value, taking it to exactly one per update cycle. Same answer,
same codelet count throughout.

*The gap between kernel and round trip is the useful finding.* It is entirely the
object-graph adapter — the host sync the probabilistic jump forces, plus marshalling
through Python lists — and it disappears when the flat layout becomes primary rather than
a projection of Python objects. WP4.1's splittable RNG is what would let the jump move
on-device.

*Layout is destination-major CSR, chosen for determinism as much as for scale.* The
reference *scatters* from sources, which on a GPU needs atomic float addition — and that
is not deterministic in accumulation order, which is unacceptable for an architecture
whose verification rests on a run being a function of its seed. Gathering per destination
is atomic-free and fixed-order. The regroup is exact because `round` is applied per edge,
so the summands are integers ≤ 100. And `intrinsic_degree_of_association` never consults
an activation, so **the sparse matrix is entirely static** — built once, never rebuilt.

*Numerical agreement.* The three float64 backends are **bit-identical** to the reference
— same answer, same codelet count, same RNG draw count. The GPU is float32 (float64 is
unsupported on Metal, which is hardware and not MLX), with a 1e-3 absolute tolerance
against a measured worst drift of ~4e-5 over 40 cycles; a formulation error would differ
by *ones*, since these are sums of integers, so the tolerance cannot hide one.

**Expected range unchanged on all four backends, including GPU float32** — 100 runs × 13
problems each, no novel states. Re-verified after the GPU became the default rather than
an override: **20 passed, no novel or missing states**, which is the gate that matters
most here, because the float32 path is now what every run takes. The GPU row is the substantive one: float32 genuinely
flips jump draws, so the runs diverge and land on different answers, and the reachable
*set* is still unchanged. That is the oracle's claim tested a second, independent way.

**The check found a real defect.** On `eqe→qeq; abbbc` the engine reaches states where all
raw importances are ~2.4e-48. The ratio is an ordinary 33, but **MLX routes Python
scalars through float32 even inside a float64 graph**, so the denominator flushed to zero
and every relative importance became `inf`. Fixed structurally: relative importance is
computed on the host in float64, so no backend ever sees a value outside [0,100].

*Where MLX could not express what was needed:* segmented reduction over ragged CSR with
per-edge rounding (its only primitive is a non-deterministic atomic scatter — hence the
hand-written Metal kernel, which beats composed MLX ops by 1.0–1.5×); `metal::simd_sum`
fixed at 32 lanes, where one-SIMD-group-per-row is **2.7× too slow at 300,000 nodes**
because mean in-degree 3.4 leaves 29 of 32 lanes idle; and no boolean indexing, so
jump-candidate compaction happens on the host through a zero-copy view.

**WP4.6 — Population batching.**
Batch K independent runs so the GPU sees fat batched kernels — what Phase 4 corpus
training, Phase 6 evolution and the expected-range oracle all need.
*Verify:* runs/second at K = 1, 8, 32, 128 against the CPU-only baseline.

**Done**, as `server/engine/population.py` and `scripts/bench_population.py`. The unit is
deliberately **runs per second**, not codelets per second: corpus training, evolutionary
search and the oracle are all bounded by how many *complete runs* an hour buys, and a
change that makes one run 1.3× faster while halving how many fit on the machine is a loss
for all three.

| K | process-parallel | batched lockstep |
|---|---|---|
| 1 | 5.4 runs/s | 34.9 |
| 8 | 27.5 | 13.7 |
| 32 | 61.4 | 12.5 |
| 128 | **70.8** | 12.1 |

**Batching does not pay at 59 nodes, and the measurement says so plainly.** Process-parallel
scales to 70.8 runs/s while batched lockstep stays flat near 12. Two reasons, both
structural rather than incidental: the numeric substrate is 0.007 ms per update cycle on
vectorised CPU, so batching 128 of those into one ~0.2 ms GPU dispatch is slower than doing
all 128 on the CPU (WP4.5's crossover is ~10⁴ nodes); and lockstep **holds every finished
run hostage to the batch's slowest**, which on the demo problems differ by an order of
magnitude in length.

So `batching_is_worthwhile(node_count)` is a predicate against WP4.5's measured threshold
rather than a policy buried in a loop, and `on_cycle` is a *seam* handed every live runner
at a shared boundary rather than a batched kernel. Building the kernel now would ship an
unmeasurable optimisation and a second numeric code path to keep correct. The seam is
tested for the thing that would make it unusable later: that all live runs really do sit at
the same codelet count when it fires.

**The two strategies produce identical stopping states** for the same seeds, and a run's
outcome does not depend on how many others it was batched with — which is the property
WP0.3 made possible by removing the process-global identifier counters, and which would
otherwise make a batched population incomparable with the process-parallel baseline.

---

## Beyond the plan — per-Run parameters

Not part of Phase 0 as written, added on request while the phase was being committed, and
recorded here because the plan is the record.

**Twenty-five parameters became per-Run.** `engine_params.json` holds 43 entries, of which
**25 are read by the engine while it thinks** — thresholds, periods, capacities, the
update cadence. Every one was global: editable only in the Admin panel, applying to every
Run at once, and present in a Run's row only indirectly through the config hash. So an
experiment was awkward to run, and a past Run was awkward to interpret, because the
parameters it executed under were whatever the global configuration happened to be.

The other 18 are deliberately not offered. Display timings (`initial_speed`,
`text_scroll_pause`, the flash settings), Scheme-era implementation details
(`garbage_collect_cycles`, `step_cycles`), and several the port reads nowhere at all
(`expiration_period`, `max_theme_activation`, `workspace_activation`,
`shrunk_link_lengths`). **Membership is decided by what the engine actually reads**,
verified against every `get_param` call site in `server/engine/**` *and* in the codelet
bodies stored in `seed_data/codelet_types.json` — and pinned by a test, because offering
a control that changes nothing is worse than offering none.

*Fixed and derived are kept apart.* Fixed parameters are inputs, constant for the Run.
Derived values — the numeric backend actually selected, the shard count sharding settled
on, the config and memory hashes, the free-running telemetry — are equally part of "what
this Run was" and are shown beside them, but read-only. Presenting a derived value as
settable would be a lie about how the engine works.

*The resolved set is stored, not the overrides.* `runs.parameters` holds all 25 values.
Storing only the overrides would mean reading them against whatever the defaults are at
the time of reading, so a Run's record would quietly change meaning whenever the
configuration did.

*An unknown name is rejected rather than ignored*, and validation happens before anything
is created, so a typo cannot produce a Run at the default whose record claims the override
was applied. The config hash is computed over the Run's own metadata, so two Runs
differing only in a parameter are distinguishable by hash alone.

*Verified to reach the engine*, which is the assertion that matters — a parameter accepted,
stored and displayed but never applied is the worst outcome, because everything looks
right:

| override | status | codelets | answer |
|---|---|---|---|
| *(defaults)* | answer_found | 2,255 | mrrjjk |
| `update_cycle_length=5` | halted | 6,000 | — |
| `update_cycle_length=50` | answer_found | 666 | mrrjjk |
| `initial_temperature=40` | answer_found | 1,594 | mrrjjk |
| `max_coderack_size=300` | answer_found | 863 | mrrjjk |
| `self_watching_enabled_default=false` | answer_found | 442 | mrrjjk |
| `spreading_activation_threshold=0` | answer_found | 451 | mrrjjk |

`theme_decay_amount` is the instructive one: raising it 25 → 60 leaves the outcome
identical on three different problems, but peak theme activation moves 99.0 → 95.0. The
override reaches the Themespace; a four-point difference simply is not enough to flip a
structure decision. Worth recording, because "no visible effect" and "silently ignored"
look the same from outside and are not the same thing.

## Acceptance criteria

- Episodic Memory carries across Run boundaries; `init_mcat` unchanged.
- A mode-mixed Training Session matches an all-Fast one, cognitively.
- Persisted identifiers depend only on the Run (WP0.3).
- Fast Run completes with the database stopped, allocating only engine state (WP3.6).
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
2. ~~**Coderack sharding strategy** (WP4.3) — by family, by region, or lock-free single
   rack; and how urgency-weighted probabilistic selection is preserved across shards.
   The hardest open question in the phase.~~ **Answered by measurement:** per-worker racks
   with work stealing. Family sharding distorts selection by up to 0.354 TV distance and
   worsens as the engine cools; region sharding is not buildable, since a codelet chooses
   its region during execution. Selection is preserved because a codelet's shard is
   independent of its type and urgency, so each shard is an unbiased sample. See WP4.3.
3. **Read-set granularity** (B4) — the coarse/fine tradeoff between false conflicts and
   missed conflicts, tuned empirically against the serial reference.
4. ~~**Staleness tolerance** (WP0.5) — how much stale state cognition absorbs before the
   expected range moves.~~ **Answered:** nothing moves to 5 codelets; convergence
   slows by 15; the answer set moves by 50. Budget for WP4.4 is ≤5. See WP0.5.

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
