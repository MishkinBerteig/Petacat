// ---------------------------------------------------------------------------
// Petacat — the Configuration screen reports what the server refused
// ---------------------------------------------------------------------------
//
// A configuration screen edits the program's domain knowledge, so a request the server
// turns down has to reach the person who made it, in words that say what failed and what
// kind of problem it is. These tests hold three properties of that reporting: a refused
// export leaves no file behind, a list that fails to load shows the reason in place of
// its rows, and two kinds of refusal read differently.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { AdminLayout } from './AdminLayout'
import { EnumEditor } from './EnumEditor'
import { FormulaCoefficientEditor } from './FormulaCoefficientEditor'
import { SlipnetEditor } from './SlipnetEditor'

const STATUS_TEXT: Record<number, string> = {
  200: 'OK',
  201: 'Created',
  400: 'Bad Request',
  404: 'Not Found',
  409: 'Conflict',
  422: 'Unprocessable Entity',
  500: 'Internal Server Error',
  503: 'Service Unavailable',
}

/** A reply in the shape `fetch` hands back: a status, and a body in both forms. */
function reply(status: number, body: unknown) {
  const text = typeof body === 'string' ? body : JSON.stringify(body)
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: STATUS_TEXT[status] ?? '',
    text: async () => text,
    json: async () => JSON.parse(text),
  } as unknown as Response
}

type Handler = (url: string, init?: RequestInit) => Response

/** Answer every request from one handler, and record what was asked. */
function serve(handler: Handler) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) =>
    handler(String(url), init),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** Every file the page asked the browser to save. */
let downloads: string[] = []
let blobUrls = 0

beforeEach(() => {
  downloads = []
  blobUrls = 0
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    downloads.push(this.download)
  })
  URL.createObjectURL = vi.fn(() => {
    blobUrls += 1
    return 'blob:petacat'
  })
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

/**
 * A file the way the file input yields one: a `File` that answers `text()`, which is how
 * the page reads what was chosen.
 */
function chosenFile(name: string, contents: string, type: string): File {
  const file = new File([contents], name, { type })
  Object.defineProperty(file, 'text', { value: async () => contents })
  return file
}

/** Double-click a cell, type, and blur — the table's edit gesture. */
async function editCell(text: string | RegExp, value: string) {
  const cell = await screen.findByText(text)
  fireEvent.doubleClick(cell)
  const input = await waitFor(() => {
    const el = cell.closest('td')?.querySelector('input')
    if (!el) throw new Error('no edit input appeared')
    return el
  })
  fireEvent.change(input, { target: { value } })
  fireEvent.blur(input)
}

// --- exporting a configuration ----------------------------------------------

describe('AdminLayout — exporting the configuration', () => {
  it('writes no file when the export is refused, and says why', async () => {
    serve((url) => {
      if (url === '/api/admin/export') {
        return reply(500, { detail: 'export failed: no database connection' })
      }
      return reply(200, [])
    })
    render(<AdminLayout />)

    fireEvent.click(await screen.findByRole('button', { name: /^Export$/ }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Could not export the configuration')
    // The status says what kind of problem it is; the detail says which one.
    expect(alert.textContent).toContain('the server failed to complete it')
    expect(alert.textContent).toContain('no database connection')

    // Nothing reached the disk, so no corrupt backup exists to be trusted later.
    expect(downloads).toEqual([])
    expect(blobUrls).toBe(0)
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('writes no file when the server is unreachable, and says so', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url) === '/api/admin/export') throw new TypeError('Failed to fetch')
      return reply(200, [])
    }))
    render(<AdminLayout />)

    fireEvent.click(await screen.findByRole('button', { name: /^Export$/ }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Could not export the configuration')
    expect(alert.textContent).toContain('the server is unreachable')
    expect(downloads).toEqual([])
  })

  it('downloads a dated file when the server returns a configuration', async () => {
    serve((url) => {
      if (url === '/api/admin/export') return reply(200, { slipnet_nodes: [] })
      return reply(200, [])
    })
    render(<AdminLayout />)

    fireEvent.click(await screen.findByRole('button', { name: /^Export$/ }))

    await waitFor(() => expect(downloads).toHaveLength(1))
    expect(downloads[0]).toMatch(/^petacat-config-\d{4}-\d{2}-\d{2}\.json$/)
    const status = await screen.findByRole('status')
    expect(status.textContent).toContain('Exported the configuration')
  })

  it('reports a refused write to the seed files', async () => {
    serve((url) => {
      if (url === '/api/admin/export-to-seed-data') {
        return reply(503, { detail: 'seed_data is read-only' })
      }
      return reply(200, [])
    })
    render(<AdminLayout />)

    fireEvent.click(
      await screen.findByRole('button', { name: /Export Current Settings to Seed Data/ }),
    )

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Could not write the current settings to seed data')
    expect(alert.textContent).toContain('seed_data is read-only')
  })

  it('reports a refused import', async () => {
    serve((url) => {
      if (url === '/api/admin/import') {
        return reply(400, { detail: 'Import failed: unknown collection "widgets"' })
      }
      return reply(200, [])
    })
    const { container } = render(<AdminLayout />)

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    const file = chosenFile('config.json', '{"slipnet_nodes": []}', 'application/json')
    fireEvent.change(input, { target: { files: [file] } })

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Could not import the configuration')
    expect(alert.textContent).toContain('the request was rejected')
    expect(alert.textContent).toContain('unknown collection')
  })

  it('names a file that is not JSON without sending it', async () => {
    const fetchMock = serve(() => reply(200, []))
    const { container } = render(<AdminLayout />)
    await screen.findByRole('button', { name: /^Export$/ })
    const before = fetchMock.mock.calls.length

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(input, {
      target: { files: [chosenFile('notes.txt', 'not json', 'text/plain')] },
    })

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('notes.txt does not contain valid JSON')
    expect(fetchMock.mock.calls.length).toBe(before)
  })
})

// --- a list that fails to load ----------------------------------------------

describe('the configuration lists — a load that fails', () => {
  it('shows the reason instead of loading forever, and retries', async () => {
    let attempt = 0
    serve(() => {
      attempt += 1
      return attempt === 1
        ? reply(500, { detail: 'relation "formula_coefficients" does not exist' })
        : reply(200, [{ name: 'bond_weight', value: 40 }])
    })
    render(<FormulaCoefficientEditor />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Could not load the formula coefficients')
    expect(alert.textContent).toContain('does not exist')
    expect(screen.queryByText(/Loading formula coefficients/)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))

    expect(await screen.findByText(/1 formula coefficients/)).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows the reason the enum tables could not be listed', async () => {
    serve(() => reply(503, { detail: 'database is starting up' }))
    render(<EnumEditor />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Could not load the enum tables')
    expect(alert.textContent).toContain('the server failed to complete it')
    expect(screen.queryByText(/Loading enum tables/)).toBeNull()
    expect(screen.getByRole('button', { name: /^Retry$/ })).toBeTruthy()
  })

  it('keeps a refused table out of the rows and names it in the reason', async () => {
    serve((url) => {
      if (url === '/api/admin/enums') return reply(200, { tables: ['event_types'] })
      return reply(404, { detail: "Unknown enum table 'event_types'" })
    })
    render(<EnumEditor />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Could not load the values in event_types')
    expect(alert.textContent).toContain('it no longer exists')
    // The failed reply is a reason, never a row: no count is claimed for it.
    expect(screen.queryByText(/values in event_types \(double-click/)).toBeNull()
  })
})

// --- two kinds of refusal ---------------------------------------------------

describe('the configuration lists — two kinds of refusal read differently', () => {
  const node = { name: 'plato-a', short_name: 'a', conceptual_depth: 10, description: '' }

  it('names a conflict on a create', async () => {
    serve((url, init) => {
      if ((init?.method ?? 'GET') === 'GET') return reply(200, [node])
      return reply(409, { detail: "Node 'plato-a' already exists" })
    })
    render(<SlipnetEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /\+ Add/ }))
    fireEvent.change(screen.getByLabelText('Short'), { target: { value: 'a' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    const message = await screen.findByText(/Could not create the slipnet node/)
    expect(message.textContent).toContain('conflicts with something already there')
    expect(message.textContent).toContain("Node 'plato-a' already exists")
  })

  it('names the field at fault on an update', async () => {
    serve((url, init) => {
      if ((init?.method ?? 'GET') === 'GET') return reply(200, [node])
      return reply(422, {
        detail: [
          {
            loc: ['body', 'conceptual_depth'],
            msg: 'Input should be less than or equal to 100',
          },
        ],
      })
    })
    render(<SlipnetEditor />)

    await editCell('10', '400')

    const message = await screen.findByText(/Could not save the slipnet node/)
    expect(message.textContent).toContain('check the values entered')
    // The 422's field list is unwrapped, so the reader is told which field and why.
    expect(message.textContent).toContain('conceptual_depth: Input should be less than or equal to 100')
    // A conflict and a rejected value are not the same news.
    expect(message.textContent).not.toContain('conflicts with something already there')
  })
})
