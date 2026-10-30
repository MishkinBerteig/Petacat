# WP3 effects audit - what shared state every codelet builtin, body and read path touches

Scope: the 57 DSL builtins (`server/engine/codelet_dsl/builtins.py::get_builtins`), the 27 codelet bodies (`seed_data/codelet_types.json`) and every engine function they reach, for the purpose of exact (serial-equivalent) speculation.  Read-only on the repo; everything here lives in `agents-workspace/wp3-speculative/audit/`.

Companion file: `effects_table.json` (machine-readable: 57 builtins, 27 bodies, 23 read-path hazards). Regenerate with `build_effects_table.py`; this report with `make_report.py`.

## 1. How it was checked

1. **Reading.** Every builtin in `builtins.py` (all 3,271 lines) and every engine function a body imports or calls directly: `bonds`, `groups`, `bridges`, `concept_mappings`, `descriptions`, `workspace`, `workspace_objects`, `workspace_structures`, `slipnet`, `coderack`, `ids`, `rng`, `themes`, `trace`, `rules` (build_rule_from_bridges, currently_works, apply_rule, revise_abstracted_rule_information, translate), `images`, `verbose`, `memory`, `temperature`, `formulas`, `runner`.
2. **AST tooling** (`scan_bodies.py`, `body_calls.py`): per-body builtin calls in evaluation order, direct engine calls, attribute stores, imports, use of the name `codelet_count`.  `scan_getter_writes.py`: methods named like getters that assign attributes.  `scan_module_mutables.py`, `scan_set_iter.py`: module-level mutable containers that are mutated (none), and iteration over sets (none).  `callgraph.py`/`who.py`: an over-approximate name-resolved call graph used to find which constructors and stores are reachable from an entry point.
   *Coverage caveat:* the rule-abstraction pipeline behind `rules.build_rule_from_bridges`, `images.py` internals, `trace_display.build_event_picture` and the barrier-family functions (`jootsing.*`, `justify.*`, `answers.*`) were not read line by line; they are covered by the call graph and the two dynamic observers, and the bodies that call the barrier ones are classed BARRIER (write-everything).
3. **Black-box confirmation** (the part that catches what reading misses):
   - `observe_effects.py`: monkey-patched every DSL builtin plus the shared mutators and ran **492 serial runs** (1136578 codelet executions; all 41 demo problems x 12 seeds, up to 4000 steps each) recording which mutator fired inside which builtin / body of which codelet type.
   - `observe_fingerprint.py`: fingerprinted 14 shared components (workspace structure, per-object values, `.image` attributes, slipnet activation / buffer, themespace, trace, coderack incl. per-codelet urgency and stamps, id counters, temperature, memory, ctx scalars, verbose log, RNG call count) before and after every builtin call **and in the gaps between builtins** (= direct engine calls made by the body), over 164 runs (323995 executions).
   - `evidence_coderack_rng.txt`, `evidence_thread_state.txt`: two tiny scripts that demonstrate hazards 4 and 6 below.

## 2. Component map (what non-barrier codelets actually do to shared state)

| component | read by | written by (non-barrier codelets) | notes |
|---|---|---|---|
| workspace | every choose_*/get_*/evaluate_*; scouts; evaluators | `build_structure`, `break_*`; **also hidden**: `rule-evaluator` (`obj.image`), `rule-builder` (`revise_abstracted_rule_information`), `rule-scout`/`rule-evaluator` (`attach_length_description` on built groups), `Bridge._all_concept_mappings` rebinds | per-object values (salience, importance, unhappiness, stored string averages, mapping strengths, rule-possible flags) change only at update cycles (barrier) - **except** `.strength` of built structures, which `_wins_fight` rewrites inside builds, even failed ones |
| slipnet_act | `fully_active`, `degree_of_assoc`, relevance, activations | **bridge builds** (`ConceptMapping.activate_label` writes `.activation` and zeroes the buffer, concept_mappings.py:379-386); otherwise only update cycles / clamps (barrier) | contradicts the working assumption that codelets never write activation |
| slipnet_buf | `activate_label` | `activate_from_workspace` (called by propose_*, evaluate_group, build_structure and the bond/description/rule evaluators and builders), `ConceptMapping.activate_descriptions` (**direct body call** in bridge-evaluator and inside propose_bridge) | `+= 100`: integer-valued, commutative, but non-atomic |
| themespace | evaluate_structure (bridge/description thematic compatibility), thematic-bridge-scout | bridge builds (`_boost_themespace_activations`) | read through the class attribute `WorkspaceStructure._themespace` |
| trace | (barrier bodies only) | `build_structure` -> `record_event` (group/slippage/rule events, concept-activation events from `activate_label`) | event recording runs `attach_picture`, which reads the whole ctx |
| memory | `answer_present` (barrier bodies) | none in non-barrier codelets | untouched by the 23 non-barrier types |
| temperature | choose_*, evaluate_*, fights, temp_adjusted_* | none (clamps are barrier) | constant between barriers |
| coderack | `_proposed_groups` (builds/breaks scan every rack codelet's arguments), eviction in `post` | `post_codelet`, `propose_*`, `propose_bridge` (posts straight to the rack), rule-builder (post answer attempt) | `post` also reads hidden `current_time`, `current_temperature`, and draws from the RUN rng |
| ids | - | every constructor of Codelet / Letter / Group / Bond / Description / Bridge / Rule / TraceEvent (see section 4) | allocation order must equal serial order |
| verbose | - | `say`, `vprint` (only when `ctx.verbose`) | order-observable (`_next` line numbers) |
| ctx_scalars | - | none in non-barrier codelets (`_pending_answer`, `_gave_up`, `last_failure*`, `run_ended` are touched by `report_answer`, `give_up`, `apply_rule`) | `ctx.codelet_count`, `coderack.current_time`, `_clock` are advanced by the runner per step |
| sink | - | `ctx.sink.on_structure_change` from builds/breaks (token-ordered) | `NullSink` by default; the Audit sink reads the whole ctx |
| proposals | - | **not private**: visible on the coderack as `Codelet.arguments['structure']`, scanned by `_proposed_groups`; a build/break can delete a `middle` description from a proposed Group | see hazard 8 |

## 3. Per codelet type

`exec %` is the share of the 1136578 observed executions; `no shared event %` is the share of that type's executions in which none of the instrumented shared mutators fired (an upper bound on how much of the type is a pure read); barrier types are the 4 in the meta/answer families.

| type | family | barrier | exec % | no shared event % | first write |
|---|---|---|---|---|---|
| top-down-bond-scout:category | bond |  | 13.9 | 77.5 | 67: propose_bond(...) |
| top-down-description-scout | description |  | 10.5 | 36.1 | 34: propose_description(obj, desc_type_node, descriptor) |
| top-down-group-scout:category | group |  | 8.0 | 36.6 | 81: Group(string, grp_cat_node, plato-letter-category, singleton_direction, [obj], []) |
| description-evaluator | description |  | 6.4 | 0.0 | 7: activate_from_workspace(desc.descriptor) |
| bottom-up-bridge-scout | bridge |  | 6.4 | 73.0 | 80: propose_bridge(bt, obj1, False, obj2, flip2, plato-identity, ctx) |
| bottom-up-bond-scout | bond |  | 5.7 | 55.4 | 61: propose_bond(...) -> activate_from_workspace x3 (slipnet_buf), Bond() (structure id), post_codelet (cod... |
| important-object-bridge-scout | bridge |  | 5.5 | 16.0 | 38: workspace.get_all_slippages(bt_name) is the first HIDDEN write (lazy rebind of Bridge._all_concept_mapp... |
| bond-evaluator | bond |  | 5.4 | 25.7 | 10: activate_from_workspace(bond.from_descriptor, bond.to_descriptor, bond.bond_facet) |
| bridge-evaluator | bridge |  | 4.5 | 25.7 | 21: cm.activate_descriptions() inside the loop at lines 20-21 (a DIRECT engine mutation: slipnet_buf) |
| thematic-bridge-scout | bridge |  | 3.8 | 56.3 | 104: propose_description_based_on_theme (conditional: Description id + descriptor.activate_from_workspace) ... |
| bond-builder | bond |  | 3.4 | 11.7 | 15: build_structure(bond) |
| rule-scout | rule |  | 3.0 | 13.0 | 25: Rule(...) in the 1% verbatim branch (structure id) -> 35: post_codelet |
| description-builder | description |  | 2.9 | 0.4 | 18: activate_from_workspace(desc.description_type, desc.descriptor) (duplicate branch, then fizzle) else 23... |
| bridge-builder | bridge |  | 2.8 | 13.4 | 19: build_structure(bridge) |
| top-down-bond-scout:direction | bond |  | 2.6 | 67.4 | 55: propose_bond(...) |
| group-scout:whole-string | group |  | 2.4 | 90.0 | 28: polarize_bonds(...) (conditional: Bond.flipped id) |
| rule-evaluator | rule |  | 2.1 | 0.0 | 11: rule.currently_works(workspace, slipnet) |
| group-evaluator | group |  | 2.0 | 16.3 | 9: evaluate_group(group) |
| bottom-up-description-scout | description |  | 1.6 | 98.6 | 50: propose_description(obj, new_desc_type, chosen_property) |
| progress-watcher | meta | YES | 1.4 | 98.2 | 11: check_progress(...) |
| top-down-group-scout:direction | group |  | 1.4 | 59.8 | 54: scan_bonds(...) (conditional: Bond.flipped id) |
| rule-builder | rule |  | 1.3 | 0.0 | 14: activate_from_workspace(node) (only if rule.get_descriptors_to_activate() is non-empty) |
| group-builder | group |  | 1.3 | 11.7 | 22: build_structure(group) |
| answer-justifier | answer | YES | 0.8 | 0.2 | 17: attempt_justification(...) |
| jootser | meta | YES | 0.5 | 98.7 | 10: attempt_jootsing(...) |
| answer-finder | answer | YES | 0.4 | 89.7 | 54: translate_rule(chosen_rule) (Rule id) / 62: apply_rule(translated) (ctx.last_failure*, obj.image rebuil... |
| breaker | breaker |  | 0.2 | 75.9 | 31: break_group(enclosing_group) / 32: break_bond(target) / 35: break_structure(target) |

Overall 41.2% of executions fire no instrumented shared mutator (pure reads that fizzle) and only 3.0% of executions are barrier types.

## 4. Constructors: ids and back-references

| constructor | ids allocated | back-reference added to another object? |
|---|---|---|
| `Codelet` (coderack.py:119-135) | KIND_CODELET x1 | no |
| `WorkspaceObject` / `Letter` (workspace_objects.py:33-73, 882-893) | KIND_OBJECT x1 | no (`WorkspaceString.__init__` appends letters to its own list) |
| `WorkspaceStructure` (workspace_structures.py:43-56) | KIND_STRUCTURE x1; `time_stamp := _clock.now` (thread-local, default 0) | no |
| `Bond` (bonds.py:26-43) | structure x1 | **no** - `from_object.right_bond` etc. are set only by `WorkspaceString.add_bond` at build |
| `Group` (groups.py:27-74) | **object x1 + structure x1 + structure x1 per initial Description (4-7)**; the structure id is drawn but the object id is kept | **no** - `enclosing_group` of constituents is set only by `add_group`; `objects`/`group_bonds` lists are stored by reference (`make_flipped_version` shares `objects` with the original) |
| `Description` (descriptions.py:39-49) | structure x1 | **no** - attached only by `add_description`/build |
| `Bridge` (bridges.py:36-69) | structure x1 | **no** - `horizontal_bridge`/`vertical_bridge` set only by `Workspace.add_bridge` |
| `Rule` (rules.py:1031-1068) | structure x1 | no (stores `workspace` back-ref on itself) |
| `ConceptMapping` (concept_mappings.py:53-71) | none | no |
| `TraceEvent` and subclasses (trace.py:106-161) | KIND_TRACE_EVENT x1 (allocated before the commit lock in `record_event`) | no |
| `EpisodicMemory.store_*` (memory.py:201-208) | answer/snag ids from the **memory's own** allocator | no (barrier paths only) |

So a proposal is private to its codelet **except** through `Codelet.arguments` once posted (hazard 8).  `Bond.flipped()` (bonds.py:357) and `Group.make_flipped_version()` (groups.py:472) allocate ids too, and are called from read prefixes.

## 5. update_strength / external strength

`WorkspaceStructure.update_strength` (workspace_structures.py:67-115) writes **only `self.strength`**.  What it reads:
- **Bond** (bonds.py:61-218): `bond_category.degree_of_assoc()` -> `fully_active()` (slipnet_act); `string.bonds` (built, disjoint, same category/direction); a stochastic neighbour walk (`choose_left/right_neighbor(rng)` -> letters, built groups, neighbours' `salience['intra']`, `right_bond/left_bond`) that draws only with >=2 candidates; `rng.trace_about` seam (no-op).
- **Group** (groups.py:201-338): same shape over `string.groups`, `spans_whole_string`, enclosing-group substitution in the walk.
- **Description** (descriptions.py:55-182): `descriptor.conceptual_depth` (static), sibling descriptions in the string, `description_type.activation`, Themespace via the class attribute.
- **Bridge** (bridges.py:240-372, 442-520): concept-mapping strength/relevance/distinguishing (slipnet_act + workspace), **other built bridges' `.strength`**, `_incompatible_bridges` over `.concept_mappings` (does NOT call the lazy `get_all_concept_mappings`), Themespace.
- **Rule** (rules.py:1357-1398): rank of `self.quality` among `workspace.top_rules/bottom_rules`.
Everything it reads is covered by the components workspace / slipnet_act / themespace; the fingerprint observer confirmed it changes nothing else.  The *callers* are what matter: `_wins_fight` (builtins.py:2168-2169) applies it to **built** opponents.

## 6. The 15 most dangerous findings

**1. rule-evaluator's read prefix rewrites shared workspace objects, every time.** `Rule.currently_works` (rules.py:1425) -> `apply_rule` -> `_fresh_string_image` (rules.py:2853-2872) sets `obj.image = None` on every object of the source string, installs `string.image`, and `StringImage._make_image_for` (images.py:1043,1089,1105) stores new Image trees back on the objects.  Observed in 24205 of 24205 rule-evaluator executions (100%).  A Length-swap clause additionally calls `attach_length_description` on a **built** group (rules.py:3006-3030).  Two concurrent rule-evaluators corrupt each other.  No builtin is involved, so a builtin-level classifier sees a pure read.  Treat as WRITE(images) from line 11.

**2. rule-builder mutates a built rule in the body, 87% of the time.** Body line 23 `other.revise_abstracted_rule_information(rule)` (rules.py:1498-1528) rewrites `tagged_supporting_horizontal_bridges`, `supporting_bridges` and `theme_pattern` of a rule already in `workspace.top_rules`, before `build_structure`, then fizzles.  Observed in 12,555 of 14,408 executions.  No builtin write precedes it (unless `get_descriptors_to_activate()` is non-empty).

**3. `Bridge.get_all_concept_mappings()` is a getter that writes (lost-update race).** bridges.py:111 rebinds `self._all_concept_mappings` on every call.  `important-object-bridge-scout` line 38 (`workspace.get_all_slippages`) calls it on every built bridge - 76% of that type's executions start with it (115,275 calls observed); rule-scout and thematic-bridge-scout reach it too.  A committing builder mutates the same list **in place** (bridges.py:155,161); a reader that rebinds after computing from the old state drops the insertion, and the reconcile later re-appends it at the END, changing the all-CMs order that rule translation and its coin sequence depend on.

**4. Eviction in `Coderack.post` draws from the run RNG, not the step stream.** `runner.py:422` sets `coderack.rng = rng` (the raw run generator); `post` (coderack.py:371-377) evicts with it, bypassing `EngineContext.rng`'s per-thread binding.  Demonstrated in `evidence_coderack_rng.txt`: 5 posts into a full rack consumed 5 draws from the run RNG and 0 from the bound codelet stream.  Every `post_codelet`, `propose_*` and the 0-3 direct posts inside `propose_bridge` are affected whenever the rack is full.

**5. Id allocation hides inside "reads" - up to 47% of one scout's executions.** `top-down-group-scout:category` builds a throw-away singleton `Group` in its prefix (body line 81): 1 object id + 1 structure id + 4-7 Description ids (mean 7.2 structure ids) in 42,564 of 90,859 executions, before the fizzle decision.  Also `scan_bonds`/`polarize_bonds` (`Bond.flipped`), `conditions_for_bridge` in thematic-bridge-scout (4,116 flipped Groups / 8,144 flipped Bonds in 42,934 executions), `propose_bridge`, `Rule(...)` in rule-scout.  Ids must be taken in serial order; hook `next_id` rather than relying on builtin classes.

**6. A fresh worker thread allocates from the wrong allocator and stamps time 0.** `ids._CURRENT` is a ContextVar defaulting to the process allocator; `_clock` is `threading.local` defaulting to 0 (workspace_structures.py:24,49).  `evidence_thread_state.txt`: a naive thread produced Bond id 1 / time_stamp 0 and left the run allocator untouched; with `use_allocator(ctx.ids)` + `set_structure_clock(n)` it produced id 50 / time_stamp 40.  Sub-structures made inside constructors (a Group's Descriptions, flipped copies) keep the `_clock` stamp - it feeds `Workspace.get_activity` -> progress-watcher.

**7. A builder that returns False has already written.** `_wins_fight` (builtins.py:2168-2169) calls `update_strength(ctx.rng)` on the proposer and every built opponent - RNG-dependent rewrites of shared `.strength` - before the coin.  Lost fights, duplicate merges (`_absorb_duplicate_group`, `_merge_duplicate_bridge`) and failed premise checks all leave side effects.  A fizzled builder is not a read-only step.

**8. Proposals are visible through the coderack.** `_proposed_groups` (builtins.py:1194-1213) scans every rack codelet's `arguments['structure']`; `delete_invalid_string_position_middle_descriptions` (workspace.py:411-416) then deletes a `middle` description from a *proposed* group.  A speculative clock-coderack that removes its pick from the bins early makes step k's build blind to a proposal that serial order still has on the rack.

**9. `except (ImageFailure, Exception)` swallows aborts.** rules.py:1442 (rule-evaluator, answer-finder).  A `SpeculationAbort(Exception)` raised in `currently_works` becomes a silent "rule does not work" fizzle.  Derive the abort from `BaseException`.

**10. Slipnet buffer writes made by direct calls, not builtins.** `bridge-evaluator` line 21 `cm.activate_descriptions()` (111,275 calls) and `propose_bridge` (`cm.activate_descriptions`, `length_node.activate_from_workspace`, `category.activate_from_workspace`) write `activation_buffer` outside the builtin layer; `ConceptMapping.activate_label` also writes `activation` itself.  `propose_bridge` also posts straight to `ctx.coderack` (0-3 scouts) without going through `post_codelet`.

**11. Hidden shared writes in rule-scout's "read" path.** `build_rule_from_bridges` -> `Rule.set_abstracted_rule_information` (rules.py:1484-1490) attaches Length descriptions to **built** groups (88 observed) and allocates their ids; 54,058 `get_all_concept_mappings` rebinds.  Rule ids are allocated at 87% of executions.

**12. Hidden coderack state and step-relative clocks.** `Coderack.post`/`remove_old_codelets` read `current_time` (set per step, runner.py:827,857) and `current_temperature` (set by every `choose_and_remove`, coderack.py:457); eviction weights are `(current_time - codelet.time_stamp)` x a temperature-indexed penalty, so `Codelet.time_stamp` (= `ctx.codelet_count` at posting) matters.  (Clamp/unclamp, a barrier, additionally restamps via `_move_urgencies`, coderack.py:719.)

**13. Back-references bypass a step-relative ctx.** `trace.ctx` and `workspace.verbose_ctx` (runner.py:470,475) point at the original `EngineContext`; `record_event` -> `attach_picture(self.ctx, ...)` and the clamp narration read through them, so a `codelet_count` property on a plugin ctx subclass is invisible there.

**14. Class-level `WorkspaceStructure._themespace`.** workspace_structures.py:41,58-64, set in `init_mcat` (runner.py:411,426).  Process-global: two runs in one process (SSR + speculative in a test harness, or threads) repoint each other's structures.  Use the swarm's processes for comparisons.

**15. Verbose mode is order-observable shared state.** `VerboseLog._next`, the bounded deque, `capture()/replay()` (pops and re-inserts lines), `_built`, lazy `_messages` (verbose.py:475-603); `print_text(Bridge)` also triggers the CM rebind.  Declare every body BARRIER (or run serially) when `ctx.verbose`.

## 7. Dynamic confirmation

`observe_effects.py` (492 runs, 1136578 executions): **no mutator fired inside any builtin classified READ** - the events in `observations.json` sit only in WRITE builtins (`propose_*`, `activate_from_workspace`, `build_structure`, `break_*`, `post_codelet`, `scan_bonds`/`polarize_bonds`, `evaluate_group` (tail), barrier builtins) or in direct body calls (`<body>`): `propose_bridge`, `cm.activate_descriptions`, `Group(...)`, `Rule(...)`, `build_rule_from_bridges`, `workspace.get_all_slippages`, `Rule.currently_works`, `Rule.revise_abstracted_rule_information`, `make_flipped_version`.

`observe_fingerprint.py` (164 runs, 323995 executions, 1522121 builtin calls):

- Component changes **inside a builtin classified READ** (ignoring RNG draws, which are expected): none.  The READ classification of the 37 READ builtins holds empirically.
- Component changes **between builtin calls**, i.e. made directly by the codelet body, by codelet type (barrier types abbreviated):
  - answer-finder (BARRIER): 134 executions changed shared state between/after builtins (update cycles, clamps, image rebuilds)
  - answer-justifier (BARRIER): 1872 executions changed shared state between/after builtins (update cycles, clamps, image rebuilds)
  - bottom-up-bridge-scout: `get_node -> post_codelet` changed ['ids', 'slipnet_buf'] (4971)
  - bottom-up-bridge-scout: `get_node -> post_codelet` changed ['coderack', 'ids', 'slipnet_buf'] (1135)
  - bottom-up-bridge-scout: `get_node -> post_codelet` changed ['ids'] (9)
  - bridge-evaluator: `evaluate_structure -> post_codelet` changed ['slipnet_buf'] (10824)
  - important-object-bridge-scout: `get_node -> post_codelet` changed ['ids', 'slipnet_buf'] (9360)
  - important-object-bridge-scout: `get_node -> post_codelet` changed ['coderack', 'ids', 'slipnet_buf'] (1724)
  - important-object-bridge-scout: `get_node -> post_codelet` changed ['ids'] (1)
  - jootser (BARRIER): 18 executions changed shared state between/after builtins (update cycles, clamps, image rebuilds)
  - progress-watcher (BARRIER): 120 executions changed shared state between/after builtins (update cycles, clamps, image rebuilds)
  - rule-builder: `activate_from_workspace -> <end>` changed ['workspace'] (236)
  - rule-evaluator: `<start> -> evaluate_structure` changed ['ws_images'] (4644)
  - rule-evaluator: `<start> -> <end>` changed ['ws_images'] (1124)
  - rule-scout: `get_built_bridges -> post_codelet` changed ['ids'] (7017)
  - rule-scout: `get_node -> post_codelet` changed ['ids'] (101)
  - rule-scout: `get_built_bridges -> post_codelet` changed ['ids', 'workspace', 'ws_values'] (16)
  - thematic-bridge-scout: `get_node -> post_codelet` changed ['ids', 'slipnet_buf'] (2921)
  - thematic-bridge-scout: `get_node -> post_codelet` changed ['ids'] (653)
  - thematic-bridge-scout: `get_node -> post_codelet` changed ['coderack', 'ids', 'slipnet_buf'] (224)
  - thematic-bridge-scout: `object_has_description_type -> <end>` changed ['ids'] (203)
  - thematic-bridge-scout: `object_has_description_type -> weighted_pick` changed ['ids'] (102)
  - top-down-group-scout:category: `get_node -> single_letter_group_probability` changed ['ids'] (12065)

What this adds to the static reading: the `rule-evaluator` image rewrites (`ws_images`) are visible between every builtin; `rule-scout` changed the **workspace** structure fingerprint inside its prefix (`get_built_bridges -> post_codelet`, 16 times: Length descriptions attached to built groups); `rule-builder` changed it 236 times between its last activate and the end of the body (`revise_abstracted_rule_information` altering a built rule's supporting bridges / theme pattern); `bridge-evaluator` and every bridge scout changed `slipnet_buf` outside any builtin; and the lazy `Bridge._all_concept_mappings` rebind is **invisible** to a value fingerprint (same content) - it can only be found by reading, which is why it ranks third.

## 8. What WP3 needs to do with this

1. **Do not classify by builtin alone.** Use dynamic hooks that acquire the commit token at the moment of the first shared effect: `IdAllocator.next`, `Coderack.post`, `SlipnetNode.activate_from_workspace`, `ConceptMapping.activate_descriptions/activate_label`, `Bridge.get_all_concept_mappings`, `groups.attach_length_description`, `Rule.revise_abstracted_rule_information`, `rules._fresh_string_image`, `Workspace.add_*/remove_*`, `WorkspaceString.add_*/remove_*`.  The `first_write_call` field of each body says where the static cut would fall.
2. **Per-step binding checklist** (all thread-local or per-ctx): `use_allocator(ctx.ids)`, `set_structure_clock(step)`, `ctx.use_codelet_rng(stream)`, the eviction stream for `Coderack.post`, `coderack.current_time/current_temperature`, `trace.ctx`/`workspace.verbose_ctx`, `ctx.codelet_count`; also keep `staleness_delay == 0`, `track_access` off, `verbose` off (or serial).
3. **Treat these as WRITE regardless of what they look like**: `rule-evaluator` from line 11, `rule-builder` from line 21, the thematic scout's `get_conditions` and `propose_description_based_on_theme`, `scan_bonds`/`polarize_bonds`, the singleton `Group(...)` of `top-down-group-scout:category`, `important-object-bridge-scout` line 38.
4. **Abort exception** must derive from `BaseException`; validation must treat any exception in a prefix as an abort (live containers are iterated while others mutate them).
5. **Read-set components** that matter for validation: workspace (structure; per-cycle values are constant between barriers but built-structure `.strength` is not), slipnet_act (written by bridge builds), themespace (written by bridge builds), coderack (arguments of rack codelets are read by builds/breaks), and `images` (a hidden workspace sub-component).

## 9. Files

- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/audit_report.md`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/bodies_numbered.txt`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/bodies_scan.json`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/bodies_scan.txt`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/body_calls.py`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/build_effects_table.py`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/callgraph.py`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/effects_table.json`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/evidence_coderack_rng.txt`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/evidence_thread_state.txt`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/getter_writes.txt`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/make_report.py`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/observations.json`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/observations_fp.json`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/observe_effects.py`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/observe_fingerprint.py`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/observe_fp_run.log`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/observe_run1.log`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/observe_run2.log`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/scan_bodies.py`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/scan_builtins_stores.py`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/scan_getter_writes.py`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/scan_module_mutables.py`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/scan_set_iter.py`
- `/Users/mishkinberteig/Development/Petacat/agents-workspace/wp3-speculative/audit/who.py`
