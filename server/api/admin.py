"""FastAPI router for admin metadata CRUD.

Provides CRUD for slipnet nodes, links, codelet types, engine params,
urgency levels, formula coefficients, and demo problems.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session
from server.models.metadata import (
    BridgeOrientationDef,
    BridgeTypeDef,
    ClauseTypeDef,
    CodeletFamilyDef,
    CodeletPhaseDef,
    CodeletTypeDef,
    CommentaryTemplate,
    DemoModeDef,
    DemoProblem,
    EngineParam,
    EventTypeDef,
    FormulaCoefficient,
    HelpTopic,
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

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------


class SlipnetNodeRequest(BaseModel):
    name: str
    short_name: str
    conceptual_depth: int
    description: str = ""


class SlipnetNodeResponse(BaseModel):
    name: str
    short_name: str
    conceptual_depth: int
    description: str


class SlipnetLinkRequest(BaseModel):
    from_node: str
    to_node: str
    link_type: str
    label_node: str | None = None
    link_length: int | None = None
    fixed_length: bool = True


class SlipnetLinkResponse(BaseModel):
    id: int
    from_node: str
    to_node: str
    link_type: str
    label_node: str | None
    link_length: int | None
    fixed_length: bool


class CodeletTypeRequest(BaseModel):
    name: str
    family: str
    phase: str
    default_urgency: int | None = None
    description: str = ""
    source_file: str = ""
    source_line: int = 0
    execute_body: str = ""


class CodeletTypeResponse(BaseModel):
    name: str
    family: str
    phase: str
    default_urgency: int | None
    description: str
    source_file: str
    source_line: int
    execute_body: str


class ParamUpdateRequest(BaseModel):
    value: str


class ParamResponse(BaseModel):
    name: str
    value: str
    value_type: str


class UrgencyLevelUpdateRequest(BaseModel):
    value: int


class UrgencyLevelResponse(BaseModel):
    name: str
    value: int


class FormulaCoefficientUpdateRequest(BaseModel):
    value: float


class FormulaCoefficientResponse(BaseModel):
    name: str
    value: float


class DemoProblemRequest(BaseModel):
    name: str
    section: str = ""
    initial: str
    modified: str
    target: str
    answer: str | None = None
    seed: int = 0
    mode: str = "discovery"
    description: str = ""


class DemoProblemResponse(BaseModel):
    id: int
    name: str
    section: str
    initial: str
    modified: str
    target: str
    answer: str | None
    seed: int
    mode: str
    description: str


# ------------------------------------------------------------------
# Slipnet nodes
# ------------------------------------------------------------------


@router.get("/slipnet/nodes", response_model=list[SlipnetNodeResponse])
async def list_slipnet_nodes(session: AsyncSession = Depends(get_session)):
    """List all slipnet node definitions."""
    result = await session.execute(
        select(SlipnetNodeDef).order_by(SlipnetNodeDef.name)
    )
    rows = result.scalars().all()
    return [
        SlipnetNodeResponse(
            name=r.name,
            short_name=r.short_name,
            conceptual_depth=r.conceptual_depth,
            description=r.description or "",
        )
        for r in rows
    ]


@router.post("/slipnet/nodes", response_model=SlipnetNodeResponse, status_code=201)
async def create_slipnet_node(
    req: SlipnetNodeRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new slipnet node definition."""
    # Check for duplicate
    existing = await session.get(SlipnetNodeDef, req.name)
    if existing is not None:
        raise HTTPException(409, f"Node '{req.name}' already exists")

    node = SlipnetNodeDef(
        name=req.name,
        short_name=req.short_name,
        conceptual_depth=req.conceptual_depth,
        description=req.description,
    )
    session.add(node)
    await session.commit()
    return SlipnetNodeResponse(
        name=node.name,
        short_name=node.short_name,
        conceptual_depth=node.conceptual_depth,
        description=node.description or "",
    )


@router.put("/slipnet/nodes/{name}", response_model=SlipnetNodeResponse)
async def update_slipnet_node(
    name: str,
    req: SlipnetNodeRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a slipnet node definition."""
    node = await session.get(SlipnetNodeDef, name)
    if node is None:
        raise HTTPException(404, f"Node '{name}' not found")
    node.short_name = req.short_name
    node.conceptual_depth = req.conceptual_depth
    node.description = req.description
    await session.commit()
    return SlipnetNodeResponse(
        name=node.name,
        short_name=node.short_name,
        conceptual_depth=node.conceptual_depth,
        description=node.description or "",
    )


@router.delete("/slipnet/nodes/{name}")
async def delete_slipnet_node(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a slipnet node definition."""
    node = await session.get(SlipnetNodeDef, name)
    if node is None:
        raise HTTPException(404, f"Node '{name}' not found")
    await session.delete(node)
    await session.commit()
    return {"deleted": name}


# ------------------------------------------------------------------
# Slipnet links
# ------------------------------------------------------------------


@router.get("/slipnet/links", response_model=list[SlipnetLinkResponse])
async def list_slipnet_links(session: AsyncSession = Depends(get_session)):
    """List all slipnet link definitions."""
    result = await session.execute(
        select(SlipnetLinkDef).order_by(SlipnetLinkDef.id)
    )
    rows = result.scalars().all()
    return [
        SlipnetLinkResponse(
            id=r.id,
            from_node=r.from_node,
            to_node=r.to_node,
            link_type=r.link_type,
            label_node=r.label_node,
            link_length=r.link_length,
            fixed_length=r.fixed_length if r.fixed_length is not None else True,
        )
        for r in rows
    ]


@router.post("/slipnet/links", response_model=SlipnetLinkResponse, status_code=201)
async def create_slipnet_link(
    req: SlipnetLinkRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new slipnet link definition."""
    link = SlipnetLinkDef(
        from_node=req.from_node,
        to_node=req.to_node,
        link_type=req.link_type,
        label_node=req.label_node,
        link_length=req.link_length,
        fixed_length=req.fixed_length,
    )
    session.add(link)
    await session.flush()
    await session.commit()
    return SlipnetLinkResponse(
        id=link.id,
        from_node=link.from_node,
        to_node=link.to_node,
        link_type=link.link_type,
        label_node=link.label_node,
        link_length=link.link_length,
        fixed_length=link.fixed_length if link.fixed_length is not None else True,
    )


@router.put("/slipnet/links/{link_id}", response_model=SlipnetLinkResponse)
async def update_slipnet_link(
    link_id: int,
    req: SlipnetLinkRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a slipnet link definition."""
    link = await session.get(SlipnetLinkDef, link_id)
    if link is None:
        raise HTTPException(404, f"Link {link_id} not found")
    link.from_node = req.from_node
    link.to_node = req.to_node
    link.link_type = req.link_type
    link.label_node = req.label_node
    link.link_length = req.link_length
    link.fixed_length = req.fixed_length
    await session.commit()
    return SlipnetLinkResponse(
        id=link.id,
        from_node=link.from_node,
        to_node=link.to_node,
        link_type=link.link_type,
        label_node=link.label_node,
        link_length=link.link_length,
        fixed_length=link.fixed_length if link.fixed_length is not None else True,
    )


@router.delete("/slipnet/links/{link_id}")
async def delete_slipnet_link(
    link_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete a slipnet link definition."""
    link = await session.get(SlipnetLinkDef, link_id)
    if link is None:
        raise HTTPException(404, f"Link {link_id} not found")
    await session.delete(link)
    await session.commit()
    return {"deleted": link_id}


# ------------------------------------------------------------------
# Codelet types
# ------------------------------------------------------------------


@router.get("/codelets", response_model=list[CodeletTypeResponse])
async def list_codelet_types(session: AsyncSession = Depends(get_session)):
    """List all codelet type definitions."""
    result = await session.execute(
        select(CodeletTypeDef).order_by(CodeletTypeDef.name)
    )
    rows = result.scalars().all()
    return [
        CodeletTypeResponse(
            name=r.name,
            family=r.family,
            phase=r.phase,
            default_urgency=r.default_urgency,
            description=r.description or "",
            source_file=r.source_file or "",
            source_line=r.source_line or 0,
            execute_body=r.execute_body or "",
        )
        for r in rows
    ]


@router.post("/codelets", response_model=CodeletTypeResponse, status_code=201)
async def create_codelet_type(
    req: CodeletTypeRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new codelet type definition."""
    existing = await session.get(CodeletTypeDef, req.name)
    if existing is not None:
        raise HTTPException(409, f"Codelet type '{req.name}' already exists")

    codelet = CodeletTypeDef(
        name=req.name,
        family=req.family,
        phase=req.phase,
        default_urgency=req.default_urgency,
        description=req.description,
        source_file=req.source_file,
        source_line=req.source_line,
        execute_body=req.execute_body,
    )
    session.add(codelet)
    await session.commit()
    return CodeletTypeResponse(
        name=codelet.name,
        family=codelet.family,
        phase=codelet.phase,
        default_urgency=codelet.default_urgency,
        description=codelet.description or "",
        source_file=codelet.source_file or "",
        source_line=codelet.source_line or 0,
        execute_body=codelet.execute_body or "",
    )


@router.put("/codelets/{name}", response_model=CodeletTypeResponse)
async def update_codelet_type(
    name: str,
    req: CodeletTypeRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a codelet type definition."""
    codelet = await session.get(CodeletTypeDef, name)
    if codelet is None:
        raise HTTPException(404, f"Codelet type '{name}' not found")
    codelet.family = req.family
    codelet.phase = req.phase
    codelet.default_urgency = req.default_urgency
    codelet.description = req.description
    codelet.source_file = req.source_file
    codelet.source_line = req.source_line
    codelet.execute_body = req.execute_body
    await session.commit()
    return CodeletTypeResponse(
        name=codelet.name,
        family=codelet.family,
        phase=codelet.phase,
        default_urgency=codelet.default_urgency,
        description=codelet.description or "",
        source_file=codelet.source_file or "",
        source_line=codelet.source_line or 0,
        execute_body=codelet.execute_body or "",
    )


@router.delete("/codelets/{name}")
async def delete_codelet_type(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a codelet type definition."""
    codelet = await session.get(CodeletTypeDef, name)
    if codelet is None:
        raise HTTPException(404, f"Codelet type '{name}' not found")
    await session.delete(codelet)
    await session.commit()
    return {"deleted": name}


# ------------------------------------------------------------------
# Engine params
# ------------------------------------------------------------------


@router.get("/params", response_model=list[ParamResponse])
async def list_params(session: AsyncSession = Depends(get_session)):
    """List all engine parameters."""
    result = await session.execute(
        select(EngineParam).order_by(EngineParam.name)
    )
    rows = result.scalars().all()
    return [
        ParamResponse(name=r.name, value=r.value, value_type=r.value_type or "string")
        for r in rows
    ]


@router.post("/params", response_model=ParamResponse, status_code=201)
async def create_param(
    req: ParamResponse,
    session: AsyncSession = Depends(get_session),
):
    """Create a new engine parameter."""
    existing = await session.get(EngineParam, req.name)
    if existing is not None:
        raise HTTPException(409, f"Parameter '{req.name}' already exists")
    param = EngineParam(name=req.name, value=req.value, value_type=req.value_type)
    session.add(param)
    await session.commit()
    return ParamResponse(name=param.name, value=param.value, value_type=param.value_type or "string")


@router.put("/params/{name}", response_model=ParamResponse)
async def update_param(
    name: str,
    req: ParamUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update an engine parameter value."""
    param = await session.get(EngineParam, name)
    if param is None:
        raise HTTPException(404, f"Parameter '{name}' not found")
    param.value = req.value
    await session.commit()
    return ParamResponse(
        name=param.name,
        value=param.value,
        value_type=param.value_type or "string",
    )


@router.delete("/params/{name}")
async def delete_param(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete an engine parameter."""
    param = await session.get(EngineParam, name)
    if param is None:
        raise HTTPException(404, f"Parameter '{name}' not found")
    await session.delete(param)
    await session.commit()
    return {"deleted": name}


# ------------------------------------------------------------------
# Urgency levels
# ------------------------------------------------------------------


@router.get("/urgency-levels", response_model=list[UrgencyLevelResponse])
async def list_urgency_levels(session: AsyncSession = Depends(get_session)):
    """List all urgency level definitions."""
    result = await session.execute(
        select(UrgencyLevel).order_by(UrgencyLevel.name)
    )
    rows = result.scalars().all()
    return [UrgencyLevelResponse(name=r.name, value=r.value) for r in rows]


@router.post("/urgency-levels", response_model=UrgencyLevelResponse, status_code=201)
async def create_urgency_level(
    req: UrgencyLevelResponse,
    session: AsyncSession = Depends(get_session),
):
    """Create a new urgency level."""
    existing = await session.get(UrgencyLevel, req.name)
    if existing is not None:
        raise HTTPException(409, f"Urgency level '{req.name}' already exists")
    level = UrgencyLevel(name=req.name, value=req.value)
    session.add(level)
    await session.commit()
    return UrgencyLevelResponse(name=level.name, value=level.value)


@router.put("/urgency-levels/{name}", response_model=UrgencyLevelResponse)
async def update_urgency_level(
    name: str,
    req: UrgencyLevelUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update an urgency level value."""
    level = await session.get(UrgencyLevel, name)
    if level is None:
        raise HTTPException(404, f"Urgency level '{name}' not found")
    level.value = req.value
    await session.commit()
    return UrgencyLevelResponse(name=level.name, value=level.value)


@router.delete("/urgency-levels/{name}")
async def delete_urgency_level(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete an urgency level."""
    level = await session.get(UrgencyLevel, name)
    if level is None:
        raise HTTPException(404, f"Urgency level '{name}' not found")
    await session.delete(level)
    await session.commit()
    return {"deleted": name}


# ------------------------------------------------------------------
# Formula coefficients
# ------------------------------------------------------------------


@router.get("/formula-coefficients", response_model=list[FormulaCoefficientResponse])
async def list_formula_coefficients(session: AsyncSession = Depends(get_session)):
    """List all formula coefficients."""
    result = await session.execute(
        select(FormulaCoefficient).order_by(FormulaCoefficient.name)
    )
    rows = result.scalars().all()
    return [FormulaCoefficientResponse(name=r.name, value=r.value) for r in rows]


@router.post("/formula-coefficients", response_model=FormulaCoefficientResponse, status_code=201)
async def create_formula_coefficient(
    req: FormulaCoefficientResponse,
    session: AsyncSession = Depends(get_session),
):
    """Create a new formula coefficient."""
    existing = await session.get(FormulaCoefficient, req.name)
    if existing is not None:
        raise HTTPException(409, f"Formula coefficient '{req.name}' already exists")
    coeff = FormulaCoefficient(name=req.name, value=req.value)
    session.add(coeff)
    await session.commit()
    return FormulaCoefficientResponse(name=coeff.name, value=coeff.value)


@router.put(
    "/formula-coefficients/{name}", response_model=FormulaCoefficientResponse
)
async def update_formula_coefficient(
    name: str,
    req: FormulaCoefficientUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a formula coefficient value."""
    coeff = await session.get(FormulaCoefficient, name)
    if coeff is None:
        raise HTTPException(404, f"Formula coefficient '{name}' not found")
    coeff.value = req.value
    await session.commit()
    return FormulaCoefficientResponse(name=coeff.name, value=coeff.value)


@router.delete("/formula-coefficients/{name}")
async def delete_formula_coefficient(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a formula coefficient."""
    coeff = await session.get(FormulaCoefficient, name)
    if coeff is None:
        raise HTTPException(404, f"Formula coefficient '{name}' not found")
    await session.delete(coeff)
    await session.commit()
    return {"deleted": name}


# ------------------------------------------------------------------
# Demo problems
# ------------------------------------------------------------------


@router.get("/demos", response_model=list[DemoProblemResponse])
async def list_demos(session: AsyncSession = Depends(get_session)):
    """List all demo problems."""
    result = await session.execute(
        select(DemoProblem).order_by(DemoProblem.id)
    )
    rows = result.scalars().all()
    return [
        DemoProblemResponse(
            id=r.id,
            name=r.name,
            section=r.section or "",
            initial=r.initial,
            modified=r.modified,
            target=r.target,
            answer=r.answer,
            seed=r.seed,
            mode=r.mode,
            description=r.description or "",
        )
        for r in rows
    ]


@router.post("/demos", response_model=DemoProblemResponse, status_code=201)
async def create_demo(
    req: DemoProblemRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new demo problem."""
    demo = DemoProblem(
        name=req.name,
        section=req.section,
        initial=req.initial,
        modified=req.modified,
        target=req.target,
        answer=req.answer,
        seed=req.seed,
        mode=req.mode,
        description=req.description,
    )
    session.add(demo)
    await session.flush()
    await session.commit()
    return DemoProblemResponse(
        id=demo.id,
        name=demo.name,
        section=demo.section or "",
        initial=demo.initial,
        modified=demo.modified,
        target=demo.target,
        answer=demo.answer,
        seed=demo.seed,
        mode=demo.mode,
        description=demo.description or "",
    )


@router.put("/demos/{demo_id}", response_model=DemoProblemResponse)
async def update_demo(
    demo_id: int,
    req: DemoProblemRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a demo problem."""
    demo = await session.get(DemoProblem, demo_id)
    if demo is None:
        raise HTTPException(404, f"Demo {demo_id} not found")
    demo.name = req.name
    demo.section = req.section
    demo.initial = req.initial
    demo.modified = req.modified
    demo.target = req.target
    demo.answer = req.answer
    demo.seed = req.seed
    demo.mode = req.mode
    demo.description = req.description
    await session.commit()
    return DemoProblemResponse(
        id=demo.id,
        name=demo.name,
        section=demo.section or "",
        initial=demo.initial,
        modified=demo.modified,
        target=demo.target,
        answer=demo.answer,
        seed=demo.seed,
        mode=demo.mode,
        description=demo.description or "",
    )


@router.delete("/demos/{demo_id}")
async def delete_demo(
    demo_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete a demo problem."""
    demo = await session.get(DemoProblem, demo_id)
    if demo is None:
        raise HTTPException(404, f"Demo {demo_id} not found")
    await session.delete(demo)
    await session.commit()
    return {"deleted": demo_id}


# ------------------------------------------------------------------
# Theme dimensions
# ------------------------------------------------------------------


class ThemeDimensionRequest(BaseModel):
    slipnet_node: str
    valid_relations: list[str]


class ThemeDimensionResponse(BaseModel):
    id: int
    slipnet_node: str
    valid_relations: list[str]


@router.get("/theme-dimensions", response_model=list[ThemeDimensionResponse])
async def list_theme_dimensions(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(ThemeDimensionDef).order_by(ThemeDimensionDef.id))
    return [
        ThemeDimensionResponse(id=r.id, slipnet_node=r.slipnet_node, valid_relations=r.valid_relations)
        for r in result.scalars().all()
    ]


@router.post("/theme-dimensions", response_model=ThemeDimensionResponse, status_code=201)
async def create_theme_dimension(
    req: ThemeDimensionRequest, session: AsyncSession = Depends(get_session),
):
    row = ThemeDimensionDef(slipnet_node=req.slipnet_node, valid_relations=req.valid_relations)
    session.add(row)
    await session.flush()
    await session.commit()
    return ThemeDimensionResponse(id=row.id, slipnet_node=row.slipnet_node, valid_relations=row.valid_relations)


@router.put("/theme-dimensions/{dim_id}", response_model=ThemeDimensionResponse)
async def update_theme_dimension(
    dim_id: int, req: ThemeDimensionRequest, session: AsyncSession = Depends(get_session),
):
    row = await session.get(ThemeDimensionDef, dim_id)
    if row is None:
        raise HTTPException(404, f"Theme dimension {dim_id} not found")
    row.slipnet_node = req.slipnet_node
    row.valid_relations = req.valid_relations
    await session.commit()
    return ThemeDimensionResponse(id=row.id, slipnet_node=row.slipnet_node, valid_relations=row.valid_relations)


@router.delete("/theme-dimensions/{dim_id}")
async def delete_theme_dimension(dim_id: int, session: AsyncSession = Depends(get_session)):
    row = await session.get(ThemeDimensionDef, dim_id)
    if row is None:
        raise HTTPException(404, f"Theme dimension {dim_id} not found")
    await session.delete(row)
    await session.commit()
    return {"deleted": dim_id}


# ------------------------------------------------------------------
# Posting rules
# ------------------------------------------------------------------


class PostingRuleRequest(BaseModel):
    codelet_type: str
    direction: str
    urgency_when_posted: int | None = None
    urgency_formula: str | None = None
    posting_formula: str = ""
    count_formula: str = ""
    count_values: dict | None = None
    condition: str = "always"
    triggering_slipnodes: list[str] | None = None


class PostingRuleResponse(BaseModel):
    id: int
    codelet_type: str
    direction: str
    urgency_when_posted: int | None
    urgency_formula: str | None
    posting_formula: str
    count_formula: str
    count_values: dict | None
    condition: str
    triggering_slipnodes: list[str] | None


@router.get("/posting-rules", response_model=list[PostingRuleResponse])
async def list_posting_rules(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(PostingRule).order_by(PostingRule.id))
    return [
        PostingRuleResponse(
            id=r.id, codelet_type=r.codelet_type, direction=r.direction,
            urgency_when_posted=r.urgency_when_posted, urgency_formula=r.urgency_formula,
            posting_formula=r.posting_formula or "", count_formula=r.count_formula or "",
            count_values=r.count_values, condition=r.condition or "always",
            triggering_slipnodes=r.triggering_slipnodes,
        )
        for r in result.scalars().all()
    ]


@router.post("/posting-rules", response_model=PostingRuleResponse, status_code=201)
async def create_posting_rule(
    req: PostingRuleRequest, session: AsyncSession = Depends(get_session),
):
    row = PostingRule(
        codelet_type=req.codelet_type, direction=req.direction,
        urgency_when_posted=req.urgency_when_posted, urgency_formula=req.urgency_formula,
        posting_formula=req.posting_formula, count_formula=req.count_formula,
        count_values=req.count_values, condition=req.condition,
        triggering_slipnodes=req.triggering_slipnodes,
    )
    session.add(row)
    await session.flush()
    await session.commit()
    return PostingRuleResponse(
        id=row.id, codelet_type=row.codelet_type, direction=row.direction,
        urgency_when_posted=row.urgency_when_posted, urgency_formula=row.urgency_formula,
        posting_formula=row.posting_formula or "", count_formula=row.count_formula or "",
        count_values=row.count_values, condition=row.condition or "always",
        triggering_slipnodes=row.triggering_slipnodes,
    )


@router.put("/posting-rules/{rule_id}", response_model=PostingRuleResponse)
async def update_posting_rule(
    rule_id: int, req: PostingRuleRequest, session: AsyncSession = Depends(get_session),
):
    row = await session.get(PostingRule, rule_id)
    if row is None:
        raise HTTPException(404, f"Posting rule {rule_id} not found")
    row.codelet_type = req.codelet_type
    row.direction = req.direction
    row.urgency_when_posted = req.urgency_when_posted
    row.urgency_formula = req.urgency_formula
    row.posting_formula = req.posting_formula
    row.count_formula = req.count_formula
    row.count_values = req.count_values
    row.condition = req.condition
    row.triggering_slipnodes = req.triggering_slipnodes
    await session.commit()
    return PostingRuleResponse(
        id=row.id, codelet_type=row.codelet_type, direction=row.direction,
        urgency_when_posted=row.urgency_when_posted, urgency_formula=row.urgency_formula,
        posting_formula=row.posting_formula or "", count_formula=row.count_formula or "",
        count_values=row.count_values, condition=row.condition or "always",
        triggering_slipnodes=row.triggering_slipnodes,
    )


@router.delete("/posting-rules/{rule_id}")
async def delete_posting_rule(rule_id: int, session: AsyncSession = Depends(get_session)):
    row = await session.get(PostingRule, rule_id)
    if row is None:
        raise HTTPException(404, f"Posting rule {rule_id} not found")
    await session.delete(row)
    await session.commit()
    return {"deleted": rule_id}


# ------------------------------------------------------------------
# Commentary templates
# ------------------------------------------------------------------


class CommentaryTemplateRequest(BaseModel):
    template_key: str
    template_data: dict


class CommentaryTemplateResponse(BaseModel):
    id: int
    template_key: str
    template_data: dict


@router.get("/commentary-templates", response_model=list[CommentaryTemplateResponse])
async def list_commentary_templates(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(CommentaryTemplate).order_by(CommentaryTemplate.id))
    return [
        CommentaryTemplateResponse(id=r.id, template_key=r.template_key, template_data=r.template_data)
        for r in result.scalars().all()
    ]


@router.post("/commentary-templates", response_model=CommentaryTemplateResponse, status_code=201)
async def create_commentary_template(
    req: CommentaryTemplateRequest, session: AsyncSession = Depends(get_session),
):
    row = CommentaryTemplate(template_key=req.template_key, template_data=req.template_data)
    session.add(row)
    await session.flush()
    await session.commit()
    return CommentaryTemplateResponse(id=row.id, template_key=row.template_key, template_data=row.template_data)


@router.put("/commentary-templates/{template_id}", response_model=CommentaryTemplateResponse)
async def update_commentary_template(
    template_id: int, req: CommentaryTemplateRequest, session: AsyncSession = Depends(get_session),
):
    row = await session.get(CommentaryTemplate, template_id)
    if row is None:
        raise HTTPException(404, f"Commentary template {template_id} not found")
    row.template_key = req.template_key
    row.template_data = req.template_data
    await session.commit()
    return CommentaryTemplateResponse(id=row.id, template_key=row.template_key, template_data=row.template_data)


@router.delete("/commentary-templates/{template_id}")
async def delete_commentary_template(template_id: int, session: AsyncSession = Depends(get_session)):
    row = await session.get(CommentaryTemplate, template_id)
    if row is None:
        raise HTTPException(404, f"Commentary template {template_id} not found")
    await session.delete(row)
    await session.commit()
    return {"deleted": template_id}


# ------------------------------------------------------------------
# Slipnet layout
# ------------------------------------------------------------------


class SlipnetLayoutRequest(BaseModel):
    node_name: str
    grid_row: int
    grid_col: int


class SlipnetLayoutResponse(BaseModel):
    node_name: str
    grid_row: int
    grid_col: int


@router.get("/slipnet-layout", response_model=list[SlipnetLayoutResponse])
async def list_slipnet_layout(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(SlipnetLayoutPos).order_by(SlipnetLayoutPos.node_name))
    return [
        SlipnetLayoutResponse(node_name=r.node_name, grid_row=r.grid_row, grid_col=r.grid_col)
        for r in result.scalars().all()
    ]


@router.post("/slipnet-layout", response_model=SlipnetLayoutResponse, status_code=201)
async def create_slipnet_layout(
    req: SlipnetLayoutRequest, session: AsyncSession = Depends(get_session),
):
    existing = await session.get(SlipnetLayoutPos, req.node_name)
    if existing is not None:
        raise HTTPException(409, f"Layout for node '{req.node_name}' already exists")
    row = SlipnetLayoutPos(node_name=req.node_name, grid_row=req.grid_row, grid_col=req.grid_col)
    session.add(row)
    await session.commit()
    return SlipnetLayoutResponse(node_name=row.node_name, grid_row=row.grid_row, grid_col=row.grid_col)


@router.put("/slipnet-layout/{node_name}", response_model=SlipnetLayoutResponse)
async def update_slipnet_layout(
    node_name: str, req: SlipnetLayoutRequest, session: AsyncSession = Depends(get_session),
):
    row = await session.get(SlipnetLayoutPos, node_name)
    if row is None:
        raise HTTPException(404, f"Layout for node '{node_name}' not found")
    row.grid_row = req.grid_row
    row.grid_col = req.grid_col
    await session.commit()
    return SlipnetLayoutResponse(node_name=row.node_name, grid_row=row.grid_row, grid_col=row.grid_col)


@router.delete("/slipnet-layout/{node_name}")
async def delete_slipnet_layout(node_name: str, session: AsyncSession = Depends(get_session)):
    row = await session.get(SlipnetLayoutPos, node_name)
    if row is None:
        raise HTTPException(404, f"Layout for node '{node_name}' not found")
    await session.delete(row)
    await session.commit()
    return {"deleted": node_name}


# ------------------------------------------------------------------
# Help topics
# ------------------------------------------------------------------


class HelpTopicRequest(BaseModel):
    topic_type: str
    topic_key: str
    title: str
    short_desc: str = ""
    full_desc: str = ""
    metadata: dict | None = None


class HelpTopicResponse(BaseModel):
    id: int
    topic_type: str
    topic_key: str
    title: str
    short_desc: str
    full_desc: str
    metadata: dict | None


@router.get("/help-topics", response_model=list[HelpTopicResponse])
async def list_help_topics(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(HelpTopic).order_by(HelpTopic.id))
    return [
        HelpTopicResponse(
            id=r.id, topic_type=r.topic_type, topic_key=r.topic_key,
            title=r.title, short_desc=r.short_desc or "", full_desc=r.full_desc or "",
            metadata=r.metadata_json,
        )
        for r in result.scalars().all()
    ]


@router.post("/help-topics", response_model=HelpTopicResponse, status_code=201)
async def create_help_topic(
    req: HelpTopicRequest, session: AsyncSession = Depends(get_session),
):
    row = HelpTopic(
        topic_type=req.topic_type, topic_key=req.topic_key, title=req.title,
        short_desc=req.short_desc, full_desc=req.full_desc, metadata_json=req.metadata,
    )
    session.add(row)
    await session.flush()
    await session.commit()
    return HelpTopicResponse(
        id=row.id, topic_type=row.topic_type, topic_key=row.topic_key,
        title=row.title, short_desc=row.short_desc or "", full_desc=row.full_desc or "",
        metadata=row.metadata_json,
    )


@router.put("/help-topics/{topic_id}", response_model=HelpTopicResponse)
async def update_help_topic(
    topic_id: int, req: HelpTopicRequest, session: AsyncSession = Depends(get_session),
):
    row = await session.get(HelpTopic, topic_id)
    if row is None:
        raise HTTPException(404, f"Help topic {topic_id} not found")
    row.topic_type = req.topic_type
    row.topic_key = req.topic_key
    row.title = req.title
    row.short_desc = req.short_desc
    row.full_desc = req.full_desc
    row.metadata_json = req.metadata
    await session.commit()
    return HelpTopicResponse(
        id=row.id, topic_type=row.topic_type, topic_key=row.topic_key,
        title=row.title, short_desc=row.short_desc or "", full_desc=row.full_desc or "",
        metadata=row.metadata_json,
    )


@router.delete("/help-topics/{topic_id}")
async def delete_help_topic(topic_id: int, session: AsyncSession = Depends(get_session)):
    row = await session.get(HelpTopic, topic_id)
    if row is None:
        raise HTTPException(404, f"Help topic {topic_id} not found")
    await session.delete(row)
    await session.commit()
    return {"deleted": topic_id}


# ------------------------------------------------------------------
# Reload & Export
# ------------------------------------------------------------------


@router.post("/reload")
async def reload_metadata(session: AsyncSession = Depends(get_session)):
    """Reload metadata cache from the database.

    Re-reads all metadata tables and rebuilds the MetadataProvider
    used by the RunService for new runs.
    """
    from server.api.runs import get_run_service
    from server.services.metadata_service import load_metadata_from_db

    svc = get_run_service()
    new_meta = await load_metadata_from_db(session)
    svc.meta = new_meta
    return {"reloaded": True}


@router.get("/export")
async def export_metadata(session: AsyncSession = Depends(get_session)):
    """Export all metadata as a single JSON object."""
    nodes_result = await session.execute(select(SlipnetNodeDef))
    links_result = await session.execute(select(SlipnetLinkDef))
    codelets_result = await session.execute(select(CodeletTypeDef))
    params_result = await session.execute(select(EngineParam))
    urgency_result = await session.execute(select(UrgencyLevel))
    formula_result = await session.execute(select(FormulaCoefficient))
    demos_result = await session.execute(select(DemoProblem))
    theme_dims_result = await session.execute(select(ThemeDimensionDef))
    posting_result = await session.execute(select(PostingRule))
    commentary_result = await session.execute(select(CommentaryTemplate))
    layout_result = await session.execute(select(SlipnetLayoutPos))
    help_result = await session.execute(select(HelpTopic))

    return {
        "slipnet_nodes": [
            {
                "name": r.name,
                "short_name": r.short_name,
                "conceptual_depth": r.conceptual_depth,
                "description": r.description or "",
            }
            for r in nodes_result.scalars().all()
        ],
        "slipnet_links": [
            {
                "id": r.id,
                "from_node": r.from_node,
                "to_node": r.to_node,
                "link_type": r.link_type,
                "label_node": r.label_node,
                "link_length": r.link_length,
                "fixed_length": r.fixed_length
                if r.fixed_length is not None
                else True,
            }
            for r in links_result.scalars().all()
        ],
        "codelet_types": [
            {
                "name": r.name,
                "family": r.family,
                "phase": r.phase,
                "default_urgency": r.default_urgency,
                "description": r.description or "",
                "source_file": r.source_file or "",
                "source_line": r.source_line or 0,
                "execute_body": r.execute_body or "",
            }
            for r in codelets_result.scalars().all()
        ],
        "engine_params": [
            {
                "name": r.name,
                "value": r.value,
                "value_type": r.value_type or "string",
            }
            for r in params_result.scalars().all()
        ],
        "urgency_levels": [
            {"name": r.name, "value": r.value}
            for r in urgency_result.scalars().all()
        ],
        "formula_coefficients": [
            {"name": r.name, "value": r.value}
            for r in formula_result.scalars().all()
        ],
        "demo_problems": [
            {
                "id": r.id,
                "name": r.name,
                "section": r.section or "",
                "initial": r.initial,
                "modified": r.modified,
                "target": r.target,
                "answer": r.answer,
                "seed": r.seed,
                "mode": r.mode,
                "description": r.description or "",
            }
            for r in demos_result.scalars().all()
        ],
        "theme_dimensions": [
            {"id": r.id, "slipnet_node": r.slipnet_node, "valid_relations": r.valid_relations}
            for r in theme_dims_result.scalars().all()
        ],
        "posting_rules": [
            {
                "id": r.id, "codelet_type": r.codelet_type, "direction": r.direction,
                "urgency_when_posted": r.urgency_when_posted, "urgency_formula": r.urgency_formula,
                "posting_formula": r.posting_formula or "", "count_formula": r.count_formula or "",
                "count_values": r.count_values, "condition": r.condition or "always",
                "triggering_slipnodes": r.triggering_slipnodes,
            }
            for r in posting_result.scalars().all()
        ],
        "commentary_templates": [
            {"id": r.id, "template_key": r.template_key, "template_data": r.template_data}
            for r in commentary_result.scalars().all()
        ],
        "slipnet_layout": [
            {"node_name": r.node_name, "grid_row": r.grid_row, "grid_col": r.grid_col}
            for r in layout_result.scalars().all()
        ],
        "help_topics": [
            {
                "id": r.id, "topic_type": r.topic_type, "topic_key": r.topic_key,
                "title": r.title, "short_desc": r.short_desc or "",
                "full_desc": r.full_desc or "", "metadata": r.metadata_json,
            }
            for r in help_result.scalars().all()
        ],
    }


@router.post("/import")
async def import_metadata(
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Import metadata from a JSON object (same format as export).

    Replaces matching rows in each table. Uses a transaction so the
    entire import succeeds or rolls back.
    """
    imported: dict[str, int] = {}
    try:
        # Slipnet nodes
        if "slipnet_nodes" in data:
            for n in data["slipnet_nodes"]:
                existing = await session.get(SlipnetNodeDef, n["name"])
                if existing:
                    existing.short_name = n["short_name"]
                    existing.conceptual_depth = n["conceptual_depth"]
                    existing.description = n.get("description", "")
                else:
                    session.add(SlipnetNodeDef(**n))
            imported["slipnet_nodes"] = len(data["slipnet_nodes"])

        # Engine params
        if "engine_params" in data:
            for p in data["engine_params"]:
                existing = await session.get(EngineParam, p["name"])
                if existing:
                    existing.value = p["value"]
                else:
                    session.add(EngineParam(**p))
            imported["engine_params"] = len(data["engine_params"])

        # Urgency levels
        if "urgency_levels" in data:
            for u in data["urgency_levels"]:
                existing = await session.get(UrgencyLevel, u["name"])
                if existing:
                    existing.value = u["value"]
                else:
                    session.add(UrgencyLevel(**u))
            imported["urgency_levels"] = len(data["urgency_levels"])

        # Formula coefficients
        if "formula_coefficients" in data:
            for f in data["formula_coefficients"]:
                existing = await session.get(FormulaCoefficient, f["name"])
                if existing:
                    existing.value = f["value"]
                else:
                    session.add(FormulaCoefficient(**f))
            imported["formula_coefficients"] = len(data["formula_coefficients"])

        await session.commit()

        # Trigger a metadata reload
        from server.api.runs import get_run_service
        from server.services.metadata_service import load_metadata_from_db
        svc = get_run_service()
        svc.meta = await load_metadata_from_db(session)

    except Exception as e:
        await session.rollback()
        raise HTTPException(400, f"Import failed: {e}")

    return {"imported": imported}


# ------------------------------------------------------------------
# Enum tables — generic CRUD
# ------------------------------------------------------------------

# Map of table name -> ORM model class
_ENUM_TABLES: dict[str, type] = {
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


class EnumValueRequest(BaseModel):
    name: str
    display_label: str
    sort_order: int = 0
    description: str = ""


class EnumValueUpdateRequest(BaseModel):
    display_label: str
    sort_order: int = 0
    description: str = ""


class EnumValueResponse(BaseModel):
    name: str
    display_label: str
    sort_order: int
    description: str


def _get_enum_model(table: str) -> type:
    model = _ENUM_TABLES.get(table)
    if model is None:
        raise HTTPException(404, f"Unknown enum table '{table}'")
    return model


@router.get("/enums")
async def list_enum_tables():
    """List all enum table names."""
    return {"tables": sorted(_ENUM_TABLES.keys())}


@router.get("/enums/{table}", response_model=list[EnumValueResponse])
async def list_enum_values(
    table: str,
    session: AsyncSession = Depends(get_session),
):
    """List all values in an enum table."""
    model = _get_enum_model(table)
    result = await session.execute(select(model).order_by(model.sort_order))
    return [
        EnumValueResponse(
            name=r.name,
            display_label=r.display_label,
            sort_order=r.sort_order,
            description=r.description or "",
        )
        for r in result.scalars().all()
    ]


@router.post("/enums/{table}", response_model=EnumValueResponse, status_code=201)
async def create_enum_value(
    table: str,
    req: EnumValueRequest,
    session: AsyncSession = Depends(get_session),
):
    """Add a value to an enum table."""
    model = _get_enum_model(table)
    existing = await session.get(model, req.name)
    if existing is not None:
        raise HTTPException(409, f"Value '{req.name}' already exists in {table}")
    row = model(
        name=req.name,
        display_label=req.display_label,
        sort_order=req.sort_order,
        description=req.description,
    )
    session.add(row)
    await session.commit()
    return EnumValueResponse(
        name=row.name,
        display_label=row.display_label,
        sort_order=row.sort_order,
        description=row.description or "",
    )


@router.put("/enums/{table}/{name}", response_model=EnumValueResponse)
async def update_enum_value(
    table: str,
    name: str,
    req: EnumValueUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update display_label, description, or sort_order of an enum value."""
    model = _get_enum_model(table)
    row = await session.get(model, name)
    if row is None:
        raise HTTPException(404, f"Value '{name}' not found in {table}")
    row.display_label = req.display_label
    row.sort_order = req.sort_order
    row.description = req.description
    await session.commit()
    return EnumValueResponse(
        name=row.name,
        display_label=row.display_label,
        sort_order=row.sort_order,
        description=row.description or "",
    )


@router.delete("/enums/{table}/{name}")
async def delete_enum_value(
    table: str,
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete an enum value (with FK-violation guard)."""
    model = _get_enum_model(table)
    row = await session.get(model, name)
    if row is None:
        raise HTTPException(404, f"Value '{name}' not found in {table}")
    try:
        await session.delete(row)
        await session.flush()
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(
            409,
            f"Cannot delete '{name}' from {table} — it is referenced by other rows",
        )
    return {"deleted": name, "table": table}


# ------------------------------------------------------------------
# Help documentation regeneration
# ------------------------------------------------------------------

@router.post("/help/regenerate")
async def regenerate_help_docs(
    session: AsyncSession = Depends(get_session),
):
    """Re-sync help topics from the locale JSON and regenerate derived docs.

    Triggered by the Admin panel's "Regenerate Help Documentation" button.
    Performs two steps:

    1. Upsert every row from `seed_data/help_topics.{locale}.json` into the
       `help_topics` table (same idempotent sync that runs on startup). After
       this, every `?` popover in the UI reflects the latest JSON content on
       the very next fetch.

    2. Rewrite `HELP.md` and `client/src/constants/helpTopics.ts` from the
       same JSON. These are dev-time artifacts: in a dev container, Vite's
       HMR picks up the TypeScript change automatically; in a production
       build, the files on disk are refreshed but the already-served frontend
       bundle does not pick them up until the next build/deploy.

    Returns a JSON object describing what was touched.
    """
    import os
    from server.services.help_docs import regenerate_all
    from server.main import _sync_help_topics

    locale = os.environ.get("HELP_LOCALE", "en")

    # Step 1: upsert DB rows from JSON
    try:
        await _sync_help_topics(session)
    except Exception as e:
        raise HTTPException(500, f"DB sync failed: {e}") from e

    # Step 2: regenerate derived files (HELP.md, helpTopics.ts)
    try:
        result = regenerate_all(locale)
    except FileNotFoundError as e:
        raise HTTPException(404, f"Help topics file not found: {e}") from e
    except Exception as e:
        raise HTTPException(500, f"Regeneration failed: {e}") from e

    return {
        "status": "ok",
        "db_synced": True,
        **result.as_dict(),
    }
