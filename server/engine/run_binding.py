"""What a run is bound to: its configuration, its constants, its Themespace and its clock.

The Scheme keeps ``*themespace*``, ``%max-activation%`` and the rest as globals, because it
runs one problem at a time.  A server holds several runs in one process, steps them in
worker threads and opens review inspectors beside them, so anything a run reaches by
implicit lookup must belong to *that run*.  Until this module existed the Themespace and the
provider were class attributes of ``WorkspaceStructure``: ``init_mcat`` assigned them, so
creating a second run changed the first (its bridge strengths were computed against the
second run's themes and coefficients), and a stepping thread could race a request on the
event loop.

The binding
-----------
:class:`RunBinding` holds, for one run:

``meta``
    the run's ``MetadataProvider`` (cold paths: names, roles, templates);
``constants``
    the run's :class:`RunConstants`, resolved once at ``init_mcat`` (hot paths);
``themespace``
    the Themespace its structures resonate with;
``clock``
    the codelet count a structure is stamped with when it is made, per thread (a worker
    thread of one run stamps with its own count, not another thread's).

It reaches the engine through a :class:`~contextvars.ContextVar`, exactly as the identifier
allocator does (``server/engine/ids.py``), and is installed at every engine entry point by
``EngineContext.scope()``.  Three properties matter:

* A ``ContextVar`` is per thread, and a thread started on the GIL build begins with an empty
  context, so **every thread entry installs it**: the free-running workers, the update-cycle
  workers and the speculative workers each open ``ctx.scope()`` (or ``use_run``) themselves.
  Nothing relies on a context being inherited.
* An entry point installs and removes it around the call, so two runs stepped alternately
  on one thread, a run stepped inside another run's call, and a review inspector stepped
  while live runs are in flight each see their own binding and leave the previous one
  exactly as it was.
* Nothing falls back.  Code that needs the binding and finds none raises
  :class:`NoRunBound` (a ``ConfigurationRequired``); it does not read the Metacat Standard
  Configuration files and does not use another run's values.

:class:`RunConstants`
---------------------
The coefficients a structure or an object reads while it computes a strength, an importance
or a salience, resolved once per run.  A read is one attribute of a frozen, slotted record
(about 20 ns) where ``bound_meta().get_formula_coeff(name)`` was a function call, a class
attribute read and a dictionary lookup (about 260 ns), and ``SalienceWeights.from_metadata``
had been rebuilt for every object twice per update.

**Adding a constant is one line**: a field on :class:`RunConstants`, declared with
``formula()`` (a formula coefficient of the same name), ``param()`` (an engine parameter of
the same name) or ``derived(lambda meta: ...)`` (anything computed from the configuration).
``from_metadata`` reads the declarations, so no second list exists to keep in step.  The
declared read list (``tests/architecture/test_declared_read_list.py``) sees these
declarations as reads of the names they carry.

**When the configuration changes.**  The record is built from the run's own
``MetadataProvider`` in ``init_mcat``, after the run's parameter overrides, and never again.
A provider is immutable (an edit swaps the object in the configuration store and never
mutates it), and a run holds its provider for life, so an edit, or a Training Mode
Session's configuration changing between its runs, reaches the *next* run's ``init_mcat``
and never the one under way.  A review inspector and a resumed run call ``init_mcat`` on
their own runner, and so build the record for the configuration they were given.
"""

from __future__ import annotations

import threading
from contextvars import ContextVar
from dataclasses import dataclass, field, fields
from fractions import Fraction
from typing import Any, Callable

from server.engine.ids import IdAllocator, bind_allocator, unbind_allocator
from server.engine.metadata import ConfigurationRequired


class NoRunBound(ConfigurationRequired):
    """Engine code that reads the run's binding ran with no run bound.

    A structure, an object or a codelet is always built and used inside an engine entry point
    (``EngineRunner.step_mcat`` and the rest, or a worker thread's ``ctx.scope()``).  Reaching
    this means a thread or a caller forgot to enter one; nothing guesses which run was meant.
    """


# ---------------------------------------------------------------------------
# Exact coefficients
# ---------------------------------------------------------------------------


def exact_fraction(value: Any) -> Fraction:
    """``Fraction(value)`` without ``numbers.Rational`` in the way.

    ``Fraction.__new__`` tests a float argument against the ``numbers.Rational`` ABC
    before it reaches its float branch, and under free-threaded CPython every such
    ``isinstance`` takes the ABC's weak-set lock -- a lock all threads share, hit
    thousands of times per run.  A float's exact value is ``as_integer_ratio()``, which
    is precisely what the float branch uses, so this returns the same ``Fraction``.
    """
    if type(value) is float:
        numerator, denominator = value.as_integer_ratio()
        return Fraction(numerator, denominator)
    return Fraction(value)


def exact_coefficient(value: Any) -> Fraction:
    """A configuration coefficient as an exact rational (``Fraction``).

    The Metacat Standard Configuration stores these as numbers; a configuration that holds a
    ``Fraction`` is taken as it is, and anything else at its exact value.
    """
    return value if type(value) is Fraction else exact_fraction(value)


# ---------------------------------------------------------------------------
# The constants record
# ---------------------------------------------------------------------------


def formula(key: str | None = None) -> Any:
    """A field read from the formula coefficient *key* (default: the field's own name)."""
    return field(metadata={"source": "formula", "key": key})


def param(key: str | None = None) -> Any:
    """A field read from the engine parameter *key* (default: the field's own name)."""
    return field(metadata={"source": "param", "key": key})


def derived(build: Callable[[Any], Any]) -> Any:
    """A field computed from the configuration: ``build(meta)``."""
    return field(metadata={"source": "derived", "build": build})


def _string_codes(frame: Any) -> Any:
    from server.engine.numeric.layout import string_type_codes

    return string_type_codes(frame)


def _salience_weights(meta: Any) -> Any:
    from server.engine.numeric.layout import SalienceWeights

    return SalienceWeights.from_metadata(meta)


@dataclass(frozen=True, slots=True)
class RunConstants:
    """The coefficients and parameters the engine reads on hot paths, resolved once per run.

    Frozen, so a run cannot change them; slotted, so a read is a slot read.  Values are kept
    exactly as the configuration holds them (an int stays an int, a float a float).
    """

    # -- Structure strength (structures, bonds, groups, bridges, descriptions) --------
    weakness_exponent: Any = formula()
    bond_compatibility_factor_same_type: Any = formula()
    bond_compatibility_factor_different_type: Any = formula()
    bond_facet_factor_letter_category: Any = formula()
    bond_facet_factor_other: Any = formula()
    bond_degree_of_assoc_scale: Any = formula()
    local_support_number_factor_base: Any = formula()
    group_bond_facet_other_multiplier: Any = formula()
    group_length_factor_1: Any = formula()
    group_length_factor_2: Any = formula()
    group_length_factor_3: Any = formula()
    group_length_factor_4_plus: Any = formula()
    group_bond_factor_weight_exponent: Any = formula()
    description_local_support_1: Any = formula()
    description_local_support_2: Any = formula()
    description_local_support_3: Any = formula()
    description_local_support_4_plus: Any = formula()
    concept_mapping_depth_bonus_exponent: Any = formula()
    concept_mapping_depth_penalty_exponent: Any = formula()
    concept_mapping_unlinked_association: Any = formula()

    # -- Bridges and thematic compatibility ------------------------------------------
    bridge_num_cm_factor_1: Any = formula()
    bridge_num_cm_factor_2: Any = formula()
    bridge_num_cm_factor_3_plus: Any = formula()
    bridge_coherence_factor_coherent: Any = formula()
    bridge_coherence_factor_incoherent: Any = formula()
    bridge_singleton_letter_mismatch_factor: Any = formula()
    bridge_theme_negative_weight_multiplier: Any = formula()
    bridge_theme_compatibility_sigmoid_beta: Any = formula()
    max_theme_activation: Any = param()
    flip_first_probability_more_spanning: Any = param()
    flip_first_probability_fewer_spanning: Any = param()
    flip_first_probability_equal_spanning: Any = param()

    # -- Object importance, unhappiness and salience ----------------------------------
    max_raw_importance: Any = formula()
    #: ``max_raw_importance`` as an exact rational (``Fraction``).
    max_raw_importance_exact: Fraction = derived(
        lambda m: exact_fraction(m.get_formula_coeff("max_raw_importance"))
    )
    #: ``enclosed_group_importance_factor`` as an exact rational, and as its correctly
    #: rounded double (``float(Fraction(2, 3))`` is ``2.0 / 3.0``).
    enclosed_group_importance_factor_exact: Fraction = derived(
        lambda m: exact_coefficient(m.get_formula_coeff("enclosed_group_importance_factor"))
    )
    enclosed_group_importance_factor_float: float = derived(
        lambda m: float(exact_coefficient(m.get_formula_coeff("enclosed_group_importance_factor")))
    )
    edge_object_bond_factor_exact: Fraction = derived(
        lambda m: exact_coefficient(m.get_formula_coeff("edge_object_bond_factor"))
    )
    interior_object_bond_factor_exact: Fraction = derived(
        lambda m: exact_coefficient(m.get_formula_coeff("interior_object_bond_factor"))
    )
    enclosed_group_bridge_factor: Any = formula()

    # -- Fixed values, clips and exponents of the structure, perception and rule formulas --
    bond_degree_of_assoc_exponent: Any = formula()
    low_prob_min_decade_factor: Any = formula()
    low_prob_target_offset: Any = formula()
    low_prob_sqrt_exponent: Any = formula()
    bond_degree_of_assoc_ceiling: Any = formula()
    local_support_density_exponent: Any = formula()
    local_support_number_exponent: Any = formula()
    local_support_number_denominator_floor: Any = formula()
    local_support_number_factor_ceiling: Any = formula()
    bond_local_support_unsupported: Any = formula()
    bond_local_density_no_string: Any = formula()
    bond_local_density_spanning: Any = formula()
    group_bond_factor_no_category: Any = formula()
    group_spanning_external_strength: Any = formula()
    group_local_support_unsupported: Any = formula()
    group_local_density_spanning: Any = formula()
    group_local_density_no_string: Any = formula()
    group_local_density_no_neighbours: Any = formula()
    intra_unhappiness_spanning: Any = formula()
    intra_unhappiness_unbonded: Any = formula()
    clamped_salience: Any = formula()
    inter_unhappiness_unbridged: Any = formula()
    thematic_pull_positive_target: Any = formula()
    thematic_pull_negative_target: Any = formula()
    average_unhappiness_empty: Any = formula()
    average_intra_unhappiness_empty: Any = formula()
    selection_weight_default: Any = formula()
    mapping_strength_spanning_possible_factor: Any = formula()
    mapping_strength_maximal_tanh_divisor: Any = formula()
    concept_mapping_depth_bonus_base: Any = formula()
    concept_mapping_depth_penalty_base: Any = formula()
    concept_mapping_full_association: Any = formula()
    concept_mapping_full_association_strength: Any = formula()
    concept_mapping_full_association_slippability: Any = formula()
    concept_mapping_identity_association: Any = formula()
    bridge_no_mapping_internal_strength: Any = formula()
    bridge_internal_strength_ceiling: Any = formula()
    bridge_external_strength_ceiling: Any = formula()
    bridge_spanning_singleton_external_strength: Any = formula()
    bridge_singleton_factor_unpenalised: Any = formula()
    bridge_theme_positive_weight_multiplier: Any = formula()
    bridge_theme_support_none: Any = formula()
    bridge_theme_support_unrelated: Any = formula()
    description_local_support_0: Any = formula()
    description_theme_support_none: Any = formula()
    description_theme_support_unrelated: Any = formula()
    link_length_unset: Any = formula()
    rule_support_missing_bridge_strength: Any = formula()
    clamp_event_strength: Any = formula()
    snag_event_strength: Any = formula()
    bond_event_progress: Any = formula()
    clamp_suppressed_concept_activation: Any = formula()
    # -- The vocabulary --------------------------------------------------------------
    #: The names of the run's configuration, by role (``Vocabulary``, ``engine/roles.py``).
    #: A hot path compares against ``constants().vocab.bridge_type_top``; a path that
    #: holds the run's provider reads ``meta.vocabulary`` (the same object).
    vocab: Any = derived(lambda m: m.vocabulary)
    #: The four-string frame (``engine/frame.py``), derived from the configuration once per run.
    frame: Any = derived(lambda m: m.frame)
    #: The code the numeric backends branch on for each string kind (``numeric/layout.py``).
    string_codes: Any = derived(lambda m: _string_codes(m.frame))
    #: The two salience averages' weights (``numeric/layout.py``), resolved once, where
    #: they had been rebuilt for every object twice per update.
    salience: Any = derived(_salience_weights)

    # -- The run, the random stream and the Trace's importances ------------------------
    #: The ``~`` operator (``rng.perturb``): the chance the delta is added, and the exponent
    #: of the delta's bound, ``1 + round(|n| ** perturb_delta_exponent)``.
    perturb_up_probability: Any = param()
    perturb_delta_exponent: Any = formula()
    #: Bond scanning: a scan of ``i`` bonds is drawn with weight ``i ** bond_scan_exponent``.
    bond_scan_exponent: Any = formula()
    #: A spanning bridge boosts its themes this many times as hard.
    spanning_bridge_theme_boost_factor: Any = formula()
    #: Slippage importance (``trace.ss:1365-1385``).
    slippage_importance_unlabelled_depth: Any = formula()
    slippage_importance_spanning_term: Any = formula()
    slippage_importance_weight_dimension_depth: Any = formula()
    slippage_importance_weight_spanning: Any = formula()
    slippage_importance_weight_descriptor_depth: Any = formula()
    slippage_importance_weight_label_depth: Any = formula()
    #: The importance a Trace event takes when it is special, and what makes a rule perfect.
    group_special_importance: Any = param()
    thematic_slippage_importance: Any = param()
    uniform_rule_importance: Any = param()
    perfect_rule_uniformity: Any = param()
    #: Justify's retention of a theme-pattern entry.
    justify_retention_string_position: Any = param()
    justify_retention_non_identity_percent: Any = param()
    #: The quality and strength bands that choose which commentary template a Trace event is
    #: reported with (``answers.ss:47-75``, ``trace.ss:212-226``, ``memory.ss:214-229``).  They
    #: select text only, and sit beside the templates they select.
    commentary_discovery_emphatic_below: Any = param()
    commentary_discovery_emphatic_from: Any = param()
    commentary_discovery_bad_below: Any = param()
    commentary_justified_bad_below: Any = param()
    commentary_justified_extreme_from: Any = param()
    commentary_progress_little_below: Any = param()
    commentary_progress_some_below: Any = param()
    commentary_reminding_strong_above: Any = param()
    commentary_reminding_some_above: Any = param()

    #: The two blends a scout draws its target from: a bond facet by local support and
    #: activation, and a string by relevance and unhappiness.
    bond_facet_choice_local_support_weight: Any = formula()
    bond_facet_choice_activation_weight: Any = formula()
    scout_string_choice_relevance_weight: Any = formula()
    scout_string_choice_unhappiness_weight: Any = formula()

    # -- The weights of a fight (``wins-fight?``), proposer against opponent -----------
    fight_bond_vs_bond_proposer_weight: Any = formula()
    fight_bond_vs_bond_opponent_weight: Any = formula()
    fight_bond_vs_group_proposer_weight: Any = formula()
    fight_bond_vs_bridge_proposer_weight: Any = formula()
    fight_bond_vs_bridge_opponent_weight: Any = formula()
    fight_group_vs_flipped_bond_opponent_weight: Any = formula()
    fight_group_vs_group_proposer_weight: Any = formula()
    fight_group_vs_group_opponent_weight: Any = formula()
    fight_group_vs_bridge_proposer_weight: Any = formula()
    fight_group_vs_bridge_opponent_weight: Any = formula()
    fight_bridge_vs_bond_proposer_weight: Any = formula()
    fight_bridge_vs_bond_opponent_weight: Any = formula()
    fight_bridge_vs_enclosing_group_proposer_weight: Any = formula()
    fight_bridge_vs_enclosing_group_opponent_weight: Any = formula()
    fight_bridge_vs_flipped_group_proposer_weight: Any = formula()
    fight_bridge_vs_flipped_group_opponent_weight: Any = formula()

    @classmethod
    def from_metadata(cls, meta: Any) -> RunConstants:
        """Resolve every declared field from *meta*.  Raises ``KeyError`` for a missing
        coefficient; a run's start check (``require_run_start``) has already named any."""
        values: dict[str, Any] = {}
        for f in fields(cls):
            source = f.metadata["source"]
            if source == "formula":
                values[f.name] = meta.get_formula_coeff(f.metadata["key"] or f.name)
            elif source == "param":
                values[f.name] = meta.get_param(f.metadata["key"] or f.name)
            else:
                values[f.name] = f.metadata["build"](meta)
        return cls(**values)


# ---------------------------------------------------------------------------
# The binding
# ---------------------------------------------------------------------------


class RunBinding:
    """Everything a run's structures and objects reach by implicit lookup."""

    __slots__ = ("meta", "constants", "themespace", "clock")

    def __init__(
        self, meta: Any, constants: RunConstants | None = None, themespace: Any = None
    ) -> None:
        self.meta = meta
        self.constants: RunConstants = (
            constants if constants is not None else RunConstants.from_metadata(meta)
        )
        #: Assigned once, by ``init_mcat``, when the run's Themespace is built (``None``
        #: before that: no structure exists yet to consult it).
        self.themespace = themespace
        #: The codelet count a structure made on this thread is stamped with
        #: (``workspace-structures.ss:22``, ``*codelet-count*``).  Per thread because the
        #: free-running and speculative executors stamp from several threads at once, and
        #: per run because two runs stepped alternately on one thread must not stamp each
        #: other's structures.
        self.clock = threading.local()

    @classmethod
    def for_meta(cls, meta: Any, themespace: Any = None) -> RunBinding:
        """A binding for *meta* with its constants resolved (a context built without a run)."""
        return cls(meta, RunConstants.from_metadata(meta), themespace)


_RUN: ContextVar[RunBinding] = ContextVar("petacat_run_binding")


def current() -> RunBinding:
    """The bound run's binding, or :class:`NoRunBound`."""
    try:
        return _RUN.get()
    except LookupError:
        raise NoRunBound(
            "this needs the run it belongs to, and no run is bound in this thread: engine "
            "code runs inside an EngineRunner entry point or a worker's ctx.scope(); "
            "nothing falls back to another run or to the Metacat Standard Configuration"
        ) from None


def constants() -> RunConstants:
    """The bound run's :class:`RunConstants` (the hot-path read)."""
    try:
        return _RUN.get().constants
    except LookupError:
        current()  # raises NoRunBound with its message
        raise  # pragma: no cover


def vocab() -> Any:
    """The bound run's :class:`~server.engine.roles.Vocabulary` (names by role)."""
    try:
        return _RUN.get().constants.vocab
    except LookupError:
        current()  # raises NoRunBound with its message
        raise  # pragma: no cover


def set_clock(codelet_count: int) -> None:
    """Stamp structures made from now on, in this thread and run, with *codelet_count*."""
    current().clock.now = codelet_count


class use_run:
    """Bind *binding* (and, when given, *ids*) for the duration of a ``with`` block.

    The previous binding is restored on exit, so a call nested inside another run's call
    leaves the outer binding as it found it.  A class rather than a generator-based context
    manager: it is entered once per codelet.
    """

    __slots__ = ("_binding", "_ids", "_tb", "_ti")

    def __init__(self, binding: RunBinding, ids: IdAllocator | None = None) -> None:
        self._binding = binding
        self._ids = ids

    def __enter__(self) -> RunBinding:
        self._tb = _RUN.set(self._binding)
        self._ti = bind_allocator(self._ids) if self._ids is not None else None
        return self._binding

    def __exit__(self, *exc: Any) -> None:
        if self._ti is not None:
            unbind_allocator(self._ti)
        _RUN.reset(self._tb)
