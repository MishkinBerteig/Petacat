// ---------------------------------------------------------------------------
// Petacat — the Link Types tab edits link types like any other configuration table
// ---------------------------------------------------------------------------
//
// A link type is a configuration table (not an enum table): a configuration may hold link
// types of its own. The tab reads `/admin/link-types`, offers the engine's behaviours as the
// pick list for the Behaviour column, and writes through the table's own routes.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { LinkTypeEditor } from './LinkTypeEditor'

interface Call { url: string; method: string; body: any }
let calls: Call[] = []

const TYPES = [
  { name: 'lateral', display_label: 'Lateral', sort_order: 3, description: 'peers', behaviour: 'lateral' },
  { name: 'near', display_label: 'Near', sort_order: 5, description: 'a plain link type', behaviour: null },
]
const ENUMS = {
  tables: ['bridge_types'],
  roles: { link_types: { column: 'behaviour', roles: ['category', 'instance', 'property', 'lateral', 'slip'], unique: false } },
}

function serve() {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit): Promise<unknown> => {
    const method = init?.method ?? 'GET'
    if (method !== 'GET') {
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })
      return { ok: true, json: async (): Promise<unknown> => TYPES[1], text: async (): Promise<string> => '' }
    }
    const body = url.includes('/admin/enums') ? ENUMS : TYPES
    return { ok: true, json: async (): Promise<unknown> => body, text: async (): Promise<string> => '' }
  }))
}

afterEach(() => { vi.unstubAllGlobals() })

describe('LinkTypeEditor', () => {
  it('lists the types, says what behaviour means, and names the engine behaviours', async () => {
    serve()
    render(<LinkTypeEditor />)
    expect(await screen.findByText('near')).toBeTruthy()
    expect(screen.getByText('2 link types (double-click to edit)')).toBeTruthy()
    const note = screen.getByTestId('link-type-note').textContent ?? ''
    expect(note).toContain('category, instance, property, lateral, slip')
    expect(note).toContain('plain')
    expect(note).toContain('fixed length')
  })

  it('saves a changed description with the link-type route', async () => {
    serve()
    render(<LinkTypeEditor />)
    const cell = await screen.findByText('a plain link type')
    fireEvent.doubleClick(cell)
    const input = await waitFor(() => {
      const el = cell.closest('td')?.querySelector('input')
      if (!el) throw new Error('no edit input appeared')
      return el
    })
    fireEvent.change(input, { target: { value: 'changed' } })
    fireEvent.blur(input)
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].method).toBe('PUT')
    expect(calls[0].url).toContain('/admin/link-types/near')
    expect(calls[0].body.description).toBe('changed')
  })
})
