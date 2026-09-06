# Three Reproducible Study Failures

Recorded 2026-09-06. **Unfixed.** These are three failing executions with two
exception signatures, not three independently diagnosed bugs. This note is
an investigation handoff; it does not modify the reconstruction patches.

All three inputs and seeds are in the intended domain. The failures occurred
in reference Metacat, not the Python port, during the held-out validation phase
of [support-v1/support-v1a](../studies/support-v1a/README.md). The completed
campaign retained them as `*ERROR*` observations rather than dropping seeds,
discarding chunks, or treating crashes as ordinary answers.

## Exact Cases

| Reproducer key | Analogy | Seed | Study codelets at error | Recorded exception |
| --- | --- | ---: | ---: | --- |
| `misc1-20713988` | `abc -> cba; mrrjjj -> ?` | 20713988 | 2,835 | attempt to apply non-procedure `#f` |
| `misc1-20716342` | `abc -> cba; mrrjjj -> ?` | 20716342 | 1,981 | attempt to apply non-procedure `#f` |
| `misc3-20226148` | `abc -> aabbcc; kkjjii -> ?` | 20226148 | 2,088 | Exception in `caddr`: incorrect list structure `#f` |

The execution settings were Chez Scheme 9.5.4 on Linux/amd64, the reconstructed
patch-bundle source, no display, freshly cleared episodic memory for every run,
and a direct 100,000-codelet cap. These are not cap exhaustions. The measured
engine/input revision was `1d7f9f19f2e28b634e9c40c5b04b24cdb71baf26`;
the crash-aware collector revision was `e5f7e79a3447616909274ba078b27e3486ddf73b`.
The engine and reconstructed source were unchanged between those revisions.

On 2026-09-06, the standalone reproducer below was run for all three cases in
separate fresh containers using the study runtime and read-only source mounts.
Each printed its case banner and the matching exception above, then exited
with status 255. These three post-study diagnostic executions are not additional
independent observations in the 969,000-run campaign.

## Reproduce One Failure

Follow [README.md](README.md) to install the dependencies and reconstruct
Metacat. Run the following from the **Metacat folder containing this note**,
not from `build/source`. Docker must be running. No full study or GPU is needed.

```sh
python3 tools/reconstruct.py --verify build/source
docker build --platform linux/amd64 -t metacat:1.2 build/source/docker
docker run --rm --platform linux/amd64 --network none --read-only \
  --cpus 1 --memory 2g \
  --mount "type=bind,src=$PWD/build/source,dst=/metacat,readonly" \
  --mount "type=bind,src=$PWD/tests,dst=/tests,readonly" \
  --workdir /metacat --entrypoint env metacat:1.2 \
  -u DISPLAY scheme -q --script /tests/reproduce-failures.ss misc1-20713988
```

To reproduce the other failures, repeat the Docker command, changing only its
last argument to `misc1-20716342` or `misc3-20226148`. Each command starts with a
new process and fresh memory. A nonzero exit with the expected exception is the
reproduced bug, not successful application behavior. Exit status 2 from the
helper means an invalid case key or an unexpected ordinary/capped return.

The helper is [tests/reproduce-failures.ss](tests/reproduce-failures.ss). It
contains only our small test driver, not upstream Metacat source. It leaves
the Scheme exception unhandled so it can be inspected. For advanced diagnosis,
Chez provides `--debug-on-exception` and continuation inspection; see the
[Chez 9.5 debugging manual](https://cisco.github.io/ChezScheme/csug9.5/debug.html).
An interactive Docker session is needed to use debugger prompts.

Docker rebuilds do not pin every Debian package. The published study manifest
records the actual Scheme/runtime hashes and dependency versions. A failure
to reproduce on a different runtime is evidence to investigate, not a reason
to overwrite the recorded data or assume the bug is fixed. Cross-platform and
headed/GUI reproduction of these particular failures has not been established.

## Where the Evidence Lives

The [full public study data](../studies/support-v1a/data/README.md) contains the
original observations, generated collector scripts, exception details, and
checksummed receipts. After extracting it, these directories are relative to
the extraction destination:

| Case | Completed main-study attempt directory |
| --- | --- |
| `misc1-20713988` | `main/chunks/validation/misc1/013750/attempt-001/` |
| `misc1-20716342` | `main/chunks/validation/misc1/016250/attempt-001/` |
| `misc3-20226148` | `main/chunks/validation/misc3/026000/attempt-001/` |

In each directory, `runs.jsonl` identifies the error by its seed, and
`segment-000/condition.txt` contains its Scheme condition. The corresponding
`segment-000/engine-error.tsv` records its index, seed, stage, codelets, and
elapsed time. `segment-000/collector.ss` is the exact generated driver used.
The next segment starts after the failed seed in a fresh process.

For the first failure, the originally interrupted attempt is also preserved
at `parent/chunks/validation/misc1/013750/attempt-001/`. Its `stderr.log`
contains the uncaught exception; its `raw.tsv` contains 238 successful runs
before the failing seed. The original collector stopped there. The continuation
replayed the chunk, matched that prefix, recorded the error once, and completed
the remaining 11 assigned seeds. The excluded preflight is under
`main/preflight/chunks/validation/misc1/013750/attempt-001/`.

## What Is Known About the Cause

### First case: `misc1-20713988`

Inspection of the failing Scheme continuation located the immediate failure
inside `make-group` in reconstructed `groups.ss`, at line 51: the local
`initial-letter-category` was `#f` when sent `get-uppercase-name`. Metacat's
procedure-based object dispatch consequently attempted to call `#f`.

The constructor starts at line 20. Lines 47-48 obtain the category and use it
in a new description before the failing name lookup. Lines 76-77 initialize
the cached category by requesting the letter-category descriptor of the first
ordered constituent. These line numbers refer to the exact file with SHA-256:

```text
b72fb1d141797339a521c49ef487c44f628cf64b9bb54a5c5490ce3e2e60a15e
```

That file matches the original tarball; the reconstruction patches do not
modify it. However, the reason its expected descriptor is missing has not been
established. Other patched behavior might make this path reachable. This is
not yet proof that an unmodified upstream installation has the same bug.

Do not assume a guard that merely skips `get-uppercase-name` is a valid repair:
the absent descriptor has already been supplied to description construction
and is used in group/image state. Investigate why it is absent and what the
constructor's invariant should be.

### Second case: `misc1-20716342`

The input and exception signature match the first case, but the seed and
recorded codelet count differ. Fresh-process reproduction confirms the failure.
Its failing continuation has not been inspected, so sharing the same exact
call site or root cause remains unverified. Start by checking whether its
failure also reaches `make-group` with a missing letter-category descriptor.

### Third case: `misc3-20226148`

The recorded condition identifies `caddr` receiving `#f` where a sufficiently
long list was expected. Fresh-process reproduction confirms the exception.
The engine call site and producer of the false value have not been located.
Inspect the failing continuation to identify that caller before proposing a
default list or suppressing the exception. No connection to the first two
failures has been established.

## When Returning to This Work

1. Keep the published study and existing patch bundle intact; investigate in
   a separate reconstructed working copy at the recorded revision.
2. Reproduce all three cases and capture their failing continuations. Trace
   the missing descriptor or false list back to its producer and intended
   state invariant, rather than only guarding the final failing operation.
3. Develop a minimal repair and regression tests for the affected invariant,
   including these seeds and unaffected cases. Check both fresh-memory and
   memory-retained operation; test the GUI path separately.
4. Publish any repair as a versioned patch change with new source hashes.
   Do not blend repaired-engine samples into the existing reference. A changed
   engine requires separately identified experiments and reference data.

The separate `newline` shadowing error in the first continuation preflight
was a collector-wrapper bug, fixed before main continuation. It is archived
under `aborted-preflight/` for transparency and is not one of these three
Metacat engine failures.
