"""FastAPI router for documentation endpoints.

Provides contextual help for slipnet concepts, codelet types,
architecture components, glossary terms, and free-text search.

Content comes from:
- slipnet_node_defs.description column
- codelet_type_defs.description column
- help_topics table (components + glossary)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session
from server.models.metadata import CodeletTypeDef, HelpTopic, SlipnetNodeDef

router = APIRouter(prefix="/api/docs", tags=["docs"])


@router.get("/concepts/{name}")
async def concept_help(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Look up a slipnet concept by name and return its description."""
    node = await session.get(SlipnetNodeDef, name)
    if node is None:
        raise HTTPException(404, f"Slipnet concept '{name}' not found")
    return {
        "name": node.name,
        "short_name": node.short_name,
        "conceptual_depth": node.conceptual_depth,
        "description": node.description or "",
    }


@router.get("/codelets/{name}")
async def codelet_help(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Look up a codelet type by name and return its description and source."""
    codelet = await session.get(CodeletTypeDef, name)
    if codelet is None:
        raise HTTPException(404, f"Codelet type '{name}' not found")
    return {
        "name": codelet.name,
        "family": codelet.family,
        "phase": codelet.phase,
        "default_urgency": codelet.default_urgency,
        "description": codelet.description or "",
        "source_file": codelet.source_file or "",
        "source_line": codelet.source_line or 0,
        "execute_body": codelet.execute_body or "",
    }


@router.get("/components/{name}")
async def component_help(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """Look up an architecture component by name (from help_topics table)."""
    key = name.lower().replace("-", "_").replace(" ", "_")

    result = await session.execute(
        select(HelpTopic).where(
            HelpTopic.topic_type == "component",
            HelpTopic.topic_key == key,
        )
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        # Fallback: list valid components
        all_result = await session.execute(
            select(HelpTopic.topic_key).where(HelpTopic.topic_type == "component")
        )
        valid = [r[0] for r in all_result.all()]
        raise HTTPException(
            404,
            f"Component '{name}' not found. Valid: {', '.join(sorted(valid)) or 'none (run seed migration)'}",
        )
    return {
        "name": topic.title,
        "topic_key": topic.topic_key,
        "short_desc": topic.short_desc or "",
        "description": topic.full_desc or "",
        "metadata": topic.metadata_json or {},
    }


@router.get("/glossary/{term}")
async def glossary_help(
    term: str,
    session: AsyncSession = Depends(get_session),
):
    """Look up a glossary term."""
    key = term.lower().replace("-", "_").replace(" ", "_")

    result = await session.execute(
        select(HelpTopic).where(
            HelpTopic.topic_type == "glossary",
            HelpTopic.topic_key == key,
        )
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(404, f"Glossary term '{term}' not found")
    return {
        "term": topic.topic_key,
        "title": topic.title,
        "definition": topic.short_desc or "",
        "details": topic.full_desc or "",
        "metadata": topic.metadata_json or {},
    }


@router.get("/glossary")
async def list_glossary(
    session: AsyncSession = Depends(get_session),
):
    """List all glossary terms."""
    result = await session.execute(
        select(HelpTopic)
        .where(HelpTopic.topic_type == "glossary")
        .order_by(HelpTopic.topic_key)
    )
    return [
        {
            "term": t.topic_key,
            "title": t.title,
            "definition": t.short_desc or "",
        }
        for t in result.scalars().all()
    ]


@router.get("/search")
async def search_docs(
    q: str = Query(..., min_length=1, description="Search query"),
    session: AsyncSession = Depends(get_session),
):
    """Search across slipnet nodes, codelet types, components, and glossary."""
    pattern = f"%{q}%"

    # Search slipnet nodes
    node_result = await session.execute(
        select(SlipnetNodeDef).where(
            or_(
                SlipnetNodeDef.name.ilike(pattern),
                SlipnetNodeDef.short_name.ilike(pattern),
                SlipnetNodeDef.description.ilike(pattern),
            )
        )
    )
    nodes = [
        {
            "type": "slipnet_node",
            "name": r.name,
            "short_name": r.short_name,
            "description": r.description or "",
        }
        for r in node_result.scalars().all()
    ]

    # Search codelet types
    codelet_result = await session.execute(
        select(CodeletTypeDef).where(
            or_(
                CodeletTypeDef.name.ilike(pattern),
                CodeletTypeDef.description.ilike(pattern),
                CodeletTypeDef.family.ilike(pattern),
            )
        )
    )
    codelets = [
        {
            "type": "codelet_type",
            "name": r.name,
            "family": r.family,
            "phase": r.phase,
            "description": r.description or "",
        }
        for r in codelet_result.scalars().all()
    ]

    # Search help topics (components + glossary)
    topic_result = await session.execute(
        select(HelpTopic).where(
            or_(
                HelpTopic.topic_key.ilike(pattern),
                HelpTopic.title.ilike(pattern),
                HelpTopic.short_desc.ilike(pattern),
                HelpTopic.full_desc.ilike(pattern),
            )
        )
    )
    topics = [
        {
            "type": r.topic_type,
            "name": r.title,
            "topic_key": r.topic_key,
            "description": r.short_desc or "",
        }
        for r in topic_result.scalars().all()
    ]

    all_results = nodes + codelets + topics
    return {
        "query": q,
        "results": all_results,
        "total": len(all_results),
    }
