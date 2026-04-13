#!/usr/bin/env python3
"""Generate derived help documentation from the help topics JSON.

Thin CLI wrapper around `server.services.help_docs`. Reads the locale JSON
and produces:

1. `HELP.md` -- human-readable Markdown reference
2. `client/src/constants/helpTopics.ts` -- TypeScript key constants/unions

Usage:
    python scripts/generate_help_docs.py [--locale en] [--check]

Options:
    --locale LOCALE    Language code (default: "en"). Reads help_topics.{locale}.json.
    --check            Exit non-zero if generated files would change (for CI).

Note: the same generation runs automatically on every backend startup (see
`server/main.py` lifespan) and can be triggered from the Admin panel. Running
this script manually is only necessary if you want to regenerate without
starting the backend (e.g. from a cold repo checkout before building).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this script directly from a repo checkout, outside the Docker
# container (which sets PYTHONPATH=/app). Add the repo root to sys.path so we
# can import server.services.help_docs.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from server.services.help_docs import (  # noqa: E402
    check_drift,
    regenerate_all,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", default="en", help="Locale code (default: en)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if files would change (for CI).",
    )
    args = parser.parse_args()

    if args.check:
        drift = check_drift(args.locale)
        if drift:
            print("Derived help docs are out of sync with the JSON source of truth:")
            for p in drift:
                print(f"  - {p}")
            print("\nRun: python scripts/generate_help_docs.py")
            return 1
        print("Help docs are in sync.")
        return 0

    result = regenerate_all(args.locale)
    if result.help_md_changed:
        print(f"wrote {result.help_md_path}")
    else:
        print(f"unchanged {result.help_md_path}")
    if result.ts_constants_changed:
        print(f"wrote {result.ts_constants_path}")
    else:
        print(f"unchanged {result.ts_constants_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
