import { useCallback, useEffect, useState } from 'react'
import {
  describeApiError,
  getConfigurationDiff,
  getConfigurationStatus,
  resetConfigurationToStandard,
  restoreConfigurationRows,
  verifyConfigurationJournal,
} from '@/api/client'
import type {
  ConfigurationDiff,
  ConfigurationDiffRow,
  ConfigurationStatus,
} from '@/types/configuration'

/** The word the server needs typed before it resets. */
const RESET_WORD = 'reset'

interface Note {
  kind: 'success' | 'error'
  text: string
}

const short = (hash: string | null) => (hash ? hash.slice(0, 12) : 'none')
const rowId = (r: ConfigurationDiffRow) => `${r.table} ${JSON.stringify(r.key)}`
const show = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v))

function describeChange(r: ConfigurationDiffRow): string {
  if (r.change === 'added') return 'in this configuration only'
  if (r.change === 'removed') return 'in the standard only'
  return r.columns.map(c => `${c}: ${show(r.current?.[c])} (standard: ${show(r.standard?.[c])})`).join('; ')
}

/**
 * Configuration status card, Compare, Reset and Restore selected, for the global configuration
 * (Metacat Mode). Reset and restore are journaled changes; the server writes them.
 */
export function ConfigurationPanel({ onChanged }: { onChanged?: () => void }) {
  const [status, setStatus] = useState<ConfigurationStatus | null>(null)
  const [diff, setDiff] = useState<ConfigurationDiff | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirming, setConfirming] = useState(false)
  const [typed, setTyped] = useState('')
  const [note, setNote] = useState<Note | null>(null)
  const [busy, setBusy] = useState(false)

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await getConfigurationStatus())
    } catch (err) {
      setNote({ kind: 'error', text: describeApiError(err, 'load the configuration status') })
    }
  }, [])

  const loadDiff = useCallback(async () => {
    try {
      setDiff(await getConfigurationDiff())
      setSelected(new Set())
    } catch (err) {
      setNote({ kind: 'error', text: describeApiError(err, 'compare with the Metacat Standard Configuration') })
    }
  }, [])

  useEffect(() => { void loadStatus() }, [loadStatus])

  const afterChange = async (text: string) => {
    setNote({ kind: 'success', text })
    await loadStatus()
    if (diff) await loadDiff()
    onChanged?.()
  }

  const doReset = async () => {
    setBusy(true)
    try {
      const res = await resetConfigurationToStandard(typed)
      setConfirming(false)
      setTyped('')
      await afterChange(
        res.wrote
          ? `Reset to the Metacat Standard Configuration (revision ${res.revision}, ${res.ops} changes).`
          : 'Nothing to reset: the configuration already equals the Metacat Standard Configuration.',
      )
    } catch (err) {
      setNote({ kind: 'error', text: describeApiError(err, 'reset to the Metacat Standard Configuration') })
    } finally {
      setBusy(false)
    }
  }

  const doRestore = async () => {
    if (!diff) return
    setBusy(true)
    try {
      const rows = diff.rows.filter(r => selected.has(rowId(r))).map(r => ({ table: r.table, key: r.key }))
      const res = await restoreConfigurationRows(rows)
      await afterChange(
        res.wrote
          ? `Restored ${rows.length} ${rows.length === 1 ? 'row' : 'rows'} (revision ${res.revision}).`
          : 'Nothing to restore.',
      )
    } catch (err) {
      setNote({ kind: 'error', text: describeApiError(err, 'restore the selected rows') })
    } finally {
      setBusy(false)
    }
  }

  const doVerify = async () => {
    try {
      const report = await verifyConfigurationJournal()
      setNote(report.ok
        ? { kind: 'success', text: `The journal verifies: ${report.entries} entries replay to the current configuration.` }
        : { kind: 'error', text: `The journal does not verify: ${report.problems.join('; ')}` })
    } catch (err) {
      setNote({ kind: 'error', text: describeApiError(err, 'verify the journal') })
    }
  }

  const toggle = (r: ConfigurationDiffRow) => {
    const id = rowId(r)
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  const button = { fontSize: 11, padding: '3px 8px' } as const

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
      {note && (
        <div
          role={note.kind === 'error' ? 'alert' : 'status'}
          style={{
            padding: '4px 8px', fontSize: 11, borderRadius: 3,
            background: note.kind === 'error' ? 'rgba(244,67,54,0.2)' : 'rgba(76,175,80,0.2)',
            color: note.kind === 'error' ? 'var(--error)' : 'var(--success)',
          }}
        >
          {note.text}
        </div>
      )}

      <section aria-label="Configuration status" style={{ border: '1px solid var(--border)', borderRadius: 4, padding: 8 }}>
        <h3 style={{ margin: '0 0 6px', fontSize: 12 }}>Configuration status (Metacat Mode)</h3>
        {status ? (
          <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '2px 12px', margin: 0 }}>
            <dt>Revision</dt><dd style={{ margin: 0 }}>{status.revision}</dd>
            <dt>Configuration hash</dt><dd style={{ margin: 0 }} title={status.config_hash ?? ''}>{short(status.config_hash)}</dd>
            <dt>Standard hash</dt><dd style={{ margin: 0 }} title={status.standard_hash ?? ''}>{short(status.standard_hash)}</dd>
            <dt>Origin</dt><dd style={{ margin: 0 }}>{status.origin ?? 'unknown'}</dd>
            <dt>Against the standard</dt>
            <dd style={{ margin: 0 }}>
              {status.equals_standard
                ? 'Equal to the Metacat Standard Configuration.'
                : `Differs from the Metacat Standard Configuration in ${status.differs_rows} ${status.differs_rows === 1 ? 'row' : 'rows'}.`}
            </dd>
          </dl>
        ) : (
          <span>Loading…</span>
        )}
        <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
          <button style={button} onClick={() => void loadDiff()}>Compare with the Metacat Standard Configuration</button>
          <button style={button} onClick={() => void doVerify()}>Verify journal</button>
          <button style={button} onClick={() => setConfirming(true)} disabled={confirming}>
            Reset to the Metacat Standard Configuration…
          </button>
        </div>
        {confirming && (
          <div style={{ marginTop: 8, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <label>
              This replaces every difference with the standard (one journal entry, which can be undone).
              Type <code>{RESET_WORD}</code> to confirm:{' '}
              <input value={typed} onChange={e => setTyped(e.target.value)} aria-label="Type reset to confirm" />
            </label>
            <button style={button} onClick={() => void doReset()} disabled={typed !== RESET_WORD || busy}>Reset</button>
            <button style={button} onClick={() => { setConfirming(false); setTyped('') }}>Cancel</button>
          </div>
        )}
      </section>

      {diff && (
        <section aria-label="Comparison with the Metacat Standard Configuration">
          <h3 style={{ margin: '0 0 6px', fontSize: 12 }}>
            {diff.count === 0
              ? 'No rows differ from the Metacat Standard Configuration.'
              : `${diff.count} ${diff.count === 1 ? 'row differs' : 'rows differ'}: ${diff.added} added, ${diff.removed} removed, ${diff.changed} changed.`}
          </h3>
          {diff.count > 0 && (
            <>
              <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                <thead>
                  <tr style={{ textAlign: 'left' }}>
                    <th style={{ width: 24 }} />
                    <th>Table</th><th>Row</th><th>Change</th><th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {diff.rows.map(r => (
                    <tr key={rowId(r)}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Select ${rowId(r)}`}
                          checked={selected.has(rowId(r))}
                          onChange={() => toggle(r)}
                        />
                      </td>
                      <td>{r.table}</td>
                      <td>{Object.values(r.key).map(show).join(' / ')}</td>
                      <td>{r.change}</td>
                      <td>{describeChange(r)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button
                style={{ ...button, marginTop: 6 }}
                onClick={() => void doRestore()}
                disabled={selected.size === 0 || busy}
              >
                Restore selected ({selected.size})
              </button>
            </>
          )}
        </section>
      )}
    </div>
  )
}
