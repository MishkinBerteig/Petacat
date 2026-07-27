"""Themespace — self-watching mechanism.

Tracks themes (activated patterns along conceptual dimensions) that
characterize the dominant perceptual interpretation being built.

Scheme source: themes.ss
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.slipnet import SlipnetNode

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
        self.activation: float = 0.0
        self.positive_activation: float = 0.0
        self.negative_activation: float = 0.0
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
        """
        amount = round(factor / 100.0 * boost_amount)
        if amount > 0:
            self.positive_activation = min(
                100.0, self.positive_activation + amount
            )
        elif amount < 0:
            self.negative_activation = max(
                -100.0, self.negative_activation + amount
            )
        self.activation = self.positive_activation + self.negative_activation

    def clamp(self, value: float) -> None:
        """Freeze this theme at *value*.

        Both polarities are set, not just the matching one: clamping a theme
        negatively when it already carried positive activation used to leave the
        two cancelling out at zero, so a snag-response clamp had no effect at all.
        """
        self.frozen = True
        if value >= 0:
            self.positive_activation = value
            self.negative_activation = 0.0
        else:
            self.positive_activation = 0.0
            self.negative_activation = value
        self.activation = self.positive_activation + self.negative_activation

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

        for target in self.themes:
            if target.frozen:
                continue

            net_input = -decay  # Decay

            # Self-excitation
            if target.activation > 0:
                net_input += target.activation * (self_weight / 100.0)

            # Inter-theme propagation
            for source in self.themes:
                if source is target:
                    continue
                if source.activation == 0:
                    continue

                # Select weight based on signs
                if source.activation < 0 and target.activation < 0:
                    weight = nn_weight
                elif source.activation < 0 and target.activation >= 0:
                    weight = np_weight
                elif source.activation >= 0 and target.activation < 0:
                    weight = pn_weight
                else:
                    weight = pp_weight

                flow = abs(source.activation) * (weight / 100.0)
                net_input += flow

            # Apply sigmoid scaling
            sensitivity = meta.get_formula_coeff("theme_net_effect_default_sensitivity")  # 1.0
            alpha = sensitivity * (1.0 / 50.0) * (1.0 / n_relations)
            net_effect = round(spread_amount * math.tanh(alpha * net_input))

            # Update activation
            if target.activation >= 0:
                target.positive_activation = max(
                    0.0, min(100.0, target.positive_activation + net_effect)
                )
            else:
                target.negative_activation = max(
                    -100.0, min(0.0, target.negative_activation - net_effect)
                )
            target.activation = target.positive_activation + target.negative_activation

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

    def spread_activation(self) -> None:
        """Spread activation within all clusters."""
        for cluster in self.clusters:
            cluster.spread_activation(self.meta)

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

    def get_max_positive_theme_activation(self) -> float:
        """Maximum positive activation across theme types exerting pressure."""
        max_act = 0.0
        for cluster in self.clusters:
            if cluster.theme_type not in self.active_theme_types:
                continue
            for theme in cluster.themes:
                if theme.activation > max_act:
                    max_act = theme.activation
        return max_act

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
        """Boost a specific theme."""
        for cluster in self.clusters:
            if cluster.theme_type == theme_type and cluster.dimension == dimension:
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
                theme.positive_activation = 0.0
                theme.negative_activation = 0.0
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
