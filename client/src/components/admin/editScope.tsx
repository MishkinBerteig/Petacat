// ---------------------------------------------------------------------------
// The scope picker's state (configuration plan 3.10.2) and the edit-all commit path
// ---------------------------------------------------------------------------
//
// AdminLayout wraps the Admin tabs in `ScopeProvider`. The header chip shows the picker. An
// editor's requester (`adminRequest.ts`) and the Database tab ask `useScope()`: when the scope
// is "this configuration" (or there is no provider) they write as before; otherwise they hand
// their ops to `commit`, which opens the preview dialog and resolves once the change is
// committed, or rejects if it was cancelled or held back.

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { listConfigurations } from '@/api/client'
import type { ConfigurationSummary, EditCommit, EditScope } from '@/types/configuration'
import { EditPreviewDialog } from './EditPreviewDialog'

export type Ops = Array<Record<string, unknown>>

export interface ScopeValue {
  scope: EditScope
  setScope: (scope: EditScope) => void
  /** The configurations a "chosen" checklist offers; null until loaded. */
  configurations: ConfigurationSummary[] | null
  reload: () => Promise<void>
  /** Send `ops` to the scope's targets through the preview; rejects when nothing was written. */
  commit: (ops: Ops) => Promise<EditCommit>
}

const ScopeContext = createContext<ScopeValue | null>(null)

/** The scope, or null outside the Admin view (writes then go to the one configuration). */
export const useScope = () => useContext(ScopeContext)

/** The current scope read at call time, for a requester that outlives a render. */
export function useScopeRef() {
  const scope = useScope()
  const ref = useRef(scope)
  ref.current = scope
  return ref
}

interface Pending {
  ops: Ops
  scope: EditScope
  revisions: Record<string, number>
  resolve: (c: EditCommit) => void
  reject: (e: Error) => void
}

export function ScopeProvider({ openId, children }: { openId: number; children: ReactNode }) {
  const [scope, setScope] = useState<EditScope>({ mode: 'this', ids: [] })
  const [configurations, setConfigurations] = useState<ConfigurationSummary[] | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const scopeRef = useRef(scope)
  scopeRef.current = scope

  const reload = useCallback(async () => {
    try { setConfigurations(await listConfigurations()) } catch { setConfigurations(null) }
  }, [])

  const choose = useCallback((next: EditScope) => {
    // Opening the picker to chosen/all reads the list (the checklist, and fresh revisions).
    if (next.mode !== 'this') void reload()
    setScope(next.mode === 'chosen' && next.ids.length === 0 ? { ...next, ids: [openId] } : next)
  }, [reload, openId])

  const commit = useCallback(async (ops: Ops): Promise<EditCommit> => {
    const current = scopeRef.current
    const list = await listConfigurations()
    setConfigurations(list)
    const revisions = Object.fromEntries(list.map(c => [String(c.id), c.live_revision ?? c.revision]))
    return new Promise<EditCommit>((resolve, reject) => {
      setPending({ ops, scope: current, revisions, resolve, reject })
    })
  }, [])

  const value = useMemo<ScopeValue>(
    () => ({ scope, setScope: choose, configurations, reload, commit }),
    [scope, choose, configurations, reload, commit],
  )

  return (
    <ScopeContext.Provider value={value}>
      {children}
      {pending && (
        <EditPreviewDialog
          ops={pending.ops}
          scope={pending.scope}
          revisions={pending.revisions}
          onDone={c => { pending.resolve(c); setPending(null) }}
          onCancel={m => { pending.reject(new Error(m)); setPending(null) }}
        />
      )}
    </ScopeContext.Provider>
  )
}
