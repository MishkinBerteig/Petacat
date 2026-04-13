import { useState, useEffect, useCallback } from 'react'
import { EditableTable, type ColumnDef } from './EditableTable'

interface UrgencyLevel { name: string; value: number }

const COLUMNS: ColumnDef[] = [
  { key: 'name', label: 'Name', type: 'readonly', width: '40%' },
  { key: 'value', label: 'Value', type: 'number', width: '20%' },
]

export function UrgencyLevelEditor() {
  const [levels, setLevels] = useState<UrgencyLevel[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    fetch('/api/admin/urgency-levels').then(r => r.json()).then(data => {
      setLevels(Array.isArray(data) ? data : Object.entries(data).map(([name, value]) => ({ name, value: value as number })))
      setLoading(false)
    })
  }, [])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading urgency levels...</div>

  const sorted = [...levels].sort((a, b) => a.value - b.value)

  return (
    <div>
      <div className="text-xs text-muted mb-2">{sorted.length} urgency levels (double-click to edit)</div>
      <EditableTable
        columns={COLUMNS}
        rows={sorted}
        idKey="name"
        onCreate={async (row) => {
          const res = await fetch('/api/admin/urgency-levels', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(row),
          })
          if (!res.ok) throw new Error(await res.text())
          return res.json()
        }}
        onUpdate={async (name, row) => {
          const res = await fetch(`/api/admin/urgency-levels/${encodeURIComponent(name)}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: row.value }),
          })
          if (!res.ok) throw new Error(await res.text())
          return res.json()
        }}
        onDelete={async (name) => {
          const res = await fetch(`/api/admin/urgency-levels/${encodeURIComponent(name)}`, { method: 'DELETE' })
          if (!res.ok) throw new Error(await res.text())
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
