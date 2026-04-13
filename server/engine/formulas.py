"""Temperature-dependent math formulas.

Translations from formulas.ss. All magic numbers come from
MetadataProvider.formula_coefficients rather than being hardcoded.

Scheme source: formulas.ss
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG
    from server.engine.workspace import Workspace


def temp_adjusted_probability(
    prob: float, temperature: float, meta: MetadataProvider
) -> float:
    """Adjust a probability based on temperature.

    High temperature pushes probabilities toward 0.5 (random).
    Low temperature preserves the original probability.

    Scheme: formulas.ss:20-29.
    """
    if prob == 0.0:
        return 0.0
    if prob == 1.0:
        return 1.0

    sqrt_base = meta.get_formula_coeff("low_prob_sqrt_base")  # 100
    scale = meta.get_formula_coeff("low_prob_scale_factor")  # 10

    adjustment = (scale - math.sqrt(sqrt_base - temperature)) / sqrt_base

    if prob < 0.5:
        low_prob_factor = max(1.0, math.floor(abs(math.log10(prob))))
        target = 10 ** (low_prob_factor - 1)
        return min(0.5, prob + adjustment * (target - prob))
    else:
        return max(0.5, 1.0 - ((1.0 - prob) + adjustment * prob))


def temp_adjusted_values(
    values: list[float], temperature: float, meta: MetadataProvider
) -> list[float]:
    """Raise values to a temperature-dependent exponent.

    Scheme: formulas.ss:32-35.
    Exponent = (100-T) / scale + base
    Default: scale=30, base=0.5 → exponent = (100-T)/30 + 0.5
    """
    scale = meta.get_formula_coeff("temp_exponent_scale")  # 30
    base = meta.get_formula_coeff("temp_exponent_base")  # 0.5
    exponent = (100.0 - temperature) / scale + base
    return [round(v**exponent) if v > 0 else 0.0 for v in values]


def update_temperature(
    avg_unhappiness: float,
    has_supported_rule: bool,
    meta: MetadataProvider,
) -> float:
    """Compute new temperature from workspace unhappiness and rule state.

    Scheme: formulas.ss:62-79.
    temperature = weighted_average(
        [avg_unhappiness, rule_factor],
        [unhappiness_weight, rule_factor_weight]
    )
    """
    unhappiness_weight = meta.get_formula_coeff("unhappiness_weight")  # 70
    rule_weight = meta.get_formula_coeff("rule_factor_weight")  # 30

    if has_supported_rule:
        rule_factor = meta.get_formula_coeff("rule_factor_with_supported_rule")  # 0
    else:
        rule_factor = meta.get_formula_coeff("rule_factor_no_supported_rule")  # 100

    total_weight = unhappiness_weight + rule_weight
    if total_weight == 0:
        return avg_unhappiness

    return round(
        (avg_unhappiness * unhappiness_weight + rule_factor * rule_weight)
        / total_weight
    )


def weighted_average(values: list[float], weights: list[float]) -> float:
    """Compute a weighted average."""
    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_weight


def sigmoid(x: float, beta: float, midpoint: float) -> float:
    """General-purpose sigmoid on [0, 100] -> [0, 1].

    Scheme: utilities.ss:488-491.
    """
    return 1.0 / (1.0 + math.exp(beta * (midpoint - x) / 25.0))


# ---------------------------------------------------------------------------
# Probability distributions for translation temperature thresholds
# Translations from constants.ss:1038-1074 and formulas.ss:38-59
# ---------------------------------------------------------------------------


class ProbabilityDistribution(NamedTuple):
    """A discrete probability distribution over a set of values.

    Mirrors Scheme ``make-probability-distribution`` in constants.ss:1038-1044.
    Each value is sampled with probability proportional to its frequency.
    """

    values: tuple[int, ...]
    frequencies: tuple[int, ...]


def make_probability_distribution(
    values: list[int], frequencies: list[int]
) -> ProbabilityDistribution:
    """Create a probability distribution from values and relative frequencies.

    Scheme: constants.ss:1038-1044.
    """
    return ProbabilityDistribution(
        values=tuple(values),
        frequencies=tuple(frequencies),
    )


def sample_distribution(dist: ProbabilityDistribution, rng: RNG) -> int:
    """Sample a value from a probability distribution.

    Uses the RNG's weighted_pick for deterministic, reproducible sampling.
    Mirrors Scheme ``(tell distribution 'choose-value)``, which calls
    ``(stochastic-pick values distribution-frequency-values)``.
    """
    return rng.weighted_pick(dist.values, dist.frequencies)


# The 5 translation temperature threshold distributions.
# Higher bond density -> lower expected threshold (translation attempted at
# lower temperatures); lower bond density -> higher expected threshold
# (translation attempted at higher temperatures).
#
# Scheme: constants.ss:1047-1074.

VERY_LOW_TRANSLATION_TEMP_DIST = make_probability_distribution(
    [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    [5, 150, 5, 2, 1, 1, 1, 1, 1, 1],
)

LOW_TRANSLATION_TEMP_DIST = make_probability_distribution(
    [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    [2, 5, 150, 5, 2, 1, 1, 1, 1, 1],
)

MEDIUM_TRANSLATION_TEMP_DIST = make_probability_distribution(
    [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    [1, 2, 5, 150, 5, 2, 1, 1, 1, 1],
)

HIGH_TRANSLATION_TEMP_DIST = make_probability_distribution(
    [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    [1, 1, 2, 5, 150, 5, 2, 1, 1, 1],
)

VERY_HIGH_TRANSLATION_TEMP_DIST = make_probability_distribution(
    [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    [1, 1, 1, 2, 5, 150, 5, 2, 1, 1],
)


def current_translation_temperature_threshold(
    workspace: Workspace,
    rng: RNG,
    meta: MetadataProvider | None = None,
) -> int:
    """Compute a stochastic temperature threshold for rule translation.

    Steps:
    1. Compute bond density = (total bonds) / (total possible bond slots).
       If all three strings are length 1, density is 1.0.
    2. Select one of 5 probability distributions based on density thresholds.
    3. Sample from the distribution to get the temperature threshold.

    Rule translation should only be attempted if the current temperature
    is below the returned threshold.

    Scheme: formulas.ss:38-59.
    """
    i_length = workspace.initial_string.length
    m_length = workspace.modified_string.length
    t_length = workspace.target_string.length

    if i_length == 1 and m_length == 1 and t_length == 1:
        bond_density = 1.0
    else:
        num_bonds = (
            len(workspace.initial_string.bonds)
            + len(workspace.modified_string.bonds)
            + len(workspace.target_string.bonds)
        )
        possible_slots = (i_length - 1) + (m_length - 1) + (t_length - 1)
        bond_density = num_bonds / possible_slots if possible_slots > 0 else 1.0

    # Select distribution based on bond density thresholds.
    # Thresholds from formula_coefficients.json (or defaults matching Scheme).
    if meta is not None:
        very_low = meta.get_formula_coeff("translation_temp_bond_density_very_low")
        low = meta.get_formula_coeff("translation_temp_bond_density_low")
        medium = meta.get_formula_coeff("translation_temp_bond_density_medium")
        high = meta.get_formula_coeff("translation_temp_bond_density_high")
    else:
        very_low = 0.8
        low = 0.6
        medium = 0.4
        high = 0.2

    if bond_density >= very_low:
        dist = VERY_LOW_TRANSLATION_TEMP_DIST
    elif bond_density >= low:
        dist = LOW_TRANSLATION_TEMP_DIST
    elif bond_density >= medium:
        dist = MEDIUM_TRANSLATION_TEMP_DIST
    elif bond_density >= high:
        dist = HIGH_TRANSLATION_TEMP_DIST
    else:
        dist = VERY_HIGH_TRANSLATION_TEMP_DIST

    return sample_distribution(dist, rng)


# ---------------------------------------------------------------------------
# Workspace-structure formulas
# Translations from workspace-structure-formulas.ss
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from server.engine.groups import Group
    from server.engine.slipnet import SlipnetNode


def length_description_probability(
    group: Group,
    plato_length: SlipnetNode,
    temperature: float,
    meta: MetadataProvider,
) -> float:
    """Probability of attaching a length description to a group.

    - Groups longer than 5 objects: probability 0 (never attach).
    - Single-object groups: probability 1 (always attach).
    - Groups of length 2-5: temperature-adjusted probability that decreases
      when the *length* concept is already highly activated (because if
      ``plato-length`` is already active, length descriptions are already
      being tracked and there is less need to redundantly attach them).

    Scheme: workspace-structure-formulas.ss:21-29.

    ``(expt 0.5 (* (^3 group-length) (% (100- (tell plato-length 'get-activation)))))``

    Breakdown of the Scheme helpers used:
      ``%``   → divide by 100
      ``100-`` → subtract from 100
      ``^3``  → cube
    """
    group_length = group.length  # number of constituent objects

    if group_length > 5:
        return 0.0
    if group_length == 1:
        return 1.0

    # Base probability before temperature adjustment:
    #   0.5 ^ (group_length^3 * (100 - activation) / 100)
    activation = plato_length.activation
    exponent = (group_length ** 3) * ((100.0 - activation) / 100.0)
    base_prob = 0.5 ** exponent

    return temp_adjusted_probability(base_prob, temperature, meta)


def single_letter_group_probability(
    group: Group,
    plato_length: SlipnetNode,
    temperature: float,
    meta: MetadataProvider,
) -> float:
    """Probability of forming a single-letter group.

    Based on the group's local support among similar neighbouring groups
    and the activation of the ``plato-length`` concept.  An exponent
    derived from the number of local supporting groups sharpens (or
    flattens) the probability.

    Scheme: workspace-structure-formulas.ss:32-41.
    """
    num_supporting = _count_local_supporting_groups(group)

    if num_supporting == 1:
        exponent = 4
    elif num_supporting == 2:
        exponent = 2
    else:
        exponent = 1

    local_support = _get_group_local_support(group)
    activation = plato_length.activation

    # (% local-support) * (% activation)  →  both divided by 100
    base_prob = ((local_support / 100.0) * (activation / 100.0)) ** exponent

    return temp_adjusted_probability(base_prob, temperature, meta)


def descriptor_support(
    descriptor: SlipnetNode,
    string: object,
) -> float:
    """How much support *descriptor* has among the groups of *string*.

    Returns the percentage (0-100) of groups in the string that have a
    description whose descriptor matches *descriptor*.

    Scheme: workspace-structure-formulas.ss:44-54.
    """
    groups: list = getattr(string, "groups", [])
    num_groups = len(groups)
    if num_groups == 0:
        return 0.0

    num_described = sum(
        1
        for g in groups
        if _has_descriptor(g, descriptor)
    )
    return round(100.0 * num_described / num_groups)


def description_type_support(
    description_type: SlipnetNode,
    string: object,
) -> float:
    """How much support *description_type* has among the objects of *string*.

    Counts what fraction of objects in the string have at least one
    description of the given type, then averages that local fraction with
    the description_type's current activation in the Slipnet.

    Used by ``choose-bond-facet`` to weight the stochastic selection of a
    bond facet.

    Scheme: workspace-structure-formulas.ss:57-67.
    """
    objects: list = getattr(string, "objects", [])
    num_objects = len(objects)
    if num_objects == 0:
        return 0.0

    num_described = sum(
        1
        for obj in objects
        if _has_description_type(obj, description_type)
    )
    local_support = 100.0 * num_described / num_objects
    activation = description_type.activation
    return round((local_support + activation) / 2.0)


# ---------------------------------------------------------------------------
# Private helpers for workspace-structure formulas
# ---------------------------------------------------------------------------


def _has_descriptor(obj: object, descriptor: object) -> bool:
    """Check whether *obj* has any description with the given descriptor.

    Mirrors Scheme ``descriptor-present?`` in workspace-objects.ss.
    """
    for d in getattr(obj, "descriptions", []):
        if getattr(d, "descriptor", None) is descriptor:
            return True
    return False


def _has_description_type(obj: object, description_type: object) -> bool:
    """Check whether *obj* has any description of the given type.

    Mirrors Scheme ``description-type-present?`` in workspace-objects.ss.
    """
    for d in getattr(obj, "descriptions", []):
        if getattr(d, "description_type", None) is description_type:
            return True
    return False


def _count_local_supporting_groups(group: Group) -> int:
    """Count groups in the same string that are disjoint from *group* and
    share the same group_category and direction.

    Mirrors Scheme ``get-num-of-local-supporting-groups`` in groups.ss:347-353.
    """
    if group.string is None:
        return 0

    all_groups: list = getattr(group.string, "groups", [])
    count = 0
    for other in all_groups:
        if other is group:
            continue
        if getattr(other, "group_category", None) is not group.group_category:
            continue
        if getattr(other, "direction", None) is not group.direction:
            continue
        # Disjoint: no overlap in string positions
        if (
            other.right_string_pos < group.left_string_pos
            or other.left_string_pos > group.right_string_pos
        ):
            count += 1
    return count


def _get_group_local_support(group: Group) -> float:
    """Compute the local support for *group*.

    If the Group class provides a ``_local_support`` method (or
    ``get_local_support``), delegate to it.  Otherwise fall back to
    a minimal reimplementation of groups.ss:384-391.
    """
    # Prefer the canonical method on the Group object if available.
    for method_name in ("_local_support", "get_local_support"):
        method = getattr(group, method_name, None)
        if callable(method):
            return method()

    # Fallback inline implementation
    num = _count_local_supporting_groups(group)
    if num == 0:
        return 0.0

    # Density: simplified — use calculate_external_strength or inline
    density = _get_group_local_density(group)
    adjusted_density = 100.0 * math.sqrt(density / 100.0)
    num_factor = min(1.0, 0.6 ** (1.0 / max(1, num ** 3)))
    return round(adjusted_density * num_factor)


def _get_group_local_density(group: Group) -> float:
    """Simplified local density for a group.

    Full implementation requires neighbour traversal; this is a reasonable
    approximation based on the ratio of supporting groups to total objects
    in the string.

    Mirrors Scheme ``get-local-density`` in groups.ss:354-383.
    """
    if getattr(group, "spans_whole_string", lambda: False)():
        return 100.0

    if group.string is None:
        return 100.0

    all_groups: list = getattr(group.string, "groups", [])
    all_objects: list = getattr(group.string, "objects", [])
    other_objects = [o for o in all_objects if o is not group]
    num_objects = len(other_objects)
    if num_objects == 0:
        return 100.0

    num_similar = sum(
        1
        for g in all_groups
        if g is not group
        and getattr(g, "group_category", None) is group.group_category
        and getattr(g, "direction", None) is group.direction
        and (
            g.right_string_pos < group.left_string_pos
            or g.left_string_pos > group.right_string_pos
        )
    )
    return round(100.0 * num_similar / num_objects)
