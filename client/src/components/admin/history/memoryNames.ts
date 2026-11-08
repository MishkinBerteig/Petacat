// ---------------------------------------------------------------------------
// Petacat -- the names an Episodic Memory holds (what the "names that no longer resolve" panel checks)
// ---------------------------------------------------------------------------

interface MemoryLike {
  answers?: object[]
  snags?: object[]
}

/**
 * The vocabulary names a memory record holds besides theme patterns: the clause types its rule
 * signatures name (`clause_types`, which the server lists from the stored signatures). A theme
 * type or a rule type is not stored in a memory, so no record carries one.
 */
function addClauseTypes(into: Set<string>, record: Record<string, unknown>): void {
  const types = record.clause_types
  if (!Array.isArray(types)) return
  for (const t of types) if (typeof t === 'string') into.add(t)
}

const THEME_FIELDS = ['themes', 'top_themes', 'vertical_themes', 'bottom_themes', 'unjustified_themes']

function addPattern(into: Set<string>, pattern: unknown): void {
  if (!pattern || typeof pattern !== 'object') return
  // The unjustified pattern is a list of [dimension, relation] entries; the others are mappings.
  const pairs: Array<[unknown, unknown]> = Array.isArray(pattern)
    ? (pattern as unknown[]).filter(Array.isArray).map(e => [e[0], e[1]] as [unknown, unknown])
    : Object.entries(pattern as Record<string, unknown>)
  for (const [dimension, relation] of pairs) {
    if (typeof dimension === 'string') into.add(dimension)
    if (typeof relation === 'string') into.add(relation)
  }
}

/**
 * Every node, theme-relation and clause-type name in a memory, sorted: each answer's four
 * theme patterns (dimension node to relation), each snag's theme pattern, and the clause
 * types of the rule signatures an answer or a snag stores.
 */
export function memoryNames(memory: MemoryLike | null | undefined): string[] {
  const names = new Set<string>()
  for (const a of (memory?.answers ?? []) as Array<Record<string, unknown>>) {
    for (const f of THEME_FIELDS) addPattern(names, a[f])
    addClauseTypes(names, a)
  }
  for (const s of (memory?.snags ?? []) as Array<Record<string, unknown>>) {
    addPattern(names, s.theme_pattern)
    addClauseTypes(names, s)
  }
  return [...names].filter(n => n !== '').sort()
}
