import { useState, useEffect, useCallback } from 'react'
import { request, describeApiError } from '@/api/client'
import { EditableTable, type ColumnDef } from './EditableTable'

interface EnumValue {
  name: string
  display_label: string
  sort_order: number
  description: string
  // The table's own columns (`role`, `behaviour`, `serialised`, a clamp type's factors ...).
  [column: string]: unknown
}

/** A column of an enum table beyond the four every enum table has (`GET /admin/enums`). */
interface ExtraColumn {
  name: string
  type: 'text' | 'bool' | 'float' | 'int' | 'json'
  nullable: boolean
  /** For a role (or behaviour) column: the engine's list for the table. */
  pick: string[] | null
  /** The table a column names a row of, if any. */
  references: string | null
}

/** Which column of a table holds its binding to the engine's vocabulary. */
interface RoleInfo {
  column: string
  roles: string[]
  unique: boolean
}

interface EnumTablesReply {
  tables: string[]
  roles?: Record<string, RoleInfo>
  columns?: Record<string, ExtraColumn[]>
}

/**
 * Send one write, and describe a refusal in terms of what was being attempted.
 *
 * The table shows the thrown message beside the row that was edited, so the sentence it
 * throws is the sentence the reader gets.
 */
async function submit<T>(action: string, path: string, options: RequestInit): Promise<T> {
  try {
    return await request<T>(path, options)
  } catch (err) {
    throw new Error(describeApiError(err, action))
  }
}

const BASE_COLUMNS: ColumnDef[] = [
  { key: 'name', label: 'Name', type: 'readonly', width: '18%' },
  { key: 'display_label', label: 'Display Label', type: 'text', width: '16%' },
  { key: 'sort_order', label: 'Order', type: 'number', width: '7%' },
  { key: 'description', label: 'Description', type: 'text' },
]

/**
 * The columns of one table: the four every table has, then the table's own.  The column that
 * binds a row to the engine's vocabulary is a pick from the engine's list for the table
 * (read-only to this editor: the engine names the concepts, the configuration names the rows);
 * a boolean is a pick between true and false; the rest are text, numbers and JSON.
 */
function columnsFor(extra: ExtraColumn[], role?: RoleInfo): ColumnDef[] {
  return [
    ...BASE_COLUMNS,
    ...extra.map((c): ColumnDef => {
      if (role && c.name === role.column) {
        return { key: c.name, label: c.name === 'behaviour' ? 'Behaviour' : 'Role', type: 'select', options: role.roles, width: '18%' }
      }
      if (c.type === 'bool') return { key: c.name, label: c.name, type: 'bool', width: '8%' }
      if (c.type === 'float' || c.type === 'int') return { key: c.name, label: c.name, type: 'number', nullable: c.nullable, width: '8%' }
      if (c.type === 'json') return { key: c.name, label: c.name, type: 'json', width: '12%' }
      return { key: c.name, label: c.name, type: 'text', width: '12%' }
    }),
  ]
}

export function EnumEditor() {
  const [tables, setTables] = useState<string[]>([])
  const [roles, setRoles] = useState<Record<string, RoleInfo>>({})
  const [extra, setExtra] = useState<Record<string, ExtraColumn[]>>({})
  const [activeTable, setActiveTable] = useState<string>('')
  const [values, setValues] = useState<EnumValue[]>([])
  const [loading, setLoading] = useState(true)
  // Two loads with two outcomes: which tables exist, and what is in the open one.
  const [tablesError, setTablesError] = useState<string | null>(null)
  const [valuesError, setValuesError] = useState<string | null>(null)

  const loadTables = useCallback(() => {
    setLoading(true)
    request<EnumTablesReply>('/admin/enums')
      .then(data => {
        const t = data.tables ?? []
        setTables(t)
        setRoles(data.roles ?? {})
        setExtra(data.columns ?? {})
        if (t.length > 0) setActiveTable(t[0])
        setTablesError(null)
      })
      .catch(err => setTablesError(describeApiError(err, 'load the enum tables')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadTables() }, [loadTables])

  const loadValues = useCallback(() => {
    if (!activeTable) return
    request<EnumValue[]>(`/admin/enums/${activeTable}`)
      .then(data => { setValues(data); setValuesError(null) })
      .catch(err => {
        // The rows on screen belong to the table that was asked for, so a failed load
        // leaves none: the reason stands in their place.
        setValues([])
        setValuesError(describeApiError(err, `load the values in ${activeTable}`))
      })
  }, [activeTable])

  useEffect(() => { loadValues() }, [loadValues])

  const [renaming, setRenaming] = useState<{ from: string; to: string }>({ from: '', to: '' })
  const [renameMessage, setRenameMessage] = useState<{ ok: boolean; text: string } | null>(null)

  if (loading) return <div className="text-muted">Loading enum tables...</div>

  if (tablesError) {
    return (
      <div role="alert" className="text-xs" style={{ color: 'var(--error)' }}>
        {tablesError}{' '}
        <button onClick={loadTables} style={{ fontSize: 10, padding: '1px 6px' }}>Retry</button>
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
        {tables.map(t => (
          <button key={t} onClick={() => setActiveTable(t)} className={activeTable === t ? 'primary' : ''} style={{ fontSize: 11 }}>
            {t}
          </button>
        ))}
      </div>

      {activeTable && valuesError && (
        <div role="alert" className="text-xs" style={{ color: 'var(--error)' }}>
          {valuesError}{' '}
          <button onClick={loadValues} style={{ fontSize: 10, padding: '1px 6px' }}>Retry</button>
        </div>
      )}

      {activeTable && !valuesError && (
        <>
          <div className="text-xs text-muted mb-2">{values.length} values in {activeTable} (double-click to edit)</div>
          {roles[activeTable] && (
            <div className="text-xs text-muted mb-2" data-testid="role-note">
              {roles[activeTable].column === 'behaviour'
                ? 'The behaviour is what the engine does with a link of this type; which type has which is configuration. '
                : 'The role is the engine’s name for the concept a row plays; an unbound row is inert. '}
              Only the engine’s own names can be picked: {roles[activeTable].roles.join(', ')}.
              {' '}A row that holds one cannot be deleted until it is unbound.
              {' '}The client’s display follows the binding: the run state carries the bindings, so a rename
              reaches the views that read them, and a view that has not yet been changed to read them
              still compares the old name.
            </div>
          )}
          <EditableTable
            columns={columnsFor(extra[activeTable] ?? [], roles[activeTable])}
            rows={values}
            idKey="name"
            onCreate={async (row) => submit<EnumValue>(
              `create a value in ${activeTable}`,
              `/admin/enums/${activeTable}`,
              { method: 'POST', body: JSON.stringify(row) },
            )}
            onUpdate={async (name, row) => {
              const current = values.find(v => v.name === name)
              const merged = { ...current, ...row }
              // The table's own columns travel only when they are the ones that changed.
              const own = Object.fromEntries(
                Object.entries(row).filter(([k]) => !['name', 'display_label', 'sort_order', 'description'].includes(k)),
              )
              return submit<EnumValue>(
                `save "${name}" in ${activeTable}`,
                `/admin/enums/${activeTable}/${encodeURIComponent(name)}`,
                {
                  method: 'PUT',
                  body: JSON.stringify({
                    display_label: merged.display_label,
                    sort_order: merged.sort_order,
                    description: merged.description,
                    ...own,
                  }),
                },
              )
            }}
            onDelete={async (name) => {
              await submit<unknown>(
                `delete "${name}" from ${activeTable}`,
                `/admin/enums/${activeTable}/${encodeURIComponent(name)}`,
                { method: 'DELETE' },
              )
              return true
            }}
            onRefresh={loadValues}
          />
          <div className="text-xs" style={{ marginTop: 8, display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="text-muted">Rename a value (every column that names it is rewritten):</span>
            <select
              aria-label="Value to rename"
              value={renaming.from}
              onChange={e => setRenaming({ from: e.target.value, to: '' })}
              style={{ fontSize: 11 }}
            >
              <option value="">(choose)</option>
              {values.map(v => <option key={v.name} value={v.name}>{v.name}</option>)}
            </select>
            <input
              aria-label="New name"
              value={renaming.to}
              onChange={e => setRenaming(r => ({ ...r, to: e.target.value }))}
              placeholder="new name"
              style={{ fontSize: 11, padding: '1px 4px' }}
            />
            <button
              style={{ fontSize: 10 }}
              disabled={!renaming.from || !renaming.to || renaming.to === renaming.from}
              onClick={async () => {
                try {
                  const reply = await submit<{ report?: { dangling?: unknown[] } }>(
                    `rename "${renaming.from}" in ${activeTable}`,
                    `/admin/enums/${activeTable}/${encodeURIComponent(renaming.from)}/rename`,
                    { method: 'POST', body: JSON.stringify({ new_name: renaming.to }) },
                  )
                  const left = reply.report?.dangling?.length ?? 0
                  setRenameMessage({
                    ok: true,
                    text: left
                      ? `Renamed. ${left} place(s) in code, parameters or templates still spell the old name: see the journal entry.`
                      : 'Renamed.',
                  })
                  setRenaming({ from: '', to: '' })
                  loadValues()
                } catch (err) {
                  setRenameMessage({ ok: false, text: err instanceof Error ? err.message : String(err) })
                }
              }}
            >
              Rename
            </button>
            {renameMessage && (
              <span
                role={renameMessage.ok ? 'status' : 'alert'}
                style={{ color: renameMessage.ok ? 'var(--success)' : 'var(--error)' }}
              >
                {renameMessage.text}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  )
}
