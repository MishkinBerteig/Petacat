# List of letter-string analogy problems

Every letter-string analogy problem used in testing and exploration of Petacat and Metacat, with the most common answer and the best answer found. Each problem appears in exactly one row. Problems are written `abc → abd; xyz → ?`.

**Data gathered 2026-10-29. No new runs of Metacat or Petacat were made for this document.** It is built only from recordings, logs, test files, docs and database rows that already existed.

## How to read it

**Groups and precedence.** A problem sits under the first group in this list that it belongs to. Its other uses go in "Also used in".

| # | Group | What it is |
|---|---|---|
| 1 | Dissertation demos | The 13 distinct problems behind Metacat's `demos.ss` runs (Marshall, 1999, mostly Chapter 5 figures and sections; also in `seed_data/demo_problems.json`). |
| 2 | Copy tests | `copy1` to `copy6`, the project's own "copy" tests where the target equals the initial string. |
| 3 | Own exploration in the app | Problems tried in the running app (`runs` table of the local database). |
| 4 | Dissertation-cited, port parity | Problems the dissertation discusses that are not in `demos.ss`, used as targets in the port docs and parity tests. |
| 5 | Lockstep snag and desync corpora | Problems recorded for the lockstep snag, desync and known-failure corpora, not already above. |
| 6 | Snag-explanation sweep | The sweep that hunted for snags and checked snag explanations (about 100 problems; 28 were also recorded as full traces). |
| 7 | Fidelity widened net | The fidelity agent's widened net: 660 runs on 84 problems, plus 24 episodes on 8 problems (2026-10-29). |
| 8 | Test fixtures only | Problems hard-coded in unit or module tests that no run data covers. |

The 19 problems in groups 1 and 2 are the "nineteen demo problems" that every lockstep corpus, the episode corpus, the academic support-set study and `ORACLE-COMPARISON.md` use. Their "Also used in" cells are long for that reason.

**Most common answer.** The most frequent outcome across all existing recorded runs of that problem. Metacat's own runs are preferred, in this order:

1. Metacat reference runs: the 19 demo problems, 10,250 to 51,000 runs each (`academic/data/reference-single-runs.json`, the sampled-to-saturation benchmark, run headless with a 100,000-codelet cap).
2. The 1,000-run Metacat study of `wxyz → vxyz; abcd` (seeds 101 to 1100, 2026-10-28).
3. Recorded single Metacat runs from the lockstep corpora (development, held-out, snags, desync, known failures) and the October 2026 sweeps (snag sweep, fidelity net). Each run is counted once however many corpora hold it. These samples are small (4 to 22 runs) and are marked "small sample".
4. Petacat runs in the app database, only where nothing else exists, and labelled as such.

"No answer" counts as an outcome. Where it is the most frequent outcome the cell says so and also gives the most frequent actual answer. Where it is 10% or more but not the top, the cell adds it. For the reference runs, "gave up" and "hit the step cap" are separate outcomes as recorded. For the smaller recorded samples they are shown together with the split in brackets.

**"Best" answer found.** The answer with the highest answer quality (Metacat's own score, `round(0.6 * rule quality + 0.4 * (100 - answer temperature))`) seen in any existing run, with that quality and the number of readings. Quality readings come from three places. Metacat's comment-window text ("Found the answer ... Answer quality = N", also "Successfully justified answer" in justify mode) covers the development, held-out, justify and episode corpora and the snag corpus. Metacat episode answer explanations cover the 8-run fidelity episodes. The app's `answer_descriptions` table holds Petacat's own quality for the user's app runs. The table shows Petacat's number only where it beats every Metacat reading, and then also gives Metacat's best. Petacat's fidelity-test recordings were not mixed in.

Where no quality was recorded, the cell shows a proxy: the answer with the lowest answer-time temperature (the temperature in the last recorded snapshot before the answer) across the recorded Metacat runs, with ties broken by frequency. The proxy is crude: temperatures cluster near the 18-degree floor, so differences are small. If no quality and no temperature exist, the cell is "—".

Intended "deep" answers that no run ever produced are noted in the Evidence column, not in the "found" column.

**Also used in** abbreviations: *dev corpus* and *held-out corpus* are `tests/lockstep/traces` and `traces-heldout`; *justify corpus* is the demo answers justified over seeds 1 to 5; *episode corpus* is 8-run episodes with memory carried; *support-set study / oracle comparison* is the academic 19-problem study and `ORACLE-COMPARISON.md`; *fidelity net* is group 7; *snag sweep* is group 6.

## The tables

### 1. Dissertation demos (13 problems)

| Problem | Most common answer | "Best" answer found | Also used in | Evidence / sample |
|---|---|---|---|---|
| `abc → abd; mrrjjj → ?` | `mrrkkk` 63.9% of 11,000 Metacat reference runs | `mrrkkk` / `mrrjjk` quality 89 (Metacat) | lockstep dev corpus, held-out corpus, justify corpus, episode corpus, support-set study / oracle comparison, snag sweep, app runs, unit/module tests, client fixtures, numeric-backend tests, smoke tests | demos: run1, abc-mrrkkk, abc-mrrjjjj (§5.2; §5.2.3); 30 recorded single runs; 40 episode runs; 116 quality readings |
| `xqc → xqd; mrrjjj → ?` | `mrrkkk` 68.5% of 11,000 Metacat reference runs | `mrrkkk` quality 87 (Metacat, 27 obs) | lockstep dev corpus, held-out corpus, justify corpus, episode corpus, support-set study / oracle comparison, snag sweep | demos: run2, run5, xqc-mrrkkk, xqc-mrrjjjj (§5.2; §5.2.3); 30 recorded single runs; 24 episode runs; 57 quality readings; demo answer `mrrjjjj` (Run 5) never produced by a free run |
| `rst → rsu; xyz → ?` | `xyu` 38.5% of 21,000 Metacat reference runs; no answer 11.2% | `wyz` quality 90 (Metacat, 22 obs) | lockstep dev corpus, held-out corpus, justify corpus, episode corpus, support-set study / oracle comparison, snag sweep, unit/module tests | demos: run3, rst-xyu, rst-wyz, rst-uyz (§5.2; §5.2.3); 30 recorded single runs; 40 episode runs; 90 quality readings |
| `abc → abd; xyz → ?` | `xyd` 36.8% of 11,000 Metacat reference runs | `wyz` quality 91 (Metacat, 26 obs) | lockstep dev corpus, held-out corpus, justify corpus, episode corpus, support-set study / oracle comparison, snag sweep, app runs, unit/module tests, client fixtures, numeric-backend tests | demos: run4, run7, abc-xyd, abc-wyz, abc-dyz, fig5.10 +1 more (§5.2; §5.2.3; §5.3.2); 36 recorded single runs; 40 episode runs; 101 quality readings |
| `eqe → qeq; abbbc → ?` | `qeeeq` 53.3% of 47,500 Metacat reference runs | `cbbba` quality 70 (Metacat, 5 obs) | lockstep dev corpus, held-out corpus, justify corpus, episode corpus, support-set study / oracle comparison, snag sweep, unit/module tests | demos: run6, run8, eqe-qeeeq, eqe-aaabccc (§5.2; §5.2.3); 30 recorded single runs; 24 episode runs; 47 quality readings; demo answer `aaabccc` (Run 6) never produced by a free run |
| `eqe → qeq; abbba → ?` | `baaab` 58.2% of 51,000 Metacat reference runs | `baaab` quality 77 (Metacat, 40 obs) | lockstep dev corpus, held-out corpus, justify corpus, episode corpus, support-set study / oracle comparison, snag sweep, unit/module tests | demos: eqe-baaab, eqe-aaabaaa (§5.2.3); 30 recorded single runs; 40 episode runs; 115 quality readings; demo answer `aaabaaa` never produced by a free run |
| `eeqee → qeeq; xxixx → ?` | `qeeq` 48.4% of 51,000 Metacat reference runs; no answer 14.3% | `ixxi` quality 82 (Metacat, 15 obs) | lockstep dev corpus, held-out corpus, episode corpus, support-set study / oracle comparison, snag sweep, unit/module tests, client fixtures | demos: fig5.4-top, fig5.5-top, fig5.4-bottom, fig5.5-bottom (§5.3.1); 30 recorded single runs; 24 episode runs; 42 quality readings |
| `aabc → aabd; ijkk → ?` | `ijll` 46.4% of 18,125 Metacat reference runs | `ijkl` quality 91 (Metacat, 25 obs) | lockstep dev corpus, held-out corpus, justify corpus, episode corpus, support-set study / oracle comparison, snag sweep, unit/module tests | demos: fig5.7, fig5.8 (§5.3.2); 30 recorded single runs; 40 episode runs; 120 quality readings |
| `abc → cba; mrrjjj → ?` | `jjjrrm` 85.2% of 30,750 Metacat reference runs | `mrrjjj` quality 97 (Metacat, 11 obs) | lockstep dev corpus, held-out corpus, justify corpus, episode corpus, known-failures corpus, support-set study / oracle comparison, snag sweep, unit/module tests | demos: misc1 (demos.ss misc); 32 recorded single runs; 24 episode runs; 57 quality readings |
| `abc → abd; ijk → ?` | `ijl` 95.3% of 11,000 Metacat reference runs | `ijl` quality 90 (Metacat, 30 obs) | lockstep dev corpus, held-out corpus, justify corpus, episode corpus, support-set study / oracle comparison, snag sweep, unit/module tests, numeric-backend tests | demos: misc2 (demos.ss misc); 30 recorded single runs; 24 episode runs; 45 quality readings |
| `abc → aabbcc; kkjjii → ?` | `kkjjii` 32.6% of 19,000 Metacat reference runs; no answer 11.3% | `kji` / `kkkjjjiii` quality 95 (Metacat) | lockstep dev corpus, held-out corpus, episode corpus, known-failures corpus, support-set study / oracle comparison, snag sweep, unit/module tests | demos: misc3 (demos.ss misc); 31 recorded single runs; 24 episode runs; 51 quality readings |
| `a → b; z → ?` | `b` 49.8% of 11,000 Metacat reference runs | `y` quality 98 (Metacat, 8 obs) | lockstep dev corpus, held-out corpus, episode corpus, support-set study / oracle comparison, snag sweep | demos: misc4 (demos.ss misc); 30 recorded single runs; 24 episode runs; 50 quality readings |
| `abc → abd; glz → ?` | `gld` 25.8% of 11,125 Metacat reference runs | `flz` / `hlz` quality 84 (Metacat) | lockstep dev corpus, held-out corpus, episode corpus, support-set study / oracle comparison, snag sweep | demos: misc5 (demos.ss misc); 30 recorded single runs; 24 episode runs; 43 quality readings |

### 2. Copy tests (6 problems)

| Problem | Most common answer | "Best" answer found | Also used in | Evidence / sample |
|---|---|---|---|---|
| `ab → c; ab → ?` | `c` 86.6% of 10,875 Metacat reference runs | `c` quality 91 (Metacat, 35 obs) | lockstep dev corpus, held-out corpus, episode corpus, support-set study / oracle comparison, snag sweep | demo: copy1 (user copy series); 30 recorded single runs; 24 episode runs; 45 quality readings |
| `bc → d; bc → ?` | `d` 100.0% of 11,250 Metacat reference runs | `d` quality 91 (Metacat, 39 obs) | lockstep dev corpus, held-out corpus, episode corpus, support-set study / oracle comparison, snag sweep, unit/module tests | demo: copy2 (user copy series); 30 recorded single runs; 24 episode runs; 39 quality readings |
| `xy → z; xy → ?` | `z` 100.0% of 11,000 Metacat reference runs | `z` quality 91 (Metacat, 39 obs) | lockstep dev corpus, held-out corpus, episode corpus, support-set study / oracle comparison, snag sweep | demo: copy3 (user copy series); 30 recorded single runs; 24 episode runs; 39 quality readings |
| `zy → x; zy → ?` | `x` 86.2% of 11,125 Metacat reference runs | `x` quality 91 (Metacat, 37 obs) | lockstep dev corpus, held-out corpus, episode corpus, support-set study / oracle comparison, snag sweep | demo: copy4 (user copy series); 30 recorded single runs; 24 episode runs; 45 quality readings |
| `aabb → cc; aabb → ?` | `cc` 50.0% of 15,500 Metacat reference runs; no answer 48.5% | `ccbb` quality 83 (Metacat, 1 obs) | lockstep dev corpus, held-out corpus, episode corpus, support-set study / oracle comparison, snag sweep | demo: copy5 (user copy series); 30 recorded single runs; 24 episode runs; 22 quality readings |
| `abc → d; abc → ?` | `d` 86.7% of 10,250 Metacat reference runs | `d` quality 91 (Metacat, 37 obs) | lockstep dev corpus, held-out corpus, episode corpus, support-set study / oracle comparison, snag sweep | demo: copy6 (user copy series); 30 recorded single runs; 24 episode runs; 45 quality readings |

### 3. Own exploration in the app (7 problems)

| Problem | Most common answer | "Best" answer found | Also used in | Evidence / sample |
|---|---|---|---|---|
| `abc → abc; xyz → ?` | `xyz` 1 of 1 Petacat app runs (small sample) | — | snag sweep | app runs 6 |
| `abC → abD; xyz → ?` | no answer (gave up) 2 of 2 Petacat app runs (small sample) | — | — | app runs 12, 13 |
| `abcd → dcba; xyz → ?` | `zyx` 5 of 5 recorded Metacat runs (small sample) | `zyx` quality 97 (Petacat app run 14) | snag sweep, fidelity net | app runs 14; 5 recorded single runs |
| `abcdefghijklm → mlkjihgfedcba; nopqrstuvwxyz → ?` | `zyxwvutsrqpon` 1 of 1 Petacat app runs (small sample) | `zyxwvutsrqpon` quality 94 (Petacat app run 15) | — | app runs 15 |
| `1234 → 4321; nopqrstuvwxyz → ?` | no answer (gave up) 1 of 1 Petacat app runs (small sample) | — | — | app runs 16 |
| `abcd → abce; wxyz → ?` | no answer (gave up) 3 of 6 Petacat app runs (small sample); most frequent answer `wxye` / `wxyz` / `vxyz` 1 | `vxyz` quality 87 (Petacat app run 23) | — | app runs 18, 19, 20, 21, 22, 23 |
| `wxyz → vxyz; abcd → ?` | `vbcd` 33.6% of 1,000 Metacat runs (seeds 101-1100); no answer 24.3% | `abce` quality 89 (Petacat app run 27); Metacat's best `vbcd` 75 | snag corpus, snag sweep, 1,000-run Metacat/Petacat comparison; README | app runs 24, 25, 26, 27; 112 recorded single runs; 1 quality reading |

### 4. Dissertation-cited, port parity (6 problems)

| Problem | Most common answer | "Best" answer found | Also used in | Evidence / sample |
|---|---|---|---|---|
| `abc → abd; iijjkk → ?` | `iijjkl` 3 of 4 recorded Metacat runs (small sample) | `iijjll` (proxy: lowest answer-time temperature, T=18, over 4 Metacat runs) | unit/module tests, client fixtures | §3.4; parity test; port doc: documented answers `iijjkl`, `iijjll`; 4 recorded single runs |
| `abc → abd; kji → ?` | `kjj` 8 of 10 recorded Metacat runs (small sample); no answer 1 | `kjh` / `kjj` quality 90 (Metacat) | snag sweep, fidelity net, fidelity episodes, unit/module tests | Fig. 4.5; parity test; port doc: documented answers `kjj`, `lji`; 10 recorded single runs; 24 episode runs; 15 quality readings |
| `abc → abcd; ijk → ?` | `ijkl` 10 of 10 recorded Metacat runs (small sample) | `ijkl` (proxy: lowest answer-time temperature, T=4, over 10 Metacat runs) | snag sweep, fidelity net | §3.3.3; port doc: documented answer `ijkl`; 10 recorded single runs |
| `abc → cba; ijkl → ?` | — (no run recorded) | — | snag sweep | port review doc: dissertation/Metacat answers `lkji`, `ljki`, `jjkk` |
| `abc → aabbcc; ijk → ?` | `iijjkk` 6 of 10 recorded Metacat runs (small sample); no answer 2 | `ijk` quality 97 (Metacat, 3 obs) | snag sweep, fidelity net, fidelity episodes | port review doc: dissertation answer `iijjkk`; 10 recorded single runs; 24 episode runs; 18 quality readings |
| `pq → qp; ijkl → ?` | — (no run recorded) | — | — | §3.1 family, named in the port review doc |

### 5. Lockstep snag and desync corpora (8 problems)

| Problem | Most common answer | "Best" answer found | Also used in | Evidence / sample |
|---|---|---|---|---|
| `a → b; xyz → ?` | no answer (9 hit the codelet cap) 9 of 13 recorded Metacat runs (small sample); most frequent answer `xyz` 3 | `wxy` quality 95 (Metacat, 1 obs) | snag sweep, unit/module tests | lockstep snag corpus / desync corpus; 13 recorded single runs; 1 quality reading |
| `aaa → bbb; xyz → ?` | no answer (8 hit the codelet cap) 8 of 14 recorded Metacat runs (small sample); most frequent answer `xyz` 5 | — | snag sweep | lockstep desync corpus; 14 recorded single runs |
| `ab → ba; xyz → ?` | `zyx` 6 of 12 recorded Metacat runs (small sample) | `zyx` quality 97 (Metacat, 1 obs) | snag sweep | lockstep snag corpus; 12 recorded single runs; 1 quality reading |
| `abc → abcd; xyz → ?` | `xyz` 5 of 12 recorded Metacat runs (small sample); no answer 4 | `xyz` quality 96 (Metacat, 1 obs) | snag sweep, unit/module tests | lockstep snag corpus; 12 recorded single runs; 1 quality reading |
| `abc → bcd; xyz → ?` | `xyz` 4 of 13 recorded Metacat runs (small sample); no answer 3 | — | snag sweep | lockstep desync corpus; 13 recorded single runs |
| `abc → cba; abcabc → ?` | `abcabc` 6 of 12 recorded Metacat runs (small sample) | `abcabc` quality 89 (Metacat, 1 obs) | snag sweep | lockstep snag corpus; 12 recorded single runs; 1 quality reading |
| `abc → zyx; xyz → ?` | `xyz` 5 of 12 recorded Metacat runs (small sample); no answer 3 | `xyz` quality 94 (Metacat, 1 obs) | snag sweep | lockstep snag corpus; 12 recorded single runs; 1 quality reading |
| `eqe → qeq; mrrjjj → ?` | `qrrqqq` 4 of 12 recorded Metacat runs (small sample) | `qrrqqq` quality 57 (Metacat, 1 obs) | snag sweep | lockstep snag corpus; 12 recorded single runs; 1 quality reading |

### 6. Snag-explanation sweep (68 problems)

| Problem | Most common answer | "Best" answer found | Also used in | Evidence / sample |
|---|---|---|---|---|
| `aab → aac; xyzz → ?` | no answer (6 hit the codelet cap) 6 of 12 recorded Metacat runs (small sample); most frequent answer `wyzz` / `yyzz` 2 | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `aabb → aabc; xyz → ?` | no answer (3 gave up, 5 hit the codelet cap) 8 of 12 recorded Metacat runs (small sample); most frequent answer `xyz` 3 | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `aabbcc → ccbbaa; xyz → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abbc → abcc; xyz → ?` | `xyzz` 7 of 13 recorded Metacat runs (small sample) | — | — | snag sweep (28 traced problems); 13 recorded single runs |
| `abc → aab; mrrjjj → ?` | tie: `mrrjjj` / `aab`, 3 each of 12 recorded Metacat runs (small sample) | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abc → aab; xyz → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → aabbcc; xyz → ?` | `xxyyzz` 10 of 10 recorded Metacat runs (small sample) | `xxyyzz` (proxy: lowest answer-time temperature, T=6, over 10 Metacat runs) | fidelity net | snag sweep (snag text only); 10 recorded single runs from the fidelity net |
| `abc → ab; xyz → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abb; xyz → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abcd; aabbcc → ?` | `aabbccdd` 10 of 12 recorded Metacat runs (small sample) | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abc → abd; aabbcc → ?` | `aabbdd` 9 of 10 recorded Metacat runs (small sample); no answer 1 | `aabbdd` (proxy: lowest answer-time temperature, T=22, over 9 Metacat runs) | fidelity net | snag sweep (snag text only); 10 recorded single runs from the fidelity net |
| `abc → abd; aabbccdd → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; abbba → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; abcba → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; bba → ?` | `bbb` 8 of 12 recorded Metacat runs (small sample) | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abc → abd; bcd → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; cba → ?` | `bba` 11 of 22 recorded Metacat runs (small sample) | `bba` (proxy: lowest answer-time temperature, T=15, over 10 Metacat runs) | fidelity net, unit/module tests | snag sweep (28 traced problems); 22 recorded single runs |
| `abc → abd; ccb → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; ijjkkk → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; kjihg → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; lmnoq → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; mnopqr → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; qeq → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; rrjjj → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; rstuvw → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; srqp → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; wxyz → ?` | tie: `vxyz` / `wxyd`, 3 each of 12 recorded Metacat runs (small sample) | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abc → abd; xyx → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; xyyz → ?` | `xyyd` 5 of 12 recorded Metacat runs (small sample); no answer 2 | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abc → abd; xyzyx → ?` | `xyzyy` 7 of 12 recorded Metacat runs (small sample); no answer 4 | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abc → abd; xyzz → ?` | no answer (3 gave up, 1 hit the codelet cap) 4 of 12 recorded Metacat runs (small sample); most frequent answer `xydd` / `xyzd` 2 | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abc → abd; zyx → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; zyxw → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → abd; zzz → ?` | no answer (10 hit the codelet cap) 10 of 12 recorded Metacat runs (small sample); most frequent answer `zzz` / `zzd` 1 | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abc → abd; zzzaaa → ?` | `zzzbbb` 6 of 12 recorded Metacat runs (small sample) | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abc → abe; xyz → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → bca; xyz → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cab; xyz → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cba; aabbcc → ?` | `ccbbaa` 9 of 10 recorded Metacat runs (small sample) | `aabbcc` (proxy: lowest answer-time temperature, T=5, over 10 Metacat runs) | fidelity net | snag sweep (snag text only); 10 recorded single runs from the fidelity net |
| `abc → cba; aabc → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cba; abc → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cba; bcd → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cba; cba → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cba; ccc → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cba; ijk → ?` | `kji` 8 of 10 recorded Metacat runs (small sample) | `kji` (proxy: lowest answer-time temperature, T=4, over 10 Metacat runs) | fidelity net | snag sweep (snag text only); 10 recorded single runs from the fidelity net |
| `abc → cba; lmn → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cba; pqrs → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cba; xyx → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cba; xyz → ?` | `zyx` 14 of 14 recorded Metacat runs (small sample) | `xyz` / `zyx` quality 98 (Metacat) | fidelity net, fidelity episodes | snag sweep (snag text only); 14 recorded single runs from the fidelity net; 24 episode runs; 16 quality readings |
| `abc → cba; xyzz → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cba; zyx → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cbd; xyz → ?` | tie: `zyd` / no answer (gave up), 4 each of 12 recorded Metacat runs (small sample) | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abc → cdb; xyz → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → cde; xyz → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abc → d; xyz → ?` | `d` 5 of 12 recorded Metacat runs (small sample); no answer 2 | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abc → dcb; xyz → ?` | `dcb` 8 of 12 recorded Metacat runs (small sample) | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abc → xyz; abc → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `abcd → abc; xyzw → ?` | no answer (7 hit the codelet cap) 7 of 12 recorded Metacat runs (small sample); most frequent answer `xyzw` 4 | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `abcd → dcba; abcd → ?` | `dcba` 4 of 5 recorded Metacat runs (small sample) | `dcba` (proxy: lowest answer-time temperature, T=4, over 5 Metacat runs) | fidelity net | snag sweep (snag text only); 5 recorded single runs from the fidelity net |
| `cba → abc; xyz → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `cba → abc; zyx → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `cba → cbd; ijk → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `eqe → qeq; xyz → ?` | `qeq` 5 of 12 recorded Metacat runs (small sample); no answer 2 | — | — | snag sweep (28 traced problems); 12 recorded single runs |
| `ijk → kji; abc → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `mrrjjj → mrrkkk; abc → ?` | `abd` 5 of 10 recorded Metacat runs (small sample); no answer 1 | `abd` (proxy: lowest answer-time temperature, T=6, over 9 Metacat runs) | fidelity net | snag sweep (snag text only); 10 recorded single runs from the fidelity net |
| `rst → rsu; abbba → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `rst → rsu; abc → ?` | — (snag text recorded, answers not) | — | — | snag sweep (snag text only; answers not recorded) |
| `xyz → xya; abc → ?` | `aba` 18 of 22 recorded Metacat runs (small sample) | `aba` (proxy: lowest answer-time temperature, T=19, over 10 Metacat runs) | fidelity net | snag sweep (28 traced problems); 22 recorded single runs |

### 7. Fidelity widened net (71 problems)

| Problem | Most common answer | "Best" answer found | Also used in | Evidence / sample |
|---|---|---|---|---|
| `a → b; a → ?` | `b` 10 of 10 recorded Metacat runs (small sample) | `b` (proxy: lowest answer-time temperature, T=0, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `a → b; c → ?` | `d` 10 of 10 recorded Metacat runs (small sample) | `d` (proxy: lowest answer-time temperature, T=3, over 10 Metacat runs) | unit/module tests | fidelity widened net; 10 recorded single runs |
| `aa → ab; xx → ?` | `xy` 7 of 10 recorded Metacat runs (small sample); no answer 1 | `xy` (proxy: lowest answer-time temperature, T=9, over 9 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `aaa → aab; xyz → ?` | no answer (10 hit the codelet cap) 10 of 10 recorded Metacat runs (small sample) | — | — | fidelity widened net; 10 recorded single runs |
| `aaaa → aaab; xxxx → ?` | no answer (3 hit the codelet cap) 3 of 5 recorded Metacat runs (small sample); most frequent answer `aaab` / `xxxy` 1 | `aaab` (proxy: lowest answer-time temperature, T=47, over 2 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `aab → aac; ijk → ?` | `ijl` 8 of 10 recorded Metacat runs (small sample); no answer 1 | `ijl` (proxy: lowest answer-time temperature, T=7, over 9 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `aab → abb; xyz → ?` | `xyz` 6 of 10 recorded Metacat runs (small sample); no answer 1 | `xyz` quality 95 (Metacat, 10 obs) | fidelity episodes | fidelity widened net + 8-run episodes; 10 recorded single runs; 24 episode runs; 24 quality readings |
| `aabb → aabc; ijkk → ?` | no answer (4 hit the codelet cap) 4 of 5 recorded Metacat runs (small sample); most frequent answer `aabc` 1 | `aabc` (proxy: lowest answer-time temperature, T=12, over 1 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `aabbcc → aabbdd; ijkkll → ?` | tie: `ijkkmm` / no answer (gave up), 2 each of 5 recorded Metacat runs (small sample) | `ijkkllmm` (proxy: lowest answer-time temperature, T=22, over 3 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `aabc → aabd; ijk → ?` | `ijl` 8 of 10 recorded Metacat runs (small sample); no answer 1 | `ijl` (proxy: lowest answer-time temperature, T=19, over 9 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `aabc → aabd; mrrjjj → ?` | no answer (5 hit the codelet cap) 5 of 10 recorded Metacat runs (small sample); most frequent answer `mrrkkk` 3 | `mrrjjjj` quality 88 (Metacat, 3 obs) | fidelity episodes | fidelity widened net + 8-run episodes; 10 recorded single runs; 24 episode runs; 14 quality readings |
| `aabc → aabd; xyz → ?` | tie: `xyd` / no answer (gave up), 4 each of 10 recorded Metacat runs (small sample) | `xyd` (proxy: lowest answer-time temperature, T=18, over 6 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `ab → ab; xy → ?` | `xy` 5 of 5 recorded Metacat runs (small sample) | `xy` (proxy: lowest answer-time temperature, T=4, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `ab → ac; xy → ?` | `xz` 10 of 10 recorded Metacat runs (small sample) | `xz` (proxy: lowest answer-time temperature, T=19, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `ab → ba; cd → ?` | `dc` 5 of 5 recorded Metacat runs (small sample) | `dc` (proxy: lowest answer-time temperature, T=6, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abab → abac; ijij → ?` | no answer (5 hit the codelet cap) 5 of 5 recorded Metacat runs (small sample) | — | — | fidelity widened net; 5 recorded single runs |
| `abb → abc; ijk → ?` | `abc` 5 of 10 recorded Metacat runs (small sample); no answer 4 | `abc` (proxy: lowest answer-time temperature, T=7, over 6 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → ab; ijk → ?` | `ij` 10 of 10 recorded Metacat runs (small sample) | `ij` (proxy: lowest answer-time temperature, T=3, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → abc; ijk → ?` | `ijk` 5 of 5 recorded Metacat runs (small sample) | `ijk` (proxy: lowest answer-time temperature, T=4, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abc → abcd; mrrjjj → ?` | tie: `mrrjjj` / no answer (gave up), 5 each of 10 recorded Metacat runs (small sample) | `mrrjjj` (proxy: lowest answer-time temperature, T=7, over 5 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → abd; aaa → ?` | `aab` 8 of 10 recorded Metacat runs (small sample); no answer 1 | `aab` (proxy: lowest answer-time temperature, T=20, over 9 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → abd; aab → ?` | `aac` 5 of 5 recorded Metacat runs (small sample) | `aac` (proxy: lowest answer-time temperature, T=18, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abc → abd; ab → ?` | `ac` 10 of 10 recorded Metacat runs (small sample) | `ac` (proxy: lowest answer-time temperature, T=16, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → abd; abb → ?` | `acc` 4 of 5 recorded Metacat runs (small sample) | `acc` (proxy: lowest answer-time temperature, T=18, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abc → abd; abcabc → ?` | `abcabd` 4 of 10 recorded Metacat runs (small sample); no answer 3 | `abcbcd` (proxy: lowest answer-time temperature, T=35, over 7 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → abd; baa → ?` | `bab` 3 of 5 recorded Metacat runs (small sample) | `aaa` (proxy: lowest answer-time temperature, T=18, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abc → abd; bdf → ?` | `bdg` 10 of 10 recorded Metacat runs (small sample) | `bdg` (proxy: lowest answer-time temperature, T=32, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → abd; cdcd → ?` | `cdce` 3 of 5 recorded Metacat runs (small sample) | `cdde` (proxy: lowest answer-time temperature, T=29, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abc → abd; efg → ?` | `efh` 5 of 5 recorded Metacat runs (small sample) | `efh` (proxy: lowest answer-time temperature, T=18, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abc → abd; ijkk → ?` | `ijll` 5 of 10 recorded Metacat runs (small sample) | `ijll` quality 90 (Metacat, 3 obs) | fidelity episodes | fidelity widened net + 8-run episodes; 10 recorded single runs; 24 episode runs; 15 quality readings |
| `abc → abd; lmnop → ?` | `lmnoq` 9 of 10 recorded Metacat runs (small sample) | `lmnoq` (proxy: lowest answer-time temperature, T=18, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → abd; mmnnoo → ?` | tie: `mmnnpp` / `mmnnop`, 2 each of 5 recorded Metacat runs (small sample) | `mmnnpp` (proxy: lowest answer-time temperature, T=18, over 4 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abc → abd; rst → ?` | `rsu` 9 of 10 recorded Metacat runs (small sample) | `rsu` (proxy: lowest answer-time temperature, T=18, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → abd; stuvw → ?` | `stuvx` 5 of 5 recorded Metacat runs (small sample) | `stuvx` (proxy: lowest answer-time temperature, T=19, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abc → abd; tuv → ?` | `tuw` 4 of 5 recorded Metacat runs (small sample) | `tuw` (proxy: lowest answer-time temperature, T=18, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abc → abd; xyzxyz → ?` | no answer (10 hit the codelet cap) 10 of 10 recorded Metacat runs (small sample) | — | — | fidelity widened net; 10 recorded single runs |
| `abc → abd; z → ?` | no answer (4 hit the codelet cap) 4 of 5 recorded Metacat runs (small sample); most frequent answer `d` 1 | `d` (proxy: lowest answer-time temperature, T=54, over 1 Metacat runs) | unit/module tests | fidelity widened net; 5 recorded single runs |
| `abc → abd; zab → ?` | `zac` 9 of 10 recorded Metacat runs (small sample) | `zac` (proxy: lowest answer-time temperature, T=31, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → abd; zzyyxx → ?` | `zzyyxy` 2 of 5 recorded Metacat runs (small sample); no answer 1 | `zzyyww` (proxy: lowest answer-time temperature, T=22, over 4 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abc → bcd; aabbcc → ?` | `bbccdd` 10 of 10 recorded Metacat runs (small sample) | `bbccdd` (proxy: lowest answer-time temperature, T=5, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → bcd; ijk → ?` | `jkl` 10 of 10 recorded Metacat runs (small sample) | `ijk` quality 96 (Metacat, 3 obs) | fidelity episodes | fidelity widened net + 8-run episodes; 10 recorded single runs; 24 episode runs; 18 quality readings |
| `abc → cba; abcd → ?` | `dcba` 5 of 5 recorded Metacat runs (small sample) | `dcba` (proxy: lowest answer-time temperature, T=4, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abc → cba; efg → ?` | `gfe` 4 of 5 recorded Metacat runs (small sample) | `gfe` (proxy: lowest answer-time temperature, T=6, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abc → cba; kji → ?` | `ijk` 10 of 10 recorded Metacat runs (small sample) | `ijk` (proxy: lowest answer-time temperature, T=5, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → d; ijk → ?` | `l` 6 of 10 recorded Metacat runs (small sample) | `l` (proxy: lowest answer-time temperature, T=8, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abc → xyz; ijk → ?` | `xyz` 5 of 5 recorded Metacat runs (small sample) | `xyz` (proxy: lowest answer-time temperature, T=8, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abcabc → abcabd; ijkijk → ?` | no answer (5 hit the codelet cap) 5 of 5 recorded Metacat runs (small sample) | — | — | fidelity widened net; 5 recorded single runs |
| `abcd → abc; ijkl → ?` | `ijk` 5 of 5 recorded Metacat runs (small sample) | `ijk` (proxy: lowest answer-time temperature, T=1, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abcd → abcde; xyz → ?` | `xyz` 2 of 5 recorded Metacat runs (small sample) | `xyz` (proxy: lowest answer-time temperature, T=7, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abcd → abce; ijkl → ?` | `ijkm` 10 of 10 recorded Metacat runs (small sample) | `ijkm` quality 89 (Metacat, 3 obs) | fidelity episodes | fidelity widened net + 8-run episodes; 10 recorded single runs; 24 episode runs; 11 quality readings |
| `abcd → abce; xyzw → ?` | `xyzx` 5 of 10 recorded Metacat runs (small sample); no answer 3 | `xyzv` (proxy: lowest answer-time temperature, T=27, over 7 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `abcde → abcdf; uvwxy → ?` | `uvwxz` 5 of 5 recorded Metacat runs (small sample) | `uvwxz` (proxy: lowest answer-time temperature, T=21, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `abcde → abcdf; vwxyz → ?` | no answer (7 hit the codelet cap) 7 of 10 recorded Metacat runs (small sample); most frequent answer `vwxyf` 2 | `vwxyf` (proxy: lowest answer-time temperature, T=20, over 3 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `ace → acf; bdf → ?` | `bdg` 9 of 10 recorded Metacat runs (small sample) | `bdg` (proxy: lowest answer-time temperature, T=36, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `az → ay; bc → ?` | `bb` 9 of 10 recorded Metacat runs (small sample) | `bb` (proxy: lowest answer-time temperature, T=29, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `az → bz; ab → ?` | `bb` 5 of 5 recorded Metacat runs (small sample) | `bb` (proxy: lowest answer-time temperature, T=25, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `cba → cbb; abc → ?` | `bbc` 5 of 10 recorded Metacat runs (small sample) | `cbb` (proxy: lowest answer-time temperature, T=6, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `ccc → ddd; xyz → ?` | no answer (5 hit the codelet cap) 5 of 5 recorded Metacat runs (small sample) | — | — | fidelity widened net; 5 recorded single runs |
| `cde → cdf; zab → ?` | `zac` 4 of 5 recorded Metacat runs (small sample) | `zab` (proxy: lowest answer-time temperature, T=31, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `eqe → qeq; abc → ?` | `qeq` 7 of 10 recorded Metacat runs (small sample); no answer 1 | `qeq` (proxy: lowest answer-time temperature, T=34, over 9 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `hij → hik; xyz → ?` | `xyk` 2 of 5 recorded Metacat runs (small sample) | `wyz` (proxy: lowest answer-time temperature, T=20, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `ijk → ijl; abc → ?` | `abd` 5 of 5 recorded Metacat runs (small sample) | `abd` (proxy: lowest answer-time temperature, T=18, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `lmn → lmo; xyz → ?` | `xyo` 2 of 5 recorded Metacat runs (small sample) | `wyz` (proxy: lowest answer-time temperature, T=20, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `mno → mnp; xyz → ?` | `xyp` 2 of 5 recorded Metacat runs (small sample) | `wyz` (proxy: lowest answer-time temperature, T=20, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `pqr → pqs; xyz → ?` | tie: `xys` / `wyz`, 3 each of 10 recorded Metacat runs (small sample) | `wyz` (proxy: lowest answer-time temperature, T=18, over 8 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `xy → xz; ab → ?` | `ac` 5 of 5 recorded Metacat runs (small sample) | `ac` (proxy: lowest answer-time temperature, T=18, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `yz → xz; ab → ?` | `xb` 6 of 10 recorded Metacat runs (small sample) | `ac` (proxy: lowest answer-time temperature, T=18, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `za → zb; ij → ?` | `ik` 10 of 10 recorded Metacat runs (small sample) | `ik` (proxy: lowest answer-time temperature, T=29, over 10 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `zab → zac; abc → ?` | `abd` 5 of 5 recorded Metacat runs (small sample) | `abd` (proxy: lowest answer-time temperature, T=28, over 5 Metacat runs) | — | fidelity widened net; 5 recorded single runs |
| `zyx → zyw; abc → ?` | `abb` 8 of 10 recorded Metacat runs (small sample); no answer 1 | `abw` (proxy: lowest answer-time temperature, T=18, over 9 Metacat runs) | — | fidelity widened net; 10 recorded single runs |
| `zz → yz; aa → ?` | `ab` 3 of 5 recorded Metacat runs (small sample); no answer 1 | `ab` (proxy: lowest answer-time temperature, T=5, over 4 Metacat runs) | — | fidelity widened net; 5 recorded single runs |

### 8. Test fixtures only (7 problems)

| Problem | Most common answer | "Best" answer found | Also used in | Evidence / sample |
|---|---|---|---|---|
| `a → aa; b → ?` | — (used only as a test fixture) | — | — | test fixture |
| `aa → bb; cc → ?` | — (used only as a test fixture) | — | — | test fixture |
| `abb → c; abb → ?` | — (used only as a test fixture) | — | — | test fixture |
| `abc → abcc; xyz → ?` | — (used only as a test fixture) | — | — | test fixture |
| `abc → abd; abc → ?` | — (used only as a test fixture) | — | — | test fixture |
| `abc → abd; abcde → ?` | — (used only as a test fixture) | — | — | test fixture |
| `ijk → ijl; ijk → ?` | — (used only as a test fixture) | — | — | test fixture |

## Notes and caveats

- **Counts.** 186 problems in 8 groups. 130 have a most common answer from Metacat runs, 5 from Petacat app runs only, and 51 have none. Of those none, 42 are snag-sweep problems whose snag text was logged but whose answers were not, 7 are test-only fixtures, and 2 are dissertation-cited problems nobody ran.
- **Source runs lost.** 110 rows quote recorded runs that were deleted on 2026-10-29. That covers all of group 7, 26 rows of group 6, 13 rows across groups 3 to 5, and the 1,000-run `wxyz → vxyz; abcd` study. The figures stand as recorded, but they can no longer be checked against their runs. See `GOVERNANCE-NOTES.md`.
- **Small samples.** Only the 19 demo problems (and `wxyz → vxyz; abcd`) have thousands of Metacat runs. Everything else rests on 4 to 22 recorded runs. Read those percentages as a rough guide.
- **Reference counts and `ORACLE-COMPARISON.md`.** The reference run counts here come from `academic/data/reference-single-runs.json`. `ORACLE-COMPARISON.md` quotes somewhat larger Metacat samples for the same problems. The top answers and their shares agree to within about a point.
- **Cap differences.** Recorded runs use different codelet caps: 100,000 in the lockstep corpora, 6,000 in the snag recordings, 4,000 in the fidelity net's single runs and 5,000 in its episodes. A run that hit the cap counts as "no answer". Capped outcomes are therefore more common in the fidelity net than a 100,000 cap would give.
- **Episodes.** Episode runs carry memory between the 8 runs of an episode, so their answers differ from single runs. They feed only the quality readings, never the "most common" column.
- **Quality of justified answers.** The best-quality readings include Metacat's justify mode, where the program is told the answer and asked to justify it. The score is the program's own, but the answer was not discovered. More generally, "best" means the program's own quality score, which can rate a plain or unchanged answer (e.g. `ijk` for `abc → bcd; ijk → ?`) above the answer a person would call deepest. For example, `abc → cba; mrrjjj → ?` has best quality at `mrrjjj` (97), the unchanged target, slightly above the intended `jjjrrm` (96).
- **Intended answers never produced.** Three demo answers appear only when the demo forces justification, and no free run produced them in the reference runs: `mrrjjjj` for `xqc → xqd; mrrjjj → ?` (Run 5), `aaabccc` for `eqe → qeq; abbbc → ?` (Run 6), and `aaabaaa` for `eqe → qeq; abbba → ?`. They are not in the "found" column.
- **Recordings without temperature.** The snag-sweep traces were recorded without snapshots, so those rows have neither a quality nor a temperature proxy and show "—" even where answers exist.
- **Own exploration in the app.** The app database holds 27 runs (2026-08-19 to 2026-10-28), 12 with a stored answer quality. `abC → abD; xyz → ?` (runs 12 and 13) is a distinct problem; both runs gave up. For `abc → abd; xyz → ?` the app's Petacat answers (`wyz` 76 and others) are lower than Metacat's best (91). For `wxyz → vxyz; abcd → ?` (app runs 24 to 27) Petacat reached `abce` at quality 89, above Metacat's single recorded reading (`vbcd`, 75). The 1,000-run Metacat study gave `vbcd` 33.6%, no answer 24.3%, `abce` 14.1%, `abcd` 13.8%. A 1,000-run Petacat serial study of the same problem gave `vbcd` 34.1%, no answer 22.5%, `abcd` 16.9%, `abce` 15.0%.
- **Problems with no data.** `abc → cba; ijkl → ?` and `pq → qp; ijkl → ?` were named in the port review doc but not run. Seven problems appear only as unit-test fixtures. Where a problem is also run elsewhere, that data is used, even if a test also hard-codes it.
- **Test coverage is approximate.** Test fixtures were found by searching `tests/` and the client fixtures for problem triples. Problems built dynamically inside a test, or passed under a variable name, may be missed.
