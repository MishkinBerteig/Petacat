# Build and Artifact Verification

2026-09-06 UTC (2026-09-05 EDT). Amortization and expanded learning-mode revision
generated with Pandoc 3.11 and built with
Tectonic 0.17.0. The canonical source is [manuscript.md](manuscript.md).

## PDF Checks

- PDF: 16 pages, US Letter (612 by 792 points), PDF 1.5, unencrypted.
- All 22 used fonts are embedded; no bitmap/Type 3 fonts.
- All 35 bibliography entries are rendered; all 35 source citation keys are present.
- No undefined citations, unresolved section references, missing-glyph warnings, or overfull/underfull boxes in the final build.
- The byline is anonymous, PDF author metadata is empty, and PDF link annotations contain no identifying Petacat repository URL.
- Every rendered page was visually inspected, and all affected pages were re-rendered and checked after final text corrections. The episodic table fits on one page; the notation and benchmark appendices share a page with both tables intact and no orphaned heading. References start on a fresh page. Text bounding boxes were checked against the 6.5-inch horizontal text area and the page boundary.
- Official `tmlr.sty`, `tmlr.bst`, and `fancyhdr.sty` match the downloaded ZIP byte for byte. The historical dated Markdown is preserved with a superseded-draft notice; the new manuscript contains the substantive revisions.

Nonfatal compiler diagnostics remain: Tectonic reports a legacy UTF-8 byte in
its bundled `lineno.sty`, and `amsmath` reports the foreign command
`\atopwithdelims`. These did not produce a visible missing glyph or text
overflow. Some mathematical font glyphs have imperfect PDF text extraction;
mathematical expressions were checked visually. This is not a PDF/A or
accessibility certification.

## Standalone Bundle Checks

- The [source ZIP](support-set-oracles-tmlr-source.zip) contains 12 files
  (47,127 bytes): build instructions, `.tex`, `.bib`, `.bbl`, four generated tables, three
  unmodified style files, and the template license. It rebuilt successfully
  after extraction into a clean temporary directory, without Pandoc or the
  repository. Its rebuilt PDF has identical extracted text to the delivered PDF.
- The [analysis ZIP](support-set-oracles-analysis.zip) contains 12 files
  (294,696 bytes):
  instructions, data documentation, four unchanged archived JSON data files,
  two arithmetic reports, two audit scripts, and two test files. In a separate
  clean directory, the audits reproduced `number-audit.json` and
  `episode-audit.json` byte for byte and all 14 tests passed using only the
  Python standard library.
- Both archives passed ZIP integrity and path checks. Neither contains the
  named historical draft, public repository documentation, original Metacat
  source, or private machine/network identifiers. Both are below 100 MB.
- These are a manuscript build bundle and an arithmetic supplement, not a
  complete experimental code artifact or independent replication.

## Test Results

Run from the repository root:

```sh
python3 -m unittest discover -s academic/tests -p 'test_*.py'
python3 -m unittest discover -s Metacat/tests -p 'test_*.py'
.venv/bin/python -m pytest tests/unit/test_compare_harness.py tests/module/test_group_image_direction.py -q
```

Results: all 14 arithmetic tests passed for this revision and again in the
extracted bundle. The earlier 14 reconstruction/packaging tests and 23
targeted CPU tests passed before the remote study launched. That earlier
pytest process exited successfully but reported
a Metal-device-unavailable exception in an exit callback in the restricted
environment. No GPU execution or fresh stochastic engine results are claimed
by this document. The separately running remote study is recorded in
[STUDY-STATUS.md](STUDY-STATUS.md), and none of its unfinished results are used here.
Build and packaging commands are in [README.md](README.md).

The additional memory regression definitions described in
[EPISODIC-IMPLEMENTATION-REVIEW.md](EPISODIC-IMPLEMENTATION-REVIEW.md) were
inspected, not executed for this manuscript expansion. They are not included
in the count of 14 arithmetic tests or claimed as newly passing engine tests.

## SHA-256 Checksums

Template archive SHA-256:

```text
48f9f972cc812d2cfc8032a78578c2f5d8939b92fbd4f61095e8cbeb3394f92d
```

Final manuscript PDF SHA-256:

```text
2363f50bb8df3a3be2baef615c2ecd7ab1e1d63b15d505c858c19ef523bb13c2
```

Source ZIP SHA-256:

```text
36048ddb3de6c8a545377b7edd225c80680bdc16ae8128bfece670d76cb56505
```

Analysis ZIP SHA-256:

```text
c187cba8a86df98b858c082ae5f3d7db2e9ac2c04076d76b7baa7f195cb64e52
```

Build verification does not resolve the remaining scientific and provenance
gaps in [REVISION-STATUS.md](REVISION-STATUS.md). It does not establish
submission readiness. No OpenReview submission was made.
