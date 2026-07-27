# Phase 0 Plan — Execution Substrate

**Goal.** Database modes and parallelism. **No semantic changes to how Petacat
works.** This phase introduces no new cognition; it establishes the execution
structure every later phase runs inside.

**Source.** Partitioned from `FUTURE_DIRECTION_DETAILS.md` §12, §12a, §12b, §13,
§13a–§13d, and the determinism bullet of §6.

**Depends on.** Nothing. This is the floor.

**Permanence.** Both workstreams are permanent architecture, not scaffolding.
Audit mode in particular remains serial *forever*, and the serial reference mode it
provides is what every later phase validates against.

---

## What "no semantic changes" means here — read this first

**Conceptual level, not technical level.** Many technical details will change, some of
them substantially: the RNG becomes splittable, codelets are reconceptualised as
read-phase-plus-delta, state mutation moves behind a commit discipline. What must
*not* change is the system's behaviour at the level of **solving letter-string
analogy problems**.

This is a hypothesis, and it is the one this phase tests: that Petacat's cognition is
robust to how its codelets are scheduled — that a wave-scheduled or free-running
coderack solves `abc→abd; xyz→?` the way the serial one does, because the parallel
terraced scan was always meant to be parallel and the serial coderack was a
concession to 1980s hardware, not a theoretical commitment.

**The bar is distributional equivalence, not bit-identity.** Above the first rung,
bit-identity is impossible by construction — concurrent codelets read stale state and
land in different orders. So the standard is empirical: across the demo suite, serial
and parallel Petacat must produce the same answers with comparable quality,
temperature, and effort *distributions*. Where they diverge, we must be able to say
why. Audit mode (Workstream A) supplies the serial reference that this is measured
against, which is why the two workstreams belong in one phase.

**All parallelism lives here, including the stale-state problem.** The full ladder in
B4 — up to free-running — is Phase 0 work, not something later phases advance. Later
phases inherit a parallel engine and do not touch scheduling.

---

## Workstream A — Persistence modes

### A1. Where the database actually is — assessment of the current code

**The engine is already database-free.** All 19 modules of `server/engine/`
(~14.6k LOC) contain **zero** SQLAlchemy imports, zero session handling, and zero
awaited I/O. `EngineRunner(meta)` plus `MetadataProvider.from_seed_data(seed_dir)`
runs a complete problem with no Postgres, no Docker, and no FastAPI — this is what
`smoke_test.py` already does and what ~100 unit and module tests already rely on.
The measurements below were taken on a checkout where **SQLAlchemy is not installed
at all**, and the engine ran fine.

Phase 0 is therefore **not a rewrite**. It makes an existing property *explicit,
enforced, and switchable* rather than incidental.

The database boundary is confined to eight files:

| Module | Role at the boundary |
|--------|----------------------|
| `server/db.py` | Async engine + session factory |
| `server/main.py` | Lifespan: `create_all`, JSON→DB seeding, help-topic sync |
| `server/services/run_service.py` | **The only writer of run state** |
| `server/services/snapshot_service.py` | State serializers + `save_cycle_snapshot` |
| `server/services/metadata_service.py` | DB → `MetadataProvider` |
| `server/models/{run,metadata}.py` | ORM definitions |
| `server/api/{runs,admin,memory,docs}.py` | 74 endpoints taking `Depends(get_session)` |

`server/api/controls.py` and `server/api/ws.py` take **no session at all** —
breakpoints, clamping, and threshold control are already pure in-memory operations.

**Exactly three things write during a run**, all in `run_service.py`:

1. `_persist_new_trace_events` — checked **after every codelet**;
2. `_persist_answer` — on an answer;
3. `save_cycle_snapshot` — **every 15 codelets** (`update_cycle_length`), plus on
   create and reset; followed by an `update(Run)` and a `commit()` per API call.

**Measured cost** (engine-only, no DB attached):

| Problem (seed) | Codelets | Engine wall | Rate | Trace rows | Snapshots | JSONB written |
|---|---|---|---|---|---|---|
| `abc→abd; xyz?` (7) | 551 | 28 ms | 19,300/s | 52 | 36 | ~2.7 MB |
| `abc→abd; xyz?` (42) | 1,356 | 74 ms | 18,300/s | 93 | 90 | ~12.2 MB |
| `abc→abd; mrrjjj?` (42) | 2,484 | 225 ms | 11,000/s | 161 | 165 | ~45.3 MB |

Metadata loads from JSON in **4 ms**. Serialising **one** snapshot costs **2.46 ms**
of CPU, so the 165 snapshots of the `mrrjjj` run cost **~405 ms — roughly 180% of
the engine's own 225 ms of thinking — before a single byte reaches Postgres.**
Persistence is not a tax on this system; it is the majority of it.
(`run_to_completion` adds a further `await asyncio.sleep(0)` per codelet, ~16 µs,
another ~40 ms on that run.)

**Three defects to fix rather than inherit:**

- **Snapshots are write-only.** `restore_slipnet_state`, `restore_trace_state`,
  `restore_runner_state`, and `restore_rng_state` are defined in
  `snapshot_service.py` and **called from nowhere**; there is no
  `restore_coderack_state` or `restore_workspace_state` *at all*. The snapshot
  payload is **88% coderack**, 5% themespace, 3% slipnet, and only 2% workspace. The
  single largest cost in the system is writing a blob no code path can read back.
  `prune_old_snapshots(keep_n=10)` is likewise never called, so rows accumulate
  without bound.
- **Episodic memory is a process-global singleton — a latent coupling, not a bug
  today.** `run_service.py:33` holds one `EpisodicMemory()` shared by every run.
  Cross-run sharing is *correct by design*: reminding is a core MetaCat feature and
  `engine/memory.py` says so explicitly. The engine already does the right thing —
  `init_mcat(memory=…)` takes it as an injected dependency; only the service layer
  hardcodes one instance. And today it cannot perturb cognition: `find_remindings`
  is called once, inside `report_answer`, *after* the answer exists, and its only
  effect is `emit_reminding` into the commentary log — no RNG, no structures, no
  trajectory change. What is true today is narrower: a run's **commentary** depends
  on which runs preceded it in the process, and `AnswerDescription._next_id` /
  `SnagDescription._next_id` are class-level counters, so even IDs carry process
  history. Both are output-level, not cognition-level. The concern is prospective —
  Phase 3 puts the cross-run token vocabulary here, Phase 4 consolidates into it,
  and Phase 2 writes love-born concepts — at which point memory *does* feed
  perception. (`rehydrate_memory` also appends without clearing, so it is not
  idempotent; it is called once at startup today.)
- **Pure serializers are welded to the ORM.** `snapshot_service.py` mixes
  side-effect-free serialization with SQLAlchemy imports, so *reading* engine state
  requires importing the database layer.

### A2. The three modes

Persistence mode is a property **of a run**, chosen at creation — not a global
setting — because later phases will legitimately want a Fast corpus-training
population and a Normal live dialogue in the same process.

| | **Fast Run** | **Normal** | **Audit** |
|---|---|---|---|
| **Purpose** | Rapid iterative testing; runs are discarded | Ordinary operation; human-inspectable, reproducible | Production audit trail; total verification |
| **Unit of persistence** | **none, ever** | **the turn** | **the tick** |
| **When it writes** | never | at turn end, once the workspace has finished responding | continuously, *as it runs* |
| **Writes** | nothing | turn start state (incl. RNG state), turn end state, the emitted response, valence, answers/snags | every codelet, every structure transition, every activation update, every valence event |
| **DB attached** | **no** | yes | yes |
| **Execution** | full parallelism | full parallelism | **serial — no parallelism, no batching** |
| **Expected cost** | full engine rate (11k–19k codelets/s today) | one transaction per turn | extremely slow, by design |

**Fast Run stores nothing in the database at any point — including at the end of the
run.** No final flush, no summary row, no answer record. Whatever the caller wants
it must read from memory while the run is live, or as a returned value. The mode is
defined by the *absence of a database connection*, not by write-frequency tuning. On
today's numbers simply not snapshotting is a ~2.8× speedup before any parallelism.

**Normal records start and end state per turn — nothing in between.** Reproducibility
is **by re-execution, not by replay**: recording the RNG state at turn start
alongside the config-hash means the turn can be re-run to the same end state without
a journal of what happened between. Mid-run detail is deliberately not kept.

**Audit writes everything, every tick, as it runs — serially, unbatched, and very
slowly.** No batching may defer a write past the tick that caused it; no parallelism
may make ordering ambiguous. Slowness is an accepted consequence, not a defect.

**Audit mode and the serial reference mode are the same thing** — a serial,
fully-recorded execution is exactly the artefact needed for fidelity
cross-validation against Marshall's semantics. Building one satisfies both.

**The limitation to state plainly:** because Audit removes concurrency, it cannot
reproduce concurrency-dependent behaviour. A defect that only manifests under
free-running will not appear in it. Audit is *not* the debugging tool for
parallelism, and the **commit journal (Workstream B) remains a separate mechanism**.
Audit answers "what did the system do, tick by tick"; the commit journal answers "in
what order did concurrent codelets land." Both are needed.

### A3. Review UX — a Phase 0 deliverable

Normal and Audit exist to be *looked at*, and today nothing looks at them. Phase 0
must ship the review surfaces alongside the writers, or it repeats the write-only
mistake it was convened to fix. Two surfaces, because the modes answer different
questions:

- **Normal review** — a run/turn browser: list runs, open a run, step through its
  turns, see start state → emitted response → end state, with the valence signal and
  any answers or snags. Coarse-grained and fast to scan.
- **Audit review** — a tick-level inspector: scrub a single run's timeline and at any
  tick see the codelet that ran, the structures that changed, and the activation and
  temperature state at that instant. Deep, narrow, slow to produce.

Both build on the existing client (`WorkspaceView`, `SlipnetView`, `TraceView`,
`ThemespaceView`) rendering *recorded* state rather than live state.

### A4. The mechanism: one code path, three sinks

A `RunSink` port with methods the engine calls at defined moments
(`on_run_created`, `on_codelet`, `on_trace_event`, `on_structure_change`,
`on_turn_end`, `on_answer`, `on_valence`), and three implementations: null,
batching, audit.

Four rules make this hold:

- **The engine never learns its mode.** No `if mode == "fast"` anywhere in
  `server/engine/`. The moment mode becomes a conditional inside the engine, the
  modes drift and Fast stops being a faithful preview of Normal.
- **Serialisation happens *inside* the sink, lazily.** Sink methods receive the live
  context, not a pre-built payload. If the null sink received an already-serialised
  snapshot, Fast would still pay the 2.46 ms and the point would be lost.
- **Mode must not change results.** Same seed → same codelet count, temperature, and
  answer in all three modes.
- **The DB-free property becomes an enforced invariant.** A test that fails if
  anything under `server/engine/**` imports SQLAlchemy.

### A5. Consequences

- **Mid-run snapshots are retired, not repaired.** No mode needs them: Fast writes
  nothing, Normal needs only turn boundaries, Audit records every tick anyway.
- **Reproducibility is by re-execution** from (RNG state at turn start, config-hash,
  memory-hash).
- **Metadata gets a config-hash.** Re-execution is only valid against identical
  configuration.
- **Episodic memory becomes a named, versioned input** — explicit at run creation
  with a recorded `memory-hash`. Sharing stays available; what changes is that
  *which* memory a run saw becomes part of the run's identity. Fast Run defaults to
  an ephemeral in-process memory.
- **Serializers split from the ORM.**
- **The API keeps working in every mode.** `controls.py` and `ws.py` are already
  session-free, so live inspection of a Fast run costs nothing — Fast means *not
  written down*, not *not observable*.

---

## Workstream B — Parallelism

### B1. The constraint

Petacat targets **Apple M-series silicon only.** No portability budget is spent on
x86, CUDA, or Linux GPUs. The implementation must achieve **true parallelism**:
codelets executing simultaneously across multiple **CPU cores**, and the system's
numeric work executing on the **GPU cores**.

**Why this is principled and not arbitrary.** Apple silicon's **unified memory
architecture (UMA)** lets CPU and GPU address the same physical memory with no copy.
This design needs a *fine-grained* handoff — the numeric substrate is touched every
update cycle (~15 codelets), on state that symbolic codelets mutate in between. On a
discrete GPU that round-trip would be dominated by bus transfer. On M-series the
codelets and the kernels read the same buffers.

**Docker is the immediate casualty.** The engine runs today in a `python:3.12-slim`
Linux container. Docker Desktop's Linux VM does not expose Metal to containers, and
CPython 3.12 holds the GIL — the current deployment target forecloses *both* halves
of this constraint. **The engine must run natively on macOS.** Postgres, the client,
and the API surface may stay containerised; the hot loop moves to the host.

### B2. What can and cannot go on the GPU

Codelets **cannot** run on GPU cores, and no engineering changes this. They are
branchy, pointer-chasing, allocating symbolic agents that `exec()` interpreted
source; GPU cores are SIMT. The honest reading of "codelets use the GPU" is a
**split by kind of work**:

| Layer | Runs on | Character |
|-------|---------|-----------|
| **Symbolic agents** — scouts, evaluators, builders, breakers, jootsers | **CPU** (P- and E-cores), truly concurrent | Irregular, branchy, mutating a shared object graph |
| **Numeric substrate** — the system's "physics" | **GPU** (Metal / MLX) | Regular, dense or sparse-but-structured, homogeneous |

Genuinely GPU-shaped work:

- **Slipnet activation spreading** — sparse mat-vec. Negligible today (59 nodes, 226
  links) but Phases 1–4 are explicitly designed to grow it.
- **Candidate scoring over O(n²) object pairs** — the bond/bridge proposal space. The
  single largest win, and exactly the cost that blocks larger windows in Phase 3.
- **Salience / importance / unhappiness** over all objects — elementwise.
- **Themespace intra- and inter-cluster dynamics** — small dense matrices.
- **Temperature** — a reduction over structure strengths.
- **Graph traversals** over the Slipnet — BFS/SSSP-shaped.

**The larger near-term GPU win is population parallelism.** A single run's Slipnet is
far too small to saturate a GPU. But Phase 4 corpus training and Phase 6 evolution
need **many runs**; batching K independent runs turns a tiny mat-vec into a fat
*batched* matmul. Expect population batching to pay before single-run acceleration.

**Contention with the other.** Any local LLM occupies the same GPU. Petacat's kernels
and that inference compete for one piece of silicon, worst during live dialogue.

**[open]** Framework: **MLX** for everything expressible as array ops, with
hand-written **Metal** kernels for irregular traversals MLX cannot express well.

### B3. Where the current code stands

- `server/engine/runner.py` — `step_mcat()` runs **exactly one codelet**. No seam for
  concurrency; the parallelism boundary must be introduced.
- `server/engine/rng.py` — a **single shared `random.Random`** with a mutating call
  counter, documented as "the single source of all non-determinism in the engine."
  Under threads this is simultaneously a data race and a reproducibility break. It
  must become **splittable / counter-based per-codelet streams**, seeded
  deterministically from `(run_seed, wave_index, slot_index)`.
- `server/engine/codelet_dsl/interpreter.py` — each codelet `exec()`s into a fresh
  namespace, so codelet *code* is already isolated; all contention lives in the
  shared-state mutations inside `codelet_dsl/builtins.py`. **That file is the
  concurrency boundary** — one place, not scattered.

### B4. The ladder — the goal is free-running

**The goal is to get as close to free-running threads as possible** — codelets
executing continuously and independently, no global barrier, the coderack sharded
across cores. Reaching it will require **reconceptualising how codelets work**, not
merely wrapping the existing ones in locks, and the long-term answer is expected to
be a **mix of techniques** applied to different parts of the system.

**The whole ladder is Phase 0 work.** It is written as rungs because that is the
sensible order to build and validate in, not because the later rungs belong to later
phases. Each rung is validated against the serial reference before the next is
attempted, so a regression is attributable to one change.

- **(i) Serial semantics, parallel substrate.** Codelets still run one at a time;
  only the numeric work goes wide. Bit-identical to today, captures the O(n²) win.
- **(ii) Bulk-synchronous waves.** W codelets run concurrently, then a barrier
  resolves conflicts and commits in **deterministic order** (by slot index, never
  completion order). The update cycle is already a barrier every 15 codelets, so
  W ≈ `update_cycle_length` is natural. **The first rung where stale state appears** —
  and therefore the first real test of the phase's hypothesis.
- **(iii) Region-partitioned execution.** Codelets claim disjoint regions and run
  barrier-free when regions do not overlap. Copycat codelets are already
  extraordinarily *local*, so disjointness is the common case.
- **(iv) Optimistic / transactional execution.** A codelet runs speculatively with a
  read-set and write-set, committing only if nothing it read changed.
- **(v) Free-running.** Continuous execution, sharded coderack with work-stealing,
  no global barrier. **The goal, and this phase's destination.**

### B5. Resolving stale state

Stale state is *the* problem of this phase, and it is resolved here rather than
deferred. Three mechanisms, already latent in the architecture:

- **Conflict → fizzle** (below) turns a lost race into an outcome the model already
  understands, so most staleness needs no resolution at all — it needs only to be
  *detected*.
- **The proposal lifecycle** (`%proposed%` → `%evaluated%` → `%built%`) is repurposed
  as the commit protocol: a codelet's read-set is validated at commit, and a structure
  whose premises moved is re-evaluated or fizzles rather than being built on stale
  evidence.
- **Locality** bounds the blast radius: a bond scout touches two adjacent objects, so
  a stale read is usually stale about something no other codelet was touching.

The open engineering question is not *whether* staleness can be handled but **how
coarse the read-set granularity can be** before either false conflicts (too fine-
grained, everything fizzles) or missed conflicts (too coarse, structures build on
moved premises) degrade the system. That is an empirical tuning problem, measured
against the serial reference.

**Why Copycat is unusually well-suited to this:**

- **Conflict → fizzle is semantically free.** `fizzle` is already a native, meaningful
  codelet outcome. A codelet that *loses a race* can fizzle for exactly the same
  reason, and nothing in the model needs a new concept. Under contention the fizzle
  rate rises — which reads, correctly, as *the workspace being busy*.
- **The proposal lifecycle is already a staged commit.** `%proposed%` → `%evaluated%`
  → `%built%` is a two-phase commit wearing cognitive clothing. Reconceptualising
  codelets as *pure read-phase plus a proposed delta* makes explicit a structure that
  is already there.

**Reproducibility survives — by replay, not by schedule.** Reproducibility does not
require the *schedule* to be predictable, only **recordable**: journal the actual
commit order and a run replays exactly. The honest cost is not to validity but to
**sample efficiency** — a free-running run is one draw from a distribution, so
evolutionary fitness needs more runs per configuration. Population parallelism is
what pays for that.

---

## Exit criteria

- Identical cognition across all three persistence modes from the same seed.
- Fast Run demonstrably opening **no database connection at all**.
- Normal turns re-executing to their recorded end state.
- Audit reconstructing a run tick by tick in its inspector.
- Normal and Audit review UX shipped and usable.
- The engine-imports-no-SQLAlchemy invariant test passing.
- Native macOS execution.
- Wall-clock improvement on the largest problems from the GPU numeric substrate.
- **The ladder climbed as far as it goes**, with free-running as the target and each
  rung validated against the serial reference before the next is attempted.
- **The phase's central claim, measured:** across the demo suite, parallel Petacat
  produces the same answers as serial Petacat with comparable quality, temperature,
  and effort distributions. Divergences are explained, not tolerated.

**A negative result here is a real finding.** If letter-string cognition turns out to
be genuinely sensitive to scheduling order — if wave-scheduled Petacat solves
different problems, or solves them worse — that says something substantive about
whether the parallel terraced scan was ever really parallel, and it would send the
ladder back down to a lower rung by evidence rather than by caution.

## Open questions

1. **Sink event vocabulary** — the exact `RunSink` call sites; what a "turn" means
   for Normal before the turn recurrence exists (interim: the run); how much of the
   live client can be reused for recorded-state review.
2. **Runtime and framework choices** — free-threaded CPython vs. a native core; MLX
   vs. hand-written Metal kernels; per-codelet RNG stream derivation; commit-journal
   format.
3. **Wave conflict resolution** — what counts as a conflict, and the commit ordering
   rule in detail.
4. **Read-set granularity** (B5) — the coarse/fine tradeoff between false conflicts
   and missed conflicts, tuned empirically against the serial reference.
5. **How far up the ladder the architecture actually goes** — free-running is the
   target, but which rung survives the distributional-equivalence bar is an empirical
   question this phase answers rather than assumes.

## Glossary

| Term | Meaning |
|------|---------|
| **Fast Run / Normal / Audit** | The three persistence modes: no database at all / turn start+end state / every tick as it runs, serial |
| **`RunSink`** | The port the engine emits events to; mode is which implementation is attached, and the engine never knows which |
| **Config-hash** | Hash of the `MetadataProvider` a run executed under |
| **Memory-hash** | Identifier of the episodic memory state a run executed against |
| **Symbolic layer** | The codelets — irregular, branchy, concurrent across CPU cores |
| **Numeric substrate** | Activation, salience, pair-scoring, temperature — on GPU cores |
| **Wave (BSP)** | A batch of codelets run concurrently, then conflict-resolved and committed in deterministic order |
| **Free-running** | The parallelism goal: continuous barrier-free execution, sharded coderack |
| **Conflict → fizzle** | A codelet that loses a race fizzles — reusing an outcome the architecture already has |
| **Replay-determinism** | Reproducibility from a journaled commit order rather than a predictable schedule |
| **Serial reference mode** | Permanently retained one-codelet-at-a-time execution — delivered by Audit mode |
