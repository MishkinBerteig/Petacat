"""Temperature computation.

Temperature is the global control parameter: 100 = confused, 0 = solved.
Regulates randomness in codelet selection and structure decisions.

Scheme source: formulas.ss (update-temperature), run.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.engine.formulas import update_temperature as _update_temp

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
        """Recompute temperature unless clamped."""
        if self.clamped:
            self.value = self.clamp_value
            return
        self.value = float(_update_temp(avg_unhappiness, has_supported_rule, meta))

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
