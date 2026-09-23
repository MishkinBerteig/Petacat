# Author-Approved Issue Resolutions

## Review and Commit Rules

Present one issue and its proposed resolution at a time. Wait for the author's
approval, modification, or rejection before implementing it or advancing to
the next issue. Approval of an individual resolution is not permission to
commit. After all issues are addressed, the author will manually review the
final draft. **Do not commit or push any revision until the author gives final
approval after that review.**

## Issue 1: Heuristic Freezing Versus Validated Coverage

Status: approved with the author's modification; implemented in the manuscript
and generated LaTeX/PDF on 2026-09-07. Final manuscript approval is still pending.

Approved resolution:

- Present Good-Turing as a candidate-construction heuristic and independent
  held-out validation as the basis for a conditional coverage statement.
- Report successful, failed, and skipped validation. Keep all observations,
  and do not retrospectively alter the protocol or enlarge its frozen supports.
- Explain that immediate stopping often yielded incomplete episodic supports,
  not reliable coverage across all 19 inputs.
- State why `best_a` and `best_b` were chosen: native quality and conceptual
  preference make the selected episode results internally justifiable.
- Admit that Good-Turing-guided construction might work more effectively with
  another population of results. A future experiment may choose a different
  conceptually motivated projection to build a better oracle. This is an
  untested possibility, not a demonstrated improvement or a way to transfer
  existing coverage bounds to a new population.

Implementation covers the abstract, episode definitions, stopping and
qualification methods, episodic coverage results, discussion, conclusion, and
artifact boundaries. The new coverage table is generated from the immutable
v3 analysis and includes all 19 inputs. The standalone source ZIP includes it.
The historical arithmetic ZIP remains a separate supplement, not a release of
the new episodic experimental artifacts. No engine runs or study changes were
authorized or performed for this resolution.

The next issue requires its own proposal and author response. This log does
not authorize fixes, new experiments, or decisions for any other issue.

## Issue 2: misc3 Episodic Port Discrepancy

Status: investigation and manuscript treatment approved by the author;
implemented in the manuscript and generated LaTeX/PDF on 2026-09-07.
See [the investigation report](investigations/MISC3-EPISODIC.md) and its linked
machine-readable audit for oracle frequencies, all outside strings, the 24
outside quality-winner events, diagnostic partitions, source-level findings,
and limits on causal attribution. No episodes were run, neither engine was
changed, and no commits or pushes were made.

Approved treatment: add a focused `misc3` case study reporting the problem,
independent freeze points, validation bounds, and outside port winners. Preserve
the distinction between the qualified quality oracle and failed conceptual-
preference coverage. Include complete frequencies and the 21/1/2 diagnostic
partition in the appendix; label the score difference and two source findings
as investigative leads, not proven causes. Emphasize asymmetric reference/check
budgets without claiming a speedup, port equivalence, or learning improvement.

The implementation updates the abstract, contribution statement, Section 8.1
(originally Section 7.1 before the single-run study was integrated),
conclusion, reproduction notes, and Appendix B. The sixth generated table
comes from the saved-data audit and is included in the standalone source ZIP.
The historical arithmetic ZIP is unchanged. Final author review is still
required before any commit or push.

## Issue 3: Completed Single-Run Evidence Is Not Integrated

Status: approved with the author's modification; implemented on 2026-09-07.

The main single-run case study still relies on historical aggregates with
incomplete sampled-build provenance. Its discussion treats independent
validation and an empirical frequency comparator as future work, while the
completed, versioned `support-v1a` study supplies relevant new evidence.

Approved resolution: make the completed 969,000-observation study the primary
versioned single-run measurement evidence, clearly distinguished from the historical repair narrative.
Report the 380,000 construction, 570,000 validation, and 19,000 port observations;
the post-failure protocol amendment and all three retained reference errors;
finite-reference discoveries and port flags; the complementary frequency
comparison; and qualified reference/check cost accounting. Update future-tense
limitations only where this evidence resolves them. Preserve unresolved
causal and comparative-power limits and do not claim equivalence or measured
speedup. The revision uses existing data only, without engine runs or repairs.

Author modification: the historical approach was central to improving the
quality of the port and motivating the paper. Keep that development history
as the core engineering result, not a relegated or superseded anecdote. State
its provenance limits without erasing its practical value. The newer study
strengthens the evaluation, not a claim to recreate the historical interventions.

The abstract, introduction, main-text development history, and conclusion now
emphasize the concrete repair workflow. Section 7 and Appendix C add the
versioned study, all retained failures, complete per-input results, prefix
comparisons, and the frequency comparator. Four additional generated tables
come from a separate saved-analysis audit. The historical arithmetic ZIP and
all frozen experimental data remain unchanged. Final author review and approval
are still required before any commit or push.

## Issue 4: Complete Episodic Port Reporting

Status: approved as proposed by the author; implemented on 2026-09-07.

The manuscript already reported coverage for all 19 inputs but concentrated
detailed port reporting on `misc3`. The approved resolution adds a complete
benchmark-wide port comparison so that this worked example is not presented
in isolation. It includes both native answer populations, answered episode
denominators, outside counts wherever a support froze, and separate reference
coverage outcomes. Missing supports are distinguished from zero outside counts;
failed or skipped validation remains explicit.

For all five construction-limited problems, both populations receive descriptive
frequency comparisons using the full construction sample, not earlier frozen
prefixes or pooled validation data. The appendix reports empirical TV and the
largest answer-share difference, without new p-values or equivalence claims.
All 38 full count vectors remain in the saved-data audit. The manuscript also
accounts for answerless episodes, inner-run caps, and the inherited partial
error episode, without counting partial-episode answers as episode winners.

Implementation adds the all-input table in Section 8 and frequency/termination
tables in Appendix D. A separate standard-library audit checks the new figures
against saved episodes; eight new audit tests and two table tests bring the
academic suite to 45 tests. The source ZIP includes all thirteen generated
tables. The historical arithmetic ZIP, original study records, and both engines
are unchanged. No new experiment, repair, commit, push, or submission is part
of this approval. Further issues await their own proposals and author responses.

## Issue 5: Anonymous Reproducibility Supplement

Status: approved as proposed by the author; implemented on 2026-09-07.

The historical arithmetic supplement did not contain the new versioned studies.
The approved resolution creates a separate combined review ZIP with historical
measurements, both studies' scientific exports, frozen port source and seed data,
analysis scripts, tests, manifests, dependency links, and reproduction commands.
All four single-run scientific archives are included unchanged. The episodic
main export, reused pilot, preflight, complete winner frequencies, and `misc3`
event ledger are included. The full private episodic attempt archive is excluded;
the paper and supplement distinguish its earlier audit from what public exports
alone can reproduce. Missing historical evidence is not synthesized.

Metacat is supplied only as upstream links, reconstruction patches, manifest,
helpers, tests, and its existing GPL license. No upstream source or dependency
binary is redistributed. Reconstruction in a clean directory verifies all 69
files without engine execution. Recorded port source and analysis code remain
byte-identical. The review manifest records their comparisons against both study
snapshots and identifies omitted repository ignore files and a GUI screenshot.

Two README files replace identifying repository navigation with review setup
instructions. The existing root MIT license is included with only the copyright
holder's displayed name temporarily anonymized; its terms and upstream
attribution are preserved. The named original remains untouched and must be
restored for a nonanonymous release. Direct project naming in manuscript prose
is neutralized without changing the historical development narrative. Scientific
implementation labels and hashes remain unchanged; this is not a guarantee
against deliberate external fingerprinting.

The extracted verifier reproduces all five audits and thirteen tables, runs
academic/reconstruction-helper tests, verifies episodic stopping and bounds,
and optionally replays the full single-run saved-data analysis with pinned
NumPy/SciPy versions. Six packaging regression tests bring the academic suite
to 51 tests. No analogy experiment, engine repair, commit, push, or OpenReview
submission was performed. Final human review and approval remain mandatory.

## Issue 6: Repetition and Focus

Status: approved as proposed by the author; implemented on 2026-09-07.

The expanded draft repeated coverage, provenance, and cost qualifications across
its abstract, study introductions, limitations, and conclusion. The approved
editorial revision consolidates these explanations without changing findings,
protocols, statistical targets, or conclusions. The abstract is reduced from
223 to 177 words. The introduction, study transitions, limitations, and conclusion
are shorter, with approximately 760 fewer whitespace-delimited words overall.

The full cost and reuse conditions remain in Section 3; coverage definitions
and the analytical zero-miss validation budget are together in Section 4.4;
Section 5 retains the statistical distinctions and counterexamples. Results
retain necessary local qualifications and use cross-references for repeated
explanations. Section 9 concentrates the remaining research questions rather
than repeating the detailed results.

The historical repair workflow remains the core engineering result in the
abstract, introduction, main-text Section 6, and conclusion. Native episodic
definitions, failed qualification, alternative-population discussion, all-input
comparisons, termination accounting, and the full `misc3` investigation remain.
All numerical values, display equations, citations, table data/captions, and
appendix prose are preserved. The existing keep-together layout option is
enabled for the two large episodic main-text tables to prevent page splits.

The LaTeX/PDF and source ZIP are rebuilt. The experimental ZIP is refreshed
only for the converter and the two tables' layout wrappers, with an updated
inventory; its scientific evidence, frozen engines, and study tools are unchanged.
No new engine experiment, repair, commit, push, or submission is authorized or
performed. Further issues require their own approval; final manual author review
and approval remain mandatory before any commit.

## Issue 7: Title Scope

Status: approved as proposed by the author; implemented on 2026-09-07.

Approved title: **Large References, Small Checks: Oracle-Guided Porting of a
Stochastic Learning System**.

The title retains the asymmetric reference/check investment, foregrounds the
port-improvement result, and reflects evaluation of one stochastic learning
system rather than suggesting a broader empirical benchmark. The manuscript
title, generated LaTeX and PDF metadata, current documentation, source ZIP,
and review supplement are updated. Historical title records remain historical.
The abstract, manuscript body, scientific evidence, and frozen source are
unchanged. No experiment, commit, push, or submission is performed; final manual
review and explicit author approval remain required before committing.

## Issue 8: Initial-Submission Readiness

Status: the proposed author-declarations checklist was rejected. The author
redirected the work to checking the anonymous initial-submission requirements
and preparing the actual OpenReview/TMLR upload files on 2026-09-07.

The public `TMLR/-/Submission` invitation and current official style distinguish
anonymous PDF/supplement files from restricted-access author metadata in the
initial form. The manuscript already uses anonymous submission mode. No names,
affiliations, funding statements, or identifying acknowledgements were added.
No preprint or camera-ready version was prepared, and no personal declarations
were inferred or entered.

The live form requires one supplementary attachment. A new deterministic ZIP
wraps the existing, unchanged experimental and source ZIPs with an anonymous
README and checksum manifest. The correct submission category is long: 18 pages
precede references. The Beyond PDF field is not for these supplementary files.
The exact file mapping and verification are in
[INITIAL-SUBMISSION.md](INITIAL-SUBMISSION.md); the public invitation snapshot
and machine-readable checks are retained separately from the uploads.

The paper, scientific evidence, and frozen source are unchanged. Five outer
packaging tests check inventory, deterministic bytes, privacy scanning, altered
content, and unwanted archive comments. No engine experiment, commit, push,
account login, or submission was performed. The requested final manual author
review and explicit approval are still required before committing.

## Author-Requested Clarification: Process Novelty

Status: directly requested by the author and implemented on 2026-09-07.

The abstract's negative "not a new estimator" framing understated the
contribution of the process. The revised abstract explicitly identifies the
integration of Good-Turing sampling guidance, frozen observed-support sets,
and empirical p50 heads for recurring port checks, with single-run and episodic
applications. Documented port improvement remains the primary engineering result.
The introduction, related work, and conclusion state process-level novelty,
distinguishing the integrated workflow and application from established
statistical ingredients. A targeted primary-literature recheck found no exact
complete process among the works examined; the paper does not claim exhaustive
priority or uniqueness.

The body explicitly distinguishes the single-run and historical episodic p50
checks from the newer native-best-answer experiment, which evaluates frozen
supports and independent coverage qualification, not a new p50 head. No data,
study protocol, scientific result, reference, or frozen code was changed. The
anonymous PDF, LaTeX source bundle, plain-text abstract, and combined submission
attachment are rebuilt. The experimental ZIP remains byte-identical. No new
experiment, commit, push, or submission is authorized by this wording change;
the requested final manual author review and explicit approval remain pending.

## Author-Requested Complete Style Rewrite

Status: directly requested by the author on 2026-09-07, including explicit
confirmation that the rewritten version is the intended TMLR submission.

A separate `support-set-oracles-final.md` rewrites the abstract, full body,
and appendices with concrete examples, defined terminology, direct questions,
and plain explanations before formal notation. It follows the supplied essay
voice profile without identifying biography, affiliations, quotations from
personal essays, or informal blog punctuation. The approved title stays.

The original manuscript, LaTeX, PDF, source bundle, submission attachment,
and shared evidence remain byte-identical. The new draft uses the same audit,
Pandoc, official TMLR template, and Tectonic workflow, with separate final
outputs and source/submission bundles. All cited works, displayed equations,
generated tables, quantitative findings, and scientific limits are retained.
The new draft is still anonymous and passes the public-form and style checks.
See [final/README.md](final/README.md) for checks and exact upload files.

No experiment, repair, commit, push, login, or submission was performed.
The filename `final` is not approval: the author's manual review and explicit
final approval are still required before committing or submitting.

## Author Feedback: Fast Checks and Conceptual Behaviour

Status: directly requested by the author on 2026-09-07.

The restyled draft now uses **Large References, Fast Checks** and the requested
abstract description of Metacat's open-ended analogy task and episodic learning.
The abstract, introduction, method, related work, and conclusion distinguish
unexpected port solutions (comparison with a Good-Turing-guided reference set)
from potentially missing common solutions (p50 head membership). The newer
native-winner study remains explicitly support-only.

The practical benefit is made explicit: automatic comparison replaces repeated
human inspection of result distributions, and native quality and preference
judgments make selected conceptual behaviour testable without one fixed target
answer. This does not assert a measured speedup, significance for every flag,
or complete conceptual equivalence. Deterministic implementation tests remain
complementary. The introduction's fuzzy-classifier view is qualified and linked
to Wikipedia's non-academic "Fuzzy classification" explanation; observed answer
frequencies are not equated with fuzzy-membership values.

Only the restyled draft and its supporting documentation and generated outputs
are revised. Older draft artifacts, scholarly references, scientific tables,
study records, and the experimental ZIP remain unchanged. No new experiment,
commit, push, login, or submission is authorized. Final manual author review
and approval remain pending.

## Author Direction: Restore the Intended Testing Scope

Status: explicitly requested by the author on 2026-09-07, superseding the
earlier proposal to retain a shortened frequency-comparison discussion.

The submission manuscript removes the statistical distribution-comparison
section entirely, its synthetic example, its single-run results and table
columns, the episodic distance-comparison material, the related-work paragraph
and citation, and related reproduction instructions. It contains no discussion
of why those comparisons were omitted. Good-Turing estimation, p50 selection,
support membership, reference-coverage validation, and raw selected-answer
counts required for the documented investigation remain.

The other requested edits are complete: $S_x$ is explicitly the observed
support set for problem $x$; the discarded historical anecdote and peripheral
preflight counts are removed; the cost section explains the TDD analogy; and
the new penultimate section, "Potential Application of the Process", discusses
uses beyond porting without representing proposed applications as experiments.

The final manuscript has its own twelve tables and 34-entry bibliography.
Nine tables are byte-identical copies; two omit the unwanted result row or
column, and the misc3 table retains every raw count with a count-based caption.
The manuscript source bundle contains only its referenced tables and bibliography.
The archived study evidence and 29 monitored earlier-draft files are untouched.
Build tests and submission verification check the permitted changes, retained
table counts, exact cited bibliography records, and absence of removed material
across Markdown, LaTeX, tables, bibliography, PDF text, and source ZIP contents.

No engine experiment, full numerical reanalysis, commit, push, or submission
was performed. Manual author review and final approval remain pending.

## Author Feedback: Human Examples as the Oracle

Status: directly requested by the author on 2026-09-07.

Section 10 adds a proposed application in which sampled speeches from one
person supply the oracle for a fine-tuned language model's style. Defined
phrasing-pattern categories support p50 selection and a Good-Turing-like
discovery estimate adapted to the sampling design. The generated speech is
checked for missing characteristic patterns and patterns outside the observed
support set; repetition rates are not prescribed. Held-out human samples
can assess reference coverage, and outside patterns remain investigation
flags rather than proof of impossible human behaviour. This is a proposed
experiment, not a reported result. The adjacent TDD distinction now allows
human reference examples to precede the software implementation.

No new experiment, commit, push, or submission is authorized. Final manual
author review and approval remain pending.

## Author-Supplied Style Diff: Integrity Review

Status: requested on 2026-09-08; reviewed before application.

The supplied diff matches the existing Markdown exactly. The applied version
accepts its stylistic changes while protecting 38 passages, including p50's
at-least-half threshold, the complete-answered-episode denominator, earliest
tied-winner selection, the head-membership condition for deletion detection,
historical attribution, conditional sampling statements, and cost limits.
The explicit process-novelty contribution and future population-selection
hypothesis also remain. This does not approve new scientific claims.

The [review note](final/STYLE-REVIEW-2026-09-08.md) and its companion JSON
record the exceptions. All cited works, data tables, section labels, displayed
equations, and reported numerical values are preserved. An editorial test now
allows sentence-initial capitalization of "Test-driven development"; numerical,
scope, and preservation checks are unchanged. The PDF and matching bundles
are rebuilt and checked without rerunning any engine experiment. No commit,
push, or submission is authorized; final manual author approval remains pending.

## Appendix Page Starts

Status: requested and checked on 2026-09-08.

The [TMLR author guidelines](https://jmlr.org/tmlr/author-guide.html) place
appendices after the references. Neither that guidance nor the
[official template](https://github.com/JmlrOrg/tmlr-style-file/blob/main/main.tex)
requires a fresh page for every appendix; the example uses `\appendix` directly
after the bibliography without a forced break. The previous layout was not a
violation of that requirement.

For consistent presentation, the final Markdown now adds `\clearpage` before
appendix A and before appendix F, matching the existing breaks before B--E.
No prose, equations, results, styles, or margins changed. The regenerated PDF
places A--F at the top of pages 25, 26, 28, 29, 30, and 31 respectively. A new
source-level regression check protects these starts; the rendered PDF was also
checked. The anonymous PDF and matching bundles are refreshed. No commit,
push, or submission is authorized.
