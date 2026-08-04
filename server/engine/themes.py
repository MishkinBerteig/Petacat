"""Themespace — self-watching mechanism.

Tracks themes (activated patterns along conceptual dimensions) that
characterize the dominant perceptual interpretation being built.

Scheme source: themes.ss
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from server.engine.numeric.backend import select_backend
from server.engine.numeric.layout import ThemeLayout, ThemeParams, ThemeState

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.slipnet import SlipnetNode

#: ``%max-theme-activation%`` — a theme's activation lives in [-100, +100] (§4.2).
MAX_THEME_ACTIVATION = 100.0


def _clip_positive(value: float) -> float:
    """Scheme: ``clip-positive`` (``themes.ss:34-35``) — clip to [0, +100]."""
    return max(0.0, min(MAX_THEME_ACTIVATION, value))


def _clip_negative(value: float) -> float:
    """Scheme: ``clip-negative`` (``themes.ss:37-38``) — clip to [-100, 0]."""
    return max(-MAX_THEME_ACTIVATION, min(0.0, value))


# Theme type string constants (values live in DB theme_types table)
THEME_TOP_BRIDGE = "top_bridge"
THEME_BOTTOM_BRIDGE = "bottom_bridge"
THEME_VERTICAL_BRIDGE = "vertical_bridge"

# All theme types for iteration
ALL_THEME_TYPES = [THEME_TOP_BRIDGE, THEME_BOTTOM_BRIDGE, THEME_VERTICAL_BRIDGE]

# ---------------------------------------------------------------------------
# Theme relations
#
# In the Scheme a theme's relation is a Slipnet node (plato-identity,
# plato-opposite, plato-successor, plato-predecessor) or ``#f`` for the
# "different" relation, which represents the *absence* of a relating concept
# (themes.ss:715 ``difference-theme?``).  Petacat uses bare relation names
# throughout — seed data, the UI and the API all speak them — so every producer
# of a relation must go through ``relation_name_for_label``.
# ---------------------------------------------------------------------------

RELATION_IDENTITY = "identity"
RELATION_OPPOSITE = "opposite"
RELATION_SUCCESSOR = "successor"
RELATION_PREDECESSOR = "predecessor"
RELATION_DIFFERENT = "diff"

# Bare relation name -> Slipnet node name.  ``diff`` deliberately has no node.
_RELATION_NODES: dict[str, str] = {
    RELATION_IDENTITY: "plato-identity",
    RELATION_OPPOSITE: "plato-opposite",
    RELATION_SUCCESSOR: "plato-successor",
    RELATION_PREDECESSOR: "plato-predecessor",
}

_NODE_RELATIONS: dict[str, str] = {v: k for k, v in _RELATION_NODES.items()}

#: See ``slipnet._UNRESOLVED`` — "not yet decided" is not "decided against".
_UNRESOLVED = object()

# Bridge-type aliases accepted by the lookup helpers below.
_BRIDGE_TYPE_TO_THEME_TYPE: dict[str, str] = {
    "top": THEME_TOP_BRIDGE,
    "top-bridge": THEME_TOP_BRIDGE,
    "top_bridge": THEME_TOP_BRIDGE,
    "bottom": THEME_BOTTOM_BRIDGE,
    "bottom-bridge": THEME_BOTTOM_BRIDGE,
    "bottom_bridge": THEME_BOTTOM_BRIDGE,
    "vertical": THEME_VERTICAL_BRIDGE,
    "vertical-bridge": THEME_VERTICAL_BRIDGE,
    "vertical_bridge": THEME_VERTICAL_BRIDGE,
}


def relation_name_for_label(label_node: Any) -> str:
    """Map a Slipnet label node (or ``None``) to a bare theme relation name.

    ``None`` — an unlabelled link, or no link at all — maps to ``diff``,
    matching the Scheme's ``#f`` relation.
    """
    if label_node is None:
        return RELATION_DIFFERENT
    name = getattr(label_node, "name", label_node)
    return _NODE_RELATIONS.get(name, RELATION_DIFFERENT)


def relation_node_name(relation: str | None) -> str | None:
    """Map a bare theme relation name back to its Slipnet node name.

    Returns ``None`` for ``diff`` (and for unknown relations), because the
    "different" relation is the absence of a concept and so has no node.
    """
    if relation is None:
        return None
    return _RELATION_NODES.get(relation)


class Theme:
    """A single theme — an activated pattern along a conceptual dimension."""

    def __init__(
        self,
        theme_type: str,
        dimension: str,
        relation: str | None,
    ) -> None:
        self.theme_type = theme_type
        self.dimension = dimension
        self.relation = relation
        #: One signed activation in [-100, +100].  §4.2: "each theme in the Themespace
        #: has an activation level ranging between -100 and +100.  (There is no
        #: effective difference between a theme having an activation level of zero and
        #: the theme not existing in the Themespace.)"  Scheme: ``make-generic-theme``
        #: (``themes.ss:574``) holds exactly this one value.
        #:
        #: The sign says which side of its idea the theme is on, and a theme stays on
        #: the side it is on: ``activation-function`` (``themes.ss:456-459``) branches
        #: on the sign and clips to [0, 100] or [-100, 0] accordingly, so cluster
        #: dynamics move a theme toward its own pole or toward zero.  A theme changes
        #: sign when it is clamped.
        self.activation: float = 0.0
        self.frozen: bool = False
        self._net_input_buffer: float = 0.0

    @property
    def is_positive(self) -> bool:
        return self.activation > 0

    @property
    def is_negative(self) -> bool:
        return self.activation < 0

    def boost(self, factor: float, boost_amount: float = 7.0) -> None:
        """Boost activation by a factor.

        Scheme: themes.ss theme-boost-amount = 7.

        A boost is always toward the positive pole and clips at zero
        (``themes.ss:674-679`` applies ``clip-positive``), so the Workspace pushing on a
        negatively-activated theme drives it toward zero rather than accumulating
        opposing activation alongside its own.

        A frozen theme is not boosted (``themes.ss:674-679``:
        ``(if* (not (tell self 'frozen?)) ...)``).  Without this a clamped theme erodes
        under ordinary Workspace pressure — measured: a theme clamped at −100 reached 0
        after 20 full-strength boosts — which would make a clamp a suggestion rather
        than a clamp.  ``Themespace.boost_theme`` applies the cluster half of the
        Scheme's own-or-cluster test.
        """
        if self.frozen:
            return
        self.activation = _clip_positive(
            round(self.activation + factor / 100.0 * boost_amount)
        )

    def clear_net_input_buffer(self) -> None:
        """Scheme: ``clear-net-input-buffer`` (``themes.ss:655-657``).

        The first of ``spread-activation``'s three passes.  Separated from the
        accumulation so that no theme can read a buffer left over from the last step.
        """
        self._net_input_buffer = 0.0

    def clamp(self, value: float) -> None:
        """Freeze this theme at *value*.

        Scheme: ``set-activation`` (``themes.ss:680-682``) followed by freezing the
        cluster.  A clamp assigns the signed activation outright, which is how a theme
        crosses from one pole to the other.
        """
        self.frozen = True
        self.activation = value

    def unclamp(self) -> None:
        self.frozen = False

    def __repr__(self) -> str:
        return (
            f"Theme({self.theme_type}, {self.dimension}:{self.relation}, "
            f"act={self.activation:.0f})"
        )


class ThemeCluster:
    """A cluster of themes for one (theme_type, dimension) pair."""

    def __init__(
        self,
        theme_type: str,
        dimension: str,
        valid_relations: list[str],
    ) -> None:
        self.theme_type = theme_type
        self.dimension = dimension
        self.themes: list[Theme] = [
            Theme(theme_type, dimension, rel) for rel in valid_relations
        ]
        self.frozen: bool = False

    def get_max_positive_theme_activation(self) -> float:
        """The strongest positive activation anywhere in this cluster.

        Scheme: ``get-max-positive-theme-activation`` on a cluster
        (themes.ss:489-490), over ``get-positive-activation``, which is
        ``(max 0 activation)`` (themes.ss:640) — so a cluster carrying only
        negative themes reports 0 rather than a negative number.
        """
        return max([0.0] + [t.activation for t in self.themes])

    def pick_positive_theme(self, rng: Any) -> Theme | None:
        """Choose one theme from this cluster, weighted by positive activation.

        Scheme: ``pick-positive-theme`` (themes.ss:491-492).  Negative themes
        carry weight zero, so they are unreachable whenever any theme in the
        cluster is positive — which is the only situation a thematic scout admits
        a cluster in.  §4.1.2: scouting on negative themes would look for
        structures that are "not LettCtgy:identity" or whatever, and the Scheme
        rejects that at themes.ss:771-775.
        """
        if not self.themes:
            return None
        return rng.weighted_pick(
            self.themes, [max(0.0, t.activation) for t in self.themes]
        )

    def get_dominant_theme(self, margin: float = 90.0) -> Theme | None:
        """A theme is dominant if it leads its cluster by more than *margin*.

        Scheme: ``update-dominant-theme`` (themes.ss:503-518).  All themes are
        ranked by *absolute* activation; the leader must itself be positively
        activated, and must beat the runner-up by strictly more than the margin.

        Ranking on absolute activation matters: a strongly negative theme in the
        cluster blocks dominance, which is the point of negatively clamping a
        theme-pattern during a snag response (§4.5.2).
        """
        if not self.themes:
            return None
        ranked = sorted(self.themes, key=lambda t: abs(t.activation), reverse=True)
        top = ranked[0]
        if top.activation <= 0:
            return None
        runner_up = abs(ranked[1].activation) if len(ranked) > 1 else 0.0
        if abs(top.activation) - runner_up > margin:
            return top
        return None

    def get_theme(self, relation: str | None) -> Theme | None:
        for t in self.themes:
            if t.relation == relation:
                return t
        return None

    def spread_activation(self, meta: MetadataProvider) -> None:
        """Intra-cluster activation spreading.

        Scheme: themes.ss propagation function.
        """
        if self.frozen:
            return

        decay = meta.get_param("theme_decay_amount", 25)
        nn_weight = meta.get_formula_coeff("theme_intra_cluster_neg_to_neg_weight")
        np_weight = meta.get_formula_coeff("theme_intra_cluster_neg_to_pos_weight")
        pn_weight = meta.get_formula_coeff("theme_intra_cluster_pos_to_neg_weight")
        pp_weight = meta.get_formula_coeff("theme_intra_cluster_pos_to_pos_weight")
        self_weight = meta.get_formula_coeff("theme_intra_cluster_self_weight")
        spread_amount = meta.get_param("theme_spread_amount", 20)

        n_relations = max(1, len(self.themes))
        sensitivity = meta.get_formula_coeff("theme_net_effect_default_sensitivity")
        alpha = sensitivity * (1.0 / 50.0) * (1.0 / n_relations)

        # ``themes.ss:520-527`` is three passes over the cluster, not one:
        #
        #     (for* each theme in themes do (tell theme 'clear-net-input-buffer))
        #     (for* each theme in themes do (tell theme 'spread-activation))
        #     (for* each theme in themes do (tell theme 'update-activation))
        #
        # so every net input is computed from the activations as they stood at the
        # *start* of the step — Jacobi, not Gauss-Seidel.  Updating each theme at the end
        # of its own iteration, so that later themes in the same cluster read already-
        # updated neighbours, is a different dynamical system: same fixed points,
        # different trajectories, and a result that depends on the order of
        # ``self.themes``.  Integer rounding hides the difference while every theme in a
        # cluster is positive, and stops hiding it as soon as one is negative — which is
        # precisely the jootsing regime, where a negative pattern has been clamped.
        #
        # ``Theme._net_input_buffer`` is the Scheme's ``net-input-buffer``; the snapshot
        # below is what makes the second pass read only pre-update values.
        snapshot = [theme.activation for theme in self.themes]

        for index, target in enumerate(self.themes):
            target.clear_net_input_buffer()
            if target.frozen:
                continue

            target_activation = snapshot[index]
            net_input = -decay  # Decay

            # Self-excitation
            if target_activation > 0:
                net_input += target_activation * (self_weight / 100.0)

            # Inter-theme propagation
            for source_index, source_activation in enumerate(snapshot):
                if source_index == index:
                    continue
                if source_activation == 0:
                    continue

                # Select weight based on signs
                if source_activation < 0 and target_activation < 0:
                    weight = nn_weight
                elif source_activation < 0 and target_activation >= 0:
                    weight = np_weight
                elif source_activation >= 0 and target_activation < 0:
                    weight = pn_weight
                else:
                    weight = pp_weight

                net_input += abs(source_activation) * (weight / 100.0)

            target._net_input_buffer = net_input

        # Third pass: apply.  A frozen theme keeps its activation (``themes.ss:670-672``
        # guards ``update-activation`` on ``frozen?``) but has still acted as a source.
        for index, target in enumerate(self.themes):
            if target.frozen:
                continue
            # ``activation-function`` (``themes.ss:456-459``): branch on the sign of the
            # theme's own activation.  Exciting a negative theme pushes it toward -100;
            # inhibiting it pulls it toward zero.  The branch reads ``snapshot`` because
            # this is a Jacobi step — every theme updates from the same pre-step state.
            net_effect = round(spread_amount * math.tanh(alpha * target._net_input_buffer))
            if snapshot[index] >= 0:
                target.activation = _clip_positive(target.activation + net_effect)
            else:
                target.activation = _clip_negative(target.activation - net_effect)
            target._net_input_buffer = 0.0

    def __repr__(self) -> str:
        return f"ThemeCluster({self.theme_type}, {self.dimension}, {len(self.themes)} themes)"


class Themespace:
    """The full Themespace — all theme clusters."""

    def __init__(self, meta: MetadataProvider) -> None:
        self.clusters: list[ThemeCluster] = []
        self.meta = meta

        # Build clusters from theme dimension specs
        for dim_spec in meta.theme_dimensions:
            for theme_type in ALL_THEME_TYPES:
                cluster = ThemeCluster(
                    theme_type=theme_type,
                    dimension=dim_spec.slipnet_node,
                    valid_relations=dim_spec.valid_relations,
                )
                self.clusters.append(cluster)

        # Which theme types are meaningful for the current mode.  Bottom themes
        # only exist when a fourth (answer) string exists.
        # Scheme: ``get-possible-theme-types`` (themes.ss:132-135).
        self.possible_theme_types: list[str] = [
            THEME_TOP_BRIDGE,
            THEME_VERTICAL_BRIDGE,
        ]

        # Which theme types are *currently exerting thematic pressure*.  Empty
        # by default: "Most of the time, therefore, themes behave as passive
        # representational structures" (§4.1.2).  Pressure is switched on
        # deliberately, by clamping a pattern.
        # Scheme: ``active-theme-types`` (themes.ss:53), initialised to '().
        self.active_theme_types: list[str] = []

        # Numeric substrate (WP4.5), resolved on first spread.  ``_UNRESOLVED``
        # rather than ``None`` because "no backend" is itself a resolved answer.
        self._numeric: Any = _UNRESOLVED
        self._numeric_layout: Any = None
        self._numeric_params: Any = None

    def set_justify_mode(self, enabled: bool) -> None:
        if enabled:
            self.possible_theme_types = list(ALL_THEME_TYPES)
        else:
            self.possible_theme_types = [
                THEME_TOP_BRIDGE,
                THEME_VERTICAL_BRIDGE,
            ]
        # Pressure can only be exerted by a type the mode allows.
        self.active_theme_types = [
            tt for tt in self.active_theme_types if tt in self.possible_theme_types
        ]

    # ------------------------------------------------------------------
    # Thematic pressure  (Scheme: themes.ss:141-166)
    # ------------------------------------------------------------------

    def thematic_pressure_on(self, types: list[str] | None = None) -> None:
        """Turn thematic pressure on, for *types* or for every possible type."""
        if types is None:
            self.active_theme_types = list(self.possible_theme_types)
            return
        for tt in types:
            if tt in self.possible_theme_types and tt not in self.active_theme_types:
                self.active_theme_types.append(tt)

    def thematic_pressure_off(self, types: list[str] | None = None) -> None:
        """Turn thematic pressure off, for *types* or entirely."""
        if types is None:
            self.active_theme_types = []
            return
        self.active_theme_types = [
            tt for tt in self.active_theme_types if tt not in types
        ]

    def get_active_themes(self, theme_type: str) -> list[Theme]:
        """Themes of *theme_type* that are currently exerting pressure.

        Returns ``[]`` when pressure is off for that type — which is what makes
        thematic influence on structure strength a no-op in the normal case.
        Scheme: ``get-active-themes`` (themes.ss:181-186).
        """
        if theme_type not in self.active_theme_types:
            return []
        return [
            t
            for c in self.clusters
            if c.theme_type == theme_type
            for t in c.themes
        ]

    def get_positive_themes(self, bridge_type: str) -> list[Theme]:
        """Positively-activated themes of *bridge_type* that exert pressure.

        Thematic-bridge-scouts "pay attention only to positively-activated
        themes in the Themespace" (§4.1.2, p.144).
        """
        tt = _BRIDGE_TYPE_TO_THEME_TYPE.get(bridge_type, bridge_type)
        return [t for t in self.get_active_themes(tt) if t.activation > 0]

    def _numeric_backend(self) -> Any:
        """The substrate for intra-cluster dynamics, or ``None`` for the loops.

        Sized on the theme count rather than the cluster count, because that is
        the quantity the arithmetic is proportional to.  With 27 clusters of at
        most four themes it is 81 today, far below any threshold at which
        vectorising pays, so under the default policy this returns ``None`` — the
        substrate is here because the theme vocabulary grows with the conceptual
        dimensions the architecture tracks, and later phases grow it a long way.
        """
        if self._numeric is not _UNRESOLVED:
            return self._numeric
        backend = select_backend(sum(len(c.themes) for c in self.clusters))
        self._numeric = backend
        if backend is not None:
            self._numeric_layout = ThemeLayout.from_themespace(self)
            self._numeric_params = ThemeParams.from_metadata(self.meta)
        return backend

    def spread_activation(self) -> None:
        """Spread activation within all clusters."""
        backend = self._numeric_backend()
        if backend is None:
            for cluster in self.clusters:
                cluster.spread_activation(self.meta)
            return

        layout = self._numeric_layout
        state = ThemeState.from_themespace(self, layout)
        backend.spread_themes(layout, state, self._numeric_params)
        state.apply_to_themespace(self, layout)

    def get_thematic_pressure(self, bridge_type: str) -> dict[str, Any]:
        """Get dominant themes for a bridge type."""
        type_map = {
            "top": THEME_TOP_BRIDGE,
            "bottom": THEME_BOTTOM_BRIDGE,
            "vertical": THEME_VERTICAL_BRIDGE,
        }
        tt = type_map.get(bridge_type)
        if tt is None or tt not in self.active_theme_types:
            return {}

        pressure: dict[str, Any] = {}
        margin = self.meta.get_param("dominant_theme_margin", 90)
        for cluster in self.clusters:
            if cluster.theme_type != tt:
                continue
            dom = cluster.get_dominant_theme(margin)
            if dom is not None:
                pressure[cluster.dimension] = dom.relation
        return pressure

    def get_dominant_theme_pattern(self, bridge_type: str) -> list:
        """Return the dominant theme pattern for a bridge type as a list.

        Scheme: themes.ss ``get-dominant-theme-pattern``.
        Returns ``[bridge_type, (dimension, relation), ...]`` matching the
        Scheme list format used by rules, justification, and jootsing.
        """
        type_map = {
            "top": THEME_TOP_BRIDGE,
            "top-bridge": THEME_TOP_BRIDGE,
            "top_bridge": THEME_TOP_BRIDGE,
            "bottom": THEME_BOTTOM_BRIDGE,
            "bottom-bridge": THEME_BOTTOM_BRIDGE,
            "bottom_bridge": THEME_BOTTOM_BRIDGE,
            "vertical": THEME_VERTICAL_BRIDGE,
            "vertical-bridge": THEME_VERTICAL_BRIDGE,
            "vertical_bridge": THEME_VERTICAL_BRIDGE,
        }
        tt = type_map.get(bridge_type, bridge_type)
        margin = self.meta.get_param("dominant_theme_margin", 90)
        entries: list[tuple[str, str | None]] = []
        for cluster in self.clusters:
            if cluster.theme_type != tt:
                continue
            dom = cluster.get_dominant_theme(margin)
            if dom is not None:
                entries.append((cluster.dimension, dom.relation))
        return [tt] + entries

    def save_current_state(self) -> None:
        """Put the live Themespace aside so a past pattern can be displayed over it.

        Scheme: ``save-current-state`` / ``get-partial-state`` (``themes.ss:67-101``).
        Every event and every stored answer in MetaCat can be *displayed*, which means
        clearing the Themespace and imposing that episode's own theme-pattern
        (``trace.ss:415-420``, ``trace.ss:809``, ``memory.ss:275-277``).  Since that
        overwrites what the program is currently thinking, the live state is saved first
        and put back when the user is done looking (``restore_current_state``).
        """
        self._saved_state = [
            [(theme.activation, theme.frozen) for theme in cluster.themes]
            for cluster in self.clusters
        ]
        self._saved_frozen = [cluster.frozen for cluster in self.clusters]
        self._saved_active_types = list(self.active_theme_types)

    def restore_current_state(self) -> bool:
        """Put back what ``save_current_state`` set aside.  Scheme: ``themes.ss:67-101``."""
        saved = getattr(self, "_saved_state", None)
        if saved is None:
            return False
        for cluster, cluster_state, frozen in zip(
            self.clusters, saved, self._saved_frozen
        ):
            cluster.frozen = frozen
            for theme, (act, theme_frozen) in zip(cluster.themes, cluster_state):
                theme.activation = act
                theme.frozen = theme_frozen
        self.active_theme_types = list(self._saved_active_types)
        self._saved_state = None
        return True

    @property
    def displaying_past_state(self) -> bool:
        """Is a past episode currently imposed over the live Themespace?"""
        return getattr(self, "_saved_state", None) is not None

    def get_current_pattern(self) -> dict[str, dict[str, str | None]]:
        """Dominant themes per theme type, regardless of thematic pressure.

        This is a read-only view of what the program currently believes, used
        for answer descriptions and for the UI, so it spans the *possible*
        theme types rather than the ones exerting pressure.
        """
        margin = self.meta.get_param("dominant_theme_margin", 90)
        pattern: dict[str, dict[str, str | None]] = {}
        for tt in self.possible_theme_types:
            pattern[tt] = {}
            for cluster in self.clusters:
                if cluster.theme_type != tt:
                    continue
                dom = cluster.get_dominant_theme(margin)
                if dom:
                    pattern[tt][cluster.dimension] = dom.relation
        return pattern

    def get_max_positive_theme_activation(
        self, theme_type: str | None = None
    ) -> float:
        """Maximum positive activation, over one theme type or over all active ones.

        Scheme: ``get-max-positive-theme-activation`` (themes.ss:248-250), whose
        argument is a theme type *or a list* of them.  The no-argument form here
        stands for the list the coderack passes — the active bridge theme types
        (coderack.ss:509-514) — which is why it filters on pressure and the
        one-type form does not: a thematic scout has already chosen its type and
        only chose among active ones (themes.ss:755-768).
        """
        max_act = 0.0
        for cluster in self.clusters:
            if theme_type is None:
                if cluster.theme_type not in self.active_theme_types:
                    continue
            elif cluster.theme_type != theme_type:
                continue
            for theme in cluster.themes:
                if theme.activation > max_act:
                    max_act = theme.activation
        return max_act

    def get_active_bridge_theme_types(self) -> list[str]:
        """The bridge theme types currently exerting pressure.

        Scheme: ``get-active-bridge-theme-types`` (themes.ss:137-140).  Every
        theme type Petacat has is a bridge theme type, so this is the active list
        in the Scheme's own iteration order — top, bottom, vertical — rather than
        the order in which pressure happened to be switched on, so that the
        thematic scout's weighted choice does not depend on clamp history.
        """
        return [tt for tt in ALL_THEME_TYPES if tt in self.active_theme_types]

    def get_clusters(self, theme_type: str) -> list[ThemeCluster]:
        """Every cluster of *theme_type*.  Scheme: ``get-clusters`` (themes.ss:190-194)."""
        tt = _BRIDGE_TYPE_TO_THEME_TYPE.get(theme_type, theme_type)
        return [c for c in self.clusters if c.theme_type == tt]

    def has_thematic_pressure(self, types: list[str] | None = None) -> bool:
        """Is thematic pressure currently switched on?

        Scheme: ``thematic-pressure?`` (themes.ss:143-148).  Note this asks
        whether pressure is *enabled*, not whether any theme is dominant.
        """
        if types is None:
            return bool(self.active_theme_types)
        return all(tt in self.active_theme_types for tt in types)

    def boost_theme(
        self,
        theme_type: str,
        dimension: str,
        relation: str | None,
        factor: float,
    ) -> None:
        """Boost a specific theme.

        A frozen *cluster* receives nothing at all: ``add-theme-if-possible``
        (``themes.ss:369-387``) returns ``#f`` for one, so ``boost-themes`` never
        reaches the theme.  Together with the check in ``Theme.boost`` this is the
        Scheme's own-or-cluster ``frozen?`` (``themes.ss:645``).
        """
        for cluster in self.clusters:
            if cluster.theme_type == theme_type and cluster.dimension == dimension:
                if cluster.frozen:
                    return
                theme = cluster.get_theme(relation)
                if theme:
                    boost_amt = self.meta.get_param("theme_boost_amount", 7)
                    theme.boost(factor, boost_amt)
                return

    def clamp_negative_pattern(
        self,
        pattern: dict[str, str],
        theme_type: str = THEME_VERTICAL_BRIDGE,
    ) -> None:
        """Clamp a negative theme pattern (inhibit a stuck interpretation).

        Clamping a pattern automatically turns thematic pressure on for that
        theme type (§4.2: "the clamping of theme activations in the Themespace
        automatically turns on thematic pressure").
        """
        clamped = False
        for cluster in self.clusters:
            if cluster.theme_type != theme_type:
                continue
            if cluster.dimension in pattern:
                theme = cluster.get_theme(pattern[cluster.dimension])
                if theme:
                    theme.clamp(-100.0)
                    clamped = True
        if clamped:
            self.thematic_pressure_on([theme_type])

    def spread_activation_to_slipnet(self, slipnet: Any, rng: Any) -> None:
        """Spread activation from active themes to slipnet nodes.

        Scheme: themes.ss:725-731, called from slipnet.ss:379-380.
        Each active theme stochastically activates its dimension node
        (probability = (|activation|/100)^3) and its relation node
        (probability = (activation/100)^3).
        """
        workspace_activation = 100  # %workspace-activation%

        for cluster in self.clusters:
            if cluster.theme_type not in self.active_theme_types:
                continue
            for theme in cluster.themes:
                if theme.activation == 0:
                    continue

                # Activate dimension node: probability = (|activation|/100)^3
                abs_prob = (abs(theme.activation) / 100.0) ** 3
                if rng.prob(abs_prob):
                    dim_node = slipnet.nodes.get(theme.dimension)
                    if dim_node and not dim_node.frozen:
                        dim_node.activation_buffer += workspace_activation

                # Activate relation node: probability = (activation/100)^3.
                # ``diff`` has no node — the "different" relation is the absence
                # of a concept — so it contributes nothing here.
                if theme.activation > 0:
                    rel_node_name = relation_node_name(theme.relation)
                    if rel_node_name is None:
                        continue
                    rel_prob = (theme.activation / 100.0) ** 3
                    if rng.prob(rel_prob):
                        rel_node = slipnet.nodes.get(rel_node_name)
                        if rel_node and not rel_node.frozen:
                            rel_node.activation_buffer += workspace_activation

    def unclamp_all(self) -> None:
        """Release every clamp and switch thematic pressure back off."""
        for cluster in self.clusters:
            cluster.frozen = False
            for theme in cluster.themes:
                theme.unclamp()
        self.thematic_pressure_off()

    def reset(self) -> None:
        for cluster in self.clusters:
            cluster.frozen = False
            for theme in cluster.themes:
                theme.activation = 0.0
                theme.frozen = False
        self.thematic_pressure_off()

    def __repr__(self) -> str:
        active = sum(
            1
            for c in self.clusters
            for t in c.themes
            if t.activation != 0
        )
        return f"Themespace({len(self.clusters)} clusters, {active} active themes)"


# ---------------------------------------------------------------------------
# Thematic bridge scouting  (Scheme: themes.ss:750-1030)
#
# The third realization of thematic pressure (§4.1.2): a thematic-bridge-scout
# looks for a bridge satisfying a *conjunction* of themes.  The dissertation's
# example is exact — "if the top themes Letter-Category: identity and
# String-Position: different are both active, thematic-scout codelets will tend
# to look for potential bridges between objects in the initial and modified
# strings having the same letter-category but different string positions".  One
# theme at a time cannot express that, and the crosswise mapping of §2.4.5 is
# precisely a conjunction of themes.
#
# These are free functions taking their collaborators explicitly, in the manner
# of ``jootsing.check_progress``, so the codelet body stays thin orchestration
# and the decisions are testable without an engine.
# ---------------------------------------------------------------------------


def bridge_type_for_theme_type(theme_type: str) -> str:
    """``top_bridge`` -> ``top``.  Scheme: ``theme-type->bridge-type`` (themes.ss:735-740)."""
    return {
        THEME_TOP_BRIDGE: "top",
        THEME_BOTTOM_BRIDGE: "bottom",
        THEME_VERTICAL_BRIDGE: "vertical",
    }[theme_type]


def bridge_orientation(bridge_type: str) -> str:
    """``top``/``bottom`` are horizontal, ``vertical`` is vertical."""
    return "horizontal" if bridge_type in ("top", "bottom") else "vertical"


def pick_theme_type(themespace: Themespace, workspace: Any, rng: Any) -> str | None:
    """Choose which mapping to scout, or ``None`` when no pressure is on.

    Scheme: themes.ss:755-768.  The weight is
    ``max-positive-theme-activation × (100 − mapping-strength)`` — how loudly the
    themes of that type are speaking, times how much room is left in that
    mapping.  A mapping that is already strong is left alone however loud its
    themes are, which is what stops thematic pressure from re-scouting a
    correspondence the program has already settled.
    """
    active = themespace.get_active_bridge_theme_types()
    if not active:
        return None
    weights = [
        themespace.get_max_positive_theme_activation(theme_type)
        * (
            100.0
            - workspace.get_mapping_strength(bridge_type_for_theme_type(theme_type))
        )
        for theme_type in active
    ]
    return rng.weighted_pick(active, weights)


def pick_theme_conjunction(
    themespace: Themespace, theme_type: str, rng: Any
) -> list[Theme]:
    """The set of themes this scout will try to satisfy at once.

    Scheme: themes.ss:776-781.  Each *cluster* is admitted independently with
    probability ``(max-positive-activation/100)²``, and one theme is then drawn
    from each admitted cluster weighted by positive activation.  Squaring makes
    admission steeply selective: a cluster at 50 gets in a quarter of the time, so
    the conjunction is usually short and made of the dimensions that are actually
    shouting.

    Only positive themes take part.  Negative themes "can only influence
    structure strengths" — scouting on them would look for structures that are
    *not* LettCtgy:identity, and "too many spurious bridges get created"
    (themes.ss:771-775).
    """
    themes: list[Theme] = []
    for cluster in themespace.get_clusters(theme_type):
        max_positive = cluster.get_max_positive_theme_activation()
        if not rng.prob((max_positive / 100.0) ** 2):
            continue
        theme = cluster.pick_positive_theme(rng)
        if theme is not None:
            themes.append(theme)
    return themes


def propose_description_based_on_theme(
    obj: Any, theme: Theme, slipnet: Any, rng: Any
) -> Any:
    """Describe *obj* along the theme's dimension, so a bridge becomes expressible.

    Scheme: ``propose-description-based-on-theme`` (themes.ss:955-970).  Returns
    the proposed ``Description``, or ``None`` when the dimension cannot describe
    the object at all.

    §4.1.2: "situations tend to be perceived in terms of the features that one is
    actively paying attention to".  A theme naming a dimension the object has no
    description along is a reason to look for one, not a reason to give up — the
    scout carries on to find the other object either way (themes.ss:830-831).
    """
    from server.engine.descriptions import Description

    dimension = slipnet.nodes.get(theme.dimension)
    if dimension is None:
        return None
    candidates = dimension.get_possible_descriptors(obj)
    if not candidates:
        return None
    # No floor: ``stochastic-pick-by-method possible-descriptors 'get-activation``
    # (``themes.ss:962``) leaves a dormant descriptor unreachable
    # (``utilities.ss:443-448``).
    descriptor = rng.weighted_pick(candidates, [c.activation for c in candidates])
    description = Description(obj, dimension, descriptor)
    description.proposal_level = description.PROPOSED
    descriptor.activate_from_workspace()
    return description


def theme_support_tester(themes: list[Theme]) -> Any:
    """A predicate over object pairs: do these themes bear this pairing out?

    Scheme: ``theme-support-tester`` (themes.ss:1020-1030) — *no* theme may
    conflict and at least one must actively support.  Assumes positively-activated
    themes, as the Scheme's own comment says.

    Note the asymmetry: conflict is a veto and support is a requirement, so a
    pairing that is merely silent on every theme is rejected.  That is what keeps
    thematic pressure a search for evidence rather than a licence.
    """
    from server.engine.bridges import objects_conflict_with_theme, objects_support_theme

    def supported(object1: Any, object2: Any) -> bool:
        if any(objects_conflict_with_theme(object1, object2, t) for t in themes):
            return False
        return any(objects_support_theme(object1, object2, t) for t in themes)

    return supported


def conditions_for_bridge(
    chosen_object: Any, from_object: bool, themes: list[Theme], rng: Any
) -> Any:
    """Build the test a candidate counterpart has to pass.

    Scheme: ``conditions-for-bridge`` (themes.ss:973-1011).  Returns a function of
    the other object which answers:

    * ``None`` — no bridge here can support the themes;
    * ``[]`` — a bridge can, with both groups read as they stand;
    * ``[group, ...]`` — a bridge can, if these spanning groups are read backwards.

    Flipping is only ever considered when *both* objects are string-spanning
    groups, because that is the only case where reversing one is a reinterpretation
    of the same material rather than a different parse: ``>abc>`` read as ``<cba<``
    still covers ``abc``.  §2.4.5's crosswise mapping is reached this way.
    """
    from server.engine.workspace_objects import (
        both_spanning_groups,
        lone_spanning_object,
    )

    supported = theme_support_tester(themes)

    def conditions(other_object: Any) -> list[Any] | None:
        object1 = chosen_object if from_object else other_object
        object2 = other_object if from_object else chosen_object

        if lone_spanning_object(object1, object2):
            return None
        if not both_spanning_groups(object1, object2):
            return [] if supported(object1, object2) else None
        if supported(object1, object2):
            return []

        # Which group to try flipping first is biased against the one already
        # carrying more spanning bridges (themes.ss:986-992): reinterpreting the
        # more-committed group costs more, so it is tried second.
        num1 = object1.get_num_of_spanning_bridges()
        num2 = object2.get_num_of_spanning_bridges()
        if num1 > num2:
            object1_bias = 0.20
        elif num1 < num2:
            object1_bias = 0.80
        else:
            object1_bias = 0.50

        first, second = (
            (object1, object2) if rng.prob(object1_bias) else (object2, object1)
        )
        for candidate in (first, second):
            if candidate is object1:
                pair = (object1.make_flipped_version(), object2)
            else:
                pair = (object1, object2.make_flipped_version())
            if supported(*pair):
                return [candidate]
        if supported(
            object1.make_flipped_version(), object2.make_flipped_version()
        ):
            return [object1, object2]
        return None

    return conditions


def look_for_auxiliary_slippages(bridge: Any, slipnet: Any, rng: Any) -> Any:
    """Drag further slippages along on the coattails of the ones a bridge has.

    Scheme: ``look-for-auxiliary-slippages`` (themes.ss:893-952), called on every
    bridge a thematic scout proposes.  For each slippage ``d1 => d2`` on some
    dimension, look at the concepts ``d1`` is linked to on *other* dimensions; if
    one of them relates to a concept by the same label — the same
    ``opposite``/``successor`` — and both ends can genuinely describe their
    objects, make that slippage too, with probability equal to the label's degree
    of association (§3.4.1's coattail slippage).

    This is how ``leftmost => rightmost`` pulls ``right => left`` after it, and
    §4.1.2 makes the point that thematic pressure is what puts a scout in a
    position to notice.

    Returns a ``Description`` when an object has to be described before it can
    carry the new slippage.  The Scheme builds that description and fizzles
    (themes.ss:933-948): the codelet's useful work was the description, and the
    slippage is left for a later codelet to find.  ``None`` means every slippage
    that could be made was made, in place, on *bridge*.
    """
    from server.engine.concept_mappings import ConceptMapping
    from server.engine.descriptions import Description

    # ``(tell proposed-bridge 'get-slippages)`` (themes.ss:896) — which is the
    # non-symmetric slippages *plus the symmetric ones* (bridges.ss:167-170).
    # Reading only the forward list halved the coattail search: ``rightmost =>
    # leftmost`` is what pulls ``left => right`` after it, and that reverse only
    # exists because the build stored it.
    for slippage in bridge.get_slippages():
        object1 = slippage.object1
        object2 = slippage.object2
        label = slippage.label
        if label is None or object1 is None or object2 is None:
            continue
        cm_type = slippage.description_type1

        linked_instances = [
            link.to_node
            for link in slippage.descriptor1.outgoing_links
            if link.to_node.is_instance and link.to_node.category is not cm_type
        ]
        for node in linked_instances:
            new_cm_type = node.category
            related_node = node.get_related_node(label)
            if new_cm_type is None or related_node is None:
                continue
            if any(
                cm.description_type1 is new_cm_type for cm in bridge.concept_mappings
            ):
                continue
            if not node.possible_descriptor(object1):
                continue
            if not related_node.possible_descriptor(object2):
                continue
            if not rng.prob(label.degree_of_assoc() / 100.0):
                continue

            if not _has_description_type(object1, new_cm_type):
                return Description(object1, new_cm_type, node)
            if not _has_description_type(object2, new_cm_type):
                return Description(object2, new_cm_type, related_node)

            bridge.add_concept_mapping(
                ConceptMapping(
                    new_cm_type,
                    node,
                    new_cm_type,
                    related_node,
                    label=slipnet.get_label(node, related_node),
                    object1=object1,
                    object2=object2,
                )
            )
    return None


def _has_description_type(obj: Any, description_type: Any) -> bool:
    """Scheme: ``description-type-present?`` (workspace-objects.ss:277-279)."""
    return any(
        d.description_type is description_type
        for d in obj.get_all_descriptions()
    )
