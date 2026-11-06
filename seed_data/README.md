# The Metacat Standard Configuration

The JSON files in this directory are the **Metacat Standard Configuration**: Metacat's own domain
knowledge as Petacat ports it. It is not a mode and not a database. It is the starting content of one.

| File | Contents |
|------|----------|
| `slipnet_nodes.json`, `slipnet_links.json`, `slipnet_layout.json` | The Slipnet's concepts and links, and the grid positions for drawing it |
| `codelet_types.json` | The codelet types, with their Python `execute_body` source |
| `roles.json` | The roles the engine looks nodes and codelet types up by |
| `engine_params.json`, `urgency_levels.json`, `formula_coefficients.json` | Parameters, urgency bins and formula coefficients (stored as exact rationals such as `2/3`). Every fixed number that decides a strength, an unhappiness, a clip, an exponent or a rule's cost is a coefficient here, in the form (int or float) the engine used |
| `engine_param_refs.json` | What a parameter's value names (`engine_params.refers_to`): see [Parameters that name things](#parameters-that-name-things) |
| `theme_dimensions.json`, `theme_relations.json` | The Themespace's dimensions and relations |
| `posting_rules.json` | Which codelets are posted, and when; a rule's `urgency_level` names a tier of `urgency_levels` |
| `commentary_templates.json` | The natural-language commentary and Verbose mode's message texts |
| `demo_problems.json` | The pre-configured analogy problems |
| `enums.json` | The 18 enum tables (bridge types, proposal levels, link types, clamp types, and the rest), with the `role` column that binds a row to the engine's vocabulary: see [The role vocabulary](#the-role-vocabulary) |
| `help_topics.en.json` | The help text. It is content, not configuration: the server syncs it into the database at every start, and `scripts/generate_help_docs.py` derives `HELP.md` and the client's `helpTopics.ts` from it |

## The role vocabulary

The engine owns the **concepts** (a bridge joins the top strings, a clamp holds the Coderack against a
background, a snag has a failure kind); the configuration owns the **names** it calls them. An
enum-table row binds one concept by holding its engine name in its **`role`** column, and the engine
reads the row bound to each role once per run and compares against that row's name, never against a
literal. In the Metacat Standard Configuration each role is bound to the row Metacat calls it. Rename
the row (`rename_enum_value` in the change API, or **Rename** in the Admin enum editor) and the run
follows; a run does not change. A role bound to no row is simply absent for that run (a comparison
against it is false), except the roles `start_check.py` lists as required, which stop a run at its start.
The names the engine accepts in a `role` column are `server/engine/roles.py`'s `VOCABULARY`; the Admin
enum editor offers exactly that list, read-only, for the table. A `role` is unique within its table, a
row that holds one is not deleted until it is unbound (`422 role_bound`), and an unbound row is allowed
and inert except that it becomes a valid value of the columns that name its table.

| Table | Role names (`<prefix>.<name>`) |
|---|---|
| `event_types` | `event_type.` + `group_built`, `rule_built`, `answer_found`, `snag`, `clamp_start`, `concept_mapping_built`, `concept_activation` |
| `bridge_types` | `bridge_type.` + `top`, `bottom`, `vertical` |
| `bridge_orientations` | `bridge_orientation.` + `horizontal`, `vertical` |
| `clause_types` | `clause_type.` + `intrinsic`, `extrinsic`, `verbatim` |
| `rule_types` | `rule_type.` + `top`, `bottom` |
| `theme_types` | `theme_type.` + `top_bridge`, `bottom_bridge`, `vertical_bridge` |
| `proposal_levels` | `proposal_level.` + `proposed`, `evaluated`, `built` |
| `posting_directions` | `posting_direction.` + `bottom_up`, `top_down`, `thematic` |
| `theme_relations` (`theme_relations.json`, not an enum table) | `theme_relation.` + `identity`, `opposite`, `successor`, `predecessor`, `diff` |
| `string_kinds` | `string_kind.` + `initial`, `modified`, `target`, `answer` |
| `rule_scopes` | `rule_scope.` + `self`, `subobjects` |
| `failure_kinds` | `failure_kind.` + `swap`, `conflict`, `change` |
| `clamp_types` | `clamp_type.` + `rule_codelet`, `snag_response`, `justify`, `manual` |

`event_types` holds exactly the seven kinds of event the Trace records (`make-generic-event` in the
Scheme's `trace.ss`: answer, clamp, concept-activation, concept-mapping, group, rule and snag), and every
one is recorded and read back by the engine.

The engine still spells the names that are its own and not a configuration's: a run's status
(`run_statuses`), a link type's behaviour, the keys of the problem JSON (`initial`, `modified`, `target`,
`answer`) and of the payloads the client reads, and the keys of the rule-English template table.
`tests/architecture/test_vocabulary_literals.py` scans `server/engine/`, `server/parallel/`,
`server/services/` and `server/api/` and lists each such literal with its reason; any other literal equal
to a bound name fails it.

Tables whose rows the engine does not name have no `role`: `run_statuses` (the lifecycle of a run and the
API protocol, which the client compares), `codelet_phases` (a grouping label) and `param_value_types`
(how the stored text of a parameter is parsed; renaming one makes the parameters of that type unreadable,
so the change API advises against it).

Four tables have other columns than the common four (`name`, `display_label`, `sort_order`,
`description`), all in `enums.json`:

- **`link_types.behaviour`** is what the engine does with a link of this type, one of `category`,
  `instance`, `property`, `lateral`, `slip` (`LINK_BEHAVIOURS`). Which type has which behaviour is
  configuration; the engine names behaviours and never a link type. Several types may share one behaviour.
  A type that holds a behaviour is not deleted until the behaviour is unset.
- **`codelet_families.serialised`** (boolean) says a codelet of this family runs alone under the
  free-running executor, because it reads and rewrites the whole Workspace (`meta` and `answer`).
- **`clamp_types`** has, besides `role`: `codelet_background_level`, the name of an urgency level the clamp
  holds the rest of the Coderack against (null: none); `jootsing_factor`, the factor a clamp of this type gives
  the jootsing probability; `jootsing_only_when_latest`, true when the factor applies only while the clamp is
  still the newest event of the Trace (otherwise it is 0); `progress_focus`, the name of a row of
  `progress_focuses`; and `codelet_patterns`, the list of codelet pattern names (the `pattern_name` of
  `codelet_pattern_defs`) a clamp of this type clamps (the justify clamp clamps `top-down-codelet-pattern`
  and `thematic-codelet-pattern`, the rule-codelet clamp `rule-codelet-pattern`, the snag-response clamp
  `bottom-up-codelet-pattern`, a person's manual clamp none: the person names the pattern).
- **`progress_focuses.event_types`** is the list of `event_types` names that count as progress for a clamp.

Renaming a row rewrites every column that names it (`posting_rules.direction`, `codelet_type_defs.family`
and `.phase`, `slipnet_link_defs.link_type`, `engine_params.value_type`, `formula_coefficients.value_type`,
`clamp_types.progress_focus`, `progress_focuses.event_types`, `theme_dimension_defs.valid_relations`,
the commentary sections keyed by the table's names) and lists the code, parameters and templates that still
spell the old name. A codelet body, descriptor predicate or posting formula should write `role('bridge_type.top')`
rather than the name, so that a rename needs no edit to it.

## Parameters that name things

`engine_params.refers_to` says what a parameter's value names, so a change that renames or removes the
thing updates the parameter with it. It is declared in `engine_param_refs.json` (a map from parameter name
to one of the seven values; a parameter not in the file refers to nothing, and the column is null):

| `refers_to` | The value is | Standard Configuration |
|---|---|---|
| `node_list` | a JSON list of Slipnet node names | `initially_clamped_slipnodes` |
| `trigger_node_list` | a JSON list of node names that is also the union of the posting rules' triggering nodes | `top_down_slipnodes` |
| `node_map` | a JSON map keyed by node name | `intrinsic_link_lengths`, `theme_dimension_labels`, `rule_english_dimension_phrases` |
| `codelet_type_list` | a JSON list of codelet type names | `initial_codelet_types` |
| `urgency_level` | the name of an urgency level, which a run needs to exist | `initial_codelet_urgency`, `bridge_recruit_urgency_level`, `default_urgency_level`, `manual_clamp_background_level` |
| `clampable_pattern_map` | a JSON map keyed by the name of a clampable codelet pattern (the Options menu: `top_down`, `bottom_up`, `rule`, `bridge`, `group`), to its label | `clampable_codelet_patterns` |
| `clampable_pattern_list` | a JSON list of names of clampable codelet patterns, each a key of the `clampable_pattern_map` parameter | `manual_clamp_background_patterns` |

The change API reads the column of the configuration it resolves against; no parameter name is written in
code. A rule-trigger edit (`add_trigger`, `remove_trigger`) also changes the `trigger_node_list` parameter.
No operation renames a clampable pattern (its name is a key of the menu parameter, and `<name>-codelet-pattern`
is its row in `codelet_pattern_defs`), so a batch that edits the menu and leaves a `clampable_pattern_list`
entry that the menu no longer offers reports that parameter as `dangling`, as an urgency level rename does for
an `urgency_level` parameter.

The engine names no urgency tier. A run needs the tiers the configuration itself names: every tier a
codelet body reads (`meta.get_urgency('low')`, found by parsing the bodies in force), every parameter above,
every posting rule, clamp type and codelet pattern entry that names one. A tier renamed in its row and in
the code that names it still runs. `manual_clamp_background_patterns` lists the clampable codelet patterns
(`rule`, `bridge`, `group`) a person's clamp holds against a background of `manual_clamp_background_level`
(`gui.ss:1221-1245`); the top-down and bottom-up patterns are clamped without one.

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

The files change only through a **committed development change**, and only in four cases:

1. to fix a fidelity bug in Petacat (a place where Petacat differs from Metacat);
2. to remove a row or field that nothing reads (proven unread by reading the code and by running);
3. to move a value the engine held as a literal into the configuration (round 2, stage 5: every
   number that determines Metacat Mode's cognition is a row, read from the database), which adds
   the row to `engine_params.json` or `formula_coefficients.json` with today's value in its
   exact form (an int stays an int, a float a float) and the name of the literal it replaces.
4. to make a row that held a copy of a stored value name it instead. A posting rule's
   `urgency_level` holds the *name* of a tier of `urgency_levels` (`low`, `medium`,
   `extremely_low`), where it used to hold that tier's number (35, 49, 7), so a tier is stored
   once and editing it moves every rule that names it. Nothing else about a row changes.

The commit message names the affected rows (table and key), so that anyone comparing a database
with these files can see why they moved. Adding a row for a new feature, or tuning a value, is a
change to a configuration in the database, not to these files.

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
