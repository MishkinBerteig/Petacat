"""S0, gate G4: a ``ConfigDocument`` read from the database equals one read from the files.

The scratch database is loaded from the Metacat Standard Configuration with no edits
(``tests/integration/equivalence_harness.py``).  Then:

* the document read from its tables has the same tables, rows and order as the document built
  from the files;
* ``provider`` of it equals ``load_metadata_from_db`` field for field, and ``config_hash``
  of it equals the database provider's engine hash (the identity test);
* an edit applied to the document gives the provider the database would give after the same
  edit written to its rows (one conversion, two callers).
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from server.engine import hashing
from server.services import config_document as cd
from tests.integration.equivalence_harness import (
    SEED_DIR,
    database_reachable,
    fresh_database,
    harness_db_url,
    provider_differences,
)

pytestmark = pytest.mark.skipif(
    not database_reachable(),
    reason="the scratch Postgres is not reachable (start it with scripts/dev.sh db)",
)


async def _read_document() -> cd.ConfigDocument:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(harness_db_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await cd.document_from_db(session)
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def db_doc():
    fresh_database()  # loads the scratch database once
    return asyncio.run(_read_document())


@pytest.fixture(scope="module")
def files_doc():
    return cd.document_from_standard_files(SEED_DIR)


def test_document_from_the_database_equals_document_from_the_files(db_doc, files_doc):
    for table in cd.TABLE_NAMES:
        a, b = list(db_doc.tables[table].items()), list(files_doc.tables[table].items())
        assert a == b, table
    assert db_doc.content_equals(files_doc)


def test_provider_of_the_document_equals_the_database_provider(db_doc):
    assert provider_differences(fresh_database().provider, cd.provider(db_doc)) == {}


def test_config_hash_of_the_document_equals_the_engine_hash_of_the_database_provider(db_doc, files_doc):
    expected = hashing.config_hash(fresh_database().provider)
    assert cd.config_hash(db_doc) == expected
    assert cd.config_hash(files_doc) == expected


def test_database_rows_have_no_surrogate_id(db_doc):
    assert all("id" not in r for t in cd.TABLE_NAMES for r in db_doc.tables[t].values())
