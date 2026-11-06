"""FastAPI router for admin metadata CRUD.

Provides CRUD for slipnet nodes, links, codelet types, engine params,
urgency levels, formula coefficients, and demo problems.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session
from server.services.problem_text import check_problem
from server.engine.rational import canonical_rational
from server.models.journal import GLOBAL_CONFIGURATION_ID
from server.services import journal
from server.services.change_resolve.spec import ENUM_COLUMN_REFERENCES, REFERENCES
from server.services.change_resolve.vocabulary import delete_problem, role_problem, roles_by_table, VOCABULARY_TABLES
from server.services.config_registry import ENUM_REGISTRY, LAYER_REGISTRY, REGISTRY
from server.services.configuration_writer import ChangeError, ChangeService
from server.models.metadata import (
    CodeletPatternDef,
    CodeletTypeRole,
    CodeletTypeDef,
    CommentaryTemplate,
    DemoProblem,
    EngineParam,
    FormulaCoefficient,
    HelpTopic,
    InitialActivationRule,
    InitialDescriptionRule,
    PostingRule,
    SlipnetLayoutPos,
    SlipnetLinkDef,
    SlipnetNodeDef,
    SlipnetNodeRole,
    ThemeDimensionDef,
    ThemeRelation,
    UrgencyLevel,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ------------------------------------------------------------------
# Writing configuration: every editor is a client of the change API
# ------------------------------------------------------------------
#
# The editors below read with ordinary queries and write only by building a batch
# (``source = admin``, ``channel = admin_editor``) and calling ``ChangeService.apply``: the
# one change API, so the input checks, the cascades and the journal entry (one per request,
# the editor's ops as its proposed ops) are the same as for every other writer.  The enum
# tables are the engine's vocabulary, not addressable by the change API's generic ops: their
# creates, updates and deletes keep a direct call to the journal layer (after the vocabulary
# rules of ``change_resolve/vocabulary.py``), and their renames are the change API's
# ``rename_enum_value``.  ``help_topics`` is content, not configuration, and keeps its own
# writes.
#
# Every route takes ``?configuration=<id>`` (default 1, the global configuration).  The
# lists read the global configuration only.  A row addressed by its surrogate ``id`` (links,
# demos, theme dimensions, posting rules, commentary templates) can be addressed in the
# global configuration only; the rows of a session's configuration are addressed by their
# natural key (``POST /api/configurations/{id}/changes`` takes any row).

GLOBAL = GLOBAL_CONFIGURATION_ID


async def _configuration_target(
    request: Request,
    session: AsyncSession = Depends(get_session),
    configuration: int = Query(
        GLOBAL, description="The configuration an editor reads or writes; 1 is the global one."
    ),
) -> int:
    if configuration != GLOBAL and request.method == "GET":
        raise HTTPException(
            422, "the editors list the global configuration only (configuration 1)")
    session.info["admin_configuration"] = configuration
    return configuration


router.dependencies.append(Depends(_configuration_target))


def _target(session: AsyncSession) -> int:
    return session.info.get("admin_configuration", GLOBAL)


def _refusal(exc: ChangeError, ops: list[dict]) -> HTTPException:
    """The HTTP answer for a refused batch: the editors' own statuses, the refusal's message.

    A malformed value is 422, as the editors always answered (the change endpoint says 400).
    A refusal that names the single update or delete's own row is a 404, as the editors
    always answered for a row that is not there.
    """
    status = 422 if exc.code == "malformed" else exc.status
    if exc.code == "unknown_reference" and len(ops) == 1 and ops[0]["op"] in ("update", "delete"):
        for problem in exc.problems:
            if problem.get("table") == ops[0]["table"] and problem.get("field") == "key":
                status = 404
    if exc.code == "unknown_reference" and len(ops) == 1 and ops[0]["op"] == "rename_enum_value":
        for problem in exc.problems:
            if problem.get("table") == ops[0]["table"] and problem.get("field") == "old":
                status = 404
    return HTTPException(status, exc.message)


async def _apply(
    session: AsyncSession, ops: list[dict], *, source: str = "admin",
    channel: str = "admin_editor", note: str = "",
) -> dict:
    """Submit one batch of generic ops to the change API; returns its report."""
    batch = {
        "configuration_id": _target(session), "source": source, "actor": "admin",
        "channel": channel, "note": note, "base_mode": "rebase", "ops": ops,
    }
    try:
        return await ChangeService.apply(session, batch)
    except ChangeError as exc:
        raise _refusal(exc, ops) from exc
    except journal.ConfigurationNotAdopted as exc:
        raise HTTPException(500, str(exc)) from exc


async def _journal_write(session: AsyncSession, ops: list[dict]) -> journal.WriteResult:
    """The enum tables' write: straight to the journal layer (global configuration only)."""
    try:
        return await journal.write_immediate(
            session, ops=ops, source="admin", actor="admin", channel="admin_editor"
        )
    except journal.ConfigurationNotAdopted as exc:
        raise HTTPException(500, str(exc)) from exc
    except journal.KeyExists as exc:
        raise HTTPException(409, str(exc)) from exc
    except journal.MissingKey as exc:
        raise HTTPException(404, str(exc)) from exc
    except journal.JournalError as exc:
        raise HTTPException(400, str(exc)) from exc


class _Row(SimpleNamespace):
    """A stored row; a column the write did not carry reads as ``None``."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return None


async def _stored(session: AsyncSession, model: type, key: dict) -> _Row | None:
    """The row of the global configuration with natural key *key*, read back after a write."""
    spec = LAYER_REGISTRY[model.__tablename__]
    query = select(model).execution_options(populate_existing=True)
    for column, value in key.items():
        attr = getattr(model, column)
        query = query.where(
            func.coalesce(attr, "") == value if spec.table.c[column].nullable and value == ""
            else attr == value
        )
    row = (await session.execute(query)).scalars().first()
    if row is None:
        return None
    return _Row(**{c.key: getattr(row, c.key) for c in sa_inspect(model).mapper.column_attrs})


async def _existing(session: AsyncSession, model: type, ident: Any, message: str) -> dict:
    """The natural key of the row an editor names, or the editor's 404 when it is not there."""
    table = model.__tablename__
    spec = LAYER_REGISTRY[table]
    if _target(session) == GLOBAL:
        row = await session.get(model, ident)
        if row is None:
            raise HTTPException(404, message)
        return spec.key_of(row)
    if table not in REGISTRY:
        raise HTTPException(
            422, f"{table} is the engine's vocabulary: only the global configuration has it")
    if spec.surrogate is not None:
        raise HTTPException(
            422, f"{table} rows are addressed by id in the global configuration only; "
                 "address this row by its natural key in a change batch")
    return {spec.key[0]: ident}


async def _insert(session: AsyncSession, model: type, values: dict) -> _Row:
    """Insert one row; returns the stored row (with its ``id`` and defaults)."""
    table = model.__tablename__
    if table not in REGISTRY:
        _require_global(session, table)
        result = await _journal_write(
            session, [{"op": "insert", "table": table, "key": {}, "row": values}])
        return _Row(**result.rows[0])
    spec = LAYER_REGISTRY[table]
    if spec.surrogate is not None and _target(session) != GLOBAL:
        raise HTTPException(
            422, f"{table} rows are addressed by id in the global configuration only; "
                 "add this row in a change batch")
    key = spec.key_of(values)
    await _apply(session, [{"op": "insert", "table": table, "row": values}])
    return await _result_row(session, model, key, values)


async def _result_row(session: AsyncSession, model: type, key: dict, values: dict) -> _Row:
    if _target(session) == GLOBAL:
        row = await _stored(session, model, key)
        if row is not None:
            return row
    return _Row(**{**key, **values})


async def _update(session: AsyncSession, model: type, key: dict, values: dict) -> _Row:
    """Change columns of the row with natural key *key*."""
    table = model.__tablename__
    if table not in REGISTRY:
        _require_global(session, table)
        result = await _journal_write(
            session, [{"op": "update", "table": table, "key": key, "set": values}])
        return _Row(**result.rows[0])
    await _apply(session, [{"op": "update", "table": table, "key": key, "fields": values}])
    return await _result_row(session, model, {**key, **{c: v for c, v in values.items() if c in key}}, values)


async def _delete(session: AsyncSession, model: type, key: dict) -> None:
    table = model.__tablename__
    if table not in REGISTRY:
        _require_global(session, table)
        await _journal_write(session, [{"op": "delete", "table": table, "key": key}])
        return
    await _apply(session, [{"op": "delete", "table": table, "key": key}])


def _require_global(session: AsyncSession, table: str) -> None:
    if _target(session) != GLOBAL:
        raise HTTPException(
            422, f"{table} is the engine's vocabulary: only the global configuration has it")


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------


class SlipnetNodeRequest(BaseModel):
    name: str
    short_name: str
    conceptual_depth: int
    description: str = ""
    #: DSL expression over ``obj`` deciding when this node validly describes a
    #: Workspace object.  Null for the many nodes whose descriptors are read off an
    #: object rather than tested, which is why it defaults to absent rather than to
    #: the empty string — an empty expression is not the same as no expression.
    descriptor_predicate: str | None = None


class SlipnetNodeResponse(BaseModel):
    name: str
    short_name: str
    conceptual_depth: int
    description: str
    descriptor_predicate: str | None = None


class SlipnetLinkRequest(BaseModel):
    from_node: str
    to_node: str
    link_type: str
    label_node: str | None = None
    link_length: int | None = None
    fixed_length: bool


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
    description: str = ""
    source_file: str = ""
    source_line: int = 0
    execute_body: str = ""


class CodeletTypeResponse(BaseModel):
    name: str
    family: str
    phase: str
    description: str
    source_file: str
    source_line: int
    execute_body: str


class ParamUpdateRequest(BaseModel):
    value: str
    #: How the value is read back — ``int``, ``float``, ``bool``, ``json``, ``string`` or ``rational`` (``n/m``).
    #: Sent when the type is being changed alongside the value.
    value_type: str | None = None
    #: What the value's names refer to (``node_list``, ``trigger_node_list``, ``node_map``,
    #: ``codelet_type_list``, ``urgency_level``, ``clampable_pattern_map``,
    #: ``clampable_pattern_list``); omitted, the parameter keeps its own.
    refers_to: str | None = None


class ParamResponse(BaseModel):
    name: str
    value: str
    value_type: str
    #: What the value's names refer to, or null (``engine_params.refers_to``).
    refers_to: str | None = None


class UrgencyLevelUpdateRequest(BaseModel):
    value: int


class UrgencyLevelResponse(BaseModel):
    name: str
    value: int


class FormulaCoefficientUpdateRequest(BaseModel):
    #: The number as text: ``5``, ``0.5`` or an exact rational ``2/3`` (written ``n/m``).
    value: str
    #: ``int``, ``float`` or ``rational``; omitted, the coefficient keeps its kind.
    value_type: str | None = None


class FormulaCoefficientResponse(BaseModel):
    name: str
    value: str
    value_type: str = "float"


class DemoProblemRequest(BaseModel):
    name: str
    section: str = ""
    initial: str
    modified: str
    target: str
    answer: str | None = None
    seed: int = 0
    description: str = ""

    @model_validator(mode="after")
    def _problem_text(self) -> "DemoProblemRequest":
        # Any Unicode text is a valid problem string; only U+0000 and a lone surrogate are
        # refused, because they cannot be stored.  See ``server.services.problem_text``.
        check_problem(self.initial, self.modified, self.target, self.answer)
        return self



class DemoProblemResponse(BaseModel):
    id: int
    name: str
    section: str
    initial: str
    modified: str
    target: str
    answer: str | None
    seed: int
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
            descriptor_predicate=r.descriptor_predicate,
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
    node = await _insert(session, SlipnetNodeDef, dict(
        name=req.name,
        short_name=req.short_name,
        conceptual_depth=req.conceptual_depth,
        description=req.description,
        descriptor_predicate=req.descriptor_predicate,
    ))
    return SlipnetNodeResponse(
        name=node.name,
        short_name=node.short_name,
        conceptual_depth=node.conceptual_depth,
        description=node.description or "",
        descriptor_predicate=node.descriptor_predicate,
    )


@router.put("/slipnet/nodes/{name}", response_model=SlipnetNodeResponse)
async def update_slipnet_node(
    name: str,
    req: SlipnetNodeRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a slipnet node definition."""
    key = await _existing(session, SlipnetNodeDef, name, f"Node '{name}' not found")
    node = await _update(session, SlipnetNodeDef, key, dict(
        short_name=req.short_name,
        conceptual_depth=req.conceptual_depth,
        description=req.description,
        descriptor_predicate=req.descriptor_predicate,
    ))
    return SlipnetNodeResponse(
        name=node.name,
        short_name=node.short_name,
        conceptual_depth=node.conceptual_depth,
        description=node.description or "",
        descriptor_predicate=node.descriptor_predicate,
    )


@router.delete("/slipnet/nodes/{name}")
async def delete_slipnet_node(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a slipnet node definition."""
    key = await _existing(session, SlipnetNodeDef, name, f"Node '{name}' not found")
    await _delete(session, SlipnetNodeDef, key)
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
            fixed_length=r.fixed_length,
        )
        for r in rows
    ]


@router.post("/slipnet/links", response_model=SlipnetLinkResponse, status_code=201)
async def create_slipnet_link(
    req: SlipnetLinkRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new slipnet link definition."""
    link = await _insert(session, SlipnetLinkDef, dict(
        from_node=req.from_node,
        to_node=req.to_node,
        link_type=req.link_type,
        label_node=req.label_node,
        link_length=req.link_length,
        fixed_length=req.fixed_length,
    ))
    return SlipnetLinkResponse(
        id=link.id,
        from_node=link.from_node,
        to_node=link.to_node,
        link_type=link.link_type,
        label_node=link.label_node,
        link_length=link.link_length,
        fixed_length=link.fixed_length,
    )


@router.put("/slipnet/links/{link_id}", response_model=SlipnetLinkResponse)
async def update_slipnet_link(
    link_id: int,
    req: SlipnetLinkRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a slipnet link definition."""
    key = await _existing(session, SlipnetLinkDef, link_id, f"Link {link_id} not found")
    link = await _update(session, SlipnetLinkDef, key, dict(
        from_node=req.from_node,
        to_node=req.to_node,
        link_type=req.link_type,
        label_node=req.label_node,
        link_length=req.link_length,
        fixed_length=req.fixed_length,
    ))
    return SlipnetLinkResponse(
        id=link.id,
        from_node=link.from_node,
        to_node=link.to_node,
        link_type=link.link_type,
        label_node=link.label_node,
        link_length=link.link_length,
        fixed_length=link.fixed_length,
    )


@router.delete("/slipnet/links/{link_id}")
async def delete_slipnet_link(
    link_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete a slipnet link definition."""
    key = await _existing(session, SlipnetLinkDef, link_id, f"Link {link_id} not found")
    await _delete(session, SlipnetLinkDef, key)
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
    codelet = await _insert(session, CodeletTypeDef, dict(
        name=req.name,
        family=req.family,
        phase=req.phase,
        description=req.description,
        source_file=req.source_file,
        source_line=req.source_line,
        execute_body=req.execute_body,
    ))
    return CodeletTypeResponse(
        name=codelet.name,
        family=codelet.family,
        phase=codelet.phase,
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
    key = await _existing(session, CodeletTypeDef, name, f"Codelet type '{name}' not found")
    codelet = await _update(session, CodeletTypeDef, key, dict(
        family=req.family,
        phase=req.phase,
        description=req.description,
        source_file=req.source_file,
        source_line=req.source_line,
        execute_body=req.execute_body,
    ))
    return CodeletTypeResponse(
        name=codelet.name,
        family=codelet.family,
        phase=codelet.phase,
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
    key = await _existing(session, CodeletTypeDef, name, f"Codelet type '{name}' not found")
    await _delete(session, CodeletTypeDef, key)
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
        ParamResponse(name=r.name, value=r.value, value_type=r.value_type or "string",
                      refers_to=r.refers_to)
        for r in rows
    ]


@router.post("/params", response_model=ParamResponse, status_code=201)
async def create_param(
    req: ParamResponse,
    session: AsyncSession = Depends(get_session),
):
    """Create a new engine parameter."""
    value = req.value
    if req.value_type == "rational":
        value = _checked_number(value, "rational", kinds=("rational",))
    param = await _insert(
        session, EngineParam,
        dict(name=req.name, value=value, value_type=req.value_type, refers_to=req.refers_to),
    )
    return ParamResponse(name=param.name, value=param.value, value_type=param.value_type or "string",
                         refers_to=param.refers_to)


@router.put("/params/{name}", response_model=ParamResponse)
async def update_param(
    name: str,
    req: ParamUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update an engine parameter value."""
    key = await _existing(session, EngineParam, name, f"Parameter '{name}' not found")
    value_type = req.value_type or await _stored_value_type(session, EngineParam, key)
    changes: dict[str, Any] = {"value": req.value}
    if value_type == "rational":
        changes["value"] = _checked_number(req.value, "rational", kinds=("rational",))
    if req.value_type is not None:
        changes["value_type"] = req.value_type
    if "refers_to" in req.model_fields_set:
        changes["refers_to"] = req.refers_to
    param = await _update(session, EngineParam, key, changes)
    return ParamResponse(
        name=param.name,
        value=param.value,
        value_type=param.value_type or "string",
        refers_to=param.refers_to,
    )


@router.delete("/params/{name}")
async def delete_param(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete an engine parameter."""
    key = await _existing(session, EngineParam, name, f"Parameter '{name}' not found")
    await _delete(session, EngineParam, key)
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
    level = await _insert(session, UrgencyLevel, dict(name=req.name, value=req.value))
    return UrgencyLevelResponse(name=level.name, value=level.value)


@router.put("/urgency-levels/{name}", response_model=UrgencyLevelResponse)
async def update_urgency_level(
    name: str,
    req: UrgencyLevelUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update an urgency level value."""
    key = await _existing(session, UrgencyLevel, name, f"Urgency level '{name}' not found")
    level = await _update(session, UrgencyLevel, key, dict(value=req.value))
    return UrgencyLevelResponse(name=level.name, value=level.value)


@router.delete("/urgency-levels/{name}")
async def delete_urgency_level(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete an urgency level."""
    key = await _existing(session, UrgencyLevel, name, f"Urgency level '{name}' not found")
    await _delete(session, UrgencyLevel, key)
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
    return [
        FormulaCoefficientResponse(name=r.name, value=r.value, value_type=r.value_type)
        for r in rows
    ]


COEFFICIENT_VALUE_TYPES = ("int", "float", "rational")


def _checked_number(text: str, value_type: str, *, kinds: tuple[str, ...]) -> str:
    """The value text to store.

    A rational is stored in its canonical ``n/m`` (lowest terms), so the Admin view shows
    what the engine holds; ``int`` and ``float`` keep the text as written.  Whether the text
    is a value of its type is the change API's to decide (``resolve``), not this function's;
    text it cannot read is passed on as written.
    """
    if value_type not in kinds:
        raise HTTPException(422, f"value_type must be one of {', '.join(kinds)}, got {value_type!r}")
    if value_type == "rational":
        try:
            return canonical_rational(text)
        except (ValueError, ZeroDivisionError, TypeError):
            return text
    return text.strip()


async def _stored_value_type(session: AsyncSession, model: type, key: dict) -> str | None:
    """The value type stored for a parameter or coefficient (the global configuration only)."""
    if _target(session) != GLOBAL:
        return None
    row = await _stored(session, model, key)
    return (row.value_type or "string") if row is not None else None


@router.post("/formula-coefficients", response_model=FormulaCoefficientResponse, status_code=201)
async def create_formula_coefficient(
    req: FormulaCoefficientResponse,
    session: AsyncSession = Depends(get_session),
):
    """Create a new formula coefficient."""
    value = _checked_number(req.value, req.value_type, kinds=COEFFICIENT_VALUE_TYPES)
    coeff = await _insert(
        session, FormulaCoefficient, dict(name=req.name, value=value, value_type=req.value_type)
    )
    return FormulaCoefficientResponse(
        name=coeff.name, value=coeff.value, value_type=coeff.value_type
    )


@router.put(
    "/formula-coefficients/{name}", response_model=FormulaCoefficientResponse
)
async def update_formula_coefficient(
    name: str,
    req: FormulaCoefficientUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a formula coefficient value."""
    key = await _existing(session, FormulaCoefficient, name, f"Formula coefficient '{name}' not found")
    value_type = req.value_type or await _stored_value_type(session, FormulaCoefficient, key)
    changes: dict[str, Any] = {"value": req.value}
    if value_type is not None:
        changes = dict(
            value=_checked_number(req.value, value_type, kinds=COEFFICIENT_VALUE_TYPES),
            value_type=value_type,
        )
    coeff = await _update(session, FormulaCoefficient, key, changes)
    return FormulaCoefficientResponse(
        name=coeff.name, value=coeff.value, value_type=coeff.value_type
    )


@router.delete("/formula-coefficients/{name}")
async def delete_formula_coefficient(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a formula coefficient."""
    key = await _existing(session, FormulaCoefficient, name, f"Formula coefficient '{name}' not found")
    await _delete(session, FormulaCoefficient, key)
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
    demo = await _insert(session, DemoProblem, dict(
        name=req.name,
        section=req.section,
        initial=req.initial,
        modified=req.modified,
        target=req.target,
        answer=req.answer,
        seed=req.seed,
        description=req.description,
    ))
    return DemoProblemResponse(
        id=demo.id,
        name=demo.name,
        section=demo.section or "",
        initial=demo.initial,
        modified=demo.modified,
        target=demo.target,
        answer=demo.answer,
        seed=demo.seed,
        description=demo.description or "",
    )


@router.put("/demos/{demo_id}", response_model=DemoProblemResponse)
async def update_demo(
    demo_id: int,
    req: DemoProblemRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a demo problem."""
    key = await _existing(session, DemoProblem, demo_id, f"Demo {demo_id} not found")
    demo = await _update(session, DemoProblem, key, dict(
        name=req.name,
        section=req.section,
        initial=req.initial,
        modified=req.modified,
        target=req.target,
        answer=req.answer,
        seed=req.seed,
        description=req.description,
    ))
    return DemoProblemResponse(
        id=demo.id,
        name=demo.name,
        section=demo.section or "",
        initial=demo.initial,
        modified=demo.modified,
        target=demo.target,
        answer=demo.answer,
        seed=demo.seed,
        description=demo.description or "",
    )


@router.delete("/demos/{demo_id}")
async def delete_demo(
    demo_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete a demo problem."""
    key = await _existing(session, DemoProblem, demo_id, f"Demo {demo_id} not found")
    await _delete(session, DemoProblem, key)
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
    row = await _insert(
        session, ThemeDimensionDef,
        dict(slipnet_node=req.slipnet_node, valid_relations=req.valid_relations),
    )
    return ThemeDimensionResponse(id=row.id, slipnet_node=row.slipnet_node, valid_relations=row.valid_relations)


@router.put("/theme-dimensions/{dim_id}", response_model=ThemeDimensionResponse)
async def update_theme_dimension(
    dim_id: int, req: ThemeDimensionRequest, session: AsyncSession = Depends(get_session),
):
    key = await _existing(session, ThemeDimensionDef, dim_id, f"Theme dimension {dim_id} not found")
    row = await _update(
        session, ThemeDimensionDef, key,
        dict(slipnet_node=req.slipnet_node, valid_relations=req.valid_relations),
    )
    return ThemeDimensionResponse(id=row.id, slipnet_node=row.slipnet_node, valid_relations=row.valid_relations)


@router.delete("/theme-dimensions/{dim_id}")
async def delete_theme_dimension(dim_id: int, session: AsyncSession = Depends(get_session)):
    key = await _existing(session, ThemeDimensionDef, dim_id, f"Theme dimension {dim_id} not found")
    await _delete(session, ThemeDimensionDef, key)
    return {"deleted": dim_id}


# ------------------------------------------------------------------
# The initial-description program
# ------------------------------------------------------------------


class InitialDescriptionRuleRequest(BaseModel):
    rule_key: str = Field(min_length=1)
    #: Left out on create, the rule goes last.
    ordinal: int | None = None
    #: ``letter``, ``translated_letter`` or ``group``.
    subject: str = "letter"
    #: A node role naming the description type.
    dimension_role: str = Field(min_length=1)
    #: ``role``, ``letter_category`` or, for a group, one of its own.
    descriptor_source: str = Field(min_length=1)
    descriptor_role: str | None = None
    #: One of the engine's closed set (``server/engine/initial_program.py``).
    condition: str = Field(min_length=1)
    activate_descriptor: bool = True
    built: bool = True
    bond_description: bool = False


class InitialDescriptionRuleResponse(BaseModel):
    id: int
    rule_key: str
    ordinal: int
    subject: str
    dimension_role: str
    descriptor_source: str
    descriptor_role: str | None
    condition: str
    activate_descriptor: bool
    built: bool
    bond_description: bool


def _initial_description_rule_response(r: Any) -> InitialDescriptionRuleResponse:
    return InitialDescriptionRuleResponse(
        id=r.id, rule_key=r.rule_key, ordinal=r.ordinal, subject=r.subject,
        dimension_role=r.dimension_role,
        descriptor_source=r.descriptor_source, descriptor_role=r.descriptor_role,
        condition=r.condition, activate_descriptor=r.activate_descriptor,
        built=r.built, bond_description=r.bond_description,
    )


def _initial_description_rule_values(req: InitialDescriptionRuleRequest) -> dict:
    values = dict(
        subject=req.subject, dimension_role=req.dimension_role, descriptor_source=req.descriptor_source,
        descriptor_role=req.descriptor_role, condition=req.condition,
        activate_descriptor=req.activate_descriptor, built=req.built,
        bond_description=req.bond_description,
    )
    if req.ordinal is not None:
        values["ordinal"] = req.ordinal
    return values


@router.get("/initial-description-rules", response_model=list[InitialDescriptionRuleResponse])
async def list_initial_description_rules(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(InitialDescriptionRule).order_by(
            InitialDescriptionRule.ordinal, InitialDescriptionRule.rule_key.collate("C"))
    )
    return [_initial_description_rule_response(r) for r in result.scalars().all()]


@router.post("/initial-description-rules", response_model=InitialDescriptionRuleResponse, status_code=201)
async def create_initial_description_rule(
    req: InitialDescriptionRuleRequest, session: AsyncSession = Depends(get_session),
):
    row = await _insert(
        session, InitialDescriptionRule,
        dict(rule_key=req.rule_key, **_initial_description_rule_values(req)),
    )
    return _initial_description_rule_response(row)


@router.put("/initial-description-rules/{rule_id}", response_model=InitialDescriptionRuleResponse)
async def update_initial_description_rule(
    rule_id: int, req: InitialDescriptionRuleRequest, session: AsyncSession = Depends(get_session),
):
    key = await _existing(
        session, InitialDescriptionRule, rule_id, f"Initial description rule {rule_id} not found")
    row = await _update(session, InitialDescriptionRule, key, _initial_description_rule_values(req))
    return _initial_description_rule_response(row)


@router.delete("/initial-description-rules/{rule_id}")
async def delete_initial_description_rule(rule_id: int, session: AsyncSession = Depends(get_session)):
    key = await _existing(
        session, InitialDescriptionRule, rule_id, f"Initial description rule {rule_id} not found")
    await _delete(session, InitialDescriptionRule, key)
    return {"deleted": rule_id}


class InitialActivationRuleRequest(BaseModel):
    rule_key: str = Field(min_length=1)
    #: Left out on create, the rule goes last.
    ordinal: int | None = None
    #: A node role naming the node.
    node_role: str = Field(min_length=1)
    #: One of the engine's closed set (``server/engine/initial_program.py``).
    condition: str = Field(min_length=1)


class InitialActivationRuleResponse(BaseModel):
    id: int
    rule_key: str
    ordinal: int
    node_role: str
    condition: str


def _initial_activation_rule_response(r: Any) -> InitialActivationRuleResponse:
    return InitialActivationRuleResponse(
        id=r.id, rule_key=r.rule_key, ordinal=r.ordinal, node_role=r.node_role, condition=r.condition,
    )


def _initial_activation_rule_values(req: InitialActivationRuleRequest) -> dict:
    values = dict(node_role=req.node_role, condition=req.condition)
    if req.ordinal is not None:
        values["ordinal"] = req.ordinal
    return values


@router.get("/initial-activation-rules", response_model=list[InitialActivationRuleResponse])
async def list_initial_activation_rules(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(InitialActivationRule).order_by(
            InitialActivationRule.ordinal, InitialActivationRule.rule_key.collate("C"))
    )
    return [_initial_activation_rule_response(r) for r in result.scalars().all()]


@router.post("/initial-activation-rules", response_model=InitialActivationRuleResponse, status_code=201)
async def create_initial_activation_rule(
    req: InitialActivationRuleRequest, session: AsyncSession = Depends(get_session),
):
    row = await _insert(
        session, InitialActivationRule,
        dict(rule_key=req.rule_key, **_initial_activation_rule_values(req)),
    )
    return _initial_activation_rule_response(row)


@router.put("/initial-activation-rules/{rule_id}", response_model=InitialActivationRuleResponse)
async def update_initial_activation_rule(
    rule_id: int, req: InitialActivationRuleRequest, session: AsyncSession = Depends(get_session),
):
    key = await _existing(
        session, InitialActivationRule, rule_id, f"Initial activation rule {rule_id} not found")
    row = await _update(session, InitialActivationRule, key, _initial_activation_rule_values(req))
    return _initial_activation_rule_response(row)


@router.delete("/initial-activation-rules/{rule_id}")
async def delete_initial_activation_rule(rule_id: int, session: AsyncSession = Depends(get_session)):
    key = await _existing(
        session, InitialActivationRule, rule_id, f"Initial activation rule {rule_id} not found")
    await _delete(session, InitialActivationRule, key)
    return {"deleted": rule_id}


# ------------------------------------------------------------------
# Posting rules
# ------------------------------------------------------------------


class PostingRuleRequest(BaseModel):
    #: Optional.  Left out on create, the server picks a free key (the codelet type, else a
    #: numbered variant).  Ignored on update: a rule keeps its key.
    rule_key: str | None = None
    codelet_type: str
    direction: str
    urgency_level: str | None = None
    urgency_formula: str | None = None
    #: A rule states what it posts with: no default, and not blank (ruling 27).
    posting_formula: str = Field(min_length=1)
    count_formula: str = Field(min_length=1)
    count_values: dict | None = None
    condition: str = Field(min_length=1)
    triggering_slipnodes: list[str] | None = None


class PostingRuleResponse(BaseModel):
    id: int
    rule_key: str
    codelet_type: str
    direction: str
    urgency_level: str | None
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
            id=r.id, rule_key=r.rule_key, codelet_type=r.codelet_type, direction=r.direction,
            urgency_level=r.urgency_level, urgency_formula=r.urgency_formula,
            posting_formula=r.posting_formula, count_formula=r.count_formula,
            count_values=r.count_values, condition=r.condition,
            triggering_slipnodes=r.triggering_slipnodes,
        )
        for r in result.scalars().all()
    ]


@router.post("/posting-rules", response_model=PostingRuleResponse, status_code=201)
async def create_posting_rule(
    req: PostingRuleRequest, session: AsyncSession = Depends(get_session),
):
    taken = set((await session.execute(select(PostingRule.rule_key))).scalars().all())
    if req.rule_key:
        if req.rule_key in taken:
            raise HTTPException(
                409, f"A posting rule with rule_key '{req.rule_key}' already exists; "
                "choose another rule_key, or leave it out to have one picked.")
        rule_key = req.rule_key
    else:
        rule_key = req.codelet_type
        n = 1
        while rule_key in taken:
            n += 1
            rule_key = f"{req.codelet_type}-{n}"
    row = await _insert(session, PostingRule, dict(
        rule_key=rule_key,
        codelet_type=req.codelet_type, direction=req.direction,
        urgency_level=req.urgency_level, urgency_formula=req.urgency_formula,
        posting_formula=req.posting_formula, count_formula=req.count_formula,
        count_values=req.count_values, condition=req.condition,
        triggering_slipnodes=req.triggering_slipnodes,
    ))
    return PostingRuleResponse(
        id=row.id, rule_key=row.rule_key, codelet_type=row.codelet_type, direction=row.direction,
        urgency_level=row.urgency_level, urgency_formula=row.urgency_formula,
        posting_formula=row.posting_formula, count_formula=row.count_formula,
        count_values=row.count_values, condition=row.condition,
        triggering_slipnodes=row.triggering_slipnodes,
    )


@router.put("/posting-rules/{rule_id}", response_model=PostingRuleResponse)
async def update_posting_rule(
    rule_id: int, req: PostingRuleRequest, session: AsyncSession = Depends(get_session),
):
    key = await _existing(session, PostingRule, rule_id, f"Posting rule {rule_id} not found")
    row = await _update(session, PostingRule, key, dict(
        codelet_type=req.codelet_type,
        direction=req.direction,
        urgency_level=req.urgency_level,
        urgency_formula=req.urgency_formula,
        posting_formula=req.posting_formula,
        count_formula=req.count_formula,
        count_values=req.count_values,
        condition=req.condition,
        triggering_slipnodes=req.triggering_slipnodes,
    ))
    return PostingRuleResponse(
        id=row.id, rule_key=row.rule_key, codelet_type=row.codelet_type, direction=row.direction,
        urgency_level=row.urgency_level, urgency_formula=row.urgency_formula,
        posting_formula=row.posting_formula, count_formula=row.count_formula,
        count_values=row.count_values, condition=row.condition,
        triggering_slipnodes=row.triggering_slipnodes,
    )


@router.delete("/posting-rules/{rule_id}")
async def delete_posting_rule(rule_id: int, session: AsyncSession = Depends(get_session)):
    key = await _existing(session, PostingRule, rule_id, f"Posting rule {rule_id} not found")
    await _delete(session, PostingRule, key)
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
    row = await _insert(
        session, CommentaryTemplate,
        dict(template_key=req.template_key, template_data=req.template_data),
    )
    return CommentaryTemplateResponse(id=row.id, template_key=row.template_key, template_data=row.template_data)


@router.put("/commentary-templates/{template_id}", response_model=CommentaryTemplateResponse)
async def update_commentary_template(
    template_id: int, req: CommentaryTemplateRequest, session: AsyncSession = Depends(get_session),
):
    key = await _existing(session, CommentaryTemplate, template_id, f"Commentary template {template_id} not found")
    row = await _update(
        session, CommentaryTemplate, key,
        dict(template_key=req.template_key, template_data=req.template_data),
    )
    return CommentaryTemplateResponse(id=row.id, template_key=row.template_key, template_data=row.template_data)


@router.delete("/commentary-templates/{template_id}")
async def delete_commentary_template(template_id: int, session: AsyncSession = Depends(get_session)):
    key = await _existing(session, CommentaryTemplate, template_id, f"Commentary template {template_id} not found")
    await _delete(session, CommentaryTemplate, key)
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
    row = await _insert(
        session, SlipnetLayoutPos,
        dict(node_name=req.node_name, grid_row=req.grid_row, grid_col=req.grid_col),
    )
    return SlipnetLayoutResponse(node_name=row.node_name, grid_row=row.grid_row, grid_col=row.grid_col)


@router.put("/slipnet-layout/{node_name}", response_model=SlipnetLayoutResponse)
async def update_slipnet_layout(
    node_name: str, req: SlipnetLayoutRequest, session: AsyncSession = Depends(get_session),
):
    key = await _existing(session, SlipnetLayoutPos, node_name, f"Layout for node '{node_name}' not found")
    row = await _update(
        session, SlipnetLayoutPos, key, dict(grid_row=req.grid_row, grid_col=req.grid_col)
    )
    return SlipnetLayoutResponse(node_name=row.node_name, grid_row=row.grid_row, grid_col=row.grid_col)


@router.delete("/slipnet-layout/{node_name}")
async def delete_slipnet_layout(node_name: str, session: AsyncSession = Depends(get_session)):
    key = await _existing(session, SlipnetLayoutPos, node_name, f"Layout for node '{node_name}' not found")
    await _delete(session, SlipnetLayoutPos, key)
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
# Export
# ------------------------------------------------------------------


#: Slipnet node columns an export carries only when a node has a value.
_NODE_OPTIONAL_COLUMNS = (
    "plain_name", "glyph", "numeric_value", "full_name", "cm_short_name",
    "article_an",
)


@router.get("/export")
async def export_metadata(session: AsyncSession = Depends(get_session)):
    """Export all metadata as a single JSON object."""
    # Ordered by primary key throughout, so two exports of the same configuration are
    # the same bytes and a backup can be diffed against the file it came from.
    # Where a table keeps the file's order (``sort_order``), that is the order, so a
    # configuration written out to the seed files comes back in the order it was read in.
    nodes_result = await session.execute(
        select(SlipnetNodeDef).order_by(SlipnetNodeDef.sort_order, SlipnetNodeDef.name)
    )
    links_result = await session.execute(
        select(SlipnetLinkDef).order_by(SlipnetLinkDef.sort_order, SlipnetLinkDef.id)
    )
    codelets_result = await session.execute(
        select(CodeletTypeDef).order_by(CodeletTypeDef.sort_order, CodeletTypeDef.name)
    )
    params_result = await session.execute(
        select(EngineParam).order_by(EngineParam.sort_order, EngineParam.name)
    )
    urgency_result = await session.execute(
        select(UrgencyLevel).order_by(UrgencyLevel.sort_order, UrgencyLevel.name)
    )
    formula_result = await session.execute(
        select(FormulaCoefficient).order_by(FormulaCoefficient.sort_order, FormulaCoefficient.name)
    )
    demos_result = await session.execute(select(DemoProblem).order_by(DemoProblem.id))
    theme_dims_result = await session.execute(
        select(ThemeDimensionDef).order_by(ThemeDimensionDef.id)
    )
    posting_result = await session.execute(
        select(PostingRule).order_by(PostingRule.sort_order, PostingRule.id)
    )
    initial_descriptions_result = await session.execute(
        select(InitialDescriptionRule).order_by(
            InitialDescriptionRule.ordinal, InitialDescriptionRule.rule_key.collate("C"))
    )
    initial_activations_result = await session.execute(
        select(InitialActivationRule).order_by(
            InitialActivationRule.ordinal, InitialActivationRule.rule_key.collate("C"))
    )
    patterns_result = await session.execute(
        select(CodeletPatternDef).order_by(CodeletPatternDef.ordinal, CodeletPatternDef.id)
    )
    node_roles_result = await session.execute(
        select(SlipnetNodeRole).order_by(SlipnetNodeRole.role.collate("C"), SlipnetNodeRole.ordinal)
    )
    codelet_roles_result = await session.execute(
        select(CodeletTypeRole).order_by(CodeletTypeRole.role.collate("C"), CodeletTypeRole.ordinal)
    )
    relations_result = await session.execute(
        select(ThemeRelation).order_by(ThemeRelation.ordinal, ThemeRelation.name)
    )
    commentary_result = await session.execute(
        select(CommentaryTemplate).order_by(CommentaryTemplate.id)
    )
    layout_result = await session.execute(
        select(SlipnetLayoutPos).order_by(SlipnetLayoutPos.sort_order, SlipnetLayoutPos.node_name)
    )
    help_result = await session.execute(select(HelpTopic).order_by(HelpTopic.id))

    return {
        "slipnet_nodes": [
            {
                "name": r.name,
                "short_name": r.short_name,
                "conceptual_depth": r.conceptual_depth,
                "description": r.description or "",
                "descriptor_predicate": r.descriptor_predicate,
                # The EN2 columns, when the node has them (a file omits what a node lacks).
                **{
                    column: getattr(r, column)
                    for column in _NODE_OPTIONAL_COLUMNS
                    if getattr(r, column) is not None
                },
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
                "fixed_length": r.fixed_length,
            }
            for r in links_result.scalars().all()
        ],
        "codelet_types": [
            {
                "name": r.name,
                "family": r.family,
                "phase": r.phase,
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
                "refers_to": r.refers_to,
            }
            for r in params_result.scalars().all()
        ],
        "urgency_levels": [
            {"name": r.name, "value": r.value}
            for r in urgency_result.scalars().all()
        ],
        "formula_coefficients": [
            {"name": r.name, "value": r.value, "value_type": r.value_type}
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
                "id": r.id, "rule_key": r.rule_key, "codelet_type": r.codelet_type,
                "direction": r.direction,
                "urgency_level": r.urgency_level, "urgency_formula": r.urgency_formula,
                "posting_formula": r.posting_formula, "count_formula": r.count_formula,
                "count_values": r.count_values, "condition": r.condition,
                "triggering_slipnodes": r.triggering_slipnodes,
            }
            for r in posting_result.scalars().all()
        ],
        "initial_description_rules": [
            {
                "id": r.id, "rule_key": r.rule_key, "ordinal": r.ordinal, "subject": r.subject,
                "dimension_role": r.dimension_role, "descriptor_source": r.descriptor_source,
                "descriptor_role": r.descriptor_role, "condition": r.condition,
                "activate_descriptor": r.activate_descriptor, "built": r.built,
                "bond_description": r.bond_description,
            }
            for r in initial_descriptions_result.scalars().all()
        ],
        "initial_activation_rules": [
            {
                "id": r.id, "rule_key": r.rule_key, "ordinal": r.ordinal,
                "node_role": r.node_role, "condition": r.condition,
            }
            for r in initial_activations_result.scalars().all()
        ],
        "codelet_patterns": [
            {
                "id": r.id, "pattern_name": r.pattern_name,
                "codelet_type": r.codelet_type, "urgency_level": r.urgency_level,
            }
            for r in patterns_result.scalars().all()
        ],
        "commentary_templates": [
            {"id": r.id, "template_key": r.template_key, "template_data": r.template_data}
            for r in commentary_result.scalars().all()
        ],
        "slipnet_layout": [
            {"node_name": r.node_name, "grid_row": r.grid_row, "grid_col": r.grid_col}
            for r in layout_result.scalars().all()
        ],
        # Not among the importable collections (``_IMPORTABLE``); the Admin API for them
        # arrives with the change API.  Exported so the download loses nothing.
        "slipnet_node_roles": [
            {"role": r.role, "ordinal": r.ordinal, "node_name": r.node_name}
            for r in node_roles_result.scalars().all()
        ],
        "codelet_type_roles": [
            {"role": r.role, "ordinal": r.ordinal, "codelet_type": r.codelet_type}
            for r in codelet_roles_result.scalars().all()
        ],
        "theme_relations": [
            {
                "name": r.name, "ordinal": r.ordinal, "node_name": r.node_name,
                "abstractness": r.abstractness, "description": r.description or "",
            }
            for r in relations_result.scalars().all()
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


#: Every collection ``GET /export`` writes, and where it lands on the way back in:
#: the model, the primary key a row is matched on, and any payload key whose name
#: differs from the ORM attribute.  Export and import read this one list, so the two
#: cover the same fifteen collections.
_IMPORTABLE: tuple[tuple[str, type, str, dict[str, str]], ...] = (
    ("slipnet_nodes", SlipnetNodeDef, "name", {}),
    ("slipnet_links", SlipnetLinkDef, "id", {}),
    ("codelet_types", CodeletTypeDef, "name", {}),
    ("engine_params", EngineParam, "name", {}),
    ("urgency_levels", UrgencyLevel, "name", {}),
    ("formula_coefficients", FormulaCoefficient, "name", {}),
    ("demo_problems", DemoProblem, "id", {}),
    ("theme_dimensions", ThemeDimensionDef, "id", {}),
    ("posting_rules", PostingRule, "id", {}),
    ("initial_description_rules", InitialDescriptionRule, "id", {}),
    ("initial_activation_rules", InitialActivationRule, "id", {}),
    ("codelet_patterns", CodeletPatternDef, "id", {}),
    ("commentary_templates", CommentaryTemplate, "id", {}),
    ("slipnet_layout", SlipnetLayoutPos, "node_name", {}),
    # ``metadata`` is reserved on a declarative class, so the column is reached
    # through ``metadata_json``.
    ("help_topics", HelpTopic, "id", {"metadata": "metadata_json"}),
)


def _model_attributes(model: type) -> set[str]:
    """The ORM attribute names a row may set."""
    from sqlalchemy import inspect as sa_inspect

    return {attr.key for attr in sa_inspect(model).mapper.column_attrs}


async def _import_collection(
    session: AsyncSession,
    model: type,
    key_field: str,
    rows: list[dict],
    aliases: dict[str, str],
) -> tuple[int, list[dict]]:
    """One collection's rows as ops, each matched on its natural key.

    A configuration row already present becomes an update of the columns the payload
    carries; one that is not becomes an insert.  The surrogate ``id`` a payload carries is
    dropped: ids are not stable across configurations, and the key is the natural key.
    Payload keys the model does not carry are left alone, so a payload from a newer
    export loads into an older schema for the columns the two share.  Returns the row
    count and the ops (none for ``help_topics``, which is content and is written
    directly, unflushed).
    """
    attributes = _model_attributes(model)
    if model is HelpTopic:
        for raw in rows:
            row = {aliases.get(key, key): value for key, value in raw.items()}
            row = {key: value for key, value in row.items() if key in attributes}
            if key_field not in row:
                raise ValueError(f"{model.__tablename__}: a row arrived without its {key_field}")
            existing = await session.get(model, row[key_field])
            if existing is None:
                session.add(model(**row))
            else:
                for field, value in row.items():
                    if field != key_field:
                        setattr(existing, field, value)
        return len(rows), []

    spec = LAYER_REGISTRY[model.__tablename__]
    present = {
        spec.key_tuple(spec.key_of(r)) for r in (await session.execute(select(model))).scalars()
    }
    ops: list[dict] = []
    for raw in rows:
        row = {aliases.get(key, key): value for key, value in raw.items()}
        row = {
            key: value for key, value in row.items()
            if key in attributes and key != spec.surrogate
        }
        missing = [c for c in spec.key if c not in row and not spec.table.c[c].nullable]
        if missing:
            raise ValueError(f"{model.__tablename__}: a row arrived without its {missing[0]}")
        key = spec.key_of(row)
        kt = spec.key_tuple(key)
        if kt in present:
            ops.append({
                "op": "update", "table": spec.name, "key": key,
                "fields": {c: v for c, v in row.items() if c not in spec.key},
            })
        else:
            ops.append({"op": "insert", "table": spec.name, "row": row})
            present.add(kt)
    return len(rows), ops


@router.post("/import")
async def import_metadata(
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Import metadata from a JSON object — the same fifteen collections ``/export`` writes.

    Every collection present in the payload is applied; the response names each one and
    how many rows it carried, so what was written is legible from the reply. Configuration
    rows are matched on their natural key and written as one journal entry
    (``source = import``); the whole import is one transaction.
    """
    if _target(session) != GLOBAL:
        raise HTTPException(
            422, "an import reads the global configuration's rows to match them; import into "
                 "a session's configuration with a change batch")
    imported: dict[str, int] = {}
    ops: list[dict] = []
    try:
        for name, model, key_field, aliases in _IMPORTABLE:
            rows = data.get(name)
            if rows is None:
                continue
            imported[name], collection_ops = await _import_collection(
                session, model, key_field, rows, aliases
            )
            ops.extend(collection_ops)

        # Help topics are flushed above and committed with the configuration entry below.
        await session.flush()
        await _apply(session, ops, source="import", channel="admin_import")

    except HTTPException as e:
        await session.rollback()
        raise HTTPException(400, f"Import failed: {e.detail}") from e
    except Exception as e:
        await session.rollback()
        raise HTTPException(400, f"Import failed: {e}")

    return {"imported": imported}


# ------------------------------------------------------------------
# Enum tables — generic CRUD
# ------------------------------------------------------------------

# Map of table name -> ORM model class: every enum lookup table of the registry.
_ENUM_TABLES: dict[str, type] = {name: spec.model for name, spec in ENUM_REGISTRY.items()}

#: The four columns every enum table has; a table may add more (``role``, ``behaviour``,
#: ``serialised``, a clamp type's factors, a progress focus's event types).
_ENUM_BASE_COLUMNS = ("name", "display_label", "sort_order", "description")


class EnumValueRequest(BaseModel):
    """A new row: the four columns every enum table has, and the table's own (``role`` ...)."""

    model_config = ConfigDict(extra="allow")

    name: str
    display_label: str
    sort_order: int = 0
    description: str = ""


class EnumValueUpdateRequest(BaseModel):
    """The columns of a row that change (its name is its key and does not): the three every
    enum table has, and the table's own."""

    model_config = ConfigDict(extra="allow")

    display_label: str
    sort_order: int = 0
    description: str = ""


class EnumRenameRequest(BaseModel):
    new_name: str


def _get_enum_model(table: str) -> type:
    model = _ENUM_TABLES.get(table)
    if model is None:
        raise HTTPException(404, f"Unknown enum table '{table}'")
    return model


def _enum_extra_columns(table: str) -> list[dict[str, Any]]:
    """The columns of an enum table beyond the four it always has, for the editor."""
    spec = LAYER_REGISTRY[table]
    vocabulary = VOCABULARY_TABLES.get(table)
    out = []
    for name in spec.columns:
        if name in _ENUM_BASE_COLUMNS:
            continue
        column = spec.table.c[name]
        kind = column.type.__class__.__name__.lower()
        entry: dict[str, Any] = {
            "name": name,
            "type": {"boolean": "bool", "float": "float", "integer": "int", "json": "json"}.get(kind, "text"),
            "nullable": bool(column.nullable),
            "pick": None,
            "references": None,
        }
        if vocabulary is not None and name == vocabulary.column:
            entry["pick"] = list(vocabulary.roles)
        ref = REFERENCES.get((table, name)) or ENUM_COLUMN_REFERENCES.get((table, name))
        if ref is not None:
            entry["references"] = ref[0]
        out.append(entry)
    return out


def _enum_row(table: str, row: Any) -> dict[str, Any]:
    """Every column of a stored row, for the editor (a text column reads ``""`` for NULL only
    where it always did: the description)."""
    out = {name: getattr(row, name) for name in LAYER_REGISTRY[table].columns}
    out["description"] = out.get("description") or ""
    return out


def _enum_values(table: str, base: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
    """The base columns and the table's own, checked: a column the table does not have is a
    422, as is a value of the wrong kind."""
    columns = {c["name"]: c for c in _enum_extra_columns(table)}
    values = dict(base)
    for name, value in (extra or {}).items():
        column = columns.get(name)
        if column is None:
            raise HTTPException(422, f"{table} has no column {name!r}")
        ok = (
            value is None and column["nullable"]
            or column["type"] == "bool" and isinstance(value, bool)
            or column["type"] == "float" and isinstance(value, (int, float)) and not isinstance(value, bool)
            or column["type"] == "int" and isinstance(value, int) and not isinstance(value, bool)
            or column["type"] == "json" and isinstance(value, list)
            or column["type"] == "text" and isinstance(value, str)
        )
        if not ok:
            raise HTTPException(422, f"{table}.{name} {value!r} is not a valid {column['type']}")
        values[name] = value
    return values


async def _enum_names(session: AsyncSession, table: str) -> set[str]:
    model = _ENUM_TABLES.get(table)
    if model is not None:
        return set((await session.execute(select(model.name))).scalars())
    return set((await session.execute(select(UrgencyLevel.name))).scalars())


async def _check_enum_write(
    session: AsyncSession, table: str, values: dict[str, Any], *, exclude: str | None
) -> None:
    """The vocabulary rules for a row about to be written: its ``role`` (or ``behaviour``) is a
    name of the table's vocabulary and held by no other row, and the names it holds in the
    columns that reference another table exist there."""
    model = _ENUM_TABLES[table]
    others = [
        {c: getattr(r, c) for c in LAYER_REGISTRY[table].columns}
        for r in (await session.execute(select(model))).scalars()
        if r.name != exclude
    ]
    problem = role_problem(table, values, others, key=[values.get("name")])
    if problem is not None:
        raise HTTPException(problem.status, f"{problem.kind}: {problem.message}")
    for (t, column), (target, many) in {**REFERENCES, **ENUM_COLUMN_REFERENCES}.items():
        if t != table or column not in values or values[column] in (None, ""):
            continue
        known = await _enum_names(session, target)
        for item in values[column] if many else [values[column]]:
            if item not in known:
                raise HTTPException(
                    422, f"unknown_reference: {table}.{column} names {item!r}, which {target} does not have")


@router.get("/enums")
async def list_enum_tables():
    """List all enum table names, with what an editor needs about each.

    ``roles`` gives, for each table whose rows the engine names, the column that holds the
    binding (``role``; ``behaviour`` for ``link_types``) and the names that column may hold
    (the engine's vocabulary for the table, ``server/engine/roles.py``); ``columns`` gives the
    columns of each table beyond the four every enum table has.
    """
    return {
        "tables": sorted(_ENUM_TABLES.keys()),
        "roles": roles_by_table(),
        "columns": {t: _enum_extra_columns(t) for t in sorted(_ENUM_TABLES)},
    }


@router.get("/enums/{table}")
async def list_enum_values(
    table: str,
    session: AsyncSession = Depends(get_session),
):
    """List all values in an enum table: every column of each row."""
    model = _get_enum_model(table)
    result = await session.execute(select(model).order_by(*LAYER_REGISTRY[table].order_by()))
    return [_enum_row(table, r) for r in result.scalars().all()]


@router.post("/enums/{table}", status_code=201)
async def create_enum_value(
    table: str,
    req: EnumValueRequest,
    session: AsyncSession = Depends(get_session),
):
    """Add a value to an enum table (an unbound row is inert until a column refers to it)."""
    model = _get_enum_model(table)
    _require_global(session, table)
    values = _enum_values(table, dict(
        name=req.name,
        display_label=req.display_label,
        sort_order=req.sort_order,
        description=req.description,
    ), req.model_extra)
    await _check_enum_write(session, table, values, exclude=None)
    row = await _insert(session, model, values)
    return {**{c: getattr(row, c) for c in LAYER_REGISTRY[table].columns}, "description": row.description or ""}


@router.put("/enums/{table}/{name}")
async def update_enum_value(
    table: str,
    name: str,
    req: EnumValueUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update the columns of an enum value but its name (``POST .../rename`` renames it)."""
    model = _get_enum_model(table)
    key = await _existing(session, model, name, f"Value '{name}' not found in {table}")
    changes = _enum_values(table, dict(
        display_label=req.display_label,
        sort_order=req.sort_order,
        description=req.description,
    ), req.model_extra)
    await _check_enum_write(session, table, {**changes, "name": name}, exclude=name)
    row = await _update(session, model, key, changes)
    return {**{c: getattr(row, c) for c in LAYER_REGISTRY[table].columns}, "description": row.description or ""}


@router.post("/enums/{table}/{name}/rename")
async def rename_enum_value(
    table: str,
    name: str,
    req: EnumRenameRequest,
    session: AsyncSession = Depends(get_session),
):
    """Rename an enum value: the change API's ``rename_enum_value``.

    Every column that references the row is rewritten with it, and the report lists the code,
    parameters and templates that still spell the old name (``dangling``).  The row keeps its
    role.  A session's Episodic Memory is not rewritten (see ``API.md``, the change API).
    """
    _get_enum_model(table)
    await _existing(session, _ENUM_TABLES[table], name, f"Value '{name}' not found in {table}")
    report = await _apply(
        session, [{"op": "rename_enum_value", "table": table, "old": name, "new": req.new_name}])
    return {"renamed": req.new_name, "table": table, "report": report}


@router.delete("/enums/{table}/{name}")
async def delete_enum_value(
    table: str,
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete an enum value.

    Refused with ``422 role_bound`` while the row holds a ``role`` (or, for ``link_types``, a
    ``behaviour``): unbind it first by setting the column to null.  Refused with 409 while
    another row refers to it.
    """
    model = _get_enum_model(table)
    key = await _existing(session, model, name, f"Value '{name}' not found in {table}")
    stored = await session.get(model, name)
    if stored is not None:
        bound = delete_problem(table, {"name": name, **{
            c: getattr(stored, c) for c in LAYER_REGISTRY[table].columns}})
        if bound is not None:
            raise HTTPException(bound.status, f"{bound.kind}: {bound.message}")
    # Columns that name an enum row without a foreign key (the database cannot refuse them).
    for (t, column), (target, many) in {**REFERENCES, **ENUM_COLUMN_REFERENCES}.items():
        if target != table or t not in _ENUM_TABLES:
            continue
        for other in (await session.execute(select(_ENUM_TABLES[t]))).scalars():
            value = getattr(other, column)
            if name in (value if many else [value]) if value is not None else False:
                raise HTTPException(
                    409,
                    f"Cannot delete '{name}' from {table} — {t} row '{other.name}' refers to it in {column}")
    try:
        await _delete(session, model, key)
    except HTTPException:
        raise
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
    """Re-sync help topics from the topics JSON and regenerate derived docs.

    Triggered by the Admin panel's "Regenerate Help Documentation" button.
    Performs two steps:

    1. Upsert every row from `seed_data/help_topics.en.json` into the
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
    from server.config import SEED_DATA_DIR
    from server.services.help_docs import regenerate_all
    from server.services.standard_configuration import sync_help_topics

    # Step 1: upsert DB rows from JSON (sync_help_topics commits)
    try:
        await sync_help_topics(session, SEED_DATA_DIR)
    except Exception as e:
        raise HTTPException(500, f"DB sync failed: {e}") from e

    # Step 2: regenerate derived files (HELP.md, helpTopics.ts)
    try:
        result = regenerate_all()
    except FileNotFoundError as e:
        raise HTTPException(404, f"Help topics file not found: {e}") from e
    except Exception as e:
        raise HTTPException(500, f"Regeneration failed: {e}") from e

    return {
        "status": "ok",
        "db_synced": True,
        **result.as_dict(),
    }
