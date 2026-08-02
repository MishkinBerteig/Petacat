# Self-Watching Parity Audit — Petacat vs. MetaCat

**Scope**: Episodic Memory, Themespace, Temporal Trace — functionality *and* user
visibility — validated against Marshall's 1999 dissertation and the original Scheme
in `../Metacat/`, while checking that the Phase 0 execution substrate has not
degraded them.

**Method**: the dissertation was extracted in full (306 pp.) and used as the spec;
both codebases were read side by side; and every behavioural claim below was
checked by *running* Petacat rather than by reading it alone. Findings are marked
CONFIRMED (executed) or LIKELY (inferred).

**Status**: most findings fixed. What was fixed, and what deliberately was not, is
recorded in "Repair status" at the end; the findings below are kept as written so the
evidence for each change stays legible.

---

## Headline

The port is structurally faithful to an unusual degree. Event inventories, formula
weights, thresholds and constants match the Scheme — often with the dissertation
quoted in the code. The 9 theme dimensions × 25 relations were derived independently
from the Scheme's link table and match exactly; the four jootsing constants and the
four Trace importance thresholds match exactly; Trace granularity matches Figure 4.12.

What is wrong is not the physics. It is a small number of **wiring defects that leave
correctly-implemented mechanisms disconnected**, plus one **live concurrency defect**.

---

## Tier 1 — defects that disable a headline mechanism

### T1.1 Thematic pressure is never switched on

`server/engine/trace.py:495` `clamp_theme_pattern` performs three of MetaCat's four
steps (`Metacat/trace.ss:1530`) — clear the theme type, impose the pattern, freeze the
type — and **omits `thematic_pressure_on`**. Its own docstring claims it does this.
`thematic_pressure_on` has exactly one caller in the codebase
(`themes.py:533`, inside `clamp_negative_pattern`).

Measured: **57 clamp activations → `active_theme_types` empty on every one.** The only
runs with pressure on are the ~11% where jootsing takes the other path.

Because `get_active_themes()` returns `[]` when pressure is off, all three of §4.1.2's
top-down channels are inert — each of which was separately verified as *correctly
implemented*:

- theme → Slipnet spreading (`themes.py:535`)
- theme → structure strength — bridges and descriptions only, with the asymmetric
  response curve and the "incompatible themes drown out compatible ones" rule
- `thematic-bridge-scout` posting probability

**Consequence**: the Themespace is today a read-only characterisation of what the
program is doing, not a mechanism that feeds back into what it does. §2.4.5's `wyz`
justification depends on a clamp weakening the incompatible `a–x` and `c–z` bridges;
in Petacat a justify clamp changes no structure strength at all. CONFIRMED.

### T1.2 Clamp progress always reads zero

`trace.py:94` `TraceEvent.get_strength()` returns `0.0`, and group / rule / slippage
events are bare `TraceEvent`s. In MetaCat these carry relative-quality, group strength
and concept-mapping strength (`trace.ss:965, 880, 796`), and `ClampEvent`'s
progress-evaluator sums them. Petacat's evaluator also maps `progress_focus` through
`{"rule","answer","group"}` only, so the `'workspace'` focus used by both the
snag-response and justify clamps matches nothing.

Measured: **every clamp in every run records `progress_achieved = 0.0`.**

Disables: the progress-watcher's follow-up answer-finder (`rng.prob(progress/100)`);
`get_clamp_jootsing_probability`, which therefore always computes maximum pressure to
give up; and the "how much progress did that idea achieve" commentary. CONFIRMED.

### T1.3 Episodic memory has no influence on cognition

MetaCat calls `answer-present?` at four sites. The main one, `answers.ss:982`, fizzles
with *"Already found this answer"* so the search continues toward a **different**
answer — the author documents this behaviour in `Metacat/help.txt:29`.

Petacat's `justify.py:717` `_answer_already_found` guards on
`hasattr(memory, "answer_present")`, and `EpisodicMemory` **has no such method**, so it
returns `False` unconditionally. The main answer path has no check at all.

That guard is the *entirety* of memory's object-level effect in MetaCat (every other
memory read — reminding, snag comparison — is reportorial). So Petacat's episodic
memory is write-only with respect to cognition.

Measured: six runs sharing one memory stored **five descriptions for two distinct
answers**, and the commentary then reports *"This answer is reminiscent of the answer
xyd to the problem abc→abd; xyz→?"* when the answer **is** `xyd` to that problem.
CONFIRMED.

### T1.4 Free-running corrupts episodic memory — and is reachable from the API

`free_running.py:260` `_collect_outcome` de-duplicates the *run status*, not the
*memory write*. Each racing worker has already completed `_report_answer_locked`,
storing its own `AnswerDescription` and emitting its own `AnswerEvent`.

Measured independently, 8 workers, `PETACAT_NUMERIC_BACKEND=numpy`:

```
runs = 40, runs storing >1 answer = 22  (55%)
answers-stored distribution: {0: 2, 1: 16, 2: 9, 3: 8, 4: 4, 5: 1}
```

Serial stores exactly 1 in 36/36.

**This is live, not latent.** `run_service.py:590` routes to `_run_free` whenever
`workers > 1`, and `create_run` accepts `workers`, rejecting only Audit mode. The
corrupted store is `_global_memory` — the Training Session's *shared* memory — so every
later run's reminding is computed against it. The database is spared (`on_answer` fires
once), so `GET /api/memory` and the live memory silently diverge. CONFIRMED.

---

## Tier 2 — significant divergences

| # | Finding | Evidence |
|---|---|---|
| T2.1 | **Clamped themes erode.** `Theme.boost` / `Themespace.boost_theme` ignore the frozen flag, which the Scheme checks own-or-cluster (`themes.ss:645,674`). A theme clamped at −100 reaches 0 after 20 boosts; a frozen cluster goes 0 → 70 in 10. Observed firing 17 times across 144 runs. | `themes.py:122,496` |
| T2.2 | **Justify clamps last ~10 codelets instead of up to 750.** `justify.py` reads `getattr(workspace,"codelet_count",0)` and `getattr(workspace,"temperature",50.0)` — `Workspace` has neither attribute (verified), so every clamp stamps time 0 and temperature 50. Measured clamp lives: 2, 7, 10, 14 codelets. | `justify.py:1002` |
| T2.3 | **The settling period is measured from the wrong event.** `record_event` deliberately excludes `CLAUDE_START`/`CLAMP_END` from `_last_significant_event_time`, but §4.5.1 is explicit that a clamp event counts. The 250-codelet settling period is already exceeded the instant a clamp is made. The faithful port, `get_elapsed_time`, has zero callers. | `trace.py:692, 1079` |
| T2.4 | **All snags compare as equivalent** (`snag_type` declared but never assigned), so jootsing's ≥3 threshold is reached by three *unrelated* snags. | `jootsing.py:732` |
| T2.5 | **Answer descriptions are not distilled from the Trace.** §2.4.3 and §4.7.1 require it; `create_answer_description` accepts a `trace` parameter and never reads it, using the live dominant pattern instead. MetaCat's rule "always include a string-position theme" makes an empty pattern impossible; Petacat produced `themes={}` in several runs. | `answers.py:101` |
| T2.6 | **Reminding over-fires.** The distance formula differs in 4 of 5 components and omits MetaCat's `+1` base, which guarantees "the distance between two non-identical answers is always at least one". Measured: `ijl` reminds of `xyd` at distance **0.0**. Three different "reminding strength" numbers exist (stored activation, reported strength, and the DB value). | `memory.py:142` |
| T2.7 | **The coherence test is inverted.** MetaCat scores `identity` as *least* abstract (0) and requires `rule < theme`; Petacat counts `identity` as maximally abstract and uses `abs(...) ≤ 50`. The canonical coherent answer `xyd` is classified incoherent. | `memory.py:62` |
| T2.8 | **7 of 8 sections in `commentary_templates.json` are read by nothing** — verified by grep. Only `answer_quality_phrases` is consumed. The comparison English is hardcoded, contrary to the stated database-driven design, and the admin UI edits data no code path reads. | `commentary.py:531` |
| T2.9 | **The Audit inspector re-executes on global parameters, not the Run's own.** `capture_run_state` records no parameters and `review_service` calls `init_mcat` without them, so the reviewer is shown a Themespace the recorded run never had (17/75 theme slots differed under an overridden margin). `runs.parameters` *is* written — it just isn't read back. | `state_graph.py:366`, `review_service.py:537` |
| T2.10 | **Audit cannot reconstruct the Themespace.** The action log has five verbs; ~6,700 self-watching state changes per run have no action (theme boosts, clamps, slipnet/temperature updates, memory writes). Reconstruction *does* work — but by re-execution from the start capture, not from the log. | `sinks.py:281` |
| T2.11 | **Restart drops six `AnswerDescription` fields** (`top_themes`, `bottom_themes`, `unjustified_themes`, both abstractnesses, `activation`), silently switching off `is_coherent`, two distance terms, the snag-justified distinction and two preference criteria. | `run_service.py:975` |
| T2.12 | **`/api/memory/compare` compares the wrong answers, silently.** `GET /api/memory` returns the DB primary key; compare looks it up in the memory's own counter, which restarts at 1 while the Postgres sequence does not. Ids below the drift return a comparison of the **wrong pair with no error**; ids above it 404. | `run_service.py:1058`, `api/memory.py:53` |
| T2.13 | **Intra-cluster spreading is Gauss-Seidel; the Scheme is Jacobi.** Absorbed by integer rounding in all-positive clusters, but diverges once a negative theme is present — i.e. exactly the jootsing regime. Also makes the result depend on theme ordering. | `themes.py:226` |
| T2.14 | **`thematic-bridge-scout` is much thinner** than `themes.ss:750-890`: one theme instead of a conjunction, no mapping-strength weighting, no group flipping, no auxiliary slippages. It cannot build the crosswise mapping §2.4.5 turns on. | `codelet_types.json:233` |

---

## Tier 3 — user visibility

All three MetaCat windows are mouse-interactive. Two of three Petacat views are inert.

| Affordance | MetaCat | Petacat |
|---|---|---|
| **Clamp a theme** | left-click = +100, right-click = −100, click again to clear; cluster zeroed first (`theme-graphics.ss:35-63`). Produces dissertation Figs 4.5 / 4.6 | **absent** — no handlers; `client.ts` has no clamp-themes call though `POST /clamp-themes` exists. The endpoint itself is also weaker: no cluster clear, no freeze, no pressure, no Trace event |
| **Click a Trace event** | horizontal timeline, seven type-specific icons (snag = octagonal stop sign); click restores the whole program state at that moment — workspace, themes re-imposed, concept pattern in the Slipnet, temperature | **absent** — vertical text log with a type filter; the API payload could not support it (`structures` written as `None`) |
| **Click a stored answer** | re-renders the workspace and imposes its three theme patterns; click again restores live state | **absent** — click toggles comparison selection |
| **Delete one answer** | `memory.ss:42`; used for the §5.2.3 experiment | **absent** — only clear-all |
| Quality score, theme chips, filters, search, counts | not shown / absent | **Petacat is richer** |
| Recorded-run review | absent | **Petacat only** — Themespace and Trace inspectable through the same components as the live views |

Memory is absent from the Audit inspector (`inspector_state` returns no `memory` key).

---

## Verified faithful

Recorded so the coverage is known.

**Themespace** — 27 clusters × 75 themes, exact; the 9 dimensions and 25 relations
derived independently from the Scheme's link table match exactly; all five intra-cluster
weights, decay, boost, and the dominance rule (rank by *absolute* activation, leader must
be positive, strictly more than 90 margin) exact; inter-cluster propagation correctly
absent in both; Workspace→Themespace boosting exact including all four special cases;
theme→Slipnet and theme→structure-strength faithfully written (though dead, T1.1);
theme→strength correctly restricted to bridges and descriptions only, with bonds, groups
and rules returning 0.

**Trace** — all 7 Scheme event types present; the 10 further constants are correctly-dead
vocabulary, since §4.4 requires those micro-events filtered out; structure is a flat list
plus period flags in *both* systems — nothing was flattened; granularity matches
Figure 4.12 (median 14 events/run vs. 12 for 1,558 codelets), and `abc→abd; xyz→?`
answers `xyd` with a Figure-4.12-shaped arc; the four importance thresholds and four
jootsing constants match exactly; justification-mode traces match Figure 4.13's sequence.

**Memory** — answer-quality formula and quality-phrase bands exact; Eliza mode faithful
and dual-voice; reminding is graded with MetaCat's bands; the §4.7.1 footnote-18 theme
restriction reproduced exactly; justify runs store descriptions correctly; snags correctly
never arise in justify mode.

**Phase 0** — Themespace capture/restore is exact, round-tripped on answering, grouped,
justify and negatively-clamped runs (all 75 themes identical, frozen flags preserved);
Trace capture/restore complete; trace ordering and numbering held over 60 free-running
runs at 4 and 8 workers with zero anomalies; memory insertion and `find_remindings` are
correctly serialised under the commit lock; run parameters *are* stored on Normal and
Audit rows.

**Numeric substrate** — the Themespace kernel is **bit-exact across all four backends**
(0 disagreements in 41,925 slot updates; activations are integral, so no threshold
comparison can flip). The `mlx` default *does* change answers for a given seed, but the
divergence is inherited from the **Slipnet**: float64 subnormals flush to zero under
float32, flipping `jump_candidates` eligibility and shifting the seeded RNG stream from
codelet 150. It stayed within the recorded expected range on the sample tested.

---

## Documentation errors found in `CLAUDE.md` / `TESTING.md`

1. *"free-running is not wired into `run_service`, and is reached only from the benchmarks
   and tests"* — **false**. `run_service.py:590` routes to it whenever `workers > 1`.
   This matters: it makes T1.4 a live defect.
2. *"nothing currently writes `ended_at`, so the clear does not in fact close the row"* —
   **false**. `clear_memory` closes every open session (`run_service.py:919`).
3. *"`test_free_running.py` … red under `mlx` and `mlx-cpu`"* — **false**; green in
   repeated runs under both.
4. *"Across clusters, activation propagates when bridge types share dimensions"* —
   **false** of both codebases. The dissertation is explicit: "Themes in different
   clusters have no effect on each other."

---

## Suggested order of repair

1. **T1.4** — memory pollution under free-running (live, data-corrupting, 55% of runs).
2. **T1.1** — one line: `themespace.thematic_pressure_on([theme_type])` in
   `clamp_theme_pattern`. Must land with **T2.1** (guard `boost` on frozen), or enabling
   pressure only makes the erosion visible.
3. **T1.3** — a structural `answer_present`; `rules_equal` already exists at
   `rules.py:1194`.
4. **T1.2** — real `get_strength` on group/rule/slippage events, plus the `'workspace'`
   progress focus.
5. **T2.2 / T2.3** — clamp lifetime: pass the real codelet count and temperature; measure
   settling from the last event of any type.
6. **T2.12 / T2.11** — key compare off the row id; persist the six dropped fields.

Items 2–4 are each roughly a line, a method and a constructor argument. They are also the
ones that change *cognition*, so each needs the expected-range oracle
(`tests/module/test_expected_range.py`) re-run, and the results are a judgement call
rather than a pass/fail.

---

## Repair status

### Fixed, with the measurement that shows it

| Finding | Before → after |
|---|---|
| **T1.4** free-running polluting shared memory | 22/40 runs storing 2–5 answers → **0/80** at 4 and 8 workers, matching serial |
| **T1.3** memory inert with respect to cognition | same seed and problem now yields `xyd → dyz → xyz → wyz` across successive runs — the dissertation's canonical alternatives, and exactly what `help.txt:29` describes |
| **T1.1** thematic pressure never switched on | 0 activations via `clamp_theme_pattern` → **45**, all through the fixed path |
| **T1.2** clamp progress always zero | constant `0.0` → real values (5, 27, 77, 100) |
| **T2.1** clamped themes eroding | frozen themes drifting off their clamp → **0** |
| **T2.2 + T2.3** clamp lifetime | 2–14 codelets → **median 350** (settling 250, max 750) |
| **T2.4** every snag equivalent to every other | now compares the translated rule's clause signature and the snag-object set |
| **T2.5** descriptions not distilled from the Trace | vertical pattern now draws on still-present slippage events, and always carries a String-Position theme — **0** empty theme-patterns, where an empty one has no index at all |
| **T2.6** reminding over-firing | everything reminding of everything at distance 0 → `dyz` reminds only of `xyd` (same problem) at strength 40 |
| **T2.7** coherence test inverted | all four dissertation cases correct: `xyd` coherent, `dyz` incoherent, `wyz` coherent |
| **T2.9** Audit inspector on global parameters | the resolved parameter set is captured and re-applied at restore |
| **T2.11** restart dropping six fields | ten columns added (migration `011`), written and read back |
| **T2.12** `/api/memory/compare` resolving the wrong pair | the row id and the in-memory id are now the same number; `clear()` resets the counter |
| Codelet-pattern clamps never lifted | `deactivate` now lifts them, with the coderack threaded to both call sites |
| Duplicate answer in `RunResult` | `step_mcat` and `run_mcat` were both appending; `['ijl','ijl']` → `['ijl']` |
| **GUI** theme clamping unreachable | left-click clamps +100, right-click −100, again clears; the server side now performs the whole of `clamp-theme-pattern` (zero the cluster, freeze, pressure on, `manual_clamp` Trace event) |
| **GUI** no per-answer delete | `DELETE /api/memory/answers/{id}`, which §5.2.3's experiment requires |
| Four stale documentation claims | corrected in `CLAUDE.md` and `TESTING.md` |

### Fixed in the second pass

| Finding | Before → after |
|---|---|
| **T2.13** intra-cluster spreading was Gauss-Seidel | now Jacobi, matching `themes.ss:520-527`'s three passes, in the reference **and** all three numeric backends. Verified two ways: the result is now independent of traversal order (the signature of Jacobi), and `[-100,50,0,0]` settles at **30** where Gauss-Seidel gave 28. All five backend settings still produce an identical theme-state hash, so the substrate's bit-exactness survived the conversion |
| **GUI** Trace events not addressable | `GET /runs/{id}/trace/{n}` serves an event's structures, theme-pattern and strength; `POST .../display` imposes that moment's pattern over the live Themespace and a second call restores it — the `display` message every MetaCat event answers |
| **GUI** stored answers not re-enterable | `POST /memory/answers/{id}/display` imposes an answer's **three** theme-patterns together (`memory.ss:275-277`), with the same click-again-to-restore |
| Trace rows persisted `structures = None` | they now carry structure descriptions, so a recorded run's events are inspectable too. Descriptions rather than references: the objects do not outlive the process |
| `Themespace` had no way to look without touching | `save_current_state` / `restore_current_state` (`themes.ss:67-101`) — inspecting the past no longer overwrites the present |
| **T2.14** `thematic-bridge-scout` scouted one theme | now a **conjunction**: measured 86,244 codelets scouting 2+ themes across 247 runs (modal size 6; none scouted 1). Group flipping, auxiliary slippages, inter-string salience and the mapping-strength weighting all follow `themes.ss:750-1030` |
| **Group flipping was silently a no-op** | `Group.make_flipped_version` and `Bond.flipped` passed the *string* `"plato-opposite"` to a method expecting a node; the `AttributeError` went into a bare `except`, so a "flipped" group kept its original direction and category. This is the root cause of the Trace finding that flips never appear in the Trace — Figure 4.12's re-perception step was unreachable. Verified: flips now flip, and flipped bridges survive the fight and get built |
| **T2.8** commentary templates were dead data | all **8** sections of `commentary_templates.json` now have readers (was 1). The comparison prose is assembled from them, so an admin edit changes the next comparison |
| All four §4.4 **importance formulas** differed | ported literally from `trace.ss:1345-1385`: concept-activation is a *product* of \|Δ\| and depth (decreases count too — a dominant concept going quiet is a milestone); a group is maximally important if **flipped**, spanning, or a singleton with a length description; a perfectly uniform rule is maximally important; concept-mapping is the 4/2/2/3 weighted average with bond-category excluded. Trace granularity stayed within Figure 4.12's range (4–10 events per run) |

**T2.14** (`thematic-bridge-scout`) and **T2.8** (the dead commentary templates) were
done in the same pass; see the notes those changes carry in `themes.ss`-citing comments
and in `server/engine/answer_comparison.py`.

### Found while verifying: the oracle could deadlock

The expected-range oracle runs its problems across a `multiprocessing.Pool`. macOS uses
**spawn**, so every worker re-imports the engine — and under the always-on GPU policy
(`DEFAULT_GPU_THRESHOLD = 0`) each initialises its own Metal context, ten at once
counting the parent. That intermittently deadlocked the whole pool.

Observed directly: parent and nine workers all at **0.0% CPU for 4h17m** at a machine
load of 6, having written no output at all. The parent's main thread was blocked
acquiring a result lock, `_handle_tasks` was idle with nothing left to send, every
worker was parked in `sem_wait`, and an `mlx::core::scheduler::StreamThread` sat in the
parent. The same suite completes in 118s on a CPU backend.

The failure is silent and intermittent — a hung oracle looks exactly like a slow one —
and this is the gate every cognition change is measured against, so `_init_worker`
now pins pool workers to a CPU backend before any engine object exists;
`PETACAT_ORACLE_ALLOW_GPU=1` opts back in. Nothing is lost: the oracle tests what the
engine *computes*, and `tests/module/test_numeric_engine.py` verifies separately that
all four backends compute the same thing.

| | |
|---|---|
| default backend, before | **hung 4h17m**, no output |
| best successful MLX run | 875 s |
| default backend, after | **114 s** |

The 7.6× speedup over even the successful MLX runs has the same cause: workers no longer
pay Metal startup, and a Metal dispatch costs ~0.2 ms whether it carries 200 edges or
340,000.

### One item remaining, as a design question rather than a defect

- **T2.10 — the Audit action log cannot reconstruct the Themespace on its own.** Its
  five verbs record structure and trace events, not theme activations. Reconstruction
  *does* work and is verified exact, by re-execution from the Run-start capture — which
  is what `review_service.advance_inspector` actually does. Whether the log should also
  be sufficient without replay is a question about what Audit is for; nothing in MetaCat
  corresponds to it, since MetaCat has no recorded-run review at all.
