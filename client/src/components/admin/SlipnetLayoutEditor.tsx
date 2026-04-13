import { useState, useEffect } from 'react'

interface LayoutPos {
  node_name: string
  grid_row: number
  grid_col: number
}

export function SlipnetLayoutEditor() {
  const [positions, setPositions] = useState<LayoutPos[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/admin/slipnet-layout')
      .then(r => r.json())
      .then(data => { setPositions(data); setLoading(false) })
  }, [])

  if (loading) return <div className="text-muted">Loading slipnet layout...</div>

  const maxRow = Math.max(...positions.map(p => p.grid_row), 0)
  const maxCol = Math.max(...positions.map(p => p.grid_col), 0)

  return (
    <div>
      <div className="text-xs text-muted mb-2">
        {positions.length} nodes in a {maxRow + 1} x {maxCol + 1} grid
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Node Name</th>
            <th style={{ textAlign: 'right', padding: '4px 8px' }}>Row</th>
            <th style={{ textAlign: 'right', padding: '4px 8px' }}>Col</th>
          </tr>
        </thead>
        <tbody>
          {positions.map(p => (
            <tr key={p.node_name} style={{ borderBottom: '1px solid var(--border)' }}>
              <td className="mono text-xs" style={{ padding: '3px 8px' }}>{p.node_name}</td>
              <td style={{ padding: '3px 8px', textAlign: 'right' }}>{p.grid_row}</td>
              <td style={{ padding: '3px 8px', textAlign: 'right' }}>{p.grid_col}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
