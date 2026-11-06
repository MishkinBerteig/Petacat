"""Generate `API.md` from the FastAPI application's OpenAPI schema.

The routes are declared once, in `server/api/*.py`, and this reads them from there, so
the reference lists exactly what the server serves.

    python scripts/generate_api_docs.py           # write API.md
    python scripts/generate_api_docs.py --check   # exit 1 when API.md is behind

`--check` is what a CI job runs: it regenerates into memory and compares, so a route
added without regenerating shows up as a failure rather than as a silence.
"""

from __future__ import annotations

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

API_MD_PATH = os.path.join(REPO_ROOT, "API.md")

#: Order the sections appear in, and what each one is for.
GROUPS: list[tuple[str, str, str]] = [
    (
        "/api/runs",
        "Runs",
        "Metacat Mode: creating, driving and reading a run. On `POST /api/runs`, `mode` is the "
        "persistence mode (Fast, Normal or Audit: how the run is recorded), a v1.2 name that "
        "stays as it is, and `workers` is the run mode (1 is single-threaded, more is the exact "
        "speculative executor).",
    ),
    (
        "/api/swarm",
        "Swarm",
        "Metacat Mode, multi-core across runs: one problem over many seeds on every core, giving the "
        "answer distribution, plus pool status (a detachable plugin; 503 when absent).",
    ),
    (
        "/api/training-mode/sessions",
        "Training Mode Sessions",
        "Training Mode: named, long-lived Training episodes of many problems over many seeds "
        "(Training Mode Sessions), each with its own Episodic Memory that no route clears (never "
        "Metacat Mode's). A Training Mode Session is created Stopped and is started, paused, resumed, stopped "
        "and started again; problems can be added in any state; the database is written only at "
        "milestones (works with or without the parallel plugin).",
    ),
    (
        "/api/memory",
        "Episodic Memory",
        "Metacat Mode: the Episodic Memory (Metacat-Mode learning) that each episodic run inherits "
        "from the runs before it, until it is cleared. Clearing is an event, recorded with an "
        "editable note. It is not Training Mode and is untouched by Training Mode Sessions.",
    ),
    ("/api/review", "Review", "Metacat Mode: reading back what a Normal or Audit run recorded, and the episodic-run timeline: recorded runs with the Episodic Memory clears between them (Metacat Mode, not Training Mode)."),
    (
        "/api/configurations",
        "Configurations and the change API",
        "Metacat Mode and Training Mode: one batch, `POST /api/configurations/{id}/changes`, is how "
        "configuration is written (the Admin editors, the Database tab, restore, reset, import, "
        "the external route and the in-worker learner submit the same batch); `GET .../schema` "
        "lists the tables, the ops and the shape of a batch. "
        "**Vocabulary.** `rename_enum_value` renames a row of an enum table or a theme relation "
        "and rewrites every column that names it: `posting_rules.direction`, "
        "`codelet_type_defs.family` and `.phase`, `slipnet_link_defs.link_type`, "
        "`engine_params.value_type`, `formula_coefficients.value_type`, "
        "`clamp_types.progress_focus`, `progress_focuses.event_types` and "
        "`theme_dimension_defs.valid_relations`, and the keys of the commentary sections keyed "
        "by the table's names; the row keeps its `role` (`behaviour` for `link_types`) and its "
        "place. Bodies, predicates, formulas, parameters and templates that still spell the old "
        "name are listed as `dangling` and left alone, as `rename_node` lists code. An urgency "
        "level rename also rewrites `clamp_types.codelet_background_level`. Deleting an enum row "
        "that holds a `role` (a `behaviour`, for `link_types`) is refused, `422 role_bound`: "
        "unbind it first by setting the column to null. A `role` must be a name of the table's "
        "vocabulary and held by one row (else `422 unknown_reference` or `422 role_taken`); an "
        "unbound row is allowed and inert, except that it becomes a valid value of the columns "
        "that name its table. "
        "**Episodic Memory.** A Training Mode Session's Episodic Memory persists names (theme "
        "types in theme patterns, rule and clause types in signatures, relations in concept "
        "patterns). The change API has one rule for every name the memory holds, a node or a "
        "vocabulary row alike: it neither refuses nor rewrites. The rename, removal or merge is "
        "carried out on the configuration, and the session's memory keeps the names it stored. "
        "**Parameters that name things.** `engine_params.refers_to` declares what a parameter's "
        "value names: `node_list`, `trigger_node_list`, `node_map`, `codelet_type_list`, "
        "`urgency_level` or null. Removing, renaming or merging a node edits every parameter "
        "that refers to nodes; a codelet type edit edits the `codelet_type_list` parameters; an "
        "urgency level edit lists the `urgency_level` parameters as `dangling`. A rule-trigger "
        "edit (`add_trigger`, `remove_trigger`) also changes the parameter whose `refers_to` is "
        "`trigger_node_list` (`top_down_slipnodes` in the Metacat Standard Configuration): the "
        "node is added to it, or removed from it only when no rule still triggers the node. A "
        "configuration that declares no such parameter leaves every parameter alone.",
    ),
    ("/api/admin", "Configuration", "Metacat Mode: the editable copy of the seed data (the global configuration). A Training Mode Session copies it when created and never changes it."),
    ("/api/docs", "Help", "In-app help topics, the glossary and search."),
    ("/api/system", "System", "What the process resolved at startup."),
]

METHOD_ORDER = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def _summarise(operation: dict) -> str:
    text = operation.get("summary") or operation.get("description") or ""
    first = text.strip().split("\n", 1)[0].strip()
    return first[:160]


def render() -> str:
    from server.main import app

    schema = app.openapi()
    paths: dict[str, dict] = schema.get("paths", {})

    rows: dict[str, list[tuple[str, str, str]]] = {prefix: [] for prefix, _, _ in GROUPS}
    other: list[tuple[str, str, str]] = []

    for path, operations in sorted(paths.items()):
        for method, operation in operations.items():
            verb = method.upper()
            if verb not in METHOD_ORDER:
                continue
            entry = (verb, path, _summarise(operation))
            for prefix, _, _ in GROUPS:
                if path.startswith(prefix):
                    rows[prefix].append(entry)
                    break
            else:
                other.append(entry)

    total = sum(len(v) for v in rows.values()) + len(other)

    lines = [
        "# Petacat API",
        "",
        "> **Auto-generated.** Run `python scripts/generate_api_docs.py` to regenerate "
        "from the FastAPI application.",
        "",
        f"{total} HTTP routes, plus `WS /ws/runs/{{run_id}}` for live state push.",
        "",
        "Interactive documentation is served at `/docs` while the API is running.",
        "",
        "Petacat has two modes: **Metacat Mode** (the v1.2 features, including Metacat's own "
        "Episodic Memory) and **Training Mode** (Training Mode Sessions and what follows). Nothing in "
        "Training Mode affects Metacat Mode. Run mode (single-threaded or multi-core) is "
        "independent of both and is not the persistence mode (Fast, Normal or Audit).",
        "",
    ]

    for prefix, title, blurb in GROUPS:
        entries = sorted(rows[prefix], key=lambda e: (e[1], METHOD_ORDER.index(e[0])))
        if not entries:
            continue
        lines += [f"## {title}", "", blurb, "", "| Method | Path | Purpose |", "|---|---|---|"]
        for verb, path, summary in entries:
            lines.append(f"| `{verb}` | `{path}` | {summary} |")
        lines.append("")

    if other:
        lines += ["## Other", "", "| Method | Path | Purpose |", "|---|---|---|"]
        for verb, path, summary in sorted(other, key=lambda e: e[1]):
            lines.append(f"| `{verb}` | `{path}` | {summary} |")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 when API.md is behind")
    args = parser.parse_args()

    rendered = render()
    if args.check:
        current = open(API_MD_PATH).read() if os.path.exists(API_MD_PATH) else ""
        if current != rendered:
            print("API.md is behind the application. Run scripts/generate_api_docs.py")
            return 1
        print("API.md is in sync.")
        return 0

    with open(API_MD_PATH, "w") as handle:
        handle.write(rendered)
    print(f"wrote API.md ({rendered.count(chr(10) + '|') } rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
