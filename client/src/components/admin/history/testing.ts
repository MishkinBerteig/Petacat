// Helpers for the History component tests: a fetch stub that records `METHOD path` and the body.
import { vi } from 'vitest'

export function reply(status: number, body: unknown) {
  const text = JSON.stringify(body)
  return {
    ok: status >= 200 && status < 300, status, statusText: '',
    text: async () => text, json: async () => JSON.parse(text),
  } as unknown as Response
}

export function serve(routes: Record<string, (body: unknown, url: string) => Response>) {
  const calls: Array<[string, unknown]> = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const full = String(url).replace('/api', '')
    const key = `${init?.method ?? 'GET'} ${full.split('?')[0]}`
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push([`${init?.method ?? 'GET'} ${full}`, body])
    const handler = routes[key]
    return handler ? handler(body, full) : reply(404, { detail: `no stub for ${key}` })
  }))
  return calls
}

export function entry(revision: number, over: Record<string, unknown> = {}) {
  return {
    id: revision * 10, configuration_id: 1, revision, group_id: null, source: 'admin', actor: 'tester',
    channel: 'admin_editor', note: '', causing_run_id: null, episode_version: null, config_hash: null,
    occurred_at: '2026-11-02T10:00:00Z', recorded_at: '2026-11-02T10:00:00Z',
    counts: { insert: 1, update: 0, delete: 0 }, tables: ['slipnet_node_defs'],
    pending: false, saved: true, label: '', ...over,
  }
}
