"""The run-start check (configuration-source plan 3.4(c); ``ABSENCE-BEHAVIOUR.md`` I-1, I-2).

A configuration that lacks something is a legitimate experiment, and an omitted concept (a
role, a node, a codelet type) is simply unavailable.  Only what the engine cannot invent
stops a run, and it stops it *at the run's start*, with one message listing everything
missing; never at edit time.

* **I-1** the scalars the engine's *declared read list* requires and the configuration lacks:
  engine parameters, formula coefficients, urgency levels (the ones the engine names, the
  one the opening batch names, and the level every codelet pattern entry names).
* **I-2** the opening Coderack cannot be filled: ``initial_codelet_types`` names no codelet
  type the configuration has, and no posting rule exists to post one.

``REQUIRED_ENGINE_PARAMETERS``, ``REQUIRED_FORMULA_COEFFICIENTS`` and
``REQUIRED_URGENCY_LEVELS`` are the declared read list: every name the engine reads from the
configuration, with no code default (a code default would hide a missing key and bury a second
copy of the value in the code: bug B12).  ``tests/architecture/test_declared_read_list.py``
holds the list to the code: every literal name passed to ``get_param``, ``get_formula_coeff``
or ``get_urgency`` is declared here, and every declared name is in the Metacat Standard
Configuration.  A new read adds its name here.

``OPTIONAL_ENGINE_PARAMETERS`` are read with their absence defined (no menu, no labels),
so a configuration without them still runs.

The check reads a handful of dictionary keys and builds nothing, so it costs microseconds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Engine parameters read by ``meta.get_param`` with a literal name, and where.
REQUIRED_ENGINE_PARAMETERS: tuple[tuple[str, str], ...] = (
    ("concept_activation_importance_threshold", "runner.py, builtins.py"),
    ("concept_mapping_importance_threshold", "builtins.py"),
    ("distance_threshold", "builtins.py"),
    ("dominant_theme_margin", "themes.py, builtins.py, serialization.py, capture_projection.py"),
    ("flip_first_probability_equal_spanning", "themes.py"),
    ("flip_first_probability_fewer_spanning", "themes.py"),
    ("flip_first_probability_more_spanning", "themes.py"),
    ("full_activation_threshold", "numeric/layout.py"),
    ("grace_period", "jootsing.py, justify.py"),
    ("group_importance_threshold", "builtins.py"),
    ("initial_clamp_fixed_time", "runner.py"),
    ("initial_codelet_rounds", "runner.py"),
    ("initial_codelet_types", "runner.py"),
    ("initial_codelet_urgency", "runner.py"),
    ("initial_slipnode_clamp_cycles", "runner.py, slipnet.py"),
    ("initial_temperature", "runner.py"),
    ("initially_clamped_slipnodes", "runner.py, slipnet.py"),
    ("intrinsic_link_lengths", "slipnet.py"),
    ("jootsing_count_scale", "jootsing.py"),
    ("max_activation", "numeric/layout.py"),
    ("max_clamp_period", "jootsing.py, runner.py, update_cycle.py"),
    ("max_coderack_size", "coderack.py, coderack_shards.py"),
    ("max_theme_activation", "themes.py, numeric/layout.py, jootsing.py"),
    ("min_shard_capacity", "coderack_shards.py"),
    ("num_coderack_bins", "coderack.py, capture_projection.py"),
    ("reference_update_cycle_length", "slipnet.py"),
    ("rough_count_few_threshold", "workspace.py, posting.py"),
    ("rough_count_some_threshold", "workspace.py, posting.py"),
    ("rule_importance_threshold", "builtins.py, justify.py"),
    ("satisfactory_rule_quality", "jootsing.py"),
    ("self_watching_enabled_default", "runner.py"),
    ("settling_period", "jootsing.py"),
    ("shrunk_link_length_factor", "slipnet.py"),
    ("snag_clamp_temperature", "builtins.py"),
    ("spreading_activation_threshold", "runner.py, run_service.py"),
    ("theme_boost_amount", "themes.py"),
    ("theme_decay_amount", "themes.py, numeric/layout.py"),
    ("theme_spread_amount", "themes.py, numeric/layout.py"),
    ("top_down_slipnodes", "runner.py, update_cycle.py"),
    ("update_cycle_length", "runner.py, slipnet.py, run_service.py, parallel"),
    ("verbatim_rule_probability", "codelet body rule-scout"),
    ("workspace_activation", "themes.py, numeric/layout.py"),
    ("bridge_recruit_urgency_level", "bridges.py"),
    ("expiration_period", "workspace.py"),
    ("justify_retention_identity_percent", "justify.py"),
    ("maximum_rule_line_length", "rule_english.py"),
    ("num_youngest_structures", "workspace.py"),
    ("rule_english_dimension_phrases", "rule_english.py"),
    ("rule_subobjects_abstraction_probability", "rules.py"),
    ("rule_swap_abstraction_probability", "rules.py"),
    ("slippage_ignore_probability", "rules.py"),
)

#: Engine parameters whose absence is defined, so a configuration without them still runs:
#: the Admin view's menu of clampable codelet patterns, and the display names the
#: Themespace state carries.
OPTIONAL_ENGINE_PARAMETERS: tuple[tuple[str, str], ...] = (
    ("clampable_codelet_patterns", "codelet_patterns.py: no menu"),
    ("theme_dimension_labels", "serialization.py: the node's short name"),
    ("theme_relation_labels", "serialization.py: no relation labels"),
)

#: Formula coefficients read by ``meta.get_formula_coeff`` with a literal name, and where.
REQUIRED_FORMULA_COEFFICIENTS: tuple[tuple[str, str], ...] = (
    ("answer_distance_abstractness_divisor", "memory.py"),
    ("answer_distance_rule_difference_weight", "memory.py"),
    ("answer_distance_unique_theme_weight", "memory.py"),
    ("answer_quality_rule_weight", "answers.py, trace.py"),
    ("answer_quality_temperature_weight", "answers.py, trace.py"),
    ("bond_degree_of_assoc_scale", "formulas.py"),
    ("coderack_bin_urgency_exponent_divisor", "coderack.py, capture_projection.py"),
    ("coderack_bin_urgency_exponent_offset", "coderack.py, capture_projection.py"),
    ("group_evaluation_tanh_divisor", "formulas.py"),
    ("length_description_base", "formulas.py"),
    ("length_description_max_group_length", "formulas.py"),
    ("low_prob_scale_factor", "formulas.py"),
    ("low_prob_sqrt_base", "formulas.py"),
    ("low_prob_threshold", "formulas.py"),
    ("rule_abstractness_sigmoid_beta", "rules.py"),
    ("rule_abstractness_sigmoid_midpoint", "rules.py"),
    ("rule_abstractness_weight", "rules.py"),
    ("rule_factor_no_supported_rule", "formulas.py, temperature.py"),
    ("rule_factor_weight", "formulas.py, temperature.py"),
    ("rule_factor_with_supported_rule", "formulas.py, temperature.py"),
    ("rule_succinctness_base_cost", "rules.py"),
    ("rule_succinctness_weight", "rules.py"),
    ("rule_uniformity_adjusted_decay_constant", "rules.py"),
    ("rule_uniformity_clause_type_weight", "rules.py"),
    ("rule_uniformity_extrinsic_obj_desc_exponent", "rules.py"),
    ("rule_uniformity_extrinsic_weight", "rules.py"),
    ("rule_uniformity_intrinsic_weight", "rules.py"),
    ("sigmoid_divisor", "rules.py"),
    ("single_letter_group_exponent_1_supporting", "builtins.py"),
    ("single_letter_group_exponent_2_supporting", "builtins.py"),
    ("single_letter_group_exponent_3_plus_supporting", "builtins.py"),
    ("temp_exponent_base", "formulas.py"),
    ("temp_exponent_scale", "formulas.py"),
    ("theme_intra_cluster_neg_to_neg_weight", "themes.py, numeric/layout.py"),
    ("theme_intra_cluster_neg_to_pos_weight", "themes.py, numeric/layout.py"),
    ("theme_intra_cluster_pos_to_neg_weight", "themes.py, numeric/layout.py"),
    ("theme_intra_cluster_pos_to_pos_weight", "themes.py, numeric/layout.py"),
    ("theme_intra_cluster_self_weight", "themes.py, numeric/layout.py"),
    ("theme_net_effect_alpha_scale", "themes.py, numeric/layout.py"),
    ("theme_net_effect_default_sensitivity", "themes.py, numeric/layout.py"),
    ("theme_relation_default_abstractness", "answers.py"),
    ("unhappiness_weight", "formulas.py, temperature.py"),
    ("bond_compatibility_factor_same_type", "bonds.py"),
    ("bond_compatibility_factor_different_type", "bonds.py"),
    ("bond_facet_factor_letter_category", "bonds.py"),
    ("bond_facet_factor_other", "bonds.py"),
    ("local_support_number_factor_base", "bonds.py, groups.py"),
    ("group_length_factor_1", "groups.py"),
    ("group_length_factor_2", "groups.py"),
    ("group_length_factor_3", "groups.py"),
    ("group_length_factor_4_plus", "groups.py"),
    ("group_bond_facet_other_multiplier", "groups.py"),
    ("group_bond_factor_weight_exponent", "groups.py"),
    ("bridge_num_cm_factor_1", "bridges.py"),
    ("bridge_num_cm_factor_2", "bridges.py"),
    ("bridge_num_cm_factor_3_plus", "bridges.py"),
    ("bridge_coherence_factor_coherent", "bridges.py"),
    ("bridge_coherence_factor_incoherent", "bridges.py"),
    ("bridge_singleton_letter_mismatch_factor", "bridges.py"),
    ("bridge_theme_negative_weight_multiplier", "bridges.py"),
    ("bridge_theme_compatibility_sigmoid_beta", "bridges.py"),
    ("concept_mapping_depth_bonus_exponent", "concept_mappings.py"),
    ("concept_mapping_depth_penalty_exponent", "concept_mappings.py"),
    ("concept_mapping_unlinked_association", "concept_mappings.py"),
    ("enclosed_group_bridge_factor", "workspace_objects.py"),
    ("weakness_exponent", "workspace_structures.py"),
    ("description_local_support_1", "descriptions.py"),
    ("description_local_support_2", "descriptions.py"),
    ("description_local_support_3", "descriptions.py"),
    ("description_local_support_4_plus", "descriptions.py"),
)

#: Engine parameters whose value is the name of an urgency level, which must exist.
LEVEL_NAMING_PARAMETERS: tuple[str, ...] = (
    "initial_codelet_urgency",  # runner.py: the opening batch
    "bridge_recruit_urgency_level",  # bridges.py: the bridge-recruiting codelet
)

#: Urgency levels read by ``meta.get_urgency`` with a literal name, and where.
REQUIRED_URGENCY_LEVELS: tuple[tuple[str, str], ...] = (
    ("extremely_high", "codelet bodies rule-builder, thematic-bridge-scout, jootser"),
    ("high", "codelet bodies rule-scout, rule-evaluator"),
    ("low", "runner.py, update_cycle.py, codelet body rule-scout"),
    ("very_high", "codelet body thematic-bridge-scout"),
    ("very_low", "run_service.py, trace.py (the rule-codelet clamp's background)"),
)


@dataclass(frozen=True)
class StartProblem:
    """One thing a run cannot start without."""

    check: str  # "I-1" or "I-2"
    kind: str
    name: str
    where: str

    def __str__(self) -> str:
        return f"{self.kind} '{self.name}' ({self.where})" if self.name else f"{self.kind} ({self.where})"


class RunStartError(ValueError):
    """The configuration lacks something the engine cannot invent; ``problems`` lists all.

    A ``ValueError`` so the API answers a request that cannot start with a 400 and the message."""

    def __init__(self, problems: tuple[StartProblem, ...]) -> None:
        self.problems = problems
        super().__init__(
            "This configuration cannot start a run; it lacks: "
            + "; ".join(str(p) for p in problems)
        )


def check_run_start(meta: Any) -> tuple[StartProblem, ...]:
    """Everything missing, in a fixed order; empty when the run may start."""
    problems: list[StartProblem] = []

    parameters = meta.params
    for name, where in REQUIRED_ENGINE_PARAMETERS:
        if name not in parameters:
            problems.append(StartProblem("I-1", "engine parameter", name, where))

    coefficients = meta.formula_coefficients
    for name, where in REQUIRED_FORMULA_COEFFICIENTS:
        if name not in coefficients:
            problems.append(StartProblem("I-1", "formula coefficient", name, where))

    levels = meta.urgency_levels
    for name, where in REQUIRED_URGENCY_LEVELS:
        if name not in levels:
            problems.append(StartProblem("I-1", "urgency level", name, where))
    for parameter in LEVEL_NAMING_PARAMETERS:
        level = meta.get_param(parameter)
        if level is not None and level not in levels:
            problems.append(StartProblem("I-1", "urgency level", level, parameter))
    for pattern, entries in meta.codelet_patterns.items():
        for _codelet_type, level in entries:
            if level not in levels:
                problems.append(
                    StartProblem("I-1", "urgency level", level, f"codelet pattern '{pattern}'")
                )

    opening_types = meta.get_param("initial_codelet_types") or []
    if not any(t in meta.codelet_specs for t in opening_types) and not meta.posting_rules:
        problems.append(StartProblem("I-2", "opening Coderack", "", "no codelet can be posted"))

    # One line per distinct problem, order kept.
    return tuple(dict.fromkeys(problems))


def require_run_start(meta: Any) -> None:
    """Raise :class:`RunStartError` naming everything missing; return silently otherwise."""
    problems = check_run_start(meta)
    if problems:
        raise RunStartError(problems)
