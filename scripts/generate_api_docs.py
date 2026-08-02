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
    ("/api/runs", "Runs", "Creating, driving and reading a run."),
    ("/api/memory", "Episodic Memory", "The Training Session's memory, shared by every run."),
    ("/api/review", "Review", "Reading back what a Normal or Audit run recorded."),
    ("/api/admin", "Configuration", "The editable copy of the seed data."),
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
