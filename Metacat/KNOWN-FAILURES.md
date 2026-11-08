# Three Reproducible Study Failures

Recorded 2026-09-06. **Unfixed in the reference reconstruction; fixed by the
bundle's second patch group, which is always applied** (2026-10-28,
[`patches/fixes/0001-known-failures.patch`](patches/fixes/0001-known-failures.patch);
see [Status](#status-lockstep-pass) below). These are three failing executions
with two exception signatures. The diagnosis found two bugs, not three. The
reference reconstruction's patches are unchanged, so the published study keeps
its exact reference.

Everything needed to reproduce the problem behind each fix is in
[How to reproduce the problem behind each fix](#how-to-reproduce-the-problem-behind-each-fix), below.

Five more crashes, found later by Petacat's lockstep checks, reach studies and a sweep, and not by the study, have their own
sections at the end ([A fourth crash: a group of six or more](#a-fourth-crash-a-group-of-six-or-more),
[A letter outside a to z](#a-letter-outside-a-to-z),
[A rule that reverses all the groups of a string](#a-rule-that-reverses-all-the-groups-of-a-string),
[A group image with no start letter](#a-group-image-with-no-start-letter) and
[A rule change with nothing left to describe](#a-rule-change-with-nothing-left-to-describe)).

All three inputs and seeds are in the intended domain. The failures occurred
in reference Metacat, not the Python port, during the held-out validation phase
of [support-v1/support-v1a](../studies/support-v1a/README.md). The completed
campaign retained them as `*ERROR*` observations rather than dropping seeds,
discarding chunks, or treating crashes as ordinary answers.

## How to reproduce the problem behind each fix

Added 2026-11-08, at the user's ruling: the recordings of the crashes were removed, but there must be a record, for each
incremental patch, of exactly how to reproduce the problem that drove it. This section is that record. There is one entry
per fix (0001 to 0006) and, inside it, one entry per case that drove the fix.

**What "reproduce" can mean here.** A crash can be reproduced only by running a tree without the fix. **This project never
runs such a tree**, and no tool in it can take a fix off. So the record gives, for each case:

1. the exact input and settings, and the build the crash was seen on (which fixes of the second patch group were applied,
   every one numbered before this fix and none after it, with the bundle manifest hash recorded at the time);
2. the point where the run stopped: the codelet count, the exact error text and the call chain, with `file:line` on the
   tree *before* the fix (the patches shift later lines; the line numbers in this section and in the sections below are
   those of the tree before the fix they belong to);
3. one command that runs the case on a tree;
4. the proof that the patched build takes the fixed path at that point.

**For someone who holds a tree without the fix.** Run the command of item 3 with that tree mounted as `/metacat` (change
`src=` of the first `--mount` in the Docker command below to the folder of that tree; the tree must have the second patch
group's earlier fixes, and none of this one). The helper then prints
`REPRODUCER FAILED <case>: the run stopped with an exception at N codelets: <the error text>` for a run, and exits with
status 1. The codelet count N and the error text are the ones in the entry. This project has not run the helper on such a
tree, so that output is what the entry predicts, not something this project observed with the helper (the original
observations are the study data and the recordings named in each entry).

**The command that runs a case on the patched build** (from the `Metacat` folder, Docker running, `build/source` patched):

```sh
python3 tools/reconstruct.py --verify build/source
docker build --platform linux/amd64 -t metacat:1.2 build/source/docker
docker run --rm --platform linux/amd64 --network none --read-only \
  --cpus 1 --memory 2g \
  --mount "type=bind,src=$PWD/build/source,dst=/metacat,readonly" \
  --mount "type=bind,src=$PWD/tests,dst=/tests,readonly" \
  --workdir /metacat --entrypoint env metacat:1.2 \
  -u DISPLAY scheme -q --script /tests/reproduce-failures.ss <case>
```

`bash scripts/reproduce-metacat-fixes.sh <case> ...` (from the repository root) does the same for the cases it is given (every case when it is given none) and
exits 0 only if every case does. The cases are: `misc1-20713988`, `misc1-20716342`, `misc3-20226148` (0001),
`fix2-aaa-seed1` (0002), `fix3-command-line`, `fix3-mcat-form` (0003), `fix4-pqcd-1`, `fix4-pqcd-69`, `fix4-pqcd-238`,
`fix4-defpqr-79`, `fix4-defpqr-102`, `fix4-defpqr-161`, `fix4-abcxyz-35`, `fix4-abcxyz-74`, `fix4-ijkm-11`,
`fix4-ijkm-126`, `fix4-ijkm-184`, `fix4-tugx-105` and `fix4-letter-trial` (0004), `fix5-wxyz-27`, `fix5-ihg-121`, `fix5-bcd-18` and `fix5-image-trial` (0005), and `fix6-abcx-19` (0006).

**How the helper proves the fixed path.** [`tests/reproduce-failures.ss`](tests/reproduce-failures.ss) is our own driver and
contains no upstream source. After it loads the patched engine it wraps one engine procedure in its own process only
(`set!` of the procedure's top-level name; no file of the source tree or of a patch is touched), calls the original unchanged,
and writes an `EVENT` line with `*codelet-count*` when the situation that used to be fatal arises and the original returns. The
wrappers draw no random number. Every run is a fresh process with freshly cleared Episodic Memory, Self-watching on (Metacat's
default; no case changes it) and `init-mcat` with no answer. The helper exits 0 only when every expected event happens at the
codelet its entry gives and the run ends as its entry says (answer and codelets, or the cap). If the patched build stops with an
exception, it prints `REPRODUCER FAILED` and exits 1 (that would mean the patch is incomplete). Exit 2 is an unknown case.
The cases of 0003 are refused before any run starts, so there the proof is the refusal.

### 0001: two sends to `#f` (`patches/fixes/0001-known-failures.patch`)

Seen on: the reference reconstruction, the bundle without the second patch group (no fix of it applied), bundle manifest
`705c5ac90f2546753626c51c04f39dab3bc7a2d07e18fa4bd90f39df3459dda1` (the `revision` header, without the
`+known-failure-fixes` mark, of the recordings made in October 2026), Chez Scheme 9.5.4 on Linux/amd64, engine/input revision
`1d7f9f19f2e28b634e9c40c5b04b24cdb71baf26` of the study. All three: fresh Episodic Memory, cap 100,000 codelets, Self-watching
at Metacat's default (on), no display. Original observations: the study data (attempt directories in
"Where the Evidence Lives" below).

| Case key | Input (initial, modified, target) | Seed | Stopped at | Exact error | Call chain (before the fix) |
| --- | --- | ---: | --- | --- | --- |
| `misc1-20713988` | `abc` `cba` `mrrjjj` | 20713988 | 2,835 codelets (the 2,836th was running; an `answer-finder`) | `Exception: attempt to apply non-procedure #f` | `answer-finder` -> `make-translated-string` -> `postorder-interior-walk` -> `instantiate-as-group` (`images.ss`) -> `make-group` (`groups.ss:47-51`, `get-uppercase-name` sent to `#f`; the `#f` is `initial-letter-category`, computed at `groups.ss:76`) |
| `misc1-20716342` | `abc` `cba` `mrrjjj` | 20716342 | 1,981 codelets (the 1,982nd was running; an `answer-finder`) | the same | the same chain |
| `misc3-20226148` | `abc` `aabbcc` `kkjjii` | 20226148 | 2,088 codelets (the 2,089th was running; a `rule-scout`) | `Exception in caddr: incorrect list structure #f` | `rule-scout` -> `make-rule` -> `transcribe-to-english` -> `get-change-phrase` (`rules.ss:1870-1874`, `(3rd BondFacet-change)` with `BondFacet-change` = `#f`); the `#f` comes from `change-descriptions->rule-clause-template` (`rules.ss:793-801`), which asked only the first change description for its BondFacet change |

- **Command:** the Docker command above with `<case>` = `misc1-20713988`, `misc1-20716342` or `misc3-20226148`. Original form:
  `scheme -q --script /tests/reproduce-failures.ss misc1-20713988` (the same file; before 2026-11-08 it printed the case banner
  and the exception and exited 255 on the reference reconstruction).
- **Recorder form** (the harness's own driver; patched build only): `python3 tests/lockstep/metacat/record.py --problem abc cba mrrjjj --seeds 20713988 --cap 100000 --jobs 1 --out <dir>`
  (likewise `--seeds 20716342`, and `--problem abc aabbcc kkjjii --seeds 20226148`).
- **Fixed path on the patched build** (helper output, `bash scripts/reproduce-metacat-fixes.sh <case>`):
  `misc1-20713988`: `make-group` returns a letter-category group whose first object has no letter category, at codelet 2835, and the run answers `rrjjjm` after 2,835 codelets;
  `misc1-20716342`: the same event at codelet 1981, answer `rrjjjm` after 1,981 codelets;
  `misc3-20226148`: `change-descriptions->rule-clause-template` is called with a first change description that has no BondFacet change and a later one that has, at codelet 2088, and the run answers `kji` after 2,152 codelets.
- **Evidence in the repository:** `studies/support-v1a/data/` (extracted per its README; the three attempt directories are listed under "Where the Evidence Lives"; `segment-000/condition.txt` holds the Scheme condition and `segment-000/collector.ss` the generated driver); the patched recordings `tests/lockstep/traces-known-failures/fixes/` (`abc-cba-mrrjjj/20713988`, `abc-cba-mrrjjj/20716342`, `abc-aabbcc-kkjjii/20226148`), which run to the answer. The unpatched recordings that once sat next to them were removed on 2026-11-08.

### 0002: a Length mapping for a group of six or more (`patches/fixes/0002-length-group-of-six-or-more.patch`)

Seen on: the reconstruction with fix 0001 only (the second patch group as it was before 0002), manifest
`705c5ac90f2546753626c51c04f39dab3bc7a2d07e18fa4bd90f39df3459dda1`, trace header `revision` ending `+known-failure-fixes`. Found by
the stage W wide check of 4,384 recorded runs: 83 ended in this error.

| Case key | Input | Seed | Settings | Stopped at | Exact error | Call chain (before the fix) |
| --- | --- | ---: | --- | --- | --- | --- |
| `fix2-aaa-seed1` | `aaa` `aaaaaa` `aaa` | 1 | cap 5,000, snapshots on, fresh memory, Self-watching on | 608 codelets (the 609th was running; a `bridge-builder` whose bridge is `bridge(top, group(i.0-2,samegrp,-,letter-category), group(m.0-5,samegrp,-,letter-category))`) | `Exception: attempt to apply non-procedure #f` | `bridge-builder` -> `build-bridge` (`bridges.ss:1396-1411`, the horizontal Length mapping) -> `make-concept-mapping object1 plato-length length1 object2 plato-length #f` -> `get-CM-short-name` sent to `#f` (`concept-mappings.ss:40`); `#f` is `platonic-length` of a group of six objects (`groups.ss:86`, from `number->platonic-number`, `slipnet.ss:495-499`: the Slipnet has number nodes 1 to 5 only) |

- **Command:** the Docker command with `<case>` = `fix2-aaa-seed1`. Recorder form: `python3 tests/lockstep/metacat/record.py --problem aaa aaaaaa aaa --seeds 1 --cap 5000 --jobs 1 --out <dir>`.
- **Fixed path on the patched build:** `build-bridge` is called for a horizontal bridge whose two objects have platonic lengths that differ because one is `#f`, at codelet 608; it returns and the bridge has no Length concept-mapping; the run answers `aaaaaa` after 1,614 codelets.
- **All 83 runs.** The smallest is the case above (row 3 of the table). Each row gives the input, the seed and the options of the recorder
  command `python3 tests/lockstep/metacat/record.py --problem <initial> <modified> <target> --seeds <seed> --cap <cap> --jobs 1 <other options>`; every one was recorded with snapshots (the default), and every one stopped with `Exception: attempt to apply non-procedure #f` inside a `bridge-builder` building a bridge that joins a group of six or more objects. A justify run is `--answer`, a run with Self-watching off is `--self-watching off`, the one with a person's actions is `--intervene`, and the one episode run is run 1 of `--episode-runs 6` (`--seeds` is the episode seed).

| # | Initial | Modified | Target | Seed | `--cap` | Other options | Stopped at (codelets) |
| ---: | --- | --- | --- | ---: | ---: | --- | ---: |
| 1 | `www` | `wwwwww` | `qp` | 1 | 5000 |  | 858 |
| 2 | `www` | `wwwwww` | `qp` | 2 | 3000 | `--self-watching off` | 634 |
| 3 | `aaa` | `aaaaaa` | `aaa` | 1 | 5000 |  | 608 |
| 4 | `abc` | `abd` | `rstuvw` | 1 | 5000 | `--answer a` | 4749 |
| 5 | `eee` | `eeeeee` | `eee` | 2 | 5000 |  | 288 |
| 6 | `eee` | `eeeeee` | `eee` | 3 | 5000 |  | 671 |
| 7 | `lll` | `llllll` | `lll` | 1 | 5000 |  | 538 |
| 8 | `ooo` | `oooooo` | `ooo` | 1 | 5000 |  | 538 |
| 9 | `bvb` | `vbb` | `opkaczc` | 1 | 5000 | `--answer ooooooo` | 1904 |
| 10 | `eee` | `eeeeee` | `vuts` | 1 | 5000 |  | 597 |
| 11 | `eee` | `eeeeee` | `vuts` | 2 | 3000 | `--self-watching off` | 554 |
| 12 | `bbb` | `bbbbbb` | `jmjkl` | 1 | 5000 |  | 493 |
| 13 | `ghituv` | `ssssss` | `dd` | 1 | 5000 |  | 1920 |
| 14 | `ppp` | `pppppp` | `zefgh` | 1 | 5000 |  | 632 |
| 15 | `ppp` | `pppppp` | `zefgh` | 1 | 3000 | `--intervene 1267:self-watching-off,2211:self-watching-on` | 632 |
| 16 | `gkkk` | `ggkkkkkk` | `pqr` | 1 | 5000 |  | 612 |
| 17 | `gkkk` | `ggkkkkkk` | `pqr` | 2 | 3000 | `--self-watching off` | 911 |
| 18 | `jjjzzz` | `vvvvvv` | `qyde` | 1 | 5000 |  | 3121 |
| 19 | `jjjzzz` | `vvvvvv` | `qyde` | 9 | 4000 | `--episode-runs 6` | 3446 |
| 20 | `brrr` | `bbrrrrrr` | `zkzuu` | 1 | 5000 |  | 712 |
| 21 | `eeeeee` | `eeeeef` | `eeeee` | 1 | 5000 |  | 1910 |
| 22 | `jjjcy` | `jjjjjjccyy` | `qq` | 1 | 5000 |  | 693 |
| 23 | `jklmno` | `jklmn` | `jklmno` | 1 | 5000 |  | 1754 |
| 24 | `ttton` | `ttttttoonn` | `kl` | 1 | 5000 |  | 947 |
| 25 | `gqgayxz` | `sssssss` | `hijk` | 1 | 5000 |  | 4832 |
| 26 | `hgflkj` | `eeeeee` | `hgflkj` | 1 | 5000 |  | 3605 |
| 27 | `hhhhhh` | `hhhhhi` | `ooohhh` | 1 | 5000 |  | 2656 |
| 28 | `mfacaac` | `wwwwwww` | `ppay` | 1 | 5000 |  | 2594 |
| 29 | `pwuuu` | `ppwwuuuuuu` | `giy` | 1 | 5000 |  | 1257 |
| 30 | `tttbj` | `ttttttbbjj` | `eii` | 1 | 5000 |  | 969 |
| 31 | `wwwwwww` | `wwwwwwx` | `wwww` | 1 | 5000 |  | 1570 |
| 32 | `ddqqq` | `ddddqqqqqq` | `efgh` | 1 | 5000 |  | 735 |
| 33 | `tatybyz` | `iiiiiii` | `cxazz` | 2 | 5000 |  | 1807 |
| 34 | `tatybyz` | `iiiiiii` | `cxazz` | 3 | 5000 |  | 1412 |
| 35 | `uuuuuuuu` | `uuuuuuuv` | `uuu` | 1 | 5000 |  | 956 |
| 36 | `zziii` | `zzzziiiiii` | `jihw` | 1 | 5000 |  | 765 |
| 37 | `zzzts` | `zzzzzzttss` | `ihee` | 1 | 5000 |  | 620 |
| 38 | `bbbnnn` | `bbbbbbnnnnnn` | `yy` | 2 | 5000 |  | 729 |
| 39 | `bbbnnn` | `bbbbbbnnnnnn` | `yy` | 3 | 5000 |  | 853 |
| 40 | `nurrr` | `nnuurrrrrr` | `zxebb` | 1 | 5000 |  | 544 |
| 41 | `rrreoe` | `rrrrrreeooee` | `fg` | 1 | 5000 |  | 564 |
| 42 | `rrreoe` | `rrrrrreeooee` | `fg` | 3 | 3000 | `--self-watching off` | 898 |
| 43 | `wvutsrqp` | `pqrstuvw` | `wvut` | 1 | 5000 |  | 1146 |
| 44 | `ddddddd` | `dddddde` | `uuuuuuu` | 1 | 5000 |  | 1401 |
| 45 | `klmkkk` | `kkllmmkkkkkk` | `ggg` | 1 | 5000 |  | 1426 |
| 46 | `pqrstuv` | `pqrstuw` | `pqrstuv` | 1 | 5000 |  | 600 |
| 47 | `pqwww` | `ppqqwwwwww` | `mnotit` | 1 | 5000 |  | 1105 |
| 48 | `vulll` | `vvuullllll` | `hhhkgo` | 1 | 5000 |  | 964 |
| 49 | `hmokobac` | `aaaaaaaa` | `ajanml` | 1 | 5000 |  | 2317 |
| 50 | `iiiiiiiii` | `iiiiiiiij` | `yyyy` | 1 | 5000 |  | 737 |
| 51 | `kkkgkl` | `kkkkkkggkkll` | `defg` | 1 | 5000 |  | 1008 |
| 52 | `qqqqqqqq` | `qqqqqqqr` | `qqqqqq` | 1 | 5000 |  | 1516 |
| 53 | `bmsmxwnopq` | `mmmmmmmmmm` | `pqr` | 1 | 5000 |  | 3109 |
| 54 | `abcdefgh` | `abcdefgi` | `fghijklm` | 1 | 5000 |  | 827 |
| 55 | `ghijklmn` | `ghijklmo` | `ghijklmn` | 1 | 5000 |  | 1097 |
| 56 | `klmnopqr` | `klmnopqs` | `abcdefgh` | 1 | 5000 |  | 1152 |
| 57 | `lkjbbb` | `llkkjjbbbbbb` | `lkjbbb` | 1 | 5000 |  | 974 |
| 58 | `lmnopqrs` | `lmnopqrt` | `srqponml` | 1 | 5000 |  | 834 |
| 59 | `opqrstuv` | `opqrstuw` | `opqrstuv` | 1 | 5000 |  | 1097 |
| 60 | `qhqsss` | `qqhhqqssssss` | `qhqsss` | 1 | 5000 |  | 1493 |
| 61 | `qhqsss` | `qqhhqqssssss` | `qhqsss` | 1 | 3000 | `--self-watching off` | 673 |
| 62 | `zxbeee` | `zzxxbbeeeeee` | `zxbeee` | 1 | 5000 |  | 696 |
| 63 | `hhhopqr` | `hhhhhhooppqqrr` | `ihgf` | 1 | 5000 |  | 1397 |
| 64 | `ixjyyy` | `iixxjjyyyyyy` | `eeeopqr` | 1 | 5000 |  | 737 |
| 65 | `lllllll` | `llllllm` | `lllllllllll` | 1 | 5000 |  | 525 |
| 66 | `yyyyyyyyyy` | `yyyyyyyyyz` | `ddddd` | 1 | 5000 |  | 626 |
| 67 | `kjihgfedcba` | `abcdefghijk` | `kjih` | 1 | 5000 |  | 1318 |
| 68 | `qponmlkjihg` | `ghijklmnopq` | `qpon` | 1 | 5000 |  | 1772 |
| 69 | `abcdefghi` | `abcdefghj` | `abcdefghi` | 1 | 5000 |  | 815 |
| 70 | `bbbbbbbb` | `bbbbbbbc` | `bbbbbbbbbbb` | 1 | 5000 |  | 992 |
| 71 | `ijklmnopq` | `ijklmnopr` | `qponmlkji` | 1 | 5000 |  | 1484 |
| 72 | `abcdefghij` | `abcdefghik` | `fghijklmno` | 1 | 5000 |  | 1030 |
| 73 | `hijklmnopq` | `hijklmnopr` | `qponmlkjih` | 1 | 5000 |  | 1742 |
| 74 | `jihgfedcba` | `abcdefghij` | `jihgfedcba` | 1 | 5000 |  | 1187 |
| 75 | `kkkkkkkkkk` | `kkkkkkkkkl` | `kkkkkkkkkk` | 1 | 5000 |  | 1260 |
| 76 | `abcdefghijk` | `abcdefghijl` | `abcdefghijk` | 1 | 5000 |  | 3125 |
| 77 | `abcdefghijk` | `abcdefghijl` | `kjihgfedcba` | 1 | 5000 |  | 1096 |
| 78 | `hijklmnopqr` | `hijklmnopqs` | `rqponmlkjih` | 1 | 5000 |  | 1604 |
| 79 | `mmmmmmmmmmm` | `mmmmmmmmmmn` | `kkkkkkkkkkk` | 1 | 5000 |  | 931 |
| 80 | `xzxxaayzycxx` | `jjjjjjjjjjjj` | `axcxaxcac` | 1 | 5000 |  | 1975 |
| 81 | `abcdefghijklm` | `mlkjihgfedcba` | `nopqrstuvwxyz` | 1 | 6000 |  | 2407 |
| 82 | `abcdefghijklm` | `mlkjihgfedcba` | `nopqrstuvwxyz` | 2 | 6000 |  | 2453 |
| 83 | `abcdefghijklm` | `mlkjihgfedcba` | `nopqrstuvwxyz` | 3 | 6000 |  | 1363 |

- **Evidence in the repository:** the patched recording of the smallest case, `tests/lockstep/data/aaa-aaaaaa-aaa.seed1.metacat.jsonl.gz` (answer `aaaaaa`, 1,614 codelets, header ending `+known-failure-fixes`; recorded at cap 5,000), and the table above.

### 0003: a letter outside a to z (`patches/fixes/0003-non-english-letter-invalid-input.patch`)

Seen on: the reconstruction with fixes 0001 and 0002, manifest
`718555f27b0ad97a01c5572c4b9526c6f8adcff324c800169a01c354f7ea8e81`. Input only; no run starts, so there is no seed, cap or
memory state, and no codelet was run (stopped at 0 codelets). The letter is U+00E9, `é`. In a script file it is safest to write
it as `\x00e9;`.

| Case key | Input exactly as given | Exact error before the fix | Call chain (before the fix) |
| --- | --- | --- | --- |
| `fix3-command-line` | the control panel's command line (the Go button), text `abc abd xyé` | `Exception: variable plato-é is not bound` (uncaught, before the run began) | `go-button-action` (`gui.ss`) -> `tokenize-string` (`gui.ss:95`; lowers, takes punctuation as separators, lets any alphabetic character into a symbol, so tokens `(abc abd xyé)`) -> `valid-token-list?` (`syntactic-sugar.ss:51`; answered true) -> the control panel's `init-new-problem` -> `init-mcat` (`gui.ss:764-786`; `run.ss:185`) -> `init-workspace` (`run.ss:215`, `:240`) -> the string constructor (`workspace-strings.ss:23`) -> `symbol->letter-categories` (`utilities.ss:303-310`, evaluates `plato-é`) |
| `fix3-mcat-form` | the form `(mcat abc abd xyé)` | none: the `(mcat ...)` macro passed it on (`syntactic-sugar.ss:43-46`, its fender is `valid-token-list?`), and `init-mcat` then stopped with the same `variable plato-é is not bound` | `mcat` -> the control panel's `run-new-problem` -> `init-mcat` -> `init-workspace` -> `workspace-strings.ss:23` -> `symbol->letter-categories` |

- **Command:** the Docker command with `<case>` = `fix3-command-line` or `fix3-mcat-form`.
- **Fixed path on the patched build:** `go-button-action`, read by name from `gui.ss` and run with a stand-in control panel, calls only `display-error` with `"Invalid input!"` (`tokenize-string` still gives `(abc abd xyé)`, `valid-token-list?` gives `#f`) and starts no problem; the control line `abc abd xyz` starts one. Evaluating `(mcat abc abd xyé)` raises `Exception in mcat: invalid syntax (mcat abc abd xyé)` and reaches the stand-in panel not at all; the control `(mcat abc abd xyz)` is accepted.
- **Evidence in the repository:** `tests/lockstep/data/parser_metacat.json.gz`, written by `tests/lockstep/metacat/record_parser.py`, holds how the patched parser reads every Unicode scalar value (in three lines) and 200 whole lines; and the "A letter outside a to z" section below.

### 0004: a rule that reverses all the groups of a string (`patches/fixes/0004-subobjects-group-category-reversal.patch`)

Seen on: the reconstruction with fixes 0001, 0002 and 0003, manifest
`237995b8e29873c166dd43909445aeaf4a558f8ad9dd06036a583f988c14dca7`, trace header `revision` ending `+known-failure-fixes`.
Every run below: recorded with `python3 tests/lockstep/metacat/record.py --problem <initial> <modified> <target> --seeds <seed> --cap 6000 --no-snapshots --jobs 1 --out <dir>` (stage V; the recordings with snapshots gave the same stops), which is a fresh Episodic Memory, Self-watching on, no answer. The same inputs, seeds and cap run with the helper's plain `init-mcat` driver.

First error, `Exception in cadr: incorrect list structure #f`, at `rules.ss:1351` (`apply-transforms`: `(2nd (assq plato-bond-facet transforms))` with no BondFacet transform). Call chain: the `rule-evaluator` codelet (`rules.ss:463`; shown for `pqcd` seed 1, where the 2,390th codelet is a `rule-evaluator`) -> `currently-works?` (`rules.ss:223-235`) -> `apply-rule` (no guard) -> `apply-transforms` (`rules.ss:1341-1353`), with the transform list `(GroupCtgy Opposite)` that `get-intrinsic-transforms` (`rules.ss:1528-1548`) gives each subobject group of a `(subobjects group-category opposite)` clause, which `rule-scout` builds on purpose (`rules.ss:607-641`); `2nd` is `cadr` (`utilities.ss:951`).

| Case key | Input (initial, modified, target) | Seed | Stopped at (codelets) | Ended on the patched build |
| --- | --- | ---: | ---: | --- |
| `fix4-pqcd-1` | `pqcd` `cbpo` `tugh` | 1 | 2,389 | cap, 6,000 |
| `fix4-pqcd-69` | `pqcd` `cbpo` `tugh` | 69 | 2,914 | cap, 6,000 |
| `fix4-pqcd-238` | `pqcd` `cbpo` `tugh` | 238 | 4,217 (see below) | cap, 6,000 |
| `fix4-defpqr-79` | `defpqr` `pondcb` `hijstu` | 79 | 4,961 | cap, 6,000 |
| `fix4-defpqr-102` | `defpqr` `pondcb` `hijstu` | 102 | 2,521 (see below) | cap, 6,000 |
| `fix4-defpqr-161` | `defpqr` `pondcb` `hijstu` | 161 | 3,749 (see below) | cap, 6,000 |
| `fix4-abcxyz-35` | `abcxyz` `cbazyx` `ijkpqr` | 35 | 4,544 (the 4,545th was running) | cap, 6,000 |
| `fix4-abcxyz-74` | `abcxyz` `cbazyx` `ijkpqr` | 74 | 5,106 | answer `kjirqp`, 5,168 codelets |
| `fix4-ijkm-11` | `abcxyz` `cbazyx` `ijkm` | 11 | 4,653 | answer `kjim`, 5,901 codelets |
| `fix4-ijkm-126` | `abcxyz` `cbazyx` `ijkm` | 126 | 3,253 | answer `kjim`, 3,268 codelets |
| `fix4-ijkm-184` | `abcxyz` `cbazyx` `ijkm` | 184 | 3,824 | cap, 6,000 |
| `fix4-tugx-105` | `pqcd` `cbpo` `tugx` | 105 | 3,792 | cap, 6,000 |

"Stopped at" is the `codelets` field of the `end` record of the recording on the build before this fix for seeds 1, 69, 79, 35, 74 (`pqcd`, `defpqr`, `abcxyz` rows) and 11, 126, 184, 105 (stage V part 1). For seeds 238, 102 and 161 it is the codelet at which the stage V counting wrapper first met such a transform list on the fixed build; those three were not recorded on the build before this fix, so they are predicted to stop there, not observed to. The eight seeds of the three problems are the ones the stage V counting wrapper found, in 720 runs (seeds 1 to 240 of each of `pqcd cbpo tugh`, `defpqr pondcb hijstu` and `abcxyz cbazyx ijkpqr`, cap 6,000), to reach such a transform list inside the recorded run.

- **Command:** the Docker command with `<case>` = a key of the table.
- **Fixed path on the patched build:** for each row, `apply-transforms` is called with a transform list that has a group-category transform and no bond-facet transform at the codelet in "Stopped at", and returns; the run then ends as the last column says. For `fix4-ijkm-11` and `fix4-ijkm-126` the run also reaches `check-for-conflicts` with a letter that has a group-category transform (codelets 5,901 and 3,268, the last codelet of each run) and `check-for-conflicts` returns `done` (the letter is left unreversed, the group is reversed).
- **Evidence in the repository:** the four golden cases `abcx-xwva-ijkr` s117, `pbcd-bpon-wfgh` s34, `abcxyz-cbazyx-ijkpqr` s35 and `pqcd-cbpo-tugh` s1 in `tests/lockstep/golden/extended_cases.json` (recorded on the patched build; the last two are the runs of the table), and the section "A rule that reverses all the groups of a string" below.

**Second error: `bad message "get-bond-facet" sent to object of type letter`.** This one was **not** seen in a recorded run. It came from stage V's *directed trial*, which shows what the code does when a rule of this form is applied to a string of letters; none of 1,000 recorded runs of five problems of this shape (seeds 1 to 200, cap 6,000) stopped on it, because the first error came first. It was seen on the same build as the first error (fixes 0001, 0002 and 0003). Case key `fix4-letter-trial`:

```scheme
(define *metacat-directory* "/metacat/")
(load "/metacat/metacat-headless.ss")
(reset-handler (lambda () (exit 1)))
(tell *memory* 'clear)
(init-mcat 'bcdep 'ponmb 'fghiw #f 1)          ; problem bcdep -> ponmb; fghiw, seed 1, no answer
(set! *break-time* 1)                          ; run one codelet only
(call/cc (lambda (k) (set! suspend (lambda () (k 'suspended))) (set! break (lambda () (k 'capped))) (run-mcat)))
(let* ((clause (list 'intrinsic (list (list 'string plato-string-position-category plato-whole))
                     (list (list 'subobjects plato-group-category plato-opposite))))
       (rule (make-rule 'top (list clause))))  ; English: "Reverse starting and ending points of all objects in string"
  (apply-rule rule *initial-string* ignore-snag))
```

At that point the string `bcdep` has five letters and no groups (`(tell *initial-string* 'get-groups)` is empty, 5 constituent objects). Stopped at: after 1 codelet, inside `apply-rule`; exact error `Ooops: bad message "get-bond-facet" sent to object of type letter`; call chain `apply-rule` -> `check-for-conflicts` (`rules.ss:1218-1224`, `:1303`) -> `intrinsic-implies-intrinsic?` -> `same-dimension-as-GroupCtgy-medium?` (`rules.ss:1049`, `(tell (tell ic 'get-reference-object) 'get-bond-facet)` with a letter). The trial is a directed construction, not a run; it shows the code's reaction, not that a run reaches it.

- **Command:** the Docker command with `<case>` = `fix4-letter-trial`.
- **Fixed path on the patched build:** after one codelet, `check-for-conflicts` meets a letter with a group-category transform and returns `done`, `apply-rule` returns a list of five entries (the transforms of the five letters), and no error is raised. A real run reaches the same site: `fix4-ijkm-11` and `fix4-ijkm-126` above.
- **Evidence in the repository:** the section "A rule that reverses all the groups of a string" below.

### 0005: a group image with no start letter (`patches/fixes/0005-group-image-with-no-start-letter.patch`)

Seen on: the reconstruction with fixes 0001 to 0004, manifest
`c875a653ebf3737948c3e091e5a79e61ed56aaecdf36201d47d851dd93004e74`, trace header `revision` ending `+known-failure-fixes`, Chez Scheme 9.5.4
on Linux/amd64. Found by stage FX's sweep of 90 problems (seeds 1 to 150, cap 100,000, 13,500 runs: 42 runs stopped, 41 of them this way)
and diagnosed by stage PX. Every run below: the project recorder `python3 tests/lockstep/metacat/record.py --problem <initial> <modified> <target> --seeds <seed> --cap 100000 --jobs 1 --out <dir>`
(snapshots on), which is a fresh Episodic Memory, Self-watching on, no answer; the helper's plain `init-mcat` driver gives the same runs.

**Where it stopped, for the smallest case `fix5-wxyz-27`.** `wxyz -> xxyz; fgzzz`, seed 27, **2,851 codelets** (the 2,852nd was running; an
`answer-finder`). Exact error `Exception: attempt to apply non-procedure #f`. Call chain on the tree before the fix: `step-mcat` ->
`answer-finder` -> `apply-transforms` (`rules.ss:1341-1353`) -> `transform-image` (`rules.ss:1370-1385`) -> the image's `new-start-letter`
(`images.ss:269-287`) -> `(tell start-letter 'get-related-node arg)` at **`images.ss:281`** with `start-letter` = `#f` (the message in progress
is `(173 new-start-letter (plato-successor ...))`). The same on the project recorder: the stored recording of the build before the fix ends
with `{"t":"end","c":2852,"reason":"error","error":"Exception: attempt to apply non-procedure #f","codelets":2851}`.

**Cause.** A group is born with the start letter of its first object, `(tell (1st ordered-objects) 'get-descriptor-for plato-letter-category)`
(`groups.ss:81-82`), and `make-image` is given that as the image's start letter (`groups.ss:90`). When the group's first object is itself a
length-based group, that object has no letter category (fix 0001 already lets such a group have none, `groups.ss:43-47`), so the new image's
start letter is `#f`. In all 41 runs the image was a length-based group of two objects whose first object is a length-based group with a real
start letter and whose second is a letter-category sameness group (`xy` + `aaa`, `fg` + `zzz`). Such images are common and harmless (`wxyz` seed 3 has 6). Nothing
else sends to a start letter without asking `exists?` first: `relationship-between`, `shorten`, `extend`, `enumerate-letter`, `reverse-medium` and `new-start-letter` of a
letter given a letter (`images.ss:244-246`, `:262-266`, `:283-286`, `:318-319`, `:342`) all fail or stay absent. Only the two sends of `get-related-node`
at `images.ss:274` (a letter image) and `:281` (a group image) did not. By the 41 runs: `plato-successor` 27 times, `plato-predecessor` 14; always `:281`, never `:274`.

**All 41 runs** (stages FX and PX; "Stopped at" is the codelet count when the run stopped, from the draw-free crash driver of stage FX's sweep, and for
seeds `wxyz` 27, `ihg` 121 and `bcd` 15, 18 and 25 also from the project recorder's recording of the build before the fix, which agree; "Ended on the
patched build" is the project recorder at cap 100,000, stage P5). The 29 whose end is the same number as "Stopped at" answer at the codelet where they used to stop.

| # | Input (initial, modified, target) | Seed | Stopped at (codelets) | Ended on the patched build |
| ---: | --- | ---: | ---: | --- |
| 1 | `wxyz` `xxyz` `fgzzz` | 22 | 14,312 | answer `ggh`, 14,312 codelets |
| 2 | `wxyz` `xxyz` `fgzzz` | 27 | 2,851 | answer `ggh`, 2,851 codelets |
| 3 | `wxyz` `xxyz` `fgzzz` | 29 | 3,900 | answer `ggh`, 3,900 codelets |
| 4 | `wxyz` `xxyz` `fgzzz` | 30 | 4,692 | answer `ghi`, 4,692 codelets |
| 5 | `wxyz` `xxyz` `fgzzz` | 42 | 5,445 | answer `ghi`, 5,445 codelets |
| 6 | `wxyz` `xxyz` `fgzzz` | 49 | 45,529 | answer `gh`, 45,529 codelets |
| 7 | `wxyz` `xxyz` `fgzzz` | 62 | 16,093 | answer `ggh`, 16,093 codelets |
| 8 | `wxyz` `xxyz` `fgzzz` | 63 | 4,803 | answer `gh`, 4,803 codelets |
| 9 | `wxyz` `xxyz` `fgzzz` | 80 | 9,375 | answer `ggh`, 9,375 codelets |
| 10 | `wxyz` `xxyz` `fgzzz` | 109 | 7,375 | answer `ggh`, 7,375 codelets |
| 11 | `wxyz` `xxyz` `fgzzz` | 120 | 7,390 | answer `ggh`, 7,390 codelets |
| 12 | `wxyz` `xxyz` `fgzzz` | 124 | 4,367 | answer `ggh`, 4,367 codelets |
| 13 | `wxyz` `xxyz` `fgzzz` | 132 | 13,096 | answer `gh`, 13,096 codelets |
| 14 | `wxyz` `xxyz` `fgzzz` | 134 | 4,470 | answer `ggh`, 4,470 codelets |
| 15 | `wxyz` `xxyz` `fgzzz` | 144 | 8,956 | answer `gh`, 8,956 codelets |
| 16 | `wxyz` `xxyz` `fgzzz` | 146 | 4,206 | answer `ggh`, 4,206 codelets |
| 17 | `ihg` `ih` `xyaaa` | 20 | 14,514 | answer `yz`, 14,514 codelets |
| 18 | `ihg` `ih` `xyaaa` | 22 | 6,843 | answer `yz`, 6,843 codelets |
| 19 | `ihg` `ih` `xyaaa` | 44 | 7,275 | answer `yzbbb`, 7,275 codelets |
| 20 | `ihg` `ih` `xyaaa` | 48 | 31,967 | answer `wx`, 31,967 codelets |
| 21 | `ihg` `ih` `xyaaa` | 56 | 9,440 | answer `yz`, 9,440 codelets |
| 22 | `ihg` `ih` `xyaaa` | 57 | 45,615 | answer `yzbbb`, 76,967 codelets |
| 23 | `ihg` `ih` `xyaaa` | 95 | 37,500 | answer `yzbbb`, 37,500 codelets |
| 24 | `ihg` `ih` `xyaaa` | 99 | 12,213 | answer `ih`, 16,022 codelets |
| 25 | `ihg` `ih` `xyaaa` | 118 | 9,579 | answer `yz`, 9,579 codelets |
| 26 | `ihg` `ih` `xyaaa` | 121 | 6,615 | answer `yz`, 6,615 codelets |
| 27 | `ihg` `ih` `xyaaa` | 138 | 26,590 | answer `yzbbb`, 26,590 codelets |
| 28 | `ihg` `ih` `xyaaa` | 143 | 18,055 | answer `yz`, 18,055 codelets |
| 29 | `bcd` `bc` `xbxmnm` | 15 | 84,683 | answer `awlml`, 84,683 codelets |
| 30 | `bcd` `bc` `xbxmnm` | 18 | 10,351 | answer `wawlm`, 57,496 codelets |
| 31 | `bcd` `bc` `xbxmnm` | 25 | 65,176 | answer `wawlml`, 65,176 codelets |
| 32 | `bcd` `bc` `xbxmnm` | 29 | 80,130 | cap, 100,000 |
| 33 | `bcd` `bc` `xbxmnm` | 30 | 21,931 | answer `wawlm`, 69,420 codelets |
| 34 | `bcd` `bc` `xbxmnm` | 44 | 67,600 | answer `lml`, 75,770 codelets |
| 35 | `bcd` `bc` `xbxmnm` | 49 | 65,377 | cap, 100,000 |
| 36 | `bcd` `bc` `xbxmnm` | 50 | 47,855 | answer `lml`, 61,305 codelets |
| 37 | `bcd` `bc` `xbxmnm` | 73 | 37,072 | answer `wawlml`, 37,072 codelets |
| 38 | `bcd` `bc` `xbxmnm` | 85 | 75,535 | cap, 100,000 |
| 39 | `bcd` `bc` `xbxmnm` | 86 | 95,492 | cap, 100,000 |
| 40 | `bcd` `bc` `xbxmnm` | 99 | 74,877 | cap, 100,000 |
| 41 | `bcd` `bc` `xbxmnm` | 121 | 74,925 | cap, 100,000 |

- **Directed trial for `images.ss:274`** (case `fix5-image-trial`; stage PX's trial `T2`, no run). A letter image with start letter `#f` is sent a platonic
  relation. Built exactly, with `(define (group-image start subs) (make-image start plato-length plato-successor plato-length plato-right subs))` and
  `g` = `(make-image #f plato-letter-category plato-successor plato-length plato-right (list (group-image plato-x (list (make-letter-image plato-x) (make-letter-image plato-y))) (group-image plato-a (list (make-letter-image plato-a) (make-letter-image plato-a)))))` (a group image with
  start letter `#f`), then `(tell g 'letter fail)`, which makes it a letter image with `sub-images` empty and start letter still `#f`, then
  `(tell g 'new-start-letter plato-successor fail)`. On the tree before the fix: `Exception: attempt to apply non-procedure #f` at `images.ss:274`
  (stage PX's log `logs/trial_px_ref.log`: `T2 ... CRASH attempt to apply non-procedure ~s (#f)`). No recorded run reaches it.
  The case builds the same state directly (`(make-image #f #f #f #f #f '())`, a letter image with no start letter) and, for `:281`, a group image with two letter sub-images and start
  letter `#f`.
- **Command:** the Docker command with `<case>` = `fix5-wxyz-27`, `fix5-ihg-121`, `fix5-bcd-18` or `fix5-image-trial`.
- **Fixed path on the patched build:** for the three runs, a group image with start letter `#f` is sent a platonic relation (successor, predecessor or identity) at the codelet of
  "Stopped at" (2,851, 6,615 and 10,351), `new-start-letter` returns, and the run ends as the table says (`fix5-wxyz-27`: answer `ggh` after 2,851 codelets; `fix5-ihg-121`: `yz` after 6,615; `fix5-bcd-18`: `wawlm` after 57,496).
  For the trial, the letter image calls its `fail` procedure and keeps no start letter; the group image returns `done`, its sub-images become `b` and `c`, and its start letter is still none; the controls (a letter image `a`, a group image starting at `a`, sent successor) become `b`.
- **Evidence in the repository:** the golden cases `wxyz-xxyz-fgzzz` s27 and s13 in `tests/lockstep/golden/extended_cases.json`, and the section "A group image with no start letter" below.

### 0006: a rule change with nothing left to describe (`patches/fixes/0006-literal-only-change-not-describable.patch`)

Seen on: the reconstruction with fixes 0001 to 0004 (as for 0005). Found by the same sweep; one run of 13,500. Recorded with the project recorder, cap 100,000, snapshots on, fresh Episodic Memory, Self-watching on.

| Case key | Input (initial, modified, target) | Seed | Stopped at | Exact error | Call chain (before the fix) | Ended on the patched build |
| --- | --- | ---: | ---: | --- | --- | --- |
| `fix6-abcx-19` | `abcx` `xwva` `ijkr` | 19 | 8,012 codelets (a `rule-scout`) | `Exception: attempt to apply non-procedure #f` | `rule-scout` (`rules.ss:397`) -> `set-quality-values` (`:196`) -> `compute-rule-abstractness` (`:1609`) -> `map` -> `tell-all` -> `get-conceptual-depth` sent to `#f` | answer `rqpa`, 14,991 codelets |

**Cause.** A literal DirCtgy or GroupCtgy change is disallowed, and `make-change-template` (`rules.ss:1060-1065`) strips the literal descriptor from the
change template's descriptor list. When a subobjects DirCtgy change has only a literal descriptor, the list is left as `()`. `instantiate-change-template`
(`rules.ss:893-912`) then `stochastic-pick`s from `()`, which gives `#f` without drawing a random number, and the abstractness of the rule asks `#f` for its conceptual depth.
`rule-scout` already stops a rule whose objects cannot be described ("Not all rule objects are describable. Fizzling.", `possible-to-instantiate?`, `rules.ss:445-458`), but that function did not look at the changes. Every
change template with an empty descriptor list crashed. `instantiate-change-template` is the only `stochastic-pick` of a change template's descriptor list, and
`rule-scout` is the only caller of `instantiate-rule-clause-template`.

- **Command:** the Docker command with `<case>` = `fix6-abcx-19`.
- **Fixed path on the patched build:** `possible-to-instantiate?` returns `#f` at codelet 8,012 for a template list whose objects can all be described and one of whose change templates has an empty descriptor list, so the `rule-scout` fizzles (the helper's wrapper checks all three conditions), and the run goes on and ends with the answer `rqpa` after 14,991 codelets.
- **Evidence in the repository:** the golden case `abcx-xwva-ijkr` s19 in `tests/lockstep/golden/extended_cases.json` and the section "A rule change with nothing left to describe" below.

---

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

*Historical for the first three cases.* The commands in
[How to reproduce the problem behind each fix](#how-to-reproduce-the-problem-behind-each-fix) run them. On the patched
tree each of the three ends with an answer after the same number of codelets as the crash, and the helper exits with status
0 (it used to exit with 255, on the reference reconstruction, after printing the case banner and the exception). Follow
[README.md](README.md) to install the dependencies and reconstruct Metacat. Run the commands from the **Metacat folder
containing this note**, not from `build/source`. Docker must be running. No full study or GPU is needed.

A nonzero exit now means that the run did not do what its record says: a crash of the patched build (the patch is then
incomplete), a different codelet or a different end. Exit status 2 means an unknown case key. The unpatched build is
never run by this project, and no tool in it takes a fix off a tree.

The helper is [tests/reproduce-failures.ss](tests/reproduce-failures.ss). It
contains only our small test driver, not upstream Metacat source. It runs one case per process and exits 0 only if
the case does what its record says. For advanced diagnosis,
Chez provides `--debug-on-exception` and continuation inspection; see the
[Chez 9.5 debugging manual](https://cisco.github.io/ChezScheme/csug9.5/debug.html).
An interactive Docker session is needed to use debugger prompts.

Docker rebuilds do not pin every Debian package. The published study manifest
records the actual Scheme/runtime hashes and dependency versions. A failure
to reproduce on a different runtime is evidence to investigate, not a reason
to overwrite the recorded data or assume the bug is fixed. Cross-platform and
headed/GUI reproduction of these particular failures has not been established.

## Where the Evidence Lives

The study was recorded on the build without the fixes, and it is kept as the record of the three study failures (it is
used for nothing else unless the user asks; see the README of `tests/lockstep/`). The evidence for each fix, in the
repository, is in "How to reproduce the problem behind each fix" above; nothing in that section points outside git.

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

**Petacat.** The patched recordings are stored data in `tests/lockstep/traces-known-failures/fixes/`, and Petacat replays
them to the end with no differences. The recordings of the crashes themselves (`traces-known-failures/reference/`) and their
registry entries were removed on 2026-11-08, at the user's ruling; "How to reproduce the problem behind each fix" is the
record, and `tests/reproduce-failures.ss` proves on the patched build that each case takes the fixed path. Investigating
these seeds found two Petacat port bugs on the same path, which are fixed.

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

## A rule that reverses all the groups of a string

Added 2026-11-07. Metacat builds a rule clause of the form `(subobjects <GroupCtgy> <Opposite>)` on purpose:
`rule-scout` abstracts it when every bridge of a cluster that spans the left side carries a group-category slippage
(`rules.ss:607-641`), and it has its own English, "Reverse starting and ending points of all objects in string"
(`get-change-phrase`, `rules.ss:1874-1883`). The rule form is found by a stage of Petacat's reach studies, and it
stopped patched Metacat in about 2 runs in 80 for `pqcd -> cbpo; tugh` (seeds 1 and 69), once in 80 for
`defpqr -> pondcb; hijstu` (seed 79) and twice in 80 for `abcxyz -> cbazyx; ijkpqr` (seeds 35 and 74). In each the
run ended with `Exception in cadr: incorrect list structure #f`, at `rules.ss:1351`.

**Cause.** `get-BondFacet-change` (`rules.ss:1054-1059`) makes the BondFacet change only for scope `self`, because the
facet says which medium (letter category or length) a group is reversed along. A `subobjects` change has no BondFacet
partner, so `get-intrinsic-transforms` (`rules.ss:1528-1548`) gives each subobject group the bare transform
`(<GroupCtgy> <Opposite>)`, and `apply-transforms` (`rules.ss:1341-1353`) took the medium as
`(2nd (assq plato-bond-facet transforms))`, which is `(cadr #f)`. Nothing stops the rule before that:
`rule-evaluator` (`rules.ss:463`) calls `currently-works?` (`rules.ss:223-235`), which calls `apply-rule` without a guard.
A second error was behind the first. When a rule of this form is applied to a string with a letter among its
subobjects (the target `ijkm`, a group and a letter), `check-for-conflicts` asks `same-dimension-as-GroupCtgy-medium?`
(`rules.ss:1049`), which sent `get-bond-facet` to the letter, and a letter has no such message: patched Metacat stops with
`bad message "get-bond-facet" sent to object of type letter` (shown in stage V by a directed trial, a rule of this form
applied to a string of letters; none of 1,000 recorded runs of five problems of this shape stopped on it; the four that stopped, stopped on the first crash).

**The fix: the second patch group's `patches/fixes/0004-subobjects-group-category-reversal.patch`.** It keeps the
rule and makes it do what its English says, in two places of `rules.ss`:
- `apply-transforms` takes the medium from the BondFacet transform when the object has one, and otherwise from the
  object's own image (`(tell image 'get-bond-facet)`, `images.ss:145`), so each group reverses along its own medium.
  `reverse-medium` already does nothing for a letter image (`images.ss:241`).
- `same-dimension-as-GroupCtgy-medium?` answers false for anything that is not a group (`(and (group? object) ...)`),
  because a letter has no medium.

Rejected: making `apply-rule` fail when a list has no medium (the rule then does other than it says), skipping the
reversal (the same), and not building the clause at `rules.ss:637-641` (that changes perception, and removes a rule
Metacat builds on purpose). The patch also adds §1.6 to the reconstructed `CODE-FIXES.md`.

Other sites that could meet the same thing were read, and none needed a change (the patch is written on the lines it
replaces, so no line of `rules.ss` moves and these citations stay true):
- `get-change-phrase` (`rules.ss:1874-1883`) takes its non-`self` branch for the English of this rule and never asks for a facet. It
  reads `(3rd BondFacet-change)` only for a `self` group-category change, which comes with the facet that
  `get-BondFacet-change` makes (a self change is made for a bridge's object, a group: a letter has no group-category description).
  The graphics files name these nodes only as Slipnet positions and theme labels (`slipnet-graphics.ss`, `theme-graphics.ss`),
  and never read a rule's changes or transforms.
- `attach-length-to-appropriate-groups` (`answers.ss:1075-1091`) tests `(exists? BondFacet-transform)` before it reads it.
- The failure path: `apply-transforms` hands `fail` the three-element transform `(GroupCtgy Opposite medium)`
  (`rules.ss:1303-1308`, `:1351-1353`), and the snag explanation reads `(tell (3rd transform) 'get-lowercase-name)`
  (`trace.ss:1111-1115`). `fail` is called under a group-category transform only from inside `reverse-medium`
  (`images.ss:239-253`), through `new-start-letter` or `new-length`, and only in a branch that exists because the medium
  is the letter category or length, so the name is never asked of `#f`; with no medium `reverse-medium` calls nothing.
- A group-category transform never reaches a string image, which has no `get-bond-facet` message (`images.ss:37-102`,
  where it would reach `base-object`): a string has no group-category change, and the subobjects of a string are its
  letters and groups. In the 720 recorded runs below the counting wrapper met no string image at one.

**Verified on 2026-11-07.**
- The five runs above, recorded again with the patch (with state snapshots), are identical record for record to the same
  runs recorded without it, up to the codelet where they used to crash, and then run on without a crash: `pqcd` seeds 1
  and 69, `defpqr` seed 79 and `abcxyz` seed 35 reach the cap of 6,000 codelets, and `abcxyz` seed 74 answers `kjirqp`
  at 5,168 codelets.
- 266 recorded runs that never crashed (the stage P sample: plain, justify, episodes, a person's actions, Self-watching
  off and long runs, and `abc -> abd; xyz` seeds 1 to 10), recorded with and without the patch, are identical record for
  record, state snapshots included, apart from the header's `revision`.
- 720 further runs with snapshots, 240 seeds of each of the three problems, ended without an error: 305 answers, 393 caps
  and 22 give-ups. A counting wrapper (in its own process, wrapping `apply-transforms` and `check-for-conflicts`) found the
  runs that reached a transform list with a group-category transform and no BondFacet transform inside the recorded run:
  seeds 1, 69 and 238 of `pqcd`, 79, 102 and 161 of `defpqr`, and 35 and 74 of `abcxyz`. The seeds of the letter case are in
  `agents-workspace/metacat-cleanup/round2/V-crash/REPORT-FIX.md`.
- With the target `ijkm` (a group and a letter), seeds 11 and 126 reach `check-for-conflicts` with a letter that has a
  group-category transform, and answer `kjim`: a group reversed and the letter left as it is.

## A group image with no start letter

Added 2026-11-08. Stage FX swept 90 problems at seeds 1 to 150 with cap 100,000 (13,500 runs) and found 42 runs where patched Metacat (fixes 0001 to 0004)
stopped with `Exception: attempt to apply non-procedure #f`: 16 of `wxyz -> xxyz; fgzzz`, 12 of `ihg -> ih; xyaaa`, 13 of `bcd -> bc; xbxmnm`, and one of another kind
(next section). Stage PX diagnosed the 41 of this kind by tracing every one with a wrapper on `make-image` that draws no random number.

**Cause.** A group's image takes the start letter of the group's first object, `#f` when that object is a length-based group (`groups.ss:81-82`, `:90`); the
group then has no letter category, as fix 0001's comment at `groups.ss:43-47` says. `answer-finder` later applies the rule's letter-category successor or
predecessor to that image (`apply-transforms`, `transform-image`), and `new-start-letter` sent `get-related-node` to the image's start letter at `images.ss:281`
(group branch) with no test. The sibling send at `images.ss:274` (letter image) has the same defect and is reached by a directed trial only. Born-`#f` images are
common and harmless; the others of the Scheme's image code already treat an absent letter by failing or staying absent.

**The fix: the second patch group's `patches/fixes/0005-group-image-with-no-start-letter.patch`**, written on the two lines it replaces (no line of `images.ss` moves):
- `images.ss:274`: `(and (exists? start-letter) (tell start-letter 'get-related-node arg))`, so a letter image with no start letter finds no related letter and fails, as that branch already does.
- `images.ss:281`: `(set! start-letter (and (exists? start-letter) (tell start-letter 'get-related-node arg)))`, so none stays none; the sub-images have already been given the relation on the line above.

Rejected: giving the image a start letter at birth (it changes runs that do not crash and undoes fix 0001's withholding), taking it from the first sub-image,
`(fail)` in the group branch (completed rule applications would snag, so the rule would do other than it says), and catching the error in `answer-finder`.
The patch also adds §1.7 to the reconstructed `CODE-FIXES.md`.

Other sites that could meet the same `#f` were read, and none needed a change: every other send to an image's start letter (`images.ss:120-123` the `print` method, a debugging
display no run calls; `:144` `get-letter`, which only returns it; `:177` `make-letter` for a letter image, whose start letter always exists; `:229` `generate`;
`:244-246` and `:262-266` `reverse-medium` and `new-alpha-position-category`, which pass the letters to `replace-all` and so to `new-start-letter`, whose first test is `(not (exists? arg))`; `:283-286`, `:318-319`, `:336-342`),
and every other use of a group's `get-initial-letter-category` (`groups.ss:51-56`, tested with `exists?` by fix 0001; `:94`, handed to `relationship-between`, which answers `#f` unless
all nodes exist; `rules.ss:1052`, `get-ending-letter-category`, compared with `eq?`).

**Verified on 2026-11-08.**
- The 42 crash runs of the two sections, recorded again with the fixes (snapshots on, cap 100,000): the six runs whose recordings of the build before the fix exist (`wxyz` 27, `ihg` 121, `bcd` 15, 18, 25, `abcx` 19), the old recording minus its end record is an exact prefix of the new one; for the other 36 only the codelet of the stop is known, and for all 42
  a one-off copy of the helper with a case for each run (same wrappers, no random draw) shows the first event of the fixed path at exactly the codelet where the run used to stop and the end of the table. 36 end with an answer (29 at the codelet where they used to stop) and 6 `bcd` runs reach the cap with no further error.
- 90 runs that never crashed, recorded again (the 89 never-crashing reference traces of stage PX on the four crash problems and the 19 corpus problems, and `ihg` 91 at cap 100,000), are identical record for record, snapshots included, apart from the header's `revision`; the 266-run sample of earlier stages
  (plain, justify, episode, person-action, Self-watching off, long, and `abc -> abd; xyz` seeds 1 to 10) is identical too.

## A rule change with nothing left to describe

Added 2026-11-08. One of the 42 runs of the sweep above, `abcx -> xwva; ijkr` seed 19, stopped in a `rule-scout` at codelet 8,012.

**Cause.** See the entry for 0006 above: a literal DirCtgy change is disallowed, `make-change-template` (`rules.ss:1060-1065`) empties its descriptor list when the literal was the only descriptor, `instantiate-change-template` picks
from the empty list and gets `#f`, and `compute-rule-abstractness` sends `get-conceptual-depth` to it. The intent of the code is clear from both ends: literal DirCtgy changes are disallowed on purpose, and `rule-scout`
already fizzles on a rule that cannot be described.

**The fix: the second patch group's `patches/fixes/0006-literal-only-change-not-describable.patch`**, written on the line it replaces (no line of `rules.ss` moves). `possible-to-instantiate?` (`rules.ss:445-458`) now needs, for an intrinsic clause template,
`(andmap (lambda (change-template) (pair? (3rd change-template))) (3rd template))` as well as a describable object, so a template with an empty descriptor list makes `rule-scout` fizzle. The patch adds §1.8 to `CODE-FIXES.md`.

Rejected: dropping the empty change from the template (the rule would say less than the bridges did), filtering `#f` in `compute-rule-abstractness`, skipping the change in `abstract-change-descriptions` (that changes the random stream), and allowing a literal DirCtgy change (it is disallowed on purpose).

Other sites that `stochastic-pick` a change template's descriptor list: none. `instantiate-change-template` (`rules.ss:893-912`) is the only one, and its only caller is `instantiate-rule-clause-template` (`rules.ss:866-878`), whose only caller is `rule-scout` (`rules.ss:437`), after the
`possible-to-instantiate?` test. The other `stochastic-pick`s of the engine (`bonds.ss`, `groups.ss`, `bridges.ss`, `answers.ss`, `justify.ss`, `descriptions.ss`, `coderack.ss`) pick from their own lists.

**Verified on 2026-11-08.** The run, recorded again with the fix, is identical record for record to the stored recording of the build before the fix up to its stop, then goes on (the `rule-scout` fizzles) and answers `rqpa` after 14,991 codelets. The same 90-run and 266-run samples as for 0005 are identical.
