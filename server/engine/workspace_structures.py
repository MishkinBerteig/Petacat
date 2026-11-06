"""Base class for all workspace structures.

Scheme source: workspace-structures.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.engine.ids import KIND_STRUCTURE, next_id
from server.engine.run_binding import constants, current, set_clock

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG


def set_structure_clock(codelet_count: int) -> None:
    """Stamp the structures made from now on, in this thread and run, with *codelet_count*.

    ``*codelet-count*`` for Scheme's ``make-workspace-structure``
    (workspace-structures.ss:22: ``(time-stamp *codelet-count*)``): every structure is
    stamped with the count at the moment it is *made*.  The runner sets it before and after
    each codelet.  It lives on the run's binding (``run_binding.RunBinding.clock``), per
    thread, so engines running in separate threads do not stamp each other's structures and
    two runs stepped alternately on one thread do not either.
    """
    set_clock(codelet_count)


def bound_meta() -> MetadataProvider:
    """The running engine's ``MetadataProvider``, for the cold paths that need a name, a
    role or a template (the coefficients a structure reads while it computes a strength are
    on ``run_binding.constants()``).

    Raises :class:`~server.engine.run_binding.NoRunBound` (a ``ConfigurationRequired``) when
    no run is bound: nothing falls back to the Metacat Standard Configuration files.
    """
    return current().meta


class WorkspaceStructure:
    """Base class for bonds, groups, bridges, descriptions, rules."""

    # The built level's name, as the run's vocabulary spells it, kept beside ``proposal_level``
    # so that ``is_built`` is one comparison.  A slot, not an entry of ``__dict__``, because the
    # state graph captures ``vars(structure)`` and this is configuration, not run state: the
    # same name for every structure of a run.  Subclasses have no ``__slots__`` and keep their
    # ``__dict__``.
    __slots__ = ("_built_level",)

    def __init__(self) -> None:
        self.id = next_id(KIND_STRUCTURE)
        run = current()
        voc = run.constants.vocab
        #: The level name the structure was made with, and the one that means "built", both
        #: from the run's vocabulary; ``is_built`` is an equality test between them.
        self.proposal_level = voc.proposal_level_proposed
        self._built_level = voc.proposal_level_built
        self.strength: float = 0.0
        #: workspace-structures.ss:22 -- the count when the structure was made (not
        #: when built); the progress-watcher's activity is the age of the youngest.
        self.time_stamp: int = getattr(run.clock, "now", 0)
        #: The group this structure is a constituent of, if any.  Set for *bonds*
        #: by ``build-group`` (groups.ss:927-928) and cleared by ``break-group``
        #: (groups.ss:988-989); the breaker reads it to decide whether a bond can
        #: be broken on its own (breakers.ss:31-40).  Declared on the base so the
        #: field set is the same on every structure the state graph captures.
        self.enclosing_group: object | None = None

    @staticmethod
    def get_themespace() -> object | None:
        """The Themespace of the run this structure belongs to (the one bound now)."""
        return current().themespace

    @property
    def is_built(self) -> bool:
        try:
            built = self._built_level
        except AttributeError:
            # A structure the state graph restored with ``__new__`` never ran ``__init__``.
            built = self._built_level = current().constants.vocab.proposal_level_built
        return self.proposal_level == built

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
        order workers happened to execute in.  ``None`` is for a structure whose external
        strength draws nothing (a Description).
        """
        internal = self.calculate_internal_strength()
        external = self.calculate_external_strength(rng)

        # ``weighted_average([internal, external], [internal, 100.0 - internal])`` written
        # out for two terms (WP9): the same operations in the same order, minus the
        # two list builds, the ``zip`` and the generator.  ``sum`` of two floats is
        # ``a + b`` (its compensated summation only matters from three terms on).
        w2 = 100.0 - internal
        total = internal + w2
        intrinsic_strength = (internal * internal + external * w2) / total

        compatibility = self.get_thematic_compatibility()
        thematic_weight = abs(compatibility)
        if thematic_weight == 0.0:
            self.strength = round(intrinsic_strength)
            return

        w2 = 1.0 - thematic_weight
        total = thematic_weight + w2
        rc = constants()
        pole = (
            rc.thematic_pull_positive_target
            if compatibility > 0
            else rc.thematic_pull_negative_target
        )
        self.strength = round((pole * thematic_weight + intrinsic_strength * w2) / total)

    # ``calculate_internal_strength()`` and ``calculate_external_strength(rng)`` are
    # supplied by every concrete structure (Bond, Group, Bridge, Description, Rule).
    # *rng* is used only by Bond and Group, whose external strength is the stochastic
    # density walk; every override takes it so the seam is one signature.

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
        return 100.0 - self.strength ** constants().weakness_exponent

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(id={self.id}, "
            f"level={self.proposal_level}, "
            f"strength={self.strength:.1f})"
        )
