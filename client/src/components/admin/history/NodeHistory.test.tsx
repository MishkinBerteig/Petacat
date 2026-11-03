// ---------------------------------------------------------------------------
// Petacat -- node History (story, restore with dependents) and the deletion preview
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { DeletionPreview } from './DeletionPreview'
import { NodeHistory } from './NodeHistory'
import { entry, reply, serve } from './testing'

afterEach(() => { vi.unstubAllGlobals() })

const event = (e: string, text: string, revision: number) => ({
  event: e, kind: 'node', table: 'slipnet_node_defs', text, entry_id: revision * 10, revision,
  source: 'admin', actor: 'erin', channel: '', note: '', group_id: null, occurred_at: '2026-11-02T10:00:00Z',
})

const DELETED = {
  name: 'plato-x', configuration_id: 1, resolves: false, kind: null, current_name: null,
  events: [event('created', "the node 'plato-x' was created", 2), event('deleted', "the node 'plato-x' was deleted", 5)],
  restorable: { table: 'slipnet_node_defs', key: { name: 'plato-x' }, as_of_revision: 4, entry_id: 50 },
  text: "the node 'plato-x' was deleted at revision 5 by source admin, actor erin",
}

describe('NodeHistory', () => {
  it('tells a deleted node\'s story and restores it with its dependents as a new entry', async () => {
    let restored = false
    const calls = serve({
      'GET /journal/where-did-name-go': () => reply(200, restored ? { ...DELETED, resolves: true, restorable: null, current_name: 'plato-x' } : DELETED),
      'GET /journal': () => reply(200, { entries: [entry(5, { counts: { insert: 0, update: 0, delete: 3 } }), entry(2)], total: 2, limit: 200, offset: 0, live: null }),
      'POST /configurations/1/restore': () => { restored = true; return reply(200, { configuration_id: 1, changed: true, revision: 6, entry_id: 60, ops: 3, config_hash: null }) },
    })
    render(<NodeHistory configurationId={1} initialName="plato-x" />)
    const story = await screen.findByTestId('node-story')
    expect(screen.getAllByTestId('story-event')).toHaveLength(2)
    expect(story.textContent).toContain('was deleted at revision 5')
    expect(screen.getAllByTestId('node-entry')).toHaveLength(2)
    expect(calls.some(([k]) => k.includes('table=slipnet_node_defs') && k.includes('plato-x'))).toBe(true)

    fireEvent.click(screen.getByText(/Restore .plato-x. with its dependents/))
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('revision 6'))
    expect(calls.find(([k]) => k.startsWith('POST'))![1]).toEqual({
      entity: { table: 'slipnet_node_defs', key: { name: 'plato-x' } }, as_of_revision: 4, note: '',
    })
    // the story is read again: the node resolves now and offers the deletion preview instead
    await screen.findByTestId('deletion-preview')
  })

  it('can undo the whole batch that removed the node', async () => {
    const calls = serve({
      'GET /journal/where-did-name-go': () => reply(200, DELETED),
      'GET /journal': () => reply(200, { entries: [], total: 0, limit: 200, offset: 0, live: null }),
      'POST /configurations/1/restore': () => reply(200, { configuration_id: 1, changed: true, revision: 6, entry_id: 60, ops: 3, config_hash: null }),
    })
    render(<NodeHistory initialName="plato-x" />)
    fireEvent.click(await screen.findByText('Undo the batch that removed it'))
    await waitFor(() => expect(calls.some(([k]) => k.startsWith('POST'))).toBe(true))
    expect(calls.find(([k]) => k.startsWith('POST'))![1]).toEqual({ undo_batch: 50, note: '' })
  })

  it('says so when the journal has no record of the name, and reports a failure', async () => {
    serve({
      'GET /journal/where-did-name-go': () => reply(200, { ...DELETED, events: [], restorable: null, text: "'zz' is not in the configuration and the journal has no record of it" }),
      'GET /journal': () => reply(200, { entries: [], total: 0, limit: 200, offset: 0, live: null }),
    })
    render(<NodeHistory initialName="zz" />)
    expect((await screen.findByTestId('node-story')).textContent).toContain('no record of it')
    vi.unstubAllGlobals()
    serve({ 'GET /journal/where-did-name-go': () => reply(404, { detail: 'configuration 9 does not exist' }), 'GET /journal': () => reply(404, {}) })
    render(<NodeHistory configurationId={9} initialName="plato-q" />)
    expect((await screen.findAllByRole('alert'))[0].textContent).toContain('Could not load the History of "plato-q"')
  })
})

describe('DeletionPreview', () => {
  const REPORT = {
    ok: true, persisted: false,
    cascaded: [{ table: 'slipnet_link_defs', key: { from_node: 'plato-x', to_node: 'plato-y' }, op: 'delete', reason: 'link of the removed node' }],
    dangling: [{ table: 'codelet_type_defs', key: { name: 'scout' }, column: 'body', reason: "source names the removed node 'plato-x'" }],
    affected: [{ table: 'demo_problems', key: { name: 'd1' }, reason: 'uses the glyph' }],
  }

  it('lists what would cascade, dangle and be affected, writing nothing until confirmed', async () => {
    const calls = serve({
      'POST /configurations/1/changes': (body) => (body as { dry_run: boolean }).dry_run ? reply(200, REPORT) : reply(200, { ...REPORT, persisted: true }),
    })
    const onDeleted = vi.fn()
    render(<DeletionPreview configurationId={1} name="plato-x" onDeleted={onDeleted} />)
    fireEvent.click(screen.getByText(/Preview deleting/))
    expect((await screen.findByTestId('preview-cascaded')).textContent).toContain('slipnet_link_defs [plato-x / plato-y]')
    expect(screen.getByTestId('preview-dangling').textContent).toContain('column body')
    expect(screen.getByTestId('preview-affected').textContent).toContain('demo_problems [d1]')
    expect(calls).toHaveLength(1)
    expect((calls[0][1] as { dry_run: boolean; ops: unknown[] }).dry_run).toBe(true)
    expect((calls[0][1] as { ops: unknown[] }).ops).toEqual([{ op: 'remove_node', name: 'plato-x' }])

    fireEvent.click(screen.getByText(/^Delete .plato-x.$/))
    await waitFor(() => expect(onDeleted).toHaveBeenCalled())
    expect((calls[1][1] as { dry_run: boolean }).dry_run).toBe(false)
    expect(screen.getByRole('status').textContent).toContain('can be restored')
  })

  it('cancel writes nothing, and a refused preview says why', async () => {
    const calls = serve({ 'POST /configurations/1/changes': () => reply(200, REPORT) })
    render(<DeletionPreview configurationId={1} name="plato-x" />)
    fireEvent.click(screen.getByText(/Preview deleting/))
    fireEvent.click(await screen.findByText('Cancel'))
    expect(screen.queryByTestId('preview-cascaded')).toBeNull()
    expect(calls).toHaveLength(1)
    vi.unstubAllGlobals()
    serve({ 'POST /configurations/1/changes': () => reply(422, { detail: 'no such node' }) })
    fireEvent.click(screen.getByText(/Preview deleting/))
    expect((await screen.findByRole('alert')).textContent).toContain('Could not preview the deletion of "plato-x"')
  })
})
