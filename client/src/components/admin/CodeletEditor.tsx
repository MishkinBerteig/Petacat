import { useState, useEffect, useCallback } from 'react'

interface CodeletDef {
  name: string
  family: string
  phase: string
  default_urgency: number | null
  description: string
  execute_body: string
}

export function CodeletEditor() {
  const [codelets, setCodelets] = useState<CodeletDef[]>([])
  const [selected, setSelected] = useState<CodeletDef | null>(null)
  const [editing, setEditing] = useState<CodeletDef | null>(null)
  const [loading, setLoading] = useState(true)
  const [flash, setFlash] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  const [filter, setFilter] = useState('')

  const load = useCallback(() => {
    fetch('/api/admin/codelets').then(r => r.json()).then(data => {
      setCodelets(data)
      setLoading(false)
    })
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (flash) { const t = setTimeout(() => setFlash(null), 2500); return () => clearTimeout(t) } }, [flash])

  const startEdit = (c: CodeletDef) => setEditing({ ...c })
  const cancelEdit = () => setEditing(null)

  const saveEdit = async () => {
    if (!editing) return
    try {
      const res = await fetch(`/api/admin/codelets/${encodeURIComponent(editing.name)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editing),
      })
      if (!res.ok) throw new Error(await res.text())
      setFlash({ type: 'success', msg: 'Saved' })
      setEditing(null)
      load()
    } catch (e: any) {
      setFlash({ type: 'error', msg: e.message ?? 'Error' })
    }
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete codelet type "${name}"?`)) return
    try {
      const res = await fetch(`/api/admin/codelets/${encodeURIComponent(name)}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(await res.text())
      setFlash({ type: 'success', msg: 'Deleted' })
      if (selected?.name === name) setSelected(null)
      if (editing?.name === name) setEditing(null)
      load()
    } catch (e: any) {
      setFlash({ type: 'error', msg: e.message ?? 'Cannot delete' })
    }
  }

  if (loading) return <div className="text-muted">Loading codelet types...</div>

  const filtered = filter
    ? codelets.filter(c => c.name.includes(filter) || c.family.includes(filter) || c.phase.includes(filter))
    : codelets

  const detail = editing ?? selected

  return (
    <div style={{ display: 'flex', gap: 8, height: '100%' }}>
      {/* Left: codelet list */}
      <div style={{ width: 260, overflow: 'auto', borderRight: '1px solid var(--border)', paddingRight: 8, flexShrink: 0 }}>
        <input
          value={filter} onChange={e => setFilter(e.target.value)}
          placeholder="Filter..." style={{ width: '100%', fontSize: 11, padding: '2px 6px', marginBottom: 4 }}
        />
        <div className="text-xs text-muted mb-2">{filtered.length} codelet types</div>
        {filtered.map(c => (
          <div
            key={c.name}
            onClick={() => { setSelected(c); setEditing(null) }}
            style={{
              padding: '4px 8px', cursor: 'pointer',
              background: detail?.name === c.name ? 'var(--bg-panel)' : 'transparent',
              borderRadius: 3, marginBottom: 2, fontSize: 12,
            }}
          >
            <div className="mono text-xs">{c.name}</div>
            <div className="text-muted text-xs">{c.family} / {c.phase}</div>
          </div>
        ))}
      </div>

      {/* Right: detail/edit */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {flash && (
          <div style={{
            padding: '4px 8px', marginBottom: 4, fontSize: 11, borderRadius: 3,
            background: flash.type === 'success' ? 'rgba(76,175,80,0.2)' : 'rgba(244,67,54,0.2)',
            color: flash.type === 'success' ? 'var(--success)' : 'var(--error)',
          }}>{flash.msg}</div>
        )}

        {detail ? (
          <div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <h3 className="mono" style={{ margin: 0, fontSize: 14 }}>{detail.name}</h3>
              {!editing && <button onClick={() => startEdit(detail)} style={{ fontSize: 10 }}>Edit</button>}
              {!editing && <button onClick={() => handleDelete(detail.name)} style={{ fontSize: 10, color: 'var(--error)' }}>Delete</button>}
              {editing && <button onClick={saveEdit} style={{ fontSize: 10 }} className="primary">Save</button>}
              {editing && <button onClick={cancelEdit} style={{ fontSize: 10 }}>Cancel</button>}
            </div>

            {editing ? (
              <>
                <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
                  <label style={{ fontSize: 11 }}>Family: <input value={editing.family} onChange={e => setEditing(ed => ed ? { ...ed, family: e.target.value } : ed)} style={{ width: 100, fontSize: 11 }} /></label>
                  <label style={{ fontSize: 11 }}>Phase: <input value={editing.phase} onChange={e => setEditing(ed => ed ? { ...ed, phase: e.target.value } : ed)} style={{ width: 100, fontSize: 11 }} /></label>
                  <label style={{ fontSize: 11 }}>Urgency: <input type="number" value={editing.default_urgency ?? ''} onChange={e => setEditing(ed => ed ? { ...ed, default_urgency: e.target.value ? Number(e.target.value) : null } : ed)} style={{ width: 60, fontSize: 11 }} /></label>
                </div>
                <label style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                  Description:
                  <input value={editing.description} onChange={e => setEditing(ed => ed ? { ...ed, description: e.target.value } : ed)} style={{ width: '100%', fontSize: 11 }} />
                </label>
                <label style={{ fontSize: 11, display: 'block', marginBottom: 2 }}>execute_body:</label>
                <textarea
                  value={editing.execute_body}
                  onChange={e => setEditing(ed => ed ? { ...ed, execute_body: e.target.value } : ed)}
                  onKeyDown={e => {
                    if (e.key === 'Tab') {
                      e.preventDefault()
                      const ta = e.target as HTMLTextAreaElement
                      const start = ta.selectionStart
                      const end = ta.selectionEnd
                      setEditing(ed => ed ? { ...ed, execute_body: ed.execute_body.substring(0, start) + '    ' + ed.execute_body.substring(end) } : ed)
                      setTimeout(() => { ta.selectionStart = ta.selectionEnd = start + 4 }, 0)
                    }
                  }}
                  style={{
                    width: '100%', minHeight: 300, fontSize: 11, fontFamily: 'var(--font-mono)',
                    background: 'var(--bg-card)', padding: 8, borderRadius: 3, resize: 'vertical',
                    whiteSpace: 'pre', overflowWrap: 'normal', overflowX: 'auto',
                  }}
                />
              </>
            ) : (
              <>
                <div className="text-sm mb-1">Family: {detail.family} | Phase: {detail.phase}</div>
                <div className="text-sm mb-1">Default urgency: {detail.default_urgency ?? 'dynamic'}</div>
                <div className="text-sm mb-2">{detail.description}</div>
                <div className="text-xs text-muted mb-1">execute_body:</div>
                <pre style={{
                  background: 'var(--bg-card)', padding: 8, borderRadius: 3, fontSize: 11,
                  overflow: 'auto', maxHeight: 400, whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)',
                }}>
                  {detail.execute_body || '(empty)'}
                </pre>
              </>
            )}
          </div>
        ) : (
          <div className="text-muted">Select a codelet type</div>
        )}
      </div>
    </div>
  )
}
