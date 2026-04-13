import { useState, useEffect, useCallback, useRef } from 'react'
import { EditableTable, type ColumnDef } from './EditableTable'

interface NodeDef {
  name: string
  short_name: string
  conceptual_depth: number
  description?: string
}

const COLUMNS: ColumnDef[] = [
  { key: 'name', label: 'Name', type: 'readonly', width: '30%' },
  { key: 'short_name', label: 'Short', type: 'text', width: '15%' },
  { key: 'conceptual_depth', label: 'Depth', type: 'number', width: '10%' },
  { key: 'description', label: 'Description', type: 'text' },
]

interface Props {
  editNodeName?: string | null;
  onClearEditNode?: () => void;
}

export function SlipnetEditor({ editNodeName, onClearEditNode }: Props) {
  const [nodes, setNodes] = useState<NodeDef[]>([])
  const [loading, setLoading] = useState(true)
  const [highlightNode, setHighlightNode] = useState<string | null>(null)
  const highlightRef = useRef<HTMLTableRowElement>(null)

  const load = useCallback(() => {
    fetch('/api/admin/slipnet/nodes').then(r => r.json()).then(setNodes).finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  // When editNodeName is set, scroll to and highlight the row
  useEffect(() => {
    if (editNodeName && nodes.length > 0) {
      setHighlightNode(editNodeName)
      // Scroll after render
      requestAnimationFrame(() => {
        highlightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      })
      // Clear the highlight and edit intent after a delay
      const timer = setTimeout(() => {
        setHighlightNode(null)
        onClearEditNode?.()
      }, 3000)
      return () => clearTimeout(timer)
    }
  }, [editNodeName, nodes, onClearEditNode])

  if (loading) return <div className="text-muted">Loading nodes...</div>

  return (
    <div>
      <div className="text-xs text-muted mb-2">{nodes.length} slipnet nodes (double-click to edit)</div>
      <EditableTable
        columns={COLUMNS}
        rows={nodes}
        idKey="name"
        highlightId={highlightNode}
        highlightRef={highlightRef}
        onCreate={async (row) => {
          const res = await fetch('/api/admin/slipnet/nodes', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(row),
          })
          if (!res.ok) throw new Error(await res.text())
          return res.json()
        }}
        onUpdate={async (name, row) => {
          const current = nodes.find(n => n.name === name)
          const merged = { ...current, ...row }
          const res = await fetch(`/api/admin/slipnet/nodes/${encodeURIComponent(name)}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(merged),
          })
          if (!res.ok) throw new Error(await res.text())
          return res.json()
        }}
        onDelete={async (name) => {
          const res = await fetch(`/api/admin/slipnet/nodes/${encodeURIComponent(name)}`, { method: 'DELETE' })
          if (!res.ok) throw new Error(await res.text())
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
