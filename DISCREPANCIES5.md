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

**Status (lockstep pass, 2026-10-27):** fixed (one row) / not changed (four) — the singleton-group gate now draws the coin first (new DSL builtin `coin_flip`) and then evaluates `single_letter_group_probability`, fizzling iff `coin < 1 - p` exactly as `stochastic-if*` does (this site therefore also takes the A-4 sense of the coin); the empty concept-mapping list, `num_bonds_to_scan` n<2 and answer-finder all-zero rows are single draws on fizzling or trivial decisions and the sharded rack is free-running only, so they are left.

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

**Status (lockstep pass, 2026-10-27):** fixed — `Node.spread_activation_to_neighbors` now rounds `scale * assoc * activation / 100.0`, so the exact half-way cases (assoc 70, act 45/85) round as Metacat's exact rational does; `tests/unit/test_arithmetic_fidelity.py`.

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

**Status (lockstep pass, 2026-10-27):** fixed — both `100*` sites (`overlap` in `_build_theme_overlap_table`, elapsed-time weights in `get_clamp_jootsing_probability`) now round the exact `Fraction` half-to-even.

## B-4. `descriptor_support` drops the reference's rounding

**Petacat** — `builtins.py:2113`: `return 100.0 * described / len(groups)`.
**Metacat** — `workspace-structure-formulas.ss:44-54` wraps it in `100*`.

Feeds the singleton-group direction pick: 33.33 vs 33. Sub-percentage-point.

`formulas.py:398-420` holds a second `descriptor_support` that *does* round and is
imported by nothing — see D-3.

**Confidence: certain**, negligible.

**Status (lockstep pass, 2026-10-27):** fixed — `descriptor_support` (the builtin the DSL calls) returns `round(Fraction(100*described, n))`; the dead `formulas.py` copy was already faithful.

---

## B-5. Posting urgencies rounded before the bin is chosen (found by the lockstep pre-triage)

**Petacat** — `seed_data/posting_rules.json` wrapped the five top-down formulas and the thematic formula in `round(...)`, `posting.evaluate_urgency` applied `int(...)`, and `Coderack._urgency_to_bin` was `int(u * bins / 100)` clamped.
**Metacat** — `slipnet.ss:214` makes the urgency the exact rational `(% depth) * activation`; `thematic-codelet-urgency` (`coderack.ss:586-591`) is the unrounded theme activation; `get-coderack-bin` (`coderack.ss:377-382`) is `>= 100 -> last`, `<= 0 -> 0`, else `floor((% urgency) * bins)`. Nothing rounds the urgency.

Rounding first moves any value in `[100k/7, 100k/7 + 0.5)` (and its mirror) one bin: depth*activation/100 = 14.4 is bin 1 in Metacat and bin 0 in Petacat. Bottom-up urgencies are integer constants or `100 - temperature` (an integer in Metacat, `formulas.ss:76`), unaffected.

**Status (lockstep pass, 2026-10-27):** fixed — the formulas no longer round, `evaluate_urgency` returns the raw value, and `_urgency_to_bin` follows `get-coderack-bin` (integers exact, floats divide-then-multiply); bin edges for non-integer urgencies are never within float error of an integer except at 100, so floats land on the exact side. `max(1, round(100 - temperature))` kept (urgency 0 and 1 are both bin 0).

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

**Status (lockstep pass, 2026-10-27):** fixed (behavioural cases only) — `Workspace.add_bridge`/`add_rule` now prepend (newest first, as `cons`), fixing rule-rank ties and bridge-list walks, and `joots_from_justify_clamps` takes the most recent clamp (`clamps[-1]`, the list being chronological). Not changed: the deferred posting batch (harness absorbs it), per-node link buckets (no consumer depends on it), and `_partition_by` cluster order (invasive; needs a replay trace to show it matters).

## C-2. `remq-duplicates` keeps the last occurrence; Petacat keeps the first

**Metacat** — `utilities.ss:915-927` drops `(1st l)` when it recurs later.
**Petacat** — `rules.py:127-132`, `rules.py:111-113`, `rules.py:1461-1466`,
`answers.py:452-457` all keep the first.

Same number of draws, different pairing of draws to items. For `_unjustified_themes` it
is worse than a pairing shift: the Scheme compares whole `(dimension relation)` entries
and so keeps **two** entries for one dimension with different relations, where a Python
dict keyed on dimension collapses them.

**Confidence: certain** on the semantics.

**Status (lockstep pass, 2026-10-27):** partially fixed — `_get_all_swaps` now orders the swap descriptors by `remq-duplicates` (last occurrence kept; it previously used an unordered `set`, so the order was hash-dependent), and `_unjustified_themes` now keeps the first entry per dimension (the Scheme's `assq`). Not changed: the dict form still cannot hold two relations for one dimension (it is persisted as JSONB and read by memory/API), and the remaining order-only dedupes (`get_concept_pattern`, `_swap_descriptor_for`'s symmetric pair).

## C-3. `sort_templates` orders intrinsic clauses enclosing-first

**Petacat** — `rules.py:2140-2149` sorts by nesting level ascending.
**Metacat** — `rules.ss:816-826`: `(tell (2nd t2) 'nested-member? (2nd t1))` puts the
*contained* object first, and `get-nesting-level` (`workspace-objects.ss:342-347`) counts
upward, so the nested object has the higher level. Deepest-first.

Clause order is read positionally by `rule-clauses-equal?` (`rules.ss:370-373`), hence by
`get-equivalent-rule`, `rule_signature` and `answer-present?`.

**Confidence: certain** on the inversion; partly self-consistent inside Petacat, since
both rules being compared are sorted the same way.

**Status (lockstep pass, 2026-10-27):** fixed — `sort_templates` now uses the Scheme comparator clause for clause (contained object first, disjoint objects by position) in a plain merge sort, since the comparator is not a strict weak order.

## C-4. `differing_dimensions` is deduplicated; `intersect` is not

**Petacat** — `answer_comparison.py:760-767` uses `dict.fromkeys`.
**Metacat** — `answers.ss:490-495` uses `intersect` = `cross-product-filter-map`
(`utilities.ss:795-797`), which emits one element per matching *pair*, so duplicates
survive and `(length differing-dimensions)` counts them.

Reminding distance comes out up to 1 lower than the reference's, against a
`%distance-threshold%` of 5. Note `average_theme_abstractness` (`answers.py:432`) *does*
keep the duplicate, so Petacat is internally inconsistent here.

**Confidence: certain** on the arithmetic; **needs-checking** on frequency.

**Status (lockstep pass, 2026-10-27):** fixed — `differing_dimensions` is now the pairwise `intersect` (duplicates survive), so `len()` counts them as in `answers.ss:490-495`.

## C-5. Answer-description theme dimensions are iterated in a different order

`answers.py:98-104` lists String-Position before Alphabetic-Position;
`answers.ss:213-218` has them the other way. Contents identical, order not — and the
result is stored in an insertion-ordered dict that `_lookup` reads first-match.

**Confidence: certain**, low impact.

**Status (lockstep pass, 2026-10-27):** fixed — `answers.py` `_ANSWER_DESCRIPTION_THEME_TYPES` now lists Alphabetic-Position before String-Position as `answers.ss:213-218` does (the seed-data copy already did).

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

**Status (lockstep pass, 2026-10-27):** fixed — added `_subobjects_gate` (with `_common_right_enclosing_object`, `_get_right_enclosing_object`, `_spans_right_side`, `_all_subobjects_describable`); the `subobjects_prob` draw now sits inside the gate. Petacat's extra `<2 constituents` guard (in place of `singleton-group?`) was left as is.

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

**Status (lockstep pass, 2026-10-27):** fixed — `_get_common_change_schemas` filters only schemas whose relation is identity; a `None` relation survives.

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

**Status (lockstep pass, 2026-10-27):** fixed — deleted from `formulas.py` the unreferenced `current_translation_temperature_threshold` (also dead in the Scheme: only the distribution is defined, `formulas.ss:38`), `single_letter_group_probability`, `descriptor_support`, `description_type_support` and their private helpers (`_count_local_supporting_groups`, `_get_group_local_*`, `_has_descriptor`, `_has_description_type`); grep over the repo including `seed_data/` showed only the same-named builtins in `codelet_dsl/builtins.py`, which are the live ones. Removed the test class that exercised the dead threshold function.

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

**Status (lockstep pass, 2026-10-27):** fixed — zero supporting groups now takes the `else` exponent 1, with a comment that the branch may be unreachable (local support is 0.0 there); the unused-coefficient half stays with `PHASE 1 PLAN.md` §0.7.

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

**Status (lockstep pass, 2026-10-27):** fixed — `if*` is `when`: a Length transform attaches to the source group (if it lacks Length) **and** unconditionally to the instantiated group; the BondFacet:Length branch is a separate, independent test; sub-objects are no longer filtered to `Group`. `attach_length_description` now accepts a letter (platonic length `plato-one`, `workspace-objects.ss:57`).

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

**Status (lockstep pass, 2026-10-27):** fixed — in `build_structure` a bond now breaks its incompatible groups first, then bonds, then bridges, and skips a group that is no longer in its string (`bonds.ss:396-402`); bonds and bridges stay unguarded as in the Scheme, and `_break_bond` is idempotent so that is harmless.

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

**Status (lockstep pass, 2026-10-27):** fixed — new `Workspace.aggregate_strings` adds the answer string only under `justify_mode` (`workspace.ss:124-160`) and drives `all_objects`, `all_structures`, `update_all_object_values` and the batched strength update; `all_strings` (used by serialization, rules, staleness) is unchanged.

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

**Status (lockstep pass, 2026-10-27):** fixed — `bridges._top_down_codelet` takes a `scope` (the object's string) and stores it in `Codelet.arguments['scope']` when given; the four string-choosing scouts use it instead of `choose_string_for`, and the description scout picks from that string (`bridges.ss:1124-1145`); slipnet-posted scouts carry no scope (= `*workspace*`).

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

**Status (lockstep pass, 2026-10-27):** fixed — `Slipnet.update_activations` takes an `on_flushed` hook and `runner._record_concept_activation_events` now tests the flush delta and the jump delta separately (`slipnet.ss:140, 153, 167`), all flushes then all jumps.

## D-10. Jootser: four divergences in the snag-theme pipeline — **three now fixed, and they were the give-up divergence**

| | Petacat | Metacat | |
|---|---|---|---|
| Depth of a *matching* description | `jootsing.py` scored every match at a hardcoded `50.0` | `jootsing.ss:95-98` → `descriptions.ss:68` — a description's depth is its **descriptor's** depth | **fixed** |
| No matching snag description | substituted the dimension's conceptual depth (30–90) and drew | `average` of the empty list is **0** (`utilities.ss:422-425`), so the weight is 0 | **fixed** |
| Snag-object descriptions | kept the multiset | `jootsing.ss:86-88` wraps it in `remq-duplicates` (last occurrence — see C-2) | **fixed** |
| Negated entries | clamped twice — once by `clamp_event.activate`, again by the codelet body at a hard −100 | `jootsing.ss:113-118` — one clamp event, activated once | open |

**Status (lockstep pass, 2026-10-27):** row 4 fixed — the `jootser` body no longer re-clamps the negative pattern (`themespace.clamp_negative_pattern` and a second `coderack.clamp_pattern`); the clamp event's own `activate` inside `attempt_jootsing` is the single activation, as `jootsing.ss:113-118`.

The first row was not in the original survey and is the largest of the four. `Description`
carries neither `conceptual_depth` nor `get_conceptual_depth` — the depth lives on
`desc.descriptor` — so both `hasattr` probes missed and the `50.0` default survived every
time. All three fixed rows pushed the inclusion weight the *same* way, up.

Measured per-entry weights on `abc→abd;xyz`, against a real Metacat trace:

| dimension | Metacat overlap / avg-dd / weight | Petacat, before |
|---|---|---|
| objectctgy | 100 / **20** / **0.20** | 100 / 50 / **0.50** |
| stringpos | 100 / **40** / **0.40** | 100 / 50 / **0.50** |
| groupctgy | 20–33 / **0** / **0.00** | 20–33 / 80 / 0.16–0.27 |
| direction | 20–33 / **0** / **0.00** | 20–33 / 70 / 0.14–0.23 |

Metacat's 20 and 40 are exactly `plato-letter` and `plato-rightmost`, the descriptors of
the snagged `z`. P(at least one entry survives the stochastic filter) is `1 − 0.8·0.6 =
0.52` in the reference against `1 − 0.5·0.5 = 0.75` in Petacat; measured across whole
runs, 43.8% of attempts built a negative theme pattern against Petacat's 75.8%.

**Why it mattered.** A give-up is exactly three mutually-equivalent snag-response clamps,
and 51 of 51 give-ups traced came from `joots_from_snag_response_clamps`. Doubling the
rate at which a pattern is built doubles the rate at which runs reach three clamps:

| `abc→abd;xyz`, 1000 seeds | before | after | Metacat |
|---|---:|---:|---:|
| clamps per 1000 codelets | 0.79 | 0.68 | 0.62 |
| runs reaching ≥3 clamps | 37.8% | 28.7% | 20.4% |
| **gave up** | **22.5%** | **17.5%** | **10.9%** |
| yyz | 3.9% | 7.0% | 6.4% |
| xyd | 22.9% | 22.2% | 37.1% |

−5.0 points against a difference-SE of ~1.8, so ~2.8σ. This closes roughly 40% of the
give-up excess and corrects `yyz`; it does not move `xyd`, which is a separate mechanism
still open. Note that the project's own oracle check passes in *both* columns — it tests
set membership, not frequency, and is blind to a 2× skew in how often a run gives up.

The fourth row is currently a no-op — `negate-theme-pattern-entry` yields −100 for the
two-element entries `get_snag_theme_pattern` returns — and is recorded under the standard
at the top of this document rather than closed.

**Confidence: certain** on all four code differences.

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

**Status (lockstep pass, 2026-10-27):** per row — `is_verbatim_rule` fixed (exactly one verbatim clause); identity rule fixed (`build_rule_from_bridges` no longer returns `None` for no describable bridges and sets the abstracted rule information); `probabilistic_jump_to_full` fixed (frozen node takes the draw but not the jump). Not changed: `Image.new_start_letter` (assigning `None` would raise a non-`ImageFailure` downstream rather than snag, needs its own pass), `translate_rule` precondition (probably unreachable), Group-Category transform (a Scheme error path), slippage log (new feature), `Bridge.add_concept_mappings` prepend (interacts with the C-1 list-order question, to be settled with it), `RNG.pick` on empty (all call sites guarded).

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

# G. Found by the lockstep replay (2026-10-28)

- **G-A1. String-level average intra-string unhappiness was computed live, not stored.** Metacat's `get-average-intra-string-unhappiness` (`workspace-strings.ss:116`) returns a value set only by `update-average-intra-string-unhappiness` (`workspace-strings.ss:335`), called once per update cycle from `update-workspace-values` (`run.ss:339-343`; the answer string only when justifying). Petacat recomputed it on every read, so string-choice weights of top-down scouts and `group-scout:whole-string` saw objects created/broken since the last cycle. Fix: `WorkspaceString` caches it (`update_average_intra_string_unhappiness`), refreshed from `Workspace.update_average_unhappiness_values`.
- **G-B1. Fresh objects start with importance, unhappiness and salience 0.** `workspace-objects.ss:69-78` initialises every importance, unhappiness and salience to 0; they become non-zero only at the next update cycle. Petacat initialised them to 100, so a group built mid-cycle was immediately a candidate for `choose-object` (e.g. `bottom-up-bridge-scout`, `top-down-description-scout`) with weight 63, where Metacat gives it weight 0 until the next update. Fix: `WorkspaceObject.__init__` (`server/engine/workspace_objects.py`) starts all of them at 0. (Cluster B also found G-A1 independently.)
- **G-C2. The rule duplicate check ignored the rule's object descriptions.** `Workspace._rules_equal` (used by `get_equivalent_rule` / `rule_present` / `add_rule`) compared only clause types and changes, so `[single] -> b` was "equal" to `[a] -> b` and the rule-builder silently dropped the newcomer (a-b-z seed 4, c=319: Metacat builds `rule(top,((intrinsic ((letter string-position-category single)) ((self letter-category b)))))`, Petacat did not, which then removed the answer-finder posting, the snag exit and later `p` mismatches). Metacat: `rules-equal?` / `rule-clauses-equal?` / `object-descriptions-equal?` (`rules.ss:364-391`). Fix: delegate to the faithful `rules.rules_equal`. (Cluster C also found G-B1 independently, as its G-C1.)

- **G-D1. The Themespace materialised every possible theme (B-2).** Metacat's `all-themes` grows only through `add-theme` (`themes.ss:374-386`; callers `set-theme-activation`, `boost-themes` at `bridges.ss:301`) and shrinks through `delete-theme-type` (`themes.ss:341-347`, first step of `clamp-theme-pattern`, `trace.ss:1533`); a cluster's `num-relations` stays the count of *possible* relations (`themes.ss:420`). Petacat built all 75 themes up front, so the bridge `neg-weight` (`bridges.ss:275`) was fixed and ghost themes spread/decayed and drove thematic posting. Fix: `ThemeCluster.themes` starts empty (newest first, as `add-theme` conses) with `valid_relations` kept for `alpha`; `Themespace` gains `all_themes`, `add_theme`, `set_theme_activation`, `delete_theme[_type]`, `delete_everything`, `get_themes`/`get_all_active_themes` (in `all-themes` order, which also fixes the order of theme-to-slipnet coin flips); `boost_theme`, `clamp_negative_pattern`, `clamp_theme_pattern`, `save/restore_current_state` (now `themes.ss:103-125` semantics), `reset`, state capture/restore, the numeric layout (rebuilt each step, `n_relations` = possible relations) and the run service's impose/clamp all go through them. API output (`serialize_themespace_state`, `project_themespace`) still lists every possible theme, an absent one at activation 0. The wrong `get-active-themes` citation in `bridges.py` is corrected. Snapshots' `themes` sections now match Metacat's set and activations in all but 19 of 190 traces, whose remaining differences are downstream (bridge strengths / descriptions).

**G-E1. Trace snapshot compared Petacat's internal event names against Metacat's.** Not an engine difference: the engine-facing Trace already holds only Metacat's seven event types (`trace.ss:229`) with the same thresholds and formulas (`group-importance` >=100, `rule-importance` >=67, `concept-mapping-importance` >=65, concept-activation >=85), recorded at the same moments and consed in the same order. The lockstep snapshot hyphenated Petacat's names (`group-built`, `rule-built`, `answer-found`, `clamp-start`, `concept-mapping-built`), so `trace.events.group`/`rule` differed in 162 of 190 traces. `tests/lockstep/snapshot.py:_trace` now maps them to Metacat's names (`group`, `rule`, `answer`, `clamp`, `concept-mapping`, `concept-activation`, `snag`) and counts only those. After the change no trace's first snapshot difference is under `trace.*`.
- **G-G1. The duplicate-group branch of `group-builder` did not warm the transferred description's concepts.** When a built group already exists, Metacat copies the proposal's missing descriptions onto it with `build-description` (`groups.ss:636-641`), which jolts the description type and descriptor (`descriptions.ss:189-191`); canonically the Length description, so `plato-length` and `plato-two`/`three` get +100. Petacat's `_absorb_duplicate_group` (`server/engine/codelet_dsl/builtins.py`) appended the description silently, so those nodes decayed a cycle early and the next jump coin (`slipnet.ss:387-389`) had a different `p`/`count` (aabb-cc-aabb seed 6 c=255: 0.343 vs 0.185). Fix: activate both after the transfer.
- **G-G2. `description-builder` tested `object.string is None`, not Metacat's `object-exists?`.** `descriptions.ss:~157` fizzles *before any activation* when the object is no longer in the workspace (`workspace.ss:312`); Petacat's body let a broken group (string still set) through to the "already present" branch, which jolts the descriptor (e.g. `plato-rightmost`). Fix: also fizzle when the object is not in `object.string.objects` (`seed_data/codelet_types.json`, description-builder). abc-abd-ijk seed 9: first error gone.
- **G-G3. An answer found on an update-cycle boundary got a second update cycle.** `report-new-answer` runs `(update-everything)` and then `(suspend)` from *inside* the answer-finder (`answers.ss:24,~84`), so the run loop's `(modulo *codelet-count* 15)` update (`run.ss:158-159`) never follows. Petacat's `_step_mcat` fell through to its periodic update after finishing the run, drawing a whole extra set of jump/posting coins (surplus `count` errors at the end of zy-x-zy 3, xy-z-xy 3, abc-abd-ijk 2). Fix: `server/engine/runner.py` returns right after the answer is recorded.
- **G-I1. `remq-duplicates` keeps the last occurrence, Petacat kept the first.** `get-incompatible-bridges` (`bridges.ss:324-338`, `728-741`) and `get-incompatible-groups` (`groups.ss:283-286`) wrap their result in `remq-duplicates` (`utilities.ss:915-927`), which drops an element that recurs *later* in the list. The fight order follows that list (`wins-all-fights?` walks it with `andmap`, `workspace-structures.ss:81-91`) and each fight draws from the random stream, so a bridge proposed against {group-bridge, letter-bridge} fought them in the opposite order to Metacat (e.g. `aabb-cc-aabb` seed 1 c=649: weights `[63504, 160000]` then `[63504, 28224]` vs Metacat's `[63504, 28224]` then `[63504, 160000]`). Fix: `Bridge.get_incompatible_bridges` (`server/engine/bridges.py`) and `Group.get_incompatible_groups` (`server/engine/groups.py`) deduplicate keeping the last occurrence. Cleared every `stochastic-pick@bridge-builder` first error (9 traces).
- **G-I2. The bridge evaluator tested the flipped copy, not the original object, for existence.** `bridge-evaluator` (`bridges.ss:1153-1160`) fizzles before drawing anything when either `get-original-object` has left the Workspace; a bridge proposed against a flipped reading of a group points at a copy that is never in the string, so Petacat's `.string is None` test passed after the group it replaced had been broken, and it drew a coin Metacat never drew (`abc-abd-ijk` seed 3 c=245; 9 first errors). Fix: `evaluate_structure` (`server/engine/codelet_dsl/builtins.py`) applies `_premises_still_hold` (which resolves the flipped original) to a bridge before strengthening it.
- **G-I3. Bridge-evaluator urgency was rounded; Metacat posts it exact.** `bottom-up-bridge-scout` / `important-object-bridge-scout` post `average-distinguishing-CM-strength` as the urgency (`bridges.ss:957-963`, `1051-1057`) with no `round`, so `(12+6+6+5)/4 = 7.25` is the codelet's original urgency. Petacat posted `round(7.25) = 7`, so the replay could not tell identical-looking evaluators apart (urgency/original-urgency tie-break in `replay_rng.py`), picked a stale one with a different concept-mapping set, and drew a different `p` (`ab-c-ab` seed 8 c=717). Fix: `seed_data/codelet_types.json` posts the unrounded average (the coderack already floors a float into its bin).
- **G-I4. Abstracting a rule did not attach Length descriptions to the groups of a Length-slipping bridge.** `set-abstracted-rule-information` (`rules.ss:151-160`) attaches a Length description to each group of a supporting horizontal bridge that slips Length and lacks one (a fifth site of `attach-length-description`; the docstring of `attach_length_description` listed only four). Without it a description's local support (`descriptions.ss:87-101`) counted one sibling too few, so `description-evaluator` for `Length:two` drew `p=0.538` where Metacat drew `0.5` (`aabb-cc-aabb` seed 4 c=420). Fix: `Rule.set_abstracted_rule_information` (`server/engine/rules.py`), plus `Bridge.slippage_type_present` (`bridges.ss:236-238`).
- **G-J1. Justify mode picked rules by raw quality, not strength.** `answer-justifier` picks the rule to translate with `(stochastic-pick-by-method ... 'get-strength)` (`justify.ss:26`) and weights the unification partner by `(100- (abs (- strength (tell r 'get-strength))))` (`justify.ss:142-146`). A rule's strength is its rank-relative quality as of the last update cycle (`rules.ss:286`, `workspace-structures.ss:40`); `justify.py` used `Rule.quality` for both, so Petacat offered weights `[95, 70]` where Metacat had `[100, 50]`. Fix: `attempt_justification` reads `Rule.strength` in both places.
- **G-J2. A justify clamp skipped the vertical pattern when no vertical theme was dominant.** `clamp-rules` always clamps `(tell *themespace* 'get-dominant-theme-pattern 'vertical-bridge)` (`justify.ss:163-170`), and `clamp-theme-pattern` (`trace.ss:1530-1536`) deletes the type, freezes it and switches thematic pressure on even for the bare `(vertical-bridge)`. `justify.clamp_rules` required the pattern to have an entry, so the vertical theme type never became active and `thematic-bridge-scout` offered two theme types where Metacat offered three. Fix: drop the length gate.
- **G-J3. Unified vertical theme pattern carried label nodes, so the clamp created no themes.** `unify-rules` returns `(vertical-bridge (dimension label) ...)`; the Themespace names a relation `identity`/`opposite`, but `get_vertical_theme_pattern_to_clamp` passed the label node (or `plato-identity`) through, which names no theme, so `clamp_theme_pattern` silently created none of them and the slipnet never received the associated concept pattern (Metacat: four vertical themes and `opposite` clamped at 100 after the clamp). It also made `_is_identity_label` and the retention probability depend on the spelling. Fix: normalise the relation with `_relation_name` on entry; `_is_identity_label` accepts the bare name. Harness: `naming.py` now spells the theme-type strings `top_bridge`/`bottom_bridge`/`vertical_bridge` as Metacat's symbols (a naming mismatch had made every thematic-scout pick a `missing-pick` fatal).
- **G-H1. The rule scout's direction-reversal change looked its nodes up in the bridges.** `abstract-change-descriptions` (`rules.ss:612-616`) builds the "reverse the direction of the whole string" change from the slipnet constants `plato-direction-category` / `plato-opposite`. `rules.py:abstract_change_descriptions` searched the bridges' concept mappings for them, which hold only `string-position:opposite`, so the lookup was always `None` and the change silently never existed (rules came out as the empty identity rule where Metacat's was non-empty, e.g. `abc-cba-mrrjjj`). The function now takes the slipnet (passed by `build_rule_from_bridges`) and uses the constants.
- **G-H2. Duplicate-group absorption compared description types, not descriptions, and skipped the activations.** The duplicate branch of `group-builder` (`groups.ss:631-642`) transfers each description of the proposal that the existing group lacks, tested by `description-present?` (type AND descriptor, `descriptions.ss:195-197`), through `build-description`, which warms the type and the descriptor (`descriptions.ss:189-191`). `_absorb_duplicate_group` tested only the type and warmed nothing, so `plato-length` was never activated by a re-proposed group and the `top-down-description-scout(length)` codelets that Metacat posts once it crosses the threshold were missing from the coderack. Also, the duplicate check now runs before the constituent-bonds check, as in the Scheme (`group-builder` codelet).
- **G-H3. `map` order of the rule-clause instantiation (Chez).** `(map instantiate-rule-clause-template ...)` (`rules.ss:430`, also the change- and extrinsic-object maps in `instantiate-rule-clause-template`) applies the procedure to the tail element first (odd length), then to the remaining pairs from the last pair back to the first, each pair front to back. Measured on the recorded traces (2 elements: 0,1; 3 elements: 2,0,1). That fixes which random draw each clause consumes. New `rules.py:_chez_map`.
- **G-H4. A WorkspaceString had no string positions.** `workspace-strings.ss:472-473` answers `get-left-string-pos` as 0 and `get-right-string-pos` as length-1; Petacat's string lacked the attributes and `getattr` defaults made it count as "disjoint" from every letter, which broke `sort-templates` ordering (the whole-string clause sorted into the middle of the letter clauses). Added the two properties.
- **G-H5. `partition` / `abstract-change-descriptions` order.** Scheme `partition` (`utilities.ss:811-825`) inserts the elements from the END of the list, each at the front of its class, and `abstract-change-descriptions` conses (so its result is reversed relative to the order the changes were added). Both are now reproduced (`_partition_by`, `all_cds.reverse()`); this changes class and clause order, which feeds `sort-templates` and the clause instantiation order.
- **G-K1. Flipping a spanning group skipped the jolts and back-references of `build-bond` / `build-group`.** `bridge-builder` flips a group by `build-bond` on each reversed bond (jolting its category and direction, `bonds.ss:419-421`) and `build-group` (claiming the bonds, jolting every description's descriptor, `groups.ss:925-930`); `_apply_group_flips` (`builtins.py`) only added them to the string. Fixed there. Reached by `abc-abd-xyz` 2 and 5, `rst-rsu-xyz` 7 (first errors gone).
- **G-K2. `answer-finder` fizzled on all-zero rule weights.** `stochastic-pick` falls back to `random-pick` (`utilities.ss:485-490`); the body (`codelet_types.json`) now lets `weighted_pick` do the same.
- **G-K3. `description-builder` "already present" ignored bond descriptions; the duplicate-group branch compared type only.** `description-present?` compares type and descriptor over `get-all-descriptions` (`workspace-objects.ss:162-165, 281-282`). Fixed in the description-builder body and `_absorb_duplicate_group`. Latent in the corpus.
- **G-K4. `progress-watcher` re-clamped the bare rule pattern.** The clamp event's own `activate` already clamps it against its very-low background (`jootsing.ss:326-333`); the redundant call is removed.
- **G-K5. Bond/bridge builder/evaluator bodies' `.string is None` tests** are never true for a broken group; `evaluate_structure` and `build_structure` already test `object-exists?` on the originals first (G-I2), so the dead tests are replaced by comments. No behaviour change.
- **G-N1. Bond fights ran through the common groups oldest-first.** `get-common-groups` (`groups.ss:1026-1033`) filters `string.groups`, which `add-group` builds by `cons` (`workspace-strings.ss:264`), newest first; the port appends. `wins-all-fights?` (`andmap`) stops at the first loss, and the group fights draw from the density walk, so the order decided which fight was drawn (and made `bond-builder` ask for a neighbour pick Metacat never made). `get_common_groups` (`bonds.py`) now returns newest first.
- **G-N2. The bond-facet change of an opposite-group-category clause used the wrong dimension.** `get-BondFacet-change` (`rules.ss:1051-1054`) is `(self plato-bond-facet (facet))`; the port built `(self facet (facet))`, i.e. `(self letter-category letter-category)`. `get_bond_facet_change(slipnet)` (`rules.py`) now uses the `plato-bond-facet` node.
- **G-N3. Rule abstraction drew its schemas/swaps in the wrong order.** `get-common-schemas` and `get-all-swaps` partition with the Scheme `partition` (`utilities.ss:811-825`), whose class order is not first-seen order; the port grouped by dict insertion. Both now use `_partition_by`. The concept-mapping list they partition was also in the wrong order: `add-concept-mappings` prepends (`bridges.ss:210-213`), and `all-possible-bridge-CMs` walks descriptions in `cons` order, newest first (`workspace-objects.ss:294`, `utilities.ss:689-701`). `Bridge.add_concept_mapping(s)` prepend and `make_concept_mappings` iterates the descriptions reversed.
- **G-N4. `get-ending-letter-category` ignored direction.** It is the last of the *ordered* objects, which are reversed for a left group (`groups.ss:70-73,228`). `_get_ending_letter_category` (`rules.py`) now takes the first object of a left group, so `implied-by-opposite-GroupCtgy?` drops the right letter-category change.
