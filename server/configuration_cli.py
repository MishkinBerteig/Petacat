"""``python -m server.config status | diff | reset-to-standard | restore-selected | verify-journal``.

Uses ``DATABASE_URL`` (default: the development database).  Every command takes
``--configuration ID`` (the global configuration, 1, by default) and ``--json``.  Reset needs
``--yes``; restore-selected takes one or more ``--row TABLE KEY_JSON``.  The exit status is 0
on success, 1 when ``verify-journal`` finds a problem, 2 on a refused or failed request.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from server.models.journal import GLOBAL_CONFIGURATION_ID

CHANNEL = "cli"
ACTOR = "cli"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m server.config",
        description="Compare and reset a configuration against the Metacat Standard Configuration (compare also against the v2.0 Base).",
    )
    parser.add_argument("--configuration", type=int, default=GLOBAL_CONFIGURATION_ID,
                        help="configuration id (default: the global configuration, 1)")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--against", choices=("standard", "training-v2"), default="standard",
                        help="what status and diff compare with: the Metacat Standard Configuration "
                             "(default) or the Training Mode Base Configuration, v2.0")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="revision, hashes and how many rows differ from the standard")
    sub.add_parser("diff", help="rows added, removed or changed against the standard")
    reset = sub.add_parser("reset-to-standard", help="reset to the Metacat Standard Configuration")
    reset.add_argument("--yes", action="store_true", help="confirm the reset")
    restore = sub.add_parser("restore-selected", help="restore chosen rows to the standard")
    restore.add_argument("--row", nargs=2, action="append", metavar=("TABLE", "KEY_JSON"),
                         required=True, help='e.g. --row engine_params \'{"name": "x"}\'')
    sub.add_parser("verify-journal", help="replay the journal and compare with the tables")
    return parser


def _text(command: str, result: dict[str, Any]) -> str:
    if command == "status":
        return "\n".join(f"{k}: {v}" for k, v in result.items())
    if command == "diff":
        lines = [f"{result['count']} row(s) differ from the {result.get('against_name', 'Metacat Standard Configuration')} "
                 f"({result['added']} added, {result['removed']} removed, "
                 f"{result['changed']} changed)"]
        for row in result["rows"]:
            cols = f" [{', '.join(row['columns'])}]" if row["columns"] else ""
            lines.append(f"  {row['change']:8} {row['table']} {json.dumps(row['key'])}{cols}")
        return "\n".join(lines)
    if command == "verify-journal":
        head = "ok" if result["ok"] else "PROBLEMS"
        return "\n".join([f"{head}: revision {result['revision']}, {result['entries']} entries",
                          *[f"  {p}" for p in result["problems"]]])
    wrote = "wrote one journal entry" if result["wrote"] else "nothing to change"
    return f"{wrote}; revision {result['revision']}, {result['ops']} op(s)"


async def _run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from server.db import async_session_factory, engine
    from server.services import configuration_admin as admin

    try:
        async with async_session_factory() as session:
            cid = args.configuration
            if args.command in ("status", "diff") and args.against != "standard":
                from server.services import configuration_compare as compare

                got = await compare.compare(session, cid, args.against)
                got["against"], got["against_name"] = args.against, got["b"]["name"]
                if args.command == "diff":
                    return got, 0
                return {"configuration_id": cid, "against": args.against,
                        "against_name": got["b"]["name"], "differs_rows": got["count"],
                        "equals_against": got["same"]}, 0
            if args.command == "status":
                return await admin.status(session, cid), 0
            if args.command == "diff":
                return await admin.diff(session, cid), 0
            if args.command == "reset-to-standard":
                if not args.yes:
                    raise admin.ConfigurationAdminError(
                        "reset-to-standard changes the configuration; pass --yes to confirm")
                return await admin.reset_to_standard(
                    session, cid, actor=ACTOR, channel=CHANNEL), 0
            if args.command == "restore-selected":
                rows = [{"table": t, "key": json.loads(k)} for t, k in args.row]
                return await admin.restore_selected(
                    session, rows, cid, actor=ACTOR, channel=CHANNEL), 0
            report = await admin.verify_journal(session, cid)
            return report, 0 if report["ok"] else 1
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result, code = asyncio.run(_run(args))
    except Exception as exc:  # a refused or failed request: say why, exit 2
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, default=str) if args.json else _text(args.command, result))
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
