// ---------------------------------------------------------------------------
// Petacat -- the deletion preview: what removing a node would cascade to, leave dangling or affect
// ---------------------------------------------------------------------------
//
// A dry run of the delete through the change API; nothing is written until the person
// confirms. The same lists the change API reports (`cascaded`, `dangling`, `affected`).
// ---------------------------------------------------------------------------

import { useState } from 'react'
import { describeApiError } from '@/api/client'
import { removeNode } from './historyApi'
import { boxStyle, errorStyle, smallButton } from './shared'
import type { DryRunReport, ReportItem } from './types'

function List({ title, items, testId }: { title: string; items: ReportItem[]; testId: string }) {
  return (
    <div data-testid={testId}>
      <strong>{title} ({items.length})</strong>
      {items.length === 0 && <div className="text-muted">None.</div>}
      <ul style={{ margin: '2px 0 0 16px', padding: 0 }}>
        {items.map((it, i) => (
          <li key={i}>
            <span className="mono">{it.table} [{Object.values(it.key ?? {}).join(' / ')}]</span>
            {it.column ? <> column <span className="mono">{it.column}</span></> : null}
            {it.reason ? <span className="text-muted"> &mdash; {it.reason}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function DeletionPreview({
  configurationId, name, onDeleted,
}: {
  configurationId: number
  name: string
  onDeleted?: () => void
}) {
  const [report, setReport] = useState<DryRunReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function preview() {
    setBusy(true); setDone(null)
    try {
      setReport(await removeNode(configurationId, name, true)); setError(null)
    } catch (err) {
      setReport(null); setError(describeApiError(err, `preview the deletion of "${name}"`))
    } finally { setBusy(false) }
  }

  async function confirm() {
    setBusy(true)
    try {
      const out = await removeNode(configurationId, name, false)
      setReport(null); setError(null)
      setDone(`Deleted "${name}". It stays in the History and can be restored.`)
      if (out.ok !== false) onDeleted?.()
    } catch (err) {
      setError(describeApiError(err, `delete "${name}"`))
    } finally { setBusy(false) }
  }

  return (
    <div data-testid="deletion-preview" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div>
        <button onClick={preview} disabled={busy || !name} style={smallButton}>
          Preview deleting &ldquo;{name}&rdquo;
        </button>
      </div>
      {error && <div role="alert" style={errorStyle}>{error}</div>}
      {done && <div role="status" className="text-xs" style={{ color: 'var(--success)' }}>{done}</div>}
      {report && (
        <div style={{ ...boxStyle, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div>
            Deleting <span className="mono">{name}</span> would remove these rows with it, and nothing has been written yet.
          </div>
          <List title="Removed with it (cascade)" items={report.cascaded ?? []} testId="preview-cascaded" />
          <List title="Left naming it (dangling)" items={report.dangling ?? []} testId="preview-dangling" />
          <List title="Affected" items={report.affected ?? []} testId="preview-affected" />
          <div className="text-muted">
            An Episodic Memory that names it keeps the name; it is then listed under &ldquo;names that no longer resolve&rdquo;.
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={confirm} disabled={busy} style={{ ...smallButton, color: 'var(--error)' }}>
              Delete &ldquo;{name}&rdquo;
            </button>
            <button onClick={() => setReport(null)} disabled={busy} style={smallButton}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}
