# Three Reproducible Study Failures

Recorded 2026-09-06. **Unfixed in the reference reconstruction; fixed by the
bundle's second patch group, which is always applied** (2026-10-28,
[`patches/fixes/0001-known-failures.patch`](patches/fixes/0001-known-failures.patch);
see [Status](#status-lockstep-pass) below). These are three failing executions
with two exception signatures. The diagnosis found two bugs, not three. The
reference reconstruction's patches are unchanged, so the published study keeps
its exact reference.

Two more crashes, found later by Petacat's lockstep checks and not by the study, have their own
sections at the end ([A fourth crash: a group of six or more](#a-fourth-crash-a-group-of-six-or-more) and
[A letter outside a to z](#a-letter-outside-a-to-z)).

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

*Historical.* These commands reproduced the crash on the reference reconstruction, which the
bundle no longer builds or verifies. On the patched tree each one ends with an answer (see
below), and the helper exits with status 2.

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

The reproducer needed the **reference reconstruction**, which the bundle no
longer builds or verifies (nothing takes the fixes off). On the patched tree the
reproducer prints `REPRODUCER returned suspended at N codelets; expected an
exception` and exits with status 2: each run now ends with an answer, after the
same number of codelets as the crash. The three crashes are kept as recorded
data (`tests/lockstep/traces-known-failures/reference/`) and in the study data
named below.

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

*As recorded on 2026-09-06.* The diagnosis of 2026-10-28
([Status](#status-lockstep-pass)) answers the questions below:
- The second case has the same cause as the first.
- The third case's caller is `get-change-phrase`, reached through
  `transcribe-to-english`, and the false value comes from
  `change-descriptions->rule-clause-template`.
- The descriptor is absent because a swap during answer construction puts a
  length-based group first in a letter-category group.
- The repair is not the bare guard warned against below. The group gets neither
  the letter description nor the print name, which is how a length-based group is
  treated.

Whether an unmodified upstream installation reaches these paths was not tested.

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

## Status (lockstep pass)

Added 2026-10-28.  The reconstruction patches and the published study are unchanged; the cases
were diagnosed with the lockstep recorder (`tests/lockstep/metacat/`) and a Chez continuation
inspector.  There are **two** causes, not three, and both are in code the patches do not touch.

* **Seeds 20713988 and 20716342 (`abc cba mrrjjj`, same cause).**  The answer-finder translates a
  rule that swaps the *leftmost letter* and the *rightmost group* of the whole-string group
  (`m` and the length group `[jjj rr]`; `m` is a singleton group `[m]`).  `apply-string-position-swap`
  exchanges the two images' states, so the image of the singleton group `[m]` (bond facet
  letter-category, start letter `m`) now has the length-based group as its only sub-image.
  `instantiate-as-group` (`images.ss`) calls `make-group` for it; `new-group` computes
  `initial-letter-category` as the letter-category descriptor of the first object, which is `#f`
  for a length-based group (`groups.ss:76`); `make-group` (`groups.ss:47-51`) then sends
  `get-uppercase-name` to `#f` ("attempt to apply non-procedure #f").  Call chain: `answer-finder`
  -> `make-translated-string` -> `postorder-interior-walk` -> `instantiate-as-group` -> `make-group`.
* **Seed 20226148 (`abc aabbcc kkjjii`).**  `rule-scout` -> `make-rule` -> `transcribe-to-english`
  -> `get-change-phrase` (`rules.ss:1870-1874`) evaluates `(3rd BondFacet-change)` with
  `BondFacet-change` = `#f` (caddr of `#f`).  `change-descriptions->rule-clause-template`
  (`rules.ss:793-801`) asks only the **first** change description of a reference object for its
  BondFacet change, but the `(self group-category opposite)` change need not be first (the order
  follows the bridges and the abstraction coin flips), so the clause carries a group-category
  change without its bond-facet change.

**The fix: the bundle's second patch group**
([`patches/fixes/0001-known-failures.patch`](patches/fixes/0001-known-failures.patch);
the reference reconstruction does not apply it).
- `make-group` skips the LettCtgy description and the print name when
  `initial-letter-category` does not exist; the group gets none, as a length-based
  group gets none.
- `change-descriptions->rule-clause-template` takes the first BondFacet change of any
  of the descriptions (`ormap-meth`).
- The patch also adds §1.3 to the reconstructed `CODE-FIXES.md`.

Apply it with `python3 tools/reconstruct.py --apply-fixes build/source` and check it
with `--verify build/source` (README, "The known-failure fixes").

Verified on 2026-10-28:
- The three seeds run to an answer: `rrjjjm` after 2835 and 1981 codelets, `kji`
  after 2152.
- The headless smoke test passes on the fixed tree.
- The bundle's 19 packaging tests passed, including an apply/remove round trip (the removal has since been taken out of the tool).
- Decision traces of every other recorded run are byte-identical with and without
  the patch: see [VALIDATION.md](VALIDATION.md).

Any use of it still counts as a changed engine in the sense of item 4 above.

**Petacat.** Petacat's lockstep harness once recorded both variants (two options of
`tests/lockstep/metacat/record.py`, since removed: only the patched Metacat is ever run now). The recordings are
stored data in `tests/lockstep/traces-known-failures/reference/` and `.../fixes/`. Petacat replays the
reference recordings in lockstep up to each crash point; it does not crash, and it
carries on as the fixed Metacat does. It replays the fixed recordings to the end with
no differences. Investigating these seeds found two Petacat port bugs on the same path
(`DISCREPANCIES5.md` G-Q1, G-Q2), which are fixed.

## A fourth crash: a group of six or more

Added 2026-11-06. The three study failures above are two bugs. This one is a third, found by Petacat's
wide lockstep check of 4,384 recorded runs: 83 of them (1.9%) ended with the Scheme exception
`attempt to apply non-procedure #f`. All 83 crash inside a `bridge-builder`, and the bridge it was
building joins a group of six or more objects (checked on all 83 by parsing the picked codelet's
name). The smallest is `aaa -> aaaaaa; aaa`, seed 1, which crashed at codelet 608.

**Cause.** The Slipnet has number nodes for 1 to 5 only (`*slipnet-numbers*`). For a group of six or
more objects `number->platonic-number` (`slipnet.ss:495-499`) returns `#f`, so the group's
`platonic-length` is `#f` (`groups.ss:86`). The engine already knows this: `attach-length-description`
(`groups.ss:836-844`) says "Check for groups longer than five objects" and gives such a group no Length
description. But `build-bridge` (`bridges.ss:1396-1411`), for a horizontal bridge, made a Length
concept-mapping whenever the two objects' platonic lengths differ, without the same check. A letter
or a shorter group on one side and a group of six or more on the other gave
`(make-concept-mapping object1 plato-length length1 object2 plato-length #f)`, and
`concept-mappings.ss:40` sent `get-CM-short-name` to `#f`.

**The fix: the second patch group's `patches/fixes/0002-length-group-of-six-or-more.patch`.** The
Length concept-mapping is made only when both lengths exist, as the Length description is
(`(and (exists? length1) (exists? length2) ...)`). Nothing else changes: when both objects are groups
of six or more their lengths are equal (both `#f`) and no mapping was made before or after. Adding
number nodes would have been a larger change, because it changes every run. Every other use of a
platonic length either compares it with `eq?` (`bridges.ss:1121`, `groups.ss:753`) or is already
guarded by `exists?` (`groups.ss:836-844`); none of them sends to it. The patch also adds §1.4 to the
reconstructed `CODE-FIXES.md`.

**Verified on 2026-11-06.**
- All 83 recorded runs, recorded again with the patch, are identical to the same runs recorded without
  the 0002 patch (but with the 0001 fixes) up to the codelet where they used to crash, and then run on:
  56 reach their cap (3,000 to 5,000 codelets), 23 end with an answer and 9 give up.
- 266 recorded runs that never crashed (the stage W sample and `abc -> abd; xyz` seeds 1 to 10), recorded
  with and without the 0002 patch, are identical record for record, apart from the header's `revision`.
- Petacat's Metacat Mode replays all 83 (88 traces with the later runs of the episodes) to their ends
  with agreement 1.0, no error and no differing snapshot.

## A letter outside a to z

Added 2026-11-06. Metacat's input parser (the control panel's command line, `gui.ss:147`) calls
`tokenize-string` (`gui.ss:95`), which lowers its input, takes punctuation, spaces, emoji and combining
marks as separators, and lets any *alphabetic* character into a symbol, and then asks `valid-token-list?`
(`syntactic-sugar.ss:51`). A letter outside a to z (`é`, `日本`, a Greek letter, `Ⅳ`) therefore became a valid
symbol, and `init-mcat` then stopped on the uncaught error `variable plato-é is not bound`
(`symbol->letter-categories`, `utilities.ss:303-310`, evaluates `plato-<letter>`), before the run began.
The `(mcat ...)` form, which uses the same `valid-token-list?` as a fender, passed it on too.

**The fix: the second patch group's `patches/fixes/0003-non-english-letter-invalid-input.patch`.**
`valid-token-list?` now requires each symbol token (the three strings and the answer) to be made only of
letters the Slipnet has a node for, by the nodes' lowercase names (`valid-letter-symbol?`). Nothing else in
the parser changes: `tokenize-string`, the lowering, the separators, the digit rule ("Invalid input!" for a digit
inside a string, a number that is not a valid seed) and the seed range are as they were. Metacat models
perception, and the way it reads its input is part of that, so the patch changes only what crashed.

- **The command line** answers "Invalid input!" to such a letter, as it does to any other invalid token list.
- **The `(mcat ...)` form** is refused before any run starts: `(mcat abc abd xyé)` prints
  `Exception in mcat: invalid syntax (mcat abc abd xyé)`, the same error as `(mcat abc abd 5)`, which was already
  invalid. A capital such as `(mcat abc abd Xyz)` is refused the same way (it also crashed in `init-mcat` before).
  Output: `P-patch/logs/mcat_form_after.txt`.

**Verified on 2026-11-06.** `tests/lockstep/metacat/record_parser.py` runs the real `tokenize-string`,
`char-noise?`, `valid-token-list?`, `valid-number?` and `symbol-or-valid-number?` over every Unicode scalar value
in three lines (`abc abd x{c}z`, `abc abd {c}`, `{c}bc abd xyz`) and 200 whole lines, on the tree with
0001 and 0002 and on the tree with 0003 (`tests/lockstep/data/parser_metacat.json.gz`). The character classes
(`char-downcase`, `char-alphabetic?`, `char-numeric?`, `char-noise?`) and every token list are identical. The only
change is the validity of a token list, from valid to invalid, and only where a symbol holds a letter outside
a to z: 104,023 of the 1,112,064 scalar values in each of the three lines, and 48 of the 200 whole lines. 266 recorded runs, recorded with
and without 0003, are identical apart from the header's `revision`.
