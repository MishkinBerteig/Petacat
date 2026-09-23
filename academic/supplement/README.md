# Review Supplement: Large References, Small Checks

**Large References, Small Checks: Oracle-Guided Porting of a Stochastic Learning System**

Start here after extracting the ZIP into a new directory. This package supports
inspection and reanalysis of the paper's saved evidence. It does not require
running Metacat, running the port, a GPU, Docker, or access to the study host.
No collection command is part of the verification workflow.

## Quick Check

Install [Python](https://www.python.org/downloads/), version 3.11 or newer.
Open a terminal in the extracted directory and run:

```sh
python3 verify.py
```

Use macOS, Linux, or [Ubuntu through WSL on Windows](https://learn.microsoft.com/en-us/windows/wsl/install).
Some preserved study modules import Unix process-locking support. On Windows,
run the commands inside Ubuntu, not PowerShell. The standard-library checks
need no Python packages. They verify bundled file hashes, recompute all five
paper audits and thirteen data tables, test the audit/reconstruction helpers, and reproduce the episodic
study's stopping decisions, qualification bounds, and frequencies. They do not
reconstruct missing native states or rerun the single-run permutation test.

For the complete single-run reanalysis, follow [REPRODUCE.md](REPRODUCE.md).
That optional step uses the recorded NumPy/SciPy versions and all saved raw
observations, but still executes neither engine.

## Evidence Map

| Paper evidence | Location |
| --- | --- |
| Historical repair-cycle counts and endpoint audit | `academic/data/`, `academic/number-audit.json`, `academic/episode-audit.json` |
| Complete 969,000-observation single-run campaign, parent and excluded preflights | `studies/support-v1a/data/` |
| Lightweight single-run table audit | `academic/support-study-audit.json` |
| All 25,974 episodic observations, frozen supports, protocol, seed plan, and validation | `studies/episodic-v3/results/main/` |
| Reused 4,000-episode pilot and separate v3 preflight | `studies/episodic-v2/results/pilot-02/`, `studies/episodic-v3/results/preflight-01/` |
| All-input episodic comparisons and complete frequency vectors | `academic/episodic-study-audit.json` |
| Detailed `misc3` evidence and 24-event ledger | `academic/investigations/MISC3-EPISODIC.md` |
| Frozen port engine, selectors, collection and analysis code | `server/engine/`, `seed_data/`, `studies/` |
| Metacat reconstruction diffs, manifest, dependency and GUI/headless instructions | `Metacat/README.md` |
| Exact package inventory, original hashes, replacements and exclusions | `SUPPLEMENT-MANIFEST.json` |

The separate manuscript source ZIP typesets the paper. This supplement includes
all generated data tables and the converter so the same table-generation code
can be inspected and tested. To rebuild the manuscript, use the separate source
ZIP; Pandoc and TeX are unnecessary for the evidence checks here.

## Boundaries

All scientific exports and source files designated `byte-identical` retain their
original bytes. Historical source identities are not retroactively recovered.
The original episodic reference used during historical development is unavailable;
its stored novelty labels cannot be independently regenerated.

The private episodic attempt archive is not included. The public export includes
selected winners, co-winner descriptions, seed assignments, and summary run
outcomes for every episode, not complete losing-answer or workspace traces.
Original receipt hashes refer to that separate archive; they do not imply the
raw files are bundled. The `misc3` raw-record inspection is a documented prior
audit, not something the public export alone reproduces.

The four single-run archives contain duplicated provenance records. Never
concatenate them as independent samples. The release verifier checks inheritance
and reproduces the admitted campaign separately from pilot/preflight observations.

Author repository links, local machine configuration, private logs, Git history,
and identifying archive owner/timestamp metadata are excluded. Two repository
README files are replaced with review instructions; their original hashes remain
in the source-snapshot ledger. The copyright holder's displayed name is temporarily
anonymized in the review copy of `LICENSE.md`, without changing the MIT terms or
upstream attribution. Technical implementation labels, immutable hashes,
and third-party attribution are preserved. This avoids altering the scientific
hash chains, but cannot prevent identification by deliberate external matching.
Synthetic private paths/IPs in named privacy-regression tests are fixtures, not
study-host information. Final author-level anonymity review remains necessary.

No original Metacat source, upstream tarball, interpreter binary, or container
image is included. Reconstruction downloads the upstream archive separately.
The existing Metacat license and patch attribution are preserved; packaging does
not relicense upstream components. [LICENSE.md](LICENSE.md) supplies the existing
port license and documents the upstream author's permission. The original named
copyright notice must be restored for a nonanonymous release. Software licenses
are not replaced by the manuscript's submission license.

The verification workflow has been tested on macOS with M-series hardware.
Cross-platform feedback is welcome; compatibility elsewhere is not certified.
