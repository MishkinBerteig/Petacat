# Capped Episodic Frozen-Oracle Study v3

This is a new, post-pilot protocol for all 19 problems in the single-run study.
It preserves earlier studies and does not modify either engine. Reference
collection and port execution belong on the designated experiment host, in a
fresh Petacat checkout, not in a separately modified Metacat source directory.

## Authorized Protocol

- Eight runs per episode, 100000 codelets per run. Memory is retained within
  an episode and starts empty in every new episode.
- `best_a` selects maximum native answer quality. `best_b` selects an
  undefeated answer under native conceptual preference. The earliest reached
  winning occurrence breaks ties independently for each definition.
- Two frequency tables of individual selected answer strings, not sequences
  or whole co-winner combinations. Native co-winner summaries remain audit
  evidence, not additional observations.
- Check `f1/N <= 0.0001` after **every construction episode**, with **no minimum
  sample floor**. Each definition freezes independently at its first crossing.
  Construction stops as soon as both have frozen, or at **2000 episodes per
  problem**, whichever comes first. No construction episode is dispatched
  speculatively past the current episode for a problem.
- A problem receives **1000 reference validation episodes only if both
  definitions have frozen**. An individually qualifying definition is not
  enough to enable validation for a problem whose other definition hits the cap.
- **Every problem receives 100 port episodes**, including capped problems.
  These episodes supply both port winner observations, so they are not doubled.
- Twelve CPU workers, no GPU. A shared queue assigns whole episodes to free
  workers. At most one construction episode per problem is in flight, so
  construction concurrency may fall below 12 near the end. Validation and
  port work have no such per-problem ordering restriction.
- Operational timeout: 300 seconds per episode and 12 hours per invocation.
  Timeouts and unexpected infrastructure/selector failures stop collection;
  they are not silently converted into answer types or automatically retried.

An immediate zero after two identical winners is allowed by explicit policy.
It is only a construction heuristic, not a coverage guarantee. Validation can
reject an oracle that froze very early. The two definitions share execution
cost but are not assumed statistically independent.

## Pilot Reuse

The four v2 pilot problems already have 1000 recorded episodes each. All of
those observations, including the engine-error episode, are imported as
construction prefixes. Their existing seed assignments remain unchanged.
Freezing is first evaluated using each whole imported prefix, then after every
new episode. No retrospective claim is made that the pilot stopped after two
episodes or cost fewer runs than it actually did. The other 15 problems start
from empty construction tables and may stop immediately when both criteria pass.

Import requires matching engine, selector, serializer, and runtime fingerprints.
The full private pilot output is preserved byte for byte. New episode identities
map its `discovery` phase to `construction`, with the original receipt and hash
retained as provenance. There is no reexecution of imported scientific samples.
The pilot's six serializer-failure attempts remain excluded diagnostic overhead:
48 inner runs and 948508 codelets. The earlier pilot code and files are untouched.

## Validation Strength

Both supports are frozen before validation begins. Every validation winner
outside its corresponding support counts as one miss, even if the same outside
answer appears repeatedly. Validation never changes an oracle. The declared
batch size is not extended until a favorable bound is obtained.

`N` counts answered, complete validation episodes. Engine-error episodes and
entirely answerless episodes are retained separately, not counted as covered
answers. The coverage statement is conditional on completing with an answer
under the declared 8-run, capped protocol. It is not a reliability guarantee.

The coverage target is a one-sided upper bound of **0.01**, with **95%
simultaneous confidence across all 38 problem/definition populations**.
The family is fixed before construction; it does not shrink when some problems
fail to qualify. We use an exact binomial bound with alpha `0.05/38` per
population. No independence between A and B is required by this correction.

At `N=1000`, zero misses gives an adjusted upper bound of approximately 0.00661,
one miss gives 0.00889, and two misses gives 0.01085. Thus at most one miss
qualifies in this full 19-problem design. These differ from the earlier
four-problem illustration, which adjusted for only eight populations.

References: [NIST exact binomial limits](https://itl.nist.gov/div898/software/dataplot/refman2/auxillar/exacbino.htm)
and [NIST Bonferroni method](https://www.itl.nist.gov/div898/handbook/prc/section4/prc463.htm).

The report distinguishes:

- `skipped-threshold-not-met`: construction reached its cap without both
  crossings; validation was not collected and no coverage claim is made.
- `coverage-target-not-met`: construction qualified, but its held-out bound
  exceeded 0.01. The observations and bound are still reported.
- `qualified`: the fixed held-out batch supports the declared conditional bound.
- `incomplete` or `no-answered-episodes`: no usable final coverage claim.

Failure to qualify does **not** make the retained observations invalid. It means
the statistical coverage guarantee is absent. Any expanded oracle and another
validation attempt would need a new version, fresh validation data, and a
declared confidence-error budget across repeated attempts. No such automatic
extension is part of this study.

## Port Comparison

For every problem and definition, publish the reference and port counts and
fractions for every answer appearing in either sample. Reference frequency
tables use **all collected construction episodes**, clearly distinguished from
an independently frozen definition's possibly shorter oracle prefix.

For capped problems these comparisons are explicitly informal: no p-values,
equivalence claims, or coverage confidence bounds are manufactured. For
validated oracles, support-membership flags have the reference coverage context,
but an outside port answer is still an investigation flag, not proof of a bug.
Frequency comparisons remain descriptive throughout; this protocol does not
introduce a calibrated port distribution test or a defect-detection power claim.

## Sampling and Accounting

New episode first seeds are independently sampled with replacement from the
valid first-seed domain. Each episode uses that seed and its next seven integer
seeds. The full sampling plan is recorded and hashed before collection. Repeated
seed draws are allowed, as required by sampling with replacement; they are not
silently removed. Disjoint numerical seed ranges alone would not establish
independent sampling from the same seed distribution. The preserved pilot
construction prefix uses its original deterministic allocation and remains
exploratory. Fresh validation is independent of the construction data.

Every engine exception ends its whole episode. Successful prefixes are not
admitted as shorter episodes, and a failed seed is not retried until success.
Actual inner-run counts, answerless and capped runs, error records, codelets,
and elapsed times are retained. Aggregate per-episode elapsed time is not wall
campaign time or CPU time.

Maximum main allocation, including inherited construction episodes:

| Phase | Maximum episodes | Maximum inner runs |
| --- | ---: | ---: |
| Construction | 38000 | 304000 |
| Eligible-problem validation | 19000 | 152000 |
| Port, all problems | 1900 | 15200 |
| Total | 58900 | 471200 |

Early stopping and skipped validation reduce this total. The imported pilot
accounts for 4000 assignments and 31999 actual inner runs; its one engine error
prevented an eighth inner run. At most 439200 additional scheduled inner runs
remain after reuse, before any reduction from stopping or errors. Independent
preflight executions and the 48 earlier diagnostic runs are additional overhead,
not new scientific observations. The preflight is capped at 256 inner runs.

This budget is not directly evidence of learning-induced savings: the validation
coverage target differs from the original single-run study's target.

## Running and Verifying

Start with the [Metacat dependency and reconstruction instructions](../../Metacat/README.md)
and the [study runtime setup](../episodic-v1/README.md). Keep the v1 and v2 study
directories: v3 deliberately reuses their fingerprinted engine adapters and
receipt validators. Its port wrapper preserves native insertion order before
the existing adapter canonicalizes evidence. The Python statistical code uses
only the standard library; NumPy is needed to execute the port.

```sh
python3 -m unittest discover -s studies/episodic-v3 -p 'test_*.py'
python3 studies/episodic-v3/study.py prepare \
  --protocol studies/episodic-v3/protocol.smoke.json \
  --image metacat:local --out studies/episodic-v3/output/preflight-01
python3 studies/episodic-v3/study.py run --out studies/episodic-v3/output/preflight-01
```

After inspecting the independent preflight, prepare the main study explicitly:

```sh
python3 studies/episodic-v3/study.py prepare --allow-full-experiment \
  --image metacat:local --out studies/episodic-v3/output/main \
  --pilot /path/to/preserved/episodic-v2/output/pilot-02
python3 studies/episodic-v3/study.py run --allow-full-experiment \
  --out studies/episodic-v3/output/main
```

Preparation rejects an existing output directory. Both engines, study tools,
input protocol, seed plan, and runtimes are fingerprinted. The Git baseline and
uncommitted study-tool content hashes are both recorded; this is not falsely
represented as a clean committed study snapshot. Do not edit a prepared checkout.
Checksummed completion receipts prevent completed tasks from being reexecuted.
Incomplete execution attempts require investigation; there is no automatic retry.

```sh
python3 studies/episodic-v3/study.py status --out studies/episodic-v3/output/main
python3 studies/episodic-v3/study.py analyze --out studies/episodic-v3/output/main
python3 studies/episodic-v3/study.py export --out studies/episodic-v3/output/main \
  --destination studies/episodic-v3/results/main
python3 studies/episodic-v3/study.py verify-export studies/episodic-v3/results/main
```

Analysis and export verification execute neither engine. A partial concurrent
phase may have gaps; wait for its fixed batch to finish before final analysis.
Public exports omit private paths, image IDs, and operational configuration.
The complete private attempt tree and preserved pilot remain in ignored
`output/`. No upstream Metacat source is redistributed.
