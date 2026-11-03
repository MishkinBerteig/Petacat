// ---------------------------------------------------------------------------
// Petacat -- the History views' calls
// ---------------------------------------------------------------------------

import { request } from '@/api/client'
import type {
  CheckNamesReply, DryRunReport, JournalEntry, JournalFilters, JournalPage, NameStory, RestoreReply,
} from './types'

function query(params: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(typeof v === 'object' ? JSON.stringify(v) : String(v))}`)
  }
  return parts.length ? `?${parts.join('&')}` : ''
}

export function getJournal(filters: JournalFilters): Promise<JournalPage> {
  return request<JournalPage>(`/journal${query({ ...filters })}`)
}

export function getJournalEntry(id: number): Promise<JournalEntry> {
  return request<JournalEntry>(`/journal/${id}`)
}

/** A pending entry has no id: its bodies come from the list, one revision, with detail. */
export async function getPendingEntry(configurationId: number, revision: number): Promise<JournalEntry | null> {
  const page = await getJournal({
    configuration_id: configurationId, revision_from: revision, revision_to: revision, detail: true,
  })
  return page.entries.find(e => e.revision === revision) ?? null
}

export function whereDidNameGo(name: string, configurationId: number): Promise<NameStory> {
  return request<NameStory>(`/journal/where-did-name-go${query({ name, configuration_id: configurationId })}`)
}

export function checkNames(configurationId: number, names: string[]): Promise<CheckNamesReply> {
  return request<CheckNamesReply>('/journal/check-names', {
    method: 'POST', body: JSON.stringify({ configuration_id: configurationId, names }),
  })
}

function restore(configurationId: number, body: Record<string, unknown>): Promise<RestoreReply> {
  return request<RestoreReply>(`/configurations/${configurationId}/restore`, {
    method: 'POST', body: JSON.stringify(body),
  })
}

export const restoreEntity = (
  configurationId: number, table: string, key: Record<string, unknown>, asOfRevision: number, note = '',
) => restore(configurationId, { entity: { table, key }, as_of_revision: asOfRevision, note })

export const undoBatch = (configurationId: number, entryId: number, note = '') =>
  restore(configurationId, { undo_batch: entryId, note })

export const undoGroup = (configurationId: number, groupId: string, note = '') =>
  restore(configurationId, { undo_group: groupId, note })

/** The deletion of a node through the change API: `dryRun` resolves and reports without writing. */
export function removeNode(configurationId: number, name: string, dryRun: boolean): Promise<DryRunReport> {
  return request<DryRunReport>(`/configurations/${configurationId}/changes`, {
    method: 'POST',
    body: JSON.stringify({
      source: 'admin', actor: 'admin', base_mode: 'rebase', dry_run: dryRun,
      ops: [{ op: 'remove_node', name }],
    }),
  })
}
