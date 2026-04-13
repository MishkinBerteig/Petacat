import { useState, useEffect } from 'react'

interface ThemeDim {
  id: number
  slipnet_node: string
  valid_relations: string[]
}

export function ThemeDimensionEditor() {
  const [dims, setDims] = useState<ThemeDim[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/admin/theme-dimensions')
      .then(r => r.json())
      .then(data => { setDims(data); setLoading(false) })
  }, [])

  if (loading) return <div className="text-muted">Loading theme dimensions...</div>

  return (
    <div>
      <div className="text-xs text-muted mb-2">{dims.length} theme dimensions</div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <th style={{ textAlign: 'right', padding: '4px 8px' }}>ID</th>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Slipnet Node</th>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Valid Relations</th>
          </tr>
        </thead>
        <tbody>
          {dims.map(d => (
            <tr key={d.id} style={{ borderBottom: '1px solid var(--border)' }}>
              <td style={{ padding: '3px 8px', textAlign: 'right' }}>{d.id}</td>
              <td className="mono text-xs" style={{ padding: '3px 8px' }}>{d.slipnet_node}</td>
              <td className="mono text-xs" style={{ padding: '3px 8px' }}>{d.valid_relations.join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
