// ---------------------------------------------------------------------------
// Petacat -- "Names that no longer resolve": the names an Episodic Memory holds that the configuration lacks
// ---------------------------------------------------------------------------
//
// Mounted on a Training Mode Session's Memory tab (its own configuration) and on Metacat
// Mode's Episodic Memory view (the global configuration). The memory is not changed: a
// name that no longer resolves is simply not available to a run, and is listed here with
// its story from the journal.
// ---------------------------------------------------------------------------

import { useEffect, useState } from 'react'
import { listConfigurations } from '@/api/client'
import { checkNames } from './historyApi'
import { boxStyle } from './shared'
import type { NameStory } from './types'

interface Props {
  /** The configuration the memory's names are checked against... */
  configurationId?: number
  /** ...or the Training Mode Session whose configuration that is. */
  sessionId?: number
  /** The names the memory holds (see `memoryNames`). */
  names: string[]
  /** Which memory this is, for the heading. */
  memoryLabel: string
}

export function NamesPanel({ configurationId, sessionId, names, memoryLabel }: Props) {
  const [unresolved, setUnresolved] = useState<NameStory[]>([])
  const namesKey = names.join('\u0000')

  useEffect(() => {
    let live = true
    if (names.length === 0) { setUnresolved([]); return }
    ;(async () => {
      let id = configurationId
      if (id === undefined && sessionId !== undefined) {
        id = (await listConfigurations()).find(c => c.session_id === sessionId)?.id
      }
      const reply = await checkNames(id ?? 1, names)
      if (live) setUnresolved(Array.isArray(reply?.unresolved) ? reply.unresolved : [])
    })().catch(() => { if (live) setUnresolved([]) })
    return () => { live = false }
    // namesKey stands for names
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configurationId, sessionId, namesKey])

  if (unresolved.length === 0) return null
  return (
    <div data-testid="unresolved-names" role="note" style={{ ...boxStyle, marginBottom: 6 }}>
      <strong>Names that no longer resolve ({unresolved.length})</strong>
      <div className="text-muted">
        {memoryLabel} names these, and the configuration no longer has them. A run does not see them (they are never read as
        depth 0); the memory keeps them. Each story is from the journal.
      </div>
      <ul style={{ margin: '3px 0 0 16px', padding: 0 }}>
        {unresolved.map(s => (
          <li key={s.name} data-testid="unresolved-name">
            <span className="mono">{s.name}</span> &mdash; {s.text}
            {s.current_name && s.current_name !== s.name ? <> (now <span className="mono">{s.current_name}</span>)</> : null}
          </li>
        ))}
      </ul>
    </div>
  )
}
