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

## What v2.0 adds so far

| Op | What it does |
|---|---|
| `add_link_type adjacent` (behaviour `lateral`) | the delta's first op. A link type this configuration owns: two symbols seen side by side. Nothing writes a link of this type yet (that is `consolidator`'s job, a later increment); the op proves the mechanism |
| `add_node plato-adjacent` | an instance of `bond-category`, beside `plato-successor` and `plato-sameness`; short name `adjacent`. Its `category` and `instance` links to `bond-category` have the lengths `plato-successor`'s have (30 and 100). Conceptual depth 45, just below `plato-successor`'s and `plato-predecessor`'s 50, because adjacency is the lowest-depth link concept (the user, 2026-11-14). No other property is set. Bound to the role `bond_category.adjacent`, and placed at grid (1, 13) in the layout |
| `update engine_params intrinsic_link_lengths` | adds `plato-adjacent` 90. A long length makes an `adjacent` bond weak (association about 10 against `successor`'s 40); a fully active category shrinks it |
| `insert theme_relations adjacent` | names `plato-adjacent`, so a rule can name the relation. No `valid_relations` list of a theme dimension has it yet |
| `add_param new_node_conceptual_depth` 10 | the depth a node made for a new symbol starts at (letters are 10) |
| `add_codelet_type symbol-scout` | family `description`, phase `scout`: finds a Letter object with no letter-category description |
| `add_codelet_type symbol-builder` | family `description`, phase `builder`: makes node `plato-cp-<hex code point>` (connected to nothing) with `apply_ops` |
| `add_posting_rule symbol-scout` | bottom-up, after `breaker`, urgency `low`, probability `1.0`, count 1, condition `num_unperceived_symbols > 0`; it draws no random number when every symbol is perceived |
| `set_codelet_body rule-scout` | one line: `any(not l ...)` instead of `any(l is None ...)`, because `letter_node` returns a falsy token, never `None` |
| `set_codelet_body answer-finder` | waits until every Letter is perceived; no longer refuses an answer Episodic Memory already holds |
| `set_codelet_body bottom-up-bond-scout` | where the Standard body fizzles at `no-bond-between-descriptors`, it proposes a bond of the category bound to `bond_category.adjacent` (and still fizzles if that role is absent). The facet choice, the direction rule and the incompatible-candidates check are the Standard's. Bonds only: both group scouts fizzle on an `adjacent` bond at their `grp_cat is None` check, because `plato-adjacent` has no group category |

What a run proposes reaches the session's configuration through the in-worker learner (source `learner`, actor
`learner:in-worker`, `rebase` and `skip`, one op per row): a node made with `apply_ops` (one `add_node` row per symbol) and,
since the third increment, every op a body records with `propose_ops` (see below). No codelet in the v2.0 Base proposes
anything but those nodes yet, so nothing writes an `adjacent` link into the Slipnet, and `ab1->ab2; cd1->?` does not give `cd2`.

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
by `-s` (`L` = `adjacent_link_length` 90 and `s` = `adjacent_link_step` 0.125 once the `consolidator` body exists). Within a run
the identical `add_link` is recorded once and the `adjust` ops add up to `-s * n`. Across runs the first run's `add_link`
creates the link, the others' are skipped as duplicates, and every `adjust` applies, so after `N` noticings the link is
`L - s * (N - 1)` long: 90 after the first. A link length can be a fraction (89.875) and a whole one stays an `int`, so a
configuration's hash and JSON print `90`, never `90.0`.

On a letter problem the v2.0 Base is no longer the Standard run for run: two neighbours with no link between them (`a` and
`c`) can now bond. An `adjacent` bond is weak (see the intrinsic link length above), so few are built.

Not yet here: `consolidator` (and with it `consolidation_threshold`, `adjacent_link_length` and `adjacent_link_step`),
`slipnet_rounds_to_whole`, an `adjacent` group category, multi-turn runs.
