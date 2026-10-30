# Parallel subsystem measurements (2026-10-29/30, Apple M5 Max)

The evidence behind the README's
[Parallelism section](../../README.md#parallelism-the-serverparallel-plugin). The machine has 6 Super
and 12 Performance cores, a 40-core GPU and 128 GB of unified memory. Unless a file says
otherwise, figures were taken on a quiet machine.

| File | What it shows |
|---|---|
| `cognitive-equivalence.md`, `serial-vs-stream-500.json` | The stream-serial reference, which the speculative executor reproduces bit for bit, against the faithful loop. 29 problems × 500 seeds, 29,000 runs: no distribution differs |
| `abce-serial-vs-stream.md` | The deep answer `abce` to `wxyz → vxyz; abcd`, the signal free-running degraded, under the faithful loop and the stream reference |
| `swarm-scaling.json` | The swarm from 1 to 17 processes on a six-problem mix, with every outcome identical to the serial run |
| `swarm-vs-serial-xyz-2000.txt` | 2,000 runs of `abc → abd; xyz`, swarm against serial: 19.1 s against 239.4 s, with the same distribution |
| `serial-before-after.jsonl` | The serial engine before this work (`cc9037b`) and after, interleaved, on three backends and both interpreters |
| `speculative-engine.md`, `speculative-bench.json` | The speculative executor: what it guarantees, the evidence, its speed, the hazards found and the engine seams that would help |
| `speculative-effects-audit.md` | The audit of every builtin and codelet body that the effects table is built from |
| `update-cycle-analysis.md` | The update cycle phase by phase: dependencies, random draws, time, and what can run in parallel |
| `gpu-ane-unified-memory.md`, `gpu-batch-bench.json` | Where the GPU, the Neural Engine and unified memory could help today: nowhere in the engine at 59 Slipnet nodes |

The scripts that regenerate these are:
- `scripts/compare_executors.py`
- `scripts/bench_swarm.py`
- `scripts/swarm.py`
- `scripts/bench_speculative.py`
- `scripts/bench_update_cycle.py`
- `scripts/bench_gpu_batch.py`

The serial A/B driver and the per-seed exactness sweep are under
`agents-workspace/wp8-validation/`, which is not committed.
