import { useState, useEffect, useCallback } from 'react'
import { EditableTable, LoadFailure, type ColumnDef } from './EditableTable'
import { request, describeApiError } from '@/api/client'

interface PostingRule {
  id: number
  codelet_type: string
  direction: string
  urgency_when_posted: number | null
  urgency_formula: string | null
  posting_formula: string
  count_formula: string
  count_values: Record<string, unknown> | null
  condition: string
  triggering_slipnodes: string[] | null
}

const COLUMNS: ColumnDef[] = [
  { key: 'id', label: 'ID', type: 'readonly', width: '5%' },
  { key: 'codelet_type', label: 'Codelet Type', type: 'text', width: '18%' },
  { key: 'direction', label: 'Direction', type: 'text', width: '10%' },
  { key: 'urgency_when_posted', label: 'Urgency', type: 'number', width: '8%' },
  { key: 'urgency_formula', label: 'Urgency Formula', type: 'text', width: '13%' },
  { key: 'posting_formula', label: 'Posting Formula', type: 'text', width: '13%' },
  { key: 'count_formula', label: 'Count Formula', type: 'text', width: '11%' },
  { key: 'count_values', label: 'Count Values', type: 'json', width: '10%' },
  { key: 'condition', label: 'Condition', type: 'text', width: '8%' },
  { key: 'triggering_slipnodes', label: 'Triggers', type: 'json' },
]

/** `PUT` carries the whole rule, so an edited field is merged into the rule it came from. */
function merged(rows: PostingRule[], id: number, patch: Partial<PostingRule>) {
  const c = rows.find(r => r.id === id)
  const pick = <K extends keyof PostingRule>(key: K, fallback: PostingRule[K]) =>
    (patch[key] !== undefined ? patch[key] : c?.[key]) ?? fallback
  return {
    codelet_type: pick('codelet_type', ''),
    direction: pick('direction', ''),
    urgency_when_posted: patch.urgency_when_posted !== undefined
      ? patch.urgency_when_posted : (c?.urgency_when_posted ?? null),
    urgency_formula: patch.urgency_formula !== undefined
      ? patch.urgency_formula : (c?.urgency_formula ?? null),
    posting_formula: pick('posting_formula', ''),
    count_formula: pick('count_formula', ''),
    count_values: patch.count_values !== undefined
      ? patch.count_values : (c?.count_values ?? null),
    condition: pick('condition', 'always'),
    triggering_slipnodes: patch.triggering_slipnodes !== undefined
      ? patch.triggering_slipnodes : (c?.triggering_slipnodes ?? null),
  }
}

/** Each operation named for this collection, so a refusal says which thing it refused. */
const ACTIONS = {
  create: 'add the posting rule',
  update: 'save the posting rule',
  delete: 'delete the posting rule',
}

export function PostingRuleEditor() {
  const [rules, setRules] = useState<PostingRule[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // A refresh leaves the table on screen, so the flash reporting what just happened
  // survives the reload it triggered.
  const load = useCallback(() => {
    request<PostingRule[]>('/admin/posting-rules')
      .then(data => { setRules(data); setLoadError(null) })
      .catch(e => setLoadError(describeApiError(e, 'load the posting rules')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading posting rules...</div>
  if (loadError) return <LoadFailure message={loadError} onRetry={load} />

  return (
    <div>
      <div className="text-xs text-muted mb-2">
        {rules.length} posting rules (double-click to edit). A rule says which codelet type
        is posted, at what urgency, and what has to hold for it to be posted at all.
      </div>
      <EditableTable
        columns={COLUMNS}
        rows={rules}
        idKey="id"
        actions={ACTIONS}
        onCreate={async (row) => request<PostingRule>('/admin/posting-rules', {
          method: 'POST',
          body: JSON.stringify(merged([], -1, row as Partial<PostingRule>)),
        })}
        onUpdate={async (id, row) => request<PostingRule>(`/admin/posting-rules/${id}`, {
          method: 'PUT',
          body: JSON.stringify(merged(rules, id as number, row)),
        })}
        onDelete={async (id) => {
          await request<void>(`/admin/posting-rules/${id}`, { method: 'DELETE' })
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
