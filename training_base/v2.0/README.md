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

1. A symbol with no Slipnet node gets one in the run (`novel-string-scout`, `node-instantiator`, `new_node_conceptual_depth`, the `rule-scout` and `answer-finder` overrides).
2. Link types a configuration creates, and `adjacent` (the link type, `plato-adjacent`, the `bottom-up-bond-scout` override).
3. A session keeps what it saw side by side: `propose_ops`, `noticings`, fractional link lengths, `plato-adjacent` at depth 45 (stage A); `consolidator`, its rule, its triggers and its five parameters (stage B); the association read from a link length clipped to 0 to 100 (stage C); a pair's `adjacent` link that approaches 0 asymptotically, through the change API's multiplying op `scale` (stage D).
4. In-run building (stage A): `apply_ops` builds links in the run's own Slipnet (`add_link`, `scale` and `adjust` of a link's length); a body proposes a change to the run's Slipnet for an instantiator (`propose_ops(ops, built_by=..., urgency=...)`, `take_proposed_ops`); `consolidator` proposes and three new codelet types build: `adjacent-instantiator`, `category-instantiator` and `instance-of-instantiator`; `symbol-scout` is renamed `novel-string-scout` and `symbol-builder` `node-instantiator`, with their behaviour unchanged.

## What v2.0 adds so far

| Op | What it does |
|---|---|
| `add_link_type adjacent` (behaviour `lateral`) | the delta's first op. A link type this configuration owns: two symbols seen side by side. `consolidator` proposes the links of this type and `adjacent-instantiator` builds them: one for each pair of single symbols that an `adjacent` bond joined |
| `add_node plato-adjacent` | an instance of `bond-category`, beside `plato-successor` and `plato-sameness`; short name `adjacent`. Its `category` and `instance` links to `bond-category` have the lengths `plato-successor`'s have (30 and 100). Conceptual depth 45, just below `plato-successor`'s and `plato-predecessor`'s 50, because adjacency is the lowest-depth link concept (the user, 2026-11-14). No other property is set. Bound to the role `bond_category.adjacent`, and placed at grid (1, 13) in the layout |
| `update engine_params intrinsic_link_lengths` | adds `plato-adjacent` 90. A long length makes an `adjacent` bond weak (association about 10 against `successor`'s 40); a fully active category shrinks it |
| `insert theme_relations adjacent` | names `plato-adjacent`, so a rule can name the relation. No `valid_relations` list of a theme dimension has it yet |
| `add_param new_node_conceptual_depth` 10 | the depth a node made for a new symbol starts at (letters are 10) |
| `add_codelet_type novel-string-scout` | family `description`, phase `scout`: finds a Letter object with no letter-category description |
| `add_codelet_type node-instantiator` | family `description`, phase `builder`: makes node `plato-cp-<hex code point>` (connected to nothing) with `apply_ops`, and proposes it as a trigger of `consolidator`'s rule (`add_trigger`, so it acts from the next turn) |
| `add_param consolidation_threshold` 40, `adjacent_link_length` 90, `adjacent_link_step` 0.0625, `symbol_category_link_length` 20, `symbol_instance_link_length` 97 | the five numbers only the `consolidator` body reads (engine parameters have no description column, so they are described here). The threshold is in noticings; the two lengths are the ones the seed's letters have for `category` and `instance`; the length and step are the pair's `adjacent` link (below): the step is the size of its first step, at the length, and each later step is in proportion to the length left. The step, 1/16, is exact in binary |
| `add_codelet_type consolidator` | family `meta`, phase `other`, top-down. One run is one noticing of the node in `args['slipnode']` (see below) |
| `add_codelet_type adjacent-instantiator`, `category-instantiator`, `instance-of-instantiator` | family `meta`, phase `builder`, no posting rule: posted only by `consolidator`, one for each link it proposes (see below). Each takes what is held for its link and builds it in the run if the evidence still holds |
| `add_posting_rule novel-string-scout` | bottom-up, after `breaker`, urgency `low`, probability `1.0`, count 1, condition `num_unperceived_symbols > 0`; it draws no random number when every symbol is perceived |
| `add_posting_rule consolidator` + 26 `add_trigger` | top-down, in Metacat's own top-down form (the strings `top-down-description-scout` has): urgency `conceptual_depth * activation / 100`, posting probability `average_unhappiness / 100`, count 1, condition `always`: when a trigger node's activation passes the gate (50) it posts with that probability, so a noticing is more likely the less happy the run is. Its triggering list is the 26 letters (`add_trigger` also adds them to `top_down_slipnodes`; each seed top-down rule names its own triggers, so none of them fires for a letter), and `node-instantiator` adds each new node. A rule with an empty triggering list would fire for every node in `top_down_slipnodes`, so the rule has none |
| `set_codelet_body rule-scout` | one line: `any(not l ...)` instead of `any(l is None ...)`, because `letter_node` returns a falsy token, never `None` |
| `set_codelet_body answer-finder` | waits until every Letter is perceived; no longer refuses an answer Episodic Memory already holds |
| `set_codelet_body bottom-up-bond-scout` | where the Standard body fizzles at `no-bond-between-descriptors`, it proposes a bond of the category bound to `bond_category.adjacent` (and still fizzles if that role is absent). The facet choice, the direction rule and the incompatible-candidates check are the Standard's. Bonds only: both group scouts fizzle on an `adjacent` bond at their `grp_cat is None` check, because `plato-adjacent` has no group category |

What a run proposes reaches the session's configuration through the in-worker learner (source `learner`, actor `learner:in-worker`,
`rebase` and `skip`, one op per row): a node made with `apply_ops` (one `add_node` row per symbol) and every op a body records with
`propose_ops` (see below). In the v2.0 Base those are the node and its trigger (`node-instantiator`), what `consolidator` proposes for the next turn (the count), and the links the three instantiators built in the run.
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

Nothing else is written: no `successor` link, no group, no change of depth, no other link type. The count goes through a plain
`propose_ops`, so it acts from the next turn. Each link change is proposed for an instantiator (`propose_ops(ops, built_by=...,
urgency=meta.get_urgency('high'))`) and is held until an instantiator builds it or the turn ends: the pair's ops
(`add_link` at `L / r` and `scale` by `r`, for each noticing) go to `adjacent-instantiator`, the `category` link to
`category-instantiator` and the `instance` link to `instance-of-instantiator`. The body reads its numbers from the five
parameters, reaches nodes through roles and spells only the Base's own link types and rule key.

## The instantiators

Each is a codelet of family `meta` and phase `builder`, written like a builder in the seed: it checks that what was noticed is
still there, and builds or fizzles. Each starts by taking everything held for its link (`take_proposed_ops(args['held'])`), draws no
random number, and builds what it took with `apply_ops`: the run's own Slipnet has the link at its new length at once, and the
changes are recorded for the session, composed as `propose_ops` composes them. A fizzle drops what it took.
- `adjacent-instantiator`: the evidence is a built `adjacent` bond in the Workspace between two single symbols whose
  letter-category descriptions are the link's `from` and `to`, `from` on the left (reading order, as `consolidator` reads it).
  The second part of the evidence is the user's rule (2026-11-16): the run's Slipnet has no other link between the two nodes, of any type, labelled or not, in either direction (a seed pair such as `a` and `b` has a `successor` link, and a symbol and the letter category have `category` and `instance` links). It applies to every build, the first and every strengthening. A pair joined only by its own `adjacent` link still builds and strengthens: the `add_link` changes nothing in the run and the `scale` shortens it.
- `category-instantiator`: the Workspace still holds the symbol (a Letter whose letter-category description is the link's
  `from`) and the run's Slipnet still lacks the link.
- `instance-of-instantiator`: the same for the letter category's link to the symbol (the symbol is the link's `to`).

`consolidator` holds at most one instantiator per link: a proposal for a link whose instantiator is on the Coderack only adds to what
is held (so noticings do not crowd the Coderack, which holds `max_coderack_size` codelets and evicts old ones when full). If that
instantiator left the Coderack without running (evicted, or flushed), the next proposal posts a new one. An instantiator is posted at
the `high` urgency level, as `node-instantiator` is (which `novel-string-scout` posts). What is still held when the turn ends is dropped:
it is not in the run's outcome and never reaches the session. The session's link after the runs is `L * r ** (B - 1)`, `B` being the
number of noticings whose changes were built (`B + start - 1` from a link that already held `start` noticings).

## What a body can propose and read

Four builtins, all for a body in a Training Mode Session; under the Metacat Standard Configuration no body names them.

- `propose_ops(ops)` records change-API op dicts in the run's `proposals`, the list `apply_ops` writes, in call order, and
  changes nothing in the run (not the Slipnet, not the metadata view, not the Workspace). What it records reaches the
  session's configuration when the run ends, so it acts from the next turn. It refuses `add_node` (that goes through
  `apply_ops`); any other op is data, and the change API checks it when the learner submits it. Within one run an identical op
  is recorded once, repeated `adjust` ops on the same target are one op, kept where the first one was, with their `by`
  values added, and repeated `scale` ops on the same target are one op in the same way, with their `factor` values multiplied
  (a `scale` never combines with an `adjust`). "The same target" is the same `table`, `field` and `key` (a NULL key part, such as a link's missing label, is
  read as `""`).
- `propose_ops(ops, built_by='<instantiator type>', urgency=<urgency>)` holds the ops of **one link** (`add_link`, and `scale` or
  `adjust` of its `link_length`) for an instantiator, composed the same way, grouped by `built_by` and the link, and posts the
  instantiator unless one for that link is waiting on the Coderack; `take_proposed_ops(args['held'])` is the instantiator's side.
  Nothing changes in the run and nothing is recorded until an instantiator builds it.
- `apply_ops(ops)` builds in the run's own Slipnet: `add_node` (a node connected to nothing), `add_link` (a link type the run's
  configuration has, between nodes the run's Slipnet has; `fixed`, and a finite `length` when fixed; no `label`, or a node's name)
  and `scale` or `adjust` of a link's `link_length` (`key` `{from_node, to_node, link_type, label_node}`). All of a call is checked
  before any is applied; anything else is refused by name. A link built in the run is in its behaviour list, its target's incoming
  links, `links_of`, category membership, `get_related_node` and slippage reads, the alphabet's first and last letter and the numeric
  layout (every backend) at once. It records what it applied in `proposals`, composed as `propose_ops` composes.
- `noticings(node)` reads the whole number in `slipnet_node_defs.noticings` as the configuration held it when the run started
  (0 for a node the run made). A count the run proposes does not change what the run reads.

**A noticing of a pair of symbols** is the same two ops every time, so that every noticing counts from the first one, in any
number of runs, in any order. With `L` = `adjacent_link_length` 90 and `s` = `adjacent_link_step` 1/16, the body works out
`r = 1 - s / L` and proposes `add_link` of the pair's `adjacent` link at length `L / r` and `scale` of that link's length by `r`
(the change API's multiplying op: `{'op': 'scale', 'table', 'key', 'field', 'factor'}`, addressed as `adjust` is; it refuses
a field that is not a number, a factor or a result that is not finite, and a fraction in a whole-number column). Within a run
the identical `add_link` is recorded once and the `scale` factors multiply into one, `r` to the power of the number of noticings.
Across runs the first run's `add_link` creates the link, the others' are skipped as duplicates, and every `scale` applies. The
first noticing leaves the link at `(L / r) * r`, which is exactly 90 for these values (a whole number, stored as an `int`);
after that each noticing multiplies it by `r`, so after `N` noticings the link is `L * r ** (N - 1)` long: its first step is
`s` (90 to 89.9375) and the steps shrink in proportion to the length. The length approaches 0 and never reaches it (after 50
runs of `123->123; 123->?`, about 100 noticings of each pair per run, it is still positive). A multiplication is used instead
of an `adjust` of a value worked out from the length a run saw, because the runs of a swarm start under one configuration, and
such an `adjust` would overshoot; factors commute, so the runs compose in any order. Float multiplication in a different order
can differ in the last bits (the tests allow a relative error of 1e-12). A link length can be a fraction (89.9375) and a whole
one stays an `int`, so a configuration's hash and JSON print `90`, never `90.0`.

On a context-response analogy problem made of letters the v2.0 Base is no longer the Standard run for run: two neighbours with no link between them (`a` and
`c`) can now bond. An `adjacent` bond is weak (see the intrinsic link length above), so few are built.

Not yet here: `slipnet_rounds_to_whole`, an `adjacent` group category, a floor on a stored link length (a pair's link has none, though
its asymptotic length does not reach 0; the association read from any length is clipped to 0 to 100, so a length of 0 or less reads as 100 and one of 100 or more as 0, and the stored length stays as it is), anything for an `adjacent` bond with a group at an end, multi-turn runs, a held proposal for a node (only links are held), and the speculative executor's support for links and nodes built in a run (`apply_ops` is a BARRIER there).
