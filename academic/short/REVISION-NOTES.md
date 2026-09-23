# Regular-Length Revision and Qualitative Check

## Authorized Scope

On 2026-09-09 the author approved restructuring the paper to at most 12 pages
of main content, preserving the current long draft and moving supporting
detail into appendices. The candidate has nine main-content pages, with the
official typography unchanged. This is a presentation revision, not a new
experiment, altered observation set, or claim of final human approval.

## Where the Material Went

| Earlier material | Current location |
| --- | --- |
| Introduction and asymmetric-cost motivation | Main Sections 1-2; cost detail in A.4 |
| Method, stopping, p50, episode selection, coverage validation | Main Section 2; formal details in A |
| Historical direction repair and execution-cap mismatch | Main Section 3; protocol, counts, and memory records in B |
| Recorded single-run protocol, results, reference failures, prefix analyses | Main Section 4; detailed protocols, seeds, and tables in C |
| Episodic construction, validation, and port results | Main Section 5; complete tables in D and execution accounting in F |
| misc3 investigation | Main Section 5.2; complete winner evidence and source leads in E |
| Related work | Main Section 6; extended discussion in J |
| Limitations | Main Section 7, with local qualifications beside results |
| Potential applications and TDD | Penultimate main Section 8; further examples in J.1 |
| Conclusion | Main Section 9 |
| Supplement reproduction, notation, benchmark inputs | Appendices G, H, I |

The full nine-equation inventory and all twelve audited external table files
remain. Two of those tables are in the main text; ten are in appendices.
A new two-row main-text misc3 summary is verified against the saved study.
The thirty-four cited works and corrected bibliography are unchanged.

Two repeated introductory paragraphs were removed from the historical appendix
because the main text already supplies the development context and benchmark
description. This also prevents a nearly empty final page of that appendix.
The appendices are individually separated by page breaks.

## Scientific Review

The revised main text was read for changes in meaning, not only length.
These boundaries remain visible without relying solely on appendices:

- The reference is modified Metacat. Patches include behaviour-affecting fixes,
  not merely graphical-interface removal.
- Port improvement through the historical investigations remains the main
  engineering result. Missing historical build provenance, reused seeds,
  the unvalidated MLX path, and unresolved copy5/aac remain acknowledged.
- Good-Turing is a construction heuristic, not a coverage certificate. p50
  selects common outcomes; its missing-member flags are not calibrated
  evidence of deletion. Outside membership does not prove a port defect.
- The later single-run study freezes full 20,000-run construction samples.
  Prefix stopping analyses are hypothetical, not actual savings. All three
  reference errors remain counted, and the continuation is identified as a
  response to failure rather than an unchanged prospective protocol.
- Episodic winners have two definitions, an earliest-occurrence tie rule,
  and conditional complete-answered-episode denominators. The definitions
  are separately counted, not assumed statistically independent. The newer
  study has no episodic p50 head.
- All eight qualifying populations, twenty failed populations, and ten
  unvalidated populations are accounted for. The immediate-stop failure
  on misc5 and the four reused full pilot prefixes remain in the main text.
- The misc3 quality discrepancy remains 24/100 outside port winners versus
  0/1,000 in reference validation, under the declared simultaneous allocation.
  The 21/1/2 tie groups, nine fully answering episodes, failed preference
  coverage, and two unproven source-level explanations remain distinguished.
- Conceptual coherence means selected-answer behaviour under native judgments,
  not equality of internal reasoning or proof of better learning. No matched
  memory-disabled control or causal diagnosis has been added.
- The paper identifies process novelty without claiming new estimators or
  optimal p50 selection. Count ratios are not measured time savings.
- TDD and human-derived speech-pattern oracles are future applications. The
  speaker example retains consent, predefined categories, appropriate sampling
  assumptions, and the distinction between an outside pattern and an impossible
  human expression. No human-data experiment is claimed.

The related-work sentence previously flagged as overgeneralizing dependence
has been narrowed in this candidate: Markov-sequence results rely on explicit
assumptions and do not automatically justify pooling an evolving memory
history. The long draft is untouched. No claim that all dependence causes
bias, or that the raw singleton estimate is exactly unbiased for independent
finite samples, is introduced.

The new main-text explanation of answer quality restates the native calculation
already documented in the preserved misc3 appendix. It adds no new experiment
or scoring rule.

## Remaining Boundaries

No new critical scientific or formatting issue was identified during the
compression review. Historical reproducibility remains incomplete, the
workflow lacks a controlled defect-suite evaluation and measured development
cost comparison, and the episodic discrepancy still lacks a demonstrated
cause. These are stated limits, not problems repaired by shortening the paper.

The earlier optional concern about explicitly discussing misuse and disclosure
in the hypothetical speaker-style application remains an author-review point;
the structural revision does not claim to resolve it. Author approval, private
OpenReview declarations, account eligibility, and editorial acceptance have
not been supplied or established by these checks.

The qualitative check and automated inventory guards are complementary.
Neither is a proof that every possible ambiguity or error has been eliminated.
See verification.json for the actual artifact hashes and submission checks.

## Qualified References: 2026-09-10

Reviewed every occurrence of "this" in the main text, footnotes, and
appendices. Bare uses now name the relevant process, observation, calculation,
or audit; the author's revised abstract sentence is preserved. The included
table sources and bibliography contain no additional occurrences. No scientific
result, equation, reference, or limitation was changed.

The build's saved-data check now tolerates the existing Markdown table's
alignment whitespace while still rejecting changed values. A regression test
covers spacing, and the altered-value test now handles aligned rows. All 105
tests pass. The regenerated candidate remains nine main-content pages and 31
pages overall; earlier drafts and the experimental attachment are unchanged.
No commit, push, submission, or engine experiment was performed.

## Abstract-Led Clarity Revision: 2026-09-11

The author's replacement abstract now guides the main narrative. The abstract
names Metacat, Petacat, their languages, and AI coding assistance; explains the
large-reference/fast-check investment; distinguishes unexpected solutions from
missing p50 solutions; and presents port improvement as the primary result and
the testing process as a second contribution. Study counts remain in the body.
Historical evidence gaps and the failure of some reference sets remain explicit.

The mathematical framing follows the author's subsequent clarification:
countable problem and solution sets, with a relation that may associate several
solutions with one problem. The body defines membership through positive
production probability under fixed settings and initial memory. Random seeds
are not treated as separate analogy problems. Single-valued versus potentially
multi-valued is the relevant distinction, not injective versus surjective.

The main text now defines reference program, reference sample, outcome, observed
support, p50 head, episode, projection, winner population, freezing, and coverage
qualification before presenting their results. Short explanations replace
compressed terminology in the repair and study accounts. The abstract's flags
are statistically motivated reasons to investigate, not claims of statistical
significance or proof that an unobserved solution has disappeared from the port.

"Solutions" replaces analogy-related "answers" throughout the manuscript and
tables. The sole prose exception quotes the native term "answer quality" to
identify it explicitly as the score called "solution quality" in the paper.
"Testing process" replaces "workflow". All uses of "this" remain qualified.
The countable-set notation is also listed in Appendix H.

Earlier tables remain untouched. The candidate uses derived copies under
`short/generated/`, with an explicit list of allowed caption/header substitutions.
The build rejects any other table change, and regression tests check every
numeric token and reject an altered count. All 34 references, nine displayed
equations, section identifiers, and the numerical-token inventory are retained.
All 108 tests pass. The 64 preserved files and experimental ZIP remain unchanged.

The current PDF has ten main-content pages, three reference pages, and nineteen
appendix pages, using unchanged official typography. The public OpenReview form
and official style ZIP were downloaded again on 2026-09-11 and match the previous
verified hashes. The [TMLR author guidelines](https://jmlr.org/tmlr/author-guide.html)
and [editorial policies](https://jmlr.org/tmlr/editorial-policies.html) were checked;
the paper stays in anonymous submission mode, with no author-linked repository
URL added. Technical checks do not guarantee acceptance or anonymity against
deliberate external identification. No engine run, commit, push, or submission
was performed. The author still needs to review and approve the draft.
