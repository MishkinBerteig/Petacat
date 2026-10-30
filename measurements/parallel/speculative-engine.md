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
