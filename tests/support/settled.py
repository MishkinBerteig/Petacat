"""Wait for the in-flight counts of a swarm and its executors to settle.

``Swarm.submit`` and the executors of ``training_mode_session_executor`` lower their in-flight
counts (``inflight_jobs``, ``in_flight``) in a future's done-callback, which ``concurrent.futures``
runs just AFTER it wakes whoever waits on ``result()``.  The instant the last ``result()`` returns,
the last job may therefore still count as in flight.  A test that asserts a count of 0 straight
after ``result()`` races that callback; it waits with this instead.  A count that never settles
still fails, at the deadline.
"""

from __future__ import annotations

import time


def counts(swarm=None, *executors) -> dict[str, int]:
    """The in-flight counts named by their source: the swarm's jobs and each executor's tasks."""
    out: dict[str, int] = {}
    if swarm is not None:
        out["swarm.inflight_jobs"] = swarm.status()["inflight_jobs"]
    for i, ex in enumerate(executors):
        out[f"executor[{i}].in_flight"] = ex.in_flight
    return out


def wait_until_settled(swarm=None, *executors, seconds: float = 30.0) -> None:
    """Wait, up to *seconds*, until every count is 0, then assert each is 0."""
    deadline = time.monotonic() + seconds
    while any(counts(swarm, *executors).values()) and time.monotonic() < deadline:
        time.sleep(0.005)
    now = counts(swarm, *executors)
    assert not any(now.values()), f"counts did not settle to 0 within {seconds}s: {now}"
