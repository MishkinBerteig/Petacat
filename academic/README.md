# TMLR Manuscript

**Status: substantively revised draft; not yet cleared for submission.**
Current title: **Large References, Small Checks: Amortized Testing of Stochastic
Learning Systems**.
Start with [REVISION-STATUS.md](REVISION-STATUS.md), which maps the major and
minor review findings to their corrections and identifies the remaining
evidence gaps. No OpenReview submission has been made.

## Completed Studies Awaiting Manuscript Integration

Publication checkpoint, 2026-09-07: both new studies are complete and their
public results are available. The current manuscript, PDF, and submission ZIPs
still describe the earlier evidence and have **not** incorporated these results.

- [Single-run study results](SUPPORT-V1A-RESULTS.md) and
  [full scientific-data release](../studies/support-v1a/data/README.md):
  969000 observations, retaining all three reference-engine errors.
- [Episodic study results](../studies/episodic-v3/results/MAIN-RESULTS.md):
  25974 episodes and 207791 actual inner runs. Only three problems meet the
  coverage target for both answer sets; five capped problems skip validation.
  The validated `misc3 best_a` reference flags 24/100 outside port winners,
  versus 0/1000 in reference validation. Its cause remains unestablished.

The next manuscript revision must report these limitations and distinguish
construction qualification from held-out coverage validation. Completion of
the episodic study does not establish port fidelity or replace memory-specific
controls, defect interventions, or learning-efficiency evidence. See
[STUDY-STATUS.md](STUDY-STATUS.md) for the publication status of both studies.

## Current Files

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
- [references.bib](references.bib): all 35 verified references.
- [REFERENCE-AUDIT.md](REFERENCE-AUDIT.md): reference identities and source links.
- [number-audit.json](number-audit.json): recomputed quantities and input hashes.
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
matched-cap episodic study has since completed, as linked above; its results
have not yet been incorporated into this draft. Memory-specific controls
remain an evidence gap for the intended learning-system contribution.

The audit now uses files in `data/`, not a sibling repository. All copied data
are unchanged historical records, not newly generated observations. No new
engine experiment or author declaration was invented. Misleading statistical
and replay comments were corrected without changing comparison behavior.

## Rebuild

Commands below run from **this `academic` directory**. The audit and its tests
need Python 3.9 or later and no third-party Python modules:

```sh
python3 tools/audit_numbers.py
python3 tools/audit_episodes.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

To regenerate LaTeX and the four data tables, install Pandoc (the tested version
is 3.11), then run:

```sh
python3 tools/convert_manuscript.py --pandoc pandoc
```

This reads `manuscript.md` and the bundled measurements. It does not read or
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

## Evidence and Submission

The portable [Metacat patch bundle](../Metacat/README.md) provides reconstructible
modified source. It does **not** establish which historical build generated the
374,500-run reference sample. Independent held-out calibration, empirical
baseline comparisons, and stronger sampled-build/intervention provenance remain
open. Their absence is disclosed in the manuscript and revision checklist.

The manuscript has an anonymous byline, empty PDF author metadata, no named
acknowledgements, and no author-identifying repository URL. The public
repository is not anonymous. The author must review all intended uploads for
anonymity, scientific accuracy, and required disclosures; the analysis ZIP alone
is not a complete anonymous experimental artifact.

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
