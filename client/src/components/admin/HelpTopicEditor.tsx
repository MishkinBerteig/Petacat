import { useState, useEffect, useCallback } from 'react'

import { request, describeApiError } from '@/api/client'
import { LoadFailure } from './EditableTable'

interface HelpTopic {
  id: number
  topic_type: string
  topic_key: string
  title: string
  short_desc: string
  full_desc: string
}

const EMPTY: HelpTopic = {
  id: -1, topic_type: 'concept', topic_key: '', title: '', short_desc: '', full_desc: '',
}

/**
 * The in-app help. A topic saved here is what `GET /api/docs` serves, and
 * `POST /api/admin/help/regenerate` writes the same content out to `HELP.md` and the
 * client's topic constants.
 */
export function HelpTopicEditor() {
  const [topics, setTopics] = useState<HelpTopic[]>([])
  const [selected, setSelected] = useState<HelpTopic | null>(null)
  const [draft, setDraft] = useState<HelpTopic>(EMPTY)
  const [status, setStatus] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // A refresh leaves the list on screen, so the status line reporting what just happened
  // survives the reload it triggered.
  const load = useCallback(() => {
    request<HelpTopic[]>('/admin/help-topics')
      .then(data => { setTopics(data); setLoadError(null) })
      .catch(e => setLoadError(describeApiError(e, 'load the help topics')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const open = (t: HelpTopic) => {
    setSelected(t)
    setDraft(t)
    setStatus(null)
  }

  const field = (key: keyof HelpTopic, value: string) =>
    setDraft(d => ({ ...d, [key]: value }))

  const save = async () => {
    if (!selected) return
    const isNew = selected.id < 0
    let saved: HelpTopic
    try {
      saved = await request<HelpTopic>(
        isNew ? '/admin/help-topics' : `/admin/help-topics/${selected.id}`,
        {
          method: isNew ? 'POST' : 'PUT',
          body: JSON.stringify({
            topic_type: draft.topic_type,
            topic_key: draft.topic_key,
            title: draft.title,
            short_desc: draft.short_desc,
            full_desc: draft.full_desc,
          }),
        },
      )
    } catch (e) {
      // The draft stays in the editor with the reason beside it, so a rejected topic is
      // corrected rather than retyped.
      setStatus(describeApiError(e, isNew ? 'add the help topic' : 'save the help topic'))
      return
    }
    setStatus('Saved')
    load()
    open(saved)
  }

  const remove = async () => {
    if (!selected || selected.id < 0) return
    try {
      await request<void>(`/admin/help-topics/${selected.id}`, { method: 'DELETE' })
    } catch (e) {
      // The topic survives a refused delete, and stays open with the reason.
      setStatus(describeApiError(e, 'delete the help topic'))
      return
    }
    setSelected(null)
    load()
  }

  if (loading) return <div className="text-muted">Loading help topics...</div>
  if (loadError) return <LoadFailure message={loadError} onRetry={load} />

  return (
    <div style={{ display: 'flex', gap: 8, height: '100%' }}>
      <div style={{ width: 240, overflow: 'auto', borderRight: '1px solid var(--border)', paddingRight: 8 }}>
        <div className="text-xs text-muted mb-2">{topics.length} help topics</div>
        {topics.map(t => (
          <div
            key={t.id}
            onClick={() => open(t)}
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
        <button onClick={() => open(EMPTY)} style={{ fontSize: 10, marginTop: 6 }}>
          + New topic
        </button>
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        {selected ? (
          <div>
            <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
              <span style={{ flex: 1 }}>
                <label className="text-xs text-muted" htmlFor="topic-type">Type</label>
                <input
                  id="topic-type"
                  value={draft.topic_type}
                  onChange={e => field('topic_type', e.target.value)}
                  className="mono"
                  style={{ width: '100%', fontSize: 12 }}
                />
              </span>
              <span style={{ flex: 2 }}>
                <label className="text-xs text-muted" htmlFor="topic-key">Key</label>
                <input
                  id="topic-key"
                  value={draft.topic_key}
                  onChange={e => field('topic_key', e.target.value)}
                  className="mono"
                  style={{ width: '100%', fontSize: 12 }}
                />
              </span>
            </div>
            <label className="text-xs text-muted" htmlFor="topic-title">Title</label>
            <input
              id="topic-title"
              value={draft.title}
              onChange={e => field('title', e.target.value)}
              style={{ width: '100%', fontSize: 13, marginBottom: 6 }}
            />
            <label className="text-xs text-muted" htmlFor="topic-short">Short description</label>
            <textarea
              id="topic-short"
              value={draft.short_desc}
              onChange={e => field('short_desc', e.target.value)}
              style={{ width: '100%', minHeight: 60, fontSize: 12, marginBottom: 6 }}
            />
            <label className="text-xs text-muted" htmlFor="topic-full">Full description</label>
            <textarea
              id="topic-full"
              value={draft.full_desc}
              onChange={e => field('full_desc', e.target.value)}
              style={{
                width: '100%',
                minHeight: 260,
                fontSize: 12,
                background: 'var(--bg-input, #111)',
                padding: 8,
                borderRadius: 4,
              }}
            />
            <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
              <button onClick={save} className="primary" style={{ fontSize: 11 }}>Save</button>
              {selected.id >= 0 && (
                <button onClick={remove} style={{ fontSize: 11, color: 'var(--error)' }}>
                  Delete
                </button>
              )}
              {status && <span className="text-xs" role="status">{status}</span>}
            </div>
          </div>
        ) : (
          <div className="text-muted text-xs">Select a topic</div>
        )}
      </div>
    </div>
  )
}
