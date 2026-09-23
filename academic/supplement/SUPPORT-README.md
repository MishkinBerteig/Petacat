# Versioned Single-Run Study: Review Copy

This review-specific document replaces repository navigation instructions.
The amended protocol in `amendment.json`, saved data, collectors, and analysis
code are unchanged. The source-snapshot ledger identifies this README as a
documentation replacement, not the originally sampled file.

The study retains 969,000 main observations: 380,000 construction, 570,000
reference validation, and 19,000 port observations. Three reference execution
errors remain in the data. The full scientific archive, interrupted parent,
excluded pilot, and aborted preflight are in [data/](data/README.md).

From the review bundle root:

```sh
python3 verify.py
```

For independent reanalysis of all raw single-run observations, install the
pinned numerical dependencies and follow [REPRODUCE.md](../../REPRODUCE.md).
This does not run either engine. Do not combine inherited provenance copies as
additional observations, enlarge construction with validation discoveries, or
replace failed executions with retries.

The separate historical repair narrative has incomplete build provenance; this
versioned study does not retroactively identify its sampled implementations.
