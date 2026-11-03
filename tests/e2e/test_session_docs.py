"""E2E (S6): the documentation for the Training Mode Session routes: ``API.md`` lists every route of
the router, the help topics for the external route and the learning sources are served, and
the words learn, learner and episode are qualified by mode in the topics this package wrote.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SESSION_ROUTES = [
    ("POST", "/api/training-mode/sessions/{session_id}/changes"),
    ("GET", "/api/training-mode/sessions/{session_id}/journal"),
    ("GET", "/api/training-mode/sessions/{session_id}/configuration"),
    ("GET", "/api/training-mode/sessions/{session_id}/configuration/diff"),
    ("GET", "/api/training-mode/sessions/{session_id}/slipnet"),
    ("GET", "/api/training-mode/sessions/{session_id}/export"),
    ("POST", "/api/training-mode/sessions/{session_id}/start"),
    ("POST", "/api/training-mode/sessions/{session_id}/pause"),
    ("POST", "/api/training-mode/sessions/{session_id}/resume"),
    ("POST", "/api/training-mode/sessions/{session_id}/stop"),
    ("POST", "/api/training-mode/sessions/{session_id}/cancel"),
]


def test_api_md_is_in_sync_and_lists_every_session_route():
    done = subprocess.run([sys.executable, str(ROOT / "scripts/generate_api_docs.py"), "--check"],
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    text = (ROOT / "API.md").read_text()
    for method, path in SESSION_ROUTES:
        assert f"| `{method}` | `{path}` |" in text, (method, path)
    assert "/api/" + "train" + "ings" not in text  # the old route names are gone (no aliases)


def test_the_contract_lists_every_session_route():
    contract = (ROOT / "agents-workspace/batch-ui/API-CONTRACT.md").read_text()
    for _method, path in SESSION_ROUTES:
        short = path.replace("{session_id}", "{id}")
        assert short in contract or short.rsplit("/", 1)[0] + "/" in contract, short
    for fragment in ("/changes", "/journal", "/configuration/diff", "/slipnet", "what` = `problems`"):
        assert fragment in contract, fragment


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["session_external_route", "session_learning_sources", "session_export"])
async def test_the_session_help_topics_are_served(app_client, key):
    resp = await app_client.get(f"/api/docs/components/{key}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["topic_key"] == key


QUALIFIERS = ("Training-Mode ", "Metacat-Mode ", "in-worker ")
EPISODE_QUALIFIERS = ("Train" + "ing ", "Metacat's ")


def test_help_uses_learn_learner_and_episode_only_when_qualified_by_mode():
    import json

    topics = {t["topic_key"]: t for t in json.loads((ROOT / "seed_data/help_topics.en.json").read_text())}
    for key in ("session_external_route", "session_learning_sources", "session_export"):
        topic = topics[key]
        text = " ".join([topic["title"], topic["short_desc"], topic["full_desc"]])
        for m in re.finditer(r"\b(learning|learner|learn|learned|episode)\b", text, re.I):
            before, word = text[:m.start()], m.group(1).lower()
            allowed = EPISODE_QUALIFIERS if word == "episode" else QUALIFIERS
            quoted = before.endswith("'")  # the glossary line that names the word itself
            assert before.endswith(allowed) or quoted, (key, text[max(0, m.start() - 40):m.end() + 20])
