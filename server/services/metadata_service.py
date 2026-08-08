"""MetadataService — loads metadata from Postgres into MetadataProvider.

Provides the load_from_db() classmethod for MetadataProvider and CRUD
for admin operations.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.posting import validate_posting_formulas
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
    CodeletPatternDef,
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

    # Slipnet nodes.
    #
    # `descriptor_predicate` is read back here.  It had the column, the startup
    # reconciliation that adds it to older databases, and the seeder that writes it —
    # and this loader built the spec from three columns and left the fourth behind, so
    # every configuration the application loaded from the database had all fourteen
    # predicates missing.  A node whose predicate is `None` falls back to being read
    # off the object (`slipnet.py:146`), which is a valid state for the fifty-odd nodes
    # that ship that way and silently wrong for the fourteen that do not.
    # Ordered explicitly.  ``select()`` promises nothing, and the node order is
    # load-bearing: ``Slipnet.update_activations`` walks the nodes for the activation
    # spread and for the probabilistic jump, so the order fixes both the float
    # accumulation order and which node each ``rng.prob`` draw is spent on.  Left
    # unordered this was Postgres heap order, which drifts with every re-seed — the
    # development database returned ``plato-y, plato-z, plato-one, …`` and ran a
    # measurably different engine from the seed data.
    result = await session.execute(
        select(SlipnetNodeDef).order_by(SlipnetNodeDef.sort_order)
    )
    node_specs = {
        row.name: SlipnodeSpec(
            name=row.name,
            short_name=row.short_name,
            conceptual_depth=row.conceptual_depth,
            descriptor_predicate=row.descriptor_predicate,
        )
        for row in result.scalars()
    }

    # Slipnet links
    result = await session.execute(select(SlipnetLinkDef).order_by(SlipnetLinkDef.id))
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
    result = await session.execute(
        select(CodeletTypeDef).order_by(CodeletTypeDef.sort_order)
    )
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

    # Posting rules.  Ordered explicitly: the engine consults these in sequence and
    # every consultation costs a draw from the run's random stream, so the order is
    # part of the configuration rather than an incidental of the query.  `id` carries
    # it, assigned from the seed file's order when the row is written.
    result = await session.execute(select(PostingRule).order_by(PostingRule.id))
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

    # A bad posting formula fails here, at load, rather than mid-run — where it would
    # look like one codelet type exploring differently rather than like a broken
    # configuration.  The same contract the descriptor predicates get.
    validate_posting_formulas(posting_rules)

    # Commentary templates
    result = await session.execute(select(CommentaryTemplate))
    commentary_templates: dict[str, Any] = {}
    for row in result.scalars():
        if row.template_key == "all":
            commentary_templates = row.template_data
        else:
            commentary_templates[row.template_key] = row.template_data

    # Demo problems
    result = await session.execute(select(DemoProblemRow).order_by(DemoProblemRow.id))
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
    result = await session.execute(
        select(ThemeDimensionDef).order_by(ThemeDimensionDef.id)
    )
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

    # Codelet patterns.  Ordered by `id`, which the seeder assigns across every
    # pattern, so both the order of the patterns and the order within each one come
    # back as the seed file wrote them.
    result = await session.execute(
        select(CodeletPatternDef).order_by(CodeletPatternDef.id)
    )
    codelet_patterns: dict[str, list[tuple[str, int]]] = {}
    for row in result.scalars():
        codelet_patterns.setdefault(row.pattern_name, []).append(
            (row.codelet_type, row.urgency_level)
        )

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
