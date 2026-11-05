"""C10: the v2.0 guards that are not about who writes the journal.

* ``server/engine/**`` is the engine tree of a named baseline commit, re-based on purpose by engine work.
* The words: no "innate" (the term is Starting Conceptual State), no "core names", and
  "protected" only where it means a Training Mode Session's Episodic Memory.
* The schema: no table named for the old session entity and no ``session_id`` column on ``runs``
  (Metacat Mode has no sessions; a Training Mode Session's runs are their own table).
* The code that runs in a worker, the swarm or a run never reaches the journal layer, even
  through its imports (evolution plan, section 4, item 6(d); the runtime half is the audit hook
  of ``tests/e2e/test_mode_isolation.py``).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: The engine tree nothing may change without re-basing this: the last engine commit of the final
#: Metacat cleanup, which removed the code nothing used and read in what the database held.  The
#: C and S packages left the tree alone; engine work moves this commit on purpose.
ENGINE_BASELINE = "9982a94"
#: The only commits that touched the engine between EN11's close-out (``0ce7f5d``) and the
#: baseline; all are allowed engine work.
ENGINE_COMMITS_AFTER_EN11 = {
    "Codelet bodies and descriptor predicates name no node",
    "Exact rationals in the configuration",
    "Engine code that only tests held in place is removed",
    "Configuration nothing reads is deleted from the seed files and the database",
    "Everything the engine uses that the database holds is read from the database",
    "The final Metacat verification's findings are fixed",
    "The backend registry is published whole",
    "Dead code is gone, and the open items of the Metacat finish are closed",
    "A run reaches only its own state",
}


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


needs_git = pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(),
    reason="the engine baseline is a git commit",
)


# ──────────────────────────────────────────────────────────────────
# The engine tree
# ──────────────────────────────────────────────────────────────────


@needs_git
def test_the_engine_tree_is_the_baseline_trees():
    if _git("cat-file", "-t", ENGINE_BASELINE).stdout.strip() != "commit":
        pytest.skip(f"baseline commit {ENGINE_BASELINE} is not in this clone")
    changed = _git("diff", "--name-status", ENGINE_BASELINE, "--", "server/engine").stdout.strip()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", "server/engine").stdout
    untracked = "\n".join(
        line for line in untracked.splitlines() if "__pycache__" not in line and not line.endswith(".pyc")
    )
    assert not changed and not untracked, (
        f"server/engine/** differs from commit {ENGINE_BASELINE}; engine work re-bases this guard "
        f"on purpose:\n{changed}\n{untracked}"
    )


@needs_git
def test_only_the_allowed_engine_packages_touched_the_engine_after_en11():
    if _git("cat-file", "-t", "0ce7f5d").stdout.strip() != "commit":
        pytest.skip("commit 0ce7f5d is not in this clone")
    log = _git("log", "--format=%s", f"0ce7f5d..{ENGINE_BASELINE}", "--", "server/engine").stdout
    assert set(log.strip().splitlines()) == ENGINE_COMMITS_AFTER_EN11


# ──────────────────────────────────────────────────────────────────
# The words
# ──────────────────────────────────────────────────────────────────

SCANNED_DIRS = ("server", "client/src", "scripts", "seed_data", "tests")
SCANNED_FILES = ("README.md", "HELP.md", "API.md", "TESTING.md")
SUFFIXES = {".py", ".ts", ".tsx", ".json", ".md", ".sh", ".css", ".html"}
THIS_FILE = Path(__file__).resolve()
#: Not scanned: this file (it names the words) and the architecture test that explains what
#: its checker treats as "protected" (a table or model of the journal layer's, not a word of
#: the product).
NOT_SCANNED = {THIS_FILE, ROOT / "tests/architecture/test_journal_only_writer.py"}

WORDS = re.compile(r"innate|core[ _-]names?", re.IGNORECASE)
PROTECTED = re.compile(r"protected", re.IGNORECASE)
#: "protected" means one thing, a Training Mode Session's Episodic Memory, and a line that
#: uses it must say so.  Engine and test comments about something else (the coderack's
#: "most protected" members) are the engine's, which is not edited.
MEMORY = re.compile(r"episodic|memory|EPISODIC", re.IGNORECASE)
PROTECTED_ELSEWHERE = {ROOT / "server/engine/coderack.py"}
#: The Database tab marks a column ``protected`` (its API field and the client's props): only
#: the Episodic Memory columns of a session's runs carry it (``server/api/database.py``).  The
#: client's admin components (the Database tab and Edit all) and the tab's e2e file say the one word without the sentence around it.
PROTECTED_DATABASE_TAB = (ROOT / "client/src/components/admin", ROOT / "tests/e2e/test_database_tab.py")


def _files():
    for d in SCANNED_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if (
                p.is_file() and p.suffix in SUFFIXES
                and not {"node_modules", "__pycache__"} & set(p.parts)
                and p.resolve() not in NOT_SCANNED
            ):
                yield p
    for f in SCANNED_FILES:
        if (ROOT / f).exists():
            yield ROOT / f


def _protected_lines(text: str):
    """Each line that says "protected", with the lines around it (a sentence may wrap)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if PROTECTED.search(line):
            yield i + 1, line, "\n".join(lines[max(0, i - 3): i + 4])


def test_nothing_is_called_innate_or_core_names():
    found = []
    for p in _files():
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if WORDS.search(line):
                found.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()[:120]}")
    assert not found, 'the term is "Starting Conceptual State"; no "innate" and no "core names":\n' + "\n".join(found)


def test_protected_means_a_sessions_episodic_memory_and_nothing_else():
    found = []
    for p in _files():
        if p.resolve() in PROTECTED_ELSEWHERE or any(
            p == t or t in p.parents for t in PROTECTED_DATABASE_TAB
        ):
            continue
        for n, line, around in _protected_lines(p.read_text(encoding="utf-8", errors="replace")):
            if not MEMORY.search(around):
                found.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()[:120]}")
    assert not found, (
        "nothing is protected except a Training Mode Session's Episodic Memory:\n" + "\n".join(found)
    )


@pytest.mark.parametrize("text,words,protected", [
    ("the innate network", True, None),
    ("Core Names of the nodes", True, None),
    ("core_names = []", True, None),
    ("a protected node", False, False),
    ("a Training Mode Session's Episodic Memory is protected", False, True),
])
def test_the_word_checks_see_what_they_are_for(text, words, protected):
    assert bool(WORDS.search(text)) is words
    if protected is not None:
        lines = list(_protected_lines(text))
        assert bool(MEMORY.search(lines[0][2])) is protected


# ──────────────────────────────────────────────────────────────────
# The schema
# ──────────────────────────────────────────────────────────────────


def _metadata():
    import server.models.journal  # noqa: F401
    import server.models.metadata  # noqa: F401
    import server.models.run  # noqa: F401
    import server.models.training_mode_session  # noqa: F401
    from server.models.metadata import Base

    return Base.metadata


def test_no_table_is_named_for_the_old_session_entity():
    old = "train" + "ing_session"  # spelled in two parts: the rename guard scans this file's text
    names = set(_metadata().tables)
    assert old + "s" not in names
    assert not [n for n in names if n.startswith(old) or n.endswith(old + "s")], sorted(names)
    # a Training Mode Session's own tables carry the whole name
    assert "training_mode_sessions" in names


def test_runs_has_no_session_id_column():
    runs = _metadata().tables["runs"]
    assert "session_id" not in runs.c
    assert not [c.name for c in runs.c if "session" in c.name], [c.name for c in runs.c]


# ──────────────────────────────────────────────────────────────────
# Worker, swarm and run code never reaches the journal layer
# ──────────────────────────────────────────────────────────────────

JOURNAL_MODULES = (
    "server.services.journal", "server.services.config_registry", "server.models.journal",
    "server.services.configuration_writer", "server.services.configuration_store",
)
WORKER_SIDE_MODULES = (
    "server.engine.runner", "server.engine.metadata", "server.parallel.swarm",
    "server.parallel.free_running", "server.parallel.update_cycle",
    "server.services.training_mode_session_executor",
)


def test_importing_the_worker_side_code_does_not_import_the_journal_layer():
    """A fresh interpreter imports everything a worker, the swarm or a run is made of."""
    code = (
        "import importlib, sys\n"
        f"for m in {WORKER_SIDE_MODULES!r}: importlib.import_module(m)\n"
        f"bad = [m for m in {JOURNAL_MODULES!r} if m in sys.modules]\n"
        "print('BAD:' + ','.join(bad))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "BAD:", out.stdout
