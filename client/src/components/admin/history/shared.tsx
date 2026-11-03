// ---------------------------------------------------------------------------
// Petacat -- small pieces shared by the History components
// ---------------------------------------------------------------------------

import { NOT_YET_SAVED, type JournalOp } from './types'

export const boxStyle: React.CSSProperties = {
  border: '1px solid var(--border)', borderRadius: 4, padding: '4px 8px', fontSize: 11,
}

export const smallButton: React.CSSProperties = { fontSize: 10, padding: '1px 6px' }

export const errorStyle: React.CSSProperties = {
  fontSize: 11, color: 'var(--error)', padding: '3px 6px', border: '1px solid var(--error)', borderRadius: 3,
}

/** "5 inserted, 1 updated" for an entry's counts. */
export function countsText(c: { insert: number; update: number; delete: number }): string {
  const parts: string[] = []
  if (c.insert) parts.push(`${c.insert} inserted`)
  if (c.update) parts.push(`${c.update} updated`)
  if (c.delete) parts.push(`${c.delete} deleted`)
  return parts.length ? parts.join(', ') : 'no row changed'
}

export function whenText(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

export function PendingBadge() {
  return (
    <span
      data-testid="pending-badge"
      title="Held in memory by a live Training Mode Session. It is written to the database when the session is stopped."
      style={{ fontSize: 9, padding: '0 4px', borderRadius: 2, border: '1px solid var(--warning)', color: 'var(--warning)' }}
    >
      {NOT_YET_SAVED}
    </span>
  )
}

export function opSummary(op: JournalOp): string {
  const key = Object.values(op.key ?? {}).join(' / ')
  return `${op.op} ${op.table} [${key}]`
}
