# Issue 2 Investigation: misc3 Episodic Winners

Status: investigation completed 2026-09-07; the author subsequently approved
its manuscript treatment, now implemented in Section 8.1 and Appendix B.
No engine runs, engine changes, oracle changes, commits, or pushes were performed.
This full investigation note is not part of the submission PDF.

## Problem and Sampling Unit

The problem is `abc -> aabbcc; kkjjii -> ?`.
The example changes one occurrence of each of `a`, `b`, and `c` into two.
The target consists of three descending same-letter pairs: `kk`, `jj`, `ii`.
Its interpretation can involve letter identity, group size, direction, and
conceptual slippages. The three frozen strings have equally sized letter blocks:
`kji` has one of each, `kkjjii` has two, and `kkkjjjiii` has three.
These descriptions explain the strings' structure, not the unrecorded rules
responsible for individual occurrences or a claim of uniquely correct answers.

Each episode has eight runs, with memory retained within the episode and reset
between episodes. Each run permits 100,000 codelets. Each answered episode
contributes exactly one `best_a` string (maximum native numerical quality) and
one `best_b` string (earliest native conceptually undefeated occurrence).
Co-winners are diagnostic evidence only; they are not substituted for the
protocol's single selected string. No sequence population is introduced here.

## Oracle Construction and Validation

Both frozen supports are `{kji, kkjjii, kkkjjjiii}`. `best_a` freezes after 11
episodes with counts 3, 6, 2. `best_b` freezes after seven with counts 2, 3, 2.
Both have `f1/N = 0` at their respective freeze points. The four subsequent
construction episodes do not enlarge or reweight the frozen `best_b` oracle.

| Phase | Episodes | Inner runs | Answered | Capped | Gave up without answer |
|---|---:|---:|---:|---:|---:|
| Reference construction | 11 | 88 | 75 | 13 | 0 |
| Reference validation | 1,000 | 8,000 | 6,984 | 991 | 25 |
| Port comparison | 100 | 800 | 731 | 66 | 3 |

All 1,111 episodes completed and had at least one answer; none had an engine
error. Capped or unsuccessful inner runs were retained in their episodes.

Reference validation selects zero outside `best_a` winners and 99 outside
`best_b` winners. The already-specified simultaneous one-sided bounds are
0.00661137 and 0.13050070, respectively (family alpha 0.05, 38 populations).
Only `best_a` meets the 0.01 coverage target. This qualifies a particular
reference population, not all answers the reference can generate and not
the port's correctness or its outside-answer probability.

The port selects 24 outside `best_a` winners across ten strings and 26 outside
`best_b` winners across 16 strings. Every one of those strings occurs among
the reference validation's selected `best_b` answers. Thus the evidence does
not establish novel or impossible-to-generate strings. It identifies a
difference in the distributions of episode winners. The failed reference
`best_b` qualification makes its port comparison descriptive only.

### Full Frequency Table

Freeze columns use the independently frozen prefixes (11 and seven episodes).
Reference columns use the 1,000 held-out episodes; port columns use 100.
Held-out discoveries remain outside the frozen supports.

| Answer | Freeze A | Freeze B | Ref A | Ref B | Port A | Port B |
|---|---:|---:|---:|---:|---:|---:|
| `jii` | 0 | 0 | 0 | 1 | 0 | 0 |
| `kji` | 3 | 2 | 466 | 380 | 25 | 28 |
| `kjii` | 0 | 0 | 0 | 1 | 0 | 1 |
| `kjiii` | 0 | 0 | 0 | 8 | 5 | 2 |
| `kjji` | 0 | 0 | 0 | 3 | 0 | 1 |
| `kjjiii` | 0 | 0 | 0 | 1 | 1 | 1 |
| `kjjji` | 0 | 0 | 0 | 9 | 2 | 1 |
| `kjjjiii` | 0 | 0 | 0 | 7 | 4 | 1 |
| `kkji` | 0 | 0 | 0 | 2 | 0 | 0 |
| `kkjiii` | 0 | 0 | 0 | 1 | 0 | 0 |
| `kkjji` | 0 | 0 | 0 | 3 | 0 | 0 |
| `kkjjii` | 6 | 3 | 319 | 293 | 15 | 19 |
| `kkjjiii` | 0 | 0 | 0 | 4 | 0 | 0 |
| `kkjjiiiii` | 0 | 0 | 0 | 2 | 0 | 0 |
| `kkjjji` | 0 | 0 | 0 | 5 | 0 | 1 |
| `kkjjjii` | 0 | 0 | 0 | 3 | 0 | 0 |
| `kkjjjiii` | 0 | 0 | 0 | 3 | 0 | 1 |
| `kkjjjiiiii` | 0 | 0 | 0 | 3 | 0 | 1 |
| `kkkji` | 0 | 0 | 0 | 9 | 2 | 4 |
| `kkkjiii` | 0 | 0 | 0 | 5 | 3 | 1 |
| `kkkjji` | 0 | 0 | 0 | 3 | 1 | 0 |
| `kkkjjii` | 0 | 0 | 0 | 2 | 0 | 1 |
| `kkkjjiii` | 0 | 0 | 0 | 10 | 4 | 7 |
| `kkkjjji` | 0 | 0 | 0 | 8 | 1 | 1 |
| `kkkjjjii` | 0 | 0 | 0 | 4 | 0 | 1 |
| `kkkjjjiii` | 2 | 2 | 215 | 228 | 36 | 27 |
| `kkkkjjjii` | 0 | 0 | 0 | 2 | 1 | 1 |

## Diagnostic Partitions, Not Proven Root Causes

The 24 outside `best_a` episodes partition exhaustively as follows:

- **21 episodes:** a single outside string occupies the maximum-quality tier.
- **One episode (43):** three outside strings tie at maximum quality. Choosing
  another tied string would still leave the frozen oracle.
- **Two episodes (74, 84):** an outside string ties with an in-oracle string.
  The recorded selection is outside under the predeclared earliest-occurrence
  policy. Changing that policy could change these two memberships, but it
  would change the experiment and cannot explain the other 22 episodes.

These are groups by observed selection mechanism, not three diagnosed engine
defects. All 24 selected descriptions are also conceptually undefeated, marked
coherent, and have zero unjustified themes and three themes. Native top-rule
abstractness is 96 in 23 cases and 94 in one. Their numerical qualities range
from 84 to 88. A string that looks uneven to a human is not thereby scored as
incoherent by Metacat's native definitions.

The quality winners use unequal multiplicities of `k`, `j`, and `i`:
17 episodes mix one and three occurrences, six mix two with one or three,
and one has multiplicities four, three, two. These structural categories also
do not identify which rules, images, slippages, or memory operations caused them.

Nine outside episodes answered on all eight runs. Fifteen have a capped run;
one of those also has a run that gave up. Therefore truncation cannot explain
the entire discrepancy. In 20 episodes, retained co-winner descriptions prove
that an in-oracle answer was also available; in 18 it scored below the outside
winner and in two it tied. The other four lack saved inside-answer evidence,
which does not prove no inside answer was generated: losing descriptions
were not exhaustively exported.

### Quality Difference

Using one maximum score per episode, reference validation has median 94
(range 82-97); the port has median 86 (range 82-90). Reference scores exceed 90
in 988/1,000 episodes, versus 0/100 for the port. Outside strings are not
uniformly over-scored relative to reference occurrences: for example, saved
reference preference co-winners with answer `kkkji` reach quality 88, while its
two selected port `best_a` occurrences score 86. The absence of the reference's
high-scoring episode maxima is a more useful diagnostic lead than assuming
all uneven strings are impossible or mechanically invalid.

Both inspected answer-quality paths use
`round(0.6 * top_rule_quality + 0.4 * (100 - temperature))`.
Native rule quality combines uniformity, abstractness, and succinctness.
Matching the outer formula does not prove its inputs or search dynamics match.
For example, at abstractness 96 and uniformity 100, a one-clause rule has
succinctness 100 and quality 98; three unit-cost clauses have succinctness 67
and quality 84. At temperature 10, the answer scores would be 95 and 86.
This is an illustrative calculation, **not a reconstruction of saved rules**.

## Source-Level Findings

Two concrete differences occur in the frozen port's live rule-abstraction path.
They are confirmed code differences, but their contribution to the 24 events
is unproven without additional, separately approved diagnostics.

1. **Literal common-change schemas are discarded.**
   [rules.py](../../server/engine/rules.py#L3464) requires a non-`None` relation
   when selecting common change schemas. Metacat `rules.ss:703` excludes only
   the Identity relation, retaining a valid literal destination without a
   named relation. Its nearby example is an object-category transition from
   letter to group with relation `#f`. This is directly relevant as a candidate
   when interpreting `a -> aa`, `b -> bb`, and `c -> cc` as a shared pattern.
   Omitting it can change which concise component-level rules are proposed.
   It does not show which schema was needed in any recorded episode.

2. **Component generalization omits eligibility checks.**
   [rules.py](../../server/engine/rules.py#L2025) probabilistically generalizes
   each common schema to subobjects without Metacat's four-case test in
   `rules.ss:619-642`. The reference checks whether bridges span the left or
   right components, whether they share a right enclosing object, and whether
   otherwise uncovered components have the required descriptors. Omitting
   those checks can propose generalizations the reference would not propose
   from that cluster. The later rule evaluator remains present, so omission
   alone does not prove an invalid proposal survives or causes an outside winner.

The checked reference is reconstructed from the repository's pinned upstream
archive and patches, not a different revision. All 69 reconstructed file hashes
and all 114 study source-file hashes matched their manifests. Neither candidate
was repaired, and no result was relabeled as attributable to it.

## Collector and Evidence Limits

The quality collectors select native numerical maxima. Reference memory is
newest first and is reversed before filtering; port memory appends and the
selector scans the original oldest-first summaries rather than the sorted export.
No alphabetical tie-break or temperature-only selector was found in this path.
See [selection.ss](../../studies/episodic-v2/selection.ss),
[outcomes.py](../../studies/episodic-v1/outcomes.py#L40), and
[study.py](../../studies/episodic-v3/study.py#L225).

The archived 1,111 completion receipts and their 9,699 named files passed hash
checks. Their episode and selection records matched the public data. All 1,011
reference raw description exports matched the published co-winner descriptions,
and the first exported winner in each category matched the saved selection.
This is consistency evidence, not proof that every native value is correct.

Port winner descriptions were saved in canonical order, along with the selected
strings. They do not independently recover arrival order in its three cross-string
quality ties. More generally, the archive does not retain all losing answers,
rule clauses, rule-quality components, workspace groupings, pairwise rule
comparability inputs, or a record of memory interventions. Therefore it cannot
partition the outside events into proven generation, scoring, memory, or
translation root causes. Nor can it isolate an effect of learning without a
matched memory-disabled comparison. No such effect is claimed here.

## Complete Outside best_a Event Ledger

Episode numbers below are one-based; the JSON also records zero-based indices.
Each seed is the episode's first seed, not a claim about which inner run won.
The next seven inner runs use successive seeds. All had the 100,000-codelet cap.

| Episode | First seed | best_a | Quality | Answered | Capped | Gave up | best_b |
|---|---:|---|---:|---:|---:|---:|---|
| 1 | 2895888787 | kkkjiii | 86 | 7 | 1 | 0 | kkkjiii |
| 8 | 2354468294 | kkkjjiii | 84 | 7 | 1 | 0 | kkjjii |
| 15 | 2530390575 | kkkji | 86 | 7 | 1 | 0 | kkkji |
| 22 | 1834014277 | kkkkjjjii | 85 | 8 | 0 | 0 | kkjjjiii |
| 23 | 3482947846 | kjjjiii | 86 | 6 | 1 | 1 | kkjjii |
| 27 | 2476902826 | kjiii | 84 | 6 | 2 | 0 | kkkjjiii |
| 32 | 280639574 | kkkjiii | 87 | 7 | 1 | 0 | kkkjjjiii |
| 34 | 437836071 | kkkjji | 86 | 7 | 1 | 0 | kkkjjjiii |
| 40 | 2578937273 | kkkjiii | 86 | 8 | 0 | 0 | kji |
| 43 | 2194106505 | kjjjiii | 86 | 8 | 0 | 0 | kkkjjiii |
| 48 | 3442677868 | kkkjjiii | 85 | 7 | 1 | 0 | kkkjjiii |
| 49 | 105575245 | kkkjjiii | 86 | 8 | 0 | 0 | kkkjjiii |
| 51 | 4025459556 | kjiii | 88 | 6 | 2 | 0 | kkjjii |
| 67 | 2269513683 | kjjji | 87 | 7 | 1 | 0 | kjjji |
| 68 | 1418809673 | kkkji | 86 | 7 | 1 | 0 | kkkji |
| 69 | 2666739882 | kjjiii | 86 | 7 | 1 | 0 | kji |
| 71 | 876818767 | kjiii | 86 | 8 | 0 | 0 | kkkjjji |
| 72 | 4101556133 | kjiii | 86 | 8 | 0 | 0 | kkkjjjiii |
| 74 | 759832026 | kjjji | 87 | 8 | 0 | 0 | kkkkjjjii |
| 82 | 2969366380 | kkkjjiii | 85 | 7 | 1 | 0 | kkkjjiii |
| 84 | 533424517 | kjjjiii | 86 | 8 | 0 | 0 | kjjjiii |
| 86 | 2770496526 | kjiii | 86 | 5 | 3 | 0 | kjiii |
| 94 | 1694651647 | kjjjiii | 87 | 8 | 0 | 0 | kkjjii |
| 95 | 2299010004 | kkkjjji | 85 | 6 | 2 | 0 | kji |

## Reproducing the Public-Data Analysis

From the repository root, using Python 3.11 or newer:

```sh
python3 academic/tools/investigate_misc3.py --output academic/investigations/misc3-episodic-audit.json
python3 -m unittest discover -s academic/tests -p 'test_misc3_investigation.py'
```

This reads the published data and writes a separate derived audit. It does not
import either engine, run episodes, update the frozen study, or require the
private archive. The [JSON audit](misc3-episodic-audit.json) includes input hashes,
all frequencies, native descriptions for the 24 selected outside quality winners,
and selection/cap diagnostics. The private raw-receipt cross-check described
above was a separate read-only check; the public-only command does not repeat it.

## Approved Manuscript Treatment

The author approved the following treatment, now incorporated in the paper.
Final manuscript review and approval are still required before committing.

Add a focused `misc3` diagnostic case study with the problem, independently
frozen supports, reference validation results, and outside-winner counts.
Emphasize that 1,000 reference validation episodes qualify `best_a`, while only
100 port episodes expose 24 outside winners: the expensive reference work yields
a reusable test that can detect a discrepancy with much less comparison work.
Do not call that a validated port, an equivalence result, or a causal demonstration
of learning. Report `best_b` separately as an inadequately covered oracle with
descriptive port results.

Place the full frequency table and the 21/1/2 diagnostic partition in an appendix
or accompanying artifact. Include the score difference and the two static code
findings explicitly as investigative leads, not proven explanations of individual
episodes. Preserve all frozen results and state that repair validation would
require a separately versioned comparison. No new experiment, repair, or change
of winner population is proposed as part of this manuscript edit.
