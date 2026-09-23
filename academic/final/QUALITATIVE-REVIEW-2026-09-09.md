# Final Qualitative Review: 2026-09-09

## Assessment

No critical scientific contradiction, broken result, direct anonymity leak,
or mandatory PDF-format failure was found in this review. One sentence
introduced by the requested reference diff should be narrowed before submission.
It is a precision correction, not grounds to discard data or run another study.
The proposed change below has not been applied; author approval remains pending.

This is a review of the current claims and evidence, not a guarantee of TMLR
acceptance, completeness of the reference supports, or fidelity of the port.
No commit, push, submission, or new engine experiment was performed.

## Recommended Correction

**Location:** Section 5, Markdown lines 614-617, PDF page 9.

The sentence says that the ordinary singleton estimate is biased once
observations are dependent. That generalizes beyond the cited result and
can imply that the estimate is exactly unbiased under independent sampling.
Pananjady, Muthukumar, and Thangaraj study stationary missing mass for ergodic
Markov chains, not arbitrary dependence or a memory process that changes
across episodes. Their analysis supports concern about substantial bias in
the Markov setting, not a universal dividing line at dependence.
[Primary paper](https://jmlr.org/papers/volume25/24-0511/24-0511.pdf).

Proposed replacement for the final two sentences of that paragraph:

> For Markov sequences, the ordinary singleton estimate can be substantially
> biased [@ref35]. We therefore do not assume that its independent-sample
> guarantees apply to runs pooled across an evolving memory history.

For context, even with independent draws, the expected raw singleton ratio
at sample size N is sum p(1-p)^(N-1), whereas the expected missing mass at N
is sum p(1-p)^N. The small finite-sample difference is not a new defect in the
study: the manuscript already treats the raw ratio as heuristic guidance and
uses separate validation. There is no need to add this derivation to the paper.

## Claims and Evidence

- The asymmetric-cost contribution is clear: collect and validate a reusable
  reference, then automate budgeted checks that name cases for investigation.
  Run-count ratios are not presented as measured elapsed-time or human speedups.
- Good-Turing-guided collection and p50 missing-answer checks have separate
  jobs. The newer native-winner episodic study is explicitly support-only;
  the manuscript does not imply that it also tested a new episodic p50 design.
- The two native winner populations are separately counted, with earliest
  eligible ties selected. Neither the sampling argument nor the confidence
  allocation assumes independence between best_a and best_b.
- Immediate stopping is openly described as a weak heuristic. Frozen-set
  validation, failed coverage, conditional answered-episode denominators,
  retained failures, and the allocation across all 38 populations are explicit.
  The three jointly qualifying problems do not become a claim of benchmark-wide
  coverage or port equivalence.
- The historical direction repair remains the central engineering result.
  Missing build provenance, unequal historical caps, seed reuse, and limits
  on historical reconstruction are stated rather than concealed by later data.
- The later 969,000 single-run observations and 25,974 episodes describe
  recorded builds. They do not retroactively reproduce the historical repair.
  The misc3 finding distinguishes 24 outside port quality winners from zero
  outside reference winners in 1,000 validation episodes, without claiming
  that the two source differences are proven event-level causes.
- Conceptual coherence is bounded to selected answers, not internal reasoning
  equivalence. Experience-conditioned exploration is distinguished from
  improved learning, transfer, or proof that memory caused the discrepancy.
- The proposed TDD and human-speech applications remain proposals, not
  additional results. Process novelty is differentiated from the established
  estimators, head selection, discovery statistics, and reset-based testing.

The newly revised memory passage was checked against the reconstructed
reference answer-finder at answers.ss:982-986 and the port's answer-finder
body in seed_data/codelet_types.json, with the duplicate predicate in
server/engine/memory.py. Both reject an already remembered structural answer
before accepting it. This is static source corroboration, not a fresh
runtime comparison of the complete memory paths.

## Remaining Reviewer Risks

These are not undisclosed defects or requirements to launch another experiment.

- The work is one cognitive-architecture engineering case study, without a
  controlled defect suite, measured development-cost comparison, or matched
  memory-disabled control. Reviewers may request more evidence. The current
  restricted claims are preferable to presenting those missing experiments
  as already accomplished.
- The historical result's incomplete provenance limits independent replication,
  even though it legitimately motivates the paper and its later studies.
- The paper has 21 main-text pages. The examples improve accessibility, but
  length and repeated qualifications may still affect reviewer reception.
- Section 10's hypothetical speaker-style generator specifies consent, but
  does not explicitly discuss deceptive impersonation or disclosure of generated
  speech. A brief risk-and-mitigation note would strengthen this proposal.
  This review does not establish that a mandatory standalone broader-impact
  statement is triggered by the present Metacat experiments. TMLR expects
  applicable negative impacts and mitigations to be discussed and explicitly
  identifies harmful deception as a concern.
  [Ethics guidelines](https://jmlr.org/tmlr/ethics.html).
- The word "fizzle" in the revised memory paragraph remains specialist
  vocabulary. Its surrounding explanation conveys the behaviour, so this is
  a minor accessibility point rather than a scientific problem.

TMLR assesses support for claims and reader interest; a new estimator or
state-of-the-art learning result is not a prerequisite. Scope and acceptance
remain editorial judgments, not outcomes a format check can establish.
[Acceptance criteria](https://jmlr.org/tmlr/acceptance-criteria.html).

## Requested Diff and References

All seven supplied hunks were applied, with a successful reverse-application
check. The three prose changes are in support-set-oracles-final.md, and the
four metadata changes are in final/references.bib. The shared older
references.bib and earlier submission draft remain unchanged.

- Chao (1984): the supplied URL is removed; the bibliographic record remains.
- Segura et al. (2016): the DOI matches the author's institutional repository
  record, [White Rose Research Online](https://eprints.whiterose.ac.uk/id/eprint/110335/).
- O'Neill (2022): issue 3 is confirmed by the publisher's
  [volume 37, issue 3 contents](https://link.springer.com/journal/180/volumes-and-issues/37-3).
- Gerhold and Stoelinga (2018): issue 1 is confirmed by the publisher's
  [volume 30, issue 1 contents](https://link.springer.com/journal/165/volumes-and-issues/30-1).

The focused online reference check covered the changed records and the
Markov claim. It supplements the earlier bibliography review; it is not a
claim that every cited paper was freshly reread in full today. All 34 cited
records resolve within the generated bibliography, with no undefined citations.

## Submission Verification

The official style archive and public OpenReview submission invitation were
downloaded afresh on 2026-09-09. The resulting checks are recorded in
[verification.json](verification.json); artifact hashes are in [build.json](build.json).

- Anonymous official TMLR mode, blank author metadata, and direct private-identifier
  scans pass for the PDF and supplementary contents. This does not prevent
  deliberate external fingerprinting of public code or scientific identifiers.
- The PDF has 31 pages, including 21 main-text pages. References occupy pages
  22-24. Appendices start on fresh pages: A 25, B 26, C 28, D 29, E 30, F 31.
- The PDF is 195,343 bytes; the single final supplement is 77,954,190 bytes.
  Both meet the current form limits. Use the long-submission category and
  leave Beyond PDF empty for this conventional PDF submission.
- All 24 fonts are embedded. Page-bound checks pass, with no overfull boxes,
  undefined references, or missing characters. All-page rendered layout review
  and closer inspection of changed pages found no overlap or clipping.
  Existing nonfatal template and underfull-box diagnostics remain.
- All 90 tests pass: 51 academic, 14 reconstruction-helper, five submission
  packaging, and 20 final-build tests. The new tests reject unauthorized,
  stale, uncited, and invalid bibliography metadata corrections.
- A clean extraction of the actual attachment rebuilds from Markdown to
  byte-identical LaTeX and identical extracted PDF text. The experimental ZIP
  and all 29 monitored earlier-draft/evidence files remain byte-identical.

Before upload, the author must complete the private OpenReview declarations,
maintain an active complete profile, and confirm remaining submission quota.
No account-specific eligibility or private responses were verified here.
TMLR requires anonymous PDF and supplementary files, permits justified longer
papers, and places appendices after references.
[Author guidelines](https://jmlr.org/tmlr/author-guide.html),
[editorial policies](https://jmlr.org/tmlr/editorial-policies.html).

Use support-set-oracles-final.pdf and support-set-oracles-final-supplement.zip,
not the earlier draft or the repository's local review documents. Final human
review and approval remain outstanding.
