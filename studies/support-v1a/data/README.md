# Full Support Study Data

This is the complete scientific-data release for `support-v1a`, plus its
interrupted parent study, excluded pilot, and unsuccessful initial preflight.
It contains the actual ordered observations and attempt evidence, not just
aggregate results. No original Metacat source or container image is included.

## Contents

| Archive | Extracted directory | Contents |
| --- | --- | --- |
| `main.tar.gz` | `main/` | Completed 969,000-observation campaign; every chunk, raw observation, attempt, generated collector, receipt, manifest, protocol, analysis, and corrected preflight. |
| `parent.tar.gz` | `parent/` | Original interrupted study, including its 643,250 completed observations and the 238-row prefix of the failed chunk. |
| `pilot.tar.gz` | `pilot/` | All 570 excluded pilot observations and their provenance. |
| `aborted-preflight.tar.gz` | `aborted-preflight/` | First continuation preparation and the preflight that exposed the wrapper's `newline` shadowing problem, before any main continuation execution. |

**Do not concatenate observations from these archives.** The parent and
aborted preparation contain copies of observations inherited by `main/`.
Those are provenance copies, not independent replications. The corrected
preflight's 375 executions are also excluded from main-study denominators.
The first failed attempt and all replay attempts remain available for audit.

The main campaign has 380,000 construction observations, 570,000 held-out
validation observations, and 19,000 port observations, in 3,876 completed
chunks. Its three reference engine errors are retained as `*ERROR*`; none
were discarded or relabeled as ordinary answers. There were no port engine
errors. Construction remains frozen and does not absorb validation discoveries.
See the [three-failure investigation note](../../../Metacat/KNOWN-FAILURES.md)
for exact reproducers and the [amended protocol](../README.md) for interpretation.

## Download, Verify, and Extract

These archives are ordinary Git files, not Git LFS pointers. Obtain the
repository using Git or GitHub's Download ZIP. Use Python 3.9 or newer for
archive verification; the complete analysis uses the study's Python 3.14
environment described below. Run these commands from the repository root:

```sh
python3 studies/support-v1a/release_data.py verify \
  --release studies/support-v1a/data \
  --extract studies/support-v1a/output/public-release
```

Choose a new extraction path: the verifier refuses to overwrite an existing
directory. It checks archive SHA-256 hashes, every published file's original
hash, safe archive paths, file ownership metadata, and private-content patterns
before reporting success. Allow about 1 GB of free disk space for extraction.
All archive members are ordinary files, with normalized owners and timestamps.

Read `main/RESULTS.md` for the generated summary and `main/analysis.json` for
per-input and per-batch results. The JSONL files under `main/chunks/` contain
the ordered main observations. `complete.json` receipts identify admitted
attempts and their artifact hashes. Error details and raw Scheme output are
retained beside each attempt. No engine or Docker setup is needed to inspect
these files or verify the archive hashes.

## Reproduce the Analysis Without Running Metacat

Install [Python 3.14](https://www.python.org/downloads/) and follow the
[study environment instructions](../../support-v1/README.md). On Windows,
use the [WSL route](../../../Metacat/README.md#windows-use-ubuntu-through-wsl-2)
because the shared study collector imports Unix process-locking support.
From the repository root:

```sh
python3.14 -m venv .venv-study
.venv-study/bin/python -m pip install -r studies/support-v1/requirements.txt
.venv-study/bin/python studies/support-v1a/release_data.py verify \
  --release studies/support-v1a/data \
  --study-tools studies/support-v1a
```

This extracts to a temporary directory, verifies the original observation
identities and scientific receipts, checks inheritance and the excluded pilot,
then reruns the full analysis. It requires **no Metacat execution, Docker,
GPU, private configuration, or access to the original study machine**.
Success includes byte-identical `analysis.json` and `RESULTS.md` hashes. The
temporary extraction is removed afterward; use `--extract` with a new path
to retain the files instead. The archived numeric/runtime versions are recorded
in the scientific manifests; different analysis-library versions may differ.

The shared collection modules remain those used in the study. Do not invoke
`collect.py run` on this public export: its operational configuration is
intentionally absent, and reproducing an analysis is not resuming collection.

## Integrity and Privacy

`release.json` records every archive and each original scientific-file hash.
`VALIDATION.json` records the release-index hash, exporter hash, observation
totals, parent-inventory verification, and reproduced analysis/report hashes.
The exporter is [release_data.py](../release_data.py); its regression tests are
[test_release.py](../test_release.py).

Scientific file contents are **byte-for-byte unchanged**, including all
receipts, raw data, manifests, exception evidence, and original analysis files.
Only the explicitly listed operational root files are excluded: private
`local.json`, coordinator locks, launcher metadata, and supervisor logs where
present. Per-attempt logs remain included. Original inventory files may retain
hashes of excluded operational files as part of the original integrity record;
their private contents are not published. Archive-level ownership and timestamps
are normalized so they do not disclose local account information.

The release was checked for private account paths, network addresses, local
hostnames, and Docker image identifiers, and reanalyzed after those operational
files were excluded. No scientific checksum was rewritten to conceal a change.
The original study directories remain untouched. The generated `collector.ss`
files are project-owned test drivers, not upstream Metacat engine source.

## Interpretation

This campaign used fresh memory for every run, not memory-retained learning
episodes. Its error-handling policy was amended after the first observed
reference failure; this is not an unchanged prospective experiment. A reference
describes observed behavior, not guaranteed correct behavior. A port is not
required to reproduce reference crashes, and an unseen port outcome is not
automatically a defect. See the protocol for statistical assumptions and costs.
