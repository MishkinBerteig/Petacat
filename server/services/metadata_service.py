"""MetadataService — loads metadata from Postgres into MetadataProvider.

Provides the load_from_db() classmethod for MetadataProvider and CRUD
for admin operations.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.metadata import (
    CodeletSpec,
    DemoProblem,
    MetadataProvider,
    PostingRuleSpec,
    SlipnetLinkSpec,
    SlipnodeSpec,
    ThemeDimensionSpec,
)
from server.models.metadata import (
    BridgeOrientationDef,
    BridgeTypeDef,
    ClauseTypeDef,
    CodeletFamilyDef,
    CodeletPhaseDef,
    CodeletTypeDef,
    CommentaryTemplate,
    DemoModeDef,
    DemoProblem as DemoProblemRow,
    EngineParam,
    EventTypeDef,
    FormulaCoefficient,
    LinkTypeDef,
    ParamValueTypeDef,
    PostingDirectionDef,
    PostingRule,
    ProposalLevelDef,
    RuleTypeDef,
    RunStatusDef,
    SlipnetLayoutPos,
    SlipnetLinkDef,
    SlipnetNodeDef,
    ThemeDimensionDef,
    ThemeTypeDef,
    UrgencyLevel,
)


async def load_metadata_from_db(session: AsyncSession) -> MetadataProvider:
    """Load all metadata from Postgres into an immutable MetadataProvider."""

    # Slipnet nodes
    result = await session.execute(select(SlipnetNodeDef))
    node_specs = {
        row.name: SlipnodeSpec(
            name=row.name,
            short_name=row.short_name,
            conceptual_depth=row.conceptual_depth,
        )
        for row in result.scalars()
    }

    # Slipnet links
    result = await session.execute(select(SlipnetLinkDef))
    link_specs = [
        SlipnetLinkSpec(
            from_node=row.from_node,
            to_node=row.to_node,
            link_type=row.link_type,
            label_node=row.label_node,
            link_length=row.link_length,
            fixed_length=row.fixed_length if row.fixed_length is not None else (row.link_length is not None),
        )
        for row in result.scalars()
    ]

    # Codelet types
    result = await session.execute(select(CodeletTypeDef))
    codelet_specs = {
        row.name: CodeletSpec(
            name=row.name,
            family=row.family,
            phase=row.phase,
            default_urgency=row.default_urgency,
            description=row.description or "",
            source_file=row.source_file or "",
            source_line=row.source_line or 0,
            execute_body=row.execute_body or "",
        )
        for row in result.scalars()
    }

    # Engine params
    result = await session.execute(select(EngineParam))
    params: dict[str, Any] = {}
    for row in result.scalars():
        params[row.name] = _parse_param(row.value, row.value_type)

    # Urgency levels
    result = await session.execute(select(UrgencyLevel))
    urgency_levels = {row.name: row.value for row in result.scalars()}

    # Formula coefficients
    result = await session.execute(select(FormulaCoefficient))
    formula_coefficients = {row.name: row.value for row in result.scalars()}

    # Posting rules
    result = await session.execute(select(PostingRule))
    posting_rules = [
        PostingRuleSpec(
            codelet_type=row.codelet_type,
            direction=row.direction,
            urgency_when_posted=row.urgency_when_posted,
            urgency_formula=row.urgency_formula,
            posting_formula=row.posting_formula or "",
            count_formula=row.count_formula or "",
            count_values=row.count_values,
            condition=row.condition or "always",
            triggering_slipnodes=row.triggering_slipnodes,
        )
        for row in result.scalars()
    ]

    # Commentary templates
    result = await session.execute(select(CommentaryTemplate))
    commentary_templates: dict[str, Any] = {}
    for row in result.scalars():
        if row.template_key == "all":
            commentary_templates = row.template_data
        else:
            commentary_templates[row.template_key] = row.template_data

    # Demo problems
    result = await session.execute(select(DemoProblemRow))
    demo_problems = [
        DemoProblem(
            name=row.name,
            section=row.section or "",
            initial=row.initial,
            modified=row.modified,
            target=row.target,
            answer=row.answer,
            seed=row.seed,
            mode=row.mode,
            description=row.description or "",
        )
        for row in result.scalars()
    ]

    # Theme dimensions
    result = await session.execute(select(ThemeDimensionDef))
    theme_dimensions = [
        ThemeDimensionSpec(
            slipnet_node=row.slipnet_node,
            valid_relations=row.valid_relations,
        )
        for row in result.scalars()
    ]

    # Slipnet layout
    result = await session.execute(select(SlipnetLayoutPos))
    slipnet_layout = {
        row.node_name: (row.grid_row, row.grid_col) for row in result.scalars()
    }

    # Codelet patterns (from posting_rules JSON — stored inline in seed_data)
    # For now, load from the posting rules JSON structure if available
    codelet_patterns: dict[str, list[tuple[str, int]]] = {}

    # Enum values from lookup tables
    enum_table_models = {
        "run_statuses": RunStatusDef,
        "event_types": EventTypeDef,
        "bridge_types": BridgeTypeDef,
        "bridge_orientations": BridgeOrientationDef,
        "clause_types": ClauseTypeDef,
        "rule_types": RuleTypeDef,
        "theme_types": ThemeTypeDef,
        "proposal_levels": ProposalLevelDef,
        "link_types": LinkTypeDef,
        "codelet_families": CodeletFamilyDef,
        "codelet_phases": CodeletPhaseDef,
        "posting_directions": PostingDirectionDef,
        "param_value_types": ParamValueTypeDef,
        "demo_modes": DemoModeDef,
    }
    enum_values: dict[str, set[str]] = {}
    for table_name, model in enum_table_models.items():
        result = await session.execute(select(model))
        enum_values[table_name] = {row.name for row in result.scalars()}

    return MetadataProvider(
        slipnet_node_specs=node_specs,
        slipnet_link_specs=link_specs,
        codelet_specs=codelet_specs,
        posting_rules=posting_rules,
        params=params,
        urgency_levels=urgency_levels,
        formula_coefficients=formula_coefficients,
        commentary_templates=commentary_templates,
        demo_problems=demo_problems,
        theme_dimensions=theme_dimensions,
        slipnet_layout=slipnet_layout,
        codelet_patterns=codelet_patterns,
        enum_values=enum_values,
    )


def _parse_param(value: str, value_type: str) -> Any:
    """Parse a string parameter value to its typed form."""
    if value_type == "int":
        return int(value)
    elif value_type == "float":
        return float(value)
    elif value_type == "bool":
        return value.lower() in ("true", "1", "yes")
    elif value_type == "json":
        return json.loads(value)
    return value
