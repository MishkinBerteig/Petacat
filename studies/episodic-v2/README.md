# Episodic Individual-Answer Discovery Pilot v2

This reference-only pilot supersedes the v1 smoke test's **whole-winner-set
population**, not its native definitions of best. No previous study is changed.
There is no port collection or full-oracle campaign in this protocol.

## Observation and Tie Rule

Each episode starts with empty memory, then runs the same problem eight times
while retaining memory. Native Metacat identifies two kinds of best answer:

- `best_a`: greatest native answer quality among the episode's stored answers.
- `best_b`: native conceptually preferred answer, selected from descriptions
  that no other description explicitly defeats in pairwise comparison.

**For either definition, tied co-winners are resolved by choosing the answer
reached FIRST in that episode.** Rank occurrences before collapsing answer
strings. A later strictly better answer still defeats an earlier weaker one.
There is no random, alphabetical, or numeric-quality tie-break for conceptual
preference. All conceptual comparisons use the same final episode memory.

Native memory stores descriptions newest first. The adapter reverses that
list before filtering and chooses the first surviving description. Native
fixtures test this against actual memory insertion, including an earlier `z`
and later `a` with equal quality and conceptual preference. Only the two chosen
answer strings and compact co-winner evidence are exported, not the run sequence.

Each answered, completed episode contributes exactly ONE answer observation to
each of two separate frequency tables. A string occurring only once in the
`best_a` table contributes one to its `f1`; `best_b` has its own `f1` and support.
An unfamiliar combination of familiar answers is no longer an unfamiliar outcome.
The two tables share episode execution cost. Their observations can be correlated;
no statistical independence between the definitions is assumed or needed here.

## Curves and Budget

[protocol.pilot.json](protocol.pilot.json) fixes four problems spanning the
earlier smoke cases and two more structurally complex cases:

| Problem | Analogy |
| --- | --- |
| `misc4` | `a -> b; z -> ?` |
| `run4` | `abc -> abd; xyz -> ?` |
| `run1` | `abc -> abd; mrrjjj -> ?` |
| `fig5.4-top` | `eeqee -> qeeq; xxixx -> ?` |

- Eight runs per episode, at most 1000 episodes per problem.
- Separate `best_a` and `best_b` curves at 100, 200, ..., 1000 episodes.
- Target `f1/N <= 0.0001`; no threshold-triggered early stopping in this pilot.
- At most **4000 episodes / 32000 inner runs**; no automatic budget increase.
- 100000 codelets per inner run; 12 CPU workers; no GPU.
- Whole episodes assigned dynamically to available workers; no shared memory
  between episodes. Every episode runs in a fresh reference process.
- 300 seconds per episode and four hours per invocation. Operational failures
  stop collection and retain attempts; incomplete retries require explicit review.
- New seed blocks starting at 90000000, disjoint from the previous studies'
  engine seed allocations. No production data are silently combined with this pilot.

For this pilot, both curves continue to the fixed budget even if one reaches zero
early. This exposes later new answers and rebounds in `f1/N`. The report identifies
each curve's first observed threshold crossing independently; that is NOT a
validated saturation point. A future oracle can freeze `best_a` and `best_b` at
different agreed stopping points, executing shared episodes until both are done.
This pilot does not choose that final stopping policy on the basis of its results.

### Denominators and Failures

The horizontal axis counts completed scheduled episodes. `N` counts completed
episodes that actually produced at least one answer, so an answerless episode
does not turn a nonexistent answer into a species. `f1/N` therefore estimates
missing mass **conditional on a completed episode producing an answer** under
the fixed episode and tie rules. Both definitions normally have the same `N`
at a given checkpoint, even though their threshold-crossing times can differ.

Entirely answerless episodes and engine-error episodes are retained and counted
separately. An engine exception terminates the whole episode; its successful
prefix is never admitted as a complete best answer. Caps and answerless inner
runs retain their actual memory for the next scheduled run. The report includes
these outcomes, attempted inner runs, and codelet costs. It also reports the
descriptive `f1 / completed episodes`; this is not an additional confidence bound.

### Interpretation

`f1/N` is a Good-Turing heuristic missing-mass estimate, not a confidence level
or upper bound. With `N <= 1000`, any nonzero value is at least **0.001**.
The proposed **0.0001** target can therefore only be crossed in this pilot when
`f1` is zero. Such a crossing does not establish that the true discovery
probability is below 0.0001. The curves are an initial feasibility and budget
diagnostic, not a completed high-confidence oracle.

The practical hypothesis is that these selected-answer populations concentrate
quickly enough to make the oracle cheaper to construct. Cost comparisons must
count the **eight inner runs per episode**, not just episodes. Selection of the
best of eight opportunities can itself concentrate results, so this pilot alone
cannot attribute a reduction causally to learning. That does not prevent it from
testing the practical oracle-construction cost with episodic memory enabled.

## Running and Auditing

Use a Petacat checkout on the experiment host, with the source reconstructed
from the [public patch bundle](../../Metacat/README.md). Reuse the dependency
setup in the [v1 study README](../episodic-v1/README.md). Do not modify frozen
previous-study checkouts. The new collector imports the unchanged v1 native
preference adapter and record-validation helpers; retain that directory too.

```sh
python3 -m unittest discover -s studies/episodic-v2 -p 'test_*.py'
docker run --rm --platform linux/amd64 --network none \
  -v "$PWD/Metacat/build/source:/metacat:ro" \
  -v "$PWD/studies/episodic-v1:/selectors:ro" \
  -v "$PWD/studies/episodic-v2:/study:ro" -w /metacat \
  --entrypoint env metacat:local -u DISPLAY \
  scheme -q --script /study/fixtures.ss
python3 studies/episodic-v2/pilot.py prepare \
  --image metacat:local --out studies/episodic-v2/output/pilot-01
python3 studies/episodic-v2/pilot.py run --out studies/episodic-v2/output/pilot-01
```

Preparation fingerprints the protocol, engine, native adapter, collector,
reconstruction, and runtimes. Development files are fingerprinted separately
from their Git baseline. Changing any prepared input invalidates resumption.
Checksummed receipts prevent completed episodes from being repeated.

```sh
python3 studies/episodic-v2/pilot.py status --out studies/episodic-v2/output/pilot-01
python3 studies/episodic-v2/pilot.py analyze --out studies/episodic-v2/output/pilot-01
python3 studies/episodic-v2/pilot.py export \
  --out studies/episodic-v2/output/pilot-01 \
  --destination studies/episodic-v2/results/pilot-01
python3 studies/episodic-v2/pilot.py verify-export studies/episodic-v2/results/pilot-01
```

Analysis and export use saved observations and execute neither engine. The
public bundle includes the compact observations, all 80 curve points, source
and runtime fingerprints, and checksums. Private machine paths, image IDs,
configuration, and operational logs remain in Git-ignored `output/`.
No original Metacat source is redistributed.

## Serializer Correction Before the First Checkpoint

The initial invocation completed search in 24 episodes. Eighteen observations
were saved, but serialization failed in six `run1` episodes: the reused v1
theme formatter treated native `diff` as a concept object, whereas `themes.ss`
defines it as `#f`. All six had already executed eight runs. The coordinator
stopped dispatch and allowed active workers to finish; it did not silently
discard these attempts or classify them as Metacat search failures.

The v2 adapter now formats this native relation as the literal `diff`.
Deterministic fixtures cover both the relation and complete answer-description
serialization. No engine, ranking, seed, tie rule, or sampling budget changed.
The interrupted checkout and output are preserved. A corrected checkout imports
the 18 checksummed complete episodes byte for byte, archives the entire parent,
and replays only the six missing observations as part of the original allocation.
Their prior **48 inner runs** are excluded diagnostic overhead, in addition to
the maximum 32000 inner runs represented by the planned observations.

`import-completed` is an explicit serializer-only amendment, not generic
permission to mix changed engines or protocols. `parent-import.json` records
the changed tool files, original artifact hashes, inherited observations, and
excluded execution costs. A new prepared output is required:

```sh
python3 studies/episodic-v2/pilot.py import-completed \
  --out studies/episodic-v2/output/pilot-02 \
  --parent /path/to/preserved/pilot-01
```
