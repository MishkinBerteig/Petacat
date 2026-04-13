"""Base class for all workspace structures.

Scheme source: workspace-structures.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.engine.formulas import weighted_average

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider


class WorkspaceStructure:
    """Base class for bonds, groups, bridges, descriptions, rules."""

    # Proposal level string constants (values live in DB proposal_levels table)
    PROPOSED = "proposed"
    EVALUATED = "evaluated"
    BUILT = "built"

    _next_id = 0

    # Thematic compatibility weight (0-100).  Loaded from the
    # ``thematic_compatibility_weight`` formula coefficient via
    # ``configure_thematic_weight()``.  Default 0 preserves backward
    # compatibility (the thematic term has no effect).
    _thematic_compatibility_weight: float = 0.0

    def __init__(self) -> None:
        WorkspaceStructure._next_id += 1
        self.id = WorkspaceStructure._next_id
        self.proposal_level = self.PROPOSED
        self.strength: float = 0.0
        self.time_stamp: int = 0

    @classmethod
    def configure_thematic_weight(cls, meta: MetadataProvider) -> None:
        """Set the class-level thematic weight from *meta* coefficients."""
        cls._thematic_compatibility_weight = meta.get_formula_coeff(
            "thematic_compatibility_weight"
        )

    @property
    def is_proposed(self) -> bool:
        return self.proposal_level == self.PROPOSED

    @property
    def is_evaluated(self) -> bool:
        return self.proposal_level == self.EVALUATED

    @property
    def is_built(self) -> bool:
        return self.proposal_level == self.BUILT

    def update_strength(self) -> None:
        """Recompute strength from internal, external, and thematic terms.

        Scheme: workspace-structures.ss:50-63.

        1. ``intrinsic_strength`` = weighted-average of internal and external
           strengths, where internal self-weights (the stronger the internal
           component, the less external matters).
        2. ``thematic`` = thematic compatibility of this structure (0 for the
           base class; subclasses like bridges and descriptions override
           ``get_thematic_compatibility``).
        3. Final strength blends thematic and intrinsic via a configurable
           ``thematic_compatibility_weight`` (from formula_coefficients).
           When the weight is 0 the formula reduces to just intrinsic_strength.
        """
        internal = self.calculate_internal_strength()
        external = self.calculate_external_strength()

        # Step 1 – intrinsic strength (unchanged from original)
        intrinsic_strength = weighted_average(
            [internal, external],
            [internal, 100.0 - internal],
        )

        # Step 2 – thematic compatibility
        thematic = self.get_thematic_compatibility()
        tw = self._thematic_compatibility_weight

        # Step 3 – blend thematic with intrinsic
        self.strength = round(
            weighted_average(
                [thematic, intrinsic_strength],
                [tw, 100.0 - tw],
            )
        )

    def calculate_internal_strength(self) -> float:
        return 0.0

    def calculate_external_strength(self) -> float:
        return 0.0

    def get_thematic_compatibility(self) -> float:
        """Return thematic compatibility for this structure.

        Base implementation returns 0.  Subclasses (bridges, descriptions)
        override this to return a value based on theme support.

        Scheme: workspace-structures.ss:66.
        """
        return 0.0

    def weakness(self) -> float:
        """Probability-of-breaking measure. Scheme: workspace-structures.ss:41."""
        return 100.0 - self.strength**0.95

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(id={self.id}, "
            f"level={self.proposal_level}, "
            f"strength={self.strength:.1f})"
        )
