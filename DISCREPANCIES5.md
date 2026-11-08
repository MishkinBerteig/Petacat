# DISCREPANCIES5 — where Petacat's source and Metacat's source still say different things

> **Status (2026-11-08).** This file keeps only the differences between Petacat's source and patched
> Metacat's source that are still present in the current code. A difference that was fixed, or whose code
> was removed, is gone from this file and is in the git history. Each entry names the Petacat site, the
> Metacat site and what diverges, with the lines of today's code. Entry IDs are kept as they were, so the
> gaps in the numbering are entries that closed. Metacat's side is `Metacat/build/source`, the patched build.
> The current description of the system is in [README.md](README.md), [TESTING.md](TESTING.md) and
> [HELP.md](HELP.md). `tests/lockstep/README.md` describes the replay that found most of these.

**What this is.** A comparison of Petacat's Python against Metacat's Scheme, function by function, for
anything that could make the two compute differently. It is a *static* comparison. It is not a measurement.

## On "inert"

Several entries describe a divergence that appears to be unreachable: a branch whose guard seems never to
hold, a value that seems always to be zero where it is used. **Those observations are conditional, and none of
them downgrades an entry.** Inertness cannot be established here. Metacat is late-bound Scheme: `round`,
`floor` and `ceiling` are *redefined* at `utilities.ss:243-252` after being captured, generic arithmetic
silently crosses between exact rationals and flonums, and `tell`-based dispatch resolves at call time. Static
analysis cannot see through that, and statistical sampling can only ever fail to reach a branch. So the standard
applied throughout is: **Petacat should replicate what the Scheme does, and carry a comment saying the branch
may be unreachable, rather than replicate a simplification that assumes it is.**

---

# A. The random stream

Metacat and Petacat use different generators, so no seeded run can be compared step-for-step regardless. What
matters in this section is whether the two consume the same *number* of draws in the same order, because when
they do not, the divergence is not a different sample from the same distribution but a different distribution.

## A-2. `stochastic-if*` always draws; `prob()` short-circuits

**Severity: medium — outcome-identical, stream-divergent, and very frequent.**

**Metacat** — `syntactic-sugar.ss:137-142`:
```scheme
(let ((prob-thunk (lambda () prob)) (exps-thunk (lambda () exp ...)))
  (let ((coin-flip (random 1.0)))
    (if (< coin-flip (prob-thunk)) (exps-thunk) (void))))
```
The draw is bound before the probability is tested, so it happens whatever the probability turns out to be.
This is a *different primitive* from `prob?` (`utilities.ss:461-466`), which does short-circuit: `(<= p 0.0)`
is `#f` and `(>= p 1.0)` is `#t` with no draw.

**Petacat** — `RNG.prob` (`server/engine/rng.py:97-103`) is a faithful port of `prob?`, and it is what the
posting code (`server/engine/runner.py:1250-1256` for bottom-up codelets, `:1294-1303` for the thematic one)
calls at every site the Scheme writes as `stochastic-if*`.

**The difference is draw count only.** `(random 1.0)` lies in `[0,1)`, so `< 1` is always true and `< 0`
always false: the *decision* is identical at both ends. What differs is that Petacat does not consume the number.

**When it bites.** Constantly. `post-codelet-probability` (`coderack.ss:465-513`) returns exactly 1 for
`rule-scout` whenever a rule type is possible and for `progress-watcher` under thematic pressure, and exactly 0
for `answer-finder` before a supported top rule exists, for `answer-justifier` outside justify mode, for
`thematic-bridge-scout` with no active theme, and for all three self-watching types when self-watching is off.
`average_intra_string_unhappiness` is pinned at 100, a probability of exactly 1, for every string until the
first bond is built. Measured when this entry was written, on `abc → abd; xyz`, seed 42: 29 skipped draws in the
first 8 update cycles, plus 8 more from condition-skipped rules.

Petacat additionally skips the *whole* posting evaluation for a rule whose `condition` is false
(`_rule_condition_holds`, `runner.py:1217-1227`, called at `:1252` and `:1294`), where the reference reaches
`stochastic-if*` and draws.

**Confidence: certain** on the mechanism.

## A-3. `_pick_neighbor` returns a lone candidate without drawing

**Severity: medium — the single highest-volume skipped draw.**

**Petacat** — `server/engine/workspace_objects.py:182-210` returns `neighbors[0]` when there is one candidate,
with a docstring arguing that "the draw cannot change the answer".

**Metacat** — `stochastic-pick` (`utilities.ss:485-490`) draws in both branches: a
`(random (exact->inexact weight-sum))` when the weight is non-zero, and `random-pick`'s
`(random (length l))` (`utilities.ss:475-479`) when it is zero. A one-element list still costs one draw.

**The difference.** The docstring is true about the element returned and false about the stream. Measured when
this entry was written, on `abc → abd; mrrjjj`, seed 7, to answer at 871 codelets: 1,612 calls, 662 of them
short-circuited, 41%. The local-density walk runs inside every `update_strength`, including the two inside every
`wins-fight?`, and in a string with no groups every edge letter offers exactly one neighbour on the walked side.

**Confidence: certain.**

## A-5. Smaller skipped or transposed draws

| | Petacat | Metacat | Note |
|---|---|---|---|
| Empty concept-mapping list | the `bottom-up-bridge-scout` body in `seed_data/codelet_types.json` (`if not cms: fizzle()`) fizzles before the slippage-admissibility gate | `bridges.ss:935` — `(product '())` is 1, so `stochastic-if*` draws, then fizzles | one draw |
| `num_bonds_to_scan`, `n < 2` | `server/engine/codelet_dsl/builtins.py:566-567` returns 0 | `workspace-strings.ss:56-59` — all-zero weights fall to `random-pick`, one draw | one draw, one-letter strings |
| Singleton-group gate | the `top-down-group-scout:category` body in `seed_data/codelet_types.json` evaluates `single_letter_group_probability(singleton)`, and only then draws the coin in `prob(1.0 - …)` | `groups.ss:486` — `stochastic-if*` binds the coin *first*, and the probability expression itself walks the density (drawing) | draws transposed |

---

# C. Ordering

Order is not cosmetic anywhere a list is indexed by a random draw, zipped positionally, or read with a
first-match predicate.

## C-1. Per-node link buckets are appended in Petacat; `cons`-built in the Scheme

**Petacat** — `server/engine/slipnet.py:1070-1080` appends each link to its node's `category_links`,
`instance_links`, `property_links`, `lateral_links`, `lateral_sliplinks` and `incoming_links`.
**Metacat** — `slipnet.ss:225-237` conses each one onto the front.

Today nothing that matters reads the order: every consumer selects by a predicate matching at most one link. A
future `random-pick` over a bucket would diverge silently.

## C-2. `remq-duplicates` keeps the last occurrence; one Petacat form cannot

**Metacat** — `utilities.ss:915-927` (`remove-duplicates-pred`, `remq-duplicates` at `:926`) drops `(1st l)`
when it recurs later, and `get-unjustified-theme-pattern` (`answers.ss:239`) compares whole
`(dimension relation)` entries, so it keeps **two** entries for one dimension with different relations.

**Petacat** — `_unjustified_themes` (`server/engine/answers.py:402-424`) builds a `dict` keyed on dimension, so it
keeps the first relation for a dimension and cannot hold two. The dict form is persisted as JSONB and read by
memory and the API, so changing the form is a schema change, not a local fix.

---

# D. Missing, extra, and duplicated logic

## D-11. Smaller items

| | Petacat | Metacat | Effect |
|---|---|---|---|
| `Image.new_start_letter` | `server/engine/images.py:420-425` keeps the old start letter when a non-letter image has no related node for the relation | `images.ss:280-282` assigns unconditionally, so it becomes `#f` | a stale start letter where the reference records "there isn't one"; assigning `None` would raise a non-`ImageFailure` downstream rather than snag, so it needs its own pass |
| `translate_rule` | `server/engine/codelet_dsl/builtins.py:3247-3248` returns `None` with no built vertical bridge | `answers.ss:1436-1448` translates each description unchanged | an added precondition; probably unreachable |
| `RNG.pick` on empty | `server/engine/rng.py:107-108` raises `ValueError` | `utilities.ss:475-479` returns `#f` | latent; all call sites appear guarded |

---

# E. Citation drift

Petacat cites the Scheme extensively. Most citations are correct; these are not, against `Metacat/build/source`.
None changes behaviour, but a wrong citation is how a wrong reading survives review. The list is of the sites
checked on 2026-11-08, not a complete audit: the drift comes from commits that added lines to `utilities.ss`
(chiefly the `round` shadow at `:250-252`) above the cited definitions, so a citation of any `utilities.ss`
definition below line 250 is suspect.

| Petacat site | Cites | Subject | Actual |
|---|---|---|---|
| `formulas.py:53`, `slipnet.py:273` | `utilities.ss:500` | `1-` | `:542` |
| `slipnet.py:274` | `utilities.ss:504` | `%` | `:546` |
| `formulas.py:279` | `utilities.ss:488-491` | `sigmoid` | `:556-559` |
| `workspace.py:45`, `workspace_objects.py:161`, `:188`, `coderack.py:606`, `themes.py:965`, `rules.py:2630` | `utilities.ss:443-448` | `stochastic-pick` | `:485-490` |
| `workspace.py:986`, `:1041`, `numeric/python_backend.py:467`, `numeric/numpy_backend.py:390`, `numeric/mlx_backend.py:598`, `numeric/layout.py:642` | `utilities.ss:388-392` | `weighted-average` | `:430-434` |
| `workspace.py:1710` | `utilities.ss:426-429` | `~` | `:468-471` |
| `rules.py:458` | `utilities.ss:380-386` | `average` | `:422-428` |
| `rules.py:892` | `utilities.ss:110-114` | `constituent-objects-of` | `:129-133` |
| `slipnet.py:669` | `utilities.ss:570-577` | `select` | from `:612` |
| `rules.py:3591` | `utilities.ss:790-813` | `bounded-random-partition` | from `:832` |
| `workspace.py:1721` | `workspace.ss:678-683` | `rough-num-of-objects` | `:683-688` |
| `workspace.py:1536`, `:1542`, `:1548` | `workspace.ss:683-684`, `:685-686`, `:687-688` | the three `get-rough-num-of-*` getters | `:625-630` |
| `numeric/python_backend.py:125` | `slipnet.ss:201-214` | the spreading loop | `:178-187` |

(All paths above are under `server/engine/`.) **Substantively wrong prose:**

- `workspace.py:1734-1735` says "a large count costs two draws and a small one costs one." Each `~` costs
  **two** draws, the delta and the sign, so it is four and two.
- `workspace_objects.py:187-193` says a sole candidate's draw "cannot change the answer". True of the answer,
  false of the stream. See A-3.

---

# G. Found by the lockstep replay

## G-Z8 (open, engine). The eviction and re-filing walks go bin by bin; Metacat's go down the rack's global codelet list.

`delete-codelets` is `(stochastic-pick-by-method codelet-list 'get-removal-weight)` (`coderack.ss:435-445`) and
`set-urgencies`/`reset-urgencies` walk the same list (`:447-456`); `codelet-list` is consed (`:405, 413`), newest
posted first. `Coderack._pick_codelet_to_remove` (`server/engine/coderack.py:585`) locates the codelet by bin
aggregates and a walk of one bin, which is the same distribution but names a different codelet for the same draw,
and `_move_urgencies` (`coderack.py:704`) re-files in bin order. In a replay both are matched by name and weight,
so the corpora cannot show it. Not changed: matching the walk needs the O(n) global list back (the aggregates exist
because that scan was 35.8% of a run, `coderack.py:566`) and `tests/seed_unit/test_coderack_eviction.py` pins the
bin-major form.

---

# H. Commentary and manual clamps (the text audit)

Every line of commentary Metacat writes for a run is compared with Petacat's replay of the same run
(`scripts/compare_commentary.py`, over the `tests/lockstep` corpora). The commentary is identical, line for line
and in both voices. What differs on purpose:

- **H-6 (intentional). In theme-edit mode the first click in a window claims the type *and* selects the theme**
  (`client/src/components/ThemespaceView.tsx:533-548`). Metacat's first click only claims the window (zeroing it);
  the second selects. A click that does nothing visible has no use on a pointer-less trackpad, so Petacat does both.
- **H-7 (intentional). Theme-edit mode is a client-side view.** Metacat deletes the themes while the dialog is open
  and restores the unedited types afterwards. Petacat leaves the run's Themespace alone and shows the user's
  selection over a blank one (`ThemespaceView.tsx:576-589`); nothing is sent until Clamp Themes, so Cancel cannot
  lose state and a run that keeps going meanwhile is not disturbed.
- **H-8 (addition, not a gap). Metacat defines `explain` (`answers.ss:310-333`) but never calls it.** The procedure
  would write an answer's explanation into the commentary window, but no menu, button or codelet invokes it;
  `explain` occurs nowhere else in the Scheme source. Petacat's single-answer explanation in the Memory panel is
  therefore an addition. Comparing two answers, which Metacat does reach from its memory window, writes "Let's
  see..." and the comparison into the run's commentary.

# I. Verbose mode (the narration port)

Verbose mode (`gui.ss:664`, `%verbose%`) is ported in `server/engine/verbose.py`; the message texts are
`verbose_messages` in `seed_data/commentary_templates.json`. It was checked against Metacat 1.2 by running it with
`%verbose%` on (`tests/lockstep/metacat/record_verbose.py`) and replaying the same recorded runs in Petacat
(`scripts/compare_verbose.py`). What differs on purpose or by construction:

- **I-1 (intentional). Headless forms.** `%workspace-graphics%` is off in the recorded Metacat, so a structure
  prints `(proposed)`, never `(proposed, not drawn)`, and a vertical bridge has no `(#n)` label.
- **I-2 (intentional). Step mode.** Metacat leaves step mode on until Go and forces `%verbose%` while the step
  interval is 10 or less. Requests are stateless here: `POST /step` with `step_mode: true` (the Step button) and
  `n <= 10` is narrated for that batch only (`server/services/run_service.py:513-533`, `VERBOSE_STEP_LIMIT`).
- **I-6 (intentional). Exact versus inexact numbers.** Metacat holds many rounded quantities as exact integers;
  Petacat's are floats. `verbose.exact` (`verbose.py:85`) prints an integral float as the integer where Metacat's
  value is exact (rule figures, progress, overlaps, strengths, salience weights). A quantity Metacat holds as a
  true rational and prints as `100/3` would differ; none occurred in the recorded runs.
- **I-7 (intentional). A translated rule prints zeros in the justifier.** Metacat prints it before
  `set-quality-values`; Petacat scores it at translation, so the print is made with the figures as 0
  (`verbose.py:346-352`).
- **I-8 (intentional). "(new)".** Petacat's structures have no new state and `_retire`
  (`server/engine/codelet_dsl/builtins.py:2227`) resets a broken structure's level, where Metacat's `break-bond`
  leaves it built. `VerboseLog` (`verbose.py:483`) records what it saw built (`_built`, `verbose.py:504`); one built
  before Verbose mode was switched on and built again would print `(new)`.
- **I-9. Free-running workers** interleave their narration; the buffer holds the last 5,000 lines
  (`DEFAULT_CAPACITY`, `verbose.py:56`; Metacat's console is unbounded). Metacat's `try-to-propose-singleton-group`
  message is dead code (never called) and is not ported.
- **I-11 (harness only). `Codelets run: N`.** `run` prints this when it reaches `*break-time*` (`run.ss:164`); the
  recorder sets that to its codelet cap, and Petacat never says it. A run that ends on the cap therefore has one
  line of Metacat's output that Petacat does not say.

---

# Summary

| Section | Entries open |
|---|---|
| A. Random stream | A-2, A-3, A-5 (three rows) |
| C. Ordering | C-1, C-2 |
| D. Missing, extra, duplicated | D-11 (three rows) |
| E. Citation drift | the table above |
| G. Found by the lockstep replay | G-Z8 |
| H. Commentary and manual clamps | H-6, H-7, H-8 (all kept on purpose) |
| I. Verbose mode | I-1, I-2, I-6, I-7, I-8, I-9, I-11 (all kept on purpose or by construction) |
