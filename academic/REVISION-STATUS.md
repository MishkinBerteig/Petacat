# Revision Status

**Publication checkpoint, 2026-09-07:** the new single-run and episodic studies
are complete; see [STUDY-STATUS.md](STUDY-STATUS.md) and the
[episodic result note](../studies/episodic-v3/results/MAIN-RESULTS.md). Their
results have not been integrated into the manuscript, PDF, or submission ZIPs.
The review assessment below is preserved as a 2026-09-06 editorial snapshot;
statements that a study or independent validation is still needed describe
that draft, not the current availability of study data. The completed episodic
study does not resolve every evidence gap: most supports failed coverage
validation or were ineligible, and a port discrepancy needs investigation.

2026-09-06. **Substantively revised draft, not yet cleared for submission.**
The current source is [manuscript.md](manuscript.md), not the historical dated
Markdown. The PDF and LaTeX are regenerated from this source and the bundled
data. This is an editorial and arithmetic revision, not a new engine experiment.

The separate [versioned study](STUDY-STATUS.md) stopped on a reproducible
reference-engine exception. An explicitly post-failure continuation preserves
the original engine and all verified completed observations, records errors
without dropping them, and keeps construction frozen. That continuation and
its analysis have now completed all 969,000 observations. The
[new results review](SUPPORT-V1A-RESULTS.md) records three reference errors,
finite-reference novelty, and the frequency comparator. The manuscript and
its bundles still require integration of these results; the learning-mode and
other evidence gaps below are not marked resolved.

The author's clarified objective is now central: **Large References, Small
Checks: Amortized Testing of Stochastic Learning Systems**. The revision adds
explicit upfront/recurring/follow-up cost accounting, reference-reuse conditions,
episode-level sampling definitions, and a main-text learning-mode case study.
Its 5:1 historical episode-count ratio is distinguished from the approximately
197:1 single-run ratio. Neither is a measured wall-clock speedup. Four primary
references on unequal sampling, covering regions, reset-trace testing, and
dependent missing mass have been verified and added.

A requested sub-agent review has further grounded the learning-mode section in
the actual implementation and existing tests: structural duplicate identity,
guards on answer acceptance, structural snag identity, reminding thresholds,
and activation resets. [EPISODIC-IMPLEMENTATION-REVIEW.md](EPISODIC-IMPLEMENTATION-REVIEW.md)
maps these claims to their evidence. It distinguishes direct search feedback
from retrospective explanation, and inspected regression definitions from
newly executed tests. Historical endpoint changes are not attributed to every
current memory repair.

## Response to the Initial Review

| Initial finding | Revision | Status |
| --- | --- | --- |
| 1. Support null and probability assumptions disagree | Reframed as an outcome-localizing diagnostic. Defines the conditional probabilities using the port law, labels reference substitutions as plug-in baselines, and provides a same-support counterexample. | Corrected in the claims; no calibrated unrestricted support test claimed. |
| 2. Missing-mass estimate treated as a bound | Stopping explicitly heuristic; selection and optional-stopping uncertainty stated. Includes the two-outcome floor counterexample and an independent fixed-size validation design. | Corrected interpretation; independent calibration not performed. |
| 3. False-negative terminology and no-flag conclusions | Absence is a possible false-positive discrepancy flag under a matched-law null. Separates individual and cycle quantities and gives rare-defect detection probabilities. No flags imply observed reachability only. | Corrected. |
| 4. TMLR relevance and empirical comparisons | Centers amortized implementation testing; adds archived learning-mode results, independent-episode formalism, and qualified cost accounting alongside the synthetic binomial example. | Partly addressed. Matched-cap learning replication, memory controls, and empirical reusable-reference comparisons remain open. |
| 5. Provenance and 35-outcome example | Withdraws the unreconstructible example. Bundles unchanged aggregate data and recomputes head sets locally. Links source availability to the new patch bundle while distinguishing it from historical build attribution. | Data arithmetic reproducible; sampled-build and historical intervention provenance still incomplete. |
| 6. Recurrence proves invalidity | Recurrence is a prioritization marker only; same-seed cycles are paired replay, not independent replication. Corrected the corresponding harness docstring, without changing behavior. | Corrected. |
| 7. Novelty counting unit and notation | Distinguishes novel draws, flagged inputs, distinct pairs, and any-novelty probability; uses N_x/n_x/J consistently and removes the unjustified 0.19 bound. | Corrected. |
| 8. p50 members automatically common | States a uniform-support counterexample, lexicographic ties, head-selection uncertainty, and the exact-boundary example. | Corrected. |
| 9. Implementation and cost qualifications | Six zero-singleton inputs, actual seed block, replay assumptions, archived MLX distinction, stored stop reasons, and run-count rather than timing claims. | Corrected. |
| 10. Presentation and submission | Single-paragraph abstract, conventional structure, author-year citations, anonymous byline/metadata, complete appendices, shorter development narrative, no identifying repository URL in the manuscript. | Format addressed; final author/anonymity review remains. |

Two further corrections emerged during revision:

- The post-repair check schedules 1,900 initial runs **plus 23 cap-resolution
  reruns**, for 1,923 execution attempts. The 197.105 ratio compares the
  reference count with initial checks only, not all execution cost.
- The recorded Scheme defect injection reproduced `cdddb` and `*NONE*`, not
  all three CPU findings attributed to the defect. The `abbbb` claim now refers
  specifically to the Python trace and repair intervention. Historical tests
  are not represented as independently repeated in this revision.

## Evidence Still Needed

1. **Identify the historically sampled builds, or run a new versioned study.**
   Archive exact reference and port revisions, applied patches, parameter data,
   dependencies, caps, seed mappings, and ordered outcomes. Current source
   availability and a correct count checksum cannot establish past execution.
2. **Independently validate the frozen reference.** Reserve fresh reference
   seed blocks, separate from construction and debugging, and compare their
   empirical flag rates with explicitly assumed baselines. Predeclare check
   sizes and confidence procedures. The 29,956-draw example in the paper is
   a proposed per-input fixed-size zero-discovery validation budget, not a
   sample we have collected or a guarantee across all 19 inputs.
3. **Evaluate the comparisons under equal budgets.** Fixed-budget and
   no-discovery reference construction require ordered runs. Compare the
   diagnostic with a specified frequency-sensitive procedure and known defect
   injections; report detection power, uncertainty, and actual runtime.
4. **Repeat or archive the defect interventions.** The saved discrepancy
   report and unit tests are useful evidence, but the historical instrumented
   Scheme builds and detailed raw traces are not in the analysis supplement.
5. **Complete a separately versioned learning-mode study.** Use independent
   reset episodes, identical reference/port caps, total outcome projections,
   memory-on/off and known-memory-defect controls, and fresh validation blocks.
   The archived episodic reference is not in the supplement. Stored novel
   endpoints decreased while capped runs increased; neither alone establishes
   learning fidelity or better learning. The live single-run study cannot
   resolve these issues.
6. **Complete author-controlled submission checks.** Confirm the intended
   contribution, all empirical claims, authorship, OpenReview profiles,
   conflicts, disclosures, quota eligibility, and anonymity of every upload.
   The public repository itself is not anonymous.

The first five items are recommended to strengthen the evidence and support
the intended paper, not claims that TMLR mandates a particular experiment or
a second case study. They cannot be resolved by copy-editing. A narrower
retrospective report remains possible, but its acceptance and scope are editorial
judgments, not assured by using the template.

## Completed Checks

- Recomputed all stored counts, selected heads, flag lists, plug-in summaries,
  cap-rerun totals, and analytic examples from repository-local data.
- Fourteen arithmetic tests pass, including five episode-audit tests. The
  earlier 14 Metacat packaging tests also passed.
- The comparison-harness and direction-image suites pass: 23 CPU tests. The
  test process reported a Metal-device-unavailable message at shutdown in the
  restricted environment; no GPU execution is claimed.
- No fresh engine results were invented or incorporated. All 31 original
  references remain real and cited, alongside four newly verified references.
- PDF and bundle verification is recorded separately in [BUILD-CHECKS.md](BUILD-CHECKS.md).

The [TMLR author guide](https://jmlr.org/tmlr/author-guide.html) requires an
anonymous TMLR-style PDF and anonymous PDF/ZIP supplementary material, with a
100 MB supplementary limit. Its [acceptance criteria](https://jmlr.org/tmlr/acceptance-criteria.html)
focus on supported findings and interest to the readership. Recheck the
[editorial policies](https://jmlr.org/tmlr/editorial-policies.html) before upload.
No submission has been made.
