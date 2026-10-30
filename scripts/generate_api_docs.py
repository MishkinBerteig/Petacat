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
        "/api/trainings",
        "Trainings",
        "Training Mode: named, long-lived Training episodes of many problems over many seeds, "
        "extendable while they run, each with its own episode memory (never Metacat Mode's "
        "Episodic Memory); the database is written only when a problem finishes (works with or "
        "without the parallel plugin).",
    ),
    (
        "/api/memory",
        "Episodic Memory",
        "Metacat Mode: the Episodic Memory (Metacat-Mode learning) shared by the runs of the "
        "Metacat Mode session, which the UI calls the \"Training Session\". It is not Training "
        "Mode and is untouched by Trainings.",
    ),
    ("/api/review", "Review", "Metacat Mode: reading back what a Normal or Audit run recorded, and the sessions (\"Training Sessions\" in the UI; Metacat Mode, not Training Mode) the runs form."),
    ("/api/admin", "Configuration", "Metacat Mode: the editable copy of the seed data (the global configuration). A Training copies it when created and never changes it."),
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
        "Episodic Memory) and **Training Mode** (Trainings and what follows). Nothing in "
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
