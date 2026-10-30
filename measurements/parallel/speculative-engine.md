# The speculative executor: exact within-run parallelism (WP3, 2026-10-29)

Code: `server/parallel/speculative/`. Tests: `tests/parallel/test_speculative_exact.py`,
`test_clock_rack.py` and `test_effects.py`. Benchmark: `scripts/bench_speculative.py`. The
effects audit is `speculative-effects-audit.md`, next to this file.

## What it guarantees
For any worker count, a run is **bit-identical** to the single-threaded stream-serial reference
(SSR) with the same seed. "Identical" covers:
- the step-by-step codelet type and id;
- every structure built or broken, in order;
- every Trace event;
- the answers, the status and the codelet count;
- a fingerprint of the final shared state.

The SSR differs from the faithful loop by having per-codelet counter-based random streams and an
exponential-race coderack. Both are equal *in law* to the faithful loop, which is checked
statistically by `scripts/compare_executors.py`.

## Evidence at hand-over
- **Free-threaded sweep** (`.venv-ft`, no GIL): 696 runs and 0 divergences. That is 29 demo
  problems × seeds 3–8 × workers 2, 4, 8 and 16, at 1,500 steps.
- **GIL sweep**: 261 runs, 0 divergences.
- **Slow pytest sweep**:
  - on `.venv-ft`, the workers 4 and 16 subset: 66 passed;
  - on `.venv`, the full `tests/parallel` with the slow sweep: 269 passed.
- **Mutation checks**: the clock-rack chi-square tests fail under a deliberately wrong law, and
  the hidden-write detector catches a planted write.

## Speed (shared, noisy machine: load 3–14)
The figures below are against the SSR on `.venv-ft`.

| workers | median speedup | median abort rate |
|---|---|---|
| 1 | 0.78 | 0 |
| 2 | 0.84 | 8% |
| 4 | 0.80 | 20% |
| 6 | 0.64 | 28% |
| 8 | 0.59 | 30% |
| 12 | 0.54 | 35% |
| 16 | 0.40 | 34% |

There were isolated 1.35–1.44× runs at 2–4 workers. The SSR itself is 1.1–1.6× slower than
the faithful loop, because of its SHA-256 counter streams.

Several ceilings stop the engine gaining at today's sizes:
- **The update cycle** takes about 53% of a run and is serial. Even free codelets cap a run
  near 1.5×.
- **Rule codelets are serial.** `rule-scout`, `rule-evaluator` and `rule-builder` run inline
  because `Rule.currently_works` writes `obj.image` onto shared objects. They are about 8% of
  codelets in the mix and up to 35% in rule-heavy runs.
- **Codelets are small and conflicts are frequent.** The mean codelet is about 25–33 µs.
  20–35% of speculations conflict at 4 or more workers, and each step carries about 20 µs of
  coordination overhead.

## Second pass: the machinery's own cost (WP10, 2026-10-30)
Quiet M5 Max, `.venv-ft`, `scripts/bench_speculative.py --workers 1,2,4,8 --steps 3000
--seeds 1,2,3 --repeats 3`, now with faithful, the SSR and each worker count interleaved per
round (`speculative-bench.json`, which also keeps the first version's summary):

| workers | first version | after the second pass | median abort rate |
|---|---|---|---|
| 1 | 0.78 | 1.01 | 0 |
| 2 | 0.82 | 0.92 | 3% (was 9%) |
| 4 | 0.79 | 0.91 | 5% (was 21%) |
| 8 | 0.56 | 0.85 | 5% (was 41%) |

Every run is exact. It is still not faster than the SSR. What changed:
- **One worker runs the SSR's own loop.** Nothing is installed and no threads start.
- **A prefix that never wrote commits on the coordinator.** The worker parks it and is free at
  once. When its step comes up, the coordinator checks the seqlock versions: the moment the
  serial run would have run the codelet, with the coordinator the only writer. A stale prefix
  is rolled back and run through the SSR's `_execute_codelet`.
- **Run-ahead is selective.** The effects table has a `profitable` flag, false for six short
  types (bond-evaluator, description-evaluator, top-down-group-scout:category,
  important-object-bridge-scout, top-down-description-scout, bottom-up-bond-scout). Running
  one of them ahead alone gave ×0.97–0.99 against running nothing ahead. Nothing runs ahead of
  or past a step that may write what prefixes read. That cut aborts to 5%.
- **One prediction per epoch.** `ClockCoderack` keeps `gen`, `floor_f`, `predict_entries` and
  `sync_row`. A best-first walk of the heap replaces `heapq.nsmallest`.
- **Idle workers park** during update cycles and after a few hundred microseconds idle.
  Spinning slowed the update cycle by 10–20%.
- **Workers bind a guarded id allocator** through the engine's own ContextVar, so the
  coordinator pays no guard.
- **The step-relative `codelet_count` lives on the workers' context.** It used to be on the
  run's own context. It was 3% of a run, and the whole of the fixed cost.

Each of these decides only who runs a step, and when. New tests vary that choice and check the
result is unchanged:
- one worker is the SSR;
- the types allowed ahead, and the lookahead depth, never change a result;
- read-only commits, including forced aborts;
- abandoned prefixes leave no trace;
- a speculating thread never reads the real context;
- the cached prediction is exact.

Verification after the pass:
- `tests/parallel` (232) and its slow sweep (64) passed on both interpreters.
- The swarm sweep found 580 seed pairs with 0 per-seed differences, run from the worktree and
  again from `main`.

**Where the time goes now.** `eqe->qeq; abbbc`, seed 1, 3,000 steps, ms:

| | codelets | update cycle | refill | other | wall |
|---|---|---|---|---|---|
| SSR | 61.7 | 101.7 | – | 16.1 | 179.5 |
| 2 workers | 59.3 | 105.7 | 8.6 | 15.7 | 189.3 |
| 4 workers | 58.0 | 106.8 | 9.3 | 15.7 | 189.8 |
| 2 workers, nothing run ahead | 63.1 | 104.5 | 7.4 | 15.5 | 190.6 |

- **The cross-thread cost.** A prefix on a worker costs about 1.7× the CPU of the same codelet
  inline. Free-threaded reference counts are writes, so the coordinator has to fetch back
  every object a worker touched.
- **Problem size changes nothing.** Strings of 8–12 letters show the same pattern.
- **Tried and dropped:**
  - Starting prefixes in the update cycle's tail. It is safe: the tail writes only the rack and
    the ids. But it slowed the coordinator by about 80 µs a cycle.
  - Swapping guard classes off for the update cycle. Assigning `__class__` is a stop-the-world
    pause of about 300 µs on the free-threaded interpreter.
  - Timed parking.
  - Lookahead depths from 1 to 12, which made no difference above the noise.

A within-run gain on this interpreter would need a different way of sharing state, such as a
per-thread replica of the Workspace. The swarm remains the way to use every core.

## Hazards found (and handled plugin-side)
- **Slipnet-buffer jolt.** `cm.activate_descriptions()` inside `bridge-evaluator` jolts the
  Slipnet buffer. It is deferred and applied at commit.
- **`Rule.currently_works` writes `obj.image` and `string.image` caches** onto shared Workspace
  objects. The rule types are therefore marked non-speculating.
- **`rule-builder` mutates the incumbent rule** before `build_structure` runs. It is
  non-speculating.
- **`Bridge.get_all_concept_mappings` rebinds a shared list on every read.** A thread-gated
  class patch computes the same answer without storing it.
- **Id allocation hidden in reads**: the singleton `Group` in
  `top-down-group-scout:category`, `Bond.flipped`, and `propose_bridge`. Guarding `ids.next`
  makes the codelet go live at its first allocation.
- **Eviction drew from the run-level RNG.** The rack now draws from the thread-bound stream.
- **Worker threads started with the wrong allocator or structure clock.** Both are bound on
  every attempt.
- **Rollback must never restore shared objects.** Only proposed or evaluated structures are
  snapshotted.
- **`SpeculationAbort` derives from `BaseException`** so it passes through the engine's own
  `except Exception`.

## Engine seams that would let more codelets speculate (not made; the engine is untouched)
1. **`Rule.currently_works`** should use call-private image maps instead of writing
   `obj.image`. See `rules.py:2853-2872` and `images.py:1043,1089,1105`.
2. **`Bridge.get_all_concept_mappings`** (`bridges.py:111`) should store only when the order
   changed.
3. **`top-down-group-scout:category`** should compute `single_letter_group_probability`
   without constructing a `Group`.
4. **`WorkspaceStructure._themespace`** (`workspace_structures.py:41`) is process-global. It
   should belong to the run.
5. **`Coderack.post`** (`coderack.py:349`) should take the eviction stream explicitly.
6. **`state_graph` restore** (`state_graph.py:574-578`) writes bins directly. After a restore,
   `ClockCoderack` must re-adopt the rack.
