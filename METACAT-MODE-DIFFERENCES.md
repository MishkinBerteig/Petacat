# Where Metacat Mode deliberately differs from patched Metacat

[`THE-THREE-SYSTEMS.md`](THE-THREE-SYSTEMS.md) says that Metacat Mode is a 100% faithful port of patched Metacat.
This file lists the places where it is not, on purpose. Each entry is a difference that the user looked at on
2026-11-08 and accepted. It says what patched Metacat does, what Metacat Mode does, whether the difference can change
anything a person or a test sees, and why it is accepted. Metacat's side is `Metacat/build/source`, the patched
build. A difference that is a bug, or that someone means to remove, does not belong here. It is fixed instead.

**The fidelity checks are not affected.** The ratchets (`tests/lockstep/ratchet*.json`) replay what patched Metacat
recorded and check, at each random decision it logged, that Petacat had the same options with the same weights or
probabilities. The recorder does not log a trivial decision: a coin whose probability is 0 or 1, a choice with fewer
than two options left after the zero weights are dropped, a draw with a bound of 1
(`tests/lockstep/metacat/README.md`, "Trivial (not logged)"). The random-number entries below are all of that kind, or
are reordered draws that are logged in the order Petacat takes them. The replay also forces Metacat's choice at each
logged decision, and it matches a coderack choice or eviction by the names and weights on offer, not by their order
(`tests/lockstep/replay_rng.py`, `_decide_composite`). So none of these differences shows up in a ratchet, and
none is registered in `tests/lockstep/known_divergences.toml`, which holds nothing. The golden baselines hold
Petacat's own runs, so they contain these differences as they are and do not measure them either.

## Why none of the random-number differences changes a decision or a probability

Four of the entries (the posting coin, the sole neighbour, the three smaller skipped draws, and the eviction walk)
are about random numbers: Petacat takes a different number of them, or takes them in a different order, or applies
them to a differently ordered list. The same reasoning covers every one:

- **Each random number is independent of the others.** A draw is a fresh uniform number. Skipping a draw whose result
  cannot matter, or taking two independent draws in the other order, leaves the probability of every decision as it
  was.
- **Metacat and Petacat use different random generators anyway.** Metacat uses Chez Scheme's `random` and Petacat uses
  Python's. Even with the same seed the two programs would not see the same numbers, so the exact stream is not
  something Petacat could share with Metacat.
- **The user ruled out same-seed runs against Metacat** (2026-11-08). Nothing compares a Metacat run with a Petacat run
  of the same seed number, so a different count of draws cannot be seen as a difference between two runs.

This was checked on each row below on 2026-11-08. In none of them does the skipped or reordered draw change a decision or a
probability. Each one is skipped only where the decision it would have made is certain, or reordered only where the
numbers are independent. A decision that is certain is a probability of exactly 0 or 1: Scheme's `(random 1.0)` lies in
[0, 1), so a coin with probability 1 is always true and one with probability 0 is always false.

## 1. The posting coin is not drawn when the probability is 0 or 1

**Patched Metacat.** `stochastic-if*` binds its coin before it looks at the probability
(`syntactic-sugar.ss:137-142`: `(let ((coin-flip (random 1.0))) (if (< coin-flip (prob-thunk)) ...))`), so it
draws every time, whatever the probability. Codelet posting uses it at every type
(`add-top-down-codelets` and `add-bottom-up-codelets`, `coderack.ss:552-572`), and so do about 30 sites in 13 files
in all (`tests/lockstep/metacat/README.md`). `prob?` is a different primitive: it returns `#f` for `p <= 0.0` and
`#t` for `p >= 1.0` without drawing (`utilities.ss:461-466`).

**Metacat Mode.** `RNG.prob` (`server/engine/rng.py:97-103`) is a port of `prob?`, and it is what the posting code
calls at every place the Scheme writes `stochastic-if*` (`server/engine/runner.py:1257` for bottom-up codelets,
`:1300` for the thematic one). It does not draw when `p` is 0 or 1. Metacat Mode also does not evaluate a posting
rule at all when the rule's `condition` is false (`_rule_condition_holds`, `runner.py:1217-1227`, called at `:1252`
and `:1294`), where Metacat reaches `stochastic-if*` and draws.

**Can anyone see it?** No. `post-codelet-probability` (`coderack.ss:465-512`) returns exactly 1 for `rule-scout`
whenever a rule type is possible and for `progress-watcher` under thematic pressure, and exactly 0 for
`answer-finder` before a supported top rule exists, for `answer-justifier` outside justify mode, for
`thematic-bridge-scout` with no active theme, and for the three self-watching types when Self-watching is off. At 0
the coin is always false and at 1 always true, so skipping the number cannot change the decision. The posting rules
whose `condition` is not `always` in `seed_data/posting_rules.json` are `answer-finder` (`not justify_mode`),
`answer-justifier` (`justify_mode`), and `thematic-bridge-scout`, `progress-watcher` and `jootser`
(`self_watching_enabled`). Each is exactly a case where `post-codelet-probability` returns 0 at `coderack.ss:466-472`
(`*self-watching-codelet-types*` is those three, `coderack.ss:648-652`), so the skipped evaluation also had a
certain outcome.

**Why it is accepted.** It saves a draw at the most frequent site in the program, with the same decisions. The
random-number reasoning at the top of this file applies.

## 2. A lone neighbour is returned without a draw

**Patched Metacat.** `stochastic-pick` draws in both of its branches: `(random (exact->inexact weight-sum))` when the
weight is not 0, and `random-pick`'s `(random (length l))` when it is 0 (`utilities.ss:485-490` and `:475-479`). A
one-element list still costs one draw. The local-density walk calls it through `choose-neighbor`,
`choose-left-neighbor` and `choose-right-neighbor` (`workspace-objects.ss:403-423`), inside every strength update.

**Metacat Mode.** `WorkspaceObject._pick_neighbor` (`server/engine/workspace_objects.py:182`) returns
`neighbors[0]` when there is one candidate (`:214`) without drawing, and its docstring says so. In a string with no
groups every edge letter offers exactly one neighbour on the walked side, so this is the commonest skipped draw.

**Can anyone see it?** No. The element returned is the same; only the draw is skipped, and a draw over one
candidate has one possible result.

**Why it is accepted.** Same reasoning as above: the draw cannot change which neighbour is chosen, and the exact
stream is not shared with Metacat. The lockstep recorder does not log a choice with fewer than two options.

## 3. Three smaller skipped or reordered draws

**An empty list of concept mappings in the bridge scouts.**
- *Patched Metacat:* the bottom-up and the important-object bridge scouts compute
  `(stochastic-if* (product (map 1- slippabilities)) ... (fizzle))` (`bridges.ss:935` and `:1029`). With no concept
  mappings `(product '())` is 1, so the coin is drawn, is always true, and the scout fizzles.
- *Metacat Mode:* the `bottom-up-bridge-scout` and `important-object-bridge-scout` bodies in
  `seed_data/codelet_types.json` run `if not cms: fizzle()` before the slippage gate, so the scout fizzles with no
  draw.
- *Effect:* one draw skipped, with the same outcome (a fizzle).

**`num_bonds_to_scan` for a string of fewer than two letters.**
- *Patched Metacat:* `bond-scan-distribution` (`workspace-strings.ss:56-59`, read by `get-num-of-bonds-to-scan`
  at `:117`) is a `make-probability-distribution` over `(ascending-index-list n)` weighted by squares
  (`constants.ss:1045-1051`). For one letter the list is `(0)` with weight 0, so `stochastic-pick` falls back to
  `random-pick` and draws once to choose the only value, 0.
- *Metacat Mode:* `num_bonds_to_scan` (`server/engine/codelet_dsl/builtins.py:553`) returns 0 for `n < 2`
  (`:566-567`), without drawing.
- *Effect:* one draw skipped, with the same value, 0. It happens only for one-letter strings.

**The singleton-group gate draws its coin and its probability in the other order.**
- *Patched Metacat:* `(stochastic-if* (1- (single-letter-group-probability singleton-group)) ... (fizzle))`
  (`groups.ss:488-490`) binds the coin first, and the probability expression then walks the local density, which
  draws.
- *Metacat Mode:* the `top-down-group-scout:category` body in `seed_data/codelet_types.json` evaluates
  `single_letter_group_probability(singleton)` first, and then draws the coin in `prob(1.0 - ...)`.
- *Effect:* the same draws in the other order. They are independent uniform numbers, so the joint distribution of
  the decision is the same. The recorder logs the coin after the probability has been computed
  (`tests/lockstep/metacat/README.md`, "Coin drawn first as before, then `p`, then `trace-hook-if`"), so the logged
  order is the order Petacat takes, and the replay pairs them directly.

**Why these are accepted.** Same reasoning as above. In the first two rows the decision is certain, so the draw
Petacat skips has one possible result. In the third the order of two independent numbers does not matter.

## 4. The eviction walk and the re-filing walk go bin by bin

**Patched Metacat.** `delete-codelets` is `(stochastic-pick-by-method codelet-list 'get-removal-weight)`
(`coderack.ss:435-445`), and `set-urgencies` and `reset-urgencies` walk the same list (`:447-456`).
`codelet-list` is built with `cons` (`:405` and `:414`), so the newest posted codelet is first.

**Metacat Mode.** `Coderack._pick_codelet_to_remove` (`server/engine/coderack.py:585`) finds the bin from the
bins' weight totals and walks one bin only. `_move_urgencies` (`:704`) re-files in bin order. The tests that pin
the form are in `tests/seed_unit/test_coderack_eviction.py`, which checks the incremental search against a brute-force
walk over the bin-major list.

**Can anyone see it?** Not in a probability. Each codelet is evicted with probability equal to its removal weight
over the total, in both programs, and it takes one draw in both. What differs is only which codelet one particular
draw names. Re-filing in a different order leaves the same codelets in the same bins with the same time stamps
(`_move_urgencies` restamps them all alike), and the later random choice inside a bin is uniform, so its order does not
matter either. In a replay Metacat's choice is forced and matched by name and weights, so the recorded corpora cannot
show the difference.

**Why it is accepted.** Matching Metacat's walk would put the O(n) scan over the global codelet list back. The
comment at `coderack.py:551` records that the scan was 35.8% of a run on `abc -> abd; mrrjjj?`. The random-number
reasoning at the top of this file applies.

## 5. Link buckets are appended; the Scheme builds them with `cons`

**Patched Metacat.** `add-to-outgoing-links` and `add-to-incoming-links` put each new link on the front of its
node's list (`slipnet.ss:225-237`), so a node's `category-links`, `instance-links`, `property-links`,
`lateral-links`, `lateral-sliplinks` and `incoming-links` are newest first.

**Metacat Mode.** The Slipnet builder appends each link to the end of the same six lists
(`server/engine/slipnet.py:1070-1080`), so they are oldest first.

**Can anyone see it?** Not with the Metacat Standard Configuration's links. Every reader of these lists in the Scheme
either picks the first link that matches a test that only one link in the list can pass, or weighs the candidates by
a value of each candidate, which moves the draw's index but not any candidate's probability. The 202 links of
`seed_data/slipnet_links.json` were checked on 2026-11-08: no node has two category links (`get-category`, `slipnet.ss:96-99`, and
`slipnet.ss:691` and `:705` take the first), no node has two links of one type with the same label, and no pair of
nodes is joined by two links (`get-label`, `slipnet.ss:287-296`, takes the first incoming link from a given node;
`get-related-node`, `slipnet.ss:114-129`, filters by label). The weighted readers are `get-possible-descriptors`
through `stochastic-pick-by-method ... 'get-activation` (`descriptions.ss:134-136` and `themes.ss:958-960`). The
readers that only ask a yes-or-no question (`spanning-group-possible?`, `workspace.ss:664-680`) do not depend on order.
A Training Mode Session, or an edit in the Admin view, could add links that make the order matter. Metacat Mode runs
only the Metacat Standard Configuration unless someone edits the global one.

**Why it is accepted.** Nothing reads the order today, and appending is the simpler form for the database loader.

## 6. `RNG.pick` on an empty list raises

**Patched Metacat.** `random-pick` returns `#f` for an empty list (`utilities.ss:475-479`).

**Metacat Mode.** `RNG.pick` raises `ValueError("Cannot pick from empty sequence")`
(`server/engine/rng.py:105-109`). `RNG.weighted_pick` does the same (`:111-121`), and falls through to `pick`
when every weight is 0.

**Can anyone see it?** Only if a caller passes an empty list, and none does. Every call of `pick` under
`server/` and the four `rng.pick` calls in the `seed_data/codelet_types.json` bodies were checked on 2026-11-08: each is behind a test that
returns, breaks or fizzles first on an empty list (`coderack.py:433` inside `if not batch: break`; `:484` and `:493`
behind `if not non_empty: return None`; `:611` behind `if not flat: return None`;
`rules.py:3615` inside `while remaining:`; `server/parallel/speculative/clock_rack.py:347` behind
`if not non_empty: return None`; `CoderackBin.choose_random`, `coderack.py:224`, is reached only with a non-empty bin;
and in the seed bodies the `group-scout:whole-string`, `rule-scout` and `breaker` picks follow `if not bonds ...:
fizzle()`, `no-rule-possible: fizzle()` and `if not structures: fizzle()`). The callers of `weighted_pick`
have not been checked the same way.

**Why it is accepted.** An unguarded empty pick would be a bug that should stop loudly, and there are no such
callers. Returning `#f` would hide one.

## 7. Theme-edit mode: the first click claims the window and selects the theme

**Patched Metacat.** In theme-edit mode the first click in a theme window only claims the theme type, which zeroes
the window. The next click selects a theme (`theme-graphics.ss:35-63`, with `ready-to-edit?` and `edit-theme-type` at
`gui.ss:837-843`).

**Metacat Mode.** The first click claims the type and selects the theme in one gesture
(`client/src/components/ThemespaceView.tsx:533-548`, `handleEditClick`).

**Can anyone see it?** Yes, in the interface: one click fewer. It changes no engine behaviour and no clamp that is
finally sent.

**Why it is accepted.** A click that does nothing visible has no use on a pointer-less trackpad.

## 8. Theme-edit mode is a view in the browser

**Patched Metacat.** `theme-edit-mode-on` saves the three Themespace states and deletes the themes while the dialog
is open (`gui.ss:850-870`), and `theme-edit-mode-off` restores the types that were not edited (`gui.ss:906-920`).

**Metacat Mode.** The run's Themespace is left alone. The client shows the user's selection over a blank Themespace
(`ThemespaceView.tsx`, `editView`, `:571-` to the end of the function), and nothing is sent until Clamp Themes
(`handleEditClick` and the clamp handler above it).

**Can anyone see it?** In the interface only. The clamp that results is the same one. Cancel cannot lose state, and a
run that keeps going while the dialog is open is not disturbed.

**Why it is accepted.** The state is kept in the browser, which is safer when a run is also being driven elsewhere.

## 9. Petacat explains a single answer; Metacat's `explain` is never called

**Patched Metacat.** `explain` (`answers.ss:310-333`) would write one answer's explanation into the commentary
window. Nothing calls it: `explain` occurs nowhere else in the Scheme source. What Metacat does reach from its
memory window is the comparison of two answers, which writes "Let's see..." and the comparison
(`memory-graphics.ss:50-65`).

**Metacat Mode.** The Memory panel explains a single answer (`client/src/components/MemoryView.tsx:172-190`, using
`explainAnswer` in `client/src/api/client.ts:629`). The comparison of two answers is ported and matches Metacat.

**Can anyone see it?** Yes, as a feature that Metacat's interface does not have. It writes nothing that Metacat does
write, and it changes no run.

**Why it is accepted.** It is an addition, not a gap, and it makes use of a procedure the original author wrote.

## 10. Verbose mode (the narration port)

Verbose mode (`%verbose%`, `gui.ss:664`) is ported in `server/engine/verbose.py`. The message texts are
`verbose_messages` in `seed_data/commentary_templates.json`. It was checked against Metacat by running it with
`%verbose%` on (`tests/lockstep/metacat/record_verbose.py`) and replaying the same recorded runs in Petacat
(`scripts/compare_verbose.py`). Narration only reads, so none of the entries below changes a run. They change only
what is printed.

### 10a. The headless forms

Patched Metacat prints a structure's level as `(~a, not drawn)` when `%workspace-graphics%` is on and the structure
has not been drawn (`bridges.ss:87`, `:106`, `:465`, `:486`; `descriptions.ss:40`; `workspace-objects.ss:108`), and a
vertical bridge gets a `(#n)` label when graphics are on (`bridges.ss:471-472`). The recorded Metacat runs with
graphics off, so a structure prints `(proposed)` and never `(proposed, not drawn)`, and a vertical bridge has no label.
Metacat Mode has no drawn state and prints the same headless forms (`server/engine/verbose.py:37-38`).

### 10b. Step mode

Patched Metacat leaves step mode on until Go and forces `%verbose%` on while the step interval is 10 or less
(`run.ss:44-47`, `set-verbose-step-mode` at `gui.ss:793-795`). Requests to Petacat are stateless, so
`POST /step` with `step_mode: true` (the Step button) and `n <= 10` is narrated for that batch only
(`server/services/run_service.py:512-533`, `VERBOSE_STEP_LIMIT` at `server/engine/verbose.py:62`).

### 10c. Exact against inexact numbers

Metacat holds many rounded quantities as exact integers because it redefines `round` (`utilities.ss:250-252`), and
prints `100` for an exact integer and `100.0` for a flonum. Petacat holds the same quantities as floats.
`verbose.exact` (`server/engine/verbose.py:85`) prints an integral float as the integer where Metacat's value is exact
(rule figures, progress, overlaps, strengths and salience weights). A quantity that Metacat holds as a true ratio and
prints as `100/3` would differ. The earlier audit found none in the recorded runs; it has not been run again since.

### 10d. A translated rule prints zeros in the justifier

Metacat prints a translated rule in justify mode before it calls `set-quality-values` on it (`justify.ss:104`).
Petacat scores it at translation, so the print is made with the figures as 0 (`server/engine/justify.py:172`,
`server/engine/verbose.py:348-359`).

### 10e. "(new)" after a structure is built again

Petacat's structures have no new state, and `_retire` (`server/engine/codelet_dsl/builtins.py:2227`) resets a broken
structure's level, where Metacat's `break-bond` leaves it built (`bonds.ss:425-433`). `VerboseLog`
(`server/engine/verbose.py:483`) records what it saw built (`_built`, `:504`; `mark_built`, `:519`; `fresh`, `:522`).
A structure built before Verbose mode was switched on and then built again would print `(new)`; with Verbose mode on
from the start it matches.

### 10f. Free-running workers and a bounded buffer

Free-running workers interleave their narration. The buffer holds the last 5,000 lines (`DEFAULT_CAPACITY`,
`server/engine/verbose.py:56`); Metacat's console is unbounded. Metacat's `try-to-propose-singleton-group` message
(`bridges.ss:1431`) is dead code, never called anywhere in the Scheme source, and is not ported.

### 10g. `Codelets run: N`

Patched Metacat's `run` prints `Codelets run: N` when it reaches `*break-time*` or is interrupted
(`run.ss:157-165`). The recorder sets the break time to its codelet cap, and Petacat never says it. A run that ends on
the cap therefore has one line of Metacat's output that Petacat does not say. This is the recording harness, not the
product.

**Why all of these are accepted.** They are display and narration only, and each is either a consequence of Petacat
having no drawing surface and no console (10a, 10b, 10f, 10g), a consequence of holding numbers as floats (10c), or a
difference in the order of two operations that print (10d, 10e).
