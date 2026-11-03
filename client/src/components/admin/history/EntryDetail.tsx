// ---------------------------------------------------------------------------
// Petacat -- one journal entry in full: proposed ops, resolved ops and before-images
// ---------------------------------------------------------------------------

import { useEffect, useState } from 'react'
import { describeApiError } from '@/api/client'
import { getJournalEntry, getPendingEntry } from './historyApi'
import { PendingBadge, boxStyle, errorStyle, opSummary } from './shared'
import type { JournalEntry } from './types'

const pre: React.CSSProperties = {
  margin: 0, padding: 4, fontSize: 10, maxHeight: 160, overflow: 'auto', background: 'var(--bg-panel)',
  whiteSpace: 'pre-wrap', wordBreak: 'break-word',
}

export function EntryDetail({ entry }: { entry: JournalEntry }) {
  const [full, setFull] = useState<JournalEntry | null>(entry.resolved ? entry : null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    if (entry.resolved) { setFull(entry); return }
    const load = entry.id === null
      ? getPendingEntry(entry.configuration_id, entry.revision)
      : getJournalEntry(entry.id)
    load
      .then(e => { if (live) { setFull(e); setError(null) } })
      .catch(err => { if (live) setError(describeApiError(err, 'load the journal entry')) })
    return () => { live = false }
  }, [entry])

  if (error) return <div role="alert" style={errorStyle}>{error}</div>
  if (!full) return <div className="text-xs text-muted">Loading the entry...</div>
  const resolved = full.resolved ?? []
  const before = full.before ?? []
  return (
    <div data-testid="entry-detail" style={{ ...boxStyle, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div>
        Revision {full.revision} {full.pending && <PendingBadge />}
        {full.causing_run_id !== null && <> &middot; caused by run {full.causing_run_id}</>}
        {full.episode_version !== null && <> &middot; Training episode version {full.episode_version}</>}
      </div>
      <div>
        <strong>Proposed</strong> (what was asked for)
        <pre style={pre}>{JSON.stringify(full.proposed, null, 2)}</pre>
      </div>
      <div>
        <strong>Resolved</strong> ({resolved.length} {resolved.length === 1 ? 'op' : 'ops'}, cascades included) with the before-image of each
        {resolved.length === 0 && <div className="text-muted">No row changed.</div>}
        {resolved.map((op, i) => (
          <div key={i} data-testid="resolved-op" style={{ marginTop: 3 }}>
            <div className="mono">{opSummary(op)}</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
              <div>
                <span className="text-muted">before</span>
                <pre style={pre}>{before[i] ? JSON.stringify(before[i], null, 1) : 'none (the row is new)'}</pre>
              </div>
              <div>
                <span className="text-muted">{op.op === 'delete' ? 'after' : op.op === 'insert' ? 'inserted' : 'set'}</span>
                <pre style={pre}>{op.op === 'delete' ? 'removed' : JSON.stringify(op.op === 'insert' ? op.row : op.set, null, 1)}</pre>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
