// ---------------------------------------------------------------------------
// Petacat — the Admin enum editor over the engine's vocabulary
// ---------------------------------------------------------------------------
//
// The column that binds a row to the engine's vocabulary is a pick from the engine's list
// for the table, a note beside it says the client's display follows the binding, a refusal
// to delete a bound row reaches the person in the server's words, and a rename is one
// request that the server carries out on every column that names the row.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { EnumEditor } from './EnumEditor'

function reply(status: number, body: unknown) {
  const text = JSON.stringify(body)
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    text: async () => text,
    json: async () => JSON.parse(text),
  } as unknown as Response
}

const ROLES = ['bridge_type.top', 'bridge_type.bottom', 'bridge_type.vertical']

const TABLES = {
  tables: ['bridge_types', 'run_statuses'],
  roles: { bridge_types: { column: 'role', roles: ROLES, unique: true } },
  columns: {
    bridge_types: [{ name: 'role', type: 'text', nullable: true, pick: ROLES, references: null }],
    run_statuses: [],
  },
}

const ROWS = [
  { name: 'top', display_label: 'Top', sort_order: 0, description: '', role: 'bridge_type.top' },
  { name: 'spare', display_label: 'Spare', sort_order: 3, description: '', role: null },
]

type Call = { url: string; method: string; body?: string }

function serve(handler: (call: Call) => Response) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const call = { url: String(url), method: init?.method ?? 'GET', body: init?.body as string | undefined }
    calls.push(call)
    return handler(call)
  }))
  return calls
}

afterEach(() => vi.unstubAllGlobals())

describe('the enum editor and the engine vocabulary', () => {
  it('shows the role column as a pick from the engine list for the table, with a note', async () => {
    serve(({ url }) => (url === '/api/admin/enums' ? reply(200, TABLES) : reply(200, ROWS)))
    render(<EnumEditor />)

    expect(await screen.findByText(/2 values in bridge_types/)).toBeTruthy()
    expect(screen.getByText('Role')).toBeTruthy()
    const note = screen.getByTestId('role-note')
    expect(note.textContent).toContain('bridge_type.top, bridge_type.bottom, bridge_type.vertical')
    expect(note.textContent).toContain('client’s display follows the binding')

    // editing the role offers exactly the engine's names and "none"
    const cell = screen.getByText('bridge_type.top')
    fireEvent.doubleClick(cell)
    const pick = (await screen.findByLabelText('Role')) as HTMLSelectElement
    expect([...pick.options].map(o => o.value)).toEqual(['', ...ROLES])
  })

  it('has no role note for a table the engine names no row of', async () => {
    serve(({ url }) => (url === '/api/admin/enums' ? reply(200, { ...TABLES, tables: ['run_statuses'] }) : reply(200, [])))
    render(<EnumEditor />)
    expect(await screen.findByText(/0 values in run_statuses/)).toBeTruthy()
    expect(screen.queryByTestId('role-note')).toBeNull()
  })

  it('saves a picked role and unbinds with the empty choice', async () => {
    const calls = serve(({ url, method }) => {
      if (url === '/api/admin/enums') return reply(200, TABLES)
      if (method === 'PUT') return reply(200, ROWS[1])
      return reply(200, ROWS)
    })
    render(<EnumEditor />)
    await screen.findByText(/2 values in bridge_types/)

    fireEvent.doubleClick(screen.getByText('bridge_type.top'))
    fireEvent.change(await screen.findByLabelText('Role'), { target: { value: '' } })

    await waitFor(() => expect(calls.some(c => c.method === 'PUT')).toBe(true))
    const put = calls.find(c => c.method === 'PUT')!
    expect(put.url).toBe('/api/admin/enums/bridge_types/top')
    expect(JSON.parse(put.body!)).toMatchObject({ role: null, display_label: 'Top' })
  })

  it('names the reason a bound row was not deleted', async () => {
    serve(({ url, method }) => {
      if (url === '/api/admin/enums') return reply(200, TABLES)
      if (method === 'DELETE') {
        return reply(422, { detail: "role_bound: bridge_types row 'top' holds the role 'bridge_type.top': unbind it first" })
      }
      return reply(200, ROWS)
    })
    render(<EnumEditor />)
    await screen.findByText(/2 values in bridge_types/)

    fireEvent.click(screen.getAllByTitle('Delete')[0])
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('role_bound')
    expect(alert.textContent).toContain('unbind it first')
    expect(screen.getByText('bridge_type.top')).toBeTruthy()
  })

  it('renames a value with one request', async () => {
    const calls = serve(({ url, method }) => {
      if (url === '/api/admin/enums') return reply(200, TABLES)
      if (method === 'POST') return reply(200, { renamed: 'tp', table: 'bridge_types', report: { dangling: [{}, {}] } })
      return reply(200, ROWS)
    })
    render(<EnumEditor />)
    await screen.findByText(/2 values in bridge_types/)

    fireEvent.change(screen.getByLabelText('Value to rename'), { target: { value: 'top' } })
    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'tp' } })
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))

    const status = await screen.findByRole('status')
    expect(status.textContent).toContain('2 place(s)')
    const post = calls.find(c => c.method === 'POST')!
    expect(post.url).toBe('/api/admin/enums/bridge_types/top/rename')
    expect(JSON.parse(post.body!)).toEqual({ new_name: 'tp' })
  })
})
