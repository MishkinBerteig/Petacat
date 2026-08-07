"""Seeding the metadata tables from `seed_data/`.

This is the one place the checked-in JSON becomes database rows.  It was extracted
from `server/main.py`'s startup path because a *second* copy of it had grown in
`tests/e2e/conftest.py`, and the two had drifted: the test copy seeded
`posting_rules` and production did not, so the suite ran an engine the application
could never build.  `PHASE 1 PLAN.md` §0.2(c) names that shape — two sources of
truth for one concept — and requires it to be resolved rather than re-homed.

Startup still owns the *decision* to seed (the fingerprint check, dropping the
derived tables, reconciling columns).  What lives here is the writing.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("petacat")

#: Seed files whose contents the DB copy of the bulk metadata mirrors.  Help
#: topics are excluded: they are upserted separately on every startup.
#:
#: A file in this tuple is part of the fingerprint, so editing it re-seeds the
#: derived tables.  That makes membership a claim that `seed_metadata_from_json`
#: writes the file's rows somewhere — `posting_rules.json` sat here for as long as
#: it went unwritten, counting towards the hash of a table it never filled, which is
#: what `tests/integration/test_seed_reconciliation.py` now refuses to allow.
BULK_SEED_FILES = (
    "enums.json",
    "slipnet_nodes.json",
    "slipnet_links.json",
    "slipnet_layout.json",
    "codelet_types.json",
    "engine_params.json",
    "urgency_levels.json",
    "formula_coefficients.json",
    "theme_dimensions.json",
    "demo_problems.json",
    "commentary_templates.json",
    "posting_rules.json",
)

#: EngineParam row that records which seed data the DB was last loaded from.
SEED_FINGERPRINT_PARAM = "__seed_data_fingerprint__"

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
    "demo_modes": "DemoModeDef",
}

#: The help topics ship in one file, which the `en` suffix names.
HELP_TOPICS_FILENAME = "help_topics.en.json"


def seed_data_fingerprint(seed_dir: str) -> str:
    """A digest of the checked-in bulk seed files **and of this seeder**.

    The seeder's own source is in the digest because a fingerprint over the data
    alone cannot see a bug in the code that writes it.  When `posting_rules` was
    added here, every existing database went on serving zero posting rules: the seed
    files had not changed, so the fingerprints matched and startup skipped the
    re-seed that would have filled the table.  The fix that fixed nothing until the
    volume was destroyed is the same silent-divergence failure `PHASE 1 PLAN.md` §0
    is about, one level up.

    The cost is that editing this file — a comment included — re-seeds the derived
    metadata on the next startup and so discards admin edits.  That is already what a
    seed-file edit does, and it is the safe direction to err in: a re-seed loses
    changes that are recorded in the JSON anyway, while a skipped one leaves the
    engine running configuration nobody can see.
    """
    import hashlib

    digest = hashlib.sha256()
    for filename in BULK_SEED_FILES:
        path = os.path.join(seed_dir, filename)
        digest.update(filename.encode())
        try:
            with open(path, "rb") as f:
                digest.update(f.read())
        except FileNotFoundError:
            digest.update(b"<missing>")

    digest.update(b"seeder:")
    try:
        with open(__file__, "rb") as f:
            digest.update(f.read())
    except OSError:  # pragma: no cover — source is on disk in every real deployment
        digest.update(b"<unreadable>")

    return digest.hexdigest()


def tables_referenced_by_runtime(derived_names: set[str]) -> frozenset[str]:
    """Derived tables that runtime data holds foreign keys into.

    ``runs.status`` points at ``run_statuses`` and ``trace_events.event_type`` at
    ``event_types``, so clearing those rows while a user's runs exist is refused
    by the database.  They are stable enum tables, so they get seeded
    insert-if-missing instead of being cleared.  Computed from the schema rather
    than hard-coded, so a new runtime foreign key protects itself.
    """
    import server.models.run  # noqa: F401 — registers the runtime tables

    from server.models.metadata import Base

    protected: set[str] = set()
    for table in Base.metadata.sorted_tables:
        if table.name in derived_names:
            continue  # only runtime / non-derived tables count as referrers
        for fk in table.foreign_keys:
            target = fk.column.table.name
            if target in derived_names:
                protected.add(target)
    return frozenset(protected)


def _derived_names() -> set[str]:
    """Every metadata table the bulk seed files are responsible for."""
    import inspect

    from server.models import metadata as metadata_models

    return {
        cls.__tablename__
        for _, cls in inspect.getmembers(metadata_models, inspect.isclass)
        if getattr(cls, "__module__", "") == metadata_models.__name__
        and hasattr(cls, "__tablename__")
        and cls.__tablename__ not in NON_DERIVED_TABLES
    }


def derived_metadata_tables() -> list:
    """Derived metadata tables, in safe deletion order (children first).

    Restricted to classes declared in ``server.models.metadata``: the runtime
    models in ``server.models.run`` share the same declarative ``Base``, so
    walking ``Base.metadata`` wholesale would have swept up ``runs``,
    ``trace_events``, ``cycle_snapshots`` and the episodic-memory tables and
    deleted a user's saved work.

    Ordering comes from SQLAlchemy's own foreign-key sort rather than a
    hand-written list — hand-listing meant playing whack-a-mole with dependencies
    (``posting_rules`` → ``posting_directions``, …) and getting it wrong twice.
    """
    from server.models.metadata import Base

    derived = _derived_names()
    protected = tables_referenced_by_runtime(derived)
    ordered = [
        t
        for t in Base.metadata.sorted_tables
        if t.name in derived and t.name not in protected
    ]
    ordered.reverse()  # children first, so foreign keys stay satisfied
    return ordered


def protected_enum_tables() -> frozenset[str]:
    """Enum tables that runtime foreign keys forbid clearing."""
    return tables_referenced_by_runtime(_derived_names())


async def seed_metadata_from_json(
    session: AsyncSession,
    seed_dir: str,
    *,
    fingerprint: str | None = None,
) -> None:
    """Write every bulk seed file into its metadata table.

    Assumes the derived tables have already been emptied by the caller, except for
    the enum tables `protected_enum_tables()` names, which are seeded
    insert-if-missing because runtime rows point at them.

    *fingerprint* records which seed data this was, as an `EngineParam` row.  Left
    `None` it is computed from *seed_dir*, which is what a caller that has not
    already computed it wants.
    """
    from server.models import metadata as models

    def _load(filename: str) -> Any:
        with open(os.path.join(seed_dir, filename)) as f:
            return json.load(f)

    # Enum lookup tables first — the FK constraints below require them.
    enums_data = _load("enums.json")
    protected = protected_enum_tables()
    for table_name, model_name in ENUM_MODELS.items():
        model_cls = getattr(models, model_name)
        rows = enums_data.get(table_name, [])
        if model_cls.__tablename__ in protected:
            # Never cleared, so add only what is missing rather than colliding on
            # the primary key.
            present = set(
                (await session.execute(select(model_cls.name))).scalars().all()
            )
            rows = [r for r in rows if r["name"] not in present]
        for row in rows:
            session.add(
                model_cls(
                    name=row["name"],
                    display_label=row["display_label"],
                    sort_order=row["sort_order"],
                    description=row.get("description", ""),
                )
            )
    await session.flush()

    for n in _load("slipnet_nodes.json"):
        session.add(
            models.SlipnetNodeDef(
                name=n["name"],
                short_name=n["short_name"],
                conceptual_depth=n["conceptual_depth"],
                description=n.get("description", ""),
                descriptor_predicate=n.get("descriptor_predicate"),
            )
        )

    for lk in _load("slipnet_links.json"):
        session.add(
            models.SlipnetLinkDef(
                from_node=lk["from_node"],
                to_node=lk["to_node"],
                link_type=lk["link_type"],
                label_node=lk.get("label_node"),
                link_length=lk.get("link_length"),
                fixed_length=lk["fixed_length"]
                if "fixed_length" in lk
                else lk.get("link_length") is not None,
            )
        )

    for c in _load("codelet_types.json"):
        session.add(
            models.CodeletTypeDef(
                name=c["name"],
                family=c["family"],
                phase=c["phase"],
                default_urgency=c.get("default_urgency"),
                description=c.get("description", ""),
                source_file=c.get("source_file", ""),
                source_line=c.get("source_line", 0),
                execute_body=c.get("execute_body", ""),
            )
        )

    for k, v in _load("engine_params.json").items():
        session.add(models.EngineParam(name=k, **_param_columns(v)))
    session.add(
        models.EngineParam(
            name=SEED_FINGERPRINT_PARAM,
            value=fingerprint if fingerprint is not None else seed_data_fingerprint(seed_dir),
            value_type="string",
        )
    )

    for k, v in _load("urgency_levels.json").items():
        session.add(models.UrgencyLevel(name=k, value=v))

    for k, v in _load("formula_coefficients.json").items():
        session.add(models.FormulaCoefficient(name=k, value=v))

    for d in _load("demo_problems.json"):
        session.add(
            models.DemoProblem(
                name=d["name"],
                section=d.get("section", ""),
                initial=d["initial"],
                modified=d["modified"],
                target=d["target"],
                answer=d.get("answer"),
                seed=d["seed"],
                mode=d["mode"],
                description=d.get("description", ""),
            )
        )

    # Posting rules.  `id` is assigned explicitly rather than left to the sequence,
    # because the order the engine consults these rules in decides how many draws it
    # takes from the run's random stream — so the file's order is part of the value,
    # and `load_metadata_from_db` sorts on this column to recover it.
    posting_data = _load("posting_rules.json")
    for position, pr in enumerate(posting_data.get("posting_rules", []), start=1):
        session.add(
            models.PostingRule(
                id=position,
                codelet_type=pr["codelet_type"],
                direction=pr["direction"],
                urgency_when_posted=pr.get("urgency_when_posted"),
                urgency_formula=pr.get("urgency_formula"),
                posting_formula=pr.get("posting_formula", ""),
                count_formula=pr.get("count_formula", ""),
                count_values=pr.get("count_values"),
                condition=pr.get("condition", "always"),
                triggering_slipnodes=pr.get("triggering_slipnodes"),
            )
        )

    for td in _load("theme_dimensions.json").get("dimensions", []):
        session.add(
            models.ThemeDimensionDef(
                slipnet_node=td["slipnet_node"],
                valid_relations=td["valid_relations"],
            )
        )

    for name, pos in _load("slipnet_layout.json").get("node_positions", {}).items():
        session.add(
            models.SlipnetLayoutPos(node_name=name, grid_row=pos[0], grid_col=pos[1])
        )

    session.add(
        models.CommentaryTemplate(
            template_key="all", template_data=_load("commentary_templates.json")
        )
    )


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
