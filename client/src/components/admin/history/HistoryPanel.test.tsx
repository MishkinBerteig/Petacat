// ---------------------------------------------------------------------------
// Petacat -- the History panel: entries, the "not yet saved" label, detail and undo
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

import { HistoryPanel } from './HistoryPanel'
import { entry, reply, serve } from './testing'

afterEach(() => { vi.unstubAllGlobals() })

const PAGE = (entries: unknown[], live: unknown = null) => reply(200, { entries, total: entries.length, limit: 50, offset: 0, live })

describe('HistoryPanel', () => {
  it('lists the entries with source, actor, channel, note, revision and counts', async () => {
    serve({ 'GET /journal': () => PAGE([entry(3, { note: 'raise depth', counts: { insert: 0, update: 2, delete: 1 } }), entry(2)]) })
    render(<HistoryPanel configurationId={1} />)
    const rows = await screen.findAllByTestId('history-entry')
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('r3')
    expect(rows[0].textContent).toContain('admin')
    expect(rows[0].textContent).toContain('tester')
    expect(rows[0].textContent).toContain('admin_editor')
    expect(rows[0].textContent).toContain('raise depth')
    expect(rows[0].textContent).toContain('2 updated, 1 deleted')
    expect(screen.queryByTestId('pending-badge')).toBeNull()
  })

  it('labels a live session\'s pending entry "not yet saved" and cannot undo it', async () => {
    serve({
      'GET /journal': () => PAGE(
        [entry(5, { id: null, pending: true, saved: false, label: 'not yet saved' }), entry(4)],
        { state: 'running', revision: 5, saved_through: 4, unsaved: 1 },
      ),
    })
    render(<HistoryPanel configurationId={7} />)
    const rows = await screen.findAllByTestId('history-entry')
    expect(within(rows[0]).getByTestId('pending-badge').textContent).toBe('not yet saved')
    expect(within(rows[1]).queryByTestId('pending-badge')).toBeNull()
    expect((within(rows[0]).getByText('Undo batch') as HTMLButtonElement).disabled).toBe(true)
    expect((within(rows[1]).getByText('Undo batch') as HTMLButtonElement).disabled).toBe(false)
    expect(screen.getByTestId('live-note').textContent).toContain('as of revision 4')
    expect(screen.getByTestId('live-note').textContent).toContain('1 batch is held in memory')
  })

  it('shows an entry in full: proposed ops, resolved ops and before-images', async () => {
    const detail = {
      ...entry(3), proposed: [{ op: 'remove_node', name: 'plato-x' }],
      resolved: [{ op: 'delete', table: 'slipnet_node_defs', key: { name: 'plato-x' } }],
      before: [{ name: 'plato-x', conceptual_depth: 40 }],
    }
    serve({
      'GET /journal': () => PAGE([entry(3)]),
      'GET /journal/30': () => reply(200, detail),
    })
    render(<HistoryPanel configurationId={1} />)
    fireEvent.click(await screen.findByText('Detail'))
    const box = await screen.findByTestId('entry-detail')
    expect(box.textContent).toContain('remove_node')
    expect(box.textContent).toContain('delete slipnet_node_defs [plato-x]')
    expect(box.textContent).toContain('"conceptual_depth": 40')
  })

  it('reads a pending entry\'s bodies from the list, since it has no id', async () => {
    const pending = { ...entry(5, { id: null, pending: true, saved: false, label: 'not yet saved' }), proposed: [], resolved: [], before: [] }
    const calls = serve({ 'GET /journal': (_b, url) => PAGE(url.includes('detail=true') ? [pending] : [{ ...pending, resolved: undefined }]) })
    render(<HistoryPanel configurationId={7} />)
    fireEvent.click(await screen.findByText('Detail'))
    await screen.findByTestId('entry-detail')
    expect(calls.some(([k]) => k.includes('revision_from=5') && k.includes('detail=true'))).toBe(true)
  })

  it('undoes a batch only after a confirmation, as a new entry, and reloads', async () => {
    let listed = 0
    const calls = serve({
      'GET /journal': () => { listed += 1; return PAGE([entry(3)]) },
      'POST /configurations/1/restore': () => reply(200, { configuration_id: 1, changed: true, revision: 4, entry_id: 40, ops: 1, config_hash: null }),
    })
    const onChanged = vi.fn()
    render(<HistoryPanel configurationId={1} onChanged={onChanged} />)
    fireEvent.click(await screen.findByText('Undo batch'))
    expect(calls.some(([k]) => k.startsWith('POST'))).toBe(false)
    fireEvent.click(screen.getByText('Confirm undo'))
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('revision 4'))
    expect(calls.find(([k]) => k.startsWith('POST'))![1]).toEqual({ undo_batch: 30, note: '' })
    expect(onChanged).toHaveBeenCalled()
    expect(listed).toBe(2)
  })

  it('undoes a group by its group id', async () => {
    const calls = serve({
      'GET /journal': () => PAGE([entry(3, { group_id: 'g-1' })]),
      'POST /configurations/1/restore': () => reply(200, { configuration_id: 1, changed: false, revision: 3, entry_id: null, ops: 0, config_hash: null }),
    })
    render(<HistoryPanel configurationId={1} />)
    fireEvent.click(await screen.findByText('Undo group'))
    fireEvent.click(screen.getByText('Confirm undo'))
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Nothing to undo'))
    expect(calls.find(([k]) => k.startsWith('POST'))![1]).toEqual({ undo_group: 'g-1', note: '' })
  })

  it('says why an undo was refused', async () => {
    serve({
      'GET /journal': () => PAGE([entry(3)]),
      'POST /configurations/1/restore': () => reply(409, { detail: 'the inverse does not apply' }),
    })
    render(<HistoryPanel configurationId={1} />)
    fireEvent.click(await screen.findByText('Undo batch'))
    fireEvent.click(screen.getByText('Confirm undo'))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Could not undo the batch')
    expect(alert.textContent).toContain('the inverse does not apply')
  })

  it('passes the filters to the server and reports a failed load', async () => {
    const calls = serve({ 'GET /journal': () => PAGE([]) })
    render(<HistoryPanel configurationId={1} />)
    await screen.findByText('No entries match.')
    fireEvent.change(screen.getByLabelText('Actor'), { target: { value: 'carol' } })
    await waitFor(() => expect(calls.some(([k]) => k.includes('actor=carol'))).toBe(true))
    vi.unstubAllGlobals()
    serve({ 'GET /journal': () => reply(500, { detail: 'boom' }) })
    render(<HistoryPanel configurationId={2} />)
    expect((await screen.findAllByRole('alert'))[0].textContent).toContain('Could not load the History')
  })
})
