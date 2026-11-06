// The Metacat Standard Configuration's bindings, as the server publishes them
// (`server/services/vocabulary_payload.py`): every role bound to the name Metacat uses.
// `setup.ts` installs this before each test; a test of a renamed binding calls
// `useVocabularyStore.getState().adopt(renamed(...))` itself.

import type { VocabularyPayload } from '@/store/vocabulary';

const ROLES: Record<string, string[]> = {
  event_type: [
    'bond_built', 'bond_broken', 'group_built', 'group_broken', 'bridge_built', 'bridge_broken',
    'rule_built', 'rule_broken', 'description_built', 'answer_found', 'snag', 'clamp_start',
    'clamp_end', 'concept_mapping_built', 'concept_activation',
  ],
  bridge_type: ['top', 'bottom', 'vertical'],
  bridge_orientation: ['horizontal', 'vertical'],
  clause_type: ['intrinsic', 'extrinsic', 'verbatim'],
  rule_type: ['top', 'bottom'],
  theme_type: ['top_bridge', 'bottom_bridge', 'vertical_bridge'],
  proposal_level: ['proposed', 'evaluated', 'built'],
  posting_direction: ['bottom_up', 'top_down', 'thematic'],
  theme_relation: ['identity', 'opposite', 'successor', 'predecessor', 'diff'],
  string_kind: ['initial', 'modified', 'target', 'answer'],
  rule_scope: ['self', 'subobjects'],
  failure_kind: ['swap', 'conflict', 'change'],
};

export const STANDARD_VOCABULARY: Record<string, string> = Object.fromEntries([
  ...Object.entries(ROLES).flatMap(([kind, names]) => names.map((n) => [`${kind}.${n}`, n])),
  ['clamp_type.rule_codelet', 'rule_codelet_clamp'],
  ['clamp_type.snag_response', 'snag_response_clamp'],
  ['clamp_type.justify', 'justify_clamp'],
  ['clamp_type.manual', 'manual_clamp'],
]);

export const STANDARD_LINK_BEHAVIOURS: Record<string, string | null> = {
  category: 'category',
  instance: 'instance',
  property: 'property',
  lateral: 'lateral',
  lateral_sliplink: 'slip',
};

export const STANDARD_PAYLOAD: VocabularyPayload = {
  vocabulary: STANDARD_VOCABULARY,
  link_behaviours: STANDARD_LINK_BEHAVIOURS,
};

/** The standard payload with some roles bound to other names (a renamed configuration). */
export function renamed(
  roles: Record<string, string>,
  linkTypes: Record<string, string> = {},
): VocabularyPayload {
  const links: Record<string, string | null> = {};
  for (const [name, behaviour] of Object.entries(STANDARD_LINK_BEHAVIOURS)) {
    links[linkTypes[name] ?? name] = behaviour;
  }
  return { vocabulary: { ...STANDARD_VOCABULARY, ...roles }, link_behaviours: links };
}
