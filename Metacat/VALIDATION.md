# Validation

Validated on 2026-09-05. All commands below are run from the directory
containing [README.md](README.md). Follow its reconstruction instructions first.

## Reconstruction

Two independent reconstructions from
[Metacat-1.2.tgz](https://science.slc.edu/jmarshall/metacat/Metacat-1.2.tgz)
applied both patches without fuzz or rejects. All **69 reconstructed files**
matched the SHA-256 hashes and executable flags in [manifest.json](manifest.json).
The directory comparison reported no differences. Reconstruction also passed
using a standalone copy of this bundle without the Petacat application files.

To repeat the comparison after creating `build/source`:

```sh
python3 tools/reconstruct.py --output build/source-check
diff -qr build/source build/source-check
python3 tools/reconstruct.py --verify build/source
python3 -m unittest discover -s tests -p 'test_*.py'
```

All **14 packaging tests passed**. They cover file inventories, checksums, permissions, unsafe
paths, symlinks, corrupt archives, refusal to overwrite an existing destination,
and keeping this bundle free of complete upstream source files and archives.
The portable GUI defaults use the current directory; they do not change the
headless engine's algorithms.

## Headless Smoke Test

Runtime: **Chez Scheme 9.5.4**, `a6le` (`linux/amd64`), with `DISPLAY` unset.
The smoke-test command is in the README. Exit status: **0**. Selected results:

```text
RUN abc abd xyz seed=42 fresh=#t result=(suspended 1364 (dyz))
RUN abc abd xyz seed=42 fresh=#t result=(suspended 1364 (dyz))
RUN abc abd xyz seed=43 fresh=#f result=(suspended 1894 (wyz dyz))
RUN aabc aabd ijkk seed=35 fresh=#t result=(suspended 5396 (ijkkk))
RUN xy z xy seed=5 fresh=#t result=(suspended 2816 (z))
RUN abc aaa xyz seed=42 fresh=#t result=(suspended 5130 ())
RUN abc abd xyz seed=42 fresh=#t result=(capped 1 ())
PASS headless smoke and targeted method checks
```

The test checks fresh-memory repeatability, episodic memory retention, the two
documented crash reproducers, cap handling, and the added object methods.
These are observed results, not ground-truth answers. `suspended` is a
continuation exit, not proof that an answer exists; the whole-string example
above suspended without an answer.

## Episodic Message Check

The preserved `docker/check_messages.py` passed in normal verification mode:
all **152/152 runs**, covering 19 problems with one eight-run episode each,
completed without bad-message errors. Each problem used seeds 200000-200007
and a 100,000-codelet cap, retaining memory within the episode.
This result covers the unchanged headless engine; the portable GUI path
configuration is not loaded by that test.

After building the toolchain as described in the README, repeat with:

```sh
docker run --rm --platform linux/amd64 --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m \
  --mount "type=bind,src=$PWD/build/source,dst=/metacat,readonly" \
  --workdir /metacat --entrypoint env metacat:1.2 \
  -u DISPLAY python3 /metacat/docker/check_messages.py \
  --episodes 1 --runs 8 --jobs 2 --max-steps 100000 \
  --start-seed 200000 --workdir /tmp/metacat-check
```

Final harness output:

```text
all 19 problems clean: no bad messages, every run completed
```

## Second Patch Group: Known-Failure Fixes

Validated on 2026-10-28 for
[patches/fixes/0001-known-failures.patch](patches/fixes/0001-known-failures.patch)
([KNOWN-FAILURES.md](KNOWN-FAILURES.md)).

- **Patching.** The patch applies to the verified reference reconstruction with
  zero fuzz. (When validated it also reversed exactly; the removal has since been taken out of
  the tool, because nothing may take the fixes off.) All 69 files of the fixed tree match
  `reconstructed_files`, overridden by `fixed_files`, in
  [manifest.json](manifest.json).
- **Packaging tests.** The bundle's 20 tests pass
  (`python3 -m unittest discover -s tests -p 'test_*.py'`). They include applying
  the fixes to a copy of `build/source`; none takes the fixes off.
- **Smoke test.** The headless smoke test passes on the fixed tree.
- **The three failures.** On the fixed tree,
  [tests/reproduce-failures.ss](tests/reproduce-failures.ss) reports an ordinary
  return for all three cases: `misc1-20713988` at 2835 codelets,
  `misc1-20716342` at 1981 and `misc3-20226148` at 2152. With the default
  reconstruction, the same commands reproduce the three exceptions.
- **No other run changes.** Petacat's decision-trace recorder
  (`tests/lockstep/metacat/`) logs every random decision of a run, plus a state
  snapshot each update cycle. Traces were recorded on the reference and on the
  fixed tree for 655 runs: all 19 demo problems at seeds 1–30 from fresh memory
  (570 runs), and justify mode for the 17 demo answers at seeds 1–5 (85 runs).
  All 655 pairs are byte-identical apart from the header's revision string.

### 0002-length-group-of-six-or-more.patch

Validated on 2026-11-06 (see [KNOWN-FAILURES.md](KNOWN-FAILURES.md), "A fourth crash").

- **Patching.** On a copy of the tree with the 0001 fixes it applies with zero fuzz.
  The result verifies as the fixed tree (`--verify build/source`, 69 files).
  The bundle's tests pass, including applying the whole group to a copy of `build/source`.
- **The 83 crashes.** All 83 runs that crashed in the stage W sample, recorded again,
  are identical record for record to the same runs recorded without this patch, up to
  the codelet where they crashed, and then run on without a crash.
- **No other run changes.** 266 recorded traces that never crashed (a sample of stage W's
  other runs, covering plain, justify, episode, person-action, Self-watching-off and
  long runs, and `abc -> abd; xyz` seeds 1 to 10) were recorded with and without the patch,
  with the same recorder: all 266 pairs are identical apart from the header's `revision`.

### 0003-non-english-letter-invalid-input.patch

Validated on 2026-11-06 (see [KNOWN-FAILURES.md](KNOWN-FAILURES.md), "A letter outside a to z").

- **Patching.** On a copy of the tree with 0001 and 0002 it applies with zero fuzz; the result verifies as the
  fixed tree (`--verify build/source`, 69 files). The bundle's tests pass.
- **The parser.** The recording of `tokenize-string`, `valid-token-list?` and the others over every Unicode
  scalar value (`tests/lockstep/metacat/record_parser.py`) is identical before and after except for the
  validity of token lists with a letter outside a to z, which go from valid to invalid.
- **No run changes.** 266 recorded traces (the stage W sample and `abc -> abd; xyz` seeds 1 to 10) recorded with and
  without the patch are identical apart from the header's `revision`.
- **The `(mcat ...)` form** refuses a symbol with such a letter ("invalid syntax") and accepts the plain forms.

### 0004-subobjects-group-category-reversal.patch

Validated on 2026-11-07 (see [KNOWN-FAILURES.md](KNOWN-FAILURES.md), "A rule that reverses all the groups of a string").

- **Patching.** On a copy of the tree with 0001, 0002 and 0003 it applies with zero fuzz, and the result equals the
  rebuilt `build/source` file for file. The result verifies as the fixed tree (`--verify build/source`, 69 files). The
  bundle's 20 tests pass.
- **The five crashes.** `pqcd -> cbpo; tugh` seeds 1 and 69, `defpqr -> pondcb; hijstu` seed 79 and `abcxyz -> cbazyx; ijkpqr`
  seeds 35 and 74, recorded again with state snapshots, are identical record for record to the same runs recorded without
  this patch, up to the codelet where they crashed, and then run on without a crash.
- **No other run changes.** 266 recorded traces that never crashed (plain, justify, episode, person-action,
  Self-watching-off and long runs, and `abc -> abd; xyz` seeds 1 to 10) were recorded with and without the patch, with the same
  recorder and state snapshots on: all 266 pairs are identical apart from the header's `revision`.
- **More runs of the three problems.** 720 runs (seeds 1 to 240 of each of the three problems) recorded with the patch ended
  without an error: 305 answers, 393 caps and 22 give-ups.

The fixes are not part of the reference reconstruction behind the published studies, which
the bundle no longer builds or verifies: `--verify` accepts only the patched tree. Results gathered
with the fixes are from a changed engine (KNOWN-FAILURES.md, "When Returning to This Work").

## Limits

The runtime tests used Chez 9.5.4. The GUI container build completed using
cached layers; a clean no-cache toolchain build was not tested. Other Scheme
versions and statistical equivalence to unmodified Metacat were not tested.
The full historical oracle datasets were not regenerated. These bounded
regressions do not exclude failures at untested seeds or establish unchanged
answer probabilities or historical sampled-build attribution.

## GUI Startup and Interaction

**Result: GUI operation verified, with an intermittent startup caveat.** The
reconstructed source and supplied Docker Compose GUI entrypoint were used.
The source and startup sequence were unchanged.

- Chez Scheme 9.5.4 and SWL 1.3 started with the Tcl/Tk 8.6 toolchain.
- Window initialization completed and the entrypoint reported
  `window layout applied`.
- All 13 normally mapped windows were present: Control Panel, Workspace,
  Slipnet, Coderack, Top/Bottom/Vertical Themes, Episodic Memory, Commentary,
  Temporal Trace, Temperature, the Scheme REPL, and the Interaction window.
- A Chromium test browser connected through noVNC. The framebuffer contained
  rendered application windows, not a blank canvas; no browser JavaScript
  exceptions were reported. Browser mouse and keyboard input successfully
  initialized the sample problem on a subsequent startup.
- Entering `abc abd xyz 42` through the Control Panel initialized the problem.
  Clicking Go advanced the computation and updated the workspace, slipnet,
  trace, and commentary. The run finished with `dyz` displayed in the
  workspace and episodic memory, and the controls became available again.
- Source verification still passed after the GUI run. No engine or startup
  code was changed for this validation.

[GUI after the sample run](gui-validation.png) shows the application framebuffer
without browser connection banners or environment identifiers. The displayed
answer is an observed result, not a claim of ground-truth correctness.

The initial startup stopped in the Scheme REPL with:

```text
Exception in get-bytevector-n!: failed on #<binary input port images.ss>: bad address
```

A full container restart recovered and completed window initialization. A
subsequent fresh-container startup also completed successfully: the initial
start failed, followed by two successful starts without source changes.
The source file's checksum was correct, but the underlying cause of the read
error was not established. This is not an unconditional reliability pass:
the noVNC page can be reachable even while Metacat has failed to load.
The README documents the startup check and restart recovery.
