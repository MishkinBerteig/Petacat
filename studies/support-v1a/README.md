# Crash-Aware Continuation of the Support Study

`support-v1a` is an explicitly post-failure amendment of
[support-v1](../support-v1/README.md), not a new untouched prospective experiment.
The original Metacat and Petacat engines, runtime, inputs, assigned seeds,
100,000-codelet limit, 12 workers, and 969,000-observation budget are unchanged.
No engine repair is included. This study still uses fresh memory, not episodes.

The completed [full scientific-data release](data/README.md) includes all
969,000 main observations, the interrupted parent, the excluded pilot, and
both preflight attempts. It can be verified and reanalyzed without running
Metacat. The [failure investigation note](../../Metacat/KNOWN-FAILURES.md)
records standalone reproducers for the three reference errors.

## Why an Amendment Is Necessary

The parent study stopped after a reproducible Metacat exception on `misc1`:
`abc -> cba; mrrjjj -> ?`, seed `20713988`. The immediate exception was
`attempt to apply non-procedure #f`. A fresh-process replay reproduced it.
Debugger inspection located a missing initial letter-category descriptor in
group construction; the root cause and contribution of other reconstruction
patches are not established. The `groups.ss` file itself matches the upstream
tarball. This is a defect in the tested reference system on an allowed input,
not an invalid observation and not proof that an unmodified upstream runtime
has the same failure.

The parent has 643,250 completed observations (380,000 construction and 263,250
validation), plus 238 saved successful rows in its interrupted 250-run chunk.
The crash occurred during held-out validation, not construction. The original
protocol correctly halted instead of silently dropping it. Neither the failed
study nor its receipts are rewritten to mark it complete.

## Data and Failure Policy

- Hash every parent file, verify every completed chunk and its artifacts, and
  copy completed chunks with byte-identical receipts into a separate output.
- Preserve incomplete attempts separately. Replay the interrupted chunk with
  its original seeds. Require its saved successful prefix to match exactly in
  identity, answer, codelet count, and termination. Timing need not match.
- Admit one observation per assigned phase/input/index/seed. Replays and
  preflight checks cost execution time but do not add independent observations.
- Record an in-engine assertion/error as `*ERROR*`, with stage, exception
  evidence, elapsed time, and codelet count when known. Exit the process after
  recording it and start a clean process at the next assigned seed. Never retry
  a seed until success or substitute a different seed.
- Scheme I/O and implementation-restriction conditions, Python OSError,
  MemoryError, and ImportError, container failures, startup errors, unexpected
  exits, malformed records, and operational timeouts still stop collection.
  Unclassified failures require diagnosis and, if necessary, another explicit
  amendment. They are not automatically labeled engine defects.
- Continue publishing heartbeat and completed counts while already running
  workers drain after an operational failure. Do not dispatch more work then.

The Scheme wrapper uses standard [exception guards](https://www.scheme.com/tspl4/exceptions.html).
It does not modify Metacat source. A guard is not permission to resume an engine
after an exception; the process is terminated. Successful execution follows the
same initialization, cap, answer extraction, and random-seed rules as v1.

## Analysis

The construction set stays frozen. Validation observations, including errors,
are never added to it to erase novelty. The original full budgets and fixed
100-observation checks remain the denominators. All original prefix, singleton,
no-discovery, and frequency-sensitive comparisons are retained over an expanded
execution-outcome alphabet containing `*ERROR*`.

Report errors separately by input and phase, including exact reproducer seeds.
Every error triggers a hard-error flag independently of support membership.
An empirical reference describes observed behavior; it is not a specification
of acceptable behavior, and the port must not be required to reproduce crashes.
No answer-only analysis silently excludes errors. An error-free corrected
engine would require separately versioned reference data, not a mixture of
pre-repair and post-repair executions.

The outcome policy was amended after seeing the failure. Label it accordingly;
do not describe all analyses as prespecified before data collection. Nominal
binomial limits retain their fixed-law independent-sampling assumptions and
multiplicity qualifications. Do not estimate a general failure probability by
pooling this interrupted, heterogeneous collection. No defect-detection power
or beneficial learning claim follows from this single counterexample.

Cost accounting includes inherited completed attempts once, the interrupted
parent attempt, continuation attempts, and excluded preflight executions.
Aggregate worker execution time is not elapsed campaign time or CPU time.
Earlier interactive diagnosis and human effort are not fully measured.

## Setup and Execution

Use the [dependency instructions](../../Metacat/README.md) and the parent's
[study setup](../support-v1/README.md). This continuation requires the exact
parent study specified in [amendment.json](amendment.json), its unchanged
Python environment, its pinned container runtime, and its verified reconstructed
Metacat source. The scripts reject changed parent hashes or changed engine files.
No original Metacat source is bundled in this repository.

Keep the original study checkout and output untouched. Clone Petacat into a
separate directory on the study machine and obtain the committed continuation
from GitHub. Do not run these experiments on a second/local machine.

```sh
git clone https://github.com/MishkinBerteig/Petacat.git Petacat-support-v1a
cd Petacat-support-v1a
git pull --ff-only

# Replace these two paths with the preserved parent checkout and output paths.
PYTHON=/path/to/original/Petacat/.venv-study/bin/python
PARENT=/path/to/original/Petacat/studies/support-v1/output/main
OUT=studies/support-v1a/output/main

"$PYTHON" -m unittest discover -s studies/support-v1a -p 'test_*.py'
"$PYTHON" studies/support-v1a/collect.py prepare --parent "$PARENT" --out "$OUT"
"$PYTHON" studies/support-v1a/collect.py preflight --out "$OUT"
"$PYTHON" studies/support-v1a/collect.py audit-parent --out "$OUT"
"$PYTHON" studies/support-v1a/collect.py launch --out "$OUT"
"$PYTHON" studies/support-v1a/collect.py status --out "$OUT"
```

Preparation reuses the parent's verified source as a read-only container mount;
it neither rebuilds nor patches the engine. It hashes the original study before
and after import to detect modifications. An interrupted import must be
investigated; never overwrite an existing output directory.

Preflight compares three prefix and three interior observations against the
saved first construction chunk for each of 19 inputs. Interior runs start in
a fresh process, checking reset behavior. It also replays the entire known
failed chunk, verifies its saved prefix and error seed, and compares each of
the 11 post-error observations with a separate fresh-process execution. These
375 executions are excluded from main-study observations. Passing these checks
is evidence of compatibility, not proof for every possible trajectory.

The main run replays the failed chunk separately, cross-checks its prefix, and
completes remaining seeds. A `STOP` file in the continuation output stops new
dispatch while current chunks finish. To resume after removing that file, run
`launch` again. Keep the continuation checkout frozen at its manifest commit.

Completion requires `COMPLETE.json`, all verified receipts, and successful
`analysis-status.json`. To repeat the independent data analysis:

```sh
"$PYTHON" studies/support-v1a/analyze.py "$OUT"
"$PYTHON" studies/support-v1a/collect.py audit-parent --out "$OUT"
```

## Publication

Operational outputs remain ignored by Git. The [published archives](data/README.md)
omit private configuration, launcher/lock files, and supervisor logs while
preserving all scientific files byte-for-byte, including per-attempt logs and
original checksums. Archive ownership metadata is normalized. Clean-room
extraction and reanalysis reproduce the original results. Future exports must
retain this privacy and integrity boundary; the original upstream source must
not be added to this patch-only repository.

For the paper, describe the failure as a reference-qualification case study:
expensive exploration yielded a reproducible reference defect and a cheap
targeted regression test. Execution revealed the crash; Good-Turing/p50 did
not specifically detect it. This does not replace the separate episodic
learning evaluation needed for the intended submission.
