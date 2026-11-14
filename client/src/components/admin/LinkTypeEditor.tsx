import { useState, useEffect, useCallback } from 'react'
import { describeApiError, request as globalRequest, GLOBAL_CONFIGURATION_ID } from '@/api/client'
import { useAdminRequest, type AdminRequest, type ConfigurationProp } from './adminRequest'
import { EditableTable, type ColumnDef } from './EditableTable'

interface LinkType {
  name: string
  display_label: string
  sort_order: number
  description: string
  /** What the engine does with a link of this type; null is a plain link type. */
  behaviour: string | null
}

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

interface EnumTablesReply {
  roles?: Record<string, { column: string; roles: string[] }>
}

/**
 * The link types of a configuration.  A link type is a configuration table like any other (not an
 * enum table): a Training Mode Session's configuration may hold link types of its own.  The
 * engine names what a link does (its behaviour); the configuration names the types.  A type with
 * no behaviour is plain: its links spread activation by their fixed length and mean what the
 * codelets that read them make of them.
 */
export function LinkTypeEditor({ configuration = GLOBAL_CONFIGURATION_ID }: ConfigurationProp) {
  const request = useAdminRequest(configuration)
  const submit = submitWith(request)
  const [types, setTypes] = useState<LinkType[]>([])
  const [behaviours, setBehaviours] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      request<LinkType[]>('/admin/link-types'),
      // The engine's behaviours are the same whatever configuration is open.
      globalRequest<EnumTablesReply>('/admin/enums'),
    ])
      .then(([rows, enums]) => {
        setTypes(rows)
        setBehaviours(enums.roles?.link_types?.roles ?? [])
        setError(null)
      })
      .catch(err => setError(describeApiError(err, 'load the link types')))
      .finally(() => setLoading(false))
  }, [request])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading link types...</div>

  if (error) {
    return (
      <div role="alert" className="text-xs" style={{ color: 'var(--error)' }}>
        {error}{' '}
        <button onClick={load} style={{ fontSize: 10, padding: '1px 6px' }}>Retry</button>
      </div>
    )
  }

  const columns: ColumnDef[] = [
    { key: 'name', label: 'Name', type: 'readonly', width: '18%' },
    { key: 'display_label', label: 'Display Label', type: 'text', width: '16%' },
    { key: 'sort_order', label: 'Order', type: 'number', width: '7%' },
    { key: 'description', label: 'Description', type: 'text' },
    // The empty choice stores null: a plain link type.
    { key: 'behaviour', label: 'Behaviour', type: 'select', options: behaviours, width: '14%' },
  ]

  return (
    <div>
      <div className="text-xs text-muted mb-2">{types.length} link types (double-click to edit)</div>
      <div className="text-xs text-muted mb-2" data-testid="link-type-note">
        The behaviour is what the engine does with a link of this type: {behaviours.join(', ')}.
        With no behaviour a type is plain: its links spread activation by their length and mean what the
        codelets that read them make of them, so every plain link needs a fixed length.
        A type cannot be removed while a link has it.
      </div>
      <EditableTable
        columns={columns}
        rows={types}
        idKey="name"
        onCreate={async (row) => submit<LinkType>(
          'create the link type',
          '/admin/link-types',
          {
            method: 'POST',
            body: JSON.stringify({
              name: row.name,
              display_label: row.display_label || null,
              description: row.description ?? '',
              behaviour: row.behaviour || null,
            }),
          },
        )}
        onUpdate={async (name, row) => submit<LinkType>(
          `save the link type "${name}"`,
          `/admin/link-types/${encodeURIComponent(name)}`,
          { method: 'PUT', body: JSON.stringify(row) },
        )}
        onDelete={async (name) => {
          await submit<unknown>(
            `delete the link type "${name}"`,
            `/admin/link-types/${encodeURIComponent(name)}`,
            { method: 'DELETE' },
          )
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
