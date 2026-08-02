import { useState, useEffect, useCallback, useRef } from 'react'
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
  const [error, setError] = useState<string | null>(null)
  const [highlightNode, setHighlightNode] = useState<string | null>(null)
  const highlightRef = useRef<HTMLTableRowElement>(null)

  const load = useCallback(() => {
    setLoading(true)
    request<NodeDef[]>('/admin/slipnet/nodes')
      .then(data => { setNodes(data); setError(null) })
      .catch(err => setError(describeApiError(err, 'load the slipnet nodes')))
      .finally(() => setLoading(false))
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
      <div className="text-xs text-muted mb-2">{nodes.length} slipnet nodes (double-click to edit)</div>
      <EditableTable
        columns={COLUMNS}
        rows={nodes}
        idKey="name"
        highlightId={highlightNode}
        highlightRef={highlightRef}
        onCreate={async (row) => submit<NodeDef>(
          'create the slipnet node',
          '/admin/slipnet/nodes',
          { method: 'POST', body: JSON.stringify(row) },
        )}
        onUpdate={async (name, row) => {
          const current = nodes.find(n => n.name === name)
          const merged = { ...current, ...row }
          return submit<NodeDef>(
            `save the slipnet node "${name}"`,
            `/admin/slipnet/nodes/${encodeURIComponent(name)}`,
            { method: 'PUT', body: JSON.stringify(merged) },
          )
        }}
        onDelete={async (name) => {
          await submit<unknown>(
            `delete the slipnet node "${name}"`,
            `/admin/slipnet/nodes/${encodeURIComponent(name)}`,
            { method: 'DELETE' },
          )
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
