"""The vocabulary a posting rule's formulas are written against.

`seed_data/posting_rules.json` states each rule's posting probability as an
expression — ``average_intra_string_unhappiness / 100``, ``temperature / 100``,
``0.4 if within_snag_or_clamp_period else 0.1``.  Those expressions were dead: their
only occurrences in `server/` were the `PostingRuleSpec` field and the two loaders
that populate it, and the engine re-derived every one of them from a switch on the
codelet's *name* (`PHASE 1 PLAN.md` §0.2(a)).  A configuration reading "post nothing,
ever" ran exactly like the shipped one.

The shape here is the one that already exists at `slipnet.py:113-143` for
`descriptor_predicate`, which §0.3 names as the missing pattern: a namespace of names
mapped to callables, a compile step that **raises at load** on a bad expression rather
than failing silently mid-run, and a call site that invokes the result.

**Names resolve lazily.**  A posting formula names one or two quantities, and the
workspace metrics behind them — average unhappiness, minimum mapping strength — walk
every object and every bridge.  Building a dict of all of them for each of the twelve
rules consulted per cycle would compute a dozen metrics to use one.  `PostingContext`
is a `Mapping`, which is what `eval` accepts for its locals, so a name costs its
metric only when the expression actually mentions it, and only once per context.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Callable, Iterator

#: Name -> how to obtain it from a `PostingContext`.
#:
#: Every entry is a quantity `seed_data/posting_rules.json` already writes its formulas
#: against, so the vocabulary is read off the data rather than invented for it.  Adding
#: a name here is what lets a new rule say something the existing ones cannot.
_PRODUCERS: dict[str, Callable[["PostingContext"], Any]] = {
    # -- Workspace unhappiness ------------------------------------------------
    "average_intra_string_unhappiness": (
        lambda c: c.workspace.get_average_intra_string_unhappiness()
    ),
    "average_unhappiness": lambda c: c.workspace.get_average_unhappiness(),
    "max_inter_string_unhappiness": (
        lambda c: c.workspace.get_max_inter_string_unhappiness()
    ),
    "min_mapping_strength": lambda c: c.workspace.get_min_mapping_strength(),
    # -- Rules and answers ----------------------------------------------------
    "possible_rule_types": lambda c: c.workspace.get_possible_rule_types(),
    "supported_top_rule_exists": lambda c: c.workspace.has_supported_rule(),
    # Both halves are asked for, in this order, exactly as the switch this replaced
    # asked for them — `top = get_supported_rules(True)` then
    # `bottom = get_supported_rules(False)`, then `if top or bottom`.
    "supported_rule_exists": lambda c: bool(
        c.workspace.get_supported_rules(True) or c.workspace.get_supported_rules(False)
    ),
    # -- Temperature ----------------------------------------------------------
    "temperature": lambda c: c.ctx.temperature.value,
    # -- Self-watching --------------------------------------------------------
    "max_positive_theme_activation": (
        lambda c: c.ctx.themespace.get_max_positive_theme_activation()
    ),
    "thematic_pressure": lambda c: c.ctx.themespace.has_thematic_pressure(),
    "within_snag_or_clamp_period": lambda c: (
        c.ctx.trace.within_snag_period or c.ctx.trace.within_clamp_period
    ),
    # -- Mode -----------------------------------------------------------------
    "justify_mode": lambda c: c.ctx.justify_mode,
    "self_watching_enabled": lambda c: c.ctx.self_watching_enabled,
    # -- Counts ---------------------------------------------------------------
    "num_possible_rule_types": lambda c: len(c.workspace.get_possible_rule_types()),
    # -- The triggering slipnode, for a top-down rule's urgency ----------------
    #
    # Only a `top_down` rule has one.  Reading either of these from a bottom-up or
    # thematic rule is a mistake in the configuration, and says so rather than
    # resolving to zero and posting everything at the bottom of the rack.
    "conceptual_depth": lambda c: _require_node(c, "conceptual_depth").conceptual_depth,
    "activation": lambda c: _require_node(c, "activation").activation,
}


def _require_node(context: "PostingContext", name: str) -> Any:
    node = context.node
    if node is None:
        raise ValueError(
            f"{name!r} is only available to a top_down rule, which is triggered by a "
            "slipnode; this rule was evaluated without one"
        )
    return node

#: The builtins a *count* formula may use.  `max(1, 2 * num_possible_rule_types)` and
#: `round(10 * max_inter_string_unhappiness / 100)` are the two the shipped rules need,
#: and `round` is Python's — banker's rounding, matching the switch this replaced.
_COUNT_BUILTINS: dict[str, Any] = {
    "__builtins__": {"max": max, "min": min, "round": round, "int": int, "abs": abs}
}

#: Count formulas that index ``count_values`` by a *stochastically blurred* object
#: tally (``rough-num-of-objects``, ``coderack.ss:517-550``) rather than computing a
#: number.  Each call draws from the run's random stream, so which of these runs and
#: when is part of the engine's behaviour and not only of its arithmetic.
_COUNT_BUCKETS: dict[str, Callable[["PostingContext"], str]] = {
    "num_unrelated_objects_based": (
        lambda c: c.workspace.get_rough_num_of_unrelated_objects(c.ctx.rng)
    ),
    "num_ungrouped_objects_based": (
        lambda c: c.workspace.get_rough_num_of_ungrouped_objects(c.ctx.rng)
    ),
    "num_unmapped_objects_based": (
        lambda c: c.workspace.get_rough_num_of_unmapped_objects(c.ctx.rng)
    ),
}

#: The names a formula may use.  Exposed so a test can state the vocabulary as a fact
#: rather than by reading the dict above and agreeing with itself.
POSTING_FORMULA_NAMES: frozenset[str] = frozenset(_PRODUCERS)

#: No builtins.  A posting formula is configuration written by whoever edits the admin
#: panel, and arithmetic over the names above is the whole of what it needs.
_NO_BUILTINS: dict[str, Any] = {"__builtins__": {}}


class PostingContext(Mapping):
    """The names a posting formula may read, resolved on demand and cached.

    One per rule evaluation.  The cache is per-context rather than global because
    every one of these quantities changes as the run proceeds; what it buys is that an
    expression naming `temperature` twice measures it once.
    """

    __slots__ = ("ctx", "node", "_cache")

    def __init__(self, ctx: Any, node: Any = None) -> None:
        self.ctx = ctx
        #: The triggering slipnode, for a top-down rule's urgency formula.  `None` for
        #: the bottom-up and thematic rules, which have no node to be triggered by.
        self.node = node
        self._cache: dict[str, Any] = {}

    @property
    def workspace(self) -> Any:
        return self.ctx.workspace

    def __getitem__(self, name: str) -> Any:
        if name in self._cache:
            return self._cache[name]
        try:
            producer = _PRODUCERS[name]
        except KeyError:
            raise KeyError(name) from None
        value = producer(self)
        self._cache[name] = value
        return value

    def __iter__(self) -> Iterator[str]:
        return iter(_PRODUCERS)

    def __len__(self) -> int:
        return len(_PRODUCERS)


@lru_cache(maxsize=256)
def compile_posting_formula(source: str, rule_name: str) -> Any:
    """Compile a posting formula, raising on a bad expression rather than at run time.

    Cached on the source text, so the seventeen shipped formulas compile once per
    process however many runs consult them.  `rule_name` is part of the key only so
    that it can appear in the error and in the code object's filename; two rules
    sharing a formula is ordinary and costs one extra entry.
    """
    try:
        return compile(source, f"<posting-formula:{rule_name}>", "eval")
    except SyntaxError as exc:
        raise ValueError(
            f"posting formula for {rule_name} does not compile: {source!r} — {exc}"
        ) from exc


def evaluate_posting_formula(source: str, rule_name: str, context: PostingContext) -> float:
    """The probability *source* states, under *context*.

    An unknown name raises rather than resolving to zero.  A formula that silently
    evaluates to "never post" is the failure this whole exercise is about: it is
    accepted, stored, hashed, displayed — and dead.

    The name lookup surfaces as `NameError`, not as the `KeyError` the mapping raises:
    `eval` resolves a bare name through locals, then globals, then builtins, so the
    mapping's miss is the *first* of three and only the last one raises to the caller.
    Both are caught, because the mapping is reachable directly in a unit test.
    """
    code = compile_posting_formula(source, rule_name)
    try:
        return float(eval(code, _NO_BUILTINS, context))  # noqa: S307
    except (NameError, KeyError) as exc:
        missing = exc.name if isinstance(exc, NameError) else exc.args[0]
        raise ValueError(
            f"posting formula for {rule_name} uses unknown name {missing!r}: "
            f"{source!r}. Known names: {', '.join(sorted(POSTING_FORMULA_NAMES))}"
        ) from exc


def validate_posting_formulas(rules: list[Any]) -> None:
    """Compile every rule's posting formula, so a bad one fails at load.

    Called from both loaders.  Startup is where an unparseable formula should be
    found: mid-run it would surface as one codelet type quietly failing to post, which
    looks like the engine exploring differently rather than like a broken
    configuration.
    """
    for rule in rules:
        if rule.posting_formula:
            compile_posting_formula(rule.posting_formula, rule.codelet_type)


def evaluate_count_formula(rule: Any, context: PostingContext) -> int:
    """How many codelets *rule* posts, this cycle.

    Scheme: ``num-of-codelets-to-post`` (``coderack.ss:517-550``).  Called only once
    the posting probability has already passed, exactly as the reference's
    ``stochastic-if*`` orders it, so the blurred tallies below draw at the same point
    in the random stream.

    Three shapes, all of them already written down in
    `seed_data/posting_rules.json`:

    * a **bucket** kind — the count is `count_values` indexed by a stochastically
      blurred object tally;
    * ``fixed`` — the count is `count_values["fixed"]`, or its ``justify_mode`` entry
      when the run is justifying, which is how the jootser posts two normally and one
      while justifying;
    * anything else is an **expression** over the same vocabulary the posting formulas
      use, plus arithmetic builtins.
    """
    formula = rule.count_formula
    values: dict[str, Any] = rule.count_values or {}

    if formula == "fixed":
        if context.ctx.justify_mode and "justify_mode" in values:
            return int(values["justify_mode"])
        return int(values.get("fixed", 1))

    bucket_of = _COUNT_BUCKETS.get(formula)
    if bucket_of is not None:
        # Grouping cannot start before anything is bonded, and the switch this
        # replaces answered that case *before* asking for the blurred tally.  The
        # order matters beyond tidiness: the tally costs a draw, so checking after it
        # would consume one extra number on every cycle before the first bond and
        # send the whole run elsewhere, with nothing in the output to say why.
        if formula == "num_ungrouped_objects_based" and not any(
            string.bonds for string in context.workspace.all_strings
        ):
            return int(values.get("none", 0))
        return int(values[bucket_of(context)])

    if not formula:
        return 1

    code = compile_posting_formula(formula, rule.codelet_type)
    try:
        return int(eval(code, _COUNT_BUILTINS, context))  # noqa: S307
    except (NameError, KeyError) as exc:
        missing = exc.name if isinstance(exc, NameError) else exc.args[0]
        raise ValueError(
            f"count formula for {rule.codelet_type} uses unknown name {missing!r}: "
            f"{formula!r}. Known names: {', '.join(sorted(POSTING_FORMULA_NAMES))}"
        ) from exc


def evaluate_urgency(rule: Any, context: PostingContext, default: int) -> int:
    """The urgency *rule* posts its codelets at.

    Scheme: ``coderack.ss:575-590`` for the bottom-up tiers, ``slipnet.ss:212-222``
    for the top-down ones.

    A rule states its urgency one of two ways, and the seed data uses both: a fixed
    ``urgency_when_posted`` for the eleven that post at a named tier's value, or an
    ``urgency_formula`` for the six whose urgency is computed from the run — the
    triggering node's depth and activation, the temperature, the theme pressure.

    *default* is what a rule stating neither gets, which the caller supplies because it
    is a *named* level rather than a number: `low`, resolved through `urgency_levels`.
    """
    if rule is not None and rule.urgency_formula:
        code = compile_posting_formula(rule.urgency_formula, rule.codelet_type)
        try:
            return int(eval(code, _COUNT_BUILTINS, context))  # noqa: S307
        except (NameError, KeyError) as exc:
            missing = exc.name if isinstance(exc, NameError) else exc.args[0]
            raise ValueError(
                f"urgency formula for {rule.codelet_type} uses unknown name "
                f"{missing!r}: {rule.urgency_formula!r}. Known names: "
                f"{', '.join(sorted(POSTING_FORMULA_NAMES))}"
            ) from exc
    if rule is not None and rule.urgency_when_posted is not None:
        return int(rule.urgency_when_posted)
    return default
