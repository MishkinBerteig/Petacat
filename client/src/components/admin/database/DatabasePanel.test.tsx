// ---------------------------------------------------------------------------
// Petacat — the Database tab: table classes, the row editor, expert mode and the SQL box
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

import { DatabasePanel } from './DatabasePanel'
import { describeDbError } from './errors'
import { parseValue, showValue } from './values'
import { AdminLayout } from '../AdminLayout'
import { ApiError } from '@/api/client'
import type { DbColumn, DbTable } from './types'

const col = (name: string, type = 'VARCHAR', extra: Partial<DbColumn> = {}): DbColumn => ({
  name, type, primary_key: false, nullable: false, protected: false, ...extra,
})

const TABLES: DbTable[] = [
  {
    name: 'engine_params', class: 'configuration', class_label: 'configuration',
    banner: 'Configuration. An edit here is a batch through the change API.',
    editable: true, expert_required: false, enum: false, rows: 2, key_columns: ['name'],
    columns: [col('id', 'INTEGER', { primary_key: true }), col('name'), col('value')],
  },
  {
    name: 'runs', class: 'runtime', class_label: 'runtime data',
    banner: 'Runtime data. Editing needs expert mode.',
    editable: true, expert_required: true, enum: false, rows: 1, key_columns: ['id'],
    columns: [col('id', 'INTEGER', { primary_key: true }), col('seed', 'BIGINT')],
  },
  {
    name: 'configuration_journal', class: 'journal', class_label: 'journal (read-only)',
    banner: 'The journal is read-only here.',
    editable: false, expert_required: false, enum: false, rows: 3, key_columns: ['id'],
    columns: [col('id', 'INTEGER', { primary_key: true })],
  },
  {
    name: 'training_mode_sessions', class: 'session_managed', class_label: 'session-managed (read-only)',
    banner: 'Session-managed and read-only. The rows below are not its current state.',
    editable: false, expert_required: false, enum: false, rows: 1, key_columns: ['id'],
    columns: [col('id', 'INTEGER', { primary_key: true }), col('name')],
  },
  {
    name: 'training_memory_merges', class: 'episodic_memory',
    class_label: 'session Episodic Memory (protected)',
    banner: 'Protected. Expert mode does not lift this.',
    editable: false, expert_required: false, enum: false, rows: 4, key_columns: ['id'],
    columns: [col('id', 'INTEGER', { primary_key: true }), col('seq', 'INTEGER')],
  },
]

function page(table: DbTable, rows: Array<Record<string, unknown>>) {
  return {
    table: table.name, class: table.class, class_label: table.class_label, banner: table.banner,
    configuration: 1, total: rows.length, limit: 25, offset: 0, key_columns: table.key_columns,
    columns: table.columns,
    rows: rows.map(values => ({
      values,
      key: Object.fromEntries(table.key_columns.map(k => [k, values[k]])),
    })),
  }
}

const ROWS: Record<string, Array<Record<string, unknown>>> = {
  engine_params: [{ id: 1, name: 'alpha', value: '3' }, { id: 2, name: 'beta', value: '5' }],
  runs: [{ id: 9, seed: 42 }],
  configuration_journal: [{ id: 1 }],
  training_mode_sessions: [{ id: 1, name: 'S one' }],
  training_memory_merges: [{ id: 1, seq: 1 }],
}

function reply(status: number, body: unknown) {
  const text = JSON.stringify(body)
  return {
    ok: status >= 200 && status < 300, status, statusText: '',
    text: async () => text, json: async () => JSON.parse(text),
  } as unknown as Response
}

/** Serve the database routes; `calls` records `METHOD path` with the body. */
function serve(overrides: Record<string, (body: any) => Response> = {}) {
  const calls: Array<[string, any]> = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace('/api', '')
    const key = `${init?.method ?? 'GET'} ${path.split('?')[0]}`
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push([key, body])
    if (overrides[key]) return overrides[key](body)
    if (key === 'GET /admin/db/tables') return reply(200, TABLES)
    const m = key.match(/^GET \/admin\/db\/tables\/(\w+)\/rows$/)
    if (m) {
      const t = TABLES.find(x => x.name === m[1])!
      return reply(200, page(t, ROWS[t.name]))
    }
    return reply(200, (init?.method ?? 'GET') === 'GET' ? [] : {})
  }))
  return calls
}

async function open(name: string) {
  render(<DatabasePanel />)
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(name) }))
  await screen.findByRole('note')
}

beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.unstubAllGlobals() })

describe('the table list', () => {
  it('shows every table with its class badge', async () => {
    serve()
    render(<DatabasePanel />)
    const list = await screen.findByRole('navigation', { name: 'Tables' })
    for (const t of TABLES) {
      const button = within(list).getByRole('button', { name: new RegExp(t.name) })
      expect(button.textContent).toContain(t.class_label)
    }
  })

  it('shows the class banner of the chosen table', async () => {
    serve()
    await open('training_mode_sessions')
    expect(screen.getByRole('note').textContent).toContain('not its current state')
  })
})

describe('classes that are never edited here', () => {
  it.each(['configuration_journal', 'training_mode_sessions', 'training_memory_merges'])(
    '%s offers no way to edit', async (name) => {
      serve()
      await open(name)
      await screen.findByText(/Page 1 of 1/)
      expect(screen.queryByRole('button', { name: 'New row' })).toBeNull()
      expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
      expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull()
      expect(screen.queryByLabelText('Expert mode')).toBeNull()
    })
})

describe('configuration tables', () => {
  it('builds a batch for the change API from an edited row', async () => {
    const calls = serve({
      'POST /admin/db/changes': () => reply(200, { ok: true, persisted: true, version_after: 8 }),
    })
    await open('engine_params')
    await screen.findByText('alpha')
    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0])
    const form = await screen.findByRole('form', { name: 'Edit row' })
    // the key column is locked
    expect((within(form).getByLabelText('name') as HTMLTextAreaElement).disabled).toBe(true)
    fireEvent.change(within(form).getByLabelText('value'), { target: { value: '9' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save' }))

    await screen.findByText(/Saved as revision 8/)
    const sent = calls.find(([k]) => k === 'POST /admin/db/changes')![1]
    expect(sent.configuration_id).toBe(1)
    expect(sent.ops).toEqual([{
      op: 'update', table: 'engine_params', key: { name: 'alpha' },
      fields: { value: '9' }, expect: { value: '3' },
    }])
  })

  it('sends an insert without the auto-numbered id, and a delete by key', async () => {
    const calls = serve({
      'POST /admin/db/changes': () => reply(200, { ok: true, persisted: true, version_after: 3 }),
    })
    await open('engine_params')
    await screen.findByText('alpha')
    fireEvent.click(screen.getByRole('button', { name: 'New row' }))
    const form = await screen.findByRole('form', { name: 'New row' })
    expect(within(form).queryByLabelText('id')).toBeNull()
    fireEvent.change(within(form).getByLabelText('name'), { target: { value: 'gamma' } })
    fireEvent.change(within(form).getByLabelText('value'), { target: { value: '1' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save' }))
    await screen.findByText(/Saved as revision 3/)
    expect(calls.find(([k]) => k === 'POST /admin/db/changes')![1].ops).toEqual([
      { op: 'insert', table: 'engine_params', row: { name: 'gamma', value: '1' } },
    ])

    fireEvent.click(screen.getAllByRole('button', { name: 'Delete' })[1])
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm delete' }))
    await waitFor(() => expect(calls.filter(([k]) => k === 'POST /admin/db/changes')).toHaveLength(2))
    expect(calls.filter(([k]) => k === 'POST /admin/db/changes')[1][1].ops).toEqual([
      { op: 'delete', table: 'engine_params', key: { name: 'beta' } },
    ])
  })

  it('says which guard refused a change', async () => {
    serve({
      'POST /admin/db/changes': () => reply(422, {
        ok: false, error: 'unknown_reference', status: 422, message: 'no such node', problems: [],
      }),
    })
    await open('engine_params')
    await screen.findByText('alpha')
    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0])
    const form = await screen.findByRole('form', { name: 'Edit row' })
    fireEvent.change(within(form).getByLabelText('value'), { target: { value: '9' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save' }))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('unknown_reference')
    expect(alert.textContent).toContain('no such node')
  })
})

describe('runtime data and expert mode', () => {
  it('is not editable until expert mode is on and the table name is typed', async () => {
    const calls = serve({ 'POST /admin/db/edit': () => reply(200, { ok: true }) })
    await open('runs')
    await screen.findByText('42')
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()

    fireEvent.click(screen.getByLabelText(/Expert mode/))
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
    fireEvent.change(screen.getByLabelText('Confirmation'), { target: { value: 'run' } })
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
    fireEvent.change(screen.getByLabelText('Confirmation'), { target: { value: 'runs' } })

    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    const form = await screen.findByRole('form', { name: 'Edit row' })
    expect((within(form).getByLabelText('id') as HTMLTextAreaElement).disabled).toBe(true)
    fireEvent.change(within(form).getByLabelText('seed'), { target: { value: '7' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save' }))
    await screen.findByText(/Saved \(update\)/)
    expect(calls.find(([k]) => k === 'POST /admin/db/edit')![1]).toEqual({
      table: 'runs', op: 'update', pk: { id: 9 }, values: { seed: 7 }, expert: true, confirm: 'runs',
    })
  })

  it('turning expert mode off removes the editing again', async () => {
    serve()
    await open('runs')
    await screen.findByText('42')
    fireEvent.click(screen.getByLabelText(/Expert mode/))
    fireEvent.change(screen.getByLabelText('Confirmation'), { target: { value: 'runs' } })
    await screen.findByRole('button', { name: 'Edit' })
    fireEvent.click(screen.getByLabelText(/Expert mode/))
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
  })

  it('shows the server refusing an active run', async () => {
    serve({
      'POST /admin/db/edit': () => reply(409, { detail: { error: 'active_row', message: 'the run is still going' } }),
    })
    await open('runs')
    await screen.findByText('42')
    fireEvent.click(screen.getByLabelText(/Expert mode/))
    fireEvent.change(screen.getByLabelText('Confirmation'), { target: { value: 'runs' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    const form = await screen.findByRole('form', { name: 'Edit row' })
    fireEvent.change(within(form).getByLabelText('seed'), { target: { value: '1' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save' }))
    expect((await screen.findByRole('alert')).textContent).toContain('the run is still going')
  })
})

describe('the SQL box', () => {
  it('posts the statement and shows the rows', async () => {
    const calls = serve({
      'POST /admin/db/sql': () => reply(200, {
        columns: ['n'], rows: [[1], [2]], row_count: 2, truncated: true, limit: 2, timeout_ms: 5000,
      }),
    })
    render(<DatabasePanel />)
    fireEvent.change(await screen.findByLabelText('SQL statement'), { target: { value: 'SELECT 1 AS n' } })
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await screen.findByText(/2 rows \(limited to the first 2\)/)
    expect(calls.find(([k]) => k === 'POST /admin/db/sql')![1]).toEqual({ sql: 'SELECT 1 AS n' })
  })

  it('shows a refusal', async () => {
    serve({ 'POST /admin/db/sql': () => reply(400, { detail: 'only a SELECT or WITH statement can be run here' }) })
    render(<DatabasePanel />)
    fireEvent.click(await screen.findByRole('button', { name: 'Run' }))
    expect((await screen.findByRole('alert')).textContent).toContain('only a SELECT or WITH')
  })
})

describe('the admin layout', () => {
  it('has the Database (all modes) tab', async () => {
    serve()
    render(<AdminLayout />)
    fireEvent.click(await screen.findByRole('button', { name: 'Database (all modes)' }))
    expect(await screen.findByRole('navigation', { name: 'Tables' })).toBeTruthy()
  })
})

describe('values and errors', () => {
  it('reads boxes back into typed values', () => {
    expect(parseValue(col('n', 'INTEGER'), '4')).toBe(4)
    expect(() => parseValue(col('n', 'INTEGER'), 'x')).toThrow()
    expect(parseValue(col('j', 'JSONB'), '{"a":1}')).toEqual({ a: 1 })
    expect(() => parseValue(col('j', 'JSONB'), '{')).toThrow()
    expect(parseValue(col('s', 'TEXT', { nullable: true }), '')).toBeNull()
    expect(parseValue(col('b', 'BOOLEAN'), 'true')).toBe(true)
    expect(showValue({ a: 1 })).toBe('{"a":1}')
    expect(showValue(null)).toBe('')
  })

  it('names the code of a refusal', () => {
    const err = new ApiError(409, 'Conflict', JSON.stringify({
      detail: { error: 'episodic_memory_protected', message: 'never edited' } }))
    expect(describeDbError(err, 'save')).toBe('Could not save (episodic_memory_protected): never edited')
  })
})

describe('DatabasePanel help (C11b)', () => {
  it('has a ? for the Database tab', async () => {
    serve()
    render(<DatabasePanel />)
    await screen.findByRole('navigation', { name: 'Tables' })
    expect(screen.getByRole('button', { name: 'Show help for the Database tab' }).textContent).toBe('?')
  })
})
