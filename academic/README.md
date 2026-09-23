# TMLR Manuscript

**Current regular-length submission candidate:**
[support-set-oracles-12-page.pdf](support-set-oracles-12-page.pdf), with ten
main-content pages, followed by references and evidence appendices. It retains
the anonymous TMLR format and the author's plain-language essay voice.
The editable base is [support-set-oracles-12-page.md](support-set-oracles-12-page.md).
The 2026-09-11 clarity revision follows the author's new abstract and uses
consistent solution/process terminology, with an explicit relation over
countable problem and solution sets.
See [short/README.md](short/README.md) for the matching submission attachment,
verification, relocation notes, and rebuild instructions. Final manual author
approval is pending; nothing has been committed, pushed, or submitted.

The previous 21-page-main-text draft remains preserved as
[support-set-oracles-final.pdf](support-set-oracles-final.pdf), with its
own [source and review record](final/README.md).

## Earlier Draft and Review Record

The earlier files and review history below are retained for comparison.

**Status: substantively revised draft; not yet cleared for submission.**
Current title: **Large References, Small Checks: Oracle-Guided Porting of a
Stochastic Learning System**.
Start with [REVISION-STATUS.md](REVISION-STATUS.md), which maps the major and
minor review findings to their corrections and identifies the remaining
evidence gaps. No OpenReview submission has been made.

The anonymous initial-submission files have been checked against TMLR's current
style and public OpenReview form definition. See
[INITIAL-SUBMISSION.md](INITIAL-SUBMISSION.md) for the exact two uploads: the
PDF and the single combined supplementary ZIP. This is not a preprint or
camera-ready version; final manual author review and approval remain pending.

## Integration and Approval Status

Revision checkpoint, 2026-09-07: both new studies are complete. The author-approved
Issue 1 resolution incorporates the episodic coverage results and population
choice limitations into the manuscript, PDF, and LaTeX source bundle. Approved
Issue 2 adds the `misc3` discrepancy case study and complete frequency appendix,
distinguishing diagnostic groups and code-level leads from proven root causes.
Approved Issue 3 integrates the completed single-run study while preserving
the historical repair workflow as the core engineering result. The development
history remains in the main text; the versioned study strengthens, rather than
replaces, that account. Approved Issue 4 adds the complete 19-input episodic
port comparison, descriptive frequencies for construction-limited problems,
and full episode/run termination accounting. Final author review remains
pending. Approved Issue 5 adds a separate review supplement with
both studies, frozen source, reconstruction patches, audits, and clean-copy
verification instructions. The historical arithmetic-analysis ZIP is unchanged;
the new experimental ZIP includes that evidence as well as the newer studies.
Approved Issue 6 consolidates repeated explanations and shortens the abstract,
introduction, limitations, and conclusion while keeping the historical repair
narrative central. All results and appendix prose are preserved; two large
episodic tables use the existing keep-together layout option. The experimental
ZIP is refreshed for those layout files and the converter, not new evidence.
Approved Issue 7 adopts the current title, foregrounding oracle-guided port
improvement and the scope of a single stochastic learning system. The manuscript
body and experimental evidence are unchanged by the title revision.
The proposed declarations checklist was rejected; the author instead requested
verification of anonymous initial-submission readiness. That audit confirms
the PDF's submission mode and adds one upload ZIP containing both verified
inner bundles. No identifying declarations were added to the manuscript.
The author's subsequent process-novelty clarification is implemented in the
abstract, introduction, related work, and conclusion. It credits the integrated
Good-Turing/support/p50 workflow and its episodic application while retaining
port improvement as the primary result and distinguishing the newer support-only
native-best study. Scientific evidence and the experimental ZIP are unchanged.

Issues are reviewed one at a time, as recorded in
[ISSUE-RESOLUTIONS.md](ISSUE-RESOLUTIONS.md). **No changes may be committed or
pushed until the author manually reviews the final draft and gives final approval.**

- [Single-run study results](SUPPORT-V1A-RESULTS.md) and
  [full scientific-data release](../studies/support-v1a/data/README.md):
  969000 observations, retaining all three reference-engine errors.
- [Episodic study results](../studies/episodic-v3/results/MAIN-RESULTS.md):
  25974 episodes and 207791 actual inner runs. Only three problems meet the
  coverage target for both answer sets; five capped problems skip validation.
  The validated `misc3 best_a` reference flags 24/100 outside port winners,
  versus 0/1000 in reference validation. Its cause remains unestablished.
- [Episodic discrepancy investigation](investigations/MISC3-EPISODIC.md):
  complete frequencies, all 24 outside quality-winner events, and the two static
  rule-generalization differences. The approved treatment is in Section 8.1
  and Appendix B; no repairs or new experimental observations were made.

The current coverage revision reports failures and distinguishes construction
qualification from held-out coverage validation. Completion of
the episodic study does not establish port fidelity or replace memory-specific
controls, defect interventions, or learning-efficiency evidence. See
[STUDY-STATUS.md](STUDY-STATUS.md) for the publication status of both studies.

## Current Files

- [support-set-oracles-submission-supplement.zip](support-set-oracles-submission-supplement.zip):
  the single anonymous Supplementary Material upload, containing the unchanged
  experimental and LaTeX source ZIPs, a README, and checksum manifest.
- [INITIAL-SUBMISSION.md](INITIAL-SUBMISSION.md): verified initial-submission
  mode, exact field/file mapping, and separation of anonymous files from private
  form metadata. [submission-readiness.json](submission-readiness.json) records
  technical checks; [submission-build.json](submission-build.json) records hashes.
- [manuscript.md](manuscript.md): the current editable manuscript and the source
  of the LaTeX conversion. Make prose changes here, not in generated LaTeX.
- [support-set-oracles-tmlr.pdf](support-set-oracles-tmlr.pdf): anonymous TMLR
  draft built from the revised manuscript.
- [support-set-oracles-tmlr.tex](support-set-oracles-tmlr.tex): generated LaTeX.
- [support-set-oracles-tmlr-source.zip](support-set-oracles-tmlr-source.zip):
  standalone LaTeX build bundle with generated tables and template license.
- [support-set-oracles-analysis.zip](support-set-oracles-analysis.zip):
  analysis-only supplement containing archived counts, arithmetic code, tests,
  and [instructions](ANALYSIS-README.md). It is not an engine replication bundle.
- [support-set-oracles-experiments.zip](support-set-oracles-experiments.zip):
  review supplement containing both versioned studies, frozen source, all paper
  audits and tables, and Metacat reconstruction patches. Start with its root
  README after extraction. Original upstream source is not included.
- [supplement-build.json](supplement-build.json): experimental ZIP checksum,
  size, inventory count, and nested-archive verification result.
- [references.bib](references.bib): all 35 verified references.
- [REFERENCE-AUDIT.md](REFERENCE-AUDIT.md): reference identities and source links.
- [number-audit.json](number-audit.json): recomputed quantities and input hashes.
- [support-study-audit.json](support-study-audit.json): the versioned single-run
  study's batch totals, reference errors, prefix comparisons, and input hashes.
- [episodic-study-audit.json](episodic-study-audit.json): all 19 episodic port
  comparisons, complete construction/port frequency vectors for both populations,
  termination accounting, and input hashes. Generated without engine execution.
- [data/README.md](data/README.md): bundled measurement inputs and their limits.
- [BUILD-CHECKS.md](BUILD-CHECKS.md): build, PDF, and bundle verification.
- [NOVELTY-REVIEW.md](NOVELTY-REVIEW.md): additional primary literature and
  limits on novelty claims, researched while the new study runs.
- [EPISODIC-REVIEW.md](EPISODIC-REVIEW.md): paper direction, archived
  episodic evidence, and a proposed separately versioned memory-dependent study.
- [EPISODIC-IMPLEMENTATION-REVIEW.md](EPISODIC-IMPLEMENTATION-REVIEW.md):
  sub-agent review mapping memory mechanisms and existing regression definitions
  to the expanded paper section. Inspection is distinguished from test execution.
- [episode-audit.json](episode-audit.json): newly audited archived episode
  sequences, summarized in the manuscript and included in the analysis ZIP.
- [generated/episodic-coverage-table.tex](generated/episodic-coverage-table.tex):
  the new 19-input coverage table, generated from the separate v3 result bundle.
- [generated/misc3-frequency-table.tex](generated/misc3-frequency-table.tex):
  all 27 observed `misc3` strings across construction, validation, and port checks,
  generated from the [saved-data audit](investigations/misc3-episodic-audit.json).

The [dated Markdown](20260828%20oracles-for-stochastic-system-comparison.md) is a
**superseded historical draft** and retains claims rejected in the revision.
It has a notice pointing to the current source. [REVIEW.md](REVIEW.md) preserves
the initial findings and refers to the historical version's numbering.

## What Changed

The title, abstract, introduction, cost model, and conclusion now center on
asymmetric effort: build an expensive reference once and reuse it for smaller
checks across port revisions. The learning-mode case study is in the main
paper, with a whole reset episode as its statistical unit. Neither the
historical run-count ratios nor the cost identity establish a measured speedup.

The revision presents the method as a support-oriented diagnostic, not a
calibrated test of unrestricted support equality. Reference-based probabilities
are labeled plug-in baselines. The missing-mass stopping rule is explicitly
heuristic. Counterexamples, rare-defect detection calculations, and a clearly
identified toy binomial comparator make the limits concrete.

The case study retains the verified archived totals and reported defect
investigation. It corrects counting units, seed reuse, head-selection
uncertainty, cap-rerun cost, and the scope of the Scheme intervention evidence.
The unsupported 35-outcome discovery-gap example and categorical claims about
frequency tests are withdrawn. The current document separates
observations, interpretation, and proposed future work.

The episodic audit reports endpoint flags, no-answer episodes, and cap effects
together. It does not call a finite-horizon endpoint convergence, treat a
single-run reference match as proof of learned-context correctness, or claim
improved learning performance. The expanded case study explains structural
duplicate rejection, retained memory versus reset activations, and retrospective
reminding, alongside existing regression contracts. These test definitions were
reviewed, not newly executed as an engine validation. A separately versioned
matched-cap episodic study has since completed, as linked above; its coverage
results and `misc3` discrepancy are now incorporated, as are the versioned
single-run results. Memory-specific controls
remain an evidence gap for the intended learning-system contribution.

The audit now uses files in `data/`, not a sibling repository. All copied data
are unchanged historical records, not newly generated observations. No new
engine experiment or author declaration was invented. Misleading statistical
and replay comments were corrected without changing comparison behavior.

## Rebuild

Commands below run from **this `academic` directory**. The audit and its tests
need Python 3.11 or later and no third-party Python modules:

```sh
python3 tools/audit_numbers.py
python3 tools/audit_episodes.py
python3 tools/audit_support_study.py
python3 tools/audit_episodic_study.py
python3 tools/investigate_misc3.py --output investigations/misc3-episodic-audit.json
python3 -m unittest discover -s tests -p 'test_*.py'
```

To regenerate LaTeX and the thirteen data tables, install Pandoc (the tested version
is 3.11), then run:

```sh
python3 tools/convert_manuscript.py --pandoc pandoc
```

This reads `manuscript.md`, the bundled historical measurements, the versioned
single-run summaries in `data/support-v1a/`, and
the saved episodes, oracles, protocol, manifest, and analysis under
`../studies/episodic-v3/results/main/`. It does not read or
rewrite the historical Markdown. Conversion overwrites the generated `.tex`
and `generated/*.tex`; edit the Markdown or converter instead.

Build the PDF with a standard TeX installation:

```sh
pdflatex -interaction=nonstopmode -halt-on-error support-set-oracles-tmlr.tex
bibtex support-set-oracles-tmlr
pdflatex -interaction=nonstopmode -halt-on-error support-set-oracles-tmlr.tex
pdflatex -interaction=nonstopmode -halt-on-error support-set-oracles-tmlr.tex
```

Or use Tectonic, which manages TeX/BibTeX passes automatically. The verified
build uses Tectonic 0.17.0:

```sh
tectonic --keep-logs --keep-intermediates support-set-oracles-tmlr.tex
python3 tools/package_artifacts.py
```

The explicit packaging list excludes the historical named manuscript, review
notes, public repository documentation, and original Metacat source. Packaging
does not rebuild the PDF; run it after conversion and compilation. The source
ZIP contains everything needed by the generated LaTeX and does not require
Pandoc or the analysis data to typeset.

Build the separate experimental supplement from the repository root:

```sh
python3 academic/tools/package_experiments.py
```

Add repeated `--forbid` arguments for author/machine identifiers during the
private pre-submission check. The builder checks frozen source hashes and the
nested scientific archives, replaces only review navigation and the displayed
copyright-holder identity, and preserves the original files. The package
manifest records the exact policy and original hash for each included file.
It refuses unexpected source changes or a package at or above 100 MB.
Its `--verify ZIP --extract NEW_DIRECTORY` mode checks and safely extracts a
clean copy; the destination must not already exist. Inside that copy,
`python3 verify.py` regenerates all audit reports and tables, runs tests, and
verifies the episodic study without an engine. See its `REPRODUCE.md` for full
single-run reanalysis with pinned dependencies.

Finally, combine the verified experimental and source ZIPs into the one
attachment accepted by the current submission form:

```sh
python3 academic/tools/package_submission.py
python3 -m unittest discover -s academic/submission/tests -p 'test_*.py'
```

These two commands run from the repository root. They do not rebuild the
inner bundles, so run the preceding manuscript/experimental packaging steps
first after changing their contents. Repeated `--forbid` arguments also apply
to this outer builder's identifying-token checks.

## Evidence and Submission

The portable [Metacat patch bundle](../Metacat/README.md) provides reconstructible
modified source. It does **not** establish which historical build generated the
374,500-run historical reference sample. The versioned study adds identified
builds, held-out validation, and a frequency comparator without retroactively
establishing the historical intervention provenance. Equal-cost defect-power
comparisons and memory-specific controls remain open. The paper retains the
historical repair narrative as central evidence of the approach's practical value.

The manuscript has an anonymous byline, empty PDF author metadata, no named
acknowledgements, and no author-identifying repository URL. The public
repository is not anonymous. The author must review all intended uploads for
anonymity, scientific accuracy, and required disclosures. The experimental ZIP
is the experimental inner bundle; the final single supplementary upload wraps
it together with the LaTeX source ZIP. The older analysis ZIP alone is insufficient.
The original MIT license and GPL reconstruction license remain unchanged in the
repository. Only the review copy's MIT copyright-holder display name is withheld;
restore its original named notice for a nonanonymous release. Scientific labels
and hash chains remain intact, so anonymity checks do not promise resistance
to deliberate external fingerprinting. Private episodic attempt files and
historically unavailable evidence are explicitly excluded, not fabricated.

Use the [TMLR author guide](https://jmlr.org/tmlr/author-guide.html) and
[editorial policies](https://jmlr.org/tmlr/editorial-policies.html) when preparing
the actual submission. The style's automatic "Under review" header indicates
template mode, not that a submission has occurred.

## Template Provenance

The original [template archive](tmlr-style-file-main.zip) was downloaded from
the [requested official URL](https://github.com/JmlrOrg/tmlr-style-file/archive/refs/heads/main.zip)
on 2026-09-05. Its ZIP comment identifies revision
`7bf90efe3a0debbba703c05c43f3ff7e4d4a2992`. The extracted original and license are
retained in [tmlr-template/tmlr-style-file-main/](tmlr-template/tmlr-style-file-main/).
`tmlr.sty`, `tmlr.bst`, and `fancyhdr.sty` remain unmodified. The small Pandoc
wrapper in `tools/tmlr-template.tex` is our document wrapper, not a replacement
for the official style.
