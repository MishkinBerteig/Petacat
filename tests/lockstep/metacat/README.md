# Metacat decision-trace recorder

Metacat side of the lockstep harness (`meta-peta-trace-idea.md` sections 3, 4, 5, 8;
`tests/lockstep/DECISIONS.md`).  It records every non-trivial random decision of a
headless Metacat 1.2 run as JSON lines.  It writes records only: it draws no random
number of its own and changes nothing Metacat computes.

| File | Purpose |
| --- | --- |
| `record.py` | CLI (plain `python3`, stdlib only): builds the patched source, writes a driver per problem and seed, runs Docker, gzips the trace |
| `recorder.patch` | Unified diff against `Metacat/build/source` (8 files, about 50 added lines) |
| `decision-trace.ss` | Run-time wrappers, JSON writer, canonical names, `trace-open`, `trace-run`, snapshots, `dump-opening-names` |
| `record_verbose.py` | CLI: the console output of runs with Metacat's Verbose mode (`%verbose%`) on, one `@@RUN` ... `@@END` block per run; compared with Petacat's narration by `scripts/compare_verbose.py` (`python3 tests/lockstep/metacat/record_verbose.py abc abd xyz 1-5 [--answer A] [--episode N]`) |
| `random-audit.ss` | Debug only: shadows `random` to find raw draws attributed to no decision |
| `opening-names.abc-abd-xyz.json` | Canonical names of every letter, description and slipnet node of the opening state (95 names, sorted) |

## Recording

```sh
python3 tests/lockstep/metacat/record.py --problem abc abd xyz --seeds 1-10   # default out: tests/lockstep/traces
python3 tests/lockstep/metacat/record.py --seeds 1,5,10600000-10600004 --cap 100000 --jobs 4 --no-snapshots
python3 tests/lockstep/metacat/record.py --names                    # rewrite opening-names.<slug>.json
python3 tests/lockstep/metacat/record.py --seeds 1-5 --baseline     # collector-style run without the recorder patch, on build/source as it is; prints answer + codelets
python3 tests/lockstep/metacat/record.py --seeds 1-3 --audit        # raw-draw audit (prints AUDIT lines; trace unchanged)
```

Output: `<out>/<slug>/<seed>.metacat.jsonl.gz`, slug = the three strings joined by `-`.  Seeds
start at 1.  The gzip header has mtime 0, so equal traces are equal bytes.  `--keep-plain`
also keeps the `.jsonl`.

**Which Metacat.** `Metacat/build/source` is either the reference reconstruction or the
reference with the bundle's second patch group, the known-failure fixes
(`Metacat/README.md`, "Optional: the known-failure fixes").  The recorder checks which
with `Metacat/tools/reconstruct.py` and refuses a tree that is neither.  By default it
records whichever `build/source` is.  `--reference` and `--known-failures-patch` choose one
explicitly, adding or taking off the fixes on its copy, never on `build/source`.  The copy
is `Metacat/build/recorder-source` for the reference and `Metacat/build/recorder-source-kf`
with the fixes; each is rebuilt when `recorder.patch` or `Metacat/manifest.json` changes.
The trace header's `revision` names the manifest's hash and, with the fixes, ends in
`+known-failure-fixes`.  The two variants record byte-identical traces except on the three
crash seeds.
Both are git-ignored.  To change the patch: edit `recorder-source`, then regenerate with
`diff -u` against `build/source` using `a/` and `b/` path prefixes (applied with `patch -p1`).

Each run is one `docker run --rm --platform linux/amd64 --network none` container
(`--entrypoint env ... scheme -q --script`; the image's default entrypoint starts the GUI).
The driver is the spec 5.2 sketch: `trace-open`, `(tell *memory* 'clear)`, `init-mcat`,
`(set! *break-time* cap)`, `trace-run`.  `trace-run` overrides `suspend` and `break`, turns
unrecognised-message halts and any other error into an `end` record with reason `error`,
and prints `RESULT <answer|*CAP*|*NONE*|*ERROR*> <codelet count>` (the collector's vocabulary).

## Episodes and justify mode

```sh
python3 tests/lockstep/metacat/record.py --problem abc abd xyz --seeds 1-5 --episode-runs 8   # 5 episodes of 8 runs
python3 tests/lockstep/metacat/record.py --problem abc abd xyz --answer wyz --seeds 1-5       # justify mode
python3 tests/lockstep/metacat/record.py --problem abc abd xyz --seeds 1-5 --episode-runs 8 --baseline   # unpatched check
```

* `--episode-runs N`: one Metacat process runs N runs of the problem; `(tell *memory* 'clear)` only before run 1
  (`init-mcat` keeps memory, `run.ss:212-213`).  Run k (1-based) uses seed `S + k - 1`, S being the episode seed
  (`--seeds`): the convention of `studies/episodic-v2/collector.ss.in`.  Each run writes its own trace
  `<out>/episodes/<slug>/<S>.r<k>.metacat.jsonl.gz` whose header has `seed` = S+k-1, `episode_run` = k and
  `episode_seed` = S.  A run that ends in an error ends the episode (later runs are not recorded).  In an episode
  the `end` record's `reason` is `answer` only if memory *gained* an answer during this run (memory carries
  earlier runs' answers).
* `--answer A`: justify mode.  The GUI sets `%justify-mode%` from a four-part problem (`gui.ss:752`); the driver
  sets it directly, then passes `'A` to `init-mcat`.  The slug gets the answer (`abc-abd-xyz-wyz`), the traces go
  under `<out>/justify/<slug>/<seed>.metacat.jsonl.gz` (episodes + answer: `episodes-justify/`), and the header
  carries `answer`.  Neither option changes the default layout, and recordings made without them are byte-identical
  to those made before the options existed.
* `decision-trace.ss`: `*tr-header-extra*` (header fields spliced after `cap`), `*tr-failed?*`, `*tr-answers-before*`.
* Validation: `--baseline` runs the unpatched collector-style loop and prints the same `RESULT answer/codelets`
  sequence; the recorder must match it, run for run.

## Record format

Spec section 3 exactly.  Field order: `t, c, ctx, who, [u], n, [about], [scope], kind,
<kind fields>, site`.  Numbers are `exact->inexact` floats written in shortest round-trip form.

* `header`: `format` 1, `engine` `metacat`, `revision` = `metacat-bundle-manifest-sha256:<hash of Metacat/manifest.json>`, `problem`, `seed`, `cap`, `settings` `{recorder, snapshots}`.
* `end`: `c`, `reason` (`answer`, `give-up`, `cap`, `error`), `answer` (reason `answer`), `error` (message), and `codelets` = Metacat's `*codelet-count*` when the run stopped (what the collector reports).  `c` is the number of the codelet that ended the run: an answer or give-up ends *inside* codelet `codelets + 1`; a cap ends after codelet `codelets`.
* `c` = `*codelet-count*` + 1 while a codelet runs or is being chosen; an update cycle run from `run-mcat` carries the count after the codelet it follows; an update cycle run inside a codelet (answer, give-up, snag) carries that codelet's `c`, and the codelet's context (including `n`) resumes afterwards.
* `ctx` values used: `init` (`who` `init-mcat`), `choose` (`who` `coderack`), `codelet` (`who` = the codelet type name), `update` (`who` = phase), `other` (`who` `run-mcat`; between a codelet and the next choice; never produced by a normal run).
* Phases (`who` of an update unit): `rules-possible`, `workspace-values`, `snag-exit`, `clamp-expiry`, `themespace`, `slipnet`, `temperature`, `post-bottom-up`, `post-top-down`, `post-deferred`.  `u` counts update cycles from 1, including those inside codelets.
* `n` counts logged decisions in a unit, from 0.  Trivial decisions are not logged and consume no `n`.
* `site` is `<helper>@<who>`: `prob?`, `~`, `random-pick`, `stochastic-pick`, `stochastic-select`, `stochastic-if*`, `random` (the `int`), `choose-codelet`, `evict`.  It never names the enclosing procedure (Scheme cannot tell cheaply); never compared.
* Trivial (not logged): fewer than two options after dropping zero weights; `prob` with p <= 0 or >= 1; `int` with bound <= 1; `perturb` with bound 1.  Zero-weight options are dropped; if every weight is zero the choice is uniform over all options and `weights` is omitted.  `perturb` `bound` is `(round (sqrt n)) + 1`, `integer` is always `true`.

### What each hook does

| Hook | Where | Effect |
| --- | --- | --- |
| `prob?`, `~`, `random-pick`, `stochastic-pick`, `stochastic-select` | `set!` at run time (`decision-trace.ss`) | Outermost call logs on completion (`prob`, `perturb`, `choice`); a depth counter silences nested helper calls (`~` -> `prob?`, `stochastic-pick` -> `random-pick`) |
| `stochastic-if*` | macro in `syntactic-sugar.ss` | Coin drawn first as before, then `p`, then `trace-hook-if p result` (a macro cannot be wrapped at run time) |
| `'choose-codelet` | `coderack.ss` | One `choice` (`ctx` `choose`, `who` `coderack`) over every codelet in `codelet-list` order, weight = its bin's urgency at the current temperature, plus `stamps`/`picked_stamp`; the two inner draws are suppressed |
| `'delete-codelets` | `coderack.ss` | One `choice` per eviction over `codelet-list` with `'get-removal-weight`, same `stamps`; `site` `evict@<who>`, unit unchanged |
| codelet `'run` | `coderack.ss` | Sets `c`/`who`; top-down scouts get `scope` = name of their second argument |
| `rules.ss:582` | `(add1 (trace-hook-int (length bridges)))` | `int` record, `result` is the raw 0-based draw |
| `update-everything` | `run.ss` | Names each phase before it runs; snapshot after `post-deferred` |
| `get-local-density` (bonds, groups) | bonds.ss, groups.ss | `about` = the bond or group, restored afterwards |
| posting loops, node and theme coins | `coderack.ss`, `slipnet.ss`, `themes.ss` | `about` for the section 5.4 phases (below) |
| codelet `get-arguments` | `coderack.ss` | New accessor so a codelet can be named |

`about` conventions: `workspace-values`: the bond or group (also inside codelets and `wins-fight?`);
`slipnet`: the node name (`successor`) for the 50-99 coin, the theme name for theme coins;
`post-bottom-up`: the codelet type name; `post-top-down`: `<type>(<node>)` for node posting
(for example `top-down-bond-scout:category(successor)`), the bare type name for the thematic
codelet types.

## Canonical names

Section 4 with the DECISIONS.md clarifications.  Concrete conventions the Petacat side needs:

* Slipnet node: `get-lowercase-name`, i.e. the node name without `plato-` (`successor`, `predgrp`, `succgrp`, `samegrp`, `letter-category`, `alphabetic-first`).  Group categories are those nodes (`predgrp`, not `predecessor-group`).
* Roles `i m t a`.  Letter `t.2`.  String `string(t)`.  Workspace (a top-down scope) `workspace`.
* Group `group(i.0-2,succgrp,right,letter-category)`, `-` for no direction (`group(t.0-1,samegrp,-,letter-category)`).
* Description `desc(i.0,letter-category,a)`; a group's description `desc(group(...),length,two)`.
* Bond `bond(from,to,category,facet)`; a bond with no direction (sameness) lists its ends left to right.
* Bridge `bridge(top|vertical,object1,object2)` (type symbol as Metacat writes it).
* Concept mapping `cm(type,descriptor1,label,descriptor2)`, `-` for no label.
* Rule `rule(top,<clauses>)` where `<clauses>` is the rule's clause *list* printed as an s-expression with single spaces, nodes by name, symbols as written, and the list parentheses always present: `rule(top,((intrinsic ((letter string-position-category rightmost)) ((self letter-category successor)))))`.  (The spec example drops the outer list and the object-description list parentheses; the real data structure has both.)  An empty clause list is `rule(top,())`.
* Theme `theme(top-bridge,letter-category,successor)`, `different` for no relation.  Theme cluster (not in the spec) `cluster(top-bridge,letter-category)`.
* Codelet `<type>(<first argument>)`, or the bare type when it has no argument: `bond-evaluator(bond(i.0,i.1,successor,letter-category))`, `top-down-bond-scout:category(successor)`, `bottom-up-bond-scout`.  The scope of a top-down scout is not part of the name (logged in `scope`).  Type names are Metacat's: `bottom-up-bond-scout`, `top-down-group-scout:direction`, `group-scout:whole-string`, `rule-scout`, `important-object-bridge-scout`, `progress-watcher`, `jootser`, `breaker`, ...
* `stochastic-select` options are named after the second element of each `(weight object conditions)` entry (the object); the `conditions` list is not part of the option.  Its only user in a normal run is the thematic bridge scout.
* A list option is `(a,b,c)`.  Numbers by value (`3`, `2.5`; integer-valued floats as integers).  Booleans `true`/`false`.  Anything unnamed is `?<type>:...` (none occurred in about 60 recorded runs).
* Names of objects are cached in a weak table; they are immutable for every object type named.

## Snapshots (section 8)

One record at the end of every update cycle (after `post-deferred`), keyed by `u`, with `c`:

```
temperature  {value, clamped}
slipnet      {node: [activation, frozen]}                       all 59 nodes, node order
themes       {theme(...): activation}                           all 75 themes
coderack     {codelets: [[name, bin 0-6, time-stamp]...],       bin order, then Metacat's bin list order
              clamped: [codelet type...]}
structures   {bonds|groups|bridges|rules|descriptions: [[name, strength]...],
              proposed: {bonds|groups|bridges: [name...]}}      built = proposal level 3; descriptions = 'get-descriptions of every built object
trace        {events: {type: count}, snag: bool, clamp: bool}
```

## Runtime findings (Chez 9.5.4, amd64 container)

* **Argument order is not left to right.**  `(g (f 1) (f 2) (f 3))` evaluates 3, 1, 2; four arguments 3, 4, 1, 2; `let` bindings 3, 1, 2 (but `let*` is sequential).  `map` (and `filter`) evaluate a single list in swapped pairs from the right: `(map f '(1 2 3 4 5 6 7 8))` calls f on 7 8 5 6 3 4 1 2; two-list `map` runs back to front (33 44 11 22).  `for-each` and `andmap` are left to right.  Metacat draws inside such `map`s and arguments follow this order, which is why the comparer must pair by content.
* **`set!` of a helper reaches code loaded earlier** (checked with a `load`ed file, and in the real tree: every wrapped helper logs).  No fallback to patching the helpers was needed.  `set!` of the primitive `random` is refused (immutable), but a top-level `(define random ...)` made *before* loading Metacat shadows it for everything loaded afterwards; `random-audit.ss` uses that.

## Raw-draw audit

Every use found by grepping the whole tree (graphics and GUI files contain none; `gui.ss:744-749` only calls `random-seed`/`randomize` for GUI-chosen seeds, and `run.ss:192` seeds the generator):

| Site | Handling |
| --- | --- |
| `utilities.ss:466` `prob?` (and its users: `stochastic-filter`, `answers.ss:1365`, `slipnet.ss:110,272`, `rules.ss:592,605`, `themes.ss:779,924,993`) | wrapper, `prob` |
| `utilities.ss:470` `~` (only user `workspace.ss:686-687`, `about` = codelet type in `post-*`) | wrapper, `perturb`; inner `prob?` and `random` silenced |
| `utilities.ss:479` `random-pick` (`breakers.ss:30`, `groups.ss:567`, `rules.ss:400,417`, `coderack.ss:395` deferred-codelet overflow, `workspace-strings.ss:100`, `bounded-random-partition`) | wrapper, uniform `choice` |
| `utilities.ss:490` `stochastic-pick` (and `-by-method`, about 40 call sites) | wrapper, `choice`; `-by-method` is not wrapped (its inner pick logs) |
| `utilities.ss:522` `stochastic-select` (`themes.ss:869`) | wrapper, `choice` |
| `syntactic-sugar.ss:125` `stochastic-if*` coin (about 30 sites in 13 files) | patched macro, `prob` |
| `coderack.ss:419` `stochastic-pick-by-method bins` + `coderack.ss:308` `(random current-index)` | composite `choose-codelet`; both draws suppressed |
| `coderack.ss:438` `stochastic-pick-by-method codelet-list` | composite eviction |
| `rules.ss:582` `(random (length bridges))` | patched, `int` |
| `utilities.ss:459` `randomize`, `run.ss:192` `random-seed`, `gui.ss` | not draws in a headless run |

Audit run (`--audit`, shadowing `random` before loading Metacat; counts a draw as accounted
for when it happens inside a wrapper, a suppressed composite, the `int` hook, or is claimed by
the following `stochastic-if*` hook): `abc abd xyz` seeds 1-3 (12,090 / 32,034 / 22,176 raw
draws), and seeds 1-4 of `abc abd iijjkk`, `aabc aabd ijkk`, `abc abd mrrjjj`, `abc cba xyz`,
`abc aabbcc kkjjii` (up to 268,400 draws): **0 stray draws, 0 orphan hooks**.  A deliberate
extra `(random 5)` is reported as a stray (negative control).  Audit mode produces
byte-identical traces.

## Checks run

* Recorder changes nothing: `abc abd xyz` seeds 10600000-10600004 (the seeds in the published
  `support-v1a` data, `main/chunks/construction/run4`) give `*NONE*` 3718, `dyz` 2630, `xyd` 1575,
  `xyz` 1878, `xyd` 3619 codelets, all equal to the published values, from both the unpatched
  collector-style driver and the recorder.  Seeds 1-5 (not in the study) give `xyz` 1331, `xyd` 3514, `yyz` 2427,
  `xyz` 361, `xyz` 2624 from both.  Another 20 seeds over five other problems also matched the unpatched driver, and the
  three `KNOWN-FAILURES.md` seeds reached the same codelet counts (2835, 2088) with reason `error`.
* Repeatability: seeds 1 and 2 recorded twice (different `--jobs`) are byte-identical gzip files.
* Measured size and time (Rosetta, one container per run, includes about 1 s start-up): 361-3514 codelets take 1.2-10 s;
  gzipped size is 0.10-1.04 MB with snapshots and 0.07-0.73 MB without (raw 4-41 MB; about 12 KB raw and 0.3 KB gzipped per
  codelet).  Codelet-choice and eviction records (whole rack) are about 85% of the raw bytes, snapshots about 6%.  Extrapolating
  to a run that reaches the 100,000-codelet cap: about 1 GB raw, 30 MB gzipped, a few minutes.


## The three reference crashes

`Metacat/KNOWN-FAILURES.md` lists three seeds on which Metacat itself crashes:
`abc cba mrrjjj` seeds 20713988 and 20716342, and `abc aabbcc kkjjii` seed 20226148.
The reference reconstruction behind the published studies is not changed.  The bundle's
second patch group, `Metacat/patches/fixes/0001-known-failures.patch`, fixes the two
causes, and Metacat's `CODE-FIXES.md` (§1.3 once applied) and `KNOWN-FAILURES.md`
describe it.

Both variants are recorded and committed:

```sh
python3 tests/lockstep/metacat/record.py --reference --problem abc cba mrrjjj \
    --seeds 20713988,20716342 --out tests/lockstep/traces-known-failures/reference
python3 tests/lockstep/metacat/record.py --known-failures-patch --problem abc cba mrrjjj \
    --seeds 20713988,20716342 --out tests/lockstep/traces-known-failures/fixes
# and the same for abc aabbcc kkjjii, seed 20226148
```

- **Reference.** Each trace ends with an `end` record of reason `error`.  The comparer
  registers each one as a reference crash (`known_divergences.toml`,
  `match.class = "reference-crash"`).  Petacat replays them in lockstep to each crash
  point.
- **Fixes.** The runs answer `rrjjjm`, `rrjjjm` and `kji`.  Petacat replays them to the end
  with no differences:
  `.venv/bin/python scripts/lockstep_corpus.py --traces tests/lockstep/traces-known-failures/fixes`.

Every other recorded run, across the development, held-out and justify corpora, gives a
byte-identical trace with and without the fixes, apart from the header's `revision`
(`Metacat/VALIDATION.md`).

## Translation logs: `record_translation.py`

`record_translation.py I M T LO-HI [--answer A] [--cap N] [--out DIR]` runs the seeds in the
container (justify mode with `--answer`) and, for every answer and snag event, reads the
slippage log Metacat's rule translation made (`answers.ss:1198`), the supporting vertical
bridges, the rules' reference objects and, for an answer, the supporting groups.  It draws
nothing.  `scripts/compare_translation_log.py` records with it, replays the same runs in
Petacat and compares field by field; `scripts/compare_translation_log.py --fixture`
regenerates `tests/lockstep/translation_log_metacat.tsv`, which
`tests/lockstep/test_translation_log.py` checks.

```sh
scripts/compare_translation_log.py abc-abd-xyz 1-10
scripts/compare_translation_log.py abc-abd-xyz-wyz 1-5 --justify
scripts/compare_translation_log.py --fixture
```

## Rule English and event names

Two more wrap-and-log recorders, built on `wrap.py` (the shared driver prelude and container
runner).  Each runs the *unpatched* `Metacat/build/source`, wraps Metacat procedures from the
driver, prints tab-separated records and changes nothing Metacat computes.  The comparers are in
`scripts/`; both need Docker and the `metacat:1.2` image, and read the lockstep traces
(`record.py`) to replay the same runs in Petacat.

| Recorder | Wraps | Comparer | Fixture it regenerates |
| --- | --- | --- | --- |
| `record_rule_english.py I M T LO-HI` | `transcribe-to-english` (`rules.ss`), once per rule built | `scripts/compare_rule_english.py` | `tests/seed_unit/rule_english_metacat.tsv` |
| `record_events.py I M T LO-HI [--answer A]` | nothing is wrapped: after each run, asks every event of `*trace*` for `'print-name` and for the header its `'display-workspace` sends to `draw-event-header` | `scripts/compare_events.py` | `tests/lockstep/event_names_metacat.tsv` |

**Rule English** (463 rows; 12,582 Metacat rules over the 19 development problems, seeds 1-10;
the list, with four widening entries, is `tests/seed_unit/rule_english_problems.txt`).

```sh
python3 tests/lockstep/metacat/record_rule_english.py --problems tests/seed_unit/rule_english_problems.txt \
    --jobs 2 --table tests/lockstep/out/rule_english_metacat.tsv     # about 40 s, byte-identical to the fixture
.venv/bin/python scripts/compare_rule_english.py --jobs 2              # Petacat against Metacat, about 7 min
```

Expected: every replayed run reports `N/N Metacat rules matched (0 text mismatches, 0 unpaired,
0 Petacat extra)`.  Runs with no committed trace (the problems `wxyz vxyz abcd`, `abc abd iijjkk`
and seeds 11-30 of two others) are run live in Petacat instead, and are compared by structure
(the set of texts for each rule structure both sides built), because a live run does not
reproduce Metacat's rules one for one (a weak check: only a handful of structures coincide).  Result: 12,582 of 12,582 matched, 23 problem entries.  The recorder's clause key spells a rule's clauses as
`V[letters]`, `X[object-descriptions][dimensions]`, `I[object-description][referent:dimension:relation;...]`
joined by `&&`; the table drops `plato-`.

**Event names and headers** (131 events in the eight runs of `tests/lockstep/event_names_runs.txt`).

```sh
.venv/bin/python scripts/compare_events.py --jobs 2 --table tests/lockstep/out/event_names_metacat.tsv   # about 30 s
.venv/bin/python scripts/compare_events.py --corpus --jobs 2                                              # every committed trace, about 13 min
.venv/bin/python scripts/compare_events.py --corpus --pick 3500 30000 --table tests/lockstep/out/picked.tsv   # re-choose the runs
```

Expected: `8 runs: 8 identical, 131/131 events identical`, and a table byte-identical to the
fixture.  Metacat runs a few codelets past an answer before the driver's suspend lands, so the
comparison keeps Metacat's events up to the codelet Petacat's replay ended at.  `--corpus`
compares the discovery corpus (seeds 1-10) and justify corpus (seeds 1-5) in full: 275 runs, 3,757 of 3,757 events identical.  `--pick 3500 30000` re-chooses exactly the fixture's eight runs.

## Answer-frequency study: `record_frequencies.py`

Metacat's answer, codelet count and final temperature for many seeds of one problem, many
seeds per container (`wrap.py` supplies the driver prelude and the Docker call).  This is
the Metacat side of the 1,000-run study of `wxyz -> vxyz; abcd -> ?` (seeds 101-1100) and of
the fidelity net's single runs; `scripts/compare_frequencies.py` is the other half.

```sh
python3 tests/lockstep/metacat/record_frequencies.py wxyz vxyz abcd 101-1100 --jobs 4   # cap 100000
python3 tests/lockstep/metacat/record_frequencies.py abc abd aabbcc 1-10 --cap 4000     # fidelity-net runs
```

Output `tests/lockstep/out/frequencies/<i>-<m>-<t>.<lo>-<hi>.cap<cap>.metacat.tsv` (git-ignored; `--out`
changes the root): `#` header lines, then `seed answer codelets temperature clamped since_snag`
per seed.  `answer` is the print name, `*CAP*`, `*NONE*` or `*ERROR*`.  Byte-identical for a
given problem, seed and cap, and independent of `--jobs`.

Expected (checked): `abc abd aabbcc` seeds 1-10 cap 4000 give `aabbdd` 9 times (the tenth hits
the cap), as the fidelity net recorded; `abc cba abcd` seeds 1-5 give `dcba` 5 of 5.  For
`wxyz vxyz abcd` 101-1100 the recorded study frequencies are `vbcd` 33.6%, no answer 24.3%,
`abce` 14.1%, `abcd` 13.8%, `vxyz` 6.6%, `abcc` 4.4%, `abcv` 2.7%.  Runtime: about 0.45 s per
`wxyz` run per container (40 runs 18 s), so the 1,000-run study is about 7 minutes with
`--jobs 1`, 2-3 minutes with `--jobs 4`.

## Snag explanations, snag sweep and fidelity net: `record_snags.py`, `record_answers.py`

Two more "wrap and log" recorders (they share `wrap.py`: the driver prelude, the container run,
seed and problem-list parsing).  Both run the *unpatched* `Metacat/build/source`, wrap Metacat
procedures from the driver, and print tab-separated lines; nothing is drawn or changed.  Output of
equal arguments is byte-identical.

| File | What it logs | Compared by |
| --- | --- | --- |
| `record_snags.py I M T SEEDS [--cap N]` | per snag: `SNAG` (failure kind and the event's `get-explanation`, wrapping `make-snag-event`) and `CMT` (the two `process-snag` comment lines, via the comment window); `END` per run; memory cleared before each run | `scripts/compare_snags.py` |
| `record_answers.py I M T LO-HI [--cap N]` | one episode (memory cleared once, runs `LO..HI`): per answer in memory `ANS` (`get-snag-explanation`) and `EXPL` (what `explain` writes in both voices), per ordered pair `CMP` (`get-answer-comparison-text`) | `scripts/compare_episode_answers.py` |

```sh
python3 tests/lockstep/metacat/record_snags.py abc zyx xyz 9 --cap 6000          # 4 snags, 1 s
python3 tests/lockstep/metacat/record_answers.py abc abd xyz 1-8                  # 5 answers, 20 comparisons, ~10 s
```

`scripts/compare_snags.py --regenerate-fixture --out DIR` re-records the 8 runs of
`tests/lockstep/snag_explanations_metacat.tsv` with `record_snags.py --cap 6000` and rebuilds
the file byte for byte (apart from the `#` header); see `tests/lockstep/README.md`, "Snag
explanations, snag sweep and fidelity net", for the sweeps built on them.  Both write under
`tests/lockstep/out/` (git-ignored) unless told otherwise.  Unit tests (no Docker):
`tests/lockstep/test_snag_and_answer_tools.py`.
