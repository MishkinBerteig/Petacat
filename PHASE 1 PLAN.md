# Phase 1 Plan — Growing the Slipnet: New Concepts and Connections

**Goal.** Work out how Petacat creates **new concept nodes and new links** in the
Slipnet, staying entirely within letter-string analogies but introducing **capital
letters**, which the system does not currently know.

**Scope — purely internal.** The mechanism must be **self-contained**: no teacher, no
external inquiry, no dependence on anything Phases 2–5 introduce. It builds on what
the system already has — the **existing episodic memory**, **new codelets**, and a
**sub-perceptual frequency-accumulation system modelled on BPE** — and nothing else.
Learning by asking (curiosity, inquiry codelets, a teacher who supplies links) is
explicitly **Phase 6** work and must not leak into this phase; if the internal
mechanism can only be made to work by asking someone, that is a finding to report,
not a licence to import Phase 6.

**Depends on.** Phase 0, now built (Fast Run makes the many short experiments here
affordable; Audit mode is how a single acquisition episode gets explained). One item of
Phase 0's is carried forward into this phase rather than closed there — see *Carried
forward: parallelism beyond sharding* below, which is unimplemented work this phase
owns.

**Starts with Step 0 (§0).** All configuration moves into the database and is actually
read from it. Everything else in this phase is expressed as data, so this comes first.

**Why capitals.** They are the smallest possible expansion of the perceptual space
that is still a genuine one. Unlike arbitrary bytes (Phase 3), capitals arrive with
an *intended* relational structure we can check the system against: `A` is a
successor of nothing and predecessor of `B`; `A` corresponds to `a`; the whole
sequence `A…Z` is isomorphic to `a…z`. So we can ask a sharp, falsifiable question —
did the system discover that structure, or merely memorise instances? Arbitrary
bytes cannot be graded that way. This phase is the controlled experiment that Phase 3
generalises.

---

## 0. Step 0 — all configuration lives in the database

**The requirement.** Fix the system to load all configuration from the database (not the
JSON) on startup: all rules, codelets, slipnet, thresholds, parameters, **everything**.
This is a **bi-directional** change. It may require new database columns or tables to
hold values that are currently hardcoded — with the JSON files doing the initial load —
and it may require currently-hardcoded code paths to read from the database instead.
**Every small change that carries one value from JSON seed → database → runtime, and
back out as an editable database field, must be implemented with guard tests.**

### 0.1 What is actually broken

The load *path* already exists and is not the problem. `server/main.py` seeds twelve bulk
JSON files into the metadata tables under a content fingerprint, and
`metadata_service.load_metadata_from_db` builds the `MetadataProvider` the engine runs
on. The app reads the database. (`MetadataProvider.from_seed_data` is the test and
script path.)

The problem is the other end: **the engine ignores much of what it loads, and other
values were never given a database representation at all.** Measured — a copy of
`seed_data` with every `posting_formula` set to `0.0`, every `count_formula` to `0`,
every `count_values` to zero, every urgency to `0`, every `condition` to `"never"`, and
`initial_codelets` emptied:

| | seed 42 | seed 7 | seed 900001 |
|---|---|---|---|
| shipped | `mrrkkk`, 777 codelets | `mrrkkk`, 871 | `mrrkkk`, 598 |
| everything zeroed | `mrrkkk`, 777 codelets | `mrrkkk`, 871 | `mrrkkk`, 598 |

Bit-identical, on `abc → abd; mrrjjj → ?`. A configuration reading "post nothing, ever,
at zero urgency" runs exactly like the shipped one.

**And the failure is silent in the worst possible direction.** The same edit changes the
config hash (`f22b4640…` → `2739bb68…`, via `hashing.py:80`) and is displayed back
through the admin API. So a change is accepted, stored, hashed, and shown — and the
engine does not read it. Phase 0 named this exact hazard when it made 25 parameters
per-Run: *"a parameter accepted, stored and displayed but never applied is the worst
outcome, because everything looks right."*

### 0.2 The three kinds of work

**(a) Loaded but ignored — needs an evaluator.** Of the eight fields on a posting rule,
five are dead everywhere: `posting_formula`, `count_formula`, `count_values`,
`urgency_formula`, `condition`. Their only occurrences in `server/` are the
`PostingRuleSpec` declaration (`metadata.py:86-90`) and the two loaders that populate it
(`metadata.py:231-234`, `metadata_service.py:118-122`). Nothing compiles or evaluates
them. The remaining three — `codelet_type`, `direction`, `triggering_slipnodes` — are
live *only* on the five `top_down` rules (`runner.py:1286-1291`; verified by mutation,
which changes the answer), and dead on all eleven `bottom_up` rules, because
`_post_bottom_up_codelets` never reads `meta.posting_rules` at all. `initial_codelets`
in the same file is dead too.

**(b) Hardcoded with no database representation.** `bottom_up_types`, a Python list
literal of eleven strings (`runner.py:1020-1032`); the three switches keyed on codelet
name — `_compute_posting_probability` (`runner.py:1087`), `_compute_num_to_post`
(`runner.py:1163`), `_compute_bottom_up_urgency` (`runner.py:1231`); the opening
population in `_post_initial_codelets` (`runner.py:583-587`); `MIN_SHARD_CAPACITY = 25`
(`coderack_shards.py:185`), which the *Carried forward* section below needs to sweep.

**(c) Two sources of truth for one concept.** `codelet_patterns.py:23` hardcodes five
clamp patterns in Python, consumed by the control API (`api/controls.py:211,245,265`)
and `run_service.py:1736,1755`. The engine's own clamp sites read a *different* set of
nine from the database (`meta.codelet_patterns` — `jootsing.py:253,429`,
`justify.py:403`). Same concept, two definitions, different contents. Cases like this
are the reason the change is bi-directional rather than a one-way migration: the
duplicate has to be resolved, not merely re-homed.

### 0.3 The pattern to follow — it already exists here

The missing shape is in this codebase, at `slipnet.py:113-143`: a namespace of
names → callables (`DESCRIPTOR_PREDICATE_NAMESPACE`), a compile-at-load step
(`compile_descriptor_predicate`) that **raises at startup** on a bad expression rather
than failing silently mid-run, and a call site that invokes it (`slipnet.py:801-804`).
`SlipnetNodeDef.descriptor_predicate` got all three. `PostingRuleSpec.posting_formula`
got the column, the loader, the admin API and a place in the config hash, and none of
the three.

The formulas are already written as expressions against a small vocabulary —
`average_intra_string_unhappiness`, `min_mapping_strength`, `possible_rule_types`,
`temperature`, `thematic_pressure`, `within_snag_or_clamp_period`,
`num_unrelated_objects_based`, `conceptual_depth`, `activation` — so the work is to give
those names values, compile the expressions at load, and change the two `_compute_*`
signatures to take **the rule** rather than the rule's name. That is where the gap is
visible in a single line: `runner.py:1293` holds a `PostingRuleSpec` whose
`posting_formula` states the answer, and passes `rule.codelet_type` into a switch that
re-derives it by matching the name against string literals.

### 0.4 Guard tests — what one has to assert

A guard test that only checks the value round-trips JSON → DB → `MetadataProvider` is
not a guard test, because everything above already passes that. Each one must assert
**both** directions:

1. The shipped database value reproduces today's behaviour exactly.
2. **A changed database value changes the run.** This is the assertion that would have
   caught the current state, and the only one that distinguishes "wired" from "stored".

Note the trap: the config hash moves on any edit, so *hash difference is not evidence
the value is live*. The assertion has to be on the run — status, answer, codelet count —
as in the table in §0.1. Phase 0's per-Run parameter table is the model: each row is one
override, with the codelets and answer it produced.

### 0.5 The bar

**No cognitive change.** This is Phase 0's constraint applied inside Phase 1: the
seventeen posting rules must reproduce the current switches exactly before a single new
rule is added, and `MIN_SHARD_CAPACITY` must still be 25 when it becomes a row. Verified
against Metacat's oracle per §5 — a data-driven engine that reaches a different set of
stopping states is a different engine, not a refactor.

**But know what the oracle does not measure.** `scripts/compare_to_metacat.py` compares
**set membership**: which stopping states a problem can reach. It says nothing about
*how often* each is reached. Petacat gave up on `abc→abd;xyz` at 22.5% against Metacat's
10.9% — a 2× skew, decisive at n=1000 — and the oracle reported "0 missing, 0 novel" the
whole time, because `gave_up` is in both sets. The root cause was three arithmetic
divergences inside one function (D-10 in `DISCREPANCIES5.md`).

Two consequences for the work below:

- A green oracle is necessary, not sufficient. Where a change could plausibly move a
  *rate*, measure the distribution over several hundred seeds and compare it to a real
  Metacat run, not just the stopping-state set.
- Two other frequency divergences on this problem are open and unexplained: `xyd` at
  22.2% against a reference 37.1%, and `xyz` at 24.7% against 15.8%. Those are a
  different mechanism from the give-up rate, which moved without moving them.

### 0.6 Why this phase owns it

Because the rest of the phase is unbuildable on top of it. §2's noticing codelet is a new
codelet type; today a new type added as data is accepted, hashed, displayed in the admin
panel, and **never posted**, because posting is a Python switch that has never heard of
it. §5's provenance marker and the new node and link rows are the same bi-directional
change in the Slipnet tables. And the *Carried forward* sweep cannot vary
`MIN_SHARD_CAPACITY` while it is a module constant.

The phase's premise is "growth is data, not code" (§5). Step 0 is the work of making
that true.

### 0.7 The unread formula coefficients

**Status: enumerated, not started.** Everything above §0.7 is done — the posting rules,
the codelet patterns, the descriptor predicates, the shard floor, the initial codelets
and nine engine parameters are read from the database, each with a guard test in both
directions. This subsection is the remainder, found by auditing what the engine reads
rather than by working from §0.2's list, and it is larger than §0.2 was.

`seed_data/formula_coefficients.json` holds **79** keys. All 79 are loaded into
`MetadataProvider.formula_coefficients` (`metadata.py:209`), exposed through the admin
API (`admin.py:623-670`) and folded into the config hash (`hashing.py:83`).
`get_formula_coeff` names **32** of them. The other **47** are the §0.1 condition
exactly — "a change is accepted, stored, hashed, and shown — and the engine does not
read it" — in a table §0.2 did not look at.

| | count | |
|---|---:|---|
| **read** | 32 | wired |
| **dead, with a literal to replace** | 44 | the worklist below |
| **dead, with no consumer at all** | 3 | seed data for an unported function; see D-10 |

#### The two hazards specific to this work

**Backend copies.** Nine of the 44 have a duplicate in each numeric backend
(`python_backend.py`, `numpy_backend.py`, `mlx_backend.py`). The vectorised paths
dispatch above `DEFAULT_VECTORISE_THRESHOLD = 512` (`numeric/backend.py:140`) — the
shipped 59-node Slipnet and 81 themes are both below it, so **a stale copy in a backend
is invisible to the whole suite at default size**. Every slice that touches one must be
re-run with the threshold lowered, and once per forced backend. The one mercy: the Metal
kernel holds no coefficient of its own; its tunables arrive through the `params` buffer,
already parameterised.

**Three seeded values disagree with the code.** `enclosed_group_importance_factor` is
`0.667` in the seed and `2.0/3.0` in the code; likewise `edge_object_bond_factor`
(`0.333` vs `/3`) and `interior_object_bond_factor` (`0.167` vs `/6`).
`workspace_objects.py:474-483` already documents the choice and its reason. Wiring these
as seeded **changes results**. Decide the seed values before substituting, or a slice
that should be a no-op will move the baseline and the failure will be correct.

#### The worklist

| # | Group | Items | Sites of note |
|---|---|---:|---|
| D-1 | Slipnet | 3 | `slipnet.py:262,394,575,1029`; the jump exponent has a copy in all three backends |
| D-2 | Structure weakness | 1 | `workspace_structures.py:136` |
| D-3 | Bonds | 6 | `bonds.py:71,73,77,79,103,128`; duplicated at `formulas.py:111,538` |
| D-4 | Groups | 6 | `groups.py:210,213,214,220` |
| D-5 | Bridges | 7 | `bridges.py:214-222,261-267,412`; `0.1` written four times in `_singleton_factor` |
| D-6 | Concept mappings, theme sigmoid | 3 | `concept_mappings.py:105,119`; `bridges.py:920` |
| D-7 | Object importance, unhappiness, salience | 9 | `workspace_objects.py:472,509,513,586-615,671-674,724`; **four copies per salience weight**, across the three backends |
| D-8 | Themespace alpha | 1 | `themes.py:300`; `python_backend.py:263`, `numpy_backend.py:191`, `mlx_backend.py:343` |
| D-9 | Shared formula helpers | 7 | `formulas.py:57,60,62,173,345,354`; `builtins.py:2128` |
| D-10 | *(not wiring)* rule intrinsic quality | 3 | `compute-rule-intrinsic-quality` (`rules.ss:1664-1711`) is **unported**; the three coefficients are its seed data, not vestigial |

**The seam most of this needs.** `WorkspaceObject`, `Bond`, `Group`, `Bridge`,
`ConceptMapping`, `SlipnetNode` and `Slipnet` carry no `MetadataProvider`, and the
strength updates are reached from `WorkspaceStructure.update_strength(rng)` and
`Workspace._update_strengths_batched`, neither of which has one either. There is a
precedent to follow rather than invent: `WorkspaceStructure._themespace`
(`workspace_structures.py:28,43`, set from `runner.py:351,366` and
`review_service.py:110,114`) is already bound as a class attribute for exactly this
reason. `ThemeParams` (`numeric/layout.py:377-402`) is the precedent for the backends.

#### Ordering

Ten slices, each verifiable on its own by `.venv/bin/python -m pytest tests/ -q` plus
the nine-run bit-identity check (`abc → abd` with `mrrjjj`, `ijk`, `xyz` at seeds 42, 7,
900001). Slices 0-7 must be **bit-identical**; 8 and 9 are expected to move, which is
why they are last and alone.

| # | Slice | Identical? |
|---|---|---|
| 0 | Decide the three rational values. No code change. | n/a |
| 1 | Build the seam. No substitutions. | yes — nothing reads it yet |
| 2 | D-9 less the exponents; delete the dead `formulas.single_letter_group_probability` | yes |
| 3 | D-3 + D-4 — bonds and groups, the first real consumer of the seam | yes |
| 4 | D-5 + D-6 — bridges and concept mappings | yes |
| 5 | D-2 + D-1 — weakness and Slipnet; verify per forced backend | yes |
| 6 | D-8 — one coefficient, four copies | yes |
| 7 | D-7 salience — the four weights, twelve sites. Re-run per backend **and** with the vectorise threshold lowered | yes, only if every backend copy moves |
| 8 | D-7 importance and unhappiness — per the slice-0 decision | only if slice 0 chose exact rationals |
| 9 | The three single-letter-group exponents — see `DISCREPANCIES5.md` | expected to move |

#### Adjacent, tracked here so it is not lost

- Port `compute-rule-intrinsic-quality` (`rules.ss:1664-1711`), which D-10's three
  coefficients belong to.
- `current_translation_temperature_threshold` (`formulas.py:249`) reads four
  coefficients and **has no caller** outside its own test. Find its call site
  (`formulas.ss:38-59`, invoked from the rule translator) or record why the port does
  without it.
- Two `meta is None` fallbacks — `trace.py:63` and `formulas.py:291-294` — are not the
  §0.1 condition, because the fallback is taken only when there is no provider at all.
  They are still second copies of the numbers; delete them by making `meta` required.

---

## 1. The concrete starting point

Today's perceptual apparatus is two short passages. Text becomes objects in five lines,
`server/engine/workspace.py:116-120`:

```python
for i, ch in enumerate(text):
    node_name = f"plato-{ch}"
    letter_node = slipnet.nodes.get(node_name)
    letter = Letter(self, i, letter_node)
    self.objects.append(letter)
```

and those objects acquire their initial descriptions in `_add_initial_descriptions`
(`server/engine/runner.py:455-520`). The line that decides this phase's starting point
is the guard at `runner.py:506`:

```python
if letter_cat_node and letter.letter_category:
```

A letter whose node is `None` has no `letter_category`, so its letter-category
description is skipped — silently, by a condition that reads as ordinary defensiveness.

`slipnet.nodes.get("plato-A")` returns `None`. Verified behaviour on
`abc → abd; XYZ → ?` (numpy backend, no codelet cap, seeds 42 / 7 / 900001):

- Initialisation **succeeds** — no exception.
- The target string's three objects are created with `node = None`, and carry two
  descriptions each — `object-category: letter` and a string-position — against three
  for `abc`, which also carries `letter-category: a`.
- The run **gives up**: status `gave_up`, no answer, after 4,459 / 3,217 / 5,178
  codelets. `XYZ` ends the run with 0 bonds and 0 groups; temperature never leaves 100.

**The degradation is partial, not total, and the boundary is exactly the missing
description.** Three vertical bridges *are* built between `abc` and `XYZ` — on the two
descriptions the nodeless letters do carry. Two of them even carry a slippage
(`leftmost` → `rightmost` under `opposite`). What cannot happen is anything that needs
letter-category: no letter-category bond, so no successor or predecessor relation
within `XYZ`, so no group over it, and no letter-category concept-mapping in a bridge,
so nothing for a rule to describe. The system sees three objects in the right places
and has nothing to say about what they are.

**This is the right baseline behaviour, and it should be preserved.** Degrading rather
than crashing on unfamiliar input is what a perceptual system ought to do — it is the
property that makes it safe to feed capitals in at all, and every later phase that
widens the perceptual space depends on it. Nothing in this phase should trade it away.

What is missing is not robustness but **a signal**. The system absorbs the unknown
symbol and carries on, and no part of it registers that it was unable to describe
something. So the first deliverable is to make the system *notice* — an object it
cannot describe should raise a signal while still being handled as gracefully as it is
today. Noticing is an addition to this behaviour, not a replacement for it.

## 2. What this phase must produce

Three capabilities, in dependency order — all of them downstream of Step 0, which is the
substrate they are expressed in rather than a capability of its own. (The `(0)` below
numbers a cognitive capability; §0 numbers the phase's first work item. They are
different things.)

- **(0) Noticing.** The system can tell that an object is unrelatable — that it has
  no concept, or a concept with no useful links. Today it cannot.
- **(a) New nodes.** A concept is created for a novel symbol and takes its place in
  the Slipnet with a conceptual depth.
- **(b) New links.** The new node is *wired* — related to existing nodes by
  successor / predecessor / sameness / correspondence — because a node without links
  cannot participate in bonds, bridges, or rules, and `FUTURE_DIRECTION.md` §0's
  criterion is exactly that a concept must "participate in slippages and bridges and
  rules the way `successor` or `leftmost` already do."

**(b) is the hard part, and the point of the phase.** Creating a node is a database
insert. Wiring it is the research problem, and everything downstream — Phase 3's
tokens, Phase 2's love-born concepts, Phase 4's consolidated structure — depends on
solving it here in the easiest domain available.

## 3. Three internal mechanisms — the design space

The valence signal (`love`/`not-love`) that later drives concept formation does not
exist until Phase 2, and asking a teacher is Phase 6. So the mechanism must be built
from what the system already has. Three candidates, to be used singly or in
combination:

### 3a. A sub-perceptual frequency accumulator, modelled on BPE

The closest working analogue in machine learning is how a tokenizer builds a
vocabulary: count adjacent-pair occurrences across a corpus, merge the most frequent
pair into a new unit, repeat, and let a hierarchy emerge from nothing but counting.

Applied here, this runs **beneath perception** — not as codelets competing in the
coderack, but as a statistical layer accumulating across runs, proposing candidate
concepts that the perceptual layer then either uses or ignores. Two properties make
this attractive as the Phase 1 spine:

- It is **unsupervised and self-contained** — exactly the constraint of this phase.
- It has a **known-good precedent** at scale, so a failure is informative: if
  BPE-style accumulation cannot find structure in something as regular as `A…Z`, the
  approach will not survive contact with arbitrary bytes in Phase 3 either.

The departure from BPE is what happens *after* a candidate is proposed. A tokenizer
merges on frequency alone; here the candidate must be **wired into the Slipnet**, and
frequency says nothing about what a thing is *related to*. Frequency proposes;
something else must dispose.

### 3b. Utility — earning a place in the Slipnet

Petacat has a signal a corpus tokenizer does not: **did this candidate participate in
bonds, bridges, and rules that actually lowered temperature?** A frequent-but-useless
pattern is a worse concept than a rare-but-pivotal one.

This is the natural counterpart to 3a: frequency accumulates candidates cheaply,
utility decides which are promoted and which decay. It also generalises directly to
Phase 3, where it becomes the tokeniser's promotion gate.

### 3c. Episodic memory as the accumulator

Cross-run accumulation needs somewhere to live, and the **existing episodic memory**
is already cross-run by design and already stores rich structural descriptions of
answers — including the themes and rules that produced them. Reusing it, rather than
building a parallel store, keeps the phase honest about building on what exists.

**But it stores answers and snags, and nothing else.** `EpisodicMemory` holds an
`AnswerDescription` per answer — the two rules with their clause-list signatures, four
theme patterns, quality, temperature, abstractness — and a `SnagDescription` per snag
(`server/engine/memory.py:18-140`). It does **not** record which structures a given
object participated in: no bridge history, no bond history, no per-object record at all.
So the "participation history" §3 leans on for links is a **store that does not exist
yet**, not an existing one to be reused. That is the first concrete cost of this phase,
and it should be stated plainly rather than discovered during implementation: the honest
version of 3c is that episodic memory supplies the *cross-run persistence mechanism* and
a precedent for what a rich structural description looks like, while the evidence itself
has to be accumulated somewhere new.

This is also where Phase 0's work first earns its keep: episodic memory as a **named,
versioned input** with a recorded `memory-hash` means a growing concept vocabulary
does not silently break reproducibility. Whatever holds participation history will need
the same treatment, and for the same reason.

**[open — the load-bearing decision of this phase]** Which of these carries the
weight, and specifically **what supplies the links**. Frequency and utility both
identify *that* something is a unit; neither says *what it resembles*. The most
promising internal answer is that links come from the **structures the candidate
already participated in** — if a chunk was repeatedly bridged to `a` with a slippage,
that bridge history is the evidence for a link. Whether that is sufficient, or whether
internal evidence fundamentally cannot supply relational structure, is the question
this phase exists to answer.

## 4. Why relational structure is the thing being learned

Copycat's power comes from atoms living in a **small, totally-ordered, richly-related
space**. What makes `a…z` work is not that there are 26 of them but that they are
densely connected: successor, predecessor, sameness, and the alphabetic-position
facet. A newly created node with no such relations is inert regardless of how
correctly it was created.

So the measure of success in this phase is **not** "does `plato-A` exist" but "does
`A` behave like a letter" — can it be bonded, bridged, grouped, and slipped. That
distinction is what keeps (a) from being mistaken for (b).

**And the measure has to be read on the letter-category dimension specifically**, since
§1 shows a nodeless letter already gets bridged and already carries slippages on the
dimensions it does have. A bridge count going up is not evidence of anything. The
evidence is a successor bond *inside* `XYZ`, a group over it, and a bridge whose
concept-mappings include a letter-category pair — the three things that are impossible
today and that a wired node makes possible.

## 5. Design constraints

- **Do not regress a–z.** The existing curated Slipnet — 59 nodes, 202 links — is the
  reference. The standard is `scripts/compare_to_metacat.py`, which compares Petacat's
  set of reachable stopping states against **Metacat's own published oracle** over the
  nineteen demo problems, recorded in `ORACLE-COMPARISON.md` and
  `measurements/vs-metacat.json`. Petacat's former self-baseline
  (`tests/fixtures/expected_range.json`) was removed in `cc25a4a` precisely because a
  baseline sampled from Petacat could detect drift but never divergence; this phase
  measures against the reference implementation, not against its own past. Any
  degradation is a finding, not a cost.

- **The capitals half has no oracle, and needs a criterion of its own.** Metacat knows
  nothing about `A…Z`, so the external standard covers only the a–z half of this phase's
  work. There is no reference distribution for `abc → abd; XYZ → ?` and there will not
  be one. The phase's headline result therefore has to be graded against something it
  defines itself, and §6 states what: the same rule and comparable temperature as the
  lower-case twin, and transfer to capitals never encountered. Naming this now matters
  because the a–z oracle will keep passing while the capitals mechanism does nothing at
  all — a green run against Metacat is evidence of no regression, never evidence of
  acquisition.

- **Graceful degradation is preserved, not replaced.** An unknown symbol must continue
  to produce a run that completes, as it does today (§1). The noticing signal is added
  alongside that behaviour; it must not become an exception, a refusal to initialise, or
  any other way of turning an unfamiliar input into a failure. A system whose
  perceptual space is meant to keep widening has to stay resilient to the parts of it
  it has not learned yet.

- **Learned vs. innate must be distinguishable.** Every node and link gains a
  provenance marker. Phase 2's `not-love` removal, and every later pruning mechanism,
  depends on being able to protect the seed ontology from self-lobotomy. Establishing
  the distinction here is cheap; retrofitting it later is not.

- **Growth is data, not code.** New nodes and links are new rows in `slipnet_node_defs`
  and `slipnet_link_defs` (`server/models/metadata.py:126-152`) — native to the
  DB-driven design. No engine changes are needed to *hold* new concepts, only to
  create and wire them. The two schema additions this phase does need are the
  provenance marker above, and a decision about `descriptor_predicate`: the node table
  already carries a DSL expression deciding when a node validly describes an object,
  and a learned node has to either supply one or fall in the majority that leaves it
  null.

- **Persistence across runs.** A concept learned in one run must survive into the
  next, or nothing accumulates. This is where the episodic-memory-as-named-input work
  from Phase 0 first earns its keep.

## 6. Exit criteria

- **Step 0 complete (§0):** every configuration value the engine reads comes from the
  database, each one covered by a guard test that shows a changed value changes the run.
  No posting formula, condition, count or urgency is a Python literal, and no concept has
  two definitions.
- The system **notices** unrelatable objects — signalling them while still degrading
  gracefully, as it does today.
- Capitals acquire concepts *and* links, with provenance recorded.
- `abc → abd; XYZ → ?` is solved — and, more tellingly, solved with the same rule and
  comparable temperature as `abc → abd; xyz → ?`.
- **Transfer, not memorisation:** having encountered some capitals, the system
  generalises to capitals it never encountered. This is the criterion that separates a
  real result from a lookup table, and it should be the headline measurement of the
  phase.
- The a↔A correspondence is discovered, not hardcoded — visible as a bridge with a
  slippage, not as a seeded link.
- All of the above **without any external input** beyond the problems themselves.
- a–z competence unregressed — `scripts/compare_to_metacat.py` over the nineteen demo
  problems, with no p50 member of Metacat's set lost. Novel states are adjudicated, not
  auto-accepted, exactly as in Phase 0.

**Only the last of these is checkable against Metacat**; the rest are the phase's own
criteria and have no external reference (§5). Read the list with that split in mind —
satisfying the last while failing all the others is the *silent* failure mode of this
phase, and it looks exactly like a clean test run.

**A negative result is informative here, and is a live possibility.** The internal
mechanisms in §3 identify *units* well; whether they can supply *relations* is
genuinely uncertain. If capitals can only be acquired by effectively hand-authoring
their links, that is the finding: internal evidence is insufficient for wiring, and
the case for Phase 6's learning-by-asking becomes an argument from necessity rather
than ambition. Phase 3's tokeniser and Phase 2's backward pass would both need
rethinking before being built on top.

## 7. Open questions

1. **Which mechanism carries the weight** (§3) — frequency accumulation, utility, or
   episodic accumulation, singly or combined.
2. **What supplies the links** (§3) — the load-bearing question. Is participation
   history (which structures a candidate appeared in) sufficient evidence for a
   relation, or is relational structure fundamentally not recoverable from internal
   evidence alone?
3. **Where the frequency accumulator lives.** Sub-perceptual statistical layer,
   episodic memory, or new codelets — and if codelets, how a statistical process that
   spans runs fits a coderack that does not.
4. **Conceptual depth of a learned node.** Where does a new concept sit relative to
   the curated depths, and is depth learned or assigned?
5. **Link typing.** Can the system only create links of the five *existing* types
   (`category`, `instance`, `property`, `lateral`, `lateral_sliplink` —
   `seed_data/enums.json`, the `link_types` table), or must it eventually invent new
   relation types? The latter is Phase 6; this phase stays within existing types and
   notes where that pinches. The curated Slipnet gives a concrete target: an interior
   letter such as `plato-m` carries **six** links — four `lateral` (successor and
   predecessor, in both directions, to its two neighbours) and the `instance` /
   `category` pair with `plato-letter-category`. The two ends carry five, trading one
   lateral for a `property` link to `plato-alphabetic-first` / `plato-alphabetic-last`.
   That is what "wired" means concretely, and it is a sharper target than "create some
   links". Note also what is *not* on the list: no `lateral_sliplink` touches an
   individual letter — the sixteen sliplinks connect concepts like `opposite`, not
   letters — so `a ↔ A` is not to be seeded as one, which is exactly what §6's
   discovered-not-hardcoded criterion demands.
6. **Merge/dedup.** What happens when the same concept is discovered twice.

### Carried forward: parallelism beyond sharding

**Unimplemented; this phase owns it.** Phase 0 established the bound and the reason for
it but did not run the measurement that would lift it. It also needs Step 0 first:
`MIN_SHARD_CAPACITY` is a module constant, so the sweep cannot vary it until it is a row.

Free-running splits the Coderack into shards, one per worker, with stealing. The shard
count is bounded by `max_coderack_size // MIN_SHARD_CAPACITY` — 100 // 25 = 4 today
(`server/engine/coderack_shards.py:185-203`). The floor of 25 is a cognition
measurement, not a guess: at eight shards of twelve the `gave_up:` stopping state
disappeared from `eqe→qeq; abbba?` entirely — 0 occurrences in 60 runs against 23 for
the serial engine, on that problem's *most frequent* outcome. A twelve-codelet shard is
too small to be a coderack, because giving up is the end of a sequence and each step
needs its codelets still on the rack when the next one looks.

A machine with more cores than shards therefore runs several workers against one shard.
Raising the shard count means raising `max_coderack_size`, which changes how long codelets
survive and what the urgency-weighted selection draws from, so it changes what the engine
computes.

**The measurement this needs:** sweep `max_coderack_size` at 100, 200, 400 and 600 and
record where the reachable set moves, against Metacat's oracle via
`scripts/compare_to_metacat.py` — the same standard §5 sets for everything else in this
phase, and a change from what Phase 0 assumed, since Petacat's own expected-range
baseline no longer exists. The result decides whether more shards are available within
the cognition the model specifies. Two things make this cheaper than it was when the
item was written: `max_coderack_size` is now a **per-Run parameter**, so a sweep is four
run configurations rather than four global reconfigurations; and a single spot-check at
300 is already recorded in Phase 0 (`answer_found`, 863 codelets, `mrrjjk`), which is
one data point but not a set comparison. The one piece of work it does need first:
`compare_to_metacat.py` takes `--mode`, `--tries`, `--runs`, `--start-seed`, `--backend`
and `--only`, but has no way to set an engine parameter, so it needs a passthrough
before it can express this sweep at all.

**Read the sweep as a cognition result, not a capacity result.** A larger rack is
expected to move the distribution — it is why the parameter is per-Run — so the question
is not whether anything changes but whether Metacat's p50 states all survive at each
size. The largest size at which they do is the real bound on shard count.

**Sharding is one approach among several.** Parallelism that scales past the shard bound
may come from somewhere other than partitioning the Coderack — running whole independent
runs in parallel (`population.py` already does this), parallelism inside the update cycle,
or parallelism inside the numeric substrate.

**This phase's Slipnet growth changes which of those matters.** Every constraint above
is stated at 59 nodes and 202 links. Activation spreading, and the salience and strength
passes that ride on it, scale with node and link count while the Coderack does not — so
as capitals are acquired the arithmetic becomes the part worth parallelising and the
rack becomes proportionally cheaper. Phase 0's GPU substrate was deliberately sized for
that future, at ~300,000 nodes, but the crossover between "the Coderack is the
bottleneck" and "the Slipnet is" has never been located. This phase is the first that
moves the Slipnet at all, and it should record where the balance sits at each new size.
One alphabet is a 44% growth in nodes — 59 → 85 — and a 51% growth in links: 26
`instance` + 26 `category`, 50 `lateral` (25 adjacent pairs, a successor and a
predecessor each) and 2 `property` for the two ends, so 202 → 306. That is exactly what
a–z contributes today, which is the point: capitals double the letter half of the
Slipnet and leave the other half alone. Small in absolute terms, and the first real
data point on a curve every later phase depends on.

## Glossary

| Term | Meaning |
|------|---------|
| **Sub-perceptual accumulator** | A statistical layer beneath the coderack, counting across runs and proposing candidate concepts |
| **Frequency proposes, utility disposes** | Cheap counting generates candidates; participation in temperature-lowering structures decides which are kept |
| **Wiring** | Giving a new node links, without which it cannot participate in bonds, bridges, or rules |
| **Participation history** | The record of which structures a candidate appeared in — the leading internal source of evidence for links. **Does not exist yet**: episodic memory stores answers and snags, not per-object structural participation (§3c) |
| **Provenance** | Marker distinguishing learned nodes/links from the innate seed ontology — a column neither `slipnet_node_defs` nor `slipnet_link_defs` has today |
| **Transfer** | Generalising to untaught instances — the criterion separating learning from memorisation |
| **Stored but not wired** | A configuration value that loads from the database, appears in the admin panel and moves the config hash, while the engine reads a Python literal instead — the condition Step 0 exists to remove |
| **Guard test** | A test asserting *both* that the shipped value reproduces today's behaviour and that a changed value changes the run; the second half is what distinguishes wired from stored |
