import { useCallback, useEffect, useState } from 'react'
import { request } from '@/api/client'
import { describeDbError } from './errors'
import { RowEditor, type EditMode } from './RowEditor'
import { SqlBox } from './SqlBox'
import type { DbRow, DbRowPage, DbTable, TableClass } from './types'
import { showValue } from './values'
import { useScope } from '../editScope'

const PAGE = 25

/** Badge colour per table class. */
const BADGE: Record<TableClass, string> = {
  configuration: 'rgba(76,175,80,0.25)',
  content: 'rgba(33,150,243,0.25)',
  runtime: 'rgba(255,152,0,0.25)',
  journal: 'rgba(158,158,158,0.3)',
  session_managed: 'rgba(156,39,176,0.25)',
  episodic_memory: 'rgba(244,67,54,0.25)',
}

interface Flash { kind: 'success' | 'error'; text: string }

/**
 * Database (all modes): a generic browser and editor for every table.
 *
 * Each table has a class, shown as a badge, and the class decides what can be done: a
 * configuration table is edited as a journaled batch through the change API; `help_topics` is
 * written directly; runtime data needs expert mode and the table's name typed; the journal, a
 * session's tables and a session's Episodic Memory are read-only (the server refuses a write to
 * them whatever this page sends). The SQL box is read-only.
 */
export function DatabasePanel() {
  const [tables, setTables] = useState<DbTable[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [configurationId, setConfigurationId] = useState('1')
  const [page, setPage] = useState<DbRowPage | null>(null)
  const [offset, setOffset] = useState(0)
  const [filterColumn, setFilterColumn] = useState('')
  const [filterText, setFilterText] = useState('')
  const [expert, setExpert] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [editor, setEditor] = useState<{ mode: EditMode; row: DbRow | null } | null>(null)
  const [deleting, setDeleting] = useState<DbRow | null>(null)
  const [flash, setFlash] = useState<Flash | null>(null)
  const [busy, setBusy] = useState(false)

  const scope = useScope()
  const table = tables.find(t => t.name === selected) ?? null

  const loadTables = useCallback(async () => {
    try {
      const list = await request<DbTable[]>(`/admin/db/tables?configuration=${encodeURIComponent(configurationId)}`)
      setTables(list)
    } catch (err) {
      setFlash({ kind: 'error', text: describeDbError(err, 'list the tables') })
    }
  }, [configurationId])

  const loadRows = useCallback(async () => {
    if (!selected) return
    const q = new URLSearchParams({
      configuration: configurationId, limit: String(PAGE), offset: String(offset),
    })
    if (filterText) {
      q.set('filter', filterText)
      if (filterColumn) q.set('filter_column', filterColumn)
    }
    try {
      setPage(await request<DbRowPage>(`/admin/db/tables/${selected}/rows?${q}`))
    } catch (err) {
      setPage(null)
      setFlash({ kind: 'error', text: describeDbError(err, `load the rows of ${selected}`) })
    }
  }, [selected, configurationId, offset, filterText, filterColumn])

  useEffect(() => { void loadTables() }, [loadTables])
  useEffect(() => { void loadRows() }, [loadRows])

  const choose = (name: string) => {
    setSelected(name)
    setOffset(0)
    setFilterColumn('')
    setFilterText('')
    setEditor(null)
    setDeleting(null)
    setConfirmText('')
    setFlash(null)
  }

  // Runtime data is editable only with expert mode on and the table's name typed.
  const expertOk = !!table && expert && confirmText === table.name
  const canEdit = !!table && (
    table.class === 'configuration' || table.class === 'content' || (table.class === 'runtime' && expertOk)
  )

  const afterWrite = async (text: string) => {
    setFlash({ kind: 'success', text })
    setEditor(null)
    setDeleting(null)
    await Promise.all([loadRows(), loadTables()])
  }

  const send = async (path: string, body: unknown, action: string, done: (r: any) => string) => {
    setBusy(true)
    try {
      const res = await request<any>(path, { method: 'POST', body: JSON.stringify(body) })
      await afterWrite(done(res))
    } catch (err) {
      setFlash({ kind: 'error', text: describeDbError(err, action) })
    } finally {
      setBusy(false)
    }
  }

  const write = (op: 'insert' | 'update' | 'delete', row: DbRow | null, changed: Record<string, unknown>, old: Record<string, unknown>) => {
    if (!table) return
    if (table.class === 'configuration') {
      const ops = [
        op === 'insert' ? { op, table: table.name, row: changed }
          : op === 'update'
            ? { op, table: table.name, key: row!.key, fields: changed,
                expect: Object.fromEntries(Object.keys(changed).map(k => [k, old[k]])) }
            : { op, table: table.name, key: row!.key },
      ]
      if (scope && scope.scope.mode !== 'this') {
        // Chosen or all configurations: through the preview, as an editor's save does.
        setBusy(true)
        scope.commit(ops)
          .then(c => afterWrite(`Committed to ${c.targets.filter(t => t.committed).length} configuration(s) in group ${c.group_id}.`))
          .catch(err => setFlash({ kind: 'error', text: err instanceof Error && !(err as any).status ? err.message : describeDbError(err, `${op} a row of ${table.name}`) }))
          .finally(() => setBusy(false))
        return
      }
      void send('/admin/db/changes',
        { configuration_id: Number(configurationId), ops, note: 'Database tab' },
        `${op} a row of ${table.name}`,
        r => `Saved as revision ${r.version_after} of the configuration (a journal entry).`)
    } else {
      void send('/admin/db/edit',
        { table: table.name, op, pk: row?.key, values: changed, expert: expertOk, confirm: expertOk ? confirmText : '' },
        `${op} a row of ${table.name}`,
        () => `Saved (${op}).`)
    }
  }

  const pages = page ? Math.max(1, Math.ceil(page.total / page.limit)) : 1

  return (
    <div style={{ display: 'flex', gap: 12, height: '100%' }}>
      <nav aria-label="Tables" style={{ width: 250, flexShrink: 0, overflow: 'auto', fontSize: 11 }}>
        <label style={{ display: 'block', marginBottom: 6 }}>
          Configuration{' '}
          <input
            aria-label="Configuration"
            value={configurationId}
            onChange={e => { setConfigurationId(e.target.value.replace(/\D/g, '') || '1'); setOffset(0) }}
            style={{ width: 40, fontSize: 11 }}
          />
        </label>
        {tables.map(t => (
          <button
            key={t.name}
            onClick={() => choose(t.name)}
            aria-pressed={t.name === selected}
            style={{
              display: 'flex', width: '100%', gap: 4, alignItems: 'center', textAlign: 'left',
              fontSize: 11, padding: '2px 4px',
              background: t.name === selected ? 'var(--bg-panel)' : 'transparent',
            }}
          >
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>{t.name}</span>
            <span style={{ fontSize: 9, padding: '0 4px', borderRadius: 3, background: BADGE[t.class] }}>
              {t.class_label}
            </span>
            <span style={{ fontSize: 9, opacity: 0.7 }}>{t.rows ?? '-'}</span>
          </button>
        ))}
      </nav>

      <div style={{ flex: 1, minWidth: 0, overflow: 'auto' }}>
        {flash && (
          <div role={flash.kind === 'error' ? 'alert' : 'status'} style={{
            fontSize: 11, padding: '4px 8px', marginBottom: 6, borderRadius: 3,
            background: flash.kind === 'error' ? 'rgba(244,67,54,0.2)' : 'rgba(76,175,80,0.2)',
            color: flash.kind === 'error' ? 'var(--error)' : 'var(--success)',
          }}>
            {flash.text}
          </div>
        )}

        {!table && <div style={{ fontSize: 11 }}>Choose a table to browse it.</div>}

        {table && (
          <>
            <div role="note" style={{
              fontSize: 11, padding: '4px 8px', marginBottom: 6, borderRadius: 3, background: BADGE[table.class],
            }}>
              <strong>{table.name}</strong> ({table.class_label}). {table.banner}
            </div>

            {table.class === 'runtime' && (
              <div style={{ fontSize: 11, marginBottom: 6, display: 'flex', gap: 8, alignItems: 'center' }}>
                <label>
                  <input
                    type="checkbox" checked={expert}
                    onChange={e => { setExpert(e.target.checked); setConfirmText('') }}
                  />{' '}
                  Expert mode
                </label>
                {expert && (
                  <label>
                    Type <code>{table.name}</code> to confirm{' '}
                    <input
                      aria-label="Confirmation" value={confirmText}
                      onChange={e => setConfirmText(e.target.value)} style={{ fontSize: 11 }}
                    />
                  </label>
                )}
              </div>
            )}

            <div style={{ display: 'flex', gap: 6, marginBottom: 6, fontSize: 11, alignItems: 'center' }}>
              <select
                aria-label="Filter column" value={filterColumn}
                onChange={e => { setFilterColumn(e.target.value); setOffset(0) }}
              >
                <option value="">any column</option>
                {table.columns.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
              </select>
              <input
                aria-label="Filter" placeholder="filter" value={filterText}
                onChange={e => { setFilterText(e.target.value); setOffset(0) }}
              />
              <span style={{ flex: 1 }} />
              {canEdit && (
                <button style={{ fontSize: 11 }} onClick={() => { setDeleting(null); setEditor({ mode: 'insert', row: null }) }}>
                  New row
                </button>
              )}
            </div>

            {editor && (
              <RowEditor
                key={`${editor.mode}:${JSON.stringify(editor.row?.key ?? null)}`}
                table={table} mode={editor.mode} row={editor.row} busy={busy}
                onCancel={() => setEditor(null)}
                onSave={(changed, old) => write(editor.mode, editor.row, changed, old)}
              />
            )}

            {page && (
              <div style={{ overflow: 'auto' }}>
                <table style={{ fontSize: 11, borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      {canEdit && <th style={cell} />}
                      {page.columns.map(c => (
                        <th key={c.name} style={cell}>
                          {c.name}{c.protected ? ' (protected)' : ''}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {page.rows.map((r, i) => (
                      <tr key={i}>
                        {canEdit && (
                          <td style={cell}>
                            <button style={mini} onClick={() => { setDeleting(null); setEditor({ mode: 'update', row: r }) }}>
                              Edit
                            </button>{' '}
                            {deleting === r ? (
                              <>
                                <button style={mini} disabled={busy} onClick={() => write('delete', r, {}, {})}>
                                  Confirm delete
                                </button>
                                <button style={mini} onClick={() => setDeleting(null)}>Cancel</button>
                              </>
                            ) : (
                              <button style={mini} onClick={() => { setEditor(null); setDeleting(r) }}>Delete</button>
                            )}
                          </td>
                        )}
                        {page.columns.map(c => (
                          <td key={c.name} style={{ ...cell, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                              title={showValue(r.values[c.name])}>
                            {showValue(r.values[c.name])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ fontSize: 11, marginTop: 4, display: 'flex', gap: 6, alignItems: 'center' }}>
                  <button style={mini} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                    Previous
                  </button>
                  <span>
                    Page {Math.floor(offset / PAGE) + 1} of {pages} ({page.total} row{page.total === 1 ? '' : 's'})
                  </span>
                  <button style={mini} disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        <SqlBox />
      </div>
    </div>
  )
}

const cell = { border: '1px solid var(--border)', padding: '2px 6px', textAlign: 'left' as const }
const mini = { fontSize: 10, padding: '1px 5px' }
