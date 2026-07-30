"""Temperature computation.

Temperature is the global control parameter: 100 = confused, 0 = solved.
Regulates randomness in codelet selection and structure decisions.

Scheme source: formulas.ss (update-temperature), run.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.engine.formulas import update_temperature as _update_temp
from server.engine.numeric.backend import select_backend

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider


class Temperature:
    """Global temperature state."""

    def __init__(self, initial: float = 100.0) -> None:
        self.value: float = initial
        self.clamped: bool = False
        self.clamp_value: float = 0.0
        self.clamp_cycles_remaining: int = 0

    def update(
        self,
        avg_unhappiness: float,
        has_supported_rule: bool,
        meta: MetadataProvider,
    ) -> None:
        """Recompute temperature unless clamped.

        Routed through the numeric substrate when one is engaged, which is never
        under the default policy and is the right answer: temperature is a
        weighted average of two numbers, and there is no arrangement of hardware
        under which dispatching that is faster than computing it.  The seam exists
        because WP4.6 batches K independent runs, at which point this becomes a
        K-element reduction that belongs with the rest of the batch rather than in
        a Python loop over runs.
        """
        if self.clamped:
            self.value = self.clamp_value
            return
        backend = select_backend(1)
        if backend is None:
            self.value = float(_update_temp(avg_unhappiness, has_supported_rule, meta))
            return
        self.value = float(
            backend.temperature(
                avg_unhappiness,
                meta.get_formula_coeff(
                    "rule_factor_with_supported_rule"
                    if has_supported_rule
                    else "rule_factor_no_supported_rule"
                ),
                meta.get_formula_coeff("unhappiness_weight"),
                meta.get_formula_coeff("rule_factor_weight"),
            )
        )

    def clamp(self, value: float, cycles: int = 0) -> None:
        """Force temperature to a fixed value."""
        self.clamped = True
        self.clamp_value = value
        self.value = value
        self.clamp_cycles_remaining = cycles

    def unclamp(self) -> None:
        self.clamped = False
        self.clamp_cycles_remaining = 0

    def tick_clamp(self) -> None:
        if self.clamped and self.clamp_cycles_remaining > 0:
            self.clamp_cycles_remaining -= 1
            if self.clamp_cycles_remaining == 0:
                self.unclamp()

    def __repr__(self) -> str:
        c = " [clamped]" if self.clamped else ""
        return f"Temperature({self.value:.1f}{c})"
