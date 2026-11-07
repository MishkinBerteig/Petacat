# Multi-threaded Metacat Mode against single-threaded: answer frequencies

Measured on 2026-11-06 at commit `b3d2209`, on the final patched Metacat. The recordings and scripts are not in the repository.

## What was compared

For each of 8 problems, the answers over 1,000 runs (seeds 1 to 1000, a cap of 100,000 codelets, a fresh Episodic Memory per run, numeric backend `numpy`) in each of these modes:

| Name in the tables | What ran |
|---|---|
| 1 worker (reference) | Metacat Mode's normal single-threaded run, seeds 1-1000 |
| 1 worker, other seeds (control) | the same single-threaded run on seeds 1001-2000. It is the same engine, so any distance from the reference is pure sampling luck. This is the yardstick for everything else |
| speculative 2, speculative 8 | the exact speculative executor with 2 and with 8 workers (what a run with `workers` 2 or 8 does), seeds 1-1000 |
| free-running 8 (run 1, run 2) | the free-running engine with 8 threads on `PYTHON_GIL=0` `.venv-ft`, seeds 1-1000. Run twice: run 1 while my own replays were using the machine, run 2 with nothing of mine running |
| Metacat (Scheme) | patched Metacat (`tests/lockstep/metacat/record_frequencies.py`, the harness refuses anything but the patched build; it reported `fixes`), seeds 1-1000 |

The machine is an Apple M5 Max with 18 cores (6 performance, 12 efficiency) and 128 GB. Other agents' jobs (a Docker e2e run, a Virtualization process) were also using it throughout; the load average was about 5 to 8 before and after the free-running runs.

The Swarm runs each seed serially, so it is not in the statistics; its identity with one worker is checked below.

## The 8 problems and why

I surveyed 12 candidate golden problems with 100 patched-Metacat runs each (`freq/survey/`) and chose by what the survey showed.

| Problem (initial, modified, target) | Why |
|---|---|
| abc abd ijk | one dominant answer: `ijl` in 95% of runs, short runs (median about 450 codelets) |
| abc cba mrrjjj | one dominant answer: `jjjrrm` about 80-85%, with a second answer near 9% |
| abc abd xyz | a wide spread: `xyd`, `wyz`, `xyz`, `dyz`, `yyz`, plus about 9% give-ups |
| abc abd glz | the widest spread: five answers between 7% and 27%, and a long tail of runs (some past 25,000 codelets) |
| rst rsu xyz | frequent give-ups (about 11%) alongside a wide spread |
| aabb cc aabb | give-ups in about half of all runs, and long runs (median about 4,300 codelets) |
| abc aabbcc kkjjii | the long runs: 11% reach the 100,000-codelet cap, mean about 20,000 codelets |
| eeqee qeeq xxixx | two main answers plus about 15% give-ups, long runs (median about 3,500) |

## How to read the tables

- **TV (total-variation distance)** is half the sum of the differences in answer frequency. 0 means identical frequencies; 0.05 means 5% of the runs would have to give a different answer to make the two tables equal.
- **Noise band** is what luck alone gives. For each row I simulated 20,000 pairs of samples of the same sizes from one single distribution (the two samples pooled) and report the average TV and the TV that 95% of those pairs stay under. The control row is the real, measured version of the same thing.
- **chi-square and p** are the two-sample chi-square test of "these two samples have the same answer frequencies" (`scripts/compare_frequencies.py`'s functions, imported unchanged; rare answers are pooled so every bin expects at least 5). A small p says the difference is hard to put down to luck.
- **p (Holm)** is p after the Holm step-down correction for multiple comparisons. The family is every row in the first table that is compared with the reference: 8 problems x 6 samples (Metacat, control, speculative 2, speculative 8, free-running run 1, run 2) = 48 tests. With 48 tests, a few raw p-values below 0.05 are expected by luck alone, so the Holm column is the one to read.
- **Give-up %** is runs where the program stopped with no answer (`*NONE*`); **cap %** is runs that hit the 100,000-codelet cap (`*CAP*`).

## Results

### Summary: distance from the one-worker reference

TV = total-variation distance (0 = same frequencies, 1 = nothing in common). Noise band = what two independent 1,000-run samples from one and the same distribution give by luck alone (simulated: mean, and the value 95% of such pairs stay under). p(Holm) = chi-square p-value after the Holm correction over all 48 comparisons in this table.

| Problem | Mode | TV | noise band mean / 95% | chi-square (df) | p | p (Holm) | give-up % | cap % | median codelets | mean codelets |
|---|---|---|---|---|---|---|---|---|---|---|
| abc abd ijk | Metacat (Scheme) | 0.007 | 0.011 / 0.022 | 1.4 (3) | 0.709 | 1.000 | 0.0 | 0.0 | 440 | 533 |
| abc abd ijk | 1 worker (reference) | - | - | - | - | - | 0.1 | 0.0 | 439 | 510 |
| abc abd ijk | 1 worker, other seeds (control) | 0.004 | 0.011 / 0.021 | 0.9 (3) | 0.834 | 1.000 | 0.3 | 0.0 | 442 | 570 |
| abc abd ijk | speculative 2 | 0.010 | 0.010 / 0.020 | 1.0 (2) | 0.603 | 1.000 | 0.1 | 0.0 | 438 | 493 |
| abc abd ijk | speculative 8 | 0.010 | 0.010 / 0.020 | 1.0 (2) | 0.603 | 1.000 | 0.1 | 0.0 | 438 | 493 |
| abc abd ijk | free-running 8 (run 1) | 0.007 | 0.012 / 0.022 | 0.6 (3) | 0.895 | 1.000 | 0.0 | 0.0 | 552 | 672 |
| abc abd ijk | free-running 8 (run 2) | 0.009 | 0.011 / 0.021 | 1.6 (2) | 0.460 | 1.000 | 0.0 | 0.0 | 561 | 677 |
| abc cba mrrjjj | Metacat (Scheme) | 0.019 | 0.022 / 0.038 | 4.5 (4) | 0.340 | 1.000 | 0.0 | 0.0 | 1071 | 1179 |
| abc cba mrrjjj | 1 worker (reference) | - | - | - | - | - | 0.0 | 0.0 | 1068 | 1212 |
| abc cba mrrjjj | 1 worker, other seeds (control) | 0.014 | 0.021 / 0.037 | 3.5 (4) | 0.477 | 1.000 | 0.0 | 0.0 | 1041 | 1178 |
| abc cba mrrjjj | speculative 2 | 0.017 | 0.020 / 0.036 | 3.8 (4) | 0.434 | 1.000 | 0.0 | 0.0 | 1082 | 1222 |
| abc cba mrrjjj | speculative 8 | 0.017 | 0.020 / 0.036 | 3.8 (4) | 0.434 | 1.000 | 0.0 | 0.0 | 1082 | 1222 |
| abc cba mrrjjj | free-running 8 (run 1) | 0.018 | 0.021 / 0.037 | 1.1 (4) | 0.891 | 1.000 | 0.0 | 0.0 | 1208 | 1394 |
| abc cba mrrjjj | free-running 8 (run 2) | 0.030 | 0.022 / 0.038 | 7.2 (5) | 0.204 | 1.000 | 0.0 | 0.0 | 1206 | 1356 |
| abc abd xyz | Metacat (Scheme) | 0.054 | 0.039 / 0.063 | 9.5 (6) | 0.150 | 1.000 | 7.7 | 0.0 | 1804 | 2043 |
| abc abd xyz | 1 worker (reference) | - | - | - | - | - | 9.0 | 0.0 | 1774 | 2012 |
| abc abd xyz | 1 worker, other seeds (control) | 0.031 | 0.039 / 0.063 | 3.8 (6) | 0.709 | 1.000 | 10.3 | 0.0 | 1825 | 2089 |
| abc abd xyz | speculative 2 | 0.036 | 0.039 / 0.063 | 3.3 (6) | 0.765 | 1.000 | 9.3 | 0.0 | 1824 | 2194 |
| abc abd xyz | speculative 8 | 0.036 | 0.039 / 0.063 | 3.3 (6) | 0.765 | 1.000 | 9.3 | 0.0 | 1824 | 2194 |
| abc abd xyz | free-running 8 (run 1) | 0.095 | 0.040 / 0.063 | 28.0 (6) | 0.000 | 0.004 | 13.2 | 0.0 | 2284 | 2662 |
| abc abd xyz | free-running 8 (run 2) | 0.100 | 0.039 / 0.063 | 29.0 (6) | 0.000 | 0.003 | 13.9 | 0.0 | 2300 | 2570 |
| abc abd glz | Metacat (Scheme) | 0.034 | 0.040 / 0.064 | 6.0 (6) | 0.427 | 1.000 | 5.9 | 0.0 | 1596 | 2200 |
| abc abd glz | 1 worker (reference) | - | - | - | - | - | 4.0 | 0.0 | 1596 | 2370 |
| abc abd glz | 1 worker, other seeds (control) | 0.024 | 0.040 / 0.064 | 3.2 (6) | 0.788 | 1.000 | 5.5 | 0.0 | 1632 | 2641 |
| abc abd glz | speculative 2 | 0.037 | 0.040 / 0.063 | 5.6 (6) | 0.470 | 1.000 | 4.6 | 0.0 | 1605 | 2218 |
| abc abd glz | speculative 8 | 0.037 | 0.040 / 0.063 | 5.6 (6) | 0.470 | 1.000 | 4.6 | 0.0 | 1605 | 2218 |
| abc abd glz | free-running 8 (run 1) | 0.085 | 0.041 / 0.065 | 33.1 (6) | 0.000 | 0.000 | 8.8 | 0.2 | 2063 | 3518 |
| abc abd glz | free-running 8 (run 2) | 0.068 | 0.041 / 0.064 | 21.9 (6) | 0.001 | 0.054 | 8.3 | 0.0 | 2043 | 3100 |
| rst rsu xyz | Metacat (Scheme) | 0.066 | 0.040 / 0.063 | 15.5 (6) | 0.016 | 0.643 | 10.4 | 0.0 | 1736 | 2144 |
| rst rsu xyz | 1 worker (reference) | - | - | - | - | - | 11.0 | 0.0 | 1750 | 2135 |
| rst rsu xyz | 1 worker, other seeds (control) | 0.052 | 0.040 / 0.063 | 8.4 (6) | 0.213 | 1.000 | 10.7 | 0.0 | 1784 | 2116 |
| rst rsu xyz | speculative 2 | 0.024 | 0.040 / 0.063 | 1.9 (6) | 0.932 | 1.000 | 11.5 | 0.0 | 1821 | 2089 |
| rst rsu xyz | speculative 8 | 0.024 | 0.040 / 0.063 | 1.9 (6) | 0.932 | 1.000 | 11.5 | 0.0 | 1821 | 2089 |
| rst rsu xyz | free-running 8 (run 1) | 0.069 | 0.039 / 0.062 | 16.1 (6) | 0.013 | 0.529 | 15.8 | 0.0 | 2333 | 2653 |
| rst rsu xyz | free-running 8 (run 2) | 0.094 | 0.039 / 0.062 | 21.9 (6) | 0.001 | 0.054 | 15.3 | 0.0 | 2332 | 2664 |
| aabb cc aabb | Metacat (Scheme) | 0.006 | 0.023 / 0.048 | 1.1 (4) | 0.887 | 1.000 | 49.1 | 0.5 | 4424 | 5620 |
| aabb cc aabb | 1 worker (reference) | - | - | - | - | - | 49.6 | 0.6 | 4330 | 5729 |
| aabb cc aabb | 1 worker, other seeds (control) | 0.010 | 0.023 / 0.048 | 3.0 (4) | 0.551 | 1.000 | 48.8 | 0.5 | 4255 | 5516 |
| aabb cc aabb | speculative 2 | 0.011 | 0.024 / 0.049 | 4.3 (4) | 0.366 | 1.000 | 49.1 | 0.6 | 4347 | 5816 |
| aabb cc aabb | speculative 8 | 0.011 | 0.024 / 0.049 | 4.3 (4) | 0.366 | 1.000 | 49.1 | 0.6 | 4347 | 5816 |
| aabb cc aabb | free-running 8 (run 1) | 0.069 | 0.023 / 0.048 | 9.8 (4) | 0.044 | 1.000 | 55.8 | 0.6 | 4446 | 5688 |
| aabb cc aabb | free-running 8 (run 2) | 0.083 | 0.023 / 0.048 | 14.8 (4) | 0.005 | 0.215 | 57.1 | 0.5 | 4384 | 5717 |
| abc aabbcc kkjjii | Metacat (Scheme) | 0.049 | 0.061 / 0.084 | 14.4 (13) | 0.343 | 1.000 | 0.5 | 11.0 | 3036 | 20807 |
| abc aabbcc kkjjii | 1 worker (reference) | - | - | - | - | - | 0.6 | 11.1 | 3024 | 20807 |
| abc aabbcc kkjjii | 1 worker, other seeds (control) | 0.050 | 0.060 / 0.083 | 11.4 (11) | 0.413 | 1.000 | 0.5 | 11.1 | 3604 | 21592 |
| abc aabbcc kkjjii | speculative 2 | 0.048 | 0.059 / 0.083 | 7.6 (9) | 0.571 | 1.000 | 0.4 | 10.3 | 3076 | 20086 |
| abc aabbcc kkjjii | speculative 8 | 0.048 | 0.059 / 0.083 | 7.6 (9) | 0.571 | 1.000 | 0.4 | 10.3 | 3076 | 20086 |
| abc aabbcc kkjjii | free-running 8 (run 1) | 0.052 | 0.061 / 0.084 | 5.6 (12) | 0.934 | 1.000 | 0.8 | 13.0 | 3751 | 22241 |
| abc aabbcc kkjjii | free-running 8 (run 2) | 0.062 | 0.060 / 0.084 | 13.5 (10) | 0.197 | 1.000 | 0.6 | 13.7 | 3793 | 21810 |
| eeqee qeeq xxixx | Metacat (Scheme) | 0.023 | 0.038 / 0.062 | 4.3 (6) | 0.639 | 1.000 | 14.7 | 0.0 | 3523 | 4009 |
| eeqee qeeq xxixx | 1 worker (reference) | - | - | - | - | - | 15.1 | 0.0 | 3530 | 4115 |
| eeqee qeeq xxixx | 1 worker, other seeds (control) | 0.024 | 0.038 / 0.061 | 1.5 (5) | 0.914 | 1.000 | 16.2 | 0.0 | 3484 | 3966 |
| eeqee qeeq xxixx | speculative 2 | 0.038 | 0.039 / 0.063 | 9.6 (6) | 0.142 | 1.000 | 13.4 | 0.0 | 3482 | 3995 |
| eeqee qeeq xxixx | speculative 8 | 0.038 | 0.039 / 0.063 | 9.6 (6) | 0.142 | 1.000 | 13.4 | 0.0 | 3482 | 3995 |
| eeqee qeeq xxixx | free-running 8 (run 1) | 0.122 | 0.038 / 0.061 | 39.1 (5) | 0.000 | 0.000 | 26.0 | 0.0 | 4112 | 4483 |
| eeqee qeeq xxixx | free-running 8 (run 2) | 0.113 | 0.037 / 0.061 | 34.5 (6) | 0.000 | 0.000 | 24.8 | 0.0 | 4123 | 4417 |

### Answers given in at least 5% of runs, by problem and mode (percent of runs)

**abc abd ijk**

| Answer | Metacat (Scheme) | 1 worker (reference) | 1 worker, other seeds (control) | speculative 2 | speculative 8 | free-running 8 (run 1) | free-running 8 (run 2) |
|---|---|---|---|---|---|---|---|
| ijl | 94.7 | 95.1 | 95.0 | 96.0 | 96.0 | 94.6 | 95.3 |

**abc cba mrrjjj**

| Answer | Metacat (Scheme) | 1 worker (reference) | 1 worker, other seeds (control) | speculative 2 | speculative 8 | free-running 8 (run 1) | free-running 8 (run 2) |
|---|---|---|---|---|---|---|---|
| jjjrrm | 84.5 | 85.0 | 85.0 | 86.2 | 86.2 | 83.6 | 83.0 |
| mrrjjj | 9.1 | 8.2 | 8.6 | 8.4 | 8.4 | 9.5 | 7.4 |

**abc abd xyz**

| Answer | Metacat (Scheme) | 1 worker (reference) | 1 worker, other seeds (control) | speculative 2 | speculative 8 | free-running 8 (run 1) | free-running 8 (run 2) |
|---|---|---|---|---|---|---|---|
| xyd | 37.0 | 36.2 | 35.9 | 37.9 | 37.9 | 40.1 | 40.3 |
| wyz | 21.8 | 24.6 | 22.6 | 22.0 | 22.0 | 16.9 | 17.2 |
| xyz | 19.3 | 17.0 | 16.3 | 16.1 | 16.1 | 15.5 | 15.2 |
| *NONE* | 7.7 | 9.0 | 10.3 | 9.3 | 9.3 | 13.2 | 13.9 |
| dyz | 4.5 | 5.8 | 6.3 | 7.0 | 7.0 | 5.7 | 5.0 |
| yyz | 7.4 | 5.3 | 5.6 | 5.6 | 5.6 | 5.2 | 5.4 |

**abc abd glz**

| Answer | Metacat (Scheme) | 1 worker (reference) | 1 worker, other seeds (control) | speculative 2 | speculative 8 | free-running 8 (run 1) | free-running 8 (run 2) |
|---|---|---|---|---|---|---|---|
| gld | 26.5 | 26.3 | 26.1 | 27.6 | 27.6 | 27.2 | 27.1 |
| hlz | 22.6 | 23.7 | 23.0 | 22.4 | 22.4 | 20.7 | 20.3 |
| glz | 18.5 | 19.0 | 19.7 | 17.6 | 17.6 | 20.1 | 18.5 |
| flz | 15.3 | 17.1 | 16.1 | 18.3 | 18.3 | 12.6 | 14.2 |
| dlz | 9.2 | 7.9 | 7.4 | 8.5 | 8.5 | 6.9 | 9.3 |
| *NONE* | 5.9 | 4.0 | 5.5 | 4.6 | 4.6 | 8.8 | 8.3 |

**rst rsu xyz**

| Answer | Metacat (Scheme) | 1 worker (reference) | 1 worker, other seeds (control) | speculative 2 | speculative 8 | free-running 8 (run 1) | free-running 8 (run 2) |
|---|---|---|---|---|---|---|---|
| xyu | 37.4 | 39.6 | 36.4 | 38.9 | 38.9 | 41.2 | 43.5 |
| wyz | 21.9 | 17.0 | 20.5 | 18.4 | 18.4 | 14.9 | 12.9 |
| xyz | 18.3 | 17.5 | 16.1 | 16.5 | 16.5 | 15.1 | 14.3 |
| *NONE* | 10.4 | 11.0 | 10.7 | 11.5 | 11.5 | 15.8 | 15.3 |
| uyz | 4.7 | 6.5 | 6.2 | 5.8 | 5.8 | 5.9 | 5.3 |
| yyz | 3.8 | 5.8 | 6.1 | 5.8 | 5.8 | 4.0 | 4.9 |

**aabb cc aabb**

| Answer | Metacat (Scheme) | 1 worker (reference) | 1 worker, other seeds (control) | speculative 2 | speculative 8 | free-running 8 (run 1) | free-running 8 (run 2) |
|---|---|---|---|---|---|---|---|
| *NONE* | 49.1 | 49.6 | 48.8 | 49.1 | 49.1 | 55.8 | 57.1 |
| cc | 48.9 | 48.8 | 49.0 | 48.2 | 48.2 | 42.1 | 40.6 |

**abc aabbcc kkjjii**

| Answer | Metacat (Scheme) | 1 worker (reference) | 1 worker, other seeds (control) | speculative 2 | speculative 8 | free-running 8 (run 1) | free-running 8 (run 2) |
|---|---|---|---|---|---|---|---|
| kkjjii | 30.0 | 31.5 | 31.7 | 31.6 | 31.6 | 31.8 | 31.4 |
| kkkjjjiii | 26.6 | 25.8 | 28.3 | 27.2 | 27.2 | 24.8 | 26.8 |
| kji | 18.1 | 17.8 | 16.5 | 19.6 | 19.6 | 18.3 | 18.3 |
| *CAP* | 11.0 | 11.1 | 11.1 | 10.3 | 10.3 | 13.0 | 13.7 |

**eeqee qeeq xxixx**

| Answer | Metacat (Scheme) | 1 worker (reference) | 1 worker, other seeds (control) | speculative 2 | speculative 8 | free-running 8 (run 1) | free-running 8 (run 2) |
|---|---|---|---|---|---|---|---|
| qeeq | 47.1 | 47.6 | 47.7 | 47.5 | 47.5 | 43.5 | 42.6 |
| ixxi | 28.6 | 29.3 | 29.1 | 28.2 | 28.2 | 23.5 | 24.9 |
| *NONE* | 14.7 | 15.1 | 16.2 | 13.4 | 13.4 | 26.0 | 24.8 |

### Is a mode further from the reference than the control is?

Mechanical reading, not a judgement of 'low': a mode 'exceeds the control' on a problem when its TV is larger than the control's TV; 'exceeds the noise band' when its TV is above the 95% value of the band; 'significant' when p (Holm) < 0.05.

| Mode | problems where TV > control TV | TV above noise band 95% | significant after Holm | mean TV over the 8 problems |
|---|---|---|---|---|
| Metacat (Scheme) | 5 of 8 | 1 of 8 | 0 of 8 | 0.0323 |
| 1 worker, other seeds (control) | - of 8 | 0 of 8 | 0 of 8 | 0.0261 |
| speculative 2 | 6 of 8 | 0 of 8 | 0 of 8 | 0.0276 |
| speculative 8 | 6 of 8 | 0 of 8 | 0 of 8 | 0.0276 |
| free-running 8 (run 1) | 8 of 8 | 5 of 8 | 3 of 8 | 0.0646 |
| free-running 8 (run 2) | 8 of 8 | 5 of 8 | 2 of 8 | 0.0699 |

### The same distances measured from patched Metacat instead of the reference

TV and unadjusted chi-square p against the Metacat sample (seeds 1-1000). These 8 x 6 comparisons are a second family and are not in the Holm family above. 'free-running 8 run 1 vs run 2' compares the two free-running samples with each other.

| Problem | 1 worker (ref) | control | spec 2 | spec 8 | free 8 run 1 | free 8 run 2 | free 8 run 1 vs run 2 |
|---|---|---|---|---|---|---|---|
| abc abd ijk | 0.007 (p 0.709) | 0.006 (p 0.983) | 0.014 (p 0.486) | 0.014 (p 0.486) | 0.004 (p 0.942) | 0.012 (p 0.454) | 0.010 (p 0.624) |
| abc cba mrrjjj | 0.019 (p 0.340) | 0.008 (p 0.974) | 0.018 (p 0.684) | 0.018 (p 0.684) | 0.021 (p 0.206) | 0.036 (p 0.020) | 0.028 (p 0.124) |
| abc abd xyz | 0.054 (p 0.150) | 0.061 (p 0.043) | 0.052 (p 0.051) | 0.052 (p 0.051) | 0.111 (p 0.000) | 0.108 (p 0.000) | 0.015 (p 0.986) |
| abc abd glz | 0.034 (p 0.427) | 0.026 (p 0.829) | 0.041 (p 0.213) | 0.041 (p 0.213) | 0.069 (p 0.006) | 0.034 (p 0.425) | 0.041 (p 0.196) |
| rst rsu xyz | 0.066 (p 0.016) | 0.048 (p 0.134) | 0.059 (p 0.110) | 0.059 (p 0.110) | 0.106 (p 0.000) | 0.132 (p 0.000) | 0.039 (p 0.636) |
| aabb cc aabb | 0.006 (p 0.887) | 0.007 (p 0.732) | 0.007 (p 0.863) | 0.007 (p 0.863) | 0.073 (p 0.048) | 0.085 (p 0.006) | 0.021 (p 0.892) |
| abc aabbcc kkjjii | 0.049 (p 0.343) | 0.057 (p 0.488) | 0.051 (p 0.431) | 0.051 (p 0.431) | 0.072 (p 0.160) | 0.074 (p 0.014) | 0.047 (p 0.737) |
| eeqee qeeq xxixx | 0.023 (p 0.639) | 0.033 (p 0.516) | 0.027 (p 0.910) | 0.027 (p 0.910) | 0.121 (p 0.000) | 0.106 (p 0.000) | 0.031 (p 0.871) |

## Which mode varies more than the control

Stated mechanically, with no view on what "low" means:

- **Speculative 2 and speculative 8**: no problem has a TV above the top of the noise band, and none is significant after Holm. Their mean TV over the 8 problems is 0.0276, against 0.0261 for the control. On 6 of the 8 problems their TV is a little larger than the control's, and on 2 smaller. They are indistinguishable from the control in this sample. The two speculative modes give identical results (below), so they are one measurement counted twice, not two.
- **Free-running 8**: it differs from the control. In run 1, 5 of 8 problems have a TV above the noise band and 3 are significant after Holm; in run 2 it is 5 of 8 and 2 of 8. The mean TV is 0.065 and 0.070, about 2.5 times the control's 0.026. It is above the control's TV on all 8 problems, in both runs. The problems it moves most are the ones with give-ups: give-up rate 13-14% against 9-10% (abc abd xyz), 25-26% against 15-16% (eeqee qeeq xxixx), 56-57% against 49-50% (aabb cc aabb), 8-9% against 4-6% (abc abd glz), and 15-16% against 11% (rst rsu xyz). It also takes more codelets: the median is 13% to 33% higher than the reference on every problem except aabb cc aabb (+3%). The second run, on a machine with none of my jobs on it, shows the same pattern, so it is not an effect of my other work running.
- **Patched Metacat against the one-worker reference** is shown for reading, and is itself inside the noise band on 7 of 8 problems. On rst rsu xyz its TV (0.066) is above the band (0.063) and its raw p is 0.016, not significant after Holm (0.59); the control on that problem is also high (0.052).

## Identity checks

- **Speculative 2 against speculative 8**: all 8,000 runs (8 problems x 1,000 seeds) have the same answer, codelet count, final temperature and status. On a sample of 160 runs (seeds 1-20 of each problem) the full final-state digest (`tests/support/golden_baseline.state_digest`) is also identical. Zero differences. (`logs/spec_identity.log`, `logs/digest_samples.log`)
- **Speculative against one worker, same seed**: not identical, as the code says (`server/api/runs.py`: "a different, equal in law, run from workers=1"): 3,352 of 8,000 runs give the same answer, and 13 give the same answer and the same codelet count.
- **Swarm against one worker**: 200 runs (seeds 1-25 of each problem, `numpy`, executor `serial`) through `server.parallel.swarm.Swarm` have the same status, answer, codelet count and temperature as the one-worker recording. Zero differences. (`logs/swarm_check.log`)

## Size and what was not done

- Every mode had 1,000 seeds per problem (the same seeds, 1-1000, in every mode), cap 100,000. The control and the one-worker reference together are 2,000 seeds. No mode had to be cut. Zero runs ended in an error in any recording.
- Wall time, summed over the 8 problems: one worker (2,000 seeds) 40 minutes on 6 processes; speculative 2 29 minutes on 4 processes; speculative 8 58 minutes on 2 processes; free-running 8 44 and 33 minutes on 2 processes.
- Free-running runs are not reproducible run for run, so the two free-running samples are two draws from one process, not one measurement twice. Their mutual TV is in the last table.
- I tested one thread count for the free-running engine (8). I did not test other counts, other problems, or the effect of machine load on the free-running engine beyond the two runs here (run 1 at load 7 to 8 and run 2 at about 5, with other agents' jobs on the machine both times).
- I did not diagnose why the free-running engine gives up more often and takes more codelets.
- The speculative executor ran on the free-threaded interpreter `.venv-ft` with `PYTHON_GIL=0`; one worker and the Swarm ran on `.venv`. It is exact, so the interpreter does not change its result, but I did not run it on the GIL interpreter at scale (20 runs of one problem agreed in a trial).
