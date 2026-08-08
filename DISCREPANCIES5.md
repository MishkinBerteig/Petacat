# DISCREPANCIES5 — where Petacat's source and Metacat's source say different things

**What this is.** A comparison of Petacat's Python against Metacat's Scheme, function by
function, looking for anything that could make the two compute differently. It is a
*static* comparison. Every entry names a Petacat site, the Metacat site it corresponds
to, and what diverges.

**What this is not.** It is not a measurement. `DISCREPANCIES.md` through
`DISCREPANCIES4.md` record variations found by *running* Petacat against Metacat's
published reference sets; those documents start from an observed difference and look for
a cause. This one starts from the source and looks for differences that a run might or
might not reveal. Nothing here was found by sampling, and nothing here is claimed to
have been observed in a run unless the entry says so.

**Nothing here is fixed.** This is a catalogue.

## On "inert"

Several entries below describe a divergence that appears to be unreachable — a branch
whose guard seems never to hold, a value that seems always to be zero where it is used.
**Those observations are recorded as conditional, and none of them downgrades an entry.**

The reason is that inertness cannot be established here. Metacat is late-bound Scheme:
`round`, `floor` and `ceiling` are *redefined* at `utilities.ss:243-252` after being
captured, generic arithmetic silently crosses between exact rationals and flonums, and
`tell`-based dispatch resolves at call time. Static analysis cannot see through that, and
statistical sampling can only ever fail to reach a branch — it cannot show the branch is
unreachable. So the standard applied throughout is: **Petacat should replicate what the
Scheme does, and carry a comment saying the branch may be unreachable, rather than
replicate a simplification that assumes it is.** An entry marked "may be unreachable" is
still a discrepancy to close.

## Method, and one caution about it

Five independent passes over the Scheme, split by subsystem: Slipnet and the shared
formulas; the Coderack and the structure codelets; rules, answers and memory; the
self-watching layer; and the constants and random primitives. Findings were checked
against the Scheme text and, where possible, by running both readings.

**Two of the five passes reached opposite conclusions on entry A-1**, the most
consequential item in the document. One read `(round (sqrt 2))` as a flonum and concluded
Petacat was correct; the other found the shadowing at `utilities.ss:250-252` and concluded
it was not. The shadowing is real, and the second reading is the one recorded here — but
the disagreement is worth stating, because it is a fair measure of how easy this
comparison is to get wrong in either direction. Entries marked *needs-checking* below
have not had that treatment and should be assumed no more reliable than a single reading.

---

# A. The random stream

Metacat and Petacat use different generators, so no seeded run can be compared
step-for-step regardless. What matters in this section is whether the two consume the
same *number* of draws in the same order — because when they do not, the divergence is
not a different sample from the same distribution but a different distribution.

## A-1. `~ 2` draws a continuous delta where Metacat draws an integer

**Severity: high — this changes how many scouts enter the rack, from the first cycle.**

**Petacat** — `server/engine/rng.py:102-111`:
```python
root = math.isqrt(int(n)) if float(n).is_integer() else -1
if root >= 0 and root * root == int(n):
    delta: float = self.randint(1 + root)                    # (~ 4)
else:
    delta = self.random() * (1 + round(math.sqrt(abs(n))))   # (~ 2)
```

**Metacat** — `utilities.ss:468-471`:
```scheme
(define ~
  (lambda (n)
    (let ((delta (random (add1 (round (sqrt n))))))
      (if (prob? 0.5) (+ n delta) (- n delta)))))
```

**The difference.** Petacat branches on whether `n` is a perfect square, on the reasoning
that `(round (sqrt 2))` is the flonum `1.0` and `(random 2.0)` is therefore continuous.
That reasoning fails on `utilities.ss:250-252`, which shadows `round`:

```scheme
(define scheme-round round)
(define round
  (lambda (n) (inexact->exact (scheme-round n))))
```

`round` is redefined to return an **exact** integer, 218 lines before `~` is defined. So
`(round (sqrt 2))` is the exact `1`, `(add1 …)` is the exact `2`, and `(random 2)` on an
exact argument returns an exact integer in `{0, 1}`. `(~ 2)` takes values in `{1, 2, 3}`
at ¼ / ½ / ¼. There is no continuous branch in the reference at all.

**When it bites.** `perturb`'s only consumer is `rough_num_of_objects`
(`workspace.py:1774-1776`), whose answer sets the scout count for the three scout
families (`coderack.ss:527-539`): bond scouts 2/4/6, group scouts 1/2/3, bridge scouts
2/5/6. Measured, 200,000 draws per count:

| unrelated objects | Metacat few / some / many | Petacat few / some / many |
|---:|---|---|
| 0 | 1.000 / 0.000 / 0.000 | 1.000 / 0.000 / 0.000 |
| 1 | 0.750 / 0.250 / 0.000 | 0.750 / 0.250 / 0.000 |
| **2** | **0.249 / 0.625 / 0.126** | **0.499 / 0.418 / 0.083** |
| **3** | **0.000 / 0.667 / 0.333** | **0.250 / 0.500 / 0.250** |
| 4 | 0.000 / 0.333 / 0.667 | 0.000 / 0.333 / 0.667 |
| 5 | 0.000 / 0.167 / 0.833 | 0.000 / 0.167 / 0.833 |

At two unrelated objects Petacat says "few" twice as often. At three, Metacat says "few"
**never** and Petacat says it a quarter of the time. Small strings early in a run sit in
exactly that band, so this under-drives bond, group and bridge scouting precisely when
structure is being seeded.

**The fix is already in the repository.** `SplittableRNG.perturb`
(`splittable_rng.py:182-186`) takes the integer branch unconditionally:
```python
delta = self.randint(1 + round(math.sqrt(abs(n))))
```
which is what the Scheme does, for both `(~ 2)` and `(~ 4)`. The two classes disagree with
each other, and `RNG` is the wrong one. (A separate audit pass reached the opposite
conclusion — that `SplittableRNG` was the defective one — for want of the shadowing.)

**Confidence: certain.** The shadowing is quoted above; the distributions are measured.

## A-2. `stochastic-if*` always draws; `prob()` short-circuits

**Severity: medium — outcome-identical, stream-divergent, and very frequent.**

**Metacat** — `syntactic-sugar.ss:121-126`:
```scheme
(let ((coin-flip (random 1.0)))
  (if (< coin-flip (prob-thunk)) (exps-thunk) (void)))
```
The draw is bound before the probability is tested, so it happens whatever the
probability turns out to be. This is a *different primitive* from `prob?`
(`utilities.ss:461-466`), which does short-circuit — and Petacat's `RNG.prob`
(`rng.py:47-53`) is a faithful port of `prob?`, used at every site the Scheme writes as
`stochastic-if*`.

**The difference is draw count only.** `(random 1.0)` lies in `[0,1)`, so `< 1` is always
true and `< 0` always false: the *decision* is identical at both ends. What differs is
that Petacat does not consume the number.

**When it bites.** Constantly. `post-codelet-probability` (`coderack.ss:465-513`) returns
exactly 1 for `rule-scout` whenever a rule type is possible and for `progress-watcher`
under thematic pressure, and exactly 0 for `answer-finder` before a supported top rule
exists, for `answer-justifier` outside justify mode, for `thematic-bridge-scout` with no
active theme, and for all three self-watching types when self-watching is off.
`average_intra_string_unhappiness` is pinned at 100 — probability exactly 1 — for every
string until the first bond is built. Measured on `abc → abd; xyz`, seed 42: **29 skipped
draws in the first 8 update cycles**, plus 8 more from condition-skipped rules.

Petacat additionally skips the *whole* posting evaluation for a rule whose `condition` is
false (`runner.py:1123`), where the reference reaches `stochastic-if*` and draws.

**Confidence: certain** on the mechanism and the counts.

## A-3. `_pick_neighbor` returns a lone candidate without drawing

**Severity: medium — the single highest-volume skipped draw.**

**Petacat** — `workspace_objects.py:199-208` returns `neighbors[0]` when there is one
candidate, with a docstring arguing that "the draw cannot change the answer".

**Metacat** — `stochastic-pick` (`utilities.ss:485-490`) draws in both branches: a
`(random (exact->inexact weight-sum))` when the weight is non-zero, and `random-pick`'s
`(random (length l))` when it is zero. A one-element list still costs one draw.

**The difference.** The docstring is true about the element returned and false about the
stream. Measured on `abc → abd; mrrjjj`, seed 7, to answer at 871 codelets: **1,612 calls,
662 of them short-circuited** — 41%. The local-density walk runs inside every
`update_strength`, including the two inside every `wins-fight?`, and in a string with no
groups every edge letter offers exactly one neighbour on the walked side.

**Confidence: certain** (measured).

## A-4. `stochastic-if*` used as a survival test inverts the sense of the coin

**Severity: medium for trajectory work, nil for distribution.**

**Metacat** — `bonds.ss:343`, `descriptions.ss:149`, `bridges.ss:1166`, `groups.ss:600`,
`breakers.ss:22`, `jootsing.ss:76`:
```scheme
(stochastic-if* (1- (temp-adjusted-probability (% strength))) ... (fizzle))
```
which fizzles iff `coin < 1 − p`, i.e. **survives iff `coin ≥ 1 − p`**.

**Petacat** — `builtins.py:752-756`, `builtins.py:505`, `jootsing.py:377`, and the
`breaker` body: survives iff `coin < p`.

**The difference.** Same survival *probability*, complementary halves of the same draw.
For `p = 0.9` and `coin = 0.05` the reference fizzles and Petacat survives.

Distributionally this is nothing. It matters only if trajectory comparison against the
reference is ever wanted, and in that case it is a blocker at the first evaluator.

**Confidence: certain.**

## A-5. Smaller skipped or transposed draws

| | Petacat | Metacat | Note |
|---|---|---|---|
| Empty concept-mapping list | `codelet_types.json` bridge scouts fizzle before the gate | `bridges.ss:924-937` — `(product '())` is 1, so `stochastic-if*` draws, then fizzles | one draw |
| `num_bonds_to_scan`, `n < 2` | `builtins.py:527-531` returns 0 | `workspace-strings.ss:56-59` — all-zero weights fall to `random-pick`, one draw | one draw, one-letter strings |
| Singleton-group gate | `codelet_types.json` evaluates the probability, then draws | `groups.ss:479-481` — `stochastic-if*` binds the coin *first*, and the probability expression itself walks the density (drawing) | draws transposed |
| Answer-finder all-zero weights | extra `if not any(weights): fizzle()` | `answers.ss:943-945` — `stochastic-pick` falls to `random-pick` and proceeds | extra branch, one draw; reachability unclear |
| Sharded coderack | `coderack_shards.py:502` adds a shard-selection `weighted_pick` | `coderack.ss:417-424` — one pick over bins | free-running only |

---

# B. Arithmetic and distribution

## B-1. Activation spreading divides before multiplying

**Severity: medium — off by one on the network's busiest links, every cycle.**

**Petacat** — `slipnet.py:397`:
```python
amount = round(scale * (assoc / 100.0) * self.activation)
```

**Metacat** — `slipnet.ss:181-186`: `(round (* (/ %update-cycle-length% 15) (% association) activation))`,
where `%` is exact rational division (`utilities.ss:546`) and `round` is the shadowed
exact one, so the rounding is applied to an exact rational.

**The difference.** Metacat computes `round(assoc·act/100)` exactly; Petacat rounds a
float product. Over all integer `(assoc, activation)` pairs in `[0,100]²` the two disagree
on 5 pairs; restricted to the 13 association values the shipped 202 links can produce,
**two** remain, both at `assoc = 70`:

```
act 45, assoc 70 → Petacat 31, Metacat round(31.5) = 32
act 85, assoc 70 → Petacat 59, Metacat round(59.5) = 60
```

`assoc = 70` is 18 of the 202 links, and they are the most-traversed: every
instance→category link, plus `sameness→samegrp`.

Note the asymmetry — `compute_rate_of_decay` (`slipnet.py:245-280`) carries a docstring
explaining exactly this hazard and stores `100 − depth` so the decay arithmetic stays
exact. The decay path has **zero** disagreements over all 10,201 pairs. The spread path
did not get the same treatment. `round(scale * assoc * activation / 100.0)` would fix it.

**Confidence: certain** (both sides computed).

## B-2. The Themespace materialises every possible theme

**Severity: high — two separate effects, both structural.**

**Petacat** — `themes.py:220-222` creates a `Theme` for every valid relation of every
dimension at construction: 25 per theme type, alive from `__init__` and never deleted.

**Metacat** — `all-themes` grows only through `add-theme` (`themes.ss:374-386`) and
shrinks through `delete-theme-type` (`themes.ss:341-347`), which `clamp-theme-pattern`
(`trace.ss:1530-1536`) calls first. It holds only themes something has touched.

**(a) It changes the bridge thematic-compatibility weighting.** `bridges.ss:273-288`
sets `neg-weight` to `2 × (length support-values)` — twice the number of themes that
*exist*. In Petacat that is permanently 50; in Metacat it is 4 during a snag-response
clamp and around 10 early in a run. For a bridge with one incompatible theme at −80 and
two supporting at +60 and +40:

| | average theme support |
|---|---|
| Metacat, 2 themes (mid-clamp) | −0.579 |
| Metacat, 5 themes | −0.653 |
| Petacat, 25 themes | −0.768 |

The "incompatible themes drown out compatible ones" asymmetry is systematically stronger,
and constant rather than growing with what the run has built.

**(b) Ghost themes can be driven positive.** A theme at 0 that does not exist in Metacat
receives no decay and no propagation. In Petacat it is a full participant, and two
negative neighbours contributing `negative→positive` at +25 each beat the decay of 25.
Simulated with Petacat's own arithmetic, a 4-relation cluster with two themes released
from a −100 clamp:

```
cycle  2: [-95, -95,   4,   4]
cycle  6: [-81, -81,  12,  12]
cycle 12: [-52, -52,  18,  18]
```

So within ~180 codelets of a clamp expiring, Petacat has invented +18 of positive
vertical-theme activation from nothing — which turns on thematic-bridge-scout posting
(probability 0.18) where the reference posts none.

**A wrong fidelity citation goes with it.** `bridges.py:420-428` claims
`get-active-themes` (`themes.ss:181-186`) "returns the whole cluster set, not only the
themes that happen to carry activation". It does not; it filters `all-themes`, the
created set. The comment then justifies the padding as preserving `neg-weight`, when the
padding is what breaks it.

**Confidence: certain** on the mechanism and the arithmetic. The magnitude of (a) depends
on how many themes a given Metacat run creates, which only an instrumented reference run
would pin down.

## B-3. Two `100*` roundings are missing in the jootser

**Petacat** — `jootsing.py:551` and `jootsing.py:1003` compute `100.0 * a / b`.
**Metacat** — `jootsing.ss:127-129` and `jootsing.ss:64-65` wrap both in `100*`, which is
`(round (* 100 x))` (`utilities.ss:544`).

Two snags out of three give `overlap = 67` in Metacat and `66.667` in Petacat. Real,
tiny — it moves a probability by 0.003.

**Confidence: certain**, marginal by construction.

## B-4. `descriptor_support` drops the reference's rounding

**Petacat** — `builtins.py:2113`: `return 100.0 * described / len(groups)`.
**Metacat** — `workspace-structure-formulas.ss:44-54` wraps it in `100*`.

Feeds the singleton-group direction pick: 33.33 vs 33. Sub-percentage-point.

`formulas.py:398-420` holds a second `descriptor_support` that *does* round and is
imported by nothing — see D-3.

**Confidence: certain**, negligible.

---

# C. Ordering

Order is not cosmetic anywhere a list is indexed by a random draw, zipped positionally,
or read with a first-match predicate.

## C-1. Every `cons`-built list in the Scheme is reversed in Petacat

Scheme accumulates with `cons`, which prepends. Petacat accumulates with `append`, which
does not. This is one difference with several faces:

| | Petacat | Metacat | What reads the order |
|---|---|---|---|
| Rule and bridge lists | `workspace.py:816-819`, `:776-783` append | `workspace.ss:479-483` conses | `get_relative_quality`'s stable sort — **tied qualities get each other's ranks**, and rank *is* rule strength (`rules.ss:286`); the answer-finder's `stochastic-pick` walks the list in order |
| Deferred codelet batch | `coderack.py:344-346` in creation order | `coderack.ss:383-385, 402-406` — last-created lands first | which codelet a uniform index selects within a bin; which member is dropped over capacity |
| Trace event list | `trace.events` appends | `trace.ss:201` conses | `jootsing.py:682` takes `clamps[0]` as "most recent" — it is the **oldest**. The Scheme's own debug line says "last clamp first" (`jootsing.ss:144`) |
| `_partition_by` clusters | `rules.py:3289-3304` seeds classes first-element-first | `utilities.ss:811-825` recurses to the end first, so the **last** element's class heads the result | the order of `stochastic-if*` draws in `abstract-change-descriptions` |
| Per-node link buckets | `slipnet.py:900-910` appends | `slipnet.ss:229-241` conses | today, nothing that matters — every consumer selects by a predicate matching at most one link. A future `random-pick` over a bucket would diverge silently |

**Confidence: certain** on every ordering. The consequences range from "changes rule
strength on ties" (real) to "changes nothing today" (the link buckets).

## C-2. `remq-duplicates` keeps the last occurrence; Petacat keeps the first

**Metacat** — `utilities.ss:915-927` drops `(1st l)` when it recurs later.
**Petacat** — `rules.py:127-132`, `rules.py:111-113`, `rules.py:1461-1466`,
`answers.py:452-457` all keep the first.

Same number of draws, different pairing of draws to items. For `_unjustified_themes` it
is worse than a pairing shift: the Scheme compares whole `(dimension relation)` entries
and so keeps **two** entries for one dimension with different relations, where a Python
dict keyed on dimension collapses them.

**Confidence: certain** on the semantics.

## C-3. `sort_templates` orders intrinsic clauses enclosing-first

**Petacat** — `rules.py:2140-2149` sorts by nesting level ascending.
**Metacat** — `rules.ss:816-826`: `(tell (2nd t2) 'nested-member? (2nd t1))` puts the
*contained* object first, and `get-nesting-level` (`workspace-objects.ss:342-347`) counts
upward, so the nested object has the higher level. Deepest-first.

Clause order is read positionally by `rule-clauses-equal?` (`rules.ss:370-373`), hence by
`get-equivalent-rule`, `rule_signature` and `answer-present?`.

**Confidence: certain** on the inversion; partly self-consistent inside Petacat, since
both rules being compared are sorted the same way.

## C-4. `differing_dimensions` is deduplicated; `intersect` is not

**Petacat** — `answer_comparison.py:760-767` uses `dict.fromkeys`.
**Metacat** — `answers.ss:490-495` uses `intersect` = `cross-product-filter-map`
(`utilities.ss:795-797`), which emits one element per matching *pair*, so duplicates
survive and `(length differing-dimensions)` counts them.

Reminding distance comes out up to 1 lower than the reference's, against a
`%distance-threshold%` of 5. Note `average_theme_abstractness` (`answers.py:432`) *does*
keep the duplicate, so Petacat is internally inconsistent here.

**Confidence: certain** on the arithmetic; **needs-checking** on frequency.

## C-5. Answer-description theme dimensions are iterated in a different order

`answers.py:98-104` lists String-Position before Alphabetic-Position;
`answers.ss:213-218` has them the other way. Contents identical, order not — and the
result is stored in an insertion-ordered dict that `_lookup` reads first-match.

**Confidence: certain**, low impact.

---

# D. Missing, extra, and duplicated logic

## D-1. The four-way gate on subobject-schema abstraction is absent

**Severity: high.**

**Petacat** — `rules.py:2025-2034` proposes a `subobjects` change description for
**every** common schema, gated only by `p = 0.75`.

**Metacat** — `rules.ss:619-640` gates it on a four-clause `or`: the cluster must span
one whole side, and one of four structural conditions must hold. `spans_right_side`,
`common_right_enclosing_object?` and `all_subobjects_describable?` do not exist anywhere
in `server/`.

Two consequences: extra `(subobjects …)` clauses in abstracted rules, and — because the
Scheme's `stochastic-if*` sits *inside* the gate — one extra draw per schema.

**When it bites.** Any cluster not covering a whole enclosing object; e.g. a partial left
side of `mrrjjj` where two of three top-level objects are bridged. Metacat abstracts
nothing; Petacat abstracts "change ⟨dim⟩ of all objects in ⟨X⟩", which then suppresses
the correct per-object changes via `intrinsic-implies-intrinsic?`.

**Confidence: certain** that the gate is missing.

## D-2. `_get_common_change_schemas` drops every schema with no common relation

**Petacat** — `rules.py:3470-3475` filters on `s[2] is not None`.
**Metacat** — `rules.ss:702-706` filters only `(eq? (schema-relation s) plato-identity)`,
and `#f` is not `eq?` to `plato-identity`, so a schema with no common relation survives.
`concept-mappings->schema` (`rules.ss:724-735`) emits one whenever *either* a common
relation or a common `descriptor2` exists.

Verified by running the pipeline: common schemas
`[(plato-letter-category, None, None, plato-d)]` → common **change** schemas `[]`.

**When it bites.** A cluster whose bridges converge on one descriptor by different
relations — `a→d` alongside `c→d`. Metacat abstracts "change letter-categories of all
objects to `d`"; Petacat cannot express that rule at all.

**Confidence: certain.**

## D-3. Dead second implementations that disagree with the live ones

`formulas.py` holds parallel implementations that nothing imports:

| Function | Line | Relationship to the live one |
|---|---|---|
| `single_letter_group_probability` | 359-391 | **matches the Scheme**; the live builtin (`builtins.py:2116`) does not — see D-4 |
| `descriptor_support` | 398-420 | **rounds**; the live builtin does not — see B-4 |
| `description_type_support` | 422 | agrees with the inlined live logic |
| `current_translation_temperature_threshold` | 249 | reads four coefficients; **has no caller** |
| `_count_local_supporting_groups` | 492 | **omits the `is_built` filter** the live method applies — would count proposed groups as support |
| `_get_group_local_density` | 551 | self-described as "simplified": no neighbour walk, no stochastic pick, different denominator — and cites `groups.ss:354-383`, which it does not implement |

Each is a second answer to a question that already has one, and in three cases the dead
copy is the more faithful. **Recommend deletion rather than reconciliation**, except
where the dead copy is right and the live one is wrong.

**Confidence: certain.**

## D-4. `single_letter_group_probability`: zero supporting groups takes exponent 4

**Petacat** — `builtins.py:2126-2132`:
```python
supporting = group.get_num_of_local_supporting_groups()
exponent = {1: 4.0, 2: 2.0}.get(supporting, 1.0)
if supporting == 0:
    exponent = ctx.meta.get_formula_coeff("single_letter_group_exponent_1_supporting")
```
The coefficient is `4.0` (`formula_coefficients.json`).

**Metacat** — `workspace-structure-formulas.ss:34-37`:
```scheme
(let ((exponent (case (tell group 'get-num-of-local-supporting-groups)
		  (1 4) (2 2) (else 1))))
```
Zero takes the `else` clause: exponent **1**.

**The difference, and why it stays on the list.** The base is
`local_support/100 × length_activation/100`, and `_local_support` returns `0.0` when
`supporting == 0` (`groups.py:245-246`, matching `groups.ss:386-387`). `0.0 ** 4` equals
`0.0 ** 1`, and `temp_adjusted_probability(0.0)` is `0.0` in both implementations. So on
inspection the branch **may be unreachable**, and every reachable case — 1 → 4, 2 → 2,
≥3 → 1 — agrees with the reference.

Per the standard set at the top of this document, that is not a reason to close it.
Petacat should take the `else` branch as the Scheme does, with a comment recording that
the branch may be unreachable and why. Note also the second-order defect: the coefficient
named `..._1_supporting` is applied at `supporting == 0`, and the case it is named for
takes `4.0` from the dict literal instead — so none of the three coefficients affects the
case it names. That half is tracked in `PHASE 1 PLAN.md` §0.7, slice 9.

**Confidence: certain** on the divergence. **Conditional** on reachability, and
deliberately not resolved.

## D-5. `_attach_length_to_appropriate_groups` reads `if*` as `if`/`else`

**Petacat** — `answers.py:610-621` uses `if`/`else` and `elif`.
**Metacat** — `answers.ss:1082-1092`. `if*` is `when`, not `if`
(`syntactic-sugar.ss:118-119`), so the reference attaches a Length description to the
source group **and** to the instantiated group, and runs the BondFacet branch
**unconditionally** as the second body form — where Petacat makes it an `elif`. Petacat
also filters the subobjects to `Group`; the reference does not.

**When it bites.** Any answer whose rule contains a Length transform — `abc → abcd`,
`aabb → aabbb`. The answer string's group ends up without a Length description the
reference gives it, which changes the concept-mappings computed over it and hence the
translated rule's theme pattern.

**Confidence: certain** on the semantics of `if*`.

## D-6. Bond builder breaks bonds before groups, and without the existence guard

**Petacat** — `builtins.py:904-907` iterates a flat list ordered bonds, groups, bridges.
**Metacat** — `bonds.ss:396-402` breaks **groups first**, each guarded by
`(tell *workspace* 'object-exists? group)`.

Two differences. `break-group` cascades, so breaking a bond first and then its enclosing
group passes through a state the reference never occupies. And `get-common-groups`
(`groups.ss:1026-1033`) returns *nested* groups, so breaking the outer one can already
have removed the inner — which is what the guard is for. Petacat breaks every one
unconditionally.

**Confidence: certain** on the ordering; **needs-checking** whether Petacat's `_retire`
is idempotent enough that the missing guard is harmless.

## D-7. Workspace aggregates include the answer string outside justify mode

**Petacat** — `workspace.py:750-762` gates the answer string on `answer_string is not None`.
**Metacat** — `workspace.ss:124-147, 155-160` gates it on `%justify-mode%`.

`report_answer` (`builtins.py:2579`) assigns `answer_string` in a **discovery** run. From
that point `all_objects` and `all_structures` include answer-string letters, feeding
average unhappiness (70% of the temperature), the bond/group scout posting probability,
`choose_object`, `get_activity`, and both value updates. A fresh answer string has no
bridges, so every one of its objects scores 100 on bridge weakness.

The exposure window in a plain run is narrow — `finish()` is called on the same step —
but it is fully live for a **restored** run (`state_graph.py:487` writes `answer_string`
back) and for free-running's post-hoc reconciliation.

**Confidence: certain** on the divergence; **needs-checking** on how much executes after
the assignment.

## D-8. `propose_bridge`'s recruitment loses its target

**Petacat** — `bridges.py:1240-1250` posts top-down scouts with a node but no scope; the
scouts then choose their own (`codelet_types.json`: `choose_string_for(...)`,
`choose_object('average')` over the whole workspace).
**Metacat** — `bridges.ss:1120-1145` passes the string explicitly, and the scouts take the
`(if (workspace-string? scope) scope …)` branch (`groups.ss:424-425`,
`descriptions.ss:132`).

The reference's point is that the moment `c` faces `jjj`, a group scout is aimed at *c's
string*. Petacat's scout does a relevance-weighted pick over all three strings and lands
elsewhere two times in three — and consumes an extra draw doing it. Affects every
horizontal bridge between objects of different platonic length, which is the mechanism
behind `mrrjjj → mrrjjjj`.

**Confidence: certain.**

## D-9. Concept-activation events are sampled once over a combined delta

**Petacat** — `runner.py:952-956` snapshots activations, runs the whole update, and tests
importance once on the total delta.
**Metacat** — `monitor-slipnode-activation-change` is called from three places
(`slipnet.ss:140, 153, 167`), so the flush delta and the jump delta are tested
**separately**.

Importance is `|delta| × cd / 100` against 85, and only four nodes have `cd ≥ 85`, so an
event needs `|delta| ≥ 94.4`. A node flushing 0 → 60 and then jumping to 100 gives
Metacat two sub-threshold deltas and Petacat one that clears it. Every Trace event resets
`get-elapsed-time 'any`, so a spurious event delays the progress-watcher's 250-codelet
settling test and can zero the justify-clamp jootsing factor.

**Confidence: certain** that the two differ; **narrow** in reach.

## D-10. Jootser: three divergences in the snag-theme pipeline

| | Petacat | Metacat |
|---|---|---|
| No matching snag description | `jootsing.py:1086-1094` substitutes the dimension's conceptual depth (30–90) and draws | `jootsing.ss:93-99` — `average` of the empty list is **0** (`utilities.ss:422-428`), so the inclusion probability is 0 and `prob?` short-circuits without drawing |
| Snag-object descriptions | `jootsing.py:1046-1054` keeps the multiset | `jootsing.ss:83-86` wraps it in `remq-duplicates` |
| Negated entries | clamped twice — once by `clamp_event.activate`, again by the codelet body at a hard −100 | `jootsing.ss:113-118` — one clamp event, activated once |

The first is the consequential one: the snag theme pattern falls back to *every* vertical
concept-mapping in the workspace when the snag objects have no vertical bridge
(`trace.ss:1062-1064`), which is exactly what a repeated snag produces. Petacat then
negates and clamps a dimension the impasse has nothing to do with, at up to 0.9
probability.

The third is currently a no-op — `negate-theme-pattern-entry` yields −100 for the
two-element entries `get_snag_theme_pattern` returns — and is recorded under the standard
at the top of this document rather than closed.

**Confidence: certain** on all three code differences.

## D-11. Smaller items

| | Petacat | Metacat | Effect |
|---|---|---|---|
| `Image.new_start_letter` | `images.py:427-431` keeps the old letter when there is no related node | `images.ss:280-282` assigns unconditionally, so it becomes `#f` | a stale start letter where the reference records "there isn't one"; needs-checking |
| `is_verbatim_rule` | `rules.py:1047-1049` — `any(c.is_verbatim …)` | `rules.ss:206-208` — exactly one clause, and it verbatim | a mixed rule reads as verbatim; likely unreachable |
| Identity rule | `rules.py:3623-3638` returns `None` when no bridge is describable, and skips `set_abstracted_rule_information` | `rules.ss:417-442` proposes the identity rule and sets its theme pattern | no identity rule for `abc → abc`; the built one has no theme pattern |
| `translate_rule` | `builtins.py:2699-2700` refuses with no built vertical bridge | `answers.ss:1440-1448` translates each description unchanged | an added precondition; probably unreachable |
| Group-Category transform | `rules.py:3059-3069` silently skips the reversal when no Bond-Facet transform exists | `rules.ss:1346-1349` errors on `(2nd (assq …))` of `#f` | Petacat reports an un-reversed answer where the reference snags |
| Slippage log | absent | `answers.ss:1298-1332` records slipped-through bridges, including coattails | the answer event's supporting vertical bridges are derived differently |
| `Bridge.add_concept_mappings` | `bridges.py:126-128` appends | `bridges.ss:210-213` prepends | first-match `CM-type?` lookups after a duplicate merge |
| `RNG.pick` on empty | raises | `utilities.ss:475-479` returns `#f` | latent; all call sites appear guarded |
| `probabilistic_jump_to_full` | `slipnet.py:560-566` has no frozen check | `slipnet.ss:387-389` → `update-activation` is wrapped in `(if* (not frozen?) …)` | unreachable with the shipped data — every clamp lands on 0 or 100 — and recorded under the standard above |

---

# E. Citation drift

Petacat cites the Scheme extensively. Most citations are correct; these are not. None
changes behaviour, but a wrong citation is how a wrong reading survives review — A-1 is
exactly that, where the drift accompanied a substantively wrong reading.

**Stale, formerly correct** — off by +42, from a commit that added lines above them:

| Cited | Actual |
|---|---|
| `rng.py:82` — `utilities.ss:426-429` for `~` | 468-471 |
| `coderack.py:494` — `utilities.ss:443-448` for `stochastic-pick` | 485-490 |
| `formulas.py:41` — `utilities.ss:500` for `1-` | 542 |
| `formulas.py:441` — `utilities.ss:502` for `100*` | 544 |
| `formulas.py:350` — `utilities.ss:504` for `%` | 546 |
| `formulas.py:172` — `utilities.ss:488-491` for `sigmoid` | 556-559 |
| `workspace.py:41`, `workspace_objects.py:172` — `utilities.ss:443-448` | 485-490 |
| `workspace.py:857` — `utilities.ss:388-392` for `weighted-average` | 430-434 |

**Never correct** — verified against every commit in Metacat's history:

| Cited | Actual |
|---|---|
| `formulas.py:184`, `:198` — `constants.ss:1038-1044` | 1045-1052 |
| `formulas.py:220` — `constants.ss:1047-1074` | 1054-1081 |
| `workspace.py:1758` — `workspace.ss:678-683` for `rough-num-of-objects` | 683-689 |
| `workspace.py:1521,1527,1533` — `workspace.ss:683-688` | those lines are `rough-num-of-objects` itself |
| `python_backend.py:121` — `slipnet.ss:201-214` for the spreading loop | 178-187 |

**Substantively wrong prose:**

- `workspace.py:1773-1774` says "a large count costs two draws and a small one costs
  one." Each `~` costs **two** draws — the delta and the sign — so it is four and two.
- `bridges.py:420-428` misdescribes `get-active-themes`; see B-2.
- `rng.py:82`'s docstring asserts `(round (sqrt 2))` is the flonum `1.0`; `round` is
  shadowed at `utilities.ss:250-252`. See A-1.
- `workspace_objects.py:199-208` says a sole candidate's draw "cannot change the answer".
  True of the answer, false of the stream. See A-3.

**Not drift:** the `rules.ss:15xx` citations in `rules.py` are ~6 lines off against the
working copy because commit `130314d` added lines to `rules.ss`; they are correct against
the Metacat 1.2 release Petacat was ported from.

---

# F. Checked and found faithful

Recorded because a clean result is evidence too, and because it bounds where the
remaining risk is.

**The Slipnet data is a perfect match.** All 59 nodes — names, short names, conceptual
depths, file order. All 202 links — the `(from, to, type)` set, every label node, every
length, every fixed-length flag, and the global definition order. Verified by mechanically
expanding `slipnet-node-list*`, `lateral-link*`, `instance-link*`, `category-link*`,
`property-link*`, the `<-->` doubling, the `all-lengths:` fan-out, the `(- (cd A) (cd B))`
length expressions and the two post-hoc override loops at `slipnet.ss:689-692` and
`705-708`, then diffing against the seed data.

**Every cognition-relevant `%…%` constant has the same value in Petacat.** 247 constants
are defined across the Scheme; 180 are graphics. Of the remaining 48 there is **not one
value difference**. This includes all seven urgency levels, all nine codelet patterns
(same members, same order, same tier), the five translation-temperature distributions,
the four Trace importance thresholds, the five theme coefficients, and the clamp periods.

**The random primitives, apart from A-1.** `prob?` agrees including both short-circuits;
`random-pick` agrees; `stochastic-pick` agrees including the zero-weight-sum fallback and
the cumulative walk; `stochastic-filter` agrees. `weighted_pick`'s `>=` where the Scheme
has `<` differs only when `random()` returns exactly `0.0` with a leading zero weight —
probability 2⁻⁵³.

**The formulas.** `temp_adjusted_probability` matches over 101 temperatures × 999
probabilities plus edge cases — **maximum absolute difference 0.0** — including the
`truncate`/`floor` question and the `log10` epsilon nudge. `temp_adjusted_values`,
`update_temperature` (70/30), `weighted_average`, `sigmoid`, `group_evaluation_probability`
and `bond_degree_of_assoc` are all faithful.

**Rule quality.** `compute_quality`, `_compute_uniformity`, `_compute_abstractness` and
`_compute_succinctness` match `rules.ss:1550-1643` exactly, including the `(3 2)` weights,
the `exp(4(x−1))` squash, the `(5 5 1)` weighting, the cubed extrinsic homogeneity,
`sigmoid(3, 40)`, and `4/(3+cost)`. `intrinsic_implies_intrinsic` matches all six cases of
`rules.ss:1194-1231`. All three `<failure-result>` shapes are present and correctly typed.

**Memory.** `calculate-answer-distance` is a term-for-term port of `memory.ss:494-583`,
including the base of 1, the ×2 weights on unique themes, the depth-filtered difference
count, the rounding fallback, and the justification and coherence terms.

**The update cycle.** `run.ss`'s step order matches exactly, including thematic codelets
coming after the top-down slipnodes, `step_mcat` incrementing after running, and the
seven steps of the snag response (`answers.ss:1189-1191`).

**The three-pass Jacobi theme update**, the clamp lifecycle, `justify.ss`'s pattern
assembly, the breaker, the thematic-bridge-scout and the progress-watcher all match.

**`workspace-objects.ss`**: importance, both unhappinesses, both saliences and the
averages, with the rounding checked rather than assumed.
**`concept-mappings.ss`** and **`descriptions.ss`**: clean.
**The numeric backends** are faithful transcriptions; the one deviation
(gather-vs-scatter summation order) is documented and bounded below 1e-13. They inherit
B-1 and introduce nothing of their own.
**The codelet bodies in `seed_data/codelet_types.json`** contain exactly one numeric
literal across all 27 types, and it is a `get_param` fallback.

---

# Summary

| Section | Entries | Of which certain |
|---|---:|---:|
| A. Random stream | 5 | 5 |
| B. Arithmetic and distribution | 4 | 4 |
| C. Ordering | 5 | 5 |
| D. Missing, extra, duplicated | 11 | 8 |
| E. Citation drift | 17 | 17 |

**The three most consequential, by the reach of what they touch:** A-1 (scout counts,
from cycle one, on every problem), B-2 (theme weighting and ghost themes, structural),
D-1 (rule abstraction gate absent).

**Four entries are recorded as possibly unreachable and deliberately left open**, per the
standard at the top: D-4, the frozen-node jump in D-11, the double clamp in D-10, and
`is_verbatim_rule` in D-11.
