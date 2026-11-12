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
| `add_param new_node_conceptual_depth` 10 | the depth a node made for a new symbol starts at (letters are 10) |
| `add_codelet_type symbol-scout` | family `description`, phase `scout`: finds a Letter object with no letter-category description |
| `add_codelet_type symbol-builder` | family `description`, phase `builder`: makes node `plato-cp-<hex code point>` (connected to nothing) with `apply_ops` |
| `add_posting_rule symbol-scout` | bottom-up, after `breaker`, urgency `low`, probability `1.0`, count 1, condition `num_unperceived_symbols > 0`; it draws no random number when every symbol is perceived |
| `set_codelet_body rule-scout` | one line: `any(not l ...)` instead of `any(l is None ...)`, because `letter_node` returns a falsy token, never `None` |
| `set_codelet_body answer-finder` | waits until every Letter is perceived; no longer refuses an answer Episodic Memory already holds |

A node made inside a run reaches the session's configuration through the in-worker learner (source `learner`, actor
`learner:in-worker`), one `add_node` row per symbol. Not yet here: `adjacent`, `noticings`, `consolidator`,
`slipnet_rounds_to_whole`, multi-turn runs.
