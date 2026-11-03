# The Metacat Standard Configuration

The JSON files in this directory are the **Metacat Standard Configuration**: Metacat's own domain
knowledge as Petacat ports it. It is not a mode and not a database. It is the starting content of one.

| File | Contents |
|------|----------|
| `slipnet_nodes.json`, `slipnet_links.json`, `slipnet_layout.json` | The Slipnet's concepts and links, and the grid positions for drawing it |
| `codelet_types.json` | The codelet types, with their Python `execute_body` source |
| `roles.json` | The roles the engine looks nodes and codelet types up by |
| `engine_params.json`, `urgency_levels.json`, `formula_coefficients.json` | Parameters, urgency bins and formula coefficients (stored as exact rationals such as `2/3`) |
| `theme_dimensions.json`, `theme_relations.json` | The Themespace's dimensions and relations |
| `posting_rules.json` | Which codelets are posted, and when |
| `commentary_templates.json` | The natural-language commentary and Verbose mode's message texts |
| `demo_problems.json` | The pre-configured analogy problems |
| `enums.json` | The enum tables (bond categories, proposal levels, and the rest) |
| `help_topics.en.json` | The help text. It is content, not configuration: the server syncs it into the database at every start, and `scripts/generate_help_docs.py` derives `HELP.md` and the client's `helpTopics.ts` from it |

## When it is loaded

Only into an **empty database**. At start-up, if the database holds no configuration, the server
reads these files and writes them into the database in one transaction, as the first entry (source
`standard_load`) of the journal. From then on the **database is the source of truth**: the engine is
handed whatever the database holds, and these files are not read again. Editing a file therefore
changes nothing for a database that already has data.

Clearing the database is a development move, for example after a schema change. Petacat is not a
production system and has no migrations or upgrades of an existing database; the next start loads
this directory into the empty one.

## Who may change it

**Run-time changes never write these files.** Not the Admin view, not Import, not Reset or Restore,
not an external program, not the in-worker learner, and not any Training Mode Session. Those all go
through the change API and change the database, and the journal records them.

The files change only through a **committed development change**, and only to fix a fidelity bug in
Petacat (a place where Petacat differs from Metacat). The commit message names the affected rows
(table and key), so that anyone comparing a database with these files can see why they moved.
Adding a row for a new feature, or tuning a value, is a change to a configuration in the database,
not to these files.

## Using it

- The Admin view shows how the open configuration differs from the Metacat Standard Configuration
  (a banner, and the **Status and reset** tab), can compare any configuration with it, and can put
  everything, or chosen rows, back to it (**Reset**, **Restore selected**). A reset is an ordinary journal entry that can be undone.
- The same from a terminal: `.venv/bin/python -m server.config status | diff | reset-to-standard --yes |
  restore-selected --row TABLE KEY_JSON | verify-journal`.
- A new Training Mode Session can take it as its base (`settings.configuration_base` of `"standard"`),
  which is its Starting Conceptual State. In testing that is often a replica of this directory's content.
- The main [README](../README.md#the-configuration-the-journal-and-the-change-api) describes the
  configuration, the change API and the journal.
