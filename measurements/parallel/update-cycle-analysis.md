# WP5 report: parallel update cycle

The WP5 agent could not write report files, so the lead saved this copy of its hand-back.

## What exists
- `UpdateCycle(runner, policy="faithful"|"stream", threads=1)` in `server/parallel/update_cycle.py`.
- `.run(stream=None)` performs one update cycle. `.close()` releases the team, and the class also
  works as a context manager.
- Options: `force_threads`, `min_items` (default 8), `profile`, `parallel_posting` (default
  False) and `spin_us`.
- On a GIL build, threads are clamped to 1 unless `force_threads=True`.

## Analysis: engine cycle on `off`, std CPython, 5 problems × 5 seeds

The cycle averages 581 µs, which is 51% of wall time. On numpy it is 743 µs, or 57%.

| step | µs | dependency | RNG | verdict |
|---|---|---|---|---|
| bond and group strengths | about 145 together with the bridge row | Jacobi | density walk, a data-dependent count per item | parallel in stream |
| bridge and rule strengths | included in the row above | Gauss-Seidel: each bridge sums the fresh strengths of others | none | serial |
| raw importance | 9 | per object | none | parallel, fused |
| relative importance | 55 | per-string ratio, exact rationals | none | parallel across strings |
| unhappiness, salience, description strengths | about 195 together with the two rows above | per object | none | parallel |
| workspace averages | 20 | reductions | none | serial |
| rules-possible, snag/clamp, temperature, EEG | under 12 | scalar | at most one coin | serial |
| workspace → themespace | 24 | accumulates into shared themes | none | serial |
| themespace spreading | 17 on off, 64 on numpy | Gauss-Seidel | none | serial |
| themespace → Slipnet | 0.7 | theme order | 2 coins per active theme | serial |
| Slipnet update and events | 28.5 + 14 | jumps in index order | 1 coin per partially active node | serial |
| posting (bottom-up 39, top-down 31, thematic 3) | 73 | read-only decisions | a few per rule | decisions fan out; codelets are built serially because ids follow construction order |
| `post_deferred` | 42 | each eviction re-weighs | sequential | serial |

About 60% of the cycle is eligible for parallelism, or 75% counting posting. At 8 threads that
would give roughly 2.0–2.4× on the cycle and about 1.3× on a run, but only if the items scaled.

## Stream keys
Each key is the blake2b hash of `(update index, phase, identity)`.
- Structure strengths use `strength/<Class>:<run id>`.
- Posting uses `post/bu|td|th/<type>`, adding `(<slipnode>)` for top-down.
- Phases with sequential draws draw from one phase stream each, in the engine's own order.

## Equal in law
Every decision is a coin or a pick made from fresh independent uniforms, and its probabilities
are set by the state at the start of the phase. Four points need care:
- No key may be reused within an update.
- The walk length depends on the data, which is harmless once each item has its own key.
- `SplittableRNG.weighted_pick` uses `>=` where `RNG.weighted_pick` uses `>`. The two differ
  only on ties, with probability 2^-53.
- Lazy caches are warmed serially before any fan-out.

## Identity
- **Faithful, single thread, against the engine:** `off` 200/200 and numpy 725/725 identical.
- **Faithful with a 4-thread team under `.venv-ft`:** `off` 200/200 identical.
- **Tests:** 30 in `tests/parallel/test_update_cycle.py`, all passing on `.venv`, with three
  passing runs on `.venv-ft`.

## Speedup: none today
Best µs per cycle on `off` under `.venv-ft` (noisy, with load at 5–12):

| setting | µs per cycle |
|---|---|
| engine | 654 |
| faithful | 670 |
| stream, 1 thread | 676 |
| stream, 2 / 3 / 4 threads | 781 / 837 / 850 |

On numpy:

| setting | µs per cycle |
|---|---|
| engine | 1005 |
| faithful | 1113 |
| stream, 1 thread | 1186 |
| stream, 2 threads | 1544 |

## Why there is no speedup
- **Scaling on a fixed workspace:** strengths take 150 µs on one thread and 153 µs on two.
  Object values take 139 µs and 132 µs.
- **Independent workspaces, K=4:** parallel efficiency is 72% for strengths, 56% for object
  values, 43% for importance and 13% for relative importance. This points at the free-threading
  hazards that WP4 owns, chiefly `Fraction` and the function-level import at
  `workspace_objects.py:488`.
- **Fan-out cost:** 1.2 µs at two threads and 6–10 µs at three to four. Under load it was
  36–64 µs.
- **Workspace size:** about 14 objects and 9–12 structures. Every phase is 25–140 µs made of
  10 µs items.

## Interface for WP3
`UpdateCycle(runner, "stream", threads=N)`, then `.run(update_stream)` with a `SplittableRNG`.
Call it from the coordinator thread with nothing else in flight. It binds `ctx.ids` itself.
