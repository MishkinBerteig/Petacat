"""A stand-in for ``resolve(cfg, batch) -> (resolved_ops, report)`` (the configuration plan's 3.12.0).

Used by the EpisodeLog tests so they do not depend on C14.  It honours exactly what the log
passes through: ``base_mode`` (strict | rebase) against ``base_version``, ``on_op_failure``
(abort | skip), ``dry_run`` ignored (the log handles it), and these batch ops, resolved in order
against a working copy so later ops see earlier ones:

* ``{"op": "insert", "table", "key", "row"}``: skipped/aborted if the key exists.
* ``{"op": "update", "table", "key", "set", "expect"?}``: ``expect`` maps column -> value.
* ``{"op": "delete", "table", "key", "expect"?}``.
* ``{"op": "adjust", "table", "key", "column", "by"}``: relative; acts on the current value.
"""

from __future__ import annotations

from server.services.config_document import ConfigDocument, apply_resolved, key_columns


class Refused(Exception):
    pass


class Stale(Refused):
    pass


def _row(cfg, table, key):
    cols = key_columns(table)
    return cfg.tables[table].get(tuple(key[c] for c in cols))


def fake_resolve(cfg: ConfigDocument, batch):
    strict = batch.get("base_mode", "strict") == "strict"
    if strict and batch.get("base_version") is not None and batch["base_version"] != cfg.version:
        raise Stale(f"base_version {batch['base_version']} != {cfg.version}")
    skip = batch.get("on_op_failure", "abort") == "skip"
    work = cfg
    resolved: list[dict] = []
    skipped: list[dict] = []

    def fail(op, reason):
        if not skip:
            raise Refused(reason)
        skipped.append({"op": op, "reason": reason})

    for op in batch.get("ops", ()):
        kind, table, key = op["op"], op["table"], op["key"]
        row = _row(work, table, key)
        if kind == "insert":
            if row is not None:
                fail(op, "key_exists")
                continue
            out = {"op": "insert", "table": table, "key": dict(key), "row": dict(op["row"])}
        elif kind in ("update", "delete", "adjust"):
            if row is None:
                fail(op, "missing_key")
                continue
            expect = op.get("expect")
            if expect and any(row.get(c) != v for c, v in expect.items()):
                fail(op, "expect_failed")
                continue
            if kind == "delete":
                out = {"op": "delete", "table": table, "key": dict(key)}
            elif kind == "update":
                out = {"op": "update", "table": table, "key": dict(key), "set": dict(op["set"])}
            else:
                out = {
                    "op": "update",
                    "table": table,
                    "key": dict(key),
                    "set": {op["column"]: row[op["column"]] + op["by"]},
                }
        else:
            raise Refused(f"unknown op {kind}")
        resolved.append(out)
        work = apply_resolved(work, [out])
    report = {
        "ok": True,
        "version_before": cfg.version,
        "applied": len(resolved),
        "skipped": skipped,
    }
    return resolved, report
