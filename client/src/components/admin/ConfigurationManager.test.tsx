// ---------------------------------------------------------------------------
// Petacat -- the configuration manager (C9a): list, open, chip, compare, apply-from, freeze
// ---------------------------------------------------------------------------
//
// The mode badge and the header chip are what keep Metacat Mode and Training Mode apart on
// every screen, so these tests hold them present and exact: on every editor tab, for the
// global configuration and for a stopped, a live and a changing-state session.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

import type { ConfigurationSummary } from '@/types/configuration'
import { AdminLayout } from './AdminLayout'
import { ConfigurationsTab } from './ConfigurationsTab'
import { makeAdminRequest } from './adminRequest'
import { SlipnetEditor } from './SlipnetEditor'
import { SlipnetLinkEditor } from './SlipnetLinkEditor'
import { CodeletEditor } from './CodeletEditor'
import { ParamsEditor } from './ParamsEditor'
import { UrgencyLevelEditor } from './UrgencyLevelEditor'
import { FormulaCoefficientEditor } from './FormulaCoefficientEditor'
import { DemoEditor } from './DemoEditor'
import { ThemeDimensionEditor } from './ThemeDimensionEditor'
import { PostingRuleEditor } from './PostingRuleEditor'
import { CommentaryTemplateEditor } from './CommentaryTemplateEditor'
import { SlipnetLayoutEditor } from './SlipnetLayoutEditor'
import { NewSessionForm } from '../session/NewSessionForm'

const GLOBAL: ConfigurationSummary = {
  id: 1, name: 'Metacat Mode: global configuration', note: '', kind: 'global', mode: 'Metacat Mode',
  mode_label: 'Metacat Mode', session_id: null, session_name: null, session_state: null,
  revision: 12, config_hash: 'a', frozen: false, created_from_configuration_id: null,
  equals_standard: false, differs_from_standard_rows: 3,
  last_change: { revision: 12, source: 'admin', actor: 'admin', channel: 'admin_editor', recorded_at: '2026-11-01T10:00:00Z' },
  source: 'stored',
}
const STOPPED: ConfigurationSummary = {
  ...GLOBAL, id: 5, name: 'Alpha', kind: 'session', mode: 'Training Mode',
  mode_label: 'Training Mode: Alpha', session_id: 7, session_name: 'Alpha', session_state: 'stopped',
  revision: 4, differs_from_standard_rows: 1, equals_standard: false,
  last_change: { revision: 4, source: 'learner', actor: 'learner', channel: 'worker', recorded_at: '2026-11-02T10:00:00Z' },
}
const LIVE: ConfigurationSummary = {
  ...STOPPED, id: 6, name: 'Beta', session_name: 'Beta', mode_label: 'Training Mode: Beta', session_id: 8,
  session_state: 'running', source: 'live', live_revision: 9, saved_through: 6, saved_at: '2026-11-02T09:00:00Z',
  unsaved: 3, revision: 6, differs_from_standard_rows: 0, equals_standard: true,
}
const CHANGING: ConfigurationSummary = { ...STOPPED, id: 9, name: 'Gamma', session_name: 'Gamma', session_state: 'stopping', session_id: 9 }
const ALL = [GLOBAL, STOPPED, LIVE, CHANGING]

function reply(status: number, body: unknown) {
  const text = JSON.stringify(body)
  return {
    ok: status >= 200 && status < 300, status, statusText: '',
    text: async () => text, json: async () => JSON.parse(text),
  } as unknown as Response
}

type Handler = (body: any, url: string) => Response
let calls: Array<{ key: string; body: any }> = []

/** Serves the manager's routes; `extra` handlers are keyed `METHOD /path` (without `/api`). */
function serve(extra: Record<string, Handler> = {}, configurations: ConfigurationSummary[] = ALL) {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${String(url).replace('/api', '')}`
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ key, body })
    if (extra[key]) return extra[key](body, key)
    if (key.startsWith('GET /journal')) return reply(200, { entries: [], total: 0, limit: 50, offset: 0, live: null })
    if (key === 'GET /configurations') return reply(200, { configurations })
    const one = key.match(/^GET \/configurations\/(\d+)$/)
    if (one) {
      const c = configurations.find(x => x.id === Number(one[1]))
      return c ? reply(200, c) : reply(404, { detail: 'no such configuration' })
    }
    if (/^GET \/configurations\/\d+\/status/.test(key)) return reply(200, { differs_rows: 0, equals_standard: true })
    if (/^GET \/configurations\/\d+\/rows/.test(key)) return reply(200, { key_columns: ['name'], rows: [] })
    return reply(200, [])
  }))
}

beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.unstubAllGlobals(); window.location.hash = '' })

const EDITOR_TABS = [
  'Slipnet Nodes', 'Slipnet Links', 'Codelet Types', 'Engine Params', 'Urgency Levels',
  'Formula Coefficients', 'Demo Problems', 'Enum Tables', 'Theme Dimensions', 'Posting Rules',
  'Commentary Templates', 'Slipnet Layout', 'Help Topics', 'History', 'Database (all modes)', 'Status and reset',
]

const GLOBAL_CHIP = 'Editing: Metacat Mode global configuration. This does not affect any session'

async function openFromManager(name: string) {
  render(<AdminLayout />)
  fireEvent.click(screen.getByText('Configurations'))
  fireEvent.click(await screen.findByRole('button', { name: `Open ${name}` }))
}

describe('the header chip', () => {
  it('is present on every editor tab, for the global configuration, with the exact wording', async () => {
    serve()
    render(<AdminLayout />)
    for (const tab of EDITOR_TABS) {
      fireEvent.click(screen.getByText(tab))
      const chip = await screen.findByTestId('configuration-chip')
      expect(chip.textContent).toContain(GLOBAL_CHIP)
    }
  })

  it('is absent only on the manager tab, where no editor is open', async () => {
    serve()
    render(<AdminLayout />)
    fireEvent.click(screen.getByText('Configurations'))
    await screen.findByLabelText('Configurations')
    expect(screen.queryByTestId('configuration-chip')).toBeNull()
  })

  it('names a stopped Training Mode Session, on every editor tab', async () => {
    serve()
    await openFromManager('Alpha')
    for (const tab of EDITOR_TABS) {
      fireEvent.click(screen.getByText(tab))
      await waitFor(() => expect(screen.getByTestId('configuration-chip').textContent).toContain(
        "Editing: Training Mode Session 'Alpha' (stopped). Changes are saved at once. This does not affect Metacat Mode."))
    }
    expect(screen.getByTestId('source-label').textContent).toBe('Stored (as of last stop)')
  })

  it('says a running session holds its changes in memory, with its last stop', async () => {
    serve()
    await openFromManager('Beta')
    await waitFor(() => {
      const text = screen.getByTestId('configuration-chip').textContent ?? ''
      expect(text).toContain("Editing: Training Mode Session 'Beta' (running). Changes are held in memory and saved when the session is stopped.")
      expect(text).toContain('The database shows the state as of its last stop (revision 6,')
    })
    expect(screen.getByTestId('source-label').textContent).toBe('Live (in memory)')
  })

  it('makes the editors read-only while a session is starting or stopping, and keeps the chip', async () => {
    serve()
    await openFromManager('Gamma')
    expect((await screen.findByTestId('changing-state')).textContent).toContain('This session is changing state')
    expect(screen.getByTestId('configuration-chip').textContent).toContain("'Gamma' (stopping)")
    expect(screen.queryByText(/slipnet nodes \(double-click/)).toBeNull()
  })

  it('shows the scope picker, defaulting to "this configuration"', async () => {
    serve()
    render(<AdminLayout />)
    const picker = await screen.findByLabelText('Apply to')
    expect(within(picker).getAllByRole('option').map(o => o.textContent))
      .toEqual(['This configuration', 'Chosen configurations', 'All configurations'])
    expect((picker as HTMLSelectElement).value).toBe('this')
  })

  it('says why the enum and help tabs have no session configuration to edit', async () => {
    serve()
    await openFromManager('Alpha')
    fireEvent.click(screen.getByText('Enum Tables'))
    expect((await screen.findByTestId('global-only')).textContent).toContain('only the global configuration (Metacat Mode)')
    expect(screen.getByTestId('configuration-chip')).toBeTruthy()
  })
})

describe('the manager list', () => {
  it('shows one row per configuration with the badge, revision, frozen, difference and last change', async () => {
    serve()
    render(<ConfigurationsTab openId={1} onOpen={() => {}} onHistory={() => {}} />)
    expect((await screen.findByTestId('badge-1')).textContent).toBe('Metacat Mode')
    expect(screen.getByTestId('badge-5').textContent).toBe('Training Mode: Alpha, stopped')
    expect(screen.getByTestId('badge-6').textContent).toBe(
      'Training Mode: Beta, running, live, saved through revision 6, 3 unsaved batches')
    const global = screen.getByTestId('configuration-1')
    expect(global.textContent).toContain('differs from the Metacat Standard Configuration in 3 rows')
    expect(global.textContent).toContain('(admin, admin, admin_editor)')
    expect(screen.getByTestId('configuration-6').textContent).toContain('equals the Metacat Standard Configuration')
    expect(screen.getByTestId('configuration-5').textContent).toContain('differs from the Metacat Standard Configuration in 1 row')
  })

  it('filters by mode and sorts by a column', async () => {
    serve()
    render(<ConfigurationsTab openId={1} onOpen={() => {}} onHistory={() => {}} />)
    await screen.findByTestId('badge-1')
    fireEvent.change(screen.getByLabelText('Filter by mode'), { target: { value: 'Metacat Mode' } })
    expect(screen.queryByTestId('badge-5')).toBeNull()
    expect(screen.getByTestId('badge-1')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Filter by mode'), { target: { value: 'Training Mode' } })
    expect(screen.queryByTestId('badge-1')).toBeNull()
    const order = () => screen.getAllByTestId(/^configuration-\d+$/).map(r => r.getAttribute('data-testid'))
    fireEvent.click(screen.getByLabelText('Sort by Revision'))
    expect(order()).toEqual(['configuration-5', 'configuration-6', 'configuration-9'].sort((x, y) => (
      ({ 'configuration-5': 4, 'configuration-6': 6, 'configuration-9': 4 } as Record<string, number>)[x]
      - ({ 'configuration-5': 4, 'configuration-6': 6, 'configuration-9': 4 } as Record<string, number>)[y])))
    fireEvent.click(screen.getByLabelText('Sort by Revision'))
    expect(order()[0]).toBe('configuration-6')
  })

  it('opens a configuration in the editors, which read its rows', async () => {
    serve()
    await openFromManager('Alpha')
    await screen.findByText(/slipnet nodes \(double-click to edit\)/)
    expect(calls.some(c => c.key === 'GET /configurations/5/rows?table=slipnet_node_defs')).toBe(true)
    // (The global list was read once, when the layout first opened on its default tab.)
    const first = calls.findIndex(c => c.key === 'GET /configurations/5/rows?table=slipnet_node_defs')
    expect(calls.slice(first).filter(c => /^GET \/admin\//.test(c.key))).toEqual([])
  })

  it('freezes and unfreezes with the PATCH', async () => {
    serve({ 'PATCH /configurations/5': () => reply(200, { ...STOPPED, frozen: true }) })
    render(<ConfigurationsTab openId={1} onOpen={() => {}} onHistory={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Freeze Alpha' }))
    await waitFor(() => expect(calls.find(c => c.key === 'PATCH /configurations/5')?.body).toEqual({ frozen: true }))
    serve({ 'PATCH /configurations/5': () => reply(200, STOPPED) }, [GLOBAL, { ...STOPPED, frozen: true }])
    render(<ConfigurationsTab openId={1} onOpen={() => {}} onHistory={() => {}} />)
    fireEvent.click(await screen.findAllByRole('button', { name: 'Unfreeze Alpha' }).then(b => b[0]))
    await waitFor(() => expect(calls.find(c => c.key === 'PATCH /configurations/5')?.body).toEqual({ frozen: false }))
  })

  it('links a configuration to the History tab', async () => {
    serve()
    render(<AdminLayout />)
    fireEvent.click(screen.getByText('Configurations'))
    fireEvent.click(await screen.findByRole('button', { name: 'History of Alpha' }))
    await screen.findByTestId('history-slot')
    await waitFor(() => expect(calls.some(c => /^GET \/journal\?.*configuration_id=5/.test(c.key))).toBe(true))
    expect(screen.getByTestId('configuration-chip').textContent).toContain("'Alpha'")
  })

  it('starts a new session from a configuration through the hash the session view reads', async () => {
    serve()
    render(<ConfigurationsTab openId={1} onOpen={() => {}} onHistory={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'New session from Alpha' }))
    expect(window.location.hash).toBe('#/training-mode/new?base=session:7&name=Alpha')
    fireEvent.click(screen.getByRole('button', { name: 'New session from Metacat Mode: global configuration' }))
    expect(window.location.hash).toBe('#/training-mode/new?base=global')
  })

  it('opens the creation form with configuration_base set', async () => {
    const posted: any[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        posted.push(JSON.parse(String(init.body)))
        return reply(200, { session: { id: 11, name: 'Child' }, added: 0 })
      }
      return reply(200, {})
    }))
    const onCreated = vi.fn()
    render(
      <NewSessionForm
        limits={null} defaults={null} onCreated={onCreated} onCancel={() => {}}
        configurationBase={{ value: { session_id: 7 }, label: "Training Mode Session 'Alpha' configuration" }}
      />,
    )
    expect(screen.getByTestId('configuration-base-line').textContent).toContain("Training Mode Session 'Alpha' configuration")
    fireEvent.change(document.getElementById('session-name')!, { target: { value: 'Child' } })
    fireEvent.click(screen.getByText('Create session'))
    await waitFor(() => expect(onCreated).toHaveBeenCalled())
    expect(posted[0].settings.configuration_base).toEqual({ session_id: 7 })
  })
})

const compareButton = async () =>
  within(await screen.findByLabelText('Compare configurations')).getByRole('button', { name: 'Compare' })

describe('compare and apply-from', () => {
  const COMPARE = {
    a: { id: 5, name: 'Alpha', mode_label: 'Training Mode: Alpha', revision: 4 },
    b: { id: 'standard', name: 'Metacat Standard Configuration', mode_label: 'Metacat Standard Configuration', revision: null },
    same: false, count: 2, added: 1, removed: 0, changed: 1,
    rows: [
      { table: 'engine_params', key: { name: 'p1' }, change: 'changed', a: { value: '9' }, b: { value: '3' }, columns: ['value'] },
      { table: 'slipnet_node_defs', key: { name: 'extra' }, change: 'added', a: { name: 'extra' }, b: null, columns: [] },
    ],
  }

  it('compares one configuration with the Metacat Standard Configuration, row by row', async () => {
    serve({ 'GET /configurations/compare?a=5&b=standard': () => reply(200, COMPARE) })
    render(<ConfigurationsTab openId={1} onOpen={() => {}} onHistory={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Compare Alpha' }))
    fireEvent.click(await compareButton())
    expect(await screen.findByText(/2 rows differ: 1 only in A, 0 only in B, 1 changed/)).toBeTruthy()
    expect(screen.getByText(/value: "?9"? \(A\)|value: 9 \(A\) \/ 3 \(B\)/)).toBeTruthy()
    expect(screen.getByText('only in A')).toBeTruthy()
  })

  it('compares two configurations picked from the lists', async () => {
    serve({ 'GET /configurations/compare?a=5&b=6': () => reply(200, { ...COMPARE, b: { id: 6, name: 'Beta', mode_label: 'Training Mode: Beta', revision: 6 } }) })
    render(<ConfigurationsTab openId={1} onOpen={() => {}} onHistory={() => {}} />)
    await screen.findByTestId('badge-1')
    fireEvent.change(screen.getByLabelText('Compare A'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('Compare B'), { target: { value: '6' } })
    fireEvent.click(await compareButton())
    await screen.findByText(/2 rows differ/)
    expect(calls.some(c => c.key === 'GET /configurations/compare?a=5&b=6')).toBe(true)
  })

  it('refuses to compare a configuration with itself', async () => {
    serve()
    render(<ConfigurationsTab openId={1} onOpen={() => {}} onHistory={() => {}} />)
    await screen.findByTestId('badge-1')
    fireEvent.change(screen.getByLabelText('Compare B'), { target: { value: '1' } })
    fireEvent.click(await compareButton())
    expect((await screen.findByRole('alert')).textContent).toContain('two different configurations')
  })

  it('previews, then applies the selected rows to the other side with a reason', async () => {
    const sent: any[] = []
    serve({
      'GET /configurations/compare?a=5&b=6': () => reply(200, { ...COMPARE, b: { id: 6, name: 'Beta', mode_label: 'Training Mode: Beta', revision: 6 } }),
      'POST /configurations/6/apply-from': (body) => {
        sent.push(body)
        return reply(200, body.dry_run
          ? { configuration_id: 6, wrote: false, persisted: false, dry_run: true, ops: 1, cascaded: [{}, {}] }
          : { configuration_id: 6, wrote: true, persisted: true, ops: 1, revision: 7 })
      },
    })
    render(<ConfigurationsTab openId={1} onOpen={() => {}} onHistory={() => {}} />)
    await screen.findByTestId('badge-1')
    fireEvent.change(screen.getByLabelText('Compare A'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('Compare B'), { target: { value: '6' } })
    fireEvent.click(await compareButton())
    fireEvent.click(await screen.findByLabelText('Select slipnet_node_defs {"name":"extra"}'))
    fireEvent.click(screen.getByText(/Apply to B \(make B match A\) for selected \(1\)/))

    const preview = await screen.findByTestId('apply-preview')
    expect(preview.textContent).toContain('1 row to Beta from Alpha: 1 change, and 2 dependent rows removed with them')
    expect(sent[0]).toMatchObject({ source: 5, dry_run: true, rows: [{ table: 'slipnet_node_defs', key: { name: 'extra' } }] })
    expect(sent).toHaveLength(1)  // the preview wrote nothing and sent one request

    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'bring it across' } })
    fireEvent.click(screen.getByText('Apply', { selector: 'button' }))
    expect(await screen.findByText(/Applied 1 change; it takes effect at that configuration's next run/)).toBeTruthy()
    expect(sent[1]).toMatchObject({ source: 5, dry_run: false, note: 'bring it across' })
  })

  it('cannot apply to the Metacat Standard Configuration', async () => {
    serve({ 'GET /configurations/compare?a=5&b=standard': () => reply(200, COMPARE) })
    render(<ConfigurationsTab openId={1} onOpen={() => {}} onHistory={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Compare Alpha' }))
    fireEvent.click(await compareButton())
    fireEvent.click(await screen.findByLabelText('Select slipnet_node_defs {"name":"extra"}'))
    expect((screen.getByText(/Apply to B/) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByText(/Apply to A/) as HTMLButtonElement).disabled).toBe(false)
  })

  it('reports a refused apply and writes nothing more', async () => {
    serve({
      'GET /configurations/compare?a=5&b=standard': () => reply(200, COMPARE),
      'POST /configurations/5/apply-from': () => reply(422, { detail: 'no such row' }),
    })
    render(<ConfigurationsTab openId={1} onOpen={() => {}} onHistory={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Compare Alpha' }))
    fireEvent.click(await compareButton())
    fireEvent.click(await screen.findByLabelText('Select slipnet_node_defs {"name":"extra"}'))
    fireEvent.click(screen.getByText(/Apply to A/))
    expect((await screen.findByRole('alert')).textContent).toContain('no such row')
  })
})

describe('every editor with a non-global configuration', () => {
  const CASES: Array<[string, () => React.ReactElement, string]> = [
    ['Slipnet Nodes', () => <SlipnetEditor configuration={5} />, 'slipnet_node_defs'],
    ['Slipnet Links', () => <SlipnetLinkEditor configuration={5} />, 'slipnet_link_defs'],
    ['Codelet Types', () => <CodeletEditor configuration={5} />, 'codelet_type_defs'],
    ['Engine Params', () => <ParamsEditor configuration={5} />, 'engine_params'],
    ['Urgency Levels', () => <UrgencyLevelEditor configuration={5} />, 'urgency_levels'],
    ['Formula Coefficients', () => <FormulaCoefficientEditor configuration={5} />, 'formula_coefficients'],
    ['Demo Problems', () => <DemoEditor configuration={5} />, 'demo_problems'],
    ['Theme Dimensions', () => <ThemeDimensionEditor configuration={5} />, 'theme_dimension_defs'],
    ['Posting Rules', () => <PostingRuleEditor configuration={5} />, 'posting_rules'],
    ['Commentary Templates', () => <CommentaryTemplateEditor configuration={5} />, 'commentary_templates'],
    ['Slipnet Layout', () => <SlipnetLayoutEditor configuration={5} />, 'slipnet_layout'],
  ]

  it.each(CASES)('%s reads the configuration\'s rows, not the global list', async (_name, make, table) => {
    serve()
    render(make())
    await waitFor(() => expect(calls.some(c => c.key === `GET /configurations/5/rows?table=${table}`)).toBe(true))
    expect(calls.some(c => /^GET \/admin\//.test(c.key))).toBe(false)
  })

  it('shows the rows of the configuration it was given', async () => {
    serve({
      'GET /configurations/5/rows?table=engine_params': () => reply(200, {
        key_columns: ['name'], rows: [{ name: 'only_in_alpha', value: '7', value_type: 'int' }] }),
    })
    render(<ParamsEditor configuration={5} />)
    expect(await screen.findByText('only_in_alpha')).toBeTruthy()
  })
})

describe('the requester for a session configuration', () => {
  const rowsReply = (table: string, keys: string[], rows: any[]) => ({
    [`GET /configurations/5/rows?table=${table}`]: () => reply(200, { key_columns: keys, rows }),
  })

  it('is the plain requester for the global configuration', async () => {
    serve()
    await makeAdminRequest(1)('/admin/params')
    expect(calls[0].key).toBe('GET /admin/params')
  })

  it('writes a natural-key editor to the same route with ?configuration=', async () => {
    serve()
    const request = makeAdminRequest(5)
    await request('/admin/params/p1', { method: 'PUT', body: JSON.stringify({ value: '3', value_type: 'int' }) })
    await request('/admin/slipnet/nodes/a%20b', { method: 'DELETE' })
    expect(calls.map(c => c.key)).toEqual([
      'PUT /admin/params/p1?configuration=5',
      'DELETE /admin/slipnet/nodes/a%20b?configuration=5',
    ])
  })

  it('turns a surrogate-id update and delete into change-API ops by natural key', async () => {
    serve(rowsReply('slipnet_link_defs', ['from_node', 'to_node', 'link_type', 'label_node'], [
      { from_node: 'x', to_node: 'y', link_type: 'lat', label_node: null, link_length: 50, fixed_length: true },
    ]))
    const request = makeAdminRequest(5)
    const links = await request<any[]>('/admin/slipnet/links')
    expect(links[0].id).toBe(1)
    const saved = await request<any>('/admin/slipnet/links/1', {
      method: 'PUT',
      body: JSON.stringify({ from_node: 'x', to_node: 'y', link_type: 'lat', label_node: null, link_length: 60, fixed_length: true }),
    })
    expect(saved).toMatchObject({ id: 1, link_length: 60 })
    await request('/admin/slipnet/links/1', { method: 'DELETE' })
    const writes = calls.filter(c => c.key === 'POST /configurations/5/changes').map(c => c.body)
    expect(writes[0]).toMatchObject({ source: 'admin', actor: 'admin', channel: 'admin_editor', base_mode: 'rebase' })
    // The unchanged key columns (a null label is the key '') name the row; they are not set again.
    expect(writes[0].ops).toEqual([{
      op: 'update', table: 'slipnet_link_defs',
      key: { from_node: 'x', to_node: 'y', link_type: 'lat', label_node: '' },
      fields: { link_length: 60, fixed_length: true },
    }])
    expect(writes[1].ops).toEqual([{
      op: 'delete', table: 'slipnet_link_defs',
      key: { from_node: 'x', to_node: 'y', link_type: 'lat', label_node: '' },
    }])
  })

  it('turns a surrogate-id create into an insert, and gives a posting rule a free key', async () => {
    serve(rowsReply('posting_rules', ['rule_key'], [{ rule_key: 'bond', codelet_type: 'bond', direction: 'out' }]))
    const request = makeAdminRequest(5)
    await request('/admin/posting-rules')
    const made = await request<any>('/admin/posting-rules', {
      method: 'POST', body: JSON.stringify({ codelet_type: 'bond', direction: 'in' }),
    })
    expect(made).toMatchObject({ rule_key: 'bond_2', id: 2 })
    const write = calls.find(c => c.key === 'POST /configurations/5/changes')!.body
    expect(write.ops).toEqual([{ op: 'insert', table: 'posting_rules', row: { codelet_type: 'bond', direction: 'in', rule_key: 'bond_2' } }])
  })

  it('reports a change-API refusal in the editors\' own words', async () => {
    serve({
      ...rowsReply('demo_problems', ['name'], [{ name: 'd', initial: 'abc', modified: 'abd', target: 'ijk' }]),
      'POST /configurations/5/changes': () => reply(422, { ok: false, error: 'unknown_reference', message: 'demo_problems has no row with key d' }),
    })
    const request = makeAdminRequest(5)
    await request('/admin/demos')
    await expect(request('/admin/demos/1', { method: 'DELETE' })).rejects.toMatchObject({
      status: 422, detail: 'demo_problems has no row with key d',
    })
  })

  it('answers 404 for a surrogate id the list never gave', async () => {
    serve(rowsReply('commentary_templates', ['template_key'], []))
    await expect(makeAdminRequest(5)('/admin/commentary-templates/4', { method: 'DELETE' }))
      .rejects.toMatchObject({ status: 404 })
  })
})

describe('the deep link #/config?configuration=<id>', () => {
  afterEach(() => { window.location.hash = '' })

  it('opens that configuration in the editors on mount', async () => {
    serve()
    window.location.hash = '#/config?configuration=5'
    render(<AdminLayout />)
    await waitFor(() => expect(screen.getByTestId('configuration-chip').textContent).toContain("Training Mode Session 'Alpha'"))
  })

  it('opens it on a hashchange while the Configurations view is shown', async () => {
    serve()
    window.location.hash = '#/config'
    render(<AdminLayout />)
    await waitFor(() => expect(screen.getByTestId('configuration-chip').textContent).toContain(GLOBAL_CHIP))
    window.location.hash = '#/config?configuration=6'
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await waitFor(() => expect(screen.getByTestId('configuration-chip').textContent).toContain("Training Mode Session 'Beta'"))
  })

  it('keeps the global configuration for a missing or invalid id', async () => {
    serve()
    window.location.hash = '#/config?configuration=abc'
    render(<AdminLayout />)
    await waitFor(() => expect(screen.getByTestId('configuration-chip').textContent).toContain(GLOBAL_CHIP))
  })
})

describe('help buttons (C11b)', () => {
  it('the manager list has a ? for the configuration manager', async () => {
    serve()
    render(<ConfigurationsTab openId={1} onOpen={() => {}} onHistory={() => {}} />)
    await screen.findByTestId('badge-1')
    expect(screen.getByRole('button', { name: 'Show help for the configuration manager' }).textContent).toBe('?')
  })

  it('the header chip has a ? for the scope picker', async () => {
    serve()
    render(<AdminLayout />)
    await screen.findByLabelText('Apply to')
    expect(screen.getByRole('button', { name: 'Show help for the scope picker (Apply to)' }).textContent).toBe('?')
  })

  it('the new-session form has a ? for the Starting Conceptual State', () => {
    render(<NewSessionForm limits={null} defaults={null} onCreated={() => {}} onCancel={() => {}} />)
    expect(screen.getByRole('button', { name: 'Show help for the Starting Conceptual State' }).textContent).toBe('?')
  })
})
