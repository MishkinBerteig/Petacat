import { useState, useEffect } from 'react'

interface HelpTopic {
  id: number
  topic_type: string
  topic_key: string
  title: string
  short_desc: string
  full_desc: string
}

export function HelpTopicEditor() {
  const [topics, setTopics] = useState<HelpTopic[]>([])
  const [selected, setSelected] = useState<HelpTopic | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/admin/help-topics')
      .then(r => r.json())
      .then(data => { setTopics(data); setLoading(false) })
  }, [])

  if (loading) return <div className="text-muted">Loading help topics...</div>

  return (
    <div style={{ display: 'flex', gap: 8, height: '100%' }}>
      <div style={{ width: 240, overflow: 'auto', borderRight: '1px solid var(--border)', paddingRight: 8 }}>
        <div className="text-xs text-muted mb-2">{topics.length} help topics</div>
        {topics.map(t => (
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
            <span className="text-muted" style={{ fontSize: 10 }}>{t.topic_type}/</span>
            <span className="mono text-xs">{t.topic_key}</span>
          </div>
        ))}
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        {selected ? (
          <div>
            <h4 style={{ margin: '0 0 4px', fontSize: 14 }}>{selected.title}</h4>
            <div className="text-xs text-muted" style={{ marginBottom: 8 }}>
              {selected.topic_type} / {selected.topic_key}
            </div>
            {selected.short_desc && (
              <p style={{ fontSize: 12, marginBottom: 8 }}>{selected.short_desc}</p>
            )}
            {selected.full_desc && (
              <div style={{
                fontSize: 12,
                whiteSpace: 'pre-wrap',
                background: 'var(--bg-input, #111)',
                padding: 8,
                borderRadius: 4,
              }}>
                {selected.full_desc}
              </div>
            )}
          </div>
        ) : (
          <div className="text-muted text-xs">Select a topic</div>
        )}
      </div>
    </div>
  )
}
