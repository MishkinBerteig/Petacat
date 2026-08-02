import { useState, useEffect, useCallback } from 'react'
import { EditableTable, LoadFailure, type ColumnDef } from './EditableTable'
import { request, describeApiError } from '@/api/client'

interface LayoutPos {
  node_name: string
  grid_row: number
  grid_col: number
}

const COLUMNS: ColumnDef[] = [
  { key: 'node_name', label: 'Node Name', type: 'text', width: '50%' },
  { key: 'grid_row', label: 'Row', type: 'number', width: '20%' },
  { key: 'grid_col', label: 'Col', type: 'number', width: '20%' },
]

/** `PUT` carries the whole position, so an edited field is merged into its row. */
function merged(rows: LayoutPos[], nodeName: string, patch: Partial<LayoutPos>) {
  const current = rows.find(r => r.node_name === nodeName)
  return {
    node_name: nodeName,
    grid_row: patch.grid_row ?? current?.grid_row ?? 0,
    grid_col: patch.grid_col ?? current?.grid_col ?? 0,
  }
}

/** Each operation named for this collection, so a refusal says which thing it refused. */
const ACTIONS = {
  create: 'add the grid position',
  update: 'save the grid position',
  delete: 'delete the grid position',
}

export function SlipnetLayoutEditor() {
  const [positions, setPositions] = useState<LayoutPos[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // A refresh leaves the table on screen, so the flash reporting what just happened
  // survives the reload it triggered.
  const load = useCallback(() => {
    request<LayoutPos[]>('/admin/slipnet-layout')
      .then(data => { setPositions(data); setLoadError(null) })
      .catch(e => setLoadError(describeApiError(e, 'load the slipnet layout')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading slipnet layout...</div>
  if (loadError) return <LoadFailure message={loadError} onRetry={load} />

  const maxRow = Math.max(...positions.map(p => p.grid_row), 0)
  const maxCol = Math.max(...positions.map(p => p.grid_col), 0)

  return (
    <div>
      <div className="text-xs text-muted mb-2">
        {positions.length} nodes in a {maxRow + 1} x {maxCol + 1} grid (double-click to edit).
        Row and column place a node in the Slipnet grid view.
      </div>
      <EditableTable
        columns={COLUMNS}
        rows={positions}
        idKey="node_name"
        actions={ACTIONS}
        onCreate={async (row) => request<LayoutPos>('/admin/slipnet-layout', {
          method: 'POST',
          body: JSON.stringify({
            node_name: row.node_name ?? '',
            grid_row: row.grid_row ?? 0,
            grid_col: row.grid_col ?? 0,
          }),
        })}
        onUpdate={async (nodeName, row) => request<LayoutPos>(
          `/admin/slipnet-layout/${encodeURIComponent(String(nodeName))}`,
          {
            method: 'PUT',
            body: JSON.stringify(merged(positions, String(nodeName), row)),
          },
        )}
        onDelete={async (nodeName) => {
          await request<void>(
            `/admin/slipnet-layout/${encodeURIComponent(String(nodeName))}`,
            { method: 'DELETE' },
          )
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
