# Petacat vs Metacat support-v1a answer frequencies (post-lockstep)

Final confirmation step of the lockstep pass (meta-peta-trace-idea.md section 1): do answer frequencies match now that decision traces match?

## Method and provenance
- Reference: Metacat construction observations of study support-v1a, from `studies/support-v1a/data/main.tar.gz` (admitted attempt of each chunk per `complete.json`; fresh memory per run; 100,000-codelet cap). 20,000 runs per problem x 19 problems (380,000 total; 6 duplicate-seed rows per problem in the archive's chunks were dropped). `termination=capped` is counted as `*CAP*`; state strings are answers or `*NONE*`. Validation observations (570,000) were not used.
- Petacat: default shipped configuration (`EngineRunner(MetadataProvider.from_seed_data('seed_data'))`, fresh memory, `init_mcat(..., seed=s)`, `run_mcat(max_steps=100000)`), seeds 5000001..5000200 (200 per problem), classified as in `scripts/compare_to_metacat.py` (answer / `*NONE*` / `*CAP*`; exceptions would be `*ERROR*`, none occurred). "faithful" repeats this with `FAITHFUL_PARAMETERS` (`initial_clamp_fixed_time`). Same seeds in both.
- Statistics: TV distance between the reference distribution and the 200-run empirical distribution. With n=200 and many categories TV is biased upward; the expected TV under the null (200 draws from the reference) is shown in parentheses. p-values are Monte Carlo (4,000 multinomial draws of n=200 from the reference distribution): one for TV, one for Pearson chi-square over all categories (reference probabilities floored at 0.5/20000 so unseen answers are penalised). A classical chi-square on bins with expected count >= 5 (rare answers pooled) is in the JSON (`chi2_pooled*`).
- Regenerate with `scripts/compare_frequencies.py support-v1a` (see `tests/lockstep/README.md`, "Answer-frequency study"); the reference counts it reads from the archive equal the ones tabulated here.

## Result
No problem differs significantly in either mode (smallest p about 0.07, misc1 TV and misc3 chi-square; 0 of 17 testable problems below 0.05; Fisher combination X=36.6 on 34 df). Mean TV 0.041 vs 0.044 expected from sampling noise alone. No novel answer (an answer Metacat never produced) appeared, and no `*ERROR*`.

## abc abd xyz (run4) give-up
Reference `*NONE*`: 9.54% (1,909/20,000). Petacat default and faithful: 5.5% (11/200) each (spec quoted 15% before the pass). One-sided binomial P(<=11 | 9.54%) is 0.027, so Petacat gives up somewhat less often than Metacat, not more; this is borderline and not significant overall. Petacat's rare answers yyz (7.5%) / dyz (7.0% in faithful) are present in Metacat's distribution but at lower frequency.

## Per-problem table (default mode; top-3 answers as percent)
| problem | Metacat | Petacat default | TV (null mean) | p(TV) | p(chi2) | TV faithful | p(chi2) faithful |
|---|---|---|---|---|---|---|---|
| copy1 | c 86.3 / ab 13.7 | c 86.5 / ab 13.5 | 0.002 (0.019) | 1.00 | 1.00 | 0.002 | 1.00 |
| copy2 | d 100.0 / *NONE* 0.0 | d 100.0 | 0.000 (0.000) | 1.00 | 1.00 | 0.000 | 1.00 |
| copy3 | z 100.0 / *NONE* 0.0 | z 100.0 | 0.000 (0.000) | 1.00 | 1.00 | 0.000 | 1.00 |
| copy4 | x 86.7 / zy 13.3 | x 85.5 / zy 14.5 | 0.012 (0.020) | 0.67 | 0.67 | 0.012 | 0.67 |
| copy5 | cc 49.8 / *NONE* 48.4 / ccc 0.6 | cc 53.0 / *NONE* 45.5 / aabb 1.0 | 0.044 (0.037) | 0.32 | 0.10 | 0.044 | 0.10 |
| copy6 | d 86.7 / abc 13.2 / dc 0.1 | d 85.5 / abc 14.5 | 0.013 (0.020) | 0.60 | 0.66 | 0.013 | 0.65 |
| eqe-baaab | baaab 58.2 / qeeeq 26.1 / qbbbq 4.4 | baaab 58.0 / qeeeq 28.0 / abbba 2.5 | 0.038 (0.060) | 0.89 | 0.16 | 0.038 | 0.16 |
| fig5.4-top | qeeq 48.5 / ixxi 27.7 / *NONE* 14.3 | qeeq 55.0 / ixxi 27.0 / *NONE* 11.5 | 0.079 (0.061) | 0.18 | 0.18 | 0.079 | 0.19 |
| fig5.7 | ijll 47.1 / ijkl 35.4 / ijl 8.4 | ijll 51.0 / ijkl 34.5 / ijl 9.0 | 0.049 (0.060) | 0.67 | 0.25 | 0.049 | 0.25 |
| misc1 | jjjrrm 84.8 / mrrjjj 8.7 / jrrmmm 2.7 | jjjrrm 87.5 / mrrjjj 4.5 / jrrjjm 4.0 | 0.055 (0.034) | 0.08 | 0.18 | 0.055 | 0.17 |
| misc2 | ijl 95.3 / ijd 2.3 / ijk 2.0 | ijl 95.5 / ijd 4.5 | 0.025 (0.017) | 0.15 | 0.17 | 0.025 | 0.15 |
| misc3 | kkjjii 32.7 / kkkjjjiii 25.5 / kji 17.4 | kkjjii 35.5 / kkkjjjiii 26.0 / kji 14.0 | 0.090 (0.097) | 0.59 | 0.07 | 0.090 | 0.07 |
| misc4 | b 50.6 / z 36.4 / y 9.8 | b 50.5 / z 35.5 / y 11.0 | 0.011 (0.042) | 0.97 | 0.96 | 0.007 | 0.99 |
| misc5 | gld 25.6 / hlz 23.3 / glz 19.1 | hlz 22.5 / gld 21.5 / glz 19.0 | 0.057 (0.064) | 0.59 | 0.55 | 0.067 | 0.52 |
| run1 | mrrkkk 62.5 / mrrjjk 22.9 / mrrjjjj 4.3 | mrrkkk 62.0 / mrrjjk 22.5 / mrrjjjj 5.5 | 0.048 (0.052) | 0.53 | 0.11 | 0.048 | 0.11 |
| run2 | mrrkkk 68.5 / mrrjjk 21.3 / mrrjkk 3.2 | mrrkkk 64.0 / mrrjjk 26.0 / mrrjjj 4.0 | 0.056 (0.044) | 0.23 | 0.75 | 0.056 | 0.75 |
| run3 | xyu 38.4 / wyz 19.5 / xyz 16.7 | xyu 36.5 / wyz 23.0 / xyz 14.0 | 0.067 (0.063) | 0.38 | 0.69 | 0.062 | 0.74 |
| run4 | xyd 36.6 / wyz 21.6 / xyz 16.7 | xyd 37.5 / wyz 22.5 / xyz 18.0 | 0.045 (0.064) | 0.81 | 0.76 | 0.045 | 0.77 |
| run6 | qeeeq 53.4 / *NONE* 9.5 / baaaq 8.2 | qeeeq 49.5 / qcccb 12.0 / baaaq 10.0 | 0.094 (0.083) | 0.27 | 0.82 | 0.094 | 0.81 |

## Caveats
- N=200 gives only modest power: differences of a few percentage points on a single answer are undetectable; rare answers (<1%) are essentially untested.
- Default and faithful modes differ in a handful of problems only (misc4, misc5, run3, run4 answer mix), so the numbers are nearly the same; the modes were not tested against each other.
- Reference seeds and Petacat seeds are different RNG streams by construction, so only distributions (not trajectories) are comparable here; trace equality is established separately by the lockstep corpus.
- Copy2/copy3 are deterministic (one reference  in 20,000); p-values are trivially 1.
- Reference is the construction phase, which the study froze; the validation phase might shift rare-answer frequencies slightly. 19 problems x 2 modes of tests with no multiplicity correction; none is significant anyway.
