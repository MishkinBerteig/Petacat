"""MetadataService — loads metadata from Postgres into MetadataProvider.

Provides the load_from_db() classmethod for MetadataProvider and CRUD
for admin operations.
"""

from __future__ import annotations

import json
from fractions import Fraction
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import inspect as sa_inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.posting import validate_posting_formulas
from server.engine.rational import parse_rational
from server.engine.metadata import (
    CodeletRoleSpec,
    CodeletSpec,
    DemoProblem,
    MetadataProvider,
    NodeRoleSpec,
    PostingRuleSpec,
    SlipnetLinkSpec,
    SlipnodeSpec,
    ThemeDimensionSpec,
    ThemeRelationSpec,
)
from server.models.metadata import (
    BridgeOrientationDef,
    BridgeTypeDef,
    ClauseTypeDef,
    CodeletFamilyDef,
    CodeletPatternDef,
    CodeletPhaseDef,
    CodeletTypeDef,
    CodeletTypeRole,
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
    SlipnetNodeRole,
    ThemeDimensionDef,
    ThemeRelation,
    ThemeTypeDef,
    UrgencyLevel,
)


#: The enum lookup tables the provider's ``enum_values`` mirrors, and the model of each.
ENUM_TABLE_MODELS: dict[str, Any] = {
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

#: Each provider field, and the configuration tables it is built from.  A change to a table
#: rebuilds only the fields that name it (``ConfigDocument``'s per-field rebuild).
PROVIDER_FIELD_TABLES: dict[str, tuple[str, ...]] = {
    "slipnet_node_specs": ("slipnet_node_defs",),
    "slipnet_link_specs": ("slipnet_link_defs",),
    "codelet_specs": ("codelet_type_defs",),
    "posting_rules": ("posting_rules",),
    "params": ("engine_params",),
    "urgency_levels": ("urgency_levels",),
    "formula_coefficients": ("formula_coefficients",),
    "commentary_templates": ("commentary_templates",),
    "demo_problems": ("demo_problems",),
    "theme_dimensions": ("theme_dimension_defs",),
    "slipnet_layout": ("slipnet_layout",),
    "codelet_patterns": ("codelet_pattern_defs",),
    "node_roles": ("slipnet_node_roles",),
    "codelet_roles": ("codelet_type_roles",),
    "theme_relations": ("theme_relations",),
    "enum_values": tuple(ENUM_TABLE_MODELS),
}


def _rows(table: Any) -> Iterable[Mapping[str, Any]]:
    """The rows of a table given either as a sequence of rows or as ``{key: row}``."""
    return table.values() if isinstance(table, Mapping) else table


# ---------------------------------------------------------------------------
# Rows to provider fields.  This is the one implementation: the database path
# (``load_metadata_from_db``) and ``ConfigDocument.provider`` both call it.  A row is a
# plain mapping of column name to value, in the table's order (the order is behaviour for
# the nodes, links, codelet types, posting rules and parameters: it fixes the float
# accumulation order and which node each ``rng.prob`` draw is spent on).
# ---------------------------------------------------------------------------


def _field_slipnet_node_specs(tables: Mapping[str, Any]) -> dict[str, SlipnodeSpec]:
    return {
        r["name"]: SlipnodeSpec(
            name=r["name"],
            short_name=r["short_name"],
            conceptual_depth=r["conceptual_depth"],
            descriptor_predicate=r.get("descriptor_predicate"),
            plain_name=r.get("plain_name"),
            glyph=r.get("glyph"),
            numeric_value=r.get("numeric_value"),
            full_name=r.get("full_name"),
            cm_short_name=r.get("cm_short_name"),
            article_an=r.get("article_an"),
        )
        for r in _rows(tables["slipnet_node_defs"])
    }


def _field_slipnet_link_specs(tables: Mapping[str, Any]) -> list[SlipnetLinkSpec]:
    return [
        SlipnetLinkSpec(
            from_node=r["from_node"],
            to_node=r["to_node"],
            link_type=r["link_type"],
            label_node=r.get("label_node"),
            link_length=r.get("link_length"),
            fixed_length=r["fixed_length"]
            if r.get("fixed_length") is not None
            else (r.get("link_length") is not None),
        )
        for r in _rows(tables["slipnet_link_defs"])
    ]


def _field_codelet_specs(tables: Mapping[str, Any]) -> dict[str, CodeletSpec]:
    return {
        r["name"]: CodeletSpec(
            name=r["name"],
            family=r["family"],
            phase=r["phase"],
            description=r.get("description") or "",
            source_file=r.get("source_file") or "",
            source_line=r.get("source_line") or 0,
            execute_body=r.get("execute_body") or "",
        )
        for r in _rows(tables["codelet_type_defs"])
    }


def _field_posting_rules(tables: Mapping[str, Any]) -> list[PostingRuleSpec]:
    posting_rules = [
        PostingRuleSpec(
            codelet_type=r["codelet_type"],
            direction=r["direction"],
            urgency_when_posted=r.get("urgency_when_posted"),
            urgency_formula=r.get("urgency_formula"),
            posting_formula=r.get("posting_formula") or "",
            count_formula=r.get("count_formula") or "",
            count_values=r.get("count_values"),
            condition=r.get("condition") or "always",
            triggering_slipnodes=r.get("triggering_slipnodes"),
            rule_key=r["rule_key"],
        )
        for r in _rows(tables["posting_rules"])
    ]
    # A bad posting formula fails here, at load, rather than mid-run -- where it would
    # look like one codelet type exploring differently rather than like a broken
    # configuration.  The same contract the descriptor predicates get.
    validate_posting_formulas(posting_rules)
    return posting_rules


def _field_params(tables: Mapping[str, Any]) -> dict[str, Any]:
    return {r["name"]: _parse_param(r["value"], r["value_type"]) for r in _rows(tables["engine_params"])}


def _field_urgency_levels(tables: Mapping[str, Any]) -> dict[str, int]:
    return {r["name"]: r["value"] for r in _rows(tables["urgency_levels"])}


def _field_formula_coefficients(tables: Mapping[str, Any]) -> dict[str, Any]:
    # ``value_type`` restores the int, float or exact rational the text holds.
    return {
        r["name"]: _parse_coefficient(r["value"], r["value_type"])
        for r in _rows(tables["formula_coefficients"])
    }


def _field_commentary_templates(tables: Mapping[str, Any]) -> dict[str, Any]:
    commentary_templates: dict[str, Any] = {}
    for r in _rows(tables["commentary_templates"]):
        if r["template_key"] == "all":
            commentary_templates = r["template_data"]
        else:
            commentary_templates[r["template_key"]] = r["template_data"]
    return commentary_templates


def _field_demo_problems(tables: Mapping[str, Any]) -> list[DemoProblem]:
    return [
        DemoProblem(
            name=r["name"],
            section=r.get("section") or "",
            initial=r["initial"],
            modified=r["modified"],
            target=r["target"],
            answer=r.get("answer"),
            seed=r["seed"],
            mode=r["mode"],
            description=r.get("description") or "",
        )
        for r in _rows(tables["demo_problems"])
    ]


def _field_theme_dimensions(tables: Mapping[str, Any]) -> list[ThemeDimensionSpec]:
    return [
        ThemeDimensionSpec(slipnet_node=r["slipnet_node"], valid_relations=r["valid_relations"])
        for r in _rows(tables["theme_dimension_defs"])
    ]


def _field_slipnet_layout(tables: Mapping[str, Any]) -> dict[str, tuple[int, int]]:
    # Display only.
    return {r["node_name"]: (r["grid_row"], r["grid_col"]) for r in _rows(tables["slipnet_layout"])}


def _field_codelet_patterns(tables: Mapping[str, Any]) -> dict[str, list[tuple[str, str]]]:
    codelet_patterns: dict[str, list[tuple[str, str]]] = {}
    for r in _rows(tables["codelet_pattern_defs"]):
        codelet_patterns.setdefault(r["pattern_name"], []).append((r["codelet_type"], r["urgency_level"]))
    return codelet_patterns


def _field_node_roles(tables: Mapping[str, Any]) -> tuple[NodeRoleSpec, ...]:
    return tuple(
        NodeRoleSpec(role=r["role"], ordinal=r["ordinal"], node_name=r["node_name"])
        for r in _rows(tables["slipnet_node_roles"])
    )


def _field_codelet_roles(tables: Mapping[str, Any]) -> tuple[CodeletRoleSpec, ...]:
    return tuple(
        CodeletRoleSpec(role=r["role"], ordinal=r["ordinal"], codelet_type=r["codelet_type"])
        for r in _rows(tables["codelet_type_roles"])
    )


def _field_theme_relations(tables: Mapping[str, Any]) -> tuple[ThemeRelationSpec, ...]:
    return tuple(
        ThemeRelationSpec(
            name=r["name"],
            ordinal=r["ordinal"],
            node_name=r.get("node_name"),
            abstractness=r.get("abstractness"),
            description=r.get("description") or "",
        )
        for r in _rows(tables["theme_relations"])
    )


def _field_enum_values(tables: Mapping[str, Any]) -> dict[str, set[str]]:
    return {name: {r["name"] for r in _rows(tables[name])} for name in ENUM_TABLE_MODELS}


_FIELD_BUILDERS = {
    "slipnet_node_specs": _field_slipnet_node_specs,
    "slipnet_link_specs": _field_slipnet_link_specs,
    "codelet_specs": _field_codelet_specs,
    "posting_rules": _field_posting_rules,
    "params": _field_params,
    "urgency_levels": _field_urgency_levels,
    "formula_coefficients": _field_formula_coefficients,
    "commentary_templates": _field_commentary_templates,
    "demo_problems": _field_demo_problems,
    "theme_dimensions": _field_theme_dimensions,
    "slipnet_layout": _field_slipnet_layout,
    "codelet_patterns": _field_codelet_patterns,
    "node_roles": _field_node_roles,
    "codelet_roles": _field_codelet_roles,
    "theme_relations": _field_theme_relations,
    "enum_values": _field_enum_values,
}


def build_provider_field(name: str, tables: Mapping[str, Any]) -> Any:
    """One provider field built from the rows of the tables it depends on."""
    return _FIELD_BUILDERS[name](tables)


def provider_from_tables(tables: Mapping[str, Any]) -> MetadataProvider:
    """The whole provider from configuration rows (``{table name: rows in order}``)."""
    return MetadataProvider(**{name: build(tables) for name, build in _FIELD_BUILDERS.items()})


def _row_dict(row: Any) -> dict[str, Any]:
    """An ORM row as a column mapping, without the surrogate ``id`` (not stable across configurations)."""
    d = {a.key: getattr(row, a.key) for a in sa_inspect(type(row)).mapper.column_attrs}
    d.pop("id", None)
    return d


async def load_rows_from_db(session: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    """Every configuration table's rows, each in the order the engine depends on.

    Ordered explicitly.  ``select()`` promises nothing, and the order of the nodes, links,
    codelet types, parameters and posting rules is load-bearing: ``Slipnet.update_activations``
    walks the nodes for the activation spread and for the probabilistic jump, so the order
    fixes both the float accumulation order and which node each ``rng.prob`` draw is spent
    on.  Left unordered this was Postgres heap order, which drifts with every re-seed.
    ``role`` is ordered by byte value (``COLLATE "C"``) so the order does not depend on the
    database's locale.
    """
    queries = {
        "slipnet_node_defs": select(SlipnetNodeDef).order_by(SlipnetNodeDef.sort_order),
        "slipnet_link_defs": select(SlipnetLinkDef).order_by(SlipnetLinkDef.sort_order, SlipnetLinkDef.id),
        "codelet_type_defs": select(CodeletTypeDef).order_by(CodeletTypeDef.sort_order),
        "engine_params": select(EngineParam).order_by(EngineParam.sort_order, EngineParam.name),
        "urgency_levels": select(UrgencyLevel).order_by(UrgencyLevel.sort_order, UrgencyLevel.name),
        "formula_coefficients": select(FormulaCoefficient).order_by(
            FormulaCoefficient.sort_order, FormulaCoefficient.name
        ),
        "posting_rules": select(PostingRule).order_by(PostingRule.sort_order, PostingRule.id),
        "commentary_templates": select(CommentaryTemplate).order_by(CommentaryTemplate.id),
        "demo_problems": select(DemoProblemRow).order_by(DemoProblemRow.id),
        "theme_dimension_defs": select(ThemeDimensionDef).order_by(ThemeDimensionDef.id),
        "slipnet_layout": select(SlipnetLayoutPos).order_by(
            SlipnetLayoutPos.sort_order, SlipnetLayoutPos.node_name
        ),
        "codelet_pattern_defs": select(CodeletPatternDef).order_by(
            CodeletPatternDef.ordinal, CodeletPatternDef.id
        ),
        "slipnet_node_roles": select(SlipnetNodeRole).order_by(
            SlipnetNodeRole.role.collate("C"), SlipnetNodeRole.ordinal
        ),
        "codelet_type_roles": select(CodeletTypeRole).order_by(
            CodeletTypeRole.role.collate("C"), CodeletTypeRole.ordinal
        ),
        "theme_relations": select(ThemeRelation).order_by(ThemeRelation.ordinal, ThemeRelation.name),
    }
    for table_name, model in ENUM_TABLE_MODELS.items():
        queries[table_name] = select(model).order_by(model.sort_order, model.name)
    tables: dict[str, list[dict[str, Any]]] = {}
    for table_name, query in queries.items():
        result = await session.execute(query)
        tables[table_name] = [_row_dict(r) for r in result.scalars()]
    return tables


async def load_metadata_from_db(session: AsyncSession) -> MetadataProvider:
    """Load all metadata from Postgres into an immutable MetadataProvider."""
    return provider_from_tables(await load_rows_from_db(session))


def _parse_coefficient(value: str, value_type: str) -> int | float | Fraction:
    """A stored coefficient as the engine reads it: an int, a float or an exact rational."""
    if value_type == "int":
        return int(value)
    if value_type == "rational":
        return parse_rational(value)
    return float(value)


def _parse_param(value: str, value_type: str) -> Any:
    """Parse a string parameter value to its typed form."""
    if value_type == "rational":
        return parse_rational(value)
    if value_type == "int":
        return int(value)
    elif value_type == "float":
        return float(value)
    elif value_type == "bool":
        return value.lower() in ("true", "1", "yes")
    elif value_type == "json":
        return json.loads(value)
    return value
