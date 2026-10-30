# WP6 findings: GPU, Neural Engine and unified memory (2026-10-29, M5 Max)

Host shared with other agents (load average 3-12 during the runs): trust ratios, not absolutes.
Raw data and scripts are in this folder; WP8 should re-measure on a quiet machine.

## Verdict
At today's 59-node / 202-link Slipnet nothing on the GPU or ANE pays. The right backend for the swarm and
the speculative engine is `off` (the engine's own loops). The engine default `auto` resolves to `mlx` at
every size and is 4.9x slower than `off`, so executors must pass the backend explicitly.

## 1. Single run (`single_run.py`, `kernel_share.py`; abc->abd; mrrjjj, 10 seeds, 9,397 codelets)
| backend | codelets/s | ms/run | vs off |
|---|---|---|---|
| off | 13,328 | 70.5 | 1.00 |
| python | 13,206 | 71.2 | 0.99 |
| numpy | 11,621 | 80.9 | 0.87 |
| mlx-cpu | 6,109 | 153.8 | 0.46 |
| mlx (GPU) | 2,712 | 346.5 | 0.20 |

Numeric share of a numpy run (wall 0.83 s), time inside Backend/session methods only:
combine_object_values 4.4%, structure_strengths 2.8%, spread_themes 2.4%, slipnet.update 0.8% (+jump
candidates 0.4%, load/store 0.5%), average_unhappiness 0.2%, gather/scatter adapters 0.8%. Total
GPU-addressable work is about 11%; the whole Slipnet update is about 2.2%. Including the call sites'
Python traversals (inclusive, overlapping) numeric-labelled code is 30-37% of wall, but those traversals
walk the Python object graph and cannot move to a GPU. Upper bound for any GPU gain on one run: ~1.12x
over numpy, i.e. about parity with `off`. Cold start: mlx first 300-step run 0.35 s vs 0.06 s numpy.

## 2. Swarm (`swarm_scale.py`, forkserver, 6 s window, total runs/s)
| workers | 1 | 2 | 4 | 6 | 8 | 12 | 16 | 17 |
|---|---|---|---|---|---|---|---|---|
| off | 11.9 | 23.6 | 37.0 | 56.1 | 64.9 | 75.6 | 86.1 | 87.0 |
| numpy | 10.5 | 20.3 | 37.8 | 50.4 | 60.5 | 62.9 | 77.9 | 84.3 |
| mlx | 2.3 | 5.9 | 7.9 | 8.3 | 8.9 | 4.4 | FAIL | FAIL |

mlx peaks at 8.9 runs/s and falls beyond 8 workers. At 16 and 17 workers the pool died:
`RuntimeError: [metal::Device] Unable to load kernel ... Unable to reach MTLCompilerService`, which the
engine's `_gpu_usable()` swallows and turns into `BackendUnavailable`. `metal_probe_n.py` (N processes
doing one GPU op at once) failed for 1 of 4, 1 of 8, 1 of 12, 5 of 16, 6 of 17, 13 of 24, 21 of 32. Part
of this is other agents compiling kernels on the same host, but the mechanism (one system compiler
service) is real and means a swarm of Metal workers is unreliable at start-up.
off scales 7.3x at 17 workers (12.8k to 109k codelets/s); its efficiency loss is memory/thermal/P-vs-E
cores, not the backend.

## 3. Equivalence (`corpus_*.json`, serial_corpus.py, 29 problems x 10 seeds = 290 runs)
off vs python: 0 differences; off vs numpy: 0 differences (state, codelet count, answers, RNG call count,
Trace sha256). mlx and mlx-cpu on a 30-run sample (6 problems x 5 seeds): 0 differences too, but float32
cannot be promised bit-identical, so mlx is only ever "statistically equivalent".

## 4. Batched GPU numerics (`scripts/bench_gpu_batch.py`, `gpu_batch_bench.log`)
Prototype of K runs' Slipnet update as one `[K, 59]` MLX dispatch, ms per update cycle across K runs:
| K | numpy x K | numpy batched (f64 CPU) | mlx resident | mlx with upload/readback |
|---|---|---|---|---|
| 1 | 0.006 | 0.009 | 0.159 | 0.153 |
| 8 | 0.046 | 0.014 | 0.183 | 0.202 |
| 32 | 0.188 | 0.026 | 0.179 | 0.186 |
| 128 | 0.748 | 0.075 | 0.196 | 0.208 |
| 512 | 3.02 | 0.266 | 0.208 | 0.193 |
| 1024 | 6.16 | 0.516 | 0.220 | 0.263 |
Crossover against K separate numpy updates: K ~ 30. Against a float64 batched CPU update: K ~ 256-512.
Results matched the float64 reference exactly (0 mismatched cells at every K) on integer-valued random
states, because the arithmetic is integer-valued and float32 holds it exactly; real states with fractional
theme contributions would not carry that guarantee. End-to-end estimate for a worker hosting K=64
lockstepped runs: the slipnet update is ~22 us of run cycles ~1.3 ms, so saving ~19 us per run-cycle is
~1.5%; batching every numeric pass too is ~5% at best, before the lockstep straggler cost (a batch runs
as long as its longest run) and the per-cycle gather/scatter of K object graphs. That is parity with `off`.
Not built: no `gpu_batch.py`. `placement.gpu_worthwhile` will honour `batch>1` if the module appears.
The seam `on_cycle` in `population.run_population_batched` stays as is. A seam in engine would be
needed to batch the rest (object values and strengths need the traversals to expose arrays).

## 5. Neural Engine
Not measurable here without Core ML, which is not installed and not to be installed in the venvs. By
analysis: the ANE runs Core ML graphs in float16 with fixed shapes, offloaded by the OS per call (the
dispatch cost is higher than Metal's 0.2 ms, and tens of microseconds is the whole CPU cost of one
Slipnet update); MLX never targets it. Petacat's numeric passes are integer-valued gather/scatter and
`round` with round-half-to-even semantics that the original relies on; float16 has 11 mantissa bits and
cannot represent the activation arithmetic (it would change which side of x.5 a contribution rounds to).
Nothing in the current engine is a dense matmul/conv a neural model would be. The ANE becomes relevant
only when a neural model exists (future plan); then a Core ML export is the only route.

## 6. Unified memory (`rss_cow.py`, `startup.py`)
Per-worker RSS after 30 runs: preload 27.0 MB, forkserver cold 28.5 MB, spawn 34.0 MB; `footprint`
23, 25, 26 MB. Eight workers sum to 216, 228, 271 MB. Pool start plus first run on 16 workers was 0.18 to
0.20 s whichever way. Memory is not a constraint (17 workers is under 0.5 GB of 128). Python object
metadata does not stay shared copy-on-write for long (refcount writes dirty pages), so the cheap and
correct recommendation is: preload via `set_forkserver_preload` (saves ~6 MB and some start-up), build
the MetadataProvider once per worker, and share nothing mutable. If metadata ever becomes big arrays,
`multiprocessing.shared_memory` or an mmap'd NumPy file would be shared for real; MLX arrays live in the
unified memory pool but cannot be shared across processes.

## 7. MLX threading and fork (`thread_safety2.py`, `fork_safety.py`, `thread_fork_results.log`)
- A stream created in one thread cannot be used in another: `There is no Stream(gpu, 0) in current thread`.
- A lazy array built in thread A and evaluated in thread B fails the same way (`Stream(gpu, 64)`).
- Several threads, each creating its own stream and its own arrays: correct, on GIL and free-threaded
  builds. Tiny-op throughput scaled 6k to 49k evals/s from 1 to 16 threads.
- One `mx.compile`d function called from 8 free-threaded threads: intermittent
  `RuntimeError('mutex lock failed: Invalid argument')` (.venv-ft, mlx 0.32.4). Compile per thread.
- mlx versions differ between the venvs (0.32.1 vs 0.32.4).
- `os.fork` after Metal init: child SIGSEGV (-11). `os.fork` after import only: child failed to load a
  kernel (MTLCompilerService connection invalid). Use forkserver or spawn, with MLX imported only in
  children, never in the forkserver preload.
Constraints for WP3: no MLX in the speculative engine's threads (placement returns `off`/`numpy`); if one
is forced, each thread must create and use its own stream and arrays, and never hand a lazy array to
another thread.

## Decisions
- No `gpu_batch.py` (measurement says no). Prototype stays in `scripts/bench_gpu_batch.py`.
- `placement.py` never picks the GPU automatically; the GPU is opt-in by env var.
- The 30-run mlx sample is too small to claim equivalence; reported as such.
- Not touched: server/engine (a seam would only be needed if batching were built).
