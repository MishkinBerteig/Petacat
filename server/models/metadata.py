"""SQLAlchemy ORM models for metadata tables.

These tables define the system's domain knowledge — slipnet topology,
codelet types, engine parameters, etc. They are seeded from seed_data/
JSON files and can be edited via the admin panel.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, Float, ForeignKey, Index, Integer, String, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


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
    short_name = Column(String(16), nullable=False)
    conceptual_depth = Column(Integer, nullable=False)
    description = Column(Text, default="")


class SlipnetLinkDef(Base):
    """Definition of a slipnet link between two nodes."""

    __tablename__ = "slipnet_link_defs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_node = Column(String(64), nullable=False, index=True)
    to_node = Column(String(64), nullable=False, index=True)
    link_type = Column(String(32), ForeignKey("link_types.name"), nullable=False)
    label_node = Column(String(64), nullable=True)
    link_length = Column(Integer, nullable=True)  # None = dynamic (from label node)
    fixed_length = Column(Boolean, default=True)


class CodeletTypeDef(Base):
    """Definition of a codelet type with its behavior as Python source."""

    __tablename__ = "codelet_type_defs"

    name = Column(String(64), primary_key=True)
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


class UrgencyLevel(Base):
    """Named urgency tier with numeric value."""

    __tablename__ = "urgency_levels"

    name = Column(String(32), primary_key=True)
    value = Column(Integer, nullable=False)


class FormulaCoefficient(Base):
    """Named coefficient for formulas."""

    __tablename__ = "formula_coefficients"

    name = Column(String(64), primary_key=True)
    value = Column(Float, nullable=False)


class PostingRule(Base):
    """Codelet posting rule."""

    __tablename__ = "posting_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codelet_type = Column(String(64), nullable=False, index=True)
    direction = Column(String(16), ForeignKey("posting_directions.name"), nullable=False)
    urgency_when_posted = Column(Integer, nullable=True)
    urgency_formula = Column(String(128), nullable=True)
    posting_formula = Column(String(256), default="")
    count_formula = Column(String(128), default="")
    count_values = Column(JSONB, nullable=True)
    condition = Column(String(128), default="always")
    triggering_slipnodes = Column(JSONB, nullable=True)


class CommentaryTemplate(Base):
    """Commentary template text."""

    __tablename__ = "commentary_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_key = Column(String(64), nullable=False, index=True)
    template_data = Column(JSONB, nullable=False)


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
