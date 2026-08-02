import { useState, useEffect, useCallback } from 'react'
import { request, describeApiError } from '@/api/client'
import { EditableTable, type ColumnDef } from './EditableTable'

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

interface LinkDef {
  id: number
  from_node: string
  to_node: string
  link_type: string
  label_node: string | null
  /**
   * The conceptual distance the link spans. `0` is a length in its own right — concepts
   * with no distance between them, so the link carries the full degree of association —
   * and `null` leaves the length to the label node to supply.
   */
  link_length: number | null
  fixed_length: boolean
}

const COLUMNS: ColumnDef[] = [
  { key: 'id', label: 'ID', type: 'readonly', width: '6%' },
  { key: 'from_node', label: 'From', type: 'text', width: '18%' },
  { key: 'to_node', label: 'To', type: 'text', width: '18%' },
  { key: 'link_type', label: 'Type', type: 'text', width: '14%' },
  { key: 'label_node', label: 'Label', type: 'text', width: '18%' },
  // A link may carry no fixed length, so an empty box means absent rather than zero.
  { key: 'link_length', label: 'Length', type: 'number', width: '8%', nullable: true },
]

export function SlipnetLinkEditor() {
  const [links, setLinks] = useState<LinkDef[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    request<LinkDef[]>('/admin/slipnet/links')
      .then(data => { setLinks(data); setError(null) })
      .catch(err => setError(describeApiError(err, 'load the slipnet links')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading slipnet links...</div>

  if (error) {
    return (
      <div role="alert" className="text-xs" style={{ color: 'var(--error)' }}>
        {error}{' '}
        <button onClick={load} style={{ fontSize: 10, padding: '1px 6px' }}>Retry</button>
      </div>
    )
  }

  const filtered = filter
    ? links.filter(l =>
        l.from_node.includes(filter) || l.to_node.includes(filter) ||
        l.link_type.includes(filter) || (l.label_node ?? '').includes(filter)
      )
    : links

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <div className="text-xs text-muted">{links.length} links ({filtered.length} shown)</div>
        <input
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="Filter by node or type..."
          style={{ fontSize: 11, padding: '2px 6px', width: 200 }}
        />
      </div>
      <EditableTable
        columns={COLUMNS}
        rows={filtered}
        idKey="id"
        onCreate={async (row) => submit<LinkDef>(
          'create the slipnet link',
          '/admin/slipnet/links',
          {
            method: 'POST',
            body: JSON.stringify({
              from_node: row.from_node, to_node: row.to_node,
              link_type: row.link_type, label_node: row.label_node || null,
              link_length: row.link_length == null ? null : Number(row.link_length),
              fixed_length: true,
            }),
          },
        )}
        onUpdate={async (id, row) => {
          const current = links.find(l => l.id === id)
          const merged = { ...current, ...row }
          return submit<LinkDef>(
            `save slipnet link ${id}`,
            `/admin/slipnet/links/${id}`,
            {
              method: 'PUT',
              body: JSON.stringify({
                from_node: merged.from_node, to_node: merged.to_node,
                link_type: merged.link_type, label_node: merged.label_node || null,
                link_length: merged.link_length == null ? null : Number(merged.link_length),
                fixed_length: merged.fixed_length ?? true,
              }),
            },
          )
        }}
        onDelete={async (id) => {
          await submit<unknown>(
            `delete slipnet link ${id}`,
            `/admin/slipnet/links/${id}`,
            { method: 'DELETE' },
          )
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
