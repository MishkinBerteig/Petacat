# Petacat API

> **Auto-generated.** Run `python scripts/generate_api_docs.py` to regenerate from the FastAPI application.

127 HTTP routes, plus `WS /ws/runs/{run_id}` for live state push.

Interactive documentation is served at `/docs` while the API is running.

## Runs

Creating, driving and reading a run.

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
| `POST` | `/api/runs/{run_id}/clamp-themes` | Clamp Themes |
| `DELETE` | `/api/runs/{run_id}/clamp-themes` | Unclamp Themes |
| `GET` | `/api/runs/{run_id}/codelet-patterns` | List Codelet Patterns |
| `GET` | `/api/runs/{run_id}/coderack` | Get Coderack |
| `GET` | `/api/runs/{run_id}/commentary` | Get Commentary |
| `GET` | `/api/runs/{run_id}/identity` | Get Run Identity |
| `GET` | `/api/runs/{run_id}/memory` | Get Memory |
| `GET` | `/api/runs/{run_id}/parameters` | Get Run Parameters |
| `POST` | `/api/runs/{run_id}/reset` | Reset Run |
| `POST` | `/api/runs/{run_id}/run` | Run To Completion |
| `GET` | `/api/runs/{run_id}/slipnet` | Get Slipnet |
| `GET` | `/api/runs/{run_id}/spreading-threshold` | Get Spreading Threshold |
| `POST` | `/api/runs/{run_id}/spreading-threshold` | Set Spreading Threshold |
| `POST` | `/api/runs/{run_id}/step` | Step Run |
| `PUT` | `/api/runs/{run_id}/step-size` | Set Step Size |
| `POST` | `/api/runs/{run_id}/stop` | Stop Run |
| `GET` | `/api/runs/{run_id}/telemetry` | Get Run Telemetry |
| `GET` | `/api/runs/{run_id}/temperature` | Get Temperature |
| `GET` | `/api/runs/{run_id}/themespace` | Get Themespace |
| `POST` | `/api/runs/{run_id}/themespace/restore` | Restore Themespace |
| `GET` | `/api/runs/{run_id}/trace` | Get Trace |
| `GET` | `/api/runs/{run_id}/trace/export` | Export Trace |
| `GET` | `/api/runs/{run_id}/trace/{event_number}` | Get Trace Event |
| `POST` | `/api/runs/{run_id}/trace/{event_number}/display` | Display Trace Event |
| `GET` | `/api/runs/{run_id}/workspace` | Get Workspace |

## Episodic Memory

The Training Session's memory, shared by every run.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/memory` | List Memory |
| `DELETE` | `/api/memory` | Clear Memory |
| `DELETE` | `/api/memory/answers/{answer_id}` | Forget Answer |
| `POST` | `/api/memory/answers/{answer_id}/display` | Display Answer |
| `GET` | `/api/memory/answers/{answer_id}/explanation` | Explain Answer |
| `POST` | `/api/memory/compare` | Compare Answers |

## Review

Reading back what a Normal or Audit run recorded.

| Method | Path | Purpose |
|---|---|---|
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
| `GET` | `/api/review/sessions` | List Sessions |
| `GET` | `/api/review/sessions/{session_id}` | Get Session Runs |
| `PUT` | `/api/review/sessions/{session_id}/note` | Set Session Note |

## Configuration

The editable copy of the seed data.

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
| `GET` | `/api/admin/demos` | List Demos |
| `POST` | `/api/admin/demos` | Create Demo |
| `PUT` | `/api/admin/demos/{demo_id}` | Update Demo |
| `DELETE` | `/api/admin/demos/{demo_id}` | Delete Demo |
| `GET` | `/api/admin/enums` | List Enum Tables |
| `GET` | `/api/admin/enums/{table}` | List Enum Values |
| `POST` | `/api/admin/enums/{table}` | Create Enum Value |
| `PUT` | `/api/admin/enums/{table}/{name}` | Update Enum Value |
| `DELETE` | `/api/admin/enums/{table}/{name}` | Delete Enum Value |
| `GET` | `/api/admin/export` | Export Metadata |
| `POST` | `/api/admin/export-to-seed-data` | Export To Seed Data |
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
| `POST` | `/api/admin/reload` | Reload Metadata |
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
| `GET` | `/healthz` | Healthz |
