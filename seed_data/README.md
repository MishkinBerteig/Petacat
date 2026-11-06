# The Metacat Standard Configuration

The JSON files in this directory are the **Metacat Standard Configuration**: Metacat's own domain
knowledge as Petacat ports it. It is not a mode and not a database. It is the starting content of one.

| File | Contents |
|------|----------|
| `slipnet_nodes.json`, `slipnet_links.json`, `slipnet_layout.json` | The Slipnet's concepts and links, and the grid positions for drawing it |
| `codelet_types.json` | The codelet types, with their Python `execute_body` source |
| `roles.json` | The roles the engine looks nodes and codelet types up by, including the policy sets (which dimensions behave a way) and the image operation each dimension performs: see [Policy roles](#policy-roles) |
| `initial_program.json` | What a run starts with: the descriptions every letter is given and the concepts that start fully active: see [The initial-description program](#the-initial-description-program) |
| `engine_params.json`, `urgency_levels.json`, `formula_coefficients.json` | Parameters, urgency bins and formula coefficients (stored as exact rationals such as `2/3`). Every fixed number that decides a strength, an unhappiness, a clip, an exponent or a rule's cost is a coefficient here, in the form (int or float) the engine used |
| `engine_param_refs.json` | What a parameter's value names (`engine_params.refers_to`): see [Parameters that name things](#parameters-that-name-things) |
| `theme_dimensions.json`, `theme_relations.json` | The Themespace's dimensions and relations |
| `posting_rules.json` | Which codelets are posted, and when; a rule's `urgency_level` names a tier of `urgency_levels` |
| `commentary_templates.json` | The natural-language commentary and Verbose mode's message texts |
| `demo_problems.json` | The pre-configured analogy problems |
| `enums.json` | The 18 enum tables (bridge types, proposal levels, link types, clamp types, and the rest), with the `role` column that binds a row to the engine's vocabulary: see [The role vocabulary](#the-role-vocabulary). Three of them (`string_kinds`, `bridge_types`, `rule_types`) also define the four-string frame: see [The four-string frame](#the-four-string-frame) |
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

Seven tables have other columns than the common four (`name`, `display_label`, `sort_order`,
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
- **`string_kinds.exists_at_start`**, **`bridge_types.from_string_kind`**, **`to_string_kind`**,
  **`orientation`**, **`theme_type`** and **`rule_types.bridge_type`** define the four-string frame:
  see [The four-string frame](#the-four-string-frame).

Renaming a row rewrites every column that names it (`posting_rules.direction`, `codelet_type_defs.family`
and `.phase`, `slipnet_link_defs.link_type`, `engine_params.value_type`, `formula_coefficients.value_type`,
`clamp_types.progress_focus`, `progress_focuses.event_types`, `theme_dimension_defs.valid_relations`,
`bridge_types.from_string_kind`, `.to_string_kind`, `.orientation` and `.theme_type`, `rule_types.bridge_type`,
the commentary sections keyed by the table's names) and lists the code, parameters and templates that still
spell the old name. A codelet body, descriptor predicate or posting formula should write `role('bridge_type.top')`
rather than the name, so that a rename needs no edit to it.

## The four-string frame

A problem has four strings (`initial`, `modified`, `target` and, once an answer exists, `answer`) and bridges
between them. Which bridge type joins which pair of strings, which theme type it feeds, in which orientation,
and which rule type describes which pair decide what every object is asked to map to, which themes a
description speaks for and what a rule is a rule about, so they are configuration, defined **once**, in three
tables of `enums.json`. `server/engine/frame.py` derives everything else from them, once per run
(`RunConstants.frame`, resolved when the run is created), and no other code of the engine spells the pairing.

| Column | Says |
|---|---|
| `string_kinds.exists_at_start` | whether a string of this kind is there from the start of a run (`answer` is not: it exists once an answer is found or supplied). `sort_order` is the kind's place in the table |
| `bridge_types.from_string_kind`, `to_string_kind` | the two kinds of string a bridge of this type joins (names of `string_kinds` rows) |
| `bridge_types.orientation` | `horizontal` (two strings of one analogy) or `vertical` (the two analogies); a name of a `bridge_orientations` row |
| `bridge_types.theme_type` | the `theme_types` row the bridges of this type feed |
| `rule_types.bridge_type` | the bridge type whose pair of strings a rule of this type describes |

From these the frame derives (`Frame` in `engine/frame.py`):

- what each kind of string **maps**: in an orientation when a bridge type of that orientation ends in it and the
  string at the other end exists from the start; the horizontal orientation **needs justification** when the
  string at the other end does not (the target string reaches the answer string only when the run justifies);
- `get-other-string`: the string across the bridge type (or orientation) the key names, and, when none ends in the
  string, across its last bridge type in table order (Metacat's `else` branch);
- the theme types of a description of an object in a string of each kind, the theme types of each mode (the bridge
  types whose strings all exist at the start, or all of them when justifying), and the maps between a bridge type
  and the theme type it feeds;
- which pair of strings a rule type describes, whether it is checked only when justifying, which kinds a rule
  translated *from* goes down from (the top rule's pair), and the bridge a translated rule's supporting bridges belong to;
- the code the numeric backends branch on for each kind (`numeric/layout.py`: both ways, horizontal only, or
  vertical with horizontal when justifying).

The engine's own **attribute names** (`top_bridges`, `initial_string`, `top_mapping_strength` ...) are Python
names the engine owns; `frame.py` maps the *role* of a row to them. The roles `string_kind.*`, `bridge_type.*`,
`bridge_orientation.*` and `rule_type.*` are **required** (`REQUIRED_VOCABULARY_ROLES`): a run cannot start
without them, because the frame is derived from their rows. A bridge type that names a string kind that does not
exist, or a rule type that names a bridge type that does not exist, also stops a run at its start (`RunStartError`).
Multi-turn runs (v2.0) will need a different frame between turns; nothing is built for that, and the frame is one
record built from the provider, so a run that changes configuration between turns builds another.

## The initial-description program

A structure's **first descriptions** are cognition: which descriptions, in which order, decide every
stochastic description pick and every bridge's theme cross-product. Dropping the middle-of-an-odd-string
description changes 40 of 48 runs. So they are rows, in `initial_program.json`, applied by
`server/engine/initial_program.py`. There are two tables:

- `initial_activation_rules` (`rule_key`, `ordinal`, `node_role`, `condition`): the node bound to `node_role` is
  made fully active (its `max_activation`) when `condition` holds, before the descriptions, in `ordinal` order.
  The Standard Configuration has one: the concept of object-category when some string of the problem has one
  letter (`run.ss:221-226`).
- `initial_description_rules` (`rule_key`, `ordinal`, `subject`, `dimension_role`, `descriptor_source`,
  `descriptor_role`, `condition`, `activate_descriptor`, `built`, `bond_description`): one row shape serves
  every structure whose first descriptions are a program (one mechanism, one table: the rows differ only in
  what they describe, `subject`, and so in which conditions and sources they may name). A rule gives the
  structure a description of type `dimension_role`'s node and descriptor `descriptor_role`'s node
  (`descriptor_source` `role`), or the descriptor the source names, when `condition` holds. The rules of a
  subject are applied **in `ordinal` order** and each description goes to the **front** of the structure's list
  (of its bond descriptions when `bond_description`), so the last rule is first. `activate_descriptor` makes the
  descriptor fully active (`run.ss:227-232`); `built` makes the description at the built level.

| `subject` | Describes | Rows in the Standard Configuration |
|---|---|---|
| `letter` | every letter of the problem's strings, at the start of a run (`make-letter`, `init-mcat`) | object-category (descriptor `object.letter`), letter-category (the letter's own), then the string-position descriptions `single`, `leftmost`, `rightmost`, `middle`; all built and activated |
| `group` | every new group (`make-group`, `groups.ss:20-54`) | object-category (`object.group`), group category, bond category (a bond description), direction, the position cascade whole, leftmost, middle, rightmost, bond facet (a bond description), and the letter category of a letter-category facet; built, not activated |
| `translated_letter` | the letters of a string built from a rule after the start (`make-translated-string`), when the letter has no description of the type yet | object-category (`object.letter`), letter-category; not built, not activated |

A rule whose dimension or fixed descriptor no node holds is dropped (what has no node is not perceived); a
descriptor that is empty for a structure (a group with no direction) is skipped. The **conditions and sources
are closed sets the engine owns**, as the count-formula kinds are, with fixed arithmetic. A subject, condition
or source outside its set stops a run at its start (`RunStartError`, and the change API reports it):

| Subject | Condition | Holds when |
|---|---|---|
| `letter` (a letter of a string of `n` letters) | `always` | always |
| | `single` | `n == 1` |
| | `leftmost` | `n != 1` and the letter is the first |
| | `rightmost` | `n != 1` and the letter is the last |
| | `middle` | `n != 1`, `n` is odd and the letter is at index `n // 2` |
| `group` | `always` | always |
| | `has_direction` | the group has a direction (a sameness group has none) |
| | `whole` | the group spans its whole string |
| | `leftmost` | not `whole`, and the group is leftmost in its string |
| | `middle` | not `whole` or `leftmost`, and the group is in the middle of its string |
| | `rightmost` | not `whole`, `leftmost` or `middle`, and the group is rightmost (the cascade of `groups.ss:34-42`: a group has the first position that holds) |
| | `facet_is_letter_category` | the group's bond facet is the letter-category dimension |
| `translated_letter` | `always` | always |
| activations | `always` | always |
| | `any_single_letter_string` | some string of the problem has one letter |

| Source | Is |
|---|---|
| `role` | the node `descriptor_role` names |
| `letter_category` | the letter's own letter-category node (`letter`, `translated_letter`) |
| `group_category`, `bond_category`, `direction`, `bond_facet` | the group's own (`group`) |
| `initial_letter_category` | the letter category of the group's first object in direction order (`groups.ss:47`) |

The three position conditions of a letter are never true together for one letter, so reordering them changes
nothing; any of them against letter-category or object-category does. Not moved, with the reason in
`POLICY.tsv`: the Length description a group may get in `propose-group` (a computed descriptor under a
probability), a duplicate group's transfer of descriptions, and the fake object a translated rule copies; none
is a first-description program.

## Policy roles

`roles.json` binds roles to nodes. A role that names one concept (`dimension.length`) is bound to one node. The
roles below are **sets** (ordered roles, with a binding per member; the order is not read) or **bindings of an
operation**: a branch of the engine reads the set, so which nodes behave a way is configuration. The branch
stays in the engine; the list it reads is here.

| Role | The nodes bound are... | Standard Configuration |
|---|---|---|
| `dimension.ladder` | dimensions whose descriptors lie on a successor / predecessor ladder: a concept mapping between two of them looks for its link among the lateral links, and a slippage on one is exempt from bridge compatibility | letter category, length |
| `dimension.reverses_together` | dimensions that reverse together when a group is re-read backwards | direction, bond category, group category |
| `dimension.bond_description` | dimensions that describe a bond (a group's bond descriptions, a bond concept mapping) | bond category, bond facet |
| `dimension.freely_mappable` | dimensions on which two descriptions are mappable whatever their descriptors | string position, length |
| `bond_category.symmetric` | bond categories whose bonds are symmetric (filed under both ends, found whichever way round they are asked for) | sameness |
| `group_category.directed` | group categories whose groups have a direction | successor group, predecessor group |
| `descriptor.generic` | descriptors that never tell an object apart from its string (besides the numbers) | letter, group |
| `rule.object_naming_dimension` | dimensions a rule may name an object by (letter category is also allowed, conditionally) | string position, alphabetic position |
| `rule.letter_or_alphabetic_dimension` | dimensions of an intrinsic change that are alphabetic | letter category, alphabetic position |
| `rule.relation_only_dimension` | dimensions whose change keeps the relation only, never a literal descriptor | direction, group category |
| `rule.apply_first` | dimensions whose transform is applied before every other (`apply-before?`, `rules.ss:1395-1403`) | group category |
| `rule.apply_by_length` | dimensions whose transform goes first or last by how the image's length changes | length |
| `image_operation.letter_or_group`, `.new_start_letter`, `.new_length`, `.reverse_direction`, `.reverse_medium`, `.new_alpha_position_category` | the dimension that performs this image operation when a rule transforms an image (`transform-image`, `rules.ss:1366-1388`); a dimension bound to none makes no change; `reverse_medium` also reads `new_start_letter` and `new_length` for the medium it reverses along | object category, letter category, length, direction, group category, alphabetic position |

No role is required: a role nothing holds is a set with no member (the behaviour does not happen), or an operation
no dimension performs. The other roles (`dimension.*`, `position.*`, `direction.*`, `object.*`, `bond_category.*`,
`group_category.*`, `alphabet.*`) name one concept each; a comparison against one is the engine saying *that
concept*, not a policy, and the configuration says which node it is. `rule.dimension_order` and
`answer.description_dimension` are ordered lists the order of which is read.

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
