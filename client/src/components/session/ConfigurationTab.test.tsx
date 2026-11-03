// ---------------------------------------------------------------------------
// Petacat -- Tests for the Training Mode Session's Configuration tab
// ---------------------------------------------------------------------------
//
// What these defend: the version slider changes the Slipnet graph; a node with no layout row is
// shown; the timeline filters by source and marks unsaved entries; the diff of two versions is
// listed; the row browser reads a table at the chosen version; every read says Live (in memory) or
// Stored (as of last stop); the tab is read-only and links to the configuration manager; and a
// refusal is shown in place of a blank view.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

import { ConfigurationTab } from './ConfigurationTab'
import type { SessionSummary } from '@/types'

type Handler = (url: string) => unknown

let calls: string[]
let handler: Handler

function reply(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

const SAVED = { stopped_at: '2026-11-01T10:00:00', configuration_revision: 2, episode_version: 5 }

function label(over: Record<string, unknown> = {}) {
  return {
    session_id: 1,
    state: 'running',
    source: 'live',
    saved_through: SAVED,
    unsaved: { runs: 3, merges: 3, problems: 0, outcomes: 0, edits: 0, configuration_batches: 1 },
    ...over,
  }
}

const NODES = [
  { name: 'a', short_name: 'A', conceptual_depth: 10 },
  { name: 'b', short_name: 'B', conceptual_depth: 20 },
]
const LINK = { from_node: 'a', to_node: 'b', link_type: 'lateral', label_node: null, link_length: 60, fixed_length: false }

function entry(revision: number, source: string, over: Record<string, unknown> = {}) {
  return {
    id: revision, revision, source, actor: source, channel: 'api', note: '', causing_run_id: null,
    group_id: null, occurred_at: '2026-11-01T10:00:00', config_hash: 'h', pending: false, label: '',
    counts: { insert: 1, update: 0, delete: 0 }, tables: ['slipnet_node_defs'], ...over,
  }
}

function session(over: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: 1, name: 'Pilot', state: 'running', source: 'live', saved_through: SAVED,
    unsaved: { runs: 3, merges: 3, problems: 0, outcomes: 0, edits: 0, configuration_batches: 1 },
    ...over,
  } as SessionSummary
}

function defaultHandler(url: string): unknown {
  const u = new URL(url, 'http://x')
  const path = u.pathname.replace('/api/training-mode/sessions/1', '')
  const version = u.searchParams.get('version')
  if (path === '/configuration' && !u.searchParams.get('table')) {
    return reply({ ...label(), configuration_id: 9, version: 3, config_hash: 'abcdef0123456789', tables: { slipnet_node_defs: 2, slipnet_layout: 1 } })
  }
  if (path === '/configuration') {
    const nodes = version === '1' ? NODES.slice(0, 1) : NODES
    return reply({
      ...label(), configuration_id: 9, version: Number(version ?? 3), config_hash: 'h', table: 'slipnet_node_defs',
      key_columns: ['name'], count: nodes.length, rows: nodes,
    })
  }
  if (path === '/slipnet') {
    const v = Number(version ?? 3)
    const nodes = v < 2 ? NODES.slice(0, 1) : v === 2 ? NODES : [...NODES, { name: 'new-concept', short_name: 'NEW', conceptual_depth: 40 }]
    return reply({
      ...label(), configuration_id: 9, version: v, config_hash: 'h', nodes,
      links: v >= 2 ? [LINK] : [], layout: [{ node_name: 'a', grid_row: 0, grid_col: 0 }, { node_name: 'b', grid_row: 0, grid_col: 1 }],
      unplaced: nodes.map((n) => n.name).filter((n) => n !== 'a' && n !== 'b'),
    })
  }
  if (path === '/journal') {
    const source = u.searchParams.get('source')
    const all = [
      entry(3, 'learner', { pending: true, label: 'not yet saved', note: 'learned a node' }),
      entry(2, 'admin'),
      entry(1, 'external'),
    ]
    const entries = source ? all.filter((e) => e.source === source) : all
    return reply({ ...label(), entries, total: entries.length, limit: 200, offset: 0 })
  }
  if (path === '/configuration/diff') {
    return reply({
      ...label(), configuration_id: 9, from: Number(u.searchParams.get('from')), to: Number(u.searchParams.get('to')),
      same: false, count: 2, added: 1, removed: 0, changed: 1,
      rows: [
        { table: 'slipnet_node_defs', key: { name: 'new-concept' }, change: 'added', from: null, to: { name: 'new-concept' }, columns: [] },
        { table: 'engine_params', key: { name: 'p' }, change: 'changed', from: { value: '1' }, to: { value: '2' }, columns: ['value'] },
      ],
    })
  }
  return reply({ detail: `nothing serves ${url}` }, 404)
}

beforeEach(() => {
  calls = []
  handler = defaultHandler
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(url)
    return handler(url)
  }))
})
afterEach(() => vi.unstubAllGlobals())

const graphNodes = () => document.querySelectorAll('.graph-node').length

describe('ConfigurationTab: the version slider and the graph', () => {
  it('shows the current version, labelled Live (in memory), with the graph at that version', async () => {
    render(<ConfigurationTab session={session()} />)
    expect(await screen.findByTestId('config-version-readout')).toHaveTextContent('Version 3 of 3 (current)')
    expect(screen.getByTestId('config-read-label')).toHaveTextContent('Live (in memory)')
    expect(screen.getByTestId('config-read-label')).toHaveTextContent('saved through version 2')
    await waitFor(() => expect(graphNodes()).toBe(3))
  })

  it('moving the slider to an earlier version redraws the graph from that version', async () => {
    render(<ConfigurationTab session={session()} />)
    await waitFor(() => expect(graphNodes()).toBe(3))
    fireEvent.change(screen.getByLabelText('Configuration version'), { target: { value: '1' } })
    await waitFor(() => expect(graphNodes()).toBe(1))
    expect(screen.getByTestId('config-version-readout')).toHaveTextContent('Version 1 of 3')
    expect(calls.some((c) => c.includes('/slipnet?version=1'))).toBe(true)
    // Back at the end the current version is followed again.
    fireEvent.click(screen.getByRole('button', { name: 'Show current version' }))
    await waitFor(() => expect(graphNodes()).toBe(3))
  })

  it('shows the nodes the layout does not place', async () => {
    render(<ConfigurationTab session={session()} />)
    expect(await screen.findByTestId('unplaced-nodes')).toHaveTextContent('new-concept')
    fireEvent.change(screen.getByLabelText('Configuration version'), { target: { value: '2' } })
    await waitFor(() => expect(screen.queryByTestId('unplaced-nodes')).not.toBeInTheDocument())
  })

  it('labels a stopped session Stored (as of last stop) and says version 0 is the Starting Conceptual State', async () => {
    handler = (url) => {
      const r = defaultHandler(url) as { json: () => Promise<Record<string, unknown>> }
      return { ...r, json: async () => ({ ...(await r.json()), ...label({ state: 'stopped', source: 'stored', unsaved: null }) }) }
    }
    render(<ConfigurationTab session={session({ state: 'stopped', source: 'stored', unsaved: null })} />)
    expect(await screen.findByTestId('config-read-label')).toHaveTextContent('Stored (as of last stop)')
    fireEvent.change(screen.getByLabelText('Configuration version'), { target: { value: '0' } })
    expect(await screen.findByText(/Version 0 is the Starting Conceptual State/)).toBeInTheDocument()
  })

  it('links to the configuration manager and offers no editing here', async () => {
    render(<ConfigurationTab session={session()} />)
    const link = await screen.findByTestId('edit-configuration-link')
    await waitFor(() => expect(link).toHaveAttribute('href', '#/admin?configuration=9'))
    expect(screen.queryByRole('button', { name: /^(Save|Add|Delete|Edit)/ })).not.toBeInTheDocument()
  })

  it('shows a refusal in place of a blank graph', async () => {
    handler = (url) => (url.includes('/slipnet') ? reply({ detail: 'version 1 is held in memory only' }, 409) : defaultHandler(url))
    render(<ConfigurationTab session={session()} />)
    expect(await screen.findByText(/held in memory only/)).toBeInTheDocument()
    expect(graphNodes()).toBe(0)
  })
})

describe('ConfigurationTab: the timeline', () => {
  async function openTimeline() {
    render(<ConfigurationTab session={session()} />)
    await screen.findByTestId('config-version-readout')
    fireEvent.click(screen.getByRole('tab', { name: 'Timeline' }))
    await screen.findByTestId('configuration-timeline')
  }

  it('lists the entries newest first and marks an unsaved one', async () => {
    await openTimeline()
    await waitFor(() => expect(screen.getAllByTestId('timeline-row')).toHaveLength(3))
    const rows = screen.getAllByTestId('timeline-row')
    expect(rows[0]).toHaveTextContent('learner')
    expect(within(rows[0]).getByTestId('pending-label')).toHaveTextContent('not yet saved')
    expect(rows[2]).toHaveTextContent('external')
  })

  it('filters by source through the route', async () => {
    await openTimeline()
    await waitFor(() => expect(screen.getAllByTestId('timeline-row')).toHaveLength(3))
    fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'admin' } })
    await waitFor(() => expect(screen.getAllByTestId('timeline-row')).toHaveLength(1))
    expect(screen.getByTestId('timeline-row')).toHaveTextContent('admin')
    expect(calls.some((c) => c.includes('/journal?source=admin'))).toBe(true)
  })

  it('Show moves the slider to that version and opens the graph', async () => {
    await openTimeline()
    await waitFor(() => expect(screen.getAllByTestId('timeline-row')).toHaveLength(3))
    fireEvent.click(screen.getByRole('button', { name: 'Show version 1' }))
    expect(await screen.findByTestId('config-version-readout')).toHaveTextContent('Version 1 of 3')
    await waitFor(() => expect(graphNodes()).toBe(1))
  })
})

describe('ConfigurationTab: compare versions', () => {
  it('lists the rows added, removed and changed between two versions', async () => {
    render(<ConfigurationTab session={session()} />)
    await screen.findByTestId('config-version-readout')
    fireEvent.click(screen.getByRole('tab', { name: 'Compare versions' }))
    fireEvent.change(screen.getByLabelText('From version'), { target: { value: '1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Show differences' }))
    expect(await screen.findByTestId('diff-summary')).toHaveTextContent('Version 1 to version 3: 1 rows added, 0 removed, 1 changed.')
    const rows = screen.getAllByTestId('diff-row')
    expect(rows[0]).toHaveTextContent('slipnet_node_defs')
    expect(rows[0]).toHaveTextContent('name=new-concept')
    expect(rows[1]).toHaveTextContent('value: 1 → 2')
    expect(calls.some((c) => c.includes('/configuration/diff?from=1&to=3'))).toBe(true)
  })
})

describe('ConfigurationTab: the table rows', () => {
  it('reads one table at the chosen version and says where it came from', async () => {
    render(<ConfigurationTab session={session()} />)
    await screen.findByTestId('config-version-readout')
    fireEvent.change(screen.getByLabelText('Configuration version'), { target: { value: '1' } })
    fireEvent.click(screen.getByRole('tab', { name: 'Table rows' }))
    await waitFor(() => expect(screen.getAllByTestId('config-row')).toHaveLength(1))
    expect(screen.getByTestId('rows-count')).toHaveTextContent('1 rows; identified by name.')
    expect(screen.getByTestId('rows-read-label')).toHaveTextContent('Live (in memory)')
    expect(calls.some((c) => c.includes('/configuration?version=1&table=slipnet_node_defs'))).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Show current version' }))
    await waitFor(() => expect(screen.getAllByTestId('config-row')).toHaveLength(2))
  })
})
