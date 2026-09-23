# Restyled Anonymous Submission Draft

This is the intended submission version, rewritten on 2026-09-07 at the
author's request. It uses concrete examples, plain-language definitions,
direct questions, shorter sentences, and explicit explanations of what
the evidence does and does not show. Personal anecdotes, identifying
affiliations, and the supplied voice profile are not part of the submission.

The title is now **Large References, Fast Checks: Oracle-Guided Porting
of a Stochastic Learning System**. The original manuscript, PDF, LaTeX,
source bundle, and earlier submission attachment remain unchanged.
The `final` filename does not indicate final author approval. **Manual
review and explicit approval are still required before any commit or push.**
Nothing has been uploaded or submitted.

Author feedback clarifies the two directions of comparison: Good-Turing-guided
reference collection supports unexpected-answer flags, while p50 heads support
missing-common-answer flags. Fast iteration is the objective, with automated
comparison replacing repeated manual distribution inspection. Native episode
judgments make selected conceptual behaviour testable without a fixed expected
answer; neither a measured speedup nor complete conceptual equivalence is
claimed. The introduction uses a qualified fuzzy-classifier view and links
Wikipedia's non-academic explanation in a footnote. The newer episodic study
remains support-only, not a new p50 experiment.

Further author feedback names $S_x$ explicitly as the observed support set
for problem $x$, removes the discarded historical anecdote and peripheral
preflight detail. The author's subsequent instruction removes all discussion
of statistical distribution comparisons from the manuscript, including its
tables, appendices, and supporting citation. The routine design remains
Good-Turing-guided support collection and p50/support checks. A TDD comparison
introduces the new penultimate
section, **Potential Application of the Process**, with proposed uses beyond
porting and an explicit distinction between regression protection and tests
specifying new behaviour. [approved-content-changes.json](approved-content-changes.json)
records the narrowly authorized changes to the manuscript's build checks.

Section 10 also proposes building a human-derived oracle from a speaker's
characteristic phrasing patterns to test a fine-tuned language model. It
uses p50 for common-pattern selection and a sampling-appropriate discovery
estimate for reference collection, without prescribing repetition rates.
This is a future application, not an additional experimental result.

On 2026-09-08, an author-supplied style diff was reviewed before application.
The stylistic edits are applied with 38 protected passages retaining the
scientific qualifications or prior author direction. These include the p50
threshold, complete-episode denominator, tied-winner handling, historical
evidence, and cost limits. [The review](STYLE-REVIEW-2026-09-08.md) explains
each exception; its companion JSON preserves proposed and retained text.
The review records are not part of the anonymous source or experimental bundle.

Appendix pagination was checked on 2026-09-08 against the author guidelines
and official template. TMLR requires appendices after references, but does not
mandate a separate starting page for each appendix. For consistency with B--E,
the source now also inserts page breaks before A and F. Every appendix starts
at the top of a fresh page: A on 25, B on 26, C on 28, D on 29, E on 30, and
F on 31. Only page-break commands changed in the manuscript for this adjustment.

The latest regeneration includes the author's subsequent direct introduction
and later-section edits and the reference diff supplied on 2026-09-09.
That diff changes three prose passages and four bibliography records: it
removes the Chao (1984) URL, adds the Segura et al. (2016) DOI, and adds
issue numbers for O'Neill (2022) and Gerhold and Stoelinga (2018).
The build check permits exactly these metadata corrections while preserving
the earlier bibliography. The PDF, LaTeX, source bundle, supplementary
attachment, and verification records have been refreshed.

[The final qualitative review](QUALITATIVE-REVIEW-2026-09-09.md) identifies
one recommended scientific-wording correction, not a need for another study.
That proposed correction is not applied pending author approval. The review
record is local documentation, not part of the anonymous submission bundles.

## Files for Review and Submission

| Purpose | File |
| --- | --- |
| Intended submission PDF | [support-set-oracles-final.pdf](../support-set-oracles-final.pdf) |
| Editable Markdown | [support-set-oracles-final.md](../support-set-oracles-final.md) |
| Generated LaTeX | [support-set-oracles-final.tex](../support-set-oracles-final.tex) |
| Standalone Markdown/LaTeX source bundle | [support-set-oracles-final-source.zip](../support-set-oracles-final-source.zip) |
| Single OpenReview supplementary attachment | [support-set-oracles-final-supplement.zip](../support-set-oracles-final-supplement.zip) |
| Plain-text abstract for the form | [abstract.txt](abstract.txt) |
| Build hashes and preserved-file checks | [build.json](build.json), [preserved-draft.json](preserved-draft.json) |
| Submission-format verification | [verification.json](verification.json) |

For this version, use the final PDF and final supplement, not the earlier
`support-set-oracles-tmlr.pdf` and submission-supplement ZIP.

The new attachment contains the new source bundle and the unchanged
experimental bundle. There is no need to upload them separately. The source
bundle includes Markdown, generated LaTeX, references, the twelve audited
tables, the official template, and rebuilding instructions. No original
upstream Metacat source is added.

## TMLR Checks

Checked against the current [author guidelines](https://jmlr.org/tmlr/author-guide.html),
[editorial policies](https://jmlr.org/tmlr/editorial-policies.html),
[public OpenReview form](https://api2.openreview.net/invitations?id=TMLR%2F-%2FSubmission),
and a fresh [official style download](https://github.com/JmlrOrg/tmlr-style-file/archive/refs/heads/main.zip).

- The PDF uses the official anonymous submission mode, not `preprint` or
  `accepted`. Author metadata is empty, and direct personal/local-identifier
  checks pass for the PDF, links, and supplementary contents.
- It has 21 pages of main text and 31 pages overall, with references before
  appendices. Select **Long submission (more than 12 pages of main content)**.
  TMLR permits longer papers but asks that their length be justified and
  warns of possible review delays. The rewrite adds explanations and worked
  examples rather than changing margins, fonts, or scientific results.
- The PDF is 195,343 bytes, below the 50 MB limit. The single supplement is
  77,954,190 bytes, below 100 MB. The title is 84 characters and the abstract
  is 1,921 characters (283 whitespace-delimited words), within the form limits.
- Leave **Beyond PDF** empty; it is for an interactive-webpage submission,
  not the LaTeX or experimental attachment.
- Required private author/profile and declaration fields remain for the
  author to complete. Their restricted form visibility does not justify
  putting identifying information in the anonymous manuscript. No private
  responses, account eligibility, or upload actions were supplied here.

These are technical submission checks, not a promise of editorial acceptance
or a guarantee against deliberate external identity fingerprinting.

## Accuracy and Reproduction

The rewritten text cites 34 scholarly works and uses 12 generated data tables.
It has nine displayed equations. Author-directed removals affect one cited
work, one section, one complete table, and selected columns/rows and prose;
the potential-applications section is added. Raw counts in the retained tables
match the archived evidence. Final tables and bibliography live separately
under `final/`, and only these are packaged in the manuscript source ZIP.
Numerical inventory
checks allow only the recorded editorial removals; they supplement, not replace,
contextual reading. Native winner definitions, tie handling, denominator
exclusions, retained failures, confidence allocation, historical evidence
limits, process-novelty boundaries, and unresolved causes remain explicit.
The methods, results, and appendices were rewritten rather than replaced
with an abbreviated summary. Related work follows the method explanation.

All 29 monitored earlier-draft and evidence files are byte-identical to the
pre-rewrite snapshot. All 90 tests pass: 51 academic, 14 reconstruction-helper,
five existing submission-package, and twenty rewrite-build tests. No engine
experiment or full single-run numerical reanalysis was performed.

All pages pass text-bound checks, all 24 fonts are embedded, and no overfull
boxes, missing characters, or undefined references/citations remain. The
rendered page overview and selected full-size pages were inspected, including
the opening, method examples, main results, conclusion, and complete final
benchmark table. Seven underfull vertical-box diagnostics and existing template
diagnostics remain nonfatal; no template metrics were altered.

A clean extraction of the actual final attachment was rebuilt from its
Markdown with Pandoc and Tectonic. The generated LaTeX is byte-identical,
and the PDF's extracted text is identical to the delivered version.

## Rebuild in This Repository

Install [Pandoc](https://pandoc.org/installing.html) and
[Tectonic](https://tectonic-typesetting.github.io/en-US/install.html).
The verified versions are Pandoc 3.11 and Tectonic 0.17.0. From the repository
root, with these executables on `PATH`:

```sh
python3 academic/tools/build_final.py
python3 -m unittest discover -s academic/final/tests -p 'test_*.py'
```

The builder accepts `--pandoc` and `--tectonic` paths. Repeated `--forbid`
arguments add private terms to the supplement scan. It uses the existing
saved-data audits, table generator, Pandoc conversion, official TMLR template,
and Tectonic, but writes only the new manuscript outputs. A preservation
manifest rejects changes to the earlier draft and shared scientific evidence.
The approved-content manifest permits only the specified prose-inventory,
reference, table, equation, and section changes. An additional check scans
Markdown, generated LaTeX, final tables, references, source-bundle contents,
and PDF text for the removed discussion. Relevant Good-Turing and p50
terminology, outcome counts, and reference-coverage validation remain.

To repeat the format audit, download the public invitation JSON and style
ZIP, then pass their paths:

```sh
python3 academic/tools/verify_final.py \
  --invitation /path/to/invitation.json --style /path/to/style.zip
```

The source ZIP has independent build instructions and does not require
the full repository just to regenerate the paper.
