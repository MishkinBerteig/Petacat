# episodic-v3-capped-frozen-oracles

Per-episode Good-Turing stopping is heuristic. Validation is fixed-size and conditional on answered complete episodes, with 95% simultaneous bounds over the preregistered 38 populations in the main study. Capped problems retain descriptive reference/port frequencies without a coverage guarantee. No port equivalence or defect-detection power is claimed.

| Problem | Construction episodes | Stop | A freeze | B freeze | Validation episodes | Port episodes | Coverage qualified |
| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| misc4 | 2000 | budget-cap | not met | 1000 | 0 | 100 | False |
| fig5.7 | 8 | both-thresholds | 8 | 6 | 1000 | 100 | False |
| misc3 | 11 | both-thresholds | 11 | 7 | 1000 | 100 | False |
| misc5 | 2 | both-thresholds | 2 | 2 | 1000 | 100 | False |
| misc2 | 2 | both-thresholds | 2 | 2 | 1000 | 100 | False |
| run1 | 2000 | budget-cap | 1000 | not met | 0 | 100 | False |
| run4 | 2000 | budget-cap | not met | 1000 | 0 | 100 | False |
| misc1 | 14 | both-thresholds | 5 | 14 | 1000 | 100 | False |
| fig5.4-top | 2000 | budget-cap | not met | not met | 0 | 100 | False |
| eqe-baaab | 2000 | budget-cap | 2 | not met | 0 | 100 | False |
| run6 | 21 | both-thresholds | 21 | 2 | 1000 | 100 | False |
| run3 | 2 | both-thresholds | 2 | 2 | 1000 | 100 | False |
| run2 | 2 | both-thresholds | 2 | 2 | 1000 | 100 | False |
| copy1 | 2 | both-thresholds | 2 | 2 | 1000 | 100 | True |
| copy2 | 2 | both-thresholds | 2 | 2 | 1000 | 100 | True |
| copy3 | 2 | both-thresholds | 2 | 2 | 1000 | 100 | True |
| copy4 | 2 | both-thresholds | 2 | 2 | 1000 | 100 | False |
| copy5 | 2 | both-thresholds | 2 | 2 | 1000 | 100 | False |
| copy6 | 2 | both-thresholds | 2 | 2 | 1000 | 100 | False |

## Validation Strength

Bounds are conditional on answered, complete episodes. Errors and entirely answerless episodes are retained separately.
A skipped validation has no statistical coverage guarantee; it does not make the retained observations invalid.

| Problem | Definition | Status | Answered N | Outside occurrences | Adjusted upper bound |
| --- | --- | --- | ---: | ---: | ---: |
| misc4 | best_a | skipped-threshold-not-met | not collected | not collected | None |
| misc4 | best_b | skipped-threshold-not-met | not collected | not collected | None |
| fig5.7 | best_a | coverage-target-not-met | 1000 | 37 | 0.05858260269842819 |
| fig5.7 | best_b | coverage-target-not-met | 1000 | 111 | 0.1438811764992598 |
| misc3 | best_a | qualified | 1000 | 0 | 0.006611366541343647 |
| misc3 | best_b | coverage-target-not-met | 1000 | 99 | 0.13050070397763958 |
| misc5 | best_a | coverage-target-not-met | 1000 | 480 | 0.5280258141350074 |
| misc5 | best_b | coverage-target-not-met | 1000 | 591 | 0.6375585303428906 |
| misc2 | best_a | coverage-target-not-met | 1000 | 6 | 0.01755960112870142 |
| misc2 | best_b | coverage-target-not-met | 1000 | 63 | 0.08949280756974776 |
| run1 | best_a | skipped-threshold-not-met | not collected | not collected | None |
| run1 | best_b | skipped-threshold-not-met | not collected | not collected | None |
| run4 | best_a | skipped-threshold-not-met | not collected | not collected | None |
| run4 | best_b | skipped-threshold-not-met | not collected | not collected | None |
| misc1 | best_a | coverage-target-not-met | 1000 | 589 | 0.6356060526442928 |
| misc1 | best_b | coverage-target-not-met | 1000 | 193 | 0.2329516700809685 |
| fig5.4-top | best_a | skipped-threshold-not-met | not collected | not collected | None |
| fig5.4-top | best_b | skipped-threshold-not-met | not collected | not collected | None |
| eqe-baaab | best_a | skipped-threshold-not-met | not collected | not collected | None |
| eqe-baaab | best_b | skipped-threshold-not-met | not collected | not collected | None |
| run6 | best_a | coverage-target-not-met | 1000 | 101 | 0.13273904612251824 |
| run6 | best_b | coverage-target-not-met | 1000 | 425 | 0.4728824989817937 |
| run3 | best_a | coverage-target-not-met | 1000 | 377 | 0.4242730691799894 |
| run3 | best_b | coverage-target-not-met | 1000 | 418 | 0.4658222749212918 |
| run2 | best_a | coverage-target-not-met | 1000 | 251 | 0.29425728876612556 |
| run2 | best_b | coverage-target-not-met | 1000 | 242 | 0.28481483138506947 |
| copy1 | best_a | qualified | 1000 | 0 | 0.006611366541343647 |
| copy1 | best_b | qualified | 1000 | 0 | 0.006611366541343647 |
| copy2 | best_a | qualified | 1000 | 0 | 0.006611366541343647 |
| copy2 | best_b | qualified | 1000 | 0 | 0.006611366541343647 |
| copy3 | best_a | qualified | 1000 | 0 | 0.006611366541343647 |
| copy3 | best_b | qualified | 1000 | 0 | 0.006611366541343647 |
| copy4 | best_a | coverage-target-not-met | 1000 | 2 | 0.01085195482779492 |
| copy4 | best_b | qualified | 1000 | 0 | 0.006611366541343647 |
| copy5 | best_a | coverage-target-not-met | 995 | 36 | 0.05764327128041122 |
| copy5 | best_b | coverage-target-not-met | 995 | 29 | 0.048922729579636934 |
| copy6 | best_a | coverage-target-not-met | 1000 | 3 | 0.012651646128276905 |
| copy6 | best_b | coverage-target-not-met | 1000 | 2 | 0.01085195482779492 |

All reference/port frequency tables are descriptive. Consult frequencies.csv and analysis.json; no frequency p-values, equivalence claims, or automatic bug verdicts are assigned.
Frozen supports are recorded separately from the frequencies of all construction observations.
