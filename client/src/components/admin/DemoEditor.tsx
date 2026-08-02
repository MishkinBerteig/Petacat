import { useState, useEffect, useCallback } from 'react'
import { EditableTable, LoadFailure, type ColumnDef } from './EditableTable'
import { request, describeApiError } from '@/api/client'
import type { DemoProblem } from '@/types'

const COLUMNS: ColumnDef[] = [
  { key: 'id', label: 'ID', type: 'readonly', width: '5%' },
  { key: 'name', label: 'Name', type: 'text', width: '20%' },
  { key: 'section', label: 'Section', type: 'text', width: '9%' },
  { key: 'initial', label: 'Initial', type: 'text', width: '9%' },
  { key: 'modified', label: 'Modified', type: 'text', width: '9%' },
  { key: 'target', label: 'Target', type: 'text', width: '9%' },
  { key: 'answer', label: 'Answer', type: 'text', width: '9%' },
  { key: 'seed', label: 'Seed', type: 'number', width: '7%' },
  { key: 'mode', label: 'Mode', type: 'text', width: '9%' },
  { key: 'description', label: 'Description', type: 'text' },
]

/** `PUT` carries the whole demo, so an edited field is merged into the demo it came from. */
function merged(rows: DemoProblem[], id: number, patch: Partial<DemoProblem>) {
  const c = rows.find(r => r.id === id)
  const take = <K extends keyof DemoProblem>(key: K) =>
    patch[key] !== undefined ? patch[key] : c?.[key]
  return {
    name: take('name') ?? '',
    section: take('section') ?? '',
    initial: take('initial') ?? '',
    modified: take('modified') ?? '',
    target: take('target') ?? '',
    answer: take('answer') || null,
    seed: Number(take('seed') ?? 0),
    mode: take('mode') ?? 'discovery',
    description: take('description') ?? '',
  }
}

/** Each operation named for this collection, so a refusal says which thing it refused. */
const ACTIONS = {
  create: 'add the demo problem',
  update: 'save the demo problem',
  delete: 'delete the demo problem',
}

export function DemoEditor() {
  const [demos, setDemos] = useState<DemoProblem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // A refresh leaves the table on screen, so the flash reporting what just happened
  // survives the reload it triggered.
  const load = useCallback(() => {
    request<DemoProblem[]>('/admin/demos')
      .then(data => { setDemos(data); setLoadError(null) })
      .catch(e => setLoadError(describeApiError(e, 'load the demo problems')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading demos...</div>
  if (loadError) return <LoadFailure message={loadError} onRetry={load} />

  return (
    <div>
      <div className="text-xs text-muted mb-2">
        {demos.length} demo problems (double-click to edit). A demo is a problem, a seed and
        a mode; adding one puts it in the Problem Input dropdown.
      </div>
      <EditableTable
        columns={COLUMNS}
        rows={demos as unknown as Record<string, any>[]}
        idKey="id"
        actions={ACTIONS}
        onCreate={async (row) => request<Record<string, any>>('/admin/demos', {
          method: 'POST',
          body: JSON.stringify(merged([], -1, row as Partial<DemoProblem>)),
        })}
        onUpdate={async (id, row) => request<Record<string, any>>(`/admin/demos/${id}`, {
          method: 'PUT',
          body: JSON.stringify(merged(demos, id as number, row as Partial<DemoProblem>)),
        })}
        onDelete={async (id) => {
          await request<void>(`/admin/demos/${id}`, { method: 'DELETE' })
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
