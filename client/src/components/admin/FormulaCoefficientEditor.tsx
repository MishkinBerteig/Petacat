import { useState, useEffect, useCallback } from 'react'
import { request, describeApiError } from '@/api/client'
import { EditableTable, type ColumnDef } from './EditableTable'

interface FormulaCoeff { name: string; value: number }

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
  { key: 'name', label: 'Name', type: 'readonly', width: '60%' },
  { key: 'value', label: 'Value', type: 'number', width: '20%' },
]

export function FormulaCoefficientEditor() {
  const [coeffs, setCoeffs] = useState<FormulaCoeff[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    request<FormulaCoeff[]>('/admin/formula-coefficients')
      .then(data => { setCoeffs(data); setError(null) })
      .catch(err => setError(describeApiError(err, 'load the formula coefficients')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading formula coefficients...</div>

  if (error) {
    return (
      <div role="alert" className="text-xs" style={{ color: 'var(--error)' }}>
        {error}{' '}
        <button onClick={load} style={{ fontSize: 10, padding: '1px 6px' }}>Retry</button>
      </div>
    )
  }

  return (
    <div>
      <div className="text-xs text-muted mb-2">{coeffs.length} formula coefficients (double-click to edit)</div>
      <EditableTable
        columns={COLUMNS}
        rows={coeffs}
        idKey="name"
        onCreate={async (row) => submit<FormulaCoeff>(
          'create the formula coefficient',
          '/admin/formula-coefficients',
          { method: 'POST', body: JSON.stringify(row) },
        )}
        onUpdate={async (name, row) => submit<FormulaCoeff>(
          `save the formula coefficient "${name}"`,
          `/admin/formula-coefficients/${encodeURIComponent(name)}`,
          { method: 'PUT', body: JSON.stringify({ value: row.value }) },
        )}
        onDelete={async (name) => {
          await submit<unknown>(
            `delete the formula coefficient "${name}"`,
            `/admin/formula-coefficients/${encodeURIComponent(name)}`,
            { method: 'DELETE' },
          )
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
