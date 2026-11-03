import { useState } from 'react'
import type { DbColumn, DbRow, DbTable } from './types'
import { parseValue, showValue } from './values'

export type EditMode = 'insert' | 'update'

interface RowEditorProps {
  table: DbTable
  mode: EditMode
  row: DbRow | null
  busy: boolean
  onCancel: () => void
  /** Called with the values to write: every column on insert, the changed ones on update. */
  onSave: (changed: Record<string, unknown>, old: Record<string, unknown>) => void
}

/**
 * The form for one row. It never writes: it reads the boxes into values and hands them up, and
 * the panel builds a change batch (configuration tables) or an edit (content, runtime data).
 * A key column of a configuration table, a primary key, and a protected column are read-only on
 * an update; an auto-numbered `id` is left out of an insert.
 */
export function RowEditor({ table, mode, row, busy, onCancel, onSave }: RowEditorProps) {
  const [draft, setDraft] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {}
    for (const c of table.columns) init[c.name] = mode === 'update' ? showValue(row?.values[c.name]) : ''
    return init
  })
  const [problem, setProblem] = useState<string | null>(null)

  const locked = (c: DbColumn) =>
    c.protected || (mode === 'update' && (c.primary_key || table.key_columns.includes(c.name)))
  const left = (c: DbColumn) => mode === 'insert' && c.primary_key && c.name === 'id'

  const save = () => {
    const changed: Record<string, unknown> = {}
    try {
      for (const c of table.columns) {
        if (locked(c) && mode === 'update') continue
        if (left(c)) continue
        const before = showValue(row?.values[c.name])
        if (mode === 'update' && draft[c.name] === before) continue
        if (mode === 'insert' && draft[c.name] === '' && c.nullable) continue
        changed[c.name] = parseValue(c, draft[c.name])
      }
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e))
      return
    }
    if (mode === 'update' && Object.keys(changed).length === 0) {
      setProblem('Nothing was changed.')
      return
    }
    setProblem(null)
    onSave(changed, row?.values ?? {})
  }

  return (
    <div role="form" aria-label={mode === 'insert' ? 'New row' : 'Edit row'} style={{
      border: '1px solid var(--border)', borderRadius: 4, padding: 8, marginBottom: 8,
      background: 'var(--bg-panel)',
    }}>
      <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 6 }}>
        {mode === 'insert' ? `New row in ${table.name}` : `Edit a row of ${table.name}`}
      </div>
      {table.columns.map(c => (
        left(c) ? null : (
          <label key={c.name} style={{ display: 'flex', gap: 6, alignItems: 'flex-start', marginBottom: 4, fontSize: 11 }}>
            <span style={{ width: 150, flexShrink: 0, paddingTop: 3 }}>
              {c.name}{locked(c) ? ' (locked)' : ''}
            </span>
            <textarea
              aria-label={c.name}
              value={draft[c.name]}
              disabled={locked(c) && mode === 'update'}
              rows={/json|text/i.test(c.type) ? 3 : 1}
              onChange={e => setDraft({ ...draft, [c.name]: e.target.value })}
              style={{ flex: 1, fontFamily: 'var(--font-mono, monospace)', fontSize: 11 }}
            />
          </label>
        )
      ))}
      {problem && <div role="alert" style={{ color: 'var(--error)', fontSize: 11 }}>{problem}</div>}
      <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
        <button onClick={save} disabled={busy} style={{ fontSize: 11 }}>Save</button>
        <button onClick={onCancel} disabled={busy} style={{ fontSize: 11 }}>Cancel</button>
      </div>
    </div>
  )
}
