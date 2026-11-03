// ---------------------------------------------------------------------------
// A successful editor save refreshes the difference banner and the header chip (SMKFIX)
// ---------------------------------------------------------------------------
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { AdminLayout } from './AdminLayout'

function reply(status: number, body: unknown) {
  const text = JSON.stringify(body)
  return {
    ok: status >= 200 && status < 300, status, statusText: '',
    text: async () => text, json: async () => JSON.parse(text),
  } as unknown as Response
}

const GLOBAL = {
  id: 1, name: 'Metacat Mode: global configuration', note: '', kind: 'global', mode: 'Metacat Mode',
  mode_label: 'Metacat Mode', session_id: null, session_name: null, session_state: null,
  revision: 1, config_hash: 'a', frozen: false, created_from_configuration_id: null,
  equals_standard: true, differs_from_standard_rows: 0, last_change: null, source: 'stored',
}

afterEach(() => { vi.unstubAllGlobals(); window.location.hash = '' })

describe('the banner and chip after an editor save', () => {
  it('refresh after an Engine Params save, without a tab change', async () => {
    let saved = false
    let statusReads = 0
    let summaryReads = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const path = String(url).replace('/api', '')
      if (method === 'PUT' && path.startsWith('/admin/params/')) {
        saved = true
        return reply(200, { name: 'expiration_period', value: '99', value_type: 'int' })
      }
      if (path === '/admin/params') return reply(200, [{ name: 'expiration_period', value: saved ? '99' : '10', value_type: 'int' }])
      if (/^\/configurations\/1\/status/.test(path)) {
        statusReads++
        return reply(200, { differs_rows: saved ? 1 : 0, equals_standard: !saved })
      }
      if (path === '/configurations/1') { summaryReads++; return reply(200, GLOBAL) }
      return reply(200, [])
    }))
    render(<AdminLayout />)
    fireEvent.click(screen.getByText('Engine Params'))
    const cell = await screen.findByText('10')
    expect(screen.queryByLabelText('Difference from the Metacat Standard Configuration')).toBeNull()
    const statusBefore = statusReads
    const summaryBefore = summaryReads
    fireEvent.doubleClick(cell)
    const input = await waitFor(() => {
      const el = cell.closest('td')?.querySelector('input')
      if (!el) throw new Error('no edit input')
      return el
    })
    fireEvent.change(input, { target: { value: '99' } })
    fireEvent.blur(input)
    const note = await screen.findByLabelText('Difference from the Metacat Standard Configuration')
    expect(note.textContent).toContain('differs from the Metacat Standard Configuration in 1 row.')
    expect(statusReads).toBeGreaterThan(statusBefore)
    expect(summaryReads).toBeGreaterThan(summaryBefore)
  })
})
