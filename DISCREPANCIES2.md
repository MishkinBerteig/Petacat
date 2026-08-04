# DISCREPANCIES2 — Unintended cognitive divergences between Petacat and the Metacat source

> ## STATUS: ALL FINDINGS APPLIED (2026-08-04)
>
> Every finding in this document has been fixed, in the five-phase order of
> Appendix A, across commits `b1fd7a8`, `39a8ec4`, `0417251`, `eff9578`,
> `2720128`, `08e9c54`, `b47ac5a` and `c20abed`. **The findings below are kept as
> written — they are the record of what was wrong, not a to-do list.** Where a
> finding turned out to be inaccurate, the correction is recorded in the commit
> that touched it and summarised under "Corrections" below.
>
> Two deviations from the stated plan, both deliberate: **RU-5** was pulled
> forward into phase 2, because its own fix plan requires the possible-rule-types
> that WS-2 stores — they are one change. And phase 4 was run in three rounds
> (bonds, then groups, then bridges) rather than one, per this document's own
> advice that group fixes change the workspace states the bridge fixes are tested
> against.
>
> ### What it did to behaviour
>
> The binding constraint turned out to be bridge formation. RU-5 restored the
> reference's gate that no rule may be abstracted until every letter of both
> strings is covered by rule-describable bridges (`rules.ss:413-416`), and
> Petacat passed it far too rarely — so until section 11 landed, the engine's
> answers were mostly the rare vacuous verbatim rule translating into the
> modified string. Measured over 40 seeds, before and after section 11:
>
> | | `abc→abd; xyz` | `abc→abd; mrrjjj` |
> |---|---|---|
> | mean rules built per run | 0.20 → 2.00 | 0.375 → 1.20 |
> | runs building any rule | 8/40 → 40/40 | 13/40 → 40/40 |
> | answers found | 3/40 → 37/40 | 8/40 → 40/40 |
>
> Two results are worth naming. **RU-1 made the extrinsic rule family reachable
> for the first time**: an instantiated swap clause was built with its dimensions
> discarded, so every one applied as a no-op and the whole of §3.3.4 was dead. With
> it fixed, `eqe→qeq; abbba?` answers `baaab` — the dissertation's own documented
> answer for that problem (§5.2.3) — on 42.7% of 300 seeds, having never once
> produced it before. And **GR-5 made Metacat's nested group hierarchy
> representable**: `abc→abd; mrrjjj` now builds the nested successor group on the
> Length facet spanning all six letters over `[m][rr][jjj]`, the 1-2-3 reading,
> which the old "supergroup destroys its own constituents" path could not express.
>
> Not everything moved in the flattering direction, and the honest cases are
> recorded in the commits: **GR-2** lowers the rule rate on short successor
> problems (successor groups score 40 in the reference, not the ~96 Petacat gave
> them), and **RU-6** raises the give-up rate on `abc→abd; xyz` by making the best
> rule of *n* dominate at rank-relative strength. Both were verified faithful
> against the Scheme line by line and kept.
>
> ### Corrections to this document
>
> Fourteen findings were wrong in some respect, and each was verified against the
> Scheme before being overruled. The consequential ones: the **bond-relevance
> rounding** row is inverted — `100*` *is* `(round (* 100 x))`, so the Scheme
> rounds and Petacat already matched; following its fix plan would have introduced
> the divergence it claimed to remove. **GR-2**'s stated consequence has the wrong
> sign (directed group strengths shift *down*). **SL-3**'s fix plan asserts the
> centre letter of `abcde` is `middle` while its own parenthetical cautions
> otherwise — the parenthetical is right, and the reference in fact contradicts
> *itself* here, since `run.ss:297-301` attaches a `middle` description by index
> arithmetic that `middle-in-string?` would deny. **BD-8**'s fix plan would have
> introduced a new bug (`build_structure` returns False for duplicates too, and the
> duplicate jolt is a large share of the activation stream). **SN-2** and **SN-3**
> claim dead code was present and faithful when `Coderack.clear` already existed,
> `clamp_salience` did not exist at all, and `undo_last_clamp_raw` was not the
> faithful call. **TM-2**'s "faithful pieces" were not faithful:
> `compare_rule_signatures` flatten-and-zipped, so two structurally unrelated rules
> could measure *zero* apart. And **SL-1**'s claim that spread amounts are already
> rounded correctly on both sides is false — Petacat pre-divides, which mis-rounds
> exact halves and makes float32 and float64 disagree by a whole activation unit.
> That last one is unreachable at the shipped `spreading_activation_threshold` of
> 100 and becomes reachable the moment the slider is lowered; it is pinned by a
> test and is the one item here left as a **new finding rather than a fix**.
>
> ### Defects found while fixing, not in this document
>
> A group's image took its letter relation from its bonds' category, so a sameness
> group carried `plato-sameness` — outside `new-start-letter`'s declared domain
> (`images.ss:164`) — and `abc→aabbcc; kkjjii?` answered **`kksamejjiisame`**, an
> answer string with a relation's name embedded in it. Also: `state_graph` omitted
> the workspace's three mapping strengths and its average unhappiness from capture,
> so restored runs diverged; `MlxBackend.combine_object_values` materialised its
> float coefficients as float32 even against a float64 array, so the mlx-cpu
> backend was not the float64 backend it claims to be; `get_equivalent_bond` was
> not symmetric for sameness bonds although `add-bond` files them under both key
> orders; `unclamp_concept_pattern` unfroze every node in the Slipnet, so ending
> one clamp released every other; and `evaluate_progress` excluded bonds by testing
> for an attribute no structure class in the port has.
>
> ### Superseded by measurement — see `ORACLE-COMPARISON.md`
>
> Several judgements in this document, and in the commits that closed it, end with
> some version of "I cannot tell from the source alone whether the reference
> behaves this way". That limit is gone. Metacat's repository now carries a
> saturated stopping-state benchmark over all nineteen demo problems, produced by
> the reference implementation running headless (`424feb0`, `d9dddee`), and
> `ORACLE-COMPARISON.md` records Petacat against it.
>
> The headline: eight of nineteen problems agree closely (total-variation distance
> ≤ 0.06), median TVD 0.20, and the disagreement clusters into a small number of
> named patterns rather than scattering — chiefly that **Metacat frequently answers
> with the target string unchanged where Petacat exhausts its alternatives and gives
> up**. That single pattern accounts for most of the remaining distance.
>
> It also **overturns a conclusion reached in this repository**: an investigation of
> `abc→cba; mrrjjj` traced bridge choice, swap-dimension selection and
> concept-mapping association values line by line, found every step faithful, and
> concluded the 70% unchanged-target rate was acceptable. The benchmark shows the
> reference answers `jjjrrm` 85.1% of the time and the unchanged target only 8.7%.
> The mechanism did match; the outcome did not. Faithful parts are not proof of
> faithful behaviour, and this is the case that demonstrates it.
>
> ### On the test suite
>
> `tests/module/test_dissertation_parity.py`'s frequency-distribution guards were
> **deleted**, not retuned. Their floors were calibrated by sampling Petacat before
> this repair, so they encoded the very defects it removes and failed precisely
> when the engine moved closer to the reference. The invariants and mechanism tests
> remain; that file is now 110 passed, 0 failed on both numeric backends, from
> roughly 40 red at the start. `tests/fixtures/expected_range.json` is likewise a
> pre-repair sample and **has not been regenerated** — the smoke sampling used
> throughout was compared against it for orientation only, never as an oracle.

**Scope.** A static, code-only parity scan of Petacat's cognitive engine against the
Metacat Scheme source (`../Metacat/*.ss`). No code was executed. The reference is the
Scheme *code*, not the dissertation and not any project documentation ("code is the
law"). The scan covered all seven architectural components plus the codelet bodies,
the main loop, and the self-watching machinery, via twelve parallel subsystem audits
whose findings were then independently re-verified against both sources. Every HIGH
finding below was confirmed by direct reading of the cited lines; most were found
independently by two or more audits.

**What was excluded.** Petacat's declared intentional divergences were not reported:
database/JSON-driven configuration and the codelet DSL as mechanisms; the numeric
substrate's multiple backends (the pure-Python reference was compared instead); the
persistence modes/sinks; free-running parallelism and coderack shards; per-run id
counters; the `spreading_activation_threshold` parameter (its default of 100
reproduces the Scheme, verified); the 75-theme count; Training Sessions sharing
Episodic Memory; and the clamp-expiry tick mechanism (verified equivalent in effect
for trace clamps). Everything else that changes what is computed was fair game.

**Relationship to prior audits.** `DISCREPANCIES.md` is a documentation/API audit —
different scope, no overlap. Commit `34535e3` ("Port fidelity: close nine conceptual
gaps") already fixed nine cognition gaps; everything below is present in the tree at
that commit, i.e. it is what that pass did not catch.

**The standard applied.** Petacat's foundation must be *process-equivalent*: for a
given problem, the set of reachable stopping states and the cognitive processes that
produce them must match Metacat's, even if exact results or frequencies vary. A
divergence is reported when it changes reachable structures/answers, their
probabilities, or the behavior of the self-watching loop. "Unintended" was judged
from the code itself: nearly every finding either contradicts the docstring/comment
sitting next to it (which cites the Scheme line it fails to match), leaves a faithful
Petacat implementation stranded as dead code, or silently drops a mechanism with no
compensation anywhere in the tree.

**Severity.** **HIGH** — changes which structures/answers are reachable or their
probabilities materially, or breaks a self-watching mechanism. **MEDIUM** — changes
dynamics/timing in ways that plausibly preserve the reachable set. **LOW** — edge
cases and small distribution perturbations.

**After fixing.** Almost every HIGH finding moves the expected-range oracle.
`tests/fixtures/expected_range.json` will need smoke testing (100 runs, all problems)
after each fix phase — and newly appearing stopping states should be reviewed by you
before being accepted into the expected sets, since a new answer may be evidence of a
fix or of a new bug.

---

## Index

| § | ID | Finding | Severity |
|---|----|---------|----------|
| 1 | CC-1 | `temp_adjusted_probability` low-probability target inverted; `p=1.0` shortcut | HIGH |
| 1 | CC-2 | Temperature exponent missing from all weighted object choice | HIGH |
| 1 | CC-3 | Structure fights: no temperature adjustment, stale strengths, floors, wrong weights | HIGH |
| 1 | CC-4 | `fully_active` is `>= 50`; Scheme requires exactly 100 | HIGH |
| 1 | CC-5 | Probabilistic jump to full activation fires from any activation > 0 | HIGH |
| 1 | CC-6 | 0.1 weight floors make zero-weight candidates reachable | MEDIUM |
| 2 | SN-1 | Snag clamps temperature at its current value instead of setting it to 100 | HIGH |
| 2 | SN-2 | Snag response omits the restart: no purge, no coderack flush, no reseed | HIGH |
| 2 | SN-3 | `SnagEvent.activate` is never called; snag concept pattern never built | HIGH |
| 2 | SN-4 | Snag theme pattern from Themespace dominance, not the failed mapping's CMs | HIGH |
| 2 | SN-5 | Post-snag progress measured over Trace events, not new Workspace structures | HIGH |
| 3 | CL-1 | Codelet-pattern clamps: `max` not replace, no re-binning, no posting override | HIGH |
| 3 | CL-2 | `against-background` complement missing from the rule-codelet clamp | HIGH |
| 3 | CL-3 | Theme-associated concept patterns never clamped | MEDIUM |
| 3 | CL-4 | Temperature stays clamped forever after a clamp ends the snag period | HIGH |
| 4 | JO-1 | Jootser's justify outcomes inverted: settle-for-answer became halt | HIGH |
| 4 | JO-2 | Invented give-up after >5 snags | HIGH |
| 4 | JO-3 | Justify-clamp jootsing gate hardcoded to 1 | MEDIUM |
| 4 | JO-4 | Clamp-event equivalence uses ordered rule lists, not set equality | MEDIUM |
| 4 | JO-5 | Progress-watcher: wrong answer-finder urgency; extra posting channel | MEDIUM |
| 5 | JU-1 | `if translated_rule.supporting_bridges or True:` — always justified | HIGH |
| 5 | JU-2 | `permission_to_clamp()` called without the codelet count | HIGH |
| 5 | JU-3 | Vacuous-translation guard (`ref-objs1`) missing | MEDIUM |
| 5 | JU-4 | Matching-rule `supported?` test inverted for bridge-less rules | MEDIUM |
| 5 | JU-5 | Justify clamps never apply their codelet patterns | HIGH |
| 5 | JU-6 | Smaller justify divergences (translated-rule theme pattern, coattails, quality, retention) | MEDIUM |
| 6 | SL-1 | Slipnet decay not rounded; the integer plateau is lost | MEDIUM |
| 6 | SL-2 | Missing initial activations (`plato-letter`; `plato-object-category`) | MEDIUM |
| 6 | SL-3 | `middle` descriptor predicate is letters-only index arithmetic | HIGH |
| 6 | SL-4 | Property-link association gate missing from the description scout | HIGH |
| 6 | SL-5 | `self_watching_enabled=False` wrongly disables Themespace spreading | LOW |
| 7 | CR-1 | Eviction weight drops the temperature-scaled bin-urgency term | HIGH |
| 7 | CR-2 | Bin selection weights unrounded | MEDIUM |
| 7 | CR-3 | rule-builder no longer posts the answer-finder/justifier | HIGH |
| 7 | CR-4 | Initial codelet population is half the reference's; reposts stamped 0 | MEDIUM |
| 7 | CR-5 | Deferred-batch posting replaced by per-post eviction | MEDIUM |
| 7 | CR-6 | Scout→evaluator urgencies computed from the wrong quantities | MEDIUM |
| 8 | WS-1 | Temperature (and description-scout posting) fed intra-string unhappiness only | HIGH |
| 8 | WS-2 | Rule possibility computed then discarded; temperature/posting keyed on wrong predicates | MEDIUM |
| 8 | WS-3 | Scout-count aggregates: wrong predicates, deterministic ratios, no blur | MEDIUM |
| 8 | WS-4 | Thematic-scout count uses intra- for inter-string unhappiness, floored at 1 | HIGH |
| 8 | WS-5 | Workspace intra-string unhappiness aggregated per-string, unweighted | MEDIUM |
| 8 | WS-6 | Justify mode: strings' `justify_mode` flag is never set | HIGH |
| 9 | BD-1 | Top-down bond scouts hardcode the letter-category facet | HIGH |
| 9 | BD-2 | Category bond scout tests only one descriptor order | MEDIUM |
| 9 | BD-3 | Bond-builder incompatibility drastically narrower; `add_bond` overwrites | HIGH |
| 9 | BD-4 | Bond/group local density walks bond chains, not positional neighbors | MEDIUM |
| 9 | BD-5 | Neighbor choice: same-nesting-level filter vs all-levels salience pick | HIGH |
| 9 | BD-6 | Top-down string choice drops the relevance term; includes the answer string | MEDIUM |
| 9 | BD-7 | Description scouts: wrong salience key; early duplicate fizzles | MEDIUM |
| 9 | BD-8 | Bond-builder activates categories after lost fights; bond-description routing | LOW |
| 10 | GR-1 | Length descriptions attached unconditionally at group construction | HIGH |
| 10 | GR-2 | Group internal strength: wrong bond factor; singletons collapse to 5 | HIGH |
| 10 | GR-3 | `group-evaluation-probability` not ported | HIGH |
| 10 | GR-4 | Bond scanning ignores facet/direction consistency; no bond flipping | HIGH |
| 10 | GR-5 | Group incompatibility = any overlap; supergroups destroy their constituents | HIGH |
| 10 | GR-6 | Breaking has no cascade (groups, bonds, bridges); breaker lacks the joint case | HIGH |
| 10 | GR-7 | Group builder: no bridge fights, no consolidation branches | HIGH |
| 10 | GR-8 | Group scout details: string choice, scan direction, scan-count distribution, whole-string walk | MEDIUM |
| 10 | GR-9 | Group activation jolts and evaluator urgency | MEDIUM |
| 10 | GR-10 | Duplicate-group handling, singleton/middle descriptions, stale-middle cleanup | MEDIUM |
| 11 | BR-1 | Slippage-admissibility gate absent from bridge scouts | HIGH |
| 11 | BR-2 | Distinguishing identity/opposite requirement absent | HIGH |
| 11 | BR-3 | Flipped-bridge proposal absent from ordinary scouts | HIGH |
| 11 | BR-4 | Concept-mappings computed from all descriptions, not relevant ones | HIGH |
| 11 | BR-5 | Build-time CM augmentation absent (Length CM, bond-CM list, symmetric slippages) | HIGH |
| 11 | BR-6 | Bridge builder fights no incompatible bonds or enclosing groups | HIGH |
| 11 | BR-7 | Bridge fight weights use one object's span, not the bridge letter-span | HIGH |
| 11 | BR-8 | Bridge-incompatibility test drops three Scheme refinements | HIGH |
| 11 | BR-9 | Duplicate-bridge merge path absent | MEDIUM |
| 11 | BR-10 | Builder relevance guard, CM activation stream, and follow-up codelets missing | MEDIUM |
| 11 | BR-11 | Bridge-evaluator urgency over all CMs instead of distinguishing CMs | MEDIUM |
| 11 | BR-12 | Smaller bridge/CM divergences (bundle) | MEDIUM |
| 12 | RU-1 | Extrinsic (swap) clauses lose their dimensions — swap rules are no-ops | HIGH |
| 12 | RU-2 | Rule translation draws slippages from the wrong bridges, without Scheme's filters | HIGH |
| 12 | RU-3 | The stochastic per-dimension slippage-ignore (p=0.4) is missing | HIGH |
| 12 | RU-4 | Conflict detection reduced to same-object-same-dimension | HIGH |
| 12 | RU-5 | Verbatim rules whenever no bridges exist; no rules-possible gate | HIGH |
| 12 | RU-6 | Rule strength is raw quality, not rank-relative quality | HIGH |
| 12 | RU-7 | Rule evaluator/builder: wrong acceptance curve, no incumbent revision | MEDIUM |
| 12 | RU-8 | Rule quality subformulas restructured; verbatim quality 10 vs 40 | MEDIUM |
| 12 | RU-9 | Whole-string object-descriptions: no spanning-group resolution or translation | MEDIUM |
| 12 | RU-10 | Translated-rule quality copied, not recomputed; bookkeeping absent | MEDIUM |
| 12 | RU-11 | Translated-clause validity check missing; invalid clauses silently no-op | MEDIUM |
| 12 | RU-12 | Smaller rule/image divergences (bundle) | MEDIUM |
| 13 | TM-1 | Answer-description vertical theme pattern built from a different recipe | HIGH |
| 13 | TM-2 | Reminding distance diverges in three components | HIGH |
| 13 | TM-3 | Snag identity judged by English text; clause lists not stored | MEDIUM |
| 13 | TM-4 | Slippage events from CM accretion never occur | MEDIUM |
| 13 | TM-5 | Smaller trace/memory divergences (bundle) | MEDIUM |
| 14 | TH-1 | No Themespace boost when a bridge is built | MEDIUM |
| 14 | TH-2 | Group bond descriptions leak into theme boosting and support tests | MEDIUM |
| 14 | TH-3 | Bridge–theme incompatibility tests description *presence*, not *possibility* | MEDIUM |
| 14 | TH-4 | Translated rules never receive their bridge-derived theme pattern | MEDIUM |
| 15 | ML-1 | `init_mcat` omits the initial workspace-values update | MEDIUM |
| 15 | ML-2 | Codelet count incremented before execution; empty-rack timing | LOW |
| 16 | LO-* | Low-severity bundle | LOW |

---

# 1. Cross-cutting stochastic machinery

These five findings sit underneath every subsystem. Fixing anything else first would
be measuring against a moving target: the temperature-controlled sharpening of
choices — the "parallel terraced scan" itself — is largely absent from the port.

## CC-1. `temp_adjusted_probability` low-probability target inverted; `p=1.0` shortcut — HIGH

**Metacat** (`formulas.ss:20-29`, with `1-` defined as *1 minus x* at
`utilities.ss:500`): for `prob <= 0.5`,

```scheme
(let ((low-prob-factor (max 1.0 (truncate (abs (log10 prob))))))
  (min 0.5 (+ prob (* (% (10- (sqrt (100- *temperature*))))
                      (- (expt 10 (1- low-prob-factor)) prob)))))
```

The interpolation target is `10^(1 − lpf)`: a probability of 0.005 (lpf 2) is nudged
toward **0.1**; 0.0005 (lpf 3) toward **0.01**. Small probabilities stay small; they
merely climb one decade at high temperature. There is no `prob = 1.0` special case:
1.0 falls into the high branch and becomes `max(0.5, 1 − adjustment)` — e.g. 0.9 at
T=100.

**Petacat** (`server/engine/formulas.py:32-43`):

```python
if prob == 1.0:
    return 1.0
...
low_prob_factor = max(1.0, math.floor(abs(math.log10(prob))))
target = 10 ** (low_prob_factor - 1)
return min(0.5, prob + adjustment * (target - prob))
```

`10^(lpf − 1)` is the reciprocal decade: for prob 0.005 the target is **10**, for
0.0005 it is **100**, so the `min` clamp delivers ≈ **0.5** at any temperature above
zero. The Scheme's `1-` was read as a decrement operator; Metacat defines it as
`(λ (x) (- 1 x))`.

**Why unintended.** The docstring cites `formulas.ss:20-29` as its source. The two
formulas coincide for prob > 0.01, which is why ordinary evaluator calls masked it.

**Consequences.**
- `length_description_probability` (Scheme values like `0.5^27 ≈ 7.5e-9` for a cold
  3-group) and `single_letter_group_probability` return ≈ 0.5 instead of fractions of
  a percent — a ~10⁷× inflation. Length descriptions and singleton groups, the
  gateways to the length-facet readings (`mrrjjj` 1-2-3), fire at coin-flip rates.
- Every consumer with a genuinely small probability is inflated to 0.5; every
  consumer with prob exactly 1.0 (strength-100 structures at evaluators; weakness-100
  structures at the breaker) passes/fires with certainty where Metacat retains up to
  a 10% margin.

**Fix plan.**
1. In `temp_adjusted_probability` (`formulas.py`), change the target to
   `10.0 ** (1 - low_prob_factor)`.
2. Delete the `if prob == 1.0: return 1.0` shortcut; the existing `> 0.5` branch
   already computes `max(0.5, 1 − ((1−prob) + adjustment·prob))`, which yields
   `1 − adjustment` at prob 1.0, matching the Scheme.
3. Unit tests: table-test the curve at prob ∈ {1e-8, 5e-4, 5e-3, 0.05, 0.5, 0.9,
   1.0} × T ∈ {0, 50, 100} against hand-computed Scheme values. Note Scheme's
   `truncate` and Python's `floor` agree for the positive inputs reachable here.
4. Regenerate the expected range afterward; this fix alone will move it.

## CC-2. Temperature exponent missing from all weighted object choice — HIGH

**Metacat**: every object selection goes through `choose-object`
(`workspace.ss:499-502`, `workspace-strings.ss:340-343`):

```scheme
(stochastic-pick objects (temp-adjusted-values weights))
```

`temp-adjusted-values` (`formulas.ss:32-35`) raises each weight to
`(100−T)/30 + 0.5` — exponent 0.5 at T=100 (flattened, near-uniform) up to ≈3.83 at
T=0 (sharply greedy). Consumers: the from-object of every bond scout
(`bonds.ss:189,242,294`), both objects of the bottom-up bridge scout
(`bridges.ss:913-916`), object1 of the important-object bridge scout
(`bridges.ss:984`), both description scouts (`descriptions.ss:107,132`), and both
top-down group scouts (`groups.ss:444,514`).

**Petacat**: `WorkspaceString.choose_object` (`workspace.py:283-287`) and
`Workspace.choose_object` (`workspace.py:699-706`) do a raw `rng.weighted_pick` over
`_object_weight` values. The DSL exposes `temp_adjusted_vals` (`builtins.py:74`) but
no codelet body calls it; `builtins.choose_object`/`choose_string_object`
(`builtins.py:156-193`) and the staleness view all use raw weights.

**Why unintended.** The faithful helper exists and is exported to the DSL namespace;
nothing uses it on the selection path.

**Consequences.** At low temperature Petacat's scouts stay as flat as at high
temperature — a salience-60 vs salience-30 object is 14:1 in Metacat at T=0, 2:1 in
Petacat at every temperature. The exploration→exploitation schedule of *attention* is
gone; which objects get structures, and when, diverges over the whole run on every
problem. This is the single most pervasive divergence found.

**Fix plan.**
1. Thread the current temperature into the two `choose_object` implementations —
   cleanest is to make the DSL builtins (`choose_object`, `choose_string_object`,
   `choose_neighbor`'s salience pick, and the staleness `_choose_from_view`) apply
   `temp_adjusted_values(weights, ctx.temperature.value, ctx.meta)` before
   `weighted_pick`, since `ctx` is in scope there; keep `WorkspaceString.choose_object`
   accepting an optional pre-adjusted weight list so non-DSL callers can opt in.
2. Do **not** adjust the important-object scout's object2 pick — the Scheme uses raw
   `stochastic-pick-by-method` there (`bridges.ss:1014-1015`); Petacat already
   matches. Audit each call site against its Scheme line before converting.
3. Scheme rounds each adjusted weight (`round` in `temp-adjusted-values`); Petacat's
   `temp_adjusted_values` already does — verify.
4. Unit test: fixed weight vector, T ∈ {0, 50, 100}, assert selection frequencies
   against the exponentiated distribution.

## CC-3. Structure fights: no temperature adjustment, stale strengths, floors, wrong weights — HIGH

**Metacat** (`workspace-structures.ss:70-78`):

```scheme
(define wins-fight?
  (lambda (challenger challenger-weight defender defender-weight)
    (tell challenger 'update-strength)
    (tell defender 'update-strength)
    (stochastic-pick '(#t #f)
      (temp-adjusted-values
        (list (* challenger-weight (tell challenger 'get-strength))
              (* defender-weight (tell defender 'get-strength)))))))
```

Both parties' strengths are recomputed at fight time, and the contest sharpens with
falling temperature: 60-vs-40 is ≈0.83 for the stronger side at T=0, ≈0.55 at T=100.

**Petacat** (`builtins.py:779-794`): linear ratio of stale strengths with a floor —

```python
p_strength = max(1.0, proposer.strength * proposer_weight)
o_strength = max(1.0, opponent.strength * opponent_weight)
win_prob = p_strength / total
```

No `update_strength()`, no temperature, and a strength-0 challenger (probability
exactly 0 in Scheme) gets a nonzero chance.

Additionally the fight *weights* diverge from the Scheme builders
(`builtins.py:708-776`):

| Fight | Scheme weights | Petacat |
|---|---|---|
| bond vs incompatible groups (`bonds.ss:379-382`) | 1 vs **max letter-span over all incompatible groups** (one shared weight) | each group's own span |
| bond vs incompatible bridges (`bonds.ss:385-398`) | 2 vs 3 | fight absent (BD-3) |
| group vs same-category groups (`groups.ss:673-680`) | **group length** (constituent count) | letter span |
| group vs bonds-to-flip (`groups.ss:652-664`) | letter-span vs 1 | fight absent (GR-7) |
| group vs incompatible bridges (`groups.ss:685-692`) | 1 vs 1 | fight absent (GR-7) |
| bridge vs bridge (`bridges.ss:1246-1254`) | bridge letter-span = span(obj1) + span(obj2), both sides | `object1.span` only |
| bridge vs incompatible bond (`bridges.ss:1259-1276`) | 3 vs 2 | fight absent (BR-6) |
| bridge vs bond's enclosing group | 1 vs 1 | fight absent (BR-6) |

**Consequences.** Build/break outcomes shift at every temperature; at low temperature
Metacat locks in strong interpretations near-deterministically while Petacat keeps
overturning them at the linear rate. Every bond, group, and bridge build over an
incumbent goes through this function.

**Fix plan.**
1. Rewrite `_wins_fight`: call `update_strength()` on both parties, drop the
   `max(1.0, …)` floors, apply `temp_adjusted_values` to the two weighted strengths,
   then a two-way weighted pick (all-zero → uniform, which `rng.weighted_pick`
   already provides).
2. Fix the weights in `_get_incompatible_structures` per the table (same-category
   group fights use `len(group.objects)`; bridge fights use
   `obj1.span + obj2.span` on both sides; bond-vs-group uses the single shared
   max-letter-span weight).
3. The missing fights themselves are BD-3, GR-7, BR-6 below.
4. Unit tests per row of the table with hand-computed probabilities at T ∈ {0, 100}.

## CC-4. `fully_active` is `>= 50`; Scheme requires exactly 100 — HIGH

**Metacat** (`slipnet.ss:390-404`): two distinct predicates —

```scheme
(define fully-active?   (lambda (node) (= (tell node 'get-activation) %max-activation%)))  ; == 100
(define above-threshold? (lambda (node) (>= (tell node 'get-activation) 50)))
```

`fully-active?` (exact 100) gates: link shrinking / degree-of-association
(`slipnet.ss:90-91, 334-339`), concept-mapping relevance
(`concept-mappings.ss:107-109`), and description relevance (`descriptions.ss:67`).
`above-threshold?` (≥ 50) is used *only* for top-down codelet posting
(`slipnet.ss:212-213`).

**Petacat** (`slipnet.py:179-180`):

```python
def fully_active(self, threshold: int = 50) -> bool:
    return self.activation >= threshold
```

Every consumer uses the default: `degree_of_assoc` (`slipnet.py:278`), link length
shrinking (`slipnet.py:516-519`), CM relevance (`concept_mappings.py:155-158`),
description relevance (`descriptions.py:171-173`), and
`workspace_objects.py:693-694`. Only the spreading path escapes, because the
run-parameter default (100) gates it separately.

**Consequences.** Throughout the 50–99 activation band — where the system spends
most of its time — links are shrunk early, degrees of association are inflated
(succ: 40 → 76, so bond factor `11·√assoc`: 70 → 96), slippages get drastically
cheaper (opposite coattail probability 0.20 → 0.68), and descriptions/CMs count as
"relevant" at half the required activation, inflating raw importance, bridge
internal strengths, and relevance-gated candidate sets everywhere.

**Fix plan.**
1. Change `fully_active` to `self.activation >= 100` (float-safe form of `== 100`;
   activation is capped at exactly 100.0 on flush and jump — verified).
2. Add an explicit `above_threshold(self) -> bool: return self.activation >= 50`
   and switch the top-down posting gate (`runner.py:988-992`) to it, so posting
   keeps the correct ≥ 50 semantics.
3. Audit every remaining `fully_active(` call site against its Scheme line; the
   only ≥ 50 consumer in the Scheme is top-down posting.
4. Unit tests: degree_of_assoc at activation 49/50/99/100; CM relevance at 99 vs
   100.

## CC-5. Probabilistic jump fires from any activation > 0 — HIGH

**Metacat** (`slipnet.ss:387-389, 397-404`): the discontinuous jump draws only for
`partially-active?` nodes — activation in [50, 100):

```scheme
(for* each node in (filter partially-active? *slipnet-nodes*) do
  (stochastic-if* (^3 (% (tell node 'get-activation)))
    (tell node 'update-activation %max-activation%)))
```

**Petacat** (`slipnet.py:305-314`, and the reference backend
`python_backend.py:167-182`): the guard is `if self.activation > 0` — the code
comment claims "(50-99)" but no 50-gate exists.

**Consequences.** A node at 49 jumps to full with p ≈ 0.118 per cycle (Scheme: 0); at
30, p ≈ 0.027; residual activations keep a nonzero jump chance forever. Spurious full
activations then spread, post top-down codelets, shrink links (CC-4), and broaden the
available slippages — the Slipnet is systematically hotter than the reference.

**Fix plan.**
1. Gate the jump on `50 <= activation < 100` in both `slipnet.py`
   (`probabilistic_jump_to_full`) and the numeric backends' jump-candidate selection
   (`python_backend.py`; mirror in numpy/MLX backends and their layout code).
2. Note the RNG-draw count changes (fewer candidates → fewer draws), so seeds will
   produce different runs; that is expected and covered by the expected-range
   oracle, not by bit-identity.
3. Unit test: node at 30 never jumps over many trials; node at 60 jumps at ≈0.216.

## CC-6. 0.1 weight floors make zero-weight candidates reachable — MEDIUM

**Metacat**: `stochastic-pick` (`utilities.ss:443-448`) gives weight-0 items
probability exactly 0; uniform fallback only when *all* weights are 0 (which
Petacat's `rng.weighted_pick` already reproduces).

**Petacat**: `max(0.1, …)` floors appear in `_object_weight` (`workspace.py:42-48`),
`choose_neighbor` (`builtins.py:226`), `choose_string` (`builtins.py:238`),
descriptor/facet picks in several codelet bodies, and the thematic scout
(`themes.py:861-863`).

**Consequences.** Zero-salience objects, zero-support facets, dormant descriptors,
and mapped-to-strength-100 bridge types all stay reachable with small probability
where Metacat excludes them outright. A persistent, small distortion of every
weighted choice, and occasionally a qualitative one (a weight-0 side of a 0-vs-50
contest can win).

**Fix plan.** Remove the floors; rely on `weighted_pick`'s all-zero → uniform
fallback. Grep for `max(0.1` and `max(1.0` / `max(1,` in selection weights across
`server/engine/` and the codelet bodies in `seed_data/codelet_types.json`; each
removal should cite the Scheme line it restores.

---

# 2. The snag response

The snag response — the entry point of the entire self-watching story — is almost
entirely unported. Four independent audits converged on the same set. The Scheme's
`process-snag` (`answers.ss:1153-1193`) performs, in order: record the snag event;
delete every proposed bond/group in all three strings and every proposed bridge; set
`*temperature*` to 100 **and** clamp it; activate the snag event (undo any live
clamp, clamp salience on every snag object, clamp the snag concept pattern); delete
**all** codelets; post the initial codelets afresh; run a full update. Petacat's
`record_snag` (`builtins.py:1085-1148`) records the event, clamps temperature at its
current value, stores a snag description, emits commentary — and the answer-finder
fizzles. Nothing else happens.

## SN-1. Snag clamps temperature at its current value instead of setting it to 100 — HIGH

**Metacat** (`answers.ss:1183-1184`): `(set! *temperature* 100)`,
`(set! *temperature-clamped?* #t)`.

**Petacat** (`builtins.py:1118-1119`):

```python
# Metacat clamps the temperature while it deals with a snag.
ctx.temperature.clamp(ctx.temperature.value)
```

**Why unintended.** The comment claims to reproduce Metacat; a snag occurs precisely
when a strong rule was about to apply, i.e. at *low* temperature, so this pins the
run **greedy** — the exact opposite of the reference's maximally-random escape
regime. `tests/module/test_dissertation_parity.py:487-489` encodes the inverted
belief ("to force focused exploration rather than more random search").

**Consequences.** Post-snag search stays locked on the interpretation that just
failed. On snag-prone problems (`abc→abd; xyz→?`) both the escape probability and
the escape *routes* change fundamentally.

**Fix plan.** `ctx.temperature.value = 100` (or a `set_and_clamp(100)` method) before
clamping; fix the parity test to assert 100. One line, but do a deep smoke test on the
`xyz` family so 1000 runs is appropriate after this fix.

## SN-2. Snag response omits the restart — HIGH

**Metacat** (`answers.ss:1176-1193`): proposed-structure purge, `delete-all-codelets`,
`post-initial-codelets`, `update-everything`.

**Petacat**: none of it. The pre-snag codelet population — including evaluators and
builders of the failed interpretation — keeps running; no fresh bottom-up scouts are
posted; no immediate update cycle runs.

**Consequences.** Post-snag dynamics are those of an uninterrupted run. Combined with
SN-1, the "empty the Coderack and post the initial codelets afresh" reset that the
architecture's escape behavior is built on does not exist.

**Fix plan.**
1. Add `Coderack.clear()` (the state-restore path already knows how to empty it) and
   call it in `record_snag`, then repost the initial codelets **stamped with the
   current codelet count** (see CR-4), then run one `update_everything`.
2. Proposed structures in Petacat exist only as codelet arguments (no proposed
   registries), so the Scheme's explicit proposed-structure purge is *subsumed by
   the rack flush* — document that equivalence in the code rather than adding
   registries.
3. e2e/module test: drive a run to a snag (seeded) and assert the rack contents
   immediately after are exactly the initial population.

## SN-3. `SnagEvent.activate` is never called; the snag concept pattern is never built — HIGH

**Metacat** (`answers.ss:1187` → `trace.ss:1155-1162`): activation undoes any live
clamp, calls `clamp-salience` on each snag object (attention returns to the failure
site), and clamps the snag concept pattern — the snag objects' descriptors pinned at
max activation (`trace.ss:1042-1048`).

**Petacat**: `SnagEvent.activate` exists (`trace.py:442-462`) but has zero callers
(verified: only `ClampEvent.activate` is invoked, from `jootsing.py:243,431` and
`justify.py:347`). The event is constructed with `snag_concept_pattern=None`
(`builtins.py:1108-1115`), so even a call would clamp nothing.
`trace.undo_last_clamp_raw` is likewise dead on this path.

**Consequences.** (a) A snag during a clamp period does not terminate the clamp;
(b) snag objects get no salience boost, so post-snag attention is not drawn to the
impasse; (c) the snag descriptors get no Slipnet clamp. All three are inputs to how
the subsequent jootsing episode unfolds.

**Fix plan.**
1. In `record_snag`, build the snag concept pattern from the snag objects'
   descriptors (dimension nodes at max activation, per `trace.ss:1042-1048`) and
   pass it to `SnagEvent`.
2. Call `event.activate(...)` after `add_snag_event`, implementing the three Scheme
   actions; `clamp_salience` already exists on workspace objects (verified — the
   clamped-salience → 100 path is live).
3. Unit test: snag during a live clamp → clamp undone, snag-object salience 100,
   descriptor nodes frozen at 100.

## SN-4. Snag theme pattern from Themespace dominance, not the failed mapping's CMs — HIGH

**Metacat** (`trace.ss:1031-1039, 1061-1067`): the pattern is derived from the
concept-mappings of the snag objects' vertical bridges (all vertical CMs when no
bridges exist) — the complete set of (dimension, relation) pairs the failed
interpretation actually rested on. `make-snag-event` also records the snag **type**
(SWAP / CONFLICT / CHANGE) and the snag concept pattern; snag equality is
translated-rule structural equality plus equivalent object sets
(`trace.ss:1150-1155`).

**Petacat** (`builtins.py:1096-1116`): `theme_pattern =
ctx.themespace.get_dominant_theme_pattern("vertical")`; `snag_type` always defaults
to `"change"`; `snag_bridges` / `snag_concept_mappings` / `snag_concept_pattern`
never populated.

**Consequences.** Dominance requires a >90-point cluster lead; clusters with two
live themes contribute nothing, and the pattern can be empty. The jootser's
snag-overlap table (`jootsing.py:325-352`) therefore operates on systematically
smaller — often empty — patterns: jootsing triggers late or not at all, and the
negative clamp it builds is narrower than the failure warrants. The stored
`SnagDescription` inherits the same defect (Scheme: `memory.ss:447-454` keeps the
dominant *relations of the CM-derived pattern*, a different computation).

**Fix plan.**
1. Port `get-snag-theme-pattern`: collect the snag objects' vertical bridges'
   concept-mappings (fallback: all vertical CMs), map each to
   (dimension, label-relation), dedupe.
2. Thread the actual failure kind out of `apply_rule` (the `ImageFailure` type
   already carries objects; add a `kind` field set at the three Scheme failure
   sites — swap `rules.ss:1433-1447`, conflict `rules.ss:1321-1338`/RU-4, change
   everywhere else) and store it as `snag_type`.
3. Store the snag concept pattern (SN-3) and the clause lists (TM-3).
4. Unit test: construct a workspace where the dominant vertical pattern is empty but
   the snag bridges carry CMs; assert the event pattern is nonempty and matches the
   CM derivation.

## SN-5. Post-snag progress measured over Trace events, not new Workspace structures — HIGH

**Metacat** (`trace.ss:96-103, 182-187`, evaluator at `trace.ss:1069-1073`): every
event snapshots the live structure list at creation; progress-since-last-snag = max
strength over *current workspace structures minus the snag-time set*, bonds
excluded. Every new bridge, group, or rule counts at its live strength. This feeds
the stochastic snag exit (`run.ss:299-302`: exit with probability progress/100 per
update cycle).

**Petacat** (`trace.py:978-1013`): iterates *Trace events* recorded since the snag,
scoring each event's attached structure plus `event.get_strength()`. Ordinary new
bridges and sub-threshold groups — the bulk of the Scheme's progress signal — are
invisible (group events need importance ≥ 100, CM events ≥ 65, rule events ≥ 67).
Conversely `ClampEvent.get_strength()` is 100, so any post-snag clamp (e.g. the
jootser's own snag-response clamp) makes the exit **certain** at the next cycle.

**Consequences.** Snag periods (with SN-1's clamped temperature) last far too long
when rebuilding is ordinary, and end instantly once jootsing clamps — wrong in both
directions. Everything downstream of a snag inherits this.

**Fix plan.**
1. Snapshot the workspace structure list on `SnagEvent` at creation (ids or object
   refs; the state-graph capture machinery shows how to reference structures
   stably).
2. Reimplement `progress_since_last_snag` as: max over `current structures −
   snapshot`, using `struct.strength` with bonds excluded, dropping the
   `event.get_strength()` term entirely.
3. Unit tests: (a) new unrecorded bridge of strength 60 → progress 60; (b) a
   post-snag clamp event alone → progress 0.

---

# 3. Clamp machinery

## CL-1. Codelet-pattern clamps: `max` not replace, no re-binning, no posting override — HIGH

**Metacat** (`coderack.ss:95-105, 194-197, 447-455, 472-473`): clamping a codelet
type (a) makes every **new** codelet of the type take exactly the clamped urgency,
(b) **re-bins every codelet already on the rack** to that urgency, (c) restores
original urgencies on unclamp, and (d) overrides the type's **posting probability**
to clamped-urgency/100 — so a snag-response clamp floods the rack with the bottom-up
pattern at probabilities 0.77/0.91 while it lasts.

**Petacat** (`coderack.py:171-173, 342-355`): `codelet.urgency =
max(codelet.urgency, clamped)` on new posts only; existing rack contents untouched;
`unclamp_all` just clears the dict; `_compute_posting_probability`
(`runner.py:816-877`) never consults `clamped_urgencies`.

**Consequences.** During precisely the episodes self-watching exists for — snag
response, jootsing, rule-codelet clamps, justify clamps — the rack composition and
posting mix barely change, where the reference redirects the whole system.

**Fix plan.**
1. Store `original_urgency` on clamp; set (not max) the clamped urgency for new
   posts; re-bin existing codelets of the type on clamp and restore on unclamp
   (the bins are lists; move entries and update the incremental per-bin counters and
   `Σ time_stamp` aggregates).
2. In `_compute_posting_probability`, return `clamped_urgency/100` for clamped
   types before any workspace-driven computation.
3. Module test: apply the bottom-up pattern clamp, assert both rack re-binning and
   the posting probabilities.

## CL-2. `against-background` complement missing — HIGH

**Metacat** (`trace.ss:1574-1581`, used at `jootsing.ss:326-331` and by manual
clamps): the rule-codelet clamp is `against-background %very-low-urgency%
%rule-codelet-pattern%` — the three rule types clamped at 77/91/91 **and all other
24 codelet types clamped at 21**, which (via CL-1(d)) also throttles their posting
to 0.21. The clamp starves everything but rule work.

**Petacat**: the progress-watcher body clamps only the three rule types; no
complement mechanism exists anywhere (grep: no hits).

**Consequences.** The stall-escape ("I still don't see a good way to describe…")
becomes a mild boost instead of a redirection; what gets built during the clamp — and
hence the measured progress that decides whether to lift it — differs.

**Fix plan.** Implement `against_background(background_urgency, pattern)` producing
the full 27-type pattern (complement at very-low urgency), use it for the
rule-codelet clamp (and manual codelet clamps if the UI exposes them); store the
*applied* pattern on the ClampEvent rather than a placeholder dict.

## CL-3. Theme-associated concept patterns never clamped — MEDIUM

**Metacat** (`trace.ss:526-530, 1503-1516`): every clamp event derives a concept
pattern from each clamped theme pattern — the theme's dimension node pinned at 100,
and for `opposite` relations `plato-opposite` pinned at 100 (positive theme) or **0**
(negative theme, actively suppressing "opposite" under a negative snag-response
clamp) — and clamps it in the Slipnet on activation. Clamping a node can also emit
concept-activation trace events (`slipnet.ss:139-140`), which the Scheme relies on
for event ordering (`justify.ss:172-174`).

**Petacat**: no `get_associated_concept_pattern` exists; jootser and justify clamps
pass `[]` or only the rules' own concept patterns; `SlipnetNode.clamp` records no
events (`runner.py` samples activation changes only at cycle boundaries, netting out
clamp deltas).

**Consequences.** During clamp periods the Slipnet is not driven toward (or away
from) the clamped themes' concepts — a whole channel of the clamp's influence, and
the Figure 4.12-style `(Opposite)` trace events, are absent.

**Fix plan.** Port `get-associated-concept-pattern`; append the derived patterns to
`clamped_concept_patterns` at ClampEvent construction for every clamp carrying theme
patterns; emit concept-activation events on clamp deltas that clear the importance
threshold (monitor inside `clamp_concept_pattern` rather than waiting for the cycle
sampler).

## CL-4. Temperature stays clamped forever after a clamp ends the snag period — HIGH

**Metacat**: clamp activation calls `undo-snag-condition` (`trace.ss:619`), which
unconditionally does `(set! *temperature-clamped?* #f)` (`trace.ss:188-196`).

**Petacat** (`trace.py:314`): `ClampEvent.activate` calls
`trace.undo_snag_condition(themespace, slipnet)` — the `temperature` parameter of
`undo_snag_condition` (`trace.py:1015-1041`) is not passed, so `temperature.unclamp()`
is skipped. The runner's snag exit (`runner.py:643-648`) is the only caller that
passes it, and it stops being reached once `within_snag_period` goes False. Verified:
`temperature.unclamp` has no other engine caller.

**Consequences.** Once any jootser or justify clamp activates during a snag period,
temperature stays frozen — at SN-1's pre-snag value — for the rest of the run. The
temperature system is permanently disabled after a snag + jootsing sequence.

**Fix plan.** Give `ClampEvent.activate` access to the temperature (add a parameter,
threaded from its three call sites, which all have `ctx`) and pass it through to
`undo_snag_condition`. Unit test: snag → clamp activation → `temperature.clamped` is
False.

# 4. Jootsing

## JO-1. Jootser's justify outcomes inverted: settle-for-answer became halt — HIGH

**Metacat** (`jootsing.ss:189-235`, `joots-from-justify-clamps`): first a memory
guard — `(if* (tell *memory* 'answer-present? …) (fizzle))`. Then: with **no**
unjustified slippages, post `answer-justifier` at extremely-high urgency and fizzle;
otherwise **report the answer**, carrying the unjustified slippages ("Settled for
unjustified answer", `trace.ss:435`). "Giving up" here means *settling for the
unjustified answer*, not halting.

**Petacat** (`jootsing.py:616-698` + the jootser body in
`seed_data/codelet_types.json`): no memory guard anywhere in the function. The
no-unjustified branch returns `action="post_answer_justifier"`, and the otherwise
branch returns `give_up=True, action="report_unjustified_answer"` — but the jootser
body handles only two cases (verified):

```python
if result.give_up:
    give_up()
elif result.pattern_detected and result.negative_pattern:
    themespace.clamp_negative_pattern(result.negative_pattern)
```

So "post answer-justifier" matches neither branch and **nothing happens**, and
"report unjustified answer" hits `give_up()` — the run **terminates with no answer**.

**Consequences.** In justify mode the terminal outcomes are inverted: where Metacat
produces an answer (unjustified, or via a high-urgency justifier a justified one),
Petacat either does nothing or halts. Without the memory guard, an already-justified
answer doesn't short-circuit the path either.

**Fix plan.**
1. Add the `memory.answer_present(...)` guard at the top of
   `joots_from_justify_clamps` (the method exists and is used at the two other
   Scheme sites).
2. Extend the jootser body to dispatch on `result.action`: `post_answer_justifier`
   → `post_codelet('answer-justifier', 91)`; `report_unjustified_answer` → call the
   report path with the unjustified slippages (the answer-reporting builtin already
   accepts them), not `give_up()`.
3. Drop `give_up=True` from the report branch's result.
4. Module test in justify mode exercising both branches.

## JO-2. Invented give-up after >5 snags — HIGH

**Metacat** (`jootsing.ss:110-112`): when no negative-pattern entries survive the
stochastic selection, the jootser just fizzles — it will try again later.

**Petacat** (`jootsing.py:383-392`): same situation, but `if num_snags > 5: return
JootserResult(give_up=True…)` — the body then terminates the run.

**Consequences.** An added termination condition with no Scheme counterpart: runs
halt on a stochastic failure to select pattern entries in situations Metacat
survives (Metacat gives up only via recurring-clamp jootsing or the justify path).

**Fix plan.** Delete the `num_snags > 5` branch; always return
`pattern_detected=False` (fizzle). Keep the legitimate give-up paths (recurring
rule-codelet/snag-response clamps) which were verified equivalent.

## JO-3. Justify-clamp jootsing gate hardcoded to 1 — MEDIUM

**Metacat** (`jootsing.ss:135-139`): jootsing from justify clamps is permitted only
when the most recent trace event *is* the clamp itself — i.e. the clamp produced no
events at all (everything stalled).

**Petacat** (`jootsing.py:545-548`): `clamp_type_factor = 1.0` with a comment
admitting "a simplified check".

**Fix plan.** Implement the gate: factor = 1 if `trace.get_last_event('any')` is a
clamp event else 0.

## JO-4. Clamp-event equivalence uses ordered rule lists — MEDIUM

**Metacat** (`trace.ss:586-590`): clamp equality compares rules with set equality
(`sets-equal-pred? rules-equal?`).

**Petacat** (`jootsing.py:765-767`): compares `[rule_signature(r) for r in e.rules]`
as ordered lists; `clamp_rules` stores `[chosen, other]` and which type is chosen
varies stochastically, so two justify clamps over the same rule pair can compare
unequal — recurring clamps get partitioned into separate equivalence sets and the
3-clamp jootsing threshold under-fires.

**Fix plan.** Compare as multisets of signatures (sort the signature lists before
comparing).

## JO-5. Progress-watcher: wrong answer-finder urgency; extra posting channel — MEDIUM

**Metacat** (`jootsing.ss:266-271`): after unclamping, post the answer codelet with
probability progress/100 at **urgency = progress-achieved**. And when the workspace
is quiescent with decent rules (`jootsing.ss:337`), the Scheme *fizzles* — posts
nothing.

**Petacat** (progress-watcher body; `jootsing.py:188-193`): the probability gate
matches, but urgency is `max(1, round(100 - temperature.value))`; and the
quiescent-with-decent-rules case posts an answer-finder/justifier with probability 1
— a posting channel Metacat does not have.

**Fix plan.** Use `result.progress` as the urgency; make the decent-rules branch
return a fizzle result. (The `against-background` half of the rule-codelet clamp is
CL-2.)

---

# 5. Justify mode

## JU-1. `or True` — every working translation is declared justified — HIGH

**Metacat** (`justify.ss:94-130`): after the translated rule works, the Scheme sets
its quality values, builds the translated string (which installs supporting bridges
and the theme pattern), adds the rule to the Workspace, monitors it, and reports the
answer **only if** the translated rule is `supported?`; otherwise it attempts
`clamp-rules` — the reorganisation clamp.

**Petacat** (`justify.py:192`):

```python
if translated_rule.supporting_bridges or True:
```

The guard is a tautology; the clamp branch at `justify.py:204-215` is dead code, and
none of the intermediate steps happen.

**Consequences.** Petacat immediately reports a justified answer whenever the
translation merely applies, where Metacat requires the Workspace to materially
support it — and Petacat never issues the corresponding justify clamp. Justify
verdicts are systematically wrong.

**Fix plan.** Remove `or True`; implement the intermediate steps (set quality
values per RU-10, build the translated string, add the rule, monitor) so
`supporting_bridges` is actually populated before the test; the dead clamp branch
then becomes live. Module test: a translation that works but has no support must go
to the clamp branch.

## JU-2. `permission_to_clamp()` called without the codelet count — HIGH

**Metacat** (`trace.ss:112-119`): the grace period is `codelet-count <
last-unclamp-time + 100`.

**Petacat** (`justify.py:225, 291`): both call `trace.permission_to_clamp()` with
the default `codelet_count=0` (`trace.py:859-864`), making
`within_grace_period(0, 100)` true forever once any clamp has been undone — i.e.
after the first unclamp of a run, **justify clamps are permanently denied**. The
jootsing call sites pass the count correctly; only `justify.py` is broken.

**Consequences.** At most one justify clamp per run reaches the unification gate;
Figure 4.13-style repeated reorganisation cannot happen.

**Fix plan.** Pass `ctx.codelet_count` (both sites have it in scope). Consider
making `codelet_count` a required parameter of `permission_to_clamp` so the default
cannot silently reappear.

## JU-3. Vacuous-translation guard missing — MEDIUM

**Metacat** (`justify.ss:88-95`): reporting requires `currently-works?` **and**
`(not (null? ref-objs1))` — the comment gives the exact failure class: "a bottom
rule gets translated to a top rule that works but doesn't refer to anything in the
initial string. Example: xqd -> xqd; mrrjjj -> mrrjjjj".

**Petacat** (`justify.py:711-723`): only `currently_works`; reference objects are
never computed.

**Fix plan.** Compute the translated rule's reference objects against the initial
string (the machinery exists in `rules.py` for `possible_to_instantiate`) and
require them non-empty.

## JU-4. Matching-rule `supported?` inverted for bridge-less rules — MEDIUM

**Metacat** (`rules.ss:219-222`): `supported?` is an `andmap` over the supporting
bridges — vacuously **true** for a rule resting on none. Petacat's own
`Rule.supported` (`rules.py:963-971`) has the correct semantics.

**Petacat** (`justify.py:150`): `if matching_rule.is_built and
matching_rule.supporting_bridges:` — requires non-empty bridges, sending bridge-less
matching rules down the clamp branch (where JU-2 likely denies the clamp) instead of
reporting the justified answer.

**Fix plan.** Use `matching_rule.supported(workspace)`.

## JU-5. Justify clamps never apply their codelet patterns — HIGH

**Metacat** (`justify.ss:167-172`, applied at `trace.ss:634-639`): a justify clamp
clamps the top-down codelet pattern **and** the thematic codelet pattern (thematic
scout at 91, which with CL-1(d) also lifts its posting probability to 0.91).

**Petacat** (`justify.py:318-321, 347`): the patterns are stored as inert
`{"type": ...}` placeholder dicts, and `clamp_event.activate(trace, themespace,
slipnet)` is called **without a coderack**, so the codelet branch of `activate` is
skipped. The intended compensation in the answer-justifier body checks
`result.action == 'clamp'` but the actual action string is `'clamp_rules'` — it
never fires, and even it omits the thematic pattern.

**Consequences.** A justify clamp freezes themes and concepts but never redirects
the Coderack — the mechanism that is supposed to rebuild the Workspace under the
clamped interpretation.

**Fix plan.** Store the real patterns (from `meta.codelet_patterns`), pass the
coderack to `activate` (in scope at the call site), fix the body's action-string
check or delete the redundant body-side application entirely once `activate` does
it.

## JU-6. Smaller justify divergences — MEDIUM

- **Translated rules have no theme pattern** (`rules.ss:184-188` builds it from the
  supporting bridges' thematic relations; Petacat has no
  `set_translated_rule_information`, so `justify.py:298-302` silently drops it from
  the clamp). Fix: implement it inside the translated-string step of JU-1/RU-10.
- **Justify translation never makes coattail slippages** — `justify.py:697` calls
  `rule.translate(slippages, direction)` without `rng`, and
  `apply_slippages(..., rng=None)` skips coattails (`slipnet.py:446-447`), where the
  Scheme uses the same probabilistic path in both modes. Fix: pass the RNG.
- **Retention filter deterministic** (`justify.py:564-567` keeps entries with
  retention probability ≥ 0.5; Scheme `justify.ss:296` samples each entry). Fix:
  `rng.prob(p)` per entry.
- **Justified-answer quality from the mean of both rules** (`justify.py:152,193`;
  Scheme uses the top rule's quality alone, `trace.ss:392-396`). Fix: pass the top
  rule's quality.
- **Rule-selection weights** use `max(1, quality)` instead of strength (=relative
  quality) (`justify.py:106-107, 232-236` vs `justify.ss:26-27, 141-146`). Fix with
  RU-6.
- **`traverse-rule-clauses` `string ↔ plato-group` case missing**
  (`justify.py:452-485` vs `justify.ss:243-244`); **whole/single CM removal removes
  all matches** instead of the first (`justify.py:946-965` vs `justify.ss:220-229`).

---

# 6. Slipnet

(The two biggest slipnet findings — the `fully_active` threshold and the jump gate —
are CC-4 and CC-5. The data layer — all 59 nodes, 202 links, depths, lengths,
labels, clamps, codelet attachments — was verified exact.)

## SL-1. Decay not rounded; the integer plateau is lost — MEDIUM

**Metacat** (`slipnet.ss:174-177`): `decay-amount = (round (* rate-of-decay
activation))` — integer arithmetic throughout. Deep nodes plateau: depth 90 never
decays below 5 (`round(0.5) = 0` under round-half-even), depth 80 sticks at ≤2.

**Petacat** (`slipnet.py:198-202`, `python_backend.py:93-95`): float decay, no
rounding — activations decay geometrically to 0.

**Consequences.** Threshold crossings shift by cycles; deep concepts lose their
persistent low-level presence; compounded by CC-5 (Petacat's nonzero residues remain
jump candidates — Scheme's plateaus never jump because they are < 50).

**Fix plan.** Round the decay amount in both the in-Python path and every numeric
backend (the backends must keep matching the reference; extend the numeric matrix
tests). Spread amounts are already rounded on both sides.

## SL-2. Missing initial activations — MEDIUM

**Metacat** (`run.ss:221-232`): init sets **every** descriptor of every initial
description to 100 — including `plato-letter` via each letter's object-category
description — and sets `plato-object-category` itself to 100 when any string has
length 1.

**Petacat** (`runner.py:358-398`): activates letter-category and string-position
descriptors, attaches the object-category description **without** activating
`plato-letter`, and has no single-letter-string special case.

**Consequences.** `plato-letter` (depth 20) matters briefly; `plato-object-category`
(depth 90, ~7 cycles above 50) gates letter⇔group CM relevance — single-letter-string
problems (`a→b; z→?`) lose the deliberate early pressure toward object-category
mappings.

**Fix plan.** Activate the object-category descriptor in the init loop; add the
length-1 check setting `plato-object-category` to 100.

## SL-3. `middle` descriptor predicate is letters-only index arithmetic — HIGH

**Metacat** (`slipnet.ss:587-589` → `workspace-objects.ss:364-370`): an object is
`middle` when its **ungrouped neighbors** exist and are leftmost/rightmost — a
group-aware test. In `mrrjjj` parsed as `[m][rr][jjj]`, the `[rr]` group *is*
middle. `groups.ss:39-40` also attaches `middle` at group build via the same test.

**Petacat** (`slipnet_nodes.json:212` → `slipnet.py:63-81`): the predicate filters
to non-group objects and requires `right − left == 2` — true only for the center
letter of a 3-letter string. A group can never be `middle`; neither can the middle
letter of a 5-letter string; neither can a letter flanked by edge groups. The
faithful `middle_in_string()` exists at `workspace_objects.py:363-373` but nothing
routes it to the descriptor path, and `groups.py:94-108` has no middle branch.

**Consequences.** The `b→[rr]` vertical bridge in `abc→abd; mrrjjj→?` loses its
`middle⇒middle` concept-mapping — a distinguishing CM in the original — weakening
exactly the interpretation the problem is famous for. Any problem whose preferred
reading maps a middle group is affected.

**Fix plan.**
1. Change the seed predicate for `plato-middle` to delegate to the object's
   `middle_in_string()` (expose it to the predicate-evaluation environment in
   `slipnet.py`), and verify leftmost/rightmost predicates against the Scheme's
   spanning-group exclusion while there (they were verified equivalent).
2. Add the middle branch to group description attachment (GR-10).
3. Unit test: `[m][rr][jjj]` — `[rr]` satisfies the middle predicate; center letter
   of `abcde` satisfies it (Scheme: yes, ungrouped neighbors b/d are not
   leftmost/rightmost — verify against the Scheme's exact semantics before
   asserting, since `middle-in-string?` requires the neighbors to *be* edge
   objects).

## SL-4. Property-link association gate missing — HIGH

**Metacat** (`slipnet.ss:108-112`, consumed at `descriptions.ss:113-122`): the
bottom-up description scout filters property links stochastically — each survives
with `temp-adjusted-probability(assoc/100)` (assoc 25 for the a→first / z→last
links) — then picks weighted by `assoc × property-node activation`.

**Petacat** (bottom-up-description-scout body): `link = rng.pick(property_links)` —
unconditional, uniform, activation-ignored.

**Consequences.** `first`/`last` descriptions — the fuel of the `xyz` family's
opposite-mapping answers — are proposed ~2–4× more often per scout run, independent
of temperature and of how active `first`/`last` are.

**Fix plan.** Implement `get_similar_property_links` on the node (filter by
`rng.prob(temp_adjusted_probability(assoc/100))`) and use it in the scout body with
the assoc×activation weighted pick. Fizzle when the filter leaves nothing.

## SL-5. `self_watching_enabled=False` disables Themespace spreading — LOW

**Metacat**: `%self-watching-enabled%` only zeroes the three self-watching codelet
types (`coderack.ss:469-470`) and clamp permission; workspace→themespace,
intra-themespace, and theme→slipnet spreading run unconditionally
(`run.ss:313-315`, `slipnet.ss:377-380`).

**Petacat** (`runner.py:660-671`): all three steps are inside
`if ctx.self_watching_enabled:`.

**Fix plan.** Move the gate off the spreading steps; keep it on codelet posting and
clamp permission. (Non-default configuration only, but it silently changes what the
"self-watching off" experiment measures.)

---

# 7. Coderack

## CR-1. Eviction weight drops the temperature-scaled bin-urgency term — HIGH

**Metacat** (`coderack.ss:237-240`, table at `coderack.ss:55-61`):

```scheme
(get-removal-weight ()
  (* (- *codelet-count* time-stamp)
     (add1 (- (tell *coderack* 'get-highest-bin-urgency)
              (tell coderack-bin 'get-urgency)))))
```

Bin urgency is `round((bin+1)^((110−T)/15))` — the same temperature-indexed table
used for selection. Penalties (bin0…bin6) at T=100: `[4,3,3,2,2,2,1]`; at T=50:
`[2401, …, 1]`; at T=0: `[≈1.6M, …, 1]`. At low temperature a bin-6 codelet is
effectively unevictable. Same-tick codelets (age 0) have weight 0 — unevictable
while any positive weight exists.

**Petacat** (`coderack.py:223-233, 80-99`): `penalty = num_bins − bin_number` —
`[7,6,5,4,3,2,1]` at every temperature — and `max(1, age)` makes same-tick codelets
evictable. The `remove_old_codelets` docstring's "the distribution is the original
one" is true only of Petacat's own earlier flat implementation, which the
incremental walk faithfully reproduces; both are unfaithful to the Scheme.

**Consequences.** Which codelets survive a full rack differs at every eviction, most
strongly at low temperature — answer-finders and builders are meaningfully more
mortal in Petacat exactly when Metacat protects them.

**Fix plan.**
1. Penalty = `1 + urgency_table(6, T) − urgency_table(bin, T)` with the rounded
   integer table (share it with selection, CR-2).
2. Age = `current_time − time_stamp` with no floor; keep the all-zero → uniform
   fallback.
3. The incremental per-bin aggregates (`count`, `Σ time_stamp`) still give the bin
   weight a closed form — only the per-bin penalty constant changes per temperature;
   recompute it at eviction time.
4. Distribution test at fixed T values comparing against a brute-force weighted
   enumeration.

## CR-2. Bin selection weights unrounded — MEDIUM

**Metacat** (`coderack.ss:282-299`): selection weight per bin = `count ×
table-value`, where the table value is **rounded** to an integer. At T=100 the row
is `[1,2,2,3,3,3,4]`.

**Petacat** (`coderack.py:120-124`): the same exponential, unrounded (at T=100:
`[1, 1.587, 2.080, …]`) — e.g. bin 1 is weighted 26% heavier in Scheme.

**Fix plan.** Precompute the rounded integer table (7 × 101 entries, as the Scheme
does) and index it with the rounded temperature; use it for both selection and
CR-1's eviction penalty.

## CR-3. rule-builder no longer posts the answer-finder/justifier — HIGH

**Metacat** (`rules.ss:489-491`): after a successful build, post `answer-justifier`
(justify mode) or `answer-finder` at `%extremely-high-urgency%` (91).

**Petacat** (rule-builder body): ends at `build_structure(rule)` + concept
activation. The only remaining answer-finder source is the per-cycle bottom-up post
gated by `(100−T)/100` at urgency `100−T`.

**Consequences.** In the reference an answer attempt lands in bin 6 the moment a
rule is built; in Petacat it waits for the next update cycle and a probability gate,
at temperature-dependent urgency. Answer attempts are systematically later and
fewer; snag timing shifts on every problem.

**Fix plan.** Append the post to the rule-builder body (mode-dependent codelet type,
urgency 91). Also restore the Scheme's revision path for duplicates (RU-7).

## CR-4. Initial codelet population halved; reposts stamped 0 — MEDIUM

**Metacat** (`run.ss:276-283`): `repeat* (* 2 N)` iterations, each adding one bond
scout **and** one bridge scout → **4N** codelets (36 for abc/abd/xyz).

**Petacat** (`runner.py:400-423`): `for _ in range(N)` → 2N codelets, and reposts
(including mid-run empty-rack reposts) hardcode `time_stamp=0`, making them
maximally eviction-prone, where the Scheme stamps at add time.

**Fix plan.** Iterate `2 * num_objects` times posting both types; stamp with
`ctx.codelet_count`.

## CR-5. Deferred-batch posting replaced by per-post eviction — MEDIUM

**Metacat** (`coderack.ss:383-408`): update-cycle codelets accumulate as a deferred
batch; ≥100 deferred → uniform drop of the excess plus a full rack flush; otherwise
the overflow is evicted **before any deferred codelet lands**, so batch members
never evict each other and weights are computed against the pre-batch rack. Posting
order: bottom-up types, then top-down slipnodes, then thematic
(`coderack.ss:553-572`).

**Petacat** (`runner.py:799-814, 1011-1019`): each post evicts immediately, from a
population including earlier same-batch posts; thematic posting happens *before*
top-down.

**Fix plan.** Collect the cycle's posts into a list; implement
`post_deferred(batch)` with the Scheme's two-regime semantics; order bottom-up →
top-down → thematic. (Also removes the same-batch eviction interaction with CR-1.)

## CR-6. Scout→evaluator urgencies computed from the wrong quantities — MEDIUM

| Codelet posted | Scheme urgency | Petacat |
|---|---|---|
| bond-evaluator (`bonds.ss:334-336`) | `bond-degree-of-assoc` = `min(100, round(11·√assoc))` — sameness ⇒ 100 always | `round(bond_category.activation)` (`builtins.py:265`) |
| group-evaluator (`groups.ss:827-828`) | same `bond-degree-of-assoc` | node activation / constant 35 (whole-string) |
| rule-evaluator (`rules.ss:411, 442`) | fixed: low (verbatim) / high | `round(max(1, rule.quality))` |
| rule-builder (`rules.ss:472`) | fixed high (63) | `round(max(1, rule.quality))` |
| bridge-evaluator (`bridges.ss:957-963`) | average **distinguishing**-CM strength | mean over **all** CMs (identity CMs pin it high) |

**Consequences.** Bin placement of every evaluator differs; sameness-bond
evaluators — Metacat's most urgent — lose their standing advantage; bridge-evaluator
ranking flattens.

**Fix plan.** Point each posting site at the Scheme quantity. `bond_degree_of_assoc`
already exists in `bonds.py:84-102`; expose it to the DSL. Distinguishing-CM
strength: `bridge.get_distinguishing_concept_mappings()` mean.

---

# 8. Workspace statistics feeding temperature and posting

## WS-1. Temperature (and description-scout posting) fed intra-string unhappiness only — HIGH

**Metacat** (`workspace.ss:581-585`): workspace average unhappiness = importance-
weighted mean of each object's **average-unhappiness** — the per-object blend of
intra-string and inter-string (mapping) unhappiness (`workspace-objects.ss:492-517`).
It carries 70% of the temperature formula (`formulas.ss:76-79`) and the
description-scout posting probability (`coderack.ss:485-487`).

**Petacat** (`workspace.py:506-521`, `python_backend.py:417-429`): aggregates
`o.intra_string_unhappiness` only. The faithful per-object `average_unhappiness` is
computed (`workspace_objects.py:478-500`) and **never read** (verified by grep).

**Consequences.** Metacat's temperature stays high until *bridges* exist
(inter-string unhappiness is 100 until then); Petacat's collapses as soon as bonds
and groups form, regardless of mapping progress. Everything temperature-touched
fires early: greedy selection, breaker rates, evaluator acceptance, the
answer-finder gate `(100−T)`, translation thresholds.

**Fix plan.** Aggregate `o.average_unhappiness` (importance-weighted, zero-weight →
0 per `utilities.ss:388-392`); update the numeric-backend call site to pass the
blended values. Unit test: bonded-but-unmapped workspace keeps average unhappiness
high.

## WS-2. Rule possibility computed then discarded — MEDIUM

**Metacat**: `check-if-rules-possible` stores per-side flags consumed by (a) the
temperature rule factor — 0 only when the top rule is possible **and** supported,
both sides in justify mode (`formulas.ss:65-75`); (b) rule-scout posting probability
(0.5 if no possible types else 1, `coderack.ss:488-491`) and count
(`max(1, 2·|types|)`, `coderack.ss:542`); (c) the rule-scout itself (RU-5).

**Petacat**: `runner.py:631` calls `check_if_rules_possible()` and discards the
result; temperature uses `has_supported_rule()` alone (`runner.py:681-682`), posting
uses `has_bonds` (`runner.py:847-849, 933-935`).

**Fix plan.** Store the result on the workspace (`top_rule_possible` /
`bottom_rule_possible`); consume it at the three sites; justify mode requires both
pairs for the temperature factor.

## WS-3. Scout-count aggregates: wrong predicates, deterministic ratios, no blur — MEDIUM

**Metacat** (`workspace.ss:683-716`, `utilities.ss:426-429`): few/some/many from
*absolute* counts against stochastically blurred thresholds (`~2`, `~4`), over
predicates covering letters **and groups**: `unrelated?` (ungrouped ∧ edge: 0 bonds
/ interior: <2), `ungrouped?` (non-spanning, no enclosing group), `unmapped?` (per
string role — initial needs *both* bridges, modified horizontal, target vertical or
both, answer horizontal).

**Petacat** (`runner.py:889-928`): deterministic ratios (0.2/0.5), and the
string-level counters (`workspace.py:141-158, 612-631`) count Letters only, require
zero bonds regardless of position, and consider vertical bridges only. Faithful
implementations exist at `workspace.py:1037-1101` but are dead on this path.

**Consequences.** The number of bond/group/bridge scouts entering the rack each
cycle (2/4/6, 1/2/3, 2/5/6) tracks a different, noiseless statistic — sustained
mis-posting of the scout mix throughout every run.

**Fix plan.** Route the posting counts through the faithful workspace-level
predicates; implement `~n` blur (`n ± random(1+round(√n))`); delete the dead
string-level counters or repoint them.

## WS-4. Thematic-scout count uses intra- for inter-string unhappiness, floored — HIGH

**Metacat** (`coderack.ss:547-549`): `round(10 · max-inter-string-unhappiness%)` —
the mapping-deficit signal, which can be 0. **Petacat** (`runner.py:936-942`): `max(1,
round(10 · max average intra-string unhappiness%))`.

**Consequences.** Thematic scouts are the vehicle of clamped-theme pressure; they
are posted in the wrong quantity exactly during clamp episodes (typically: strings
well-bonded → intra low → 1 scout where the Scheme posts up to 10), and posted even
when the mappings are settled.

**Fix plan.** Implement `get_max_inter_string_unhappiness` (top/vertical, + bottom
in justify) on the workspace; drop the floor. Also fix the bridge-scout posting
input `get_min_mapping_strength` to include the bottom mapping in justify mode
(`workspace.ss:522-528` vs `runner.py:837-842`).

## WS-5. Workspace intra-string average aggregated per-string, unweighted — MEDIUM

**Metacat** (`workspace.ss:557-561`): importance-weighted mean over all objects.
**Petacat** (`workspace.py:633-638`): unweighted mean of per-string unweighted
means. Feeds bond/group scout posting probability.

**Fix plan.** Weight by relative importance over the object population, rounded.

## WS-6. Justify mode: strings' `justify_mode` flag never set — HIGH

**Metacat** (`workspace-objects.ss:484-487, 504-512, 548-555, 574-582`): in justify
mode, target-string objects also carry **horizontal** inter-string
unhappiness/salience (they map to the answer string).

**Petacat**: `WorkspaceObject._justify_mode` reads `self.string.justify_mode`
(`workspace_objects.py:623-629`), which is initialized False (`workspace.py:74`) and
**never set anywhere** — `runner.py:304` sets only `ctx.justify_mode` (verified: the
only assignments are the initializer and the state-graph restore of the same
False).

**Consequences.** Every justify run: target objects' horizontal unhappiness stays
frozen at its init value (100), their average unhappiness/salience use the
non-justify formulas, and bottom mapping strength is systematically depressed by
`_average_inter_string_unhappiness` mixing live answer-object values with frozen
100s. The numeric path inherits the same flag.

**Fix plan.** In `init_mcat`, after creating the strings, set
`string.justify_mode = ctx.justify_mode` on all four (or have the object property
read `ctx`). e2e justify test asserting target-object salience responds to bottom
bridges.

---

# 9. Bonds and descriptions

## BD-1. Top-down bond scouts hardcode the letter-category facet — HIGH

**Metacat** (`bonds.ss:247, 301`): both top-down scouts call `choose-bond-facet`
(letter-category *or* length, weighted by `description-type-support` — the same
weighting the bottom-up scout uses, which commit `34535e3` already fixed there).

**Petacat** (both top-down bodies in `seed_data/codelet_types.json`):
`bond_facet = get_node('plato-letter-category')` — length is never considered
despite a "try letter-category first" comment implying a second attempt.

**Consequences.** Length-facet bonds can only arise from the bottom-up scout. In
Metacat, once succ/pred/sameness or left/right go active, the heavily-posted
top-down scouts are a major channel for length bonds — exactly the `mrrjjj` 1-2-3
reading. The rate of length-bond formation is structurally suppressed.

**Fix plan.** Use the same `choose_bond_facet` helper the bottom-up body uses (both
objects' shared facets, `description_type_support`-weighted) in both top-down
bodies.

## BD-2. Category bond scout tests only one descriptor order — MEDIUM

**Metacat** (`bonds.ss:258-263`): tries `(descriptor1, descriptor2)` and, failing
that, `(descriptor2, descriptor1)`, proposing the reversed bond.

**Petacat** (top-down-bond-scout:category body): one order; mismatch → fizzle.
Drawing `c` with neighbor `b` while hunting successor fizzles where the Scheme
proposes b→c.

**Fix plan.** Add the reversed-order branch proposing `(neighbor, obj)`.

## BD-3. Bond-builder incompatibility drastically narrower; `add_bond` overwrites — HIGH

**Metacat** (`bonds.ss:354-407`): the builder fights, in order: (a) **incompatible
bonds** — any bond occupying either positional slot (`bonds.ss:79-83`), 1:1; (b)
**incompatible groups** — every group nesting both objects at any depth
(`get-common-groups`), at 1 : max-letter-span; (c) **incompatible bridges** — for
directed edge bonds whose implied direction mapping contradicts a bridge's
string-position CM (`bonds.ss:84-122`), at 2:3 — breaking all losers. The duplicate
test (`bond-present?`, `workspace-strings.ss:127-137`) ignores the facet.

**Petacat** (`builtins.py:717-740`): incompatible bonds must be the *same object
pair with a different category* — a bond from either object to a different neighbor
(or at a different nesting level) is not detected, and `add_bond`
(`workspace.py:100-110`) then **silently overwrites** the displaced bond's
positional pointers, leaving it in `string.bonds` with dangling slots. Incompatible
groups are only those with a same-pair different-category constituent bond. The
bridge fight is absent. The duplicate test additionally requires the same facet, so
a length-facet twin of an existing letter-category sameness bond is built as a
coexisting second bond between the same pair, double-counting in
support/density. The faithful `Bond.get_incompatible_bonds` (`bonds.py:196-209`)
and `WorkspaceString.bond_present` exist as dead code.

**Consequences.** Reachable workspace *states* differ, not just probabilities:
displaced-but-listed bonds, duplicate same-pair bonds, cross-level conflicts never
fought, and bridges never broken by bonds.

**Fix plan.**
1. Use `Bond.get_incompatible_bonds` (positional-slot semantics) for (a).
2. Implement `get-common-groups` (any-depth nesting of both objects) for (b), with
   the single shared max-letter-span weight (CC-3).
3. Port the bond-vs-bridge fight (2:3) for directed edge bonds, using the
   direction-mapping incompatibility test of `bonds.ss:84-122`.
4. Duplicate test = `bond_present` semantics (category + direction, facet ignored),
   with the Scheme's activate-then-fizzle behavior.
5. Make `add_bond` assert both slots are free (the builder must have broken
   occupants first).

## BD-4. Local density walks bond chains, not positional neighbors — MEDIUM

**Metacat** (`bonds.ss:136-160`, `groups.ss:354-383`): the density walk moves
through **positional** neighbors (`choose-left/right-neighbor` — a stochastic,
salience-weighted choice among the adjacent letter and the groups edged there),
counting every step as a slot whether bonded or not; 100 only when there are zero
slots.

**Petacat** (`bonds.py:157-194, 270-299`; `groups.py:262-263, 500-539`): the walk
follows existing `left_bond`/`right_bond` pointers, stopping at the first unbonded
object, and returns 100 when the truncated walk finds nothing. Unbonded neighbors
never enter the denominator.

**Consequences.** Density — hence local support, external strength, evaluator
survival, and fight odds — is systematically inflated whenever bonds are sparse
(worked example: `abcdef` with only `a-b` built, proposed `c-d`: Scheme support 30,
Petacat 60). Early bonds snowball harder than the reference.

**Fix plan.** Rewrite both walks over positional adjacency with the stochastic
neighbor choice (re-rolled per strength update, as the Scheme does), counting
unbonded slots in the denominator; keep the zero-slot → 100 case only for genuinely
spanning pairs.

## BD-5. Neighbor choice: same-nesting-level filter vs all-levels salience pick — HIGH

**Metacat** (`workspace-objects.ss:375-387, 417-423`): a bond candidate's neighbors
are the adjacent *letter* (even inside a group) **plus every group edged at that
position**, at any nesting level, picked by intra-string salience. The direction
scout uses the same chooser (`bonds.ss:295-297`).

**Petacat** (`builtins.py:213-227`): only objects with the *identical*
`enclosing_group` qualify — a grouped letter is never a bond candidate for its
ungrouped neighbor. The direction scout bypasses even this via
`string.get_object_at(pos)` (always the letter, possibly inside an adjacent group).
The faithful enumeration exists (`workspace_objects.py:77-155`) unused.

**Consequences.** Some bonds Metacat can propose are unreachable in Petacat
(e.g. `m` to the letter `r` inside `[rr]` — which then fights the group), and the
direction scout can pair mismatched levels. The candidate set of bondable pairs is
different.

**Fix plan.** Reimplement `choose_neighbor` over
`get_all_left/right_neighbors` (letter + edged groups) with the intra-string
salience pick; use it in the direction scout too.

## BD-6. Top-down string choice drops the relevance term; includes the answer string — MEDIUM

**Metacat** (`bonds.ss:222-241, 274-293`): string weighted by
`average(bond-category/direction relevance, average intra-string unhappiness)`, over
non-answer strings (all four only in justify mode). The same applies to the
top-down group scouts (`groups.ss:427-443, 497-513`).

**Petacat** (`builtins.py:235-239`): bare unhappiness with a 0.1 floor, over
`all_strings` — which includes the answer string whenever it exists.

**Consequences.** The "success breeds attention" feedback of the top-down channel —
scouts concentrating on strings where their category is already taking hold — is
missing; post-answer, scouts can be aimed at the answer string, which Metacat never
does outside justify mode.

**Fix plan.** Add a `choose_string_for(category_or_direction)` builtin computing the
Scheme weight over the mode-correct string set; use it in all four top-down
scout bodies.

## BD-7. Description scouts: wrong salience key; early duplicate fizzles — MEDIUM

**Metacat**: both description scouts choose objects by **average** salience
(`descriptions.ss:107, 132`); neither pre-checks duplicates — a duplicate flows to
the builder, which re-activates the type and descriptor before fizzling
(`descriptions.ss:164-168`).

**Petacat**: both bodies use `choose_object('intra')` (the correct
`salience["average"]` is maintained and unused), and both pre-fizzle on duplicates —
the top-down body on mere *type* presence — so the steady re-activation stream
duplicates provide in Metacat is suppressed.

**Fix plan.** Switch to the average-salience key; remove the pre-checks and let the
evaluator/builder handle duplicates with their activation side-effects. (The
property-link gate for the bottom-up scout is SL-4; the ≥50 relevance issue is
CC-4.)

## BD-8. Bond-builder activation after lost fights; bond-description routing — LOW

Petacat's bond-builder body activates category/direction unconditionally after
`build_structure` (which returns False on lost fights); the Scheme activates only on
the duplicate path and inside `build-bond`. And the description-builder appends
every description to `object.descriptions`, where the Scheme routes
bond-descriptions to the separate list (`descriptions.ss:187-189`) — reachable via
the thematic scout's description proposals, after which description-counting
formulas that exclude bond descriptions see them.

**Fix plan.** Gate the activation on the build result; route
`bond_description=True` descriptions to `bond_descriptions` in the build path.

---

# 10. Groups

## GR-1. Length descriptions attached unconditionally at construction — HIGH

**Metacat** (`groups.ss:816-818`): length is attached *probabilistically at
proposal*, via `length-description-probability`
(`workspace-structure-formulas.ss:21-29`) — for a 3-group with `plato-length` cold,
`0.5^27 ≈ 7.5e-9`. Length descriptions on 2–5 groups are rare unless Length is
already active. (Singletons get one with probability 1 via the same formula.)

**Petacat** (`groups.py:112-115`): `Group.__init__` attaches the length description
unconditionally for lengths 1–5. The faithful `length_description_probability`
(`formulas.py:253`) has **zero callers**.

**Consequences.** Every group build jolts `plato-one/two/three` and hence
`plato-length` (via the build-time descriptor jolts), permanently inflating the
length facet; every singleton counts as the "singleton with length description"
Trace milestone; bridges carry Length CMs Metacat almost never offers. Interacts
with CC-1 (which inflates the probability when it *is* consulted).

**Fix plan.** Remove the unconditional attach; call the stochastic attach at
proposal time in all three scout paths (`stochastic-if*` semantics), keep the
unconditional attach only where the Scheme has it (singleton path and the
length-facet sameness consolidation, GR-7).

## GR-2. Group internal strength: wrong bond factor; singletons collapse to 5 — HIGH

**Metacat** (`groups.ss:392-410`): bond factor = the bond **category's**
degree-of-association (sameness 100; succ/pred 40, 76 when fully active) × (1 or ½
by facet); it exists for every group *including singletons* (bond-category is
derived from the group category at construction). A singleton sameness group scores
≈ 92.

**Petacat** (`groups.py:167-191`): bond factor = mean overall *strength of the
constituent bonds* (which already folds in compatibility, facet, `11·√assoc`, and
external support), and a bond-less singleton returns the bare length factor: **5**.

**Consequences.** Singleton groups (internal 5) nearly always die at the evaluator —
compounded by GR-3 — foreclosing the letter⇒group slippages and 1-2-3 readings that
gate `mrrjjj`-family answers; directed-group strengths shift up.

**Fix plan.** Compute the bond factor from
`group.bond_category.degree_of_assoc()` (shrunk-aware — correct only after CC-4) ×
facet multiplier, for all groups including singletons; keep the length-factor table
and 0.98 weighting, which were verified correct.

## GR-3. `group-evaluation-probability` not ported — HIGH

**Metacat** (`groups.ss:590-620`): the group evaluator uses a *dedicated* survival
curve — `T%·tanh(strength/10) + (1−T%)·strength%` — with a comment explaining it
deliberately boosts weak groups at high temperature (strength 20 at T=100 survives
with p ≈ 0.96).

**Petacat**: the group-evaluator body calls the generic `evaluate_structure` →
`temp_adjusted_probability(strength/100)` — p ≈ 0.28 for the same case. No
`group_evaluation_probability` exists anywhere.

**Consequences.** Early-run group formation — the seed of every grouped reading — is
suppressed ~3.5× at high temperature; exactly the behavior the Scheme author added
this function to enable.

**Fix plan.** Implement the function in `formulas.py` (coefficients to
`formula_coefficients.json`); call it from the group-evaluator body in place of
`evaluate_structure`'s probability (keep the strength update and the fizzle
plumbing).

## GR-4. Bond scanning ignores facet/direction consistency; no bond flipping — HIGH

**Metacat** (`groups.ss:858-907`): `scan-bonds` extends a group only through bonds
matching **facet ∧ category ∧ direction**, and *additionally* accepts an
opposite-category/opposite-direction bond by taking its flipped version;
`polarize-bonds` does the same for the whole-string scout; the builder later fights
and replaces the flipped originals.

**Petacat**: the category-scout scan checks only `bond_category`; the
direction-scout checks category+direction but not facet; the whole-string scout
checks category only. No flipping exists in any scan (verified — the only flip
machinery is bridge-driven).

**Consequences.** Petacat can chain a left- and a right-directed successor bond, or
a letter-category and a length bond, into one "group" whose recorded
direction/facet misdescribes its contents — structures Metacat cannot build.
Conversely, a group whose relation currently exists as opposite-polarity bonds
(right-going predecessors where a left-going successor group is wanted) is
unreachable, where Metacat reaches it by flipping.

**Fix plan.** Add facet+direction equality to every scan; add the flipped-bond
acceptance branch (collect flipped copies of opposite bonds); implement
`polarize-bonds` for the whole-string scout; make the builder break the flipped
originals and build the proposal's flipped bonds (with the letter-span vs 1 fight,
CC-3 table).

## GR-5. Group incompatibility = any overlap; supergroups destroy their constituents — HIGH

**Metacat** (`groups.ss:283-286`): a proposed group's incompatible groups are
exactly the **enclosing groups of its constituents**. A supergroup over built
subgroups `[m][rr][jjj]` has none — the subgroups become nested members
(`groups.ss:925-928`).

**Petacat** (`builtins.py:742-753`): every span-overlapping built group is
incompatible — including the proposal's own constituents. Building a group of
groups therefore requires beating each constituent in a fight, then
`break_structure` removes them, leaving `structure.objects` holding groups no
longer in the string and letters pointing at nothing. The faithful
`Group.get_incompatible_groups` (`groups.py:279-292`) is dead code.

**Consequences.** Metacat's nested-group hierarchy (the `mrrjjj`
group-of-length-groups; `kkjjii`) is replaced by "supergroup destroys subgroups
with dangling references" — plus unrelated merely-overlapping groups being fought
that Metacat ignores. Reachable structure *states* differ.

**Fix plan.** Use `Group.get_incompatible_groups`; on build, set each constituent's
`enclosing_group` and leave built subgroups in place (audit
`workspace.add_group`/`remove_group` invariants for nesting); with GR-6's cascade,
assert no dangling references in a module test that builds `[[m][rr][jjj]]`.

## GR-6. Breaking has no cascade; breaker lacks the joint bond-in-group case — HIGH

**Metacat**: `break-group` (`groups.ss:954-1018`) recursively breaks the enclosing
group, breaks all incident bonds, deletes proposed bonds/bridges touching the
group, breaks the group's vertical and horizontal bridges, clears back-references,
and deletes now-invalid `middle` descriptions. The breaker (`breakers.ss:30-46`)
will break a bond enclosed in a built group only *together with* the group, at
probability p1·p2.

**Petacat** (`builtins.py:797-823`): `break_structure` only removes the one
structure from its containing list; the breaker body breaks any structure alone at
p1. Verified: no other cascading-removal path exists.

**Consequences.** After any lost fight or break: bridges keep pointing at removed
groups (still feeding mapping strength, rule support, unhappiness), supergroups
survive their members' death, groups survive their internal bonds' death, stale
`middle` descriptions persist. States Metacat cannot represent.

**Fix plan.**
1. Implement `break_group` / `break_bond` / `break_bridge` cascades per the Scheme
   (each with its dependent-structure list); route `break_structure` and the
   builder-fight loser path through them.
2. Add the breaker's joint case (bond in built group → p1·p2, break both).
3. Implement `delete_invalid_middle_descriptions`
   (`workspace-strings.ss:300-321`) — strip stale `middle` descriptors and break
   the concept-mappings/bridges resting on them — called on group build and break
   (also closes WS/GR stale-middle findings).
4. Module test: break a group with incident bonds and a vertical bridge; assert the
   workspace holds no references to any of them.

## GR-7. Group builder: no bridge fights, no consolidation branches — HIGH

**Metacat**: the builder fights incompatible **bridges** 1:1 (`groups.ss:685-700` —
a directed group whose direction CM contradicts an existing bridge's
string-position CM must beat it and breaks it on winning). It also has three
consolidation branches (`groups.ss:707-786`): a letter-category sameness group over
sameness subgroups is rebuilt **flat** (subgroups broken, missing bonds built on
the spot); a length-facet sameness group over length groups splices their
constituents (fizzling on mixed lengths, always attaching a length description);
and constituent bonds existing only as flipped versions are replaced
(break-flipped + build-proposed).

**Petacat** (group-builder body, verified in full — 15 lines): checks constituent
bonds are built, calls `build_structure`, activates three nodes. None of the above
exists.

**Consequences.** Groups contradicting the existing mapping build without paying
for it; `[a][aa]`-style proposals hit the GR-5 pathology instead of flattening to
`[aaa]`; flip-dependent groups fizzle.

**Fix plan.** Port `get-incompatible-bridge` for groups (the
leftmost/rightmost + directed-bond CM test) into the builder's fight roster; port
the three consolidation branches into the builder body (they need `build_bond` /
`break_bond` builtins, which exist).

## GR-8. Group scout details — MEDIUM

Four smaller divergences in the scout bodies, each shifting group-formation
probabilities:

- **String choice** drops the category/direction relevance term (see BD-6; same fix).
- **Scan direction** (`groups.ss:448-457, 518-531`): leftmost object → scan right;
  rightmost → left; otherwise stochastic by `plato-right`/`plato-left` activation.
  Petacat picks by which bonds exist (deterministically collapsing the
  singleton-path branch), and the direction scout examines only the bond on the
  target side — half the entry points.
- **Scan count** (`workspace-strings.ss:56-59`): drawn from a distribution over
  1..n−1 weighted i² (long scans favored). Petacat: uniform over 1..n, and the
  direction scout over-scans by one (seeds the list *then* loops `max_scan` times).
- **Whole-string scout** (`groups.ss:560-579`): starts from a stochastic
  leftmost *object* (letter or group, importance-weighted) and walks top-level
  bonds, picking a random bond as the polarization template. Petacat always starts
  at `letters[0]` and walks letter-level bonds — spanning groups *of groups* are
  unreachable via this scout.

**Fix plan.** Port `bond-scan-distribution` (i²) and `choose-leftmost-object` onto
`WorkspaceString`; fix the two scan-side branches; walk top-level objects in the
whole-string scout with the random template pick.

## GR-9. Group activation jolts and evaluator urgency — MEDIUM

**Metacat**: `propose-group` jolts bond-category + direction (`groups.ss:819-821`);
the evaluator jolts them again on survival (`groups.ss:598-601`); evaluator urgency
is `bond-degree-of-assoc` (CR-6). **Petacat**: no jolts until a successful build,
plus an extra bond-facet jolt at build with no Scheme counterpart; urgencies from
node activation.

**Fix plan.** Add the propose/evaluate jolts to the scout and evaluator bodies;
drop the builder's facet jolt; urgency per CR-6.

## GR-10. Duplicate handling, singleton/middle descriptions, stale-middle cleanup — MEDIUM

- **Duplicate group** (`groups.ss:631-642`): the Scheme activates every descriptor
  of the existing group and transfers any *new* descriptions from the proposal
  (canonically the length description). Petacat's `build_structure` returns False
  with no transfer or activation. Also the equivalence tests differ
  (`workspace-strings.ss:227-240` keys on leftmost object + category + direction +
  length; Petacat requires identical facet and object lists).
- **Singletons lack the bond-category description** (`groups.py:85-90` gates it on
  `group_bonds`; Scheme always attaches it, `groups.ss:30-31`), so singleton
  bridges lose the BondCtgy CM.
- **Groups can never be described `middle`** — `_attach_initial_descriptions`
  (`groups.py:94-108`) has no middle branch (Scheme `groups.ss:39-40`); together
  with SL-3 both avenues are closed. The faithful
  `add_descriptions_for_group` (`groups.py:346-429`) is dead code.
- **Stale `middle` cleanup** — covered by GR-6 step 3.

**Fix plan.** Port the duplicate-transfer branch; attach the bond-category
description unconditionally; add the middle branch (using `middle_in_string()`);
align the equivalence predicate with `get-equivalent-group`.

---

# 11. Bridges and concept-mappings

The bridge *data model and strength formulas* track the Scheme closely (verified in
detail); the divergences concentrate in the scout codelet bodies — Metacat's
probabilistic gates between "pick two objects" and "post evaluator" are missing —
and in the builder's fight roster and post-build augmentation. Three pieces of
Petacat dead code (`ConceptMapping.slippability`, `Bridge.get_incompatible_bond`,
`ConceptMapping.opposite_mapping`) mark exactly where the port stopped.

## BR-1. Slippage-admissibility gate absent — HIGH

**Metacat** (`bridges.ss:928-937` bottom-up; `bridges.ss:1026-1031`
important-object): after computing the possible CMs, the scout fizzles with
probability `∏(1 − temp_adjusted(slippability/100))` — a temperature- and
depth-controlled refusal to propose bridges resting on deep/weak slippages.

**Petacat**: both scout bodies go straight from `make_concept_mappings` to posting
the evaluator. `ConceptMapping.slippability()` (`concept_mappings.py:84-97`) is
implemented and never called. (The `builtins.py:1382-1388` comment about removing a
slippability filter concerns rule *translation* — a correctly-removed misplacement —
not this proposal-time gate.)

**Consequences.** Deep slippages (opposite mappings, letter⇒group) become
proposable at low temperature where Metacat nearly always fizzles; slippage
admissibility is no longer temperature-controlled — a core piece of "conceptual
slippage over logical mapping".

**Fix plan.** Add the gate to both scout bodies:
`if rng.prob(product(1 - temp_adjusted_probability(cm.slippability()/100) for cm in cms)): fizzle()`.

## BR-2. Distinguishing identity/opposite requirement absent — HIGH

**Metacat** (`bridges.ss:948-952, 1042-1046`, with the file-head comment naming the
b–d-in-abc→abcd example): a bridge must have at least one *distinguishing* CM with
an Identity or Opposite relation — bridges justified only by slippages are reserved
for thematic scouts under pressure.

**Petacat**: absent; scouts check only `if not cms: fizzle()`.

**Consequences.** "Stupid mappings" (the Scheme's words) become proposable at any
time; the division of labor between bottom-up and thematic scouting — load-bearing
for how theme pressure changes behavior — is erased.

**Fix plan.** Implement `distinguishing_identity_or_opposite` on `ConceptMapping`
(distinguishing? ∧ label ∈ {identity, opposite}); fizzle when no CM qualifies, in
both scouts (not the thematic scout).

## BR-3. Flipped-bridge proposal absent from ordinary scouts — HIGH

**Metacat** (`bridges.ss:953-956, 1047-1050, 1060-1066`): when both objects are
spanning groups, all reversible CM dimensions map opposite, and `plato-opposite` is
*not* fully active, the scouts propose the bridge to the **flipped** second group
(`>abc> → <cba<` re-perceived as `>abc> → >abc>` reversed).

**Petacat**: both scouts construct `Bridge(...)` directly; `make_flipped_version`
is reachable only from the thematic path; `ConceptMapping.opposite_mapping` has no
callers.

**Consequences.** Without active themes, re-perceiving a spanning group in the
opposite direction is unreachable from bottom-up processing — answer families
depending on it (crosswise `xyz` readings before any snag) shrink.

**Fix plan.** Implement `reverse_direction_orientation(cms)` (uses
`opposite_mapping` and the `plato-opposite` fully-active check — after CC-4); route
both scouts through `bridges.propose_bridge` with the flip flag, as the thematic
scout already does.

## BR-4. CMs computed from all descriptions, not relevant ones — HIGH

**Metacat** (`bridges.ss:924-927, 1022-1025, 1090-1097`): scouts pass
`get-relevant-descriptions` (relevance snapshot: only currently-fully-active
description types can justify a bridge); all-descriptions is used only for
string-spanning groups; bond descriptions are *never* in the main CM set — bond CMs
live in a separate list added at build (see BR-5) and excluded from strength,
incompatibility, and support.

**Petacat** (`bridges.py:793-794, 516-521`): `make_concept_mappings` iterates
`get_all_descriptions()` — irrelevant descriptions and group bond-descriptions
included — so BondCtgy/BondFacet CMs sit in the main list of every group-group
proposal, entering internal strength, incompatibility verdicts, support sums, and
evaluator urgency.

**Consequences.** Group-group bridge strengths, incompatibility, and support all
differ; the "only what is active now can justify a bridge" semantics is lost.

**Fix plan.** Filter to relevant descriptions (correct only after CC-4), with the
spanning-group all-descriptions exception; exclude bond descriptions from the main
list (they return via BR-5's separate bond-CM list).

## BR-5. Build-time CM augmentation absent — HIGH

**Metacat** (`build-bridge`, `bridges.ss:1365-1411`): on build, guarantee an
ObjCtgy CM on horizontal bridges; store the **symmetric** version of every
slippage; for group-group bridges compute **bond CMs** from bond descriptions into
the separate list; for horizontal bridges between objects of different platonic
lengths, add a Length CM *even when neither object carries a Length description*.

**Petacat** (`_build_structure_locked`, `builtins.py:420-451`): none of this. The
ObjCtgy guarantee is accidentally compensated by BR-4 (wrong time, wrong filter);
symmetric slippages are synthesized on the fly only for
`workspace.get_all_slippages`, *not* for the thematic scout's auxiliary-slippage
search (`themes.py:990` iterates `concept_mappings` where the Scheme iterates
slippages incl. symmetric); the Length CM is simply missing — an a→aa bridge with
no Length descriptions yields no `Length: one⇒two` CM, so rules abstracted from it
lack length-change information.

**Fix plan.** Implement the four augmentations in the bridge build path: ObjCtgy
guarantee (then BR-4's filter can't starve it), `symmetric_slippages` stored on the
bridge (fix the symmetric label to recompute, per BR-12), `bond_concept_mappings`
as a separate list consulted only where the Scheme consults it, and the platonic-
length CM.

## BR-6. Builder fights no incompatible bonds or enclosing groups — HIGH

**Metacat** (`bridges.ss:1259-1291, 1318-1321`): when both objects sit at string
edges, the builder fights the incompatible directed bond (3:2) and its enclosing
group (1:1), breaking losers — the mechanism by which a new mapping restructures
bonds and groups.

**Petacat**: `Bridge.get_incompatible_bond` exists (`bridges.py:379-433`) with
**no callers** — and is itself broken (it can only construct its probe CM when the
bridge already has a DirCtgy CM to steal the node from; the Scheme builds it from
`plato-direction-category` unconditionally, `bridges.ss:350-357`).
`_get_incompatible_structures`' bridge branch collects only bridges and
flipped-group originals.

**Fix plan.** Fix `get_incompatible_bond` to build the probe CM unconditionally;
add the bond (3:2) and enclosing-group (1:1) fights to the builder's roster.

## BR-7. Bridge fight weights use one object's span — HIGH

**Metacat** (`bridges.ss:1246-1254, 178-180`): bridge-vs-bridge fights weigh each
side by its **letter-span** = span(object1) + span(object2) — a spanning bridge
fights a letter bridge at 6:2.

**Petacat** (`builtins.py:765-767`): `structure.object1.span` vs
`bridge.object1.span` — 3:1 in the same case, and blind to object2 entirely.

**Fix plan.** Covered by the CC-3 weight table; noted separately because it changes
every spanning-vs-local mapping contest.

## BR-8. Bridge-incompatibility test drops three Scheme refinements — HIGH

**Metacat** (`bridges.ss:1551-1580, 331-338, 869-892`): (a) letter-category and
length **slippages are exempted** from the CM cross-check (the Scheme's own comment:
in abc→abcc, the spanning bridge must not be incompatible with c→cc via the Length
CMs 3⇒3 vs 1⇒2); (b) a bridge's DirCtgy CMs enter the check only when it
**encloses** the other bridge; (c) spanning direction-mapped bridges additionally
break subobject bridges whose position ordering contradicts the direction label
(`direction-incompatible-bridges`).

**Petacat** (`bridges.py:921-939`): raw cross-product of all CMs — no exemption, no
enclosure gating (the `orientation` parameter is unused), and
`direction_incompatible_bridges` does not exist.

**Consequences.** False-positive incompatibilities (needless fights breaking
structures that coexist in Metacat — directly the abc→abcc case) *and* false
negatives (crossing sub-mappings under a spanning bridge persist).

**Fix plan.** Port the three refinements; wire `direction_incompatible_bridges`
into `get_incompatible_bridges` for spanning direction-mapped bridges.

## BR-9. Duplicate-bridge merge path absent — MEDIUM

**Metacat** (`bridges.ss:1208-1232`): proposing an existing bridge activates all CM
labels and **adds the CMs not already present** (monitored into the Trace), then
fizzles. This is how a sparse early bridge accumulates slippages as relevance
shifts — and a second source of slippage Trace events (see TM-4).

**Petacat**: `_equivalent_structure_exists` → `build_structure` returns False;
nothing merges, nothing activates.

**Fix plan.** On duplicate detection in the bridge build path: activate labels,
`add_concept_mapping` for novel CMs, run the slippage monitor on exactly the added
ones, then fizzle.

## BR-10. Builder relevance guard, CM activation stream, follow-up codelets — MEDIUM

Three missing pieces around propose/evaluate/build:

- **Builder guards** (`bridges.ss:1233-1237, 1200-1207`): fizzle when not all CMs
  are still relevant (a live gate at high temperature; the description-types-present
  guard is benign in Petacat since descriptions are never deleted — until GR-6
  introduces deletion, after which it is needed too).
- **CM activation at propose and evaluate** (`bridges.ss:1109-1110, 1172-1174`):
  every CM's description types and descriptors are jolted at both stages; Petacat
  activates only after build. The re-activation stream that keeps bridge-relevant
  concepts hot — and that the relevance guard depends on — is missing.
- **propose-bridge side-effects** (`bridges.ss:1120-1145`): a horizontal proposal
  between objects of different platonic lengths activates `plato-length` and posts
  two length description-scouts at very-high urgency; a letter↔group pairing
  activates the group category and posts a `top-down-group-scout:category` into the
  letter's string — the targeted recruitment loop for the `mrrjjj`
  letter-faces-group situation.

**Fix plan.** Add the guard to the builder; add the jolts to both scouts and the
evaluator body; implement the side-effect block in `propose_bridge` (posting via
the ctx).

## BR-11. Evaluator urgency over all CMs — MEDIUM

**Metacat** (`bridges.ss:957-963, 1051-1057`): urgency = average strength of the
**distinguishing** CMs. **Petacat**: mean over all CMs — identity CMs at 100 pin it
high, flattening the ranking. **Fix**: covered in CR-6.

## BR-12. Smaller bridge/CM divergences — MEDIUM

- **Unlabeled-but-linked CM strength flattened to 5** (`concept_mappings.py:64-82`
  branches on `label is not None`; Scheme uses the link's degree-of-assoc whenever
  the *link* exists — letter⇔group and single⇔whole score 13, not 5,
  `concept-mappings.ss:119-135`). Depresses every letter↔group bridge. Fix: branch
  on link existence.
- **`incompatible_with_theme` tests description presence, not possibility**
  (`bridges.py:695-703` vs `bridges.ss:254-267`; the correct
  `SlipnetNode.description_possible` exists and the thematic scout uses it).
  Under pressure, bridges are penalized for dimensions the object merely hasn't
  been described along yet. Fix: call the possibility predicate.
- **Theme boosting walks bond descriptions** (`bridges.py:257-271` uses
  `_all_descriptions`; Scheme `bridges.ss:311-322` uses plain descriptions) —
  BondCtgy/BondFacet themes acquire workspace activation the original never gives
  them, and can then appear in dominant patterns, answer indexing, and Petacat's
  snag patterns. Fix: plain `descriptions` in `boost_themes` /
  `get_associated_thematic_relations` / `_check_descriptions`.
- **`symmetric_mapping` keeps the forward label** (`concept_mappings.py:241-258`;
  Scheme recomputes — succ becomes pred). Latent until BR-5 stores symmetric
  slippages. Fix: recompute via `get_label(descriptor2, descriptor1)`.
- **Theme-support negative weight counts only nonzero themes**
  (`bridges.py:300-321` vs `bridges.ss:273-288` — 2n over all present themes).
- **`letter-category-mappable-objects?` re-expressed as a bond-facet test**
  (`bridges.py:753-766` vs `bridges.ss:1515-1522` — letter↔group requires
  *all-letter* groups; group↔group is always allowed).
- **Thematic scout's auxiliary-slippage search skips symmetric slippages**
  (`themes.py:990` vs `themes.ss:896`) — fixed by BR-5.
- **No proposed-bridge registry / evaluator object-existence fizzle**
  (`bridges.ss:1153-1160`) — one wasted evaluation and RNG draw per broken-object
  proposal; caught at build.
- **`supports_theme_pattern` compares node names to bare relation names**
  (`bridges.py:448-453`) — can never match; currently dead code, flagged so it is
  fixed rather than wired in as-is.

---

# 12. Rules, translation, and answers

## RU-1. Extrinsic (swap) clauses lose their dimensions — swap rules are no-ops — HIGH

**Metacat** (`rules.ss:871-875`): an instantiated extrinsic clause carries its
dimensions (`(list 'extrinsic object-descriptions dimensions)`), which
`get-extrinsic-transforms` (`rules.ss:1419-1438`) reads to generate the swap
transforms.

**Petacat** (`rules.py:1775-1787`): the clause is constructed with
`changes=[]` and the computed `sorted_dims` discarded; application reads dimensions
from `clause.changes` (`rules.py:2081-2085`), which is always empty for a
pipeline-built extrinsic clause. Verified: no other code constructs extrinsic
clauses with populated changes.

**Consequences.** Every extrinsic clause applies as a no-op: a pure swap rule
("Swap positions of the leftmost and rightmost letters") produces an unchanged
string, fails `currently_works`, and is never built. The entire extrinsic rule
family of §3.3.4 is unreachable; the SWAP snag kind can never occur; the
swap-dimension abstractness factor is dead; problems whose obvious reading is a
swap lose those answers entirely.

**Fix plan.** Store the sorted dimensions on the clause (either a dedicated
`dimensions` field or `RuleChange` entries with `dimension` set) and read them at
application; add a module test that abstracts and applies a swap rule end-to-end on
a swap problem. Then un-dead-code M9's partition (RU-12) which feeds swap
clustering.

## RU-2. Translation draws slippages from the wrong bridges, without the Scheme's filters — HIGH

**Metacat** (`answers.ss:1432-1494`): slippages applicable to a clause come *only*
from the **vertical bridges of that clause's reference objects** (plus the
enclosing group's bond slippages); inconsistent enclosing groups fail the whole
translation; missing reference objects fail it; and a direction-sensitive filter
excludes symmetric slippages going down unless labeled `opposite`.

**Petacat** (`builtins.py:1389-1407`, `rules.py:103-115`): collects **every CM of
every built vertical bridge**, and `_slippages_for_clause` *prepends the reference
objects' horizontal-bridge CMs with precedence*:

```python
for attribute in ("vertical_bridge", "horizontal_bridge"):
    ...own.extend(bridge.concept_mappings)
```

**Consequences.** Horizontal-mapping slippages participate in vertical translation
(in a crossed top mapping, the horizontal `rightmost⇒leftmost` CM rewrites the
rule during a top→bottom translation the vertical mapping says is identity);
slippages from unrelated objects apply as fallback; translations succeed that
Metacat aborts. Produces answers Metacat cannot produce from the same Workspace
state.

**Fix plan.** Restrict each clause's slippage set to its reference objects'
**vertical** bridges + enclosing-group bond slippages; implement the three failure
modes and the symmetric-direction filter (needs BR-5's stored symmetric slippages
for the justify direction); remove the global-fallback `rest` list.

## RU-3. The stochastic per-dimension slippage-ignore (p = 0.4) is missing — HIGH

**Metacat** (`answers.ss:1362-1371`): on every translation attempt, each conceptual
dimension present among the transform slippages is *dropped with probability 0.4* —
a designed source of answer diversity (the same rule + mapping yields different
translated rules on different attempts; this is part of how `mrrjjk` and `mrrkkk`
coexist, and how literal answers coexist with abstract ones).

**Petacat**: absent — translation applies every applicable slippage
deterministically; the only randomness left is the coattail probability.

**Consequences.** Translated rules are near-deterministic given the mapping; the
reachable-answer set per Workspace state shrinks. This is a direct
reachable-set change, not just a frequency shift.

**Fix plan.** In the translate path, collect the distinct CM-types of the
applicable transform slippages, drop each with `rng.prob(0.4)` (constant to
`engine_params.json`), and filter the slippages accordingly, per attempt.

## RU-4. Conflict detection reduced to same-object-same-dimension — HIGH

**Metacat** (`rules.ss:1321-1338` using the bidirectional implication heuristics of
`rules.ss:1194-1231`): transform pairs conflict via the full
`intrinsic-implies-intrinsic?` battery (Length-on-group vs LettCtgy-on-member,
GroupCtgy vs medium changes, enclosure at any level, …); failure raises the
**CONFLICT** snag naming both objects and dimensions.

**Petacat** (`rules.py:2235-2256`): `if obj1 is obj2 and dim1 is dim2` — nothing
else. The full heuristics exist in the same file (`rules.py:408-465`, used during
abstraction) but are not consulted at application time.

**Consequences.** Transform pairs Metacat rejects as CONFLICT snags are silently
applied in sequence — producing answer strings the reference cannot produce and
suppressing CONFLICT snags with all their trace/memory/jootsing consequences.

**Fix plan.** Build the intrinsic change-descriptions per transform and test with
the existing implication heuristics (both directions), raising `ImageFailure` with
`kind="conflict"` and both objects (feeds SN-4's snag typing).

## RU-5. Verbatim rules whenever no bridges exist; no rules-possible gate — HIGH

**Metacat** (`rules.ss:395-416`): the verbatim path fires at probability **0.01**
regardless of state; otherwise the scout fizzles unless
`get-possible-rule-types` is non-empty (all letters of both strings covered by
rule-describable bridges).

**Petacat** (rule-scout body): `if not bridges or prob(0.01):` — a verbatim rule
with probability **1.0** whenever no bridges exist (the entire early run), and no
possibility gate at all: rules are abstracted from whatever partial bridge set
exists (e.g. "change rightmost to d" from the lone c–d bridge, long before Metacat
allows any rule).

**Consequences.** The workspace floods with verbatim rules early; a verbatim top
rule is vacuously supported, so it opens the answer-finder gate and can translate
into the "modified-string-verbatim" answer (e.g. `abd` for target `xyz`) at far
above Metacat's frequency. Rules also arrive earlier and from weaker evidence,
shifting when answers appear and their character.

**Fix plan.** Restructure the body: draw the verbatim branch at 0.01 first;
otherwise consult the stored possible-rule-types (WS-2) and fizzle when empty;
choose the rule type from the possible set (justify mode picks among both when both
are possible, matching `rules.ss:404-409`).

## RU-6. Rule strength is raw quality, not rank-relative quality — HIGH

**Metacat** (`rules.ss:286, 244-251`): internal strength = `get-relative-quality` —
`100·rank/count` among the workspace's same-type rules (the best rule of n scores
100 regardless of absolute quality).

**Petacat** (`rules.py:938-961`): `calculate_internal_strength` calls
`get_relative_quality()` with the default `workspace=None`, which returns raw
quality. The rank logic exists and is unreachable from the strength path.

**Consequences.** The answer-finder's temperature-adjusted pick over rule
*strengths*, the evaluator's acceptance, and rule weakness for the breaker all run
on absolute quality — the percentile spreading that makes the best current rule
dominant is lost.

**Fix plan.** Give the rule access to its workspace at strength time (pass it
through `update_strength`, or store a back-reference at build); make
`workspace=None` an error rather than a silent fallback.

## RU-7. Rule evaluator/builder: wrong acceptance curve, no incumbent revision — MEDIUM

**Metacat** (`rules.ss:461-491`): the evaluator gates on `currently-works?`, then
fizzles with **raw** probability `1 − strength/100` (no temperature), posting the
builder at fixed high urgency; the builder, on meeting an equivalent incumbent,
runs `revise-abstracted-rule-information` (upgrading the incumbent's supporting
bridges when a previously-unsupported change is now supported — which changes
`supported?` and degree-of-support for the answer-finder), and posts the
answer codelet (CR-3).

**Petacat**: the evaluator uses temp-adjusted probability; both posts use
`round(max(1, rule.quality))`; the builder fizzles on duplicates with no revision
(no `revise` method exists).

**Fix plan.** Raw strength test in the evaluator; fixed urgencies (CR-6); implement
`revise_abstracted_rule_information` and call it on the duplicate path; CR-3 adds
the answer post.

## RU-8. Rule quality subformulas restructured; verbatim quality 10 vs 40 — MEDIUM

**Metacat** (`rules.ss:1544-1662`): uniformity = weighted-average(5,5,1) of
[intrinsic uniformity (per-dimension `2·|p−½|` products × object-description
uniformity), mean of *cubed* extrinsic uniformities, clause-type ratio] squashed by
`exp(4(x−1))`, with ObjCtgy/BondFacet changes excluded; abstractness = sigmoid(3,40)
of the mean of up to three *per-category* averages; succinctness costs: intrinsic 1,
extrinsic 2 iff >1 object-description; a verbatim rule scores
`round((0·3 + 100·2)/5) = 40`.

**Petacat** (`rules.py:795-936`): unweighted mean of ad-hoc homogeneity factors
(no exclusions, no cube, no 5/5/1; single-clause rules short-circuit to 100), one
flat pooled depth mean, different cost table (extrinsic = n_objects; a
subobjects-only intrinsic clause costs 0.5, letting succinctness reach 114), and
verbatim hardcodes **10** — the Scheme's *intrinsic-quality* constant, a different
quantity. The seed coefficients for the Scheme weights exist in
`formula_coefficients.json` and are never read.

**Consequences.** Quality ranks — which are rule strength (RU-6), evaluator
survival, the progress-watcher's `satisfactory_rule_quality=80` test, and 60% of
answer quality — systematically differ for multi-clause, extrinsic, and verbatim
rules (a verbatim answer's quality moves by 18 points).

**Fix plan.** Port the three subformulas exactly, reading the existing seed
coefficients; delete the verbatim short-circuit and let the formula produce 40.
Table-driven unit tests from hand-computed Scheme values over representative
rules.

## RU-9. Whole-string object-descriptions: no spanning-group resolution or translation — MEDIUM

**Metacat**: a `('string StrPos whole)` object-description resolves to the
**spanning group if one exists**, else the string (`workspace-strings.ss:429-444`);
translation converts whole-string ODs to group/string form according to whether the
*target* has a spanning group (`answers.ss:1506-1510`).

**Petacat** (`rules.py:2210-2211, 1122-1129`): resolves to `[string]`
unconditionally and passes the `'string'` token through translation unchanged.

**Consequences.** A rule abstracted before the spanning group existed, or
translated onto a target with one, aims transforms at the string image — whose
`new_length` always fails — snagging where Metacat succeeds; `subobjects` changes
hit the spanning group itself instead of its members (different answer letters in
the abc→aabbcc family).

**Fix plan.** Port both conversions; the group-vs-string interchange logic already
exists in `rules_equal`, so reuse its detection.

## RU-10. Translated-rule quality copied; translated bookkeeping absent — MEDIUM

**Metacat** (`answers.ss:987`, `rules.ss:164-189`, `answers.ss:1074-1142`): a
translated rule's quality values are **recomputed** (slippages change the
literal/relation mix and depths); `set-translated-rule-information` installs real
concept-mappings on the answer bridges and the rule's theme pattern;
`attach-length-to-appropriate-groups` and irrelevant-group pruning shape the
answer string's recorded structure.

**Petacat** (`rules.py:1095-1098`, `answers.py:320-424`): the four numbers are
copied from the original; answer bridges get identity-only CMs; no theme pattern,
no length attachment, no pruning.

**Fix plan.** Recompute quality after translation; port
`set_translated_rule_information` (also closes TH-4 and part of JU-1); port the two
answer-string post-processing steps.

## RU-11. Translated-clause validity check missing — MEDIUM

**Metacat** (`answers.ss:1304-1305, 1536-1557`): `valid-rule-clause?` rejects
translated clauses whose descriptor/category/relation combinations are nonsense —
translation returns failure and the answer-finder fizzles ("Couldn't translate
chosen rule").

**Petacat**: no counterpart; an invalid clause flows into `apply_rule`, matches no
objects, and is silently skipped (`rules.py:2130-2131`) — yielding an
*unchanged-target* answer instead of a fizzle. `translate_rule` returns None only
when the vertical mapping has zero CMs, so "couldn't translate" effectively never
occurs.

**Fix plan.** Port `valid_rule_clause` and check every translated clause; fizzle
the answer-finder on failure. Also remove the blanket
`except Exception: return None` in `apply_rule` (`rules.py:1998-2006`), which
converts engine defects into silent snags.

## RU-12. Smaller rule/image divergences — MEDIUM

- **Swap clustering derandomized** — `_bounded_random_partition`
  (`rules.py:2484-2496`) ignores `rng` and the random class-size bound
  (`utilities.ss:790-812`); once RU-1 revives swaps, this removes reachable rule
  variants. Fix: implement the random insertion order and bound.
- **`extend` succeeds where Scheme fails** (`images.py:582-591` guards
  `letter_arg is not None` and silently copies; `images.ss:326-345` fails the
  application → CHANGE snag for groups with no uniform sub-relation, e.g.
  `[aa][b][cc]`). Fix: fail on missing relation args.
- **StrPos multi-candidate disambiguation** (`workspace-strings.ss:449-458`: pick
  the lowest-level object, preferring ones with vertical bridges; Petacat returns
  all matches → double application / spurious conflicts).
- **Change-template descriptor pick not temperature-adjusted**
  (`rules.py:1809-1818` raw depths vs `temp-adjusted-values`, `rules.ss:896-899`).
- **Answer reporting**: no fresh `update_everything` and no clamp-undo before
  recording (`answers.ss:24-26`), so stored temperature/quality lag a cycle and a
  live clamp survives into a resumed run.

---

# 13. Trace and Episodic Memory

## TM-1. Answer-description vertical theme pattern built from a different recipe — HIGH

**Metacat** (`answers.ss:155-220`): the pattern is assembled dimension-by-dimension
over the five permitted dimensions: (1) themes from recent, still-present important
**slippage events** take precedence; (2) StringPos — copy the Direction relation if
a Direction entry exists, else the *dominant* StringPos theme, else identity
(always present); (3) BondFacet identity excluded; (4) any *other* dimension enters
as identity **only when a whole-string identity concept-mapping exists on the
spanning vertical bridge**; (5) otherwise the dimension is absent. Event liveness
uses *equivalence* (`bridge-present?`), so a broken-and-rebuilt bridge keeps its
slippage.

**Petacat** (`answers.py:169-237`): `pattern = dict(dominant)` — the **full
dominant Themespace pattern seeds every dimension** — then trace slippages overlay,
then the StringPos identity fallback. The docstring itself says only "two of its
rules are reproduced here". The StringPos←Direction rule and the
whole-string-identity gate are absent; liveness is `id(bridge) in live` (identity,
not equivalence); and `_trace_slippage_themes` reads *all* non-identity CMs off the
event's bridge rather than the recorded important slippage.

**Consequences.** The vertical theme pattern is the index an answer is stored,
compared, and reminded under. Dominant Direction/GroupCtgy themes with no
supporting whole-string identity CM enter descriptions the Scheme would omit;
rebuilt bridges lose their slippages. Every reminding distance and stored
comparison shifts.

**Fix plan.** Implement the Scheme recipe literally (the five-dimension loop with
its precedence order); store the specific important slippage on the CM event (not
just the bridge); use equivalence-based liveness. Unit-test against hand-worked
patterns for a crosswise `xyz` answer and a plain `abd`-style answer.

## TM-2. Reminding distance diverges in three components — HIGH

**Metacat** (`memory.ss:494-583`): distance = base 1 + theme component (differing ×1
+ unique ×2 ×2) + **top-rule** distance (2 × the number of concept pairs that
differ *and differ in conceptual depth* — leftmost-vs-rightmost counts 0 — via
`traverse-rule-clauses`; abstractness fallback on structural non-alignability) +
justification component over `(dimension relation)` entries with **snag-justified
themes subtracted** and already-counted themes excluded + coherence mismatch.

**Petacat** (`memory.py:211-285`): adds a **bottom-rule** distance term with no
Scheme counterpart; `_rule_distance` counts unequal clause entries with **no depth
filter**; the justification component compares dimension-only key sets with no
snag-justified subtraction and no differing-theme exclusion. The faithful pieces
exist in `answer_comparison.py` (`compare_rule_signatures`,
`count_rule_differences`, `common_a_only_unjustified`) and are not used by
`distance`.

**Consequences.** Distances are systematically inflated or misweighted against the
threshold of 5 — fewer and weaker remindings, i.e. the memory-feeds-back-into-
perception channel operates on wrong similarity.

**Fix plan.** Rebuild `distance` on the `answer_comparison.py` primitives: top
rules only, depth-filtered pair differences, the Scheme's justification chain.
Table-test against hand-computed distances for the dissertation's `xyz` answer
pairs.

## TM-3. Snag identity judged by English text; clause lists not stored — MEDIUM

**Metacat** (`memory.ss:78-89, 289-291`): snag equality = three problem strings +
structural `rule-clause-lists-equal?`; snag descriptions store the clause lists.

**Petacat** (`builtins.py:1126-1128`, `memory.py:102-112, 298-304`): dedup compares
the rule's **English transcription**; no clause lists stored. Two structurally
different rules with identical prose collide; any rule transcribing to "Unknown
transformation" collides with every other such rule — the exact hazard
`rules.py:1245-1254` documents for answers is left open for snags.

**Fix plan.** Store `rule_signature` clause lists on `SnagDescription`; compare
structurally.

## TM-4. Slippage events from CM accretion never occur — MEDIUM

**Metacat** (`bridges.ss:1213-1226`): CMs added to an existing bridge are monitored
into the Trace — a second source of slippage events (common for spanning bridges
late in a run). **Petacat**: no accretion (BR-9), and the one `add_concept_mapping`
path (auxiliary slippages, `themes.py:1015`) is unmonitored.

**Fix plan.** BR-9 restores accretion; run the slippage monitor on the added CMs in
both paths.

## TM-5. Smaller trace/memory divergences — MEDIUM

- **Unjustified theme pattern lacks the BondFacet augmentation**
  (`answers.ss:239-263`: an unjustified BondFacet slippage adds default GroupCtgy
  and Direction entries; `answers.py:307-317` doesn't) — alters `all_themes`,
  distance, and the §4.7.3 comparisons.
- **Memory answer activations not reset at run start** (`run.ss:212`
  `clear-activations`; `runner.py` never touches them, and they persist through DB
  rehydration).
- **Answer event recorded without the fresh update / clamp-undo** (see RU-12) and
  with thinned display content (no cognitive reader affected).
- **Concept-activation events carry no node** (`runner.py:719-726` records a
  description string, strength 0) — harmless today, wrong the moment any consumer
  reads them.

---

# 14. Themespace edges

(The Themespace core — clusters, dynamics, dominance, clamping, pressure,
theme→slipnet — was verified equivalent in detail. These are its edges.)

## TH-1. No Themespace boost when a bridge is built — MEDIUM

**Metacat** (`bridges.ss:1349-1352`): `boost-themespace-activations` runs
immediately after `build-bridge` — *in addition to* the per-cycle boost of all
built bridges. **Petacat**: only the per-cycle path (`runner.py:727-750`).

**Consequences.** Themes lag up to 15 codelets behind bridge construction; a bridge
built and broken within one cycle leaves no thematic residue; dominance readouts
taken between cycles (rule building, answer descriptions, slippage importance) can
differ near the 90-point margin.

**Fix plan.** Call the boost (and the dominant-theme update) from the bridge build
path.

## TH-2. Group bond descriptions leak into theme boosting and support tests — MEDIUM

Covered under BR-12 (third bullet): `boost_themes`,
`get_associated_thematic_relations`, and `_check_descriptions` must walk plain
`descriptions`, not `get_all_descriptions` — in the Scheme, BondCtgy/BondFacet
themes are never boosted by bridges and never satisfy support tests through
description pairs; this is exactly why the dissertation's 66-theme count treats
those clusters as inert.

## TH-3. Bridge–theme incompatibility tests description presence, not possibility — MEDIUM

Covered under BR-12 (second bullet). Active only under thematic pressure — but then
it directly shifts fight outcomes.

## TH-4. Translated rules never receive their theme pattern — MEDIUM

Covered under JU-6/RU-10: implement `set_translated_rule_information`
(`rules.ss:184-188`) so justify clamps stop silently dropping the translated
rule's pattern.

---

# 15. Main loop

## ML-1. `init_mcat` omits the initial workspace-values update — MEDIUM

**Metacat** (`run.ss:233`): `update-workspace-values` runs before the first
codelet, so importances and saliences derive from the just-activated descriptors.

**Petacat** (`runner.py:243-336`): no such call — all objects start with
`relative_importance = 0.0`, so for the first 15 codelets every weighted object
choice degenerates to uniform.

**Consequences.** The opening scouts pick objects uniformly; leftmost/rightmost
letters lose their designed head start for the entire first cycle.

**Fix plan.** Call `update_all_structure_strengths`, `update_all_object_values`,
and `update_average_unhappiness_values` at the end of init.

## ML-2. Smaller loop divergences — LOW

- **Codelet count incremented before execution** (`runner.py:457` vs
  `run.ss:178-183` after) — every time-stamp and event `codelet_count` is one
  higher than the reference.
- **Empty-rack repost timing** — Scheme checks after each codelet *before* the
  update (`run.ss:155-159`); Petacat at the top of the next step, after
  `update_everything` has posted, so an exactly-at-boundary empty rack skips the
  repost and the initial-slipnode re-clamp.
- **Frozen nodes accept incoming spread** (`slipnet.py:213-217, 650-653` buffer
  into frozen nodes; `slipnet.ss:157-163` refuses) — observable for concept
  patterns clamped below 100.
- **Thematic posting ordered before top-down** (`runner.py:804-814`) — folded into
  CR-5's batch fix.

---

# 16. Low-severity bundle — LOW

Collected small items, each with its one-line fix:

| Item | Scheme | Petacat | Fix |
|---|---|---|---|
| Enclosed-importance factor | exact `2/3` (`workspace-objects.ss:432`) | `0.667` default parameter; seed value not even passed (`workspace_objects.py:423-431`) | use `2/3`; wire or delete the coefficient |
| Bond-relevance rounding | exact rational into strength math (`workspace-strings.ss:360-376`) | pre-rounded to int (`workspace.py:265`) | keep fractional |
| Per-string intra-unhappiness rounding | rounded (`workspace-strings.ss:336-338`) | unrounded (`workspace.py:135-139`) | round |
| CM strength cap | uncapped — deep slippage can exceed 100 (`concept-mappings.ss:130-135`) | `min(100, …)` (`concept_mappings.py:80`) | drop the cap |
| `description_type_support` rounding | local support `100*`-rounded before averaging (`workspace-structure-formulas.ss:57-67`) | fractional (`formulas.py:375-377`) | round first |
| Description theme-types | target → bottom-bridge only in justify (`descriptions.ss:54-61`) | always both (`descriptions.py:128-129`) | gate on justify mode |
| Zero-importance fallback | weighted-average with zero weights → 0 (`utilities.ss:388-392`) | unweighted mean (`workspace.py:517-521`) | return 0 (reachable only pre-first-cycle; moot after ML-1) |
| `symmetric` singleton pick floor | zero-support side unreachable (`utilities.ss:443-448`) | 0.1 floor in the singleton direction pick | CC-6 |
| `get_related_node` fallback | category-sharing member or none (`slipnet.ss:123-129`) | falls back to `related_nodes[0]` | return None |
| Unlabeled-link length fallback | 0 → assoc 100 | 50 / 0.0 (`slipnet.py:522`) | align (unreachable with shipped seeds) |
| Initial description order | object-category before letter-category | reversed | align while touching SL-2 |
| Shadowed `get_possible_descriptors` | — | permissive first definition shadowed by the faithful second (`slipnet.py:246-255` vs `380-390`) | delete the dead permissive copy |
| Manual-clamp `unclamp_theme_pattern` | releases only the pattern's theme type (`trace.ss:1538-1542`) | `unclamp_all()` — every type, pressure off globally (`themes.py:729-735`) | release per-type |

---

# Appendix A — Suggested fix order

The findings interact; fixing them in dependency order keeps each phase verifiable.

**Phase 1 — the stochastic substrate (CC-1 … CC-6).** Everything else's
probabilities are computed through these. Land them together with the unit tables;
regenerate the expected range once at the end of the phase and review the new
stopping states.

**Phase 2 — the measured quantities (WS-1 … WS-6, SL-1, SL-2, ML-1, CR-1, CR-2).**
Temperature, posting inputs, eviction, and init now measure what the Scheme
measures.

**Phase 3 — the snag/clamp/self-watching loop (SN-1 … SN-5, CL-1 … CL-4, JO-1 …
JO-5, JU-1 … JU-6).** This is a coherent subsystem; SN-2 needs `Coderack.clear`,
CL-1 is a prerequisite for CL-2 and JU-5 to have their Scheme effect.

**Phase 4 — perception codelets (BD-*, GR-*, BR-*, SL-3, SL-4, CR-3 … CR-6).**
Largest phase; go structure by structure (bonds → groups → bridges), since group
fixes (GR-5/GR-6) change the workspace states the bridge fixes are tested on.

**Phase 5 — rules, translation, answers, memory (RU-*, TM-*, TH-*).** RU-1 and
RU-4 restore missing snag kinds, so SN-4's typing lands here too.

After each phase: run the full suite, rebuild
`tests/fixtures/expected_range.json`, and review the diff of reachable stopping
states — new answers appearing are expected (many findings *removed* reachable
answers), but each should be recognizable as one the Scheme could produce; I'll
present any new ones for your judgment rather than accepting them silently.

# Appendix B — What was verified equivalent

For legibility of coverage, the major mechanisms confirmed to match (beyond the
per-section notes): the Slipnet data layer in full (59 nodes, 202 links, depths,
intrinsic/shrunk lengths, label topology, initial clamps, codelet attachments);
spreading arithmetic and buffer semantics at the default threshold; the Themespace
core (27 clusters / 75 themes, three-pass Jacobi dynamics, dominance margin,
clamping semantics, pressure gating, theme→slipnet, thematic scout skeleton,
auxiliary-slippage ladder); temperature arithmetic given its inputs;
`temp_adjusted_values` itself; structure-strength composition and weakness; bond
internal strength and `11·√assoc`; bridge internal/external strength formulas and
the supporting/incompatible CM core; description strength and the 0/20/60/90/100
support ladder; rule support product and `currently_works`; the images layer
including the z-successor failure (no wraparound anywhere — the `xyz` snag itself
is intact); the answer-finder's four gates in their Scheme order (restored by
commit `34535e3`); `answer_present` memory feedback at its two live sites; trace
event types, importance thresholds and formulas; clamp-period bookkeeping
(750/250/100 constants and expiry); jootsing's snag-overlap math and negative-
pattern construction; the coderack's bins, selection structure, capacity, posting
probability formulas and urgency ladder; and the update cycle's step order.

---

*Produced by a static parity scan; no code was executed and no fixes have been
applied. Every finding cites the exact lines compared; where a faithful Petacat
implementation already exists as dead code, the fix plan points at it.*
