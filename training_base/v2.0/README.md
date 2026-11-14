# The Training Mode Base Configuration, v2.0 ("the v2.0 Base")

`configuration_base` value: `"training-v2"`. A new Training Mode Session starts from it unless the request names
`"global"`, `"standard"` or `{"session_id": n}`. Metacat Mode never reads this folder, and a test holds that.

**This folder evolves.** `seed_data/` is the Metacat Standard Configuration and changes only to follow patched Metacat.
This folder is a delta over it and is expected to change as v2.0 work goes on. Change the delta, and a new session starts from the new text.

## What is here

- `delta.json`: `{"name", "title", "ops"}`. `ops` is an ordered change-API batch. It is resolved over the current Metacat
  Standard Configuration every time a session is created (or the Base is compared), so it is never stale.
- `codelets/*.py`: codelet bodies as real files, in the codelet interpreter's own Python.
- This file.

## How an op takes its text from a file

Any string value inside an op may be `{"$file": "codelets/<name>.py"}`. The loader replaces it with the file's text before
the batch reaches the change API. A `set_codelet_body` op that overrides a Standard body also carries
`"standard_sha256"`: the sha256 of the Standard body the override was written against. If the Standard body has since
changed, resolution refuses with a message naming the codelet, and nobody gets a silently stale override. The loader removes
that key before the change API sees the op. A Standard change that breaks any other op (a missing row, say) is refused the same way.

## Increments

1. A symbol with no Slipnet node gets one in the run (`symbol-scout`, `symbol-builder`, `new_node_conceptual_depth`, the `rule-scout` and `answer-finder` overrides).
2. Link types a configuration creates, and `adjacent` (the link type, `plato-adjacent`, the `bottom-up-bond-scout` override).
3. A session keeps what it saw side by side: `propose_ops`, `noticings`, fractional link lengths, `plato-adjacent` at depth 45 (stage A); `consolidator`, its rule, its triggers and its five parameters (stage B).

## What v2.0 adds so far

| Op | What it does |
|---|---|
| `add_link_type adjacent` (behaviour `lateral`) | the delta's first op. A link type this configuration owns: two symbols seen side by side. `consolidator` writes the links of this type: one for each pair of single symbols that an `adjacent` bond joined |
| `add_node plato-adjacent` | an instance of `bond-category`, beside `plato-successor` and `plato-sameness`; short name `adjacent`. Its `category` and `instance` links to `bond-category` have the lengths `plato-successor`'s have (30 and 100). Conceptual depth 45, just below `plato-successor`'s and `plato-predecessor`'s 50, because adjacency is the lowest-depth link concept (the user, 2026-11-14). No other property is set. Bound to the role `bond_category.adjacent`, and placed at grid (1, 13) in the layout |
| `update engine_params intrinsic_link_lengths` | adds `plato-adjacent` 90. A long length makes an `adjacent` bond weak (association about 10 against `successor`'s 40); a fully active category shrinks it |
| `insert theme_relations adjacent` | names `plato-adjacent`, so a rule can name the relation. No `valid_relations` list of a theme dimension has it yet |
| `add_param new_node_conceptual_depth` 10 | the depth a node made for a new symbol starts at (letters are 10) |
| `add_codelet_type symbol-scout` | family `description`, phase `scout`: finds a Letter object with no letter-category description |
| `add_codelet_type symbol-builder` | family `description`, phase `builder`: makes node `plato-cp-<hex code point>` (connected to nothing) with `apply_ops`, and proposes it as a trigger of `consolidator`'s rule (`add_trigger`, so it acts from the next run) |
| `add_param consolidation_threshold` 40, `adjacent_link_length` 90, `adjacent_link_step` 0.125, `symbol_category_link_length` 20, `symbol_instance_link_length` 97 | the five numbers only the `consolidator` body reads (engine parameters have no description column, so they are described here). The threshold is in noticings; the two lengths are the ones the seed's letters have for `category` and `instance`; the length and step are the pair's `adjacent` link (below). The step is exact in binary |
| `add_codelet_type consolidator` | family `meta`, phase `other`, top-down. One run is one noticing of the node in `args['slipnode']` (see below) |
| `add_posting_rule symbol-scout` | bottom-up, after `breaker`, urgency `low`, probability `1.0`, count 1, condition `num_unperceived_symbols > 0`; it draws no random number when every symbol is perceived |
| `add_posting_rule consolidator` + 26 `add_trigger` | top-down, urgency `round(activation / 2)`, posting probability `1.0`, count 1, condition `always`: it posts every time a trigger node's activation passes the gate (50), so that repeats register. Its triggering list is the 26 letters (`add_trigger` also adds them to `top_down_slipnodes`; each seed top-down rule names its own triggers, so none of them fires for a letter), and `symbol-builder` adds each new node. A rule with an empty triggering list would fire for every node in `top_down_slipnodes`, so the rule has none |
| `set_codelet_body rule-scout` | one line: `any(not l ...)` instead of `any(l is None ...)`, because `letter_node` returns a falsy token, never `None` |
| `set_codelet_body answer-finder` | waits until every Letter is perceived; no longer refuses an answer Episodic Memory already holds |
| `set_codelet_body bottom-up-bond-scout` | where the Standard body fizzles at `no-bond-between-descriptors`, it proposes a bond of the category bound to `bond_category.adjacent` (and still fizzles if that role is absent). The facet choice, the direction rule and the incompatible-candidates check are the Standard's. Bonds only: both group scouts fizzle on an `adjacent` bond at their `grp_cat is None` check, because `plato-adjacent` has no group category |

What a run proposes reaches the session's configuration through the in-worker learner (source `learner`, actor `learner:in-worker`,
`rebase` and `skip`, one op per row): a node made with `apply_ops` (one `add_node` row per symbol) and every op a body records with
`propose_ops` (see below). In the v2.0 Base those are the node and its trigger (`symbol-builder`) and what `consolidator` proposes.
A second run's identical `add_trigger` is skipped cleanly: it applies nothing, and the rule's list and `top_down_slipnodes` keep one entry each.

## `consolidator`

One run is one noticing of the node that triggered it. In order:
1. It finds the node's occurrences: `Letter` objects anywhere in the Workspace whose letter-category description is the node. **With
   none, it fizzles and proposes nothing**: a node raised past the gate only by spreading activation is primed, not noticed.
2. It proposes `adjust` of the node's `noticings` by 1.
3. For each built bond whose category is `bond_category.adjacent`, whose two ends are both `Letter` objects with a letter-category
   description, and one of whose ends is an occurrence of the node, it proposes the pair-link ops below (the Workspace's own order, no
   random number). The link goes from the left end's node to the right end's, labelled by `plato-adjacent`. A bond with a group at either end,
   a bond whose end has no letter-category description, and a bond of a symbol to itself (which cannot be an `adjacent` bond, because the
   same node gives a `sameness` bond) propose nothing. A pair is noticed from either end, and a pair seen twice in the Workspace counts twice.
4. If `noticings(node)` (the count as the run started) is at least `consolidation_threshold`, it proposes the node's `category` link to
   the letter category and the letter category's `instance` link to the node, each only if the run's Slipnet lacks it, fixed length,
   `symbol_category_link_length` and `symbol_instance_link_length`. The seed's letters have both, so nothing is proposed for them.

Nothing else is written: no `successor` link, no group, no change of depth, no other link type. Everything goes through `propose_ops`,
so nothing changes in the run, and every effect acts from the next run. The body reads its numbers from the five parameters, reaches
nodes through roles and spells only the Base's own link types and rule key.

## What a body can propose and read

Two builtins, both for a body in a Training Mode Session; under the Metacat Standard Configuration no body names them.

- `propose_ops(ops)` records change-API op dicts in the run's `proposals`, the list `apply_ops` writes, in call order, and
  changes nothing in the run (not the Slipnet, not the metadata view, not the Workspace). What it records reaches the
  session's configuration when the run ends, so it acts from the next run. It refuses `add_node` (that goes through
  `apply_ops`); any other op is data, and the change API checks it when the learner submits it. Within one run an identical op
  is recorded once, and repeated `adjust` ops on the same target are one op, kept where the first one was, with their `by`
  values added. "The same target" is the same `table`, `field` and `key` (a NULL key part, such as a link's missing label, is
  read as `""`).
- `noticings(node)` reads the whole number in `slipnet_node_defs.noticings` as the configuration held it when the run started
  (0 for a node the run made). A count the run proposes does not change what the run reads.

**A noticing of a pair of symbols** is the same two ops every time, so that every noticing counts from the first one, in any
number of runs, in any order: `add_link` of the pair's `adjacent` link at length `L + s`, and `adjust` of that link's length
by `-s` (`L` = `adjacent_link_length` 90 and `s` = `adjacent_link_step` 0.125). Within a run
the identical `add_link` is recorded once and the `adjust` ops add up to `-s * n`. Across runs the first run's `add_link`
creates the link, the others' are skipped as duplicates, and every `adjust` applies, so after `N` noticings the link is
`L - s * (N - 1)` long: 90 after the first. A link length can be a fraction (89.875) and a whole one stays an `int`, so a
configuration's hash and JSON print `90`, never `90.0`.

On a letter problem the v2.0 Base is no longer the Standard run for run: two neighbours with no link between them (`a` and
`c`) can now bond. An `adjacent` bond is weak (see the intrinsic link length above), so few are built.

Not yet here: `slipnet_rounds_to_whole`, an `adjacent` group category, a floor on a link's length (a pair's link length has none: after enough
noticings it is zero and then negative; the association read from any length is clipped to 0 to 100, so a length of 0 or less reads as 100 and one of 100 or more as 0, and the stored length stays as it is), anything for an `adjacent` bond with a group at an end, multi-turn runs.
