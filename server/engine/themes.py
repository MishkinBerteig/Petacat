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
        self.frozen = True
        if value >= 0:
            self.positive_activation = value
        else:
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
        """A theme is dominant if positive and exceeds all others by margin.

        Scheme: themes.ss dominant theme criterion.
        """
        positive = [t for t in self.themes if t.activation > 0]
        if not positive:
            return None
        positive.sort(key=lambda t: abs(t.activation), reverse=True)
        if len(positive) == 1:
            if positive[0].activation >= margin:
                return positive[0]
            return None
        top = positive[0]
        second = positive[1]
        if abs(top.activation) - abs(second.activation) >= margin:
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

        self.active_theme_types: list[str] = [
            THEME_TOP_BRIDGE,
            THEME_VERTICAL_BRIDGE,
        ]

    def set_justify_mode(self, enabled: bool) -> None:
        if enabled:
            self.active_theme_types = list(ALL_THEME_TYPES)
        else:
            self.active_theme_types = [
                THEME_TOP_BRIDGE,
                THEME_VERTICAL_BRIDGE,
            ]

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
        """Get the current theme pattern across all active types."""
        pattern: dict[str, dict[str, str | None]] = {}
        for tt in self.active_theme_types:
            pattern[tt] = {}
            for cluster in self.clusters:
                if cluster.theme_type != tt:
                    continue
                dom = cluster.get_dominant_theme()
                if dom:
                    pattern[tt][cluster.dimension] = dom.relation
        return pattern

    def get_max_positive_theme_activation(self) -> float:
        """Maximum positive activation across all active theme types."""
        max_act = 0.0
        for cluster in self.clusters:
            if cluster.theme_type not in self.active_theme_types:
                continue
            for theme in cluster.themes:
                if theme.activation > max_act:
                    max_act = theme.activation
        return max_act

    def has_thematic_pressure(self) -> bool:
        for tt in self.active_theme_types:
            tt_name = {
                THEME_TOP_BRIDGE: "top",
                THEME_BOTTOM_BRIDGE: "bottom",
                THEME_VERTICAL_BRIDGE: "vertical",
            }[tt]
            if self.get_thematic_pressure(tt_name):
                return True
        return False

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

    def clamp_negative_pattern(self, pattern: dict[str, str]) -> None:
        """Clamp a negative theme pattern (inhibit a stuck interpretation)."""
        for cluster in self.clusters:
            dim = cluster.dimension
            if dim in pattern:
                theme = cluster.get_theme(pattern[dim])
                if theme:
                    theme.clamp(-100.0)

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

                # Activate relation node: probability = (activation/100)^3
                # Only for themes with a relation and positive activation
                if theme.relation is not None and theme.activation > 0:
                    rel_prob = (theme.activation / 100.0) ** 3
                    if rng.prob(rel_prob):
                        rel_node = slipnet.nodes.get(theme.relation)
                        if rel_node and not rel_node.frozen:
                            rel_node.activation_buffer += workspace_activation

    def unclamp_all(self) -> None:
        for cluster in self.clusters:
            cluster.frozen = False
            for theme in cluster.themes:
                theme.unclamp()

    def reset(self) -> None:
        for cluster in self.clusters:
            cluster.frozen = False
            for theme in cluster.themes:
                theme.activation = 0.0
                theme.positive_activation = 0.0
                theme.negative_activation = 0.0
                theme.frozen = False

    def __repr__(self) -> str:
        active = sum(
            1
            for c in self.clusters
            for t in c.themes
            if t.activation != 0
        )
        return f"Themespace({len(self.clusters)} clusters, {active} active themes)"
