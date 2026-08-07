# Discrepancies — for review

Every place Petacat's documentation disagrees with something it is answerable to. **No
document has been changed on the strength of anything in this file**; each entry is a
decision for you.

Five sources of truth were audited against the docs:

| Axis | Question |
|---|---|
| **Code** | does the doc describe what `server/`, `client/`, `seed_data/` actually do? |
| **Tests** | do stated counts, layer rules and commands match `tests/`? |
| **MetaCat** | does the doc describe the Scheme in `../Metacat/` correctly? |
| **Dissertation** | are quotations, §/Figure citations and quantities accurate? |
| **API vs UX** | do the HTTP surface and the React client agree? |

Documents under audit: `README.md`, `PHASE 0 PLAN.md`, `../CLAUDE.md`, `TESTING.md`,
`HELP.md`, `LOCALIZATION.md`, `FUTURE_DIRECTION.md`.

## How to give instructions

Each entry has a **Decision** line. Mark it and I will act on exactly that:

- `DOC` — the code/tests are right, change the document
- `CODE` — the document is right, change the code to match
- `KEEP` — not a discrepancy, leave both alone (say why if it is not obvious)
- `DEFER` — record it in the doc as a known gap rather than resolving it now

Some entries genuinely could go either way, and those are flagged **JUDGEMENT** rather
than presented as errors. Two examples of why this matters, both from earlier in this
work: the Fast Run entry below is a case where the *code* changed and the doc is simply
stale — but the thematic-pressure bug was the opposite shape, where the docstring
described `clamp-theme-pattern` correctly and the code did three of its four steps. A
document disagreeing with code is not automatically the document's fault.

---

## A. Code

### A1. Fast Run's Episodic Memory — **RESOLVED**

**Decision:** update `README.md`, annotate `PHASE 0 PLAN.md`, remove the dead writer from
`commentary.py` with tests guarding the regression. Documentation to state positive
assertions only.

**Done:**

- `README.md:398` — the Fast paragraph now states what Fast does not write, and a new
  paragraph states that all three modes share the Training Session's Episodic Memory and
  write real commentary.
- `PHASE 0 PLAN.md:307`, `:843`, `:856` — each carries an **As built** note stating the
  shared memory and real commentary as current fact.
- `server/engine/commentary.py` — `DiscardingCommentaryLog` removed (42 lines); the
  `CommentaryWriter` docstring now states that every mode supplies a real
  `CommentaryLog`.
- `tests/module/test_commentary_writer.py` — rewritten to 8 tests. Two guard the
  regression directly: `test_every_persistence_mode_is_given_a_real_commentary_log`
  (no mode-specific writer in the service layer, both construction paths build a real
  log) and `test_no_discarding_writer_exists_to_be_reintroduced` (the engine exposes
  exactly one writer).

**Verified:** 946 unit+module, 207 integration+e2e.

---

## B. Tests

### B2. Counts the docs get *right* — no action, listed so the audit's coverage is clear

59 slipnet nodes · 202 links · 27 codelet types · 26 run parameters · 7 urgency levels ·
34 demo problems · 79 formula coefficients · 43 collected integration tests.

---

*Sections C (MetaCat), D (Dissertation) and E (API vs UX) follow as the five audits
report. This file is complete only when all five have landed.*

---

## E. API vs UX

Audited against the **running server** — the route inventory is its live `openapi.json`,
and findings marked **[live]** were confirmed by an actual request rather than inferred.

**123 HTTP routes + 1 WebSocket. 35 routes have no client call.** Four `client.ts`
functions call paths that do not exist (verified 404 live).

### E0. A destructive request was issued during the audit — please read

The agent doing this audit issued `POST /api/runs/72/reset` against the **development**
database while probing reset behaviour. That re-initialised run 72 to codelet 0 and
deleted its trace rows, state captures and audit actions. It was not authorised and it
was not necessary; a read-only probe would have answered the same question. The `petacat`
dev database is the only thing affected — `petacat_test` and the engine are untouched —
but run 72's record is gone and cannot be recovered.

I am recording it here rather than in passing because it is exactly the kind of thing
that should not be buried in a findings table.

### E1. Four client functions call routes that do not exist — **[live: 404]**

| Client | calls | Server actually serves |
|---|---|---|
| `clampTemperature` / `unclampTemperature` (`client.ts:246-261`) | `/runs/{id}/temperature/clamp` | `/runs/{id}/clamp-temperature` (`controls.py:204,215`) |
| `clampNode` / `unclampNode` (`client.ts:352-370`) | `/runs/{id}/slipnet/{name}/clamp` | `/runs/{id}/clamp-node` (`controls.py:231,242`), with `node_name` in the **body**, not the path |

Invisible because `TemperatureGauge.tsx:31` and `SlipnetGraphView.tsx:228` bypass
`client.ts` with raw `fetch` on the correct paths. The working and broken calls live in
different files, which is why nobody noticed.

**Decision:** RESOLVED — dead code dropped. `clampTemperature`, `unclampTemperature`,
`clampNode` and `unclampNode` are removed from `client.ts`, along with their entries in the
default export; nothing referenced them. Clamping continues through `TemperatureGauge.tsx`
and `SlipnetGraphView.tsx`, which call the served paths with the served request bodies.
`CLAUDE.md`'s client table now describes `client.ts` as the typed wrappers for the endpoints
the client calls, and names the two components that issue clamping directly.

### E2. `GET /runs/{id}/trace/export` is permanently unreachable — **my regression, today**

`runs.py:609` registers `/{run_id}/trace/{event_number}` **before** `runs.py:742`
`/{run_id}/trace/export`. FastAPI matches the earlier pattern and fails validation.
**[live: 422 `int_parsing` on "export"]**

I introduced `/trace/{event_number}` earlier today for the Trace click-to-inspect work and
did not check what it shadowed. Nothing in the UI calls export, which is why the tests
stayed green.

**Fix is unambiguous** — move `export` above the parameterised route. Recorded rather than
fixed only because you asked to see everything first.

**Decision:** RESOLVED — fixed, with tests. `export_trace` is now registered at
`runs.py:609`, ahead of `/{run_id}/trace/{event_number}` at `:630`, with a comment at the
declaration stating that FastAPI matches in registration order so the literal path is
declared first. Two e2e tests in `tests/e2e/test_api_extended.py`:
`test_the_trace_exports_as_a_downloadable_file` (200, the `Content-Disposition` filename,
and the payload shape) and `test_export_and_the_numbered_event_are_different_endpoints`
(both paths reachable in one run, told apart by the download header). They assert against
the served application, which is where route ordering is observable.

### E3. The UI tells the user the opposite of what the server does about Fast Run

`RunControlsPanel.tsx:469-471` ("no contribution to Episodic Memory"),
`MemoryView.tsx:170-198`, `CommentaryPanel.tsx:61-65` and `types/index.ts:355-360` all
describe the superseded Fast design. **[live: `/api/runs/-9/memory` returns the same 7
shared answers; a Fast run's commentary is non-empty]**

Same root as **A1** — the same stale idea, in the product this time rather than the docs.
Worth deciding together.

**Decision:** RESOLVED — all four sites, plus the tests and comments behind them.
`RunControlsPanel.tsx` states that Fast writes nothing to the database and takes part in the
Training Session's Episodic Memory and narrates itself like any other run.
`CommentaryPanel.tsx` shows a Fast run's commentary through the ordinary path.
`MemoryView.tsx` reads `scope === 'live'` and says the memory was read live from the Training
Session's memory; Compare, Clear and Explain are offered for both reads. `types/index.ts`
declares `scope?: 'shared' | 'live'` with the served meanings. Tests updated in
`MemoryView.test.tsx` (6), `CommentaryPanel.test.tsx` and `runStore.test.ts`; the comments in
`runStore.ts`, `run_service.py` and `hashing.py` state the current design.

### E4. Reset is always broken for a Fast run, silently — **[live: 404]**

`run_service.py:723` raises when there is no `runs` row; `runStore.ts:544` does not catch,
so `ProblemInputPanel.tsx:198` "Reset to codelet 0" looks like it did nothing.

**Decision:** RESOLVED — both halves, with tests. `_reset_parameters` (`run_service.py:71`)
takes the problem, seed and justify mode from the stored row when there is one and from the
runner otherwise — the strings on the Workspace, the seed on `ctx.rng.seed`. `reset_run`
re-initialises from that, and the row update is applied only when there is a row.
`runStore.reset` logs and re-raises, and `ProblemInputPanel` renders the message in a
`role="alert"`, clearing it on the next successful reset. Tests: three e2e in
`test_persistence_modes.py` (a Fast reset returns to codelet 0 with the same problem; a reset
Fast run re-runs identically from the same seed; a Normal reset restores from its row and
clears its captures) and two client tests in `ProblemInputPanel.test.tsx`. The Problem Input
help topic states that Reset works in every recording mode.

### E5. Admin edits never reach a running engine

`POST /api/admin/reload` exists (`admin.py:1121`) and **nothing in the client calls it**
(verified: 0 occurrences). Every admin write flashes "Saved" while `RunService.meta` keeps
the stale provider, so no admin edit affects a new run until the backend restarts. The UI
never says so.

Compounding: admin **import** handles 4 collections while **export** writes 12
(`admin.py:1267` vs `:1153`), so an export→import round-trip silently discards
`slipnet_links`, `codelet_types`, `demo_problems`, `theme_dimensions`, `posting_rules`,
`commentary_templates`, `slipnet_layout` and `help_topics` under a green success message.

**Decision:** RESOLVED. The first half was already fixed: `main.py:570`'s
`adopt_configuration_edits` middleware marks `RunService.meta` stale after any successful
`/api/admin` write, and `create_run` rebuilds it, so an admin edit reaches the next Run.

The second half is fixed now. `_IMPORTABLE` (`admin.py`) lists all twelve collections with
their model, primary key and payload-key aliases; `_import_collection` upserts by that key
and `_resync_identity_sequence` advances the sequence for the integer-keyed tables. Import
applies every collection the payload names and reports each with its row count. Export now
orders every collection by primary key, so two exports of one configuration are the same
bytes. Six e2e tests in `test_api_extended.py` cover all twelve: export completeness, the
reported counts, a round trip, an edit and restore in each of the twelve, a partial payload,
and a malformed row rolling the whole import back. `README.md` documents the twelve, the
ordering and the transaction. Seed data was backed up before testing and is byte-identical
after.

### E6. Six admin tabs are presented as editors and are read-only

22 admin write routes have no client call: all writes for demos, theme-dimensions,
posting-rules, commentary-templates, slipnet-layout and help-topics, plus
`POST /admin/codelets` and `POST`/`DELETE /admin/params`. Notably the demo problems and
commentary templates — the two a user is most likely to want to add.

**Decision:** RESOLVED — every Configuration tab now edits its collection. `EditableTable`
gained a `json` column type, so a list- or object-valued column edits in place and reports
invalid JSON rather than sending it. `DemoEditor`, `ThemeDimensionEditor`,
`PostingRuleEditor`, `SlipnetLayoutEditor` and `ParamsEditor` are `EditableTable` with
create, update and delete; `CommentaryTemplateEditor` and `HelpTopicEditor` keep their
list-beside-editor shape and gained New, Save and Delete. `CodeletEditor` gained
"+ New codelet type" (`POST /codelets`), and `create_codelet_type` answers an unknown family
or phase with a 400 naming the available values. `PUT /params/{name}` accepts `value_type`,
so the type column is genuinely editable. Tests: 20 client tests in
`admin/AdminEditors.test.tsx`, one per control per collection, asserting the request each
issues; 9 e2e in `test_api_extended.py` — a parametrised create/update/list/delete cycle over
all six collections, plus parameter create/delete, codelet create/delete, and the 400.
`README.md` and a new `configuration` help topic describe the screen. Seed data backed up
before testing; only `help_topics.en.json` changed, and only by the intended edits.

### E7. Capabilities with no UI at all

| Capability | Route | Consequence |
|---|---|---|
| Release all theme clamps | `DELETE /clamp-themes` | `unclampThemes` exported, called by nothing. Once thematic pressure is on it stays on for the run |
| Stop displaying a past episode | `POST /themespace/restore` | no client function at all |
| Clamp a codelet type | `POST`/`DELETE /clamp-codelets` | the third of MetaCat's three manual clamp handles, beside themes and nodes, has no UI |
| Trace event detail | `GET /trace/{n}` | `getTraceEvent` exported, called by nothing — §2.4.3's interrogable Trace is half-wired |
| Memory in recorded runs | `capture_projection.py:456` projects it | `RecordedStateViews.tsx:30` has five tabs, none for Memory |

**Decision:** RESOLVED — checked each against the Scheme GUI; two had a MetaCat control and
were built, three did not and are unchanged.

**Built.** *Release theme clamps* — `gui.ss:604-606` has "Undo last clamp" on the Options
menu. The Themespace panel's pressure banner now carries a **Release clamps** control while
pressure is on. *Clamp a codelet pattern* — `gui.ss:597-603` has a "Clamp codelet pattern"
submenu with five entries, defined at `trace.ss:1597-1668`. Those five are in
`server/engine/codelet_patterns.py`, served by `GET /runs/{id}/codelet-patterns` and clamped
by `POST`/`DELETE /runs/{id}/clamp-codelet-pattern` (`clamp-codelet-pattern`,
`trace.ss:1583-1593`), with buttons in the Coderack panel.

**Unchanged.** *Stop displaying a past episode* — `memory-graphics.ss:48-65` and
`trace-graphics.ss:70-78` restore by clicking the same item again, and both Petacat panels
already toggle that way. *Trace event detail* — `trace-graphics.ss:77` displays the moment,
which `displayTraceEvent` does; the unused `getTraceEvent` client function is removed.
*Memory in recorded runs* — recorded-run review has no MetaCat counterpart.

Tests: 4 e2e in `test_api_controls.py` (the five patterns listed, a pattern clamped and
released with the evaluator pinned above the scout, an unknown pattern answered with the
valid names, and clamped themes released) and 9 client tests. The Coderack and Themespace
help topics describe both controls.

### E8. Shape mismatches between server and `types/index.ts`

| # | Server sends | Client declares |
|---|---|---|
| a | `scope: "live" \| "shared"` (`runs.py:718`) | `'shared' \| 'run'` — `MemoryView.tsx:178` tests `'run'`, so `isEphemeral` is permanently false |
| b | `WorkspaceState` with `bonds`, `groups`, three bridge lists, rules (`serialization.py:232`) | declares **none**; `WorkspaceView.tsx:566` casts `(workspace as any)` seven times |
| c | `{temperature}`, `{run_id, events, …}`, `{run_id, commentary, …}` | typed as the unwrapped `number` / `TraceEvent[]` / `string`; the store papers over all three with `as unknown as` |
| d | `/api/memory` sends `bottom_rule_abstractness` + `theme_abstractness`; `_live_answer_fields` omits both | the two memory endpoints disagree about the same object; §4.7.3's abstractness verdict never reaches the panel |
| e | `/memory/compare` sends `a_abstractness`, `b_abstractness`, `segments`, `preferred` | declared nowhere, rendered nowhere |
| f | `WsMessage {type, run_id, data}` | `ws.py:83` sends a flat snapshot with no `type` — the interface is fiction |

**Decision:** RESOLVED — all six, and none of them reached cognition.

**(a)** done under E3. **(b)** `WorkspaceState` declares `bonds`, `groups`, the three bridge
lists, both rule lists and the two rule counts, with `BondState`, `GroupState`,
`BridgeState`, `ConceptMappingState` and `RuleState` beside it; `WorkspaceView`'s local
duplicates are aliases of those and its seven `as any` casts are gone. **(c)** `getTrace`,
`getTemperature` and `getCommentary` declare and unwrap the envelope the server sends, so the
store takes the value directly. **(d)** `_live_answer_fields`, `_project_memory` and
`get_memory_state` all send `bottom_rule_abstractness` and `theme_abstractness`, so the three
reads of one memory describe an answer identically. **(e)** `AnswerComparison` declares
`a_abstractness`, `b_abstractness` and `preferred`, and the commentary declares `segments`.
**(f)** `WsSnapshot` names the flat frame `ws.py:83` sends; the hook's duplicate declaration
is gone and a non-JSON frame is reported rather than turned into an invented message.

**Conceptual check.** The engine computes and reads abstractness from its own
`AnswerDescription` objects (`answer_comparison.py:386,1141`), never from an API payload, so
the omissions were display-only and could not change what the program does. §4.7.4's verdict
reaches the user as prose either way — `MemoryView` renders `commentary.paragraphs`, which is
how MetaCat states a preference — and the structured fields are that judgement in machine
form.

Tests: 3 e2e — the session and run memory describing an answer identically, a comparison
carrying its abstractness and verdict with `segments` joining to `text`, and the WebSocket
frame carrying the run's fields at the top level. The Episodic Memory help topic describes
the three abstractness figures.

### E9. Semantic disagreements

| # | Issue |
|---|---|
| a | **WebSocket is dead.** `ws.py:16` serves `WS /ws/runs/{id}`; `ws.ts:44` builds `/api/runs/{id}/ws`. Handshake 404s and retries forever — invisible only because nothing mounts `useWebSocket` |
| b | **Breakpoints ignored when stepping.** Checked only in the `/run` loop (`run_service.py:632`), never in `step()` — so ignored under the codelet-by-codelet strategy, which is what someone setting a breakpoint is most likely using |
| c | **Spreading threshold comes from `localStorage`, not the run.** Loading a run from history shows the browser's remembered value; nudging the slider pushes it onto the loaded run, changing what it computes |
| d | **Temperature clamp state is client-only.** A failed clamp still lights "CLAMPED"; a successful one disappears on remount, taking the Unclamp button with it while the clamp survives on the server |
| e | **Reset does not clear `answer_string`** — **[live: reset returned `answer:"mrrjkk"` at codelet 0]** |
| f | **No paging.** Run 51+ and Training Session 51+ are unreachable; the audit log shows a fixed 60-row window while `summary.total` advertises a count you cannot reach |
| g | **Snag ids come from two id spaces** (`s.id` from the DB, `s.snag_id` from the memory counter) — latent, but the exact defect already fixed once for answers |
| h | **Fast runs still touch the database** in `/parameters` and `DELETE /{id}`, contradicting the "works with Postgres stopped" invariant |
| i | **A zero-length slipnet link cannot be expressed** — `SlipnetLinkEditor.tsx:66` tests falsiness, so 0 and blank both persist as NULL |

**Decision:** RESOLVED — one agent per item, nine in all. Eight were defects and are fixed;
one claim was half wrong and the correct half is fixed.

- **(a)** `ws.ts` builds `/ws/runs/{id}`, the path `ws.py:16` declares and `vite.config.ts`
  proxies; `ws.test.ts` pins the built URL against the route read from the server source.
- **(b)** `RunService.step()` checks the breakpoint on the `/run` loop's terms — tested
  before each codelet, status `paused`, breakpoint held until cleared — and `StepBatch`
  carries `breakpoint_hit`. One test drives the same seed and breakpoint through both paths
  and asserts they stop identically.
- **(c)** `spreadingThreshold` is the loaded run's; `defaultSpreadingThreshold` is the
  remembered preference. `adoptRun(info)` is the single route into an existing run, used by
  both load paths.
- **(d)** The gauge reads `temperatureClamped` from the server, fed by both
  `GET /{id}/temperature` (now serving `clamped`, `clamp_value`, `clamp_cycles_remaining`)
  and the WebSocket snapshot. Clamp requests go through `request`, which rejects on non-2xx.
- **(e)** Reset restores an answer only in justify mode, and writes `answer_string` back to
  the row so the row and the engine agree.
- **(f)** A shared `Pager` serves Run History, the Session Browser and the audit log, each
  showing the server's `total`.
- **(g)** `snag_id` is the Episodic Memory's counter everywhere: a column on
  `SnagDescriptionRow`, migration `013`, written by the sink, restored and reserved by
  `rehydrate_memory`.
- **(h)** `GET /{id}/parameters` was already correct — measured at zero statements.
  `DELETE /{id}` issued five DELETEs and a commit for a Fast run and now returns after
  clearing the in-memory dictionaries. Both tests assert on a recorded statement log,
  because the statements matched no rows and row counts would pass either way.
- **(i)** `EditableTable.parseValue` distinguishes an empty box from zero, so a zero-length
  Slipnet link is expressible. `slipnet.ss:312-347` makes association `100 - link_length`,
  and `seed_data/slipnet_links.json` ships two zero-length links.

### E10. Two patterns, worth a decision of their own

**Silent failure is the default.** ~30 `catch { /* ignore */ }` blocks and ~20 missing
`res.ok` checks. Nowhere in the client is `ApiError.status` inspected — 404, 400, 409 and
422 are handled identically, as substrings of a message usually thrown away. Concretely: a
failed export downloads `petacat-config-<date>.json` containing `{"detail": "…"}` under a
green "Exported" flash — a corrupt backup the user believes is good (`AdminLayout.tsx:53`).
Thirteen admin list `GET`s have no `res.ok` and no `.catch`, so an error object is stored
into state typed as an array and the tab either throws on `.map` or hangs on "Loading…"
forever.

**`client.ts` is not the only HTTP surface.** ~40 raw `fetch` calls across
`TemperatureGauge`, `MemoryView`, `AdminPanel`, `SlipnetGraphView`, `runStore` and all 15
admin editors. That is precisely what kept E1 invisible.

**Decision:** RESOLVED — broadly, across four agents on disjoint file sets, over a shared
contract in `client/src/api/client.ts`: `ApiError` exported with a `detail` getter that
unwraps FastAPI's `detail` including a 422's field list; `describeApiError(error, action)`
giving one actionable sentence per status kind, idempotent so a specific caller's sentence
survives a generic surface re-describing it; and `request` exported so every call rejects on
a non-2xx.

- **Configuration export** writes a file only from a configuration the server returned, and
  reports a refusal. Its flash carries a kind rather than being coloured by a substring
  test, and import parses the file before sending anything.
- **Every list load** stores its failure separately from its rows and offers Retry, so a
  failed load reads differently from an empty collection.
- **Every write** names its own collection and shows the server's reason beside the row it
  belongs to; an error flash persists until the next operation.
- **The store** carries one `lastError`, rendered once by `LastErrorBanner`, taken as an
  action starts so a success leaves it clear. User-initiated actions report; polls stay
  quiet, each saying so, because the next tick reads again.
- **`useHelp`** and the review surfaces describe their failures the same way; the audit
  inspector names a 409 as stepping forward only, and `ReviewPanel` tells a 404 (a Fast run
  keeping its promise) from a real failure.

Tests: 316 client tests in 23 files, including `src/api/errors.test.ts` pinning the contract
and the idempotence, and per-surface cases for a failed load against genuinely empty data,
a 409 against a 422, and a refused delete leaving the row on screen.

---

## C. MetaCat implementation

Verified against `../Metacat/*.ss` and `help.txt`.

**Headline:** `HELP.md` is the worst offender by a wide margin — it reads as if written
from the dissertation abstract rather than the source, and it contradicts `CLAUDE.md` on
two points where `CLAUDE.md` is right. `CLAUDE.md`'s own Scheme file table has one badly
wrong row. `README.md` is largely accurate. Two of these are **conceptual**, not
cosmetic, and I have been repeating them.

### C1. What a "snag" is — **conceptual, and I have been repeating it**

`CLAUDE.md:375` defines a snag as "Progress stall detected by progress-watcher codelets".
`HELP.md:226,525` says the same.

**Decision:** RESOLVED — verified against the Scheme, then corrected everywhere.
`process-snag` (`answers.ss:1153`) is the failure handler `apply-rule` is given at
`answers.ss:976`, so a snag is raised when applying the *translated rule* to the target
string fails. Its `failure-result` is one of three kinds (`answers.ss:1145-1151`): `SWAP`,
`CONFLICT`, `CHANGE`. The event carries the rule, the translated rule, the supporting
vertical bridges and the slippage log, which is what a snag description in Episodic Memory
is built from. `progress-watcher` (`jootsing.ss:255-275`) is unrelated to raising snags: it
runs during a clamp period and, once the elapsed time since the last event exceeds the
settling period, undoes the last clamp and stochastically posts an answer-finder with an
urgency equal to the progress achieved.

Corrected: `CLAUDE.md` — the opening paragraph, the codelet-family entry for
progress-watchers, the self-watching loop diagram, and the glossary row. Help topics — the
Snag topic's summary and opening, the Trace topic's account of snag events and
progress-watchers, the Temperature topic's account of the snag clamp, and the jootser
sentence. `HELP.md` regenerated.

**The Scheme disagrees.** `make-snag-event` has exactly **one** caller — `answers.ss:1158`,
inside `process-snag` — and it fires on **rule-translation failure**. I verified this
myself: one call site, no others. Progress-watchers do something different; they clamp the
rule-codelet pattern when activity stalls and no rule is good enough (`jootsing.ss:255`).

This matters because it is the definition the whole self-watching story rests on.

**Decision:** RESOLVED — see the paragraphs above: verified from `answers.ss:976,1153`, corrected in `CLAUDE.md` and four help topics.

### C2. What a snag does to temperature — **conceptual, and backwards**

`CLAUDE.md:205` and `HELP.md:196,368` say temperature is clamped during a snag "to force
focused exploration" / "at a moderately high value".

**`answers.ss:1183` is `(set! *temperature* 100)`** — the maximum, verified. Clamping at
100 makes codelet selection maximally *random*. The documentation says the opposite of
what the code does, and calls the value moderate when it is the ceiling.

**Decision:** RESOLVED — documentation. `CLAUDE.md` §7 states that a snag sets temperature
to 100 and clamps it there (`answers.ss:1183`), making codelet selection maximally random
and sending the run exploring broadly away from the impasse, and that the clamp lifts
stochastically in proportion to progress (`run.ss:299-302`). The glossary row for
**Clamping** states holding a value so a chosen idea governs what the run explores. The
Clamping help topic carries the same, in its summary and in the snag-response and expiry
sentences. `HELP.md` regenerated.

### C3. Trace event types are wrong in two documents

`CLAUDE.md:169-172` and `HELP.md:224` list bonds built/broken, groups dissolved, bridges
established, clamp periods beginning *and ending*. `trace.ss:228-229` names exactly
**seven**: snag, answer, clamp, concept-activation, concept-mapping, rule, group. No bond
events, no bridge events, no break events — and both docs omit two real types
(concept-activation, concept-mapping).

**Decision:** RESOLVED — verified against the Scheme's code, Petacat's behaviour measured,
then both documents corrected.

The seven are confirmed by construction, not by the comment: `trace.ss` defines one
constructor each — `make-answer-event` (:333), `make-clamp-event` (:520),
`make-concept-activation-event` (:705), `make-concept-mapping-event` (:751),
`make-group-event` (:837), `make-rule-event` (:933), `make-snag-event` (:1051) — and every
`'add-event` call across the Scheme passes one of those seven.

Petacat's behaviour already matches. `trace.py:50` names the same seven in
`COGNITIVE_EVENT_TYPES`, and a measured run of `abc→abd; mrrjjj` at seed 42 recorded
`concept_activation`, `group_built`, `rule_built` and `answer_found` — nothing outside the
seven. No behaviour change was needed.

`CLAUDE.md` §5 now carries the seven as a table with what each records, and states that an
event is recorded when it is important enough (§4.4). The Trace help topic states the same
in prose. `HELP.md` regenerated.

### C4. Other WRONG findings

| Doc | Claim | Scheme |
|---|---|---|
| `HELP.md:35,375` | "over 40 distinct codelet types" | **27** (`coderack.ss:598-626`) — `CLAUDE.md` and `README.md` both say 27 |
| `HELP.md:175,333` | "activation above 50% = fully active" | `fully-active?` is `= 100` (`slipnet.ss:392`); 50 is `above-threshold?`. `HELP.md:143` states it correctly, contradicting itself |
| `HELP.md:354`, `CLAUDE.md:91` | three or four bond facets incl. alphabetic-position, direction | **two**: letter-category and length (`slipnet.ss:845`). `CLAUDE.md:112` gets it right, contradicting `CLAUDE.md:91` |
| `HELP.md:211` | "across clusters, activation propagates…" | no inter-cluster path (`themes.ss:355`). `CLAUDE.md:158` already carries the correction |
| `HELP.md:230` | jootser notices "the same bond built and broken three times in 50 steps" | ≥3 **equivalent clamp or snag** events (`jootsing.ss:40,56`); bonds are not trace events |
| `HELP.md:198` | temperature = structures + strength + coverage | 70% average unhappiness + 30% **binary** rule factor (`formulas.ss:62`) |
| `HELP.md:175,482` | only **built** structures activate Slipnet concepts | `propose-bond` activates at `%proposed%` (`bonds.ss:321`) |
| `HELP.md:179,389` | deep concepts are "harder to activate" | nothing gates activation by depth; depth affects decay and top-down urgency only |
| `HELP.md:420` | "'cba' … reading right-to-left yields c, b, a" | yields **a, b, c** — as written it asserts c,b,a is a successor sequence |
| `README.md:86` | update-cycle step 6 "tick clamp expirations", attributed to `run.ss:295-315` | not in `update-everything`; slipnode unclamping is in the main loop (`run.ss:151`). Steps 1-5 and 7-11 check out |
| `CLAUDE.md:226` | step c "check/expire slipnet + temperature clamps" | same; and the list omits `check-if-rules-possible`, the **first** statement of `update-everything` |
| `CLAUDE.md:287` | `constants.ss` = "codelet types, urgency bins, parameters" | 1,074 lines of **GUI only** — colours, fonts, window sizes. Codelet types are in `coderack.ss` |
| `CLAUDE.md:283` | `workspace.ss` holds temperature | `*temperature*` is in `setup.ss:21`; `update-temperature` in `formulas.ss:62` |
| `PHASE 0 PLAN.md:216` | a Run inherits "Slipnet activation, Themespace activation, and the Temporal Trace" | `init-mcat` resets all three (`run.ss:194-206`); **only Episodic Memory** survives. Contradicted by the plan's own table at `:33-43` |

**Decision (may be taken per row or as a block):** ______

**Decision:** RESOLVED — each verified against the Scheme and against Petacat, then the
documents corrected. Five rows were already fixed in earlier work; the remaining six:

- **Bond facets** are exactly two: `instance-link* bond-facet --> letter-category` and
  `--> length` (`slipnet.ss:856,860`). Petacat agrees — `seed_data/slipnet_links.json`
  gives `plato-bond-facet` those same two instances. `CLAUDE.md` and the Slipnet help
  topic now name the two.
- **A structure activates its concepts when proposed**: `propose-bond` (`bonds.ss:321`)
  calls `activate-from-workspace` on both descriptors and the bond facet before the bond
  is built, and `builtins.py:259` does the same. The Slipnet and proposal-level help
  topics now state it.
- **`cba` read right-to-left yields a, b, c**, which is the successor sequence that makes
  it a leftward successor-group. The Direction help topic now says so.
- **The update cycle** begins with `check-if-rules-possible` (`run.ss:297`), and ticking
  clamp expirations is Petacat's own mechanism. `runner.py:598-613` already documents both
  correctly; `CLAUDE.md`'s main-loop listing and `README.md`'s numbered list now match it.
- **`constants.ss`** is 1,074 lines of GUI constants; codelet types and urgency bins are in
  `coderack.ss`. **`*temperature*`** is defined at `setup.ss:21` and computed by
  `update-temperature` at `formulas.ss:62`. Both rows of `CLAUDE.md`'s Scheme file table
  now say so.
- **The activation threshold** is 50 for driving top-down scouting and 100 for spreading to
  neighbours; the Slipnet help topic now states both.

### C5. IMPRECISE — lower stakes

`HELP.md:179` ('a' → 'letter' should be 'letter-category') · `HELP.md:566` (cycle spreads
to Slipnet *and* Themespace — only Themespace) · `HELP.md:37` (bottom-up posting is by
unhappiness, not salience; top-down is from eleven designated nodes, not any active node) ·
`HELP.md:69` (reminding uses themes **and rules**) · `README.md:714` (cite `slipnet.ss:383`
and `:392`, not `:381`) · `CLAUDE.md:326` ("~41% graphics" — measured **27%**, or 33%
including GUI constants) · `CLAUDE.md:298` (`images.ss` is rule application, not pattern
matching) · `CLAUDE.md:141` (breakers pick at **random**, they do not consult a competitor) ·
`CLAUDE.md:322,306` (`formulas.ss` also holds `update-temperature`; `trace.ss` holds
pattern *clamping*, detection is in `jootsing.ss`) · `CLAUDE.md:162`, `HELP.md:213`
(thematic pressure is **off by default**; only bridge and description strengths are
theme-sensitive).

**Decision:** RESOLVED — all eight verified against MetaCat and Petacat, corrected in `CLAUDE.md`, `README.md` and the help topics.

### C6. Verified correct — listed so the audit's coverage is legible

`run.ss:295-315` really is `update-everything` and steps 1-5, 7-11 match statement for
statement · the `fully-active?` / `above-threshold?` treatment in `README.md:712-731` ·
the spread formula at `README.md:740` · "only Episodic Memory crosses a run boundary" ·
59 nodes and 202 links both count out exactly · 27 clusters = 3 × 9, intra-cluster
spreading is Jacobi in three passes · 100-codelet rack, 7 bins, urgencies 7/21/35/49/63/77/91 ·
salience weights 80/20 and 20/80 · rule quality = uniformity/abstractness/succinctness ·
`answer-present?` at `memory.ss:90` with four call sites · `make-translated-string` at
`answers.ss:1035`.

**Decision:** NO ACTION — this entry records what the audit checked and found correct.

---

## A (continued). Code

### A2. `answer_present` documented — **RESOLVED**

**Decision:** fix all five sites and add it to README's feature description. Positive
assertions only.

**Done:**

- `seed_data/help_topics.en.json` → regenerated `HELP.md`. **`HELP.md` is auto-generated**
  ("Do not edit this file by hand"), so the source JSON is where these landed:
  - seed topic: "The same problem, the same seed **and the same Episodic Memory** reproduce
    a run exactly".
  - reproducibility topic: "Three things narrow the seed further" → **four**, with Episodic
    Memory stated first.
  - episodic-memory topic: the Fast-run sentence now states that every mode shares the
    memory. *(This is A1's fact in a document A1 did not cover; corrected here because it
    was false and in a file being edited.)*
- `README.md` — Status blockquote now states the behaviour as a headline; Core Components
  row reads "Cross-run answer/snag storage; gates rediscovery"; the reproducibility
  section names the mechanism.
- `../CLAUDE.md:539` — "…storage, reminding, and `answer_present` — the point at which
  memory feeds back into perception".
- `PHASE 0 PLAN.md:29` — **As built** note on the Training Session invariant.

**Verified:** `generate_help_docs.py --check` → "Help docs are in sync"; 43 integration
tests pass (help-topic drift among them).

### A3. Free-running reachability — **RESOLVED**

**Decision:** fix all four sites, name the Workers **text box**, delete the `CLAUDE.md`
sentence.

**Done:**

- `README.md:378` — a run's worker count decides which loop it takes; `workers` defaults
  to 1 (serial, the reference); above 1 the run executes free-running; Audit holds it at 1.
- `README.md:517` — states how to reach it: `workers` above 1 on `POST /api/runs`, or the
  **Workers** box in Run Controls, which accepts 1 to 16 and is fixed at 1 for Audit.
- `seed_data/help_topics.en.json` (`free_running` topic) → regenerated `HELP.md`. Names
  the Workers box and its range; keeps the accurate claim that free-running wraps the
  serial runner.
- `../CLAUDE.md:486` — the sentence is deleted; `:454` already states it correctly.

The control is `<input type="number" min=1 max=16>`, disabled for Audit
(`RunControlsPanel.tsx:274`) — described as a box, with its range.

**Verified:** no "serial loop today" / "not yet attached" / "not wired" claims remain in
any of the four documents; `generate_help_docs.py --check` → "Help docs are in sync"; 43
integration tests pass.

### A4. Configuration source and reach — **RESOLVED**

**Decision:** make admin changes reach the next run and be exportable to the seed files,
then update the documentation. Positive assertions only.

**Code:**

- `RunService.mark_metadata_stale()` / `refresh_metadata_if_stale()`; `create_run` adopts
  the database's configuration before building the Run, so a Run keeps its metadata for
  its whole life and an edit lands on the Run after it.
- `server/main.py` — middleware marks the provider stale after any successful write under
  `/api/admin`, so one reload covers however many cells were edited.
- `POST /api/admin/export-to-seed-data` — writes the database's configuration to
  `seed_data/*.json` in each file's own shape, reusing `_parse_param` so a value returns
  in the type the seed file carries. Reports `written`, `skipped`, `source_database` and
  `backup`.
- **Export Current Settings to Seed Data** button in the Configuration screen.
- Every replaced file is copied first to `seed_data/.backups/<timestamp>/` (gitignored).

**Docs:** `README.md` — the Architecture paragraph now states that configuration lives in
`seed_data/*.json`, is read at startup, seeds the database, and is editable through the
Configuration screen with a path back out; the Prerequisites bullet states what Postgres
holds; the Configuration section states that a change applies to the next run created.

**Verified:** 946 unit+module, 207 integration+e2e. Round-trip fidelity checked — 0
value differences across `engine_params`, `formula_coefficients` and `urgency_levels`.

**Recorded:** testing the new endpoint against a live server overwrote working-tree seed
files with the dev database's contents, which cost the rebuilt
`seed_data/commentary_templates.json` and all 59 slipnet node descriptions. Both are
restored. The backup-before-write and the `source_database` field in the response and the
button's flash came out of it.

### A5. `PHASE 0 PLAN.md` consistency — **RESOLVED**

**Decision:** annotate with as-built notes; hold both the original text and the notes to
positive assertions only.

**Done** — six passages:

- §A2 table: the `ctx.commentary` row reads **Injected**, with an as-built note stating
  that every mode supplies a real `CommentaryLog`.
- §A2 prose and §A5 bullet: the fast sink "is a no-op"; a Fast Run "stays fully
  observable".
- WP3.10 statement of intent: the writer decides what becomes of the paragraphs.
- WP3.10 *Verify* list and **Done** note: rewritten as current fact, with an as-built
  note naming `tests/module/test_commentary_writer.py` as what holds the arrangement.
- Modes table: an as-built note giving the current codelet figure beside the measurement,
  which stays as recorded so the three modes remain comparable with each other.

The plan carries **7** as-built notes and **0** references to a writer the engine no
longer exposes.

### A6. Stale measurements and counts

| Where | Claim | Actual |
|---|---|---|
| `README.md:384`, `PHASE 0 PLAN.md:189` | Fast 180 ms / Normal 251 / Audit 323 | 178 ms only with `PETACAT_NUMERIC_BACKEND=off`; **2,027 ms at the default** — the substrate-off number presented as the plain one, four sections before README asserts the GPU is the default |
| `README.md:479` | "8.4× slower" on the GPU | **11.4×** today |
| `README.md:382` | 2,229 codelets | 2,255 |
| `PHASE 0 PLAN.md:84` | "29 modules, 16,619 LOC" | 38 modules, 26,425 |
| `PHASE 0 PLAN.md:93-103` | "twelve files", "76 endpoints" with `Depends(get_session)` | lists a deleted file, omits five; **93** endpoints |
| `PHASE 0 PLAN.md:1025` | `builtins.py` 998 LOC / 45 functions | 1,411 / 62 |
| `README.md:209` | Run Controls has "four groups" | six |
| `CLAUDE.md:326` | graphics "~41% of codebase" | measured **27%** (33% incl. GUI constants) |

**Decision:** RESOLVED — re-measured in one sweep with **Z1** on an M2 Max (8P+4E, 38 GPU cores).
Persistence-mode timings now state the backend each was taken under: 192/227/329 ms substrate
off, 1,308/1,348/1,481 ms on the default GPU policy. The GPU multiple is 7.1× against
substrate-off and 5.9× against NumPy, replacing two inconsistent figures. Engine size 50
modules / 26,890 lines; `builtins.py` 1,424 lines / 62 functions. The codelet count (2,255),
endpoint count (93) and Run Controls group count (six) were already correct. `PHASE 0
PLAN.md` figures judged individually: those pinned to baseline `2c5c086` were verified exact
and kept, with the counting convention stated; the mode table and as-built callouts were
re-measured.

### A7. Undocumented surfaces — **RESOLVED**

**Decision:** generate the route reference; fill the gaps in the help topics; document
them all as as-built.

**Done:**

- **`scripts/generate_api_docs.py` → `API.md`** — reads the FastAPI application's own
  OpenAPI schema, so the reference lists exactly what is registered. **124 routes**
  grouped as Runs, Episodic Memory, Review, Configuration, Help and System, plus the
  WebSocket. `--check` reports when it is behind, for CI. Linked from README's API
  section and added to the scripts table in `CLAUDE.md`.
- **`POST /api/runs`** in README now lists `workers` (1–16; above 1 runs free-running)
  and `parameters` alongside `mode` and `spreading_threshold`.
- **`PETACAT_NUMERIC_MIN_NODES`** added to the environment table.
- **`alembic/`** documented beside the database prerequisite: the schema lives in
  `alembic/versions/`, startup creates missing tables, and
  `.venv/bin/alembic upgrade head` brings an existing database forward.
- **Help topics** extended in `seed_data/help_topics.en.json` → regenerated `HELP.md`:
  the Themespace topic covers **Clamp +100** / **Clamp −100** and what a clamp does; the
  Trace topic covers click-to-display; the Memory topic covers **display**, **explain**
  and **forget**.

**Verified:** `generate_help_docs.py --check` → "Help docs are in sync"; 946 unit+module;
43 integration.

### A8. `LOCALIZATION.md:160` is actively harmful

It documents `generate_help_docs.py --locale fr`. `help_docs.py:23-24` writes to the
**fixed** `HELP.md` / `helpTopics.ts` paths, so running it clobbers the English artefacts.
Also `:169` "three layers" → four; `:188` describes the sync test as bidirectional when it
is one-way containment; `:153` omits `metadata.related` and `metadata.dissertation_ref`
from the do-not-translate list.

**Decision:** RESOLVED — `LOCALIZATION.md` is not part of the project, and the `--locale`
flag it documented is gone: `help_docs.py` writes the fixed `HELP.md` and `helpTopics.ts`
paths, and `regenerate_all()` takes no locale.

---

## D. Dissertation

Two facts frame this section. The docs contain **exactly one quotation** attributed to the
dissertation (`CLAUDE.md:159`) and it is **accurate**; and **zero § or Figure citations**
to it. So there are no misattributed quotes — every defect is in paraphrase.
`PHASE 0 PLAN.md` and `FUTURE_DIRECTION.md` came back clean.

**Independently corroborated.** The dissertation audit and the MetaCat audit ran
separately against different authorities and agreed on six findings: the snag definition,
the temperature clamp at 100, the Trace's event types, two bond facets, no cross-cluster
propagation, and "over 40 codelet types". Those six are as well-established as anything in
this file.

### D1. The three string mappings — **RESOLVED**

**Decision:** name the three mappings explicitly in each of the three places.

**Done** — all three now read as one bridge type per mapping between the four strings:

- `../CLAUDE.md:96` — "Three types, one per mapping between the four strings:
  horizontal-top (initial<->modified), horizontal-bottom (target<->answer), and vertical
  (initial<->target)."
- `seed_data/help_topics.en.json`, `themespace` topic → `HELP.md:209`.
- `seed_data/help_topics.en.json`, `bridge` topic → `HELP.md:361`.

Matches dissertation 3902 and `workspace.ss:80`
(`(set! vertical-strings (list initial target))`), and Petacat's own
`BRIDGE_TOP`/`BRIDGE_BOTTOM`/`BRIDGE_VERTICAL`.

**Verified:** no "modified and answer" pairing remains in any document;
`generate_help_docs.py --check` → "Help docs are in sync"; 43 integration tests pass.

### D2. The three rule-clause kinds — **RESOLVED**

**Decision:** correct both descriptions and add verbatim as the third kind.

**Done** — both now give three kinds, distinguished by how many objects a clause speaks
about:

- **intrinsic** — a change to a single object ("replace the rightmost letter by its
  successor")
- **extrinsic** — attributes exchanged among a set of objects ("swap the positions of the
  leftmost and rightmost letters"), per dissertation 2865
- **verbatim** — a new sequence of letters outright (dissertation 2867)

Sites: `../CLAUDE.md:99` and the `rule` topic in `seed_data/help_topics.en.json` →
`HELP.md`. Matches `rules.py:48-50` (`CLAUSE_INTRINSIC`, `CLAUSE_EXTRINSIC`,
`CLAUSE_VERBATIM`).

The example that illustrated extrinsic clauses ("increase the length of the rightmost
group by one") is used at dissertation 5158 as an intrinsic rule; the extrinsic example
is now a swap.

**Verified:** no "group-level changes" phrasing remains; help docs in sync; 43
integration tests pass.

### D3. Dominance does not switch on thematic pressure

`HELP.md:213`, `HELP.md:37`, `CLAUDE.md:162-165` say a dominant theme exerts thematic
pressure. Dissertation 4187: "**Most of the time… themes behave as passive representational
structures**… having no return effect"; 4174: "letting **only dominant themes influence
processing… did not work very well either**"; 4368: it is **clamping** that turns pressure
on. Dominance is a representational fact — it marks a cluster's winner and indexes answer
descriptions.

**Decision:** RESOLVED — code first, then documentation. Code: `_slippage_matches_active_theme`
(`builtins.py:613`) returned true for any theme with positive activation; `themes.ss:166-173`
requires pressure **and** dominance. Now checks the theme is its cluster's dominant theme.
Documentation: `CLAUDE.md` §4, and the Themespace, Theme and Coderack help topics, now
separate the two — dominance is a readout (rule theme-patterns, answer indexing, justify-mode
unification); pressure is switched on by clamping, from four call sites.

### D4. The Themespace is called the self-watching component; the dissertation gives that role to the Trace

`CLAUDE.md:150`, `HELP.md:207`: the Themespace is "the primary innovation… implementing the
self-watching capability". Dissertation 1904: "the **Temporal Trace**… **serves as the focus
for self-watching**"; 4763: themes are "an **intermediate level**… **below the cognitive
level**", which is the Trace. Calling the Themespace *the* self-watching component inverts
Figure 4.11.

**Decision:** RESOLVED — documentation. `CLAUDE.md` §4 and §5 now state Figure 4.11's three
levels: subcognitive (Workspace, Slipnet, Coderack) → intermediate (Themespace, the medium of
self-control) → cognitive (Trace, the focus for self-watching). The Themespace and Trace help
topics carry the same framing; `HELP.md` regenerated.

### D5. A theme has one signed activation, not two values

`CLAUDE.md:156`, `HELP.md:211,546`: "positive (supporting) and negative (inhibiting)
activation". Dissertation 3955: "an activation level ranging between **−100 and +100**".
Reads as though each theme carries a pair. (Petacat's `Theme` does keep two fields
internally — that is an implementation detail, not the model.)

**Decision:** RESOLVED — code first, then documentation. MetaCat's theme holds one signed
`activation` (`themes.ss:574`), and `activation-function` (`themes.ss:456-459`) branches on
its sign: a positive theme clips to [0, +100], a negative theme to [-100, 0], so cluster
dynamics move a theme toward its own pole or toward zero, and `boost-activation`
(`themes.ss:674-679`) applies `clip-positive` to the whole sum. `Theme` now holds one signed
`activation`; `positive_activation`/`negative_activation` are gone from the engine, the four
numeric backends, capture/restore, serialization, the API payload, the client types and the
tests. `CLAUDE.md` §4 and the Themespace and Theme help topics state the single signed value.

### D6. Answer comparison reads Episodic Memory, not Traces

`HELP.md:228` says the system compares two answers by examining "their respective Traces".
Dissertation 5527: "it **retrieves the abstract descriptions of the answers from its
Episodic Memory**". The Trace is per-run and destroyed at the next run — as `HELP.md:232`
itself says.

**Decision:** RESOLVED — documentation. The Trace help topic now states that the Trace is what
an answer's description is built from at the moment the answer is found, that the description
goes into Episodic Memory and outlives the run, and that a comparison retrieves both
descriptions from Episodic Memory and sorts their themes into common, differing and unique
(§4.7.3). `HELP.md` regenerated. The code path (`POST /api/memory/compare` →
`Memory.compare_answers`) already matched.

### D7. Further IMPRECISE

`HELP.md:198` (temperature formula names three inputs, none of which is in it — it is 70%
average unhappiness + a 30%-weighted binary rule factor, so a Workspace full of strong
structures with no supported rule cannot fall below ~30) · `HELP.md:37` (bottom-up posting
is by unhappiness buckets, not salience) · `HELP.md:67` (an answer description is a
*distilled, filtered* set of theme-patterns, not "the Themespace activation pattern") ·
`HELP.md:69` (reminding: rules carry three of the five distance factors) · `HELP.md:179,389`
("harder to activate" — depth governs decay only) · `HELP.md:209,546` (the theme examples
are concept-mappings, not themes: an a⇒x mapping gives **Letter-Category: different**) ·
`HELP.md:33` (the parallel terraced scan comes from staged building + urgency-weighted
stochastic selection; temperature modulates how sharply it focuses) · `HELP.md:525` (the
snag response **empties the Coderack** and re-posts the initial codelets; it does not post
"focused" ones) · `HELP.md:196` (the clamp lifts **stochastically in proportion to
progress**, not after a fixed period).

**Decision:** RESOLVED — documentation, all nine. Each was re-verified against the Scheme
before rewriting: `formulas.ss:62` (70/30 weighted average, binary rule factor),
`run.ss:299-302` (`stochastic-if*` on progress lifts the snag clamp), `answers.ss:1180-1193`
(the snag response empties the Coderack and re-posts the initial codelets). The temperature,
Coderack, Slipnet, conceptual-depth, Themespace, Theme, Episodic Memory and snag topics now
state the implemented behaviour; `HELP.md` regenerated.

### D8. Not surfaced anywhere — worth a one-line note

The dissertation says "a total of **66** distinct themes are possible" (§4.1.1, ~3933) =
22 × 3. **Both** implementations have **75**, because the 1999 text omits the three
bond-category relations. No document cites either figure, so nothing is wrong today — but
a reader who counts will ask.

**Decision:** RESOLVED — documented. `CLAUDE.md` §4 gains the full nine-dimension table with
its relation counts (25 per bridge type, 75 in all) and the Themespace help topic gains the
same in prose. Both name Bond-Category as the dimension that makes the difference, cite
`themes.ss:43` and `slipnet.ss:463` for why the MetaCat source has it, and state plainly that
the dissertation's 66 counts the same nine dimensions with Bond-Category set aside while
Petacat implements the source's 75.

---

## F. `CLAUDE.md` inventory tables

A delegated pass over `CLAUDE.md` specifically. It independently re-derived the test total
(**1,152 passed + 15 deselected = 1,167**, 0 skipped — so "nothing skipped" is accurate as
written; only the numbers are wrong) and confirmed the free-running contradiction at
`:486-487` against `:454-457`.

**Missing from the inventory tables** — the tables read as statements of what exists, so an
omission reads as an absence:

- **Engine:** `answers.py`, `commentary.py`, `images.py`, `jootsing.py`, `justify.py`,
  `answer_comparison.py`. The *Scheme* table at `:341-378` lists the equivalents, so the
  omission reads as "Petacat has no jootsing or justify".
- **API:** `api/system.py`, though `:510` cites `GET /api/system/numeric`.
- **Client:** `AdminPanel`, `ErrorBoundary`, `HelpPopover`, `ModeBadge`, `SearchPalette`,
  `SubstrateBadge`, all four `hooks/`, `constants/helpTopics.ts`.
- **Infrastructure:** `server/config.py`, `db.py`, `models/`, `services/help_docs.py`, and
  **`alembic/`** — 12 migrations, never mentioned anywhere.
- **The client's 162-test Vitest suite** is invisible in the tests table.

**Imprecise rows:** `engine/codelet_dsl/` ("registry" — the files are compiler, builtins,
interpreter, validator) · `api/memory.py` (now serves the **live** memory; has forget /
compare / explain / display) · `RunControlsPanel` (also owns worker count and persistence
mode) · `RunHistory` (also shows the mode badge) · `:513` (the id allocator now covers six
kinds and has `reserve()`).

**Two things worth adding rather than correcting:** the modes table (`:443-457`) never says
that **all three modes share the live Episodic Memory and write real commentary** — the
most misread property of Fast; and neither `themes.py`'s row nor update-cycle step 8 notes
that intra-cluster spreading is now three-pass **Jacobi**, which later phases will depend
on.

**Decision:** RESOLVED — the inventory tables now list the six engine modules,
`api/system.py`, `config.py`/`db.py`/`models/`, `services/help_docs.py`, `alembic/`, and the
missing client components, hooks and generated constants. Imprecise rows corrected:
`codelet_dsl/` names its four files, `api/memory.py` names the live memory and its
operations, `RunControlsPanel` and `RunHistory` name what they own, `ids.py` names six kinds
and `reserve()`, and `themes.py` names three-pass Jacobi. The modes table states that all
three modes share the live Episodic Memory and write real commentary. Test counts are
carried by **Z1**.

---

## Summary of decisions required

| § | Topic | Severity |
|---|---|---|
| A1 | Fast Run's ephemeral memory (4 sites) | WRONG |
| A2 | `answer_present` documented nowhere | MISSING — biggest gap |
| A3 | Free-running "not wired in" (4 sites) | WRONG |
| A4 | Config loads from DB (it loads from JSON) | WRONG |
| A5 | `PHASE 0 PLAN.md` internally inconsistent | JUDGEMENT |
| A6 | Stale measurements and counts | STALE |
| A7 | Undocumented routes, env var, GUI, `alembic/` | MISSING |
| A8 | `LOCALIZATION.md` `--locale` clobbers English | WRONG, harmful |
| B1 | Test counts (4 docs) | JUDGEMENT — how to stop the drift |
| C1 | What a snag is | WRONG, conceptual |
| C2 | Snag clamps temperature to 100, not "moderate/focused" | WRONG, conceptual |
| C3–C5 | Trace event types, bond facets, codelet count, and 12 more | WRONG / IMPRECISE |
| D1–D8 | Vertical bridges, extrinsic clauses, dominance, Trace-vs-Themespace, and more | WRONG / IMPRECISE |
| E0 | **A destructive request was issued against the dev database** | — |
| E1–E10 | 35 API/UX findings | BROKEN / UNREACHABLE / MISMATCH |
| F | `CLAUDE.md` inventory tables | MISSING / IMPRECISE |

---

## G. `TESTING.md` and `LOCALIZATION.md`

Totals independently re-derived three times, converging: per-layer `--collect-only`
(662/298/43/164), `945 + 207 + 15`, and the full documented command —
**`1167 passed in 29m47s`, 0 skipped**.

### G1. RETRACTED — "a couple of minutes" is accurate, and the *reason* given is not

This was reported as an order-of-magnitude error and then **withdrawn on further
measurement**, which is worth recording rather than deleting.

The full documented command measured **`1167 passed in 29m47s`** — *longer* than the
doc's 24 minutes, not shorter. The original finding inferred staleness from the oracle
dropping to ~65 s, but the oracle is only ~4% of the suite, and the fast per-layer numbers
it was compared against had been taken with `PETACAT_NUMERIC_BACKEND=off`. Not comparable.
`TESTING.md:30-35` is accurate as written, caveat included.

**What is worth adding**, and is a real gap: `TESTING.md:30` attributes the cost to "the
expected-range check alone is ~1,300 engine runs", which is now ~65 s of a ~30 minute run.
The actual cost driver is the **default GPU backend on the unit and module layers** — the
8–9× penalty `README.md:478` already documents. `PETACAT_NUMERIC_BACKEND=off` turns a
30-minute suite into roughly four minutes, and **no document says so**.

**Decision:** NO ACTION on the retraction; the cost driver it surfaced is fixed — `TESTING.md` names the numeric substrate and `PETACAT_NUMERIC_BACKEND=off`.

### G2. The oracle's GPU pinning is undocumented — and it is mine

`tests/support/expected_range.py:208` forces pool workers onto `numpy` before any engine
object exists, because ~10 spawned Metal contexts intermittently deadlocked the pool
(observed: 4h17m, zero output). `PETACAT_ORACLE_ALLOW_GPU` and
`PETACAT_NUMERIC_BACKEND_WORKERS` appear in no document. **A hung oracle looks exactly
like a slow one**, which is precisely why it needs saying.

Also undocumented: `PETACAT_RANGE_RUNS`, `PETACAT_RANGE_WORKERS`, `PETACAT_RNG_RANGE_RUNS`.
`PETACAT_RANGE_RUNS=1000` is the documented way to do the "re-sample deeply" that
`TESTING.md:122` instructs — with no way given to do it.

### G3. The 162-test frontend suite is absent from `TESTING.md`

The file opens "how Petacat's **backend** tests are written", so this is arguably by
design — but two Vitest suites (`HelpPopover.test.tsx`, `SearchPalette.test.tsx`) are
guardrails for the localisation system `LOCALIZATION.md:167` enumerates, and are missing
from that list too.

### G4. Smaller `TESTING.md` items

`:37` "the one place the suite runs codelets concurrently" — four other files thread over
engine state (`test_coderack_shards`, `test_access_sets`, `test_run_identifiers`,
`test_splittable_rng`); only codelet *execution* is unique · `:92` "the one that matters" —
**three** functions carry `slow`, expanding to 15; the other two guard the RNG range and
the "MLX stays optional" invariant · `:16` integration scope omits help-topic drift.

**Verified true and worth keeping:** "nothing skipped" (0 skipped, nine conditional skips
traced, none fired) and "green under every backend including `mlx`" (15 passed).

### G5. `LOCALIZATION.md` — five findings

Beyond **A8** (`--locale fr` clobbers the English artefacts): `:169` "three layers" → four ·
`:188` describes the sync test as bidirectional; it is one-way substring containment, so a
*removed* JSON topic left in the TS file still passes · `:91-95` says all three sync paths
upsert the database; only two do — the CLI never touches Postgres · `:153` omits
`metadata.related` and `metadata.dissertation_ref` from the do-not-translate list ·
`:36,210` documents two `/api/docs` routes; there are seven, and `SearchPalette.tsx` uses
`/search`, which appears nowhere.

**Decision:** G1-G4 fixed; G5 closed as moot.

- **G1** — `TESTING.md:28` now names the numeric substrate as the dominant cost, with
  `PETACAT_NUMERIC_BACKEND=off` bringing a 30-minute suite to roughly four minutes.
- **G2** — a new "The oracle's environment" section tabulates
  `PETACAT_NUMERIC_BACKEND_WORKERS`, `PETACAT_ORACLE_ALLOW_GPU`, `PETACAT_RANGE_RUNS`,
  `PETACAT_RANGE_WORKERS` and `PETACAT_RNG_RANGE_RUNS`, states that the pool's workers run
  on the NumPy backend so each holds one CPU numeric context, and points at
  `PETACAT_RANGE_RUNS=1000` for the deep re-sample the baseline section calls for.
- **G3** — a "The client suite" section names what it covers and how to run it.
- **G4** — `test_free_running.py` is described as the one place *codelets* run
  concurrently, naming the four files that thread over engine state without executing
  codelets; three functions are stated to carry `slow`, expanding to 15; the integration
  row includes help-topic drift.
- **G5** — `LOCALIZATION.md` is not part of the project, so its five findings do not apply.
  `HelpPopover.test.tsx` and `SearchPalette.test.tsx` guard the help pipeline, which the
  client-suite section now covers.

---

## H. Tests — final audit

### H1. My oracle fix broke the free-threaded suite — **CODE, not DOC**

`TESTING.md:136`, `README.md:326`, `CLAUDE.md:710` all give
`PYTHON_GIL=0 .venv-ft/bin/python -m pytest tests/ -q`. Under it, **13 of the 15 `slow`
tests now fail**:

```
BackendUnavailable: numeric backend 'numpy' is not available;
available backends are ['python']
```

`tests/support/expected_range.py:237` — my pool-worker pin — selects the backend **by
name**, and `.venv-ft` has no NumPy. Verified workaround:
`PETACAT_NUMERIC_BACKEND_WORKERS=python` → `13 passed in 67.55s`.
Non-slow is green there: `1098 passed, 18 skipped`.

This also falsifies `TESTING.md:153-155` — "tests that need a specific backend **skip
rather than fail** when it is unavailable" — which was true before I changed it.

**This is a code fix, not a doc fix:** `_init_worker` should *prefer* a CPU backend and
fall back, rather than demand one by name. I have not made it, because you asked to see
everything first.

**Decision:** RESOLVED — `_init_worker` resolves its backend from a candidate list, and the pool now raises `SampleWorkerLost` naming the vanished PID. The hang was a lost pool worker, not Metal: 7,800 GPU runs across four campaigns produced no stall.

### H2. `TESTING.md:14` — "None — all collaborators mocked" is false for 46% of the layer

**302 of 662 unit tests, across 14 files**, load real `seed_data/*.json`, drive full
`init_mcat`/`run_mcat` runs, or import `server.main` / `server.models`. Largest offenders:
`test_numeric_backends.py` (50), `test_coderack_eviction.py` (48),
`test_codelet_behaviours.py` (41), `test_engine_purity.py` (34), `test_formulas.py` (31).

**JUDGEMENT:** soften the column to "engine objects and seed data permitted; no DB/HTTP",
or promote the 14 files to `module/`. As written the table is contradicted by nearly half
its own layer — and `TESTING.md`'s own P4 (`:264`) already concedes two of them.

**Decision:** RESOLVED — new layers, not a softened rule: the test code is reorganised so every row of the layer table is true of every test in it.

### H3. `admitted_states` is documented as half a mechanism

`TESTING.md:121-126` says to admit a state under `admitted_states` and that
`build_expected_range.py` carries it through. But `check_problem`
(`tests/support/expected_range.py:401`) reads **only** `expected_range` — a hand-added
`admitted_states` entry changes nothing until the baseline is rebuilt. All 9 admitted
states across 6 problems are currently *also* present in `expected_range`, which is why
this has never bitten.

**Decision:** RESOLVED — code and documentation. `admitted_range`
(`tests/support/expected_range.py:612`) unions `expected_range` with `admitted_states`, so an
adjudication takes effect on the next run. `TESTING.md` now states the two outcomes the
oracle distinguishes — a missing p50 state fails as a regression, a novel state is reported
for adjudication with the problem, state, backend, sample size and re-sample command — and
names `admitted_states` as where a ruling is written, read on the next run and carried
through a rebuild.

### H4. Smaller items

`TESTING.md:32` "24 minutes" predates the worker pinning — the oracle alone is now ~65 s ·
`:98` "the one that matters" — 15 slow tests from **three** functions, not one ·
`:264` P4 is **done** but unticked (0 vacuous assertions remain in
`test_codelet_behaviours.py`) · **44 of 57 backend test files are named in no document**,
including `test_answer_comparison.py` (37), `test_thematic_scouting.py` (20),
`test_dissertation_parity.py` · `PETACAT_RANGE_RUNS` / `PETACAT_RANGE_WORKERS` documented
only inside a test docstring.

**`PHASE 0 PLAN.md:17,628,663`** ("590 passing", "797 passed") are ~2× low but are
explicitly pinned to baseline `2c5c086` and are the evidence for WP2.1/2.2. **Recommend
KEEP** — silently updating them destroys what they record. Line `:663` ("suite green under
free-threading") deserves a footnote given **H1**.

**Decision:** RESOLVED — P4 ticked, `PHASE 0 PLAN.md:677` carries an as-built note, the pinned baseline counts kept as evidence, and the test-file inventory lands with the layer reorganisation.

### H5. A note on this audit's own conditions

The docs changed *during* the audit: I corrected the counts and the Fast Run text, then
reverted both when you asked to review everything first. One agent snapshotted the files
mid-flight and worked against the snapshot. Line numbers in this document were taken after
the revert and should hold, but re-check before editing.

**Decision:** NO ACTION — a note on the audit's conditions. Every edit made from this ledger located its anchor by content and asserted the old text was present before replacing it, so a moved line number surfaces as a failed edit rather than a wrong one.

### H6. Verified correct — do not "fix"

The mlx/free-running note (`test_free_running.py`: 15 passed under `mlx`, `mlx-cpu`,
`numpy`, `python` and `off`) · the `PYTHON_GIL=0` rationale, confirmed by observing
`sys._is_gil_enabled()` flip · `tests/support/` imported but never collected · e2e skipping
without Postgres · the advisory lock (two concurrent sessions ran throughout this audit
with no schema collision) · the oracle's 13 problems / 410,000-run baseline and its ~1%
novel-state estimate · every test file named in the docs exists.

**Decision:** NO ACTION — this entry records what the audit checked and found correct.

---

## Z. Held to the end

### Z1. Test counts in four documents

**Severity:** STALE. Measured with `pytest --collect-only` per layer.

**Held to the end of the review**, so the numbers are taken once, after every other item has
finished changing the suite.

| Layer | Doc claims | Actual |
|---|---|---|
| `unit/` | 601 | **663** |
| `module/` | 282 | **299** |
| `integration/` | 43 | 43 — correct |
| `e2e/` | 123 | **164** |
| total | "1,049 tests" | **1,169** (15 marked `slow`) |

Sites: `CLAUDE.md:632-637`, `TESTING.md:14-17`, `TESTING.md:23`, `README.md:28`,
`README.md:300`.

**JUDGEMENT — worth deciding once, for all counts.** A number in prose goes stale the
next time anyone adds a test, and this is at least the second time these have drifted.
Options:

- **(a)** Update the numbers now and accept they will drift again.
- **(b)** Update them and add a test that asserts the documented totals match reality, so
  drift fails the suite rather than misleading a reader. Cheap: the counts are already
  available from `--collect-only`.
- **(c)** Replace exact counts with the shape of the suite ("four layers, ~1,200 tests")
  and keep exact numbers only in `TESTING.md`, where one assertion can guard them.

**Decision:** RESOLVED — suite total **1,533**; unit 338, seed_unit 261, module 626, architecture 34,
integration 65, e2e 209, plus 316 client tests across 23 files. Corrected in `TESTING.md`,
`README.md` and `CLAUDE.md`. Guarded rather than restated: `tests/integration/
test_documented_counts.py` checks every layer count, suite total and inventory row against
`session.items` on a full-suite run, and `test_documented_code_shape.py` checks the engine's
module and line counts, the session-taking endpoint count, `builtins.py`'s size and the Run
Controls group count against the sentences that state them. Wall-clock figures and the
per-seed codelet count are deliberately unguarded, and the files say why.
