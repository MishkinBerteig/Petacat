"""Temperature-dependent math formulas.

Translations from formulas.ss. All magic numbers come from
MetadataProvider.formula_coefficients rather than being hardcoded.

Scheme source: formulas.ss
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider


def temp_adjusted_probability(
    prob: float, temperature: float, meta: MetadataProvider
) -> float:
    """Adjust a probability based on temperature.

    High temperature nudges probabilities toward 0.5 (random); low temperature
    preserves the original probability.  A *small* probability is not dragged
    to 0.5 — it is interpolated toward ``10 ** (1 - low_prob_factor)``, one
    decade above itself, so it stays small.

    Scheme: formulas.ss:20-29::

        ((<= prob 0.5)
         (let ((low-prob-factor (max 1.0 (truncate (abs (log10 prob))))))
           (min 0.5 (+ prob (* (% (10- (sqrt (100- *temperature*))))
                               (- (expt 10 (1- low-prob-factor)) prob))))))
        ((> prob 0.5)
         (max 0.5 (1- (+ (1- prob)
                         (* (% (10- (sqrt (100- *temperature*)))) prob)))))

    Note that Scheme's ``1-`` is *one minus x* (``utilities.ss:500``), not a
    decrement: the interpolation target is ``10^(1 - lpf)`` and the high branch
    is ``1 - ((1 - prob) + adjustment * prob)``.  There is no ``prob = 1.0``
    special case — 1.0 takes the high branch and comes back as
    ``1 - adjustment`` (0.9 at temperature 100).

    Scheme's ``truncate`` and Python's ``floor`` agree here: their argument is
    ``abs(log10(prob))``, which is non-negative.
    """
    if prob == 0.0:
        return 0.0

    sqrt_base = meta.get_formula_coeff("low_prob_sqrt_base")  # 100
    scale = meta.get_formula_coeff("low_prob_scale_factor")  # 10
    threshold = meta.get_formula_coeff("low_prob_threshold")  # 0.5

    adjustment = (scale - math.sqrt(sqrt_base - temperature)) / sqrt_base

    if prob <= threshold:
        low_prob_factor = max(1.0, math.floor(abs(math.log10(prob))))
        target = 10.0 ** (1.0 - low_prob_factor)
        return min(threshold, prob + adjustment * (target - prob))
    else:
        return max(threshold, 1.0 - ((1.0 - prob) + adjustment * prob))


def group_evaluation_probability(
    strength: float, temperature: float, meta: MetadataProvider
) -> float:
    """The group evaluator's own survival curve.

    Scheme: ``group-evaluation-probability`` (``groups.ss:616-619``)::

        (+ (* (% *temperature*) (- (/ 2 (1+ (exp (/ (- x) 5)))) 1))
           (* (1- (% *temperature*)) (% x)))

    which the author's own comment (``groups.ss:607-614``) gives as

        f(x) = T/100 * tanh(x/10) + (1 - T/100) * x/100

    and explains: "Copycat has problems building weak groups in strings such as
    xwyxzy or abijxy, especially in the beginning of a run.  At higher
    temperatures, the probability is strongly boosted toward 1 for all but the
    lowest values of x.  At lower temperatures, the probability approaches a
    linear identity function."

    This is **not** ``temp_adjusted_probability``, and the difference is the
    point of the function: a strength-20 group at T=100 survives here with
    p = 0.96, where the generic curve gives 0.28.  Early group formation — the
    seed of every grouped reading — was being suppressed by a factor of three
    and a half at exactly the temperature the reference deliberately boosts it.
    """
    divisor = meta.get_formula_coeff("group_evaluation_tanh_divisor")  # 5
    t = temperature / 100.0
    return t * (2.0 / (1.0 + math.exp(-strength / divisor)) - 1.0) + (1.0 - t) * (
        strength / 100.0
    )


def bond_degree_of_assoc(bond_category: SlipnetNode, meta: MetadataProvider) -> float:
    """A bond category's degree of association, scaled for urgencies and strengths.

    Scheme: ``bond-degree-of-assoc`` (``bonds.ss:490-492``) —
    ``(min 100 (round (* 11 (sqrt (tell bond-category 'get-degree-of-assoc)))))``.

    ``propose-group`` (``groups.ss:827``) posts its evaluator at this urgency, so
    it is not a bond-only quantity; :meth:`server.engine.bonds.Bond._bond_degree_of_assoc`
    is the same formula reached from the other side.
    """
    degree = getattr(bond_category, "degree_of_assoc", None)
    if degree is None:
        return 0.0
    scale = meta.get_formula_coeff("bond_degree_of_assoc_scale")  # 11
    return min(100.0, round(scale * math.sqrt(max(0.0, degree()))))


# ---------------------------------------------------------------------------
# Exact rounding
# ---------------------------------------------------------------------------
#
# Metacat computes with Scheme's numeric tower: whole numbers, and the ratios of whole
# numbers they make (``(% 75)`` is the exact ``3/4``), stay *exact* until a float enters, and
# its ``round`` (``utilities.ss:251``) of an exact ratio is half-to-even on the exact value.  A
# float product does not reproduce that: ``0.75 * 0.74 * 100`` is ``55.49999999999999`` where
# ``3/4 * 37/50 * 100`` is exactly ``111/2``, which rounds to 56.  Where the Scheme is exact and
# the arithmetic is more than one correctly rounded division of whole numbers, the engine
# rounds through these helpers.  They use whole-number arithmetic only (``as_integer_ratio``
# is exact for an int, a float and a ``Fraction`` alike), so no rational type is involved.


def ratio_of(x: Any) -> tuple[int, int]:
    """The exact value of *x* as ``(numerator, denominator)``, denominator positive."""
    return x.as_integer_ratio()


def ratio_mul(p: tuple[int, int], q: tuple[int, int]) -> tuple[int, int]:
    return p[0] * q[0], p[1] * q[1]


def ratio_add(p: tuple[int, int], q: tuple[int, int]) -> tuple[int, int]:
    return p[0] * q[1] + q[0] * p[1], p[1] * q[1]


def ratio_div(p: tuple[int, int], q: tuple[int, int]) -> tuple[int, int]:
    """``p / q``; ``ZeroDivisionError`` if *q* is zero."""
    if q[0] == 0:
        raise ZeroDivisionError("ratio_div by zero")
    return (p[0] * q[1], p[1] * q[0]) if q[0] > 0 else (-p[0] * q[1], -p[1] * q[0])


def round_ratio(numerator: int, denominator: int) -> int:
    """``numerator / denominator`` rounded half to even, in whole-number arithmetic.

    This is Scheme's ``round`` of an exact ratio (and Python's ``round`` of the same exact
    value), without a float on the way.  *denominator* must not be zero.
    """
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    quotient, remainder = divmod(numerator, denominator)
    twice = 2 * remainder
    if twice > denominator or (twice == denominator and quotient & 1):
        quotient += 1
    return quotient


def round_exact(numerators: Any, denominators: Any = ()) -> int:
    """Round ``prod(numerators) / prod(denominators)`` half to even, exactly.

    Every factor is taken at its exact value, so ``round_exact((100, 75, 74), (100, 100))``
    is Scheme's ``(100* (* (% 75) (% 74)))``, 56.
    """
    num, den = 1, 1
    for x in numerators:
        n, d = ratio_of(x)
        num, den = num * n, den * d
    for x in denominators:
        n, d = ratio_of(x)
        num, den = num * d, den * n
    return round_ratio(num, den)


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


def share_of_ceiling(activation: float, ceiling: float) -> float:
    """``activation / ceiling``: the share of the activation ceiling a node holds.

    Scheme: ``%`` (``utilities.ss``) divides by 100, which here is ``%max-activation%``.  The
    ceiling is configuration (``max_activation``), and Training-Mode learning may set it to 0,
    where the quotient is undefined.  A node under a ceiling of 0 can hold no activation, so
    its share is 0.0.
    """
    return activation / ceiling if ceiling else 0.0


def unfilled_share_of_ceiling(activation: float, ceiling: float) -> float:
    """``(ceiling - activation) / ceiling``: the share of the ceiling a node has not filled.

    Scheme: ``(% (100- activation))``.  Under a ceiling of 0 the node holds nothing, so all of
    the room is unfilled: 1.0, which is also what an absent node (activation 0) gave when the
    ceiling was the literal 100.
    """
    return (ceiling - activation) / ceiling if ceiling else 1.0


def weighted_average(values: list[float], weights: list[float]) -> float:
    """Compute a weighted average."""
    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_weight


def sigmoid(x: float, beta: float, midpoint: float, divisor: float) -> float:
    """General-purpose sigmoid on [0, 100] -> [0, 1].

    Scheme: utilities.ss:488-491.  *divisor* is the coefficient ``sigmoid_divisor``.
    """
    return 1.0 / (1.0 + math.exp(beta * (midpoint - x) / divisor))


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

    - Groups longer than ``length_description_max_group_length`` (5) objects:
      probability 0 (never attach).
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
    max_length = meta.get_formula_coeff("length_description_max_group_length")  # 5
    base = meta.get_formula_coeff("length_description_base")  # 0.5

    if group_length > max_length:
        return 0.0
    if group_length == 1:
        return 1.0

    # Base probability before temperature adjustment:
    #   0.5 ^ (group_length^3 * (100 - activation) / 100)
    activation = plato_length.activation
    ceiling = plato_length.max_activation
    exponent = (group_length ** 3) * unfilled_share_of_ceiling(activation, ceiling)
    base_prob = base ** exponent

    return temp_adjusted_probability(base_prob, temperature, meta)
