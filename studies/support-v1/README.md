# Versioned Support Diagnostic Study

This prospective study replaces uncertain historical build attribution with
committed code, a fixed protocol, verified reference source, and ordered runs.
The protocol must be committed before the main collection starts. This is a
repository-recorded protocol, not an externally registered preregistration.

## Scope

The 19 historical inputs are fixed in [protocol.json](protocol.json). Each run
starts with fresh episodic memory and goes directly to a 100,000-codelet cap.
There is no low-cap replay, adaptive collection stop, GPU run, or engine repair
in this study. The reference uses reconstructed Metacat and Chez Scheme 9.5.4;
the port uses the committed Petacat serial engine with NumPy float64.

| Phase | Runs per input | Total | Purpose |
| --- | ---: | ---: | --- |
| Construction | 20,000 | 380,000 | Freeze observed sets and heads |
| Validation | 30,000 | 570,000 | Measure held-out reference novelty and flags |
| Port | 1,000 | 19,000 | Ten nonoverlapping 100-run checks per input |

The main study has **969,000 runs**. Separate pilot samples contain 475 reference
and 95 port runs; they are excluded from all main analyses. Seed blocks are
disjoint across phases and inputs: `seed_base + input_index * 100000 + run_index`,
with zero-based indices. Shared seed numbers across languages are not treated
as matched random trajectories. Deterministic pseudorandom seeds provide
replayability, not a proof of independent sampling.

Twelve workers share the machine. Jobs are immutable 250-run chunks, with one
fresh process per chunk. A crash or timeout fails collection instead of being
counted as an answer or silently dropping slow runs. Validated chunks are
reused on resume; incomplete attempts and logs are retained. The 4-hour chunk
timeout is an operational safeguard, not a data-selection rule. No partial
study is eligible for the main analysis.

## Prespecified Analysis

1. Freeze each full construction set and its smallest frequency-ranked prefix
   containing at least half the observations. Break frequency ties
   lexicographically. `*NONE*` and `*CAP*` are outcomes, not discarded runs.
2. Report held-out novel-draw counts and one-sided 95% exact binomial upper
   limits, both per input and Bonferroni-adjusted across the 19 full-reference
   inputs. A zero count among 30,000 gives a per-input upper limit below 1e-4,
   but not a simultaneous 19-input limit below 1e-4. These limits require the
   usual independent, common-law sampling assumption conditional on the frozen
   reference; support equality alone does not transfer them to Petacat.
3. Divide validation and port sequences into nonoverlapping 100-run batches.
   Report novel draws, distinct novel outcomes, missing head members, and
   per-batch flags separately. Validation is not merged into the frozen set.
4. Compare against a frequency-sensitive two-sample total-variation permutation
   test at the same 100-run check budget, using the same 20,000 construction
   observations. Generate 999 conditional label permutations using NumPy's
   multivariate hypergeometric sampler and the fixed analysis RNG seed. Use
   `(1 + number_at_least_as_extreme) / 1000`; report raw p-values and thresholds
   0.05 and 0.05/19. Its null is equality of outcome distributions, not support.
   Repeated batches share a reference; they are not unconditional independent
   replications. No familywise claim across all batches is made.
5. Replay construction prefixes of 1,000, 5,000, 10,000, and 20,000 and two
   prespecified heuristic stopping rules against the same held-out observations.
   The singleton rule checks every 500 runs, after 3,000, for `f1/N <= 1e-4`,
   with a 10,000-run floor when `f1=0`. The no-discovery rule requires at least
   3,000 runs and a 1,000-run discovery-free gap, checked every 500. Both are
   truncated at the fixed 20,000 budget and report whether the rule fired.
   These are prospective comparator definitions, not reconstructions of
   undocumented historical scheduling. Report their differing construction
   costs; do not call differing construction budgets equal.
6. Preserve codelet counts, per-run elapsed time, chunk wall time, failures,
   source/data hashes, dependency versions, and completion times. Concurrent
   emulated Scheme and native Python timings are descriptive, not a controlled
   language-performance benchmark. Engine defect injections and episodic/GPU
   studies remain separate future protocols; this study cannot estimate power
   against all possible defects.

Exact intervals use [SciPy's binomial confidence procedure](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html).
The frequency comparison uses the conditional independent-label null described
in [SciPy's permutation-test documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html).
Analysis is descriptive unless its particular assumptions and multiplicity
scope are stated. Observed support is never claimed to be true support.

## Setup on the Study Machine

Run these commands in the **Petacat repository**, not a separate Metacat
checkout. Follow [the dependency guide](../../Metacat/README.md) for Git, Python,
and Docker. Python 3.14 is required for Petacat. No database, web server, or
Metal GPU is needed for this CPU study.

```sh
git pull --ff-only
python3.14 -m venv .venv-study
.venv-study/bin/python -m pip install -r studies/support-v1/requirements.txt
python3.14 Metacat/tools/reconstruct.py --output Metacat/build/source
docker build --platform linux/amd64 -t petacat-study-runtime:chez-9.5.4 Metacat/build/source/docker
```

The destination must not already exist. For an existing pristine reconstruction,
use `python3.14 Metacat/tools/reconstruct.py --verify Metacat/build/source`.
The original source is downloaded only into the ignored reconstruction
directory, never added to Git. Collection mounts it read-only. The runtime
container has no network access, exposed ports, or access to another checkout.
Noninteractive macOS shells may need Docker's resource directory on `PATH`
so its credential helper can run.

```sh
.venv-study/bin/python -m unittest discover -s studies/support-v1 -p 'test_*.py'
.venv-study/bin/python studies/support-v1/collect.py prepare --out studies/support-v1/output/pilot --pilot
.venv-study/bin/python studies/support-v1/collect.py run --out studies/support-v1/output/pilot
.venv-study/bin/python studies/support-v1/collect.py prepare --out studies/support-v1/output/main
.venv-study/bin/python studies/support-v1/collect.py run --out studies/support-v1/output/main
.venv-study/bin/python studies/support-v1/analyze.py studies/support-v1/output/main
```

`prepare` refuses dirty tracked files or untracked executable/source files in
the engine, seed-data, Metacat-bundle, and study directories. It records the
commit, Git tree, full file hashes, public runtime details, and installed Python
versions. It also verifies every reconstructed file and tests the headless
runtime. Public provenance omits hostnames, usernames, network addresses, and
Docker image IDs. Private operational paths are kept in ignored `local.json`.

`run` verifies that the checkout, runtime, and dependencies still match the
manifest. It acquires a single-coordinator lock and refuses changed provenance.
It stops at a phase boundary or between chunks when a `STOP` file exists in
the output directory. Remove that file and rerun the same command to resume;
do not edit the protocol, data, or manifest. Failed/incomplete chunk attempts
remain on disk and a resume launches a new attempt with the same assigned seeds.
Use a new output directory for any changed protocol or engine revision.

For a long run, keep the machine awake and supervise the command in a persistent
terminal, or use the supplied detached launcher:

```sh
.venv-study/bin/python studies/support-v1/collect.py launch --out studies/support-v1/output/main
.venv-study/bin/python studies/support-v1/collect.py status --out studies/support-v1/output/main
```

The launcher writes a supervisor log and invokes `caffeinate -i` on macOS.
`status` reports validated chunks and the last coordinator heartbeat. A launch
message is not proof of completion: only `COMPLETE.json` plus a successful
analysis establishes that every assigned run was collected and checked.

## Artifacts

Each output directory contains an immutable `manifest.json` and `protocol.json`,
ordered chunk JSONL files, checksummed completion receipts, original Scheme
TSV output, generated collector scripts, attempt logs, progress, and a completion
inventory. The analysis writes `analysis.json` and `RESULTS.md`. Failed attempts
are not included in histograms but remain auditable and are counted as attempts.
Before publishing data, remove private `local.json`, PID/lock files, and logs
with operational paths; preserve the scientific manifest, raw successful
records, failure summaries, and checksums. Do not publish the downloaded source.
The output directory is ignored to prevent accidental upload of partial data
or private logs. A release archive will be assembled after completion and review.
