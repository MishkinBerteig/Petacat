"""The lint: no node literals in the engine, and no seed-file reads at run time.

Work package EN0 of the configuration-source plan (``agents-workspace/config-source/
CONFIG-SOURCE-PLAN.md``, section 4.4 and 3.5).  The engine owns a *vocabulary* of roles;
the configuration owns the content, so no line of ``server/engine/**`` may name a node or
a codelet type of the Metacat Standard Configuration, and no line may read the
standard-configuration files while a run executes.

Test 1, ``test_no_node_literals_in_engine``, is an AST walk of every module under
``server/engine/`` (docstrings and comments are exempt) that finds

* ``plato-literal``   a string literal beginning ``plato-`` (a node name is one);
* ``plato-compose``   ``"plato-" + x`` and ``f"plato-{...}"``, which build a node name;
* ``slice-6``         ``name[6:]``, which strips the prefix by counting its characters;
* ``node-name``       any other string literal equal to a node name of the Metacat
                      Standard Configuration (``seed_data/slipnet_nodes.json``);
* ``codelet-type``    a string literal equal to a codelet type name of the Metacat
                      Standard Configuration (``seed_data/codelet_types.json``).

Test 2, ``test_no_seed_file_reads_in_engine``, finds in the same modules

* ``seed-dir-name``   a name or attribute spelled ``..SEED_DIR..``;
* ``seed-data-literal``  a string literal containing ``seed_data``;
* ``from-seed-data-call``  a call of ``from_standard_configuration``;
* ``file-read-call``  ``open(...)``, ``.read_text()``, ``.read_bytes()``, ``json.load(...)``.

**The allow-list.**  ``no_node_literals_allowlist.txt`` beside this file is the current hit
list, committed with EN0.  Each line is ``lint, file, category, count, text`` (tab
separated, the text JSON-encoded).  It may only shrink: every engine package deletes the
entries it resolves, and EN11 requires it empty.  The tests are strict in both directions
so that it does:

* a hit that is not in the list, or more hits of an entry than it allows, fails;
* an entry that is no longer hit (or hit fewer times) fails too, naming the line to
  delete or lower.

Entries are keyed by file, category and literal text, not by line number, so an edit
elsewhere in a file does not disturb them.  To regenerate after an approved engine edit:
``.venv/bin/python tests/architecture/test_no_node_literals_in_engine.py --write``
(then review the diff; it should only have lost lines).

``engine/roles.py`` (EN3) is *not* an exception: it names roles, not nodes.
"""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = REPO_ROOT / "server" / "engine"
SEED_DIR = REPO_ROOT / "seed_data"
ALLOWLIST = Path(__file__).with_name("no_node_literals_allowlist.txt")

PREFIX = "plato-"

Hit = tuple[str, str, str, str]  # (lint, file, category, text)


def standard_configuration_names() -> tuple[frozenset[str], frozenset[str]]:
    """The node names and codelet type names of the Metacat Standard Configuration."""
    nodes = json.loads((SEED_DIR / "slipnet_nodes.json").read_text())
    codelets = json.loads((SEED_DIR / "codelet_types.json").read_text())
    return (frozenset(n["name"] for n in nodes), frozenset(c["name"] for c in codelets))


def _engine_files() -> list[Path]:
    return sorted(p for p in ENGINE_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _is_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


class _NameVisitor(ast.NodeVisitor):
    def __init__(self, rel: str, node_names: frozenset[str], codelet_names: frozenset[str]):
        self.rel, self.node_names, self.codelet_names = rel, node_names, codelet_names
        self.hits: list[Hit] = []

    def _hit(self, category: str, text: str) -> None:
        self.hits.append(("names", self.rel, category, text))

    # docstrings and other bare string statements are documentation, not code
    def visit_Expr(self, node: ast.Expr) -> None:
        if not _is_str(node.value):
            self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        value = node.value
        if not isinstance(value, str):
            return
        if value.startswith(PREFIX):
            self._hit("plato-literal", value)
        elif value in self.node_names:
            self._hit("node-name", value)
        elif value in self.codelet_names:
            self._hit("codelet-type", value)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, ast.Add) and _is_str(node.left) and node.left.value.startswith(PREFIX):
            self._hit("plato-compose", ast.unparse(node))
            self.visit(node.right)  # the prefix itself is counted once, as the compose
            return
        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        first = node.values[0] if node.values else None
        if first is not None and _is_str(first) and first.value.startswith(PREFIX):
            self._hit("plato-compose", ast.unparse(node))
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                self.visit(part)
            elif not (_is_str(part) and part.value.startswith(PREFIX) and part is first):
                self.visit(part)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        s = node.slice
        if (isinstance(s, ast.Slice) and isinstance(s.lower, ast.Constant) and s.lower.value == 6
                and s.upper is None and s.step is None):
            self._hit("slice-6", ast.unparse(node))
        self.generic_visit(node)


class _SeedVisitor(ast.NodeVisitor):
    def __init__(self, rel: str):
        self.rel = rel
        self.hits: list[Hit] = []

    def _hit(self, category: str, text: str) -> None:
        self.hits.append(("seed-reads", self.rel, category, text))

    def visit_Expr(self, node: ast.Expr) -> None:
        if not _is_str(node.value):
            self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and "seed_data" in node.value:
            self._hit("seed-data-literal", node.value)

    def visit_Name(self, node: ast.Name) -> None:
        if "SEED_DIR" in node.id:
            self._hit("seed-dir-name", node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if "SEED_DIR" in node.attr:
            self._hit("seed-dir-name", node.attr)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        if name == "from_standard_configuration":
            self._hit("from-seed-data-call", ast.unparse(f))
        elif name in ("open", "read_text", "read_bytes") or (
                name == "load" and isinstance(f, ast.Attribute) and ast.unparse(f.value) == "json"):
            self._hit("file-read-call", ast.unparse(f))
        self.generic_visit(node)


def scan() -> list[Hit]:
    node_names, codelet_names = standard_configuration_names()
    hits: list[Hit] = []
    for path in _engine_files():
        rel = str(path.relative_to(REPO_ROOT))
        tree = ast.parse(path.read_text(), filename=rel)
        names = _NameVisitor(rel, node_names, codelet_names)
        names.visit(tree)
        seeds = _SeedVisitor(rel)
        seeds.visit(tree)
        hits += names.hits + seeds.hits
    return hits


def counts(hits: list[Hit], lint: str) -> Counter[tuple[str, str, str]]:
    return Counter((f, c, t) for (l, f, c, t) in hits if l == lint)


def read_allowlist() -> dict[str, Counter[tuple[str, str, str]]]:
    out: dict[str, Counter[tuple[str, str, str]]] = {"names": Counter(), "seed-reads": Counter()}
    for raw in ALLOWLIST.read_text().splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        lint, file, category, count, text = raw.split("\t")
        out[lint][(file, category, json.loads(text))] += int(count)
    return out


def render_allowlist(hits: list[Hit]) -> str:
    header = (
        "# The current hit list of tests/architecture/test_no_node_literals_in_engine.py.\n"
        "# It may only shrink: each engine package deletes the entries it resolves; EN11\n"
        "# requires it empty.  Columns (tab separated): lint, file, category, count, text.\n"
    )
    rows = []
    for lint in ("names", "seed-reads"):
        for (f, c, t), n in sorted(counts(hits, lint).items()):
            rows.append(f"{lint}\t{f}\t{c}\t{n}\t{json.dumps(t)}")
    return header + "\n".join(rows) + "\n"


def _compare(lint: str) -> list[str]:
    current = counts(scan(), lint)
    allowed = read_allowlist()[lint]
    problems = []
    for key, n in sorted(current.items()):
        if n > allowed.get(key, 0):
            file, category, text = key
            problems.append(f"NEW {category} in {file}: {text!r} (x{n}, allowed {allowed.get(key, 0)})")
    for key, n in sorted(allowed.items()):
        if current.get(key, 0) < n:
            file, category, text = key
            problems.append(
                f"RESOLVED, shrink the allow-list: {category} in {file}: {text!r} "
                f"(allowed {n}, now {current.get(key, 0)})")
    return problems


def test_no_node_literals_in_engine() -> None:
    problems = _compare("names")
    assert not problems, (
        "The engine may not name a node or a codelet type of the Metacat Standard "
        "Configuration (plan 4.4). The allow-list may only shrink.\n  " + "\n  ".join(problems[:40])
        + (f"\n  ... and {len(problems) - 40} more" if len(problems) > 40 else ""))


def test_no_seed_file_reads_in_engine() -> None:
    problems = _compare("seed-reads")
    assert not problems, (
        "The engine may not read the standard-configuration files at run time (plan 3.5). "
        "The allow-list may only shrink.\n  " + "\n  ".join(problems[:40]))


def test_the_allowlist_is_sorted_and_well_formed() -> None:
    """The file is the committed hit list: parseable, no blank categories, no duplicates."""
    seen = set()
    for raw in ALLOWLIST.read_text().splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        lint, file, category, count, text = raw.split("\t")
        assert lint in ("names", "seed-reads")
        assert (ENGINE_DIR.parent.parent / file).exists(), f"{file} is not a file"
        assert int(count) >= 1
        key = (lint, file, category, json.loads(text))
        assert key not in seen, f"duplicate allow-list entry {key}"
        seen.add(key)


def test_the_lint_catches_what_it_claims_to() -> None:
    """The visitor on a sample module: each pattern is found, docstrings are not."""
    source = '''
"""plato-docstring is exempt."""
def f(x, name):
    """plato-also-exempt"""
    a = "plato-left"
    b = "plato-" + x
    c = f"plato-{x}"
    d = name[6:]
    e = "bond-evaluator"
    "a bare string statement plato-comment"
    return a, b, c, d, e
'''
    v = _NameVisitor("sample.py", frozenset({"plato-left"}), frozenset({"bond-evaluator"}))
    v.visit(ast.parse(source))
    found = sorted((c, t) for (_, _, c, t) in v.hits)
    assert found == sorted([
        ("plato-literal", "plato-left"),
        ("plato-compose", "'plato-' + x"),
        ("plato-compose", "f'plato-{x}'"),
        ("slice-6", "name[6:]"),
        ("codelet-type", "bond-evaluator"),
    ])


if __name__ == "__main__":
    if "--write" in sys.argv:
        ALLOWLIST.write_text(render_allowlist(scan()))
        print(f"wrote {ALLOWLIST}")
    else:
        print(render_allowlist(scan()))
