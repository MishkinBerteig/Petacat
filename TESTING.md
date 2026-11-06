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

which drops the tests marked `slow` and puts the whole session on one CPU
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

**What float32 can and cannot promise.**
Activations live in [0, 100], and float32 carries about seven significant digits
where float64 carries sixteen. Under the Metacat Standard Configuration that
difference has not been seen to matter. The Slipnet update rounds every decay and
every per-edge contribution to a whole number before anything is summed
(`numpy_backend.py` `np.rint`, `mlx_backend.py` `mx.round` and the fused kernel's
`rint`), so an activation is always a whole number between 0 and 100, which float32
represents exactly, and the activation never decays to a subnormal.

*The guard.* `backend.exact_backend_for` refuses a float32 backend under a configuration
outside the measured-exact conditions (see the README, "The exactness guard"; the measurements
are `agents-workspace/metacat-cleanup/round2/S3-dead-open/measure_guard*.py`), and
`tests/seed_unit/test_float32_guard.py` pins its decisions. `apply_jumps` honours `frozen` on
every backend (`tests/seed_unit/test_frozen_jump.py`).

*Measured:* 768 runs (the 41 demo problems, seeds 101 to 112, discovery and
justification). `mlx` on the Metal GPU in float32, through the fused kernel
(`_update_fused`, confirmed by call counts), equalled `off` in float64 in every
recorded field: status, codelet count, answers, RNG draws, a hash of the Trace, a
hash of the temperature series and every final activation. `numpy` and `mlx-cpu`
did too. That is 768 runs at seeds outside the golden set, not a proof for every
seed. *Inferred, not measured:* that the whole-number rounding is why.

The two precisions can still part when activations are fractional. With the
Slipnet's rounding removed, a measurement made while planning v2.0 found the float64
engines identical to each other while `mlx` against `numpy` was run-identical in 116
of 120 runs and state-identical in 0 of 120, and found the GPU reading 0 for activations float64 holds as positive (below
1.18e-38, a subnormal flush). A seed that forks that way reaches a different but
valid run, as it would under any new scheduler or generator that reorders the
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
  cpu  numpy    float64    1142 tests
  gpu  mlx      float32    1142 tests
  whole suite requested: the full matrix is required of this run

  unit          1977 collected   1977 run   1977 passed      0 failed      0 skipped  complete
  seed_unit     1790 collected   1790 run   1790 passed      0 failed      0 skipped  complete
  module        1051 collected   1051 run   1051 passed      0 failed      0 skipped  complete
  architecture   104 collected    104 run    104 passed      0 failed      0 skipped  complete
  integration    366 collected    366 run    366 passed      0 failed      0 skipped  complete
  parallel       304 collected    304 run    304 passed      0 failed      0 skipped  complete
  lockstep       247 collected    247 run    247 passed      0 failed      0 skipped  complete
  e2e            644 collected    644 run    644 passed      0 failed      0 skipped  complete

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
  cpu  numpy    float64      1142 tests
  gpu  mlx      float32     1142 tests
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
  module         1051 collected    198 run    198 passed      0 failed      0 skipped  INCOMPLETE

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
| **unit** | `tests/unit/` | One class or function, business logic only | Only what the test constructs: hand-rolled fakes and plain engine objects | 1977 |
| **seed unit** | `tests/seed_unit/` | One class or function, measured against the values Petacat ships with | Real `seed_data/*.json`, and the machine the process is running on | 1790 |
| **module** | `tests/module/` | Several real components assembled and driven | Real engine objects and `seed_data/*.json`; no DB, no HTTP | 1051 |
| **architecture** | `tests/architecture/` | How the source tree is allowed to depend on itself | The repository's source, `seed_data/*.json`, child interpreters | 104 |
| **integration** | `tests/integration/` | Agreement between the repository's artifacts, and the harness's own rules | Real `seed_data/*.json`, the ORM declarations, the generated client files, the documentation, a real pytest session | 366 |
| **parallel** | `tests/parallel/` | The detachable multi-core plugin (`server/parallel/`): each executor against the serial run it claims to equal | Real engine objects and `seed_data/*.json`, worker processes and threads; each test pins the backend it compares on | 304 |
| **lockstep** | `tests/lockstep/` | Petacat's decision traces against Metacat's: naming, helper conformance, tracing/replay RNGs, determinism guards, the comparer | Real engine in faithful mode (numeric backend off, or a named backend); recorded Metacat traces | 247 |
| **e2e** | `tests/e2e/` | Full HTTP API + persistence | Local PostgreSQL (`petacat_test`) | 644 |

Those counts are cases, so they include the second pass the numeric matrix makes
over the 1142 backend-sensitive tests.

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
eight actually run: **6,483 cases**, every one of them executed. A layer that is
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
doing" looks like in practice. Budget against the largest.

What `-m "not slow"` drops is the tests marked `slow`, among them the ones that recompute a
whole baseline in a fresh interpreter (the golden baseline, the replay of recorded
traces), run a wide seed sweep of the speculative executor or compare a database-fed
run with the seed-fed one over many problems. Reach for the tight loop when you want
a fast loop rather than a number to compare, and for the required command when you
want the number.

> **If `tests/module/test_free_running.py` fails, read
> `server/parallel/free_running.py` and `server/parallel/coderack_shards.py` (the locked rack)
> before reaching for `--numeric-backends`.**
> Those files are the one place the suite runs *codelets* concurrently —
> `test_access_sets`, `test_run_identifiers` and
> `test_splittable_rng` thread over engine state without executing codelets — so
> a red here is a concurrency result first and a backend result second.
>
> This callout used to say the opposite, and said the file was "currently green
> under every backend". It was not: a test that every worker did some work failed
> about 40% of the time on `[numpy]`, bimodally — either an even split across the
> four workers or `[4001, 0, 0, 0]`, nothing in between. The cause was a thread
> startup race, not the substrate, and the advice to check the backend first sent
> a reader looking at float32 for a defect that was not there. `mlx` never failed
> for the revealing reason that it is ~4× slower, so the main thread always won
> the race eventually. The defect is fixed
> (`FreeRunningEngine._all_started`); the lesson kept here is that a red in this
> file is about scheduling until proven otherwise. That test is now
> `test_the_whole_pool_exists_before_any_worker_touches_the_rack`, which checks the
> defect itself. Asserting that every worker claimed a codelet could still fail about
> 1 run in 200 on the GIL build with NumPy, for a worker that had started and had not
> yet had a turn when a short run ended (0 of 400 on `off` at the same load).
>
> A backend can still matter. Under the Metacat Standard Configuration `mlx`
> (float32, Metal GPU) equalled `off` (float64) in every recorded field over 768
> runs (41 problems, seeds 101 to 112; see "What float32 can and cannot promise"),
> so a failure seen only under `mlx` must **not** be written off as a seed
> difference: investigate it as a defect, in the float32 path or in the test.
> Only with fractional activations (a configuration that removes the Slipnet's
> rounding) is a fork of the random stream a known cause. The file is in the numeric matrix, so each case
> carries its backend in its name — `…[numpy]` and `…[mlx]` sit side by side in
> the report. A red `[mlx]` beside a green `[numpy]` is a float32-path
> defect until shown otherwise, and both red is a concurrency defect. Note also that the "group reachable from a bond but absent from its
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
- *The extended golden baseline.* The 188 runs above are the common case: the 19 demo
  problems and the justify demos at seeds 1-5 and one 8-run episode. They leave rare paths
  unreached (a weight on one could move wrongly and no run would notice), so
  `tests/lockstep/golden/extended_baseline.jsonl` and `extended_baseline_rng.json.gz` add
  cases chosen by coverage: each reaches engine lines or branches, a codelet body,
  descriptor predicate or posting formula, or a kind of event, snag or clamp that the
  original runs do not. They include a person's clamps and Undo, Clear Memory between two
  runs of an episode and the answer report of an episode (the explanation of every answer in
  memory and the comparison of every ordered pair), justify with unusual answers, runs the
  codelet cap ends, the engine's own object-graph loops and the pure-Python backend. The
  case list is `tests/lockstep/golden/extended_cases.json`, and **every case in it was
  recorded in Metacat 1.2 and replayed in Petacat with no divergence**; a case that did not
  match is a fidelity defect and is not in the file. `scripts/golden_coverage.py` measures
  what either baseline reaches. Recapture with
  `.venv/bin/python scripts/capture_golden_baseline.py --extended --jobs 8` (it writes only
  the two `extended_` files, so it cannot touch the original baseline) under the same rule as above.
  A case may carry its own `parameters` (the Self-watching-off cases do), and every case also runs on the
  four other numeric backends in a slow test.
- *EN0, the no-node-literals lint.* `tests/architecture/test_no_node_literals_in_engine.py`
  with `no_node_literals_allowlist.txt`: the allow-list may only shrink, and since EN11 it is
  empty. The one seed-file read the lint permits is the door,
  `MetadataProvider.from_standard_configuration` in `server/engine/metadata.py`.
- *EN0, role identity and reduced configurations.* `tests/seed_unit/test_role_identity.py`
  held a skeleton whose comparison with `slipnet.roles` EN3 turned on (it runs now);
  `test_reduced_configurations.py` checks the generated reduced configurations that later
  packages run the engine on.
- *EN3, the role mechanism.* `server/engine/roles.py` (vocabulary, `Roles`, the `Absent`
  token) and `server/engine/start_check.py` (the run-start check, wired at `init_mcat`);
  `tests/seed_unit/test_roles.py` tests them and is the G9 skeleton. No engine code reads a role yet.
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
| `test_rationals.py` | 13 | The rational value kind: `n/m` parsed exactly, refused unless it is two integers over a positive denominator, and stored in lowest terms; the configuration hash follows it. The Metacat Standard Configuration holds `enclosed_group_importance_factor`, `edge_object_bond_factor` and `interior_object_bond_factor` as `2/3`, `1/3` and `1/6`, on the declared read list; under them importance and intra-string unhappiness are the old arithmetic, and a non-standard rational changes them as it implies |
| `test_config_document.py` | 26 | S0: the pure `ConfigDocument` (`server/services/config_document.py`): identity with the files' provider and the engine's `config_hash`, order, structure sharing between versions, errors, codecs (int, float and rational typing), replay against a naive reference model, the incremental hash against the whole hash, and `diff` followed by `apply_resolved` |
| `test_config_registry.py` | 5 | C6: the configuration table registry (`server/services/config_registry.py`): natural keys, order columns, code and JSON columns, the 18 enum tables (the first 13 and the string kinds, rule scopes, failure kinds, clamp types and progress focuses), a NULL link label read as `''`, the frozen spec |
| `test_journal_replay.py` | 5 | C6: pure journal replay, reconstruction from before-images and inverse ops; an update and its undo keep the row's place |
| `test_session_episodic_memory_always.py` | 4 | S11: a Training Mode Session always has an Episodic Memory: no memory, status or `closed_at` columns and non-null episode columns; no shared or independent branch and no `close`; no route clears the memory; the create request forbids extra fields |
| `test_no_training_entity_name.py` | 2 | S12: the grep guard: the old entity name is used nowhere outside Training Mode, Training episode and `training_memory_merges`, in code, UI strings and current docs; and the old modules, routes and component folder are gone |
| `test_problem_text.py` | 11 | Any Unicode text is a valid problem string (`server/services/problem_text.py`): the shared check accepts a broad corpus (scripts, emoji, combining and invisible characters, whitespace, line breaks, 1,000 characters) exactly, keeps NFC and NFD distinct, and refuses only U+0000 and a lone surrogate with clear messages; every request model (session problems, runs, the Swarm, demo problems) uses it, and the session, run and Swarm requests keep the structural rule (non-empty initial, modified and target; an answer absent or non-empty); `check_deep` checks every string and key of a nested value and names the path of a bad one |
| `test_session_episode.py` | 34 | S1: the pure `EpisodeLog` (`server/services/session_episode.py`): one version counter over memory and configuration, the run-finish entry (memory, then batch, then one version), external and Admin entries, relative ops commuting, `expect` first-wins with the loser recorded, abort and skip, targets removed since the snapshot, `config_at` at every version, all interleavings of three runs, removing, renaming or merging a memory-named node, exact reduction to serial, a fuzz test; against a fake and the real `resolve` |
| `test_database_sql_check.py` | 3 | C7: the Database tab's SQL box accepts one `SELECT` or `WITH` statement only (quoted semicolons and comments handled) |
| `test_session_live_config.py` | 20 | S3: `LiveConfiguration` (`server/services/session_live_config.py`): a live session's configuration in memory over the `EpisodeLog`; the configuration revision as the compare-and-set token, distinct from the episode version; run-finish entries; live batches held as pending journal entries in revision order |
| `test_configuration_edits.py` | 8 | C12: edit-all's service: the preview token round trip, the Admin batch each target gets, overwrite and apply-the-rest, and how each report or refusal becomes one of the six per-target results |
| `test_change_resolve.py` | 32 | C14a: `resolve` (`server/services/change_resolve/`): generic ops, `expect`, `ok_if_missing`, JSON Patch; G6 (each malformed, unknown-reference, code, stale and key-exists case refused with the op named and its status); the changes that must not be refused (a role's node, a letter, the chain, every node, a coefficient, a required parameter, an urgency level, a codelet type, every posting rule); advisories; `skip` with rollback; purity, determinism and the report's shape |
| `test_change_resolve_convenience.py` | 36 | C14a: every convenience op equals its expansion into generic ops; cascades, rename, merge, relative ops without clamping, role and trigger ops, and a posting rule naming a tier of the urgency levels (rename rewrites it, removal is reported as a run-start gap and refused at the run, an unknown tier is an unknown reference) |
| `test_change_resolve_property.py` | 6 | C14a: random op sequences keep the document well-formed (no dangling reference, no duplicate key, deterministic, replays); single ops equal one batch; memory-named nodes can be removed, renamed and merged from every source |
| `test_change_resolve_patch_schema.py` | 9 | C14a: the JSON Patch subset, `schema()`, and the refusal type with its status map |
| `test_change_resolve_vocabulary.py` | 28 | Stage 4: `rename_enum_value` over every enum table and `theme_relations` (every referencing column rewritten, the role and the place kept, the keyed commentary sections renamed, what still spells the old name listed as dangling, the refusals); the vocabulary rules (a role is a name of the table's vocabulary and held by one row, a bound row is not deleted); Episodic Memory's names (accepted, from every source); `engine_params.refers_to` (the lists derived from it, the trigger-node parameter found by the column); the manual clamp's background level and its list of clampable pattern names (declared by what they name, a renamed level or an edited menu reaching them as `dangling`) |
| `test_configuration_admin_order.py` | 2 | Stage 4: the order a reset or restore writes its ops in: an enum row's inserts first, its deletes last, the role handed over last; other deletes still children before parents |
| `test_configuration_writer.py` | 7 | C5: `ChangeService`'s envelope check, the `ChangeError` type and its HTTP mapping, and the translation of journal errors |
| `test_bonds.py` | 22 | `Bond`: direction, facet, strength, flipping |
| `test_bridge_types.py` | 2 | The bridge-type and orientation constants |
| `test_vocabulary_payload.py` | 4 | The vocabulary payload the client compares through (`server/services/vocabulary_payload.py`): every binding and every link type's behaviour, a renamed binding, an unbound role absent, and a loaded runner's own provider against the store's current one |
| `test_codelet_dsl.py` | 3 | Compiling a codelet body: what the interpreter accepts and refuses |
| `test_clamp_commentary.py` | 12 | A clamp announces itself and its undoing in Metacat's words; remindings newest first with a whole-number strength; the "stumped" answer |
| `test_commentary.py` | 29 | The `CommentaryLog`, and the emit helpers whose English is written in Python |
| `test_compare_harness.py` | 18 | The oracle comparison's decision logic: what gets flagged, and how, and its engine-parameter passthrough; the shipped reference sets in `measurements/reference/` |
| `test_concept_mappings.py` | 31 | `ConceptMapping`: identity, slippage, distinguishing descriptors |
| `test_descriptions.py` | 23 | `Description`: relevance, strength, descriptor predicates |
| `test_episodic_memory.py` | 12 | `EpisodicMemory`: identifier scoping, `answer_present`; the list kept newest first as Metacat conses it, the oldest-first window listing, remindings newest first |
| `test_formulas.py` | 13 | The temperature-adjusted probability curve, averaging, the sigmoid, bond degree of association and the group-evaluation probability |
| `test_groups.py` | 21 | `Group`: length, spanning, membership, internal and external strength |
| `test_jootsing_outcomes.py` | 7 | The jootser's outcomes: what counts as the same clamp, and when it gives up |
| `test_object_choice.py` | 8 | Weighted object choice: the temperature exponent, and the absence of floors |
| `test_config_hash_guard.py` | 11 | The hash guard (plan 3.8, EN2): `config_hash` covers every `MetadataProvider` field by reflection, the exclusion set is pinned, a field added to the provider is hashed without editing the hasher, each hashed field's digest moves with its value and order, the hash is `combine(field_digests)`, and the scheme and a number's type are part of it |
| `test_en4_relations.py` | 15 | EN4: relations read from `theme_relations` through `slipnet.relation(...)`, the opposite pin, the `diff` abstractness from data, and each relation's row or node removed (a run builds and steps on the demo problems) |
| `test_en7_codelets_control.py` | 11 | EN7: the initial-description order per string shape, the thematic posted list, `rng.call_count` per codelet against the golden sidecar, each converted role unbound or its node removed, and an absent evaluator role posting nothing |
| `test_en9_answers_memory_text.py` | 14 | EN9: answers and comparison read roles and relations; an absent template key gives no text and one warning; `comparison_judgment_priority` absent judges no preference; Episodic Memory carried into a run whose configuration lacks a node, a link label or a codelet type it names completes, and the missing name contributes nothing |
| `test_en5b_alphabet.py` | 14 | EN5b: the alphabet and numbers as data: `slipnet.alphabet` equals the old letter and number lists, a shared glyph or value goes to the first node, a character with no glyph node is unperceived, and the a-d/w-z alphabet and the 1, 2, 4 ladder (cascaded, or with dangling links) build and step on the demo problems |
| `test_en8_rules_language.py` | 14 | EN8: rules, justify and rule English read roles and relations; `rule.dimension_order` and its sort; the abstract-change draws and `rng.get_state()` with a role absent; the justify handlers narrowed (B10); each converted role or relation absent on demo and justify problems |
| `test_en6_perception.py` | 12 | EN6: bonds, groups, bridges, concept mappings and images read roles, relations and the alphabet; the bridge recruitment post sequence is unchanged; identity absent never raises; every dimension, position, direction, object and recruit role unbound or its node removed, and each relation node removed, on the demo and justify problems; and whole runs (discovery, justify, Episodic Memory carried) on a configuration whose role-bound, relation, letter and number nodes are all renamed give the same answers, codelet counts, RNG draws and English |
| `test_en10b_scalars.py` | 9 | EN10: the rules, justify and perception scalars read from the configuration with today's values and types (the two rule abstraction probabilities, the justify identity retention, the bridge-recruit urgency level, description local support, concept-mapping and bridge coefficients); a configuration lacking one stops the run at its start naming it |
| `test_en11a_engine_closeout.py` | 5 | EN11: the rule-signature token comes from the `object.group` role (exactly the old token under the Metacat Standard Configuration, following a rename, defined when the role is absent); the remaining scalars (`sigmoid_divisor`, the theme flip probabilities, the reminding threshold, the rough-count thresholds) are read from the configuration and a configuration lacking one stops at the run's start |
| `test_order_fidelity.py` | 10 | The list orders `cons` and vectors fix: Chez Scheme's `sort` (80 cases from the Metacat image), a string's groups, the rule's subobject bridges, the coderack bin and deferred batch, the jootser's event set, and the display-time prints (DISCREPANCIES5 C-1, G-Z4, G-Z5, I-3…I-5) |
| `test_exact_rounding.py` | 9 | Exact rounding where Metacat is exact: `round_ratio` and `round_exact` against `fractions.Fraction` over every whole input, the degree of support for every pair of strengths, concept-mapping strength and slippability for every association and depth, rule quality for every uniformity, abstractness and reachable succinctness, the Slipnet's spread at any update cycle length and its decay at a whole-number exponent |
| `test_rule_order_fidelity.py` | 4 | The orders Chez Scheme decides in rule application: `check-for-conflicts` visits pairs in `pairwise-map`'s order, `apply-transforms` sorts with Chez's merge sort and `apply-before?`, and `build-bond` overwrites a held slot's pointers |
| `test_fidelity_fixes.py` | 6 | Stage F's fixes: a rule's degree of support is an exact product, a Themespace adds no theme while Self-watching is off, the context keeps the two in step, and `permission_to_clamp` has no default for the flag |
| `test_rng.py` | 17 | The deterministic RNG wrapper |
| `test_rule_bond_facet_change.py` | 1 | A GroupCtgy self change's BondFacet change is found wherever it sits (KNOWN-FAILURES, G-Q1) |
| `test_rule_types.py` | 9 | `Rule` and `RuleClause` predicates and translation |
| `test_rules_lockstep_ordering.py` | 12 | Rule construction in Metacat's order: subobject gate, common change schemas, `sort-templates`, swaps, list order (DISCREPANCIES5 C-1…C-4, D-1…D-5) |
| `test_run_service_ids.py` | 2 | A clamp or Undo on a live run takes its trace-event number from the run's own id allocator |
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
| `test_themespace.py` | 24 | Themespace self-watching dynamics: cluster spreading, dominance |
| `test_trace_event.py` | 3 | `TemporalTrace` event recording |
| `test_trace_display.py` | 16 | A Trace event's print name and display header against `trace.ss`: every event type, the three group directions, the bridge prefixes, flipped groups, the answer headers; a picture that cannot be taken never stops the trace |
| `test_validate_overrides.py` | 3 | `validate_overrides` needs the configuration a run executes under (`meta` is required), and checks a reference parameter's shape against that configuration's `engine_params.refers_to`: the same override is accepted under one and refused under another |
| `test_verbose.py` | 16 | Scheme's display of values, the bounded narration log (capture and replay, dropped lines), the message-catalogue overlay, and that the narration builtins exist in a codelet's namespace only when Verbose mode is on |
| `test_workspace_object.py` | 35 | `WorkspaceObject` and `Letter`: geometry, importance, unhappiness |
| `test_workspace_string.py` | 25 | `WorkspaceString`: bond and group management, spanning, relevance |
| `test_workspace_structure.py` | 10 | The base structure class and its proposal levels |
| `test_vocabulary_reduced.py` | 3 | Stage 4: every vocabulary role that is not required, unbound in turn, still runs every demo problem; unbinding a required role gives `RunStartError` at the start |
| `test_vocabulary_rename.py` | 7 | Stage 4 (the vocabulary comes from the database): every bound row of the enum tables, each link type and each theme relation renamed to an opaque name (`v_17`) changes nothing a run does: six cases, a justification run, a three-run episode, Self-watching off and three intervention schedules match the Standard Configuration in status, answer, codelet count, RNG draws, codelet types and English, with the trace's names mapped back; renaming urgency tiers (probes M11, M24) changes nothing either; with two runs alive in one thread, each run's structures answer in that run's own names |

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
| `test_every_moved_value_reaches_its_site_n.py` | 4 | Round 2, stage N: the ten values the numeric literal guard found and moved (the nine commentary bands in `engine_params`, and `local_support_number_denominator_floor`) reach their sites: today's value is the old literal in its old form, a missing key stops the run at its start, and the site called with the key changed gives another result |
| `test_every_moved_value_reaches_its_site_b.py` | 11 | Round 2, stage 5 (group B): every value moved into the database from the run, the codelet bodies' builtins, self-watching, memory, justify and the random stream reaches a run: one key changed, a run that reaches its site differs (40 rows, a chain of runs for the answer distance, direct tests for the five sites no run reaches in reasonable time and for the two generators' `~`), today's value is the old literal in its old form, and each key is on the declared read list |
| `test_every_moved_policy_reaches_its_site.py` | 7 | Stage 6: for every member of every policy role that moved into `roles.json` (the ten sets of dimensions, `descriptor.generic`, the six `image_operation.*` roles), dropping the binding changes a run (or, for the four sites no demo problem reaches, the site called directly); the dispatch follows a rebinding, not a node name |
| `test_fallback_instrumentation.py` | 4 | The silent-fallback observer (EN0, `tests/support/fallback_instrumentation.py`) sees the three blanket `except Exception` blocks of `justify.py` and a lookup of an absent Slipnet node, and changes nothing else; `scripts/count_silent_fallbacks.py` makes the count over the whole baseline set |
| `test_frame.py` | 13 | Stage 6: the four-string frame derived from `string_kinds`, `bridge_types` and `rule_types` (`server/engine/frame.py`) gives Metacat's table (what each kind maps, `get-other-string` for every kind and key, the theme types of each kind and mode, the rules' pairs, the numeric layout codes); a topology row changed in the configuration changes a run; an incomplete row leaves the thing out; the rows are hashed |
| `test_formulas.py` | 10 | The temperature-dependent formulas against the seeded coefficients |
| `test_hardware.py` | 20 | The machine description and the sizes derived from it: real probes, faked probes, environment overrides |
| `test_float32_guard.py` | 6 | The GPU exactness guard: the measured-exact configurations are not refused, the measured-inexact ones are refused naming the value, `auto` falls back to a float64 backend, an explicit `mlx` raises |
| `test_initial_program.py` | 11 | Stage 6: the initial-description program (`initial_description_rules`, `initial_activation_rules`): the Standard Configuration's rows give every letter the descriptions the code gave it, in the same order, with the same concepts active, and eight whole runs (justify and translated strings included) equal the old group and translated-letter code run for run; the group and translated-letter rows (subjects) are read in order, and a condition or source of another subject stops the run at its start; rules are applied in `ordinal` order, a rule whose role nothing holds is dropped, a condition outside the engine's closed set stops the run at its start; removing a row, reordering two, and switching off an activation each change a run |
| `test_frozen_jump.py` | 1 | A frozen node in the jump window does not jump on any backend, and its coin is still drawn |
| `test_justify_conceptual_depth.py` | 5 | Justify's retention of a pattern entry naming no node: `Absent`'s depth, probability 0, entry dropped |
| `test_metacat_display_seed.py` | 5 | Seed data that exists so a display can match Metacat: every Metacat demo, the Themespace's dimension and relation names |
| `test_metadata_provider.py` | 25 | `MetadataProvider` loading every seed collection |
| `test_mlx_kernel_fallback.py` | 2 | An unreachable Metal compiler service (`MTLCompilerService`) at the fused kernel's first use is caught: the update is redone with the composed operations (equal to the `mlx-cpu` result), the kernel is switched off for the process, and the log says so once. Any other kernel error still surfaces. Skipped where the MLX GPU backend is not available |
| `test_numeric_backends.py` | 31 | The numeric backends against the reference (decay and spreading against exact rationals, including spreading's halfway cases), and the engine without them; and that changing the four salience weights or `probabilistic_activation_exponent` changes the result on every backend, and the jump probability is defined at a zero share and at overflow identically on every backend (stage W), and that a reader arriving while the class registry is being built sees it complete |
| `test_reduced_configurations.py` | 14 | The reduced-configuration fixture generator (EN0, `tests/support/reduced_configurations.py` and `configuration_cascade.py`): nothing left that names a removed node or codelet type, the cascade removes what the plan's rules say, a provider loads from each; the engine is not run on them yet |
| `test_standard_configuration_roles.py` | 14 | EN2: the Metacat Standard Configuration binds every role of `tests/support/role_table.py` to the node or codelet type today's code names (the two ordered roles in today's order), carries the five theme relations, `plain_name`, `glyph`, `numeric_value` and the display columns that reproduce the tables they replace, unique `rule_key`s and unique link keys, and the provider loads them |
| `test_display_names.py` | 4 | EN5a: display text comes from the node columns: renamed nodes keep their printed text byte for byte, all-NULL columns fall back, and unbound roles or removed nodes still print |
| `test_declared_names_stop_the_run.py` | 10 | EN10: every name on the declared read list (`server/engine/start_check.py`), removed from the Metacat Standard Configuration, is named by the run-start check, and the run stops before its first codelet on the Metacat Mode, Swarm, Training Mode and population paths |
| `test_g9_any_configuration.py` | 8 | Gate G9 complete: every node removed with its cascade, random node subsets, the a-d/w-z alphabet, a gapped ladder and no alphabet successor, on discovery and justify demos, with Episodic Memory carried in from a full-configuration run and a small Swarm; only the run-start error may stop a run, and a symbol with no node is never perceived (an exhaustive sweep runs under the `slow` marker) |
| `test_codelet_body_lookups.py` | 16 | The Metacat Standard Configuration's codelet bodies and descriptor predicates name no node and build no node name (an AST lint, so comments quoting Scheme are allowed); the body builtins `role`, `relation` and `letter_node`, `descriptor_support` by node identity, and the predicate helper `letter_glyph`, each with its absent case |
| `test_role_identity.py` | 13 | Role identity (gate G5): the role-to-literal table against the Metacat Standard Configuration, the engine's ordered constants and `role_identity_today.json`; and, since EN3, every role resolved through `slipnet.roles` is the node (or codelet type) the old literal finds, the ordered roles equal the old tuples, and the ladder and alphabet (the nodes with a `numeric_value` or a `glyph`) equal the old lists |
| `test_roles.py` | 20 | The role mechanism (EN3): the vocabulary against the role table and `roles.json`; the `Absent` token (falsy, frozen, one per role, identical only to itself, node-shaped); `Roles` never holds `None`; resolution skips unknown role names and missing targets; the run-start check (I-1, I-2) and its declared read list; and the G9 skeleton, building the Slipnet and resolving roles on every reduced configuration |
| `test_rule_english.py` | 10 | A rule's English against Metacat 1.2's own `transcribe-to-english` output: 463 recorded rule shapes, each string state, wrapping, articles, and the text kept from the moment the rule was made |
| `test_snag_explanation.py` | 20 | A snag's explanation against Metacat 1.2's `get-explanation` (`trace.ss:1097-1125`): every branch of the failure-result, the object phrases, the commentary lines, the template-driven wording, and the old sentence built when a failure has no Metacat sentence |
| `test_rule_quality.py` | 13 | Rule uniformity, abstractness and succinctness against the Scheme's formulas, hand-computed from the seeded depths |
| `test_every_moved_value_reaches_its_site_a.py` | 8 | Stage 5, group A: each of the 76 formula coefficients that replaced a literal in the structure, formula, perception, rule, Themespace, trace and numeric files carries the old literal in its old type, is on the declared read list, and is read by its site: a real run (`moved_values_runs_a.json`) differs when the key changes, or the site is called directly where no run reaches it (a guard for an input a run never builds); the numeric backends read `clamped_salience`, the thematic pull targets and `average_unhappiness_empty` from the configuration |
| `test_slipnet_link_lengths.py` | 6 | The Slipnet's link lengths against the reference Scheme |
| `test_slipnet_node.py` | 20 | The 59-node Slipnet: its nodes, its links, its clamps and its spreading |
| `test_temperature.py` | 2 | Temperature updating against the seeded coefficients |

**`tests/module/` — real components assembled and driven**

| File | Fns | Covers |
|------|----:|--------|
| `test_access_sets.py` | 19 | Read-set / write-set discipline and commit-time validation |
| `test_lockstep_desync_fixes.py` | 5 | Fixes found by replaying runs beyond the lockstep corpus, as small hand-built states: `get-equivalent-bridge`, rule clauses `self` vs `subobjects`, any-descriptor reference objects, both-order internal coherence, `remove-duplicates` keeping the last entry (G-Y1…G-Y3, G-Y5, G-Y8) |
| `test_answer_description_pattern.py` | 13 | The vertical theme-pattern an answer description is indexed by |
| `test_wired_numbers.py` | 11 | Stage W: each number the engine used to repeat as a literal or ignore (`probabilistic_activation_exponent`, the four `*_string_salience_*_weight` coefficients, `max_raw_importance`, `max_activation`, `max_theme_activation`, `concept_activation_importance_threshold`, `jootsing_count_scale`) is changed in a configuration built in the test and a real run moves, on every backend in the matrix; and each site is pinned alone (clamp default, label flush, length-description exponent, theme-conjunction admission, theme patterns, derived concept patterns, snag branch of the jootser) |
| `test_bridge_scouting.py` | 25 | The bridge scouts' probabilistic gates, the build-time mapping augmentation, the incompatibility refinements, and the deferred posting batch |
| `test_capture_projection.py` | 9 | A recorded capture renders exactly as the same state renders live, including the unbuilt translated rule justify mode adds |
| `test_coderack_eeg_display.py` | 8 | The coderack window's figures and the EEG's samples from a real run, serial and free-running |
| `test_codelet_behaviours.py` | 79 | What each of the 27 codelet types does to a live workspace |
| `test_codelet_dsl.py` | 7 | Codelet bodies executed against a live engine context |
| `test_commentary_writer.py` | 8 | Commentary is an injected writer, and every Run gets a real one |
| `test_dissertation_parity.py` | 45 | The dissertation's claims, encoded as tests |
| `test_free_running.py` | 23 | Free-running execution across worker threads, and the loop matching the serial one (codelet count, structure clock, initial unclamp, per-codelet answer hand-off) |
| `test_group_image_direction.py` | 6 | A group's image is built in the group's own direction |
| `test_image_relations.py` | 4 | The relations a group's image is built with, and what happens when they are wrong |
| `test_justify_and_jootsing.py` | 14 | Justify mode's verdicts and the jootser's justify outcomes |
| `test_lockstep_structure.py` | 7 | Structure-building fidelity: bridge-proposal scout scope, bond-builder break order, answer string outside justify mode, concept-activation sampling (DISCREPANCIES5 C-5, D-6…D-10) |
| `test_numeric_engine.py` | 7 | The engine computes the same thing with the substrate engaged |
| `test_no_seed_reads_at_run_time.py` | 8 | EN1: the engine takes its configuration from the run's `MetadataProvider` and never reads the Metacat Standard Configuration files at run time. A `sys.addaudithook` fixture (local to the module) fails any `open` under `seed_data/` during a Verbose-mode run, a swarm call, an episode with Episodic Memory carried and the comparison and explanation of its answers; and the former fallbacks (rule English parameters, the Verbose catalogue, commentary templates, conceptual depths, reminding and distance) raise when no provider is given |
| `test_run_binding.py` | 16 | A run is bound to its own configuration, constants, Themespace and clock (round 2, stage 2): every run is identical to the same run alone (codelets, answers, status, every draw, every Trace event, the final state graph) when a second run with the same or another configuration is created before it finishes, when two runs are stepped alternately or one inside the other's step, beside a restored review inspector, on parallel threads running different problems, and under two speculative engines in one process; with no run bound, `current`, `constants`, `next_id` and a structure's construction raise `NoRunBound`; nothing run-wide is left on `WorkspaceStructure`; a run holds the `RunConstants` of its own provider, resolved once, and a changed configuration reaches the next run and not the running one |
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
| `test_state_graph.py` | 12 | A captured run restores to a state that continues identically; memory captured oldest first and restored newest first, with the slippage logs of its events |
| `test_swaps_and_translation.py` | 14 | Extrinsic (swap) rules end to end, the conflict battery, the per-dimension slippage ignore, and the ways a translation fails |
| `test_thematic_bridge_scout.py` | 9 | The thematic-bridge-scout inside an assembled engine |
| `test_themespace.py` | 14 | Themespace driven by a real run's bridges |
| `test_trace_persistence.py` | 8 | Trace event persistence logic; the Trace records only the seven cognitive event types, and one discovery run records every event type row there is |
| `test_trace_pictures.py` | 8 | What a real run keeps for redisplay: print names and pictures on every event, the Workspace as it was, answer and snag description pictures, and that taking a picture changes nothing the run does |
| `test_verbose_mode.py` | 11 | Verbose mode on a real run: every codelet's banner, a run identical with the mode on or off, the mode switched mid-run, step mode, the bounded buffer, and the message catalogue agreeing with the call sites |
| `test_workspace.py` | 19 | Workspace aggregation across its four strings |

**`tests/architecture/` — properties of the source tree**

| File | Fns | Covers |
|------|----:|--------|
| `test_engine_purity.py` | 18 | Nothing under `server/engine/**` imports `sqlalchemy`, `server.models`, `server.db` or `server.services`, and the serializers run in an interpreter where those cannot be imported |
| `test_declared_read_list.py` | 9 | EN10: every literal name passed to `get_param`, `get_formula_coeff` or `get_urgency` in `server/` is on the declared read list, and every declared name exists in the Metacat Standard Configuration; and the converse (stage W): every name stored in `engine_params`, `formula_coefficients` and `urgency_levels` is read, by an accessor, a codelet body, or (for a tier) a posting rule, a codelet pattern, a level-naming parameter or the clamp background, with no list of exceptions |
| `test_journal_only_writer.py` | 10 | C6: only the journal layer writes a configuration or journal table (an AST check over the table list from model introspection), the checker on planted snippets, the two doors `write_immediate` and `write_deferred`, and nothing in `engine/` or `parallel/` imports the journal |
| `test_no_node_literals_in_engine.py` | 5 | The EN0 lint: no line of `server/engine/**` names a node or codelet type of the Metacat Standard Configuration (`plato-` literals and compositions, `name[6:]`, node names, codelet types), and none reads the seed files outside the one door (`MetadataProvider.from_standard_configuration`); a read anywhere else, even in `metadata.py`, is caught. The allow-list `no_node_literals_allowlist.txt` is empty and may only shrink: an entry that no longer matches fails, and a new violation cannot be added to it |
| `test_numeric_literals.py` | 3 | Round 2, stage N (ruling 53): no `int` or `float` literal in `server/engine/` or `server/parallel/` outside an allow-list (keyed by file, enclosing function and literal, with a count, a class `UNIT` or `NONCOG-KEEP`, and a reason); the only exempt shapes are a constant index and a constant slice bound; the table is strict in both directions and every reason is defined and used |
| `test_no_policy_in_engine.py` | 3 | Stage 6: the engine does not decide by concept where the configuration can say: no set of dimensions spelled as an `or` of role questions, no table keyed by two or more bridge types, string kinds, theme types or rule types, no comparison against one bridge type or string kind (outside the formats that write them), no initial description built outside `initial_program.py` (a group's only other is the probabilistic Length description) |
| `test_parallel_detachable.py` | 5 | Nothing under `server/engine/**` imports the parallel plugin, and a serial run and the service layer work in an interpreter where `server.parallel` cannot be imported; a Training Mode Session run there chooses the serial executor and produces the plugin's runs, run for run. The session test uses a database of its own, `petacat_detached`, created on demand (drop it with `dropdb --if-exists petacat_detached`; `DETACHED_DATABASE_NAME` renames it for a second session); it cannot be pointed at `petacat_test` or at `TEST_DATABASE_URL`'s database, and a guard test holds that |
| `test_v2_guards.py` | 8 | C10: the engine tree is the baseline commit's, touched after EN11 only by the allowed packages; the retired term for the Starting Conceptual State is used nowhere, and the word for a session's Episodic Memory class means nothing else (with the checker seen catching planted words); no table named for the old session entity and no `session_id` column on `runs`; the worker-side code never imports the journal layer |
| `test_vocabulary_literals.py` | 4 | Stage 4: no string literal in `server/engine/`, `server/parallel/`, `server/services/` or `server/api/` equals a name the vocabulary binds (outside an allow-list, each entry with its reason: the engine's own formats and, in the services and the API, the keys of the problem JSON and of the payloads the client reads); the Standard Configuration's codelet bodies, descriptor predicates and posting formulas write `role('...')`; every role is bound once to the row Metacat names |

**`tests/integration/` — the repository's artifacts agree**

| File | Fns | Covers |
|------|----:|--------|
| `test_documented_code_shape.py` | 4 | The engine's size, the endpoint count, the builtins module and the Run Controls groups, as the documentation states them |
| `test_documented_counts.py` | 3 | Every documented layer count, suite total and per-file figure, against the collection that produced it |
| `test_no_ambient_run.py` | 3 | Only `unit`, `seed_unit` and `module` get an ambient run bound around their tests; `architecture`, `integration`, `parallel`, `lockstep` and `e2e` run with none, so a real path that forgot to open its run's scope raises `NoRunBound` there as in production |
| `test_configuration_input.py` | 31 | The four input-check classes of the configuration input library (C0, `server/services/configuration_input.py`) as pure functions, with no database, engine or routes: unknown reference, key exists, malformed, does-not-compile, stale base version, and applying operations to a copy |
| `test_configuration_source.py` | 15 | C2, start-up tests 1-6 of the plan's 3.6, through `server/services/configuration_startup.py` (what `lifespan` calls): the database is the source and not the files; an empty database first-loads with a `configuration_state` row; a loaded database is never re-seeded (edits and deletions survive a restart) even when a seed file changes; the start-up reference equals the seed files whatever the database holds; refusals (unreachable database, rows without a state row, a state that is not `ready`, a state row over empty tables, an older schema, an unparseable parameter, an unreadable seed file); two simultaneous start-ups load once; start-up never writes the seed files. Uses its own scratch database `petacat_c2` (`C2_DATABASE_URL` overrides) |
| `test_db_seed_equivalence.py` | 17 | C0 gate G4: a database loaded from the Metacat Standard Configuration with no edits yields a provider equal, field by field (order and JSON number typing included), to `MetadataProvider.from_standard_configuration`. `RECORDED_STORAGE_LIMITS` lists what the database cannot carry and may only shrink; EN2 removed the last three (ordinals on the name-keyed tables, `value_type` on formula coefficients, `json` rather than `jsonb`), so it is empty and the providers and `config_hash` must be equal in full. A new table must be added to `_expected_tables`. Uses its own scratch database `petacat_c0` (`C0_HARNESS_DATABASE_URL` overrides), built by `equivalence_harness.py` |
| `test_config_document_db.py` | 4 | S0: the `ConfigDocument` from the database equals the one from the Metacat Standard Configuration files (tables, rows, order), its provider equals the database provider, its hash the engine's, and rows carry no surrogate id |
| `test_config_document_runs.py` | 2 | S0: an unedited document runs exactly as the files' provider, and an evolved one (a coefficient edit by `apply_resolved`) exactly as the hand-evolved provider |
| `test_journal_layer.py` | 20 | C6: the journal layer on its own scratch database (`C6_DATABASE_URL`): the first load as the `standard_load` entry, cascades, atomicity, the global configuration refusing Training Mode sources (M2), re-keying, replay equal to before-image reconstruction at every revision, `verify_journal`, restore, undo, provenance, both doors, append-only |
| `test_configuration_writer.py` | 26 | C5: `ChangeService.apply` on a scratch database (`C5_DATABASE_URL`): the write and its journal entry (proposed and resolved ops, provenance), compare-and-set under `strict`, `rebase` and `head`, `dry_run` writes nothing, M2 (a learner-shaped call refused on the global configuration), the G6 classes, the changes that must not be refused, a convenience op journaled as proposed and resolved |
| `test_change_resolve_journal.py` | 2 | C14a: the resolved ops of ten batches written through the journal layer read back equal to `apply_resolved`, and `verify_journal` is clean (`C14A_DATABASE_URL`) |
| `test_configuration_admin.py` | 9 | C4: start-up test 7: reset gives equality with the Metacat Standard Configuration and is a journal entry undo can reverse; runtime tables untouched; `diff` lists exactly the changed rows; restore-selected restores only those; and the `python -m server.config` command line, run as a subprocess |
| `test_session_configurations.py` | 23 | C8: session configurations as entities: creation from `standard`, `global` and another session; creation overrides journaled with `source = creation` and provenance "from the Starting Conceptual State"; edits through `ChangeService` read back through the store at each revision and episode version; status, diff, reset, restore and verify on a session; M1 and M2; the meta edit; list, rows and export; the live source; the delete cascade and journal immutability |
| `test_history_views.py` | 12 | C13: views of the journal: filters and order (table and key, including a re-key; time; across configurations), one entry in full, as-of by time; restore and undo of a batch and of a group as new entries equal to their target, with `verify_journal`; as-of, restore and undo on a session configuration; a name's story after delete, rename and merge; `check_names`; pending entries of a live source merged and labelled |
| `test_db_seed_parallel_equivalence.py` | 2 | C0 gate G4: a swarm (real process pool) and a speculative run with `workers >= 2` equal the seed-file provider's runs on the database-loaded provider; slow, CPU float64 pinned by the tests themselves |
| `test_db_seed_run_equivalence.py` | 2 | C0 gate G4: Metacat Mode runs per (problem, seed) on the database-loaded provider are identical to the seed-file provider's (answers, codelet count, draw count, final temperature, step/structure/trace hashes, final state); in the numeric matrix, with bit-identity down to the draw asserted on the float64 CPU half |
| `test_enum_constants.py` | 12 | Engine string constants match `seed_data/enums.json` |
| `test_tie_order.py` | 4 | Rows that tie on `sort_order` or `ordinal` come out in the same order from the database and from a `ConfigDocument` (total order: order columns, then the rest of the natural key; byte-order collation) |
| `test_help_topics.py` | 13 | The help JSON, the generated TypeScript and the panels that reference them |
| `test_metadata_seeding.py` | 13 | Every seed file is well-formed, and the `MetadataProvider` round-trip holds |
| `test_numeric_matrix_harness.py` | 11 | The matrix's own reporting rules and the exit status of a narrowed run |
| `test_role_and_key_schema.py` | 9 | EN2, on the scratch database inside a rolled-back transaction: deleting a node or codelet type deletes its role bindings and theme relation (`ON DELETE CASCADE`), a rename follows, one node per role ordinal, the widened link key (two labels between the same nodes, no repeat, no second unlabeled link), unique glyph and numeric value, a row added without an ordinal goes last, and an Admin-style create of a posting rule, link, demo and theme dimension succeeds without an explicit id (the first load sets each id sequence past the ids it wrote) |
| `test_seed_reconciliation.py` | 6 | The seeder writes every configuration table, the configuration tables exclude the runtime tables (the four Training Mode Session tables among them), and no fingerprint or re-seed path remains |

**`tests/lockstep/` — Petacat's decision traces (the Petacat/Metacat lockstep harness)**

| File | Fns | Covers |
|------|----:|--------|
| `test_commentary.py` | 1 | Every comment-window paragraph (both voices) of 28 Metacat runs -- snags, all four clamps and their undoing, "I'm getting frustrated", answers, "Okay, I'm stumped" -- replayed in Petacat and compared as Metacat 1.2 logged them |
| `test_comparer.py` | 32 | The trace comparer (with Metacat's crash on a group of six or more objects registered by its shape, and the smallest such crash replayed from a recorded trace): hand-made trace pairs with known faults give the expected classes; the registry's reference-crash class; proposed structures counted apart from state snapshots, and the ratchet on both |
| `test_desync_fixes.py` | 1 | Prefixes of three Metacat runs beyond the corpus that used to desynchronise the replay (`traces-desync/`) replay to their end with no error and no differing state (DISCREPANCIES5 G-Y2…G-Y4) |
| `test_episodes.py` | 8 | Episodes and justify mode: recorder driver text, corpus globs, an episode's self-replay with memory carried, a forced fatal, justify self-replay |
| `test_golden_baseline.py` | 5 | The EN0 golden baseline gate (G3): `tests/lockstep/golden/engine_baseline.jsonl` and `engine_baseline_rng.json.gz`, captured from the Metacat Standard Configuration on the CPU numeric backend (float64), hold for the 19 demo problems and the justify problems at seeds 1-5 and one 8-run episode the answer, codelet count, final temperature, per-codelet RNG call counts, trace and final-state hashes and the English corpus. A quick consistency check and a four-run sample run always; the slow test recomputes everything in a fresh interpreter and compares byte for byte, naming the first differing run and codelet. Outside the numeric matrix (it pins its backend) |
| `test_extended_tools.py` | 7 | The tools behind the extended golden baseline, without Docker: the recorder's driver text for a person's clamps, Undo, Self-watching mode and Clear Memory, the interventions calling the product's own `RunService` methods, bare, a description or rule proposal's own time stamp told apart on replay, a cleared-memory header honoured by the answer check, and `scripts/golden_coverage.py` attributing the database's code (codelet bodies, descriptor predicates, posting formulas) to its units |
| `test_golden_extended.py` | 6 | The extended golden baseline gate: `tests/lockstep/golden/extended_baseline.jsonl` and `extended_baseline_rng.json.gz`, 73 cases chosen by coverage (four added by stage 6 for the alphabetic-position sites), each checked against Metacat, under the faithful parameters on the engine's own loops (backend off) or the pure-Python backend. A consistency check against the case list, a baseline-of-real-runs check and a sample always run; the slow test recomputes everything in a fresh interpreter over a process pool (about 10 s) and compares byte for byte, naming the first differing run, field and codelet; a changed update-cycle length is noticed. Four slow tests run every case on `numpy`, `python`, `mlx-cpu` and `mlx` and compare each record field and the final state with numbers normalised (a backend that is not available is a skip). Outside the numeric matrix |
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
| `test_admin_reload.py` | 8 | An Admin write is in force for the next run, the Swarm and the parameter listings with no restart; a run under way keeps its configuration; a rebuild that fails keeps the previous one |
| `test_admin_journal.py` | 5 | C6: every Admin configuration write is a journal entry; a no-op or refused request writes nothing; a node delete cascades and undo restores it; an import is one entry |
| `test_configuration_store.py` | 5 | C3: the `ConfigurationStore`: the Training Mode scheduler sees an Admin edit with no run between (B4); a run created before an edit keeps its `config_hash` and the next gets the new one; an edit reaches the next Swarm and Fast run; the hook runs only after a committed global change; a failed refresh answers 500 and keeps the previous provider |
| `test_configurations_api.py` | 7 | C4: `/api/configurations/{id}/status`, `diff`, `reset-to-standard` (typed confirmation), `restore-selected`, `verify-journal`, their refusals, and the seed-export endpoint gone |
| `test_configuration_entities_api.py` | 5 | C8: `GET /api/configurations`, `GET` and `PATCH /{id}`, rows and export, and status, diff, reset and verify on a session configuration |
| `test_change_api_endpoints.py` | 19 | C14b: `POST /api/configurations/{id}/changes` (the report and journal entry, `dry_run`, `strict`, `rebase` and `head`, `expect`, `skip`, the G6 classes with status and op index, a bad envelope, the Metacat Mode refusal of Training Mode sources, an unknown configuration), `GET /{id}/schema`, the Admin editors' journal entries, `?configuration=`, and a Stopped session's configuration |
| `test_enum_vocabulary.py` | 12 | Stage 4: the Admin enum editor over the engine's vocabulary: the roles per table and the table's own columns, an unbound row freely added and deleted, a role checked (`unknown_reference`, `role_taken`), a bound row refused (`422 role_bound`), the columns that name another table checked, a rename rewriting every referencing column (and reset-to-standard putting it back), the journal's story of a renamed theme type, the journal undoing a rename, and a session's configuration renamed through the change API |
| `test_database_tab.py` | 24 | C7: the Database tab: table classes, paging and filters, a configuration edit as a journal entry, refusals per class (journal, session-managed, session Episodic Memory and its run columns, deleting a session row), `help_topics` writes, runtime expert mode and active rows, and the read-only SQL box |
| `test_configuration_compare_api.py` | 6 | C9a: compare any two configurations or one with the Metacat Standard Configuration (diff by table and natural key), and apply-from (a dry-run preview, then add, remove and update rows through the change API as a `restore`), with their refusals |
| `test_journal_api.py` | 6 | C13: `/api/journal` (list, filters, one entry, errors), as-of by revision and time, where-did-name-go and check-names, the restore and undo round trip, bad restore requests, and a session configuration's history with a live source |
| `test_session_configuration.py` | 21 | S3: a Training Mode Session runs its own configuration: creation from each base with parameters folded, the WP-S3 equivalence, one worker equal to the serial episode with a learner, a live batch reaching the next dispatched run and not one in flight, a Stopped session's edit written at once, Starting and Stopping busy, M1, and the hand-off of held entries to the Stop write; creation overrides checked against the configuration the session starts from (a reference parameter accepted for one base and refused for another) |
| `test_session_stop_start.py` | 8 | S5: Stop then Start round-trips a session exactly with zero journal or merge statements at Start; many Stop/Start cycles; a failed Stop writes nothing and a retry writes everything; a tampered stored state refuses the Start while a Stopped edit does not; graceful shutdown stores every live configuration; a never-stopped session writes nothing while live |
| `test_configuration_edits_api.py` | 8 | C12: edit-all over HTTP: the matrix of global, running, paused, Stopped, frozen and differing targets with M3 and undo by group; a missing row and a removed node with apply-the-rest; no_change, overwrite and a frozen target chosen by id; a session changing state; a stale preview re-previewed; all-or-nothing across stored and live targets |
| `test_session_routes.py` | 13 | S6: the session routes that carry its configuration: the external route (a Stopped session writes at once, a live one holds the batch, 409 while starting or stopping, every learning source recorded, refusals in the change API's shape, dry runs); the journal timeline with live pending entries; the configuration, diff and Slipnet at a version, stored and live; export of the configuration and the journal |
| `test_session_docs.py` | 4 | S6: `API.md` and the contract list every session route; the help topics for the external route and the learning sources are served; learn, learner and episode are qualified by mode |
| `test_session_long_journal.py` | 2 | S8: a session with a long journal (30,000 entries by default; `PETACAT_LONG_JOURNAL_ENTRIES` sets the length) starts with no journal or merge statement, the same statements as a one-entry journal, and the stored hash; `verify_journal` still agrees over it; the journal-growth budget per entry (only with `PETACAT_BUDGETS=1`) |
| `test_mode_isolation.py` | 7 | C10: M1, a Metacat Mode run is identical after a battery of session activity and session edits never change the global provider or hash; M2, the global configuration refuses `learner` and `external`; M3, edit-all end to end, one Admin entry per configuration, and a session-only edit-all leaves the global configuration alone; no journal row from a Metacat Mode run, nor from a live session before its Stop write |
| `test_configuration_edit_scope_ui_flow.py` | 1 | C9b: the Admin scope picker's request shapes: preview by natural key with `expect`, commit to the global configuration and a Stopped session with a reason, then undo by group |
| `test_configuration_stamp_link.py` | 2 | The configuration stamp (plan 3.8): every answer description, snag description and state capture a Normal or Audit run stores carries its run's id, and so the run's `config_hash`; the Training Mode tables carry theirs by construction |
| `test_api_controls.py` | 28 | Breakpoints, clamping, Clamp theme pattern, Undo last clamp, the mid-run self-watching toggle, and the threshold endpoints |
| `test_api_displays.py` | 5 | The coderack, EEG and Themespace-name data the Metacat windows need |
| `test_api_docs.py` | 11 | The documentation endpoints |
| `test_api_extended.py` | 59 | Extended runs, memory, docs and admin endpoints |
| `test_api_review.py` | 26 | The review surfaces read back what the persistence modes wrote, and the episodic-run timeline places each Episodic Memory clear exactly between the runs, page by page, with its note |
| `test_api_runs.py` | 26 | The runs API with persistence |
| `test_api_system.py` | 8 | The system endpoints: what is executing, not what was recorded |
| `test_help_api.py` | 7 | The help topics API |
| `test_help_regenerate_route.py` | 1 | `POST /api/admin/help/regenerate` syncs the help topic rows and commits them (`regenerate_all` patched) |
| `test_persistence.py` | 4 | Snapshot save/restore and the DB metadata round-trip |
| `test_persistence_modes.py` | 33 | The three persistence modes: Fast, Normal, Audit; a parallel Run is the same at any worker count |
| `test_run_parameters.py` | 13 | Run parameters are settable per Run, stored, and readable back |
| `test_run_to_answer.py` | 8 | The Run-to-Answer feature over HTTP |
| `test_review_replay.py` | 18 | Review replays what the Run did (round 2, stage R): the Audit inspector's views equal the live Run's at every codelet, over HTTP, for each kind of action a person takes on a live Run (clamps of temperature, node, theme and codelet, Undo, Self-watching, the threshold, displaying a past event or answer, a reset, a pause with Run), several in one Run, each kind of configuration edit after the Run (coefficient, node, links, codelet body, posting rules, theme dimension, reset to standard, an Admin import that edited and restored a row), runs under different configurations and a server restart; an unrebuildable configuration is refused with 422, a replay that disagrees with the log says so, captures are projected under the Run's configuration, and only Audit records a person's actions |
| `test_two_runs_over_http.py` | 5 | Two live runs held by one server (round 2, stage 2): run A, driven as the client does (step batches, view polls between them), is codelet-for-codelet and view-for-view the run it is alone when run B is created before A is stepped, with the same configuration (normal and fast) or one edited in between through the Admin API, and when the two are stepped alternately; an open Audit inspector, stepped between A's batches, changes nothing; and no run is bound around an e2e test (the unit/module fixture's ambient run must not hide a server path that forgot its scope) |
| `test_s5b_values_from_the_database.py` | 8 | Round 2, stage 5 (group B): the spreading-threshold clip is `max_activation`, a run made with no threshold takes the configuration's, a theme clamp that states no activation takes `max_theme_activation`, the run-parameter catalogue serves both ceilings, the Swarm and a Training Mode Session take `default_max_codelets` (and the Swarm's status serves it), and a slipnet link or posting rule that leaves out `fixed_length`, `posting_formula`, `count_formula` or `condition` is refused (422) |
| `test_memory_order.py` | 2 | A restart puts stored answers back newest first by the memory's own identifier, both projections list them oldest first, and forgetting one keeps the rest in order |
| `test_snag_identity.py` | 5 | A snag is the same snag whichever endpoint served it, and is written once |
| `test_display_does_not_touch_run.py` | 9 | A displayed moment never touches the run (round 2, stage D): on `off` and `numpy`, with one worker and with two, a Step or a Run after the display of an event, an answer or a snag (also under thematic pressure and with Self-watching off) is the run undisturbed in every field (steps, answer, draws, Trace, whole engine state); Clamp Themes and Clamp theme pattern act on the live state; a display met by a serial run at its yield, or by a parallel run before and while its workers execute, is refused and leaves the run identical; a reset or a delete forgets what was on show |
| `test_moment_display.py` | 6 | Event, answer and snag redisplay over the API: print names in the listing, the picture served live and from the stored row, the toggle and the switch, rows with no picture |
| `test_swarm_api.py` | 5 | `POST /api/swarm` equals the serial runs, persists nothing, and rejects bad requests; `GET /api/swarm` reports the pool |
| `test_training_mode_sessions_api.py` | 49 | Training Mode Sessions over HTTP: every stored run is the serial run; the 25 + 5 workflow (problems added while it runs); the finished long-poll; pause, resume, close, cancel, delete; the database written only when a problem finishes; a restart redoes what was cut off to the identical result and rebuilds the shared memory exactly; one worker is a serial episode and many replay from the merge log; fair sharing of the cores; every error policy; worker-failure retries, charged only to the run that broke the pool; a policy pause survives a concurrent status change; live counts never step backwards; a summary's finished cursor comes from the same snapshot as its counts; seed ranges fit the database; configuration change stalls or is adopted; validation, export, defaults and fixed settings |
| `test_unicode_problem_strings.py` | 6 | Any Unicode text end to end: a Training Mode Session of 20 corpus problems runs, is Stopped and reads back exactly from the database and the API; NFC and NFD problems both kept; Metacat Mode runs store and return the corpus exactly (runs row, Review, Run History); demo problems take Unicode names, sections and strings; U+0000 and a lone surrogate are a 422 in sessions, runs and demo problems; empty strings are a 422, not a crash, in runs and the Swarm |
| `test_unlimited_text.py` | 9 | All other text is unlimited too: a Training Mode Session's name and note and a configuration's name and note of any length and script are stored and returned exactly; configuration text (names, labels, formulas, a multi-character glyph) round-trips through the change API, and codelet type and help topic text holds any length; the journal's actor, channel, group and note are stored exactly; U+0000 and a lone surrogate are a 4xx naming the field at every entry point (session, configuration, and every string and key of a change batch); a caller's value for a fixed-vocabulary column is checked first, a 4xx never a 500 |
| `test_step0_config_from_db.py` | 47 | Step 0's guard tests: a shipped value reproduces the run and a changed one moves it |

**`tests/parallel/` — the multi-core plugin against the serial runs it claims to equal**

| File | Fns | Covers |
|------|----:|--------|
| `test_swarm.py` | 24 | A swarm outcome is the serial run's, byte for byte: demo problems × seeds, justification, episodes, parameter overrides, both CPU backends; errors come back as outcomes; configuration changes re-initialise workers; `Swarm.submit` (the Training Mode Session executor's entry point) returns futures equal to the serial runs, counts runs in flight (settled by the done-callback, which runs just after `result()` wakes its waiter, forced deterministically; task counts are not lost to concurrent `+=`) and resolves the default backend like `map` |
| `test_placement.py` | 13 | The measured backend policy: the CPU by default, never the GPU on its own, the environment overrides |
| `test_update_cycle.py` | 9 | The plugin's update cycle: faithful is bit-identical to the engine's, stream is identical at every thread count |
| `test_clock_rack.py` | 12 | The exponential-race coderack draws each codelet with the faithful two-stage draw's probability, and a later post never disturbs an earlier choice it does not beat; the prediction cached for an epoch stays exact until a post passes it |
| `test_effects.py` | 18 | The builtin effects table is complete, and no speculated read prefix writes shared state (the hidden-write detector) |
| `test_grant_timeout.py` | 1 | The speculative coordinator's grant timeout, forced to fire at every grant and at 1e-5 to 1e-4 seconds, changes nothing: the run's record equals the stream-serial reference's |
| `test_speculative_exact.py` | 19 | The speculative executor is bit-identical to the stream-serial reference at every worker count, with forced aborts too; which codelets run ahead, and how far, never changes a result; one worker is the reference itself; the slow sweep (`PETACAT_SPECULATIVE_SWEEP_SEEDS`) widens it |
| `test_session_transport.py` | 17 | S4: transport to workers: swarm equals serial equals in-process on evolved configurations (parameters changed, a body edited); the configuration shipped per task equals the plain run; no rebind across many configuration versions of two alternating sessions, and one serial child; worker death on the swarm and the serial child; the shipper and the worker cache bounded and exact; Metacat Mode's Swarm calls unchanged |
| `test_session_budgets.py` | 9 | S8: performance budgets of the session configuration machinery: a task's configuration is the provider's pickle and under the snapshot budget (always run); resolving and applying a batch, a live submit, hashing a new version, a worker composing one and the per-task overhead (timings, run only with `PETACAT_BUDGETS=1`) |
| `test_session_evolved_speculative.py` | 4 | S8: the speculative executor on a configuration evolved through the change API: edited bodies stay exact against the stream-serial reference, a restored body speculates again, an earlier version keeps its own decision, and a parameter-only evolution demotes no codelet type |
| `test_session_worker_isolation.py` | 1 | S8: a worker-side run, in a fresh interpreter, imports neither the journal layer, the database driver nor the ORM, so no worker can write a journal row |
| `test_training_mode_session_memory.py` | 10 | The Training episode memory without a database: descriptions survive the JSON storage encoding and pickle transport, a merge skips what the episode already holds and restamps ids in the master's numbering, a run's copy is independent of the master, a serial episode equals copy-and-merge one run at a time, and a worker reaches a version from its cache plus the tail (or asks for a snapshot) |

**Collected by no layer**

| File | Holds |
|------|-------|
| `tests/conftest.py` | The numeric backend matrix, the session ceiling, the per-layer summary |
| `tests/e2e/conftest.py` | The Postgres fixtures and the session advisory lock |
| `tests/unit/_fakes.py` | The shared hand-rolled doubles |
| `tests/support/expected_range.py` | A sampling pool over the demo problems, pointable at a modified engine through a `run_one` callable |
| `tests/support/standard_configuration.py` | The Metacat Standard Configuration as one cached `MetadataProvider` and its `ActivationParams`, and builders (`make_node`, `bare_slipnet`, `synthetic`) for the objects tests construct by hand, so no engine object carries a code default for a number the configuration holds |
| `tests/support/standard_names.py` | The Metacat Standard Configuration's vocabulary names as plain strings (`BRIDGE_TOP = "top"`, `GROUP_BUILT = "group_built"`, `PROPOSED`/`EVALUATED`/`BUILT`, the failure kinds ...), for tests that build structures by hand against the Standard Configuration. The engine spells none of them (it reads the run's vocabulary); a test that runs under a renamed vocabulary reads the vocabulary instead |

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
`test_dissertation_parity.py` and `test_numeric_engine.py`
use its `default_run_one` helper, and `scripts/bench_engine.py` drives it. Its pool runs workers on the NumPy backend,
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
`npx tsc --noEmit` alongside it. **744 cases across 52 files**, all passing, in
3.1 s on an Apple M-series machine.

| File (`client/src/`) | Cases | Covers |
|----------------------|------:|--------|
| `api/errors.test.ts` | 5 | One failure, one sentence a reader can act on |
| `api/ws.test.ts` | 4 | The URL the client opens is the route the server serves |
| `store/displayStore.test.ts` | 7 | Panel visibility (an entry for every panel including the EEG, Verbose hidden by default, toggling, show or hide all, remembered in localStorage, and surviving storage that throws) and the graphics switches that stop and resume the Slipnet and Coderack polls independently |
| `store/runStore.test.ts` | 45 | The spreading threshold outliving a page reload, the run's vocabulary adopted with the run, and the store's run lifecycle |
| `store/vocabulary.test.ts` | 6 | The run's bound vocabulary: `v(role)` follows a renamed binding, an unbound role is a name nothing equals (no crash), link types compare by behaviour, and a response without a vocabulary leaves the current one |
| `hooks/useWorkspaceClick.test.ts` | 3 | Clicking the Workspace steps when idle, stops a running run and resumes it on the next click, and ignores other buttons and a missing run |
| `App.test.tsx` | 4 | App's routing: `#/config?configuration=<id>` opens the configuration editors on that configuration (on load and on a hashchange), `#/config/slipnet/<node>` and `#/admin` still route, and the Configurations view's header and menu entry are neutral between the modes |
| `components/AdminPanel.test.tsx` | 6 | The Admin panel's operations report what became of them, and it says it edits the global configuration Metacat Mode uses |
| `components/CoderackBars.test.tsx` | 9 | The Coderack window as Metacat draws it: a slot per codelet type in engine order, bars at the engine's selection probability and never derived from a type's name, counts and total, the last-run marker, a recorded coderack without probabilities, and the Options-menu switches for the count column and the last-type marker |
| `components/CoderackView.test.tsx` | 6 | The Coderack panel's codelet-pattern clamps |
| `components/ClampControls.test.tsx` | 5 | Clamp theme pattern, Undo last clamp and the mid-run Self-watching toggle, as Metacat's Options menu has them |
| `components/CollapsibleGroup.test.tsx` | 8 | A collapsible group opens and closes from its header button, stays mounted when closed, remembers its state across a remount, and works when storage throws; the Run Controls panel's six groups start with Run and Episodic Memory open |
| `components/CommentaryPanel.test.tsx` | 7 | An empty commentary panel has two different causes |
| `components/EegView.test.tsx` | 4 | The EEG window: the two curves titled in Metacat's colours, each starting at 100 with one point per cycle, the message when a run has no EEG, and the live run read from the store |
| `components/HamburgerMenu.test.tsx` | 3 | Training Mode is a view of its own, between Review and Configurations (Metacat Mode and Training Mode), and choosing it reports the view to the app |
| `components/HelpPopover.test.tsx` | 3 | The popover shows a glossary term, and says when it cannot |
| `components/LastErrorBanner.test.tsx` | 3 | The error channel is rendered where it can be seen |
| `components/MemoryView.test.tsx` | 19 | The Memory panel shows the memory the run is thinking against, labelled as Metacat Mode's Episodic Memory |
| `components/ModeSwitch.test.tsx` | 16 | The header's switch between Metacat Mode and Training Mode: which mode each view belongs to, moving between them, the help link, and staying put while a run is processing |
| `components/MomentDisplay.test.tsx` | 25 | When the run is driven or Clamp Themes opens or closes, what is on show is forgotten and the server is asked for the live Themespace; clicking a Trace event, answer or snag redisplays the moment: the Workspace header and highlights, the Slipnet pattern, the Coderack, the Temperature, the Trace window's print-name labels |
| `components/ProblemInputPanel.test.tsx` | 13 | The problem panel owns the problem's identity; its four fields keep any text exactly, line breaks included |
| `components/RunControlsPanel.test.tsx` | 56 | A run starts on the problem the form actually shows, and the Workers control is labelled as the run mode |
| `components/RunHistory.test.tsx` | 34 | Run History stays current as runs finish |
| `components/RunParametersPanel.test.tsx` | 14 | The twenty-six run parameters, settable before a run |
| `components/SearchPalette.test.tsx` | 7 | Cmd+K search reaches every kind of help topic |
| `components/SelfWatchingWarning.test.tsx` | 4 | The red warning shown whenever self-watching is off: absent while it is on, and separate warnings for the next run and the loaded run, following a catalogue default of off |
| `components/SlipnetGraphView.test.tsx` | 13 | The Slipnet graph says what it could not do; links are drawn and filtered by behaviour, so a renamed slip link type still draws as a slip link |
| `components/SlipnetView.test.tsx` | 11 | The node-focus Edit button's visibility; a connection is coloured by its link type's behaviour |
| `components/SubstrateBadge.test.tsx` | 5 | The header says which processor the arithmetic runs on |
| `components/SwarmPanel.test.tsx` | 6 | The Swarm group: it sends the form's problem with the chosen seeds, shows the distribution and telemetry returned, uses justification mode when there is an answer, disables itself with a reason when the plugin is detached or the seed count is over the limit or there is no problem, and shows a server error without losing the form |
| `components/TemperatureGauge.test.tsx` | 8 | The gauge reports the engine's temperature clamp |
| `components/ThemespaceView.test.tsx` | 17 | The Themespace grid is clampable, as MetaCat's theme windows are; its theme-edit mode; column headings follow the bound theme-type names |
| `components/TraceView.test.tsx` | 5 | The Trace's icons, labels and filter follow the event-type names the run binds; an unbound or renamed name falls back to the plain form |
| `components/VerbosePanel.test.tsx` | 11 | The Verbose panel and the store's narration: polled from where the last reply ended, bounded on both sides, the Step button sent as step mode, the mode remembered with no run loaded |
| `components/WindowsMenu.test.tsx` | 3 | The Windows menu lists Hide/Show for each panel including EEG, hides and shows all windows, and carries the Slipnet and Coderack graphics switches |
| `components/WorkspaceView.test.tsx` | 17 | Workspace labels do not print on top of each other; bridge types and string kinds are the run's bound names |
| `components/admin/AdminEditors.test.tsx` | 43 | Every Configuration tab edits the collection it shows; opening a cell selects its value |
| `components/admin/AdminHttpFailures.test.tsx` | 10 | The Configuration screen reports what the server refused |
| `components/admin/ConfigurationManager.test.tsx` | 44 | The configuration manager: the chip's exact wording on every tab for global, Stopped, live and changing-state configurations, the list's badges, columns, filter and sort, Open, Freeze and Unfreeze, History, New session from this configuration (and the form's `configuration_base`), Compare and Apply from, and the deep link `#/admin?configuration=<id>` |
| `components/admin/ConfigurationPanel.test.tsx` | 11 | The Status and reset tab and the information banner: differing rows from the Metacat Standard Configuration, Compare, Verify journal, Reset after a typed confirmation, Restore selected |
| `components/admin/database/DatabasePanel.test.tsx` | 17 | The Database tab: class badges and banners, no edit control on read-only classes, the change batch built from the row editor, expert mode and its typed confirmation, refusals named by code, the SQL box |
| `components/admin/EditorSaveRefresh.test.tsx` | 1 | A successful Engine Params save refreshes the difference banner and the header chip without a tab change |
| `components/admin/EditAll.test.tsx` | 17 | Edit all: the scope picker (This, Chosen, All), the preview request, each per-target result, Overwrite, Apply the rest, Preview again, all-or-nothing and the reason, cancel, and Undo this group |
| `components/admin/EnumEditor.test.tsx` | 5 | The enum editor: the role column as a pick from the engine's list for the table with its note, no note for a table the engine names nothing of, a picked role saved and unbound, a refused delete of a bound row named, a rename as one request |
| `components/admin/ParamsEditorRefersTo.test.tsx` | 1 | The Engine Params tab shows what a parameter refers to and saves a picked value |
| `components/admin/history/HistoryPanel.test.tsx` | 9 | History: entries with source, actor, channel, note, version and counts, a live session's pending entries marked "not yet saved" and not undoable, entry detail, undo of a batch or group as a new entry, filters, and a refusal explained |
| `components/admin/history/mounting.test.tsx` | 2 | The names panel is mounted on a Training Mode Session's Memory tab (checked against that session's configuration) and on Metacat Mode's Episodic Memory view (checked against the global configuration) |
| `components/admin/history/NamesPanel.test.tsx` | 4 | Names that no longer resolve: the names of an Episodic Memory's theme patterns, each missing name with its story from the journal, finding a session's configuration, and showing nothing when all resolve |
| `components/admin/history/NodeHistory.test.tsx` | 5 | A node's History and restoring a deleted node with its dependents as a new entry, undoing the batch that removed it, and the deletion preview listing what cascades, dangles or is affected |
| `components/review/EpisodicRunTimeline.test.tsx` | 3 | A note being typed on an Episodic Memory clear survives a late refresh, and an untouched note follows the server |
| `components/review/ReviewPanel.test.tsx` | 35 | The review surfaces read the record back, and the episodic-run timeline shows each Episodic Memory clear between the runs with an editable note |
| `components/session/ConfigurationTab.test.tsx` | 12 | A Training Mode Session's Configuration tab: the version slider and the Live (in memory) or Stored (as of last stop) label, the Slipnet graph redrawn per version, the timeline and its source filter, Compare versions, Table rows, the link to the configuration manager, and no edit controls |
| `components/session/problemText.test.ts` | 52 | Parsing pasted or uploaded problems (any Unicode text, kept exactly and case-sensitive; double-quoted fields with JSON escapes in every line form; JSON entries with their own seeds, answer and tag) and the preview the Training Mode Session view shows before adding them |
| `components/session/SessionPanel.test.tsx` | 71 | The Training Mode Session view: the list and the selected Training Mode Session, creating one, adding problems, the error-policy fields, the problems table searched and sorted through the server, the Memory and Configuration tabs, the controls (start, pause, resume, stop, cancel, export), and Delete behind the session's name typed exactly; a session name of any length is sent whole on create and rename |

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
and `bench_free_running.py` (throughput and conflict rate by worker count). They take minutes and
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

## A run is bound in the layers that build structures directly

Structures, objects and trace events belong to a run: they take their identifier from its
allocator and their coefficients, Themespace and clock from its `RunBinding`
(`server/engine/run_binding.py`), and there is no process-wide fallback for either. The
autouse fixture `_test_run` in `tests/conftest.py` binds a run for the body of every **`unit`,
`seed_unit` and `module`** test (the Metacat Standard Configuration and a fresh identifier
allocator), so a test that builds a bond or a description directly has a run to belong to.
`architecture`, `integration`, `parallel`, `lockstep` and `e2e` run with **no** ambient run: what
they execute is a real engine path, and a path that forgot to open its run's scope must raise
`NoRunBound` there as it would in production, not find a run a fixture left behind
(`tests/integration/test_no_ambient_run.py`, and an e2e test of the same, hold the fixture to
that). A test in those layers that builds objects by hand binds its own, explicitly: `use_run` /
`use_allocator` in a fixture (`tests/parallel/test_clock_rack.py`, `tests/lockstep/test_naming.py`).
A test that needs structures to read another configuration or another Themespace calls
`rebind(meta=..., themespace=...)` from `tests/support/run_binding.py`; the fixture restores the
previous binding when the test ends. A test that wants to show that nothing is bound runs its body
in `contextvars.Context().run`, an empty context, and expects `NoRunBound`. A test that runs an
engine opens that engine's own scope on top (`EngineRunner` does it at every entry point).

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
- [x] `concept_mappings._descriptor_is_distinguishing` did an inline
      `from ...groups import Group` for an `isinstance` check.  **Moot** — the method
      was dead and is removed; the one live predicate is
      `workspace_objects.distinguishing_descriptor`.
- [ ] `themes.ThemeCluster.spread_activation` reads ~8 coefficients from
      `meta` — parameterize so the dynamics can be tested without a full
      `MetadataProvider`.
