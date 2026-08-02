import { useState, useEffect, useCallback } from 'react'
import { request, describeApiError } from '@/api/client'
import { EditableTable, type ColumnDef } from './EditableTable'

interface UrgencyLevel { name: string; value: number }

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
  { key: 'name', label: 'Name', type: 'readonly', width: '40%' },
  { key: 'value', label: 'Value', type: 'number', width: '20%' },
]

export function UrgencyLevelEditor() {
  const [levels, setLevels] = useState<UrgencyLevel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    // The seven bins arrive as a list of rows or as one object keyed by name; both say
    // the same thing, so both are read into the same list of levels.
    request<UrgencyLevel[] | Record<string, number>>('/admin/urgency-levels')
      .then(data => {
        setLevels(
          Array.isArray(data)
            ? data
            : Object.entries(data).map(([name, value]) => ({ name, value: value as number })),
        )
        setError(null)
      })
      .catch(err => setError(describeApiError(err, 'load the urgency levels')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading urgency levels...</div>

  if (error) {
    return (
      <div role="alert" className="text-xs" style={{ color: 'var(--error)' }}>
        {error}{' '}
        <button onClick={load} style={{ fontSize: 10, padding: '1px 6px' }}>Retry</button>
      </div>
    )
  }

  const sorted = [...levels].sort((a, b) => a.value - b.value)

  return (
    <div>
      <div className="text-xs text-muted mb-2">{sorted.length} urgency levels (double-click to edit)</div>
      <EditableTable
        columns={COLUMNS}
        rows={sorted}
        idKey="name"
        onCreate={async (row) => submit<UrgencyLevel>(
          'create the urgency level',
          '/admin/urgency-levels',
          { method: 'POST', body: JSON.stringify(row) },
        )}
        onUpdate={async (name, row) => submit<UrgencyLevel>(
          `save the urgency level "${name}"`,
          `/admin/urgency-levels/${encodeURIComponent(name)}`,
          { method: 'PUT', body: JSON.stringify({ value: row.value }) },
        )}
        onDelete={async (name) => {
          await submit<unknown>(
            `delete the urgency level "${name}"`,
            `/admin/urgency-levels/${encodeURIComponent(name)}`,
            { method: 'DELETE' },
          )
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
