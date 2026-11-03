"""C6: the journal layer is the only writer of configuration (configuration plan 3.11, R21, R34).

There are no database triggers.  What takes their place is the layer being the only writer
and this test: an AST walk over ``server/**`` that finds any statement outside the layer's
module writing a configuration table or a journal table.  The table list is computed by model
introspection (``server/services/config_registry.py``), so a table added to the models is
covered the day it is added.

What it detects, in every module but the layer:

* a SQLAlchemy ``insert`` / ``update`` / ``delete`` (also through ``Model.__table__``) that
  names a protected model, table object or table-name string;
* ``add`` / ``add_all`` / ``delete`` / ``merge`` of a protected model's instance, and
  ``setattr`` or an attribute assignment on one (the unit of work would write it): an instance
  is a name bound in the same function from an expression that names a protected model;
* raw SQL strings (``INSERT INTO``, ``UPDATE``, ``DELETE FROM``, ``TRUNCATE``) naming a
  protected table.

It does not see an instance that reaches a function only as a parameter, or a table name
built at run time; the layer's own tests and ``verify_journal`` cover what an AST cannot.  A
write made outside the application (raw ``psql``) is not prevented: ``verify_journal``
detects it.

The two doors are named here: ``write_immediate`` (any route; never from the engine, a
worker or the swarm) and ``write_deferred`` (a session's Stop write only; the allowlist is
empty until S5 adds it).  The layer has no update or delete of a journal entry.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from server.models.journal import Configuration, ConfigurationSnapshot, JournalEntry
from server.services import config_registry

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"

#: The layer's module: the one place allowed to write.
LAYER = "services/journal.py"
#: The model definitions (they declare the tables and the append-only refusal; no writes).
MODEL_FILES = {"models/journal.py", "models/metadata.py"}

#: Where ``write_deferred`` may be called: a session's Stop write.  Empty until S5 (the Stop
#: write); each entry is ``(file relative to server/, enclosing function)``.
WRITE_DEFERRED_CALLERS: set[tuple[str, str]] = set()

#: Directories that never write the journal: not a run, a worker, the swarm or the
#: speculative executor (3.11).
NEVER_WRITE_JOURNAL = ("engine/", "parallel/")

_JOURNAL_TABLES = {
    Configuration.__tablename__, ConfigurationSnapshot.__tablename__, JournalEntry.__tablename__,
}
PROTECTED_TABLES = set(config_registry.configuration_table_names()) | _JOURNAL_TABLES
PROTECTED_CLASSES = {m.__name__ for m in config_registry.configuration_models().values()} | {
    Configuration.__name__, ConfigurationSnapshot.__name__, JournalEntry.__name__,
}
#: The module-level names of the layer's table objects, which a caller could import.
PROTECTED_OBJECTS = {"_CONFIGURATIONS", "_JOURNAL", "_SNAPSHOTS"}

_BUILDERS = {"insert", "update", "delete", "pg_insert", "sa_insert", "sa_update", "sa_delete"}
_SESSION_WRITES = {"add", "add_all", "delete", "merge"}
_RAW_WRITE = re.compile(
    r"(?is)\b(?:insert\s+into|update|delete\s+from|truncate(?:\s+table)?)\s+\"?(\w+)\"?"
)


# ──────────────────────────────────────────────────────────────────
# The checker (also exercised on snippets, below)
# ──────────────────────────────────────────────────────────────────


def _mentions(node: ast.AST, tainted: set[str] = frozenset()) -> bool:
    """Does the expression name a protected model, table, table name or tainted variable?"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and (
            sub.id in PROTECTED_CLASSES or sub.id in PROTECTED_OBJECTS or sub.id in tainted
        ):
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in PROTECTED_CLASSES:
            return True
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if sub.value in PROTECTED_TABLES:
                return True
    return False


def _targets(node: ast.AST) -> list[str]:
    return [n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)]


def _seeds(node: ast.AST, tainted: set[str]) -> bool:
    """A value that names a protected model or table, or is just a copy of a tainted name.

    Taint does not spread through an arbitrary call (``Report(x.revision)`` is not an
    instance of ``x``'s model), only through the expression that names the model and plain
    copies and awaits of a tainted name.
    """
    while isinstance(node, (ast.Await, ast.Starred)):
        node = node.value
    if isinstance(node, ast.Name) and node.id in tainted:
        return True
    return _mentions(node)


def _tainted_names(fn: ast.AST) -> set[str]:
    """Names bound in ``fn`` from an expression that names a protected model."""
    tainted: set[str] = set()
    for _ in range(3):  # a short fixpoint: x = Model(); y = x
        for node in ast.walk(fn):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                if _seeds(node.value, tainted):
                    tainted.update(_targets(node.target) if not isinstance(node, ast.Assign)
                                   else [n for t in node.targets for n in _targets(t)])
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                if _seeds(node.iter, tainted):
                    tainted.update(_targets(node.target))
            elif isinstance(node, ast.comprehension):
                if _seeds(node.iter, tainted):
                    tainted.update(_targets(node.target))
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None and _seeds(item.context_expr, tainted):
                        tainted.update(_targets(item.optional_vars))
    return tainted


def _call_name(call: ast.Call) -> str:
    func = call.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def violations(source: str, filename: str = "<snippet>") -> list[str]:
    """Every statement in ``source`` that writes a configuration or journal table."""
    tree = ast.parse(source)
    found: list[str] = []
    scopes: list[ast.AST] = [tree] + [
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    seen: set[int] = set()
    for scope in scopes:
        tainted = _tainted_names(scope)
        # Nested scopes are visited on their own; skip their bodies here.
        for node in _own_nodes(scope):
            where = f"{filename}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.Call) and id(node) not in seen:
                name = _call_name(node)
                if name in _BUILDERS and _mentions(node, tainted):
                    found.append(f"{where}: {name}(...) on a protected table")
                    seen.add(id(node))
                elif name in _SESSION_WRITES and isinstance(node.func, ast.Attribute) and any(
                    _mentions(a, tainted) for a in node.args
                ):
                    found.append(f"{where}: .{name}(...) of a protected model instance")
                    seen.add(id(node))
                elif name == "setattr" and node.args and _mentions(node.args[0], tainted):
                    found.append(f"{where}: setattr on a protected model instance")
                    seen.add(id(node))
                elif name in {"execute", "text", "exec_driver_sql"}:
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            hit = _RAW_WRITE.search(arg.value)
                            if hit and hit.group(1) in PROTECTED_TABLES:
                                found.append(f"{where}: raw SQL writes {hit.group(1)}")
                                seen.add(id(node))
            elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id in tainted
                    ):
                        found.append(f"{where}: attribute assignment on a protected model instance")
    return found


def _own_nodes(scope: ast.AST):
    """The nodes of ``scope`` that are not inside a nested function."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _server_files():
    for path in sorted(SERVER.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path, path.relative_to(SERVER).as_posix()


# ──────────────────────────────────────────────────────────────────
# The enforcement
# ──────────────────────────────────────────────────────────────────


def test_no_statement_outside_the_layer_writes_a_configuration_or_journal_table():
    found: list[str] = []
    for path, rel in _server_files():
        if rel == LAYER:
            continue
        found += violations(path.read_text(), rel)
    assert not found, (
        "only server/services/journal.py (write_immediate / write_deferred) may write a "
        "configuration or journal table:\n  " + "\n  ".join(found)
    )


def test_the_table_list_is_computed_by_introspection_and_covers_every_configuration_table():
    from server.models import metadata

    names = {
        cls.__tablename__
        for cls in vars(metadata).values()
        if isinstance(cls, type) and getattr(cls, "__module__", "") == metadata.__name__
        and hasattr(cls, "__tablename__")
    }
    assert PROTECTED_TABLES >= names - {"help_topics"}
    assert "help_topics" not in PROTECTED_TABLES  # content, not configuration (3.6)
    assert _JOURNAL_TABLES == {"configurations", "configuration_snapshots", "configuration_journal"}


@pytest.mark.parametrize(
    "snippet",
    [
        "async def f(s):\n    s.add(SlipnetNodeDef(name='x'))\n",
        "async def f(s):\n    row = await s.get(EngineParam, 'a')\n    row.value = 'b'\n",
        "async def f(s):\n    row = await s.get(EngineParam, 'a')\n    await s.delete(row)\n",
        "async def f(s):\n    await s.execute(update(UrgencyLevel).values(value=1))\n",
        "async def f(s):\n    await s.execute(delete(SlipnetLinkDef.__table__))\n",
        "async def f(s):\n    await s.execute(insert(JournalEntry).values(note=''))\n",
        "async def f(s):\n    await s.execute(text('UPDATE engine_params SET value = 1'))\n",
        "async def f(s):\n    await s.execute(text('INSERT INTO configuration_journal VALUES (1)'))\n",
        "async def f(s):\n    await s.execute(text('DELETE FROM slipnet_node_roles'))\n",
        "async def f(s):\n    for r in (await s.execute(select(PostingRule))).scalars():\n        setattr(r, 'condition', 'x')\n",
        "async def f(s):\n    await s.execute(Configuration.__table__.update().values(revision=9))\n",
        "async def f(s):\n    await s.execute(update(table('formula_coefficients')))\n",
    ],
)
def test_the_checker_finds_each_kind_of_write(snippet):
    assert violations(snippet), snippet


@pytest.mark.parametrize(
    "snippet",
    [
        # reads are free
        "async def f(s):\n    return (await s.execute(select(SlipnetNodeDef))).scalars().all()\n",
        "async def f(s):\n    row = await s.get(EngineParam, 'a')\n    return row.value\n",
        # help topics are content
        "async def f(s):\n    s.add(HelpTopic(topic_key='x'))\n",
        "async def f(s):\n    await s.execute(text('UPDATE help_topics SET title = 1'))\n",
        # the runtime tables are not configuration
        "async def f(s):\n    await s.execute(update(Run).values(status='done'))\n",
    ],
)
def test_the_checker_leaves_reads_and_other_tables_alone(snippet):
    assert not violations(snippet), snippet


# ──────────────────────────────────────────────────────────────────
# The two doors
# ──────────────────────────────────────────────────────────────────


def _calls(name: str):
    """``(file, enclosing function)`` of each call to ``name`` outside the layer."""
    out = []
    for path, rel in _server_files():
        if rel == LAYER:
            continue
        tree = ast.parse(path.read_text())
        for fn in [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for node in _own_nodes(fn):
                if isinstance(node, ast.Call) and _call_name(node) == name:
                    out.append((rel, getattr(fn, "name", "<module>")))
    return out


def test_the_layer_has_exactly_the_two_doors():
    tree = ast.parse((SERVER / LAYER).read_text())
    doors = {
        n.name for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name in {"write_immediate", "write_deferred"}
    }
    assert doors == {"write_immediate", "write_deferred"}
    # the only functions of the layer that write an entry are reached through those two
    writers = {
        n.name for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and any(
            isinstance(c, ast.Call) and _call_name(c) == "insert" and _mentions(c)
            and any(isinstance(a, ast.Name) and a.id == "_JOURNAL" for a in c.args)
            for c in ast.walk(n)
        )
    }
    # a configuration's meta edit (name, note, frozen) is a journal entry with no ops (C8)
    assert writers == {"_write", "write_deferred", "update_configuration_meta"}


def test_write_deferred_is_called_only_from_the_stop_write():
    callers = set(_calls("write_deferred"))
    assert callers <= WRITE_DEFERRED_CALLERS, (
        f"write_deferred may be called only from a session's Stop write: {sorted(callers - WRITE_DEFERRED_CALLERS)}"
    )


def test_no_run_worker_swarm_or_speculative_executor_writes_the_journal():
    offenders = []
    for path, rel in _server_files():
        if not rel.startswith(NEVER_WRITE_JOURNAL):
            continue
        text = path.read_text()
        if re.search(r"services\.journal|services import journal|config_registry|models\.journal", text):
            offenders.append(rel)
    assert not offenders, offenders


def test_the_layer_has_no_update_or_delete_of_a_journal_entry():
    tree = ast.parse((SERVER / LAYER).read_text())
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in {"update", "delete"}:
            if any(isinstance(n, ast.Name) and n.id in {"_JOURNAL", "JournalEntry"} for a in node.args for n in ast.walk(a)):
                bad.append(node.lineno)
    assert not bad, f"the layer updates or deletes a journal entry at lines {bad}"
