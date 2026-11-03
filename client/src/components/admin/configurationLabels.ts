// ---------------------------------------------------------------------------
// The wording of a configuration's mode, state and header chip (configuration plan 3.10.2, 3.16.2)
// ---------------------------------------------------------------------------
//
// One place, so the manager's list, the header chip and the tests say the same thing.
// "Metacat Mode" and "Training Mode" are proper names: no label says "mode" without one.

import type { ConfigurationSummary } from '@/types/configuration'

export const METACAT_MODE = 'Metacat Mode'
export const TRAINING_MODE = 'Training Mode'

/** Badge colours by mode (not the persistence-mode colours of `ModeBadge`). */
export const BADGE_COLORS: Record<string, string> = {
  [METACAT_MODE]: 'rgba(76,175,80,0.28)',
  [TRAINING_MODE]: 'rgba(171,71,188,0.28)',
}

export const isLive = (c: ConfigurationSummary) => c.source === 'live'

/** A session in these states is changing state: its editors are read-only (3.16.2). */
export const isChangingState = (c: ConfigurationSummary) =>
  c.session_state === 'starting' || c.session_state === 'stopping'

const when = (iso: string | null | undefined) => {
  if (!iso) return 'unknown time'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

/**
 * The mode badge of 3.10.2: "Metacat Mode", or "Training Mode: <name>, <state>"; a live session
 * adds ", live, saved through revision R, N unsaved batches".
 */
export function badgeText(c: ConfigurationSummary): string {
  if (c.kind === 'global') return METACAT_MODE
  const base = `${TRAINING_MODE}: ${c.session_name ?? c.name}, ${c.session_state ?? 'stopped'}`
  if (!isLive(c)) return base
  const n = c.unsaved ?? 0
  return `${base}, live, saved through revision ${c.saved_through ?? 0}, ${n} unsaved ${n === 1 ? 'batch' : 'batches'}`
}

/** The mode a badge belongs to, for the filter. */
export const badgeMode = (c: ConfigurationSummary) => (c.kind === 'global' ? METACAT_MODE : TRAINING_MODE)

/** "Live (in memory)" or "Stored (as of last stop)": the label of 3.16.2 for a session's view. */
export function sourceLabel(c: ConfigurationSummary): string | null {
  if (c.kind === 'global') return null
  return isLive(c) ? 'Live (in memory)' : 'Stored (as of last stop)'
}

/** The persistent header chip (exact strings of 3.10.2 and 3.16.2). */
export function chipText(c: ConfigurationSummary): string {
  if (c.kind === 'global') {
    return `Editing: ${METACAT_MODE} global configuration. This does not affect any session`
  }
  const name = c.session_name ?? c.name
  const state = c.session_state ?? 'stopped'
  const head = `Editing: ${TRAINING_MODE} Session '${name}' (${state}).`
  if (state === 'starting' || state === 'stopping') {
    return `${head} This session is changing state: the editors are read-only until it has finished.`
  }
  if (isLive(c)) {
    return `${head} Changes are held in memory and saved when the session is stopped. `
      + `The database shows the state as of its last stop (revision ${c.saved_through ?? 0}, ${when(c.saved_at)}).`
  }
  return `${head} Changes are saved at once. This does not affect ${METACAT_MODE}.`
}

/** What the chip says before the configuration's summary has arrived (or if it never does). */
export function fallbackChipText(configuration: number): string {
  if (configuration === 1) {
    return `Editing: ${METACAT_MODE} global configuration. This does not affect any session`
  }
  return `Editing: ${TRAINING_MODE} Session configuration ${configuration}. This does not affect ${METACAT_MODE}.`
}
