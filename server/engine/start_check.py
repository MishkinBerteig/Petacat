"""The run-start check (configuration-source plan 3.4(c); ``ABSENCE-BEHAVIOUR.md`` I-1, I-2).

A configuration that lacks something is a legitimate experiment, and an omitted concept (a
role, a node, a codelet type) is simply unavailable.  Only what the engine cannot invent
stops a run, and it stops it *at the run's start*, with one message listing everything
missing; never at edit time.

* **I-1** the scalars the engine's *declared read list* requires and the configuration lacks:
  engine parameters and formula coefficients; and the urgency levels the configuration itself
  names: a codelet body that reads a tier (``meta.get_urgency('low')``), every parameter whose
  ``refers_to`` is ``urgency_level``, every posting rule, clamp type and codelet pattern entry
  that names one.  The engine names no tier, so a tier renamed in the rows and in the code that
  names it still runs.
* **I-2** the opening Coderack cannot be filled: ``initial_codelet_types`` names no codelet
  type the configuration has, and no posting rule exists to post one.

``REQUIRED_ENGINE_PARAMETERS`` and ``REQUIRED_FORMULA_COEFFICIENTS`` are the declared read list: every name the engine reads from the
configuration, with no code default (a code default would hide a missing key and bury a second
copy of the value in the code: bug B12).  ``tests/architecture/test_declared_read_list.py``
holds the list to the code: every literal name passed to ``get_param`` or ``get_formula_coeff``
is declared here (a ``RunConstants`` field declared ``formula()`` or ``param()``, in
``run_binding.py``, is a read of the name it carries), no engine module reads a tier by a literal
name (``get_urgency``), and every declared name is in the Metacat Standard Configuration.  The
converse holds too: every name stored in ``engine_params``, ``formula_coefficients`` and
``urgency_levels`` is read (an urgency level also by being named by a codelet body, a posting
rule's ``urgency_level``, a codelet pattern, a level-naming parameter or the clamp background),
so a stored number is the only copy of its value.  A new read adds its name here.

``OPTIONAL_ENGINE_PARAMETERS`` are read with their absence defined (no menu, no labels),
so a configuration without them still runs.

The check reads a handful of dictionary keys and builds nothing, so it costs microseconds.
"""

from __future__ import annotations

import ast
import functools
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from server.engine.roles import VOCABULARY

#: Engine parameters read by ``meta.get_param`` with a literal name, and where.
REQUIRED_ENGINE_PARAMETERS: tuple[tuple[str, str], ...] = (
    ("concept_activation_importance_threshold", "runner.py, builtins.py, trace.py"),
    ("concept_mapping_importance_threshold", "builtins.py"),
    ("default_urgency_level", "posting.py, runner.py"),
    ("distance_threshold", "builtins.py"),
    ("dominant_theme_margin", "themes.py, builtins.py, serialization.py, capture_projection.py"),
    ("flip_first_probability_equal_spanning", "run_binding.py (RunConstants); read in themes.py"),
    ("flip_first_probability_fewer_spanning", "run_binding.py (RunConstants); read in themes.py"),
    ("flip_first_probability_more_spanning", "run_binding.py (RunConstants); read in themes.py"),
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
    ("jootsing_count_scale", "jootsing.py (clamps and snags)"),
    ("manual_clamp_background_level", "run_service.py (a codelet pattern the person clamps)"),
    ("manual_clamp_background_patterns", "run_service.py (which clampable patterns hold a background)"),
    ("max_activation", "numeric/layout.py, jootsing.py, justify.py, run_service.py"),
    ("max_clamp_period", "jootsing.py, runner.py, update_cycle.py"),
    ("max_coderack_size", "coderack.py"),
    ("max_theme_activation", "run_binding.py (RunConstants); read in themes.py, numeric/layout.py, jootsing.py, trace.py, justify.py"),
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
    ("unlisted_clamp_jootsing_factor", "jootsing.py (a clamp type the table lacks)"),
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
    ("perturb_up_probability", "run_binding.py (RunConstants); read in rng.py, splittable_rng.py"),
    ("jootsing_recurring_clamps_min", "jootsing.py"),
    ("jootsing_recurring_snags_min", "jootsing.py"),
    ("jootsing_elapsed_weight_at_start", "jootsing.py"),
    ("justify_retention_string_position", "run_binding.py (RunConstants); read in justify.py"),
    ("justify_retention_non_identity_percent", "run_binding.py (RunConstants); read in justify.py"),
    ("answer_incoherent_theme_abstractness_min", "memory.py"),
    ("answer_incoherent_abstractness_gap_min", "memory.py"),
    ("new_answer_activation", "memory.py"),
    ("group_special_importance", "run_binding.py (RunConstants); read in builtins.py"),
    ("thematic_slippage_importance", "run_binding.py (RunConstants); read in builtins.py"),
    ("uniform_rule_importance", "run_binding.py (RunConstants); read in builtins.py, justify.py"),
    ("perfect_rule_uniformity", "run_binding.py (RunConstants); read in builtins.py, justify.py"),
    ("default_max_codelets", "run_service.py, swarm.py, training_mode_session_service.py, the client's run forms"),
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
    ("bond_degree_of_assoc_scale", "run_binding.py (RunConstants); read in formulas.py"),
    ("coderack_bin_urgency_exponent_divisor", "coderack.py, capture_projection.py"),
    ("coderack_bin_urgency_exponent_offset", "coderack.py, capture_projection.py"),
    ("group_evaluation_tanh_divisor", "formulas.py"),
    ("length_description_base", "formulas.py"),
    ("length_description_max_group_length", "formulas.py"),
    ("low_prob_scale_factor", "formulas.py"),
    ("low_prob_sqrt_base", "formulas.py"),
    ("low_prob_threshold", "formulas.py"),
    ("intra_string_salience_importance_weight", "numeric/layout.py (SalienceWeights)"),
    ("intra_string_salience_unhappiness_weight", "numeric/layout.py (SalienceWeights)"),
    ("inter_string_salience_importance_weight", "numeric/layout.py (SalienceWeights)"),
    ("inter_string_salience_unhappiness_weight", "numeric/layout.py (SalienceWeights)"),
    ("max_raw_importance", "run_binding.py (RunConstants); read in workspace_objects.py"),
    ("probabilistic_activation_exponent", "numeric/layout.py (ActivationParams)"),
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
    ("bond_compatibility_factor_same_type", "run_binding.py (RunConstants); read in bonds.py"),
    ("bond_compatibility_factor_different_type", "run_binding.py (RunConstants); read in bonds.py"),
    ("bond_facet_factor_letter_category", "run_binding.py (RunConstants); read in bonds.py"),
    ("bond_facet_factor_other", "run_binding.py (RunConstants); read in bonds.py"),
    ("local_support_number_factor_base", "run_binding.py (RunConstants); read in bonds.py, groups.py"),
    ("group_length_factor_1", "run_binding.py (RunConstants); read in groups.py"),
    ("group_length_factor_2", "run_binding.py (RunConstants); read in groups.py"),
    ("group_length_factor_3", "run_binding.py (RunConstants); read in groups.py"),
    ("group_length_factor_4_plus", "run_binding.py (RunConstants); read in groups.py"),
    ("group_bond_facet_other_multiplier", "run_binding.py (RunConstants); read in groups.py"),
    ("group_bond_factor_weight_exponent", "run_binding.py (RunConstants); read in groups.py"),
    ("bridge_num_cm_factor_1", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_num_cm_factor_2", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_num_cm_factor_3_plus", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_coherence_factor_coherent", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_coherence_factor_incoherent", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_singleton_letter_mismatch_factor", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_theme_negative_weight_multiplier", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_theme_compatibility_sigmoid_beta", "run_binding.py (RunConstants); read in bridges.py"),
    ("concept_mapping_depth_bonus_exponent", "run_binding.py (RunConstants); read in concept_mappings.py"),
    ("concept_mapping_depth_penalty_exponent", "run_binding.py (RunConstants); read in concept_mappings.py"),
    ("concept_mapping_unlinked_association", "run_binding.py (RunConstants); read in concept_mappings.py"),
    ("enclosed_group_bridge_factor", "run_binding.py (RunConstants); read in workspace_objects.py"),
    ("enclosed_group_importance_factor", "run_binding.py (RunConstants); read in workspace_objects.py"),
    ("edge_object_bond_factor", "run_binding.py (RunConstants); read in workspace_objects.py"),
    ("interior_object_bond_factor", "run_binding.py (RunConstants); read in workspace_objects.py"),
    ("weakness_exponent", "run_binding.py (RunConstants); read in workspace_structures.py"),
    ("description_local_support_1", "run_binding.py (RunConstants); read in descriptions.py"),
    ("description_local_support_2", "run_binding.py (RunConstants); read in descriptions.py"),
    ("description_local_support_3", "run_binding.py (RunConstants); read in descriptions.py"),
    ("description_local_support_4_plus", "run_binding.py (RunConstants); read in descriptions.py"),
    ("perturb_delta_exponent", "run_binding.py (RunConstants); read in rng.py, splittable_rng.py"),
    ("bond_scan_exponent", "run_binding.py (RunConstants); read in builtins.py"),
    ("spanning_bridge_theme_boost_factor", "run_binding.py (RunConstants); read in runner.py, builtins.py"),
    ("slippage_importance_unlabelled_depth", "run_binding.py (RunConstants); read in builtins.py"),
    ("slippage_importance_spanning_term", "run_binding.py (RunConstants); read in builtins.py"),
    ("slippage_importance_weight_dimension_depth", "run_binding.py (RunConstants); read in builtins.py"),
    ("slippage_importance_weight_spanning", "run_binding.py (RunConstants); read in builtins.py"),
    ("slippage_importance_weight_descriptor_depth", "run_binding.py (RunConstants); read in builtins.py"),
    ("slippage_importance_weight_label_depth", "run_binding.py (RunConstants); read in builtins.py"),
    ("bond_facet_choice_local_support_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("bond_facet_choice_activation_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("scout_string_choice_relevance_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("scout_string_choice_unhappiness_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("answer_distance_base", "memory.py"),
    ("answer_distance_differing_theme_weight", "memory.py"),
    ("answer_distance_justification_weight", "memory.py"),
    ("answer_distance_coherence_weight", "memory.py"),
    ("fight_bond_vs_bond_proposer_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_bond_vs_bond_opponent_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_bond_vs_group_proposer_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_bond_vs_bridge_proposer_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_bond_vs_bridge_opponent_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_group_vs_flipped_bond_opponent_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_group_vs_group_proposer_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_group_vs_group_opponent_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_group_vs_bridge_proposer_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_group_vs_bridge_opponent_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_bridge_vs_bond_proposer_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_bridge_vs_bond_opponent_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_bridge_vs_enclosing_group_proposer_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_bridge_vs_enclosing_group_opponent_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_bridge_vs_flipped_group_proposer_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("fight_bridge_vs_flipped_group_opponent_weight", "run_binding.py (RunConstants); read in builtins.py"),
    ("low_prob_min_decade_factor", "run_binding.py (RunConstants); read in formulas.py"),
    ("low_prob_target_offset", "run_binding.py (RunConstants); read in formulas.py"),
    ("low_prob_sqrt_exponent", "run_binding.py (RunConstants); read in formulas.py"),
    ("length_description_over_max_probability", "formulas.py"),
    ("length_description_single_probability", "formulas.py"),
    ("length_description_length_exponent", "formulas.py"),
    ("urgency_ceiling", "formulas.py, coderack.py"),
    ("bond_degree_of_assoc_exponent", "run_binding.py (RunConstants); read in formulas.py, bonds.py"),
    ("bond_degree_of_assoc_ceiling", "run_binding.py (RunConstants); read in bonds.py"),
    ("local_support_density_exponent", "run_binding.py (RunConstants); read in bonds.py, groups.py"),
    ("local_support_number_exponent", "run_binding.py (RunConstants); read in bonds.py, groups.py"),
    ("local_support_number_factor_ceiling", "run_binding.py (RunConstants); read in bonds.py, groups.py"),
    ("bond_local_support_unsupported", "run_binding.py (RunConstants); read in bonds.py"),
    ("bond_local_density_no_string", "run_binding.py (RunConstants); read in bonds.py"),
    ("bond_local_density_spanning", "run_binding.py (RunConstants); read in bonds.py"),
    ("group_bond_factor_no_category", "run_binding.py (RunConstants); read in groups.py"),
    ("group_spanning_external_strength", "run_binding.py (RunConstants); read in groups.py"),
    ("group_local_support_unsupported", "run_binding.py (RunConstants); read in groups.py"),
    ("group_local_density_spanning", "run_binding.py (RunConstants); read in groups.py"),
    ("group_local_density_no_string", "run_binding.py (RunConstants); read in groups.py"),
    ("group_local_density_no_neighbours", "run_binding.py (RunConstants); read in groups.py"),
    ("intra_unhappiness_spanning", "run_binding.py (RunConstants); read in workspace_objects.py"),
    ("intra_unhappiness_unbonded", "run_binding.py (RunConstants); read in workspace_objects.py"),
    ("clamped_salience", "run_binding.py (RunConstants); read in workspace_objects.py, numeric/layout.py, python_backend.py, numpy_backend.py, mlx_backend.py"),
    ("inter_unhappiness_unbridged", "run_binding.py (RunConstants); read in workspace_objects.py"),
    ("thematic_pull_positive_target", "run_binding.py (RunConstants); read in workspace_structures.py, python_backend.py, numpy_backend.py, mlx_backend.py"),
    ("thematic_pull_negative_target", "run_binding.py (RunConstants); read in workspace_structures.py, python_backend.py, numpy_backend.py, mlx_backend.py"),
    ("average_unhappiness_empty", "run_binding.py (RunConstants); read in workspace.py, python_backend.py, numpy_backend.py, mlx_backend.py"),
    ("average_intra_unhappiness_empty", "run_binding.py (RunConstants); read in workspace.py"),
    ("selection_weight_default", "run_binding.py (RunConstants); read in workspace.py"),
    ("mapping_strength_spanning_possible_factor", "run_binding.py (RunConstants); read in workspace.py"),
    ("mapping_strength_maximal_tanh_divisor", "run_binding.py (RunConstants); read in workspace.py"),
    ("activity_age_share_ceiling", "workspace.py"),
    ("concept_mapping_depth_bonus_base", "run_binding.py (RunConstants); read in concept_mappings.py"),
    ("concept_mapping_depth_penalty_base", "run_binding.py (RunConstants); read in concept_mappings.py"),
    ("concept_mapping_full_association", "run_binding.py (RunConstants); read in concept_mappings.py"),
    ("concept_mapping_full_association_strength", "run_binding.py (RunConstants); read in concept_mappings.py"),
    ("concept_mapping_full_association_slippability", "run_binding.py (RunConstants); read in concept_mappings.py"),
    ("concept_mapping_identity_association", "run_binding.py (RunConstants); read in concept_mappings.py"),
    ("bridge_no_mapping_internal_strength", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_internal_strength_ceiling", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_external_strength_ceiling", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_spanning_singleton_external_strength", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_singleton_factor_unpenalised", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_theme_positive_weight_multiplier", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_theme_support_none", "run_binding.py (RunConstants); read in bridges.py"),
    ("bridge_theme_support_unrelated", "run_binding.py (RunConstants); read in bridges.py"),
    ("description_local_support_0", "run_binding.py (RunConstants); read in descriptions.py"),
    ("description_theme_support_none", "run_binding.py (RunConstants); read in descriptions.py"),
    ("description_theme_support_unrelated", "run_binding.py (RunConstants); read in descriptions.py"),
    ("link_length_unset", "run_binding.py (RunConstants); read in slipnet.py"),
    ("rule_support_missing_bridge_strength", "run_binding.py (RunConstants); read in rules.py"),
    ("rule_homogeneity_empty", "rules.py"),
    ("rule_object_description_uniformity_empty", "rules.py"),
    ("rule_change_abstractness_uniformity_empty", "rules.py"),
    ("rule_change_abstractness_scale", "rules.py"),
    ("rule_change_abstractness_midpoint", "rules.py"),
    ("rule_identity_quality", "rules.py"),
    ("rule_trivial_uniformity", "rules.py"),
    ("rule_intrinsic_uniformity_empty", "rules.py"),
    ("rule_extrinsic_uniformity_empty", "rules.py"),
    ("rule_uniformity_perfect", "rules.py"),
    ("rule_identity_abstractness", "rules.py"),
    ("rule_verbatim_abstractness", "rules.py"),
    ("rule_trivial_succinctness", "rules.py"),
    ("rule_succinctness_swap_clause_cost", "rules.py"),
    ("rule_succinctness_clause_cost", "rules.py"),
    ("rule_succinctness_best_cost", "rules.py"),
    ("theme_dimension_node_activation_exponent", "themes.py"),
    ("theme_relation_node_activation_exponent", "themes.py"),
    ("theme_conjunction_admission_exponent", "themes.py"),
    ("clamp_event_strength", "run_binding.py (RunConstants); read in trace.py"),
    ("snag_event_strength", "run_binding.py (RunConstants); read in trace.py"),
    ("bond_event_progress", "run_binding.py (RunConstants); read in trace.py"),
    ("clamp_suppressed_concept_activation", "run_binding.py (RunConstants); read in trace.py"),
    ("coderack_removal_penalty_offset", "coderack.py"),
)

@functools.lru_cache(maxsize=512)
def _tiers_read_by(source: str) -> tuple[str, ...]:
    """The tiers named by ``get_urgency('x')`` calls in one body's source (cached: a body is
    parsed once however often a configuration is checked)."""
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return ()
    found: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get_urgency"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value not in found
        ):
            found.append(node.args[0].value)
    return tuple(found)


def urgency_levels_read_by_bodies(bodies: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    """``{tier: [codelet type, ...]}`` for every tier a codelet body reads by a literal name
    (``meta.get_urgency('low')``), from ``(codelet type, body source)`` pairs.

    The configuration's own code names its tiers, so the run-start check derives the names from
    the bodies in force and no list of them stands in the engine.  A body that does not parse is
    left to fail when it runs."""
    named: dict[str, list[str]] = {}
    for codelet_type, source in bodies:
        for tier in _tiers_read_by(source or ""):
            users = named.setdefault(tier, [])
            if codelet_type not in users:
                users.append(codelet_type)
    return named


#: Vocabulary roles (``roles.VOCABULARY``) the engine cannot run without, and why.  Every
#: other role may be unbound: the concept is then absent, as an absent node is, and a
#: comparison against its ``AbsentName`` is simply false.
REQUIRED_VOCABULARY_ROLES: tuple[tuple[str, str], ...] = (
    tuple(
        (spec.name, "the Trace records events of this type, under the name the run's vocabulary gives it")
        for spec in VOCABULARY
        if spec.name.startswith("event_type.")
    )
    + (
        ("proposal_level.proposed", "a structure is made at this level"),
        ("proposal_level.built", "a structure is built when it reaches this level"),
        ("posting_direction.bottom_up", "the bottom-up posting loop"),
        ("posting_direction.top_down", "the top-down posting loop"),
        ("posting_direction.thematic", "the thematic posting loop"),
    )
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
    named_by_bodies = urgency_levels_read_by_bodies(
        (spec.name, spec.execute_body) for spec in meta.codelet_specs.values()
    )
    for name, users in named_by_bodies.items():
        if name not in levels:
            problems.append(StartProblem(
                "I-1", "urgency level", name,
                ("codelet body " if len(users) == 1 else "codelet bodies ") + ", ".join(users)))
    for parameter in meta.params_referring_to("urgency_level"):
        level = meta.get_param(parameter)
        if level is not None and level not in levels:
            problems.append(StartProblem("I-1", "urgency level", level, parameter))
    for rule in meta.posting_rules:
        if rule.urgency_level is not None and rule.urgency_level not in levels:
            problems.append(
                StartProblem("I-1", "urgency level", rule.urgency_level,
                             f"posting rule '{rule.rule_key or rule.codelet_type}'")
            )
    for clamp_type in meta.clamp_types:
        level = clamp_type.codelet_background_level
        if level is not None and level not in levels:
            problems.append(
                StartProblem("I-1", "urgency level", level, f"clamp type '{clamp_type.name}'")
            )
    for pattern, entries in meta.codelet_patterns.items():
        for _codelet_type, level in entries:
            if level not in levels:
                problems.append(
                    StartProblem("I-1", "urgency level", level, f"codelet pattern '{pattern}'")
                )

    bound = {b.role for b in meta.vocabulary_bindings}
    for role_name, where in REQUIRED_VOCABULARY_ROLES:
        if role_name not in bound:
            problems.append(StartProblem("I-1", "vocabulary role", role_name, where))

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
