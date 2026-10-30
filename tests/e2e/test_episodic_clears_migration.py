"""The lossless conversion of Training Sessions into Episodic Memory clears.

Metacat Mode has no sessions: runs are episodic runs and clearing Episodic Memory is an
event.  An older database recorded sessions in ``training_sessions`` and stamped
``runs.session_id``; ``convert_sessions_to_clears`` (shared by Alembic 018 and startup)
must turn that into ``episodic_memory_clears`` without losing a note or misplacing a run.

These run against a scratch database, ``petacat_migration_test``, created and dropped
here, because the conversion drops a table and a column.  ``petacat_test`` is never used.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from server.services.episodic_clears_migration import (
    EpisodicClearMigrationError,
    convert_clears_to_sessions,
    convert_sessions_to_clears,
    plan_clears,
)
from tests.e2e.conftest import TEST_DB_URL

SCRATCH = "petacat_migration_test"
SCRATCH_URL = TEST_DB_URL.rsplit("/", 1)[0] + "/" + SCRATCH
REPO = Path(__file__).resolve().parents[2]

@pytest.fixture
async def scratch():
    """An empty scratch database holding the pre-018 shape of the two tables."""
    admin = create_async_engine(
        TEST_DB_URL.rsplit("/", 1)[0] + "/petacat",
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
        await conn.execute(text(f"CREATE DATABASE {SCRATCH}"))
    engine = create_async_engine(SCRATCH_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE runs (id SERIAL PRIMARY KEY, session_id INTEGER)"))
        await conn.execute(text("CREATE INDEX ix_runs_session_id ON runs (session_id)"))
        await conn.execute(
            text(
                "CREATE TABLE training_sessions (id SERIAL PRIMARY KEY, "
                "started_at TIMESTAMP, ended_at TIMESTAMP, note TEXT)"
            )
        )
    yield engine
    await engine.dispose()
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
    await admin.dispose()


async def _seed(engine, sessions, runs_per_session):
    """``sessions`` = [(ended_at | None, note)], ``runs_per_session`` = run counts."""
    async with engine.begin() as conn:
        for ended, note in sessions:
            await conn.execute(
                text(
                    "INSERT INTO training_sessions (started_at, ended_at, note) "
                    "VALUES (:s, :e, :n)"
                ),
                {"s": datetime(2026, 1, 1), "e": ended, "n": note},
            )
        for sid, count in enumerate(runs_per_session, start=1):
            for _ in range(count):
                await conn.execute(text("INSERT INTO runs (session_id) VALUES (:s)"), {"s": sid})


async def _clears(engine):
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, cleared_at, after_run_id, note "
                    "FROM episodic_memory_clears ORDER BY id"
                )
            )
        ).all()
    return [(r.cleared_at, r.after_run_id, r.note) for r in rows]


async def _has(engine, table=None, column=None):
    async with engine.connect() as conn:
        if table:
            return bool(
                (await conn.execute(text("SELECT to_regclass(:t)"), {"t": table})).scalar()
            )
        return bool(
            (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name='runs' AND column_name=:c"
                    ),
                    {"c": column},
                )
            ).scalar()
        )


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_the_mapping_is_a_pure_function():
    """The plan is computable without a database: that is what both paths share."""
    sessions = [
        (1, datetime(2026, 1, 1), "a"),
        (2, datetime(2026, 2, 1), ""),
        (3, None, "open"),
    ]
    through = {1: 3, 2: 5, 3: 7}
    clears, open_note = plan_clears(sessions, through.get)
    assert clears == [
        {"cleared_at": datetime(2026, 1, 1), "after_run_id": 3,
         "note": "Runs before this clear: a"},
        {"cleared_at": datetime(2026, 2, 1), "after_run_id": 5, "note": ""},
    ]
    assert open_note == "Runs after this clear: open"


@pytest.mark.asyncio
async def test_sessions_with_notes_become_clears_without_losing_a_note(scratch):
    await _seed(
        scratch,
        [
            (datetime(2026, 1, 1, 12, 0), "alpha"),
            (datetime(2026, 2, 1, 8, 30), ""),
            (None, "gamma"),
        ],
        [3, 2, 2],
    )
    async with scratch.begin() as conn:
        result = await conn.run_sync(convert_sessions_to_clears)
    assert result == {"converted": True, "clears": 2}

    assert await _clears(scratch) == [
        (_utc(2026, 1, 1, 12, 0), 3, "Runs before this clear: alpha"),
        # The open session's note lands on the latest clear.
        (_utc(2026, 2, 1, 8, 30), 5, "Runs after this clear: gamma"),
    ]
    assert not await _has(scratch, table="training_sessions")
    assert not await _has(scratch, column="session_id")
    async with scratch.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM runs"))).scalar() == 7


@pytest.mark.asyncio
async def test_the_open_note_is_appended_to_a_note_the_latest_clear_already_has(scratch):
    await _seed(
        scratch,
        [(datetime(2026, 1, 1), "alpha"), (datetime(2026, 2, 1), "beta"), (None, "gamma")],
        [1, 1, 1],
    )
    async with scratch.begin() as conn:
        await conn.run_sync(convert_sessions_to_clears)
    notes = [c[2] for c in await _clears(scratch)]
    assert notes == [
        "Runs before this clear: alpha",
        "Runs before this clear: beta\nRuns after this clear: gamma",
    ]


@pytest.mark.asyncio
async def test_an_open_session_note_with_no_clear_fails_loudly_and_changes_nothing(scratch):
    await _seed(scratch, [(None, "the only note")], [4])
    with pytest.raises(EpisodicClearMigrationError, match="no ended session"):
        async with scratch.begin() as conn:
            await conn.run_sync(convert_sessions_to_clears)
    # Nothing was lost: the note, the table and the column are all still there.
    assert await _has(scratch, table="training_sessions")
    assert await _has(scratch, column="session_id")
    async with scratch.connect() as conn:
        note = (await conn.execute(text("SELECT note FROM training_sessions"))).scalar()
        assert note == "the only note"
        assert await _has(scratch, table="episodic_memory_clears") is False


@pytest.mark.asyncio
async def test_the_dev_database_shape_converts_and_conversion_is_idempotent(scratch):
    """Two sessions, the first ended, no notes, 8 + 19 runs: one clear after run 8."""
    await _seed(scratch, [(datetime(2026, 8, 29, 19, 35, 4, 382166), ""), (None, "")], [8, 19])
    async with scratch.begin() as conn:
        first = await conn.run_sync(convert_sessions_to_clears)
    assert first == {"converted": True, "clears": 1}
    expected = [(_utc(2026, 8, 29, 19, 35, 4, 382166), 8, "")]
    assert await _clears(scratch) == expected

    async with scratch.begin() as conn:
        again = await conn.run_sync(convert_sessions_to_clears)
    assert again == {"converted": False, "clears": 0}
    assert await _clears(scratch) == expected


@pytest.mark.asyncio
async def test_a_session_with_no_runs_gets_a_null_marker_and_unstamped_runs_are_ignored(scratch):
    await _seed(scratch, [(datetime(2026, 1, 1), ""), (datetime(2026, 2, 1), ""), (None, "")], [0, 2, 0])
    async with scratch.begin() as conn:
        await conn.execute(text("INSERT INTO runs (session_id) VALUES (NULL)"))  # id 3, unstamped
        await conn.run_sync(convert_sessions_to_clears)
    assert [(c[1]) for c in await _clears(scratch)] == [None, 2]


@pytest.mark.asyncio
async def test_downgrade_rebuilds_sessions_and_stamps_every_run(scratch):
    await _seed(
        scratch,
        [(datetime(2026, 1, 1, 12, 0), "alpha"), (datetime(2026, 2, 1, 8, 30), ""), (None, "gamma")],
        [3, 2, 2],
    )
    async with scratch.begin() as conn:
        await conn.run_sync(convert_sessions_to_clears)
    async with scratch.begin() as conn:
        await conn.run_sync(convert_clears_to_sessions)

    assert not await _has(scratch, table="episodic_memory_clears")
    async with scratch.connect() as conn:
        sessions = (
            await conn.execute(
                text("SELECT id, ended_at, note FROM training_sessions ORDER BY id")
            )
        ).all()
        stamps = (
            await conn.execute(text("SELECT id, session_id FROM runs ORDER BY id"))
        ).all()
    assert [(s.id, s.ended_at, s.note) for s in sessions] == [
        (1, datetime(2026, 1, 1, 12, 0), "alpha"),
        (2, datetime(2026, 2, 1, 8, 30), ""),
        (3, None, "gamma"),
    ]
    assert [r.session_id for r in stamps] == [1, 1, 1, 2, 2, 3, 3]


@pytest.mark.asyncio
async def test_alembic_018_upgrades_and_downgrades_a_real_database(scratch):
    await _seed(scratch, [(datetime(2026, 1, 1), "alpha"), (None, "")], [2, 3])
    async with scratch.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('017')"))

    env = {**os.environ, "DATABASE_URL": SCRATCH_URL}

    def alembic(*args):
        done = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=REPO, env=env, capture_output=True, text=True,
        )
        assert done.returncode == 0, done.stderr + done.stdout

    import asyncio

    await asyncio.to_thread(alembic, "upgrade", "018")
    assert await _clears(scratch) == [(_utc(2026, 1, 1), 2, "Runs before this clear: alpha")]
    assert not await _has(scratch, column="session_id")

    await asyncio.to_thread(alembic, "downgrade", "017")
    assert await _has(scratch, table="training_sessions")
    assert await _has(scratch, column="session_id")
    async with scratch.connect() as conn:
        stamps = [r.session_id for r in (await conn.execute(text("SELECT session_id FROM runs ORDER BY id"))).all()]
        note = (await conn.execute(text("SELECT note FROM training_sessions WHERE id = 1"))).scalar()
    assert stamps == [1, 1, 2, 2, 2]
    assert note == "alpha"

    await asyncio.to_thread(alembic, "upgrade", "018")  # and forward again
    assert [c[1] for c in await _clears(scratch)] == [2]
