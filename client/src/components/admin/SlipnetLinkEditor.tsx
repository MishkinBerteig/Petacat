import { useState, useEffect, useCallback } from 'react'
import { EditableTable, type ColumnDef } from './EditableTable'

interface LinkDef {
  id: number
  from_node: string
  to_node: string
  link_type: string
  label_node: string | null
  link_length: number | null
  fixed_length: boolean
}

const COLUMNS: ColumnDef[] = [
  { key: 'id', label: 'ID', type: 'readonly', width: '6%' },
  { key: 'from_node', label: 'From', type: 'text', width: '18%' },
  { key: 'to_node', label: 'To', type: 'text', width: '18%' },
  { key: 'link_type', label: 'Type', type: 'text', width: '14%' },
  { key: 'label_node', label: 'Label', type: 'text', width: '18%' },
  { key: 'link_length', label: 'Length', type: 'number', width: '8%' },
]

export function SlipnetLinkEditor() {
  const [links, setLinks] = useState<LinkDef[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')

  const load = useCallback(() => {
    fetch('/api/admin/slipnet/links').then(r => r.json()).then(data => {
      setLinks(data)
      setLoading(false)
    })
  }, [])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading slipnet links...</div>

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
        onCreate={async (row) => {
          const res = await fetch('/api/admin/slipnet/links', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              from_node: row.from_node, to_node: row.to_node,
              link_type: row.link_type, label_node: row.label_node || null,
              link_length: row.link_length ? Number(row.link_length) : null,
              fixed_length: true,
            }),
          })
          if (!res.ok) throw new Error(await res.text())
          return res.json()
        }}
        onUpdate={async (id, row) => {
          const current = links.find(l => l.id === id)
          const merged = { ...current, ...row }
          const res = await fetch(`/api/admin/slipnet/links/${id}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              from_node: merged.from_node, to_node: merged.to_node,
              link_type: merged.link_type, label_node: merged.label_node || null,
              link_length: merged.link_length ? Number(merged.link_length) : null,
              fixed_length: merged.fixed_length ?? true,
            }),
          })
          if (!res.ok) throw new Error(await res.text())
          return res.json()
        }}
        onDelete={async (id) => {
          const res = await fetch(`/api/admin/slipnet/links/${id}`, { method: 'DELETE' })
          if (!res.ok) throw new Error(await res.text())
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
