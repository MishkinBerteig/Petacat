# episodic-v2-answer-discovery-pilot

Separate individual-answer populations. N counts answered complete episodes; failures and answerless episodes are reported separately. f1/N is a heuristic conditional missing-mass estimate, not a confidence bound. Pilot collection never stops on a threshold crossing.

Complete: True. Episodes: 4000. Inner runs: 31999.

| Problem | Definition | Episodes | N answers | f1 | f1/N | Distinct answers |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| misc4 | best_a | 100 | 100 | 0 | 0.0 | 2 |
| misc4 | best_a | 200 | 200 | 0 | 0.0 | 2 |
| misc4 | best_a | 300 | 300 | 0 | 0.0 | 2 |
| misc4 | best_a | 400 | 400 | 0 | 0.0 | 2 |
| misc4 | best_a | 500 | 500 | 0 | 0.0 | 2 |
| misc4 | best_a | 600 | 600 | 0 | 0.0 | 2 |
| misc4 | best_a | 700 | 700 | 0 | 0.0 | 2 |
| misc4 | best_a | 800 | 800 | 1 | 0.00125 | 3 |
| misc4 | best_a | 900 | 900 | 1 | 0.0011111111111111111 | 3 |
| misc4 | best_a | 1000 | 1000 | 1 | 0.001 | 3 |
| misc4 | best_b | 100 | 100 | 0 | 0.0 | 1 |
| misc4 | best_b | 200 | 200 | 0 | 0.0 | 1 |
| misc4 | best_b | 300 | 300 | 1 | 0.0033333333333333335 | 2 |
| misc4 | best_b | 400 | 400 | 0 | 0.0 | 2 |
| misc4 | best_b | 500 | 500 | 0 | 0.0 | 3 |
| misc4 | best_b | 600 | 600 | 0 | 0.0 | 3 |
| misc4 | best_b | 700 | 700 | 0 | 0.0 | 3 |
| misc4 | best_b | 800 | 800 | 0 | 0.0 | 3 |
| misc4 | best_b | 900 | 900 | 0 | 0.0 | 3 |
| misc4 | best_b | 1000 | 1000 | 0 | 0.0 | 3 |
| run4 | best_a | 100 | 99 | 0 | 0.0 | 2 |
| run4 | best_a | 200 | 199 | 0 | 0.0 | 2 |
| run4 | best_a | 300 | 299 | 1 | 0.0033444816053511705 | 3 |
| run4 | best_a | 400 | 399 | 3 | 0.007518796992481203 | 5 |
| run4 | best_a | 500 | 499 | 3 | 0.006012024048096192 | 5 |
| run4 | best_a | 600 | 599 | 3 | 0.005008347245409015 | 5 |
| run4 | best_a | 700 | 699 | 3 | 0.004291845493562232 | 5 |
| run4 | best_a | 800 | 799 | 2 | 0.0025031289111389237 | 5 |
| run4 | best_a | 900 | 899 | 1 | 0.0011123470522803114 | 5 |
| run4 | best_a | 1000 | 999 | 1 | 0.001001001001001001 | 5 |
| run4 | best_b | 100 | 99 | 0 | 0.0 | 4 |
| run4 | best_b | 200 | 199 | 0 | 0.0 | 4 |
| run4 | best_b | 300 | 299 | 1 | 0.0033444816053511705 | 5 |
| run4 | best_b | 400 | 399 | 0 | 0.0 | 5 |
| run4 | best_b | 500 | 499 | 0 | 0.0 | 5 |
| run4 | best_b | 600 | 599 | 0 | 0.0 | 5 |
| run4 | best_b | 700 | 699 | 0 | 0.0 | 5 |
| run4 | best_b | 800 | 799 | 0 | 0.0 | 5 |
| run4 | best_b | 900 | 899 | 0 | 0.0 | 5 |
| run4 | best_b | 1000 | 999 | 0 | 0.0 | 5 |
| run1 | best_a | 100 | 100 | 0 | 0.0 | 4 |
| run1 | best_a | 200 | 200 | 1 | 0.005 | 5 |
| run1 | best_a | 300 | 300 | 1 | 0.0033333333333333335 | 5 |
| run1 | best_a | 400 | 400 | 1 | 0.0025 | 5 |
| run1 | best_a | 500 | 500 | 1 | 0.002 | 5 |
| run1 | best_a | 600 | 600 | 1 | 0.0016666666666666668 | 5 |
| run1 | best_a | 700 | 700 | 1 | 0.0014285714285714286 | 5 |
| run1 | best_a | 800 | 800 | 0 | 0.0 | 5 |
| run1 | best_a | 900 | 900 | 0 | 0.0 | 5 |
| run1 | best_a | 1000 | 1000 | 0 | 0.0 | 5 |
| run1 | best_b | 100 | 100 | 0 | 0.0 | 4 |
| run1 | best_b | 200 | 200 | 1 | 0.005 | 5 |
| run1 | best_b | 300 | 300 | 0 | 0.0 | 5 |
| run1 | best_b | 400 | 400 | 0 | 0.0 | 5 |
| run1 | best_b | 500 | 500 | 0 | 0.0 | 5 |
| run1 | best_b | 600 | 600 | 0 | 0.0 | 5 |
| run1 | best_b | 700 | 700 | 1 | 0.0014285714285714286 | 6 |
| run1 | best_b | 800 | 800 | 1 | 0.00125 | 6 |
| run1 | best_b | 900 | 900 | 1 | 0.0011111111111111111 | 6 |
| run1 | best_b | 1000 | 1000 | 1 | 0.001 | 6 |
| fig5.4-top | best_a | 100 | 100 | 0 | 0.0 | 2 |
| fig5.4-top | best_a | 200 | 200 | 1 | 0.005 | 3 |
| fig5.4-top | best_a | 300 | 300 | 2 | 0.006666666666666667 | 4 |
| fig5.4-top | best_a | 400 | 400 | 3 | 0.0075 | 5 |
| fig5.4-top | best_a | 500 | 500 | 2 | 0.004 | 5 |
| fig5.4-top | best_a | 600 | 600 | 2 | 0.0033333333333333335 | 5 |
| fig5.4-top | best_a | 700 | 700 | 2 | 0.002857142857142857 | 5 |
| fig5.4-top | best_a | 800 | 800 | 2 | 0.0025 | 5 |
| fig5.4-top | best_a | 900 | 900 | 2 | 0.0022222222222222222 | 5 |
| fig5.4-top | best_a | 1000 | 1000 | 2 | 0.002 | 5 |
| fig5.4-top | best_b | 100 | 100 | 3 | 0.03 | 6 |
| fig5.4-top | best_b | 200 | 200 | 4 | 0.02 | 9 |
| fig5.4-top | best_b | 300 | 300 | 9 | 0.03 | 14 |
| fig5.4-top | best_b | 400 | 400 | 12 | 0.03 | 17 |
| fig5.4-top | best_b | 500 | 500 | 13 | 0.026 | 18 |
| fig5.4-top | best_b | 600 | 600 | 13 | 0.021666666666666667 | 18 |
| fig5.4-top | best_b | 700 | 700 | 13 | 0.018571428571428572 | 19 |
| fig5.4-top | best_b | 800 | 800 | 13 | 0.01625 | 19 |
| fig5.4-top | best_b | 900 | 900 | 13 | 0.014444444444444444 | 21 |
| fig5.4-top | best_b | 1000 | 1000 | 13 | 0.013 | 22 |

The target is 0.0001; with N <= 1000 any nonzero f1/N is at least 0.001.
A zero value or early target crossing is not evidence that discovery probability is zero or below 0.0001.
Compare actual inner-run costs (eight per full episode), not episode counts alone.
