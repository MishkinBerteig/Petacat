# DISCREPANCIES4 — every variation between Petacat and the Metacat oracle

**What this is.** One entry per variation found by comparing Petacat against
Metacat's published reference sets. Each records the problem, the discrepancy
type, and the run detail needed to reproduce and eventually diagnose it.

**What this is not.** There are no explanations in the measurement sections.
Nothing between here and [Root causes](#root-causes) says *why* a variation
occurred, and no entry there names a cause, a suspect mechanism or a fix. Run
detail is recorded because a root-cause analysis will need it, not because it
implies one.

**Amendment, 2026-08-06.** That analysis has since been done, and it is in
[Root causes](#root-causes) at the end. Every measurement section above it is
unchanged; each entry gains one line naming its cause and nothing else. In
summary: **one defect accounts for 7 of the 22 variations and 17 of the 33
runs** — a group's image is built left-to-right whatever the group's own
direction — and it is confirmed by intervention on both sides. One entry is the
codelet cap and is closed. Eleven are the convergence sets' own unsaturation.
Three remain open, with the diagnostic that would settle them named.

**Amendment, 2026-08-06 (later). Every plan below has been carried out**, and the
tables above therefore record the engine and the harness before them.
**The measurement this document reports is now
`measurements/vs-metacat-pre-rc-a.json`**; `measurements/vs-metacat.json` holds
the current cycle.

| | what changed | where |
|---|---|---|
| **RC-A** | one function — a group's image is built in the group's own direction | `server/engine/images.py`, [detail](#implemented-2026-08-06) |
| **RC-B** | a capped *single* run is re-run at the reference's cap; episodes deliberately are not | `scripts/compare_to_metacat.py`, [detail](#implemented-2026-08-06--and-the-reason-narrowed) |
| **RC-C** | nothing — the diagnostic **eliminated the cause this document named** | [detail](#the-diagnostic-was-run-and-it-refutes-its-own-hypothesis) |
| **RC-D** | nothing, as planned; re-checked after RC-A | [detail](#rc-d--misc2s-ajd-is-a-correctly-applied-rule) |
| **RC-E** | the episodic NOVEL flag is split, and recurrence across cycles is marked | `scripts/compare_to_metacat.py`, [detail](#implemented-2026-08-06--both-changes) |

A full cycle on the repaired engine and the repaired harness, same seeds:

| | before | after |
|---|---|---|
| single-run novel members | 5 — `abbbb`, `cdddb`, `*NONE*`, `*CAP*`, `aac` | **1** — `aac` |
| episodic novel members | 17 over 28 episodes | **2** — `ajd`, `qrrbq` — plus 11 filed as answers the reference reaches in single runs |
| missing p50 | 0 | **0** |

**One open finding remains**, and it is not the one this document expected:
`copy5`'s `aac`, whose named cause was measured and refuted. What is left of it,
and the census that would settle it, is under
[RC-C](#the-diagnostic-was-run-and-it-refutes-its-own-hypothesis).

## Measurement conditions

| | |
|---|---|
| Petacat | commit `cc25a4a`, `numpy` backend (float64), **20,000-codelet cap** |
| reference | `../Metacat/oracle/derived/`, from Metacat `46a479b` |
| single-run reference | 374,500 runs, 100,000-codelet cap |
| convergence reference | 9,500 episodes × 8 runs, 100,000-codelet cap |
| sample | 100 tries per problem per mode, 19 problems |
| seeds | single: `900000 + i`, i ∈ 0…99 · episodic: episode *e* run *i* uses `900000 + 8e + i` |
| harness | `scripts/compare_to_metacat.py`; full output in `measurements/vs-metacat-pre-rc-a.json` |

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

**Root cause: [RC-A](#rc-a--a-groups-image-is-built-left-to-right-discarding-the-groups-direction) — fixed.**
With the image built the reference's way this seed answers `baaab`.

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

**Root cause: [RC-A](#rc-a--a-groups-image-is-built-left-to-right-discarding-the-groups-direction) — fixed.**
With the image built the reference's way this seed answers `bcccb`, which is in
the reference set.

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

**Root cause: [RC-C](#rc-c--a-rule-clause-that-denotes-no-object-in-the-target-applies-as-a-silent-no-op) — open.**
The first clause denotes nothing in the target and applies as a silent no-op, as
it would in the reference; what does not match is the rate at which the answer
comes out.

### `copy1` — `ab → c ; ab → ?`

**NOVEL `*NONE*`** (the run stopped without an answer), 1 of 100 runs. Reference
set: 2 members over 10,875 runs — `c` 86.6%, `ab` 13.4% — `f1/n` = 0.00000. The
reference recorded no `*NONE*` and no `*CAP*` on this problem.

| seed | codelets | final T | snags |
|---:|---:|---:|---:|
| 900068 | 2,287 | 38.0 | 0 |

The run terminated at 2,287 codelets, well below the 20,000 cap.

**Root cause: [RC-A](#rc-a--a-groups-image-is-built-left-to-right-discarding-the-groups-direction) — fixed.**
With the image built the reference's way this seed answers `c` at 391 codelets.
The reference produces `*NONE*` here too once it is given Petacat's version of
the same procedure — six times in 300 runs.

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

**Root cause: [RC-B](#rc-b--run1s-cap-is-the-cap-and-it-is-now-closed) — closed.**
It has since been measured. At 100,000 codelets this seed answers `abd` at
36,815, and `abd` is in the reference set at 1.3%.

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

**Root causes.** `abbbb` (all 7) and `baaba`:
[RC-A](#rc-a--a-groups-image-is-built-left-to-right-discarding-the-groups-direction),
fixed — with the image built the reference's way the seven `abbbb` episodes converge
instead on `qeq`, `qbbba`, `qbbbq`, `abbba` and `pqqqq`, every one of which is in
the reference's convergence set. `aqqqp`:
[RC-E](#rc-e--eleven-entries-are-the-convergence-sets-own-unsaturation) — it is
in the reference's saturated single-run set. `qrrbq`:
[RC-C](#rc-c--a-rule-clause-that-denotes-no-object-in-the-target-applies-as-a-silent-no-op),
open — the `(letter StringPos middle)` clause denotes nothing, because that
run read the middle of `abbba` as a group.

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

**Root cause: [RC-A](#rc-a--a-groups-image-is-built-left-to-right-discarding-the-groups-direction), fixed**,
both members. All six episodes lose them with the image built the reference's
way, and the reference produces `cdddb` and `cddbc` itself once it is given
Petacat's version of the same procedure — four times in 300 single runs.

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

**Root cause: [RC-E](#rc-e--eleven-entries-are-the-convergence-sets-own-unsaturation),
all three** — every one is in the reference's saturated single-run set. Four
novel episodes against 0.6 expected is the least comfortable row in that
section, and it says watch rather than investigate.

### `fig5.4-top` — `eeqee → qeeq ; xxixx → ?`

Reference set: 15 members over 500 episodes, `f1/n` = 0.0140.

| member | episode | position | seed | codelets | final T | quality | snags |
|---|---:|---:|---:|---:|---:|---:|---:|
| `iixxi` | 19 | 7 | 900159 | 4,368 | 41.0 | 58.0 | 0 |
| `qexq` | 47 | 7 | 900383 | 2,821 | 39.0 | 60.0 | 0 |
| `qiiq` | 23 | 7 | 900191 | 1,225 | 37.0 | 49.0 | 0 |

All three are single-episode occurrences at position 7.

**Root cause: [RC-E](#rc-e--eleven-entries-are-the-convergence-sets-own-unsaturation),
all three** — every one is in the reference's saturated single-run set, and this
problem's convergence `f1/n` of 0.0140 expects 1.4 novel episodes per hundred.

### `misc3` — `abc → aabbcc ; kkjjii → ?`

Reference set: 30 members over 500 episodes, `f1/n` = 0.0080. This problem's
single-run reference is the one DISCREPANCIES3 flags as stopped by hand
(`shards_exited`, 19,000 runs).

| member | episode | position | seed | codelets | final T | quality | snags |
|---|---:|---:|---:|---:|---:|---:|---:|
| `kkjiii` | 74 | 7 | 900599 | 3,333 | 18.0 | 71.0 | 0 |
| `kkjjiiiii` | 83 | 6 | 900670 | 1,399 | 22.0 | 82.0 | 0 |
| `kkjjjjii` | 15 | 7 | 900127 | 1,846 | 25.0 | 68.0 | 0 |

**Root cause: [RC-E](#rc-e--eleven-entries-are-the-convergence-sets-own-unsaturation),
all three** — every one is in the single-run set, which for this problem is the
one stopped by hand and so is the weakest of the nineteen in both directions.

### `misc2` — `abc → abd ; ijk → ?`

Reference set: 12 members over 500 episodes, `f1/n` = 0.0080.

**NOVEL `ajd`**, 1 episode — ep 75, position 4, seed 900604, 3,487 codelets,
T 29.0, quality 65.0, 0 snags.

**Root cause: [RC-D](#rc-d--misc2s-ajd-is-a-correctly-applied-rule).** The rule
is applied exactly as written; `ajd` appears in 0 of 3,000 Petacat single runs
and 0 of 11,000 reference ones, and one novel episode is what this problem's
`f1/n` of 0.0080 expects.

### `copy5` — `aabb → cc ; aabb → ?`

Reference set: 8 members over 500 episodes, `f1/n` = 0.0040.

**NOVEL `cac`**, 1 episode — ep 32, position 3, seed 900259, 3,232 codelets,
T 24.0, quality 48.0, 0 snags.

**Root cause: [RC-E](#rc-e--eleven-entries-are-the-convergence-sets-own-unsaturation)**
— `cac` is in the reference's single-run set, at 0.039%.

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

**What the analysis made of this.** The whole-string extrinsic clause is the
route by which a literal letter-category change reaches a *group's* image, and a
group's image is where [RC-A](#rc-a--a-groups-image-is-built-left-to-right-discarding-the-groups-direction)
lives — which is why the two problems whose variations RC-A explains are the two
whose rule populations carry that clause in every run. The position figure is
the other half: 19 of 28 at position 7 is Episodic Memory refusing an answer it
already holds (`answers.ss:982`) and pushing the run toward rules it would not
otherwise reach, which is what turns a 1-in-100 single-run defect into a
7-in-100 episodic one.

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

### Reproducing the reference side

The analysis below runs Metacat itself. The toolchain is a Docker image the
Metacat repository builds (`../Metacat/docker/Dockerfile`); `chez-oracle:9.5.4`
is that image. A script like the oracle sampler's, driving `metacat-headless.ss`
one seed at a time, is enough:

```sh
docker run --rm --platform linux/amd64 \
  -v "$PWD/../Metacat":/metacat -v /tmp/mc_many.ss:/tmp/mc_many.ss \
  -w /metacat chez-oracle:9.5.4 scheme --script /tmp/mc_many.ss
```

Reference seeds do not correspond to Petacat seeds — the RNG streams are
unrelated — so a reference run reproduces a *distribution*, never a run. The two
patched trees the analysis uses are copies of `../Metacat`, mounted in place of
it; the repository itself is left alone.

## What is not covered

- **e2e and integration layers** were not run; they need a Postgres instance.
- **The GPU half of the numeric matrix** was not run; MLX is not installed, and
  DISCREPANCIES3 records it aborting the interpreter in
  `test_a_free_running_run_is_persisted_like_any_other`. *(Stale as of the
  2026-08-06 amendment: MLX 0.32.0 is installed, the matrix runs both backends,
  and the suite figure under [RC-A](#implemented-2026-08-06) covers them. The
  measurement this document reports was still `numpy`-only.)*
- **The 20,000-codelet cap** applies to every Petacat run here, against the
  reference's 100,000. One entry (`run1` `*CAP*`) is directly affected; whether
  any other entry would differ at the higher cap is not measured.
- **Rules are recorded, answers are compared.** The reference sets contain answer
  strings only, so an answer reached by a different rule is indistinguishable
  from the same answer reached the same way.

---

## Root causes

**Added 2026-08-06.** Everything above this line is measurement and is unchanged
apart from the one-line cause each entry now carries. This section is analysis.
It names a cause for each of the 22 variations and a plan for each cause. Where
a claim is measured the measurement is given; where it is read out of a source,
it says so.

### Method

Three instruments, beyond the harness the tables came from.

| | |
|---|---|
| Petacat, instrumented | `apply_rule`, `_get_extrinsic_transforms`, `_get_intrinsic_transforms` and `_transform_image` wrapped to record the rule, its reference and denoted objects, every transform, and the image before and after |
| the reference, run | Chez Scheme 9.5.4 in Docker (`chez-oracle:9.5.4`, the image `Metacat/docker/` builds), `metacat-headless.ss`, 100,000-codelet cap, one process per problem, seeds 1…300 unless stated |
| the reference, patched | two working copies of the Metacat tree: one carrying probes that print without changing behaviour, one carrying a one-hunk emulation of Petacat's defect |

The reference is now runnable here, which it was not when DISCREPANCIES3 was
written; that document had to read the Scheme where this one can execute it.
Reference seeds and Petacat seeds index different RNG streams, so no run
corresponds to a run. What can be compared is a *distribution* against the same
oracle sets, and whether a named operation succeeds or fails.

### Disposition

| # | problem | mode | member | cause |
|---:|---|---|---|---|
| 1 | `eqe-baaab` | single | `abbbb` | **RC-A** |
| 2 | `run6` | single | `cdddb` | **RC-A** |
| 3 | `copy1` | single | `*NONE*` | **RC-A** |
| 4 | `eqe-baaab` | episodic | `abbbb` (7 episodes) | **RC-A** |
| 5 | `eqe-baaab` | episodic | `baaba` | **RC-A** |
| 6 | `run6` | episodic | `cdddb` (5 episodes) | **RC-A** |
| 7 | `run6` | episodic | `cddbc` | **RC-A** |
| 8 | `run1` | single | `*CAP*` | **RC-B** — the cap. Closed |
| 9 | `copy5` | single | `aac` | **RC-C** — open |
| 10 | `eqe-baaab` | episodic | `qrrbq` | **RC-C** — open |
| 11 | `misc2` | episodic | `ajd` | **RC-D** — expected rate |
| 12–22 | `misc1`, `misc3`, `fig5.4-top`, `copy5`, `eqe-baaab` | episodic | `crraaa`, `mrraaa`, `jjjrmr`, `kkjiii`, `kkjjiiiii`, `kkjjjjii`, `iixxi`, `qexq`, `qiiq`, `cac`, `aqqqp` | **RC-E** — convergence-set unsaturation |

RC-A is 7 variations over 17 runs; RC-E is 11 variations over 12 episodes.

### RC-A — a group's image is built left to right, discarding the group's direction

A group whose bonds run **leftward** — `[[a][bbb]]` in `abbba`, read right to
left as `b`, `a`, a predecessor group — is given an image that says it runs
rightward.

In the reference a group's image is built at the moment the group itself is, out
of its objects **in direction order** (`groups.ss:58-98`):

```scheme
(ordered-objects (if (eq? direction plato-left) (reverse objects) objects))
(initial-letter-category
  (tell (1st ordered-objects) 'get-descriptor-for plato-letter-category))
...
(image (make-image
         initial-letter-category
         group-bond-facet
         (relationship-between (tell-all ordered-objects 'get-initial-letter-category))
         (relationship-between (tell-all ordered-objects 'get-platonic-length))
         (if (exists? direction) direction plato-right)      ; groups.ss:97
         (tell-all ordered-objects 'get-image)))             ; groups.ss:98
```

Petacat builds the image tree lazily instead, from the string, in
`StringImage._make_image_for` (`server/engine/images.py:1037-1080`) — and there
the group's direction is dropped:

```python
sub_images = [...]                       # obj.objects, physical left to right
first = sub_images[0]
letter_relation, length_relation = _group_image_relations(obj, list(sub_objects), ...)
return make_group_image(
    self.slipnet, first.start_letter, getattr(obj, "bond_facet", None),
    letter_relation, length_relation,
    # Physical left-to-right order, *not* the group's bonding direction:
    self.slipnet.nodes.get("plato-right"),                   # images.py:1078
    sub_images,
)
```

For a left-going group the two differ in four ways at once:

| | reference | Petacat |
|---|---|---|
| sub-image order | direction order — rightmost first | string order — leftmost first |
| direction | `plato-left` | `plato-right` |
| start letter | the **rightmost** constituent's LetterCtgy | the leftmost constituent's |
| letter / length relation | over the direction order | over the string order — its **inverse** |

**Why it stays invisible until a rule touches it.** `generate` reverses the
sub-images again when the direction is left (`images.ss:227-231`, mirrored at
`images.py:645-653`), so the two reversals cancel and an *untouched* image of a
left-going group prints its letters left to right either way. The comment at
`images.py:1072-1077` records the moment this was met from the other end: the
direction was flipped without reversing the sub-image list, an untouched `abc`
came out `acb`, and the repair taken was to drop the direction rather than to
reverse the list along with it.

Every direction-sensitive operation then diverges. `new_start_letter` with a
literal letter enumerates from the wrong end with the inverse relation
(`images.ss:282-286`, `images.py:432-443`); `extend` and `shorten` grow and cut
the wrong end; `reverse_direction` and `reverse_medium` turn the image the wrong
way; `leaf_walk` and `postorder_interior_walk` visit in the wrong order; and
`instantiate_as_group` gives the group it builds in the **answer** string the
direction `right` (`images.py:670-739`), so the answer's own perceived structure
is wrong as well.

#### Evidence

**1. Petacat, traced.** `eqe → qeq ; abbba`, seed 900056 — the first entry in
this document. The target is read as `[[a][bbb]]`, a left-going predecessor group
spanning positions 0-3, beside `[a]`, a same-group at position 4. The rule is the
whole-string subobjects swap the entry records, and it swaps LetterCtgy between
those two constituents: the predgrp `b ⇒ a`, the singleton `a ⇒ b`. Applying
`LetterCtgy → a` to the predgrp's image — which Petacat built as `start=a`,
`rel=succ`, `dir=right`, `subs=[[a],[bbb]]` — enumerates `[a, b]`, hands `a` back
to `[a]` and `b` back to `[bbb]`, and changes **nothing**. The singleton becomes
`b`. `abbba → abbbb`.

**2. The reference, probed.** With `images.ss:282` instrumented to print its
arguments and to report an `enumerate-letter` failure, 60 reference runs of
`eqe → qeq ; abbba` reach that call 118 times. 117 are `dir=right`. One is not:

```
PROBE NSL arg=a rel=predecessor dir=left n=2
PROBE ENUMFAIL arg=a rel=predecessor
```

The reference builds the same image the other way round — `start=b`,
`rel=predecessor`, `dir=left` — is asked for start letter `a`, has no predecessor
of `a` to enumerate, and **fails**, which aborts the rule application into the
snag machinery. That seed went on to answer `baaab`. Petacat, at the same
juncture, succeeds silently as a no-op.

**3. The reference, carrying Petacat's version.** One hunk in `groups.ss:84-98`
— `objects` for `ordered-objects`, `plato-right` for the direction — and nothing
else. 300 seeds per problem, stock tree beside patched tree, same seeds:

| problem | seeds whose answer changed | novel, stock | novel, carrying Petacat's version |
|---|---:|---|---|
| `eqe-baaab` | 3 of 300 | none | `abbab` |
| `run6` | 11 of 300 | none | **`cdddb`×3, `cddbc`×1**, `caaab`×5, `qccbc`×1 |
| `copy1` | 6 of 300 | none | **`*NONE*`×6** |
| `copy5` | 0 of 170 | none | none |
| `misc2` | 0 of 300 | none | none |

"Novel" is against the same `single-run-sets.json` this document compares
against. The emulation makes the reference produce, from its own side, the two
members recorded here for `run6` and the state recorded for `copy1` — including
`*NONE*` on a problem whose reference set is `c` and `ab` over 10,875 runs and
nothing else. It changes nothing on the two problems RC-A does not explain.

**4. Petacat, with the reference's version.** `_make_image_for` rewritten to
transcribe `groups.ss:70-98`, and the whole comparison re-run on the same seeds,
same cap, same backend:

| | novel members | runs / episodes |
|---|---:|---:|
| single, as measured | 5 | 5 |
| single, with the fix | **2** | **2** |
| episodic, as measured | 17 | 28 |
| episodic, with the fix | **13** | **14** |

Every RC-A member disappears — `abbbb`, `cdddb`, `cddbc`, `baaba`, and `copy1`'s
`*NONE*` — and **every other novel entry is bit-identical between the two runs**,
which is the check that the intervention is not merely reshuffling the noise. The
seven `eqe-baaab` episodes that converged on `abbbb` converge instead on `qeq`
(twice), `qbbba` (twice), `qbbbq`, `abbba` and `pqqqq` — every one of which is in
the reference's convergence set. No p50 member goes missing, in either mode.

#### How much of the engine this touches

Left-going groups are not rare. Group images built for a left-going group, as a
share of all group images, 12 runs per problem:

| problem | | problem | | problem | |
|---|---:|---|---:|---|---:|
| `copy6` | 92.9% | `copy4` | 55.4% | `copy5` | 11.8% |
| `copy1` | 76.1% | `run3` | 47.5% | `run4` | 5.2% |
| `misc2` | 66.1% | `misc1` | 37.6% | `run1` | 4.5% |
| `copy2` | 57.9% | `misc5` | 35.7% | `misc3` | 1.4% |
| `copy3` | 56.8% | `fig5.7` | 17.7% | `fig5.4-top` | 0.1% |
| | | `run6` | 15.1% | `eqe-baaab`, `run2`, `misc4` | 0.0% |

`eqe-baaab` reaches 0% over those twelve seeds and still produces `abbbb` once in
a hundred, which is the shape of the whole finding: the wrong image is built
constantly, and it only changes an answer when a rule asks the image to do
something its direction governs.

#### Plan

**One function — `StringImage._make_image_for` (`server/engine/images.py:1037`).**
Transcribe `groups.ss:70-98`:

1. `ordered = list(reversed(obj.objects))` when `obj.direction` is `plato-left`,
   else `obj.objects`;
2. build the sub-images from `ordered`, still caching each back onto its object
   so the image tree stays shared;
3. take `start_letter` from the group itself —
   `Group._get_initial_letter_category` (`server/engine/groups.py:495`) already
   orders by direction, so this is the reference's `initial-letter-category`
   rather than a second derivation of it;
4. take the relations from `_group_image_relations(obj, ordered, slipnet)`, not
   from the string-order list;
5. pass `obj.direction` when it exists, `plato-right` otherwise.

Rewrite the comment at `images.py:1072-1077` rather than deleting it. What it
records is true and worth keeping — flipping the direction alone *does* produce
`acb` — and the reason that is no longer a hazard is that the sub-image list is
now reversed with it, so `generate`'s own reversal cancels.

**Guard it in three directions**, all in the numeric matrix so each runs on both
backends:

- an untouched image of a left-going group generates its letters left to right,
  and so does a right-going one — the `acb` regression the comment records,
  tested from both sides;
- `new_start_letter(plato_a)` on a left-going image whose letter relation is
  predecessor raises `ImageFailure` — the reference's `ENUMFAIL` above — while
  the mirrored right-going case still succeeds;
- a group instantiated from a left-going image carries direction left.

**Then re-measure everything.** This is not a local change: it moves the image of
a majority of the groups on six of the nineteen problems. What has to be redone
is `scripts/compare_to_metacat.py -n 100 -r 8` in both modes and the numeric
matrix on both backends. The expected comparison result is the fourth table
above, and the check that matters most is that no p50 member goes missing.

#### Implemented, 2026-08-06

All of the above landed as written. One function, `StringImage._make_image_for`
(`server/engine/images.py:1037`), and one new test file. The comment at
`images.py:1072-1077` was rewritten rather than deleted, for the reason the plan
gives.

**The comparison was re-run on the same seeds, cap and backend**, and it
reproduces the intervention *exactly* — not merely in the flag counts but in
every per-problem `produced` distribution, on all 19 problems in both modes:

| | novel members | runs / episodes |
|---|---:|---:|
| single, before | 5 | 5 |
| single, after | **2** | **2** |
| episodic, before | 17 | 28 |
| episodic, after | **13** | **14** |

Gone: `abbbb` (1 single + 7 episodes), `cdddb` (1 + 5), `cddbc`, `baaba`, and
`copy1`'s `*NONE*` — 7 variations over 17 runs. Remaining: `run1`'s `*CAP*` and
`copy5`'s `aac` in single runs; `qrrbq`, `ajd`, `cac`, `aqqqp` and the nine RC-E
members in episodes. **No p50 member is missing on any problem in either mode**,
and every remaining entry is bit-identical to the pre-fix run. Full output in
`measurements/vs-metacat.json`; the pre-fix run this document's tables report is
kept beside it as `measurements/vs-metacat-pre-rc-a.json`.

**Suite:** 1,888 passed, 6 skipped, 0 failed across unit, seed_unit, module and
architecture, with the numeric matrix exercising 438 tests on each of `numpy` and
`mlx`. The two failures the intervention run showed were both artefacts of how it
was run and do not recur: `test_every_worker_does_some_work` is load-sensitive
and this run had the machine to itself, and
`test_engine_runs_identically_with_mlx_and_numpy_absent` fails whenever
`PETACAT_NUMERIC_BACKEND` is exported into it, so it is run without that and
passes.

**Guarded by** `tests/module/test_group_image_direction.py`, six tests in the
numeric matrix, of which **five fail on the pre-repair implementation**:

| | |
|---|---|
| enumeration runs from the group's first object in direction order | `c` gives `bc`, not `cd` |
| enumerating off the end of the alphabet raises `ImageFailure` | where it used to change nothing and answer |
| a left-going group grows at the end it reads towards | `bc` extends to `abc`, not `bcd` |
| the length relation is read in direction order too | lengths two-then-one relate as predecessor |
| a group instantiated from a left-going image goes left | and its members are still stored left to right |
| an untouched image generates left to right | passes either way **by design** |

The last one is the point of the set rather than an omission from it: it guards
the half the old code had right, and the `acb` regression is exactly what breaks
if a later change puts back one of the two reversals without the other. The two
middle rows were added after the first four, because `extend` and the *length*
relation are the same one-line ordering on paths the first four never touch.

**One thing the plan did not anticipate.** It called for the start letter to come
from `Group._get_initial_letter_category`, which is `groups.ss:76-77` exactly —
the LettCtgy *descriptor* of the first object in direction order, and therefore
`None` where that object is a group with no LettCtgy description, which the
previous code's recursive `first.start_letter` could never be. Measured before
shipping: **0 of 12,845 group images across 190 runs** of all nineteen problems.
The faithful form is used, and no fallback was added for a case that does not
arise.

### RC-B — `run1`'s `*CAP*` is the cap, and it is now closed

The entry says the cap is the confound. Removing it settles it. Seed 900038,
`abc → abd ; mrrjjj`, run again at the reference's own 100,000-codelet ceiling:

```
answer_found   abd   36,815 codelets
```

`abd` is in `run1`'s reference set, at 1.3%. The run was not going anywhere the
reference set does not already contain; it was 16,815 codelets short of getting
there. Nothing about the engine is implicated.

**Plan.** Two things, and the first is not optional if the flag is to stop
recurring:

1. **Record it resolved** in the `run1` entry, with the codelet count, so the
   next reader does not re-derive it. (Done above.)
2. **Decide what the harness's cap should be.** `MAX_STEPS = 20_000`
   (`scripts/compare_to_metacat.py:57`) is one fifth of the reference's, and the
   comment there already says a lower cap "can only turn a would-be answer into
   `*CAP*`". Raising it to 100,000 removes the confound permanently and makes
   every `*CAP*` comparable; the cost is wall clock on exactly the runs that are
   already slowest. A cheaper option — leave the cap at 20,000 and re-run only
   the runs that hit it at 100,000 before reporting them — is a change to the
   reporting rather than to the measurement, and would have closed this entry
   automatically. Either is defensible. Reporting a state the harness knows is
   not comparable is the option that is not.

#### Implemented, 2026-08-06 — and the reason narrowed

Measuring the cap before changing anything moved the argument. **The cap is not
distorting the episodic comparison, and the plan above was wrong to imply it
might.** Capping is what an exhausted session *does* in both programs, because
`answers.ss:982` refuses an answer already stored, and the reference does it at
the same rate on the same problems:

| | episodic runs capped | episodes with any capped run |
|---|---:|---:|
| the reference, at 100,000 | 9,928 of 76,000 (13.1%) | 4,111 of 9,500 (43%) |
| Petacat, at 20,000 | 2,406 of 15,200 (15.8%) | 1,054 of 1,900 (55%) |

and 16.8% of the reference's own episodic runs pass 20,000 codelets — against
Petacat's 15.8% capped there. Episodes with their *last* run capped run 32% in
the reference and 31% here. The two modes agree in shape.

**Single runs are where the cap actually shows**, and there the reference is
almost silent: `*CAP*` at 100,000 is 0.578% over 374,500 runs, and **zero on
sixteen of the nineteen problems**. The exceptions are `misc3` (10.96%, with
24.9% of its runs passing 20,000), `copy5` (0.52%) and `misc5` (0.009%). On
`run1` the reference caps **0 times in 11,000**, while 34 of those runs (0.31%)
pass 20,000 — which is exactly this entry, quantified from the reference's side.

So the change is the narrower of the two options, and it is narrower still than
the plan's version of it: **a single run that hits the cap is re-run at
`REFERENCE_MAX_STEPS = 100_000` and compared on what it reaches there.** Episodes
are left alone, and the reason is now stated in the code — memory carries
forward, so there is no such thing as re-running one run of an episode, and
re-running the whole episode is a different measurement rather than a resolution
of this one.

Measured on the four problems that cap:

| problem | capped at 20,000 | after resolution | novel flag |
|---|---:|---|---|
| `run1` | 1 | `abd` at 36,815 codelets | `*CAP*` → **gone** |
| `misc3` | 22 | 19 answers, 3 still `*CAP*` at 100,000 | unchanged (none) |
| `copy5`, `copy1` | 0 | — | unchanged |

`misc3` lands at 3% against the reference's 10.96%, and gains four distinct
states it was previously truncating away. Cost: 23 extra runs in a cycle of
1,900, and the resolutions are printed and stored in
`resolved_at_reference_cap` rather than folded away, because the state being
compared came from a longer run than every other state in its row.

### RC-C — a rule clause that denotes no object in the target applies as a silent no-op

Two entries are the same shape: a rule of several clauses, one of which names an
object the *target* does not have. That clause contributes no transforms, the
others apply, and the run reports the result as an answer.

**`copy5` `aac`, seed 900059.** The second clause, `(group StringPos rmost)`,
denotes the `bb` group and turns it into the letter `c`. The first,
`(group AlphaPos first)`, denotes **nothing**: the target's `aa` group carries
`ObjectCtgy`, `GroupCtgy`, `StringPos` and `LetterCtgy` descriptions and no
`AlphaPos` one, while the initial string's `aa` group — which is what the rule
was abstracted from — does have it. `aabb` keeps its `aa` and loses its `bb`.

**`eqe-baaab` `qrrbq`, episode 71, position 7.** A three-clause rule —
`(group StringPos lmost) → q`, `(letter StringPos middle) → e`,
`(letter StringPos rmost) → q`. The middle clause names a *letter*, and that run
read the middle of `abbba` as a group, so it denotes nothing. The other two apply
exactly: the lmost group `abb` takes start letter `q` with its successor relation
and generates `qrr`, the rmost letter becomes `q`, and the `b` between them is
untouched.

**The no-op itself is faithful.** `get-intrinsic-transforms` (`rules.ss:1524-1543`)
crosses the reference objects with the transforms, and `(cross-product '() ...)`
is `'()`. There is no error branch, and Marshall's comment at
`workspace-strings.ss:499-506` describes exactly this situation arising and being
lived with. Measured on both sides, counting every intrinsic-clause resolution
against the **target** string by how many objects it denoted:

| problem | | runs | resolutions | denoted 0 |
|---|---|---:|---:|---:|
| `misc2` | Petacat | 300 | 600 | 6 (1.0%) |
| `misc2` | reference | 208 | 414 | 6 (1.4%) |
| `copy5` | Petacat | 300 | 308 | 2 (0.65%) |
| `copy5` | reference | 461 | 614 | 4 (0.65%) |

So the mechanism is not the divergence, and its rate is not either. **What comes
out of it is.** `copy5`, Petacat single runs on seeds 920000…922999, against the
reference's own 15,500:

| state | Petacat, n=3,000 | reference, n=15,500 |
|---|---:|---:|
| `*NONE*` | 62.4% | 47.9% |
| `cc` | 36.3% | 50.0% |
| **`aac`** | **0.87%** | **0.000%** |
| `cac` | 0.20% | 0.039% |
| `cbc` | 0.17% | 0.019% |
| `bc` | 0.03% | 0.000% |
| `cbb` | 0.03% | 0.000% |
| `ccc` | 0.03% | 0.63% |
| `*CAP*` | 0.00% | 0.52% |
| `a`, `ac`, `aabb`, `ccbb`, `cccc`, `cb`, `ab` | 0.00% | 0.39% … 0.006% |

At 0.87% the reference's 15,500 runs would have held about 134 `aac`s. They hold
none — though `aac` *is* in the reference's **convergence** set, so this is an
answer the reference reaches in a session and never in a single run. `bc` and
`cbb`, one run each, are outside the reference set too, and are absent from this
document's tables only because they fall outside its seed range.

This is where the analysis stops short of a cause. What it has established is
where to look: not at rule application, which matches on both the mechanism and
its rate, but at what the target string is carrying and which rules get built
over it. `copy5`'s wider disagreement points the same way — `*NONE*` 62.4%
against 47.9%, `*CAP*` 0% against 0.52%, `ccc` 0.03% against 0.63% — and says the
problem is being *read* differently, not only described differently.

**Plan.** In order. The first two are diagnosis, not repair:

1. **Name the missing description.** Instrument both programs to record, for
   every rule clause that denotes nothing on the target, the description type it
   named and whether any object in the target could have carried it. If Petacat's
   target strings are systematically thinner in `AlphaPos` descriptions, the cause
   is in description building — `descriptions.py` against `descriptions.ss:105-140`
   and the `descriptor-predicate?` definitions at `slipnet.ss:557-609` — and not
   in rules at all.
2. **Open `copy5` as a distribution, not as two flags.** The table above is a
   wider disagreement than the two NOVEL entries this document records, and it is
   the more likely place the cause is visible. It deserves its own entry.
3. **Do not "fix" the no-op.** Making an empty clause a failure would diverge
   from the reference in the other direction, and would take `qrrbq`'s run —
   whose other two clauses are applied precisely as the reference would apply
   them — away from an answer the reference may well reach itself.
4. **Re-run RC-C's measurements after RC-A lands.** RC-A leaves both of these runs
   bit-identical, so nothing here is contingent on it; but `copy5`'s distribution
   is not, and the 11.8% of its group images that are left-going will move.

#### The diagnostic was run, and it refutes its own hypothesis

Steps 1 and 4 are done. Step 3 is respected — nothing was changed. Step 2 is
below.

**Step 4 first, because it is quick: RC-A moved neither problem.** Re-running the
two distribution tables on the same 3,000 seeds after the fix gives results
**identical to the last state** — every state, every count, on both `copy5` and
`misc2`. The prediction that `copy5`'s distribution would move because 11.8% of
its group images are left-going was wrong; those images exist but no rule in
these runs asks them to do anything the direction governs.

**Step 1 says the description is there.** Instrumenting every intrinsic clause
resolved against the target that denoted nothing, over 300 `copy5` runs: both
occurrences name `(group AlphaPos first)`, and for both the target **could** have
carried it — the Slipnet's own `alphabetic-first` predicate (`slipnet.ss:599-601`)
admits the `aa` group, whose LettCtgy is `a` — while the initial string, which
the rule was abstracted from, does carry it.

So the question became whether Petacat's target strings are thinner in `AlphaPos`
descriptions than the reference's. **They are not.** Counting target groups
carrying an `AlphaPos` description at run end, 300 runs each:

| groups carrying AlphaPos, per run | 0 | 1 | 2 | runs with at least one |
|---|---:|---:|---:|---:|
| Petacat, target | 21 | 220 | 59 | **93.0%** |
| reference, target | 24 | 223 | 53 | **92.0%** |
| Petacat, initial | 27 | 187 | 86 | 91.0% |
| reference, initial | 39 | 202 | 59 | 87.0% |

**That eliminates the cause this plan named.** Three things now measured to
match: the no-op mechanism, the rate of empty denotation (0.65% on both sides of
`copy5`, 1.0% against 1.4% on `misc2`), and the availability of the description
the empty clause names. And `aac` still comes out at 0.87% here against 0 in
15,500 reference runs.

**What that leaves, and the next diagnostic.** The divergence is not in whether
the clause *can* resolve but in how often a rule of that shape is built, chosen
and applied — and `copy5`'s wider disagreement is the place to look for it,
because it is much larger than these two flags: `*NONE*` 62.4% against 47.9%,
`*CAP*` 0% against 0.52%, `ccc` 0.03% against 0.63%. The measurement that would
separate them is a **rule census** rather than an answer census: for each program,
over the same problem, the distribution of *built top rules* by clause shape, and
for each shape how often it reaches `currently_works` and how often the
answer-finder takes it. Both programs can be instrumented at that level — the
reference at `rules.ss:223-235` and `answers.ss:929-1000`, Petacat at
`rules.py:1389` and `answers.py:510` — and it is the same technique RC-5 used in
DISCREPANCIES3, which is what settled that one.

That census is not run here. `copy5` needs its own entry before it is, which is
step 2.

### RC-D — `misc2`'s `ajd` is a correctly applied rule

Episode 75, position 4. The rule has three clauses: an extrinsic `StrPosCtgy`
swap of the leftmost and rightmost letters, and two intrinsic clauses making the
leftmost letter `d` and the rightmost `a`. It is a baroque but exact reading of
`abc → abd` — make `a` into `d` and `c` into `a`, then exchange their positions,
and `abc` does become `abd`. Applied to `ijk` it makes `i` into `d` and `k` into
`a`, exchanges them, and yields `ajd`. Every clause denoted, every transform
applied; the answer is what the rule says.

Petacat's `misc2` distribution is otherwise close to the reference's:

| state | Petacat, n=3,000 | reference, n=11,000 |
|---|---:|---:|
| `ijl` | 94.97% | 95.30% |
| `ijd` | 2.53% | 2.09% |
| `ijk` | 1.77% | 1.98% |
| `abd` | 0.63% | 0.56% |
| `*NONE*` | 0.067% | 0.009% |
| `ikl` | 0.033% | 0.055% |
| `ajd` | **0 of 3,000** | 0 of 11,000 |

`ajd` appears in 3,000 single runs of neither program. It appeared once in 100
episodes, at a position where Episodic Memory has already refused the answers the
run would otherwise give (`answers.ss:982`) and is pushing it toward rules it
would not otherwise reach. `misc2`'s convergence set expects **0.8** novel
members per 100 episodes. This is one.

**Plan.** No change to the engine. Record it as expected-rate and check it
against the next cycle: if `ajd` recurs, or recurs at several episodes, it stops
being consistent with the rate and needs the treatment RC-A got. That check
costs nothing if the harness keeps the previous cycle's novel list — see the
last item under RC-E.

**Re-checked, 2026-08-06.** Nothing was changed, and nothing needed to be.
`misc2`'s distribution after RC-A is identical to the table above on the same
3,000 seeds, `ajd` included at 0. The standing check the plan asks for is now
automatic: the harness marks a novel member the previous cycle also produced, so
if `ajd` returns next cycle it arrives with a `+` against it rather than needing
someone to remember this paragraph.

### RC-E — eleven entries are the convergence sets' own unsaturation

The remaining eleven episodic members are all in the reference's **saturated
single-run sets**. The reference produces every one of them. What it has not done
is produce them as the convergence answer of one of its 500 sampled episodes, and
its convergence sets are deliberately not sampled to saturation for exactly that
reason (`../Metacat/ORACLE-USAGE.md`; `f1_over_n` up to 0.0160).

| problem | members | in the single-run set | `f1/n` | expected novel episodes per 100 | observed |
|---|---|---|---:|---:|---:|
| `misc1` | `crraaa`, `mrraaa`, `jjjrmr` | all three | 0.0060 | 0.6 | 4 |
| `fig5.4-top` | `iixxi`, `qexq`, `qiiq` | all three | 0.0140 | 1.4 | 3 |
| `misc3` | `kkjiii`, `kkjjiiiii`, `kkjjjjii` | all three | 0.0080 | 0.8 | 3 |
| `eqe-baaab` | `aqqqp` | yes | 0.0080 | 0.8 | 1 |
| `copy5` | `cac` | yes | 0.0040 | 0.4 | 1 |

Across all nineteen problems the reference's own figures predict **7.8** novel
convergence episodes per 100-episode cycle. This cycle produced 28. With RC-A
repaired it produces **14** — still 1.8× the expectation, but concentrated on
these five problems rather than spread across the nineteen.

The counter-argument that settles the two repeated members, and does not apply
here: a member appearing in 7 of 100 episodes cannot be missing-mass. If `abbbb`
were reachable at 7%, the reference's 500 episodes would have held about 35 of
them, and the probability of holding none is astronomically small. `cdddb` at 5%
is the same argument. Every RC-E member appeared exactly once or twice, which is
what missing mass looks like.

`misc1` is the one row that does not sit comfortably. Four novel episodes against
0.6 expected is a Poisson tail of about 0.003, and about 0.06 across nineteen
problems — unlikely rather than impossible. It is also the problem this document
notes has two of its three members in DISCREPANCIES3's pre-repair single-run
table at 0.2% each, so they are answers Petacat has reached before.

**Plan.** Nothing to fix in Petacat. Two changes to how the comparison reports:

1. **Split the episodic NOVEL flag in two.** A member that is in the reference's
   *single-run* set is a different kind of finding from one that is in neither
   set. `scripts/compare_to_metacat.py:126-139` already loads both sets, so
   `compare` can report "novel to the convergence set, but the reference reaches
   it in single runs" separately from "novel to both". That would have put
   twelve of this cycle's twenty-eight episodes in the first bucket
   automatically, and left the second bucket — `abbbb`, `baaba`, `cdddb`,
   `cddbc`, `ajd`, `qrrbq` — as the thing to read. Four of those six are RC-A;
   the other two are RC-C's `qrrbq` and RC-D's `ajd`.
2. **Keep the previous cycle's novel list** so recurrence is visible without
   anyone remembering. A member that recurs across cycles is not missing mass,
   whatever its count in one cycle; `misc1` is the row that needs this and
   RC-D's `ajd` is the other.

#### Implemented, 2026-08-06 — both changes

Both, in `scripts/compare_to_metacat.py`, and nothing else changed.

**The split.** `compare` takes the reference's single-run set when comparing
episodes and marks each novel member `in_single_run_set`. `report` then prints
only the members outside *both* sets in the NOVEL column, and lists the rest
below it under what they are — answers the reference reaches, just not as the
convergence answer of one of its 500 episodes. Run on the four problems that
carry them, the nine novel members become **one** worth reading:

```
problem      distinct                      MISSING p50  NOVEL
misc1              12                                -  -
fig5.4-top          8                                -  -
eqe-baaab          13                                -  qrrbqx1
copy5               4                                -  -

8 further member(s) are outside the convergence set but INSIDE the reference's
saturated single-run set — answers the reference reaches, just not as the convergence
answer of one of its 500 episodes. Expected, at the rate f1/n gives:
  misc1        crraaax2, jjjrmrx1, mrraaax1
  fig5.4-top   iixxix1, qexqx1, qiiqx1
  eqe-baaab    aqqqpx1
  copy5        cacx1
```

That is the RC-E finding made structural: the eleven entries this section
accounts for now sort themselves, and what is left in the column is
[RC-C](#rc-c--a-rule-clause-that-denotes-no-object-in-the-target-applies-as-a-silent-no-op)'s
open one.

**The recurrence mark.** Before overwriting its output, the harness reads the
previous cycle from the same path and marks every novel member that cycle also
produced — `also_last_cycle` in the JSON, a `+` in the report:

```
copy5               4                                -  aacx1+

+ marks 1 member(s) the previous cycle produced too. A member that
recurs across cycles is not missing mass, whatever its count in one of them.
```

A missing or unreadable previous file is not an error; the marks are simply
absent. Nothing about the flags themselves changed — a novel member is still
novel, still counted, still in the JSON. What changed is which of them the report
puts in front of you.

**Read the `+` for what it is.** It says the previous cycle produced this member
too, and nothing more. Run twice on the same seeds with an unchanged engine and
*everything* recurs — the first full cycle after these changes marks all 13, which
is trivially true and not a finding. The mark earns its keep across cycles that
differ: after an engine change, or on a moved seed range, a member that survives
both is not missing mass, and that is precisely the question `misc1` and RC-D's
`ajd` leave open.

**Now covered by a test.** `tests/unit/test_compare_harness.py` is the first test
of a measurement script, and it exists because every defect in this file is
silent in the worst direction: a broken `compare` does not crash, it stops
flagging, and a cycle comes back clean because nothing looked. Fourteen tests
over the pure decision functions — the two flags, RC-E's split (including that
single mode must *not* apply it, since there the single-run set is the comparison
itself), the recurrence mark, `convergence_answer`'s backwards skip, and RC-B's
two caps. The script is loaded by path rather than made importable, because being
a script that runs from the command line is part of what it is.

Checked by mutation rather than by passing: reverting `compare` to ignore the
split, `report` to print every novel member in the column, `mark_recurrences` to
compare across problems instead of within one, and `convergence_answer` to stop
skipping answerless runs each fails exactly the tests that claim that ground, and
nothing else.

### What was measured and what was read

Measured, on Petacat: every trace in RC-A and RC-C, the blast-radius table, the
two distribution tables, the Petacat half of the empty-denotation table, the
whole-comparison intervention, `run1`'s 100,000-codelet re-run, and the suite
run.

Measured, on the reference: the `ENUMFAIL` probe, the five-problem defect
emulation, and the reference half of the empty-denotation table. Both patched
trees are working copies outside the Metacat repository, and **nothing in
`../Metacat` was changed** — `git status` there is clean.

Read, not run: nothing load-bearing. The Scheme quoted in RC-A and RC-C is quoted
to explain what the measurements show, and each claim it supports has a
measurement beside it. This is the difference from RC-5 in DISCREPANCIES3, whose
reference side had to be read because no Chez toolchain was available.

Not measured: whether any entry other than `run1` would differ at the reference's
100,000-codelet cap, and whether the RC-A repair moves the *distributions* — the
re-run records every problem's full `produced` counts, but this document compares
them only through the NOVEL and MISSING flags.

Since corrected: MLX **is** installed here, so the GPU half of the matrix does
run, and the suite figure above covers both backends. The "not covered" note at
the top of this document, inherited from DISCREPANCIES3, is stale on that point.

### The order to do this in

1. ~~**RC-A.** One function, guarded by three tests, then the full comparison and
   the numeric matrix re-run. It is the only entry here that changes the engine,
   and it closes 7 of the 22 variations.~~ **Done** — see
   [Implemented](#implemented-2026-08-06).
2. ~~**RC-B.** Decide the harness cap and write the decision into
   `scripts/compare_to_metacat.py` beside the constant.~~ **Done** — single runs
   resolve at the reference's cap, episodes deliberately do not, and the
   measurement that settled which is in
   [RC-B](#implemented-2026-08-06--and-the-reason-narrowed).
3. ~~**RC-E's two reporting changes.** They cost little and they are what stops the
   next cycle spending its attention where this one did.~~ **Done** — see
   [RC-E](#implemented-2026-08-06--both-changes).
4. **RC-C.** ~~The diagnostic first — which description the target lacks and why~~
   — **done, and it eliminated the cause this document named**; the target is not
   short of the description, and neither the no-op nor its rate diverges. What
   remains is the `copy5` distribution entry, and then the rule census named
   [there](#the-diagnostic-was-run-and-it-refutes-its-own-hypothesis). Both are
   new work rather than the completion of this one.
5. ~~**RC-D.** Nothing, until it recurs.~~ **Done** — nothing changed, re-checked
   after RC-A, and the recurrence check is now automatic.
