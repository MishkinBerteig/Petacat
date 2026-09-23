# Anonymous Initial Submission to TMLR

Checked 2026-09-07 against the public
[OpenReview submission invitation](https://api2.openreview.net/invitations?id=TMLR%2F-%2FSubmission),
the [TMLR author guidelines](https://jmlr.org/tmlr/author-guide.html), and the
[official style template](https://github.com/JmlrOrg/tmlr-style-file/blob/main/main.tex).
The public form definition is preserved in
[submission/openreview-invitation.json](submission/openreview-invitation.json).
No account was accessed and no submission was made.

## Exact Uploads

| OpenReview field | File or selection |
| --- | --- |
| PDF | [support-set-oracles-tmlr.pdf](support-set-oracles-tmlr.pdf), 187,278 bytes |
| Submission Type | Long submission (more than 12 pages of main content) |
| Supplementary Material | [support-set-oracles-submission-supplement.zip](support-set-oracles-submission-supplement.zip), 77,920,750 bytes |
| Beyond PDF | Leave empty; this is not an interactive-webpage submission. |

The form allows a 50 MB PDF and one supplementary attachment up to 100 MB.
The paper has 18 main-text pages, with references starting on page 19, and
27 pages overall. Long submissions are permitted, though review may take longer.
The single supplement contains the verified experimental and LaTeX source ZIPs,
an anonymous entry-point README, and a checksum manifest. Do not upload the older
analysis-only ZIP instead; its evidence is already in the experimental bundle.

Title: **Large References, Small Checks: Oracle-Guided Porting of a Stochastic
Learning System**. The generated [plain-text abstract](submission/abstract.txt)
matches the paper. Title and abstract fit the form's 250- and 5,000-character
limits, respectively. Neither file supplies private form responses.

## Submission Mode, Not Preprint Mode

The manuscript uses `\usepackage{tmlr}` without `preprint` or `accepted`.
The anonymous byline and review header are the official submission format.
No author names, affiliations, identifying acknowledgements, acceptance date,
or published OpenReview link belong in this version. PDF author metadata is
empty. Its text, metadata, links, and intended supplementary contents pass
direct-author and local-identifier checks. The current style files match a
fresh download of the official template. Appendices follow the references.

Anonymity concerns the files and reviewer-visible content. The initial form
separately requires author profiles and restricted-access competing-interest
and human-subject fields. Its declared readers for these fields exclude
reviewers and the public. These are not instructions to add identifying
statements to the PDF, and no responses were inferred or entered. The
[author guide](https://jmlr.org/tmlr/author-guide.html) makes this distinction.

## Verification and Boundaries

[submission-readiness.json](submission-readiness.json) records the format,
field-limit, mode, metadata, and page checks.
[submission-build.json](submission-build.json) identifies the exact upload
bytes and inner bundles. The author's process-novelty clarification updates the
abstract, introduction, related work, and conclusion; the PDF, LaTeX source ZIP,
and outer attachment are rebuilt and rechecked. Scientific results, frozen
source snapshots, all 35 references, and the experimental ZIP remain unchanged.
The paper and supplement retain their stated scientific and provenance limits;
technical readiness does not guarantee editorial acceptance. Direct-identifier
checks are not a guarantee against deliberate external fingerprint matching.

The original Metacat source remains external; only its reconstruction diffs
are supplied. This audit does not change the study, infer personal declarations,
or prepare a named preprint or camera-ready version. The author still has the
requested final manual review. No commit, push, or upload is authorized by this
technical audit.

To rebuild the outer attachment from the current verified inner bundles:

```sh
python3 academic/tools/package_submission.py
python3 -m unittest discover -s academic/submission/tests -p 'test_*.py'
```

Add repeated `--forbid` arguments to the builder for the private identifier
scan. The upload manifest preserves the inner ZIP hashes unchanged.
