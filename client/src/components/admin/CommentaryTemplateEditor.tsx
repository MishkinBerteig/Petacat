import { useState, useEffect } from 'react'

interface Template {
  id: number
  template_key: string
  template_data: Record<string, any>
}

export function CommentaryTemplateEditor() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [selected, setSelected] = useState<Template | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/admin/commentary-templates')
      .then(r => r.json())
      .then(data => { setTemplates(data); setLoading(false) })
  }, [])

  if (loading) return <div className="text-muted">Loading commentary templates...</div>

  return (
    <div style={{ display: 'flex', gap: 8, height: '100%' }}>
      <div style={{ width: 200, overflow: 'auto', borderRight: '1px solid var(--border)', paddingRight: 8 }}>
        <div className="text-xs text-muted mb-2">{templates.length} templates</div>
        {templates.map(t => (
          <div
            key={t.id}
            onClick={() => setSelected(t)}
            style={{
              padding: '4px 6px',
              cursor: 'pointer',
              borderRadius: 3,
              fontSize: 12,
              background: selected?.id === t.id ? 'var(--bg-highlight, #2a2a2a)' : 'transparent',
            }}
          >
            <span className="mono text-xs">{t.template_key}</span>
          </div>
        ))}
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        {selected ? (
          <div>
            <h4 style={{ margin: '0 0 8px', fontSize: 13 }}>{selected.template_key}</h4>
            <pre style={{
              fontSize: 11,
              whiteSpace: 'pre-wrap',
              background: 'var(--bg-input, #111)',
              padding: 8,
              borderRadius: 4,
              maxHeight: 400,
              overflow: 'auto',
            }}>
              {JSON.stringify(selected.template_data, null, 2)}
            </pre>
          </div>
        ) : (
          <div className="text-muted text-xs">Select a template</div>
        )}
      </div>
    </div>
  )
}
