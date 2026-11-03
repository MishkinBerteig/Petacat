import { useState, useEffect, useCallback } from 'react'
import { describeApiError, GLOBAL_CONFIGURATION_ID } from '@/api/client'
import { useAdminRequest, type AdminRequest, type ConfigurationProp } from './adminRequest'
import { EditableTable, type ColumnDef } from './EditableTable'

/**
 * ``value`` is text: ``5``, ``0.5`` or an exact rational ``n/m`` (such as ``2/3``), held and
 * shown exactly, never as a rounded decimal.  ``value_type`` is ``int``, ``float`` or ``rational``.
 */
interface FormulaCoeff { name: string; value: string; value_type: string }

/**
 * Send one write, and describe a refusal in terms of what was being attempted.
 *
 * The table shows the thrown message beside the row that was edited, so the sentence it
 * throws is the sentence the reader gets.
 */
const submitWith = (request: AdminRequest) =>
  async function submit<T>(action: string, path: string, options: RequestInit): Promise<T> {
    try {
      return await request<T>(path, options)
    } catch (err) {
      throw new Error(describeApiError(err, action))
    }
  }

const COLUMNS: ColumnDef[] = [
  { key: 'name', label: 'Name', type: 'readonly', width: '50%' },
  { key: 'value', label: 'Value', type: 'text', width: '30%' },
  { key: 'value_type', label: 'Type', type: 'text', width: '20%' },
]

export function FormulaCoefficientEditor({ configuration = GLOBAL_CONFIGURATION_ID }: ConfigurationProp) {
  const request = useAdminRequest(configuration)
  const submit = submitWith(request)
  const [coeffs, setCoeffs] = useState<FormulaCoeff[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    request<FormulaCoeff[]>('/admin/formula-coefficients')
      .then(data => { setCoeffs(data); setError(null) })
      .catch(err => setError(describeApiError(err, 'load the formula coefficients')))
      .finally(() => setLoading(false))
  }, [request])

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
      <div className="text-xs text-muted mb-2">{coeffs.length} formula coefficients (double-click to edit). A value is a number, or
        {' '}n/m for an exact rational such as 2/3.</div>
      <EditableTable
        columns={COLUMNS}
        rows={coeffs}
        idKey="name"
        onCreate={async (row) => submit<FormulaCoeff>(
          'create the formula coefficient',
          '/admin/formula-coefficients',
          {
            method: 'POST',
            body: JSON.stringify({
              name: row.name ?? '',
              value: row.value ?? '',
              value_type: row.value_type || 'float',
            }),
          },
        )}
        onUpdate={async (name, row) => {
          const current = coeffs.find(c => c.name === name)
          return submit<FormulaCoeff>(
            `save the formula coefficient "${name}"`,
            `/admin/formula-coefficients/${encodeURIComponent(String(name))}`,
            {
              method: 'PUT',
              body: JSON.stringify({
                value: row.value ?? current?.value ?? '',
                value_type: row.value_type ?? current?.value_type ?? 'float',
              }),
            },
          )
        }}
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
