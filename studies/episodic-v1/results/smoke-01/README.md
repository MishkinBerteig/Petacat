# Episodic Smoke Test 01

Completed 2026-09-06 using the [bounded protocol](protocol.json) and the
[study design](../../README.md). This is development verification, not the
full experiment and not publication-strength evidence of equivalence.

## Results

| Problem | Population | Reference episodes | f1 | f1/N | Held-out novel sets | Port novel sets |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `a -> b; z -> ?` | Quality | 16 | 1 | 0.0625 | 0/4 | 0/4 |
| `a -> b; z -> ?` | Conceptual preference | 16 | 0 | 0 | 0/4 | 0/4 |
| `abc -> abd; xyz -> ?` | Quality | 16 | 0 | 0 | 0/4 | 0/4 |
| `abc -> abd; xyz -> ?` | Conceptual preference | 16 | 0 | 0 | 0/4 | 1/4 |

Both problems passed the joint heuristic criterion at N=12 and N=16, then
stopped at N=16. The four population rows share their underlying episodes;
they are not four independent samples.

- 32 reference-construction episodes, 8 held-out reference episodes, and
  8 port episodes: **48 episodes, 384 inner runs**. The maximum was 56/448.
- 254 inner runs added an answer to memory; 130 ended without one. All 48
  episodes contained at least one answer. No engine-error episodes, capped
  runs, incomplete attempts, or automatic retries occurred.
- 840713 total codelets. Collection elapsed time was about 66 seconds with
  two CPU workers. No GPU or local-machine engine searches were used.
- The two selected answer sets differed in 22/48 episodes. Nine episodes
  had multiple quality-winning strings; eleven had multiple preference-winning
  strings. Thus the test actually exercised both distinct selectors and ties.
- No ordered within-episode histories were exported. All 96 stdout/stderr
  logs were empty. Only aggregate run counts and selected-answer evidence
  were retained in the observations.

## Interpretation of the Novel Set

For the port's `run4` episode 1 (first seed 80100008), the quality winner was
`{yyz}` and the preference winners were `{xyd, yyz}`. The reference preference
support contained `{yyz}`, `{wyz}`, `{wyz, yyz}`, and `{wyz, xyd, yyz}`.
Thus this is a new **combination**, not a new individual answer string.

The saved evidence explains the tie: `xyd` and `yyz` were both coherent, each
had three themes and zero unjustified themes, but their themes differed.
Consequently the native abstractness tie-break did not apply; unequal numeric
qualities (74 and 89) did not force a conceptual preference.

This is not a confirmed port defect. Sixteen reference episodes and a
heuristic singleton estimate cannot establish complete support. Indeed,
zero singletons did not prevent a later novel port set. The held-out native
sample also missed the `{yyz}` preference p50 member for `run4`, illustrating
why tiny-sample missing-head flags cannot be treated as defect verdicts.

There were zero novel outcomes in each four-episode native held-out check.
The corresponding nominal per-problem, per-population 95% zero-event upper
bound is still 0.527, not 0.1. These data establish that the collector operates
and preserves the intended distinctions; they do not validate its full-study
false-alarm rate or establish that episodic learning caused an improvement.

## Verification and Reuse

Before collection, 29 deterministic Python tests and 14 native Scheme selector
checks passed. Those checks executed zero search codelets. The Scheme fixtures
also compared selected decisions against the original native commentary logic.

After completion, repeating the remote collector's `run` command was tested
with an assertion that would fail on any collection call. It made zero such
calls, and all 376 output-file hashes remained unchanged. Local saved-data
analysis reproduced the remote analysis byte for byte.

To verify this public bundle and recompute every reported population,
checkpoint, novelty, and p50 statistic without Docker or either engine:

```sh
python3 studies/episodic-v1/results/verify.py
```

The bundle contains [48 compact observations](episodes.json), the
[analysis](analysis.json), [protocol](protocol.json), [fingerprints](manifest.json),
[completion receipt](COMPLETE.json), and [checksums](SHA256.json).
The fingerprints identify the unchanged engine baseline
`5e80c69f4d5f119ca0487e650c051c443993aae5` plus the exact development collector
files. They also record CPython 3.14.6, NumPy 2.5.1, SciPy 1.18.1, and Chez
Scheme 9.5.4. The reference ran in Linux/amd64 emulation and the port natively
on macOS/arm64; these smoke timings are not an engine speed benchmark.

No account names, hostnames, local network addresses, Docker image IDs, or
original Metacat source are included. The private execution configuration and
full per-attempt receipts remain under the Git-ignored `output/smoke-01/`.
No full episodic experiment has been launched.
