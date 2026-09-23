# Versioned Study Status

Updated 2026-09-07. **Both the single-run continuation and the episodic v3
study are complete. Episodic coverage and the misc3 port-discrepancy case study
are integrated under approved Issues 1 and 2. Approved Issue 3 integrates the
single-run study while keeping the historical port-improvement workflow central.
Approved Issue 4 adds the all-19-input episodic port comparison and termination
accounting, with descriptive frequencies for construction-limited problems.
Approved Issue 5 packages both studies for review, with recorded exclusions
and a clean-copy saved-data verification workflow.**
This document is a snapshot, not a live progress monitor.

## Episodic Final Status

The [episodic v3 result note](../studies/episodic-v3/results/MAIN-RESULTS.md)
links its public oracle, observations, protocol, source fingerprints, seeds,
curves, and verification record. It completed 25974 episodes with 207791
actual inner runs: 10074 construction episodes including 4000 reused pilot
episodes, 14000 validation episodes, and 1900 port episodes.

Fourteen problems qualified for validation; five hit the construction cap
and received only descriptive port comparisons. Only `copy1`, `copy2`, and
`copy3` meet the coverage target for both definitions. Eight of 28 tested
individual populations meet it, with confidence correction across all 38
predeclared populations. Immediate zero-singleton freezing frequently yielded
incomplete supports, which held-out validation exposed.

For the individually validated `misc3 best_a` support, the port produced
24/100 outside winners, compared with 0/1000 in reference validation. This
warranted the now-completed [saved-data and code investigation](investigations/MISC3-EPISODIC.md),
not an automatic bug verdict. Two static rule-generalization differences were
identified, but the saved records do not establish their event-level causal
contributions. The approved manuscript treatment reports the full frequencies
and distinguishes diagnostic partitions from root causes. No engine was modified
and no additional validation batch was added after inspecting the result.
There were no new engine-error episodes; the preserved pilot error remains
in construction. All public statistics reproduce without running an engine.
The full private raw archive remains ignored and is not part of the public
release. The current manuscript reports failed and skipped validation alongside
successes and the unresolved port discrepancy; further issues require separate
author approval.

The complete manuscript comparison reports eight coverage-qualified populations:
`misc3 best_a` has 24/100 outside port winners and the other seven have zero.
Unqualified frozen supports still have descriptive memberships; missing frozen
supports are not reported as zero misses. Four entirely answerless `copy5` port
episodes leave 96 winners per population. The new
[saved-data audit](episodic-study-audit.json) includes all 38 construction/port
frequency vectors, five capped problems' descriptive summaries, and disjoint
inner-run accounting. It does not change frozen data or execute either engine.

## Single-Run Final Status

The continuation completed all 969,000 observations in 3,876 verified chunks
at `2026-09-06T17:00:40.037314+00:00`. Automatic analysis finished at
`2026-09-06T17:00:59.593099+00:00`. There are three reference engine errors
and no port engine errors. No assigned seed was omitted or replaced.

A full post-completion analysis rerun reproduced the analysis and report
hashes, and a separate inventory audit confirmed that the original interrupted
study's files remain unchanged. Monitoring ended after completion was verified.
See [results and paper implications](SUPPORT-V1A-RESULTS.md) and the
[local result-summary export](data/support-v1a/README.md). The manuscript,
PDF, and LaTeX source bundle now include this study in Section 7 and Appendix C.
The historical arithmetic ZIP remains separate and unchanged; anonymous
packaging is now supplied in the separate experimental review ZIP. Its original
scientific archives and executable source retain their recorded hashes; the
manifest documents review-specific documentation and licensing-display changes.

Completion inventory SHA-256:

```text
3abfc9771de43120cf75772a03d5fb24b8bfd949d47923cef09d283913036eec
```

Analysis SHA-256:

```text
26ff98e0ca39eeddb8eec2b85186bd235682048625bb07cd8bf4a8bb65fd8128
```

Generated report SHA-256:

```text
c8ea18ba97410dcfea430607ffc81f813577be187cf7a32839b9051a2f1959c3
```

## Failure and Continuation

The original `support-v1` worker failed at `2026-09-06T06:10:11.861766+00:00`
on `misc1` (`abc -> cba; mrrjjj -> ?`), seed `20713988`, with
`attempt to apply non-procedure #f`. Fresh-process diagnostic replay reproduced
the failure. In `make-group`, the initial letter-category descriptor was `#f`
when receiving `get-uppercase-name`. The relevant `groups.ss` file is identical
to upstream, but the cause of the missing descriptor and whether other patches
make the path reachable remain unresolved. This is an engine defect on an
allowed input, not an invalid sample.

There are 643,250 completed parent observations: 380,000 construction and
263,250 validation, with no port observations. The interrupted 250-run chunk
also preserves 238 successful raw rows. The coordinator stopped dispatching,
but its old heartbeat and counters remained stale while in-flight work drained;
its final failed-state timestamp is `2026-09-06T06:29:03.357082+00:00`.

The approved [support-v1a amendment](../studies/support-v1a/README.md) retains
the original engines, runtime, inputs, caps, seeds, and total budget. A separate
checkout obtained from GitHub keeps the original checkout and output untouched.
Preparation fully rehashed the parent files and completed receipts, copied
verified chunks with unchanged receipts, and preserved the incomplete attempt
separately. The parent inventory matched before and after import.

The amended wrapper records engine errors as `*ERROR*`, exits that process,
and starts the next assigned seed cleanly. Infrastructure and unclassified
failures still halt collection. The failed chunk is replayed with its original
seeds; its first 238 results must match the saved prefix. Each seed contributes
only one admitted observation. Errors remain in denominators and separately
trigger hard-error flags; the port is not required to reproduce reference bugs.
Construction stays frozen and does not absorb validation discoveries.

This is a post-failure amendment, not an unchanged prospective experiment.
The expensive campaign's reference-defect discovery is useful evidence about
reference qualification, not a result specifically attributable to Good-Turing
or p50. It does not replace the separate learning-mode study.

The first continuation preflight at `19b91b6` found a wrapper-output bug:
Metacat shadows the standard `newline` procedure with a zero-argument helper.
That preflight was stopped and preserved in `studies/support-v1a/output/main/`;
no main continuation observations were collected. Revision `e5f7e79` uses
the original collector's `write-char` operation. Its separate prepared output
is `studies/support-v1a/output/main-02/`. All 28 continuation unit tests and
17 original study-tool tests passed remotely; no tests were skipped there.
Wrapper-development/preflight failures are distinct from the original engine
defect. Earlier setup and diagnosis costs are not fully included in the main
analysis's execution-time accounting.

## Continuation Launch Record

- Frozen continuation revision: `e5f7e79a3447616909274ba078b27e3486ddf73b`.
- Corrected preflight completed: `2026-09-06T12:59:57.649044+00:00`.
- All 114 prefix/interior compatibility observations matched across 19 inputs.
- All 238 saved pre-crash observations matched; the known error reproduced at
  seed `20713988` with a recorded codelet count of 2,835.
- All 11 post-error suffix observations matched separate fresh-process runs.
- These 375 preflight executions are excluded from the 969,000 main observations.
- A separate post-preflight audit found the original parent file inventory
  unchanged, including the failed attempt and logs.
- Main continuation started: `2026-09-06T13:00:24.749601+00:00`.
- Initial running heartbeat: `2026-09-06T13:00:38.979517+00:00`; 12 active
  workers, 643,250 inherited completed observations, validation phase.
- The previously interrupted chunk completed in the main continuation at
  `2026-09-06T13:01:10.346389+00:00`: 238 ordinary observations, the recorded
  engine error, then 11 observations in a fresh process. Its 250 admitted
  observations matched the excluded preflight replay; the saved parent prefix
  also matched. Neither the error nor its seed was skipped.
- Monitoring interval: 900 seconds. Progress counts alone are not a completed
  analysis or a freshly repeated checksum audit.

At the `2026-09-06T13:30:58.198605+00:00` heartbeat, 696,250 observations
were complete and 12 workers remained active. A second admitted engine-error
observation occurred on `misc1`, seed `20716342`, at 1,981 codelets, with the
same non-procedure-`#f` exception signature. This does not by itself establish
the same internal root cause. Its chunk completed under the amended policy.
These are interim execution observations, not a completed failure-rate estimate.

At the `2026-09-06T16:01:42.375017+00:00` heartbeat, 915,250 observations
were complete. A third admitted engine error occurred on `misc3`
(`abc -> aabbcc; kkjjii -> ?`), seed `20226148`, at 2,088 codelets:
`caddr: incorrect list structure #f`. Its chunk completed after a clean
post-error restart. This is a different exception signature; the root cause
has not been traced and independence from the other failure is not established.

Continuation manifest SHA-256:

```text
948e361edd6fad6fa9f84cae8d15895a6a9075599aa605d507ae46f60c50f217
```

Materialized amended protocol SHA-256:

```text
7fcad7a070165571f1f715f8f534e498edd8b516671b4e8e20e1f5a5863f6bcf
```

Verified parent-import record SHA-256:

```text
3ab6829d6011a8bd7ce9d38d7ea708c7fefdae0f9eba8fbea9955a1e7cfb40c0
```

Passed preflight record SHA-256:

```text
5b3175874d7c1f0983dd2f0eb73fa3d8d38a207e0a128eb83514327d9ed09c17
```

## Original Launch Record

The [versioned protocol and tools](../studies/support-v1/README.md) were committed
and pushed before main collection. Execution uses a clean Petacat checkout and
Metacat reconstructed inside that checkout from the committed patch bundle.
It does not use a separate modified-Metacat working directory. All engine runs
take place on the designated remote study machine.

- Main source revision: `1d7f9f19f2e28b634e9c40c5b04b24cdb71baf26`.
- Main collection started: `2026-09-05T22:54:26.710138+00:00`.
- Inputs: the 19 fixed problems in `studies/support-v1/protocol.json`.
- Planned main runs: 380,000 construction, 570,000 held-out validation, and
  19,000 Petacat checks, totaling 969,000.
- Runtime: Chez Scheme 9.5.4 under Linux/amd64 emulation for the reference;
  Python 3.14.6 with NumPy 2.5.1 for the serial CPU port. No GPU run is claimed.
- Analysis: SciPy 1.18.1 and the committed analysis code, run automatically
  after all assigned chunks and checksums pass validation.
- Execution: 12 workers, direct 100,000-codelet cap, fresh episodic memory,
  disjoint seed blocks, ordered records, checksummed chunk receipts, and
  retained failed/incomplete attempts.

The 570-run excluded pilot completed at revision
`cd6d853238cede6dfa954ca6e3406206d9a9ca88`. Its full receipt inventory and all
records passed verification. Main-study budgets and seed assignments were
already committed before that pilot. The subsequent commit added automatic
analysis supervision and more tests, not engine or protocol changes.

Verification before main launch: 17 study-tool tests, 14 reconstruction tests,
and 23 targeted CPU tests passed remotely. The CPU pytest invocation reported
an unused `asyncio_mode` configuration warning because the isolated study
environment omits the web application's async test plugin. No failed test or
GPU execution is hidden by that warning.

## Checksums

Main manifest:

```text
8c497eeb7d9425bce436f22bc9c5fdb95fcbba779048af95daa87625d4e4b820
```

Protocol:

```text
8358d32c1fb85029f458631ac8bb0498e34da272753470f61f042fc32f42505c
```

Pilot manifest:

```text
d7911b3ad9282993292c17dc4ca238e239f117166a7ab2acf9db8fd2dda77ccc
```

Pilot completion inventory:

```text
b277e5a9f64ea63fc222a0d5236f392870cc3da373332bc2d0b7c6b5551c53f1
```

## Completion Criteria

The original output remains at `studies/support-v1/output/main/` in its frozen
checkout. It is interrupted, not complete. Use the continuation checkout and
its `studies/support-v1a/output/main-02/` output for subsequent collection and
status checks. Keep both checkouts at their recorded revisions; do not pull
changes into the active continuation checkout while collection runs.

Collection is complete only when `COMPLETE.json` inventories every assigned
chunk and a full checksum/identity check succeeds. Analysis is complete only
when `analysis-status.json` reports success and `analysis.json` and `RESULTS.md`
are present with their recorded hashes. A launch, heartbeat, or partial
histogram is not a completed experiment. The output directory is ignored by
Git; an audited release archive and manuscript changes follow completion.

This study addresses version attribution, held-out calibration, ordered
construction comparisons, and a frequency-sensitive comparator. It does not
reproduce historical defect interventions, test episodic learning or GPU
execution, or establish power against arbitrary defects. It cannot by itself
guarantee TMLR acceptance or prove equality of true supports.
