# Archived Measurement Inputs

These are measurement records, not Metacat source code. They are copied
unchanged from the available historical artifacts so that the paper's count
audit no longer requires a separate checkout or access to another computer.

- `reference-single-runs.json`: 19 reference problems, 374,500 runs, outcome
  counts, stopping metadata, and codelet-count histograms. It is an aggregate,
  not an ordered per-run trace. Its original filename was `single-runs.json`.
- `vs-metacat-pre-rc-a.json`: archived pre-repair NumPy check.
- `vs-metacat.json`: archived post-repair NumPy check.
- `vs-metacat-mlx.json`: archived MLX check, not evidence of a repaired MLX run.

SHA-256 fingerprints are recomputed into `../number-audit.json` by
`../tools/audit_numbers.py`. The three check files match the repository's
`measurements/` copies byte for byte. The legacy `reference` field in these
records is descriptive metadata; no analysis tool follows that external path.

## Provenance Limits

These records do not pin all historical sampled source revisions or environment
settings. The current reconstructible reference patch bundle does not establish
which build generated these older counts. Codelet histograms cannot recover
discovery order, seed-to-outcome mappings, or inter-discovery gaps. Do not use
these data to claim a fresh independent replication, a confidence certificate,
or validation of unchanged output probabilities.

The paper uses both single-run summaries and ordered eight-run port episodes.
`../tools/audit_episodes.py` reconstructs the latter's endpoint, no-answer, and
cap counts into `../episode-audit.json`. The historical episodic reference is
not included, so stored novelty labels cannot be independently regenerated.
Reference and port episode caps differ; the terminal projection is the last
successful answer, not a demonstrated convergence state. No fabricated
observations, reconstructed ordering, or additional engine runs have been added.
