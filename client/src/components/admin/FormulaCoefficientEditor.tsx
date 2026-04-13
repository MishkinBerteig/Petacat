import { useState, useEffect, useCallback } from 'react'
import { EditableTable, type ColumnDef } from './EditableTable'

interface FormulaCoeff { name: string; value: number }

const COLUMNS: ColumnDef[] = [
  { key: 'name', label: 'Name', type: 'readonly', width: '60%' },
  { key: 'value', label: 'Value', type: 'number', width: '20%' },
]

export function FormulaCoefficientEditor() {
  const [coeffs, setCoeffs] = useState<FormulaCoeff[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    fetch('/api/admin/formula-coefficients').then(r => r.json()).then(data => {
      setCoeffs(data)
      setLoading(false)
    })
  }, [])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading formula coefficients...</div>

  return (
    <div>
      <div className="text-xs text-muted mb-2">{coeffs.length} formula coefficients (double-click to edit)</div>
      <EditableTable
        columns={COLUMNS}
        rows={coeffs}
        idKey="name"
        onCreate={async (row) => {
          const res = await fetch('/api/admin/formula-coefficients', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(row),
          })
          if (!res.ok) throw new Error(await res.text())
          return res.json()
        }}
        onUpdate={async (name, row) => {
          const res = await fetch(`/api/admin/formula-coefficients/${encodeURIComponent(name)}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: row.value }),
          })
          if (!res.ok) throw new Error(await res.text())
          return res.json()
        }}
        onDelete={async (name) => {
          const res = await fetch(`/api/admin/formula-coefficients/${encodeURIComponent(name)}`, { method: 'DELETE' })
          if (!res.ok) throw new Error(await res.text())
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
