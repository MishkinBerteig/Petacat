// ---------------------------------------------------------------------------
// Petacat -- the scope picker's "chosen" and "all", and the edit-all preview (C9b)
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

import type { ConfigurationSummary, EditCommit, EditPreview, EditPreviewTarget } from '@/types/configuration'
import { ScopeProvider } from './editScope'
import { ConfigurationChip } from './ConfigurationChip'
import { useAdminRequest } from './adminRequest'
import { DatabasePanel } from './database/DatabasePanel'

const cfg = (id: number, name: string, extra: Partial<ConfigurationSummary> = {}): ConfigurationSummary => ({
  id, name, note: '', kind: id === 1 ? 'global' : 'session', mode: id === 1 ? 'Metacat Mode' : 'Training Mode',
  mode_label: id === 1 ? 'Metacat Mode' : `Training Mode: ${name}`, session_id: id === 1 ? null : id,
  session_name: id === 1 ? null : name, session_state: id === 1 ? null : 'stopped', revision: id * 10,
  config_hash: 'h', frozen: false, created_from_configuration_id: null, equals_standard: false,
  differs_from_standard_rows: 0, last_change: null, source: 'stored', ...extra,
})
const CONFIGS = [cfg(1, 'Global'), cfg(5, 'Alpha'), cfg(6, 'Beta', { source: 'live', live_revision: 62, session_state: 'running' }),
  cfg(7, 'Gamma', { frozen: true })]

const target = (id: number, result: EditPreviewTarget['result'], extra: Partial<EditPreviewTarget> = {}): EditPreviewTarget => {
  const c = CONFIGS.find(x => x.id === id)!
  return {
    configuration_id: id, name: c.name, mode: c.mode, mode_label: c.mode_label, session_id: c.session_id,
    session_state: c.session_state, frozen: c.frozen, result, reason: null, revision: c.revision, persisted: true, ...extra,
  }
}

function reply(status: number, body: unknown) {
  const text = JSON.stringify(body)
  return { ok: status >= 200 && status < 300, status, statusText: '', text: async () => text, json: async () => JSON.parse(text) } as unknown as Response
}

let calls: Array<{ key: string; body: any }> = []

function serve(preview: EditPreview, commit?: Partial<EditCommit>, extra: Record<string, () => Response> = {}) {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${String(url).replace('/api', '')}`
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ key, body })
    if (extra[key]) return extra[key]()
    if (key === 'GET /configurations') return reply(200, { configurations: CONFIGS })
    if (key === 'GET /admin/params') return reply(200, [{ name: 'p1', value: '1', value_type: 'int' }])
    if (key.startsWith('GET /configurations/1/rows')) return reply(200, { key_columns: ['name'], rows: [] })
    if (key === 'POST /configurations/edits/preview') return reply(200, preview)
    if (key === 'POST /configurations/edits') {
      return reply(200, { group_id: 'edit-all-1', committed: true, all_or_nothing: false, counts: {},
        targets: preview.targets.map(t => ({ ...t, version_after: (t.revision ?? 0) + 1 })), ...commit })
    }
    if (key === 'POST /configurations/5/restore') return reply(200, { wrote: true })
    return reply(200, [])
  }))
}

const PREVIEW = (targets: EditPreviewTarget[]): EditPreview => ({ preview_token: 'tok', targets, counts: {} })

let outcome: string[] = []

function Harness() {
  const request = useAdminRequest(1)
  return (
    <>
      <button onClick={() => {
        request('/admin/params/p1', { method: 'PUT', body: JSON.stringify({ value: '3', value_type: 'int' }) })
          .then(() => outcome.push('saved'), e => outcome.push(`failed: ${e.message}`))
      }}>Save</button>
    </>
  )
}

function mount() {
  outcome = []
  render(
    <ScopeProvider openId={1}>
      <ConfigurationChip configuration={1} summary={CONFIGS[0]} />
      <Harness />
    </ScopeProvider>,
  )
}

const pickScope = (value: string) => fireEvent.change(screen.getByLabelText('Apply to'), { target: { value } })
async function saveWith(value: string, opts: { refused?: boolean } = {}) {
  pickScope(value)
  if (value === 'chosen') {
    await screen.findByLabelText('Include Alpha')
    fireEvent.click(screen.getByLabelText('Include Alpha'))
  }
  fireEvent.click(screen.getByText('Save'))
  await screen.findByTestId('edit-preview')
  if (!opts.refused) await screen.findByLabelText('Preview per configuration')
}

beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.unstubAllGlobals() })

describe('the scope picker', () => {
  it('offers this, chosen and all configurations, defaulting to this one', () => {
    serve(PREVIEW([]))
    mount()
    const select = screen.getByLabelText('Apply to') as HTMLSelectElement
    expect(select.value).toBe('this')
    expect([...select.options].map(o => o.text)).toEqual(['This configuration', 'Chosen configurations', 'All configurations'])
  })

  it('shows a checklist for chosen, with the open configuration ticked and frozen ones marked', async () => {
    serve(PREVIEW([]))
    mount()
    pickScope('chosen')
    expect(await screen.findByLabelText('Include Gamma')).toBeTruthy()
    expect(screen.getByText(/Gamma \(frozen\)/)).toBeTruthy()
    expect((screen.getByLabelText('Include Global') as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText('Include Alpha') as HTMLInputElement).checked).toBe(false)
  })

  it('says that all skips the frozen ones', () => {
    serve(PREVIEW([]))
    mount()
    pickScope('all')
    expect(screen.getByTestId('scope-all-note').textContent).toContain('frozen ones are skipped')
  })

  it('writes straight to the editor route for this configuration, with no preview', async () => {
    serve(PREVIEW([]))
    mount()
    fireEvent.click(screen.getByText('Save'))
    await waitFor(() => expect(outcome).toEqual(['saved']))
    expect(calls.map(c => c.key)).toEqual(['PUT /admin/params/p1'])
    expect(screen.queryByTestId('edit-preview')).toBeNull()
  })
})

describe('the preview', () => {
  it('sends the ops, the chosen ids and the base revisions', async () => {
    serve(PREVIEW([target(1, 'apply'), target(5, 'apply')]))
    mount()
    await saveWith('chosen')
    const sent = calls.find(c => c.key === 'POST /configurations/edits/preview')!.body
    expect(sent.targets).toEqual({ ids: [1, 5] })
    expect(sent.ops).toEqual([{ op: 'update', table: 'engine_params', key: { name: 'p1' },
      fields: { value: '3' }, expect: { value: '1' } }])
    expect(sent.base_revisions).toMatchObject({ '1': 10, '5': 50, '6': 62 })
  })

  it('sends {all: true} for all configurations', async () => {
    serve(PREVIEW([target(1, 'apply'), target(7, 'skipped_by_selection', { reason: 'frozen' })]))
    mount()
    await saveWith('all')
    expect(calls.find(c => c.key === 'POST /configurations/edits/preview')!.body.targets).toEqual({ all: true })
  })

  it('shows every kind of result with its words', async () => {
    serve(PREVIEW([
      target(1, 'apply'), target(5, 'no_change'), target(6, 'differs', { persisted: false }),
      target(7, 'skipped_by_selection', { reason: 'frozen' }),
    ]))
    mount()
    await saveWith('all')
    expect(within(screen.getByTestId('target-1')).getByText('Will apply')).toBeTruthy()
    expect(within(screen.getByTestId('target-5')).getByText(/No change/)).toBeTruthy()
    expect(within(screen.getByTestId('target-6')).getByText(/^Differs/)).toBeTruthy()
    expect(within(screen.getByTestId('target-7')).getByText('Skipped: frozen')).toBeTruthy()
  })

  it('labels a live target "Live (in memory)" and a changing-state target skipped', async () => {
    serve(PREVIEW([
      target(6, 'apply', { persisted: false }),
      target(5, 'skipped_by_selection', { reason: 'changing state', session_state: 'stopping' }),
    ]))
    mount()
    await saveWith('all')
    expect(within(screen.getByTestId('target-6')).getByText('Live (in memory)')).toBeTruthy()
    expect(screen.getByText(/saved when the session is stopped/)).toBeTruthy()
    expect(within(screen.getByTestId('target-5')).getByText('Skipped: changing state')).toBeTruthy()
  })

  it('offers an overwrite tick per differs target, and sends it', async () => {
    serve(PREVIEW([target(1, 'apply'), target(5, 'differs'), target(6, 'differs')]))
    mount()
    await saveWith('all')
    fireEvent.click(screen.getByLabelText('Overwrite Alpha'))
    fireEvent.click(screen.getByRole('button', { name: 'Commit' }))
    await screen.findByLabelText('Commit result per configuration')
    const body = calls.find(c => c.key === 'POST /configurations/edits')!.body
    expect(body).toMatchObject({ preview_token: 'tok', overwrite: [5], apply_rest: [], all_or_nothing: false })
  })

  it('offers "apply the rest" for a not applicable target, and sends it', async () => {
    serve(PREVIEW([target(1, 'apply'), target(5, 'not_applicable')]))
    mount()
    await saveWith('all')
    fireEvent.click(screen.getByLabelText('Apply the rest to Alpha'))
    fireEvent.click(screen.getByRole('button', { name: 'Commit' }))
    await screen.findByLabelText('Commit result per configuration')
    expect(calls.find(c => c.key === 'POST /configurations/edits')!.body.apply_rest).toEqual([5])
  })

  it('previews again from a stale target', async () => {
    serve(PREVIEW([target(1, 'apply'), target(5, 'stale', { current_revision: 51 })]))
    mount()
    await saveWith('all')
    fireEvent.click(screen.getByText('Preview again'))
    await waitFor(() => expect(calls.filter(c => c.key === 'POST /configurations/edits/preview')).toHaveLength(2))
  })

  it('sends all-or-nothing and the reason', async () => {
    serve(PREVIEW([target(1, 'apply'), target(5, 'apply')]))
    mount()
    await saveWith('all')
    fireEvent.click(screen.getByLabelText(/All or nothing/))
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'tuning' } })
    fireEvent.click(screen.getByRole('button', { name: 'Commit' }))
    await screen.findByLabelText('Commit result per configuration')
    expect(calls.find(c => c.key === 'POST /configurations/edits')!.body)
      .toMatchObject({ all_or_nothing: true, reason: 'tuning' })
  })

  it('cancelling writes nothing and fails the save', async () => {
    serve(PREVIEW([target(1, 'apply')]))
    mount()
    await saveWith('all')
    fireEvent.click(screen.getByText('Cancel'))
    await waitFor(() => expect(outcome[0]).toContain('failed: The change was cancelled'))
    expect(calls.some(c => c.key === 'POST /configurations/edits')).toBe(false)
  })
})

describe('the commit result', () => {
  it('shows each target, an undo for a stored one, and saved-at-Stop for a live one', async () => {
    serve(PREVIEW([target(5, 'apply'), target(6, 'apply', { persisted: false })]), {
      targets: [
        { ...target(5, 'apply'), committed: true, version_after: 51 },
        { ...target(6, 'apply', { persisted: false }), committed: true, version_after: 63 },
      ],
    })
    mount()
    await saveWith('all')
    fireEvent.click(screen.getByRole('button', { name: 'Commit' }))
    const stored = await screen.findByTestId('result-5')
    expect(stored.textContent).toContain('Written as revision 51')
    expect(screen.getByTestId('result-6').textContent).toContain('Applied in memory (revision 63); saved at Stop')
    fireEvent.click(screen.getByLabelText('Undo group in Alpha'))
    await waitFor(() => expect(calls.find(c => c.key === 'POST /configurations/5/restore')!.body)
      .toMatchObject({ undo_group: 'edit-all-1' }))
    expect(screen.getByTestId('result-5').textContent).toContain('Undone')
    fireEvent.click(screen.getByText('Close'))
    await waitFor(() => expect(outcome).toEqual(['saved']))
  })

  it('reports an all-or-nothing hold: nothing written, and closing fails the save', async () => {
    serve(PREVIEW([target(1, 'apply'), target(5, 'differs')]), {
      committed: false, all_or_nothing: true, blocked_by: [5],
      targets: [{ ...target(1, 'apply'), committed: false }, { ...target(5, 'differs'), committed: false }],
    })
    mount()
    await saveWith('all')
    fireEvent.click(screen.getByLabelText(/All or nothing/))
    fireEvent.click(screen.getByLabelText('Overwrite Alpha'))
    fireEvent.click(screen.getByRole('button', { name: 'Commit' }))
    expect((await screen.findByTestId('blocked')).textContent).toContain('nothing was written')
    expect(screen.getByTestId('blocked').textContent).toContain('configuration 5')
    fireEvent.click(screen.getByText('Close'))
    await waitFor(() => expect(outcome[0]).toContain('failed: All or nothing'))
  })

  it('shows a refused preview as an error', async () => {
    serve(PREVIEW([]), undefined, { 'POST /configurations/edits/preview': () => reply(400, { message: 'bad ops' }) })
    mount()
    await saveWith('all', { refused: true })
    expect((await screen.findByRole('alert')).textContent).toBeTruthy()
  })
})

describe('the Database tab', () => {
  it('sends a configuration-table delete through the preview when the scope is all', async () => {
    const table = {
      name: 'engine_params', class: 'configuration', class_label: 'configuration', banner: 'b', editable: true,
      expert_required: false, enum: false, rows: 1, key_columns: ['name'],
      columns: [{ name: 'name', type: 'VARCHAR', primary_key: true, nullable: false, protected: false }],
    }
    serve(PREVIEW([target(1, 'apply'), target(5, 'apply')]), undefined, {
      'GET /admin/db/tables?configuration=1': () => reply(200, [table]),
      'GET /admin/db/tables/engine_params/rows?configuration=1&limit=25&offset=0': () => reply(200, {
        ...table, configuration: 1, total: 1, limit: 25, offset: 0,
        rows: [{ values: { name: 'p1' }, key: { name: 'p1' } }],
      }),
    })
    render(
      <ScopeProvider openId={1}>
        <ConfigurationChip configuration={1} summary={CONFIGS[0]} />
        <DatabasePanel />
      </ScopeProvider>,
    )
    pickScope('all')
    fireEvent.click(await screen.findByRole('button', { name: /engine_params/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm delete' }))
    await screen.findByLabelText('Preview per configuration')
    expect(calls.find(c => c.key === 'POST /configurations/edits/preview')!.body.ops)
      .toEqual([{ op: 'delete', table: 'engine_params', key: { name: 'p1' } }])
    expect(calls.some(c => c.key === 'POST /admin/db/changes')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Commit' }))
    await screen.findByLabelText('Commit result per configuration')
  })
})
