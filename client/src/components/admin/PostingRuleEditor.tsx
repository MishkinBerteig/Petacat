import { useState, useEffect } from 'react'

interface PostingRule {
  id: number
  codelet_type: string
  direction: string
  urgency_when_posted: number | null
  urgency_formula: string | null
  posting_formula: string
  count_formula: string
  condition: string
  triggering_slipnodes: string[] | null
}

export function PostingRuleEditor() {
  const [rules, setRules] = useState<PostingRule[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/admin/posting-rules')
      .then(r => r.json())
      .then(data => { setRules(data); setLoading(false) })
  }, [])

  if (loading) return <div className="text-muted">Loading posting rules...</div>

  return (
    <div>
      <div className="text-xs text-muted mb-2">{rules.length} posting rules</div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Codelet Type</th>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Direction</th>
            <th style={{ textAlign: 'right', padding: '4px 8px' }}>Urgency</th>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Condition</th>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Triggers</th>
          </tr>
        </thead>
        <tbody>
          {rules.map(r => (
            <tr key={r.id} style={{ borderBottom: '1px solid var(--border)' }}>
              <td className="mono text-xs" style={{ padding: '3px 8px' }}>{r.codelet_type}</td>
              <td style={{ padding: '3px 8px' }}>{r.direction}</td>
              <td style={{ padding: '3px 8px', textAlign: 'right' }}>
                {r.urgency_when_posted ?? r.urgency_formula ?? '-'}
              </td>
              <td className="text-xs" style={{ padding: '3px 8px' }}>{r.condition}</td>
              <td className="mono text-xs" style={{ padding: '3px 8px' }}>
                {r.triggering_slipnodes?.join(', ') || '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
