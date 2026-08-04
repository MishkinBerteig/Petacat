# Oracle comparison — Petacat against Metacat's own measured behaviour

Metacat's repository now carries a saturated stopping-state benchmark over all
nineteen demo problems, produced by the reference implementation running headless
(`oracle-out/oracle.json`, `oracle-out-copy/oracle.json`; commits `424feb0` and
`d9dddee`). That is a far better standard than Petacat's own
`tests/fixtures/expected_range.json`, which was sampled from Petacat *before* the
parity repair and therefore measures the defects the repair removed.

This file records where Petacat now stands against it. **It is a record, not a
claim of success** — several problems disagree materially and are listed here
rather than smoothed over.

## Method

- Petacat: 500 runs per problem, seeds 0..499, `numpy` backend (float64, the reference's own precision), 20,000-codelet cap, **a fresh `EpisodicMemory` per run**.
- Metacat: 10k–51k runs per problem, sampled to Good-Turing saturation, 100,000-codelet
  cap, Episodic Memory off.
- Both record three kinds of stopping state: the answer string, `*NONE*` for a run that
  ended without one, and `*CAP*` for a run that hit the codelet ceiling.

Two methodology differences are worth holding in mind when reading a row. Petacat's
cap is five times lower, so some of its `*CAP*` mass would resolve given Metacat's
budget. And Petacat's sample is two orders of magnitude smaller, so a state below
roughly 1% is not reliably distinguishable from absent.

## Agreement at a glance

Total-variation distance between the two distributions — 0 is identical, 1 is disjoint.

| TVD | problem | | Metacat n | Petacat n |
|---:|---|---|---:|---:|
| **0.01** | `bc→d; bc` | copy2 | 11,454 | 500 |
| **0.01** | `ab→c; ab` | copy1 | 10,956 | 500 |
| **0.01** | `zy→x; zy` | copy4 | 11,288 | 500 |
| **0.01** | `xy→z; xy` | copy3 | 11,288 | 500 |
| **0.03** | `abc→abd; ijk` | misc2 | 11,454 | 500 |
| **0.03** | `abc→d; abc` | copy6 | 10,292 | 500 |
| **0.04** | `xqc→xqd; mrrjjj` | run2 | 11,454 | 500 |
| **0.06** | `abc→abd; mrrjjj` | run1 | 11,122 | 500 |
| **0.19** | `abc→aabbcc; kkjjii` | misc3 | 1,660 | 500 |
| **0.20** | `abc→abd; glz` | misc5 | 11,288 | 500 |
| **0.24** | `aabc→aabd; ijkk` | fig5.7 | 14,608 | 500 |
| **0.27** | `abc→abd; xyz` | run4 | 11,122 | 500 |
| **0.28** | `rst→rsu; xyz` | run3 | 13,778 | 500 |
| **0.36** | `a→b; z` | misc4 | 11,454 | 500 |
| **0.40** | `aabb→cc; aabb` | copy5 | 31,042 | 500 |
| **0.47** | `eqe→qeq; abbba` | eqe-baaab | 51,128 | 500 |
| **0.50** | `eqe→qeq; abbbc` | run6 | 51,128 | 500 |
| **0.56** | `eeqee→qeeq; xxixx` | fig5.4-top | 51,128 | 500 |
| **0.59** | `abc→cba; mrrjjj` | misc1 | 40,836 | 500 |

Median TVD **0.20** across 19 problems; 8 of 19 at or below 0.10.

## What diverges, and how it clusters

The disagreement is not spread evenly. Eight problems agree closely (TVD <= 0.06),
and the rest fall into a small number of named patterns.

### 1. The unchanged-target answer, and giving up instead

Metacat frequently answers with the target string itself. Petacat almost never
does, and gives up in roughly the same proportion instead:

| problem | target as answer, Metacat | Petacat | `*NONE*` Metacat | Petacat |
|---|---:|---:|---:|---:|
| `rst→rsu; xyz` | 17.1% | **0.0%** | 11.4% | **32.2%** |
| `abc→abd; xyz` | 16.3% | **0.0%** | 9.7% | **35.0%** |
| `a→b; z` | 36.7% | **0.4%** | 3.2% | 5.8% |
| `abc→abd; glz` | 20.1% | **1.0%** | 5.2% | 13.4% |
| `eeqee→qeeq; xxixx` | 0.1% | 0.0% | 15.8% | **71.2%** |
| `aabb→cc; aabb` | 1.4% | 0.0% | 48.4% | **74.6%** |

This one pattern accounts for most of the total divergence. Its shape is
consistent: where the reference reports "the answer is the target unchanged",
Petacat exhausts its alternatives and stops. `a→b; z` is the cleanest case,
because `z` has no successor and the do-nothing answer is the reference's single
most common outcome there.

### 2. `abc→cba; mrrjjj` is inverted

| state | Metacat | Petacat |
|---|---:|---:|
| `jjjrrm` | 85.1% | 23.6% |
| `mrrjjj` (unchanged) | 8.7% | **66.2%** |

The same mechanism as pattern 1, seen from the other side: here the unchanged
target is what Petacat over-produces. An earlier investigation in this repository
traced the machinery line by line — bridge choice, swap-dimension selection,
concept-mapping association values — and found every step faithful, concluding the
distribution was acceptable. This benchmark shows that conclusion was wrong. The
mechanism does match; the outcome does not. The reference *applies* the
direction-reversal reading, and Petacat fails to apply it and falls through to the
target.

### 3. The `eqe → qeq` pair

`qeeeq` is under-produced (63.5% -> 24.6% and 49.4% -> 21.4%), `baaab` is
over-produced, and Petacat reaches a handful of states the reference never does
(`qabbb`, `bbbaq`, `qcbbb`, `aabbb`). These are the two problems with the widest
answer sets in the reference — 61 and 87 distinct states — so they are also the
most sensitive to any translation difference.

### 4. Codelet budget

Petacat's cap is 20,000 against the reference's 100,000, which inflates `*CAP*`
where runs are long: `abc→aabbcc; kkjjii` 10.6% -> 17.2%, `aabb→cc; aabb`
0.6% -> 14.6%. Some of that mass would resolve with the reference's budget, and
this is the one difference in the table that is methodology rather than cognition.

## Per problem

### `abc → abd ; mrrjjj → ?`  (run1)

Metacat n=11,122 · Petacat n=500 · total-variation distance **0.06**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `mrrkkk` | 63.9% | 62.2% |  |
| `mrrjjk` | 22.1% | 26.2% |  |
| `mrrjjjj` | 4.0% | 5.2% |  |
| `mrrddd` | 2.2% | 2.4% |  |
| `mrrjkk` | 2.2% | 2.2% |  |
| `mrrjjj` | 3.3% | 0.6% |  |
| `abd` | 1.3% | 0.2% |  |
| `mrrjjd` | 0.8% | 0.4% |  |
| `*CAP*` | 0.0% | 0.6% |  |

### `xqc → xqd ; mrrjjj → ?`  (run2)

Metacat n=11,454 · Petacat n=500 · total-variation distance **0.04**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `mrrkkk` | 68.6% | 71.8% |  |
| `mrrjjk` | 21.3% | 21.0% |  |
| `mrrjkk` | 3.0% | 3.2% |  |
| `mrrddd` | 2.7% | 3.0% |  |
| `mrrjjj` | 3.0% | 0.2% |  |
| `mrrjjd` | 0.9% | 0.4% |  |

### `rst → rsu ; xyz → ?`  (run3)

Metacat n=13,778 · Petacat n=500 · total-variation distance **0.28**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `xyu` | 38.0% | 43.6% |  |
| `*NONE*` | 11.4% | 32.2% | large gap |
| `wyz` | 19.7% | 12.6% |  |
| `xyz` | 17.1% | 0.0% | Petacat never reaches it |
| `uyz` | 5.6% | 4.6% |  |
| `yyz` | 5.4% | 3.0% |  |
| `rsu` | 2.7% | 2.8% |  |
| `*CAP*` | 0.0% | 1.0% | Metacat never reaches it |

### `abc → abd ; xyz → ?`  (run4)

Metacat n=11,122 · Petacat n=500 · total-variation distance **0.27**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `xyd` | 36.8% | 36.0% |  |
| `*NONE*` | 9.7% | 35.0% | large gap |
| `wyz` | 21.4% | 17.6% |  |
| `xyz` | 16.3% | 0.0% | Petacat never reaches it |
| `yyz` | 7.2% | 5.0% |  |
| `dyz` | 6.0% | 2.6% |  |
| `abd` | 2.4% | 2.4% |  |
| `*CAP*` | 0.0% | 1.4% | Metacat never reaches it |

### `eqe → qeq ; abbbc → ?`  (run6)

Metacat n=51,128 · Petacat n=500 · total-variation distance **0.50**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `qeeeq` | 63.5% | 34.0% | large gap |
| `*NONE*` | 2.5% | 21.2% | large gap |
| `qeq` | 2.9% | 15.4% |  |
| `baaaq` | 7.6% | 4.0% |  |
| `qcccb` | 7.5% | 2.6% |  |
| `qbbbq` | 7.8% | 1.6% |  |
| `bbbaq` | 0.0% | 8.4% |  |
| `cbbba` | 4.6% | 1.6% |  |
| `qcbbb` | 0.0% | 5.8% |  |
| `baaab` | 0.2% | 1.0% |  |
| `qbbbc` | 0.8% | 0.4% |  |
| `abbbq` | 0.8% | 0.2% |  |
| `cddda` | 0.0% | 0.8% |  |
| `bcaab` | 0.1% | 0.6% |  |
| `cddbc` | 0.0% | 0.6% |  |
| `cdddb` | 0.0% | 0.6% |  |

### `eqe → qeq ; abbba → ?`  (eqe-baaab)

Metacat n=51,128 · Petacat n=500 · total-variation distance **0.47**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `qeeeq` | 49.4% | 20.0% | large gap |
| `baaab` | 24.9% | 44.0% | large gap |
| `qeq` | 2.3% | 8.8% |  |
| `*NONE*` | 0.5% | 8.8% |  |
| `qbbbq` | 7.3% | 1.8% |  |
| `qabbb` | 0.0% | 7.6% | Metacat never reaches it |
| `baaaq` | 5.0% | 1.4% |  |
| `qaaab` | 5.0% | 0.8% |  |
| `abbba` | 3.3% | 1.0% |  |
| `bbbaq` | 0.0% | 3.6% | Metacat never reaches it |
| `abbbq` | 0.7% | 0.4% |  |
| `qbbba` | 0.7% | 0.2% |  |
| `baaaa` | 0.0% | 0.6% |  |

### `eeqee → qeeq ; xxixx → ?`  (fig5.4-top)

Metacat n=51,128 · Petacat n=500 · total-variation distance **0.56**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `qeeq` | 64.9% | 27.4% | large gap |
| `*NONE*` | 15.8% | 71.2% | large gap |
| `qxxi` | 5.6% | 0.4% |  |
| `ixxq` | 5.6% | 0.4% |  |
| `ixxi` | 4.4% | 0.0% | Petacat never reaches it |
| `qiq` | 1.5% | 0.0% | Petacat never reaches it |

### `aabc → aabd ; ijkk → ?`  (fig5.7)

Metacat n=14,608 · Petacat n=500 · total-variation distance **0.24**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `ijkl` | 35.5% | 50.4% |  |
| `ijll` | 46.5% | 32.2% |  |
| `ijl` | 8.9% | 0.8% |  |
| `jjkk` | 2.1% | 3.8% |  |
| `*CAP*` | 0.0% | 4.6% | Metacat never reaches it |
| `hjkk` | 1.7% | 2.6% |  |
| `ijkk` | 2.1% | 1.2% |  |
| `aabd` | 0.5% | 1.8% |  |
| `ijkd` | 0.8% | 1.4% |  |
| `ijdd` | 1.2% | 0.8% |  |

### `abc → cba ; mrrjjj → ?`  (misc1)

Metacat n=40,836 · Petacat n=500 · total-variation distance **0.59**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `jjjrrm` | 85.1% | 28.4% | large gap |
| `mrrjjj` | 8.7% | 66.2% | large gap |
| `jrrjjm` | 2.5% | 1.6% |  |
| `jrrmmm` | 2.6% | 1.4% |  |
| `cba` | 0.1% | 1.0% |  |
| `jjrrjm` | 0.2% | 0.8% |  |

### `abc → abd ; ijk → ?`  (misc2)

Metacat n=11,454 · Petacat n=500 · total-variation distance **0.03**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `ijl` | 95.3% | 95.8% |  |
| `ijd` | 2.0% | 3.6% |  |
| `ijk` | 2.0% | 0.0% | Petacat never reaches it |
| `abd` | 0.5% | 0.0% |  |

### `abc → aabbcc ; kkjjii → ?`  (misc3)

Metacat n=1,660 · Petacat n=500 · total-variation distance **0.19**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `kkjjii` | 34.0% | 37.8% |  |
| `kkkjjjiii` | 24.5% | 19.8% |  |
| `*CAP*` | 10.6% | 17.2% |  |
| `kji` | 16.6% | 6.6% |  |
| `*NONE*` | 0.5% | 4.2% |  |
| `kkjjjiii` | 2.0% | 1.6% |  |
| `kkkjjiii` | 1.1% | 2.4% |  |
| `aabbcc` | 1.9% | 0.8% |  |
| `kkkjjjii` | 0.9% | 1.4% |  |
| `kkjjiii` | 1.5% | 0.6% |  |
| `kjiii` | 0.5% | 1.0% |  |
| `kjjji` | 0.2% | 1.0% |  |
| `kkkji` | 0.5% | 0.6% |  |
| `kkkjjji` | 0.5% | 0.6% |  |
| `kkkjiii` | 0.5% | 0.6% |  |
| `kkjjjii` | 0.4% | 0.6% |  |
| `kkkjji` | 0.3% | 0.6% |  |

### `a → b ; z → ?`  (misc4)

Metacat n=11,454 · Petacat n=500 · total-variation distance **0.36**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `b` | 49.9% | 63.4% |  |
| `y` | 10.1% | 30.4% | large gap |
| `z` | 36.7% | 0.4% | large gap |
| `*NONE*` | 3.2% | 5.8% |  |

### `abc → abd ; glz → ?`  (misc5)

Metacat n=11,288 · Petacat n=500 · total-variation distance **0.20**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `gld` | 26.0% | 30.4% |  |
| `hlz` | 21.9% | 26.6% |  |
| `flz` | 16.6% | 17.2% |  |
| `glz` | 20.1% | 1.0% | large gap |
| `*NONE*` | 5.2% | 13.4% |  |
| `dlz` | 8.4% | 8.8% |  |
| `abd` | 1.9% | 1.2% |  |
| `*CAP*` | 0.0% | 1.4% |  |

### `ab → c ; ab → ?`  (copy1)

Metacat n=10,956 · Petacat n=500 · total-variation distance **0.01**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `c` | 86.6% | 85.2% |  |
| `ab` | 13.4% | 14.0% |  |
| `*NONE*` | 0.0% | 0.8% |  |

### `bc → d ; bc → ?`  (copy2)

Metacat n=11,454 · Petacat n=500 · total-variation distance **0.01**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `d` | 100.0% | 99.4% |  |

### `xy → z ; xy → ?`  (copy3)

Metacat n=11,288 · Petacat n=500 · total-variation distance **0.01**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `z` | 100.0% | 98.6% |  |
| `*NONE*` | 0.0% | 1.0% | Metacat never reaches it |

### `zy → x ; zy → ?`  (copy4)

Metacat n=11,288 · Petacat n=500 · total-variation distance **0.01**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `x` | 86.1% | 84.8% |  |
| `zy` | 13.9% | 13.8% |  |
| `*NONE*` | 0.0% | 1.4% | Metacat never reaches it |

### `aabb → cc ; aabb → ?`  (copy5)

Metacat n=31,042 · Petacat n=500 · total-variation distance **0.40**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `*NONE*` | 48.4% | 74.6% | large gap |
| `cc` | 48.5% | 10.8% | large gap |
| `*CAP*` | 0.6% | 14.6% |  |
| `aabb` | 1.4% | 0.0% | Petacat never reaches it |

### `abc → d ; abc → ?`  (copy6)

Metacat n=10,292 · Petacat n=500 · total-variation distance **0.03**

| state | Metacat | Petacat | |
|---|---:|---:|---|
| `d` | 86.7% | 87.6% |  |
| `abc` | 13.2% | 10.6% |  |
| `*NONE*` | 0.0% | 1.2% |  |
