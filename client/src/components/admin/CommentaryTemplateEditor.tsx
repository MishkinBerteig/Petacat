import { useState, useEffect, useCallback } from 'react'

import { request, describeApiError } from '@/api/client'
import { LoadFailure } from './EditableTable'

interface Template {
  id: number
  template_key: string
  template_data: Record<string, any>
}

const EMPTY: Template = { id: -1, template_key: '', template_data: {} }

/**
 * Commentary templates are the program's English. §4.6 makes them data — the prose is
 * "an illusion arising from a flexible set of phrase-templates" — so editing one here
 * changes what the program says in the next commentary it writes.
 */
export function CommentaryTemplateEditor() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [selected, setSelected] = useState<Template | null>(null)
  const [draftKey, setDraftKey] = useState('')
  const [draftData, setDraftData] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // A refresh leaves the list on screen, so the status line reporting what just happened
  // survives the reload it triggered.
  const load = useCallback(() => {
    request<Template[]>('/admin/commentary-templates')
      .then(data => { setTemplates(data); setLoadError(null) })
      .catch(e => setLoadError(describeApiError(e, 'load the commentary templates')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const open = (t: Template) => {
    setSelected(t)
    setDraftKey(t.template_key)
    setDraftData(JSON.stringify(t.template_data, null, 2))
    setStatus(null)
  }

  const save = async () => {
    if (!selected) return
    let parsed: Record<string, any>
    try {
      parsed = JSON.parse(draftData)
    } catch {
      setStatus('Template data needs valid JSON')
      return
    }
    const isNew = selected.id < 0
    let saved: Template
    try {
      saved = await request<Template>(
        isNew ? '/admin/commentary-templates'
              : `/admin/commentary-templates/${selected.id}`,
        {
          method: isNew ? 'POST' : 'PUT',
          body: JSON.stringify({ template_key: draftKey, template_data: parsed }),
        },
      )
    } catch (e) {
      // The draft stays in the editor with the reason beside it, so a rejected template
      // is corrected rather than retyped.
      setStatus(describeApiError(
        e, isNew ? 'add the commentary template' : 'save the commentary template',
      ))
      return
    }
    setStatus('Saved')
    load()
    open(saved)
  }

  const remove = async () => {
    if (!selected || selected.id < 0) return
    try {
      await request<void>(`/admin/commentary-templates/${selected.id}`, {
        method: 'DELETE',
      })
    } catch (e) {
      // The template survives a refused delete, and stays open with the reason.
      setStatus(describeApiError(e, 'delete the commentary template'))
      return
    }
    setSelected(null)
    load()
  }

  if (loading) return <div className="text-muted">Loading commentary templates...</div>
  if (loadError) return <LoadFailure message={loadError} onRetry={load} />

  return (
    <div style={{ display: 'flex', gap: 8, height: '100%' }}>
      <div style={{ width: 200, overflow: 'auto', borderRight: '1px solid var(--border)', paddingRight: 8 }}>
        <div className="text-xs text-muted mb-2">{templates.length} templates</div>
        {templates.map(t => (
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
            <span className="mono text-xs">{t.template_key}</span>
          </div>
        ))}
        <button
          onClick={() => open(EMPTY)}
          style={{ fontSize: 10, marginTop: 6 }}
        >
          + New template
        </button>
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        {selected ? (
          <div>
            <label className="text-xs text-muted" htmlFor="template-key">Key</label>
            <input
              id="template-key"
              value={draftKey}
              onChange={e => setDraftKey(e.target.value)}
              className="mono"
              style={{ width: '100%', fontSize: 12, marginBottom: 6 }}
            />
            <label className="text-xs text-muted" htmlFor="template-data">Template data (JSON)</label>
            <textarea
              id="template-data"
              value={draftData}
              onChange={e => setDraftData(e.target.value)}
              spellCheck={false}
              style={{
                width: '100%',
                minHeight: 320,
                fontSize: 11,
                fontFamily: 'monospace',
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
          <div className="text-muted text-xs">Select a template</div>
        )}
      </div>
    </div>
  )
}
