// ---------------------------------------------------------------------------
// Petacat — the Configuration status card, banner, Compare, Reset and Restore selected
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { ConfigurationBanner } from './ConfigurationBanner'
import { ConfigurationPanel } from './ConfigurationPanel'
import { AdminLayout } from './AdminLayout'

const STATUS = {
  configuration_id: 1, kind: 'global', revision: 7,
  config_hash: 'a'.repeat(64), standard_hash: 'b'.repeat(64), origin: 'metacat_standard',
  loaded_at: null, standard_config_hash: 'c'.repeat(64), differs_rows: 2, equals_standard: false,
}
const DIFF = {
  configuration_id: 1, revision: 7, count: 2, added: 1, removed: 0, changed: 1,
  rows: [
    { table: 'engine_params', key: { name: 'p1' }, change: 'changed', current: { value: '9' },
      standard: { value: '3' }, columns: ['value'] },
    { table: 'slipnet_node_defs', key: { name: 'extra' }, change: 'added',
      current: { name: 'extra' }, standard: null, columns: [] },
  ],
}

function reply(status: number, body: unknown) {
  const text = JSON.stringify(body)
  return {
    ok: status >= 200 && status < 300, status, statusText: '',
    text: async () => text, json: async () => JSON.parse(text),
  } as unknown as Response
}

/** Serve the configuration routes; `calls` records `METHOD path` and the body. */
function serve(overrides: Record<string, (body: unknown) => Response> = {}) {
  const calls: Array<[string, unknown]> = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${String(url).replace('/api', '')}`
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push([key, body])
    if (overrides[key]) return overrides[key](body)
    if (key === 'GET /configurations/1/status') return reply(200, STATUS)
    if (key === 'GET /configurations/1/diff') return reply(200, DIFF)
    return reply(200, [])
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.unstubAllGlobals() })

describe('ConfigurationBanner', () => {
  it('says how many rows differ, as information only', async () => {
    serve()
    render(<ConfigurationBanner />)
    const note = await screen.findByRole('note')
    expect(note.textContent).toContain('differs from the Metacat Standard Configuration in 2 rows')
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('shows nothing when the configuration equals the standard', async () => {
    serve({ 'GET /configurations/1/status': () => reply(200, { ...STATUS, differs_rows: 0, equals_standard: true }) })
    const { container } = render(<ConfigurationBanner />)
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    expect(container.textContent).toBe('')
  })

  it('shows nothing when the server fails or answers something else', async () => {
    serve({ 'GET /configurations/1/status': () => reply(500, 'boom') })
    const { container } = render(<ConfigurationBanner />)
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    expect(container.textContent).toBe('')
  })
})

describe('ConfigurationPanel', () => {
  it('shows the status card', async () => {
    serve()
    render(<ConfigurationPanel />)
    expect(await screen.findByText('7')).toBeTruthy()
    expect(screen.getByText('aaaaaaaaaaaa')).toBeTruthy()
    expect(screen.getByText(/Differs from the Metacat Standard Configuration in 2 rows/)).toBeTruthy()
  })

  it('compares and lists the rows', async () => {
    serve()
    render(<ConfigurationPanel />)
    fireEvent.click(await screen.findByText('Compare with the Metacat Standard Configuration'))
    expect(await screen.findByText(/2 rows differ: 1 added, 0 removed, 1 changed/)).toBeTruthy()
    expect(screen.getByText(/value: "?9"? \(standard: "?3"?\)|value: 9 \(standard: 3\)/)).toBeTruthy()
    expect(screen.getByText('in this configuration only')).toBeTruthy()
  })

  it('restores only the selected rows', async () => {
    const calls = serve({
      'POST /configurations/1/restore-selected': () =>
        reply(200, { configuration_id: 1, revision: 8, wrote: true, entry_id: 9, ops: 1, config_hash: null }),
    })
    const changed = vi.fn()
    render(<ConfigurationPanel onChanged={changed} />)
    fireEvent.click(await screen.findByText('Compare with the Metacat Standard Configuration'))
    const restore = await screen.findByText('Restore selected (0)') as HTMLButtonElement
    expect(restore.disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('Select engine_params {"name":"p1"}'))
    fireEvent.click(await screen.findByText('Restore selected (1)'))
    await waitFor(() => expect(changed).toHaveBeenCalled())
    const post = calls.find(([k]) => k === 'POST /configurations/1/restore-selected')
    expect(post?.[1]).toEqual({ rows: [{ table: 'engine_params', key: { name: 'p1' } }] })
    expect(await screen.findByText(/Restored 1 row \(revision 8\)/)).toBeTruthy()
  })

  it('needs the typed word before it resets', async () => {
    const calls = serve({
      'POST /configurations/1/reset-to-standard': () =>
        reply(200, { configuration_id: 1, revision: 8, wrote: true, entry_id: 9, ops: 2, config_hash: null }),
    })
    render(<ConfigurationPanel />)
    fireEvent.click(await screen.findByText('Reset to the Metacat Standard Configuration…'))
    const confirm = screen.getByText('Reset') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Type reset to confirm'), { target: { value: 'rese' } })
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Type reset to confirm'), { target: { value: 'reset' } })
    expect(confirm.disabled).toBe(false)
    fireEvent.click(confirm)
    expect(await screen.findByText(/Reset to the Metacat Standard Configuration \(revision 8, 2 changes\)/)).toBeTruthy()
    expect(calls.find(([k]) => k === 'POST /configurations/1/reset-to-standard')?.[1]).toEqual({ confirm: 'reset' })
  })

  it('reports a refused reset and stays open', async () => {
    serve({ 'POST /configurations/1/reset-to-standard': () => reply(409, { detail: 'conflict' }) })
    render(<ConfigurationPanel />)
    fireEvent.click(await screen.findByText('Reset to the Metacat Standard Configuration…'))
    fireEvent.change(screen.getByLabelText('Type reset to confirm'), { target: { value: 'reset' } })
    fireEvent.click(screen.getByText('Reset'))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Could not reset to the Metacat Standard Configuration')
  })

  it('verifies the journal', async () => {
    serve({ 'GET /configurations/1/verify-journal': () =>
      reply(200, { ok: true, configuration_id: 1, revision: 7, entries: 7, problems: [] }) })
    render(<ConfigurationPanel />)
    fireEvent.click(await screen.findByText('Verify journal'))
    expect(await screen.findByText(/The journal verifies: 7 entries/)).toBeTruthy()
  })
})

describe('AdminLayout', () => {
  it('has a Status and reset tab and no seed-data export', async () => {
    serve()
    render(<AdminLayout />)
    fireEvent.click(screen.getByText('Status and reset'))
    expect(await screen.findByText(/Configuration status \(Metacat Mode\)/)).toBeTruthy()
    expect(screen.queryByText(/seed data/i)).toBeNull()
  })
})

describe('ConfigurationPanel help (C11b)', () => {
  it('has a ? for the Metacat Standard Configuration beside the status heading', async () => {
    serve()
    render(<ConfigurationPanel />)
    await screen.findByText('7')
    expect(screen.getByRole('button', { name: 'Show help for the Metacat Standard Configuration' }).textContent).toBe('?')
  })
})
