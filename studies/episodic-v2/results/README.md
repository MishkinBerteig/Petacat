# Discovery Pilot Results

The completed [pilot-02 summary](pilot-02/SUMMARY.md) and
[discovery figure](pilot-02/discovery-curves.png) report all 4000 episode assignments.
The bundle includes the
100-through-1000 episode discovery curves for four problems, separately for
`best_a` (native quality) and `best_b` (native conceptual preference).
The answer reached first wins an unresolved tie within either definition.

The interrupted serializer-only predecessor is documented in the
[study README](../README.md#serializer-correction-before-the-first-checkpoint)
and in the bundle's `parent-import.json`. Its completed observations are not
counted twice. Excluded diagnostic execution costs are reported separately.

## Verify Without Any Engine Execution

From the repository root:

```sh
python3 studies/episodic-v2/pilot.py verify-export studies/episodic-v2/results/pilot-02
python3 -m unittest discover -s studies/episodic-v2
python3 -m unittest discover -s studies/episodic-v2/results
```

Verification uses only saved records and the Python standard library. The
collector shares Unix file-locking helpers, so use macOS, Linux, or the WSL
route described in the [dependency instructions](../../../Metacat/README.md).
Docker, Metacat execution, and a GPU are not needed to recompute the curves.

## Regenerate the Figure

The optional plotting environment is separate from the frozen experiment
runtime. The plots were generated with Matplotlib 3.11.1:

```sh
python3 -m venv /tmp/episodic-plots
/tmp/episodic-plots/bin/python -m pip install matplotlib==3.11.1
/tmp/episodic-plots/bin/python studies/episodic-v2/results/plot_curves.py \
  studies/episodic-v2/results/pilot-02
```

This writes `discovery-curves.png` and `discovery-curves.pdf` from
`analysis.json`. No engine is imported or run. The figure uses a logarithmic
vertical scale above 0.0001 and a linear scale near zero, preserving actual
zero estimates rather than replacing them with artificial positive values.
Both curves remain visible when they differ; coincident points may overlap.

The recorded `SHA256.json` covers the scientific bundle files. The
rendered figures and human summary are additional derived artifacts, not
inputs to the episode collection or the Good-Turing calculation.
