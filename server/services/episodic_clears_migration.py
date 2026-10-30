"""The lossless conversion from Training Sessions to Episodic Memory clears.

Metacat Mode has no sessions: its runs are episodic runs, and clearing Episodic Memory is an
event.  Earlier databases recorded the span between two clears as a ``training_sessions``
row and stamped ``runs.session_id`` on each run.  This module turns that record into
``episodic_memory_clears`` rows and drops the old table and column.

There is exactly one implementation of the mapping, ``convert_sessions_to_clears``, and it is
shared by Alembic migration 018 and by startup reconciliation (``server/main.py``), because
the development database has no ``alembic_version`` table and is kept current by startup.
It takes a synchronous SQLAlchemy ``Connection`` (``AsyncConnection.run_sync`` hands one over)
and is idempotent: once the old table and column are gone it does nothing.

The mapping:

* each *ended* session, in id order, becomes one clear:
  ``cleared_at`` = ``ended_at``; ``after_run_id`` = the highest ``runs.id`` whose ``session_id``
  is at most that session's id, or null; ``note`` = the session's note, prefixed
  ``"Runs before this clear: "`` when it is not empty;
* the note of the open session (``ended_at`` null) is appended, prefixed
  ``"Runs after this clear: "``, to the latest clear's note.  With no clear at all there is
  nowhere to put it, and ``EpisodicClearMigrationError`` is raised instead of losing it.

``training_sessions.ended_at`` is a naive UTC timestamp; ``cleared_at`` is timestamptz.
"""

from __future__ import annotations

from datetime import timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

BEFORE_PREFIX = "Runs before this clear: "
AFTER_PREFIX = "Runs after this clear: "

CLEARS_DDL = """
CREATE TABLE IF NOT EXISTS episodic_memory_clears (
    id SERIAL PRIMARY KEY,
    cleared_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    after_run_id INTEGER,
    note TEXT NOT NULL DEFAULT ''
)
"""


class EpisodicClearMigrationError(RuntimeError):
    """The conversion would lose data, so it refuses to run."""


def plan_clears(sessions, max_run_id_through):
    """Pure mapping.  ``sessions`` is ``[(id, ended_at, note)]`` in id order.

    ``max_run_id_through(session_id)`` gives the highest run id with ``session_id`` <= it.
    Returns ``(clears, open_note)`` where ``clears`` is a list of
    ``{"cleared_at", "after_run_id", "note"}`` and ``open_note`` is the open sessions' notes
    (already prefixed) as one string, or ``""``.
    """
    clears: list[dict] = []
    open_parts: list[str] = []
    for sid, ended_at, note in sessions:
        note = note or ""
        if ended_at is None:
            if note.strip():
                open_parts.append(AFTER_PREFIX + note)
            continue
        clears.append(
            {
                "cleared_at": ended_at,
                "after_run_id": max_run_id_through(sid),
                "note": (BEFORE_PREFIX + note) if note.strip() else "",
            }
        )
    return clears, "\n".join(open_parts)


def convert_sessions_to_clears(conn: Connection) -> dict:
    """Convert ``training_sessions`` and ``runs.session_id``; a no-op when already converted."""
    insp = inspect(conn)
    has_table = insp.has_table("training_sessions")
    has_column = insp.has_table("runs") and "session_id" in {
        c["name"] for c in insp.get_columns("runs")
    }
    if not has_table and not has_column:
        return {"converted": False, "clears": 0}

    conn.execute(text(CLEARS_DDL))

    sessions = []
    if has_table:
        sessions = [
            tuple(r)
            for r in conn.execute(
                text("SELECT id, ended_at, note FROM training_sessions ORDER BY id")
            )
        ]

    def max_run_id_through(sid):
        if not has_column:
            return None
        return conn.execute(
            text("SELECT max(id) FROM runs WHERE session_id <= :sid"), {"sid": sid}
        ).scalar()

    clears, open_note = plan_clears(sessions, max_run_id_through)

    if open_note and not clears:
        existing = conn.execute(text("SELECT count(*) FROM episodic_memory_clears")).scalar()
        if not existing:
            raise EpisodicClearMigrationError(
                "Cannot convert training_sessions: the open session has a note "
                f"({open_note[:60]!r}...) but there is no ended session, so there is no "
                "Episodic Memory clear to attach it to.  Copy the note somewhere safe, or "
                "clear it, then retry; nothing was changed."
            )

    for c in clears:
        conn.execute(
            text(
                "INSERT INTO episodic_memory_clears (cleared_at, after_run_id, note) "
                "VALUES (CAST(:at AS timestamp) AT TIME ZONE 'UTC', :after, :note)"
            ),
            {"at": c["cleared_at"], "after": c["after_run_id"], "note": c["note"]},
        )
    if open_note:
        conn.execute(
            text(
                "UPDATE episodic_memory_clears SET note = "
                "CASE WHEN note = '' THEN :extra ELSE note || E'\\n' || :extra END "
                "WHERE id = (SELECT max(id) FROM episodic_memory_clears)"
            ),
            {"extra": open_note},
        )

    if has_column:
        conn.execute(text("DROP INDEX IF EXISTS ix_runs_session_id"))
        conn.execute(text("ALTER TABLE runs DROP COLUMN session_id"))
    if has_table:
        conn.execute(text("DROP TABLE training_sessions"))
    return {"converted": True, "clears": len(clears)}


def _split_note(note: str) -> tuple[str, str]:
    """Undo the upgrade's note composition: ``(before-note, after-note)``."""
    after = ""
    marker = "\n" + AFTER_PREFIX
    if marker in note:
        note, after = note.split(marker, 1)
    elif note.startswith(AFTER_PREFIX):
        note, after = "", note[len(AFTER_PREFIX):]
    if note.startswith(BEFORE_PREFIX):
        note = note[len(BEFORE_PREFIX):]
    return note, after


def convert_clears_to_sessions(conn: Connection) -> dict:
    """The downgrade: rebuild sessions and ``runs.session_id`` from the clears.

    Clear *k* (id order) ends session *k*; one open session follows.  A run belongs to the
    first session whose clear has ``after_run_id`` >= the run's id (the open session when
    none).  A clear note that carries the upgrade's prefix is split back out.
    """
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS training_sessions ("
            "id SERIAL PRIMARY KEY, started_at TIMESTAMP, ended_at TIMESTAMP, note TEXT)"
        )
    )
    conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS session_id INTEGER"))
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_runs_session_id ON runs (session_id)")
    )
    clears = conn.execute(
        text("SELECT id, cleared_at, after_run_id, note FROM episodic_memory_clears ORDER BY id")
    ).all()
    session_ids = []
    prev_end = None
    last_after = ""
    for _cid, at, after_run, note in clears:
        before, last_after = _split_note(note or "")
        sid = conn.execute(
            text(
                "INSERT INTO training_sessions (started_at, ended_at, note) "
                "VALUES (:s, CAST(:e AS timestamptz) AT TIME ZONE 'UTC', :n) RETURNING id"
            ),
            {"s": prev_end, "e": at, "n": before},
        ).scalar()
        session_ids.append((sid, after_run))
        prev_end = at.astimezone(timezone.utc).replace(tzinfo=None)
    open_note = last_after if clears else ""
    open_id = conn.execute(
        text(
            "INSERT INTO training_sessions (started_at, ended_at, note) "
            "VALUES (:s, NULL, :n) RETURNING id"
        ),
        {"s": prev_end, "n": open_note},
    ).scalar()
    # Runs: first session whose clear lies at or after the run, else the open session.
    for sid, after in session_ids:
        if after is None:
            continue
        conn.execute(
            text("UPDATE runs SET session_id = :sid WHERE session_id IS NULL AND id <= :a"),
            {"sid": sid, "a": after},
        )
    conn.execute(
        text("UPDATE runs SET session_id = :sid WHERE session_id IS NULL"), {"sid": open_id}
    )
    conn.execute(text("DROP TABLE episodic_memory_clears"))
    return {"sessions": len(session_ids) + 1}
