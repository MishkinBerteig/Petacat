# Lockstep harness — decisions and interface contract

This file records the answers to the open questions in `meta-peta-trace-idea.md`
§12 and the interface details every part of the harness must agree on.  The spec
(`meta-peta-trace-idea.md`, repository root) is the design; where this file and the
spec differ, this file wins.

## Answers to the spec's open questions (§12)

1. **Reference.** Metacat 1.2 plus both bundle patches (`Metacat/patches/0001`,
   `0002`), reconstructed with `Metacat/tools/reconstruct.py` into
   `Metacat/build/source` (git-ignored) and run in the `metacat:1.2` image built
   from `Metacat/build/source/docker`.  The recorder patch is applied to a *copy*
   (`Metacat/build/recorder-source`), never to `build/source`.  Since 2026-10-28 the
   bundle also has a second, optional patch group, the known-failure fixes
   (`Metacat/patches/fixes/`).  It changes no recorded run except the three crash
   seeds, so traces recorded with and without it are interchangeable.  The recorder
   notes which it used in the header's `revision` (`metacat/README.md`, "Which
   Metacat").
2. **`~`.** Petacat changes.  Metacat redefines `round` to return exact integers
   (`utilities.ss:238-252`), so every `~` delta is a whole number drawn from
   `0 .. round(sqrt n)`.  `RNG.perturb` is fixed and `tests/unit/test_rng.py`
   updated with it.
3. **Switches.** Port bugs are fixed in the engine (defaults change).  A
   *deliberate*, documented Petacat deviation gets a parameter whose faithful
   value reproduces Metacat, and the faithful-mode settings set it; the default
   stays as it is unless the deviation turns out to be a port bug.
4. **Order-only differences.** Left alone; the harness absorbs them.
5. **Scout scope.** Decided by triage when the trace reaches it.  If Metacat's
   behaviour is the cognitive model's behaviour and Petacat's is an accident, fix
   Petacat.
6. **Engine seam.** Accepted.  `init_mcat` gains an optional `rng` argument and the
   engine gets a small, documented trace seam (unit context, phase names, `about`,
   composite codelet choice).  The base `RNG` implements the seam methods as plain
   pass-throughs so ordinary runs draw exactly as before.  Documented size figures
   (`tests/integration/test_documented_code_shape.py`, `PHASE 0 PLAN.md`) are
   updated in the same change.
7. **Corpus.** Start with `abc→abd; xyz` seeds 1–10, then the 19 demo problems.
   Traces are committed gzipped under `tests/lockstep/traces/` if a capped run is
   small enough; otherwise capped runs stay out of git and only the end records are
   kept.
8. **Runtime.** Chez 9.5.4 under amd64 emulation (Rosetta) is accepted.

## Interface contract (both recorders, replayer and comparer)

* **Files.** `<dir>/<problem-slug>/<seed>.<engine>.jsonl[.gz]`, problem slug
  `abc-abd-xyz` (the three strings joined by `-`).  Readers accept gzipped or plain.
* **Records.** Exactly as spec §3: `header`, `decision`, `snapshot`, `end`.
  Every record is one JSON object on one line with a `t` field.
* **Petacat replay additions.** Every Petacat `decision` record written during
  replay carries `pair`: the 0-based index of the Metacat record it was paired with
  (index into the Metacat trace's `decision` records, counting from 0 in file
  order), or `null` when it was surplus.  The comparer uses `pair` as the
  authority on pairing; it never re-pairs, and it is the single place every check
  class of spec §7.3 is computed.  When replay hits a fatal failure (spec §7.3:
  `unit`, `missing-pick`) it writes a final `{"t":"fatal","class":...,"c":...,
  "detail":...}` record, then an `end` record with `reason` `"fatal"`, and stops.
  A `choose` decision's `who` is `coderack`; an eviction's `who` is the phase or
  codelet it happens in (its `ctx` is unchanged) and its `site` says `evict`.
* **Numbers.** Weights and probabilities are JSON numbers converted to float
  (`exact->inexact` in Scheme).  Python writes `repr(float)`; Chez writes
  `number->string` of a flonum.  Both are shortest round-trip.
* **Canonical names** (spec §4), with these clarifications:
  * Slipnet nodes: the node name without `plato-` (`successor`, `a`,
    `letter-category`, `rightmost`).
  * Roles: `i` initial, `m` modified, `t` target, `a` answer.
  * Letters `i.0` (0-based left position).  Groups
    `group(i.0-2,successor-group,right,letter-category)`; `-` for no direction.
  * An option that is itself a list/tuple of things is written
    `(name1,name2,...)` — no spaces.
  * Numbers by value (`3`, `0.5`), booleans `true`/`false`, symbols as written.
  * Codelets: `<metacat-codelet-type-name>(<argument-name>)`, or just the type name
    when it has no argument.  Metacat's names are canonical; Petacat maps to them.
  * Anything a recorder cannot name yet is written `?<kind>:<repr>` so it shows up
    in reports instead of crashing the run.
* **Unit context.** `c`, `ctx`, `who`, `u`, `n`, `about` exactly as spec §3.
  Update-cycle phase names exactly as spec §5.4.
* **Trivial decisions** (spec §7.1) are not logged by either recorder and consume
  no record in replay.

## Metacat recorder notes

Conventions chosen by the Metacat recorder (`tests/lockstep/metacat/`; details and the full
naming table in its `README.md`):

* `end` carries `c` (the codelet that ended the run: inside codelet `codelets + 1` for
  `answer`/`give-up`/`error`, codelet `codelets` for `cap`) and `codelets` (Metacat's
  `*codelet-count*`, the number the published support-v1a data reports).
* Group categories and other slipnet nodes use the plain node name (`predgrp`, `succgrp`,
  `samegrp`); a rule is `rule(top,<clause list printed as an s-expression>)` with the list
  parentheses present; a theme cluster is `cluster(<type>,<dimension>)`.
* `stochastic-select` options are named after the object (second element of each entry).
* `about`: bond/group for density walks, the node for slipnet coins, the theme for theme
  coins, `<type>` or `<type>(<node>)` (e.g. `top-down-bond-scout:category(successor)`) for
  posting coins and `~`.  Top-down scouts add a `scope` field (not compared).
* Update-cycle `u` counts every `update-everything` call, including those inside codelets;
  the interrupted codelet's unit (and its `n`) resumes afterwards.
* Snapshots: `temperature`, `slipnet` `{node:[activation,frozen]}`, `themes` `{name:activation}`,
  `coderack` `{codelets:[[name,bin,stamp]...],clamped:[...]}`, `structures`
  `{bonds,groups,bridges,rules,descriptions:[[name,strength]...],proposed:{bonds,groups,bridges:[name...]}}`,
  `trace` `{events:{type:count},snag,clamp}`.
* Chez 9.5.4 does not evaluate arguments or `map` left to right (3,1,2; swapped pairs from the
  right); Metacat traces therefore have that draw order inside such expressions.
* Published-data seeds for `abc abd xyz` are 10600000-10600249 (construction), 20600000-
  (validation) and 30600000- (port), not 1-10.

## Decisions taken during the lockstep pass (2026-10-27/28)

* **Survival coins ask Metacat's question.** Rather than registering DISC5 A-4's
  complemented coins, every Petacat site that tested the opposite half of a
  `(stochastic-if* (1- p) (fizzle))` coin now asks `prob(1 - p)` and fizzles on true. The
  distribution is unchanged and replay pairs the coin directly. The registry keeps no
  A-4 entries.
* **Composite codelet choices carry more than name and stamp.** A clamp restamps the
  codelets it moves to another bin, and an unclamp restores each codelet's original
  urgency, so name and stamp alone don't identify a codelet. Both recorders log
  `picked_weight`, `picked_urgency`, `picked_original_urgency` and, for top-down scouts,
  `picked_scope`. Replay matches on those in that order.
* **A scout's scope is not part of its codelet name**, as in Metacat's recorder. It is
  logged as `scope` and `picked_scope`.
* **Proposed structures in Petacat's snapshots** are the unbuilt structures carried by
  the codelets on the rack. Petacat keeps no proposed tables, and Metacat's tables are
  read only by its graphics.
* **Trace event types** are compared under Metacat's seven names. Petacat's engine-facing
  Trace already held exactly those events.
* **Corpus storage.** Only the `abc-abd-xyz` development traces and the six
  known-failure traces are committed. The rest regenerate with `metacat/record.py`.
* **Ratchet.** More unregistered errors count as a step back only when reach did not
  grow, because a trace that replays further meets decisions it never reached before.
* **Metacat's known failures.** The verified reference reconstruction behind the
  published studies is not changed, and plain `reconstruct.py --verify` still means it.
  The three crashes are diagnosed.  Their fix is the bundle's second patch group
  (`Metacat/patches/fixes/0001-known-failures.patch`, checksummed in
  `Metacat/manifest.json`), applied with `reconstruct.py --apply-fixes` or `--fixes`.  It
  is applied to the local `Metacat/build/source`.  Every other recorded run (655 across
  the development, held-out and justify corpora) gives a byte-identical trace with and
  without it.  Petacat follows Metacat to each crash point and behaves as the fixed
  Metacat past it.  The registry marks the three as reference crashes.
* **Seam test pins.** `test_seam.py`'s four ordinary runs were measured before and after
  the seam was added and matched exactly. Since then they have been re-pinned with each
  port fix, so they now guard the seam against later change.
* **Episodes** use seed `S + k - 1` for run k, as `studies/episodic-v2` does. **Justify
  mode** sets `%justify-mode%` in the driver, as Metacat's GUI does (`gui.ss:752`).
