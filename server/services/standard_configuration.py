"""Loading the Metacat Standard Configuration (`seed_data/`) into the database.

This is the one place the checked-in JSON becomes database rows.  It was extracted
from `server/main.py`'s startup path because a *second* copy of it had grown in
`tests/e2e/conftest.py`, and the two had drifted: the test copy seeded
`posting_rules` and production did not, so the suite ran an engine the application
could never build.  `PHASE 1 PLAN.md` §0.2(c) names that shape — two sources of
truth for one concept — and requires it to be resolved rather than re-homed.

Start-up (``server/services/configuration_startup.py``) decides whether to load: the
database is the source of truth, and the files are loaded into it only when it is empty.
What lives here is the load's ops (the journal layer, ``server/services/journal.py``,
writes them as the global journal's first entry, ``source = standard_load``), and the
help-topic upsert.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.rational import canonical_rational

logger = logging.getLogger("petacat")

#: Seed files whose contents the DB copy of the bulk metadata mirrors.  Help
#: topics are excluded: they are upserted separately on every startup.
#: Membership is a claim that `seed_metadata_from_json` writes the file's rows
#: somewhere (`tests/integration/test_seed_reconciliation.py` enforces it).
BULK_SEED_FILES = (
    "enums.json",
    "slipnet_nodes.json",
    "slipnet_links.json",
    "slipnet_layout.json",
    "codelet_types.json",
    "engine_params.json",
    "engine_param_refs.json",
    "urgency_levels.json",
    "formula_coefficients.json",
    "theme_dimensions.json",
    "demo_problems.json",
    "commentary_templates.json",
    "posting_rules.json",
    "roles.json",
    "initial_program.json",
    "input_parser.json",
    "theme_relations.json",
)

#: Metadata tables that are *not* derived from the bulk seed files.
NON_DERIVED_TABLES = frozenset({"help_topics"})

#: The enum lookup tables, and the model each one's rows become.
ENUM_MODELS: dict[str, str] = {
    "run_statuses": "RunStatusDef",
    "event_types": "EventTypeDef",
    "bridge_types": "BridgeTypeDef",
    "bridge_orientations": "BridgeOrientationDef",
    "clause_types": "ClauseTypeDef",
    "rule_types": "RuleTypeDef",
    "theme_types": "ThemeTypeDef",
    "proposal_levels": "ProposalLevelDef",
    "link_types": "LinkTypeDef",
    "codelet_families": "CodeletFamilyDef",
    "codelet_phases": "CodeletPhaseDef",
    "posting_directions": "PostingDirectionDef",
    "param_value_types": "ParamValueTypeDef",
    "string_kinds": "StringKindDef",
    "rule_scopes": "RuleScopeDef",
    "failure_kinds": "FailureKindDef",
    "clamp_types": "ClampTypeDef",
    "progress_focuses": "ProgressFocusDef",
}

#: The help topics ship in one file, which the `en` suffix names.
HELP_TOPICS_FILENAME = "help_topics.en.json"


def standard_configuration_hash(seed_dir: str) -> str:
    """A digest of the bulk Metacat Standard Configuration files, recorded at the first load.

    Provenance only (``configuration_state.standard_hash``): nothing compares it with the
    files at start-up, because the database is the source of truth.
    """
    import hashlib

    digest = hashlib.sha256()
    for filename in BULK_SEED_FILES:
        digest.update(filename.encode())
        with open(os.path.join(seed_dir, filename), "rb") as f:
            digest.update(f.read())
    return digest.hexdigest()


def configuration_table_names() -> frozenset[str]:
    """Every table the Metacat Standard Configuration loads into (by model introspection)."""
    from server.services.config_registry import configuration_table_names as names

    return names()


def _derived_names() -> set[str]:
    """Every metadata table the bulk seed files are responsible for."""
    return set(configuration_table_names())


async def seed_metadata_from_json(session: AsyncSession, seed_dir: str) -> None:
    """Write every bulk seed file into its metadata table, as the global journal's first entry.

    The rows go through the journal layer (``server/services/journal.py``) as one
    ``standard_load`` entry: plain inserts into **empty** tables, because the database is
    loaded from the files only when it is empty (the first load, or a test database).  The
    caller owns the transaction (the layer is told not to commit), so the configuration
    rows, this entry and ``configuration_state`` end up in one.
    """
    from server.services.journal import write_immediate

    await write_immediate(
        session,
        ops=standard_load_ops(seed_dir),
        source="standard_load",
        actor="system",
        channel="first_load",
        note="the Metacat Standard Configuration",
        proposed={
            "standard_configuration_hash": standard_configuration_hash(seed_dir),
            "files": list(BULK_SEED_FILES),
        },
        commit=False,
    )


def standard_load_ops(seed_dir: str) -> list[dict]:
    """The Metacat Standard Configuration as resolved insert ops, in load order.

    The rows come from :func:`server.services.config_document.rows_from_standard_files`, the
    one place the checked-in JSON becomes configuration rows (the document built from the
    files and this load therefore cannot differ).  The enum lookup tables come first (the
    foreign keys below require them).  Every order column (``sort_order``, ``ordinal``) is
    written explicitly, because the order of the nodes, links, codelet types, parameters and
    posting rules is behaviour: it fixes the float accumulation order of the spread and which
    node each ``rng.prob`` draw is spent on.  The integer ``id`` of the tables that have one
    comes from the table's sequence, in insertion order.
    """
    from server.services.config_document import rows_from_standard_files
    from server.services.config_registry import LAYER_REGISTRY

    ops: list[dict] = []
    for table, rows in rows_from_standard_files(seed_dir).items():
        for row in rows:
            ops.append(
                {"op": "insert", "table": table, "key": LAYER_REGISTRY[table].key_of(row), "row": row}
            )
    return ops


def _coefficient_columns(value: Any) -> dict[str, str]:
    """The `value` / `value_type` pair a formula coefficient is stored as.

    A JSON string is a rational, ``"n/m"``, stored in its canonical text and held exactly.
    """
    if isinstance(value, str):
        return {"value": canonical_rational(value), "value_type": "rational"}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"value": str(value), "value_type": "int"}
    return {"value": repr(float(value)), "value_type": "float"}


def _param_columns(value: Any) -> dict[str, str]:
    """The `value` / `value_type` pair an engine parameter is stored as.

    `bool` is tested before `int` on purpose: `isinstance(True, int)` is true in
    Python, so the other order files every boolean parameter as an integer and
    `_parse_param` hands the engine `1` where it expects `True`.
    """
    if isinstance(value, (list, dict)):
        return {"value": json.dumps(value), "value_type": "json"}
    if isinstance(value, bool):
        return {"value": str(value).lower(), "value_type": "bool"}
    if isinstance(value, int):
        return {"value": str(value), "value_type": "int"}
    if isinstance(value, float):
        return {"value": str(value), "value_type": "float"}
    return {"value": str(value), "value_type": "string"}


async def sync_help_topics(session: AsyncSession, seed_dir: str) -> None:
    """Upsert all help topics from the topics JSON into the `help_topics` table.

    Unlike the bulk seeding, this is idempotent — it runs on every startup and
    keeps the DB in sync with the JSON source of truth. Existing rows are
    updated by `topic_key`; new rows are inserted.
    """
    from server.models.metadata import HelpTopic

    help_file = os.path.join(seed_dir, HELP_TOPICS_FILENAME)
    if not os.path.exists(help_file):
        logger.warning("Help topics file not found: %s", help_file)
        return

    with open(help_file) as f:
        topics = json.load(f)

    result = await session.execute(select(HelpTopic))
    existing = {t.topic_key: t for t in result.scalars().all()}

    for t in topics:
        key = t["topic_key"]
        if key in existing:
            row = existing[key]
            row.topic_type = t["topic_type"]
            row.title = t["title"]
            row.short_desc = t.get("short_desc", "")
            row.full_desc = t.get("full_desc", "")
            row.metadata_json = t.get("metadata", {})
        else:
            session.add(
                HelpTopic(
                    topic_type=t["topic_type"],
                    topic_key=key,
                    title=t["title"],
                    short_desc=t.get("short_desc", ""),
                    full_desc=t.get("full_desc", ""),
                    metadata_json=t.get("metadata", {}),
                )
            )

    await session.commit()
    logger.info(
        "Help topics synced: %d in file, %d pre-existing",
        len(topics),
        len(existing),
    )
