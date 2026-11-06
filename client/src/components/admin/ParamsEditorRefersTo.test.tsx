// A parameter says what its names refer to (`engine_params.refers_to`), so a change that
// renames or removes a node, a codelet type or an urgency level updates the parameter with it.

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { ParamsEditor } from './ParamsEditor'

const PARAMS = [
  { name: 'top_down_slipnodes', value: '["a"]', value_type: 'json', refers_to: 'trigger_node_list' },
  { name: 'max_activation', value: '100', value_type: 'int', refers_to: null },
]

function serve() {
  const calls: { url: string; method: string; body?: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({ url: String(url), method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const body = JSON.stringify(method === 'GET' ? PARAMS : PARAMS[0])
    return { ok: true, status: 200, statusText: '', text: async () => body, json: async () => JSON.parse(body) } as unknown as Response
  }))
  return calls
}

afterEach(() => vi.unstubAllGlobals())

describe('ParamsEditor — what a parameter refers to', () => {
  it('shows the column and saves a picked value', async () => {
    const calls = serve()
    render(<ParamsEditor />)

    expect(await screen.findByText('trigger_node_list')).toBeTruthy()
    expect(screen.getByText('Refers to')).toBeTruthy()

    fireEvent.doubleClick(screen.getAllByText('100')[0])
    expect(screen.queryByLabelText('Refers to')).toBeNull()

    fireEvent.doubleClick(screen.getByText('trigger_node_list'))
    const pick = (await screen.findByLabelText('Refers to')) as HTMLSelectElement
    expect([...pick.options].map(o => o.value)).toEqual([
      '', 'node_list', 'trigger_node_list', 'node_map', 'codelet_type_list', 'urgency_level',
      'clampable_pattern_map', 'clampable_pattern_list',
    ])
    fireEvent.change(pick, { target: { value: 'node_list' } })

    await waitFor(() => expect(calls.some(c => c.method === 'PUT')).toBe(true))
    const put = calls.find(c => c.method === 'PUT')!
    expect(put.url).toBe('/api/admin/params/top_down_slipnodes')
    expect(put.body).toEqual({ value: '["a"]', value_type: 'json', refers_to: 'node_list' })
  })
})
