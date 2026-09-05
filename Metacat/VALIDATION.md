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
