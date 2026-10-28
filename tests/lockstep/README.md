# The Petacat–Metacat lockstep harness

This harness records every random decision headless Metacat 1.2 makes, replays those
decisions inside Petacat, and checks at each one that Petacat had the same options
with the same weights or probabilities. Each mismatch is a located bug report. The
design is in `meta-peta-trace-idea.md` (repository root). The decisions taken while
building and running it are in [`DECISIONS.md`](DECISIONS.md). The port bugs it found
are recorded in `DISCREPANCIES5.md`: the status lines on A-1…D-11 and section **G**.

## Parts

| Part | Where | What it does |
| --- | --- | --- |
| Metacat recorder | `metacat/` (`record.py`, `recorder.patch`, `decision-trace.ss`) | Runs Metacat 1.2 (the `Metacat/` bundle's reconstruction plus a recorder patch applied to a *copy*) in the `metacat:1.2` Docker image and writes one gzipped JSON-lines trace per problem and seed. The recorder draws nothing and changes no run: its end results match the published support-v1a data, and two recordings of a run are byte-identical. See [`metacat/README.md`](metacat/README.md). |
| Petacat tracer and replayer | `naming.py`, `context.py`, `tracing_rng.py`, `replay_rng.py`, `faithful.py`, `snapshot.py`, `run_trace.py` | `TracingRNG` records Petacat's own decisions in the same format. `ReplayRNG` pairs each Petacat decision with Metacat's record in the same unit, forces Metacat's result, and writes Petacat's trace with a `pair` field. Runs are in faithful mode: sequential engine, numeric backend `off`, fresh memory, `initial_clamp_fixed_time` on. `--numeric-backend NAME` (or `PETACAT_LOCKSTEP_NUMERIC_BACKEND`) runs it with a numeric backend instead, the GPU included. |
| Engine seam | `server/engine/rng.py` (`TraceSeam`), `runner.py`, `coderack.py` | `init_mcat(rng=...)`, plus no-op hooks for the unit context, the update-cycle phases, `about`, and the composite codelet choice and eviction. An ordinary run draws exactly as it did without the seam (`test_seam.py`). |
| Comparer | `scripts/compare_traces.py` | Computes every check class of spec §7.3 from the replay's pairing, compares snapshots per update cycle, applies the registry, and reports reach, agreement, and the number of update-cycle snapshots whose state differs (proposed structures aside, which the two programs hold differently by design). |
| Corpus driver and ratchet | `scripts/lockstep_corpus.py`, `ratchet*.json` | Replays and compares a whole corpus in parallel, prints a table, and keeps per-trace reach, agreement, error count and differing state snapshots. A trace may not get worse. `--numeric-backend` replays with a backend on and checks against the same ratchet. |
| Registry | `known_divergences.toml` | Divergences that were triaged and kept. Today it holds only Metacat's own crashes (`Metacat/KNOWN-FAILURES.md`); every port divergence found so far was fixed. |

## Corpora

| Corpus | Location | Size | Committed? |
| --- | --- | --- | --- |
| Development: 19 demo problems × seeds 1–10 | `traces/<slug>/<seed>.metacat.jsonl.gz` | 190 traces, ~130 MB | Only `abc-abd-xyz` |
| Held-out: the same problems × seeds 11–30 | `traces-heldout/` | 380 traces, ~320 MB | No |
| Episodes: 8 runs per episode, memory carried | `traces/episodes/<slug>/<S>.r<k>.metacat.jsonl.gz` | 67 episodes over all 19 problems (536 runs, 6.5 M codelets, ~1.6 GB) | No |
| Justify mode: the demo answers × seeds 1–5 | `traces/justify/<i-m-t-a>/<seed>…` | 85 traces | No |
| Metacat's known failures, on the reference and with the bundle's known-failure fixes | `traces-known-failures/{reference,fixes}/` | 6 traces | Yes |

The uncommitted corpora regenerate in minutes with `metacat/record.py`. Recording all 190
development traces takes about three minutes with `--jobs 12`.

## Everyday use

```sh
# Record (Metacat side; needs Docker and the metacat:1.2 image, see Metacat/README.md)
python3 tests/lockstep/metacat/record.py --problem abc abd xyz --seeds 1-10
python3 tests/lockstep/metacat/record.py --problem abc abd xyz --seeds 1-5 --episode-runs 8
python3 tests/lockstep/metacat/record.py --problem abc abd xyz --answer wyz --seeds 1-5

# Replay and compare one trace
.venv/bin/python -m tests.lockstep.run_trace replay --metacat tests/lockstep/traces/abc-abd-xyz/1.metacat.jsonl.gz --out /tmp/replay
.venv/bin/python scripts/compare_traces.py tests/lockstep/traces/abc-abd-xyz/1.metacat.jsonl.gz /tmp/replay/1.petacat.jsonl.gz

# Whole corpus; --check-ratchet fails if any trace got worse
.venv/bin/python scripts/lockstep_corpus.py --jobs 12 --check-ratchet
.venv/bin/python scripts/lockstep_corpus.py --traces tests/lockstep/traces-heldout --jobs 12
.venv/bin/python scripts/lockstep_corpus.py --episodes --jobs 8
.venv/bin/python scripts/lockstep_corpus.py --justify --jobs 8

# The same corpora through the GPU backend Petacat uses by default; it must match
# the ratchet the backend-off replays wrote
.venv/bin/python scripts/lockstep_corpus.py --numeric-backend mlx --jobs 12 --check-ratchet
```

The report shows the first fatal failure and the first error, with both records side by
side and the nearest snapshot difference. It also gives counts by class and agreement by
codelet type and by site. *Reach* is the codelet where replay had to stop, or the run's
length if it never stopped. *Agreement* is the share of Metacat's decisions that were
paired with no unregistered error. *Snaps* in the corpus table is the number of
update-cycle snapshots whose state differs: a difference that changed no decision shows
up there and nowhere else.

## How a divergence is worked

1. Take a trace's **first error**, not its first fatal: a `missing-pick` at `choose` or
   `evict` only means the two coderacks diverged earlier.
2. Read both records and the nearest snapshot difference. The snapshot difference usually
   points upstream, to a salience, an activation, or a structure that exists on one side
   only.
3. Fix Petacat in its own idiom and cite the Scheme. Then replay the development corpus
   and the held-out corpus, and update `ratchet.json` in the same commit.

The traps that produced most of the bugs:
- Metacat redefines `round`, `floor`, `ceiling` and `truncate` to return exact integers
  (round half to even), and computes many values as exact rationals.
- Lists are built with `cons`, so they are newest first, and `remq-duplicates` keeps the
  last occurrence.
- Chez evaluates procedure arguments and `map` out of order.
- Several quantities are stored once per update cycle rather than read live.

## Results of the lockstep pass (2026-10-27/28)

| Corpus | First replay | After the pass |
| --- | --- | --- |
| Development: 19 problems × seeds 1–10 (190 runs) | reach 21 % of codelets; 29 traces replay to their end | **all 190 replay to their end with no error** |
| Held-out: seeds 11–30 (380 runs) | 260 to their end (first run, mid-pass) | **all 380 replay to their end with no error** |
| Justify mode (85 runs) | 21 to their end (first run, mid-pass) | **all 85 replay to their end with no error** |
| Episodes, memory carried (536 runs, 6.5 M codelets) | 66 of 200 runs to their end (first run, mid-pass) | **all 536 replay to their end with no error** |
| Metacat's three known crashes | — | Petacat follows Metacat to each crash point with no error |

"No error" means every random decision had the same options with the same weights or
probability, and the run ended the same way. This README used to say that every
update-cycle snapshot agreed as well. The comparer did compare them, but neither the
corpus table nor the ratchet counted them, so state that changed no decision went
unreported. Since 2026-10-28 both count the snapshots whose state differs (`snaps`),
leaving out proposed structures, which the two programs hold differently by design
(`DECISIONS.md`). Re-run that day:

| Corpus | Snapshots | Differing state snapshots |
| --- | --- | --- |
| Development (190 runs) | 29,085 | 24, all in `abc-abd-glz` 3 |
| Held-out (380 runs) | 68,779 | 10, all in `zy-x-zy` 20 |
| Justify mode (85 runs) | 38,690 | none |
| Episodes (536 runs) | 434,387 | 454, all in the three runs at `abc-abd-glz` seed 3 |

What remains is one harness gap, not an engine difference: two builders for the same
description that agree on everything the recorder logs, so replay cannot tell which one
Metacat ran. Petacat builds the other proposal, whose time stamp differs
(`DISCREPANCIES5.md` G-T3). The re-run also found two faults that the decisions had
hidden:
- **The snapshot writer** left out the translated rule justify mode adds without
  building it. That came to 8,682 snapshots across 40 justify traces. The API's rule
  list had the same filter, so the dashboard did not show that rule; both are fixed.
- **The numeric backends**, which Petacat runs by default, still had the spreading
  arithmetic that `DISCREPANCIES5.md` B-1 fixed in the engine's own loops.

**Through the GPU.** Replayed with `--numeric-backend mlx`, the MLX backend Petacat uses
by default, every corpus gives exactly the backend-off results: all 190 development,
380 held-out and 85 justify runs and 536 episode runs replay to their end with no
error, with the same differing snapshots as above. Faithful mode keeps the backend off
for the reference path, so this is the check that what Petacat actually runs makes
Metacat's decisions too.

As the spec's final confirmation, Petacat's own answer distributions were compared with the
published support-v1a reference: 200 runs per problem against 20,000 Metacat runs per
problem. No significant difference was found on any of the 19 problems
(`measurements/vs-metacat-support-v1a-lockstep.md`).

The individual fixes are listed in `DISCREPANCIES5.md` section G (G-A1 … G-W1) and in the
status lines of A-1 … D-11.
