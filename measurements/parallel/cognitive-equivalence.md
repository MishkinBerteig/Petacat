# Cognitive equivalence: the stream-serial reference against the faithful loop (2026-10-30)

The parallel plugin's within-run executors follow the **stream-serial reference** (`"stream"`),
which changes two mechanisms of the faithful loop (`run_mcat`):
- every codelet draws from a counter-based random stream keyed by its id, not from the run's one
  Mersenne Twister;
- the coderack chooses by an exponential race. Each codelet gets a firing clock when it is
  posted, and the smallest clock wins. This replaces Metacat's two-stage draw (a bin weighted by
  count × urgency, then uniform within the bin).

Both changes are claimed to be equal *in law*: the same probability for every outcome, reached
through different random numbers. The speculative executor is bit-identical to the stream
reference for every worker count. So if the stream reference thinks what the faithful loop
thinks, every parallel run does too.

A claim in law can only be checked statistically. This is that check:

    .venv/bin/python scripts/compare_executors.py --executors serial,stream --seeds 500 \
        --json measurements/parallel/serial-vs-stream-500.json

- **Scope:** every distinct demo problem (29, discovery and justification) × seeds 1–500 ×
  both executors, which is **29,000 runs**. The cap was 20,000 codelets, the backend was the
  placement default (`off`), and the run took 34 minutes on the swarm (17 processes, on a
  machine shared with other work).
- **Test:** each problem's stopping-state distribution (`status:answer`) was compared with a
  two-sample chi-square, pooling rare states to an expected count of 5, alongside the total
  variation distance and every state's two-proportion z-score.

**Result: no difference.**
- **Chi-square:** 0 of the 29 problems reach p < 0.01, against about 0.2 expected by chance.
  The smallest p is 0.148 (`abc → abd; ijk`).
- **Per-state z-scores:** of 157 state comparisons, 0 exceed the Bonferroni-corrected
  |z| > 4.00. The largest |z| is 2.34.
- **Distance:** total variation is at most 0.07.
- **Run length:** mean codelet counts agree to within the run-to-run spread (table below).

```
problem                                  pair                             n     chi2  df        p     TV  max|z|          codelets
abc-abd-mrrjjj=mrrjjjj                   serial vs stream         500/500       1.02   1   0.3134  0.008    1.42       4647/4874    
xqc-xqd-mrrjjj=mrrkkk                    serial vs stream         500/500       0.00   0        -  0.000    0.00       1366/1355    
rst-rsu-xyz=uyz                          serial vs stream         500/500       0.33   1   0.5660  0.016    0.57       4463/4635    
abc-abd-xyz=dyz                          serial vs stream         500/500       0.26   1   0.6097  0.016    0.59       4505/4575    
xqc-xqd-mrrjjj=mrrjjjj                   serial vs stream         500/500       0.00   0        -  0.006    1.73       5781/5605    
eqe-qeq-abbbc=aaabccc                    serial vs stream         500/500       0.03   2   0.9835  0.002    0.18       9373/9635    
abc-abd-xyz                              serial vs stream         500/500       2.89   6   0.8222  0.054    1.42       2052/2225    
eqe-qeq-abbbc                            serial vs stream         500/500       6.81  10   0.7430  0.070    1.73       2632/2576    
abc-abd-xyz=xyd                          serial vs stream         500/500       0.00   0        -  0.002    0.58       1126/1081    
abc-abd-xyz=wyz                          serial vs stream         500/500       0.00   0        -  0.004    1.42       1400/1492    
rst-rsu-xyz=xyu                          serial vs stream         500/500       0.00   0        -  0.004    0.71        950/942     
rst-rsu-xyz=wyz                          serial vs stream         500/500       0.00   0        -  0.004    0.71       1535/1411    
abc-abd-mrrjjj=mrrkkk                    serial vs stream         500/500       0.00   0        -  0.002    1.00       1709/1668    
eqe-qeq-abbba=baaab                      serial vs stream         500/500       0.61   1   0.4351  0.006    0.78       3458/3361    
eqe-qeq-abbba=aaabaaa                    serial vs stream         500/500       0.63   2   0.7305  0.014    0.69      17082/17081   
eeqee-qeeq-xxixx                         serial vs stream         500/500       5.13   5   0.4006  0.052    2.34       4135/4132    
aabc-aabd-ijkk=ijll                      serial vs stream         500/500       0.00   0        -  0.002    1.00       2399/2214    
aabc-aabd-ijkk=hjkk                      serial vs stream         500/500       0.00   0        -  0.006    1.35       4938/4966    
abc-cba-mrrjjj=mmmrrj                    serial vs stream         500/500       0.25   1   0.6183  0.014    1.00      11071/11076   
abc-abd-ijk=abd                          serial vs stream         500/500       2.10   1   0.1477  0.044    1.45       4705/4555    
abc-aabbcc-kkjjii                        serial vs stream         500/500       7.99   6   0.2390  0.060    2.32       7760/7904    
a-b-z                                    serial vs stream         500/500       2.59   3   0.4589  0.036    1.45        429/417     
abc-abd-glz                              serial vs stream         500/500       8.22   6   0.2225  0.042    2.03       2140/2018    
ab-c-ab                                  serial vs stream         500/500       0.04   1   0.8499  0.004    0.19        700/730     
bc-d-bc                                  serial vs stream         500/500       0.00   0        -  0.000    0.00        672/683     
xy-z-xy                                  serial vs stream         500/500       0.00   0        -  0.000    0.00        712/725     
zy-x-zy                                  serial vs stream         500/500       0.08   1   0.7742  0.006    0.29        702/713     
aabb-cc-aabb                             serial vs stream         500/500       1.52   3   0.6784  0.014    1.00       5032/5067    
abc-d-abc                                serial vs stream         500/500       0.13   1   0.7217  0.012    1.00        840/863     

chi-square p < 0.01: 0 of 29 comparisons (about 0.2 expected by chance if the executors agree)
Bonferroni |z| > 4.00 over 157 state comparisons: 0 flagged (marked *)
```
