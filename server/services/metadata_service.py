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
from server.engine.roles import ROLE_COLUMN, vocabulary_bindings
from server.engine.metadata import (
    BridgeTypeSpec,
    ClampTypeSpec,
    CodeletRoleSpec,
    CodeletSpec,
    DemoProblem,
    InitialActivationRuleSpec,
    InputCharacterRangeSpec,
    InputLoweringRangeSpec,
    InitialDescriptionRuleSpec,
    LinkTypeSpec,
    MetadataProvider,
    NodeRoleSpec,
    PostingRuleSpec,
    ProgressFocusSpec,
    RuleTypeSpec,
    SlipnetLinkSpec,
    SlipnodeSpec,
    StringKindSpec,
    ThemeDimensionSpec,
    ThemeRelationSpec,
)
from server.models.metadata import (
    BridgeOrientationDef,
    BridgeTypeDef,
    ClampTypeDef,
    ClauseTypeDef,
    CodeletFamilyDef,
    CodeletPatternDef,
    CodeletPhaseDef,
    CodeletTypeDef,
    CodeletTypeRole,
    CommentaryTemplate,
    DemoProblem as DemoProblemRow,
    EngineParam,
    EventTypeDef,
    FailureKindDef,
    FormulaCoefficient,
    InitialActivationRule,
    InputCharacterRange,
    InputLoweringRange,
    InitialDescriptionRule,
    LinkTypeDef,
    ParamValueTypeDef,
    PostingDirectionDef,
    PostingRule,
    ProgressFocusDef,
    ProposalLevelDef,
    RuleScopeDef,
    RuleTypeDef,
    RunStatusDef,
    SlipnetLayoutPos,
    SlipnetLinkDef,
    SlipnetNodeDef,
    SlipnetNodeRole,
    StringKindDef,
    ThemeDimensionDef,
    ThemeRelation,
    ThemeTypeDef,
    UrgencyLevel,
)


#: The enum lookup tables (17), and the model of each.  ``link_types`` is not one: it is a
#: configuration table the change API addresses (``config_registry``), loaded beside them
#: (:data:`ENUM_FILE_TABLE_MODELS`).
ENUM_TABLE_MODELS: dict[str, Any] = {
    "run_statuses": RunStatusDef,
    "event_types": EventTypeDef,
    "bridge_types": BridgeTypeDef,
    "bridge_orientations": BridgeOrientationDef,
    "clause_types": ClauseTypeDef,
    "rule_types": RuleTypeDef,
    "theme_types": ThemeTypeDef,
    "proposal_levels": ProposalLevelDef,
    "codelet_families": CodeletFamilyDef,
    "codelet_phases": CodeletPhaseDef,
    "posting_directions": PostingDirectionDef,
    "param_value_types": ParamValueTypeDef,
    "string_kinds": StringKindDef,
    "rule_scopes": RuleScopeDef,
    "failure_kinds": FailureKindDef,
    "clamp_types": ClampTypeDef,
    "progress_focuses": ProgressFocusDef,
}

#: The tables the Metacat Standard Configuration's ``enums.json`` holds: the 17 enum tables and
#: ``link_types``, which the change API addresses.
ENUM_FILE_TABLE_MODELS: dict[str, Any] = {**ENUM_TABLE_MODELS, "link_types": LinkTypeDef}

#: Each provider field, and the configuration tables it is built from.  A change to a table
#: rebuilds only the fields that name it (``ConfigDocument``'s per-field rebuild).
PROVIDER_FIELD_TABLES: dict[str, tuple[str, ...]] = {
    "slipnet_node_specs": ("slipnet_node_defs",),
    "slipnet_link_specs": ("slipnet_link_defs",),
    "codelet_specs": ("codelet_type_defs",),
    "posting_rules": ("posting_rules",),
    "params": ("engine_params",),
    "param_refers_to": ("engine_params",),
    "urgency_levels": ("urgency_levels",),
    "formula_coefficients": ("formula_coefficients",),
    "commentary_templates": ("commentary_templates",),
    "demo_problems": ("demo_problems",),
    "theme_dimensions": ("theme_dimension_defs",),
    "slipnet_layout": ("slipnet_layout",),
    "codelet_patterns": ("codelet_pattern_defs",),
    "node_roles": ("slipnet_node_roles",),
    "codelet_roles": ("codelet_type_roles",),
    "initial_description_rules": ("initial_description_rules",),
    "initial_activation_rules": ("initial_activation_rules",),
    "input_character_ranges": ("input_character_ranges",),
    "input_lowering_ranges": ("input_lowering_ranges",),
    "theme_relations": ("theme_relations",),
    "vocabulary_bindings": tuple(ROLE_COLUMN),
    "string_kinds": ("string_kinds",),
    "bridge_types": ("bridge_types",),
    "rule_types": ("rule_types",),
    "link_types": ("link_types",),
    "clamp_types": ("clamp_types",),
    "progress_focuses": ("progress_focuses",),
    "serialised_families": ("codelet_families",),
}

#: A provider field that reads only some of the columns of a table it is built from: an update
#: that sets none of them leaves the field as it was (``engine_params`` feeds both the
#: parameters and what their names refer to).  A field not listed here reads every column.
PROVIDER_FIELD_COLUMNS: dict[str, dict[str, frozenset[str]]] = {
    "param_refers_to": {"engine_params": frozenset({"name", "sort_order", "refers_to"})},
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
            fixed_length=r["fixed_length"],
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


def _stated(row: Mapping[str, Any], column: str) -> str:
    """A posting rule's formula or condition, which the rule must state.

    No default stands in for an unstated one: an empty ``posting_formula`` was answered
    with a probability of 0.5, an empty ``count_formula`` with a count of 1 and an empty
    ``condition`` with ``always``, all invented by the code.  The row states them, or the
    configuration does not load."""
    value = row[column]
    if not value:
        raise ValueError(
            f"posting rule '{row['rule_key']}' states no {column}; "
            "a posting rule must state its posting_formula, count_formula and condition"
        )
    return value


def _field_posting_rules(tables: Mapping[str, Any]) -> list[PostingRuleSpec]:
    posting_rules = [
        PostingRuleSpec(
            codelet_type=r["codelet_type"],
            direction=r["direction"],
            urgency_level=r.get("urgency_level"),
            urgency_formula=r.get("urgency_formula"),
            posting_formula=_stated(r, "posting_formula"),
            count_formula=_stated(r, "count_formula"),
            count_values=r.get("count_values"),
            condition=_stated(r, "condition"),
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


def _field_param_refers_to(tables: Mapping[str, Any]) -> dict[str, str]:
    return {r["name"]: r["refers_to"] for r in _rows(tables["engine_params"]) if r.get("refers_to")}


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


def _field_initial_description_rules(tables: Mapping[str, Any]) -> tuple[InitialDescriptionRuleSpec, ...]:
    return tuple(
        InitialDescriptionRuleSpec(
            rule_key=r["rule_key"],
            ordinal=r["ordinal"],
            dimension_role=r["dimension_role"],
            descriptor_source=r["descriptor_source"],
            descriptor_role=r.get("descriptor_role"),
            condition=r["condition"],
            activate_descriptor=bool(r["activate_descriptor"]),
            subject=r["subject"],
            built=bool(r["built"]),
            bond_description=bool(r["bond_description"]),
        )
        for r in _rows(tables["initial_description_rules"])
    )


def _field_initial_activation_rules(tables: Mapping[str, Any]) -> tuple[InitialActivationRuleSpec, ...]:
    return tuple(
        InitialActivationRuleSpec(
            rule_key=r["rule_key"],
            ordinal=r["ordinal"],
            node_role=r["node_role"],
            condition=r["condition"],
        )
        for r in _rows(tables["initial_activation_rules"])
    )


def _field_input_character_ranges(tables: Mapping[str, Any]) -> tuple[InputCharacterRangeSpec, ...]:
    return tuple(
        (r["kind"], r["first"], r["last"])
        for r in _rows(tables["input_character_ranges"])
    )


def _field_input_lowering_ranges(tables: Mapping[str, Any]) -> tuple[InputLoweringRangeSpec, ...]:
    return tuple(
        (r["first"], r["last"], r["step"], r["delta"])
        for r in _rows(tables["input_lowering_ranges"])
    )


def _field_theme_relations(tables: Mapping[str, Any]) -> tuple[ThemeRelationSpec, ...]:
    return tuple(
        ThemeRelationSpec(
            name=r["name"],
            ordinal=r["ordinal"],
            node_name=r.get("node_name"),
            abstractness=r.get("abstractness"),
            description=r.get("description") or "",
            role=r.get("role"),
        )
        for r in _rows(tables["theme_relations"])
    )


def _field_vocabulary_bindings(tables: Mapping[str, Any]) -> tuple:
    return vocabulary_bindings({name: list(_rows(tables[name])) for name in ROLE_COLUMN})


def _field_string_kinds(tables: Mapping[str, Any]) -> tuple[StringKindSpec, ...]:
    return tuple(
        StringKindSpec(name=r["name"], role=r.get("role"), exists_at_start=bool(r.get("exists_at_start")))
        for r in _rows(tables["string_kinds"])
    )


def _field_bridge_types(tables: Mapping[str, Any]) -> tuple[BridgeTypeSpec, ...]:
    return tuple(
        BridgeTypeSpec(
            name=r["name"],
            role=r.get("role"),
            from_string_kind=r.get("from_string_kind"),
            to_string_kind=r.get("to_string_kind"),
            orientation=r.get("orientation"),
            theme_type=r.get("theme_type"),
        )
        for r in _rows(tables["bridge_types"])
    )


def _field_rule_types(tables: Mapping[str, Any]) -> tuple[RuleTypeSpec, ...]:
    return tuple(
        RuleTypeSpec(name=r["name"], role=r.get("role"), bridge_type=r.get("bridge_type"))
        for r in _rows(tables["rule_types"])
    )


def _field_link_types(tables: Mapping[str, Any]) -> tuple[LinkTypeSpec, ...]:
    return tuple(
        LinkTypeSpec(name=r["name"], behaviour=r.get("behaviour")) for r in _rows(tables["link_types"])
    )


def _field_clamp_types(tables: Mapping[str, Any]) -> tuple[ClampTypeSpec, ...]:
    return tuple(
        ClampTypeSpec(
            name=r["name"],
            role=r.get("role"),
            codelet_background_level=r.get("codelet_background_level"),
            jootsing_factor=r.get("jootsing_factor"),
            jootsing_only_when_latest=bool(r.get("jootsing_only_when_latest")),
            progress_focus=r.get("progress_focus"),
            codelet_patterns=tuple(r.get("codelet_patterns") or ()),
        )
        for r in _rows(tables["clamp_types"])
    )


def _field_progress_focuses(tables: Mapping[str, Any]) -> tuple[ProgressFocusSpec, ...]:
    return tuple(
        ProgressFocusSpec(name=r["name"], event_types=tuple(r["event_types"]))
        for r in _rows(tables["progress_focuses"])
    )


def _field_serialised_families(tables: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(r["name"] for r in _rows(tables["codelet_families"]) if r.get("serialised"))


_FIELD_BUILDERS = {
    "slipnet_node_specs": _field_slipnet_node_specs,
    "slipnet_link_specs": _field_slipnet_link_specs,
    "codelet_specs": _field_codelet_specs,
    "posting_rules": _field_posting_rules,
    "params": _field_params,
    "param_refers_to": _field_param_refers_to,
    "urgency_levels": _field_urgency_levels,
    "formula_coefficients": _field_formula_coefficients,
    "commentary_templates": _field_commentary_templates,
    "demo_problems": _field_demo_problems,
    "theme_dimensions": _field_theme_dimensions,
    "slipnet_layout": _field_slipnet_layout,
    "codelet_patterns": _field_codelet_patterns,
    "node_roles": _field_node_roles,
    "codelet_roles": _field_codelet_roles,
    "initial_description_rules": _field_initial_description_rules,
    "initial_activation_rules": _field_initial_activation_rules,
    "input_character_ranges": _field_input_character_ranges,
    "input_lowering_ranges": _field_input_lowering_ranges,
    "theme_relations": _field_theme_relations,
    "vocabulary_bindings": _field_vocabulary_bindings,
    "string_kinds": _field_string_kinds,
    "bridge_types": _field_bridge_types,
    "rule_types": _field_rule_types,
    "link_types": _field_link_types,
    "clamp_types": _field_clamp_types,
    "progress_focuses": _field_progress_focuses,
    "serialised_families": _field_serialised_families,
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
    from server.services.config_registry import LAYER_REGISTRY

    # Every table with order columns is ordered by its total order (``TableSpec.order_by``): the
    # order columns, then the rest of the natural key, which a ``ConfigDocument`` sorts by too.
    # A table with no order columns keeps insertion order (``id``), which a document also keeps.
    insertion_order = {
        "commentary_templates": CommentaryTemplate,
        "demo_problems": DemoProblemRow,
        "theme_dimension_defs": ThemeDimensionDef,
    }
    models = {
        "slipnet_node_defs": SlipnetNodeDef,
        "slipnet_link_defs": SlipnetLinkDef,
        "codelet_type_defs": CodeletTypeDef,
        "engine_params": EngineParam,
        "urgency_levels": UrgencyLevel,
        "formula_coefficients": FormulaCoefficient,
        "posting_rules": PostingRule,
        "slipnet_layout": SlipnetLayoutPos,
        "codelet_pattern_defs": CodeletPatternDef,
        "slipnet_node_roles": SlipnetNodeRole,
        "codelet_type_roles": CodeletTypeRole,
        "theme_relations": ThemeRelation,
        "initial_description_rules": InitialDescriptionRule,
        "initial_activation_rules": InitialActivationRule,
        "input_character_ranges": InputCharacterRange,
        "input_lowering_ranges": InputLoweringRange,
        **ENUM_FILE_TABLE_MODELS,
    }
    queries = {
        name: select(model).order_by(*LAYER_REGISTRY[name].order_by())
        for name, model in models.items()
    }
    for name, model in insertion_order.items():
        queries[name] = select(model).order_by(model.id)
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
