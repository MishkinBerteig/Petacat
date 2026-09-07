# Completed Support-v1a Study: Results and Paper Implications

2026-09-06. These are completed single-run, fresh-memory results, not an
episodic-learning study. The post-failure amendment and its inherited observations
must remain explicit. See [provenance](STUDY-STATUS.md), the
[generated report](data/support-v1a/RESULTS.md), and
[full analysis summaries](data/support-v1a/analysis.json).

## Completion and Verification

All 969,000 assigned observations are present in 3,876 verified chunks:
380,000 reference construction, 570,000 reference validation, and 19,000
NumPy port checks. Collection completed at `2026-09-06T17:00:40.037314+00:00`;
automatic analysis completed at `2026-09-06T17:00:59.593099+00:00`.

A subsequent complete analysis rerun rechecked observation identities, chunk
artifacts, completion inventory, inheritance, and preflight evidence. Its
analysis and report hashes match the automatic run. A post-completion inventory
audit also confirms that the original interrupted study remains unchanged.
The 28 continuation and 17 original study-tool tests passed remotely. All
375 successful corrected-preflight executions remain excluded from the main
observation count; the earlier wrapper-development preflight is also preserved
and excluded. No engine repair was made.

## Main Comparisons

All columns below use the frozen 20,000-observation construction per input.
Checks contain 100 observations; there are 19 inputs. Engine errors remain
in denominators and in the execution-outcome alphabet.

| Measure | Reference validation | Port |
| --- | ---: | ---: |
| Observations | 570,000 | 19,000 |
| Check batches | 5,700 | 190 |
| Draws outside the frozen construction set | 124 | 8 |
| Batches with an out-of-set draw | 119 | 6 |
| Batches missing a selected p50 member | 0 | 0 |
| Engine-error observations | 3 | 0 |
| Frequency-test rejections at 0.05/19 | 4 | 31 |

The 124 reference out-of-set draws include the three engine errors, not 124
plus three. Sixteen of 19 inputs had at least one held-out discovery. The
three zero-discovery inputs meet the nominal per-input 95% upper limit below
1e-4 at 30,000 validation observations, but this is not a simultaneous claim
across 19 inputs. The other inputs do not meet that zero-discovery target.

The frequency comparator uses the same frozen reference and check budget.
Its null is equality of distributions, whereas the support/head diagnostic
asks different questions. The 0.05/19 threshold adjusts for inputs within a
batch, not for every repeated batch in the campaign. Reused reference samples
also make batch results dependent. These rejection counts are not calibrated
defect-detection power estimates or proof that one test dominates another.

## Port Novelty Follow-up

There are five novel input/outcome pairs across four inputs:

| Input | Outcome | Port occurrences | Held-out reference occurrences |
| --- | --- | ---: | ---: |
| misc1 | `*NONE*` | 1 | 0 |
| fig5.4-top | `qqiqq` | 1 | 5 |
| run6 | `pqqbc` | 1 | 2 |
| copy5 | `acc` | 1 | 0 |
| copy5 | `cbb` | 4 | 2 |

Thus six of the eight flagged port observations have counterparts in held-out
reference data. This is direct evidence that finite construction samples can
miss legitimate reference behavior. Validation is not merged into the frozen
set to retroactively erase those flags. The remaining `misc1/*NONE*` and
`copy5/acc` observations warrant diagnosis, but finite nonobservation does not
establish impossibility in the reference or prove a port defect.

## Reference Failures

| Input | Seed | Codelets at error | Exception signature |
| --- | ---: | ---: | --- |
| misc1 | 20713988 | 2,835 | attempt to apply non-procedure `#f` |
| misc1 | 20716342 | 1,981 | attempt to apply non-procedure `#f` |
| misc3 | 20226148 | 2,088 | `caddr`: incorrect list structure `#f` |

These are three failed executions with two observed exception signatures, not
three independently diagnosed bugs. Only the first has an inspected failing
continuation locating the missing letter-category descriptor in `make-group`.
Shared or distinct root causes for the other executions are not established.

Every failure was retained once as an engine-error observation. Following runs
started in a new process, with their original assigned seeds. The first failed
chunk matched the saved 238-row prefix and the excluded amended preflight.
An error remains a hard correctness violation even if it occurs in a reference
set. A port must not be required to reproduce reference defects.

The large reference campaign, specifically its held-out validation stage,
exposed these errors. This supports a reference-qualification case study and
the value of converting expensive exploration into targeted regression tests.
The errors were not specifically detected by Good-Turing/p50.

## Sampling Budgets

| Construction rule | Total construction observations | Held-out out-of-set draws | Port out-of-set draws |
| --- | ---: | ---: | ---: |
| Fixed 1,000/input | 19,000 | 991 | 49 |
| Fixed 5,000/input | 95,000 | 383 | 33 |
| Fixed 10,000/input | 190,000 | 229 | 16 |
| Fixed 20,000/input | 380,000 | 124 | 8 |
| Singleton heuristic | 268,500 | 135 | 9 |
| No-discovery heuristic | 81,500 | 346 | 34 |

These are ordered-prefix comparisons against shared validation and port
observations, not independent experiments, and their construction budgets
are not equal. The heuristic budgets include truncation where a rule did not
fire; consult the per-input `rule_fired` fields before calling them stopping
successes. No optimality or novel missing-mass estimator is demonstrated.

The full campaign spent 950,000 reference executions on construction plus
validation, compared with 19,000 port executions. That is a 50:1 aggregate
execution-count ratio across the ten 100-run checks per input, not a measured
speedup. Both the support diagnostic and frequency comparator reuse the same
reference investment. The recorded aggregate attempt wall time is about
466,573 seconds, including inherited attempts, the interrupted original
attempt, continuation attempts, and the successful corrected preflight. It is
not elapsed campaign time or CPU time. Earlier diagnosis, wrapper-development
preflight, setup, human effort, and analysis costs are not fully included.

## Manuscript Work Remaining

Replace the draft's future-tense independent-validation discussion with these
qualified completed results; retain the protocol amendment. Add the reference
failure case study without attributing ordinary crash detection to the
statistical heuristic. Explain the finite-reference flags and the frequency
comparator's complementary findings. Do not present the absence of missing
p50 members as evidence of distributional equivalence.

The manuscript PDF and its existing bundles have not yet been regenerated to
include this study. A separate [full raw-data release](../studies/support-v1a/data/README.md)
now supports self-contained verification and reanalysis. Manuscript integration
and the matched-cap, independently versioned episodic-memory study remain
central follow-up work for the intended TMLR submission.
