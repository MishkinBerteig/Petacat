"""Helpers for the tests of multi-turn runs (chats): an in-process executor and a scripted teacher."""

from __future__ import annotations

from concurrent.futures import Future
from typing import Any

from server.engine.start_check import require_run_start
from server.services.training_mode_session_executor import run_task


class InProcessExecutor:
    """The third route a run can take: ``run_task`` in the service's own process, one task at a time.

    The same interface as ``SerialExecutor`` and ``SwarmExecutor`` (``submit``, ``workers``, ``in_flight``,
    ``kind``, ``close``), so a service built on it runs sessions exactly as the other two do."""

    kind = "in-process"
    workers = 1

    def __init__(self) -> None:
        self.in_flight = 0

    def submit(self, tasks: list, meta: Any) -> Future:
        require_run_start(meta)
        future: Future = Future()
        future.set_result([run_task(task, meta) for task in tasks])
        return future

    def close(self) -> None:
        pass


def series_teacher(series: dict[str, list[str]], label: str = "series over", log: list | None = None):
    """A teacher that supplies, per problem (keyed by its ``initial``), the inputs of turns 2, 3, ... and
    then ends the run with *label*.  Every call it is given is appended to *log* when one is passed."""

    def teacher(conversation: dict) -> Any:
        if log is not None:
            log.append((conversation["problem_id"], conversation["seed"], conversation["waiting_for"]))
        inputs = series.get(conversation["problem"]["initial"], [])
        index = conversation["waiting_for"] - 2
        return inputs[index] if index < len(inputs) else {"end": True, "label": label}

    return teacher


def conversation_key(conversation: dict) -> list:
    """What must be identical between two executors for one run: every turn's positions, status, codelets,
    seed, proposals and evidence (never the timing), and how the run ended."""
    return [
        conversation["seed"], conversation["state"], conversation["end_reason"], conversation["end_label"],
        [
            (t["turn"], t["positions"], t["supplied_by"], t["status"], t["codelets"], t["turn_seed"],
             t["answers"], t["answer_quality"], t["end_reason"], t["end_label"], t["proposals"], t["evidence"])
            for t in conversation["turns"]
        ],
    ]


class ScriptedExecutor:
    """An executor whose outcomes are a function of the task, so a chat's mechanism can be tested without the
    engine's cognition deciding whether a turn answers.

    A task answers ``<input>!`` (and proposes a node named for the input, so a turn builds structure the next
    turn is dispatched under).  An input of ``NOANSWER`` gives up, and ``BOOM`` raises inside the run.  With
    ``hold`` set the futures are not resolved until :meth:`finish` (the session then has a turn in flight)."""

    kind = "scripted"
    workers = 1

    def __init__(self, hold: bool = False) -> None:
        self.hold = hold
        self.calls: list[tuple[Any, Any, Future]] = []

    @property
    def in_flight(self) -> int:
        return sum(1 for *_, f in self.calls if not f.done())

    @staticmethod
    def node(name: str) -> dict:
        return {"op": "add_node", "name": f"plato-chat-{name}",
                "fields": {"short_name": name, "glyph": name, "plain_name": name,
                           "article_an": False, "conceptual_depth": 10, "description": "scripted"}}

    @staticmethod
    def outcome(task) -> Any:
        from server.services.training_mode_session_executor import SessionOutcome

        if task.target == "BOOM":
            return SessionOutcome(seed=task.seed, status="error", answer="", answers=[], codelets=0, seconds=0.0,
                                  stopping_state="error:", error="scripted failure")
        if task.target == "NOANSWER":
            return SessionOutcome(seed=task.seed, status="gave_up", answer="", answers=[], codelets=7, seconds=0.0,
                                  stopping_state="gave_up:", temperature=5.0, proposals=[ScriptedExecutor.node("NOANSWER")])
        answer = f"{task.target}!"
        node = ScriptedExecutor.node(task.target)
        return SessionOutcome(
            seed=task.seed, status="answer_found", answer=answer, answers=[answer], codelets=10 + len(task.initial),
            seconds=0.0, stopping_state=f"answer_found:{answer}", temperature=1.0, answer_quality=50.0,
            proposals=[node], evidence={"bonds": {}, "groups": {}, "rule": None, "snags": [], "unperceived": 0,
                                          "coderack": {"full_posts": 0, "overflowing_batches": 0, "evicted": 0}})

    def submit(self, tasks: list, meta: Any) -> Future:
        future: Future = Future()
        self.calls.append((tasks[0], meta, future))
        if not self.hold:
            future.set_result([self.outcome(t) for t in tasks])
        return future

    def finish(self, index: int) -> None:
        task, _meta, future = self.calls[index]
        future.set_result([self.outcome(task)])

    def close(self) -> None:
        pass
