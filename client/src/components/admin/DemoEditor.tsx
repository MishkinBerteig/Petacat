import { useState, useEffect } from 'react'
import { api } from '@/api/client'
import type { DemoProblem } from '@/types'

export function DemoEditor() {
  const [demos, setDemos] = useState<DemoProblem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.getDemos().then(data => {
      setDemos(data)
      setLoading(false)
    })
  }, [])

  if (loading) return <div className="text-muted">Loading demos...</div>

  return (
    <div>
      <div className="text-xs text-muted mb-2">{demos.length} demo problems</div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Name</th>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Problem</th>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Answer</th>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Mode</th>
            <th style={{ textAlign: 'right', padding: '4px 8px' }}>Seed</th>
          </tr>
        </thead>
        <tbody>
          {demos.map(d => (
            <tr key={d.id ?? d.name} style={{ borderBottom: '1px solid var(--border)' }}>
              <td className="mono text-xs" style={{ padding: '3px 8px' }}>{d.name}</td>
              <td className="mono" style={{ padding: '3px 8px' }}>
                {d.initial} → {d.modified}; {d.target} → ?
              </td>
              <td className="mono" style={{ padding: '3px 8px' }}>{d.answer ?? '—'}</td>
              <td className="text-xs" style={{ padding: '3px 8px' }}>{d.mode}</td>
              <td className="mono text-xs" style={{ padding: '3px 8px', textAlign: 'right' }}>{d.seed}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
