# Testing Guide

This document defines how Petacat's **backend** tests are written and
organised. It exists so that new tests stay consistent, deterministic, and
focused on the research goals of the project.

## The required command

```bash
.venv/bin/python -m pytest tests/ -q
```

This is the command a change is verified with. It runs all six layers against the
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
  cpu  numpy    float64    250 tests
  gpu  mlx      float32    250 tests
  whole suite requested: the full matrix is required of this run

  unit           525 collected    525 run    525 passed      0 failed      0 skipped  complete
  seed_unit      456 collected    456 run    456 passed      0 failed      0 skipped  complete
  module         901 collected    901 run    901 passed      0 failed      0 skipped  complete
  architecture    34 collected     34 run     34 passed      0 failed      0 skipped  complete
  integration     68 collected     68 run     68 passed      0 failed      0 skipped  complete
  e2e            256 collected    256 run    256 passed      0 failed      0 skipped  complete

  run complete in 14.2 min against a 60 min ceiling
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
  module         901 collected    198 run    198 passed      0 failed      0 skipped  INCOMPLETE

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

The backend suite (`tests/`) is organised into six layers. A layer is defined by
what its tests are allowed to reach for, and every test in a layer stays inside
that allowance.

| Layer | Directory | Scope | May depend on | Cases |
|-------|-----------|-------|---------------|-------|
| **unit** | `tests/unit/` | One class or function, business logic only | Only what the test constructs: hand-rolled fakes and plain engine objects | 525 |
| **seed unit** | `tests/seed_unit/` | One class or function, measured against the values Petacat ships with | Real `seed_data/*.json`, and the machine the process is running on | 456 |
| **module** | `tests/module/` | Several real components assembled and driven | Real engine objects and `seed_data/*.json`; no DB, no HTTP | 901 |
| **architecture** | `tests/architecture/` | How the source tree is allowed to depend on itself | The repository's source, `seed_data/*.json`, child interpreters | 34 |
| **integration** | `tests/integration/` | Agreement between the repository's artifacts, and the harness's own rules | Real `seed_data/*.json`, the ORM declarations, the generated client files, the documentation, a real pytest session | 68 |
| **e2e** | `tests/e2e/` | Full HTTP API + persistence | Local PostgreSQL (`petacat_test`) | 256 |

Those counts are cases, so they include the second pass the numeric matrix makes
over the 250 backend-sensitive tests.

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
- **e2e** — the assertion travels over HTTP.

A first pass should test **the lowest level of code just above the database
first**, then move up toward the API and GUI.

All six layers run in one command — the
[required command](#the-required-command) — and, since Petacat runs natively, all
six actually run: **2,240 cases**, every one of them executed. A layer that is
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
> `server/engine/coderack_shards.py` before reaching for `--numeric-backends`.**
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

**`tests/unit/` — one class or function, against what the test constructs**

| File | Fns | Covers |
|------|----:|--------|
| `test_bonds.py` | 25 | `Bond`: direction, facet, strength, flipping |
| `test_bridge_types.py` | 2 | The bridge-type and orientation constants |
| `test_codelet_dsl.py` | 3 | Compiling a codelet body: what the interpreter accepts and refuses |
| `test_commentary.py` | 23 | The `CommentaryLog`, and the emit helpers whose English is written in Python |
| `test_compare_harness.py` | 17 | The oracle comparison's decision logic: what gets flagged, and how, and its engine-parameter passthrough |
| `test_concept_mappings.py` | 37 | `ConceptMapping`: identity, slippage, distinguishing descriptors |
| `test_descriptions.py` | 23 | `Description`: relevance, strength, descriptor predicates |
| `test_episodic_memory.py` | 13 | `EpisodicMemory`: identifier scoping, theme distance, `answer_present` |
| `test_formulas.py` | 25 | Averaging, the sigmoid, and the five translation-temperature distributions |
| `test_groups.py` | 22 | `Group`: length, spanning, membership, internal and external strength |
| `test_jootsing_outcomes.py` | 7 | The jootser's outcomes: what counts as the same clamp, and when it gives up |
| `test_object_choice.py` | 8 | Weighted object choice: the temperature exponent, and the absence of floors |
| `test_rng.py` | 16 | The deterministic RNG wrapper |
| `test_rule_types.py` | 9 | `Rule` and `RuleClause` predicates and translation |
| `test_runner_status.py` | 1 | The runner's status constants |
| `test_scout_counts.py` | 14 | The scout-count aggregates that decide how many codelets a cycle posts |
| `test_sink.py` | 8 | The `RunSink` port: its event vocabulary and `NullSink` |
| `test_slipnet_node.py` | 30 | Nodes and links built directly: degree of association, probabilistic jump |
| `test_snag_response.py` | 21 | The snag response and the clamp machinery, one piece at a time |
| `test_splittable_rng.py` | 21 | Counter-based per-codelet random streams |
| `test_structure_fights.py` | 13 | `wins-fight?` and the weights the builders bring to a fight |
| `test_temperature.py` | 3 | `Temperature`'s own state: starting value and clamp |
| `test_thematic_scouting.py` | 20 | The thematic-bridge-scout's decisions (`themes.ss:750-1030`) |
| `test_theme_types.py` | 6 | `Theme` and `Themespace` type constants |
| `test_themespace.py` | 31 | Themespace self-watching dynamics: cluster spreading, dominance |
| `test_trace_event.py` | 6 | `TemporalTrace` event recording |
| `test_workspace_object.py` | 40 | `WorkspaceObject` and `Letter`: geometry, importance, unhappiness |
| `test_workspace_string.py` | 28 | `WorkspaceString`: bond and group management, spanning, relevance |
| `test_workspace_structure.py` | 10 | The base structure class and its proposal levels |

**`tests/seed_unit/` — one class or function against the shipped values**

| File | Fns | Covers |
|------|----:|--------|
| `test_answer_comparison.py` | 42 | The answer-comparison and answer-explanation English (`answers.ss:267-882`) |
| `test_answer_description.py` | 4 | Storing, reminding and comparing inside `EpisodicMemory` |
| `test_bridge_types.py` | 4 | Bridge orientation over letters of a real Workspace |
| `test_codelet_dsl.py` | 2 | The codelet registry built from the seeded codelet types |
| `test_coderack_bin.py` | 10 | The Coderack's urgency bins and temperature-weighted choice |
| `test_coderack_clamping.py` | 14 | Codelet-type clamping, against the urgencies Petacat ships with |
| `test_coderack_eviction.py` | 19 | Incremental eviction picks exactly what the flat scan picked |
| `test_commentary.py` | 6 | The emit helpers that render from the seeded commentary templates |
| `test_episodic_memory.py` | 20 | Reminding, comparison and the reminding distance, which resolve the seeded templates and the seeded conceptual depths |
| `test_formulas.py` | 15 | The temperature-dependent formulas against the seeded coefficients |
| `test_hardware.py` | 21 | The machine description and the sizes derived from it: real probes, faked probes, environment overrides |
| `test_metadata_provider.py` | 25 | `MetadataProvider` loading every seed collection |
| `test_numeric_backends.py` | 25 | The numeric backends against the reference, and the engine without them |
| `test_rule_quality.py` | 13 | Rule uniformity, abstractness and succinctness against the Scheme's formulas, hand-computed from the seeded depths |
| `test_slipnet_link_lengths.py` | 6 | The Slipnet's link lengths against the reference Scheme |
| `test_slipnet_node.py` | 23 | The 59-node Slipnet: its nodes, its links, its clamps and its spreading |
| `test_temperature.py` | 2 | Temperature updating against the seeded coefficients |

**`tests/module/` — real components assembled and driven**

| File | Fns | Covers |
|------|----:|--------|
| `test_access_sets.py` | 19 | Read-set / write-set discipline and commit-time validation |
| `test_answer_description_pattern.py` | 13 | The vertical theme-pattern an answer description is indexed by |
| `test_bridge_scouting.py` | 25 | The bridge scouts' probabilistic gates, the build-time mapping augmentation, the incompatibility refinements, and the deferred posting batch |
| `test_capture_projection.py` | 8 | A recorded capture renders exactly as the same state renders live |
| `test_codelet_behaviours.py` | 79 | What each of the 27 codelet types does to a live workspace |
| `test_codelet_dsl.py` | 7 | Codelet bodies executed against a live engine context |
| `test_coderack_shards.py` | 13 | The candidate sharded coderacks: fidelity and contention |
| `test_commentary_writer.py` | 8 | Commentary is an injected writer, and every Run gets a real one |
| `test_dissertation_parity.py` | 45 | The dissertation's claims, encoded as tests |
| `test_free_running.py` | 14 | Free-running execution across worker threads |
| `test_group_image_direction.py` | 6 | A group's image is built in the group's own direction |
| `test_image_relations.py` | 4 | The relations a group's image is built with, and what happens when they are wrong |
| `test_justify_and_jootsing.py` | 11 | Justify mode's verdicts and the jootser's justify outcomes |
| `test_numeric_engine.py` | 7 | The engine computes the same thing with the substrate engaged |
| `test_population.py` | 9 | Population batching: K independent runs together |
| `test_run_identifiers.py` | 8 | Identifiers depend on the run, not on the process's history |
| `test_rule_object_descriptions.py` | 8 | What a rule may name its object by, and whether that name finds anything |
| `test_run_to_answer.py` | 7 | Run-to-answer behaviour at the `EngineRunner` level |
| `test_runner.py` | 19 | `EngineRunner`: initialisation, stepping, the update cycle |
| `test_runner_commentary.py` | 6 | Commentary emitted as the runner drives a problem |
| `test_runner_status.py` | 6 | The status an `EngineRunner` reports as a run moves through it |
| `test_singleton_group_images.py` | 3 | Every object a rule names owns an image, singleton groups included |
| `test_sink_emission.py` | 9 | The engine emits a complete run record to its sink |
| `test_snag_response.py` | 7 | The snag response driven end to end through a real run |
| `test_staleness.py` | 8 | The staleness probe reads a Workspace that lags the live one |
| `test_state_graph.py` | 11 | A captured run restores to a state that continues identically |
| `test_swaps_and_translation.py` | 14 | Extrinsic (swap) rules end to end, the conflict battery, the per-dimension slippage ignore, and the ways a translation fails |
| `test_thematic_bridge_scout.py` | 9 | The thematic-bridge-scout inside an assembled engine |
| `test_themespace.py` | 14 | Themespace driven by a real run's bridges |
| `test_trace_persistence.py` | 7 | Trace event persistence logic |
| `test_workspace.py` | 19 | Workspace aggregation across its four strings |

**`tests/architecture/` — properties of the source tree**

| File | Fns | Covers |
|------|----:|--------|
| `test_engine_purity.py` | 18 | Nothing under `server/engine/**` imports `sqlalchemy`, `server.models`, `server.db` or `server.services`, and the serializers run in an interpreter where those cannot be imported |

**`tests/integration/` — the repository's artifacts agree**

| File | Fns | Covers |
|------|----:|--------|
| `test_documented_code_shape.py` | 4 | The engine's size, the endpoint count, the builtins module and the Run Controls groups, as the documentation states them |
| `test_documented_counts.py` | 3 | Every documented layer count, suite total and per-file figure, against the collection that produced it |
| `test_enum_constants.py` | 17 | Engine string constants match `seed_data/enums.json` |
| `test_help_topics.py` | 13 | The help JSON, the generated TypeScript and the panels that reference them |
| `test_metadata_seeding.py` | 13 | Every seed file is well-formed, and the `MetadataProvider` round-trip holds |
| `test_numeric_matrix_harness.py` | 11 | The matrix's own reporting rules and the exit status of a narrowed run |
| `test_seed_reconciliation.py` | 7 | The DB copy of the metadata tracks the seed files without eating runtime data, and the seeder refills every table it empties |

**`tests/e2e/` — the HTTP API against a real database**

| File | Fns | Covers |
|------|----:|--------|
| `test_api_controls.py` | 20 | Breakpoints, clamping and the threshold endpoints |
| `test_api_docs.py` | 11 | The documentation endpoints |
| `test_api_extended.py` | 56 | Extended runs, memory, docs and admin endpoints |
| `test_api_review.py` | 19 | The review surfaces read back what the persistence modes wrote |
| `test_api_runs.py` | 26 | The runs API with persistence |
| `test_api_system.py` | 8 | The system endpoints: what is executing, not what was recorded |
| `test_help_api.py` | 7 | The help topics API |
| `test_persistence.py` | 4 | Snapshot save/restore and the DB metadata round-trip |
| `test_persistence_modes.py` | 30 | The three persistence modes: Fast, Normal, Audit |
| `test_run_parameters.py` | 13 | Run parameters are settable per Run, stored, and readable back |
| `test_run_to_answer.py` | 8 | The Run-to-Answer feature over HTTP |
| `test_snag_identity.py` | 2 | A snag is the same snag whichever endpoint served it |
| `test_step0_config_from_db.py` | 47 | Step 0's guard tests: a shipped value reproduces the run and a changed one moves it |

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

**The comparison now points at Metacat's published sets instead.**
`scripts/compare_to_metacat.py` runs 100 tries per problem in each of two modes —
single runs from a fresh Episodic Memory, and eight-run episodes with memory
carried forward — against the oracle in `../Metacat/oracle/derived/`, sampled from
the reference implementation itself. It reports two flags and fails nothing:

- **MISSING** — a p50 member of the reference set that Petacat did not produce.
  Decisive: the false-alarm rate at n=100 is 0.0000 on every problem.
- **NOVEL** — something Petacat produced that the reference never did. Only as
  strong as the reference set's saturation, which is why the episodic mode
  separates members the reference reaches in single runs from members it reaches
  nowhere.

It is **not part of the test suite**, and that is deliberate: MetaCat is
stochastic and self-watching with no ground truth, so the comparison says stable
or changed, never pass or fail. Run it when the codelet scheduler, the random
stream, the numeric backend or the update cycle moves:

```bash
.venv/bin/python scripts/compare_to_metacat.py -n 100 -r 8
```

Its own decision logic *is* under test, in
`tests/unit/test_compare_harness.py` — a broken comparison does not crash, it
stops flagging, and a cycle comes back clean because nothing looked.

The protocol is `../Metacat/ORACLE-USAGE.md`; where Petacat currently stands
against it, and the root causes of every variation found, is `DISCREPANCIES4.md`.

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
`npx tsc --noEmit` alongside it. **316 cases across 23 files**, all passing, in
3.2 s on an Apple M2 Max.

| File (`client/src/`) | Cases | Covers |
|----------------------|------:|--------|
| `api/errors.test.ts` | 5 | One failure, one sentence a reader can act on |
| `api/ws.test.ts` | 4 | The URL the client opens is the route the server serves |
| `store/runStore.test.ts` | 39 | The spreading threshold outliving a page reload, and the store's run lifecycle |
| `components/AdminPanel.test.tsx` | 5 | The Admin panel's operations report what became of them |
| `components/CoderackView.test.tsx` | 6 | The Coderack panel's codelet-pattern clamps |
| `components/CommentaryPanel.test.tsx` | 3 | An empty commentary panel has two different causes |
| `components/HelpPopover.test.tsx` | 3 | The popover shows a glossary term, and says when it cannot |
| `components/LastErrorBanner.test.tsx` | 3 | The error channel is rendered where it can be seen |
| `components/MemoryView.test.tsx` | 16 | The Memory panel shows the memory the run is thinking against |
| `components/ProblemInputPanel.test.tsx` | 7 | The problem panel owns the problem's identity |
| `components/RunControlsPanel.test.tsx` | 40 | A run starts on the problem the form actually shows |
| `components/RunHistory.test.tsx` | 31 | Run History stays current as runs finish |
| `components/RunParametersPanel.test.tsx` | 14 | The twenty-six run parameters, settable before a run |
| `components/SearchPalette.test.tsx` | 7 | Cmd+K search reaches every kind of help topic |
| `components/SlipnetGraphView.test.tsx` | 7 | The Slipnet graph says what it could not do |
| `components/SlipnetView.test.tsx` | 8 | The node-focus Edit button's visibility |
| `components/SubstrateBadge.test.tsx` | 5 | The header says which processor the arithmetic runs on |
| `components/TemperatureGauge.test.tsx` | 8 | The gauge reports the engine's temperature clamp |
| `components/ThemespaceView.test.tsx` | 8 | The Themespace grid is clampable, as MetaCat's theme windows are |
| `components/WorkspaceView.test.tsx` | 10 | Workspace labels do not print on top of each other |
| `components/admin/AdminEditors.test.tsx` | 42 | Every Configuration tab edits the collection it shows |
| `components/admin/AdminHttpFailures.test.tsx` | 11 | The Configuration screen reports what the server refused |
| `components/review/ReviewPanel.test.tsx` | 34 | The review surfaces read the record back |

### Running under the free-threaded interpreter

`.venv-ft` holds CPython 3.14.6 built without the GIL (`python3.14t`,
`Py_GIL_DISABLED=1`). It exists because the concurrency work is meaningless on
an interpreter that cannot execute Python on two cores at once, and the suite is
run under it as well as under the standard build.

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

NumPy and MLX are not installed in `.venv-ft`, so the numeric substrate falls
back to its pure-Python reference backend there. Tests that need a specific
backend skip rather than fail when it is unavailable, and the matrix reports its
`cpu` role as filled by `python` and its `gpu` role as not installed — one pass,
on the reference, stated in the summary.

The interpreter costs roughly 9% single-threaded against the standard build,
with identical codelet counts — so it is the interpreter's overhead, not
different cognition, and the parallelism has to beat it before it earns
anything.

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
