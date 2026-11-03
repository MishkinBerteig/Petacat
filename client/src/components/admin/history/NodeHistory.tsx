// ---------------------------------------------------------------------------
// Petacat -- one node's History: its story, the entries that touched it, restore and the deletion preview
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useState } from 'react'
import { describeApiError } from '@/api/client'
import { DeletionPreview } from './DeletionPreview'
import { EntryDetail } from './EntryDetail'
import { getJournal, restoreEntity, undoBatch, whereDidNameGo } from './historyApi'
import { PendingBadge, boxStyle, countsText, errorStyle, smallButton, whenText } from './shared'
import type { JournalEntry, NameStory } from './types'

const NODES = 'slipnet_node_defs'

interface Props {
  configurationId?: number
  /** The node to show first (the Slipnet editor passes the row being edited). */
  initialName?: string | null
  onChanged?: () => void
}

export function NodeHistory({ configurationId = 1, initialName, onChanged }: Props) {
  const [name, setName] = useState(initialName ?? '')
  const [shown, setShown] = useState('')
  const [story, setStory] = useState<NameStory | null>(null)
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [open, setOpen] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => { if (initialName) { setName(initialName); setShown(initialName) } }, [initialName])

  const load = useCallback(async (n: string) => {
    if (!n) return
    try {
      const [s, page] = await Promise.all([
        whereDidNameGo(n, configurationId),
        getJournal({ configuration_id: configurationId, table: NODES, key: { name: n }, limit: 200 }),
      ])
      setStory(s); setEntries(page.entries); setError(null)
    } catch (err) {
      setStory(null); setEntries([])
      setError(describeApiError(err, `load the History of "${n}"`))
    }
  }, [configurationId])

  useEffect(() => { void load(shown) }, [shown, load])

  async function act(label: string, run: () => Promise<{ changed: boolean; revision: number }>) {
    try {
      const out = await run()
      setMessage(out.changed ? `${label}: a new entry, revision ${out.revision}, was written.` : 'Nothing changed.')
      setError(null)
      onChanged?.()
      await load(shown)
    } catch (err) {
      setMessage(null)
      setError(describeApiError(err, label.toLowerCase()))
    }
  }

  const restorable = story?.restorable
  return (
    <div data-testid="node-history" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <form
        onSubmit={e => { e.preventDefault(); setShown(name.trim()) }}
        style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 11 }}
      >
        <label htmlFor="node-history-name">Node</label>
        <input id="node-history-name" value={name} onChange={e => setName(e.target.value)} placeholder="plato-..." style={{ width: 220 }} />
        <button type="submit" style={smallButton} disabled={!name.trim()}>Show History</button>
      </form>
      {error && <div role="alert" style={errorStyle}>{error}</div>}
      {message && <div role="status" className="text-xs" style={{ color: 'var(--success)' }}>{message}</div>}
      {story && (
        <div style={boxStyle} data-testid="node-story">
          <div>{story.text}.</div>
          {!story.resolves && story.current_name && <div>It is now <span className="mono">{story.current_name}</span>.</div>}
          <ol style={{ margin: '4px 0 0 16px', padding: 0 }}>
            {story.events.map((ev, i) => (
              <li key={i} data-testid="story-event">
                {ev.text} &mdash; revision {ev.revision}, source {ev.source}, actor {ev.actor}, {whenText(ev.occurred_at)}
                {ev.note ? <span className="text-muted"> ({ev.note})</span> : null}
              </li>
            ))}
          </ol>
          {restorable && !story.resolves && (
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              <button style={smallButton}
                onClick={() => void act('Restore the node', () => restoreEntity(
                  configurationId, restorable.table, restorable.key, restorable.as_of_revision))}>
                Restore &ldquo;{story.name}&rdquo; with its dependents
              </button>
              <button style={smallButton}
                title="Undo the whole batch that removed it, including the list entries and references it took with it"
                onClick={() => void act('Undo the batch that removed it', () => undoBatch(configurationId, restorable.entry_id))}>
                Undo the batch that removed it
              </button>
            </div>
          )}
        </div>
      )}
      {shown && story?.resolves && (
        <DeletionPreview configurationId={configurationId} name={shown} onDeleted={() => void load(shown)} />
      )}
      {shown && entries.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <strong className="text-xs">Entries that touched this node</strong>
          {entries.map(e => (
            <div key={e.revision} data-testid="node-entry" style={boxStyle}>
              <span>r{e.revision}</span> {e.pending && <PendingBadge />} {e.source} {e.actor}{' '}
              <span className="text-muted">{countsText(e.counts)}</span>{' '}
              <button style={smallButton} onClick={() => setOpen(open === e.revision ? null : e.revision)}>
                {open === e.revision ? 'Hide' : 'Detail'}
              </button>
              {open === e.revision && <EntryDetail entry={e} />}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
