# Episodic Best-Answer Study v1

This study compares conceptual results from memory-retaining Metacat and
Petacat episodes. It does not compare ordered run sequences. The shipped
configuration is a tightly bounded smoke test, not the full experiment.

## Two Populations

Each episode starts with empty episodic memory, runs the same problem eight
times while retaining memory, then produces two observations:

1. **Quality:** the unordered set of answer strings from all occurrences tied
   for the highest native answer quality.
2. **Preference:** the unordered set of answer strings from answer descriptions
   that no other description in that episode is explicitly preferred to under
   the native conceptual comparison.

Rank answer occurrences before collapsing their spelling. Identical letters can
come from different conceptual interpretations. Pairwise comparisons use the
same final episode memory. Neither arrival order nor numeric quality breaks a
native conceptual tie. A cyclic or asymmetric preference relation stops the
collector for review rather than selecting an arbitrary winner.

The two populations have separate counters, supports, p50 sets, and `f1/N`
estimates, but observations from the same episode are **paired, not statistically
independent**. These experiments do not estimate a distribution over trajectories.

An entire unordered winner set is ONE categorical observation. For example,
`{a,b}` and `{a}` are different outcomes, even if both letters were seen before.
`N` counts episodes, and `f1` counts winner-set outcomes observed exactly once.
Thus `f1/N` estimates the missing probability mass of best-answer SETS, not the
chance of a new individual member string. Newly encountered member strings are
reported separately. Tied members are never counted as independent draws.

The native quality formula is 60% absolute top-rule quality plus 40% inverse
answer-time temperature, rounded. The preference ordering uses coherence,
snag-adjusted justification, comparable-rule abstractness, and thematic richness.
See the [conceptual analysis](../../academic/EPISODIC-BEST-ANSWER-ANALYSIS.md)
and the [original Metacat archive](https://science.slc.edu/jmarshall/metacat/Metacat-1.2.tgz).
No original source is included in this directory.

## Experimental Design

There are three disjoint seed allocations per problem:

1. **Construction:** Metacat episodes produce both populations. At declared
   checkpoints, calculate `f1/N` separately. Stop only after BOTH estimates are
   at or below the threshold for the specified number of consecutive checkpoints,
   after the minimum sample size. Otherwise stop at the hard episode budget and
   label the result `budget-exhausted`, not saturated.
2. **Validation:** collect a fixed number of fresh Metacat episodes against
   the frozen construction oracles. Never add validation outcomes to them.
3. **Port:** collect a smaller fixed Petacat episode sample and compare its two
   populations with those same frozen oracles.

Each episode has its own process, fresh initial memory, and fixed consecutive
seed block. A process never supplies another episode's memory or global state.
Different problems and phases use nonoverlapping blocks. The reproducible seed
schedule is a pseudorandom sampling convention, not a proof of independence.
The engine code, seed data, reconstructed source, runtime, and protocol are
fingerprinted. Full runs require clean committed study inputs; development
smokes may use a separately fingerprinted working-tree snapshot.

For both engines the limit is 100000 codelets PER RUN, not per episode. Capped
and answerless runs leave their actual memory for the next scheduled run. An
engine exception terminates the whole episode, becomes an `engine-error`
observation in both populations, and retains its seed/step and condition.
An entirely answerless episode becomes `no-answer`. Both remain in `N`.
Neither is silently assigned a numerical quality. No suffix is restarted with
empty memory, and no successful prefix is represented as a complete episode.

Timeouts, resource/I/O failures, malformed output, and selector failures are
operational failures, not ordinary answer outcomes. Attempts are preserved and
collection stops. Retrying an incomplete attempt requires explicit review and
`--retry-incomplete`; completed observations, including engine errors, are never
automatically retried. Work is distributed as whole episodes through a shared
worker pool, so idle workers take the next available episode.

### Interpreting Good-Turing

`f1/N` is a heuristic estimate of missing probability mass. It is NOT a
confidence level, a confidence bound, a p-value, or proof that a correct port
cannot produce a new outcome. Repeated checkpoint inspection does not convert
it into a sequential confidence guarantee. Zero singletons does not establish
zero missing mass. [Good's original paper](https://doi.org/10.1093/biomet/40.3-4.237)
provides the species-frequency foundation.

Held-out novelty is reported separately. If a fixed held-out sample has zero
novel outcomes, the report includes the nominal per-problem, per-projection
95% upper bound `1 - 0.05**(1/n)`, conditional on the frozen oracle and independent
validation episodes. It is not simultaneous across projections/problems. Four
zero-novelty validation episodes still give an upper bound of about 0.527:
the smoke test cannot establish 0.1 missing mass with 95% confidence.

The p50 set is the deterministic smallest frequency-ranked set of construction
outcomes accumulating at least half the empirical episode mass; ties are ordered
by canonical outcome encoding. Missing-p50 and novelty are descriptive outputs
in this smoke test, not calibrated defect verdicts. A production combined alarm
across both populations will need a declared false-alarm policy and adequate
held-out calibration. Reference cost is shared by both projections.

## Smoke Budget

[protocol.smoke.json](protocol.smoke.json) fixes:

| Parameter | Value |
| --- | --- |
| Problems | `misc4`: `a -> b; z -> ?`; `run4`: `abc -> abd; xyz -> ?` |
| Episode horizon | 8 runs with memory retained |
| Construction | Minimum 8, maximum 20 episodes per problem |
| Checkpoints | Every 4 episodes; two consecutive passing checkpoints |
| Heuristic target | Both `f1/N <= 0.1` |
| Held-out validation | 4 reference episodes per problem |
| Port comparison | 4 episodes per problem |
| Workers | 2 CPU workers; no GPU |
| Operational limits | 300 seconds per episode; 1800 seconds per invocation |
| Maximum main smoke observations | 56 episodes, 448 inner runs |

Reaching the target can reduce collection below this maximum. Failure to reach
it is useful smoke evidence and will NOT automatically increase the budget or
relax the threshold. Separate diagnostic replay checks, if performed, must be
counted and labelled outside these observations.

## Setup and Commands

Run actual engine collection on the designated experiment host. The following
commands are relative to a **Petacat checkout**, not a separate modified
Metacat directory. Use a new checkout to leave previous frozen studies alone.

1. Install Git, Python, Docker, and the Metacat runtime using the linked
   [dependency and reconstruction instructions](../../Metacat/README.md).
2. Pull the intended Petacat revision and reconstruct its patch bundle:

   ```sh
   git pull --ff-only origin main
   python3 Metacat/tools/reconstruct.py --output Metacat/build/source
   python3 Metacat/tools/reconstruct.py --verify Metacat/build/source
   ```

3. Use a Python environment with NumPy and SciPy. An existing study environment
   can be reused without modifying it, or create one:

   ```sh
   python3 -m venv .venv-episodic
   .venv-episodic/bin/python -m pip install numpy scipy
   ```

   The exact installed package versions are recorded at preparation and checked
   before resuming. See [Python venv](https://docs.python.org/3/library/venv.html),
   [NumPy installation](https://numpy.org/install/), and
   [SciPy installation](https://scipy.org/install/).

4. Build/tag the Docker runtime as described in the Metacat README, or use an
   existing compatible runtime image. Replace `metacat:local` below with its
   local tag; image identifiers are private execution configuration, not an
   installation prerequisite for other users. The source executed is always
   the reconstructed source mounted from this checkout, not source inside the
   image.

5. Run deterministic tool tests, which execute no search codelets:

   ```sh
   python3 -m unittest discover -s studies/episodic-v1 -p 'test_*.py'
   docker run --rm --platform linux/amd64 --network none \
     -v "$PWD/Metacat/build/source:/metacat:ro" \
     -v "$PWD/studies/episodic-v1:/study:ro" -w /metacat \
     --entrypoint env metacat:local -u DISPLAY \
     scheme -q --script /study/fixtures.ss
   ```

6. Explicitly prepare and start ONLY the bounded smoke configuration:

   ```sh
   .venv-episodic/bin/python studies/episodic-v1/collect.py prepare \
     --protocol studies/episodic-v1/protocol.smoke.json \
     --image metacat:local --out studies/episodic-v1/output/smoke-01
   .venv-episodic/bin/python studies/episodic-v1/collect.py run \
     --out studies/episodic-v1/output/smoke-01
   ```

Status and saved-data analysis:

```sh
python3 studies/episodic-v1/collect.py status --out studies/episodic-v1/output/smoke-01
python3 studies/episodic-v1/collect.py analyze --out studies/episodic-v1/output/smoke-01
```

Analysis reads checksummed saved observations; it does not execute either engine.
Repeating `run` on a completed study verifies it and performs no new collection.
Do not change inputs inside a prepared study. Preserve a failed development
attempt and prepare a newly named output directory after fixing the code.

## Artifacts and Future Main Study

Each episode emits a compact `episode.json`, selected-answer evidence, and an
artifact-checksummed completion receipt. Its engine's episodic memory exists
normally during execution but no ordered run/answer list is exported. Quality
and preference winners can retain multiple descriptions with the same spelling;
those descriptions collapse to one member in the categorical winner set.

The output contains `protocol.json`, `manifest.json`, `progress.json`,
`analysis.json`, `REPORT.md`, and a final `COMPLETE.json`. `local.json` and
operational logs are local execution details. The entire `output/` directory is
ignored by Git; a future public release should exclude local configuration and
sanitize operational metadata as in the earlier study release.

The collector supports larger versioned protocols but ships no approved full
study budget. To prepare a main study, copy and review the JSON protocol with
`study_kind` set to `main`, choose nonoverlapping new seed blocks, the full
problem set, minimum/checkpoint/maximum construction budgets, and fixed
validation and port sample sizes. Threshold choice and a maximum budget are
separate decisions. Commit the study inputs before preparation. Main preparation
AND collection require the explicit `--allow-full-experiment` flag. There is no
automatic transition from this smoke test into a main experiment.

The separate experience-then-judgment experiment discussed in the analysis is
not included here: this version implements the requested two best-answer
populations from repeated solve-mode episodes.
