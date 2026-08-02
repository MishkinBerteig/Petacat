// ---------------------------------------------------------------------------
// Petacat -- the Slipnet graph says what it could not do
// ---------------------------------------------------------------------------
//
// The graph is two things at once: a picture of the 59 concept nodes and the 202
// links between them, and the surface a reader clamps a node from. Both have a
// silent failure available to them, and both are misread the same way.
//
// A graph with no nodes in it reads as a Slipnet that has not been built. A node
// that stays where it was after a clamp reads as a clamp that took hold and did
// nothing -- the node draws the run's own activation either way. So the load names
// its reason in place of the picture, and the clamp names its reason above it.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { SlipnetGraphView } from './SlipnetGraphView'
import { useRunStore } from '@/store/runStore'

/** The parts of a Response the API client's `request` reads. */
function reply(body: unknown, status = 200, statusText = 'OK') {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

/** A refusal in the shape FastAPI sends one. */
function refusal(status: number, statusText: string, detail: string) {
  return reply({ detail }, status, statusText)
}

/** Two nodes and the link between them: enough graph to clamp something in. */
const EXPORT = {
  slipnet_nodes: [
    { name: 'plato-successor', short_name: 'succ', conceptual_depth: 50 },
    { name: 'plato-predecessor', short_name: 'pred', conceptual_depth: 50 },
  ],
  slipnet_layout: [
    { node_name: 'plato-successor', grid_row: 0, grid_col: 0 },
    { node_name: 'plato-predecessor', grid_row: 0, grid_col: 1 },
  ],
}

const LINKS = [
  {
    id: 1,
    from_node: 'plato-successor',
    to_node: 'plato-predecessor',
    link_type: 'lateral_sliplink',
    label_node: null,
    link_length: 60,
    fixed_length: false,
  },
]

type Handler = (url: string, init?: RequestInit) => Promise<unknown>

let handler: Handler

const ORIGINAL = useRunStore.getState()

beforeEach(() => {
  useRunStore.setState({ ...ORIGINAL, runId: 7 }, true)
  handler = async (url) => {
    if (url.endsWith('/api/admin/export')) return reply(EXPORT)
    if (url.endsWith('/api/admin/slipnet/links')) return reply(LINKS)
    return refusal(404, 'Not Found', `nothing serves ${url}`)
  }
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => handler(url, init)))
})

afterEach(() => {
  vi.unstubAllGlobals()
  useRunStore.setState({ ...ORIGINAL }, true)
})

/** Open the node menu the way a reader does: a right-click on the node. */
async function openNodeMenu(): Promise<void> {
  await waitFor(() => expect(document.querySelector('.graph-node')).toBeTruthy())
  fireEvent.contextMenu(document.querySelector('.graph-node')!)
}

describe('SlipnetGraphView — a graph that would not load', () => {
  it('gives the reason in place of an empty picture', async () => {
    handler = async () =>
      refusal(500, 'Internal Server Error', 'the slipnet_layout table is empty')

    render(<SlipnetGraphView />)

    await waitFor(() =>
      expect(
        screen.getByText(/Could not load the Slipnet graph: the server failed to complete it/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/the slipnet_layout table is empty/)).toBeTruthy()
    // A blank canvas would be the alternative reading, so there is no canvas.
    expect(document.querySelector('svg')).toBeNull()
  })

  it('names an unreachable server as unreachable', async () => {
    handler = async () => {
      throw new TypeError('Failed to fetch')
    }

    render(<SlipnetGraphView />)

    await waitFor(() =>
      expect(
        screen.getByText(/Could not load the Slipnet graph: the server is unreachable/),
      ).toBeTruthy(),
    )
  })

  it('draws the graph when the nodes and links arrive', async () => {
    render(<SlipnetGraphView />)

    await waitFor(() => expect(screen.getByText('succ')).toBeTruthy())
    expect(screen.getByText('pred')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('SlipnetGraphView — a clamp the server refuses', () => {
  it('names the action and the reason', async () => {
    render(<SlipnetGraphView />)
    await openNodeMenu()

    handler = async (url) => {
      if (url.includes('/clamp-node')) {
        return refusal(409, 'Conflict', 'plato-successor is already clamped')
      }
      return refusal(404, 'Not Found', url)
    }
    fireEvent.click(screen.getByRole('button', { name: 'Clamp to 100' }))

    await waitFor(() =>
      expect(
        screen.getByText(
          /Could not clamp the Slipnet node: that conflicts with something already there/,
        ),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/plato-successor is already clamped/)).toBeTruthy()
  })

  it('leaves nothing said when the clamp is accepted', async () => {
    render(<SlipnetGraphView />)
    await openNodeMenu()

    const asked: string[] = []
    handler = async (url) => {
      asked.push(url)
      return reply(null, 204, 'No Content')
    }
    fireEvent.click(screen.getByRole('button', { name: 'Clamp to 100' }))

    await waitFor(() => expect(asked).toHaveLength(1))
    expect(asked[0]).toBe('/api/runs/7/clamp-node')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('says why a clamp was not released', async () => {
    // A node the run reports as frozen offers Unclamp instead of Clamp.
    useRunStore.setState({
      slipnet: {
        'plato-successor': { activation: 100, frozen: true },
        'plato-predecessor': { activation: 0, frozen: false },
      } as never,
    })

    render(<SlipnetGraphView />)
    await openNodeMenu()

    handler = async () => refusal(404, 'Not Found', 'plato-successor is not clamped')
    fireEvent.click(screen.getByRole('button', { name: 'Unclamp' }))

    await waitFor(() =>
      expect(
        screen.getByText(/Could not release the Slipnet node clamp: it no longer exists/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/plato-successor is not clamped/)).toBeTruthy()
  })

  it('offers no clamp at all over a recorded Slipnet', async () => {
    render(<SlipnetGraphView slipnet={null} readOnly />)
    await openNodeMenu()

    expect(screen.queryByRole('button', { name: 'Clamp to 100' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Unclamp' })).toBeNull()
  })
})
