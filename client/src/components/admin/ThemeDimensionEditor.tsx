import { useState, useEffect, useCallback } from 'react'
import { EditableTable, LoadFailure, type ColumnDef } from './EditableTable'
import { request, describeApiError } from '@/api/client'

interface ThemeDim {
  id: number
  slipnet_node: string
  valid_relations: string[]
}

const COLUMNS: ColumnDef[] = [
  { key: 'id', label: 'ID', type: 'readonly', width: '8%' },
  { key: 'slipnet_node', label: 'Slipnet Node', type: 'text', width: '40%' },
  { key: 'valid_relations', label: 'Valid Relations', type: 'json' },
]

/** `PUT` carries the whole row, so an edited field is merged into the row it came from. */
function merged(rows: ThemeDim[], id: number, patch: Partial<ThemeDim>) {
  const current = rows.find(r => r.id === id)
  return {
    slipnet_node: patch.slipnet_node ?? current?.slipnet_node ?? '',
    valid_relations: patch.valid_relations ?? current?.valid_relations ?? [],
  }
}

/** Each operation named for this collection, so a refusal says which thing it refused. */
const ACTIONS = {
  create: 'add the theme dimension',
  update: 'save the theme dimension',
  delete: 'delete the theme dimension',
}

export function ThemeDimensionEditor() {
  const [dims, setDims] = useState<ThemeDim[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // A refresh leaves the table on screen, so the flash reporting what just happened
  // survives the reload it triggered.
  const load = useCallback(() => {
    request<ThemeDim[]>('/admin/theme-dimensions')
      .then(data => { setDims(data); setLoadError(null) })
      .catch(e => setLoadError(describeApiError(e, 'load the theme dimensions')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading theme dimensions...</div>
  if (loadError) return <LoadFailure message={loadError} onRetry={load} />

  return (
    <div>
      <div className="text-xs text-muted mb-2">
        {dims.length} theme dimensions (double-click to edit). A dimension and its relations
        decide which themes exist for each of the three bridge types.
      </div>
      <EditableTable
        columns={COLUMNS}
        rows={dims}
        idKey="id"
        actions={ACTIONS}
        onCreate={async (row) => request<ThemeDim>('/admin/theme-dimensions', {
          method: 'POST',
          body: JSON.stringify({
            slipnet_node: row.slipnet_node ?? '',
            valid_relations: row.valid_relations ?? [],
          }),
        })}
        onUpdate={async (id, row) => request<ThemeDim>(`/admin/theme-dimensions/${id}`, {
          method: 'PUT',
          body: JSON.stringify(merged(dims, id as number, row)),
        })}
        onDelete={async (id) => {
          await request<void>(`/admin/theme-dimensions/${id}`, { method: 'DELETE' })
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
