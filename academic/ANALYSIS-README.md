# Analysis Supplement

This supplement reproduces arithmetic from archived measurement counts and
exact toy-distribution calculations. It is not an end-to-end engine replication
or a certificate of support equality. It contains no original Metacat source.

From the `academic` directory after extracting the ZIP, using Python 3.9 or later:

```sh
python3 tools/audit_numbers.py
python3 tools/audit_episodes.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: 19 inputs, 374,500 reference runs, 366 observed problem--outcome pairs,
27 head members, and 14 tests passing. The post-repair CPU single-run cycle has one novel
pair, zero missing head members, and 23 cap-resolution reruns in addition to its
1,900 initial runs. `number-audit.json` contains the calculations and data hashes.

Each archived learning-mode cycle contains 1,900 eight-run episodes. The
post-repair CPU file has 13 stored novel endpoint pairs in 14 episodes, zero
missing stored head members, four never-answering episodes, and 2,404 capped
within-episode runs. `episode-audit.json` reconstructs endpoint and cap counts
from the ordered port sequences. It checks stored novelty counts, but cannot
independently determine episodic novelty without the historical episodic
reference, which is not included. The archived reference and port episode caps
also differ. Last successful answers do not establish convergence or improved
learning.

No third-party Python modules or network access are needed. See `data/README.md`
for the input descriptions and provenance limits. Stopping labels such as
`saturated` in the archived files describe a heuristic, not a statistical bound.
The records do not establish the exact historically sampled source builds.

The manuscript's toy binomial test and fixed-size validation budget are
analytical examples. They are not new Metacat experiments. The held-out
validation stage has no completed results included in this supplement.
