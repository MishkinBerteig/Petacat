# Testing Guide

This document defines how Petacat's **backend** tests are written and
organised. It exists so that new tests stay consistent, deterministic, and
focused on the research goals of the project.

## The required command

```bash
.venv/bin/python -m pytest tests/ -q
```

This is the command a change is verified with. It runs all eight layers against the
local Postgres, runs every test whose outcome the numeric substrate produces on
**both the CPU and the GPU**, and stops at a **60-minute wall-clock ceiling**. The
matrix and the ceiling are properties of the suite, so this one command carries
them; there is nothing further to remember and nothing to add on the command line.

A tight edit-test loop uses:

```bash
.venv/bin/python -m pytest tests/ -q -m "not slow" --numeric-backends=cpu
```

which drops the expected-range oracle and puts the whole session on one CPU
backend. Verify with the required command before considering a change done.

### The numeric backend matrix

`server/engine/numeric/` computes the engine's arithmetic — activation spreading,
decay, the probabilistic jump, structure strengths, object values, themespace
dynamics, temperature — behind four interchangeable backends, and the default
policy puts a run on the Metal GPU at every Slipnet size. A test whose outcome
that arithmetic produces therefore has two answers worth knowing, and the matrix
runs it once for each:

| Role | Backend | Precision | What the role covers |
|------|---------|-----------|----------------------|
| `cpu` | `numpy`, or `python` where NumPy is absent | float64 | The engine's arithmetic at the reference's precision. Agreement with the pure-Python reference is exact here — same values, same number of random draws — so a seeded run on this half of the matrix is reproducible down to the draw. |
| `gpu` | `mlx` | float32 | The arithmetic as a Petacat run actually executes it, on the Metal cores, in the only precision Apple's GPUs offer. |

The `cpu` role is fillable on every machine, so the matrix always has a float64
half. The `gpu` role appears when MLX is installed and its Metal probe succeeds,
and is reported as not installed otherwise, which is the same skip-rather-than-fail
rule the rest of the suite follows.

**Why float32 diverges on individual runs while the reachable set holds.**
Activations live in [0, 100], and float32 carries about seven significant digits
where float64 carries sixteen. A Slipnet activation that has decayed to a subnormal
survives in float64 and flushes to zero in float32, which changes the
`jump_candidates` list, which changes how many draws the run consumes, which sends
every subsequent probabilistic decision somewhere else. A given seed therefore
reaches a different answer on the GPU than on the CPU. That is right behaviour:
Petacat is stochastic by design, so a different-but-valid run is a correct run, and
the same thing happens whenever a new scheduler or a new generator reorders the
draws. What must hold across the two halves is the **set** of stopping states each
problem can reach. That question is no longer asked of Petacat's own past but of
Metacat's published sets, by `scripts/compare_to_metacat.py` — see
[Regressions](#regressions-what-replaced-the-expected-range-oracle) — which
reports a missing p50 member and a novel one in their own terms rather than as a
pass or a failure.

So the matrix asks each half for what that half can promise. The float64 tests
assert bit-identity where they assert it, and the float32 pass asserts the
properties that survive a forked random stream: that the run completes, that the
structures it builds are coherent, that a captured state restores, that the
concurrency invariants hold.

**Where the line is drawn.** A test is in the matrix when its outcome is produced
by arithmetic the substrate performs — when it drives a real `Slipnet`,
`Themespace`, `Workspace` or `Temperature` update, or a run that does. That is
every module file that assembles and drives the engine, plus the four individual
tests elsewhere that reach a real engine rather than a fake. Everything else runs
once, because the backend cannot reach it: `tests/unit/` computes against fakes,
`tests/seed_unit/` reads shipped values without driving anything, `tests/architecture/`
inspects source, `tests/integration/` compares seed data against the schema and
checks the harness's own rules, and `tests/e2e/` exercises the HTTP and persistence
stack, which adds no numeric path of its own and runs on the policy the
application ships with.

A module opts in with one line beneath its imports:

```python
pytestmark = pytest.mark.numeric_matrix
```

and a single test with `@pytest.mark.numeric_matrix`, which is what
`tests/seed_unit/test_temperature.py`, `tests/module/test_codelet_dsl.py` and
`tests/module/test_codelet_behaviours.py` use.

A matrix module's engine-running fixtures are **function-scoped**. The case's
backend is in force for the duration of the test, so a fixture rebuilt per case
carries that case's backend into the state it hands over. Module-scoped fixtures
in these files hold configuration — a `MetadataProvider`, a seed directory —
which the substrate never touches.

Membership is enforced rather than curated. `tests/conftest.py` wraps
`select_backend` in the four engine modules that consult it and counts each test's
calls; a test in any layer but `tests/e2e/` that
reaches the substrate without the marker is named in the summary and fails the
session, with the line to add. Two files are exempt because they choose backends
themselves and more finely than a role can — `tests/seed_unit/test_numeric_backends.py`
and `tests/module/test_numeric_engine.py` parametrise over *every* installed
backend and separate the exact ones from the inexact one — and so are the `slow`
guards, which set their own worker pools' backend or run an interpreter with MLX
and NumPy made unimportable.

**Running one backend alone.** `--numeric-backends` takes roles (`cpu`, `gpu`),
backend names (`python`, `numpy`, `mlx`, `mlx-cpu`), `all`, or a comma-separated
mixture. Naming a single backend also makes it the session's default, so the tests
outside the matrix take it too and the run is entirely what it says it is.
`PETACAT_TEST_BACKENDS` sets the same thing from the environment.

```bash
.venv/bin/python -m pytest tests/ -q --numeric-backends=gpu     # Metal only
.venv/bin/python -m pytest tests/ -q --numeric-backends=cpu     # float64 only
.venv/bin/python -m pytest tests/ -q --numeric-backends=all     # every backend
```

**What a run reports.** Every session ends with a `petacat test matrix` block:

```
============================= petacat test matrix ==============================
  cpu  numpy    float64    519 tests
  gpu  mlx      float32    519 tests
  whole suite requested: the full matrix is required of this run

  unit           756 collected    756 run    756 passed      0 failed      0 skipped  complete
  seed_unit      626 collected    626 run    593 passed      0 failed     33 skipped  complete
  module        1041 collected   1041 run   1041 passed      0 failed      0 skipped  complete
  architecture    42 collected     42 run     42 passed      0 failed      0 skipped  complete
  integration    203 collected    203 run    203 passed      0 failed      0 skipped  complete
  parallel       244 collected    244 run    244 passed      0 failed      0 skipped  complete
  lockstep       228 collected    228 run    228 passed      0 failed      0 skipped  complete
  e2e            339 collected    339 run    339 passed      0 failed      0 skipped  complete

  run complete in 13.9 min against a 60 min ceiling
```

The first block is what makes "both were run" checkable: it names each backend, its
precision and how many tests took it. A role that no selected test reached says so
on its own line, and so does a role whose backend is not installed.

**Completeness is required of a run that asked for everything.** The required
command asks for the whole suite, so it is held to the whole matrix: if a backend
in the matrix runs none of the selected tests, the session fails with that as the
reason. A deliberate slice asked a narrower question and answers it on the strength
of its own tests — `-m slow`, `-m "not slow"`, `-k`, `--numeric-backends=cpu`, a
single file or node id. Such a run names what narrowed it, names the roles it
exercised, and exits on whether its tests passed:

```
  cpu  numpy    float64      0 tests
  gpu  mlx      float32     14 tests
  cpu  numpy: no selected test ran on it
  narrowed by -k 'mlx': this run reports the roles it exercised and is not held to the full matrix
```

A role whose backend is not installed is never a shortfall, on any run. That is
what keeps MLX an optional dependency: a machine without a GPU holds a one-role
matrix, runs all of it, and stays green.

The rules are pinned by `tests/integration/test_numeric_matrix_harness.py`,
including the exit status of a narrowed run, which a test inside that run cannot
observe and so is checked in a child interpreter.

### The session ceiling

A full run stops at a wall-clock deadline, 60 minutes by default. The deadline is
checked at each test boundary, so the run overshoots by at most the duration of the
test in progress and then stops through pytest's own `session.shouldstop`, which
keeps every report already collected.

`--test-ceiling=MINUTES` sets it, `PETACAT_TEST_CEILING_MINUTES` sets it from the
environment, and `--test-ceiling=0` runs to the end. Set it from the machine: the
same suite takes different wall-clock time on different hardware, and the ceiling
is there to bound a run, not to describe one.

A truncated run reports itself as truncated, and the difference from a clean run is
visible three ways:

```
  module         1041 collected    198 run    198 passed      0 failed      0 skipped  INCOMPLETE

  RUN TRUNCATED: the 60 min ceiling was reached after 60.4 min. Everything above is
  what the run produced before it stopped; the tests it had not reached never ran.
  Raise the ceiling with --test-ceiling=MINUTES, or narrow the run, to get a
  complete result.
! Interrupted: the 60 min test ceiling was reached after 60.4 min — this run is TRUNCATED !
```

The per-layer line shows `INCOMPLETE` with the collected and run counts beside each
other, the summary states the truncation in words, and the exit status is pytest's
`INTERRUPTED` (2) rather than success. The results obtained before the stop are all
present — the backends exercised, the layers finished, and pytest's own list of
what passed and failed — so a truncated run is evidence about the part of the suite
it reached.

## Test layers

The backend suite (`tests/`) is organised into eight layers. A layer is defined by
what its tests are allowed to reach for, and every test in a layer stays inside
that allowance.

| Layer | Directory | Scope | May depend on | Cases |
|-------|-----------|-------|---------------|-------|
| **unit** | `tests/unit/` | One class or function, business logic only | Only what the test constructs: hand-rolled fakes and plain engine objects | 756 |
| **seed unit** | `tests/seed_unit/` | One class or function, measured against the values Petacat ships with | Real `seed_data/*.json`, and the machine the process is running on | 626 |
| **module** | `tests/module/` | Several real components assembled and driven | Real engine objects and `seed_data/*.json`; no DB, no HTTP | 1041 |
| **architecture** | `tests/architecture/` | How the source tree is allowed to depend on itself | The repository's source, `seed_data/*.json`, child interpreters | 42 |
| **integration** | `tests/integration/` | Agreement between the repository's artifacts, and the harness's own rules | Real `seed_data/*.json`, the ORM declarations, the generated client files, the documentation, a real pytest session | 203 |
| **parallel** | `tests/parallel/` | The detachable multi-core plugin (`server/parallel/`): each executor against the serial run it claims to equal | Real engine objects and `seed_data/*.json`, worker processes and threads; each test pins the backend it compares on | 244 |
| **lockstep** | `tests/lockstep/` | Petacat's decision traces against Metacat's: naming, helper conformance, tracing/replay RNGs, determinism guards, the comparer | Real engine in faithful mode (numeric backend off, or a named backend); recorded Metacat traces | 228 |
| **e2e** | `tests/e2e/` | Full HTTP API + persistence | Local PostgreSQL (`petacat_test`) | 339 |

Those counts are cases, so they include the second pass the numeric matrix makes
over the 519 backend-sensitive tests.

One line decides each layer. Read them as a question about what a new test's
subject is, and write the test where the answer lands:

- **unit** — everything it touches is constructed in the test: a hand-rolled
  fake, or a plain engine object. No file is read and no process is started.
- **seed unit** — the same shape of test, except that the shipped value is what
  is being asserted about, so it reads `seed_data/` or the machine. No codelets
  run.
- **module** — codelets run.
- **architecture** — the assertion is about the source tree rather than about
  what running it produces.
- **integration** — the assertion is that two artifacts in the repository say
  the same thing.
- **parallel** — the subject is the parallel plugin, and the assertion is an
  equality: a swarm outcome equals the serial run's, a speculative run equals the
  stream-serial reference's, bit for bit, at every worker count. Outside the backend
  matrix, like lockstep: each test pins the backend its comparison is made on.
- **lockstep** — the assertion is about Petacat's random decisions: what they are
  named, how a helper draws, whether a replay of a Metacat trace repeats exactly.
  It runs the engine in faithful mode, which pins the numeric backend off, so it
  stays outside the backend matrix and the substrate-marker guard. One test names
  the exact CPU backend instead, and `scripts/lockstep_corpus.py --numeric-backend`
  replays whole corpora with any backend, the GPU included.
- **e2e** — the assertion travels over HTTP.

A first pass should test **the lowest level of code just above the database
first**, then move up toward the API and GUI.

All eight layers run in one command — the
[required command](#the-required-command) — and, since Petacat runs natively, all
eight actually run: **3,479 cases**, every one of them executed. A layer that is
normally skipped is not a layer that is normally green, and none of these is.

Wall-clock time depends heavily on the machine and on what else it is doing. The
dominant cost is the numeric substrate: the default policy puts the engine's
arithmetic on the GPU at every Slipnet size, which at today's 59 nodes runs 5.9×
slower than the NumPy path the matrix's CPU half takes, and 7.1× slower than the
engine's own loops (`README.md` carries both measurements). Three invocations,
measured on an Apple M2 Max:

| Invocation | Wall time |
|---|---:|
| `pytest tests/ -q` — the [required command](#the-required-command), full matrix | 14.2, 14.6 and 24.4 min |
| `pytest tests/ -q --numeric-backends=cpu` — whole session on the CPU | 8.2 min |
| `pytest tests/ -q -m "not slow" --numeric-backends=cpu` — the tight loop | 1.8 min |

The required command is given as three figures because three runs of it on the
same machine produced them, and that spread is what "depends on what else it is
doing" looks like in practice. Budget against the largest: the expected-range
oracle holds each problem to a per-sample deadline (`PETACAT_RANGE_TIMEOUT`,
600 s), so on a machine loaded enough to reach 24 minutes that deadline is within
reach, and a problem that hits it reports the stall and names the workers still
running.

What `-m "not slow"` drops is the expected-range check, which is ~1,300 engine runs
across a process pool. Reach for the tight loop when you want a fast loop rather
than a number to compare, and for the required command when you want the number.

> **If `tests/module/test_free_running.py` fails, read
> `server/parallel/coderack_shards.py` before reaching for `--numeric-backends`.**
> That file is the one place the suite runs *codelets* concurrently —
> `test_coderack_shards`, `test_access_sets`, `test_run_identifiers` and
> `test_splittable_rng` thread over engine state without executing codelets — so
> a red here is a concurrency result first and a backend result second.
>
> This callout used to say the opposite, and said the file was "currently green
> under every backend". It was not: `test_every_worker_does_some_work` failed
> about 40% of the time on `[numpy]`, bimodally — either an even split across the
> four workers or `[4001, 0, 0, 0]`, nothing in between. The cause was a thread
> startup race, not the substrate, and the advice to check the backend first sent
> a reader looking at float32 for a defect that was not there. `mlx` never failed
> for the revealing reason that it is ~4× slower, so the main thread always won
> the race eventually. The defect is fixed
> (`FreeRunningEngine._all_started`); the lesson kept here is that a red in this
> file is about scheduling until proven otherwise.
>
> The reason a backend can matter at all is that the default `mlx` path forks a
> run's random stream: float32 flushes the Slipnet's decayed subnormal
> activations to zero, which changes the `jump_candidates` list and shifts every
> subsequent draw. So a failure seen only under `mlx` is a different run, not a
> different degree of safety. The file is in the numeric matrix, so each case
> carries its backend in its name — `…[numpy]` and `…[mlx]` sit side by side in
> the report, and a red `[mlx]` beside a green `[numpy]` is that seed difference
> while both red is a concurrency defect. Note also that the "group reachable from a bond but absent from its
> string's object list" symptom occurs *serially* too, and the file documents it
> as a pre-existing property rather than a race.

The database it needs is the local Postgres (`scripts/dev.sh db` starts it and
creates the databases). e2e talks to `petacat_test`, deliberately separate from
the development database on the same instance, so a test run cannot disturb the
runs and episodic memory accumulated in `petacat`. `TEST_DATABASE_URL` overrides
it; if no Postgres is reachable, the e2e layer skips rather than fails.

Two pytest sessions sharing `petacat_test` would destroy each other's schema,
because `setup_db` drops and recreates every table at session scope. That is not
hypothetical — it produced two `relation "runs" does not exist` failures that
looked like a free-threading defect and were not. `tests/e2e/conftest.py` now
holds a Postgres advisory lock for the session, so concurrent suites serialise
instead of interleaving.

Shared helpers that more than one test module needs live in `tests/support/`.
That directory is imported, never collected.

### The test-file inventory

Every backend test file, by layer, with the number of test functions it defines
and what it covers. Case counts are higher where the numeric matrix or a
`parametrize` expands a function.

**These figures are checked, not restated.**
`tests/integration/test_documented_counts.py` compares every layer count, suite
total and per-file figure in this document, in `README.md` and in the
repository's `CLAUDE.md` against the collection the running session produced, and
names the ones that have drifted. It reads `session.items`, the list pytest has
already built, so the check costs one pass over it. It is held of a run that
asked for the whole suite; a narrowed invocation collects a subset by design, and
there the check stands aside and says so.
`tests/integration/test_documented_code_shape.py` does the same for the figures
the documentation gives about the source: the engine's module and line counts,
the number of endpoints taking `Depends(get_session)`, the size of
`codelet_dsl/builtins.py`, and the number of groups in the Run Controls panel.

**Configuration-source work packages C0 and EN0.** Two groups of tests guard the move of
the engine's configuration from the seed files to the database, and each has rules about
changing what it records.

- *C0, the equivalence harness (gate G4).* `tests/integration/equivalence_harness.py` loads
  an empty scratch database, `petacat_c0` on the local Postgres (override with
  `C0_HARNESS_DATABASE_URL`), from the Metacat Standard Configuration and compares the
  provider read back from it with the one built from the seed files: the provider itself,
  Metacat Mode runs, a swarm and a speculative run. Every package that touches a loader or
  adds a table re-runs it. What the database cannot yet carry is recorded in
  `RECORDED_STORAGE_LIMITS`; the list can only shrink. The configuration input library
  (`server/services/configuration_input.py`) is tested on its own in
  `test_configuration_input.py`.
- *C2, start-up.* `tests/integration/test_configuration_source.py` runs the start-up
  sequence `lifespan` uses against its own scratch database, `petacat_c2` (override with
  `C2_DATABASE_URL`): the database is the configuration source, the seed files load only
  into an empty database, and an unreachable or unreadable one refuses to start.
- *EN0, the golden baseline gate (G3).* `tests/lockstep/golden/` records the engine's
  behaviour before the first configuration-source engine edit, on the CPU numeric backend
  (float64) from the Metacat Standard Configuration. Recapture with
  `.venv/bin/python scripts/capture_golden_baseline.py` only for a deliberate, reviewed
  change of behaviour, stated in the commit; never to turn a red gate green.
  The baseline records behaviour only, not which configuration produced it (no
  configuration hash), so behaviour-preserving changes to the Metacat Standard
  Configuration do not touch it.
- *EN0, the no-node-literals lint.* `tests/architecture/test_no_node_literals_in_engine.py`
  with `no_node_literals_allowlist.txt`: the allow-list may only shrink.
- *EN0, role identity and reduced configurations.* `tests/seed_unit/test_role_identity.py`
  is a skeleton whose comparison with `slipnet.roles` skips until EN3;
  `test_reduced_configurations.py` checks the generated reduced configurations that later
  packages run the engine on.
- *EN1, no run-time seed reads.* `tests/module/test_no_seed_reads_at_run_time.py` arms a
  `sys.addaudithook` (installed by a fixture local to the module, so no `conftest.py`
  change) that fails any `open` under `seed_data/` during a run, a swarm call and an
  episode, and checks that the former fallbacks raise when given no `MetadataProvider`.
  Tests that call an engine function that now takes the provider build one with
  `MetadataProvider.from_standard_configuration`; the engine's own run-time paths never do.
- *EN2, schema and provider.* `tests/unit/test_config_hash_guard.py` (the hash guard),
  `tests/seed_unit/test_standard_configuration_roles.py` (the role bindings and node data in
  the Metacat Standard Configuration), `tests/integration/test_role_and_key_schema.py` (the
  new tables on a database) and the G4 harness, which now compares the role tables, theme
  relations, node columns, `rule_key`s and every ordinal field for field, with an empty
  `RECORDED_STORAGE_LIMITS`.

**`tests/unit/` — one class or function, against what the test constructs**

| File | Fns | Covers |
|------|----:|--------|
| `test_arithmetic_fidelity.py` | 10 | Metacat's exact roundings and orders: spreading, urgencies and bins, jootser, descriptor support, single-letter groups (DISCREPANCIES5 B-1…B-5, D-4, D-11) |
| `test_bonds.py` | 25 | `Bond`: direction, facet, strength, flipping |
| `test_bridge_types.py` | 2 | The bridge-type and orientation constants |
| `test_codelet_dsl.py` | 3 | Compiling a codelet body: what the interpreter accepts and refuses |
| `test_clamp_commentary.py` | 12 | A clamp announces itself and its undoing in Metacat's words; remindings newest first with a whole-number strength; the "stumped" answer |
| `test_commentary.py` | 29 | The `CommentaryLog`, and the emit helpers whose English is written in Python |
| `test_compare_harness.py` | 18 | The oracle comparison's decision logic: what gets flagged, and how, and its engine-parameter passthrough; the shipped reference sets in `measurements/reference/` |
| `test_concept_mappings.py` | 37 | `ConceptMapping`: identity, slippage, distinguishing descriptors |
| `test_descriptions.py` | 23 | `Description`: relevance, strength, descriptor predicates |
| `test_episodic_memory.py` | 16 | `EpisodicMemory`: identifier scoping, theme distance, `answer_present`; the list kept newest first as Metacat conses it, the oldest-first window listing, remindings newest first |
| `test_formulas.py` | 25 | Averaging, the sigmoid, and the five translation-temperature distributions |
| `test_groups.py` | 22 | `Group`: length, spanning, membership, internal and external strength |
| `test_jootsing_outcomes.py` | 7 | The jootser's outcomes: what counts as the same clamp, and when it gives up |
| `test_object_choice.py` | 8 | Weighted object choice: the temperature exponent, and the absence of floors |
| `test_config_hash_guard.py` | 11 | The hash guard (plan 3.8, EN2): `config_hash` covers every `MetadataProvider` field by reflection, the exclusion set is pinned, a field added to the provider is hashed without editing the hasher, each hashed field's digest moves with its value and order, the hash is `combine(field_digests)`, and the scheme and a number's type are part of it |
| `test_order_fidelity.py` | 10 | The list orders `cons` and vectors fix: Chez Scheme's `sort` (80 cases from the Metacat image), a string's groups, the rule's subobject bridges, the coderack bin and deferred batch, the jootser's event set, and the display-time prints (DISCREPANCIES5 C-1, G-Z4, G-Z5, I-3…I-5) |
| `test_rng.py` | 17 | The deterministic RNG wrapper |
| `test_rule_bond_facet_change.py` | 1 | A GroupCtgy self change's BondFacet change is found wherever it sits (KNOWN-FAILURES, G-Q1) |
| `test_rule_types.py` | 9 | `Rule` and `RuleClause` predicates and translation |
| `test_rules_lockstep_ordering.py` | 12 | Rule construction in Metacat's order: subobject gate, common change schemas, `sort-templates`, swaps, list order (DISCREPANCIES5 C-1…C-4, D-1…D-5) |
| `test_runner_status.py` | 1 | The runner's status constants |
| `test_scout_counts.py` | 14 | The scout-count aggregates that decide how many codelets a cycle posts |
| `test_eeg.py` | 5 | The EEG recorder: ring buffer, the average that excludes the current reading |
| `test_coderack_display.py` | 4 | The coderack window's selection probabilities, from hand-computed racks |
| `test_sink.py` | 8 | The `RunSink` port: its event vocabulary and `NullSink` |
| `test_slipnet_node.py` | 30 | Nodes and links built directly: degree of association, probabilistic jump |
| `test_slippage_log.py` | 4 | `SlippageLog`: applied and coattail slippages recorded newest first, bridges deduplicated keeping the last, the slippage to highlight |
| `test_snag_response.py` | 21 | The snag response and the clamp machinery, one piece at a time |
| `test_splittable_rng.py` | 21 | Counter-based per-codelet random streams |
| `test_structure_fights.py` | 13 | `wins-fight?` and the weights the builders bring to a fight |
| `test_temperature.py` | 3 | `Temperature`'s own state: starting value and clamp |
| `test_thematic_scouting.py` | 20 | The thematic-bridge-scout's decisions (`themes.ss:750-1030`) |
| `test_theme_types.py` | 6 | `Theme` and `Themespace` type constants |
| `test_themespace.py` | 31 | Themespace self-watching dynamics: cluster spreading, dominance |
| `test_trace_event.py` | 6 | `TemporalTrace` event recording |
| `test_trace_display.py` | 16 | A Trace event's print name and display header against `trace.ss`: every event type, the three group directions, the bridge prefixes, flipped groups, the answer headers; a picture that cannot be taken never stops the trace |
| `test_verbose.py` | 16 | Scheme's display of values, the bounded narration log (capture and replay, dropped lines), the message-catalogue overlay, and that the narration builtins exist in a codelet's namespace only when Verbose mode is on |
| `test_workspace_object.py` | 40 | `WorkspaceObject` and `Letter`: geometry, importance, unhappiness |
| `test_workspace_string.py` | 28 | `WorkspaceString`: bond and group management, spanning, relevance |
| `test_workspace_structure.py` | 10 | The base structure class and its proposal levels |

**`tests/seed_unit/` — one class or function against the shipped values**

| File | Fns | Covers |
|------|----:|--------|
| `test_answer_comparison.py` | 44 | The answer-comparison and answer-explanation English (`answers.ss:267-882`) |
| `test_answer_description.py` | 4 | Storing, reminding and comparing inside `EpisodicMemory` |
| `test_bridge_types.py` | 4 | Bridge orientation over letters of a real Workspace |
| `test_codelet_dsl.py` | 2 | The codelet registry built from the seeded codelet types |
| `test_coderack_bin.py` | 10 | The Coderack's urgency bins and temperature-weighted choice |
| `test_coderack_clamping.py` | 15 | Codelet-type clamping, against the urgencies Petacat ships with |
| `test_coderack_eviction.py` | 19 | Incremental eviction picks exactly what the flat scan picked |
| `test_commentary.py` | 7 | The emit helpers that render from the seeded commentary templates |

| `test_episodic_memory.py` | 21 | Reminding, comparison and the reminding distance, which resolve the seeded templates and the seeded conceptual depths |
| `test_fallback_instrumentation.py` | 4 | The silent-fallback observer (EN0, `tests/support/fallback_instrumentation.py`) sees the three blanket `except Exception` blocks of `justify.py` and a lookup of an absent Slipnet node, and changes nothing else; `scripts/count_silent_fallbacks.py` makes the count over the whole baseline set |
| `test_formulas.py` | 10 | The temperature-dependent formulas against the seeded coefficients |
| `test_hardware.py` | 21 | The machine description and the sizes derived from it: real probes, faked probes, environment overrides |
| `test_metacat_display_seed.py` | 5 | Seed data that exists so a display can match Metacat: every Metacat demo, the Themespace's dimension and relation names |
| `test_metadata_provider.py` | 25 | `MetadataProvider` loading every seed collection |
| `test_numeric_backends.py` | 27 | The numeric backends against the reference (decay and spreading against exact rationals, including spreading's halfway cases), and the engine without them |
| `test_reduced_configurations.py` | 14 | The reduced-configuration fixture generator (EN0, `tests/support/reduced_configurations.py` and `configuration_cascade.py`): nothing left that names a removed node or codelet type, the cascade removes what the plan's rules say, a provider loads from each; the engine is not run on them yet |
| `test_standard_configuration_roles.py` | 14 | EN2: the Metacat Standard Configuration binds every role of `tests/support/role_table.py` to the node or codelet type today's code names (the two ordered roles in today's order), carries the five theme relations, `plain_name`, `glyph`, `numeric_value` and the display columns that reproduce the tables they replace, unique `rule_key`s and unique link keys, and the provider loads them |
| `test_role_identity.py` | 12 | Role identity (gate G5), the skeleton laid down by EN0: today's side runs now (the role-to-literal table against the Metacat Standard Configuration, the engine's ordered constants and `role_identity_today.json`); the comparison with `slipnet.roles` skips, with a stated reason, until EN3 adds it |
| `test_rule_english.py` | 10 | A rule's English against Metacat 1.2's own `transcribe-to-english` output: 463 recorded rule shapes, each string state, wrapping, articles, and the text kept from the moment the rule was made |
| `test_snag_explanation.py` | 20 | A snag's explanation against Metacat 1.2's `get-explanation` (`trace.ss:1097-1125`): every branch of the failure-result, the object phrases, the commentary lines, the template-driven wording, and the fallback for a snag with no stored explanation |
| `test_rule_quality.py` | 13 | Rule uniformity, abstractness and succinctness against the Scheme's formulas, hand-computed from the seeded depths |
| `test_slipnet_link_lengths.py` | 6 | The Slipnet's link lengths against the reference Scheme |
| `test_slipnet_node.py` | 23 | The 59-node Slipnet: its nodes, its links, its clamps and its spreading |
| `test_temperature.py` | 2 | Temperature updating against the seeded coefficients |

**`tests/module/` — real components assembled and driven**

| File | Fns | Covers |
|------|----:|--------|
| `test_access_sets.py` | 19 | Read-set / write-set discipline and commit-time validation |
| `test_lockstep_desync_fixes.py` | 5 | Fixes found by replaying runs beyond the lockstep corpus, as small hand-built states: `get-equivalent-bridge`, rule clauses `self` vs `subobjects`, any-descriptor reference objects, both-order internal coherence, `remove-duplicates` keeping the last entry (G-Y1…G-Y3, G-Y5, G-Y8) |
| `test_answer_description_pattern.py` | 13 | The vertical theme-pattern an answer description is indexed by |
| `test_bridge_scouting.py` | 25 | The bridge scouts' probabilistic gates, the build-time mapping augmentation, the incompatibility refinements, and the deferred posting batch |
| `test_capture_projection.py` | 9 | A recorded capture renders exactly as the same state renders live, including the unbuilt translated rule justify mode adds |
| `test_coderack_eeg_display.py` | 8 | The coderack window's figures and the EEG's samples from a real run, serial and free-running |
| `test_codelet_behaviours.py` | 79 | What each of the 27 codelet types does to a live workspace |
| `test_codelet_dsl.py` | 7 | Codelet bodies executed against a live engine context |
| `test_coderack_shards.py` | 15 | The candidate sharded coderacks: fidelity and contention; the free-running rack's draw and eviction are exactly the serial rack's |
| `test_commentary_writer.py` | 8 | Commentary is an injected writer, and every Run gets a real one |
| `test_dissertation_parity.py` | 45 | The dissertation's claims, encoded as tests |
| `test_free_running.py` | 23 | Free-running execution across worker threads, and the loop matching the serial one (codelet count, structure clock, initial unclamp, per-codelet answer hand-off) |
| `test_group_image_direction.py` | 6 | A group's image is built in the group's own direction |
| `test_image_relations.py` | 4 | The relations a group's image is built with, and what happens when they are wrong |
| `test_justify_and_jootsing.py` | 14 | Justify mode's verdicts and the jootser's justify outcomes |
| `test_lockstep_structure.py` | 7 | Structure-building fidelity: bridge-proposal scout scope, bond-builder break order, answer string outside justify mode, concept-activation sampling (DISCREPANCIES5 C-5, D-6…D-10) |
| `test_numeric_engine.py` | 7 | The engine computes the same thing with the substrate engaged |
| `test_no_seed_reads_at_run_time.py` | 8 | EN1: the engine takes its configuration from the run's `MetadataProvider` and never reads the Metacat Standard Configuration files at run time. A `sys.addaudithook` fixture (local to the module) fails any `open` under `seed_data/` during a Verbose-mode run, a swarm call, an episode with Episodic Memory carried and the comparison and explanation of its answers; and the former fallbacks (rule English parameters, the Verbose catalogue, commentary templates, conceptual depths, reminding and distance) raise when no provider is given |
| `test_population.py` | 9 | Population batching: K independent runs together |
| `test_run_identifiers.py` | 8 | Identifiers depend on the run, not on the process's history |
| `test_rule_object_descriptions.py` | 8 | What a rule may name its object by, and whether that name finds anything |
| `test_run_to_answer.py` | 7 | Run-to-answer behaviour at the `EngineRunner` level |
| `test_runner.py` | 19 | `EngineRunner`: initialisation, stepping, the update cycle |
| `test_runner_commentary.py` | 6 | Commentary emitted as the runner drives a problem |
| `test_runner_status.py` | 7 | The status an `EngineRunner` reports as a run moves through it |
| `test_singleton_group_images.py` | 3 | Every object a rule names owns an image, singleton groups included |
| `test_sink_emission.py` | 9 | The engine emits a complete run record to its sink |
| `test_snag_records.py` | 4 | A run records the snags it adds to Metacat Mode's Episodic Memory, once each |
| `test_snag_response.py` | 7 | The snag response driven end to end through a real run |
| `test_staleness.py` | 8 | The staleness probe reads a Workspace that lags the live one |
| `test_state_graph.py` | 12 | A captured run restores to a state that continues identically; memory captured oldest first and restored newest first, with the slippage logs of its events |
| `test_swaps_and_translation.py` | 14 | Extrinsic (swap) rules end to end, the conflict battery, the per-dimension slippage ignore, and the ways a translation fails |
| `test_thematic_bridge_scout.py` | 9 | The thematic-bridge-scout inside an assembled engine |
| `test_themespace.py` | 14 | Themespace driven by a real run's bridges |
| `test_trace_persistence.py` | 7 | Trace event persistence logic |
| `test_trace_pictures.py` | 8 | What a real run keeps for redisplay: print names and pictures on every event, the Workspace as it was, answer and snag description pictures, and that taking a picture changes nothing the run does |
| `test_verbose_mode.py` | 11 | Verbose mode on a real run: every codelet's banner, a run identical with the mode on or off, the mode switched mid-run, step mode, the bounded buffer, and the message catalogue agreeing with the call sites |
| `test_workspace.py` | 19 | Workspace aggregation across its four strings |

**`tests/architecture/` — properties of the source tree**

| File | Fns | Covers |
|------|----:|--------|
| `test_engine_purity.py` | 18 | Nothing under `server/engine/**` imports `sqlalchemy`, `server.models`, `server.db` or `server.services`, and the serializers run in an interpreter where those cannot be imported |
| `test_no_node_literals_in_engine.py` | 4 | The EN0 lint: no line of `server/engine/**` names a node or codelet type of the Metacat Standard Configuration (`plato-` literals and compositions, `name[6:]`, node names, codelet types), and none reads the seed files at run time. Known violations are in `no_node_literals_allowlist.txt`, which may only shrink: an entry that no longer matches fails, and a new violation cannot be added to it |
| `test_parallel_detachable.py` | 4 | Nothing under `server/engine/**` imports the parallel plugin, and a serial run and the service layer work in an interpreter where `server.parallel` cannot be imported; a Training run there chooses the serial executor and produces the plugin's runs, run for run |

**`tests/integration/` — the repository's artifacts agree**

| File | Fns | Covers |
|------|----:|--------|
| `test_documented_code_shape.py` | 4 | The engine's size, the endpoint count, the builtins module and the Run Controls groups, as the documentation states them |
| `test_documented_counts.py` | 3 | Every documented layer count, suite total and per-file figure, against the collection that produced it |
| `test_configuration_input.py` | 31 | The four input-check classes of the configuration input library (C0, `server/services/configuration_input.py`) as pure functions, with no database, engine or routes: unknown reference, key exists, malformed, does-not-compile, stale base version, and applying operations to a copy |
| `test_configuration_source.py` | 15 | C2, start-up tests 1-6 of the plan's 3.6, through `server/services/configuration_startup.py` (what `lifespan` calls): the database is the source and not the files; an empty database first-loads with a `configuration_state` row; a loaded database is never re-seeded (edits and deletions survive a restart) even when a seed file changes; the start-up reference equals the seed files whatever the database holds; refusals (unreachable database, rows without a state row, a state that is not `ready`, a state row over empty tables, an older schema, an unparseable parameter, an unreadable seed file); two simultaneous start-ups load once; start-up never writes the seed files. Uses its own scratch database `petacat_c2` (`C2_DATABASE_URL` overrides) |
| `test_db_seed_equivalence.py` | 15 | C0 gate G4: a database loaded from the Metacat Standard Configuration with no edits yields a provider equal, field by field (order and JSON number typing included), to `MetadataProvider.from_standard_configuration`. `RECORDED_STORAGE_LIMITS` lists what the database cannot carry and may only shrink; EN2 removed the last three (ordinals on the name-keyed tables, `value_type` on formula coefficients, `json` rather than `jsonb`), so it is empty and the providers and `config_hash` must be equal in full. A new table must be added to `_expected_tables`. Uses its own scratch database `petacat_c0` (`C0_HARNESS_DATABASE_URL` overrides), built by `equivalence_harness.py` |
| `test_db_seed_parallel_equivalence.py` | 2 | C0 gate G4: a swarm (real process pool) and a speculative run with `workers >= 2` equal the seed-file provider's runs on the database-loaded provider; slow, CPU float64 pinned by the tests themselves |
| `test_db_seed_run_equivalence.py` | 2 | C0 gate G4: Metacat Mode runs per (problem, seed) on the database-loaded provider are identical to the seed-file provider's (answers, codelet count, draw count, final temperature, step/structure/trace hashes, final state); in the numeric matrix, with bit-identity down to the draw asserted on the float64 CPU half |
| `test_enum_constants.py` | 17 | Engine string constants match `seed_data/enums.json` |
| `test_help_topics.py` | 13 | The help JSON, the generated TypeScript and the panels that reference them |
| `test_metadata_seeding.py` | 13 | Every seed file is well-formed, and the `MetadataProvider` round-trip holds |
| `test_numeric_matrix_harness.py` | 11 | The matrix's own reporting rules and the exit status of a narrowed run |
| `test_role_and_key_schema.py` | 9 | EN2, on the scratch database inside a rolled-back transaction: deleting a node or codelet type deletes its role bindings and theme relation (`ON DELETE CASCADE`), a rename follows, one node per role ordinal, the widened link key (two labels between the same nodes, no repeat, no second unlabeled link), unique glyph and numeric value, a row added without an ordinal goes last, and an Admin-style create of a posting rule, link, demo and theme dimension succeeds without an explicit id (the first load sets each id sequence past the ids it wrote) |
| `test_seed_reconciliation.py` | 6 | The seeder writes every configuration table, the configuration tables exclude the runtime tables (the four Training tables among them), and no fingerprint or re-seed path remains |

**`tests/lockstep/` — Petacat's decision traces (the Petacat/Metacat lockstep harness)**

| File | Fns | Covers |
|------|----:|--------|
| `test_commentary.py` | 1 | Every comment-window paragraph (both voices) of 28 Metacat runs -- snags, all four clamps and their undoing, "I'm getting frustrated", answers, "Okay, I'm stumped" -- replayed in Petacat and compared as Metacat 1.2 logged them |
| `test_comparer.py` | 29 | The trace comparer: hand-made trace pairs with known faults give the expected classes; the registry's reference-crash class; proposed structures counted apart from state snapshots, and the ratchet on both |
| `test_desync_fixes.py` | 1 | Prefixes of three Metacat runs beyond the corpus that used to desynchronise the replay (`traces-desync/`) replay to their end with no error and no differing state (DISCREPANCIES5 G-Y2…G-Y4) |
| `test_episodes.py` | 8 | Episodes and justify mode: recorder driver text, corpus globs, an episode's self-replay with memory carried, a forced fatal, justify self-replay |
| `test_golden_baseline.py` | 5 | The EN0 golden baseline gate (G3): `tests/lockstep/golden/engine_baseline.jsonl` and `engine_baseline_rng.json.gz`, captured from the Metacat Standard Configuration on the CPU numeric backend (float64), hold for the 19 demo problems and the justify problems at seeds 1-5 and one 8-run episode the answer, codelet count, final temperature, per-codelet RNG call counts, trace and final-state hashes and the English corpus. A quick consistency check and a four-run sample run always; the slow test recomputes everything in a fresh interpreter and compares byte for byte, naming the first differing run and codelet. Outside the numeric matrix (it pins its backend) |
| `test_event_names.py` | 2 | Every Trace event in eight Metacat runs (all event types, all three group directions, flips, slippages on all three bridges, translated rules, the three answer headers) named and headed exactly as Metacat 1.2 logged them |
| `test_helpers.py` | 11 | Helper conformance: `prob`, `~`, `weighted_pick` and `pick` give Metacat's results for the same draws |
| `test_naming.py` | 9 | Canonical names for plain values and every kind of object, and the opening state against Metacat's |
| `test_replay.py` | 15 | Tracing rules, trace shape, self-replay, Guard 1, fatal and surplus paths, Guard 2 (slow); a committed Metacat trace replayed with the numeric backend on |
| `test_seam.py` | 6 | The engine's trace seam changes nothing for an ordinary run; the faithful clamp-expiry switch |
| `test_translation_log.py` | 2 | The slippage log, supporting vertical bridges, reference objects and supporting groups of every answer and snag in six Metacat runs (coattail slippages, a justify-mode answer, a snag with an applied slippage), equal to what Metacat 1.2 logged |
| `test_verbose.py` | 2 | Nine Metacat runs (six discovery, three justify) with `%verbose%` on, narrated line for line by Petacat's replay; and the replayed trace is the same with Verbose mode off |
| `test_snag_explanations.py` | 2 | Every snag in eight Metacat runs (CHANGE, SWAP, CONFLICT, group-category reversal) explained, and its two comment lines worded, exactly as Metacat 1.2 logged them |
| `test_rule_english_tools.py` | 8 | The rule-English recorder and comparer (no Docker): problem-list and Metacat-record parsing, clause-structure keys, exact pairing, fixture-table rows |
| `test_event_tools.py` | 6 | The event-name recorder and comparer (no Docker): record parsing, run-list reading, per-run comparison, fixture-table rows, `--pick` selection |
| `test_snag_and_answer_tools.py` | 26 | The snag and episode-answer recorders, comparers and the snag and fidelity sweep drivers (no Docker): record parsing, order-sensitive and order-insensitive answer comparison, problem-list data files, sweep stage selection |
| `test_frequencies.py` | 17 | The answer-frequency tools (no Docker): recording parsing, frequency tables, total variation, pooled two-sample chi-square, the support-v1a reference counts against the committed measurement |

**`tests/e2e/` — the HTTP API against a real database**

| File | Fns | Covers |
|------|----:|--------|
| `test_api_controls.py` | 29 | Breakpoints, clamping, Clamp theme pattern, Undo last clamp, the mid-run self-watching toggle, and the threshold endpoints |
| `test_api_displays.py` | 5 | The coderack, EEG and Themespace-name data the Metacat windows need |
| `test_api_docs.py` | 11 | The documentation endpoints |
| `test_api_extended.py` | 57 | Extended runs, memory, docs and admin endpoints |
| `test_api_review.py` | 26 | The review surfaces read back what the persistence modes wrote, and the episodic-run timeline places each Episodic Memory clear exactly between the runs, page by page, with its note |
| `test_api_runs.py` | 26 | The runs API with persistence |
| `test_api_system.py` | 8 | The system endpoints: what is executing, not what was recorded |
| `test_episodic_clears_migration.py` | 8 | Training Sessions become Episodic Memory clears without losing anything: the mapping, notes before and after a clear, failing loudly rather than dropping a note, idempotence, the downgrade, and an Alembic 018 round trip |
| `test_help_api.py` | 7 | The help topics API |
| `test_persistence.py` | 4 | Snapshot save/restore and the DB metadata round-trip |
| `test_persistence_modes.py` | 33 | The three persistence modes: Fast, Normal, Audit; a parallel Run is the same at any worker count |
| `test_run_parameters.py` | 13 | Run parameters are settable per Run, stored, and readable back |
| `test_run_to_answer.py` | 8 | The Run-to-Answer feature over HTTP |
| `test_memory_order.py` | 2 | A restart puts stored answers back newest first by the memory's own identifier, both projections list them oldest first, and forgetting one keeps the rest in order |
| `test_snag_identity.py` | 5 | A snag is the same snag whichever endpoint served it, and is written once |
| `test_moment_display.py` | 6 | Event, answer and snag redisplay over the API: print names in the listing, the picture served live and from the stored row, the toggle and the switch, rows with no picture |
| `test_swarm_api.py` | 5 | `POST /api/swarm` equals the serial runs, persists nothing, and rejects bad requests; `GET /api/swarm` reports the pool |
| `test_trainings_api.py` | 32 | Trainings over HTTP: every stored run is the serial run; the 25 + 5 workflow (problems added while it runs); the finished long-poll; pause, resume, close, cancel, delete; the database written only when a problem finishes; a restart redoes what was cut off to the identical result and rebuilds the shared memory exactly; one worker is a serial episode and many replay from the merge log; fair sharing of the cores; every error policy; worker-failure retries, charged only to the run that broke the pool; a policy pause survives a concurrent status change; live counts never step backwards; a summary's finished cursor comes from the same snapshot as its counts; seed ranges fit the database; configuration change stalls or is adopted; validation, export, defaults and fixed settings |
| `test_step0_config_from_db.py` | 48 | Step 0's guard tests: a shipped value reproduces the run and a changed one moves it |

**`tests/parallel/` — the multi-core plugin against the serial runs it claims to equal**

| File | Fns | Covers |
|------|----:|--------|
| `test_swarm.py` | 22 | A swarm outcome is the serial run's, byte for byte: demo problems × seeds, justification, episodes, parameter overrides, both CPU backends; errors come back as outcomes; configuration changes re-initialise workers; `Swarm.submit` (the Training executor's entry point) returns futures equal to the serial runs, counts runs in flight and resolves the default backend like `map` |
| `test_placement.py` | 13 | The measured backend policy: the CPU by default, never the GPU on its own, the environment overrides |
| `test_update_cycle.py` | 9 | The plugin's update cycle: faithful is bit-identical to the engine's, stream is identical at every thread count |
| `test_clock_rack.py` | 12 | The exponential-race coderack draws each codelet with the faithful two-stage draw's probability, and a later post never disturbs an earlier choice it does not beat; the prediction cached for an epoch stays exact until a post passes it |
| `test_effects.py` | 8 | The builtin effects table is complete, and no speculated read prefix writes shared state (the hidden-write detector) |
| `test_speculative_exact.py` | 17 | The speculative executor is bit-identical to the stream-serial reference at every worker count, with forced aborts too; which codelets run ahead, and how far, never changes a result; one worker is the reference itself; the slow sweep (`PETACAT_SPECULATIVE_SWEEP_SEEDS`) widens it |
| `test_training_memory.py` | 6 | The Training episode memory without a database: descriptions survive the JSON storage encoding and pickle transport, a merge skips what the episode already holds and restamps ids in the master's numbering, a run's copy is independent of the master, a serial episode equals copy-and-merge one run at a time, and a worker reaches a version from its cache plus the tail (or asks for a snapshot) |

**Collected by no layer**

| File | Holds |
|------|-------|
| `tests/conftest.py` | The numeric backend matrix, the session ceiling, the per-layer summary |
| `tests/e2e/conftest.py` | The Postgres fixtures and the session advisory lock |
| `tests/unit/_fakes.py` | The shared hand-rolled doubles |
| `tests/support/expected_range.py` | A sampling pool over the demo problems, pointable at a modified engine through a `run_one` callable |

Almost every file in `tests/module/` is in the
[numeric backend matrix](#the-numeric-backend-matrix), because driving the engine
is what those tests do and the substrate is where its arithmetic happens.

### The `slow` marker

A test that costs seconds to minutes is marked `@pytest.mark.slow`. Marked tests
still run by default — they are guards, and a guard that has to be remembered is
not a guard — but a tight edit-test loop can drop them with `-m "not slow"`.

**One function carries the marker**, expanding to one case: the guard that MLX
stays optional (`tests/seed_unit/test_numeric_backends.py`), which runs the engine
in a child interpreter with MLX and NumPy made unimportable. It chooses its own
backend environment, which is why it sits outside the numeric matrix.

Three others carried it until the expected-range oracle was removed; see below.

The parallel layer adds two more, both in `tests/parallel/test_speculative_exact.py`:
a sweep of every demo problem at 4 and 16 workers, and six runs to their natural end
at 8 workers, each compared bit for bit with the stream-serial reference. The sweep
runs one seed per problem by default; `PETACAT_SPECULATIVE_SWEEP_SEEDS=5` restores
the full sweep (five seeds at 2, 4, 8 and 16 workers, about 25 minutes), which is
worth running under `.venv-ft` after any change to the speculative executor.

### Regressions: what replaced the expected-range oracle

This section used to describe `tests/module/test_expected_range.py` and the
saturated baseline in `tests/fixtures/expected_range.json` as the project's
regression oracle. **Both are gone**, along with `test_splittable_rng_range.py`,
and the reason is worth keeping because it is easy to rebuild the same mistake.

That baseline was 410,000 runs *of Petacat*, so it could detect drift but never
divergence: an engine that disagreed with MetaCat from the outset agreed with
itself perfectly, and every one of the reference's own answers arriving for the
first time was read as an anomaly. The decision and the evidence are in
`DISCREPANCIES3.md`.

**The comparison now points at Metacat's measured behaviour instead.**
`scripts/compare_to_metacat.py` runs 100 tries per problem from a fresh Episodic
Memory against the single-run sets in `measurements/reference/`: every stopping
state of Metacat's 50,000 construction and validation runs per problem in the
support-v1a study, derived from `studies/support-v1a/data/main.tar.gz` by
`scripts/make_reference_sets.py`. Its second mode, eight-run episodes with memory
carried forward, needs convergence sets this repository does not have, because no
study here keeps every run of an episode. It runs with `--reference` pointing at a
directory that has them (a Metacat checkout's `oracle/derived/`); otherwise the
default `--mode both` runs single runs only and says so, and `studies/episodic-v3`
is the in-repository check of episodes. It reports two flags and fails nothing:

- **MISSING** — a p50 member of the reference set that Petacat did not produce.
  Decisive: the false-alarm rate at n=100 is 0.0000 on every problem.
- **NOVEL** — something Petacat produced that the reference never did. Only as
  strong as the reference set's saturation (`f1/n` is at most 0.0004 on every
  problem), which is why the episodic mode separates members the reference reaches
  in single runs from members it reaches nowhere.

It is **not part of the test suite**, and that is deliberate: MetaCat is
stochastic and self-watching with no ground truth, so the comparison says stable
or changed, never pass or fail. Run it when the codelet scheduler, the random
stream, the numeric backend or the update cycle moves:

```bash
.venv/bin/python scripts/compare_to_metacat.py -n 100
.venv/bin/python scripts/make_reference_sets.py   # rebuild measurements/reference/ (about two minutes)
```

Its own decision logic *is* under test, in
`tests/unit/test_compare_harness.py` — a broken comparison does not crash, it
stops flagging, and a cycle comes back clean because nothing looked.

The protocol is Metacat's `ORACLE-USAGE.md` (reconstructed into
`Metacat/build/source/`); the root causes of every variation found against the
earlier reference are in `DISCREPANCIES4.md`.

### The oracle's environment

`tests/support/expected_range.py` survives the removal above, because
`test_population.py`, `test_dissertation_parity.py` and `test_numeric_engine.py`
use its `default_run_one` helper, and `scripts/measure_staleness.py` and
`scripts/bench_engine.py` drive it. Its pool runs workers on the NumPy backend,
set before any engine object exists, so each worker holds one CPU numeric context.

| Variable | Effect |
|---|---|
| `PETACAT_NUMERIC_BACKEND_WORKERS` | The backend the pool's workers run on |
| `PETACAT_ORACLE_ALLOW_GPU` | Lets the workers take the default policy |
| `PETACAT_RANGE_RUNS` | Samples per problem |
| `PETACAT_RANGE_TIMEOUT` | Per-sample deadline in seconds; `0` waits indefinitely |

The `PETACAT_RANGE_GPU*`, `PETACAT_RANGE_WORKERS` and `PETACAT_RNG_RANGE_RUNS`
variables documented here previously were read only by the deleted tests, and
nothing consults them now.

### The client suite

`client/` carries a Vitest suite covering the store, the panels, the admin
editors and the review surfaces. Run it with `cd client && npx vitest run`, and
`npx tsc --noEmit` alongside it. **545 cases across 38 files**, all passing, in
3.1 s on an Apple M-series machine.

| File (`client/src/`) | Cases | Covers |
|----------------------|------:|--------|
| `api/errors.test.ts` | 5 | One failure, one sentence a reader can act on |
| `api/ws.test.ts` | 4 | The URL the client opens is the route the server serves |
| `store/displayStore.test.ts` | 7 | Panel visibility (an entry for every panel including the EEG, Verbose hidden by default, toggling, show or hide all, remembered in localStorage, and surviving storage that throws) and the graphics switches that stop and resume the Slipnet and Coderack polls independently |
| `store/runStore.test.ts` | 44 | The spreading threshold outliving a page reload, and the store's run lifecycle |
| `hooks/useWorkspaceClick.test.ts` | 3 | Clicking the Workspace steps when idle, stops a running run and resumes it on the next click, and ignores other buttons and a missing run |
| `components/AdminPanel.test.tsx` | 6 | The Admin panel's operations report what became of them, and it says it edits the global configuration Metacat Mode uses |
| `components/CoderackBars.test.tsx` | 9 | The Coderack window as Metacat draws it: a slot per codelet type in engine order, bars at the engine's selection probability and never derived from a type's name, counts and total, the last-run marker, a recorded coderack without probabilities, and the Options-menu switches for the count column and the last-type marker |
| `components/CoderackView.test.tsx` | 6 | The Coderack panel's codelet-pattern clamps |
| `components/ClampControls.test.tsx` | 5 | Clamp theme pattern, Undo last clamp and the mid-run Self-watching toggle, as Metacat's Options menu has them |
| `components/CommentaryPanel.test.tsx` | 7 | An empty commentary panel has two different causes |
| `components/EegView.test.tsx` | 4 | The EEG window: the two curves titled in Metacat's colours, each starting at 100 with one point per cycle, the message when a run has no EEG, and the live run read from the store |
| `components/HamburgerMenu.test.tsx` | 3 | Training is a view of its own, between Review and Configuration, and choosing it reports the view to the app |
| `components/HelpPopover.test.tsx` | 3 | The popover shows a glossary term, and says when it cannot |
| `components/LastErrorBanner.test.tsx` | 3 | The error channel is rendered where it can be seen |
| `components/MemoryView.test.tsx` | 19 | The Memory panel shows the memory the run is thinking against, labelled as Metacat Mode's Episodic Memory |
| `components/ModeSwitch.test.tsx` | 15 | The header's switch between Metacat Mode and Training Mode: which mode each view belongs to, moving between them, the help link, and staying put while a run is processing |
| `components/MomentDisplay.test.tsx` | 21 | Clicking a Trace event, answer or snag redisplays the moment: the Workspace header and highlights, the Slipnet pattern, the Coderack, the Temperature, the Trace window's print-name labels |
| `components/ProblemInputPanel.test.tsx` | 7 | The problem panel owns the problem's identity |
| `components/RunControlsPanel.test.tsx` | 56 | A run starts on the problem the form actually shows, and the Workers control is labelled as the run mode |
| `components/RunHistory.test.tsx` | 34 | Run History stays current as runs finish |
| `components/RunParametersPanel.test.tsx` | 14 | The twenty-six run parameters, settable before a run |
| `components/SearchPalette.test.tsx` | 7 | Cmd+K search reaches every kind of help topic |
| `components/SelfWatchingWarning.test.tsx` | 4 | The red warning shown whenever self-watching is off: absent while it is on, and separate warnings for the next run and the loaded run, following a catalogue default of off |
| `components/SlipnetGraphView.test.tsx` | 7 | The Slipnet graph says what it could not do |
| `components/SlipnetView.test.tsx` | 8 | The node-focus Edit button's visibility |
| `components/SubstrateBadge.test.tsx` | 5 | The header says which processor the arithmetic runs on |
| `components/SwarmPanel.test.tsx` | 6 | The Swarm group: it sends the form's problem with the chosen seeds, shows the distribution and telemetry returned, uses justification mode when there is an answer, disables itself with a reason when the plugin is detached or the seed count is over the limit or there is no problem, and shows a server error without losing the form |
| `components/TemperatureGauge.test.tsx` | 8 | The gauge reports the engine's temperature clamp |
| `components/ThemespaceView.test.tsx` | 14 | The Themespace grid is clampable, as MetaCat's theme windows are; its theme-edit mode |
| `components/VerbosePanel.test.tsx` | 11 | The Verbose panel and the store's narration: polled from where the last reply ended, bounded on both sides, the Step button sent as step mode, the mode remembered with no run loaded |
| `components/WindowsMenu.test.tsx` | 3 | The Windows menu lists Hide/Show for each panel including EEG, hides and shows all windows, and carries the Slipnet and Coderack graphics switches |
| `components/WorkspaceView.test.tsx` | 12 | Workspace labels do not print on top of each other |
| `components/admin/AdminEditors.test.tsx` | 42 | Every Configuration tab edits the collection it shows |
| `components/admin/AdminHttpFailures.test.tsx` | 10 | The Configuration screen reports what the server refused |
| `components/review/EpisodicRunTimeline.test.tsx` | 3 | A note being typed on an Episodic Memory clear survives a late refresh, and an untouched note follows the server |
| `components/review/ReviewPanel.test.tsx` | 34 | The review surfaces read the record back, and the episodic-run timeline shows each Episodic Memory clear between the runs with an editable note |
| `components/training/problemText.test.ts` | 37 | Parsing pasted or uploaded problems (letters only, 1 to 64 characters, case-sensitive; JSON entries with their own seeds, answer and tag) and the preview the Training view shows before adding them |
| `components/training/TrainingPanel.test.tsx` | 59 | The Training view: the list and the selected Training, creating one, adding problems, the error-policy fields, the problems table searched and sorted through the server, the Memory tab, and the controls (pause, resume, close, cancel, export) |

### Running under the free-threaded interpreter

`.venv-ft` holds CPython 3.14.9 built without the GIL (`python3.14t`,
`Py_GIL_DISABLED=1`), the same release as `.venv`. It exists because the
concurrency work is meaningless on an interpreter that cannot execute Python on two
cores at once, and the suite is run under it as well as under the standard build.
The parallel layer matters most there: the speculative executor's exactness tests
(`tests/parallel/test_speculative_exact.py`, and its `slow` sweep) only meet real
interleavings when the threads genuinely overlap.

```bash
# The suite, with the GIL genuinely off
PYTHON_GIL=0 .venv-ft/bin/python -m pytest tests/ -q

# One layer, quickly
.venv-ft/bin/python -m pytest tests/unit/ -q
```

`PYTHON_GIL=0` is not decoration. Importing SQLAlchemy **re-enables the GIL at
runtime** — `sqlalchemy.cyextension.collections` has not declared free-threaded
safety, and CPython silently switches the lock back on when it loads such a
module — so without the override the e2e layer runs with the GIL on and the
free-threaded build tells you nothing. Importing the *engine* leaves the GIL off
unaided, because the engine imports nothing beyond the standard library and
itself; that is the property `tests/architecture/test_engine_purity.py` protects, and it
is the reason codelet parallelism gets a genuinely lock-free interpreter while
only the API process pays.

NumPy and MLX are installed in `.venv-ft` (both ship free-threaded wheels), so
the matrix runs both roles there as it does under the standard build.

Single-threaded, the free-threaded build now costs nothing measurable against the
standard one (14,195 against 13,824 codelets per second on an M5 Max, identical
codelet counts). What it used to cost, and why it scaled so badly across threads,
was the engine rather than the interpreter: binding the codelet builtins set
`__name__` and `__doc__` on about 270 fresh closures per codelet, and on a
free-threaded build every such assignment stops the world. The README's
[parallelism section](README.md#parallelism-the-serverparallel-plugin) has the rest.

Rebuilding it: Homebrew's `python-freethreading` moves to each new minor release
(it is 3.15 at the time of writing), so the interpreter comes from `uv`, which
pins the exact build:

```bash
uv python install 3.14.9+freethreaded
"$(uv python find 3.14.9+freethreaded)" -m venv .venv-ft
.venv-ft/bin/pip install -e ".[dev]" numpy mlx
```

### Benchmarks are not tests

`scripts/bench_*.py` measure; they do not assert, and they are not collected by
pytest. They exist so that a performance claim in `PHASE 0 PLAN.md` can be
re-derived rather than trusted: `bench_engine.py` (per-phase timings and Amdahl
fractions), `bench_numeric.py` (backend scaling from 59 to 10⁵ nodes),
`bench_shards.py` (coderack shard fidelity and contention),
`bench_free_running.py` (throughput and conflict rate by worker count), and
`bench_population.py` (runs per second at K = 1/8/32/128). They take minutes and
load the machine, so run them deliberately.

## Unit-test rules

Every file in `tests/unit/` must obey these five rules. Rules 1, 2, 4 and 5 hold
for `tests/seed_unit/` as well, which is the same shape of test with one
allowance: rule 3 lets the shipped seed data stand in for a double, because there
the real value is what is being asserted about.

1. **Business logic only.** Test algorithms and behaviour — not glue code,
   framework wiring, or API endpoints. A test that only asserts a constant is
   a string, an enum's membership, or a dataclass echoes its constructor args
   is *not* a unit test and does not belong here.
2. **One path per test.** Each test exercises a single path through the unit.
   Alternative branches, boundary cases, and error paths are **separate
   tests**. If a test asserts across two branches (e.g. `threshold=100` *and*
   `threshold=0`, or "identity" *and* "slippage"), split it.
3. **Completely mock dependencies.** A unit test isolates one unit; replace
   every collaborator with a deterministic double (see
   [Test doubles](#test-doubles-testsunit_fakespy)). If a unit's
   dependencies are so extensive that mocking is impractical, that is a signal
   to **refactor the source** for testability (dependency injection,
   abstraction, polymorphism, parameterization) rather than to write a heavy,
   coupled test. Refactoring source code to make it testable is encouraged.
4. **Deterministic.** No test may depend on wall-clock time or unseeded
   randomness. Petacat funnels all randomness through
   [`engine/rng.py`](server/engine/rng.py); construct `RNG(seed)` with a fixed
   seed, or supply deterministic mock data. The same test must produce the
   same result on every machine and every run.
5. **Bottom-up, research-driven.** Prioritise coverage from the data-structure
   layer upward. Within that ordering, weight effort toward the modules that
   carry the project's research contribution — the **self-watching**
   machinery: Themespace (`themes.py`), Temporal Trace (`trace.py`), Episodic
   Memory (`memory.py`), and Jootsing (`jootsing.py`).

## Test doubles (`tests/unit/_fakes.py`)

Shared, hand-rolled fakes live in `tests/unit/_fakes.py` (the leading
underscore keeps pytest from collecting it as a test module). They implement
*only* the surface the engine actually consumes, so a test reads as an
explicit statement of the unit's true inputs:

- `FakeNode` — a slipnet node (`activation`, `conceptual_depth`,
  `fully_active()`, link lists). `fully_active` is an explicit boolean the
  test sets, so relevance logic never depends on real activation thresholds.
- `FakeLink` — a slipnet link with a fixed `degree_of_association()`.
- `FakeString` — a workspace string with independent `objects` / `letters` /
  `groups` lists.
- `FakeObject` / `FakeContainer` — an atomic object vs. a group-like container
  (the latter can nest members for containment checks).
- `FakeDescription` — a description entry carried on `object.descriptions`.

Where a unit needs geometry or config the shared fakes don't carry (e.g. bond
string positions, or the Themespace's coefficient reads), define a small local
fake in that test file rather than bloating `_fakes.py`. Config-heavy units are
mocked with a per-file `_FakeMeta` that returns fixed coefficients — this keeps
formula-driven dynamics (e.g. the Themespace `tanh` spreading) exactly
assertable.

Prefer explicit fakes over `unittest.mock` for engine collaborators: they are
clearer, self-documenting, and impossible to mis-configure into passing
vacuously.

---

## Deferred work (prioritised TODO)

Discovered during the first unit-testing pass. Ordered by priority.

### P1 — Continue bottom-up coverage of low-level structures
- [x] `groups.py` — length, spanning, membership/containment, internal/external
      strength, flipping, constituent queries (`test_groups.py`).
- [x] `workspace_objects.py` — geometry, bond bookkeeping, importance,
      intra-string unhappiness, bridge weakness (`test_workspace_object.py`).
- [x] `workspace.py` → `WorkspaceString` — bond/group management, counting,
      equivalence, spanning, relevance (`test_workspace_string.py`).
- [ ] `workspace.py` → `Workspace` — the outer container's aggregation
      (average unhappiness, mapping strength, unmapped-object counts). Several
      of these methods reach across strings/bridges; isolate with fakes or flag
      for refactoring where the coupling is heavy.

### P2 — Deepen self-watching (research core)
- [ ] `trace.py` — pattern detection beyond the basic record/snag paths.
- [ ] `jootsing.py` — snag detection and jootsing (negative-theme clamping).
- [ ] `themes.py` — multi-theme intra-cluster excite/inhibit dynamics
      (the first pass pins the single-theme decay path only).
- [ ] `justify.py` — justification-mode rule building and translation.

### P3 — Broaden mid-level coverage
- [ ] `rules.py` — quality computation (uniformity / abstractness /
      succinctness); currently only predicates + `translate` are tested.
- [ ] `bridges.py` — convert the integration-flavoured tests to isolated units
      with a stub letter instead of a full `Workspace`.
- [ ] `images.py` — abstract image pattern matching.

### P4 — Finish the audit cleanup
- [x] Replace the vacuous assertions in `test_codelet_behaviours.py` (tests
      that only assert "doesn't crash" or `after >= before`) with meaningful
      checks, or move them to `tests/module/`. **Done** — the file carries no
      vacuous assertion.
- [ ] Decide the fate of the pure constant/enum tests (Rule 1 violations):
      delete, or consciously keep as change-detector guards and document why.
- [x] Place every test in the layer whose dependencies it stays inside.
      **Done** — `tests/seed_unit/` and `tests/architecture/` hold what the
      other layers' rows do not cover, and the engine-driving tests live in
      `tests/module/`.

### P5 — Testability refactors (source changes, pre-approved)
- [ ] `concept_mappings._descriptor_is_distinguishing` does an inline
      `from ...groups import Group` for an `isinstance` check — replace with a
      polymorphic `obj.is_group()` so the group path is unit-testable without
      constructing a real `Group`.
- [ ] `themes.ThemeCluster.spread_activation` reads ~8 coefficients from
      `meta` — parameterize so the dynamics can be tested without a full
      `MetadataProvider`.
