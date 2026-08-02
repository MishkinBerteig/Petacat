"""The runner's status constants."""

from server.engine.runner import (
    STATUS_ANSWER_FOUND,
    STATUS_GAVE_UP,
    STATUS_HALTED,
    STATUS_INITIALIZED,
    STATUS_PAUSED,
    STATUS_RUNNING,
)


def test_status_constants_are_strings():
    assert isinstance(STATUS_INITIALIZED, str)
    assert isinstance(STATUS_RUNNING, str)
    assert isinstance(STATUS_PAUSED, str)
    assert isinstance(STATUS_ANSWER_FOUND, str)
    assert isinstance(STATUS_HALTED, str)
    assert isinstance(STATUS_GAVE_UP, str)
