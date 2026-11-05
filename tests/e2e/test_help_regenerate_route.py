"""E2E test: POST /api/admin/help/regenerate syncs the help_topics rows and commits them.

The route was importing a name that had left ``server/main.py``, so it raised ImportError
before doing anything, and nothing exercised it. ``regenerate_all`` is patched so the test
does not rewrite HELP.md or helpTopics.ts in the working tree; the database half is real,
and the row is read back in a separate session to prove the sync was committed.
"""

import json
import os
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.models.metadata import HelpTopic
from server.services.help_docs import RegenerateResult


@pytest.mark.asyncio
async def test_regenerate_route_restores_a_changed_help_topic_row(app_client, test_engine):
    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    with open(os.path.join(seed_dir, "help_topics.en.json")) as f:
        topic = json.load(f)[0]
    key, title = topic["topic_key"], topic["title"]

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        row = (await s.execute(select(HelpTopic).where(HelpTopic.topic_key == key))).scalar_one()
        row.title = "changed by the test"
        await s.commit()

    fake = RegenerateResult(1, 1, 0, False, False, "HELP.md", "client/src/constants/helpTopics.ts")
    with patch("server.services.help_docs.regenerate_all", return_value=fake):
        resp = await app_client.post("/api/admin/help/regenerate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["db_synced"] is True

    async with factory() as s:
        row = (await s.execute(select(HelpTopic).where(HelpTopic.topic_key == key))).scalar_one()
        assert row.title == title
