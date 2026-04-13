# Localization & the Help Text System

Petacat's in-app help (the `?` buttons in every dashboard panel, the detailed
descriptions in the Admin view, and the static [`HELP.md`](HELP.md) reference)
is all served from a single JSON source of truth. This document explains how
the help text system is organised, how to edit existing content, and how to
contribute a new language.

If you just want to read the help content in English, see
[`HELP.md`](HELP.md) — it is regenerated from the JSON every time Petacat's
backend starts.

## The single source of truth

All help text lives in a locale-named JSON file under `seed_data/`:

- `seed_data/help_topics.en.json` — English (shipped)
- `seed_data/help_topics.{locale}.json` — additional languages (see
  [Adding a new language](#adding-a-new-language) below)

Each entry has the shape:

```json
{
  "topic_type": "component" | "glossary",
  "topic_key": "workspace",
  "title": "Workspace",
  "short_desc": "One-sentence summary.",
  "full_desc": "Full paragraph description...",
  "metadata": { "key_concepts": ["bond", "group", "rule"] }
}
```

The file is read at backend startup and upserted into the `help_topics`
database table (keyed by `topic_key`). The frontend fetches help content via
`GET /api/docs/components/{key}` and `GET /api/docs/glossary/{term}` — it
never hardcodes any help text.

### Three kinds of help topics

All three kinds live in the same JSON file and are all served by the same API.
They differ only in how the frontend renders them.

1. **Dashboard panel topics** (`topic_type: "component"`, no `metadata.kind`)
   back the `?` buttons in each dashboard panel. `full_desc` holds the body
   text shown in the HelpPopover, with paragraph breaks rendered verbatim
   (`\n\n` in the JSON becomes a blank line in the popover).

2. **Admin action topics** (`topic_type: "component"`, with
   `metadata.kind: "admin_action"`) describe each button in the Admin view.
   Instead of a single `full_desc` blob, they carry two parallel string
   arrays for structured rendering:

   ```json
   {
     "topic_type": "component",
     "topic_key": "admin_clear_memory",
     "title": "Clear Episodic Memory",
     "short_desc": "Removes all stored answer and snag descriptions.",
     "full_desc": "",
     "metadata": {
       "kind": "admin_action",
       "button_variant": "warning",
       "user_description": ["bullet 1", "bullet 2", "..."],
       "technical_description": ["bullet 1", "bullet 2", "..."]
     }
   }
   ```

   `AdminPanel.tsx` fetches these on mount and renders the bullet arrays as
   two `<ul>` lists ("What this does (user perspective)" and "Technical
   details"). To change the wording of an admin description, edit the JSON
   and click **Regenerate Help Documentation** in the Admin view — no
   TypeScript edits required.

3. **Glossary topics** (`topic_type: "glossary"`) are concept definitions
   (e.g. "slippage", "snag", "jootsing") served by
   `GET /api/docs/glossary/{term}` and listed via `GET /api/docs/glossary`.

## Data flow

```
seed_data/help_topics.en.json         ← single source of truth (edit here)
         │
         │   The sync runs automatically on:
         │     • every backend startup     (server/main.py lifespan)
         │     • admin button click        (POST /api/admin/help/regenerate)
         │     • CLI invocation            (python scripts/generate_help_docs.py)
         │   All three paths call server/services/help_docs.regenerate_all.
         │
         ├──▶ server/main.py::_sync_help_topics
         │    Idempotent UPSERT by topic_key into the help_topics table.
         │        ↓
         │    help_topics table (PostgreSQL)
         │        ↓
         │    GET /api/docs/components/{key}
         │    GET /api/docs/glossary/{term}
         │        ↓
         │    client useHelp() Zustand store → HelpPopover (? buttons)
         │
         └──▶ server/services/help_docs.regenerate_all
              Rewrites (idempotent — skipped if unchanged):
              • HELP.md                              (human-readable reference)
              • client/src/constants/helpTopics.ts   (TypeScript union types)
```

## Editing an existing help topic

The fastest path is to edit the JSON and click a button:

1. Edit `seed_data/help_topics.en.json`.
2. Open the Admin view (hamburger menu → **Admin**) and click
   **Regenerate Help Documentation**. This calls
   `POST /api/admin/help/regenerate`, which:
   - Upserts every row from the JSON into the `help_topics` table.
   - Rewrites `HELP.md` and `client/src/constants/helpTopics.ts` from the
     same JSON (no writes if the content is already in sync).
   - Returns a JSON summary of what changed.

   The `?` popovers in every dashboard panel immediately reflect the new
   content on the next fetch — **no backend restart required**.

Alternative triggers, all equivalent in effect:

- **Backend restart** —
  `docker compose -f docker-compose.dev.yml restart app`.
  The lifespan hook runs the same sync and regeneration on every startup.

- **CLI** — `python scripts/generate_help_docs.py`. Useful when the backend
  is not running and you need the derived files on disk (for a build, a
  static import, or to inspect drift from a cold checkout).

## Adding a new language

The first release ships English only, but the plumbing is already in place
for additional languages without any schema changes.

1. Copy `seed_data/help_topics.en.json` to `seed_data/help_topics.{locale}.json`,
   where `{locale}` is a short language code (e.g. `fr`, `de`, `ja`).
2. Translate the `title`, `short_desc`, and `full_desc` fields. Also translate
   every string inside `metadata.user_description` and
   `metadata.technical_description` arrays (these are the bullet lists that
   the Admin panel renders for admin actions).
3. **Do not change** `topic_type`, `topic_key`, or the non-string keys inside
   `metadata` (`kind`, `button_variant`, `key_concepts`). These are stable
   identifiers used throughout the codebase and across translations.
4. Set the `HELP_LOCALE` environment variable on the backend (e.g.
   `HELP_LOCALE=fr`). The `_sync_help_topics` loader reads
   `help_topics.{HELP_LOCALE}.json`, falling back to
   `help_topics.en.json` only if the locale file is missing.
5. Regenerate derived artifacts for the target locale:
   `python scripts/generate_help_docs.py --locale fr`.

Translators contributing a new language file should open a pull request with
only the new `help_topics.{locale}.json` added. The maintainer will
regenerate derived artifacts and wire it up.

## Guardrails

Three layers enforce synchronization between the JSON, the database, the
generated files, and the frontend code.

### Compile-time (TypeScript)

`PanelHelpButton` is typed as `componentName: ComponentHelpKey`, where
`ComponentHelpKey` is a union generated from the JSON by
`scripts/generate_help_docs.py`. Any reference to a topic key that doesn't
exist in the JSON is a **compile-time error** — you physically can't build a
frontend with a broken help reference.

### Integration tests

`tests/integration/test_help_topics.py` validates:

- JSON is valid and every entry has required fields
  (`topic_type`, `topic_key`, `title`).
- Topic keys are unique and follow the snake_case convention.
- Every `componentName="..."` usage scanned from `client/src/**/*.tsx` maps
  to a real component topic in the JSON.
- The generated `client/src/constants/helpTopics.ts` is in sync with the JSON
  (i.e. the generator was run after the last content edit).
- `HELP.md` exists.
- Every expected panel and admin action has a topic.
- Admin action topics have the required `metadata.kind`, `button_variant`,
  and non-empty `user_description` / `technical_description` arrays.

### End-to-end tests

`tests/e2e/test_help_api.py` validates that every topic in the JSON is
actually fetchable via the API, with correct key normalization (so
`problem_input`, `problem-input`, and `Problem Input` all resolve to the
same topic).

### CI drift detection

Run `python scripts/generate_help_docs.py --check` in CI. It re-renders
`HELP.md` and `helpTopics.ts` in memory, compares them to the files on disk,
and exits non-zero if they differ. Fails fast when someone edits the JSON
but forgets to regenerate.

## Related files

| Path | Role |
|------|------|
| `seed_data/help_topics.en.json` | **Single source of truth** — edit here |
| `HELP.md` | Human-readable static reference (generated) |
| `client/src/constants/helpTopics.ts` | TypeScript union types for topic keys (generated) |
| `server/services/help_docs.py` | Loader, renderers, `regenerate_all()` |
| `server/main.py::_sync_help_topics` | Startup upsert into the database |
| `server/api/admin.py::regenerate_help_docs` | `POST /api/admin/help/regenerate` endpoint |
| `scripts/generate_help_docs.py` | CLI wrapper around the generator |
| `client/src/hooks/useHelp.ts` | Zustand-backed shared state for the popover |
| `client/src/components/HelpPopover.tsx` | The floating help panel |
| `client/src/components/AdminPanel.tsx` | Renders admin action topics inline |
| `tests/integration/test_help_topics.py` | Schema, drift, reference tests |
| `tests/e2e/test_help_api.py` | API-level tests |
