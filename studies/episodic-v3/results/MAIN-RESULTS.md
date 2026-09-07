# Episodic v3: Completed Study

The declared study is complete. No engine changes, repeated failed seeds,
construction extensions, or extra validation batches were used. All searches
ran in the separate experiment checkout; local verification only reads data.

## Results

- Construction: 10074 episodes across all 19 problems, including the 4000
  preserved pilot episodes. Fourteen problems froze both answer sets.
- Five problems reached the 2000-episode cap without freezing both sets:
  `misc4`, `run4`, `run1`, `fig5.4-top`, and `eqe-baaab`. None received
  validation; all received their 100 port episodes.
- Validation: exactly 1000 assigned episodes for each of the 14 eligible
  problems, or 14000 episodes total.
- Port: exactly 100 assigned episodes for every problem, or 1900 total.
- Only `copy1`, `copy2`, and `copy3` meet the validation coverage target for
  **both** answer sets. All their port winners fall within their respective
  frozen supports. This is not a distributional-equivalence claim.
- Eight of 28 tested individual populations meet the target: both definitions
  for `copy1` through `copy3`, `misc3 best_a`, and `copy4 best_b`. Twenty tested
  populations fail it; another ten were not tested because their problems
  did not pass the construction gate. Confidence correction still uses the
  full, predeclared family of 38 populations.

Every passing individual population had zero validation misses among 1000
answered episodes, giving an adjusted one-sided upper bound of approximately
0.006611. The target was 0.01 with 95% simultaneous confidence. Bounds are
conditional on answered, complete episodes, not guarantees of engine reliability.

`copy5` had five completely answerless validation episodes and four completely
answerless port episodes. Its answered denominators are therefore 995 and 96,
respectively; all 1000 and 100 assignments remain in the data. There were no
new engine-error episodes. The single construction engine error is the retained
`run4` pilot failure, not a newly encountered or retried failure.

## Main Methodological Finding

Immediate freezing at the first zero Good-Turing estimate often produces an
incomplete oracle. Two identical initial winners can yield `f1/N = 0` even
when further sampling frequently produces other winners. The independent
validation exposed this: for example, `misc5` froze both supports at episode 2,
but 480/1000 `best_a` and 591/1000 `best_b` validation winners were outside them.

The estimator is a construction heuristic, not a confidence guarantee. The
study does not justify presenting its 14 construction-qualified problems as
14 validated oracles, or describing 0.0001 as achieved coverage. The fixed
validation step worked as an independent check, including when it rejected
the construction heuristic's result.

The imported pilot prefixes were first eligible to freeze at episode 1000,
whereas the other problems could freeze immediately. That declared asymmetry
must remain explicit. Construction frequency tables use all collected
construction observations, not the independent validation observations.

## Priority Port Discrepancy

For `misc3 best_a`, the frozen support is `{kji, kkjjii, kkkjjjiii}`.
Reference validation produced 0 outside winners in 1000 answered episodes;
the port produced 24 outside winners in 100 answered episodes, spanning ten
additional answer strings. This is a concrete investigation flag with a
validated reference-coverage context, despite `misc3 best_b` failing its
separate validation check. It is not an established root cause or a calibrated
port-test verdict. No new hypothesis test or engine fix was added after seeing
this result.

The port's outside `best_a` counts are: `kjiii` 5, `kjjiii` 1, `kjjji` 2,
`kjjjiii` 4, `kkkji` 2, `kkkjiii` 3, `kkkjji` 1, `kkkjjiii` 4,
`kkkjjji` 1, and `kkkkjjjii` 1. The next investigation should distinguish
winner extraction/scoring differences from differences in the underlying
episodic search, using the preserved evidence before scheduling new runs.

For capped problems and failed coverage checks, reference/port frequencies
remain descriptive. Outside-oracle port answers alone do not show a port bug
when the reference oracle itself demonstrably misses common answers.

## Cost and Preservation

| Phase | Episodes | Actual inner runs | Engine-error episodes |
| --- | ---: | ---: | ---: |
| Construction, including pilot | 10074 | 80591 | 1 inherited |
| Reference validation | 14000 | 112000 | 0 |
| Port | 1900 | 15200 | 0 |
| Main study total | 25974 | 207791 | 1 inherited |

The main campaign newly executed 175792 inner runs after reusing 31999 pilot
runs. The independent preflight added 208 runs; the earlier pilot serializer
diagnostics cost another 48 historical runs. Those overheads are not additional
scientific samples. The new main campaign took approximately 10 hours 27
minutes; inherited pilot execution time is not included in that wall duration.

Lower cost than the earlier single-run study cannot by itself demonstrate
learning-induced savings: the coverage target and protocol differ, and most
episodic supports did not meet the coverage target. These results support a
limitations analysis and an investigation of the port, not an unqualified
episodic-port fidelity or learning-efficiency claim in the paper.

## Artifacts and Verification

- [Full per-problem report](main/REPORT.md), [machine-readable results](main/analysis.json),
  [frozen supports](main/oracles.json), and [episode observations](main/episodes.json).
- [Per-episode construction curves](main/curves.csv) and
  [descriptive reference/port frequencies](main/frequencies.csv).
- [Protocol](main/protocol.json), [source/runtime manifest](main/manifest.json),
  [seed assignments](main/seeds.json), and [pilot provenance](main/pilot-import.json).
- [Public checksums](main/SHA256.json) and [completed-study replay audit](main-audit.json).

Both remote and local export verification reproduce all 25974 observations'
stopping decisions, gates, confidence bounds, and frequency summaries without
engine execution. A completed-study replay made zero engine calls and left
274304 raw-data and oracle files unchanged. All 114 fingerprinted source files
match the local checkout. The v3 deterministic suite passes all 22 tests.

The full private attempt tree, including the byte-preserved pilot, is also
archived under ignored `../output/main-private.tar.gz`; its checksum is in
`../output/main-private-checksum.json`. That private archive contains operational
metadata and must not be committed. The public bundle omits private machine
paths and identifiers, Docker image IDs, and upstream Metacat source. This
results note is outside the immutable checksummed bundle.

To verify the public results, without running either engine:

```sh
python3 studies/episodic-v3/study.py verify-export studies/episodic-v3/results/main
```
