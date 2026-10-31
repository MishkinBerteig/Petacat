"""SQLAlchemy ORM models for metadata tables.

These tables define the system's domain knowledge — slipnet topology,
codelet types, engine parameters, etc. They are seeded from seed_data/
JSON files and can be edited via the admin panel.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger, Boolean, Column, Float, ForeignKey, Index, Integer, String, Text,
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
# Enum lookup tables (14 tables, all share the same schema pattern)
# ──────────────────────────────────────────────────────────────────

class RunStatusDef(Base):
    __tablename__ = "run_statuses"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class EventTypeDef(Base):
    __tablename__ = "event_types"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class BridgeTypeDef(Base):
    __tablename__ = "bridge_types"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class BridgeOrientationDef(Base):
    __tablename__ = "bridge_orientations"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class ClauseTypeDef(Base):
    __tablename__ = "clause_types"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class RuleTypeDef(Base):
    __tablename__ = "rule_types"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class ThemeTypeDef(Base):
    __tablename__ = "theme_types"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class ProposalLevelDef(Base):
    __tablename__ = "proposal_levels"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class LinkTypeDef(Base):
    __tablename__ = "link_types"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class CodeletFamilyDef(Base):
    __tablename__ = "codelet_families"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class CodeletPhaseDef(Base):
    __tablename__ = "codelet_phases"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class PostingDirectionDef(Base):
    __tablename__ = "posting_directions"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class ParamValueTypeDef(Base):
    __tablename__ = "param_value_types"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")

class DemoModeDef(Base):
    __tablename__ = "demo_modes"
    name = Column(String(32), primary_key=True)
    display_label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")


# ──────────────────────────────────────────────────────────────────
# Domain knowledge tables
# ──────────────────────────────────────────────────────────────────

class SlipnetNodeDef(Base):
    """Definition of a slipnet concept node."""

    __tablename__ = "slipnet_node_defs"

    name = Column(String(64), primary_key=True)
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
    short_name = Column(String(16), nullable=False)
    conceptual_depth = Column(Integer, nullable=False)
    description = Column(Text, default="")
    # DSL expression over `obj` deciding whether this node validly describes a
    # Workspace object (Scheme: define-descriptor-predicate).  Null for the many
    # nodes whose descriptors are read off an object rather than tested.
    descriptor_predicate = Column(Text, nullable=True)
    #: What code used to read off the name (``name[6:]``).  Names are opaque (plan 3.1).
    plain_name = Column(String(64), nullable=True)
    #: The character a letter node stands for.  Case-sensitive; a node with a glyph is a
    #: letter, and the alphabet is the set of such nodes (plan 3.13).
    glyph = Column(String(1), nullable=True, unique=True)
    #: The value of a number node.  Any integers, contiguous or not (plan 3.13).
    numeric_value = Column(Integer, nullable=True, unique=True)
    #: Display only; NULL falls back to ``plain_name`` or ``short_name`` (plan 3.3).
    full_name = Column(String(64), nullable=True)
    cm_short_name = Column(String(16), nullable=True)
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
    from_node = Column(String(64), nullable=False, index=True)
    to_node = Column(String(64), nullable=False, index=True)
    link_type = Column(String(32), ForeignKey("link_types.name"), nullable=False)
    label_node = Column(String(64), nullable=True)
    link_length = Column(Integer, nullable=True)  # None = dynamic (from label node)
    fixed_length = Column(Boolean, default=True)


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

    name = Column(String(64), primary_key=True)
    #: Seed-file order.  Same reason as ``SlipnetNodeDef.sort_order`` — the primary key
    #: is a name, so without this the order is the storage layout's.
    sort_order = Column(Integer, nullable=False, default=0, index=True)
    family = Column(String(32), ForeignKey("codelet_families.name"), nullable=False)
    phase = Column(String(32), ForeignKey("codelet_phases.name"), nullable=False)
    default_urgency = Column(Integer, nullable=True)
    description = Column(Text, default="")
    source_file = Column(String(64), default="")
    source_line = Column(Integer, default=0)
    execute_body = Column(Text, default="")  # Python source code


class EngineParam(Base):
    """A named engine parameter (key-value)."""

    __tablename__ = "engine_params"

    name = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)  # Stored as text, parsed at load
    value_type = Column(String(16), ForeignKey("param_value_types.name"), default="string")
    #: The seed file's key order (parameters are looked up by name, but the database keeps
    #: the order so that it loses nothing the file says).
    sort_order = Column(Integer, nullable=False, default=_next_after_last("engine_params"))


class UrgencyLevel(Base):
    """Named urgency tier with numeric value."""

    __tablename__ = "urgency_levels"

    name = Column(String(32), primary_key=True)
    value = Column(Integer, nullable=False)
    sort_order = Column(Integer, nullable=False, default=_next_after_last("urgency_levels"))


class FormulaCoefficient(Base):
    """Named coefficient for formulas."""

    __tablename__ = "formula_coefficients"

    name = Column(String(64), primary_key=True)
    value = Column(Float, nullable=False)
    #: ``int`` or ``float``: the JSON type the seed file gives the number, which a Float
    #: column alone cannot keep (``5`` against ``5.0``).
    value_type = Column(String(16), ForeignKey("param_value_types.name"), nullable=False, default="float")
    sort_order = Column(Integer, nullable=False, default=_next_after_last("formula_coefficients"))


class PostingRule(Base):
    """Codelet posting rule."""

    __tablename__ = "posting_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    #: The rule's natural key, so a rule can be named without its integer ``id``.  Unique;
    #: when a row is written without one it is the codelet type.
    rule_key = Column(
        String(64), nullable=False, unique=True,
        default=lambda context: context.get_current_parameters()["codelet_type"],
    )
    #: The file's order.  The engine consults the rules in sequence and every consultation
    #: costs a draw from the run's random stream, so the order is behaviour.
    sort_order = Column(Integer, nullable=False, default=_next_after_last("posting_rules"))
    codelet_type = Column(String(64), nullable=False, index=True)
    direction = Column(String(16), ForeignKey("posting_directions.name"), nullable=False)
    urgency_when_posted = Column(Integer, nullable=True)
    urgency_formula = Column(String(128), nullable=True)
    posting_formula = Column(String(256), default="")
    count_formula = Column(String(128), default="")
    #: ``json``, not ``jsonb``: JSONB reorders object keys, and key order is read back.
    count_values = Column(JSON, nullable=True)
    condition = Column(String(128), default="always")
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
    pattern_name = Column(String(64), nullable=False, index=True)
    codelet_type = Column(String(64), nullable=False)
    #: A *named* tier from ``urgency_levels``, not a number.  A pattern says which
    #: level and the run resolves it (``Coderack._pattern_entry``), so changing what
    #: ``very_high`` means moves every pattern that names it instead of leaving 77
    #: written down in a second place.
    urgency_level = Column(String(32), nullable=False)


class CommentaryTemplate(Base):
    """Commentary template text."""

    __tablename__ = "commentary_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_key = Column(String(64), nullable=False, index=True)
    #: ``json``, not ``jsonb``: the templates' key order is read back.
    template_data = Column(JSON, nullable=False)


class DemoProblem(Base):
    """Pre-configured demo problem."""

    __tablename__ = "demo_problems"
    __table_args__ = (
        Index("ix_demo_problems_mode", "mode"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, unique=True)
    section = Column(String(16), default="")
    initial = Column(String(32), nullable=False)
    modified = Column(String(32), nullable=False)
    target = Column(String(32), nullable=False)
    answer = Column(String(32), nullable=True)
    seed = Column(BigInteger, nullable=False)
    mode = Column(String(16), ForeignKey("demo_modes.name"), nullable=False)
    description = Column(Text, default="")


class ThemeDimensionDef(Base):
    """Theme dimension specification."""

    __tablename__ = "theme_dimension_defs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slipnet_node = Column(String(64), nullable=False)
    valid_relations = Column(JSONB, nullable=False)  # list of strings


class SlipnetLayoutPos(Base):
    """Grid position for slipnet visualization."""

    __tablename__ = "slipnet_layout"

    node_name = Column(String(64), primary_key=True)
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

    role = Column(String(64), primary_key=True)
    ordinal = Column(Integer, primary_key=True, default=0)
    node_name = Column(
        String(64),
        ForeignKey("slipnet_node_defs.name", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )


class CodeletTypeRole(Base):
    """A role bound to a codelet type (plan 3.2); the same shape as ``SlipnetNodeRole``."""

    __tablename__ = "codelet_type_roles"
    __table_args__ = (UniqueConstraint("codelet_type", "role", name="uq_codelet_type_role"),)

    role = Column(String(64), primary_key=True)
    ordinal = Column(Integer, primary_key=True, default=0)
    codelet_type = Column(
        String(64),
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

    name = Column(String(32), primary_key=True)
    ordinal = Column(Integer, nullable=False, default=_next_after_last("theme_relations", "ordinal"))
    node_name = Column(
        String(64),
        ForeignKey("slipnet_node_defs.name", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=True,
    )
    abstractness = Column(Integer, nullable=True)
    description = Column(Text, default="")


class HelpTopic(Base):
    """Context-sensitive documentation topic."""

    __tablename__ = "help_topics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    topic_type = Column(String(32), nullable=False, index=True)  # component, glossary
    topic_key = Column(String(64), nullable=False, unique=True, index=True)
    title = Column(String(128), nullable=False)
    short_desc = Column(Text, default="")
    full_desc = Column(Text, default="")
    metadata_json = Column("metadata", JSONB, default=dict)
