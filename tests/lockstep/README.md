# The Petacat–Metacat lockstep harness

> **Terms.** "Episode" here means Metacat's own episodic runs: a sequence of runs in one Metacat process, each inheriting the Episodic Memory the runs before it left. It is a Metacat Mode idea, and not a Training episode (Training Mode's whole-session notion). The lockstep harness compares engine decisions with Metacat's and never touches a Training Mode Session.

This harness records every random decision headless Metacat 1.2 makes, replays those
decisions inside Petacat, and checks at each one that Petacat had the same options
with the same weights or probabilities. Each mismatch is a located bug report. The
design is in `meta-peta-trace-idea.md` (repository root). The decisions taken while
building and running it are in [`DECISIONS.md`](DECISIONS.md). The port bugs it found
are recorded in `DISCREPANCIES5.md`: the status lines on A-1…D-11 and section **G**.

## Parts

| Part | Where | What it does |
| --- | --- | --- |
| Metacat recorder | `metacat/` (`record.py`, `recorder.patch`, `decision-trace.ss`) | Runs the patched Metacat 1.2 (the `Metacat/` bundle's reconstruction with the known-failure fixes, plus a recorder patch applied to a *copy*; no other build can be run) in the `metacat:1.2` Docker image and writes one gzipped JSON-lines trace per problem and seed. The recorder draws nothing and changes no run: its end results match the published support-v1a data, and two recordings of a run are byte-identical. See [`metacat/README.md`](metacat/README.md). |
| Petacat tracer and replayer | `naming.py`, `context.py`, `tracing_rng.py`, `replay_rng.py`, `faithful.py`, `snapshot.py`, `run_trace.py` | `TracingRNG` records Petacat's own decisions in the same format. `ReplayRNG` pairs each Petacat decision with Metacat's record in the same unit, forces Metacat's result, and writes Petacat's trace with a `pair` field. Runs are in faithful mode: sequential engine, numeric backend `off`, fresh memory. `--numeric-backend NAME` (or `PETACAT_LOCKSTEP_NUMERIC_BACKEND`) runs it with a numeric backend instead, the GPU included. |
| Engine seam | `server/engine/rng.py` (`TraceSeam`), `runner.py`, `coderack.py` | `init_mcat(rng=...)`, plus no-op hooks for the unit context, the update-cycle phases, `about`, and the composite codelet choice and eviction. An ordinary run draws exactly as it did without the seam (`test_seam.py`). |
| Comparer | `scripts/compare_traces.py` | Computes every check class of spec §7.3 from the replay's pairing, compares snapshots per update cycle, applies the registry, and reports reach, agreement, and the number of update-cycle snapshots whose state differs (proposed structures aside, which the two programs hold differently by design). |
| Corpus driver and ratchet | `scripts/lockstep_corpus.py`, `ratchet*.json` | Replays and compares a whole corpus in parallel, prints a table, and keeps per-trace reach, agreement, error count and differing state snapshots. A trace may not get worse. `--numeric-backend` replays with a backend on and checks against the same ratchet; `--extended` replays the extended golden baseline's cases against `ratchet-extended.json`. |
| Verbose narration | `metacat/record_verbose.py`, `scripts/compare_verbose.py`, `verbose_metacat.txt.gz`, `test_verbose.py` | Logs what Metacat prints with `%verbose%` on (the per-codelet banner and every `say`, `vprintf`, `vprint`), replays the same run in Petacat with Verbose mode on, and compares the two line for line. `--verbose` on the corpus driver replays with the mode on and checks the same ratchet. |
| Golden baselines | `golden/engine_baseline*`, `golden/extended_*`, `../support/golden_baseline.py`, `../support/golden_extended.py`, `../../scripts/capture_golden_baseline.py`, `../../scripts/golden_coverage.py` | Byte-for-byte records of what the engine does (answers, per-codelet RNG draws, trace and state hashes, English): the 188 common-case runs, and the extended baseline of rare paths whose every case was checked against Metacat (below). They guard engine refactors, not fidelity; fidelity is what the traces above measure. |
| Patched-only and coverage guards | `test_patched_only.py`, `test_ratchet_covers_golden.py` | The first fails if a recorder can run anything but the patched build, or if a stored trace's header does not end in `+known-failure-fixes` (`traces-known-failures/reference/` aside). The second fails if a run of either golden baseline has no ratchet entry. |
| Registry | `known_divergences.toml` | Divergences that were triaged and kept. Today it holds only Metacat's own crashes (`Metacat/KNOWN-FAILURES.md`); every port divergence found so far was fixed. |

## Corpora

Every corpus below was recorded from the **patched Metacat**: `Metacat/build/source` with the bundle's second
patch group, the known-failure fixes. The recorder refuses any other build (`metacat/record.py`,
`require_patched`), and a trace's `revision` header ends in `+known-failure-fixes`; `test_patched_only.py` checks
every stored header. The one folder that is not patched is `traces-known-failures/reference/`, stored data that
nothing runs and that documents the crashes the fixes remove.

| Corpus | Location | Size | Committed? |
| --- | --- | --- | --- |
| Plain: 19 demo problems × seeds 1–30 (seeds 11–30 were once a separate "held-out" corpus; there is none now) | `traces/<slug>/<seed>.metacat.jsonl.gz` | 570 traces, ~450 MB | Only `abc-abd-xyz` seeds 1–10 |
| Episodes: 8 runs per episode, memory carried | `traces/episodes/<slug>/<S>.r<k>.metacat.jsonl.gz` | 67 episodes over all 19 problems (536 runs, 6.5 M codelets, ~1.6 GB) | No |
| Justify mode: the demo answers × seeds 1–5 | `traces/justify/<i-m-t-a>/<seed>…` | 85 traces | No |
| Extended golden baseline: every case of `golden/extended_cases.json`, recorded with the case's own cap, answer, memory clears, interventions and Self-watching setting | `traces-extended/<case id>/` (laid out like the corpora above) | 73 cases, 114 runs | No |
| Metacat's known failures: with the bundle's known-failure fixes (the patched build), and as the unpatched reference reconstruction crashed | `traces-known-failures/{fixes,reference}/` | 6 traces | Yes |
| Translation logs: the six runs behind `translation_log_metacat.tsv` | `traces-translation/<slug>/<seed>.metacat.jsonl.gz` | 6 traces | Yes |
| Snag explanations: seven runs beyond the corpus that between them hit every shape of failure (CHANGE, SWAP, CONFLICT, group-category reversal), with Metacat's logged explanations and comment lines | `traces-snags/<slug>/<seed>.metacat.jsonl.gz`, `snag_explanations_metacat.tsv` | 7 traces, 1.5 MB | Yes |
| Desync regressions: the shortest prefixes (caps of 260-480 codelets) of three runs beyond the corpus that used to desynchronise Petacat's replay (`a-b-xyz` 1, `abc-bcd-xyz` 1, `aaa-bbb-xyz` 3; `DISCREPANCIES5.md` G-Y2…G-Y4) | `traces-desync/<slug>/<seed>.metacat.jsonl.gz` | 3 traces, 0.3 MB | Yes |

`traces-known-failures/reference/` was made once, in October 2026, by recording the three crash seeds on the
reconstruction without the fixes, to show what the fixes remove (`metacat/README.md`, "Metacat's known failures").
Nothing records on that build any more.

`tests/lockstep/data/parser_metacat.json.gz` is not a trace: it is how Metacat's own input parser (`tokenize-string`
and `valid-token-list?`, the command line of the control panel) reads every Unicode scalar value and 200 whole lines, recorded
by `metacat/record_parser.py` on the patched Metacat (its format is stated at the top of the script). With patch 0003 a letter
outside a to z makes a token list invalid ("Invalid input!") instead of a crash.

The uncommitted corpora regenerate with `metacat/record.py`. Recording all 190 seeds 1–10 traces takes about
three minutes with `--jobs 12`.

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

# Whole plain corpus (seeds 1-30), then the other corpora; --check-ratchet fails if any trace got worse
.venv/bin/python scripts/lockstep_corpus.py --jobs 12 --check-ratchet
.venv/bin/python scripts/lockstep_corpus.py --extended --jobs 8
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
   and the rest of the plain corpus (seeds 1–30), and update `ratchet.json` in the same commit.

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
| Seeds 11–30 (380 runs; then a separate "held-out" corpus) | 260 to their end (first run, mid-pass) | **all 380 replay to their end with no error** |
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
| Development (190 runs) | 29,085 | none |
| Seeds 11–30 (380 runs) | 68,779 | none |
| Justify mode (85 runs) | 38,690 | none |
| Episodes (536 runs) | 434,387 | none |

The one harness gap these corpora had, two builders (or two evaluators) for the same description or rule that
agree on everything the recorder logged, so replay could not tell which one Metacat ran, is closed: the recorder
now logs the proposal's own time stamp for a description and a rule as it did for a bond, a group and a bridge
(`DISCREPANCIES5.md` G-T3). The corpora were first recorded before that, and before the project ruled that
only the patched Metacat is ever run. In round 2, stages T and T2, **every stored trace was recorded again** from the
patched Metacat with the fixed recorder: the 190 + 380 plain traces, the 536 episode runs, the 85 justify traces and
the 6 translation-log traces, 1,197 in all. Each new trace is the old one record for record, apart from the
header's `revision` (the manifest hash now ends in `+known-failure-fixes`) and the new `picked_arg_stamp` field on
description and rule decisions (about 1.7 M records gained it). That includes the traces that had 24, 215, 215 and 24
differing snapshots (`abc-abd-glz` 3 alone and as `1.r3`, `2.r2`, `3.r1` of its episodes) and seeds 11–30's `zy-x-zy` 20
(10): each replays with none, and their ratchet entries were lowered to 0. Every `state_snapshots_differing` in
the ratchets is 0, so a difference in any trace is a defect.
The re-run also
found two faults that the decisions had hidden:
- **The snapshot writer** left out the translated rule justify mode adds without
  building it. That came to 8,682 snapshots across 40 justify traces. The API's rule
  list had the same filter, so the dashboard did not show that rule; both are fixed.
- **The numeric backends**, which Petacat runs by default, still had the spreading
  arithmetic that `DISCREPANCIES5.md` B-1 fixed in the engine's own loops.

**Through the GPU.** Replayed with `--numeric-backend mlx`, the MLX backend Petacat uses
by default, every corpus gives exactly the backend-off results: all 570 plain,
85 justify and 536 episode runs replay to their end with no
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

## The extended golden baseline

The golden baseline (`golden/engine_baseline.jsonl`) is 188 runs: the 19 demo problems and the justify
demos at seeds 1-5, and one 8-run episode. It is the common case. A weight on a rare path can move
wrongly without any of those runs noticing, so `golden/extended_baseline.jsonl` and
`extended_baseline_rng.json.gz` record further cases (format and reproduction test:
`../support/golden_extended.py`, `test_golden_extended.py`). Nothing in the original baseline changed.

**How a case earns its place.** `scripts/golden_coverage.py` runs every case of a baseline in a fresh
interpreter under coverage.py (branch coverage, `sys.monitoring` core) over `server/engine/**`, and under
a `sys.monitoring` tool over the code that lives in the database: the 27 codelet bodies, the descriptor
predicates and the posting formulas, which compile from strings to code objects named `<codelet:NAME>`,
`<descriptor-predicate:NODE>` and `<posting-formula:TYPE>`. The candidates were about 7,200 runs: the 186
problems of `list-of-letter-string-analogy-problems.md` and `data/*.txt` (discovery at seeds 1-3, justify
with the answers Petacat found and with constructed ones, 6-run episodes with and without a Clear Memory),
5,000 constructed problems (random and edge-shaped: one-letter, equal, doubled, reversed, alphabet
ends), and a person's actions during a run. The selection is greedy on engine lines, engine arcs,
database lines, database branch arcs and the kinds of event, snag and clamp: a candidate that adds
none of them is not in the file. Each case's `why` in `golden/extended_cases.json` says what it added over
the original baseline and the cases before it.

**Every case runs on every numeric backend.** The committed records ran on `off`. The slow test
`test_every_extended_case_does_the_same_on_each_numeric_backend` (one per backend: `numpy`, `python`, `mlx-cpu`,
`mlx`) runs every case on that backend in a process pool and compares each field of each record with the committed
backend's recomputation, and the final state with numbers normalised (a value that is `0` on one path and `0.0` on
another is one value; that is the only way the raw `state` hash differs). A backend that is not installed or usable
is reported as a skip, never a pass.

**The cases are recorded from the patched Metacat only.** `Metacat/build/source` is the build with the known-failure
fixes, and the recorder runs nothing else. In stage T2 the 40 original cases (65 traces) were first compared as recorded
on the reconstruction without the fixes and with them (a one-off check, before the flag that chose between them was
removed): the traces were byte-identical apart from the header's `revision`. (`record_answers.py` runs only the build
as it stands, so the five episodes' answer reports were not recorded on both; the runs they follow are identical.)

**Every case was checked against Metacat 1.2.** Each case was recorded with `metacat/record.py` and
replayed with `scripts/lockstep_corpus.py` in faithful mode: it counts only if the replay reaches the end,
every decision agrees, there are no unregistered errors and no differing state snapshot. An episode must also
pass `scripts/compare_episode_answers.py` (the snag explanation, the explanation of each answer in memory and
the comparison of every ordered pair, as Metacat writes them). A case that failed is a fidelity defect in
Petacat and is **not** in the file (below). The cases run under the Standard Configuration plus a case's own parameters, if it names any, on the
engine's own object-graph loops (`off`; three cases on the pure-Python backend, replayed with
`--numeric-backend python`), which are what the lockstep harness compares with Metacat. The original baseline
runs the default configuration on NumPy. One caveat: the replay follows Metacat's trajectory, and the baseline
runs Petacat's own random stream on the same inputs, so the check says that the situations Metacat reaches
are handled as Metacat handles them, not that the baseline's own trajectory is Metacat's.

**Every case is in a ratchet.** All 114 runs are in `ratchet-extended.json` (key `<case id>|<layout slug>/<seed>`, for
example `episode/a-aa-b/s1x6-cap4000|episodes/a-aa-b/1.r1`), and all 188 runs of the original baseline are in
`ratchet.json`, `ratchet-justify.json` and `ratchet-episodes.json`. `test_ratchet_covers_golden.py` fails for any run of
either golden baseline that has no entry. The extended traces are recorded from the patched Metacat, one folder per
case under `traces-extended/<case id>/`, with each case's own cap, answer, `clear_before`, interventions and
Self-watching setting (a header that disagrees with its case is a defect: the recording script compared every header
with its case). `scripts/lockstep_corpus.py --extended` replays them (a case that names a numeric backend, three of
them `python`, is replayed with that backend whatever `--numeric-backend` says) and checks `ratchet-extended.json`. Every
entry is full reach, agreement 1.0, 0 errors and 0 differing snapshots. The 8 episode answer reports stay checked
by `scripts/compare_episode_answers.py`, which is not a ratchet.

**What is in it** (73 cases, 114 runs, 8 episode answer reports; about 30 s in one process, the whole file
recomputed in 6-12 s over a process pool): 42 discovery cases, 19 justify cases, 8 episodes; four with a
person's actions (the Options menu's group and rule codelet clamps, Clamp Themes with two themes, Undo last
clamp, the Self-watching check item off and on again), one episode with Clear Memory before run 4, 15 runs
that the codelet cap ends, and the first appearance of `conflict` snags, `manual-clamp` events and cap-ended
runs in any baseline. Five cases (`-selfwatchingoff-`) run with Self-watching mode off from the start, through a
per-case `parameters` entry (`self_watching_enabled_default: false`). Twenty-nine were added by stage F of round 2 after
the fidelity fixes below: the two that exposed a defect (`ly -> yl; cbaii`, `aazzz -> azzza; aye`), the five
Self-watching-off cases, 16 from stage W's wide check (N1, N2, defect A in an episode, the Self-watching switch at codelet 302, the cluster C runs and the long N3 run) and 6 that reach lines nothing before reached. They add no engine or database line or branch to the coverage below (measured: the
posting rules give a Self-watching codelet probability 0 while the mode is off, so its fizzle lines can only be
reached by a codelet already on the rack when the mode is switched off, as in `xqc-xqd-mrrjjj`); the five
Self-watching-off cases change Petacat's own record on the code before the fix (the `state` hash for three; the
decisions too for the two justify cases), whereas the other two do not: the baseline runs Petacat's own random
stream, which neither defect moved in these runs, so they only show that the situation Metacat reaches is handled
as Metacat handles it (`tests/unit/test_fidelity_fixes.py` guards the degree of support, and the recorder the time stamp).

Stage 6 added four cases (`a -> z; abc`, `abc -> zbc; xyz`, `xyz -> xya; zzz`, `aab -> zzb; aab`) whose rules change a letter's
alphabetic position (first <-> last of the alphabet). Dropping the binding of `plato-alphabetic-position-category` from
`rule.letter_or_alphabetic_dimension` or from `image_operation.new_alpha_position_category` changes these runs and none of
the 41 demo problems at seeds 1-3. Each was recorded with `record.py` (seeds 1-4, cap 3000) and replayed in faithful mode:
agreement 1.0, no errors, no differing snapshot, in all 16 runs. The coverage table below was measured before stage 6.

| | Original baseline | Original + extended |
| --- | --- | --- |
| Engine lines (`server/engine/**`, 14,259; measured before stage 6) | 11,431 (80.2 %) | 12,149 (85.2 %) |
| Engine branches (5,886) | 4,139 | 4,533 |
| Database code lines (846) | 779 | 795 |
| Database code branch arcs (718) | 626 | 644 |

```sh
# Reproduce the file and read the coverage (minutes)
.venv/bin/python scripts/capture_golden_baseline.py --extended --jobs 8            # writes only extended_*
.venv/bin/python scripts/golden_coverage.py --which both --jobs 8                  # the table above
# Measure candidate cases (extended-format JSON) with the baseline
.venv/bin/python scripts/golden_coverage.py --which both --jobs 8 --extra-cases candidates.json
# Record, replay and compare one candidate case
python3 tests/lockstep/metacat/record.py --problem abc abd xyz --seeds 1 --cap 3000 --intervene "200:clamp-group,500:undo"
.venv/bin/python scripts/lockstep_corpus.py --traces <out> --out-dir <out>/replays
```

**Fidelity defects the search found, and what fixed them** (round 2, stage F; each case is now in the file):
- **Degree of support, `answer-finder`.** `ly → yl; cbaii`, seed 1, codelet 339: Metacat's `stochastic-if*`
  probability was 0.44, Petacat's 0.45. A bridge's strength is a whole number, so Metacat's `(% strength)` is an
  exact rational and `rules.ss:237-242`'s `(100* (product ...))` is exact: 75 and 74 give 111/2, which rounds
  half to even to 56. Petacat multiplied floats (`0.75 * 0.74 * 100` is 55.49999999999999) and got 55.
  `Rule.get_degree_of_support` now multiplies `Fraction`s.
- **`Themespace.add_theme` ignored Self-watching mode.** `themes.ss:374-375` returns `#f` when
  `%self-watching-enabled%` is off. `Themespace.self_watching_enabled`, kept in step by
  `EngineContext.self_watching_enabled` (a property), is now tested first. Every other use of the flag was
  audited against the Scheme (`coderack.ss:469` posting, `trace.ss:117` `permission-to-clamp?`,
  `jootsing.ss:25,258` and `themes.ss:752` the three self-watching codelets, `gui.ss:607-626` the switch):
  all agreed except one. The justify clamps (`justify.ss:79,124,138`) asked `permission-to-clamp?` with the flag
  defaulted to on, so a justify run with the mode off diverged at once (`abc → abd; xyz`, answer `wyz`, from
  codelet 488); `TemporalTrace.permission_to_clamp` takes the flag with no default, and `attempt_justification`,
  `clamp_rules` and the `answer-justifier` body pass it. The runner's `if ctx.self_watching_enabled` guards around
  the Themespace's spreading (`run.ss:313-314` has none) are now redundant, since no theme exists while the mode is off,
  and are kept. Of the 54 cases recorded earlier all 54 now match, and so do three justify cases with the mode off.
- **The same mistake in four more places**, found by auditing every `round`, `100*`, `floor`, `truncate` and `ceiling`
  of the Scheme (instrumented in Metacat, 123 runs, 65 sites reached; the table is `agents-workspace/metacat-cleanup/round2/F-fidelity/ROUNDING-AUDIT.tsv`, not part of the repository).
  Scheme's whole numbers and the ratios they make stay exact until a float enters, and `round` of an exact ratio is
  half to even on the exact value. Where Petacat went through a float product, the exact halves were lost:
  `ConceptMapping.strength` and `slippability` (association 50, depth 30 gave 55 for Metacat's 54; association 50,
  depth 90 gave 9 for 10), `compute-rule-quality` (uniformity 70, abstractness 37, succinctness 57 gave 31 for 32;
  98 of 1,030,301 combinations, 14 of them reachable), the Slipnet's spread at an `update_cycle_length` other than 15
  (186 of 612,060 combinations; the float backends are not used then), and the decay at a whole-number exponent above
  1. All now round through `server/engine/formulas.py` (`round_exact`, `round_ratio`: whole-number arithmetic, no
  rational type), with exhaustive tests in `tests/unit/test_exact_rounding.py`. The other 60 sites are one correctly
  rounded division of whole numbers, a float in Metacat too, or display; each is a row of the audit.
- **Stage W's wide check** (4,384 runs against Metacat, `DISCREPANCIES5.md` F-N1, F-N2, F-N4, F-C, R1): the order
  `check-for-conflicts` and `apply-transforms` take (Chez's `pairwise-map` and merge sort), a consolidated group built over
  a slot a stale bond holds (`build-bond` overwrites the pointers), and the recording limit behind stage W's "cluster C"
  and its long N3 run, which re-recorded replay with no difference. The one thing left was a crash of patched Metacat itself,
  on a `bridge-builder` of a group of six or more objects (`slipnet.ss:495`, `bridges.ss:1404-1407`,
  `concept-mappings.ss:40`; 83 of the 4,384 runs, crash R1). A crash of patched Metacat means the patch is incomplete, so
  `Metacat/patches/fixes/0002-length-group-of-six-or-more.patch` makes the Length concept mapping only when both lengths
  exist (as `attach-length-description` already checks), and the registry entry for the shape
  (`REF:crash-bridge-builder-group-of-6-or-more`) is gone. All 83 runs, recorded again, are identical to their old
  recordings up to the old crash point; Petacat's guard at `builtins.py` now matches what Metacat does, and the 83 replay to
  their new ends (88 traces, with the later runs of the episodes) with agreement 1.0, no error and no differing snapshot.
  `data/aaa-aaaaaa-aaa.seed1.metacat.jsonl.gz`, the smallest case (`aaa → aaaaaa; aaa`, 1,614 codelets, answer `aaaaaa`),
  is replayed by `test_comparer.py`.
- **A description's time stamp** was not an engine fault. `aazzz → azzza; aye`, seed 3: two top-down description scouts
  proposed `desc(m.2,alphabetic-position-category,alphabetic-last)` at 1670 and 1676, both builders agreed on every
  field the recorder logged, and replay took the later one (`DISCREPANCIES5.md` G-T3). Fixed in the recorder
  (`decision-trace.ss`, `picked_arg_stamp` for a description and a rule); no engine change.
- **Not Metacat's to run.** Problem strings with a capital letter or a digit (`abC`, `1234`) are accepted by
  Petacat and refused by Metacat's recorder (lowercase letters only), so they cannot be checked and are not in the baseline.

Not Metacat Mode surfaces that Petacat has and Metacat lacks, so they cannot be checked and are not in
the baseline either: clamping a single codelet type, the temperature or a Slipnet node by hand, and the
spreading-activation threshold control.

**Tools added for this** (`metacat/README.md`, "A person's actions"): `record.py --episode-clear-before`,
`--intervene` (codelet-pattern clamps, Clamp Themes, Undo last clamp, the Self-watching check item) and
`--self-watching off`, with the replay side in `run_trace.py`, `faithful.py` and
`../support/interventions.py` (which calls the product's own `RunService.clamp_codelet_pattern`,
`clamp_theme_pattern`, `undo_last_clamp` and `set_self_watching`, bare: each binds the run's own id allocator, so
a clamp event's number is the run's and not the process's). `scripts/compare_episode_answers.py` had
stopped working at `d4b4cd2` (`explain_answer` now needs the run's `meta`) and was repaired.

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
