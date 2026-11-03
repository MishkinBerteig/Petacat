// ---------------------------------------------------------------------------
// Petacat -- the names an Episodic Memory holds (what the "names that no longer resolve" panel checks)
// ---------------------------------------------------------------------------

interface MemoryLike {
  answers?: object[]
  snags?: object[]
}

const THEME_FIELDS = ['themes', 'top_themes', 'vertical_themes', 'bottom_themes', 'unjustified_themes']

function addPattern(into: Set<string>, pattern: unknown): void {
  if (!pattern || typeof pattern !== 'object') return
  for (const [dimension, relation] of Object.entries(pattern as Record<string, unknown>)) {
    into.add(dimension)
    if (typeof relation === 'string') into.add(relation)
  }
}

/**
 * Every node and theme-relation name in a memory's theme patterns, sorted: each answer's
 * four theme patterns (dimension node to relation) and each snag's theme pattern.
 */
export function memoryNames(memory: MemoryLike | null | undefined): string[] {
  const names = new Set<string>()
  for (const a of (memory?.answers ?? []) as Array<Record<string, unknown>>) {
    for (const f of THEME_FIELDS) addPattern(names, a[f])
  }
  for (const s of (memory?.snags ?? []) as Array<Record<string, unknown>>) addPattern(names, s.theme_pattern)
  return [...names].filter(n => n !== '').sort()
}
