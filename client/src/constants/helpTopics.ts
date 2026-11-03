// -------------------------------------------------------------------
// Petacat — Help topic key constants
// -------------------------------------------------------------------
//
// AUTO-GENERATED from seed_data/help_topics.en.json by
// scripts/generate_help_docs.py (or the admin Regenerate Help
// endpoint / backend lifespan startup). Do NOT edit by hand --
// changes will be lost on the next regeneration. To add or change
// help topics, edit the JSON and re-run the generator.
//
// -------------------------------------------------------------------

/** Every topic_key for topic_type='component'. */
export const COMPONENT_HELP_KEYS = [
  'admin',
  'admin_clear_memory',
  'admin_full_reset',
  'admin_regenerate_help',
  'change_api',
  'coderack',
  'commentary',
  'configuration',
  'configuration_journal',
  'configuration_manager',
  'database_tab',
  'edit_scope',
  'eeg',
  'memory',
  'metacat_standard_configuration',
  'modes',
  'problem_input',
  'review',
  'run_controls',
  'run_history',
  'session',
  'session_add_problems',
  'session_configuration_tab',
  'session_error_policy',
  'session_export',
  'session_external_route',
  'session_learning_sources',
  'session_new',
  'session_problem_text',
  'session_problems_table',
  'session_run_state',
  'session_seeds',
  'slipnet',
  'starting_conceptual_state',
  'swarm',
  'swarm_first_seed',
  'swarm_max_steps',
  'swarm_run',
  'swarm_seed_count',
  'temperature',
  'themespace',
  'trace',
  'training_mode_session_memory',
  'verbose',
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
  'episodic_runs',
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
  'update_cycle',
  'urgency',
  'windows_menu',
  'workspace_structure',
] as const;

export type GlossaryHelpKey = (typeof GLOSSARY_HELP_KEYS)[number];

/** Union of every known help topic key (component or glossary). */
export type HelpTopicKey = ComponentHelpKey | GlossaryHelpKey;
