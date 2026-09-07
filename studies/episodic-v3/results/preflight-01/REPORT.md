# episodic-v3-preflight

Per-episode Good-Turing stopping is heuristic. Validation is fixed-size and conditional on answered complete episodes, with 95% simultaneous bounds over the preregistered 38 populations in the main study. Capped problems retain descriptive reference/port frequencies without a coverage guarantee. No port equivalence or defect-detection power is claimed.

| Problem | Construction episodes | Stop | A freeze | B freeze | Validation episodes | Port episodes | Coverage qualified |
| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| misc4 | 2 | both-thresholds | 2 | 2 | 2 | 2 | False |
| run4 | 3 | both-thresholds | 3 | 3 | 2 | 2 | False |
| fig5.7 | 3 | both-thresholds | 2 | 3 | 2 | 2 | False |
| copy5 | 2 | both-thresholds | 2 | 2 | 2 | 2 | False |

## Validation Strength

Bounds are conditional on answered, complete episodes. Errors and entirely answerless episodes are retained separately.
A skipped validation has no statistical coverage guarantee; it does not make the retained observations invalid.

| Problem | Definition | Status | Answered N | Outside occurrences | Adjusted upper bound |
| --- | --- | --- | ---: | ---: | ---: |
| misc4 | best_a | coverage-target-not-met | 2 | 0 | 0.9209430584957905 |
| misc4 | best_b | coverage-target-not-met | 2 | 0 | 0.9209430584957905 |
| run4 | best_a | coverage-target-not-met | 2 | 0 | 0.9209430584957905 |
| run4 | best_b | coverage-target-not-met | 2 | 0 | 0.9209430584957905 |
| fig5.7 | best_a | coverage-target-not-met | 2 | 1 | 0.9968701018688444 |
| fig5.7 | best_b | coverage-target-not-met | 2 | 2 | 1.0 |
| copy5 | best_a | coverage-target-not-met | 2 | 0 | 0.9209430584957905 |
| copy5 | best_b | coverage-target-not-met | 2 | 0 | 0.9209430584957905 |

All reference/port frequency tables are descriptive. Consult frequencies.csv and analysis.json; no frequency p-values, equivalence claims, or automatic bug verdicts are assigned.
Frozen supports are recorded separately from the frequencies of all construction observations.
