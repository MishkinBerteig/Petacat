"""The turns of a Training Mode Session's multi-turn run: the window, the turn seed and the turn's evidence.

**Training Mode only.**  Nothing in Metacat Mode reads this module.  It is pure: no database, no engine
state, nothing global, so a worker, the swarm, the serial child and the service all call the same functions
and agree.

A multi-turn run is a chat (plan section 4.4).  A **turn** is one engine run, a pure function of the session's
configuration at dispatch, its Episodic Memory at dispatch, the turn's four positions (its context, its
second string, its input, and the response Petacat constructs), the run's seed and the turn number.

The window
----------
Turn 1's positions are the problem's ``(initial, modified, target)``.  When a turn answers and the run's
next input arrives, the next turn's positions are

* context = the turn's context, second string and input, joined with single spaces (U+0020),
* second string = the turn's response,
* input = the new input.

So ``one:two::1:?`` answered ``2`` and then given ``3`` becomes ``one two 1:2::3:?``.  The space is a symbol like
any other in a Training Mode Session: perception gives it a node of its own (``novel-string-scout`` and
``node-instantiator``) and nothing treats it as a boundary.  No string is trimmed, normalised or cut: the
joined strings reach the Workspace exactly.

The turn seed
-------------
Turn 1 runs with the run's own seed, so a single-turn problem is bit-identical to a run before turns existed.
Turn ``n >= 2`` runs with ``turn_seed(seed, n)``: the first eight bytes of ``SHA-256`` over the text
``petacat-turn:<seed>:<n>``, read as a big-endian unsigned integer and cut to its low 63 bits (so it fits the
database's ``bigint``).  It is a pure function of ``(seed, n)``, is the same in every process, and gives turns of
one run, and turns of different runs, unrelated random streams.

The evidence
------------
:func:`gather_evidence` summarises what a turn's Workspace built, as plain data: the bonds and groups formed
(counts by category), the rule the turn's answer used, the snags the turn recorded, and how many symbols were
still unperceived at the end, and the Coderack's pressure over the run: codelets posted while it was full,
deferred batches that took it past its size, and codelets evicted to make room (counted by the Coderack, read
here and never used by the engine).  A turn blocked on perception (symbols with no node, so nothing to build on)
can be told apart from a cognitive give-up.
"""

from __future__ import annotations

import hashlib
from typing import Any

#: Why a run ended (the ``end_reason`` of its last turn).  ``answered`` is never a reason: a turn that
#: answers does not end a multi-turn run, the teacher does.
END_SINGLE_TURN = "single-turn"
END_NO_ANSWER = "no-answer"
END_TEACHER = "teacher"
END_ERROR = "error"
END_CANCELLED = "cancelled"
END_REASONS = (END_SINGLE_TURN, END_NO_ANSWER, END_TEACHER, END_ERROR, END_CANCELLED)

#: Who supplied a turn's input.
FROM_PROBLEM = "problem"
FROM_TEACHER = "teacher"


def turn_seed(seed: int, turn: int) -> int:
    """The seed turn *turn* of the run with seed *seed* runs under (turn 1 runs with *seed* itself)."""
    if turn <= 1:
        return seed
    digest = hashlib.sha256(f"petacat-turn:{seed}:{turn}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def next_window(context: str, second: str, input_text: str, response: str, next_input: str) -> tuple[str, str, str]:
    """The next turn's ``(context, second string, input)`` from a turn that answered *response*."""
    return f"{context} {second} {input_text}", response, next_input


def gather_evidence(ctx: Any, base_answers: int, base_snags: int) -> dict[str, Any] | None:
    """What this run's Workspace built, as plain data (``None`` when there is no run context).

    Called after a Training Mode Session's run ends, by ``swarm.run_one`` and the session executor's
    ``run_task``; Metacat Mode's runs never call it.  *base_answers* and *base_snags* are how many answers and
    snags the run's Episodic Memory copy held when the run began, so only what this turn added is reported.
    """
    if ctx is None:
        return None
    from server.engine.workspace_objects import Letter

    workspace = ctx.workspace
    bonds: dict[str, int] = {}
    groups: dict[str, int] = {}
    for string in workspace.aggregate_strings:
        for bond in string.bonds:
            name = bond.bond_category.name
            bonds[name] = bonds.get(name, 0) + 1
        for group in string.groups:
            name = group.group_category.name
            groups[name] = groups.get(name, 0) + 1
    dimension = ctx.slipnet.roles.dimension_letter_category
    unperceived = sum(
        isinstance(obj, Letter) and obj.get_descriptor_for(dimension) is None
        for obj in (workspace.all_objects if dimension else ())
    )
    coderack = ctx.coderack
    memory = ctx.memory
    new_answers = len(memory.answers) - base_answers
    rule = None
    if new_answers > 0:  # newest first: the answer this turn reported last
        newest = memory.answers[0]
        rule = {"top_rule": newest.top_rule_description, "bottom_rule": newest.bottom_rule_description}
    new_snags = max(len(memory.snags) - base_snags, 0)
    return {
        "bonds": dict(sorted(bonds.items())),
        "groups": dict(sorted(groups.items())),
        "rule": rule,
        "snags": [s.explanation for s in memory.snags[:new_snags]],
        "unperceived": unperceived,
        "coderack": {
            "full_posts": coderack.full_posts,
            "overflowing_batches": coderack.overflowing_batches,
            "evicted": coderack.evicted,
        },
    }
