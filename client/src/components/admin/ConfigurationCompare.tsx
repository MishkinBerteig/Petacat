import { useState } from 'react'
import {
  applyConfigurationFrom,
  compareConfigurations,
  describeApiError,
} from '@/api/client'
import type {
  ApplyFromReport,
  CompareRow,
  CompareSide,
  ConfigurationCompare as Compared,
  ConfigurationSummary,
} from '@/types/configuration'
import { badgeText } from './configurationLabels'

type Ref = number | 'standard'

const STANDARD_LABEL = 'Metacat Standard Configuration'
const rowId = (r: CompareRow) => `${r.table} ${JSON.stringify(r.key)}`
const show = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v))
const parseRef = (v: string): Ref => (v === 'standard' ? 'standard' : Number(v))
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

function describe(r: CompareRow): string {
  if (r.change === 'added') return 'only in A'
  if (r.change === 'removed') return 'only in B'
  return r.columns.map(c => `${c}: ${show(r.a?.[c])} (A) / ${show(r.b?.[c])} (B)`).join('; ')
}

interface Pending {
  target: number
  source: Ref
  rows: CompareRow[]
  preview: ApplyFromReport | null
}

/**
 * Compare any two configurations, or one and the Metacat Standard Configuration, row by row
 * (table and natural key). From the result the Admin selects rows and applies them to the other
 * side: a change batch with a preview and a reason, which takes effect at that configuration's
 * next run.
 */
export function ConfigurationCompare({
  configurations,
  initialA,
  initialB,
  onChanged,
}: {
  configurations: ConfigurationSummary[]
  initialA?: Ref
  initialB?: Ref
  onChanged?: () => void
}) {
  const [a, setA] = useState<Ref>(initialA ?? 1)
  const [b, setB] = useState<Ref>(initialB ?? 'standard')
  const [result, setResult] = useState<Compared | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [pending, setPending] = useState<Pending | null>(null)
  const [reason, setReason] = useState('')
  const [note, setNote] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async (left: Ref = a, right: Ref = b) => {
    if (left === right) {
      setNote({ kind: 'error', text: 'Pick two different configurations to compare.' })
      return
    }
    try {
      setResult(await compareConfigurations(left, right))
      setSelected(new Set())
      setPending(null)
      setNote(null)
    } catch (err) {
      setNote({ kind: 'error', text: describeApiError(err, 'compare the configurations') })
    }
  }

  const choose = (side: 'a' | 'b') => (e: React.ChangeEvent<HTMLSelectElement>) => {
    ;(side === 'a' ? setA : setB)(parseRef(e.target.value))
    setResult(null)
    setPending(null)
  }

  const toggle = (r: CompareRow) => {
    const next = new Set(selected)
    if (next.has(rowId(r))) next.delete(rowId(r))
    else next.add(rowId(r))
    setSelected(next)
  }

  // "Apply to the other side": the target is the side named, the source is the other.
  const startApply = async (toSide: 'a' | 'b') => {
    if (!result) return
    const target = (toSide === 'a' ? result.a : result.b).id
    const source = (toSide === 'a' ? result.b : result.a).id
    if (typeof target !== 'number') return
    const rows = result.rows.filter(r => selected.has(rowId(r)))
    setBusy(true)
    try {
      const preview = await applyConfigurationFrom(
        target, source, rows.map(r => ({ table: r.table, key: r.key })), { dryRun: true })
      setPending({ target, source, rows, preview })
      setNote(null)
    } catch (err) {
      setNote({ kind: 'error', text: describeApiError(err, 'preview the change') })
    } finally {
      setBusy(false)
    }
  }

  const commit = async () => {
    if (!pending) return
    setBusy(true)
    try {
      const res = await applyConfigurationFrom(
        pending.target, pending.source,
        pending.rows.map(r => ({ table: r.table, key: r.key })), { note: reason })
      setPending(null)
      setReason('')
      await run()
      setNote({
        kind: 'success',
        text: res.wrote
          ? `Applied ${plural(res.ops, 'change', 'changes')}; it takes effect at that configuration's next run.`
          : 'Nothing to apply: the chosen rows already match.',
      })
      onChanged?.()
    } catch (err) {
      setNote({ kind: 'error', text: describeApiError(err, 'apply the rows') })
    } finally {
      setBusy(false)
    }
  }

  const sideName = (s: CompareSide) => (s.id === 'standard' ? STANDARD_LABEL : s.name)
  const options = (
    <>
      {configurations.map(c => (
        <option key={c.id} value={c.id}>{`${c.name} (${badgeText(c)})`}</option>
      ))}
      <option value="standard">{STANDARD_LABEL}</option>
    </>
  )
  const button = { fontSize: 11, padding: '3px 8px' } as const
  const targetName = (id: number) => configurations.find(c => c.id === id)?.name ?? `configuration ${id}`

  return (
    <section aria-label="Compare configurations" style={{ border: '1px solid var(--border)', borderRadius: 4, padding: 8 }}>
      <h3 style={{ margin: '0 0 6px', fontSize: 12 }}>Compare</h3>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 11 }}>
        <label>A{' '}
          <select aria-label="Compare A" value={String(a)} onChange={choose('a')}>{options}</select>
        </label>
        <label>B{' '}
          <select aria-label="Compare B" value={String(b)} onChange={choose('b')}>{options}</select>
        </label>
        <button style={button} onClick={() => void run()}>Compare</button>
      </div>

      {note && (
        <div
          role={note.kind === 'error' ? 'alert' : 'status'}
          style={{
            marginTop: 6, padding: '4px 8px', fontSize: 11, borderRadius: 3,
            background: note.kind === 'error' ? 'rgba(244,67,54,0.2)' : 'rgba(76,175,80,0.2)',
            color: note.kind === 'error' ? 'var(--error)' : 'var(--success)',
          }}
        >
          {note.text}
        </div>
      )}

      {result && (
        <div style={{ marginTop: 8, fontSize: 12 }}>
          <div>
            A is <b>{sideName(result.a)}</b> ({result.a.mode_label}); B is <b>{sideName(result.b)}</b> ({result.b.mode_label}).{' '}
            {result.count === 0
              ? 'No rows differ.'
              : `${plural(result.count, 'row differs', 'rows differ')}: ${result.added} only in A, ${result.removed} only in B, ${result.changed} changed.`}
          </div>
          {result.count > 0 && (
            <>
              <table style={{ borderCollapse: 'collapse', width: '100%', marginTop: 6 }}>
                <thead>
                  <tr style={{ textAlign: 'left' }}>
                    <th style={{ width: 24 }} />
                    <th>Table</th><th>Row</th><th>Difference</th>
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map(r => (
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
                      <td>{describe(r)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                <button
                  style={button}
                  disabled={selected.size === 0 || busy || result.a.id === 'standard'}
                  onClick={() => void startApply('a')}
                >
                  Apply to A (make A match B) for selected ({selected.size})
                </button>
                <button
                  style={button}
                  disabled={selected.size === 0 || busy || result.b.id === 'standard'}
                  onClick={() => void startApply('b')}
                >
                  Apply to B (make B match A) for selected ({selected.size})
                </button>
              </div>
            </>
          )}

          {pending && (
            <div role="group" aria-label="Preview" style={{ marginTop: 8, padding: 8, border: '1px solid var(--border)', borderRadius: 4 }}>
              <div data-testid="apply-preview">
                Apply {plural(pending.rows.length, 'row', 'rows')} to <b>{targetName(pending.target)}</b>
                {' '}from {pending.source === 'standard' ? STANDARD_LABEL : targetName(pending.source)}:{' '}
                {plural(pending.preview?.ops ?? 0, 'change', 'changes')}
                {(pending.preview?.cascaded?.length ?? 0) > 0
                  ? `, and ${plural(pending.preview!.cascaded!.length, 'dependent row', 'dependent rows')} removed with them`
                  : ''}
                . It takes effect at that configuration's next run.
              </div>
              <label style={{ display: 'block', marginTop: 4 }}>
                Reason{' '}
                <input value={reason} onChange={e => setReason(e.target.value)} aria-label="Reason" style={{ width: 280 }} />
              </label>
              <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                <button style={button} disabled={busy} onClick={() => void commit()}>Apply</button>
                <button style={button} onClick={() => setPending(null)}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
