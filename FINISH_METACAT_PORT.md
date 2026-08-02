# Finish the Metacat Port

> **Note (July 2026).** This is a record of completed work and is kept as written.
> One thing in it has since changed: Phase 0 WP2.1 removed the container stack, so
> `Dockerfile`, `Dockerfile.dev` and both compose files no longer exist and Petacat
> runs natively — `scripts/dev.sh` is the dev runner that replaced
> `docker compose up`, and [README.md](README.md) has the current setup. The Docker
> section below, and the test counts throughout, describe the state at the time.

**Goal:** bring Petacat to functional parity with Marshall's Metacat (PhD dissertation,
Indiana University, 1999) and the reference Scheme implementation in `../Metacat/`.

This document is a work list, not a roadmap. Everything here is *restoring behaviour the
dissertation already specifies*. Nothing in this document is new capability. Do not add
anything beyond parity — the point is to reach a trustworthy baseline before any real work
starts.

**Reference precedence:** where the dissertation's prose is ambiguous, the Scheme source in
`../Metacat/*.ss` is authoritative, because it is the implementation Marshall actually ran
and reported on in Chapter 5.

---

## Status

Phases A–L are implemented. `python3 -m pytest tests/unit tests/integration tests/module`
is green: **589 passed, 1 skipped** (the skip needs `sqlalchemy`, which only the Docker image
has), including ~90 new tests that encode the dissertation's claims rather than the code's
habits (`tests/module/test_dissertation_parity.py`, `tests/seed_unit/test_slipnet_link_lengths.py`).

Documented answers, measured over 20 seeds per problem at a 4000-codelet cap. "Before" is the
same measurement taken before any of this work:

| Problem | Documented answers | Before | After |
|---|---|---|---|
| `abc→abd; ijk→?` (§1.5) | `ijl`, `ijd`, `ijk` | `ijl` 7/20 | **`ijl` 19/20** |
| `abc→abd; xyz→?` (§5.2.1) | `xyd`, `wyz`, `dyz`, `xyz` | never `xyd`; 5/20 stalled | **`xyd` 16/20**, `wyz`, `xyz` |
| `abc→abd; kji→?` (Fig. 4.5) | `kjj`, `lji` | `kjj` 10/20 | **`kjj` 17/20** |
| `abc→abd; mrrjjj→?` (§5.1.2) | `mrrjjk`, `mrrkkk`, `mrrjkk`, `mrrjjjj` | `mrrkjj` (wrong letters); 8/20 stalled | **`mrrjjk` 13/20, `mrrkkk` 5/20** |
| `abc→abd; iijjkk→?` (§3.4) | `iijjkl`, `iijjll` | `iijjlk` (wrong letter) | **`iijjkl` 14/20, `iijjll` 5/20** |
| `rst→rsu; xyz→?` (§5.2.1 Run 3) | `xyu`, `uyz`, `wyz` | — | **`xyu` 15/20**, `wyz` 1/20 |
| `abc→abcd; ijk→?` (§3.3.3) | `ijkl` | never | **`ijkl` 7/20** |
| `abc→abd; xyz→wyz` justify (§4.3) | — | never justified, 0 bottom rules | `xyd` justified 5/6; `wyz`/`dyz` give up gracefully |

Every problem in the first six rows now reaches an answer in at least 19 of 20 runs — before,
three of them stalled silently a quarter to a half of the time.

Eighteen defects found during the work that were not in the original review, all fixed:

- **`WorkspaceString.add_bond` attached left/right pointers by from/to rather than by
  position**, so a right-to-left bond made walking rightwards loop on one letter. The
  whole-string group scout then built `Group(predgrp, 4 objects)` on a 3-letter string.
- **`Slipnet.spread_activation` cleared the activation buffers at the start of each
  update**, discarding every `activate_from_workspace` jolt and every theme contribution —
  so the Slipnet decayed to zero a few hundred codelets into every run. Masked previously
  because the missing link lengths (Phase G) left everything spreading at degree 50.
- **`activate_from_workspace` didn't exist.** The Scheme's proposers, evaluators *and*
  builders all re-activate the concepts they touch; Petacat only nudged a few nodes on
  build. Nodes decay ~70% per cycle, so nothing stayed relevant.
- **The Coderack ignored `max_coderack_size`.** `remove_old_codelets` had no callers, so the
  rack grew past 600 and the codelet mix drifted away from the Workspace state.
- **Bridge incompatibility only fired on an identical object *pair*.** `abc → abcd` ended up
  with `a–a`, `a–b` and `a–d` all built at once, from which no coherent rule can be
  abstracted. `Bridge.get_incompatible_bridges` existed and was unused; the string→workspace
  back-link it needs was also missing, which is why bridge external strength was always 0.
- **Groups carried no descriptions at all**, making them invisible to the bridge scouts.
- **`Image.set_state` aliased the saved sub-image list**, and `justify.py` defined two
  different local `_Fail` classes so a raise in one escaped the `except` in the other,
  crashing the answer-justifier.
- **`Bridge._singleton_factor` penalised *every* letter↔group bridge by 0.1**, where
  `singleton-letter-factor` (bridges.ss:808-822) penalises only genuine singletons. An `a–aa`
  bridge could therefore never compete with `a–a`, making the whole `letter ⇒ group` slippage
  family of §3.3.1 and Fig. 3.1 effectively unreachable.
- **`_get_bridges_of_type` probed a `workspace.bridges` dict that does not exist**, so
  `getattr` returned `{}` and the function returned an empty list *every* time. Bridge
  external strength was always 0 and bridge incompatibility never fired at all.
- **`(group String-Position whole)` resolved to the string, not the string-spanning group.**
  Fig. 3.2 reserves that meaning for the special `string` object type. A string image cannot
  take a length change, so "Increase length of whole group by one" always failed — and with
  it every `abc → abcd` style answer.
- **A group image was seeded with the group's *bonding* direction.** Since `Group.objects` is
  stored left-to-right, an untouched image of `abc` perceived as a left-going predecessor
  group generated `acb`, which made every rule look broken to `currently_works`.
- **The `subobjects` abstraction fired on clusters of a single bridge.** §3.3.6 step 4
  abstracts a pattern common to *sets* of bridges anchored to all of an object's components;
  with one component there is no common pattern, and a lone group→group bridge was producing
  "reverse the direction of all objects in the string" instead of "reverse direction of whole
  group" — and that bogus change then suppressed the correct one.
- **`top-down-group-scout:category` only ever scanned rightwards**, so a group could be found
  from just one of its ends. The Scheme picks a scan direction by activation
  (groups.ss:418-486).
- **`important-object-bridge-scout` took the *first* descriptor match** in `string2.objects`,
  where letters always precede groups (bridges.ss:966-1030 collects every candidate and picks
  by inter-string salience, and propagates an existing slippage to pick the descriptor).
- **`WorkspaceString.choose_object` ignored salience entirely** — every object got weight 1.0,
  so attention was uniformly random.
- **Rule translation was handed the whole vertical mapping at once**, and dropped each *direct*
  slippage with probability `1 - slippability` (only coattails are probabilistic in the Scheme).
- **`choose_neighbor` could never return a group**, so no group-to-group bond was proposable and
  a group of groups was unreachable.
- **Singleton groups were never created** (groups.ss:466-486's third branch).
- **`StringImage._constituent_images` selected top-level objects by back-pointer**, duplicating
  letters under nesting.

### Group-level answers

§1.5 sets out the fork this turns on: the answers to `abc→abd; mrrjjj→?` differ "depending on
the rule and **whether or not `c` in `abc` is seen as corresponding to the `jjj` group or to
just the rightmost letter `j`**", and it names `mrrkkk` as "by far the most common" answer —
for Copycat and for people alike. Petacat gave `mrrkkk` 0 times in 30 and `mrrjjk` 26 times:
the fork had collapsed onto one branch. Four independent defects were responsible.

- **`Bridge._singleton_factor` penalised *every* letter↔group bridge by 0.1**, where
  `singleton-letter-factor` (bridges.ss:808-822) penalises only genuine singletons. An `a–aa`
  bridge could never compete with `a–a`.
- **`important-object-bridge-scout` took the *first* descriptor match** in `string2.objects`.
  Letters always precede groups in that list, so a bridge from a letter to a group was
  essentially unreachable. The Scheme (bridges.ss:966-1030) collects *every* candidate with
  that descriptor and picks among them by inter-string salience — and it propagates an existing
  slippage to decide which descriptor to look for, which is how an established interpretation
  spreads across the rest of the mapping.
- **`WorkspaceString.choose_object` ignored salience entirely.** It probed `getattr(o,
  weight_key, 1.0)`, and since the `1.0` default is itself a float the numeric branch always
  won — every object got weight 1.0. Object choice was uniformly random, so salience, "how
  attention-worthy an object is", did nothing at all.
- **Rule translation was handed the whole vertical mapping at once.** `apply-slippages` returns
  on the first slippage matching the concept being translated, so an unrelated
  `letter ⇒ letter` identity from the `a–m` bridge shadowed the `letter ⇒ group` slippage from
  `c–jjj`, and the rule kept saying "rightmost **letter**". The Scheme scopes slippages per
  clause to that clause's own reference objects (answers.ss:1430-1450). Separately, the
  translation was dropping each *direct* slippage with probability `1 - slippability`, so deep
  slippages were discarded most often — the `letter ⇒ group` mapping survived about 7% of the
  time. Only **coattail** slippages are probabilistic in the Scheme (slipnet.ss:257-277).

With those fixed, over 20 seeds: **`mrrkkk` 6/20**, **`iijjll` 6/20** (§3.4), **`ijkl` 9/20**
(§3.3.3), plus `mrrjkk` — another answer §1.5 lists.

### Groups of groups, and singleton groups

A second cluster of functional gaps blocked every answer that needs a *hierarchy* of groups:
`kkjjhh` (Fig. 4.2 — `kkjjii` read as a predecessor group *of sameness groups*), `mrrjjjj`
(§5.2.1 Run 1 / Fig. 5.2 — `mrrjjj` read as a 1‑2‑3 *length* group), and `iiijjjkkk` (§3.4).

- **`choose_neighbor` could never return a group.** It used `get_object_at`, which returns the
  first object covering a position, and letters always precede groups in `string.objects`.
  Bonds join adjacent objects, and "adjacent" has to respect the hierarchy: a group's neighbour
  is the next group, not a letter inside it. Neighbours are now same-level siblings.
- **Singleton groups were never created.** `groups.ss:466-486` has a third branch: when the
  chosen object is a lone letter with no matching bond to scan, it is wrapped in a *group of
  length one*, gated by `single-letter-group-probability`
  (workspace-structure-formulas.ss:32-41). This is what gives `m` in `mrrjjj` a Length
  description so it can bond to `rr` (length two) on the Length facet — the 1‑2‑3 reading. The
  branch now lives in the `top-down-group-scout:category` codelet body, where it belongs, and
  the exponents come from the already-seeded `single_letter_group_exponent_*` coefficients.
- **The image layer duplicated letters under nesting.** `StringImage._constituent_images`
  selected top-level objects by `enclosing_group is None`; when two groups claim the same
  member the later one wins the back-pointer, so the earlier group *and* its orphaned members
  all looked top-level and their letters generated twice — `iijjkk` came out as
  `iiijjkdijjkd`. It now walks the string left to right taking the widest built object at each
  position, which cannot double-count whatever state the back-pointers are in.

Verified end to end (`TestStructuralCapabilities`): singleton `m` forms with `Length: one`, a
group is offered a neighbouring group, successor bonds form between the three groups *on the
Length facet*, a nested `succgrp` over `[m][rr][jjj]` carries `BondFacet: Length` /
`StringPos: whole` / `Length: three`, and the nested image still generates `mrrjjj` untouched.

Group-level answers over 20 seeds: **`mrrkkk` 5/20** (§1.5's "by far the most common"),
**`iijjll` 5/20** (§3.4), **`ijkl` 7/20** (§3.3.3).

> On frequency vs capability: some documented answers are rare even for Metacat. Of `mrrjjjj`
> the dissertation says "Many people do not think of the answer mrrjjjj, even when given an
> unlimited amount of time" (p.30), and its own Run 1 for that answer is a *justification* run,
> not a discovery run. The tests therefore assert that the structures and rule forms are
> reachable — which is what functional equivalence means — and only put frequency floors on the
> answers the dissertation presents as common.

### Running it in Docker

`docker compose -f docker-compose.dev.yml up -d` works — API on **:8100**, frontend on
**:59595**. Verified from a clean volume and from a pre-existing one, plus
`pytest tests/e2e` (88 passed) and `npm run build` / `vitest` in the frontend container.

Bringing Docker up surfaced four defects that the local, JSON-driven tests could not, because
the container also loads the seed data into PostgreSQL and the engine does not:

- **`slipnet_node_defs` had no `descriptor_predicate` column.** `create_all` creates missing
  *tables* but never alters an existing one, so any pre-existing volume kept the old column set
  and every query naming the new column failed — the app logged "DB setup skipped" and carried
  on with a broken database. Startup now reconciles missing columns additively, and migration
  `007` covers the alembic path.
- **The re-seed check was "are there any rows?"** — so a volume from an earlier build kept
  serving stale metadata to the admin panel while the engine ran the new JSON. Startup now
  fingerprints the bulk seed files and re-seeds when they change.
- **The first version of that re-seed would have deleted the user's runs.**
  `server/models/run.py` shares the declarative `Base` with the metadata models, so walking
  `Base.metadata` swept up `runs`, `trace_events`, `cycle_snapshots` and the episodic-memory
  tables. The derived set is now restricted to classes declared in `server.models.metadata`,
  and the tables runtime data holds foreign keys into (`run_statuses`, `event_types`) are
  computed from the schema and seeded insert-if-missing rather than cleared.
- **`concept_activation` was missing from `enums.json`.** `trace_events.event_type` is a
  foreign key onto `event_types`, so persisting the new event type failed with a foreign-key
  violation the moment a run was stepped through the API. It is domain knowledge, so it belongs
  in the seed data. A test now asserts every event-type constant has an enum row.

Three pre-existing TypeScript errors (in `admin/EditableTable.tsx` and `main.tsx`, files this
work did not otherwise touch) were blocking `tsc -b` and `npm run build`; they are fixed, so
client changes can be type-checked again.

If you hit anything odd with an old volume, `docker compose -f docker-compose.dev.yml down -v`
still resets cleanly — but it should no longer be necessary.

### Where each fix lives

Petacat's design intent is that domain knowledge lives in `seed_data/*.json` and only mechanism
lives in Python. The fixes were placed to match where `../Metacat` puts each concern:

| Concern | Petacat | Scheme |
|---|---|---|
| Link lengths, node depths, descriptor predicates | `seed_data/*.json` | `slipnet.ss` declarations |
| Codelet behaviour (scouts, watchers, jootser, justifier) | `codelet_types.execute_body` | `define-codelet-procedure*` |
| Codelet/theme/concept patterns, thresholds, coefficients | `posting_rules.json`, `engine_params.json`, `formula_coefficients.json` | `constants.ss` |
| Strength and probability formulas | `server/engine/*.py` | `workspace-structure-formulas.ss` |
| Data structures and algorithms | `server/engine/*.py` | `bonds.ss`, `groups.ss`, `bridges.ss`, `rules.ss`, `images.ss` |

One case was initially misplaced and has been corrected: **descriptor predicates**. The Scheme
attaches them to nodes (`(tell plato-leftmost 'define-descriptor-predicate ...)`), so they are
knowledge about a concept, not mechanism. They were first written as a Python dict keyed by node
name — which would have meant a code change to add a descriptor. They now travel with the node
in `slipnet_nodes.json` as a DSL expression over `obj`, compiled at startup exactly like a
codelet's `execute_body`, against a small published vocabulary
(`DESCRIPTOR_PREDICATE_NAMESPACE`).

### Known remaining gap

`abc→aabbcc; ijk→?` produces no answer: it needs `a–aa`, `b–bb` and `c–cc` all present at once,
and the three letter→group bridges do not co-occur often enough. The §3.1 `pq→qp; ijkl→?` family
(`ljki` / `jjkk` / `lkji`) likewise does not assemble its three-bridge mapping reliably. Both are
frequency rather than capability — every ingredient is verified reachable above — but neither is
demonstrated, so treat them as open.

---

## Background: how the port broke

Petacat's data model is largely faithful. The Slipnet topology and conceptual depths are
exact; the refined §3.5 concept-mapping predicates match `bridges.ss`; split
horizontal/vertical happiness is right; the update-cycle ordering matches `run.ss:295-315`.
`rules.py`, `jootsing.py`, `justify.py` and `images.py` contain substantial and largely
correct ports of the hard algorithms.

The failure is almost entirely in **wiring**. The 27 codelet `execute_body` strings in
`seed_data/codelet_types.json` implement a simplified engine that bypasses those modules,
and three of them call the self-watching entry points with arguments omitted in ways that
disable every stochastic path. Add one string-prefix mismatch in the Themespace and a set of
missing Slipnet link lengths, and the result is that the Themespace, jootsing, answer
justification, rule abstraction and answer comparison — everything that distinguishes
Metacat from Copycat — are present as code but unreachable at runtime.

Evidence of the end state, 12 seeds per problem, 4000-codelet cap, before any fixes:

| Problem | Petacat produced | Metacat / dissertation |
|---|---|---|
| `abc→abd; ijk→?` | `ijl` 4/12; also `hkk`, `ikk`, `hjk` | `ijl` essentially always |
| `abc→abd; xyz→?` | `xyy`, `xzz`, `xxz`, `yyz`, `wyz`; never `xyd` | `xyd`, `wyz`, `dyz`, `xyz` (Figs. 4.12, 4.14) |
| `abc→abd; mrrjjj→?` | `mrrkjj`, `mrrijj`, `msrjjj`; 5/12 no answer | `mrrjjjj`, `mrrkkk`, `mrrjjk` |
| `abc→abcd; ijk→?` | `ijl` 7/12 | `ijkl` |
| `abc→aabbcc; ijk→?` | `ijj`, `jjk`, `jjj` | `iijjkk` |
| `abc→cba; ijkl→?` | 6/12 no answer; 1048 snags | `lkji` / `ljki` / `jjkk` |

All 494 existing tests pass. They test what is implemented, not what the dissertation
specifies. Expect to *add* tests, not to fix failing ones.

---

## Phase A — Make the Themespace work at all

The Themespace is the dissertation's central architectural contribution (§4.1). It is
currently a permanent no-op: measured 0 non-zero themes and 0 dominant themes after 3000
codelets on `abc→abd; ijk→?`.

### A1. Fix the relation-name mismatch

`Bridge.get_theme_pattern()` (`server/engine/bridges.py:194`) emits relation names as
Slipnet node names — `plato-identity`, `plato-opposite` — but `ThemeCluster` is built from
`seed_data/theme_dimensions.json` with bare relations `identity`, `opposite`, `diff`.
`Themespace.boost_theme()` therefore never finds a theme and returns silently. It has
exactly one caller, `runner.py:474`.

Repro:

```
sample theme pattern: {'plato-letter-category': 'plato-identity', ...}
cluster relations:    ['identity', 'successor', 'predecessor', 'diff']
get_theme('plato-identity') -> None
get_theme('identity')       -> Theme(top_bridge, plato-letter-category:identity, act=0)
```

Canonical form is **bare relation names** (`identity`, `successor`, `predecessor`,
`opposite`, `diff`). That matches the seed data, the existing unit tests, and
`client/src/components/ThemespaceView.tsx`'s `REL_LABELS`. Dimensions stay `plato-`-prefixed
(they are genuine Slipnet nodes; `diff` has no node, which is why relations cannot be).

- Add a single canonicalising helper, `relation_name_for_label(label_node) -> str`, that maps
  a label node (or `None`) to one of the five bare names. `None` → `"diff"`, matching the
  Scheme's `difference-theme?` = "relation does not exist" (`themes.ss:715`).
- Route every producer of a theme relation through it.

### A2. Derive theme relations from descriptions, not concept-mappings

`get_theme_pattern()` iterates `self.concept_mappings` and skips any CM whose label is
`None`. That is wrong twice over:

1. **`X: different` themes can never be created.** They are exactly the label-less case. The
   dissertation needs them: vertical `Letter-Category: different` and `Object-Type: different`
   are dominant in Figs. 4.1/4.2, and `Bond-Facet: different` carries the entire
   `eqe→qeq; abbbc→?` analysis (§4.7.2–4.7.3).
2. It uses the wrong source. `bridges.ss:296-322` (`boost-themes`,
   `get-associated-thematic-relations`) iterates the **cross-product of object1's and
   object2's descriptions**, filtered by `descriptions-affect-themespace?`, and takes the
   relation from `get-label(descriptor1, descriptor2)`.

Implement:

- `Bridge.get_associated_thematic_relations() -> list[tuple[str, str]]` following
  `bridges.ss:314-322`.
- `descriptions_affect_themespace(d1, d2)` per `themes.ss:1093-1107`: same description type,
  both relevant, and *not* any of — object-category on two spanning groups, string-position
  on two spanning objects, or both descriptors `middle`.
- Keep `get_theme_pattern()` as a dict wrapper; `supports_theme_pattern()` still uses it.

### A3. Boost spanning bridges twice

`bridges.ss:308-310`: a spanning bridge boosts by `2 * strength`. Apply in
`runner._spread_activation_to_themespace`.

### A4. Fix theme → Slipnet spreading

`Themespace.spread_activation_to_slipnet` (`themes.py:371`) does
`slipnet.nodes.get(theme.relation)` with a bare name against `plato-`-prefixed keys — the
same bug. Map bare → `plato-*`, and skip `diff` (it has no node, which is correct: the
"different" relation is the *absence* of a concept).

### A5. Align dominance with the Scheme

`ThemeCluster.get_dominant_theme` filters to positive themes before ranking.
`themes.ss:503-518` ranks **all** themes by absolute activation, requires the top one to be
positively activated, and requires a **strictly greater** margin than 90. A strong negative
theme should block dominance; today it does not. Also serialise the server-side dominance
flag so the UI stops recomputing it with a different heuristic (see K1).

> Note on theme count: the dissertation says 66 themes are possible (§4.1). The Scheme's
> `get-possible-relations` (`themes.ss:403`) yields 25 (dimension, relation) pairs across the
> 9 category nodes, i.e. 75 with the three theme types. Petacat's `theme_dimensions.json`
> already matches the Scheme exactly. Leave it alone; the prose figure appears to predate the
> final node set.

---

## Phase B — Themes must influence Workspace structure strength

§4.1.2 and Fig. 4.4: themes "act like a set of knobs that can be used to smoothly vary the
strengths of Workspace structures". This is the primary channel of top-down thematic
pressure, and it does not exist.

`WorkspaceStructure.get_thematic_compatibility()` returns 0 and no subclass overrides it.
`thematic_compatibility_weight` is seeded to `0.0` in `formula_coefficients.json`, so even
the placeholder term is inert.

### B1. Use the Scheme's strength formula

`workspace-structures.ss:50-63`:

```
compatibility  = get-thematic-compatibility        ; -1 .. +1
thematic_weight = |compatibility|
strength = weighted_average([100 if compatibility > 0 else 0, intrinsic_strength],
                            [thematic_weight, 1 - thematic_weight])
```

The weight is **dynamic**, derived per-structure, and pulls strength toward 100 (compatible)
or 0 (incompatible). Petacat instead blends the compatibility *value* using a fixed
coefficient. Replace it. Delete the now-meaningless `thematic_compatibility_weight`
coefficient rather than leaving dead config.

### B2. `Bridge.get_thematic_compatibility()`

Port `bridges.ss:270-287`:

- `get_theme_support_values()` — for each active theme of this bridge's theme type:
  `-activation/100` if incompatible, `+activation/100` if supported, else `0`.
- `get_average_theme_support()` — weighted average where negative values carry weight
  `2 * len(values)` and positives weight `1` (this is the "incompatible themes drown out
  compatible themes" behaviour described on p.143).
- `bridge_theme_compatibility_sigmoid(x) = 2/(1 + exp(-2*beta*x)) - 1`, `beta = 4`
  (`themes.ss:1115`). The coefficient `theme_compatibility_sigmoid_beta` is already seeded.

`incompatible_with_theme` / `supported_by_theme` per `themes.ss:1047-1090`, including the
three mutually exclusive special cases (`special_direction_case`,
`special_spanning_bridge_case`, `special_middle_middle_case`) and
`relation_consistent_with_theme`.

### B3. `Description.get_thematic_compatibility()`

`descriptions.ss:73-79`: the max over active themes of `|activation|/100` for themes whose
dimension equals this description's type, else 0.

### B4. Give structures access to the Themespace

The Scheme uses a global `*themespace*`. Mirror it with a class-level binding on
`WorkspaceStructure`, set during `init_mcat` alongside the existing
`configure_thematic_weight` call. Reset it between runs so tests don't leak state.

---

## Phase C — Thematic pressure needs an on/off switch

`themes.ss:53` initialises `active-theme-types` to `'()` — pressure **off** — and comments it
as "those currently exerting thematic pressure". `get-possible-theme-types` is a separate
concept (which types are meaningful given justify mode).

Petacat conflates them: `Themespace.__init__` sets `active_theme_types = [TOP, VERTICAL]`
(`themes.py:213`), and `has_thematic_pressure()` derives pressure from dominance. That is
precisely the design the dissertation records as tried and rejected (p.139: *"Another
approach involved letting only dominant themes influence processing, but this did not work
very well either."*)

- Split into `possible_theme_types` (mode-derived) and `active_theme_types` (pressure), the
  latter defaulting to empty.
- Add `thematic_pressure_on(types=None)` / `thematic_pressure_off(types=None)` /
  `has_thematic_pressure(types=None)` mirroring `themes.ss:132-166`.
- `get_active_themes(theme_type)` returns `[]` when pressure is off — this is what makes B2/B3
  no-ops in the normal case, exactly as the dissertation requires ("Most of the time,
  therefore, themes behave as passive representational structures").
- Clamping a theme pattern turns pressure on; unclamping turns it off
  (`themes.ss:129-131`).

### C1. Make `thematic-bridge-scout` actually thematic

Today it computes `theme_pattern`, never reads it, picks objects by salience, and accepts
whatever concept-mappings happen to exist. Per §4.1.2 it must:

- run only under thematic pressure;
- prefer object pairs whose descriptions are *compatible with positively-activated themes*,
  with urgency scaled by theme activation;
- propose a missing **description** when one would enable a theme-compatible bridge (the
  `Alphabetic-Position` example on p.144 — this is how `a`/`z` acquire first/last
  descriptions);
- ignore negatively-activated themes (p.143-144: negative themes exert pressure only through
  structure strength, never through scouts).

---

## Phase D — Reconnect self-watching

`jootsing.py` and the clamp lifecycle in `trace.py` are faithful ports. They are unreachable.

### D1. Progress-watcher is called with arguments missing

`seed_data/codelet_types.json`, `progress-watcher`:

```python
result = check_progress(workspace, trace, codelet_count, meta, commentary=commentary)
```

`rng`, `themespace`, `slipnet` and `justify_mode` are all omitted. Consequences:

- `progress` is hardcoded `0.0` because `undo_last_clamp` is never called;
- the follow-up Answer-finder after a clamp is never posted (§4.5.1);
- `if rng is not None and not rng.prob(clamp_probability)` is skipped, so rule-codelet clamps
  fire **deterministically** whenever activity is zero and rules are poor;
- `justify_mode=False` means bottom rules are never considered.

Also, the codelet body calls `trace.record_clamp_start` on top of `check_progress`'s
`add_clamp_event`, double-counting every clamp.

Pass everything through; delete the duplicate record.

### D2. Jootser is called with arguments missing

```python
result = attempt_jootsing(trace, themespace, meta, commentary=commentary, codelet_count=codelet_count)
```

`rng`, `slipnet` and `workspace` are omitted. The clamp branch is gated on
`if rng is not None and rng.prob(...)` (`jootsing.py:288`), so **jootsing from repeated
clamps never runs at all**: no first-order jootsing from rule-codelet clamps, no meta-level
jootsing from repeated snag-response clamps, no graceful give-up, no settling for an
unjustified answer (§4.5.2). Pass them through.

### D3. Snags must be recorded as snag events

Codelets call the `record_event` builtin, which constructs a plain `TraceEvent`. So:

- `SnagEvent` is never constructed anywhere — it is a dead class;
- snag events carry no structures and no theme pattern, so the jootser's snag branch returns
  `pattern_detected=False` immediately and **jootsing from repeated snags never runs either**;
- `TemporalTrace.within_snag_period` is never set, so the snag temperature clamp at
  `runner.py:398` never fires;
- `trace.snag_count` stays 0, so the commentary never appends "again" (p.181).

Build a real `SnagEvent` at the snag site in `answer-finder`, carrying the snag object(s),
the translated rule, and the current vertical theme pattern (§4.7.2 lists exactly what a snag
description holds). Clamp temperature for the snag period.

### D4. Answers must be recorded as answer events

`AnswerEvent` is likewise never constructed. `report_answer` records a bare `TraceEvent`.
Answer descriptions are supposed to be distilled from Trace contents (§4.7.1).

---

## Phase E — Rules

### E1. The entire rule-abstraction pipeline is dead code

`build_rule_from_bridges` (`rules.py:2453`), `abstract_change_descriptions` (:1207),
`remove_redundant_change_descriptions` (:1333) and `instantiate_rule_clause_template` (:1527)
have **zero callers repo-wide**. `rule-scout` instead emits one intrinsic clause per slippage
of every top bridge, deterministically.

So none of §3.3.6 applies: no extrinsic clauses (swaps), no `components` / "all objects in
string" changes, no verbatim rules (`verbatim_rule_probability` is seeded and unread), none
of the six abstraction heuristics, no probabilistic choice of description level.

Point `rule-scout` at `build_rule_from_bridges`. It must:

- choose the top **or** bottom mapping (bottom only in justify mode);
- take the small `verbatim_rule_probability` shortcut that bypasses abstraction entirely
  (§3.3.6: *"There is also some (small) chance that the codelet will simply ignore the bridges
  and instead propose a verbatim rule"*);
- pass `rng`, `temperature`, `themespace` and `meta` so the rule gets its theme-pattern
  (§4.2.1: a rule's theme-pattern is permanently associated with it at creation).

`rule-evaluator` must check the rule actually works (`Rule.currently_works`) before building,
per §3.3.6.

### E2. Only top rules are ever built

`rule-scout` reads `get_built_bridges('top')` and always emits `RULE_TOP`. Measured on
`abc→abd; xyz→wyz` justify mode, 4 seeds: bottom bridges 8–9, **bottom rules 0**, no answer,
status halted every time. Justify mode — Chapter 5 Runs 1–3 — cannot produce a result.

### E3. Rule application cannot express the model's changes

The DSL `apply_rule` builtin (`codelet_dsl/builtins.py:591`) works on `list(target.text)` and
only substitutes single letters. No length change, no direction reversal, no position swap,
no group-level objects, no `components` changes; verbatim clauses are `continue`d, which
silently yields the identity. It shadows the image-based `rules.apply_rule` (`rules.py:1699`),
which is correct and unused, along with all of `images.py`.

Measured consequence: `abc→abcd; ijk→?` gives `ijl` (should be `ijkl`); `abc→aabbcc; ijk→?`
gives three-letter answers (should be `iijjkk`).

Replace the builtin with a thin wrapper over `rules.apply_rule` plus a
`StringImage`→text step.

### E4. Rule translation is deterministic

§3.4 is entirely about *nondeterministic* rule translation — Figs. 3.11/3.12 (`kji` vs
`kkkjjjiii`) and 3.13/3.14 (`mmmrrj` vs `jrrmmm`) differ *only* in whether a slippage was
applied. Petacat always applies every slippage.

Coattail slippages (§3.4.1) *are* implemented in `SlipnetNode.apply_slippages`
(`slipnet.py:200`), but `Rule._slip` (`rules.py:987`) calls it with no `rng`, and the code then
takes the branch documented as *"Without RNG, always apply coattail (deterministic mode)"*.
So coattails fire on **every** eligible slippage instead of with probability proportional to
degree of association. In `abc→abd; xyz→?` that means a `first⇒last` slippage always drags
`successor⇒predecessor` along.

- Thread `rng` through `Rule.translate` / `_translate_clause` / `_slip`.
- Probabilistically ignore individual vertical slippages during translation.
- Return the slippages that were *not* applied, so answer descriptions can record unjustified
  slippages (§4.7.1).

### E5. Rule grammar violations

Fig. 3.2 defines `<object-description> ::= (<object-type> <object-attribute>
<object-descriptor>) | (string String-Position whole)`. `rule-scout` emits 2-tuples
`(attribute, descriptor)` with no object-type and no `string` form.

Worse, it produces **intrinsic String-Position clauses** — observed output includes
`change StringPos from middle to lmost` — which §3.3.2 footnote 2 explicitly forbids: *"a
change to an object's string position cannot be described intrinsically."* Position changes
are extrinsic-only. This resolves itself once E1 lands (`build_rule_from_bridges` already
builds 3-part object-descriptions), but add a guard and a test.

Also observed: a 7-clause rule for `abc→abd`, against §3.3.4's *"in practice, most rules
describe no more than two or three changes"*.

### E6. Quality measures are reduced to stubs

§3.3.5 specifies three measures with nine sub-factors between them. Petacat implements two
sub-factors.

- **Uniformity** (`rules.py:727`) is commented *"Simplified: more uniform if clauses share the
  same type"* — factor 4 of 4. Missing: uniformity of intrinsic-clause object-description
  attributes, of extrinsic-clause object-description attributes, and of intrinsic-clause
  change-descriptors (the abstract/literal mix).
- **Abstractness** (`rules.py:739`) averages only `change.dimension.conceptual_depth`, never
  descriptor depth. So *"…to successor"* and *"…to `d'"* score **identically** — which is the
  dissertation's headline abstractness example. Missing: average depth of object-description
  attributes, and of extrinsic-clause object-attributes.
- **Succinctness** (`rules.py:764`) ignores factor 2, the degree to which changes are described
  via `components`. Verbatim rules get 10; §3.3.5 says verbatim rules are *maximally* uniform,
  *minimally* abstract, *maximally* succinct.

`rule_uniformity_intrinsic_weight`, `rule_uniformity_extrinsic_weight`,
`rule_uniformity_extrinsic_obj_desc_exponent` and `rule_intrinsic_quality_*` are all seeded
and never read — they belong to the missing factors.

---

## Phase F — Answer justification

`answer-justifier` declares success when `len(tr.clauses) == len(br.clauses)`. That is the
whole implementation.

`justify.py` — 1018 lines implementing `attempt_justification`, `unify_rules`,
`get_unifying_slippages`, `clamp_rules`, `get_vertical_theme_pattern_to_clamp` — has no
callers outside two helpers used by `jootsing.joots_from_justify_clamps`.

Point the codelet at `justify.attempt_justification`. §4.3.1 requires, in order:

1. choose a top or bottom rule by strength;
2. translate it through the vertical mapping;
3. if the translated rule matches an existing supported rule → justified, report;
4. if it doesn't match but *works*, add it as a new rule on the other side;
5. if a rule is unsupported, clamp its theme-pattern + the dominant vertical theme-pattern +
   the unsupported rule's concept-pattern + a top-down codelet-pattern;
6. otherwise attempt **rule unification** and clamp the derived vertical theme-pattern.

The top-down codelet-pattern in step 5 must include `thematic-bridge-scout`
(§4.3.1: *"…on their associated Evaluator and Builder codelets, and on Thematic-bridge-scout
codelets"*). The seeded `top-down-codelet-pattern` in `posting_rules.json` omits it.

---

## Phase G — Restore Slipnet link lengths

Topology is exact: 59 nodes with identical conceptual depths, 202 links, and the four new
§3.5 link labels (`leftmost↔left` identity, `rightmost↔right` identity, `leftmost↔right`
opposite, `rightmost↔left` opposite) all present.

But **no link in `seed_data/slipnet_links.json` carries a length.** In the Scheme,
`set-link-length` also sets `fixed-length? #t` (`slipnet.ss:345-348`), so 134 of 202 links are
fixed-length. Petacat seeds `fixed_length: false` everywhere and `SlipnetLink.link_length()`
falls through to `return 50`. 114 links diverge measurably:

| link class | Scheme | Petacat | degree-of-assoc |
|---|---|---|---|
| `letter-category → a…z` (instance) | 97 | 50 | 3 → 50 |
| `a…z → letter-category` (category) | depth diff | 50 | ~80 → 50 |
| `string-position-category → leftmost…` (instance) | 100 | 50 | 0 → 50 |
| `a → alphabetic-first` (property) | 75 | 50 | 25 → 50 |
| `alphabetic-first ↔ leftmost` (lateral) | 100 | 50 | 0 → 50 |
| `leftmost ↔ left` (lateral, labelled identity) | 90 fixed | 0 (label-derived) | 100 → 10 |

Degree-of-association scales activation spreading *and* slippage probability, so this
distorts Slipnet dynamics globally — most sharply by making category→instance spreading
roughly 17× stronger than intended.

Regenerate `slipnet_links.json` from `../Metacat/slipnet.ss`, including the computed
category-link lengths (`(- (cd category) (cd descriptor))`) and the `all-lengths:` forms.
Links declared with `label:` **only** stay dynamic; links declared with `length:` are fixed
even when they also carry a label.

Also: `CLAUDE.md` and `README.md` both claim "226 links". The correct count, matching the
Scheme, is **202**. Fix both.

---

## Phase H — Horizontal/vertical bridge asymmetry

§3.3.1 is explicit: *"slippages involving length or letter-category, such as one ⇒ two or
c ⇒ d, are only possible for horizontal bridges."* The reason is structural — horizontal
concept-mappings ground both similarity *and* difference (a rule is abstracted from them),
vertical ones ground similarity only.

Both bridge scouts build the same concept-mapping set for every bridge type. There is no
analogue of `horizontal-mappable-descriptions?` / `vertical-mappable-descriptions?`
(`bridges.ss`). So vertical bridges pick up `a⇒i` and `one⇒two` slippages, which pollutes
vertical mappings, manufactures spurious vertical `Letter-Category: different` themes, and
distorts bridge coherence and strength.

Port both predicates and apply them in `bottom-up-bridge-scout`,
`important-object-bridge-scout` and `thematic-bridge-scout`.

---

## Phase I — The Temporal Trace is a subcognitive log

§4.4 makes the Trace the "cognitive level" — the filtered, chunked record that
progress-watchers and jootsers reason over. *"At the level of description of the Trace, a
typical run consists of a few dozen steps."* Fig. 4.12 shows twelve events for a 1,558-codelet
run.

`build_structure` (`builtins.py:183`) records an event for **every** bond, group, bridge,
description and rule built or broken, with no importance filter. Measured ~150 events per run.
The four seeded importance thresholds — `group_importance_threshold`,
`rule_importance_threshold`, `concept_activation_importance_threshold`,
`concept_mapping_importance_threshold` — are read nowhere.

The dissertation lists exactly seven event types. Petacat's status:

| Event type (§4.4) | Status |
|---|---|
| Concept-activation | **Missing entirely** — Slipnet nodes don't monitor their own activation |
| Group | Recorded, unfiltered |
| Slippage | **Missing** — bridge builders record `bridge_built`, not slippages |
| Rule | Recorded, unfiltered |
| Answer | Recorded as bare `TraceEvent` (see D4) |
| Snag | Recorded as bare `TraceEvent` (see D3) |
| Pattern-clamp | Recorded |

Work:

- Apply the importance thresholds; stop recording bond/bridge/description build and break as
  Trace events (they remain Workspace events — the Trace is not a debug log).
- Add slippage events at bridge-build time for sufficiently important slippages, with the
  §4.4 special case: *a slippage made under thematic pressure and compatible with the clamped
  themes is of very high importance regardless of its concepts.* Answer descriptions depend on
  this (§4.7.1 distils the vertical theme-pattern from recent slippage and group events).
- Add concept-activation events: nodes monitor their own activation and emit when a deep
  concept changes substantially.
- Every event records the Workspace structures and Themespace patterns extant at the time
  (§4.4), because progress-evaluators and the jootser read them back.

Note the knock-on: `_last_significant_event_time` is bumped by every micro-event, so the
"settling period" in `check_progress` never elapses cleanly. Filtering fixes that too.

---

## Phase J — Episodic Memory, reminding, comparison

### J1. Answer descriptions are too thin

§4.7.1 specifies seven components. Petacat's `AnswerDescription` stores rule *strings*, two
quality floats, and one flat theme dict. Missing: the Workspace structures involved, separate
**top / vertical / bottom** theme-patterns, the unjustified theme-pattern
(`unjustified_slippages` is hardcoded `[]` in `answers.create_answer_description`), and the
per-answer activation level (0–100) that reminding is defined in terms of.

The vertical theme-pattern in particular must be distilled from recent slippage and group
events in the Trace (§4.7.1), which depends on Phase I. Apply the §4.7.1 footnote-18
restriction: only `String-Position`, `Alphabetic-Position`, `Direction`, `Group-Type` and
`Bond-Facet` vertical themes may appear, and `Bond-Facet` only as `different`.
`theme_dimensions.json` already carries this list as `answer_description_theme_types`; it is
unread.

### J2. Snag descriptions are never created

`SnagDescription` exists and is only ever *rehydrated* from the database
(`run_service.py:601`). Nothing in the engine creates one. So snag-justified themes are
impossible, and with them the entire `aaabccc` vs `aaabaaa` discrimination of §4.7.2–4.7.3 —
the dissertation's showcase for why episodic memory of failure matters.

§4.7.2: a snag description holds the Workspace structures responsible, a vertical
theme-pattern, the top rule, and the translated rule that caused the snag.

### J3. Reminding is degenerate

§4.7.5 defines distance over five components. Petacat's `_theme_distance` (`memory.py:133`)
counts differing dimensions — component 1 only, and crudely. Combined with the empty theme
patterns from Phase A, the observed result is:

```
stored answers: [ijl, xyy, xyy, mrrkjj]
reminded of 3 of 3 prior answers
   dist 0.0  ('abc','abd','ijk','ijl')
   dist 0.0  ('abc','abd','xyz','xyy')
   dist 0.0  ('rst','rsu','xyz','xyy')
themes of last answer: {'top_bridge': {}, 'vertical_bridge': {}}
```

Every answer reminds the program of every stored answer, at full strength.

Implement all five components: (1) differing + unique themes; (2) structural and conceptual
rule differences; (3) rule abstractness difference; (4) themes justified for one answer but
not the other; (5) coherence mismatch. Store per-answer activation and set it from distance
on each new answer, per §4.7.5.

### J4. Answer comparison and its commentary don't exist

§4.7.3–4.7.4 — one of the four headline objectives of the Metacat project.

`comparison_templates`, `theme_phrase_templates`, `caveat_templates`,
`comparison_judgment_priority` and `answer_explanation` are all present in
`seed_data/commentary_templates.json` and referenced by **no Python code**.
`POST /api/memory/compare` returns raw theme dicts.

Needed: classification into **common / differing / unique / unjustified / snag-justified**
themes; the snag-justified reclassification rule from §4.7.3 (an unjustified theme becomes
snag-justified when a snag description exists for the same strings and rule); a coherence
check comparing rule abstractness against theme abstractness; structural rule alignment; a
preference judgement; and English rendering through the seeded templates in the
`comparison_judgment_priority` order.

---

## Phase K — Surface all of this in the UI

Fixes that don't reach the UI can't be smoke-tested.

- **K1 — Themespace.** Serialise the server's dominance flag and the thematic-pressure state.
  `ThemespaceView.tsx:51` currently recomputes dominance client-side with a different rule
  (`max |activation|`, threshold 5) than the server's margin-of-90. Show pressure on/off per
  theme type, and distinguish clamped themes.
- **K2 — Trace.** Render the seven dissertation event types distinctly, including the new
  slippage and concept-activation events, and show each event's importance.
- **K3 — Memory.** Show per-answer activation (§4.7.5 renders it as a grey-scale "fade into
  the background"), snag descriptions, unjustified/snag-justified themes, and the English
  comparison commentary from J4.
- **K4 — Rules.** Surface built top and bottom rules with quality, uniformity, abstractness
  and succinctness, so E6 is verifiable by eye.
- **K5 — Types.** Extend `client/src/types/index.ts` for all of the above.

### K6 — Second pass over the UI, after the engine work landed

Three things the engine could now express but the display could not:

- **K6a — Nested group enclosures.** `_serialize_group` sent only `left_pos`/`right_pos`,
  and `WorkspaceView` drew every box with the same padding, so a group-of-groups drew
  *on top of* its subgroups instead of around them. The Scheme sizes each enclosure by
  letter span — `sizing-factor = (max 1 (sub1 letter-span))`, `groups.ss:147` — which is
  what makes an enclosing box bigger than what it encloses. Ported that, with `depth`
  (`get_nesting_level()`) breaking the tie when a group and its subgroup span the same
  letters, standing in for the Scheme's singleton `shrink-factor` (`groups.ss:149-158`).
  `length` is serialised too, since Length is a bond facet the display should be able
  to show. Covered by the nesting assertions in
  `test_the_one_two_three_reading_of_mrrjjj_is_constructible`.
- **K6b — Giving up was invisible.** `runner.status` became `gave_up` and the DB row
  recorded it, but `StepResult` carried no such flag, so the client's stepping loop
  could not tell "gave up" from "ran out of codelets" and kept stepping to `halted`.
  Added `StepResult.gave_up` → `StepResponse.gave_up` → the store's `RunStatus` union
  and its terminal-state check, plus a distinct colour in `RunHistory` (warning, not
  error — §4.5.2 giving up is a considered outcome). Verified reachable: `gave_up`
  occurs 3/20 seeds on `abc→abd; xyz→dyz` justification and 1/20 on `abc→abd; xyz→?`.
  Covered by `test_giving_up_is_reported_on_the_step_result`.
- **K6c — Status strings.** `RunHistory` printed the raw enum name; underscores are now
  rendered as spaces so `gave_up` reads as "gave up".

- **K6d — Changing the problem did nothing.** All three run handlers were guarded by
  `if (!store.runId)`, so a run was created only when *none* existed. Once one did,
  editing a string or picking a different demo and pressing Run silently continued the
  **previous** problem — the workspace never changed, which reads as "the GUI won't
  reset". It compounded: `ProblemInputPanel` re-synced the form from `workspace` on every
  refresh, so the old problem's strings were then stamped back over what had just been
  typed. Three fixes: the store records `runParams` for the loaded run and the handlers
  start a new run whenever the form has drifted from it (strings, answer, or seed);
  `createRun` now blanks the panels the way `reset` does, so the switch is visible
  immediately even if a refresh fails; and the form-sync effect is keyed on run id
  instead of on every workspace poll. Added a status line under **Run to Answer** naming
  the run on screen and warning when the inputs no longer match it — the previous UI gave
  no way to tell which problem the visible workspace belonged to. Covered by
  `client/src/components/RunControlsPanel.test.tsx` (8 tests).

- **K6e — "Clear Memory" cleared the wrong copy.** Episodic memory exists twice over: as
  `answer_descriptions`/`snag_descriptions` rows, and in the process-wide `_global_memory`
  that live runs read and write. `GET /api/memory` serves the *rows*
  (`get_memory_state_from_db`), but `DELETE /api/memory` called only `_global_memory.clear()`
  — so the UI's refresh-after-clear re-read the untouched rows and showed everything still
  there. Moved the clear into `RunService.clear_memory`, which deletes both and reports how
  many of each it removed, mirroring what `delete_all_runs` already did correctly. Verified
  live: 3 answers + 9 snags → `{"cleared":true,"removed":{"answers":3,"snags":9}}` → refetch
  returns empty. Covered by `test_clearing_memory_clears_what_the_ui_reads_back`, confirmed
  to fail against the old endpoint.

- **K6f — The two run buttons hid a mode choice.** "Run to Answer" and "Run with Live
  Updates" are not two features; they are two mutually exclusive strategies for executing
  the same run — backend-at-full-speed sampled by `pollingInterval`, versus client-driven
  codelet-at-a-time paced by `stepDelay`. Presenting them as two primary buttons in two
  separate boxes made the choice invisible and stranded the pacing controls: the polling
  slider sat under one button and applied only to it, while `stepDelay` had **no control
  at all**. Replaced with a single "How to run" selector; the action button relabels and
  only the selected mode's pacing control is shown (renamed *Sampling interval* — it reads
  the engine, it doesn't pace it — and a new *Delay per codelet*). `Step N` moved to its
  own "Manual stepping" group, being orthogonal to run mode. The mode also now sets
  `liveUpdate` explicitly rather than relying on the store default.
- **K6g — Reset was in the wrong panel.** It sat wedged next to `Step N` inside a box
  labelled "Live Updates", i.e. among controls for *how* to run rather than *what* to run.
  Moved to the foot of Problem Input together with **Seed**, so the panel owns the
  problem's identity and Reset's meaning is legible: same strings, same seed, workspace
  cleared. Relabelled "Reset to codelet 0" — the old label said only "Reset", and `reset()`
  deliberately does *not* start running, which the help text now states.
- **K6h — Labels were not associated with their inputs.** None of the Problem Input fields
  had `htmlFor`/`id` pairs, so clicking a label didn't focus its field and screen readers
  had nothing to announce. Fixed for all six controls.

- **K6i — Run History never refreshed after a run finished.** The panel is mounted for the
  whole session, and its fetch effect depended only on `[currentRunId, epoch]` — neither of
  which changes when a run *ends*. So the list was fetched once just after a run was created
  and never again: completed runs sat there reading "initialized, 0 codelets, T 100" while
  the API had the real outcome all along (confirmed by hand — a run went
  `initialized/0/100` → `gave_up/520/47` in `GET /api/runs` with the row on screen unchanged).
  Added `liveStatus` to the deps so every status transition refetches, and overlaid the
  store's live figures onto the active run's row so it advances during a run at no extra
  request cost. Covered by `RunHistory.test.tsx` (4 tests); the refetch test was confirmed to
  fail with the dependency removed.

- **K6j — `GET /api/runs/{id}` reported creation-time values for a live run.**
  `run_to_completion` writes `codelet_count` and `temperature` back to the row only when
  the run *ends*, so mid-run the row still said `running` with 0 codelets and temperature
  100 — measured directly: four consecutive polls returned `cdlts=0 T=100.0` while
  `/temperature` read 45–64. The UI polls that endpoint each sampling tick and then calls
  `refreshAll`, so every tick set the temperature to 100 and a live read corrected it a
  moment later: a visible spike on every sample, and a codelet count pinned at 0 because
  nothing else sets it. `get_run_info` now prefers the loaded runner — which is the
  authority on how far a run has got — and falls back to the row for runs not in memory.
  Covered by `test_run_info_reports_live_progress_while_running`, which polls a run in
  flight and was confirmed to fail with the fix disabled. `list_runs` still serves rows,
  which is why K6i's client-side overlay stays.

- **K6k — The answer now appears in the Run History row.** The row showed only the problem,
  so the outcome — the interesting part — was invisible without loading the run. Rows now
  read `abc->abd; xyz -> xyd`. One subtlety made this more than a formatting change: in
  justification mode the answer is *supplied* at creation for the engine to explain, so a
  non-null `answer` does not by itself mean the engine found anything. `justify_mode` existed
  on the `runs` row but was never exposed, so the display had no way to tell "it found xyd"
  from "it was asked about xyd". Threaded through `RunInfo` → `RunResponse` → the client
  type, and a given answer renders in the warning colour with a trailing `?` while a
  discovered one renders in the success colour. The active row also takes its answer from
  the live workspace, so it appears the moment the engine finds it. Covered by 4 more
  `RunHistory.test.tsx` cases and
  `test_run_list_carries_the_answer_and_how_it_was_obtained`.

- **K6l — The workspace diagram was illegible wherever structures were dense.** Every
  bridge label was written at the midpoint of its own line; since all bridges of a type
  span the same two rows, all those midpoints were the *same* y and the labels printed on
  top of each other. Group labels, string labels, bond labels and the rule text collided
  the same way — fixed offsets with nothing reserving space. Fixes:
  - **Connectors are shallow arcs** (quadratic, bowed by index) rather than straight
    chords. Two bridges with different endpoints previously shared almost their whole
    path; bowing separates them along their length, and it lifts a same-row bridge clear
    of the letters it used to be drawn straight through.
  - **Bridge text moved off the lines** into a numbered key below the diagram — badge on
    the arc, full entry in the key. A bridge carries five or six concept-mappings, so
    those labels were wider than the diagram.
  - **Slippages over identities**: `is_slippage` is now serialised per mapping, so the key
    shows `lmost⇒rmost, first⇒last +1id` instead of spelling out every
    `LetterCtgy=LetterCtgy`. Full text stays in the tooltip.
  - **Greedy lane packing** for group and bond labels, so overlapping ones step to a free
    row instead of stacking. Nine groups on one string used to be a row of superimposed
    words.
  - **Reserved bands** for rules, string labels, group labels, bonds and counts; the
    inter-row band grows with the vertical-bridge count; canvas height is computed rather
    than a fixed 320 everything was squeezed into.
  - Bridges now attach at each object's **centre** (`obj1_right_pos`/`obj2_right_pos` added
    to the serializer), so a bridge onto a group points at the group, not its first letter.
  - Halos (`paintOrder="stroke"`) on text that arcs unavoidably cross, and the counts are
    drawn after the bridges so arcs pass behind them.

  Verified by `WorkspaceView.test.tsx`, which renders four real captured workspaces
  (`__fixtures__/`, including the two cases that showed the problem worst) and asserts that
  no two text boxes overlap and nothing escapes the canvas — it started by reporting 28
  collisions and now reports none. Also checked by eye: rendered to standalone SVG and
  inspected, which is how the cramped badges and over-painted counts were caught, neither
  of which a text-overlap check can see.

- **K6m — The spreading threshold usually never reached the run that executed.** The value
  lived only on the server's in-memory `runner.ctx`, with no DB column and nothing carrying
  it forward. Three consequences compounded: a newly created run started at the metadata
  default; `reset_run` called `init_mcat`, which re-read that default and discarded the
  chosen value; and the slider was `disabled={!hasRun}`, so it could not be set until a run
  already existed. The practical effect was that setting the slider and pressing Run
  applied the value to whichever run happened to be loaded, then executed a *different*,
  freshly created run at 100 — and the slider snapping back to 100 was reporting the run's
  real state rather than misdisplaying it.

  The threshold does reach the engine when it does apply — measured on one problem at one
  seed: 797 codelets at 100, 2165 at 50, 731 at 0. So this was a plumbing failure, not a
  dead setting.

  Fixed by treating it as what it is — a Run Controls session setting, like the Eliza toggle
  and the pacing sliders, which already persisted because they live in the store. It now
  lives in the store, is pushed to each new run inside `createRun`, is applied immediately
  to the loaded run when moved, and the slider no longer requires a run to exist.
  Server-side, `reset_run` preserves it across the re-init. Covered by three
  `RunControlsPanel.test.tsx` cases and
  `test_spreading_threshold_changes_the_run_and_survives_reset`, which fails if the
  threshold stops affecting the engine at all.

- **K6n — Persisting the threshold properly, as the fundamental parameter it is.** Two
  separate things needed to survive, and only one of them is a UI preference:
  - *The value a run used* is now a column on the run — `runs.spreading_threshold`,
    migration `008`, `server_default="100"` so existing rows read as the behaviour they
    actually ran at. Set at creation (`POST /api/runs` accepts `spreading_threshold`, so
    the engine is initialised with it rather than patched after the opening codelets), and
    written on every change. Carried through `RunInfo` → `RunResponse` → the client type,
    and shown in a **Spr** column in Run History, highlighted when it is not 100 — a run at
    any other value is not comparable with the dissertation's.
  - *The value the user chose* is kept in `localStorage`, so it outlives a page reload, and
    is sent with each new run.

  `_reconcile_metadata_columns` gained server-default support so the new column backfills
  on an existing volume instead of leaving NULLs; the models share one `Base`, so it
  already covered runtime tables. Verified on the live volume: column added with
  `DEFAULT 100`, existing rows read 100, and thresholds of 0 / 45 / 100 survived an app
  restart with 731 / 819 / 797 codelets respectively.

  **One bug found by the new test, in this work itself:** the row was read back with
  `int(r.spreading_threshold or 100)`, so a threshold of **0** — the most interesting
  non-default value — silently reported as 100. The e2e test caught it precisely because it
  asserts on both 100 and 0; the 100 case passed while the 0 case failed. Replaced with
  explicit `is None` checks at all three sites.

  Covered by `client/src/store/runStore.test.ts` (6 tests: default, save, reload, clamping,
  sent-at-creation, per-run override), two `RunHistory.test.tsx` cases, and two e2e tests.

Docs updated to match: the `run_controls` and `problem_input` help topics in
`seed_data/help_topics.en.json` (regenerated into `HELP.md`, `--check` clean) and the
README's Getting Started section, which described the old two-button layout.

### Frontend port, and two things found next to it

The dev frontend now publishes on **:59595** (`docker-compose.dev.yml`), with the CORS
origin in `server/main.py` and the docs updated to match. Two adjacent problems surfaced:

- **The README told you to open the wrong port.** It said "Open http://localhost:8100" for
  the dev stack, but the static mount is `../static`, which only exists in the production
  image (`Dockerfile:52` copies `client/dist` there). In dev, 8100 is API-only and answers
  404 at `/`; the UI is served by Vite, which proxies `/api` and `/ws` back to the app. The
  README and root `CLAUDE.md` now say which port is which and why.
- **The frontend container was clobbering the host's `node_modules`.** `./client` is bind
  mounted, so the container's `npm install` (linux/musl) overwrote the host's platform
  binaries and broke `npm run build` on the host with a missing
  `@rollup/rollup-darwin-arm64`. It happened twice this session before the cause was clear —
  the second time immediately after recreating the container for the port change. Added a
  named volume for `/app/client/node_modules` so each side keeps its own. While editing that
  file: the compose had **two top-level `volumes:` keys**, the second silently overriding the
  first, so declaring the new volume in the wrong one would have dropped `petacat-pgdata`
  and the database with it. Merged. Also dropped `VITE_API_URL`, which no client code reads.

Checked and already wired, no change needed: commentary (`/commentary` → store →
`CommentaryPanel`), the demo dropdown (`ProblemInputPanel` fetches all 34), the Answer
field for justification mode, and the temperature clamp controls. **Reset** itself was
always correct — it clears panel state and re-inits the same problem and seed; it was the
placement and label that were wrong. Admin's **Full Reset** was likewise already correct:
it goes through `DELETE /api/runs` → `delete_all_runs`, which always cleared both copies.

Known cosmetic inconsistency, left alone: `MemoryView` calls `/api/memory/compare` with
a bare `fetch` rather than going through `api/client.ts` like every other call.

---

## Phase L — Tests

Add tests that encode the *dissertation's* claims, not the current behaviour. At minimum:

- **A** — a built bridge boosts a theme; a label-less concept-mapping produces a `diff` theme;
  after a short run at least one theme is non-zero; dominance matches the margin rule
  including the negative-theme case.
- **B/C** — thematic compatibility is 0 with pressure off; a clamped positive theme raises a
  compatible bridge's strength and lowers an incompatible one's; an incompatible theme
  outweighs two compatible ones (p.143).
- **D** — a snag produces a `SnagEvent` with structures and a theme pattern; three similar
  snags let the jootser clamp a negative vertical pattern; repeated clamps lead to give-up.
- **E** — extrinsic (swap) rules are buildable; `components` rules are buildable; verbatim
  rules appear at roughly `verbatim_rule_probability`; no intrinsic String-Position clause is
  ever emitted; `abc→abcd` applied to `ijk` yields `ijkl`; `abc→aabbcc` applied to `ijk`
  yields `iijjkk`; *"…to successor"* scores more abstract than *"…to `d'"*.
- **F** — justify mode on `abc→abd; xyz→wyz` builds a bottom rule and reports a justification.
- **G** — every link's effective length matches the Scheme (table-driven from a checked-in
  expected-lengths fixture); link count is 202.
- **H** — a vertical bridge between `a` and `i` has no letter-category slippage; the
  equivalent horizontal bridge does.
- **I** — a run of a few hundred codelets produces Trace events in the dozens, not hundreds;
  no bond events; slippage and concept-activation events appear.
- **J** — reminding distance separates `xyd` from `dyz`; an answer does not remind the program
  of an unrelated one; comparison classifies common/differing/unique correctly; a stored snag
  for the same strings and rule reclassifies an unjustified theme as snag-justified.

Also add a **behavioural regression test** over the dissertation's canonical problems with
fixed seeds, asserting the expected answers appear (`ijl` for `abc→abd; ijk→?`, `ijkl` for
`abc→abcd; ijk→?`, `xyd`/`wyz`/`dyz`/`xyz` for `abc→abd; xyz→?`, and so on). Keep it tolerant
of the model's stochasticity — assert membership in Metacat's known answer set and a minimum
hit rate, not a single answer.

---

## Out of scope

Explicitly **not** part of reaching parity. Do not start these:

- Anything not in the dissertation.
- Performance work, refactors, or architectural changes for their own sake.
- New codelet types, new Slipnet nodes, new theme dimensions.
- The dissertation's own listed shortcomings (§5.3, §6.2) — context-sensitive rule quality,
  decaying answer activations, comparing answers on top/bottom themes, snag reminding.
  Metacat doesn't do these either, so parity means not doing them.
