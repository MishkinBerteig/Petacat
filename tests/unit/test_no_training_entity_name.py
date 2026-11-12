"""S12: the rename guard.  "Training" names nothing but the mode and the Training episode.

A Training Mode Session is "a Training Mode Session" (or "session" where obvious) in code, UI
strings, help topics and docs.  After the allowed phrases below are removed, the word "training"
must not remain in any scanned file.

Allowed: "Training Mode" (and ``training_mode``, ``training-mode``, ``TRAINING_MODE_SOURCES``,
``TrainingMode``), "Training episode", the v2.0 Base's names (``training_base/``, ``training_base.py``
and the ``configuration_base`` value ``training-v2``), the table ``training_memory_merges`` (S5 kept it as
the session's Episodic Memory record, written at Stop), "corpus training" (Phase 4's
corpus-mode training), "training population" (a Fast population of runs) and "LLM training text"
(the corpora Training Mode is meant to learn from, in the project's own definition).

Not scanned, because they record the past or quote the old names: ``PHASE * PLAN.md``,
``FUTURE_DIRECTION*.md``, ``SELF_WATCHING_AUDIT.md``, ``CLAUDE.md``
(which quotes the old name when it defines the new one), ``academic/``,
``Metacat/`` and ``agents-workspace/`` (except the
API contract), ``node_modules`` and this file.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCANNED_DIRS = ("server", "client/src", "tests", "scripts", "seed_data")
SCANNED_FILES = (
    "README.md", "HELP.md", "API.md", "TESTING.md", "agents-workspace/batch-ui/API-CONTRACT.md",
)
SUFFIXES = {".py", ".ts", ".tsx", ".json", ".md", ".sh", ".css", ".html"}

ALLOWED = re.compile(
    r"Training[ -][Mm]ode|training[ -]mode|training_mode|TRAINING_MODE|TrainingMode|trainingMode"
    r"|[Tt]raining episodes?|training_memory_merges|[Cc]orpus[ -]training|training\s+(?:#\s*)?population"
    r"|pre-training|test_no_training_entity_name|LLM training text"
    r"|training_base|training-v2"
)
FORBIDDEN = re.compile(r"training", re.IGNORECASE)


def _files():
    for d in SCANNED_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if (
                p.is_file()
                and p.suffix in SUFFIXES
                and "node_modules" not in p.parts
                and "__pycache__" not in p.parts
                and p.resolve() != Path(__file__).resolve()
            ):
                yield p
    for f in SCANNED_FILES:
        yield ROOT / f


def test_training_names_no_entity_anywhere():
    found = []
    for p in _files():
        text = p.read_text(encoding="utf-8", errors="replace")
        # Blank the allowed phrases (keeping offsets), then look for what is left.
        rest = ALLOWED.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
        for m in FORBIDDEN.finditer(rest):
            n = text.count("\n", 0, m.start()) + 1
            found.append(f"{p.relative_to(ROOT)}:{n}: {text.splitlines()[n - 1].strip()[:120]}")
    assert not found, "an entity is still called 'Training':\n" + "\n".join(found[:40])


def test_the_old_modules_routes_and_tables_are_gone():
    for gone in (
        "server/models/training.py",
        "server/services/training_service.py",
        "server/services/training_executor.py",
        "server/services/training_memory.py",
        "server/api/trainings.py",
        "server/services/episodic_clears_migration.py",
        "client/src/components/training",
    ):
        assert not (ROOT / gone).exists(), gone
