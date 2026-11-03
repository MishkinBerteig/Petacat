"""Every Training Mode Session has an Episodic Memory (S11): the schema, the service and the router carry no
trace of ``memory: "independent"``, no ``closed`` or ``cancelled`` state, and no route clears
the memory.  No database is needed: these read the models, the routes and the service source."""

import inspect
import re

from server.api.training_mode_sessions import CreateSessionRequest, router
from server.models import training_mode_session as models
from server.services import training_mode_session_service as service


def test_the_schema_has_no_memory_mode_and_no_nullable_episode_columns():
    t = models.TrainingModeSession.__table__
    assert "memory" not in t.c and "status" not in t.c and "closed_at" not in t.c
    assert {"stopped_at", "stopped_from", "stop_reason"} <= set(t.c.keys())
    names = {c.name for c in t.constraints if c.name}
    assert "ck_training_mode_sessions_memory" not in names and "ck_training_mode_sessions_status" not in names
    r = models.TrainingModeSessionRun.__table__.c
    for column in ("seq", "memory_version", "added_answers", "added_snags"):
        assert not r[column].nullable, column
    assert not hasattr(models, "MEMORY_MODES") and not hasattr(models, "SESSION_STATUSES")


def test_the_service_has_no_shared_branch_and_no_closed_or_cancelled_state():
    source = inspect.getsource(service)
    assert not re.search(r"\blt\.shared\b|\.shared\b|memory_mode|independent", source)
    assert not hasattr(service.LiveSession, "shared")
    assert not hasattr(service.TrainingModeSessionService, "close")
    live = service.LiveSession.__dataclass_fields__
    assert "closed" not in live and "memory_mode" not in live


def test_no_route_clears_the_memory_and_close_is_gone():
    routes = [(r.path, m) for r in router.routes for m in r.methods]
    for path, method in routes:
        if "memory" in path:
            assert method == "GET", (path, method)
    assert not any(path.endswith("/close") for path, _ in routes)
    assert ("/api/training-mode/sessions/{session_id}/stop", "POST") in routes
    assert ("/api/training-mode/sessions/{session_id}/start", "POST") in routes


def test_a_request_that_sends_memory_is_refused():
    assert CreateSessionRequest.model_config["extra"] == "forbid"
    assert "memory" not in CreateSessionRequest.model_fields
    assert "memory" not in service._SETTINGS_KEYS
