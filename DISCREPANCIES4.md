# DISCREPANCIES4 — every variation between Petacat and the Metacat oracle

**What this is.** One entry per variation found by comparing Petacat against
Metacat's published reference sets. Each records the problem, the discrepancy
type, and the run detail needed to reproduce and eventually diagnose it.

**What this is not.** There are no explanations here. Nothing below says *why* a
variation occurred, and no entry names a cause, a suspect mechanism or a fix.
Run detail is recorded because a root-cause analysis will need it, not because
it implies one.

## Measurement conditions

| | |
|---|---|
| Petacat | commit `cc25a4a`, `numpy` backend (float64), **20,000-codelet cap** |
| reference | `../Metacat/oracle/derived/`, from Metacat `46a479b` |
| single-run reference | 374,500 runs, 100,000-codelet cap |
| convergence reference | 9,500 episodes × 8 runs, 100,000-codelet cap |
| sample | 100 tries per problem per mode, 19 problems |
| seeds | single: `900000 + i`, i ∈ 0…99 · episodic: episode *e* run *i* uses `900000 + 8e + i` |
| harness | `scripts/compare_to_metacat.py`; full output in `measurements/vs-metacat.json` |

**The two caps differ.** Petacat ran at 20,000 codelets, the reference at
100,000. Any Petacat `*CAP*` is therefore not comparable to a reference `*CAP*`.

**The two modes share a seed range.** Single-run seeds `900000…900099` overlap
the episodic range `900000…900799`; episode *e* run 0 uses seed `900000 + 8e`, so
every eighth single-run seed recurs as an episode's first run. Runs at those
seeds are the same run, since an episode's first run also starts from empty
memory.

## Discrepancy types

| type | meaning |
|---|---|
| **NOVEL** | a member Petacat produced that is not in the reference set at all |
| **CONDITION** | a difference in measurement conditions, not in behaviour |

## Summary

**NOVEL: 22 distinct (problem, mode, member) variations**, over 33 runs.

| mode | problems affected | distinct members | runs |
|---|---:|---:|---:|
| single | 5 of 19 | 5 | 5 |
| episodic | 7 of 19 | 17 | 28 |

Reference `f1_over_n` — the rate at which the reference itself produces an unseen
member — is given per entry, because it differs by three orders of magnitude
between the two modes. The single-run sets are sampled to `f1/n ≤ 1e-4`; the
convergence sets are not.

---

## Single-run variations

100 runs per problem, each from a fresh Episodic Memory, against
`single-run-sets.json`.

### `eqe-baaab` — `eqe → qeq ; abbba → ?`

**NOVEL `abbbb`**, 1 of 100 runs. Reference set: 51 members over 51,000 runs,
`f1/n` = 0.00026.

| seed | codelets | final T | answer quality | answer T | snags | target groups |
|---:|---:|---:|---:|---:|---:|---:|
| 900056 | 2,026 | 41.0 | 75.0 | 41.0 | 0 | — |

Top rules in the Workspace at answer time:

```
extrinsic (string StringPos whole) swap<LetterCtgy>
intrinsic (letter StringPos lmost) [LetterCtgy->q]
  || intrinsic (letter StringPos middle) [LetterCtgy->e]
  || intrinsic (letter StringPos rmost) [LetterCtgy->q]
```

### `run6` — `eqe → qeq ; abbbc → ?`

**NOVEL `cdddb`**, 1 of 100 runs. Reference set: 80 members over 47,500 runs,
`f1/n` = 0.00008.

| seed | codelets | final T | answer quality | answer T | snags |
|---:|---:|---:|---:|---:|---:|
| 900058 | 2,074 | 41.0 | 75.0 | 41.0 | 1 |

Top rules in the Workspace at answer time:

```
intrinsic (letter StringPos lmost) [LetterCtgy->q]
  || intrinsic (letter StringPos middle) [LetterCtgy->e]
  || intrinsic (letter StringPos rmost) [LetterCtgy->q]
extrinsic (string StringPos whole) swap<LetterCtgy>
```

### `copy5` — `aabb → cc ; aabb → ?`

**NOVEL `aac`**, 1 of 100 runs. Reference set: 13 members over 15,500 runs,
`f1/n` = 0.00006.

| seed | codelets | final T | answer quality | answer T | snags |
|---:|---:|---:|---:|---:|---:|
| 900059 | 1,023 | 13.0 | 47.0 | 13.0 | 0 |

Top rule in the Workspace at answer time:

```
intrinsic (group AlphaPos first) [LetterCtgy->c; ObjectCtgy->letter]
  || intrinsic (group StringPos rmost) [LetterCtgy->succ; ObjectCtgy->letter]
```

### `copy1` — `ab → c ; ab → ?`

**NOVEL `*NONE*`** (the run stopped without an answer), 1 of 100 runs. Reference
set: 2 members over 10,875 runs — `c` 86.6%, `ab` 13.4% — `f1/n` = 0.00000. The
reference recorded no `*NONE*` and no `*CAP*` on this problem.

| seed | codelets | final T | snags |
|---:|---:|---:|---:|
| 900068 | 2,287 | 38.0 | 0 |

The run terminated at 2,287 codelets, well below the 20,000 cap.

### `run1` — `abc → abd ; mrrjjj → ?`

**NOVEL `*CAP*`** (the run reached the codelet ceiling), 1 of 100 runs. Reference
set: 11 members over 11,000 runs, `f1/n` = 0.00000. The reference recorded
`*NONE*` on this problem but no `*CAP*`.

| seed | codelets | final T | snags |
|---:|---:|---:|---:|
| 900038 | 20,000 | 53.0 | 0 |

Top rule in the Workspace at the cap:

```
intrinsic (letter StringPos rmost) [LetterCtgy->succ]
```

**CONDITION.** This run hit Petacat's 20,000-codelet cap. The reference's cap is
100,000. Whether this run would have produced an answer between 20,000 and
100,000 codelets is not measured here, and the entry cannot be read as a
behavioural difference until it is.

---

## Episodic variations

100 episodes of 8 runs per problem, Episodic Memory carried forward within an
episode, against `convergence-sets.json`. An episode's **convergence answer** is
its last run that produced an answer; `*NONE*` and `*CAP*` runs are skipped
looking backwards.

The reference convergence sets are **not** sampled to saturation. Their
`f1_over_n` is given per problem below and reaches 0.0160.

### `eqe-baaab` — `eqe → qeq ; abbba → ?`

Reference set: 19 members over 500 episodes, `f1/n` = 0.0080.

**NOVEL `abbbb`, 7 of 100 episodes** — the largest single variation in this
document.

| episode | position | seed | codelets | final T | answer quality | snags |
|---:|---:|---:|---:|---:|---:|---:|
| 3 | 7 | 900031 | 2,033 | 44.0 | 74.0 | 0 |
| 16 | 7 | 900135 | 3,160 | 41.0 | 75.0 | 0 |
| 59 | 7 | 900479 | 15,686 | 42.0 | 75.0 | 0 |
| 73 | 7 | 900591 | 1,711 | 41.0 | 75.0 | 0 |
| 78 | 5 | 900629 | 7,983 | 41.0 | 75.0 | 1 |
| 91 | 7 | 900735 | 8,675 | 44.0 | 74.0 | 0 |
| 92 | 6 | 900742 | 10,911 | 43.0 | 74.0 | 0 |

Answer quality is 74–75 in every case. Six of the seven land at position 6 or 7,
the last two runs of the episode.

**NOVEL `aqqqp`**, 1 episode — ep 75, position 7, seed 900607, 8,350 codelets,
T 41.0, quality 49.0, 1 snag.
**NOVEL `baaba`**, 1 episode — ep 12, position 7, seed 900103, 19,831 codelets,
T 43.0, quality 74.0, 0 snags.
**NOVEL `qrrbq`**, 1 episode — ep 71, position 7, seed 900575, 2,871 codelets,
T 45.0, quality 56.0, 0 snags.

### `run6` — `eqe → qeq ; abbbc → ?`

Reference set: 25 members over 500 episodes, `f1/n` = 0.0160 — the highest of any
problem.

**NOVEL `cdddb`, 5 of 100 episodes.**

| episode | position | seed | codelets | final T | answer quality | snags |
|---:|---:|---:|---:|---:|---:|---:|
| 3 | 6 | 900030 | 3,966 | 46.0 | 73.0 | 2 |
| 55 | 5 | 900445 | 3,330 | 43.0 | 76.0 | 1 |
| 71 | 7 | 900575 | 3,694 | 43.0 | 74.0 | 2 |
| 80 | 4 | 900644 | 1,818 | 43.0 | 74.0 | 1 |
| 81 | 7 | 900655 | 3,108 | 43.0 | 74.0 | 1 |

Answer quality 73–76; every one of these episodes recorded at least one snag.

**NOVEL `cddbc`**, 1 episode — ep 58, position 7, seed 900471, 5,068 codelets,
T 39.0, quality 76.0, 2 snags.

### `misc1` — `abc → cba ; mrrjjj → ?`

Reference set: 11 members over 500 episodes, `f1/n` = 0.0060.

**NOVEL `crraaa`**, 2 episodes.

| episode | position | seed | codelets | final T | answer quality | snags |
|---:|---:|---:|---:|---:|---:|---:|
| 22 | 7 | 900183 | 5,371 | 24.0 | 68.0 | 0 |
| 92 | 6 | 900742 | 3,574 | 22.0 | 68.0 | 0 |

**NOVEL `jjjrmr`**, 1 episode — ep 61, position 6, seed 900494, 2,209 codelets,
T 20.0, quality 91.0, 0 snags. This carries the highest answer quality of any
variation recorded here.
**NOVEL `mrraaa`**, 1 episode — ep 45, position 6, seed 900366, 13,399 codelets,
T 21.0, quality 57.0, 0 snags.

`crraaa` and `mrraaa` both appear in DISCREPANCIES3's pre-repair single-run table
for this problem, at 0.2% each.

### `fig5.4-top` — `eeqee → qeeq ; xxixx → ?`

Reference set: 15 members over 500 episodes, `f1/n` = 0.0140.

| member | episode | position | seed | codelets | final T | quality | snags |
|---|---:|---:|---:|---:|---:|---:|---:|
| `iixxi` | 19 | 7 | 900159 | 4,368 | 41.0 | 58.0 | 0 |
| `qexq` | 47 | 7 | 900383 | 2,821 | 39.0 | 60.0 | 0 |
| `qiiq` | 23 | 7 | 900191 | 1,225 | 37.0 | 49.0 | 0 |

All three are single-episode occurrences at position 7.

### `misc3` — `abc → aabbcc ; kkjjii → ?`

Reference set: 30 members over 500 episodes, `f1/n` = 0.0080. This problem's
single-run reference is the one DISCREPANCIES3 flags as stopped by hand
(`shards_exited`, 19,000 runs).

| member | episode | position | seed | codelets | final T | quality | snags |
|---|---:|---:|---:|---:|---:|---:|---:|
| `kkjiii` | 74 | 7 | 900599 | 3,333 | 18.0 | 71.0 | 0 |
| `kkjjiiiii` | 83 | 6 | 900670 | 1,399 | 22.0 | 82.0 | 0 |
| `kkjjjjii` | 15 | 7 | 900127 | 1,846 | 25.0 | 68.0 | 0 |

### `misc2` — `abc → abd ; ijk → ?`

Reference set: 12 members over 500 episodes, `f1/n` = 0.0080.

**NOVEL `ajd`**, 1 episode — ep 75, position 4, seed 900604, 3,487 codelets,
T 29.0, quality 65.0, 0 snags.

### `copy5` — `aabb → cc ; aabb → ?`

Reference set: 8 members over 500 episodes, `f1/n` = 0.0040.

**NOVEL `cac`**, 1 episode — ep 32, position 3, seed 900259, 3,232 codelets,
T 24.0, quality 48.0, 0 snags.

---

## Cross-cutting run detail

Recorded because it may bear on a later analysis. No claim is made about what any
of it means.

**Rule population.** For each of the 33 runs above, the Workspace's rule set was
captured at answer time. In **20 of 33**, it contained an extrinsic clause naming
the whole string — `extrinsic (string StringPos whole) swap<...>`. The split by
problem:

| problem | runs with a whole-string extrinsic clause |
|---|---|
| `eqe-baaab` | 11 of 11 |
| `run6` | 6 of 6 |
| `fig5.4-top` | 2 of 3 |
| `misc1` | 0 of 4 |
| `misc3` | 0 of 3 |
| `misc2`, `copy1`, `copy5`, `run1` | 0 of 6 |

**Position within the episode.** Of the 28 episodic variations, 19 occur at
position 7 (the last run), 5 at position 6, and 4 earlier (positions 3, 4, 5, 5).

**Answer quality.** Ranges 47.0 to 91.0. The two repeated members are tightly
clustered: `abbbb` at 74–75 across all 7 occurrences, `cdddb` at 73–76 across all
5.

**Codelet counts.** Range 1,023 to 20,000. Only one run reached the cap
(`run1` seed 900038).

**Snags.** Recorded in 8 of 33 runs. All 6 `run6` variations had at least one;
all 11 `eqe-baaab` variations had at most one.

## Reproducing any entry

Every run above is reproducible from its seed alone.

```sh
# a single-run entry
.venv/bin/python -c "
import os; os.environ['PETACAT_NUMERIC_BACKEND']='numpy'
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
m = MetadataProvider.from_seed_data('seed_data')
r = EngineRunner(m); r.init_mcat('eqe','qeq','abbba', seed=900056)
r.run_mcat(max_steps=20000)
print(r.status, r.ctx.workspace.answer_string.text)"
```

An episodic entry needs the runs before it in its episode: create one
`EpisodicMemory`, then run seeds `episode_start_seed + 0 … + position`, passing
the same memory to each `init_mcat`. `episode_start_seed` is `900000 + 8e`.

To re-derive the whole table:

```sh
.venv/bin/python scripts/compare_to_metacat.py -n 100 -r 8
```

## What is not covered

- **e2e and integration layers** were not run; they need a Postgres instance.
- **The GPU half of the numeric matrix** was not run; MLX is not installed, and
  DISCREPANCIES3 records it aborting the interpreter in
  `test_a_free_running_run_is_persisted_like_any_other`.
- **The 20,000-codelet cap** applies to every Petacat run here, against the
  reference's 100,000. One entry (`run1` `*CAP*`) is directly affected; whether
  any other entry would differ at the higher cap is not measured.
- **Rules are recorded, answers are compared.** The reference sets contain answer
  strings only, so an answer reached by a different rule is indistinguishable
  from the same answer reached the same way.
