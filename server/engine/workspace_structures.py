"""Base class for all workspace structures.

Scheme source: workspace-structures.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.engine.formulas import weighted_average
from server.engine.ids import KIND_STRUCTURE, next_id

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider


class WorkspaceStructure:
    """Base class for bonds, groups, bridges, descriptions, rules."""

    # Proposal level string constants (values live in DB proposal_levels table)
    PROPOSED = "proposed"
    EVALUATED = "evaluated"
    BUILT = "built"

    # The Themespace the current run's structures resonate with.  The Scheme uses
    # a global ``*themespace*``; this mirrors it.  Set by ``init_mcat``.
    _themespace: object | None = None

    def __init__(self) -> None:
        self.id = next_id(KIND_STRUCTURE)
        self.proposal_level = self.PROPOSED
        self.strength: float = 0.0
        self.time_stamp: int = 0
        #: The group this structure is a constituent of, if any.  Set for *bonds*
        #: by ``build-group`` (groups.ss:927-928) and cleared by ``break-group``
        #: (groups.ss:988-989); the breaker reads it to decide whether a bond can
        #: be broken on its own (breakers.ss:31-40).  Declared on the base so the
        #: field set is the same on every structure the state graph captures.
        self.enclosing_group: object | None = None

    @classmethod
    def set_themespace(cls, themespace: object | None) -> None:
        """Bind the Themespace structures consult for thematic compatibility."""
        cls._themespace = themespace

    @classmethod
    def get_themespace(cls) -> object | None:
        return cls._themespace

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

        Scheme: ``update-strength`` (workspace-structures.ss:50-63)::

            compatibility   = get-thematic-compatibility        ; -1 .. +1
            thematic-weight = |compatibility|
            strength = weighted-average([100 if compatibility > 0 else 0,
                                         intrinsic],
                                        [thematic-weight, 1 - thematic-weight])

        The thematic weight is *dynamic*, derived per-structure, and pulls
        strength toward 100 when the structure resonates with the active themes
        and toward 0 when it clashes with them.  This is the "knobs" mechanism of
        §4.1.2 / Fig. 4.4 — a small amount of negative theme activation quickly
        undermines a structure, a small amount of positive activation quickly
        boosts it, and with no active themes the strength reverts to intrinsic.
        """
        internal = self.calculate_internal_strength()
        external = self.calculate_external_strength()

        intrinsic_strength = weighted_average(
            [internal, external],
            [internal, 100.0 - internal],
        )

        compatibility = self.get_thematic_compatibility()
        thematic_weight = abs(compatibility)
        if thematic_weight == 0.0:
            self.strength = round(intrinsic_strength)
            return

        self.strength = round(
            weighted_average(
                [100.0 if compatibility > 0 else 0.0, intrinsic_strength],
                [thematic_weight, 1.0 - thematic_weight],
            )
        )

    def calculate_internal_strength(self) -> float:
        return 0.0

    def calculate_external_strength(self) -> float:
        return 0.0

    def get_thematic_compatibility(self) -> float:
        """How well this structure resonates with the active themes, in -1..+1.

        Base implementation returns 0 — "For structures that lack their own local
        method" (workspace-structures.ss:66).  Bridges and descriptions override
        it; §4.1.2 notes that in the current version of Metacat only those two
        structure types are influenced by themes.
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
