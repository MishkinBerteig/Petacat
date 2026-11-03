// ---------------------------------------------------------------------------
// The edit-all preview (configuration plan 3.10.3, 3.16.2, 3.16.3)
// ---------------------------------------------------------------------------
//
// Opened when a save's scope is "chosen configurations" or "all configurations". It previews the
// change against every target, lets the user decide each `differs` target (overwrite) and each
// `not_applicable` one (apply the rest), offers all-or-nothing and a reason, then commits and
// shows each target's result with a way to undo the group.

import { useEffect, useMemo, useState } from 'react'
import { commitConfigurationEdits, describeApiError, previewConfigurationEdits } from '@/api/client'
import type { EditCommit, EditCommitTarget, EditPreview, EditPreviewTarget, EditScope } from '@/types/configuration'
import { undoGroup } from './history/historyApi'

const RESULT_TEXT: Record<string, string> = {
  apply: 'Will apply',
  no_change: 'No change: already as asked',
  differs: 'Differs: a value is not what this change expects',
  not_applicable: 'Not applicable: a row is missing or cannot be changed',
  stale: 'Changed since the preview: preview again',
  skipped_by_selection: 'Skipped',
}

/** Why a target is skipped, in the words of the plan. */
function skipText(t: EditPreviewTarget): string {
  if (t.frozen || t.reason === 'frozen') return 'Skipped: frozen'
  if (t.reason && /chang/i.test(t.reason)) return 'Skipped: changing state'
  return t.reason ? `Skipped: ${t.reason}` : 'Skipped'
}

/** The route sets `committed` per target only for all-or-nothing; otherwise `apply` is what was written. */
export const wasWritten = (t: EditCommitTarget, commit: EditCommit) =>
  commit.committed && (t.committed ?? t.result === 'apply')

export const resultText = (t: EditPreviewTarget) =>
  t.result === 'skipped_by_selection' ? skipText(t) : RESULT_TEXT[t.result] ?? t.result

/** "Live (in memory)" for a target that holds the change in memory; "Stored" otherwise. */
export const targetPlace = (t: EditPreviewTarget) =>
  t.mode === 'Metacat Mode' || t.session_id === null
    ? 'Stored'
    : t.persisted === false ? 'Live (in memory)' : 'Stored'

interface Props {
  ops: Array<Record<string, unknown>>
  scope: EditScope
  /** Revisions by configuration id, read when the dialog opened. */
  revisions: Record<string, number>
  onDone: (commit: EditCommit) => void
  onCancel: (message: string) => void
}

export function EditPreviewDialog({ ops, scope, revisions, onDone, onCancel }: Props) {
  const [preview, setPreview] = useState<EditPreview | null>(null)
  const [commit, setCommit] = useState<EditCommit | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [overwrite, setOverwrite] = useState<Set<number>>(new Set())
  const [applyRest, setApplyRest] = useState<Set<number>>(new Set())
  const [allOrNothing, setAllOrNothing] = useState(false)
  const [reason, setReason] = useState('')
  const [undone, setUndone] = useState<Record<number, string>>({})

  const targets = useMemo(
    () => (scope.mode === 'all' ? { all: true as const } : { ids: scope.ids }),
    [scope],
  )

  const runPreview = async () => {
    setBusy(true)
    setError(null)
    try {
      setPreview(await previewConfigurationEdits(ops, targets, revisions, reason))
      setOverwrite(new Set())
      setApplyRest(new Set())
    } catch (err) {
      setError(describeApiError(err, 'preview the change'))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => { void runPreview() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (set: Set<number>, put: (s: Set<number>) => void, id: number) => {
    const next = new Set(set)
    if (next.has(id)) next.delete(id); else next.add(id)
    put(next)
  }

  const doCommit = async () => {
    if (!preview) return
    setBusy(true)
    setError(null)
    try {
      setCommit(await commitConfigurationEdits({
        preview_token: preview.preview_token,
        overwrite: [...overwrite],
        apply_rest: [...applyRest],
        all_or_nothing: allOrNothing,
        reason,
      }))
    } catch (err) {
      setError(describeApiError(err, 'commit the change'))
    } finally {
      setBusy(false)
    }
  }

  const undo = async (t: EditCommitTarget, groupId: string) => {
    try {
      await undoGroup(t.configuration_id, groupId, reason)
      setUndone(u => ({ ...u, [t.configuration_id]: 'Undone with one new entry.' }))
    } catch (err) {
      setUndone(u => ({ ...u, [t.configuration_id]: describeApiError(err, 'undo the group') }))
    }
  }

  const nothingToDo = !!preview && !preview.targets.some(t =>
    t.result === 'apply' || (t.result === 'differs' && overwrite.has(t.configuration_id))
    || (t.result === 'not_applicable' && applyRest.has(t.configuration_id)))

  return (
    <div role="dialog" aria-label="Preview of the change" data-testid="edit-preview"
      style={{
        position: 'fixed', inset: 0, zIndex: 50, background: 'rgba(0,0,0,0.45)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
      <div style={{
        background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 4,
        padding: 12, width: 'min(900px, 94vw)', maxHeight: '88vh', overflow: 'auto', fontSize: 11,
      }}>
        <h3 style={{ margin: '0 0 6px', fontSize: 13 }}>
          {commit ? 'Result of the change' : 'Preview: apply this change to '}
          {!commit && (scope.mode === 'all' ? 'all configurations' : 'the chosen configurations')}
        </h3>
        <div className="text-muted" style={{ marginBottom: 6 }}>
          {ops.length} {ops.length === 1 ? 'change' : 'changes'}. Frozen configurations are skipped when you choose all of them.
        </div>

        {error && <div role="alert" style={{ color: 'var(--error)', marginBottom: 6 }}>{error}</div>}
        {!preview && !error && <div>Previewing...</div>}

        {preview && !commit && (
          <>
            <table style={{ borderCollapse: 'collapse', width: '100%' }} aria-label="Preview per configuration">
              <thead>
                <tr style={{ textAlign: 'left' }}>
                  <th>Configuration</th><th>Where</th><th>Result</th><th>Decision</th>
                </tr>
              </thead>
              <tbody>
                {preview.targets.map(t => (
                  <tr key={t.configuration_id} data-testid={`target-${t.configuration_id}`} data-result={t.result}>
                    <td>{t.name} <span className="text-muted">({t.mode_label})</span></td>
                    <td>{targetPlace(t)}</td>
                    <td>{resultText(t)}{t.result === 'differs' && t.reason ? ` (${t.reason})` : ''}</td>
                    <td>
                      {t.result === 'differs' && (
                        <label>
                          <input type="checkbox" aria-label={`Overwrite ${t.name}`}
                            checked={overwrite.has(t.configuration_id)}
                            onChange={() => toggle(overwrite, setOverwrite, t.configuration_id)} />
                          {' '}Overwrite
                        </label>
                      )}
                      {t.result === 'not_applicable' && (
                        <label>
                          <input type="checkbox" aria-label={`Apply the rest to ${t.name}`}
                            checked={applyRest.has(t.configuration_id)}
                            onChange={() => toggle(applyRest, setApplyRest, t.configuration_id)} />
                          {' '}Apply the rest
                        </label>
                      )}
                      {t.result === 'apply' && 'Will be written'}
                      {(t.result === 'no_change' || t.result === 'skipped_by_selection') && 'Nothing written'}
                      {t.result === 'stale' && (
                        <button style={{ fontSize: 10 }} onClick={() => void runPreview()}>Preview again</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {preview.targets.length === 0 && <div>No configuration is in this scope.</div>}
            {preview.targets.some(t => t.persisted === false) && (
              <div className="text-muted" style={{ marginTop: 4 }}>
                A live session holds the change in memory; it is saved when the session is stopped.
              </div>
            )}
            <label style={{ display: 'block', marginTop: 8 }}>
              <input type="checkbox" checked={allOrNothing} onChange={e => setAllOrNothing(e.target.checked)} />
              {' '}All or nothing: write nothing unless every target can take the change
            </label>
            <label style={{ display: 'block', marginTop: 4 }}>
              Reason{' '}
              <input aria-label="Reason" value={reason} onChange={e => setReason(e.target.value)} style={{ width: '60%' }} />
            </label>
            <div style={{ marginTop: 8, display: 'flex', gap: 6 }}>
              <button disabled={busy || nothingToDo} onClick={() => void doCommit()}>
                Commit
              </button>
              <button onClick={() => onCancel('The change was cancelled; nothing was written.')}>Cancel</button>
            </div>
          </>
        )}

        {commit && (
          <>
            {!commit.committed && (
              <div role="status" data-testid="blocked" style={{ marginBottom: 6 }}>
                All or nothing: nothing was written.
                {commit.blocked_by && commit.blocked_by.length > 0
                  && ` Held back by configuration ${commit.blocked_by.join(', ')}.`}
              </div>
            )}
            <table style={{ borderCollapse: 'collapse', width: '100%' }} aria-label="Commit result per configuration">
              <thead>
                <tr style={{ textAlign: 'left' }}><th>Configuration</th><th>Where</th><th>Result</th><th>Undo</th></tr>
              </thead>
              <tbody>
                {commit.targets.map(t => (
                  <tr key={t.configuration_id} data-testid={`result-${t.configuration_id}`}>
                    <td>{t.name}</td>
                    <td>{targetPlace(t)}</td>
                    <td>
                      {wasWritten(t, commit)
                        ? (t.persisted === false
                          ? `Applied in memory (revision ${t.version_after ?? '?'}); saved at Stop`
                          : `Written as revision ${t.version_after ?? '?'}`)
                        : resultText(t)}
                      {t.result === 'stale' ? ' (preview again)' : ''}
                    </td>
                    <td>
                      {wasWritten(t, commit) && t.persisted !== false && (
                        undone[t.configuration_id]
                          ? undone[t.configuration_id]
                          : <button style={{ fontSize: 10 }} aria-label={`Undo group in ${t.name}`}
                              onClick={() => void undo(t, commit.group_id)}>Undo this group</button>
                      )}
                      {wasWritten(t, commit) && t.persisted === false && 'Undo after it is stopped'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="text-muted" style={{ marginTop: 4 }}>Group {commit.group_id}</div>
            <div style={{ marginTop: 8 }}>
              <button onClick={() => commit.committed
                ? onDone(commit)
                : onCancel('All or nothing: nothing was written.')}>Close</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
