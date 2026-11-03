"""Every Training has an Episodic Memory (S11): the schema, the service and the router carry no
trace of ``memory: "independent"``, no ``closed`` or ``cancelled`` state, and no route clears
the memory.  No database is needed: these read the models, the routes and the service source."""

import inspect
import re

from server.api.trainings import CreateTrainingRequest, router
from server.models import training as models
from server.services import training_service as service


def test_the_schema_has_no_memory_mode_and_no_nullable_episode_columns():
    t = models.Training.__table__
    assert "memory" not in t.c and "status" not in t.c and "closed_at" not in t.c
    assert {"stopped_at", "stopped_from", "stop_reason"} <= set(t.c.keys())
    names = {c.name for c in t.constraints if c.name}
    assert "ck_trainings_memory" not in names and "ck_trainings_status" not in names
    r = models.TrainingRun.__table__.c
    for column in ("seq", "memory_version", "added_answers", "added_snags"):
        assert not r[column].nullable, column
    assert not hasattr(models, "MEMORY_MODES") and not hasattr(models, "TRAINING_STATUSES")


def test_the_service_has_no_shared_branch_and_no_closed_or_cancelled_state():
    source = inspect.getsource(service)
    assert not re.search(r"\blt\.shared\b|\.shared\b|memory_mode|independent", source)
    assert not hasattr(service.LiveTraining, "shared")
    assert not hasattr(service.TrainingService, "close")
    live = service.LiveTraining.__dataclass_fields__
    assert "closed" not in live and "memory_mode" not in live


def test_no_route_clears_the_memory_and_close_is_gone():
    routes = [(r.path, m) for r in router.routes for m in r.methods]
    for path, method in routes:
        if "memory" in path:
            assert method == "GET", (path, method)
    assert not any(path.endswith("/close") for path, _ in routes)
    assert ("/api/trainings/{training_id}/stop", "POST") in routes
    assert ("/api/trainings/{training_id}/start", "POST") in routes


def test_a_request_that_sends_memory_is_refused():
    assert CreateTrainingRequest.model_config["extra"] == "forbid"
    assert "memory" not in CreateTrainingRequest.model_fields
    assert "memory" not in service._SETTINGS_KEYS
