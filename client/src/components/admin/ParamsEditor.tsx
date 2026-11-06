import { useState, useEffect, useCallback } from 'react'
import { EditableTable, LoadFailure, type ColumnDef } from './EditableTable'
import { describeApiError, GLOBAL_CONFIGURATION_ID } from '@/api/client'
import { useAdminRequest, type AdminRequest, type ConfigurationProp } from './adminRequest'

interface Param {
  name: string
  value: string
  value_type: string
  /** What the value's names refer to, so a change that renames or removes the thing updates it. */
  refers_to?: string | null
}

/** What a parameter's names can refer to (`engine_params.refers_to`); none for most. */
const REFERS_TO = [
  'node_list', 'trigger_node_list', 'node_map', 'codelet_type_list', 'urgency_level',
  'clampable_pattern_map', 'clampable_pattern_list',
]

const COLUMNS: ColumnDef[] = [
  { key: 'name', label: 'Name', type: 'text', width: '38%' },
  { key: 'value', label: 'Value', type: 'text', width: '30%' },
  { key: 'value_type', label: 'Type', type: 'text', width: '14%' },
  { key: 'refers_to', label: 'Refers to', type: 'select', options: REFERS_TO, width: '18%' },
]

/** Each operation named for this collection, so a refusal says which thing it refused. */
const ACTIONS = {
  create: 'add the parameter',
  update: 'save the parameter',
  delete: 'delete the parameter',
}

export function ParamsEditor({ configuration = GLOBAL_CONFIGURATION_ID }: ConfigurationProp) {
  const request = useAdminRequest(configuration)
  const [params, setParams] = useState<Param[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // A refresh leaves the table on screen, so the flash reporting what just happened
  // survives the reload it triggered.
  const load = useCallback(() => {
    request<Param[]>('/admin/params')
      .then(data => { setParams(data); setLoadError(null) })
      .catch(e => setLoadError(describeApiError(e, 'load the engine parameters')))
      .finally(() => setLoading(false))
  }, [request])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading parameters...</div>
  if (loadError) return <LoadFailure message={loadError} onRetry={load} />

  return (
    <div>
      <div className="text-xs text-muted mb-2">
        {params.length} engine parameters (double-click to edit). A saved change is picked
        up by the next run created.
      </div>
      <EditableTable
        columns={COLUMNS}
        rows={params}
        idKey="name"
        actions={ACTIONS}
        onCreate={async (row) => request<Param>('/admin/params', {
          method: 'POST',
          body: JSON.stringify({
            name: row.name ?? '',
            value: row.value ?? '',
            value_type: row.value_type || 'string',
            ...(row.refers_to ? { refers_to: row.refers_to } : {}),
          }),
        })}
        onUpdate={async (name, row) => {
          const current = params.find(p => p.name === name)
          return request<Param>(`/admin/params/${encodeURIComponent(String(name))}`, {
            method: 'PUT',
            body: JSON.stringify({
              value: row.value ?? current?.value ?? '',
              value_type: row.value_type ?? current?.value_type ?? 'string',
              ...('refers_to' in row ? { refers_to: row.refers_to } : {}),
            }),
          })
        }}
        onDelete={async (name) => {
          await request<void>(
            `/admin/params/${encodeURIComponent(String(name))}`, { method: 'DELETE' },
          )
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
