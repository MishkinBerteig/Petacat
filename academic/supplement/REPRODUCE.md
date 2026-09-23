# Reproduction Commands and Dependencies

Run commands from the extracted review bundle's root. Do not run `prepare`,
`run`, `export`, or a general engine test suite to reproduce the paper tables.
The commands below operate on saved data only.

## Standard-Library Verification

Requirements: [Python 3.11+](https://www.python.org/downloads/), macOS/Linux or
[WSL Ubuntu](https://learn.microsoft.com/en-us/windows/wsl/install), and about
1 GB of available RAM. No external Python modules are needed.

```sh
python3 verify.py
```

Equivalent core commands:

```sh
python3 academic/tools/audit_numbers.py
python3 academic/tools/audit_episodes.py
python3 academic/tools/audit_support_study.py
python3 academic/tools/audit_episodic_study.py
python3 academic/tools/investigate_misc3.py --output academic/investigations/misc3-episodic-audit.json
python3 studies/episodic-v3/study.py verify-export studies/episodic-v3/results/main
python3 -m unittest discover -s academic/tests -p 'test_*.py'
python3 -m unittest discover -s Metacat/tests -p 'test_*.py'
```

The wrapper checks the original audit output hashes after regeneration. The
episodic verifier compares the full recalculated analysis with the recorded
one. Missing frozen supports, errors, and unanswered episodes remain distinct.

## Full Single-Run Reanalysis

Use [Python 3.14](https://www.python.org/downloads/) and a new
[virtual environment](https://docs.python.org/3/library/venv.html). The recorded
study used Python 3.14.6. The bundled requirements pin NumPy 2.5.1, SciPy 1.18.1,
and pytest 9.1.1. Installation references:
[NumPy](https://numpy.org/install/), [SciPy](https://scipy.org/install/),
[pytest](https://docs.pytest.org/en/stable/getting-started.html).

```sh
python3.14 -m venv .venv-review
.venv-review/bin/python -m pip install -r studies/support-v1/requirements.txt
.venv-review/bin/python verify.py --full-single-run
```

This includes the quick checks, safely extracts all four scientific archives
to a temporary directory, verifies the original file inventories and inheritance,
and reruns the saved-observation analysis, including the Monte Carlo frequency
comparisons. It checks byte-identical `analysis.json` and `RESULTS.md` outputs.
Allow several minutes and at least 2 GB of temporary disk space. Runtime varies;
these are analysis costs, not a new 969,000-run experiment. Different numerical
library versions may not reproduce the exact hashes. No GPU or Docker is used.

For archive integrity and extraction without numerical reanalysis:

```sh
python3 studies/support-v1a/release_data.py verify --release studies/support-v1a/data
```

Add `--extract review-data` to preserve the extracted files. The destination
must not already exist. Do not modify the bundled archives or their manifests.

## Reconstruct the Reference Without Executing It

Install [Python](https://www.python.org/downloads/),
[curl](https://curl.se/), and [patch](https://www.gnu.org/software/patch/).
The complete platform-specific dependency instructions are in
[Metacat/README.md](Metacat/README.md). From the bundle root:

```sh
python3 Metacat/tools/reconstruct.py --output Metacat/build/source
python3 Metacat/tools/reconstruct.py --verify Metacat/build/source
```

The helper downloads [Metacat 1.2](https://science.slc.edu/jmarshall/metacat/Metacat-1.2.tgz),
checks the upstream checksum, applies both patches without fuzz, and verifies
every reconstructed file and executable bit. To work offline, download the
archive separately and pass `--archive /path/to/Metacat-1.2.tgz` with `--output`.
Reconstruction does not run Scheme or change the measured data. It does not
establish the sampled identity of the older historical repair-cycle artifacts.

Actually starting the reference additionally requires the documented Chez Scheme
9.5.4/SWL runtime, normally built with [Docker Desktop](https://docs.docker.com/desktop/).
GUI and headless commands are in the Metacat README. They are optional engine
execution, not part of manuscript verification. No new study should silently
append observations to a frozen campaign. A newly built container is not claimed
bit-identical to the original runtime merely because its Dockerfile matches.

## Source and Licensing Boundaries

The source-snapshot ledger compares every included frozen file with the recorded
study hash. Repository ignore files and a GUI screenshot are omitted; two README
files are review replacements. These exceptions are documentation, not modified
engine algorithms, selectors, protocols, or analysis code. The port engine and
seed data are included for inspection, not as a complete UI/database deployment.

Metacat's original source remains external, with its own license. The bundled
GPL license and diffs remain distinct from the port's existing MIT license in
`LICENSE.md`. The review copy temporarily anonymizes its copyright holder's
displayed name, preserving the terms and upstream attribution; it does not
reassign copyright. No third-party runtime or dependency source is redistributed.
