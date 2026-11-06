# Petacat API

> **Auto-generated.** Run `python scripts/generate_api_docs.py` to regenerate from the FastAPI application.

185 HTTP routes, plus `WS /ws/runs/{run_id}` for live state push.

Interactive documentation is served at `/docs` while the API is running.

Petacat has two modes: **Metacat Mode** (the v1.2 features, including Metacat's own Episodic Memory) and **Training Mode** (Training Mode Sessions and what follows). Nothing in Training Mode affects Metacat Mode. Run mode (single-threaded or multi-core) is independent of both and is not the persistence mode (Fast, Normal or Audit).

## Runs

Metacat Mode: creating, driving and reading a run. On `POST /api/runs`, `mode` is the persistence mode (Fast, Normal or Audit: how the run is recorded), a v1.2 name that stays as it is, and `workers` is the run mode (1 is single-threaded, more is the exact speculative executor).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/runs` | List Runs |
| `POST` | `/api/runs` | Create Run |
| `DELETE` | `/api/runs` | Delete All Runs |
| `GET` | `/api/runs/parameters/catalogue` | Get Parameter Catalogue |
| `GET` | `/api/runs/{run_id}` | Get Run |
| `DELETE` | `/api/runs/{run_id}` | Delete Run |
| `POST` | `/api/runs/{run_id}/breakpoint` | Set Breakpoint |
| `DELETE` | `/api/runs/{run_id}/breakpoint` | Clear Breakpoint |
| `POST` | `/api/runs/{run_id}/clamp-codelet-pattern` | Clamp Codelet Pattern |
| `DELETE` | `/api/runs/{run_id}/clamp-codelet-pattern` | Unclamp Codelet Pattern |
| `POST` | `/api/runs/{run_id}/clamp-codelets` | Clamp Codelets |
| `DELETE` | `/api/runs/{run_id}/clamp-codelets` | Unclamp Codelets |
| `POST` | `/api/runs/{run_id}/clamp-node` | Clamp Node |
| `DELETE` | `/api/runs/{run_id}/clamp-node` | Unclamp Node |
| `POST` | `/api/runs/{run_id}/clamp-temperature` | Clamp Temperature |
| `DELETE` | `/api/runs/{run_id}/clamp-temperature` | Unclamp Temperature |
| `POST` | `/api/runs/{run_id}/clamp-theme-pattern` | Clamp Theme Pattern |
| `POST` | `/api/runs/{run_id}/clamp-themes` | Clamp Themes |
| `DELETE` | `/api/runs/{run_id}/clamp-themes` | Unclamp Themes |
| `GET` | `/api/runs/{run_id}/codelet-patterns` | List Codelet Patterns |
| `GET` | `/api/runs/{run_id}/coderack` | Get Coderack |
| `GET` | `/api/runs/{run_id}/commentary` | Get Commentary |
| `GET` | `/api/runs/{run_id}/eeg` | Get Eeg |
| `GET` | `/api/runs/{run_id}/identity` | Get Run Identity |
| `GET` | `/api/runs/{run_id}/memory` | Get Memory |
| `GET` | `/api/runs/{run_id}/parameters` | Get Run Parameters |
| `POST` | `/api/runs/{run_id}/reset` | Reset Run |
| `POST` | `/api/runs/{run_id}/run` | Run To Completion |
| `PUT` | `/api/runs/{run_id}/self-watching` | Set Self Watching |
| `GET` | `/api/runs/{run_id}/slipnet` | Get Slipnet |
| `GET` | `/api/runs/{run_id}/spreading-threshold` | Get Spreading Threshold |
| `POST` | `/api/runs/{run_id}/spreading-threshold` | Set Spreading Threshold |
| `POST` | `/api/runs/{run_id}/step` | Step Run |
| `POST` | `/api/runs/{run_id}/stop` | Stop Run |
| `GET` | `/api/runs/{run_id}/telemetry` | Get Run Telemetry |
| `GET` | `/api/runs/{run_id}/temperature` | Get Temperature |
| `GET` | `/api/runs/{run_id}/themespace` | Get Themespace |
| `POST` | `/api/runs/{run_id}/themespace/restore` | Restore Themespace |
| `GET` | `/api/runs/{run_id}/trace` | Get Trace |
| `GET` | `/api/runs/{run_id}/trace/export` | Export Trace |
| `GET` | `/api/runs/{run_id}/trace/{event_number}` | Get Trace Event |
| `POST` | `/api/runs/{run_id}/trace/{event_number}/display` | Display Trace Event |
| `POST` | `/api/runs/{run_id}/undo-last-clamp` | Undo Last Clamp |
| `GET` | `/api/runs/{run_id}/verbose` | Get Verbose |
| `PUT` | `/api/runs/{run_id}/verbose` | Set Verbose |
| `DELETE` | `/api/runs/{run_id}/verbose` | Clear Verbose |
| `GET` | `/api/runs/{run_id}/workspace` | Get Workspace |

## Swarm

Metacat Mode, multi-core across runs: one problem over many seeds on every core, giving the answer distribution, plus pool status (a detachable plugin; 503 when absent).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/swarm` | Swarm Status |
| `POST` | `/api/swarm` | Run Swarm |

## Training Mode Sessions

Training Mode: named, long-lived Training episodes of many problems over many seeds (Training Mode Sessions), each with its own Episodic Memory that no route clears (never Metacat Mode's). A Training Mode Session is created Stopped and is started, paused, resumed, stopped and started again; problems can be added in any state; the database is written only at milestones (works with or without the parallel plugin).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/training-mode/sessions` | List Sessions |
| `POST` | `/api/training-mode/sessions` | Create Session |
| `GET` | `/api/training-mode/sessions/{session_id}` | Get Session |
| `PATCH` | `/api/training-mode/sessions/{session_id}` | Update Session |
| `DELETE` | `/api/training-mode/sessions/{session_id}` | Delete Session |
| `POST` | `/api/training-mode/sessions/{session_id}/cancel` | Cancel |
| `POST` | `/api/training-mode/sessions/{session_id}/changes` | Post Changes |
| `GET` | `/api/training-mode/sessions/{session_id}/configuration` | Session Configuration |
| `GET` | `/api/training-mode/sessions/{session_id}/configuration/diff` | Session Configuration Diff |
| `GET` | `/api/training-mode/sessions/{session_id}/export` | Export |
| `GET` | `/api/training-mode/sessions/{session_id}/finished` | Finished |
| `GET` | `/api/training-mode/sessions/{session_id}/journal` | Session Journal |
| `GET` | `/api/training-mode/sessions/{session_id}/memory` | Training Mode Session Memory |
| `POST` | `/api/training-mode/sessions/{session_id}/pause` | Pause |
| `GET` | `/api/training-mode/sessions/{session_id}/problems` | List Problems |
| `POST` | `/api/training-mode/sessions/{session_id}/problems` | Add Problems |
| `GET` | `/api/training-mode/sessions/{session_id}/problems/{problem_id}` | Get Problem |
| `POST` | `/api/training-mode/sessions/{session_id}/problems/{problem_id}/cancel` | Cancel Problem |
| `GET` | `/api/training-mode/sessions/{session_id}/problems/{problem_id}/runs` | Problem Runs |
| `POST` | `/api/training-mode/sessions/{session_id}/resume` | Resume |
| `GET` | `/api/training-mode/sessions/{session_id}/slipnet` | Session Slipnet |
| `POST` | `/api/training-mode/sessions/{session_id}/start` | Start |
| `POST` | `/api/training-mode/sessions/{session_id}/stop` | Stop |

## Episodic Memory

Metacat Mode: the Episodic Memory (Metacat-Mode learning) that each episodic run inherits from the runs before it, until it is cleared. Clearing is an event, recorded with an editable note. It is not Training Mode and is untouched by Training Mode Sessions.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/memory` | List Memory |
| `DELETE` | `/api/memory` | Clear Memory |
| `DELETE` | `/api/memory/answers/{answer_id}` | Forget Answer |
| `POST` | `/api/memory/answers/{answer_id}/display` | Display Answer |
| `GET` | `/api/memory/answers/{answer_id}/explanation` | Explain Answer |
| `GET` | `/api/memory/clears` | List Memory Clears |
| `PUT` | `/api/memory/clears/{clear_id}/note` | Set Memory Clear Note |
| `POST` | `/api/memory/compare` | Compare Answers |
| `POST` | `/api/memory/snags/{snag_id}/display` | Display Snag |

## Review

Metacat Mode: reading back what a Normal or Audit run recorded, and the episodic-run timeline: recorded runs with the Episodic Memory clears between them (Metacat Mode, not Training Mode).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/review/episodic-runs` | List Episodic Runs |
| `GET` | `/api/review/runs/{run_id}` | Get Recorded Run |
| `GET` | `/api/review/runs/{run_id}/actions` | List Actions |
| `GET` | `/api/review/runs/{run_id}/actions/summary` | Action Summary |
| `GET` | `/api/review/runs/{run_id}/captures` | List Captures |
| `GET` | `/api/review/runs/{run_id}/captures/{boundary}` | Get Capture |
| `GET` | `/api/review/runs/{run_id}/captures/{boundary}/raw` | Get Raw Capture |
| `GET` | `/api/review/runs/{run_id}/comparison` | Compare Run |
| `GET` | `/api/review/runs/{run_id}/inspector` | Inspector State |
| `POST` | `/api/review/runs/{run_id}/inspector` | Open Inspector |
| `DELETE` | `/api/review/runs/{run_id}/inspector` | Close Inspector |
| `POST` | `/api/review/runs/{run_id}/inspector/advance` | Advance Inspector |

## Configurations and the change API

Metacat Mode and Training Mode: one batch, `POST /api/configurations/{id}/changes`, is how configuration is written (the Admin editors, the Database tab, restore, reset, import, the external route and the in-worker learner submit the same batch); `GET .../schema` lists the tables, the ops and the shape of a batch. **Vocabulary.** `rename_enum_value` renames a row of an enum table or a theme relation and rewrites every column that names it: `posting_rules.direction`, `codelet_type_defs.family` and `.phase`, `slipnet_link_defs.link_type`, `engine_params.value_type`, `formula_coefficients.value_type`, `clamp_types.progress_focus`, `progress_focuses.event_types` and `theme_dimension_defs.valid_relations`, and the keys of the commentary sections keyed by the table's names; the row keeps its `role` (`behaviour` for `link_types`) and its place. Bodies, predicates, formulas, parameters and templates that still spell the old name are listed as `dangling` and left alone, as `rename_node` lists code. An urgency level rename also rewrites `clamp_types.codelet_background_level`. Deleting an enum row that holds a `role` (a `behaviour`, for `link_types`) is refused, `422 role_bound`: unbind it first by setting the column to null. A `role` must be a name of the table's vocabulary and held by one row (else `422 unknown_reference` or `422 role_taken`); an unbound row is allowed and inert, except that it becomes a valid value of the columns that name its table. **Episodic Memory.** A Training Mode Session's Episodic Memory persists names (theme types in theme patterns, rule and clause types in signatures, relations in concept patterns). The change API has one rule for every name the memory holds, a node or a vocabulary row alike: it neither refuses nor rewrites. The rename, removal or merge is carried out on the configuration, and the session's memory keeps the names it stored. **Parameters that name things.** `engine_params.refers_to` declares what a parameter's value names: `node_list`, `trigger_node_list`, `node_map`, `codelet_type_list`, `urgency_level` or null. Removing, renaming or merging a node edits every parameter that refers to nodes; a codelet type edit edits the `codelet_type_list` parameters; an urgency level edit lists the `urgency_level` parameters as `dangling`. A rule-trigger edit (`add_trigger`, `remove_trigger`) also changes the parameter whose `refers_to` is `trigger_node_list` (`top_down_slipnodes` in the Metacat Standard Configuration): the node is added to it, or removed from it only when no rule still triggers the node. A configuration that declares no such parameter leaves every parameter alone.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/configurations` | List Configurations |
| `GET` | `/api/configurations/compare` | Get Compare |
| `POST` | `/api/configurations/edits` | Post Edits |
| `POST` | `/api/configurations/edits/preview` | Post Edits Preview |
| `GET` | `/api/configurations/{configuration_id}` | Get Configuration |
| `PATCH` | `/api/configurations/{configuration_id}` | Patch Configuration |
| `POST` | `/api/configurations/{configuration_id}/apply-from` | Post Apply From |
| `GET` | `/api/configurations/{configuration_id}/as-of` | Get As Of |
| `POST` | `/api/configurations/{configuration_id}/changes` | Post Changes |
| `GET` | `/api/configurations/{configuration_id}/diff` | Get Diff |
| `GET` | `/api/configurations/{configuration_id}/export` | Get Export |
| `POST` | `/api/configurations/{configuration_id}/reset-to-standard` | Post Reset |
| `POST` | `/api/configurations/{configuration_id}/restore` | Post Restore |
| `POST` | `/api/configurations/{configuration_id}/restore-selected` | Post Restore Selected |
| `GET` | `/api/configurations/{configuration_id}/rows` | Get Rows |
| `GET` | `/api/configurations/{configuration_id}/schema` | Get Schema |
| `GET` | `/api/configurations/{configuration_id}/status` | Get Status |
| `GET` | `/api/configurations/{configuration_id}/verify-journal` | Get Verify Journal |

## Configuration

Metacat Mode: the editable copy of the seed data (the global configuration). A Training Mode Session copies it when created and never changes it.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/admin/codelets` | List Codelet Types |
| `POST` | `/api/admin/codelets` | Create Codelet Type |
| `PUT` | `/api/admin/codelets/{name}` | Update Codelet Type |
| `DELETE` | `/api/admin/codelets/{name}` | Delete Codelet Type |
| `GET` | `/api/admin/commentary-templates` | List Commentary Templates |
| `POST` | `/api/admin/commentary-templates` | Create Commentary Template |
| `PUT` | `/api/admin/commentary-templates/{template_id}` | Update Commentary Template |
| `DELETE` | `/api/admin/commentary-templates/{template_id}` | Delete Commentary Template |
| `POST` | `/api/admin/db/changes` | Apply a configuration edit as a journaled batch (channel admin_database) |
| `POST` | `/api/admin/db/edit` | Edit one content or runtime row (runtime needs expert mode) |
| `POST` | `/api/admin/db/sql` | Run one read-only SELECT or WITH statement |
| `GET` | `/api/admin/db/tables` | List every table with its class (Database tab) |
| `GET` | `/api/admin/db/tables/{name}/rows` | Page through a table's rows, with a filter |
| `GET` | `/api/admin/demos` | List Demos |
| `POST` | `/api/admin/demos` | Create Demo |
| `PUT` | `/api/admin/demos/{demo_id}` | Update Demo |
| `DELETE` | `/api/admin/demos/{demo_id}` | Delete Demo |
| `GET` | `/api/admin/enums` | List Enum Tables |
| `GET` | `/api/admin/enums/{table}` | List Enum Values |
| `POST` | `/api/admin/enums/{table}` | Create Enum Value |
| `PUT` | `/api/admin/enums/{table}/{name}` | Update Enum Value |
| `DELETE` | `/api/admin/enums/{table}/{name}` | Delete Enum Value |
| `POST` | `/api/admin/enums/{table}/{name}/rename` | Rename Enum Value |
| `GET` | `/api/admin/export` | Export Metadata |
| `GET` | `/api/admin/formula-coefficients` | List Formula Coefficients |
| `POST` | `/api/admin/formula-coefficients` | Create Formula Coefficient |
| `PUT` | `/api/admin/formula-coefficients/{name}` | Update Formula Coefficient |
| `DELETE` | `/api/admin/formula-coefficients/{name}` | Delete Formula Coefficient |
| `GET` | `/api/admin/help-topics` | List Help Topics |
| `POST` | `/api/admin/help-topics` | Create Help Topic |
| `PUT` | `/api/admin/help-topics/{topic_id}` | Update Help Topic |
| `DELETE` | `/api/admin/help-topics/{topic_id}` | Delete Help Topic |
| `POST` | `/api/admin/help/regenerate` | Regenerate Help Docs |
| `POST` | `/api/admin/import` | Import Metadata |
| `GET` | `/api/admin/params` | List Params |
| `POST` | `/api/admin/params` | Create Param |
| `PUT` | `/api/admin/params/{name}` | Update Param |
| `DELETE` | `/api/admin/params/{name}` | Delete Param |
| `GET` | `/api/admin/posting-rules` | List Posting Rules |
| `POST` | `/api/admin/posting-rules` | Create Posting Rule |
| `PUT` | `/api/admin/posting-rules/{rule_id}` | Update Posting Rule |
| `DELETE` | `/api/admin/posting-rules/{rule_id}` | Delete Posting Rule |
| `GET` | `/api/admin/slipnet-layout` | List Slipnet Layout |
| `POST` | `/api/admin/slipnet-layout` | Create Slipnet Layout |
| `PUT` | `/api/admin/slipnet-layout/{node_name}` | Update Slipnet Layout |
| `DELETE` | `/api/admin/slipnet-layout/{node_name}` | Delete Slipnet Layout |
| `GET` | `/api/admin/slipnet/links` | List Slipnet Links |
| `POST` | `/api/admin/slipnet/links` | Create Slipnet Link |
| `PUT` | `/api/admin/slipnet/links/{link_id}` | Update Slipnet Link |
| `DELETE` | `/api/admin/slipnet/links/{link_id}` | Delete Slipnet Link |
| `GET` | `/api/admin/slipnet/nodes` | List Slipnet Nodes |
| `POST` | `/api/admin/slipnet/nodes` | Create Slipnet Node |
| `PUT` | `/api/admin/slipnet/nodes/{name}` | Update Slipnet Node |
| `DELETE` | `/api/admin/slipnet/nodes/{name}` | Delete Slipnet Node |
| `GET` | `/api/admin/theme-dimensions` | List Theme Dimensions |
| `POST` | `/api/admin/theme-dimensions` | Create Theme Dimension |
| `PUT` | `/api/admin/theme-dimensions/{dim_id}` | Update Theme Dimension |
| `DELETE` | `/api/admin/theme-dimensions/{dim_id}` | Delete Theme Dimension |
| `GET` | `/api/admin/urgency-levels` | List Urgency Levels |
| `POST` | `/api/admin/urgency-levels` | Create Urgency Level |
| `PUT` | `/api/admin/urgency-levels/{name}` | Update Urgency Level |
| `DELETE` | `/api/admin/urgency-levels/{name}` | Delete Urgency Level |

## Help

In-app help topics, the glossary and search.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/docs/codelets/{name}` | Codelet Help |
| `GET` | `/api/docs/components/{name}` | Component Help |
| `GET` | `/api/docs/concepts/{name}` | Concept Help |
| `GET` | `/api/docs/glossary` | List Glossary |
| `GET` | `/api/docs/glossary/{term}` | Glossary Help |
| `GET` | `/api/docs/search` | Search Docs |

## System

What the process resolved at startup.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/system/numeric` | Numeric Substrate |

## Other

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/journal` | Get Journal |
| `POST` | `/api/journal/check-names` | Check Names |
| `GET` | `/api/journal/where-did-name-go` | Where Did Name Go |
| `GET` | `/api/journal/{entry_id}` | Get Journal Entry |
| `GET` | `/healthz` | Healthz |
