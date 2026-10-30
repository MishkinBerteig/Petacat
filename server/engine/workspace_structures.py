"""Base class for all workspace structures.

Scheme source: workspace-structures.ss
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from server.engine.ids import KIND_STRUCTURE, next_id

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG


#: The running engine's codelet count, as ``*codelet-count*`` is for Scheme's
#: ``make-workspace-structure`` (workspace-structures.ss:22: ``(time-stamp
#: *codelet-count*)``): every structure is stamped with the count at the moment it is
#: *made*.  The runner sets it before and after each codelet.  Thread-local, so
#: engines running in separate threads do not stamp each other's structures.
_clock = threading.local()


def set_structure_clock(codelet_count: int) -> None:
    _clock.now = codelet_count


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
        #: workspace-structures.ss:22 -- the count when the structure was made (not
        #: when built); the progress-watcher's activity is the age of the youngest.
        self.time_stamp: int = getattr(_clock, "now", 0)
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

    def update_strength(self, rng: RNG | None = None) -> None:
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

        **Why this takes an RNG when the Scheme's does not.**  A bond's and a
        group's external strength is local density (``bonds.ss:136-160``,
        ``groups.ss:354-383``), and that walk chooses each positional neighbour
        by a salience-weighted stochastic pick, re-rolled on every strength
        update.  The Scheme reaches its generator as a global; this port has
        none, so the generator is threaded from the call site instead.  Pass the
        RNG the *calling codelet* is drawing from — ``ctx.rng``, which under
        free-running is that codelet's own counter-based stream — so a run's
        randomness stays a function of where a codelet ran rather than of the
        order workers happened to execute in.  ``None`` is for callers with no
        run context (unit tests): the walk then takes the first candidate at
        each step rather than inventing a generator of its own.
        """
        internal = self.calculate_internal_strength()
        external = self.calculate_external_strength(rng)

        # ``weighted_average([internal, external], [internal, 100.0 - internal])`` written
        # out for two terms (WP9): the same operations in the same order, minus the
        # two list builds, the ``zip`` and the generator.  ``sum`` of two floats is
        # ``a + b`` (its compensated summation only matters from three terms on).
        w2 = 100.0 - internal
        total = internal + w2
        if total == 0:
            intrinsic_strength = 0.0
        else:
            intrinsic_strength = (internal * internal + external * w2) / total

        compatibility = self.get_thematic_compatibility()
        thematic_weight = abs(compatibility)
        if thematic_weight == 0.0:
            self.strength = round(intrinsic_strength)
            return

        w2 = 1.0 - thematic_weight
        total = thematic_weight + w2
        if total == 0:
            self.strength = round(0.0)
            return
        pole = 100.0 if compatibility > 0 else 0.0
        self.strength = round((pole * thematic_weight + intrinsic_strength * w2) / total)

    def calculate_internal_strength(self) -> float:
        return 0.0

    def calculate_external_strength(self, rng: RNG | None = None) -> float:
        """*rng* is used only by Bond and Group, whose external strength is the
        stochastic density walk.  Every override takes it so the seam is one
        signature rather than a special case."""
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
