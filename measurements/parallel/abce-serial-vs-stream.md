# The deep answer `abce`: faithful loop vs stream-serial reference (2026-10-30)

`wxyz → vxyz; abcd` is the problem on which the first attempt at codelet parallelism
showed its damage. Free-running at six workers found the deep answer `abce` in 9.3% of runs,
against 15.0% serially. The stream-serial reference is the run that every speculative
executor reproduces bit for bit, so the question here is whether it finds `abce` as often as
the faithful loop does.

    scripts/compare_executors.py --problem wxyz vxyz abcd --executors serial,stream \
        --max-steps 100000 --backend numpy --count-answer abce --seeds N --seed-start S

The settings are the original study's: a budget of 100,000 codelets and the numpy backend.
Each sample uses fresh seeds.

| Sample | Seeds | Faithful `abce` | Stream `abce` | Two-proportion z | Omnibus χ² p |
|---|---|---:|---:|---:|---:|
| 1 | 101–1100 | 165 / 1000 (16.5%) | 122 / 1000 (12.2%) | 2.74 | 0.052 |
| 2 | 1101–3100 | 276 / 2000 (13.8%) | 266 / 2000 (13.3%) | 0.46 | 0.98 |
| 3 | 3101–8100 | 655 / 5000 (13.1%) | 676 / 5000 (13.5%) | −0.62 | 0.71 |
| all | 8,000 seeds | 1,096 (13.7%) | 1,064 (13.3%) | 0.74 | — |

**Result: no difference.**
- **Why there were three samples.** Sample 1 alone looked like a loss: `abce` was the
  pre-specified answer, and p ≈ 0.006 on its own. That is why samples 2 and 3 were taken, on
  fresh seeds. They show the opposite sign or nothing.
- **What the seeds alone do.** The faithful loop's own rate moves from 16.5% to 13.1% between
  samples, which is the seed-to-seed spread at this sample size.
- **What the pooled figures say.** Pooled over 8,000 seeds per loop, the rates are 13.7% and
  13.3%, which is z = 0.74.
- **The whole distribution agrees too.** Across the full stopping-state distribution, with
  `vbcd`, `abcd`, `abce`, giving up, `vxyz`, `abcv` and `abcc`, no state's z passes the
  Bonferroni line in any sample.

Sample 1 also shows that one 1,000-run comparison cannot settle a 3–4 point difference in an
answer found 13–16% of the time. A rate claim on this problem needs several thousand runs per
side, and the swarm makes that a five-minute job.
