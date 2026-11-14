// ---------------------------------------------------------------------------
// adminRequest -- one way for every Admin editor to read and write any configuration
// ---------------------------------------------------------------------------
//
// The editors were written against `/api/admin/...` for the global configuration (Metacat
// Mode). Each now takes a `configuration` prop and calls `useAdminRequest(configuration)`
// where it used to call `request`. For the global configuration that IS `request`, so
// nothing changes. For a Training Mode Session's configuration:
//
//  * a list is read from `GET /configurations/{id}/rows?table=...` (the editors' list routes
//    answer the global configuration only);
//  * a write to an editor addressed by natural key (nodes, codelets, parameters, urgency
//    levels, coefficients, layout) goes to the same editor route with `?configuration=`;
//  * a write to an editor addressed by a surrogate `id` (links, demos, theme dimensions,
//    posting rules, commentary templates) goes to the change API by natural key
//    (`POST /configurations/{id}/changes`). The surrogate id is not stable across
//    configurations, so a list here hands each row a number that stands for its natural key
//    for as long as the list lives, and the write turns it back into the key.
//
// Either way the server writes one journaled batch, so the change takes effect at the
// start of the next run.

import { useMemo } from 'react'
import { ApiError, GLOBAL_CONFIGURATION_ID, request } from '@/api/client'
import { useScopeRef, type ScopeValue } from './editScope'

export type AdminRequest = <T>(path: string, options?: RequestInit) => Promise<T>

/** The prop every editor takes. Omitted, it is the global configuration (Metacat Mode). */
export interface ConfigurationProp {
  configuration?: number
}

type Row = Record<string, any>

interface RowsResponse {
  key_columns: string[]
  rows: Row[]
}

interface Spec {
  table: string
  /** Rows are addressed by a surrogate `id` in the editor's routes. */
  surrogate?: boolean
}

const SPECS: Record<string, Spec> = {
  '/admin/slipnet/nodes': { table: 'slipnet_node_defs' },
  '/admin/slipnet/links': { table: 'slipnet_link_defs', surrogate: true },
  '/admin/link-types': { table: 'link_types' },
  '/admin/codelets': { table: 'codelet_type_defs' },
  '/admin/params': { table: 'engine_params' },
  '/admin/urgency-levels': { table: 'urgency_levels' },
  '/admin/formula-coefficients': { table: 'formula_coefficients' },
  '/admin/demos': { table: 'demo_problems', surrogate: true },
  '/admin/theme-dimensions': { table: 'theme_dimension_defs', surrogate: true },
  '/admin/posting-rules': { table: 'posting_rules', surrogate: true },
  '/admin/initial-description-rules': { table: 'initial_description_rules', surrogate: true },
  '/admin/initial-activation-rules': { table: 'initial_activation_rules', surrogate: true },
  '/admin/input-character-ranges': { table: 'input_character_ranges', surrogate: true },
  '/admin/input-lowering-ranges': { table: 'input_lowering_ranges', surrogate: true },
  '/admin/commentary-templates': { table: 'commentary_templates', surrogate: true },
  '/admin/slipnet-layout': { table: 'slipnet_layout' },
}

/** The collection a path belongs to, and the id after it (`/admin/demos/3` -> demos, `3`). */
function locate(path: string): { base: string; spec: Spec; id: string | null } | null {
  const bare = path.split('?')[0]
  for (const [base, spec] of Object.entries(SPECS)) {
    if (bare === base) return { base, spec, id: null }
    if (bare.startsWith(base + '/')) return { base, spec, id: bare.slice(base.length + 1) }
  }
  return null
}

const sameValue = (a: unknown, b: unknown) => (a ?? '') === (b ?? '')

/** A change-API refusal carries `message`, not FastAPI's `detail`; make it read the same. */
function asApiError(err: unknown): unknown {
  if (!(err instanceof ApiError)) return err
  try {
    const parsed = JSON.parse(err.body)
    if (parsed && typeof parsed.message === 'string' && parsed.detail === undefined) {
      return new ApiError(err.status, err.statusText, JSON.stringify({ detail: parsed.message }))
    }
  } catch {
    // Not JSON: leave it.
  }
  return err
}

interface Table {
  keyColumns: string[]
  rows: Row[]
  /** surrogate number -> natural key */
  keys: Map<number, Row>
  next: number
}

/** The requester for one configuration. `GLOBAL_CONFIGURATION_ID` is `request` itself. */
function makeConfigurationRequest(configuration: number): AdminRequest {
  if (configuration === GLOBAL_CONFIGURATION_ID) return request

  const tables = new Map<string, Table>()
  const changes = `/configurations/${configuration}/changes`
  const withConfiguration = (path: string) =>
    `${path}${path.includes('?') ? '&' : '?'}configuration=${configuration}`

  const keyOf = (t: Table, row: Row): Row =>
    Object.fromEntries(t.keyColumns.map(c => [c, row[c] ?? '']))

  async function list(spec: Spec): Promise<Row[]> {
    const res = await request<RowsResponse>(`/configurations/${configuration}/rows?table=${spec.table}`)
    if (!spec.surrogate) return res.rows
    const t: Table = { keyColumns: res.key_columns, rows: [], keys: new Map(), next: 1 }
    t.rows = res.rows.map(r => {
      const id = t.next++
      t.keys.set(id, keyOf(t, r))
      return { ...r, id }
    })
    tables.set(spec.table, t)
    return t.rows
  }

  async function tableFor(spec: Spec): Promise<Table> {
    if (!tables.has(spec.table)) await list(spec)
    return tables.get(spec.table)!
  }

  async function send(ops: Row[]): Promise<void> {
    try {
      await request(changes, {
        method: 'POST',
        body: JSON.stringify({
          source: 'admin', actor: 'admin', channel: 'admin_editor', base_mode: 'rebase', ops,
        }),
      })
    } catch (err) {
      throw asApiError(err)
    }
  }

  async function surrogateWrite(spec: Spec, method: string, idText: string | null, options: RequestInit) {
    const t = await tableFor(spec)
    const body: Row = options.body ? JSON.parse(String(options.body)) : {}
    if (method === 'POST') {
      const row = { ...body }
      if (spec.table === 'posting_rules' && !row.rule_key) {
        // The global route picks a free key; so does this: the codelet type, else a numbered variant.
        const taken = new Set(t.rows.map(r => r.rule_key))
        let key = String(row.codelet_type)
        for (let n = 2; taken.has(key); n++) key = `${row.codelet_type}_${n}`
        row.rule_key = key
      }
      await send([{ op: 'insert', table: spec.table, row }])
      const id = t.next++
      const stored = { ...row, id }
      t.keys.set(id, keyOf(t, row))
      t.rows.push(stored)
      return stored
    }
    const id = Number(idText)
    const key = t.keys.get(id)
    if (!key) {
      throw new ApiError(404, 'Not Found', JSON.stringify({ detail: `${spec.table} row ${idText} is not in this configuration` }))
    }
    if (method === 'DELETE') {
      await send([{ op: 'delete', table: spec.table, key }])
      t.keys.delete(id)
      t.rows = t.rows.filter(r => r.id !== id)
      return undefined
    }
    // PUT: a column of the key that did not change is left out of the fields (it names the row).
    const fields: Row = {}
    for (const [c, v] of Object.entries(body)) {
      if (c === 'id' || (spec.table === 'posting_rules' && c === 'rule_key')) continue
      if (t.keyColumns.includes(c) && sameValue(v, key[c])) continue
      fields[c] = v
    }
    await send([{ op: 'update', table: spec.table, key, fields }])
    const current = t.rows.find(r => r.id === id) ?? { id }
    const stored = { ...current, ...body, id }
    t.keys.set(id, keyOf(t, stored))
    t.rows = t.rows.map(r => (r.id === id ? stored : r))
    return stored
  }

  return async function adminRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
    const method = (options.method ?? 'GET').toUpperCase()
    const found = locate(path)
    if (!found) return request<T>(withConfiguration(path), options)
    if (method === 'GET' && found.id === null) return (await list(found.spec)) as T
    if (!found.spec.surrogate) return request<T>(withConfiguration(path), options)
    return (await surrogateWrite(found.spec, method, found.id, options)) as T
  }
}

/**
 * The requester for one configuration, with the scope picker (3.10.2) applied. While the scope is
 * "this configuration" (or `getScope` is absent) it is the plain requester. Otherwise a write to
 * an editor becomes ops for the edits routes, and goes through the preview dialog to the
 * chosen configurations or to all of them; reads are unchanged.
 */
export function makeAdminRequest(
  configuration: number,
  getScope?: () => ScopeValue | null,
): AdminRequest {
  const plain = makeConfigurationRequest(configuration)
  if (!getScope) return plain

  let keyColumns: Record<string, string[]> = {}
  async function keysOf(table: string): Promise<string[]> {
    if (!keyColumns[table]) {
      const res = await request<RowsResponse>(`/configurations/${configuration}/rows?table=${table}`)
      keyColumns = { ...keyColumns, [table]: res.key_columns }
    }
    return keyColumns[table]
  }

  return async function scopedRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
    const sc = getScope()
    const method = (options.method ?? 'GET').toUpperCase()
    const found = locate(path)
    if (!sc || sc.scope.mode === 'this' || method === 'GET' || !found) return plain<T>(path, options)

    const { spec } = found
    const cols = await keysOf(spec.table)
    const list = (await plain<Row[]>(found.base)) as Row[]
    const body: Row = options.body ? JSON.parse(String(options.body)) : {}
    const keyOf = (row: Row): Row => Object.fromEntries(cols.map(c => [c, row[c] ?? '']))

    if (method === 'POST') {
      const row = { ...body }
      if (spec.table === 'posting_rules' && !row.rule_key) {
        const taken = new Set(list.map(r => r.rule_key))
        let key = String(row.codelet_type)
        for (let n = 2; taken.has(key); n++) key = `${row.codelet_type}_${n}`
        row.rule_key = key
      }
      await sc.commit([{ op: 'insert', table: spec.table, row }])
      return row as T
    }

    const idText = decodeURIComponent(found.id ?? '')
    const current = list.find(r => (spec.surrogate ? String(r.id) === idText : String(r[cols[0]]) === idText))
    if (!current) {
      throw new ApiError(404, 'Not Found', JSON.stringify({ detail: `${spec.table} row ${idText} is not in this configuration` }))
    }
    const key = keyOf(current)
    if (method === 'DELETE') {
      await sc.commit([{ op: 'delete', table: spec.table, key }])
      return undefined as T
    }
    // PUT: only columns the row has; a key column that did not change names the row, not a field.
    const fields: Row = {}
    for (const [c, v] of Object.entries(body)) {
      if (c === 'id' || !(c in current) || (spec.table === 'posting_rules' && c === 'rule_key')) continue
      if (cols.includes(c) && sameValue(v, key[c])) continue
      if (sameValue(v, current[c])) continue
      fields[c] = v
    }
    const expect = Object.fromEntries(Object.keys(fields).map(c => [c, current[c]]))
    await sc.commit([{ op: 'update', table: spec.table, key, fields, expect }])
    return { ...current, ...body } as T
  }
}

/** The requester an editor uses; it changes only when the configuration does. */
export function useAdminRequest(configuration: number = GLOBAL_CONFIGURATION_ID): AdminRequest {
  const scope = useScopeRef()
  return useMemo(() => {
    const inner = makeAdminRequest(configuration, () => scope.current)
    // One place covers every editor and every scope: a write that succeeded tells the layout, which
    // refreshes the difference banner and the header chip.
    return (async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
      const result = await inner<T>(path, options)
      if ((options.method ?? 'GET').toUpperCase() !== 'GET') scope.current?.written()
      return result
    }) as AdminRequest
  }, [configuration, scope])
}
