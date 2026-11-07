"""SQLAlchemy ORM models for metadata tables.

These tables define the system's domain knowledge — slipnet topology,
codelet types, engine parameters, etc. They are seeded from seed_data/
JSON files and can be edited via the admin panel.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger, Boolean, Column, Float, ForeignKey, Index, Integer, Text,
    UniqueConstraint, column, func, select, table,
)
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def _next_after_last(table_name: str, column_name: str = "sort_order"):
    """A column default: one past the largest value the table holds (0 when empty).

    For the ordinals of tables whose rows an Admin adds one at a time: a new row goes
    last, as it did when the order was the integer ``id``.  The seeder writes every
    ordinal explicitly and never relies on this.
    """
    t = table(table_name, column(column_name))
    return select(func.coalesce(func.max(t.c[column_name]), -1) + 1).scalar_subquery()


# ──────────────────────────────────────────────────────────────────
# Enum lookup tables (18 tables; all have name, display_label, sort_order and description,
# and some add columns: a role, a behaviour, a clamp type's factors ...)
# ──────────────────────────────────────────────────────────────────

class RunStatusDef(Base):
    __tablename__ = "run_statuses"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class EventTypeDef(Base):
    __tablename__ = "event_types"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The engine's name for the concept this row plays (``server/engine/roles.py``,
    #: ``VOCABULARY``), or NULL for a row the engine does not name.  Unique within the table.
    role = Column(Text, nullable=True, unique=True)

class BridgeTypeDef(Base):
    """A kind of bridge, and the part of the four-string frame it plays.

    The frame (which strings a bridge joins, in which orientation, which theme type it feeds,
    and from these what each string maps and who its partner is) is defined here and in
    ``string_kinds`` and ``rule_types``, once; ``server/engine/frame.py`` derives everything else
    from them, once per run.
    """
    __tablename__ = "bridge_types"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The engine's name for the concept this row plays (``server/engine/roles.py``,
    #: ``VOCABULARY``), or NULL for a row the engine does not name.  Unique within the table.
    role = Column(Text, nullable=True, unique=True)
    #: The strings a bridge of this type joins: names of ``string_kinds`` (a bridge goes from the
    #: first to the second).
    from_string_kind = Column(Text, nullable=True)
    to_string_kind = Column(Text, nullable=True)
    #: The name of a ``bridge_orientations`` row: ``horizontal`` joins two strings of one
    #: analogy, ``vertical`` joins the two analogies (the engine names both by role).
    orientation = Column(Text, nullable=True)
    #: The name of the ``theme_types`` row the bridges of this type feed.
    theme_type = Column(Text, nullable=True)

class BridgeOrientationDef(Base):
    __tablename__ = "bridge_orientations"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The engine's name for the concept this row plays (``server/engine/roles.py``,
    #: ``VOCABULARY``), or NULL for a row the engine does not name.  Unique within the table.
    role = Column(Text, nullable=True, unique=True)

class ClauseTypeDef(Base):
    __tablename__ = "clause_types"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The engine's name for the concept this row plays (``server/engine/roles.py``,
    #: ``VOCABULARY``), or NULL for a row the engine does not name.  Unique within the table.
    role = Column(Text, nullable=True, unique=True)

class RuleTypeDef(Base):
    __tablename__ = "rule_types"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The engine's name for the concept this row plays (``server/engine/roles.py``,
    #: ``VOCABULARY``), or NULL for a row the engine does not name.  Unique within the table.
    role = Column(Text, nullable=True, unique=True)
    #: The name of the ``bridge_types`` row whose pair of strings a rule of this type describes
    #: (a top rule describes the change from the initial to the modified string).
    bridge_type = Column(Text, nullable=True)

class ThemeTypeDef(Base):
    __tablename__ = "theme_types"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The engine's name for the concept this row plays (``server/engine/roles.py``,
    #: ``VOCABULARY``), or NULL for a row the engine does not name.  Unique within the table.
    role = Column(Text, nullable=True, unique=True)

class ProposalLevelDef(Base):
    __tablename__ = "proposal_levels"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The engine's name for the concept this row plays (``server/engine/roles.py``,
    #: ``VOCABULARY``), or NULL for a row the engine does not name.  Unique within the table.
    role = Column(Text, nullable=True, unique=True)

class LinkTypeDef(Base):
    __tablename__ = "link_types"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: What the engine does with a link of this type: ``category``, ``instance``,
    #: ``property``, ``lateral`` or ``slip`` (``server/engine/roles.py``,
    #: ``LINK_BEHAVIOURS``).  Which type has which behaviour is configuration; the engine
    #: names behaviours and never a link type.  NULL gives a link no behaviour.
    behaviour = Column(Text, nullable=True)

class CodeletFamilyDef(Base):
    __tablename__ = "codelet_families"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: A codelet of this family runs alone under the free-running executor (the meta and
    #: answer codelets read and rewrite the whole Workspace), where the others run beside
    #: one another.  Read by ``parallel/free_running.py``.
    serialised = Column(Boolean, nullable=False, default=False)

class CodeletPhaseDef(Base):
    __tablename__ = "codelet_phases"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class PostingDirectionDef(Base):
    __tablename__ = "posting_directions"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The engine's name for the concept this row plays (``server/engine/roles.py``,
    #: ``VOCABULARY``), or NULL for a row the engine does not name.  Unique within the table.
    role = Column(Text, nullable=True, unique=True)

class ParamValueTypeDef(Base):
    __tablename__ = "param_value_types"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")


class StringKindDef(Base):
    """The kinds of string a problem has (initial, modified, target, answer).

    ``sort_order`` is the kind's place in the frame (the numeric backends' code for it).
    """
    __tablename__ = "string_kinds"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The engine's name for the concept this row plays (``server/engine/roles.py``,
    #: ``VOCABULARY``), or NULL for a row the engine does not name.  Unique within the table.
    role = Column(Text, nullable=True, unique=True)
    #: Whether a string of this kind is there from the start of a run.  The answer string is
    #: not: it exists once an answer has been found or supplied, so a bridge to it is possible
    #: only when the run justifies.
    exists_at_start = Column(Boolean, nullable=False, default=True)

class RuleScopeDef(Base):
    """The scope a rule's clause applies to (the object itself, or its subobjects)."""
    __tablename__ = "rule_scopes"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The engine's name for the concept this row plays (``server/engine/roles.py``,
    #: ``VOCABULARY``), or NULL for a row the engine does not name.  Unique within the table.
    role = Column(Text, nullable=True, unique=True)

class FailureKindDef(Base):
    """The kinds of failure a snag reports (swap, conflict, change)."""
    __tablename__ = "failure_kinds"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The engine's name for the concept this row plays (``server/engine/roles.py``,
    #: ``VOCABULARY``), or NULL for a row the engine does not name.  Unique within the table.
    role = Column(Text, nullable=True, unique=True)

class ClampTypeDef(Base):
    """A kind of clamp, and what it holds the Coderack to.

    The name is the engine's ``clamp_type`` string; ``role`` names which of the engine's
    four clamp concepts the row is.  ``codelet_background_level`` names the tier of
    ``urgency_levels`` the clamp holds the rest of the Coderack against (NULL: none),
    ``jootsing_factor`` is the factor the jootsing probability takes for a clamp of this
    type, ``progress_focus`` names a row of ``progress_focuses`` and ``codelet_patterns`` lists the
    codelet patterns the clamp clamps.
    """
    __tablename__ = "clamp_types"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The engine's name for the concept this row plays (``server/engine/roles.py``,
    #: ``VOCABULARY``), or NULL for a row the engine does not name.  Unique within the table.
    role = Column(Text, nullable=True, unique=True)
    codelet_background_level = Column(Text, nullable=True)
    jootsing_factor = Column(Float, nullable=True)
    #: The factor applies only while the clamp is still the newest event of the Trace (the
    #: justify clamp: ``jootsing.ss:135-139``); otherwise the factor is 0.
    jootsing_only_when_latest = Column(Boolean, nullable=False, default=False)
    progress_focus = Column(Text, nullable=True)
    #: The codelet patterns (names in ``codelet_pattern_defs``) a clamp of this type clamps, as a
    #: list: a justify clamp clamps two, a rule-codelet clamp one, a manual clamp none (a person
    #: names the pattern when making it).
    codelet_patterns = Column(JSON, nullable=False, default=list)


class ProgressFocusDef(Base):
    """A progress focus: which trace event types count as progress for a clamp."""
    __tablename__ = "progress_focuses"
    name = Column(Text, primary_key=True)
    display_label = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    #: The event types (names of ``event_types``) that count as progress, as a list.
    event_types = Column(JSON, nullable=False, default=list)


# ──────────────────────────────────────────────────────────────────
# Domain knowledge tables
# ──────────────────────────────────────────────────────────────────

class SlipnetNodeDef(Base):
    """Definition of a slipnet concept node."""

    __tablename__ = "slipnet_node_defs"

    name = Column(Text, primary_key=True)
    #: The Scheme's own definition order (``slipnet.ss:407-468``), which
    #: ``seed_data/slipnet_nodes.json`` reproduces element for element.
    #:
    #: Load-bearing, and it had nowhere to live: ``name`` is the primary key and there
    #: was no ordinal, so the loader returned Postgres *heap* order.
    #: ``Slipnet.update_activations`` iterates the nodes for the spread and for the
    #: probabilistic jump, so the order fixes the float accumulation order of the
    #: activation sum and which node each ``rng.prob`` draw is spent on.  Sorting by
    #: ``name`` is not a substitute: ``plato-alphabetic-first`` falls between
    #: ``plato-a`` and ``plato-b``.
    sort_order = Column(Integer, nullable=False, default=0, index=True)
    short_name = Column(Text, nullable=False)
    conceptual_depth = Column(Integer, nullable=False)
    description = Column(Text, default="")
    # DSL expression over `obj` deciding whether this node validly describes a
    # Workspace object (Scheme: define-descriptor-predicate).  Null for the many
    # nodes whose descriptors are read off an object rather than tested.
    descriptor_predicate = Column(Text, nullable=True)
    #: What code used to read off the name (``name[6:]``).  Names are opaque (plan 3.1).
    plain_name = Column(Text, nullable=True)
    #: The character a letter node stands for.  Case-sensitive; a node with a glyph is a
    #: letter, and the alphabet is the set of such nodes (plan 3.13).
    glyph = Column(Text, nullable=True, unique=True)
    #: The value of a number node.  Any integers, contiguous or not (plan 3.13).
    numeric_value = Column(Integer, nullable=True, unique=True)
    #: Display only; NULL falls back to ``plain_name`` or ``short_name`` (plan 3.3).
    full_name = Column(Text, nullable=True)
    cm_short_name = Column(Text, nullable=True)
    article_an = Column(Boolean, nullable=True)


class SlipnetLinkDef(Base):
    """Definition of a slipnet link between two nodes.

    The key is ``(from_node, to_node, link_type, label)`` where the label is the label
    node, or the empty string for a link with none (a NULL cannot be part of a unique
    key, so the index is over ``coalesce(label_node, '')``).  Two differently labelled links between the same two nodes can exist.
    ``sort_order`` carries the file's order, which fixes the float accumulation order of
    the spread; ``id`` is not stable across configurations.
    """

    __tablename__ = "slipnet_link_defs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sort_order = Column(
        Integer, nullable=False, index=True,
        default=_next_after_last("slipnet_link_defs"),
    )
    from_node = Column(Text, nullable=False, index=True)
    to_node = Column(Text, nullable=False, index=True)
    link_type = Column(Text, ForeignKey("link_types.name"), nullable=False)
    label_node = Column(Text, nullable=True)
    link_length = Column(Integer, nullable=True)  # None = dynamic (from label node)
    fixed_length = Column(Boolean, nullable=False)


Index(
    "uq_slipnet_link_key",
    SlipnetLinkDef.from_node,
    SlipnetLinkDef.to_node,
    SlipnetLinkDef.link_type,
    func.coalesce(SlipnetLinkDef.label_node, ""),
    unique=True,
)


class CodeletTypeDef(Base):
    """Definition of a codelet type with its behavior as Python source."""

    __tablename__ = "codelet_type_defs"

    name = Column(Text, primary_key=True)
    #: Seed-file order.  Same reason as ``SlipnetNodeDef.sort_order`` — the primary key
    #: is a name, so without this the order is the storage layout's.
    sort_order = Column(Integer, nullable=False, default=0, index=True)
    family = Column(Text, ForeignKey("codelet_families.name"), nullable=False)
    phase = Column(Text, ForeignKey("codelet_phases.name"), nullable=False)
    description = Column(Text, default="")
    source_file = Column(Text, default="")
    source_line = Column(Integer, default=0)
    execute_body = Column(Text, default="")  # Python source code


class EngineParam(Base):
    """A named engine parameter (key-value)."""

    __tablename__ = "engine_params"

    name = Column(Text, primary_key=True)
    value = Column(Text, nullable=False)  # Stored as text, parsed at load
    value_type = Column(Text, ForeignKey("param_value_types.name"), default="string")
    #: The seed file's key order (parameters are looked up by name, but the database keeps
    #: the order so that it loses nothing the file says).
    sort_order = Column(Integer, nullable=False, default=_next_after_last("engine_params"))
    #: What the value's names refer to, so a change that renames or removes the thing
    #: updates the parameter with it: ``node_list`` (a list of Slipnet node names),
    #: ``trigger_node_list`` (a node list that is also the union of the posting rules'
    #: triggering nodes), ``node_map`` (a map keyed by node name), ``codelet_type_list`` (a list
    #: of codelet type names), ``urgency_level`` (the name of an urgency level),
    #: ``clampable_pattern_map`` (a map keyed by the names of the clampable codelet patterns, the
    #: menu), ``clampable_pattern_list`` (a list of those names) or NULL (the value names nothing).  Declared in ``seed_data/engine_param_refs.json``.
    refers_to = Column(Text, nullable=True)


class UrgencyLevel(Base):
    """Named urgency tier with numeric value."""

    __tablename__ = "urgency_levels"

    name = Column(Text, primary_key=True)
    value = Column(Integer, nullable=False)
    sort_order = Column(Integer, nullable=False, default=_next_after_last("urgency_levels"))


class FormulaCoefficient(Base):
    """Named coefficient for formulas."""

    __tablename__ = "formula_coefficients"

    name = Column(Text, primary_key=True)
    #: The number as text, parsed by ``value_type`` at load (as ``engine_params`` does): a
    #: Float column keeps neither ``5`` against ``5.0`` nor an exact rational.
    value = Column(Text, nullable=False)
    #: ``int``, ``float`` or ``rational`` (written ``n/m``, held exactly): the kind the seed
    #: file gives the value.
    value_type = Column(Text, ForeignKey("param_value_types.name"), nullable=False, default="float")
    sort_order = Column(Integer, nullable=False, default=_next_after_last("formula_coefficients"))


class PostingRule(Base):
    """Codelet posting rule."""

    __tablename__ = "posting_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    #: The rule's natural key, so a rule can be named without its integer ``id``.  Unique;
    #: when a row is written without one it is the codelet type.
    rule_key = Column(
        Text, nullable=False, unique=True,
        default=lambda context: context.get_current_parameters()["codelet_type"],
    )
    #: The file's order.  The engine consults the rules in sequence and every consultation
    #: costs a draw from the run's random stream, so the order is behaviour.
    sort_order = Column(Integer, nullable=False, default=_next_after_last("posting_rules"))
    codelet_type = Column(Text, nullable=False, index=True)
    direction = Column(Text, ForeignKey("posting_directions.name"), nullable=False)
    #: The name of a tier in ``urgency_levels`` that the rule posts at, or ``None`` for a rule
    #: with a formula (or neither).  A name, not the tier's number, so the tier is stored once.
    urgency_level = Column(Text, nullable=True)
    urgency_formula = Column(Text, nullable=True)
    posting_formula = Column(Text, nullable=False)
    count_formula = Column(Text, nullable=False)
    #: ``json``, not ``jsonb``: JSONB reorders object keys, and key order is read back.
    count_values = Column(JSON, nullable=True)
    condition = Column(Text, nullable=False)
    triggering_slipnodes = Column(JSONB, nullable=True)


class CodeletPatternDef(Base):
    """One entry of a named codelet pattern.

    A pattern is a set of ``(codelet type, urgency)`` pairs clamped together, so that
    clamping one pins a whole line of work rather than a single codelet type
    (``trace.ss:1597-1668``).  The engine's clamp sites read the nine of them through
    ``meta.codelet_patterns`` — the jootser's response to a repeated snag
    (``jootsing.py:429``), and the whole of justify mode's opening
    (``justify.py:403``).

    Stored one row per entry rather than one row per pattern, so a pattern's
    membership is editable a line at a time in the admin panel, the way a posting rule
    is.  ``id`` carries the order within a pattern and across patterns, assigned from
    the seed file when the row is written.
    """

    __tablename__ = "codelet_pattern_defs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    #: Position across all patterns, in the file's order: both the order of the patterns
    #: and the order within each one.
    ordinal = Column(Integer, nullable=False, default=_next_after_last("codelet_pattern_defs", "ordinal"))
    pattern_name = Column(Text, nullable=False, index=True)
    codelet_type = Column(Text, nullable=False)
    #: A *named* tier from ``urgency_levels``, not a number.  A pattern says which
    #: level and the run resolves it (``Coderack._pattern_entry``), so changing what
    #: ``very_high`` means moves every pattern that names it instead of leaving 77
    #: written down in a second place.
    urgency_level = Column(Text, nullable=False)


class CommentaryTemplate(Base):
    """Commentary template text."""

    __tablename__ = "commentary_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_key = Column(Text, nullable=False, index=True)
    #: ``json``, not ``jsonb``: the templates' key order is read back.
    template_data = Column(JSON, nullable=False)


class DemoProblem(Base):
    """Pre-configured demo problem."""

    __tablename__ = "demo_problems"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False, unique=True)
    section = Column(Text, default="")
    initial = Column(Text, nullable=False)
    modified = Column(Text, nullable=False)
    target = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    seed = Column(BigInteger, nullable=False)
    description = Column(Text, default="")


class ThemeDimensionDef(Base):
    """Theme dimension specification."""

    __tablename__ = "theme_dimension_defs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slipnet_node = Column(Text, nullable=False)
    valid_relations = Column(JSONB, nullable=False)  # list of strings


class InitialDescriptionRule(Base):
    """One rule of the initial-description program: a description every letter is given.

    Before the first codelet, ``make-letter`` (Scheme ``workspace-objects.ss:21-26``) and
    ``init-mcat`` (``run.ss:227-232``) give each letter its first descriptions.  The rows are
    applied to every letter in ``ordinal`` order, and each description is put at the *front* of
    the letter's description list, so the order is part of what a run does (every stochastic
    description pick, and the bridge's theme cross-product, walk that list in order).

    A rule says *which* description (``dimension_role`` names the description type by the
    engine's node role, ``descriptor_source`` and ``descriptor_role`` the descriptor), *when*
    (``condition``, one of the engine's closed set of arithmetic conditions: ``always``,
    ``single``, ``leftmost``, ``rightmost``, ``middle``) and whether the descriptor is made fully
    active.  A role nothing holds drops the rule: what has no node is not perceived.
    """

    __tablename__ = "initial_description_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    #: The rule's natural key.
    rule_key = Column(Text, nullable=False, unique=True)
    #: The order the rules are applied in; each description goes to the front of the list.
    ordinal = Column(Integer, nullable=False, default=_next_after_last("initial_description_rules", "ordinal"))
    #: What the rule describes: ``letter`` (the letters of the problem, at the start of a run),
    #: ``translated_letter`` (the letters of a string translated from a rule) or ``group`` (every
    #: new group).  The conditions and sources a rule may name depend on its subject.
    subject = Column(Text, nullable=False, default="letter")
    #: A node role (``roles.json``) naming the description type.
    dimension_role = Column(Text, nullable=False)
    #: Where the descriptor comes from: ``role`` (the node ``descriptor_role`` names) or
    #: ``letter_category`` (the letter's own letter-category node).
    descriptor_source = Column(Text, nullable=False)
    #: A node role, for ``descriptor_source = role``; NULL otherwise.
    descriptor_role = Column(Text, nullable=True)
    #: ``always``, ``single``, ``leftmost``, ``rightmost`` or ``middle`` (``initial_program.py``).
    condition = Column(Text, nullable=False)
    #: Whether the descriptor is made fully active (``run.ss:227-232``).
    activate_descriptor = Column(Boolean, nullable=False, default=True)
    #: Whether the description is made at the built level (a letter's and a group's are; a translated
    #: string's letters are left at the level a new description starts at).
    built = Column(Boolean, nullable=False, default=True)
    #: Whether the description is put with the structure's bond descriptions (a group's bond category
    #: and bond facet) and not with its descriptions.
    bond_description = Column(Boolean, nullable=False, default=False)


class InitialActivationRule(Base):
    """One rule of the concepts a run starts with fully active (``run.ss:221-226``).

    The rules are applied in ``ordinal`` order, before the initial descriptions.  ``node_role``
    names the node (by the engine's node role); ``condition`` is one of the engine's closed set
    (``always``, ``any_single_letter_string``: some string of the problem has one letter).
    """

    __tablename__ = "initial_activation_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_key = Column(Text, nullable=False, unique=True)
    ordinal = Column(Integer, nullable=False, default=_next_after_last("initial_activation_rules", "ordinal"))
    node_role = Column(Text, nullable=False)
    condition = Column(Text, nullable=False)


class InputCharacterRange(Base):
    """A run of characters of one kind, for Metacat Mode's input parser (``input_parser.py``).

    ``kind`` is ``alphabetic`` (Scheme's ``char-alphabetic?``) or ``numeric`` (``char-numeric?``);
    the characters ``first`` to ``last`` (Unicode scalar values, inclusive) are of that kind.
    A character in no row of either kind is a separator.  A character may be in both kinds.
    Generated from Metacat's own Chez Scheme by ``scripts/generate_input_parser_seed.py``, so
    a Python upgrade cannot change what Metacat Mode perceives.  A Training Mode Session never
    reads these rows.
    """

    __tablename__ = "input_character_ranges"
    __table_args__ = (UniqueConstraint("kind", "first", name="uq_input_character_range"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(Text, nullable=False)
    first = Column(Integer, nullable=False)
    last = Column(Integer, nullable=False)


class InputLoweringRange(Base):
    """How Metacat Mode's input parser lowers characters (Scheme's ``char-downcase``).

    The characters ``first``, ``first + step``, ... up to ``last`` are each replaced by the
    character ``delta`` further on.  A character in no row is its own lowered form.  Generated
    with ``input_character_ranges``.  A Training Mode Session never reads these rows.
    """

    __tablename__ = "input_lowering_ranges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    first = Column(Integer, nullable=False, unique=True)
    last = Column(Integer, nullable=False)
    step = Column(Integer, nullable=False, default=1)
    delta = Column(Integer, nullable=False)


class SlipnetLayoutPos(Base):
    """Grid position for slipnet visualization."""

    __tablename__ = "slipnet_layout"

    node_name = Column(Text, primary_key=True)
    grid_row = Column(Integer, nullable=False)
    grid_col = Column(Integer, nullable=False)
    sort_order = Column(Integer, nullable=False, default=_next_after_last("slipnet_layout"))


class SlipnetNodeRole(Base):
    """A role bound to a Slipnet node (plan 3.2).

    The engine owns the vocabulary of role names (``server/engine/roles.py``, EN3); the
    configuration owns which node plays each.  A single-node role has ordinal 0; an ordered
    role (a list whose order is behaviour) has one row per element, ordinal being the
    position.  A node may hold several roles.  Deleting a node deletes its bindings.
    """

    __tablename__ = "slipnet_node_roles"
    __table_args__ = (UniqueConstraint("node_name", "role", name="uq_slipnet_node_role"),)

    role = Column(Text, primary_key=True)
    ordinal = Column(Integer, primary_key=True, default=0)
    node_name = Column(
        Text,
        ForeignKey("slipnet_node_defs.name", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )


class CodeletTypeRole(Base):
    """A role bound to a codelet type (plan 3.2); the same shape as ``SlipnetNodeRole``."""

    __tablename__ = "codelet_type_roles"
    __table_args__ = (UniqueConstraint("codelet_type", "role", name="uq_codelet_type_role"),)

    role = Column(Text, primary_key=True)
    ordinal = Column(Integer, primary_key=True, default=0)
    codelet_type = Column(
        Text,
        ForeignKey("codelet_type_defs.name", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )


class ThemeRelation(Base):
    """A theme relation: its name, the node that stands for it and its abstractness.

    ``node_name`` is NULL for ``diff``, which has no node.  ``abstractness`` is NULL when
    it is the node's conceptual depth (identity 0 and diff 50 are fixed).  No row is
    required; a relation without a row is unavailable.
    """

    __tablename__ = "theme_relations"

    name = Column(Text, primary_key=True)
    ordinal = Column(Integer, nullable=False, default=_next_after_last("theme_relations", "ordinal"))
    node_name = Column(
        Text,
        ForeignKey("slipnet_node_defs.name", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=True,
    )
    abstractness = Column(Integer, nullable=True)
    description = Column(Text, default="")
    #: The engine's name for the relation (``relation.opposite`` ...), or NULL.  Unique.
    role = Column(Text, nullable=True, unique=True)


class HelpTopic(Base):
    """Context-sensitive documentation topic."""

    __tablename__ = "help_topics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    topic_type = Column(Text, nullable=False, index=True)  # component, glossary
    topic_key = Column(Text, nullable=False, unique=True, index=True)
    title = Column(Text, nullable=False)
    short_desc = Column(Text, default="")
    full_desc = Column(Text, default="")
    metadata_json = Column("metadata", JSONB, default=dict)
