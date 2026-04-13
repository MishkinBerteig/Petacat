import { useState, useEffect, useCallback } from 'react'
import { EditableTable, type ColumnDef } from './EditableTable'

interface EnumValue {
  name: string
  display_label: string
  sort_order: number
  description: string
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

  useEffect(() => {
    fetch('/api/admin/enums').then(r => r.json()).then(data => {
      const t = data.tables || []
      setTables(t)
      if (t.length > 0) setActiveTable(t[0])
      setLoading(false)
    })
  }, [])

  const loadValues = useCallback(() => {
    if (!activeTable) return
    fetch(`/api/admin/enums/${activeTable}`).then(r => r.json()).then(setValues)
  }, [activeTable])

  useEffect(() => { loadValues() }, [loadValues])

  if (loading) return <div className="text-muted">Loading enum tables...</div>

  return (
    <div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
        {tables.map(t => (
          <button key={t} onClick={() => setActiveTable(t)} className={activeTable === t ? 'primary' : ''} style={{ fontSize: 11 }}>
            {t}
          </button>
        ))}
      </div>

      {activeTable && (
        <>
          <div className="text-xs text-muted mb-2">{values.length} values in {activeTable} (double-click to edit)</div>
          <EditableTable
            columns={COLUMNS}
            rows={values}
            idKey="name"
            onCreate={async (row) => {
              const res = await fetch(`/api/admin/enums/${activeTable}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(row),
              })
              if (!res.ok) throw new Error(await res.text())
              return res.json()
            }}
            onUpdate={async (name, row) => {
              const current = values.find(v => v.name === name)
              const merged = { ...current, ...row }
              const res = await fetch(`/api/admin/enums/${activeTable}/${encodeURIComponent(name)}`, {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ display_label: merged.display_label, sort_order: merged.sort_order, description: merged.description }),
              })
              if (!res.ok) throw new Error(await res.text())
              return res.json()
            }}
            onDelete={async (name) => {
              const res = await fetch(`/api/admin/enums/${activeTable}/${encodeURIComponent(name)}`, { method: 'DELETE' })
              if (!res.ok) throw new Error(await res.text())
              return true
            }}
            onRefresh={loadValues}
          />
        </>
      )}
    </div>
  )
}
