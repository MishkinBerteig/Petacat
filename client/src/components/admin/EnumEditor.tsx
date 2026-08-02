import { useState, useEffect, useCallback } from 'react'
import { request, describeApiError } from '@/api/client'
import { EditableTable, type ColumnDef } from './EditableTable'

interface EnumValue {
  name: string
  display_label: string
  sort_order: number
  description: string
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

const COLUMNS: ColumnDef[] = [
  { key: 'name', label: 'Name', type: 'readonly', width: '20%' },
  { key: 'display_label', label: 'Display Label', type: 'text', width: '20%' },
  { key: 'sort_order', label: 'Order', type: 'number', width: '10%' },
  { key: 'description', label: 'Description', type: 'text' },
]

export function EnumEditor() {
  const [tables, setTables] = useState<string[]>([])
  const [activeTable, setActiveTable] = useState<string>('')
  const [values, setValues] = useState<EnumValue[]>([])
  const [loading, setLoading] = useState(true)
  // Two loads with two outcomes: which tables exist, and what is in the open one.
  const [tablesError, setTablesError] = useState<string | null>(null)
  const [valuesError, setValuesError] = useState<string | null>(null)

  const loadTables = useCallback(() => {
    setLoading(true)
    request<{ tables: string[] }>('/admin/enums')
      .then(data => {
        const t = data.tables ?? []
        setTables(t)
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
          <EditableTable
            columns={COLUMNS}
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
              return submit<EnumValue>(
                `save "${name}" in ${activeTable}`,
                `/admin/enums/${activeTable}/${encodeURIComponent(name)}`,
                {
                  method: 'PUT',
                  body: JSON.stringify({
                    display_label: merged.display_label,
                    sort_order: merged.sort_order,
                    description: merged.description,
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
        </>
      )}
    </div>
  )
}
