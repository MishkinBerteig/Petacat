// -------------------------------------------------------------------
// Petacat — Help topic key constants
// -------------------------------------------------------------------
//
// AUTO-GENERATED from seed_data/help_topics.{locale}.json by
// scripts/generate_help_docs.py (or the admin Regenerate Help
// endpoint / backend lifespan startup). Do NOT edit by hand --
// changes will be lost on the next regeneration. To add or change
// help topics, edit the JSON and re-run the generator.
//
// Locale: en
// -------------------------------------------------------------------

/** Every topic_key for topic_type='component'. */
export const COMPONENT_HELP_KEYS = [
  'admin',
  'admin_clear_memory',
  'admin_full_reset',
  'admin_regenerate_help',
  'coderack',
  'commentary',
  'memory',
  'problem_input',
  'review',
  'run_controls',
  'run_history',
  'slipnet',
  'temperature',
  'themespace',
  'trace',
  'workspace',
] as const;

export type ComponentHelpKey = (typeof COMPONENT_HELP_KEYS)[number];

/** Every topic_key for topic_type='glossary'. */
export const GLOSSARY_HELP_KEYS = [
  'activation',
  'bond',
  'bond_category',
  'bond_facet',
  'bridge',
  'clamping',
  'codelet',
  'concept_mapping',
  'conceptual_depth',
  'description',
  'deterministic_replay',
  'direction',
  'free_running',
  'group_category',
  'jootsing',
  'numeric_substrate',
  'persistence_mode',
  'proposal_level',
  'rule',
  'run_parameters',
  'salience',
  'slippage',
  'snag',
  'spanning_group',
  'temperature_glossary',
  'theme',
  'training_session',
  'update_cycle',
  'urgency',
  'workspace_structure',
] as const;

export type GlossaryHelpKey = (typeof GLOSSARY_HELP_KEYS)[number];

/** Union of every known help topic key (component or glossary). */
export type HelpTopicKey = ComponentHelpKey | GlossaryHelpKey;
