# DISCREPANCIES3 — divergent outcomes between Petacat and Metacat

**What this is.** A record of where Petacat's stopping-state distributions differ
from Metacat's, measured. Nothing else.

**What this is not.** The measurement sections carry no hypotheses. Every table
below reports what the two programs produced, and nothing is inferred from a
table that was not measured.

**Amendment, 2026-08-04.** The five widest-divergence problems have since been
investigated, and each now carries an inline **Root cause and plan** block under
its distribution table, drawing on the shared findings in
[Root causes](#root-causes-of-the-five-widest-divergences) below. Those blocks
are analysis; everything else in this document remains measurement. The
measurement tables are unchanged.

**Amendment, 2026-08-05.** RC-1 through RC-4 are **implemented**. Every "Petacat"
column in this document therefore describes the engine *before* those four
changes; the "after" figures are in each block's **Measured effect** paragraph and
in [The fix set](#the-fix-set-and-what-it-is-worth). RC-5 remains open. Two things
the implementation surfaced that the investigation had not:

- the Slipnet's same-group node is named `plato-samegrp`, not `plato-same-group`.
  Testing against the name that does not exist silently *excludes* every
  same-group from the eligible descriptions instead of admitting it — a second way
  to get the set wrong, and one the monkeypatched measurement shared. Corrected,
  and guarded by a test either way round;
- `tests/module/test_expected_range.py` now fails on three problems. That is the
  fixture being stale, not the engine regressing — see
  [The expected-range fixture](#the-expected-range-fixture-needs-adjudication).

**Amendment, 2026-08-05 (later).** RC-5's diagnostic has been run and RC-5 is
**settled**: the divergence is not in Petacat. The Metacat build that produced the
oracle carries a regression, introduced by its own commit `130314d`, that stops a
rule clause naming the *whole string* from denoting anything. Petacat reproduces
Marshall's behaviour; the oracle records the regression. The evidence and the
measurement are in [RC-5](#rc-5--a-reference-side-regression-in-constituent-objects-of),
and **the decision it forces is open** — see
[What RC-5 leaves to decide](#what-rc-5-leaves-to-decide).

**Amendment, 2026-08-06. This document is now a record of how the divergence was
found, not of where Petacat currently stands.** Four things happened, and each
invalidates part of what is below. Current standing is in
[Where things actually stand](#where-things-actually-stand) at the end.

1. **RC-5's decision was taken: repair the reference.** Petacat was not changed.
   `constituent-objects-of` now tests `letter?` rather than `group?`
   (Metacat `bf06847`), which restores the string path Marshall documents.
2. **The oracle was re-sampled on the repaired reference** — 374,500 runs, all 19
   problems. **Every TVD in this document is measured against the superseded
   oracle.** Five problems moved materially: `eqe-baaab` 0.335, `fig5.4-top`
   0.236, `run6` 0.124, `misc3` 0.053, `copy5` 0.020, with the other fourteen
   inside 0.006. Those five are precisely the ones this document analyses in most
   depth, so their numbers are not merely stale — they are measured against a
   reference that has since been corrected.
3. **TVD is no longer the comparison.** It was replaced by two set comparisons
   that flag rather than fail, in both a single-run and an episodic mode. See
   [The comparison changed](#the-comparison-changed).
4. **The expected-range fixture is gone**, along with the two tests that read it,
   which closes the adjudication this document asked for. See
   [The expected-range fixture](#the-expected-range-fixture-needs-adjudication).

### What earlier amendments got wrong

Kept rather than quietly edited, because the reasoning that produced them is the
subject of this document.

- **The RC-5 heading was wrong.** It read "a swap abstracted one level too high",
  which named the abstraction step as the defect. Both programs abstract the swap
  identically; the reference could not *apply* the resulting clause. The heading
  is corrected in place and the original noted there.
- **The three candidate explanations listed in the `eqe → qeq ; abbba` plan were
  all wrong.** The diagnostic was still worth running: it eliminated them and
  pointed one step further on.
- **"Found by enumeration in one pass" overstated the technique.** Replacing
  `report-error-and-halt` with a recorder that returns `#f` does let a run
  continue, but `#f` corrupts the computation, so the run usually dies of a
  downstream type error before the next genuine bad message. It took three sweeps
  to find nine missing methods, not one.
- **The single-run oracle was described as saturated throughout.** Three problems
  never reached the 1e-4 target: `fig5.4-top` (0.00037) and `eqe-baaab` (0.00025)
  stopped at the run ceiling, `misc3` (0.00021) was stopped by hand. The practical
  cost is under 0.04 spurious flags per 100 runs, but the claim was too strong.
- **Predicting that the 2026-08-06 engine fixes would move the measurement was
  wrong.** Re-measuring on identical seeds gave byte-identical results. The fixes
  are real divergences from the repaired reference but too rare to shift a
  100-sample distribution.

## Provenance of the two samples

| | Metacat | Petacat |
|---|---|---|
| source | `../Metacat/oracle-out/oracle.json`, `oracle-out-copy/oracle.json` | ad-hoc sampler, not committed |
| commits | `424feb0`, `d9dddee` | `0de0d75` |
| runs per problem | 10,292 – 51,128, sampled to Good-Turing saturation | 500 (seeds 0–499) |
| codelet cap | 100,000 | 20,000 |
| episodic memory | off | fresh instance per run |
| arithmetic | Chez Scheme | `numpy` backend, float64 |

`*NONE*` is a run that stopped without an answer. `*CAP*` is a run that reached
the codelet ceiling. Both samples use that vocabulary.

**Two sampling facts bear on how any single row should be read.** Petacat's
codelet cap is one fifth of Metacat's, so the two `*CAP*` columns are not
measuring the same thing. And Petacat's sample is roughly two orders of magnitude
smaller, so with 500 runs a state below about 0.6% is not reliably
distinguishable from one that is absent; single-run states are recorded here but
carry no weight on their own.

## Divergence by problem

Total-variation distance between the two distributions: 0 identical, 1 disjoint.
Ordered widest first.

| TVD | problem | demo | Metacat n | how Metacat's sample stopped | Petacat n |
|---:|---|---|---:|---|---:|
| **0.59** | `abc → cba ; mrrjjj` | misc1 | 40,836 | saturated | 500 |
| **0.56** | `eeqee → qeeq ; xxixx` | fig5.4-top | 51,128 | checkpoint | 500 |
| **0.50** | `eqe → qeq ; abbbc` | run6 | 51,128 | checkpoint | 500 |
| **0.47** | `eqe → qeq ; abbba` | eqe-baaab | 51,128 | checkpoint | 500 |
| **0.40** | `aabb → cc ; aabb` | copy5 | 31,042 | saturated | 500 |
| **0.36** | `a → b ; z` | misc4 | 11,454 | no_singletons | 500 |
| **0.28** | `rst → rsu ; xyz` | run3 | 13,778 | saturated | 500 |
| **0.27** | `abc → abd ; xyz` | run4 | 11,122 | saturated | 500 |
| **0.24** | `aabc → aabd ; ijkk` | fig5.7 | 14,608 | saturated | 500 |
| **0.20** | `abc → abd ; glz` | misc5 | 11,288 | saturated | 500 |
| **0.19** | `abc → aabbcc ; kkjjii` | misc3 | 1,660 | shards_exited | 500 |
| **0.06** | `abc → abd ; mrrjjj` | run1 | 11,122 | no_singletons | 500 |
| **0.04** | `xqc → xqd ; mrrjjj` | run2 | 11,454 | saturated | 500 |
| **0.03** | `abc → d ; abc` | copy6 | 10,292 | saturated | 500 |
| **0.03** | `abc → abd ; ijk` | misc2 | 11,454 | saturated | 500 |
| **0.01** | `xy → z ; xy` | copy3 | 11,288 | no_singletons | 500 |
| **0.01** | `zy → x ; zy` | copy4 | 11,288 | no_singletons | 500 |
| **0.01** | `ab → c ; ab` | copy1 | 10,956 | no_singletons | 500 |
| **0.01** | `bc → d ; bc` | copy2 | 11,454 | no_singletons | 500 |

Median 0.20 across 19 problems. 8 at or below 0.10; 5 at or above 0.40.

The stop column matters when reading a row. `saturated` and `no_singletons` mean
Metacat's own sampler judged the state set complete. `checkpoint` means it stopped
at a run ceiling with the set still growing — those three problems have 55, 61 and
87 distinct states. `shards_exited` means the sample ended early: **misc3 rests on
1,660 runs**, an order of magnitude below every other problem here, and its 36
recorded states are not a saturated set.

## Inventory: states Metacat reaches and Petacat did not

Listed where Metacat's share is at least 1%, which is far above the level at which
Petacat's 500 runs could miss a state by chance.

| problem | state | Metacat | Petacat |
|---|---|---:|---:|
| copy5 | `aabb` | 1.4% | 0.0% |
| fig5.4-top | `ixxi` | 4.4% | 0.0% |
| fig5.4-top | `qiq` | 1.5% | 0.0% |
| misc2 | `ijk` | 2.0% | 0.0% |
| run3 | `xyz` | 17.1% | 0.0% |
| run4 | `xyz` | 16.3% | 0.0% |

## Inventory: states Petacat reached and Metacat does not

How strong a zero in the Metacat column is depends on that problem's stop reason
in the table above: firm where the sample saturated, weaker for the three
`checkpoint` problems whose state sets were still growing, and weakest for misc3.
Petacat's counts are given raw as well as by share, because several are single runs.

| problem | state | Metacat | Petacat | Petacat runs |
|---|---|---:|---:|---:|
| copy1 | `*NONE*` | 0.0% | 0.8% | 4 |
| copy2 | `*NONE*` | 0.0% | 0.4% | 2 |
| copy2 | `bc` | 0.0% | 0.2% | 1 |
| copy3 | `*NONE*` | 0.0% | 1.0% | 5 |
| copy3 | `xy` | 0.0% | 0.4% | 2 |
| copy4 | `*NONE*` | 0.0% | 1.4% | 7 |
| copy6 | `ad` | 0.0% | 0.4% | 2 |
| eqe-baaab | `qabbb` | 0.0% | 7.6% | 38 |
| eqe-baaab | `bbbaq` | 0.0% | 3.6% | 18 |
| eqe-baaab | `baaaa` | 0.0% | 0.6% | 3 |
| eqe-baaab | `aaaab` | 0.0% | 0.4% | 2 |
| eqe-baaab | `aabbb` | 0.0% | 0.2% | 1 |
| eqe-baaab | `aaaaa` | 0.0% | 0.2% | 1 |
| eqe-baaab | `baaba` | 0.0% | 0.2% | 1 |
| fig5.7 | `*CAP*` | 0.0% | 4.6% | 23 |
| misc2 | `*CAP*` | 0.0% | 0.4% | 2 |
| misc3 | `kkjii` | 0.0% | 0.2% | 1 |
| run1 | `*CAP*` | 0.0% | 0.6% | 3 |
| run3 | `*CAP*` | 0.0% | 1.0% | 5 |
| run4 | `*CAP*` | 0.0% | 1.4% | 7 |
| run6 | `cdddb` | 0.0% | 0.6% | 3 |
| run6 | `cddbc` | 0.0% | 0.6% | 3 |
| run6 | `aeeeq` | 0.0% | 0.4% | 2 |
| run6 | `cdccb` | 0.0% | 0.2% | 1 |

## Inventory: the target string as the answer

The share of runs answering with the target string unchanged, and the share
stopping without an answer, side by side.

| problem | target | `target` Metacat | Petacat | `*NONE*` Metacat | Petacat | `*CAP*` Metacat | Petacat |
|---|---|---:|---:|---:|---:|---:|---:|
| copy1 | `ab` | 13.4% | 14.0% | 0.0% | 0.8% | 0.0% | 0.0% |
| copy2 | `bc` | 0.0% | 0.2% | 0.0% | 0.4% | 0.0% | 0.0% |
| copy3 | `xy` | 0.0% | 0.4% | 0.0% | 1.0% | 0.0% | 0.0% |
| copy4 | `zy` | 13.9% | 13.8% | 0.0% | 1.4% | 0.0% | 0.0% |
| copy5 | `aabb` | 1.4% | 0.0% | 48.4% | 74.6% | 0.6% | 14.6% |
| copy6 | `abc` | 13.2% | 10.6% | 0.0% | 1.2% | 0.0% | 0.0% |
| eqe-baaab | `abbba` | 3.3% | 1.0% | 0.5% | 8.8% | 0.0% | 0.0% |
| fig5.4-top | `xxixx` | 0.1% | 0.0% | 15.8% | 71.2% | 0.0% | 0.0% |
| fig5.7 | `ijkk` | 2.1% | 1.2% | 0.0% | 0.4% | 0.0% | 4.6% |
| misc1 | `mrrjjj` | 8.7% | 66.2% | 0.0% | 0.0% | 0.0% | 0.0% |
| misc2 | `ijk` | 2.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.4% |
| misc3 | `kkjjii` | 34.0% | 37.8% | 0.5% | 4.2% | 10.6% | 17.2% |
| misc4 | `z` | 36.7% | 0.4% | 3.2% | 5.8% | 0.0% | 0.0% |
| misc5 | `glz` | 20.1% | 1.0% | 5.2% | 13.4% | 0.0% | 1.4% |
| run1 | `mrrjjj` | 3.3% | 0.6% | 0.0% | 0.0% | 0.0% | 0.6% |
| run2 | `mrrjjj` | 3.0% | 0.2% | 0.1% | 0.0% | 0.0% | 0.0% |
| run3 | `xyz` | 17.1% | 0.0% | 11.4% | 32.2% | 0.0% | 1.0% |
| run4 | `xyz` | 16.3% | 0.0% | 9.7% | 35.0% | 0.0% | 1.4% |
| run6 | `abbbc` | 0.0% | 0.0% | 2.5% | 21.2% | 0.0% | 0.0% |

## Root causes of the five widest divergences

Five defects account for the five widest-divergence problems. They were found by
running the reference headless (`chez -q --script`, `metacat-headless.ss`, the
same entry point the oracle sampler used) beside instrumented Petacat runs, and
by reading the two sources side by side. Each is a single named divergence from
the Scheme with a code site on both sides.

Four of the five (RC-1 … RC-4) were then **verified by intervention**: applied to
a live engine as monkeypatches and every problem re-sampled against the oracle.
The per-problem effect is recorded in that problem's own block below. RC-5 has
since been settled too, and it is not a Petacat defect: it is a divergence
between the reference build the oracle was sampled from and the reference's own
source. See its block below.

| | Defect | Petacat site | Reference |
|---|---|---|---|
| **RC-1** | `distinguishing?` is inverted: `all` where the reference has `any` | `concept_mappings.py:216`, `descriptions.py:197` | `workspace-objects.ss:223-244` |
| **RC-2** | A rule may name its object by *any* description type | `rules.py:2195` | `workspace-objects.ss:260-268` |
| **RC-3** | A rule's object-description is an argmax, not a stochastic pick | `rules.py:2195,2182-2190`, `rules.py:3475` | `workspace-objects.ss:270-275`, `rules.ss:455-458` |
| **RC-4** | A singleton group never gets an image, and `apply_rule` skips it in silence | `images.py:997`, `rules.py:2463` | `groups.ss:84`, `workspace-strings.ss:411-417` |
| **RC-5** | *(reference-side)* a rule clause naming the whole string denotes nothing | — | `utilities.ss:110-114`, `rules.ss:1432`, `rules.ss:1540` |

### RC-1 — `distinguishing?` is inverted

The reference has one predicate, `distinguishing-descriptor?`
(`workspace-objects.ss:223-244`), and its last line is

```scheme
(not (member? descriptor other-descriptors))
```

A descriptor distinguishes an object when **no other object in the string
carries it**. Petacat has two independently-written copies of this predicate —
`ConceptMapping._descriptor_is_distinguishing` (`concept_mappings.py:216`) and
`Description.is_distinguishing` (`descriptions.py:197`) — and both read

```python
all_have_it = all(any(d.descriptor is descriptor …) for other in other_objects)
return not all_have_it
```

`all` where the reference has `any`. A descriptor is treated as distinguishing
unless *every* sibling carries it.

The predicate is load-bearing in four places: the bridge scouts' admissibility
gate, bridge urgency, rule object-description eligibility, and
`important-object-bridge-scout`'s choice of description. Its most visible
consequence is in the bridge gate. `bottom-up-bridge-scout` (`bridges.ss:938-952`)
refuses to propose a bridge with no distinguishing Identity/Opposite mapping, and
says why in a comment: a bridge resting only on `StrPosCtgy` and `LettCtgy`
slippages has "no *a priori* justification". Under the inversion that gate opens.

Measured on `eqe → qeq` (60 runs): Petacat builds 42 *crossing* horizontal-top
bridges — `lmost=>middle`, `middle=>lmost`, `middle=>rmost`, `rmost=>middle` — out
of 172 built. The reference builds **zero** in 300 runs; every top bridge it
builds is position-preserving (`lmost=>lmost`, `middle=>middle`, `rmost=>rmost`)
with letter-category slippages. In `eqe` the leftmost `e` is not distinguished by
`e`, because the rightmost letter is also an `e` — which is exactly what the
reference's `member?` catches and Petacat's `all` does not.

A second, smaller divergence sits in the same function: the reference excludes a
group's supergroup and its own subgroups from the sibling set; Petacat excludes
only the object itself.

### RC-2 — a rule may name its object by any description type

`get-descriptions-for-rule` (`workspace-objects.ss:260-268`) restricts a rule's
object-description to exactly three kinds:

```scheme
(or (description-type? plato-string-position-category)
    (description-type? plato-alphabetic-position-category)
    (and (description-type? plato-letter-category)
         (or (letter? self) (eq? (get-group-category self) plato-samegrp))))
```

Petacat's `_choose_description_for_rule` (`rules.py:2195`) admits every relevant
distinguishing description except object-category. So it produces object
descriptions the reference cannot express — `(group GroupCtgy succgrp)`,
`(group Length two)`, `(group Direction left)`, and, via the fallbacks at
`rules.py:2182-2190`, `(letter ObjectCtgy letter)`.

This matters because those descriptors are not unique within a string. Measured
share of all object-description resolutions, and how many objects each resolved
to (60 runs per problem):

| problem | `group/GroupCtgy` share | what those resolutions matched |
|---|---:|---|
| `abc → cba ; mrrjjj` | 36.3% | **no** object 68× — a silent no-op |
| `eeqee → qeeq ; xxixx` | 72.1% | **3** objects at once, 3,417× of 3,451 |
| `aabb → cc ; aabb` | 91.3% | **2 or 3** objects at once, 42,120× of 48,824 |

An ambiguous object-description has two failure modes, and both are visible in
the distributions. Resolving to *several* objects makes the clauses collide —
19,352 `Conflicting transforms` failures across 60 runs of `aabb → cc`, 322 per
run — so the rule fails `currently_works`, is never built, rule-codelet clamps
recur, and the jootser gives up (`jootsing.ss:173-178`). Resolving to *no* object
makes the clause a silent no-op, and the answer comes out as the target string
unchanged.

### RC-3 — argmax where the reference makes a stochastic pick

`choose-description-for-rule` (`workspace-objects.ss:270-275`) is

```scheme
(stochastic-pick possible-descriptions
  (temp-adjusted-values (tell-all possible-descriptions 'get-conceptual-depth)))
```

Petacat's is `max(candidates, key=conceptual_depth)` — deterministic. That
removes a source of variation the reference has, and permanently prefers the
deepest descriptor over the shallower ones the reference still reaches at
temperature. Note that the sibling routine `_instantiate_change_template`
(`rules.py:2288-2300`) already implements the stochastic pick correctly, so the
machinery and the metadata coefficients are both in place.

Attached to the same defect: `_object_description_possible` (`rules.py:3475`)
tests `len(descriptions) > 0` where the reference tests
`(not (null? (tell object 'get-descriptions-for-rule)))` (`rules.ss:455-458`).
The reference refuses to instantiate a rule template naming an object it cannot
legally describe; Petacat instantiates one anyway and then invents a description
through the fallbacks. Fixing RC-2 without fixing this simply moves the illegal
description from the chooser into the fallback.

### RC-4 — a singleton group never gets an image

In the reference every object owns an image from the moment it is constructed
(`groups.ss:84`), so "the middle group" always has one. Petacat builds the image
tree lazily from the string image, and `StringImage._constituent_images`
(`images.py:963-1014`) partitions the string positionally, taking at each
position

```python
widest = max(candidates, key=lambda o: o.right_string_pos)
```

`max` is first-wins on ties, and `string.objects` lists letters before groups. A
**singleton group** and the letter it encloses span the same single position, so
the letter wins and the group's `image` stays `None`.

`apply_rule` (`rules.py:2461-2469`) then does `if img is not None:` and skips
that object's transforms **in silence**. The reference has no such case, so it
has no such branch.

Measured directly on `eeqee → qeeq` (seed 0), in two steps.

Three-clause rules of this shape resolve their clauses correctly and still
produce the wrong string:

```
(group StringPos lmost)[LetterCtgy→q; ObjectCtgy→letter]
 || (group StringPos middle)[LetterCtgy→e; Length→succ]
 || (group StringPos rmost)[LetterCtgy→q; Length→pred]

eeqee => qqq            (expected qeeq)
```

Instrumenting `_group_transforms_by_object` on the same run shows why — six
transforms group cleanly onto three distinct objects, and the middle one carries
no image:

```
Group  img=Image(letter=e, dir=right, subs=2)  [LetterCtgy q, Length one]
Group  img=Image(letter=e, dir=right, subs=2)  [LetterCtgy q, Length one]
Group  img=None                                [LetterCtgy e, Length two]
```

Not one of the applied transforms in any traced run of this problem is
`LetterCtgy→e` — the middle group's transforms never reach an image at all.
`currently_works` passed **2 of 2,736 times** for three-clause rules here; the
reference builds such a rule in about half its runs.

### RC-5 — the rule shape only Petacat reaches

*(This heading read "a swap abstracted one level too high" until the diagnostic
was run. The measurement below is unchanged; the cause it was attributed to was
wrong, and is corrected in the sub-block that follows.)*

The reference's rules for `eqe → qeq` name the swapped objects — "Swap
letter-categories of leftmost letter, middle letter, and rightmost letter" —
which is an extrinsic clause with three object-descriptions, costing 2 in
`compute-rule-succinctness` (`rules.ss:1628-1637`), giving succinctness 80 and
quality 78. Petacat additionally produces a one-object form of the same clause —
the `subobjects_swap` marking from
`ExtrinsicChangeDescription.mark_as_subobjects_swap_if_possible`
(`rules.py:651`) — which costs 1, giving **succinctness 100 and quality 86**.

Measured on `eqe → qeq ; abbba` (120 runs each, RC-1…RC-4 applied to Petacat):

| rule shape | reference | Petacat | q | u | a | s |
|---|---:|---:|---:|---:|---:|---:|
| `(intrinsic, intrinsic, intrinsic)` | 104 | 94 | 57 | 100 | 50 | 67 |
| `(extrinsic)` naming the objects | 51 | 19 | 78 | 100 | 77 | 80 |
| `(extrinsic)` as a subobjects swap | **0** | **70** | 86 | 100 | 77 | 100 |
| `(intrinsic, extrinsic)` | 102 | 51 | 42 | 83 | 40 | 67 |
| `(verbatim)` | 11 | 11 | 40 | 100 | 0 | 100 |

The quality formulas agree exactly wherever both programs produce the same rule
shape, so this is not a formula divergence: it is that Petacat *reaches* a rule
shape the reference does not, and that shape outranks every other rule in the
Workspace, so the answer-finder takes it.

**Where the two programs part company is not the marking.**

#### RC-5 — a reference-side regression in `constituent-objects-of`

Both programs mark the swap. Instrumenting
`mark_as_subobjects_swap_if_possible` (`rules.py:651`) over 20 runs of
`eqe → qeq ; abbba` records the marking condition being met 107 times and failing
72 — and where it is met, the enclosing object is the *WorkspaceString* `eqe`, with
three constituents against the swap's three reference objects:

```
(enclosing kind, #constituents, #reference objects, marked) -> count
('WorkspaceString', 3, 3, True)  -> 107
('WorkspaceString', 3, 2, False) ->  72
```

That is exactly what `mark-as-subobjects-swap-if-possible` (`rules.ss:987-991`)
computes in the Scheme, whose `get-enclosing-object` (`rules.ss:674-679`) answers
the string when an object has no enclosing group and whose string answers
`get-constituent-objects` with its top-level objects
(`workspace-strings.ss:411-413`). `eqe` admits no bonds and so has no groups, so
the enclosing object is the string in both programs and the three letters are its
constituents in both. **The reference marks the swap too.**

What the reference then cannot do is *apply* it.
`change-descriptions->rule-clause-template` (`rules.ss:793-809`) turns a marked
swap into a clause with one object-description, and
`reference-object->object-description` (`rules.ss:878-886`) renders a string as
`(string StrPosCtgy whole)`. `get-extrinsic-transforms` (`rules.ss:1425-1436`)
sees a single object-description and asks for the reference object's
constituents — through `constituent-objects-of` (`utilities.ss:110-114`):

```scheme
(define constituent-objects-of
  (lambda (object)
    (if (group? object)
      (tell object 'get-constituent-objects)
      '())))
```

A workspace-string is not a `group?`. The clause denotes nothing, `(< (length
denoted-objects) 2)` yields no transforms, the string generates unchanged,
`currently-works?` (`rules.ss:223-235`) fails, and the rule is never built. The
oracle's zero in the table above is that fizzle, not an abstraction the reference
declines to make.

`constituent-objects-of` is **not Marshall's**. It was added in the Metacat
repository's commit `130314d` to stop a *letter* reference object reaching
`report-error-and-halt`, replacing `(tell-all reference-objects
'get-constituent-objects)` at both `rules.ss:1432` and `rules.ss:1540`. Excluding
letters was right; narrowing to groups was wider than the bug, and it caught
strings. Marshall's `workspace-strings.ss:385-388` says what it cost, in his own
words and directly above the method it disables:

```scheme
;; The following methods allow workspace-strings to behave as spanning
;; groups, so that a workspace-string can be used as the reference-object
;; of an intrinsic change-description or rule-clause-template:
```

His comment at `workspace-strings.ss:455-460` names a rule of exactly that shape
— `abc → aaa` giving `CHANGE (string <StrPos> <whole>) (subobjs <LetCat> <a>)` —
and the second patched site, `rules.ss:1540`, is the one that applies it. Both
oracle commits (`424feb0`, `d9dddee`) postdate `130314d`, so the whole oracle
carries the regression.

**Measured by intervention, the other way round.** Narrowing Petacat's
`_get_constituent_objects` to the reference build's semantics — `[]` for a
WorkspaceString — at exactly those two sites, and re-sampling all nineteen
problems, 500 seeds, `numpy`, 20,000-codelet cap:

| problem | TVD, shipped | TVD, emulating the reference build | |
|---|---:|---:|---|
| `eqe-baaab` | 0.300 | **0.072** | extrinsic site |
| `fig5.4-top` | 0.230 | **0.044** | extrinsic site |
| `run6` | 0.096 | **0.058** | extrinsic site |
| `misc3` | 0.269 | **0.234** | intrinsic site |
| `copy5` | 0.195 | **0.182** | intrinsic site |
| the other fourteen | — | unchanged to ±0.001 | |

Median 0.073 → 0.059. Nothing gets worse. On `eqe-baaab` the rank inversion
reverses to the oracle's own ordering — `qeeeq` 27.8% → 46.0% against the
reference's 49.4%, `baaab` 51.8% → 25.8% against 24.9% — and on `fig5.4-top` the
`ixxi` over-production the RC-4 block left behind disappears. Splitting the two
call sites apart (500 seeds each) separates the two effects cleanly: patching
only `_get_extrinsic_transforms` gives `eqe-baaab` 0.072, `fig5.4-top` 0.042 and
`run6` 0.058 with `copy5` and `misc3` untouched; patching only
`_get_intrinsic_transforms` gives `copy5` 0.182 and `misc3` 0.234 with the other
three untouched.

**What was run, and what was not.** The Petacat side is measured — the marking
instrumentation, the nineteen-problem sweep, and the two-site split. The
reference side is *read*: the Scheme above is quoted from the working tree at
`5cb8afc`, and the claim that its rule fizzles rather than builds follows from
those five procedures rather than from a Chez run, because no Chez toolchain is
installed here (`Metacat/docker/` builds one). Confirming it directly means
building that image and running `eqe → qeq ; abbba` headless with and without the
one-line reference change; the prediction is 49/25 before and roughly 28/52
after, matching Petacat's two columns.

Reproducing the oracle from Petacat by adopting the reference build's semantics
is *not* an argument that those semantics are right. It is the same one-word
difference reproduced from the other side.

#### What RC-5 leaves to decide

Petacat is not wrong here and the oracle is not neutral. Two ways forward, and
the choice is not one to make while editing a file:

1. **Repair the reference and re-measure.** Change `constituent-objects-of` to
   exclude letters rather than admit only groups — `(if (letter? object) '()
   (tell object 'get-constituent-objects))` — which fixes the crash `130314d`
   was written for and restores the string path Marshall documents. The oracle
   then has to be re-sampled; five problems' distributions move, and every TVD in
   this document that involves them is provisional until it is. Petacat needs no
   change.
2. **Track the oracle.** Narrow Petacat to the reference build's semantics at the
   two sites, buying the five improvements above at the cost of shipping a
   divergence from Marshall's source that this document would then have to record
   as deliberate.

The measurement cannot choose between them; only a decision about what the oracle
is *for* can. Nothing has been changed in either program pending that decision.

**Decided, 2026-08-06: option 1.** The reference was repaired and the whole
oracle re-sampled. Petacat was not changed, which is the point — it already
implemented Marshall's semantics, and the divergence was in the instrument.

What the repair cost and confirmed:

- The reference was verified from its own side before anything was rebuilt.
  Running `eqe → qeq ; abbba` headless, 300 seeds: `constituent-objects-of` on
  the initial string answers **0 objects as built and 3 repaired**, and built top
  rules carrying a single-object extrinsic clause go **0 → 202**. As built it
  reproduces its own oracle (`qeeeq` 47.7% against 49.4%, `baaab` 25.3% against
  24.9%); repaired it lands on Petacat's distribution (30.3% / 54.3% against
  27.8% / 51.8%). The loop closes from both sides.
- The repair was regression-checked against the crash `130314d` was written for:
  950 runs over all 19 problems plus `aabc → aabd; ijkk` seed 35 specifically, no
  bad messages, every run completed.
- **Five further latent bugs surfaced**, all the same family: a workspace-string
  used as a snag object being sent messages only letters and groups answer. They
  need two snags in one run, so 374,500 single runs never hit them; a
  session-based sample reaches them easily and they killed shards on `copy1`,
  `copy2` and `copy4`. Fixed in the reference (`ca8f7e0`), and the corresponding
  divergences in Petacat are recorded in
  [Where things actually stand](#where-things-actually-stand).

### The fix set, and what it is worth

RC-1 through RC-4 are implemented, and **all nineteen problems** were re-sampled
against the oracle from the shipped engine — 300 seeds each, `numpy` backend,
20,000-codelet cap, the same conditions as the baseline sample this document
reports, so the two columns are comparable. The "before" column reproduces the
headline table's TVDs to sampling noise, which is the check that the harness is
measuring the same thing.

| problem | TVD before | TVD after | |
|---|---:|---:|---|
| `misc1` | 0.629 | **0.074** | |
| `fig5.4-top` | 0.561 | **0.200** | RC-5 residual |
| `run6` | 0.507 | **0.130** | |
| `eqe-baaab` | 0.446 | **0.319** | RC-5 residual |
| `copy5` | 0.394 | **0.183** | |
| `misc4` | 0.361 | **0.140** | |
| `run4` | 0.295 | 0.272 | |
| `run3` | 0.272 | 0.265 | |
| `fig5.7` | 0.238 | **0.108** | |
| `misc5` | 0.214 | **0.135** | |
| `misc3` | 0.191 | *0.252* | **worse** |
| `run2` | 0.071 | 0.027 | |
| `run1` | 0.057 | 0.046 | |
| `copy6` | 0.031 | *0.072* | **worse** |
| `misc2` | 0.027 | 0.008 | |
| `copy4` | 0.017 | *0.036* | **worse** |
| `copy3` | 0.017 | 0.010 | |
| `copy1` | 0.010 | *0.037* | **worse** |
| `copy2` | 0.010 | 0.013 | **worse** |

Median 0.214 → **0.108**. Problems at or below 0.10: 8 → 9. Problems at or above
0.40: **4 → 0**.

Three of these moved when the `plato-samegrp` naming error was corrected during
implementation: `fig5.4-top` 0.266 → 0.200 and `misc3` unchanged, against
`copy5` 0.122 → 0.183 and `fig5.7` 0.070 → 0.108. The correction admits a
description the reference admits, so it stands on its own terms; the two problems
it costs are worth re-visiting once RC-5 is settled, since both turn on
`subobjects` changes over a whole group.

**The five that got worse.** Four of them (`copy1`, `copy2`, `copy4`, `copy6`)
move by 0.02–0.04 from a base at or below 0.03, which is within the noise of a
300-run sample and should be re-measured at 3,000 before anything is concluded.
`misc3` moving 0.191 → 0.252 is larger, but its reference distribution is the one
this document flags as **not saturated** — 1,660 runs, `shards_exited`, 36 states
still growing — so the comparison is weak in both directions. Neither is a reason
to withhold the fixes; both are reasons to re-measure, and `misc3` is a reason to
extend the reference sample before treating its TVD as evidence at all.

**Where the changes are.** Five functions, no seed data, no codelet source:

| | file | what changed |
|---|---|---|
| RC-1 | `workspace_objects.py` | `distinguishing_descriptor` — one module-level predicate, transcribing `workspace-objects.ss:223-244` |
| RC-1 | `concept_mappings.py`, `descriptions.py` | the two divergent copies deleted; both call sites delegate |
| RC-2 | `rules.py` | `descriptions_for_rule` added — the three admissible description types |
| RC-3 | `rules.py` | `_choose_description_for_rule` draws stochastically; the three fallbacks in `reference_object_to_object_description` deleted; `_object_description_possible` gates on rule-eligibility; `rng`/`temperature`/`meta` threaded from `instantiate_rule_clause_template` |
| RC-4 | `images.py` | `_constituent_images` breaks the width tie toward the group |
| RC-4 | `rules.py` | `apply_rule` raises `ImageFailure` where it used to skip |

Guarded by `tests/module/test_rule_object_descriptions.py` (8 test functions) and
`tests/module/test_singleton_group_images.py` (3), both in the numeric matrix so
each runs on the CPU and the GPU. Among them are the two that fail before the
fix: MetaCat's own three-clause rule applied to `eeqee` must generate `qeeq`, and
no built bottom rule may name an object the target does not have. `descriptions_for_rule`
is guarded in both directions — a successor group may *not* be named by its
letter-category, a same-group *may* — because testing against a node name that
does not exist in the Slipnet fails silently in the permissive direction, which is
how the `plato-samegrp` error survived into the measurement.

**RC-5**'s diagnostic has since been run. It is a reference-side regression, no
Petacat change is implied by it, and the five "after" figures it touches —
`eqe-baaab`, `fig5.4-top`, `run6`, `misc3`, `copy5` — are measured against an
oracle that carries it. See [RC-5](#rc-5--a-reference-side-regression-in-constituent-objects-of)
and [What RC-5 leaves to decide](#what-rc-5-leaves-to-decide).

### The expected-range fixture needs adjudication

`tests/module/test_expected_range.py` fails on three problems — `misc1`,
`eqe-baaab`, `run6` — on both backends. Every other layer is green: 508 unit, 448
seed_unit, 34 architecture, 910 module (non-slow), 62 integration, 209 e2e.

(A separate hazard when re-running the suite: `test_a_free_running_run_is_persisted_like_any_other`
aborts the interpreter intermittently under the default `mlx` backend —
`There is no Stream(gpu, 2) in current thread`, MLX's GPU streams meeting the
free-running worker threads. It reproduces on a clean checkout with these changes
stashed, and passes under `PETACAT_NUMERIC_BACKEND=numpy`, so it is unrelated to
this work — but it is what stops a full-suite session often enough to matter.)

The failures are the fixture recording the *old* engine, and they come in two
kinds. **Novel states**, warned about for adjudication, are overwhelmingly the
reference's own answers arriving for the first time — `misc1` now reaches
`jjjrrm` in 89 of 100 runs, the answer MetaCat gives 85.1% of the time and the
baseline had never once seen; `fig5.4-top` reaches `qeeq` (MetaCat 64.9%) and
`ixxi` (4.4%); `run6` reaches `qeeeq` (63.5%); `misc4` reaches `z` (36.7%) and
`y` (10.1%); `misc3` reaches `kkkjjjiii` (24.5%) and `kji` (16.6%). **Missing p50
states**, which fail hard, are three: `gave_up:` on `misc1` and `eqe-baaab`, and
`answer_found:qbebq` on `eqe-baaab` and `run6`. MetaCat gives up on `misc1` 0.0%
of the time and on `eqe-baaab` 0.5%, so no longer giving up on them is agreement
with the reference rather than a loss; `qbebq` is still reachable (1 run in 500)
but no longer frequent enough to appear in 100.

Rebuilding the fixture (`scripts/build_expected_range.py`) is therefore the
expected next step — but which states belong in a baseline is not a decision to
take while regenerating a file. The argument for admitting them is that they are
states the reference itself reaches; that argument is for the author to accept or
refuse.

**Resolved, 2026-08-06: the fixture was deleted rather than rebuilt**, and with
it `test_expected_range.py` and `test_splittable_rng_range.py`, which is the same
check under the splittable RNG.

Rebuilding would have re-made the underlying mistake. That fixture was 410,000
runs *of Petacat*, so it could detect drift but never divergence: an engine that
disagreed with MetaCat from the outset agreed with itself perfectly. Every
"novel state" listed above is an instance — they are the reference's own answers
arriving, read as anomalies because the baseline was Petacat's past behaviour.
The comparison now points at Metacat's published sets instead.

`tests/support/expected_range.py` survives, because `test_population.py` uses its
`default_run_one`; its baseline half is dead within the suite and still imported
by `scripts/measure_staleness.py`, which will fail against the deleted fixture
and needs a decision.

The MLX hazard noted above is unchanged and still avoided by running on `numpy`.

---

## Full distributions

Every state either sample produced, with raw counts. Ordered widest divergence
first, matching the table above.

### `abc → cba ; mrrjjj → ?` — misc1, TVD 0.59

Metacat n=40,836 (saturated) · Petacat n=500 · 18 distinct states in Metacat, 9 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `jjjrrm` | 85.1% | 28.4% | -56.7 | 34,736 | 142 |
| `mrrjjj` | 8.7% | 66.2% | +57.5 | 3,567 | 331 |
| `jrrjjm` | 2.5% | 1.6% | -0.9 | 1,040 | 8 |
| `jrrmmm` | 2.6% | 1.4% | -1.2 | 1,060 | 7 |
| `cba` | 0.1% | 1.0% | +0.9 | 41 | 5 |
| `jjrrjm` | 0.2% | 0.8% | +0.6 | 98 | 4 |
| `mmmrrj` | 0.5% | 0.2% | -0.3 | 193 | 1 |
| `crraaa` | 0.1% | 0.2% | +0.1 | 26 | 1 |
| `mrraaa` | 0.0% | 0.2% | +0.2 | 3 | 1 |

Below 0.2% and omitted: 12 further states in Metacat, 0 in Petacat.

#### Root cause and plan — RC-2, RC-3

**What happens.** Petacat answers with the target string unchanged in two runs
out of three. The rule it finds is right and the translation is right; the
translated rule then applies to `mrrjjj` as a **no-op**, because the object it
names is not there.

Traced on seed 3 — the bottom rule is
`intrinsic obj=(group GroupCtgy succgrp) [self:Direction→Opposite]`, and applying
it to `mrrjjj` yields zero transforms. The target's built groups at that moment
are `[rr]`, `[jjj]` and `[m]`, all three `samegrp`; no group in the string carries
`GroupCtgy: succgrp`, so `_get_reference_objects_for_clause` returns nothing,
`_get_intrinsic_transforms` returns nothing, and `apply_rule` returns an empty
transform list without complaint. The answer string is the target.

**Why.** `(group GroupCtgy succgrp)` is not an object-description the reference
can express (RC-2): `get-descriptions-for-rule` admits String-Position,
Alphabetic-Position, and Letter-Category on a letter or a same-group, and nothing
else. Across 60 Petacat runs of this problem, `group/GroupCtgy` is 36.3% of all
object-description resolutions and resolves to no object 68 times.

The reference names the same rule as **"Reverse direction of whole group"**
(`(group StrPosCtgy whole)`) or **"Reverse direction of string"**
(`(string StrPosCtgy whole)`) — 200 of its 300 bottom rules are the latter. A
`string` object-description resolves to the whole group *if one exists and to the
string otherwise* (`workspace-strings.ss:450-480`), so it can never fail to find
its object, which is why the reference reaches `jjjrrm` 85% of the time. Petacat
produced `string/StringPos` once in 60 runs.

**Plan.**

1. Add `descriptions_for_rule(obj)` to `server/engine/rules.py`, transcribing
   `workspace-objects.ss:260-268`: keep a relevant *and* distinguishing
   description whose type is String-Position or Alphabetic-Position, or
   Letter-Category when the object is a Letter or a group whose
   `group_category` is `plato-same-group`. Reject everything else.
2. Rewrite `_choose_description_for_rule` (`rules.py:2195`) to draw from that
   set with `rng.weighted_pick(candidates, temp_adjusted_values(depths, T, meta))`
   — the reference's `stochastic-pick`, not `max` (RC-3). Thread `rng`,
   `temperature` and `meta` down from `instantiate_rule_clause_template`
   (`rules.py:2226`), which already holds all three.
3. Delete the three fallbacks in `reference_object_to_object_description`
   (`rules.py:2182-2190`). The reference has none; step 4 is what makes them
   unnecessary.
4. Point `_object_description_possible` (`rules.py:3475`) at
   `descriptions_for_rule` instead of `len(descriptions) > 0`, matching
   `rules.ss:455-458`, so a template naming an undescribable object is refused
   at instantiation rather than patched over.
5. Regression-guard with a unit test asserting that no rule built on this problem
   carries a Group-Category, Length, Direction or Object-Category
   object-description, and a module test asserting that a bottom rule whose
   clause resolves to no object does not yield the target string.

**Measured effect.** Applying RC-1 through RC-4 to a live engine and re-sampling
500 seeds: `jjjrrm` 87.0% (reference 85.1%), `jrrjjm` 4.4% (2.5%), `mrrjjj` 3.6%
(8.7%), `jrrmmm` 2.0% (2.6%), `mmmrrj` 0.6% (0.5%). **TVD 0.63 → 0.07** on the
300-seed sweep. RC-2 and RC-3 carry essentially all of it: with those two alone
the TVD is 0.04 and `mrrjjj` sits at 7.5%, and adding RC-1's second half
(`Description.is_distinguishing`) slightly *overshoots*, pushing `mrrjjj` below
the reference's 8.7%. RC-1 is right on the merits and should still land, but this
problem is the one to re-measure after it does.

### `eeqee → qeeq ; xxixx → ?` — fig5.4-top, TVD 0.56

Metacat n=51,128 (checkpoint) · Petacat n=500 · 55 distinct states in Metacat, 6 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `qeeq` | 64.9% | 27.4% | -37.5 | 33,157 | 137 |
| `*NONE*` | 15.8% | 71.2% | +55.4 | 8,055 | 356 |
| `qxxi` | 5.6% | 0.4% | -5.2 | 2,857 | 2 |
| `ixxq` | 5.6% | 0.4% | -5.2 | 2,855 | 2 |
| `ixxi` | 4.4% | 0.0% | -4.4 | 2,269 | 0 |
| `qiq` | 1.5% | 0.0% | -1.5 | 770 | 0 |
| `xxiq` | 0.2% | 0.4% | +0.2 | 84 | 2 |
| `qeexq` | 0.5% | 0.0% | -0.5 | 231 | 0 |
| `qxeeq` | 0.4% | 0.0% | -0.4 | 226 | 0 |
| `qixx` | 0.1% | 0.2% | +0.1 | 69 | 1 |

Below 0.2% and omitted: 47 further states in Metacat, 0 in Petacat.

#### Root cause and plan — RC-4, then RC-2/RC-3, then RC-5

**What happens.** Petacat gives up on 71% of runs. It gives up because it almost
never builds a rule: across 150 runs the Trace records 52 `rule_built` events and
519 `clamp_start` events — three and a half clamps per run, none of them snags.
Rule codelets fail to find a rule, rule-codelet clamps recur, and the jootser
takes the `joots-from-rule-codelet-clamps` branch, which is an unconditional
`give-up` (`jootsing.ss:173-178`). *This is the reference's own machinery working
correctly on a program that cannot find a rule.*

**Why it cannot find a rule.** Two independent causes, in the order they bite.

*RC-4 is the larger.* The reference's rules for this problem are three-clause
intrinsic rules over the leftmost, middle and rightmost groups — "Change
letter-category of leftmost group to `q`, decrease length of leftmost group by
one, change letter-category of middle group to `e`, increase length of middle
group by one, …" — built in roughly half its runs. Petacat abstracts the same
rule, and then applies it wrongly. `eeqee` is `[ee] [q] [ee]`; the middle group is
a **singleton group** around `q`, so it ties with the letter `q` in
`_constituent_images`' positional partition (`images.py:997`), loses the tie to
the letter, and never receives an image. `apply_rule` skips it in silence, so
`eeqee` generates as `qqq` instead of `qeeq`, `currently_works` fails, and the
rule is never built. Measured: `currently_works` returned true **2 times out of
2,736** for three-clause rules on this problem.

*RC-2 and RC-3 come first in time.* Before RC-4 can even be reached, 72.1% of
this problem's object-description resolutions are `group/GroupCtgy`, and 3,417 of
those 3,451 resolve to **all three groups at once** — every group in `eeqee` is a
same-group. Three clauses each naming all three objects collide: 477
`Conflicting transforms` and 714 `Swap objects are not disjoint` failures across
60 runs.

**Plan.**

1. Land RC-2 and RC-3 as set out in the `abc → cba ; mrrjjj` block above. Measured
   with RC-1 through RC-3 but *without* RC-4, they lift `qeeq` from 27.4% to
   42.5% — but leave the give-up rate at 55%, barely moved from 71.2%. RC-2 and
   RC-3 are necessary and not sufficient here; step 2 is the one that matters.
2. Fix the tie in `StringImage._constituent_images` (`images.py:997`): at equal
   `right_string_pos`, prefer a group over a letter, and prefer an unenclosed
   group over an enclosed one. The reference's `get-top-level-objects`
   (`workspace-strings.ss:411-417`) selects on `enclosing_group is None` and has
   no tie to break; the positional partition exists here to survive
   `enclosing_group` bookkeeping that two competing groups can leave
   inconsistent, so keep the partition and fix only its ordering key.
3. Make `apply_rule` (`rules.py:2461-2469`) **fail** rather than skip when an
   object named by a clause has no image. A missing image is a structural
   inconsistency, not a licence to produce a different answer; raising
   `ImageFailure` routes it into the snag machinery the architecture already
   has, and turns a wrong answer into a recorded impasse.
4. Add a module test on `eeqee`: build the three groups, apply the reference's
   own three-clause rule, and assert the result is `qeeq`. That test fails today
   and is the tightest possible guard on RC-4.
5. RC-5 then becomes the remaining gap on this problem — see the
   `eqe → qeq ; abbba` block.

**Measured effect.** With RC-1 through RC-4 implemented (500 seeds): `qeeq` 51.0%
(reference 64.9%), `ixxi` 26.8% (4.4%), `*NONE*` 12.8% (15.8%), `ixxq` 4.0%
(5.6%), `qxxi` 3.6% (5.6%), `qiq` 0.6% (1.5%), `qxeeq` 0.6% (0.4%), `xxiq` 0.4%
(0.2%). **TVD 0.56 → 0.20.** The give-up rate lands near the reference's, and the
four states Petacat could not reach at all — `ixxi`, `qiq`, `qxeeq`, `qeexq` —
all appear. The residual is now almost entirely `ixxi` over-production, which is
RC-5 — and the RC-5 diagnostic confirms it: emulating the reference build's
`constituent-objects-of` at the extrinsic site takes this problem from 0.230 to
**0.042** with nothing else changed.

### `eqe → qeq ; abbbc → ?` — run6, TVD 0.50

Metacat n=51,128 (checkpoint) · Petacat n=500 · 87 distinct states in Metacat, 21 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `qeeeq` | 63.5% | 34.0% | -29.5 | 32,464 | 170 |
| `*NONE*` | 2.5% | 21.2% | +18.7 | 1,288 | 106 |
| `qeq` | 2.9% | 15.4% | +12.5 | 1,488 | 77 |
| `baaaq` | 7.6% | 4.0% | -3.6 | 3,892 | 20 |
| `qcccb` | 7.5% | 2.6% | -4.9 | 3,829 | 13 |
| `qbbbq` | 7.8% | 1.6% | -6.2 | 3,969 | 8 |
| `bbbaq` | 0.0% | 8.4% | +8.4 | 1 | 42 |
| `cbbba` | 4.6% | 1.6% | -3.0 | 2,337 | 8 |
| `qcbbb` | 0.0% | 5.8% | +5.8 | 2 | 29 |
| `baaab` | 0.2% | 1.0% | +0.8 | 113 | 5 |
| `qbbbc` | 0.8% | 0.4% | -0.4 | 398 | 2 |
| `abbbq` | 0.8% | 0.2% | -0.6 | 394 | 1 |
| `cddda` | 0.0% | 0.8% | +0.8 | 24 | 4 |
| `bcaab` | 0.1% | 0.6% | +0.5 | 28 | 3 |
| `cddbc` | 0.0% | 0.6% | +0.6 | 0 | 3 |
| `cdddb` | 0.0% | 0.6% | +0.6 | 0 | 3 |
| `aeeeq` | 0.0% | 0.4% | +0.4 | 0 | 2 |
| `qreeq` | 0.1% | 0.2% | +0.1 | 57 | 1 |
| `qeeqr` | 0.1% | 0.2% | +0.1 | 34 | 1 |
| `qrrrq` | 0.0% | 0.2% | +0.2 | 19 | 1 |
| `bcccb` | 0.2% | 0.0% | -0.2 | 113 | 0 |
| `cdccb` | 0.0% | 0.2% | +0.2 | 0 | 1 |

Below 0.2% and omitted: 76 further states in Metacat, 0 in Petacat.

#### Root cause and plan — RC-1

**What happens.** Three of the states Petacat reaches here are unreachable for
the reference — `bbbaq` at 8.4%, `qcbbb` at 5.8%, `cddbc` and `cdddb` — and they
are all *rearrangements* of the target rather than letter changes. `*NONE*` is
21.2% against 2.5%, and `qeq` (the modified string returned verbatim) is 15.4%
against 2.9%.

Traced on seeds 12 and 11, the rules that produce them are

```
seed 12  intrinsic (letter rmost)[LetterCtgy→q] || extrinsic (letter lmost),(group middle) dims=StringPos   →  bbbaq
seed 11  intrinsic (letter lmost)[LetterCtgy→q] || extrinsic (group middle),(letter rmost) dims=StringPos   →  qcbbb
```

The extrinsic clause swaps **string positions**. The reference's extrinsic clause
for this problem always swaps **letter-categories** — "Swap letter-categories of
leftmost letter and middle group" — which turns `abbbc` into `baaaq`, a state the
reference reaches 7.6% of the time and Petacat only 4.0%.

**Why.** A swap's dimension is the concept-mapping type of the slippages
underlying it (`rules.ss:758-788`, `slippages->swap`). A String-Position swap
therefore requires *crossing* horizontal-top bridges — the leftmost `e` of `eqe`
mapped to the middle `e` of `qeq`, and the middle `q` mapped to the leftmost `q`.

Measured over 60 runs, Petacat builds 42 such crossing bridges out of 172 built
top bridges: `lmost=>middle` 12, `middle=>rmost` 11, `middle=>lmost` 10,
`rmost=>middle` 9. The reference builds **zero** in 300 runs — every top bridge
it builds is `lmost=>lmost`, `middle=>middle` or `rmost=>rmost`.

The gate that stops it is `bottom-up-bridge-scout`'s requirement of at least one
distinguishing Identity/Opposite mapping (`bridges.ss:938-952`). The crossing
bridge's mappings are `letter=>letter` (Object-Category, never distinguishing),
`lmost=>middle` (unlabelled, so neither identity nor opposite), and `e=>e`
(identity, but **not distinguishing**, because the rightmost letter of `eqe` is
also an `e`). Under RC-1's inverted `distinguishing?` that last one reads as
distinguishing, the gate opens, and the crossing bridge is built. Petacat's
codelet source even carries the reference's comment explaining why the gate
exists; the predicate underneath it is what disagrees.

The elevated `*NONE*` and `qeq` follow from the same place: a Workspace full of
mutually incompatible crossing and non-crossing bridges is a Workspace where no
coherent rule settles, which is what drives runs into the rule-codelet clamp
pattern and into the 1%-per-scout verbatim rule as the only thing that works.

**Plan.**

1. Rewrite `ConceptMapping._descriptor_is_distinguishing`
   (`concept_mappings.py:216`) as a direct transcription of
   `workspace-objects.ss:223-244`: return `False` as soon as **any** sibling
   carries the descriptor. Keep the generic-category short-circuit
   (`plato-letter`, `plato-group`, the number nodes) as it is.
2. In the same rewrite, restore the reference's sibling set for a group: all
   other groups in the string **except** its enclosing group and its own
   constituent subgroups. Petacat currently excludes only the object itself.
3. Delete `Description.is_distinguishing` (`descriptions.py:197`) as an
   independent implementation and delegate it to the corrected predicate. The
   reference has one predicate; two copies is how they came to disagree, and the
   second copy is still ambiguity-producing after step 1 (`letter/LetterCtgy`
   resolved to 2 objects 200 times in a 60-run sample).
4. Regression-guard with a unit test on `eqe`: assert that `e` does *not*
   distinguish the leftmost letter and that `q` *does* distinguish the middle
   one; and a module test asserting no crossing horizontal-top bridge is built on
   `eqe → qeq`.

**Measured effect.** With RC-1 through RC-4 (500 seeds): `qeeeq` 59.4%
(reference 63.5%), `qbbbq` 7.6% (7.8%), `baaaq` 7.2% (7.6%), `*NONE*` 5.4%
(2.5%), `qcccb` 4.6% (7.5%), `cbbba` 4.4% (4.6%), `qeq` 3.0% (2.9%), `baaab` 2.0%
(0.2%). **TVD 0.50 → 0.13.** `bbbaq` and `qcbbb` are gone, `*NONE*` falls from
21.2% to 5.4%, and `qeq` from 15.4% to the reference's own 2.9%.

**RC-1 carries most of that on its own.** Measured separately (300 seeds, RC-1
only): **TVD 0.50 → 0.17**, with `qeeeq` at 57.0%, `*NONE*` at 9.7% and `qeq` at
5.7%, and both crossing-swap states absent. That is the evidence that the
elevated `*NONE*` and `qeq` on this problem really are downstream of the bridge
gate, and not an independent defect.

### `eqe → qeq ; abbba → ?` — eqe-baaab, TVD 0.47

Metacat n=51,128 (checkpoint) · Petacat n=500 · 61 distinct states in Metacat, 17 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `qeeeq` | 49.4% | 20.0% | -29.4 | 25,272 | 100 |
| `baaab` | 24.9% | 44.0% | +19.1 | 12,755 | 220 |
| `qeq` | 2.3% | 8.8% | +6.5 | 1,198 | 44 |
| `*NONE*` | 0.5% | 8.8% | +8.3 | 239 | 44 |
| `qbbbq` | 7.3% | 1.8% | -5.5 | 3,723 | 9 |
| `qabbb` | 0.0% | 7.6% | +7.6 | 0 | 38 |
| `baaaq` | 5.0% | 1.4% | -3.6 | 2,565 | 7 |
| `qaaab` | 5.0% | 0.8% | -4.2 | 2,540 | 4 |
| `abbba` | 3.3% | 1.0% | -2.3 | 1,698 | 5 |
| `bbbaq` | 0.0% | 3.6% | +3.6 | 0 | 18 |
| `abbbq` | 0.7% | 0.4% | -0.3 | 375 | 2 |
| `qbbba` | 0.7% | 0.2% | -0.5 | 361 | 1 |
| `baaaa` | 0.0% | 0.6% | +0.6 | 0 | 3 |
| `aaaab` | 0.0% | 0.4% | +0.4 | 0 | 2 |
| `aabbb` | 0.0% | 0.2% | +0.2 | 0 | 1 |
| `baaba` | 0.0% | 0.2% | +0.2 | 0 | 1 |
| `aaaaa` | 0.0% | 0.2% | +0.2 | 0 | 1 |

Below 0.2% and omitted: 51 further states in Metacat, 0 in Petacat.

#### Root cause and plan — RC-1, then RC-5

**What happens.** Two separable things. The states the reference never reaches —
`qabbb` 7.6%, `bbbaq` 3.6%, `baaaa`, `aaaab`, `aabbb`, `aaaaa`, `baaba` — are
RC-1, the same crossing-bridge String-Position swaps analysed in the
`eqe → qeq ; abbbc` block above; this is the same top pair. And the two dominant
answers are **rank-inverted**: the reference gives `qeeeq` 49.4% and `baaab`
24.9%, Petacat gives `baaab` 44.0% and `qeeeq` 20.0%.

The inversion survives RC-1 through RC-4 — it gets slightly worse — and it is
RC-5.

**Why the inversion.** `qeeeq` comes from the three-clause intrinsic rule
("change leftmost letter to `q`, middle letter to `e`, rightmost letter to `q`");
`baaab` comes from the three-way extrinsic swap ("swap letter-categories of
leftmost letter, middle letter and rightmost letter"). Both programs build both.
Measured over 120 runs each, with RC-1…RC-4 applied to Petacat:

| rule shape | reference | Petacat | quality |
|---|---:|---:|---:|
| three-clause intrinsic | 104 | 94 | 57 |
| extrinsic naming the three objects | 51 | 19 | 78 |
| extrinsic as a **subobjects swap** | **0** | **70** | **86** |

The quality formulas agree wherever both produce the same shape — the
three-clause rule is q=57 (u=100, a=50, s=67) on both sides, the object-naming
swap q=78 (u=100, a=77, s=80) on both. What Petacat additionally produces is the
*one-object* form of the swap: `ExtrinsicChangeDescription.mark_as_subobjects_swap_if_possible`
(`rules.py:651`) marks the swap as a swap of the enclosing object's components,
which collapses three object-descriptions to one. `compute-rule-succinctness`
(`rules.ss:1628-1637`) charges 2 for a multi-object extrinsic clause and 1 for a
single-object one, so succinctness goes 80 → 100 and quality 78 → 86. That makes
it the highest-quality rule in the Workspace, so the answer-finder takes it, and
`baaab` displaces `qeeeq`.

The marking condition itself reads identically on both sides — the swapped
objects must be set-equal to the enclosing object's constituents, where a letter
with no enclosing group takes the string as its enclosing object.

**The diagnostic below has been run, and the answer is none of the three
candidates it listed.** The reference marks the swap exactly as Petacat does; it
then cannot *apply* the clause, because the build the oracle was sampled from
answers a workspace-string's constituents with `'()`. The full account, with the
Scheme, is in
[RC-5](#rc-5--a-reference-side-regression-in-constituent-objects-of); what it
leaves open is [a decision, not a measurement](#what-rc-5-leaves-to-decide). The
plan is kept below as it stood, because step 2 is what was run.

**Plan.**

1. ~~Land RC-1 (see the `eqe → qeq ; abbbc` block). It removes `qabbb`, `bbbaq`
   and the five rare rearrangement states, and is a prerequisite for measuring
   RC-5 cleanly.~~ Done.
2. ~~**Settle RC-5 by direct comparison before changing anything.**~~ Done —
   Petacat side instrumented at `mark_as_subobjects_swap_if_possible`
   (`rules.py:651`), reference side read rather than run. Of the three candidate
   explanations listed here, none holds: `_get_constituent_objects` on a
   *WorkspaceString* **does** reproduce `get-top-level-objects`; the swap's
   reference-object set is the same three letters on both sides; and the 0.75
   gate fires at the same point. The divergence is one step further on, in
   `constituent-objects-of` (`utilities.ss:110-114`) at `rules.ss:1432` and
   `rules.ss:1540`.
   *Original text:* Instrument both programs at the same point: in the reference, print
   `subobjects-swap?`, the reference objects and
   `(tell (get-enclosing-object (1st reference-objects)) 'get-constituent-objects)`
   inside `mark-as-subobjects-swap-if-possible` (`rules.ss:987-991`); in Petacat,
   print the same three values in `mark_as_subobjects_swap_if_possible`
   (`rules.py:651`). Run both on `eqe → qeq ; abbba` over the same seed range.
   Three candidate explanations to discriminate, in order of likelihood:
   - `_get_constituent_objects` on a *WorkspaceString* does not reproduce
     `get-top-level-objects` (`workspace-strings.ss:411-417`) — the same
     top-level-object question as RC-4, which would make this RC-4's second head
     rather than a separate defect;
   - the reference's swap has a different reference-object set at this point
     (e.g. two objects rather than three), so set-equality legitimately fails;
   - the 0.75 `subobjects_abstraction_probability` gate is consuming its random
     draw at a different point in the stream.
3. Only then decide the fix. Do **not** reach for the succinctness formula: it is
   verified identical on both sides and is not where the divergence lives. What
   the diagnostic found puts the fix in the *reference*, not in Petacat, at the
   cost of re-sampling the oracle — which is the decision recorded under
   [What RC-5 leaves to decide](#what-rc-5-leaves-to-decide) and not yet taken.
4. Regression-guard once that decision is taken. Which direction the guard points
   depends on it: either that a rule clause naming the whole string denotes the
   string's top-level objects (Marshall's semantics, Petacat's today), or that it
   denotes nothing (the oracle's). Both are testable in one module test on `eqe`;
   only one of them is worth writing.

**Measured effect.** With RC-1 through RC-4 (500 seeds): `baaab` 51.8%
(reference 24.9%), `qeeeq` 27.8% (49.4%), `qbbbq` 6.4% (7.3%), `qaaab` 4.2%
(5.0%), `qeq` 3.8% (2.3%), `baaaq` 2.0% (5.0%), `abbba` 1.6% (3.3%). **TVD 0.45 →
0.32.** `qabbb` and `bbbaq` — 11.2% of runs between them, and unreachable for the
reference — are gone, and `*NONE*` falls from 8.8% to 0.2% against the
reference's 0.5%. But the `baaab`/`qeeeq` inversion is untouched, and it is now
essentially the whole of the residual. This is the one problem of the five where
the plan does not yet close the gap.

### `aabb → cc ; aabb → ?` — copy5, TVD 0.40

Metacat n=31,042 (saturated) · Petacat n=500 · 21 distinct states in Metacat, 3 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `*NONE*` | 48.4% | 74.6% | +26.2 | 15,025 | 373 |
| `cc` | 48.5% | 10.8% | -37.7 | 15,048 | 54 |
| `*CAP*` | 0.6% | 14.6% | +14.0 | 179 | 73 |
| `aabb` | 1.4% | 0.0% | -1.4 | 429 | 0 |
| `ccbb` | 0.3% | 0.0% | -0.3 | 103 | 0 |
| `ccc` | 0.3% | 0.0% | -0.3 | 79 | 0 |
| `a` | 0.2% | 0.0% | -0.2 | 71 | 0 |

Below 0.2% and omitted: 14 further states in Metacat, 0 in Petacat.

#### Root cause and plan — RC-2, RC-3

**What happens.** The reference splits almost evenly between `cc` (48.5%) and
giving up (48.4%). Petacat gives up on 74.6% and reaches `cc` on 10.8%, and
adds 14.6% of runs that hit the codelet ceiling — against the reference's 0.6%
at a ceiling five times higher.

This is the same failure as `eeqee → qeeq` and it is the most extreme instance of
it: **91.3%** of this problem's object-description resolutions are
`group/GroupCtgy`, and 42,120 of those 48,824 resolve to two or three objects at
once. `aabb` is `[aa] [bb]`, and the target is the same string again, so every
group in sight is a same-group and `(group GroupCtgy samegrp)` names all of them.
Three clauses each naming every group collide on contact: **19,352 `Conflicting
transforms` failures across 60 runs — 322 per run.** No rule survives
`currently_works`, rule-codelet clamps recur, and the jootser gives up. (Whether
the 14.6% that reach the ceiling instead are runs whose clamp pattern never
reaches the jootser's three-clamp threshold is not established here — but they
vanish once the rule can be built, which is consistent with it.)

The reference's rule for this problem is "**Change all objects in whole group to
the letter `c`**" — a `(group StrPosCtgy whole)` object-description with a
`subobjects` change — in 98 of its 300 top rules and 104 of its bottom rules. It
is unambiguous by construction: exactly one group in `aabb` is `whole`.

**Plan.** RC-2 and RC-3, exactly as set out in the `abc → cba ; mrrjjj` block —
no work is specific to this problem. Two things to check while landing them,
because this problem is where they show up:

1. `group/AlphaPos` resolves to 2 objects 2,676 times here. Alphabetic-Position
   *is* a legal rule description type in the reference, so ambiguity there is not
   in itself a defect — but confirm against
   `workspace-strings.ss:468-480` that Petacat's `_find_matching_objects`
   applies the reference's tie-break (lowest-level object, preferring those
   carrying a vertical bridge) only to String-Position, as the reference does,
   and returns all candidates otherwise.
2. This problem is the natural regression test for RC-2: assert that a run of
   `aabb → cc ; aabb` produces zero `Conflicting transforms` failures arising
   from an object-description that resolved to more than one object.

**Measured effect.** With RC-1 through RC-4 implemented (500 seeds): `*NONE*`
65.6% (reference 48.4%), `cc` 31.8% (48.5%), `ccc` 0.4% (0.3%), plus five further
states below 1%. **TVD 0.39 → 0.18.** The `*CAP*` runs disappear entirely — 14.6%
→ 0.0% against the reference's 0.6% — because a run now either finds the rule or
reaches the give-up threshold instead of grinding against the ceiling.

What is left is a give-up rate 17 points above the reference's. This problem is
also the one that moved *backwards* when the `plato-samegrp` naming error was
corrected (0.12 → 0.18), which is a pointer rather than a puzzle: admitting
Letter-Category for a same-group gives `[aa]` and `[bb]` a second name to be
called by, and `aabb`'s rules are `subobjects` changes over the whole group —
the same abstraction RC-5 lives in. Re-measure after RC-5 is settled.

### `a → b ; z → ?` — misc4, TVD 0.36

Metacat n=11,454 (no_singletons) · Petacat n=500 · 4 distinct states in Metacat, 4 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `b` | 49.9% | 63.4% | +13.5 | 5,718 | 317 |
| `y` | 10.1% | 30.4% | +20.3 | 1,162 | 152 |
| `z` | 36.7% | 0.4% | -36.3 | 4,207 | 2 |
| `*NONE*` | 3.2% | 5.8% | +2.6 | 367 | 29 |

### `rst → rsu ; xyz → ?` — run3, TVD 0.28

Metacat n=13,778 (saturated) · Petacat n=500 · 11 distinct states in Metacat, 8 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `xyu` | 38.0% | 43.6% | +5.6 | 5,242 | 218 |
| `*NONE*` | 11.4% | 32.2% | +20.8 | 1,569 | 161 |
| `wyz` | 19.7% | 12.6% | -7.1 | 2,715 | 63 |
| `xyz` | 17.1% | 0.0% | -17.1 | 2,352 | 0 |
| `uyz` | 5.6% | 4.6% | -1.0 | 766 | 23 |
| `yyz` | 5.4% | 3.0% | -2.4 | 740 | 15 |
| `rsu` | 2.7% | 2.8% | +0.1 | 377 | 14 |
| `*CAP*` | 0.0% | 1.0% | +1.0 | 0 | 5 |
| `wxz` | 0.1% | 0.2% | +0.1 | 7 | 1 |

Below 0.2% and omitted: 4 further states in Metacat, 0 in Petacat.

### `abc → abd ; xyz → ?` — run4, TVD 0.27

Metacat n=11,122 (saturated) · Petacat n=500 · 10 distinct states in Metacat, 7 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `xyd` | 36.8% | 36.0% | -0.8 | 4,089 | 180 |
| `*NONE*` | 9.7% | 35.0% | +25.3 | 1,083 | 175 |
| `wyz` | 21.4% | 17.6% | -3.8 | 2,380 | 88 |
| `xyz` | 16.3% | 0.0% | -16.3 | 1,813 | 0 |
| `yyz` | 7.2% | 5.0% | -2.2 | 806 | 25 |
| `dyz` | 6.0% | 2.6% | -3.4 | 665 | 13 |
| `abd` | 2.4% | 2.4% | -0.0 | 269 | 12 |
| `*CAP*` | 0.0% | 1.4% | +1.4 | 0 | 7 |

Below 0.2% and omitted: 3 further states in Metacat, 0 in Petacat.

### `aabc → aabd ; ijkk → ?` — fig5.7, TVD 0.24

Metacat n=14,608 (saturated) · Petacat n=500 · 18 distinct states in Metacat, 11 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `ijkl` | 35.5% | 50.4% | +14.9 | 5,183 | 252 |
| `ijll` | 46.5% | 32.2% | -14.3 | 6,795 | 161 |
| `ijl` | 8.9% | 0.8% | -8.1 | 1,296 | 4 |
| `jjkk` | 2.1% | 3.8% | +1.7 | 308 | 19 |
| `*CAP*` | 0.0% | 4.6% | +4.6 | 0 | 23 |
| `hjkk` | 1.7% | 2.6% | +0.9 | 247 | 13 |
| `ijkk` | 2.1% | 1.2% | -0.9 | 304 | 6 |
| `aabd` | 0.5% | 1.8% | +1.3 | 68 | 9 |
| `ijkd` | 0.8% | 1.4% | +0.6 | 121 | 7 |
| `ijdd` | 1.2% | 0.8% | -0.4 | 168 | 4 |
| `*NONE*` | 0.0% | 0.4% | +0.4 | 1 | 2 |
| `ijkkk` | 0.3% | 0.0% | -0.3 | 49 | 0 |

Below 0.2% and omitted: 8 further states in Metacat, 0 in Petacat.

### `abc → abd ; glz → ?` — misc5, TVD 0.20

Metacat n=11,288 (saturated) · Petacat n=500 · 8 distinct states in Metacat, 8 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `gld` | 26.0% | 30.4% | +4.4 | 2,930 | 152 |
| `hlz` | 21.9% | 26.6% | +4.7 | 2,468 | 133 |
| `flz` | 16.6% | 17.2% | +0.6 | 1,879 | 86 |
| `glz` | 20.1% | 1.0% | -19.1 | 2,273 | 5 |
| `*NONE*` | 5.2% | 13.4% | +8.2 | 582 | 67 |
| `dlz` | 8.4% | 8.8% | +0.4 | 943 | 44 |
| `abd` | 1.9% | 1.2% | -0.7 | 212 | 6 |
| `*CAP*` | 0.0% | 1.4% | +1.4 | 1 | 7 |

Below 0.2% and omitted: 1 further states in Metacat, 0 in Petacat.

### `abc → aabbcc ; kkjjii → ?` — misc3, TVD 0.19

Metacat n=1,660 (shards_exited) · Petacat n=500 · 36 distinct states in Metacat, 27 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `kkjjii` | 34.0% | 37.8% | +3.8 | 564 | 189 |
| `kkkjjjiii` | 24.5% | 19.8% | -4.7 | 407 | 99 |
| `*CAP*` | 10.6% | 17.2% | +6.6 | 176 | 86 |
| `kji` | 16.6% | 6.6% | -10.0 | 275 | 33 |
| `*NONE*` | 0.5% | 4.2% | +3.7 | 8 | 21 |
| `kkjjjiii` | 2.0% | 1.6% | -0.4 | 34 | 8 |
| `kkkjjiii` | 1.1% | 2.4% | +1.3 | 19 | 12 |
| `aabbcc` | 1.9% | 0.8% | -1.1 | 31 | 4 |
| `kkkjjjii` | 0.9% | 1.4% | +0.5 | 15 | 7 |
| `kkjjiii` | 1.5% | 0.6% | -0.9 | 25 | 3 |
| `kjiii` | 0.5% | 1.0% | +0.5 | 9 | 5 |
| `kjjji` | 0.2% | 1.0% | +0.8 | 4 | 5 |
| `kkkji` | 0.5% | 0.6% | +0.1 | 9 | 3 |
| `kkkjiii` | 0.5% | 0.6% | +0.1 | 8 | 3 |
| `kkkjjji` | 0.5% | 0.6% | +0.1 | 8 | 3 |
| `kkjjjii` | 0.4% | 0.6% | +0.2 | 7 | 3 |
| `kkkjji` | 0.3% | 0.6% | +0.3 | 5 | 3 |
| `kkkjjii` | 0.4% | 0.4% | -0.0 | 7 | 2 |
| `kkjjji` | 0.3% | 0.4% | +0.1 | 5 | 2 |
| `kjjjiii` | 0.5% | 0.2% | -0.3 | 8 | 1 |
| `kkji` | 0.1% | 0.4% | +0.3 | 2 | 2 |
| `kjii` | 0.3% | 0.2% | -0.1 | 5 | 1 |
| `kkjjjiiiii` | 0.2% | 0.2% | -0.0 | 4 | 1 |
| `kkkjjiihh` | 0.2% | 0.2% | +0.0 | 3 | 1 |
| `kkkkjjiii` | 0.3% | 0.0% | -0.3 | 5 | 0 |
| `kkkjii` | 0.1% | 0.2% | +0.1 | 1 | 1 |
| `kkjiii` | 0.1% | 0.2% | +0.1 | 1 | 1 |
| `kkjii` | 0.0% | 0.2% | +0.2 | 0 | 1 |

Below 0.2% and omitted: 13 further states in Metacat, 0 in Petacat.

### `abc → abd ; mrrjjj → ?` — run1, TVD 0.06

Metacat n=11,122 (no_singletons) · Petacat n=500 · 11 distinct states in Metacat, 9 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `mrrkkk` | 63.9% | 62.2% | -1.7 | 7,106 | 311 |
| `mrrjjk` | 22.1% | 26.2% | +4.1 | 2,457 | 131 |
| `mrrjjjj` | 4.0% | 5.2% | +1.2 | 443 | 26 |
| `mrrddd` | 2.2% | 2.4% | +0.2 | 249 | 12 |
| `mrrjkk` | 2.2% | 2.2% | +0.0 | 244 | 11 |
| `mrrjjj` | 3.3% | 0.6% | -2.7 | 372 | 3 |
| `abd` | 1.3% | 0.2% | -1.1 | 141 | 1 |
| `mrrjjd` | 0.8% | 0.4% | -0.4 | 89 | 2 |
| `*CAP*` | 0.0% | 0.6% | +0.6 | 0 | 3 |

Below 0.2% and omitted: 3 further states in Metacat, 0 in Petacat.

### `xqc → xqd ; mrrjjj → ?` — run2, TVD 0.04

Metacat n=11,454 (saturated) · Petacat n=500 · 10 distinct states in Metacat, 7 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `mrrkkk` | 68.6% | 71.8% | +3.2 | 7,858 | 359 |
| `mrrjjk` | 21.3% | 21.0% | -0.3 | 2,442 | 105 |
| `mrrjkk` | 3.0% | 3.2% | +0.2 | 345 | 16 |
| `mrrddd` | 2.7% | 3.0% | +0.3 | 309 | 15 |
| `mrrjjj` | 3.0% | 0.2% | -2.8 | 347 | 1 |
| `mrrjjd` | 0.9% | 0.4% | -0.5 | 102 | 2 |
| `xqd` | 0.3% | 0.4% | +0.1 | 33 | 2 |

Below 0.2% and omitted: 3 further states in Metacat, 0 in Petacat.

### `abc → d ; abc → ?` — copy6, TVD 0.03

Metacat n=10,292 (saturated) · Petacat n=500 · 4 distinct states in Metacat, 5 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `d` | 86.7% | 87.6% | +0.9 | 8,927 | 438 |
| `abc` | 13.2% | 10.6% | -2.6 | 1,359 | 53 |
| `*NONE*` | 0.0% | 1.2% | +1.2 | 1 | 6 |
| `ad` | 0.0% | 0.4% | +0.4 | 0 | 2 |
| `dc` | 0.0% | 0.2% | +0.2 | 5 | 1 |

Below 0.2% and omitted: 2 further states in Metacat, 0 in Petacat.

### `abc → abd ; ijk → ?` — misc2, TVD 0.03

Metacat n=11,454 (saturated) · Petacat n=500 · 6 distinct states in Metacat, 4 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `ijl` | 95.3% | 95.8% | +0.5 | 10,918 | 479 |
| `ijd` | 2.0% | 3.6% | +1.6 | 232 | 18 |
| `ijk` | 2.0% | 0.0% | -2.0 | 232 | 0 |
| `abd` | 0.5% | 0.0% | -0.5 | 62 | 0 |
| `*CAP*` | 0.0% | 0.4% | +0.4 | 0 | 2 |
| `ikl` | 0.1% | 0.2% | +0.1 | 7 | 1 |

Below 0.2% and omitted: 2 further states in Metacat, 0 in Petacat.

### `xy → z ; xy → ?` — copy3, TVD 0.01

Metacat n=11,288 (no_singletons) · Petacat n=500 · 1 distinct states in Metacat, 3 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `z` | 100.0% | 98.6% | -1.4 | 11,288 | 493 |
| `*NONE*` | 0.0% | 1.0% | +1.0 | 0 | 5 |
| `xy` | 0.0% | 0.4% | +0.4 | 0 | 2 |

### `zy → x ; zy → ?` — copy4, TVD 0.01

Metacat n=11,288 (no_singletons) · Petacat n=500 · 2 distinct states in Metacat, 3 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `x` | 86.1% | 84.8% | -1.3 | 9,721 | 424 |
| `zy` | 13.9% | 13.8% | -0.1 | 1,567 | 69 |
| `*NONE*` | 0.0% | 1.4% | +1.4 | 0 | 7 |

### `ab → c ; ab → ?` — copy1, TVD 0.01

Metacat n=10,956 (no_singletons) · Petacat n=500 · 2 distinct states in Metacat, 3 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `c` | 86.6% | 85.2% | -1.4 | 9,484 | 426 |
| `ab` | 13.4% | 14.0% | +0.6 | 1,472 | 70 |
| `*NONE*` | 0.0% | 0.8% | +0.8 | 0 | 4 |

### `bc → d ; bc → ?` — copy2, TVD 0.01

Metacat n=11,454 (no_singletons) · Petacat n=500 · 1 distinct states in Metacat, 3 in Petacat

| state | Metacat | Petacat | difference | Metacat count | Petacat count |
|---|---:|---:|---:|---:|---:|
| `d` | 100.0% | 99.4% | -0.6 | 11,454 | 497 |
| `*NONE*` | 0.0% | 0.4% | +0.4 | 0 | 2 |
| `bc` | 0.0% | 0.2% | +0.2 | 0 | 1 |


---

## The comparison changed

Everything above compares two *distributions* by total-variation distance. That
is no longer how Petacat is measured, for two reasons the work above exposed.

TVD needs both sides sampled densely, and Petacat is not going to be. It runs
100 tries per problem and compares against sets Metacat published; it never
generates oracle data of its own. At n=100 a TVD estimate is dominated by
small-sample bias that scales with the number of states — measured null bands
ran from 0.00 to 0.20 across the 19 problems, tracking state count rather than
behaviour, so a single threshold could not work and a per-problem one would be
calibrating noise.

And TVD answers the wrong question. Metacat is stochastic and self-watching with
no ground truth; there is no right answer to `abc → cba ; mrrjjj`. A distance
invites a pass/fail reading of something that has neither.

**What replaced it.** Two set comparisons, in each of two modes, every one of
which *flags* rather than fails:

| | |
|---|---|
| MISSING | a p50 member of the reference set that Petacat did not produce |
| NOVEL | something Petacat produced that the reference never did |

  *single* — 100 runs from a fresh Episodic Memory, against the single-run sets.
  *episodic* — 100 episodes of 8 runs with memory carried forward, against the
  convergence sets. An episode's convergence answer is its last run that produced
  an answer; `*NONE*` and `*CAP*` are skipped looking backwards.

The episodic mode is new, and it exists because memory is the one thing that
survives `init-mcat`. It is what makes a session more than eight independent
runs: `answers.ss:982` refuses to report an answer already stored, so a session
is pushed toward novelty. That is also why five reference bugs hid there for
374,500 single runs.

The two flags are not equally strong, and the reference publishes the numbers to
weigh them. A missing p50 member has a **0.0000** false-alarm rate at n=100 on
every problem, so it is decisive. A novel member is only as strong as the
reference set's saturation: `f1/n ≤ 1e-4` on the single-run sets, but the
convergence sets are deliberately left unsaturated, at up to 0.0160, because
novel convergence answers are a signal the research programme wants rather than
noise to be sampled away. About eight novel convergence answers per 100-episode
cycle across the 19 problems are expected from a *correct* port.

Protocol: `../Metacat/ORACLE-USAGE.md`. Harness: `scripts/compare_to_metacat.py`.

## Where things actually stand

Measured 2026-08-06, numpy backend, 20,000-codelet cap, seeds from 900,000, all
19 problems. Full results in `measurements/vs-metacat.json`.

**No p50 member is missing anywhere — 0 across all 19 problems in both modes.**
That is the decisive check, and it is completely clean. Every dominant behaviour
the reference exhibits, Petacat reaches.

**Two novel answers are reproducible**, appearing in both modes:

| problem | answer | single runs | episodes | reference |
|---|---|---:|---:|---|
| `eqe-baaab` | `abbbb` | 1 of 100 | **7 of 100** | absent from 51,000 runs |
| `run6` | `cdddb` | 1 of 100 | **5 of 100** | absent from 47,500 runs |

Everything else is a singleton, consistent with the convergence sets' expected
rate. In single runs, 5 novel members against an expected ~0.2 is above noise,
but three are singletons and `run1`'s `*CAP*` is most likely this cap against the
reference's 100,000 rather than a divergence — worth re-running at 100,000 to
remove the confound before reading anything into it.

`cdddb` is not new to this document: the pre-repair table for `run6` lists it as
a Petacat-only state at 0.6%. It survived RC-1 through RC-4 and the oracle
re-sample. Those two answers are the only findings the current data supports
pursuing.

### Engine changes since the oracle re-run

Three, all tracking Metacat's `ca8f7e0` and `bf06847`, committed as `e76cae8`:

1. `WorkspaceString` gains the five methods a snag object needs. Four were
   already correct *incidentally* — `getattr(..., None)` and a `hasattr` — which
   is one refactor from the same defect the reference had.
2. `equivalent_workspace_objects` compared two strings on type and text length
   alone. The repaired reference also compares constituent count and recurses, so
   `mrrjjj` read as three groups was equivalent to `mrrjjj` read as six letters.
3. A string's constituents were returned unsorted where
   `workspace-strings.ss:427` sorts by position — `[1, 3, 0]` on
   `abc → abd ; mrrjjj` seed 1. Swaps pair denoted objects with descriptors
   positionally, so order changes the answer. Latent until `bf06847` made the
   string path reachable.

None of the three moved the measurement: re-running on identical seeds gave
byte-identical results. They are correctness fixes, not distribution fixes.

**Suite:** 1,398 passed, 12 skipped, 0 failed across unit, seed_unit, module and
architecture on `numpy`. Not covered: e2e and integration need a Postgres
instance; the GPU half of the matrix needs MLX, avoided for the interpreter
abort recorded above.
