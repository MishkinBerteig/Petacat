import { useState, useEffect, useCallback } from 'react'

interface Param {
  name: string
  value: string
  value_type: string
}

export function ParamsEditor() {
  const [params, setParams] = useState<Param[]>([])
  const [loading, setLoading] = useState(true)
  const [editingName, setEditingName] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [flash, setFlash] = useState<{ name: string; type: 'success' | 'error'; msg: string } | null>(null)

  const load = useCallback(() => {
    fetch('/api/admin/params').then(r => r.json()).then(data => { setParams(data); setLoading(false) })
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (flash) { const t = setTimeout(() => setFlash(null), 2000); return () => clearTimeout(t) } }, [flash])

  const startEdit = (p: Param) => { setEditingName(p.name); setEditValue(p.value) }

  const saveEdit = async () => {
    if (!editingName) return
    try {
      const res = await fetch(`/api/admin/params/${encodeURIComponent(editingName)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: editValue }),
      })
      if (!res.ok) throw new Error(await res.text())
      setFlash({ name: editingName, type: 'success', msg: 'Saved' })
      setEditingName(null)
      load()
    } catch (e: any) {
      setFlash({ name: editingName!, type: 'error', msg: e.message ?? 'Error' })
    }
  }

  if (loading) return <div className="text-muted">Loading parameters...</div>

  return (
    <div>
      <div className="text-xs text-muted mb-2">{params.length} engine parameters (double-click value to edit)</div>
      {flash && (
        <div style={{
          padding: '4px 8px', marginBottom: 4, fontSize: 11, borderRadius: 3,
          background: flash.type === 'success' ? 'rgba(76,175,80,0.2)' : 'rgba(244,67,54,0.2)',
          color: flash.type === 'success' ? 'var(--success)' : 'var(--error)',
        }}>{flash.msg}</div>
      )}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Name</th>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Value</th>
            <th style={{ textAlign: 'left', padding: '4px 8px', width: 60 }}>Type</th>
          </tr>
        </thead>
        <tbody>
          {params.map(p => (
            <tr key={p.name} style={{ borderBottom: '1px solid var(--border)' }}>
              <td className="mono text-xs" style={{ padding: '3px 8px' }}>{p.name}</td>
              <td style={{ padding: '3px 8px' }}>
                {editingName === p.name ? (
                  <span style={{ display: 'flex', gap: 4 }}>
                    {p.value_type === 'bool' ? (
                      <select
                        value={editValue}
                        onChange={e => setEditValue(e.target.value)}
                        onBlur={saveEdit}
                        autoFocus
                        style={{ fontSize: 11 }}
                      >
                        <option value="true">true</option>
                        <option value="false">false</option>
                      </select>
                    ) : (
                      <input
                        value={editValue}
                        onChange={e => setEditValue(e.target.value)}
                        onBlur={saveEdit}
                        onKeyDown={e => { if (e.key === 'Enter') saveEdit(); if (e.key === 'Escape') setEditingName(null) }}
                        type={p.value_type === 'int' || p.value_type === 'float' ? 'number' : 'text'}
                        step={p.value_type === 'float' ? '0.01' : undefined}
                        autoFocus
                        style={{ width: '100%', fontSize: 11, padding: '1px 4px' }}
                      />
                    )}
                  </span>
                ) : (
                  <span
                    className="mono"
                    style={{ cursor: 'pointer' }}
                    onDoubleClick={() => startEdit(p)}
                    title="Double-click to edit"
                  >
                    {p.value}
                  </span>
                )}
              </td>
              <td className="text-muted text-xs" style={{ padding: '3px 8px' }}>{p.value_type}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
