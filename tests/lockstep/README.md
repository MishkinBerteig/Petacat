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
| Verbose narration | `metacat/record_verbose.py`, `scripts/compare_verbose.py`, `verbose_metacat.txt.gz`, `test_verbose.py` | Logs what Metacat prints with `%verbose%` on (the per-codelet banner and every `say`, `vprintf`, `vprint`), replays the same run in Petacat with Verbose mode on, and compares the two line for line. `--verbose` on the corpus driver replays with the mode on and checks the same ratchet. |
| Registry | `known_divergences.toml` | Divergences that were triaged and kept. Today it holds only Metacat's own crashes (`Metacat/KNOWN-FAILURES.md`); every port divergence found so far was fixed. |

## Corpora

| Corpus | Location | Size | Committed? |
| --- | --- | --- | --- |
| Development: 19 demo problems × seeds 1–10 | `traces/<slug>/<seed>.metacat.jsonl.gz` | 190 traces, ~130 MB | Only `abc-abd-xyz` |
| Held-out: the same problems × seeds 11–30 | `traces-heldout/` | 380 traces, ~320 MB | No |
| Episodes: 8 runs per episode, memory carried | `traces/episodes/<slug>/<S>.r<k>.metacat.jsonl.gz` | 67 episodes over all 19 problems (536 runs, 6.5 M codelets, ~1.6 GB) | No |
| Justify mode: the demo answers × seeds 1–5 | `traces/justify/<i-m-t-a>/<seed>…` | 85 traces | No |
| Metacat's known failures, on the reference and with the bundle's known-failure fixes | `traces-known-failures/{reference,fixes}/` | 6 traces | Yes |
| Snag explanations: seven runs beyond the corpus that between them hit every shape of failure (CHANGE, SWAP, CONFLICT, group-category reversal), with Metacat's logged explanations and comment lines | `traces-snags/<slug>/<seed>.metacat.jsonl.gz`, `snag_explanations_metacat.tsv` | 7 traces, 1.5 MB | Yes |
| Desync regressions: the shortest prefixes (caps of 260-480 codelets) of three runs beyond the corpus that used to desynchronise Petacat's replay (`a-b-xyz` 1, `abc-bcd-xyz` 1, `aaa-bbb-xyz` 3; `DISCREPANCIES5.md` G-Y2…G-Y4) | `traces-desync/<slug>/<seed>.metacat.jsonl.gz` | 3 traces, 0.3 MB | Yes |

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

# Commentary: Metacat's comment-window paragraphs (both voices) against Petacat's replay
.venv/bin/python scripts/compare_commentary.py abc-abd-xyz 1-10
.venv/bin/python scripts/compare_commentary.py abc-abd-xyz-wyz 1-5 --justify
.venv/bin/python scripts/compare_commentary.py abc-abd-xyz 1-3 --episode

# Verbose mode: Metacat's console narration (%verbose% on) against Petacat's, line for line
.venv/bin/python scripts/compare_verbose.py abc-abd-xyz 1-5
.venv/bin/python scripts/compare_verbose.py abc-abd-xyz-wyz 1-3 --justify
.venv/bin/python scripts/compare_verbose.py abc-abd-xyz 1 --episode

# Whole corpus; --check-ratchet fails if any trace got worse
.venv/bin/python scripts/lockstep_corpus.py --jobs 12 --check-ratchet
.venv/bin/python scripts/lockstep_corpus.py --traces tests/lockstep/traces-heldout --jobs 12
.venv/bin/python scripts/lockstep_corpus.py --episodes --jobs 8
.venv/bin/python scripts/lockstep_corpus.py --justify --jobs 8

# The same corpora with Verbose mode on; narration only reads, so the results are the
# ratchet's, unchanged
.venv/bin/python scripts/lockstep_corpus.py --verbose --jobs 12 --check-ratchet

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

## Beyond the corpus (2026-10-29)

The corpora above are 19 problems. Three further sweeps used the same recorder and the
same replay, on problems chosen to be unlike them:

| Sweep | Runs | Problems | Codelet cap | Result before the pass | Result after |
| --- | --- | --- | --- | --- | --- |
| Snag problems, seeds 1-12 (snapshots off) | 336 | 28 | 6000 | **28 runs desynchronised** (5 problems) | all 336 replay to their end, 0 errors (5.49 M decisions) |
| Widened net, seeds 1-10 / 1-5 (snapshots on) | 660 | 84 | 4000 | not run before | all 660 replay to their end, 0 errors, 0 differing state snapshots (5.81 M decisions, 61,070 snapshots) |
| Widened episodes, 3 seeds x 8 problems x 8 runs (memory carried) | 192 | 8 | 5000 | not run before | all 192 replay to their end, 0 errors, 0 differing snapshots (3.18 M decisions); the 131 stored answers are explained and compared as Metacat does |

The 28 desyncs were five real engine differences, none a harness tie: a reference object
matched through the first descriptor of a type instead of any (`a → b; xyz`), rule clauses
differing in `self` / `subobjects` taken for equal (`abc → bcd; xyz`, `aaa → bbb; xyz`), the
duplicate branch of `group-builder` pre-empted by Petacat's stale-premise guard
(`aaa → bbb; xyz` 3), a bridge's internal coherence tried in one order only (`abbc → abcc;
xyz` 4), and, in answer descriptions, `get-equivalent-bridge` taking any bridge over the same
positions for the same bridge (the `ijll` themes of `aabc → aabd; ijkk`). `DISCREPANCIES5.md`
G-Y1…G-Y7 has each, with the Scheme and the evidence; the three that show at a codelet are
pinned by `test_desync_fixes.py` on committed prefixes, the other two by
`tests/module/test_lockstep_desync_fixes.py`. These sweeps are not committed (the traces are
tens of megabytes); to repeat one: `python3 tests/lockstep/metacat/record.py --problem abc abd
ijkk --seeds 1-10 --cap 4000 --out /tmp/w` then `scripts/lockstep_corpus.py --traces /tmp/w
--out-dir /tmp/wr --jobs 12`. A trace recorded with `--no-snapshots` cannot show a state
difference that did not change a decision yet (G-Y5 was found by re-recording one run with
snapshots).

The individual fixes are listed in `DISCREPANCIES5.md` section G (G-A1 … G-W1) and in the
status lines of A-1 … D-11.

## Rule English and event names

Two text checks that are not part of the decision-trace comparison: the English of every rule
(`tests/seed_unit/rule_english_metacat.tsv`) and the print-names and headers of the Temporal
Trace events (`tests/lockstep/event_names_metacat.tsv`).  Each fixture is regenerated from
Metacat, and Petacat is compared with it over the whole recorded set, by

```sh
.venv/bin/python scripts/compare_rule_english.py --jobs 2 --table out.tsv   # 12,582 rules
.venv/bin/python scripts/compare_events.py --table out.tsv                  # 131 events (--corpus: all runs)
```

Recorders, expected results and runtimes: `tests/lockstep/metacat/README.md`, "Rule English and
event names".  The comparison logic that needs no Docker is tested by
`test_rule_english_tools.py` and `test_event_tools.py`.

## Answer-frequency study

If decision traces match run for run, answer *frequencies* match too; this is the final
confirmation the spec asks for, with the tool that made the published numbers.  Both
forms are in `scripts/compare_frequencies.py` (Metacat side:
`tests/lockstep/metacat/record_frequencies.py`).

```sh
# one problem, both engines on the same seeds (the 1,000-run wxyz study; ~10 min, Docker + 4 cores)
.venv/bin/python scripts/compare_frequencies.py study wxyz vxyz abcd 101-1100 --jobs 4 --metacat-jobs 4
.venv/bin/python scripts/compare_frequencies.py study wxyz vxyz abcd 101-1100 --workers 6 --jobs 3   # free-running Petacat (BACKEND=numpy)
# Petacat against the published support-v1a observations of the 19 problems (~25 min, 10 cores, no Docker)
.venv/bin/python scripts/compare_frequencies.py support-v1a --runs 200 --jobs 10 \
    --json measurements/vs-metacat-support-v1a-lockstep.json
```

`study` prints both frequency tables, mean codelets, the total-variation distance, a
two-sample chi-square (rare answers pooled to expected count >= 5) and a z score per common
answer; recordings land in `tests/lockstep/out/frequencies/` and can be re-compared with
`--metacat FILE --petacat FILE`.  `support-v1a` reads the reference counts from
`studies/support-v1a/data/main.tar.gz` (reproduced exactly: the per-problem frequencies in
`measurements/vs-metacat-support-v1a-lockstep.json` are equal to those computed now), runs
Petacat on seeds 5000001.. and reports TV against its expected value under the reference,
Monte Carlo p-values and the novel answers.  Expected: Petacat's frequencies are
statistically indistinguishable from Metacat's on every problem (see
`measurements/vs-metacat-support-v1a-lockstep.md`); the Monte Carlo p-values vary a little with
the random generator, the frequencies and TV do not.  Spot-checked: `--only copy1,copy4,misc2,run4`
reproduces the committed Petacat frequencies and TV exactly (about 2.5 minutes with `--jobs 4`).
No comparison is a pass/fail gate.  Tests without Docker: `test_frequencies.py`.

## Snag explanations, snag sweep and fidelity net

Text and state checks that read Metacat 1.2 itself, rebuilt as runnable tools (the first pass
used throw-away scripts).  Each needs Docker and `metacat:1.2`; none is part of the test suite.
Recorders are in `tests/lockstep/metacat/`, comparers and drivers in `scripts/`, problem lists in
`tests/lockstep/data/`, default output in `tests/lockstep/out/` (git-ignored; `--out DIR` changes
it).  Tests without Docker: `test_snag_and_answer_tools.py`.

**Snag explanations (fixture `snag_explanations_metacat.tsv`).**  Metacat's `get-explanation` for
each snag and the two snag comment lines, against Petacat's replay.

```sh
.venv/bin/python scripts/compare_snags.py --regenerate-fixture --out tests/lockstep/out   # ~10 s, 8 containers
.venv/bin/python scripts/compare_snags.py abc-abd-xyz 1-10                                # corpus: 24/24 snags, 24/24 comments, ~25 s
```

Expected: the rebuilt file has the same 16 rows as the committed one (identical apart from the `#`
header).  The other mode compares a problem's snags over a seed list, replaying the committed
trace of each run (`--traces DIR` adds a corpus root).

**Snag sweep.**  The search for problems on which Petacat's snag text could differ: 87 problems
(`data/snag_sweep_problems.txt`), seeds 1-12, cap 6000; the 28 that hit a snag are in
`data/snag_sweep_with_snags.txt`.  Original result: 479 snags (CHANGE 397, SWAP 53, CONFLICT 29)
and 478 matched, the one miss a replay desynchronisation since fixed.

```sh
.venv/bin/python scripts/sweep_snags.py --limit 2                    # smoke: ~1.5 min
.venv/bin/python scripts/sweep_snags.py --only-known --jobs 3        # the 28 problems: search, record, replay, compare; about an hour, several GB under --out
.venv/bin/python scripts/sweep_snags.py --stage search               # Metacat side only; minutes
```

Spot-check: the search stage on `abc abd xyzz`, `abc zyx xyz`, `abc abd wxyz`, `abc abcd xyz`
gives 46, 29, 38 and 66 snags, the numbers of the first search; `wxyz vxyz abcd` (30 snags, 12 runs)
replays 30/30 with 30/30 comments.

**Fidelity widened net.**  660 single runs on 84 problems and 24 eight-run episodes, recorded
with snapshots and replayed with `lockstep_corpus.py`.  Lists: `data/fidelity_widen.txt` (48
problems, seeds 1-10, cap 4000), `data/fidelity_widen2.txt` (36, seeds 1-5, cap 4000),
`data/fidelity_episodes.txt` (8, episode seeds 1-3, cap 5000).  Original result: every run
replays to its end with 0 errors and 0 differing snapshots; the 131 answers of the episodes are
explained and compared as Metacat does.

```sh
.venv/bin/python scripts/sweep_fidelity.py --net widen --limit 1 --seeds 1-3        # smoke: 10 s
.venv/bin/python scripts/sweep_fidelity.py --net widen2 --jobs 3                    # 180 runs: tens of minutes
.venv/bin/python scripts/sweep_fidelity.py --net episodes --limit 1 --seeds 1-2     # 2 episodes + answer check: ~2.5 min
.venv/bin/python scripts/sweep_fidelity.py --net all --jobs 3                       # the whole net: hours
```

Spot-check: `abc cba abcd` seeds 1-5 give `dcba` 5 of 5, `abcd dcba xyz` `zyx` 5 of 5, `abc abd
aabbcc` seeds 1-10 `aabbdd` 9 and one run to the cap, as recorded; all replay with no difference.

**Episode answer check.**  After an episode, Metacat explains each answer in memory and compares
every ordered pair; Petacat does the same from its replay of the recorded runs.

```sh
.venv/bin/python scripts/compare_episode_answers.py abc-abd-xyz 1-3 --jobs 3    # 15/15 ANS, 15/15 EXPL, 60/60 CMP; ~100 s
```

The comparison is order-sensitive by default: answers, explanations and pairs must come in the
order Metacat's `get-answers` gives (reported as `ORDER`); `--ignore-order` compares by answer.
`sweep_fidelity.py --net episodes` runs the same check on its own episodes.
