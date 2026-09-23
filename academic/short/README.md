# Regular-Length Anonymous Submission Candidate

The author approved a separate version with no more than 12 main-content
pages on 2026-09-09. The compiled candidate has **ten main-content pages**,
including the title, abstract, and three main-text tables. References occupy
pages 11-13; appendices occupy pages 14-32. There are 32 pages overall.
The shorter main text does not mean the detailed evidence has been discarded.

The title remains **Large References, Fast Checks: Oracle-Guided Porting
of a Stochastic Learning System**. The official style and the conversion
template are unchanged. No font, margin, or spacing reduction was used.
The filename describes the maximum, not an assertion that all 12 pages
must be filled. The actual layout leaves room for author revisions.

**This is a candidate for manual review, not final author approval.**
Nothing has been committed, pushed, or submitted. Neither analogy engine
was run. The previous 21-page-main-text draft remains unchanged.

## Files

| Purpose | File |
| --- | --- |
| Current PDF for review | [support-set-oracles-12-page.pdf](../support-set-oracles-12-page.pdf) |
| Editable Markdown | [support-set-oracles-12-page.md](../support-set-oracles-12-page.md) |
| Generated LaTeX | [support-set-oracles-12-page.tex](../support-set-oracles-12-page.tex) |
| Standalone manuscript source | [support-set-oracles-12-page-source.zip](../support-set-oracles-12-page-source.zip) |
| Single supplementary attachment | [support-set-oracles-12-page-supplement.zip](../support-set-oracles-12-page-supplement.zip) |
| Form abstract | [abstract.txt](abstract.txt) |
| Checks and artifact hashes | [verification.json](verification.json) |
| Earlier-file preservation hashes | [preserved-drafts.json](preserved-drafts.json) |
| Relocation and scientific review | [REVISION-NOTES.md](REVISION-NOTES.md) |

The source ZIP contains the Markdown, LaTeX, bibliography, twelve audited
tables, official style, and instructions. Table captions and headings now use
"solutions" consistently; their values are unchanged. The compact misc3
table is in the Markdown and is checked against the saved episodic analysis.
The outer attachment contains this source ZIP and the unchanged experimental
ZIP; upload the combined attachment, not a second copy of each inner ZIP.

The preserved [support-set-oracles-final.pdf](../support-set-oracles-final.pdf)
is the earlier long draft. Do not mix its source or supplementary attachment
with this candidate. Older review documents describe that earlier version.

## What Changed

The method, statistical interpretation, and cost discussion are consolidated.
The repair history and native-winner episodic study remain central. Repeated
explanations are shortened, while detailed calculations, protocols, tables,
memory records, and related work move to appendices. The penultimate potential
applications section retains TDD and the consenting-speaker example; additional
software-development examples appear in Appendix J.1.

The main text still states incomplete historical provenance, fixed-budget
single-run collection, the versioned response to engine failure, reused pilot
prefixes, independent validation, conditional winner denominators, failed and
skipped coverage, and the unresolved cause of misc3. It does not introduce a
new episodic p50 experiment, a measured speedup, or proof of learning fidelity.

The 2026-09-10 readability pass qualified every remaining use of "this".
The 2026-09-11 rewrite follows the author's new abstract, foregrounding
practical port improvement, asymmetric sampling cost, and the testing
process's contribution. Terms are explained before the results, and
"solutions" and "testing process" are consistent through the appendices and
tables. The body formalizes a possibly multi-valued relation over countable
problem and solution sets. Study counts stay in the body, not the abstract.
See the latest entry in [REVISION-NOTES.md](REVISION-NOTES.md).

## Verification

- Main-content limit enforced at build time: 10 pages, maximum 12. References
  must begin on a new page, so main text cannot be hidden on a reference page.
- All 34 bibliography records, nine displayed equations, and twelve audited
  table files are retained. The new misc3 summary matches archived data.
- All 108 tests pass: 51 academic, 14 reconstruction-helper, five submission
  packaging, 20 earlier rewrite, and 18 regular-length build tests. Table
  wording changes are explicitly restricted; changed values are rejected.
- All 64 monitored earlier-draft and evidence files are byte-identical.
  The experimental ZIP retains SHA-256
  `08cb16fee2840f73dfdd78033a38c0c85eb9ac1ceba4432c1724928d2a327713`.
- Anonymous mode, empty author metadata, direct private-identifier scans,
  official style bytes, PDF text bounds, and all 24 embedded fonts pass.
  No overfull boxes, undefined citations/references, or missing characters
  remain. Nonfatal template and underfull-box diagnostics persist.
- All-page visual inspection and closer review of the main narrative,
  summary tables, references, and appendix starts found no clipping or overlap.
- A clean extraction of the actual source attachment rebuilds from Markdown
  to byte-identical LaTeX and identical extracted PDF text.

For this PDF, the checked OpenReview category is **Regular submission
(no more than 12 pages of main content)**. Leave Beyond PDF empty.
The PDF and the approximately 78 MB supplement meet the checked form limits.
Private declarations, profile eligibility, author quota, manual review, and
the submission action remain the author's responsibility. Technical checks
do not guarantee editorial acceptance or prevent deliberate external identity
fingerprinting of scientific records.

## Rebuild

Install [Pandoc](https://pandoc.org/installing.html),
[Tectonic](https://tectonic-typesetting.github.io/en-US/install.html), and
[Poppler](https://poppler.freedesktop.org/) for PDF checks. The checked versions
of the converters are Pandoc 3.11 and Tectonic 0.17.0. Download the public
OpenReview invitation and official style ZIP to a temporary directory:

```sh
curl -fL 'https://api2.openreview.net/invitations?id=TMLR%2F-%2FSubmission' -o /tmp/tmlr-invitation.json
curl -fL https://github.com/JmlrOrg/tmlr-style-file/archive/refs/heads/main.zip -o /tmp/tmlr-style.zip
python3 academic/tools/build_short.py --invitation /tmp/tmlr-invitation.json --style /tmp/tmlr-style.zip
python3 -m unittest discover -s academic/short/tests -p 'test_*.py'
```

The builder accepts explicit `--pandoc` and `--tectonic` paths. It uses the
existing Pandoc/TMLR/Tectonic conversion process and saved tables, writing only this
candidate's outputs and its verification record. A failed page limit stops
packaging. The PDF may still exist for diagnosis, but a failed build is not
a verified submission release.
