# Manuscript review for TMLR

Reviewed 2026-09-05. **Recommendation: revise before submitting.** The engineering case study is useful, the main stored totals agree with the manuscript, and all 31 references identify real works. The central statistical interpretation, however, is not supported as written. Formatting alone does not resolve that issue.

This is the **initial review record**, referring to the historical Markdown's
section numbers and line numbers before its superseded-draft notice was added.
The manuscript at repository revision `a4046b8` preserves that reviewed text.
The current [revised manuscript](manuscript.md) and LaTeX/PDF now correct many
of these claims. See [REVISION-STATUS.md](REVISION-STATUS.md) for resolutions
and remaining evidence gaps; do not read the findings below as a status report
on the revised prose.

## Findings

### 1. Major: the null hypothesis and the calibration assumptions disagree

**Original: lines 14-20, 79-80, 133-137, 145-149, 193-195, 289-301.**

The paper declares the null to be equality of supports and explicitly allows probability reweighting. Neither error formula is calibrated for that null. Let S_N be the observed reference set, p_R(o) the reference probability, and p_P(o) the port probability. Conditional on the frozen reference sample, the head absence probability is `(1 - p_P(o))^n`, and the probability of any apparent novelty is `1 - (1 - q_P)^n`, where `q_P = sum_{o outside S_N} p_P(o)`. The reference estimates p_R and its own missing mass, not p_P or q_P.

For example, an outcome can retain positive probability 0.001 in the port after having reference probability 0.1947. The supports remain identical, but it is absent from 100 port runs with probability **0.90479**, not approximately 4e-10. Similarly, arbitrarily much port mass may move to outcomes absent from S_N without changing the true support. Independence alone does not repair either problem.

**Revision:** describe the oracle as a support-oriented diagnostic, and label the numbers as plug-in reference-distribution baselines. Alternatively, state and justify quantitative restrictions on probability drift that make bounds transferable. Do not present the current formulas as a calibrated test of unrestricted support equality.

### 2. Major: a missing-mass estimate is treated as a certified bound, including after optional stopping

**Original: lines 40, 46, 54, 159-175, 223-225, 289-301, 351-355.**

`f1/N` is an estimator, not an upper confidence limit. Stopping when that estimator crosses a threshold does not itself establish that the true missing mass is below the threshold. The cited [McAllester and Schapire paper](https://www.learningtheory.org/colt2000/papers/McAllesterSchapire.pdf) adds a confidence-dependent error term to the estimate for an independent sample of fixed size. No corresponding term, confidence level, or treatment of repeated looks appears here. At N around 10,000-50,000, a generic square-root finite-sample term cannot simply be ignored relative to a target of 1e-4.

The zero-singleton floor is a practical guard, not a distribution-free certificate. Consider two outcomes with probabilities 0.9998 and 0.0002. At N=10,000, the probability of seeing only the first outcome is **0.13531**. Then `f1=0` and the floor is met, but the true missing mass is twice the target. A zero estimate therefore does not establish zero novelty risk. Also, `f1=1` at `N=1/tau_upper` is accepted by the stated upper-threshold rule, contrary to the rationale at line 175.

**Revision:** explicitly call the stopping criterion heuristic and the estimates uncertain. Strong guarantees require a valid confidence procedure accounting for the stopping rule, or an independently sampled validation stage. The current data can still support an engineering report if its claims are reduced.

### 3. Major: false-negative terminology and conclusions from no flags are incorrect

**Original: lines 20, 195, 223, 265-285, 335-336, 364, 370.**

When a still-reachable head outcome is absent by chance and triggers MISSING, that is a **false-positive divergence flag** under a rate-matched null. It is not a false negative. If the outcome really has probability zero, it will be absent with certainty; the quoted 4e-10 is not the power to detect its loss. Detecting novel erroneous mass epsilon instead has miss probability `(1-epsilon)^n`, which is not evaluated in the paper.

The 3.94e-10 figure concerns the least-frequent individual head member. The sum of the 27 member-specific plug-in absence probabilities is **6.1339841e-10**, a cycle-level union bound under the stronger reference-distribution assumption. The looser bound `27 * max(absence)` is about 1.06e-8. Neither includes uncertainty in the reference shares or sequential selection.

Observing every head member once does not show broadly comparable rates. The paper's own 85%-to-20% example makes that clear. **Revision:** replace the terminology throughout, distinguish member-level from cycle-level calculations, and restrict the no-flag conclusion to observed reachability of the selected head outcomes.

### 4. Major: TMLR relevance and empirical validation need a clearer argument

**Original: lines 86, 145-151, 317-325, 370-391, 409, 425.**

The present contribution is predominantly a software-testing experience report about an analogy architecture. Episodic-memory behavior is excluded from the reported experiment. A connection to machine learning is plausible through reproducibility of cognitive or probabilistic systems, but must be developed: name the scientific question, explain what researchers learn beyond this port, and show the relevance to learning systems. Assertions that distributional alternatives are necessarily expensive or uninterpretable need a specified test, effect size, power target, and comparison. The current report offers none.

TMLR's [scope](https://jmlr.org/tmlr/editorial-policies.html) includes reproducibility studies and applications that illuminate intelligent learning systems. Its [acceptance criteria](https://jmlr.org/tmlr/acceptance-criteria.html) emphasize supported claims and clear findings of interest; a novel algorithm or state-of-the-art result is not required. A single case study is not automatically disqualifying. The present general claims nevertheless outrun the evidence.

**Revision:** retain the strong defect-intervention example, narrow the transfer claims, add comparisons with fixed-budget/no-discovery stopping and an appropriate frequency-based test, and calibrate flags on independent unchanged-reference checks. A second learning-related case study would strengthen suitability, but it is not a formal submission requirement. This is an editorial assessment, not a prediction of an editor's decision.

### 5. Major: reference provenance and the 35-outcome example cannot be reconstructed

**Original: lines 50, 175-177, 321-325, 343, 501-516.**

The no-new-outcome example claims 35 outcomes for `abc -> abd; xyz -> ?`; the final reference table and stored `run4` counts contain **10**. These may be different builds, caps, modes, or earlier samples. That distinction and the underlying ordered observations are not supplied. The sibling `Metacat/oracle/raw/single-runs.json` contains aggregated counts and histograms, not an ordered record from which the quoted inter-discovery gaps can be recomputed. `check_saturation.py` computes subsample trends; it does not reconstruct the six ordered gaps claimed in the paper.

The reference was locally modified. `../Metacat/CODE-FIXES.md` records changes with substantial measured distribution effects. The paper acknowledges changes but does not pin the exact sampled build, patch set, configuration, or container digest. The current sibling checkout is `46a479b7a6646f3c335be449bc1a43b9a5f87c68`; that is an audit locator, not proof it generated the archived sample.

Appendix A's original Petacat GitHub URL does not contain the sibling Metacat tree. The local Metacat checkout has no configured remote. **Revision:** supply an anonymized artifact bundle containing the actual sampled reference, its changes from upstream, commands, raw data, and hashes; identify the sample used for the 35-outcome example or withdraw that example. Do not describe aggregate counts as an ordered per-run trace.

### 6. Moderate: recurring novelty is not proof of an invalid outcome

**Original: line 391; also `scripts/compare_to_metacat.py:242`.**

An outcome omitted from a finite reference sample can recur in independent checks while still belonging to the reference distribution. Furthermore, the saved cycles reuse the same starting seed, 900,000. Repetition on unchanged code with the same seeds is replay, not independent confirmation. Even changes of implementation can leave outcomes correlated across reused seeds.

**Revision:** retain recurrence as a prioritization aid; remove the categorical claim that a recurring outcome cannot be missing mass. Use fresh seed blocks for an independent recurrence study and evaluate its probability under an explicit model. The code's explanatory comment repeats the paper's erroneous interpretation; no application code was changed during this review.

### 7. Moderate: the counting unit for the novelty budget is ambiguous

**Original: lines 163-167, 289-301, 355, 423.**

`n * M0` is the expected number of draws outside a frozen observed reference set. `1-(1-M0)^n` is the probability that a problem gets at least one such draw. The harness emits distinct novel outcomes per problem. Their expected count is `sum_{o outside S_N} [1-(1-p(o))^n]`, which is bounded above by `n*M0` but is not generally equal to it.

From the stored ratios, the plug-in expectations are **0.1694851 novel draws** and **0.1678980 flagged problems** per cycle. The plug-in probability of any novelty is **0.1559143**, assuming independent checks across problems. The numerical approximations are close here; the definitions still matter. The bound `19*100*tau=0.19` applies to estimates only when every problem meets the target, whereas three do not. Their actual sum happens to remain below 0.19.

**Revision:** define the counting unit and present each number as an estimate under the stronger assumptions. Do not call 0.19 an established bound on this partially unsaturated reference's true risk.

The notation also needs repair: the reference sample is called N in Section 3.6 and Appendix B, but n elsewhere. Section 4.2 writes `n * f1/n` while intending check size times the reference missing-mass estimate. Use `N_x` for the reference size, `n_x` for the check size, and a separate symbol for the number of problems instead of reusing P, which already denotes the program under test.

### 8. Moderate: coverage of half the mass does not make every head member common

**Original: lines 187-191, 273-281.**

For a uniform distribution over K outcomes, a p50 member has probability 1/K, which can be arbitrarily small. A finite uniform distribution is usable if the sample budget is large enough; it is not intrinsically excluded. The favorable sample size comes from the measured minimum share in this benchmark, not the p50 definition itself. `copy5` also sits exactly on the empirical 0.5 boundary, so the selected head need not be stable under resampling.

**Revision:** give the measurable condition on the minimum selected probability, state tie handling and head-selection uncertainty, and remove the categorical exclusion of uniform finite supports. Distinguish an observed support from the unknown true support throughout.

### 9. Moderate: several implementation and cost statements need qualification

**Original: lines 181, 254-257, 355, 364-366, 415-419.**

- The stated 1,000,000 seed offset differs from the saved 900,000 start and the harness default. Corrected in the formatted draft.
- There are **six**, not eight, zero-singleton problems. Corrected in the formatted draft.
- Independent sessions remove memory carryover; they do not prove independence of pseudorandom streams or stationarity. State these as modeling assumptions.
- Re-running a capped seed reproduces a trajectory only if the implementation, configuration, and backend are deterministic for that seed, and the larger cap does not alter earlier transitions. Independence between sessions alone is insufficient.
- A shard count K does not establish wall time N/K without per-run cost and scheduling overhead. The 197.105 ratio is a run-count ratio, not a measured speedup between different implementations.
- The archived CPU post-repair cycle has one novelty; the archived MLX cycle still has five. Both have zero missing head members. The latter supports the narrow no-missing observation but does not demonstrate post-repair GPU equivalence.
- Repeated reference outcomes establish a lower bound on reachable outcomes. A countably infinite, nonuniform outcome space need not keep missing mass above every threshold forever. Failure to meet a target under a finite budget is not diagnostic of outcome granularity alone.

### 10. Presentation and submission issues

**Original: lines 5-6, 10-20, 24, 257, 429-431, 435-497, 503, 533-535.**

The original has an author byline, identifying repository URL, acknowledgements, a four-paragraph abstract, an unusual section 0, numeric references, an unresolved `[UNCLEAR:]` note, and an empty Appendix C. The official template requests a one-paragraph abstract, author-year citations, an alphabetical bibliography, and omission of acknowledgements during anonymous review. The conversion addresses these formatting issues and fills Appendix C from verified stored outcomes. All tables are captioned. Section references now follow automatic numbering.

The abstract remains unusually long and the development narrative repeats the method. For revision, compress the abstract and Background, replace conversational claims such as "confident nonsense" with evidence, and separate observed results from conjectured generality. Project naming and supplementary materials still need an author-level anonymity check.

## Reference audit

**31 of 31 works verified as real; no fabricated work found.** See [REFERENCE-AUDIT.md](REFERENCE-AUDIT.md) for a per-entry record and primary-source links. Publication years were checked against issue dates where online-first dates differ. Citation existence does not establish that each cited work supports the surrounding assertion. In particular:

- McAllester and Schapire [10] do not supply the paper's claimed certificate for optional stopping on the raw estimate.
- Orlitsky, Suresh, and Wu [29] study optimal extrapolation of the number of newly discovered species. That result is not a proof that this stopping rule or support test is optimal.
- The adaptive estimators in Böhme and colleagues [13,14] are tied to their sampling settings, not a general correction for arbitrary adaptive port-comparison samples.
- The replication standards discussed with [20] are traced there to Axtell and colleagues [19]; avoid suggesting their origin is the later paper.

## Submission requirements and remaining work

The [official author guide](https://jmlr.org/tmlr/author-guide.html) requires an anonymized PDF generated with the TMLR style. Appendices follow the references. Supplementary PDF/ZIP files must also be anonymous; the stated limit is 100 MB. Complete active OpenReview profiles are required for all authors. The guide also describes editor recommendations and disclosures. The template imposes no fixed page limit, but length should be justified.

Before uploading through [TMLR on OpenReview](https://openreview.net/group?id=TMLR), revise the scientific claims above, prepare a reproducible anonymous supplement, verify author profiles and conflicts, and complete the form's author declarations. Confirm originality and absence of prohibited simultaneous archival submission, and check the current authorship quota and licensing terms in the [editorial policies](https://jmlr.org/tmlr/editorial-policies.html). Assess whether the work needs a broader-impact statement under the [ethics guidance](https://jmlr.org/tmlr/ethics.html); it is required for significant potential harm, not mechanically for every paper. Author responsibility for LLM-assisted content remains with the authors.

No upload or publication was performed. The official style's built-in "Under review as submission to TMLR" running header denotes its submission mode; it does not mean this draft has actually been submitted.

## Verification performed

The repository was updated from `origin/main` (`a4046b8c77228a467014c7215f2c60bf4f657380`) before the review. A conflict-free merge commit `1dcdd743916535b7563a14612b245c09091ba6d9` preserved both histories; its tracked tree matched the remote tip. The pre-existing untracked `.DS_Store` was left alone.

Read the complete manuscript, the comparison harness, saved CPU/MLX measurements, derived head sets, sibling reference counts, and reference-change documentation. Recomputed counts, minimum head probability, member/cycle absence baselines, novelty baselines, and before/after flags. [number-audit.json](number-audit.json) records the arithmetic and input hashes; [tools/audit_numbers.py](tools/audit_numbers.py) reproduces it. No costly stochastic experiment was rerun, and the historical causal interventions were not independently repeated. Their detailed logs were inspected, so they remain reported experimental evidence rather than new replication results from this review.
