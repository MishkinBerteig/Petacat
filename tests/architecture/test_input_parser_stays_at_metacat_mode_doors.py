"""Metacat's input parser is Metacat Mode's alone (``THE-THREE-SYSTEMS.md``).

Only the three Metacat Mode doors import ``server.services.input_parser``: ``RunService.create_run``
(``run_service.py``), ``POST /api/swarm`` (``api/swarm.py``) and the Admin view's demo problems and
parser tables (``api/admin.py``).  Nothing of Training Mode, no other service and nothing under
``server/engine/`` or ``server/parallel/`` reads the parser or the rows it reads (``input_character_ranges``,
``input_lowering_ranges``, ``largest_seed``), so a session cannot depend on Metacat Mode's perception.
"""

from __future__ import annotations

import re
from pathlib import Path

SERVER = Path(__file__).resolve().parents[2] / "server"

#: The files that may import the parser.
DOORS = {"services/run_service.py", "api/swarm.py", "api/admin.py"}

#: The files that may mention the parser's configuration besides the doors: the parser, and the
#: places that carry every table of the configuration whichever mode reads it.
CARRIERS = {
    "services/input_parser.py", "engine/metadata.py", "engine/start_check.py", "models/metadata.py",
    "services/metadata_service.py", "services/config_document.py", "services/config_registry.py",
    "services/standard_configuration.py", "api/admin.py",
}


def _files():
    for path in sorted(SERVER.rglob("*.py")):
        yield path.relative_to(SERVER).as_posix(), path.read_text()


def test_only_the_metacat_mode_doors_import_the_parser():
    importers = {rel for rel, text in _files() if re.search(r"services\.input_parser", text) and rel != "services/input_parser.py"}
    assert importers == DOORS, importers ^ DOORS


def test_nothing_else_reads_the_parsers_configuration():
    pattern = re.compile(r"input_character_ranges|input_lowering_ranges|largest_seed")
    readers = {rel for rel, text in _files() if pattern.search(text)}
    assert readers <= DOORS | CARRIERS, sorted(readers - (DOORS | CARRIERS))
    for rel in readers:
        assert not rel.startswith(("services/training_mode", "parallel/")), rel
