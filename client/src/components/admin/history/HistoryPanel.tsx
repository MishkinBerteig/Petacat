// ---------------------------------------------------------------------------
// Petacat -- History: a configuration's journal, with entry detail and undo
// ---------------------------------------------------------------------------
//
// A view of the one journal. An undo is a new entry (source "restore"), never a rewrite.
// For a live Training Mode Session the entries it holds only in memory are listed too,
// labelled "not yet saved"; they cannot be undone until the session is stopped.
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useState } from 'react'
import { describeApiError, listConfigurations } from '@/api/client'
import type { ConfigurationSummary } from '@/types/configuration'
import { ControlHelp } from '../../session/shared'
import { EntryDetail } from './EntryDetail'
import { getJournal, undoBatch, undoGroup } from './historyApi'
import { PendingBadge, boxStyle, countsText, errorStyle, smallButton, whenText } from './shared'
import type { JournalEntry, JournalPage } from './types'

const PAGE = 50

interface Props {
  /** Fixed to one configuration; without it the panel offers a choice of them. */
  configurationId?: number
  /** Called after an undo wrote a new entry. */
  onChanged?: () => void
}

type Pending = { kind: 'batch'; entry: JournalEntry } | { kind: 'group'; entry: JournalEntry }

export function HistoryPanel({ configurationId, onChanged }: Props) {
  const [choices, setChoices] = useState<ConfigurationSummary[]>([])
  const [chosen, setChosen] = useState<number>(configurationId ?? 1)
  const id = configurationId ?? chosen
  const [source, setSource] = useState('')
  const [actor, setActor] = useState('')
  const [table, setTable] = useState('')
  const [group, setGroup] = useState('')
  const [page, setPage] = useState<JournalPage | null>(null)
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<Pending | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (configurationId !== undefined) return
    listConfigurations().then(setChoices).catch(() => setChoices([]))
  }, [configurationId])

  const load = useCallback(async (offset: number) => {
    try {
      const next = await getJournal({
        configuration_id: id, source: source || undefined, actor: actor || undefined,
        table: table || undefined, group_id: group || undefined, limit: PAGE, offset,
      })
      setPage(next)
      setEntries(prev => (offset === 0 ? next.entries : [...prev, ...next.entries]))
      setError(null)
    } catch (err) {
      setError(describeApiError(err, 'load the History'))
    }
  }, [id, source, actor, table, group])

  useEffect(() => { void load(0) }, [load])

  async function runUndo(p: Pending) {
    try {
      const out = p.kind === 'batch'
        ? await undoBatch(id, p.entry.id as number)
        : await undoGroup(id, p.entry.group_id as string)
      setMessage(out.changed
        ? `Undone: a new entry, revision ${out.revision}, was written.`
        : 'Nothing to undo: the configuration already is that way.')
      setError(null)
      onChanged?.()
      await load(0)
    } catch (err) {
      setMessage(null)
      setError(describeApiError(err, p.kind === 'batch' ? 'undo the batch' : 'undo the group'))
    } finally { setConfirming(null) }
  }

  const live = page?.live
  const key = (e: JournalEntry) => `${e.pending ? 'p' : 's'}${e.revision}`

  return (
    <div data-testid="history-panel" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="text-xs text-muted" style={{ display: 'flex', alignItems: 'center' }}>
        The journal is the one record of changes: every edit, restore and undo is an entry, and nothing is rewritten.
        <ControlHelp topic="configuration_journal" label="the configuration journal" />
        <ControlHelp topic="change_api" label="the change API" />
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', fontSize: 11 }}>
        {configurationId === undefined && (
          <select aria-label="Configuration" value={chosen} onChange={e => setChosen(Number(e.target.value))}>
            {(choices.length ? choices : [{ id: 1, mode_label: 'Metacat Mode', name: '' } as ConfigurationSummary]).map(c => (
              <option key={c.id} value={c.id}>{c.mode_label}{c.id === 1 ? '' : ` (configuration ${c.id})`}</option>
            ))}
          </select>
        )}
        <input aria-label="Source" placeholder="source" value={source} onChange={e => setSource(e.target.value)} style={{ width: 80 }} />
        <input aria-label="Actor" placeholder="actor" value={actor} onChange={e => setActor(e.target.value)} style={{ width: 80 }} />
        <input aria-label="Table" placeholder="table" value={table} onChange={e => setTable(e.target.value)} style={{ width: 130 }} />
        <input aria-label="Group" placeholder="group id" value={group} onChange={e => setGroup(e.target.value)} style={{ width: 90 }} />
        <span className="text-muted">{page ? `${page.total} ${page.total === 1 ? 'entry' : 'entries'}` : ''}</span>
      </div>
      {live && (
        <div data-testid="live-note" style={boxStyle}>
          Live (in memory): this Training Mode Session is {live.state}. The database shows it as of revision {live.saved_through};
          {' '}{live.unsaved} {live.unsaved === 1 ? 'batch is' : 'batches are'} held in memory and saved when it is stopped.
        </div>
      )}
      {error && <div role="alert" style={errorStyle}>{error}</div>}
      {message && <div role="status" className="text-xs" style={{ color: 'var(--success)' }}>{message}</div>}
      {page && entries.length === 0 && <div className="text-xs text-muted">No entries match.</div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {entries.map(e => (
          <div key={key(e)} data-testid="history-entry" style={boxStyle}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
              <strong>r{e.revision}</strong>
              {e.pending && <PendingBadge />}
              <span>{e.source}</span>
              <span>{e.actor}</span>
              {e.channel && <span className="text-muted">{e.channel}</span>}
              <span className="text-muted">{whenText(e.occurred_at)}</span>
              <span className="text-muted">{countsText(e.counts)}</span>
              {e.group_id && <span className="text-muted">group {e.group_id}</span>}
              <span style={{ flex: 1 }} />
              <button style={smallButton} onClick={() => setOpen(open === key(e) ? null : key(e))}>
                {open === key(e) ? 'Hide detail' : 'Detail'}
              </button>
              <button style={smallButton} disabled={e.pending || e.counts.insert + e.counts.update + e.counts.delete === 0}
                title={e.pending ? 'Held in memory: undo is possible once the session is stopped' : 'Write a new entry that undoes this batch'}
                onClick={() => setConfirming({ kind: 'batch', entry: e })}>
                Undo batch
              </button>
              {e.group_id && !e.pending && (
                <button style={smallButton} onClick={() => setConfirming({ kind: 'group', entry: e })}>Undo group</button>
              )}
            </div>
            {e.note && <div className="text-muted">{e.note}</div>}
            {confirming?.entry === e && (
              <div role="alertdialog" style={{ marginTop: 4, display: 'flex', gap: 6, alignItems: 'center' }}>
                <span>
                  {confirming.kind === 'batch'
                    ? `Undo revision ${e.revision} with a new entry?`
                    : `Undo every entry of group ${e.group_id} with one new entry?`}
                </span>
                <button style={smallButton} onClick={() => void runUndo(confirming)}>Confirm undo</button>
                <button style={smallButton} onClick={() => setConfirming(null)}>Cancel</button>
              </div>
            )}
            {open === key(e) && <div style={{ marginTop: 4 }}><EntryDetail entry={e} /></div>}
          </div>
        ))}
      </div>
      {page && entries.length < page.total && (
        <button style={smallButton} onClick={() => void load(entries.length)}>Load more</button>
      )}
    </div>
  )
}
