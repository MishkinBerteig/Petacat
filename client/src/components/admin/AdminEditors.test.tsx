// ---------------------------------------------------------------------------
// Petacat — every Configuration tab edits the collection it shows
// ---------------------------------------------------------------------------
//
// The seed data is the program's domain knowledge, and the Configuration screen is how
// it is changed without editing a file: the twelve collections that make up a
// configuration each have a tab, and each tab creates, updates and deletes rows in the
// collection it lists. These tests hold that property one collection at a time, by
// asserting on the request each control issues.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { CodeletEditor } from './CodeletEditor'
import { DemoEditor } from './DemoEditor'
import { SlipnetLinkEditor } from './SlipnetLinkEditor'
import { ThemeDimensionEditor } from './ThemeDimensionEditor'
import { PostingRuleEditor } from './PostingRuleEditor'
import { SlipnetLayoutEditor } from './SlipnetLayoutEditor'
import { CommentaryTemplateEditor } from './CommentaryTemplateEditor'
import { HelpTopicEditor } from './HelpTopicEditor'
import { ParamsEditor } from './ParamsEditor'
import { UrgencyLevelEditor } from './UrgencyLevelEditor'

interface Call {
  url: string
  method: string
  body: any
}

let calls: Call[] = []

/** Serves `rows` to every GET and records every write. */
function serve(rows: any[]) {
  calls = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (method !== 'GET') {
      calls.push({
        url,
        method,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      })
      return { ok: true, json: async () => rows[0] ?? {}, text: async () => '' }
    }
    return { ok: true, json: async () => rows, text: async () => '' }
  })
  vi.stubGlobal('fetch', fetchMock)
}

/** Answers every request from `handler`, and records the writes as `serve` does. */
function stubFetch(handler: (url: string, init?: RequestInit) => any) {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (method !== 'GET') {
      calls.push({
        url,
        method,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      })
    }
    return handler(url, init)
  }))
}

/** A 2xx carrying `body`. */
function ok(body: any) {
  return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) }
}

/** A refusal in the shape FastAPI sends one: a status and a `detail`. */
function refusal(status: number, statusText: string, detail: unknown) {
  const body = JSON.stringify({ detail })
  return { ok: false, status, statusText, text: async () => body, json: async () => ({ detail }) }
}

/** The one field error a 422 carries, in FastAPI's shape. */
function fieldError(field: string, msg: string) {
  return [{ type: 'value_error', loc: ['body', field], msg, input: null }]
}

const method = (init?: RequestInit) => init?.method ?? 'GET'

beforeEach(() => { calls = [] })
afterEach(() => { vi.unstubAllGlobals() })

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

// --- the six table-shaped collections ---------------------------------------

describe('DemoEditor — demo problems', () => {
  const demo = {
    id: 3, name: 'abc-xyz', section: '2.1', initial: 'abc', modified: 'abd',
    target: 'xyz', answer: null, seed: 7, mode: 'discovery', description: '',
  }

  it('updates a demo, carrying the whole row the API asks for', async () => {
    serve([demo])
    render(<DemoEditor />)

    await editCell('abc-xyz', 'renamed')

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].method).toBe('PUT')
    expect(calls[0].url).toBe('/api/admin/demos/3')
    expect(calls[0].body.name).toBe('renamed')
    // The fields not edited travel with it, since PUT replaces the row.
    expect(calls[0].body.target).toBe('xyz')
    expect(calls[0].body.seed).toBe(7)
  })

  it('creates a demo', async () => {
    serve([demo])
    render(<DemoEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /\+ Add/ }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'new demo' } })
    fireEvent.change(screen.getByLabelText('Initial'), { target: { value: 'aab' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].method).toBe('POST')
    expect(calls[0].url).toBe('/api/admin/demos')
    expect(calls[0].body.name).toBe('new demo')
    expect(calls[0].body.initial).toBe('aab')
  })

  it('deletes a demo once the deletion is confirmed', async () => {
    serve([demo])
    render(<DemoEditor />)

    fireEvent.click(await screen.findByTitle('Delete'))
    fireEvent.click(screen.getByRole('button', { name: /^Yes$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({ method: 'DELETE', url: '/api/admin/demos/3' })
  })
})

describe('EditableTable — an empty number box', () => {
  const level = { name: 'high', value: 50 }

  it('submits zero for a column that always carries a number', async () => {
    // Urgency, conceptual depth, a formula coefficient and a sort order each hold a
    // number, so clearing the box asks for zero.
    serve([level])
    render(<UrgencyLevelEditor />)

    await editCell('50', '')

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body.value).toBe(0)
  })

  it('submits null for a column whose value may be absent', async () => {
    serve([{
      id: 1, from_node: 'plato-a', to_node: 'plato-b', link_type: 'lateral',
      label_node: null, link_length: 20, fixed_length: true,
    }])
    render(<SlipnetLinkEditor />)

    await editCell('20', '')

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body.link_length).toBeNull()
  })

  it('submits zero for a nullable column when zero is typed', async () => {
    // Association strength is `100 - link_length`, so a zero-length link is the
    // strongest one there is.
    serve([{
      id: 1, from_node: 'plato-a', to_node: 'plato-b', link_type: 'lateral',
      label_node: null, link_length: 20, fixed_length: true,
    }])
    render(<SlipnetLinkEditor />)

    await editCell('20', '0')

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body.link_length).toBe(0)
  })
})

describe('ThemeDimensionEditor — theme dimensions', () => {
  const dim = { id: 5, slipnet_node: 'plato-direction-category', valid_relations: ['identity'] }

  it('edits the relation list as JSON', async () => {
    serve([dim])
    render(<ThemeDimensionEditor />)

    await editCell('["identity"]', '["identity","opposite"]')

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].method).toBe('PUT')
    expect(calls[0].body.valid_relations).toEqual(['identity', 'opposite'])
  })

  it('reports invalid JSON instead of sending it', async () => {
    serve([dim])
    render(<ThemeDimensionEditor />)

    await editCell('["identity"]', 'identity, opposite')

    await waitFor(() => {
      expect(screen.getByText(/needs valid JSON/)).toBeTruthy()
    })
    expect(calls).toHaveLength(0)
  })

  it('creates a dimension', async () => {
    serve([dim])
    render(<ThemeDimensionEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /\+ Add/ }))
    fireEvent.change(screen.getByLabelText('Slipnet Node'), { target: { value: 'plato-length' } })
    fireEvent.change(screen.getByLabelText('Valid Relations'), { target: { value: '["identity"]' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({ method: 'POST', url: '/api/admin/theme-dimensions' })
    expect(calls[0].body).toEqual({
      slipnet_node: 'plato-length', valid_relations: ['identity'],
    })
  })
})

describe('PostingRuleEditor — posting rules', () => {
  const rule = {
    id: 2, codelet_type: 'bottom-up-bond-scout', direction: 'bottom_up',
    urgency_when_posted: 30, urgency_formula: null, posting_formula: '',
    count_formula: '', count_values: null, condition: 'always',
    triggering_slipnodes: null,
  }

  it('edits a rule condition', async () => {
    serve([rule])
    render(<PostingRuleEditor />)

    await editCell('always', 'never')

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({ method: 'PUT', url: '/api/admin/posting-rules/2' })
    expect(calls[0].body.condition).toBe('never')
    expect(calls[0].body.codelet_type).toBe('bottom-up-bond-scout')
  })

  it('deletes a rule', async () => {
    serve([rule])
    render(<PostingRuleEditor />)

    fireEvent.click(await screen.findByTitle('Delete'))
    fireEvent.click(screen.getByRole('button', { name: /^Yes$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({ method: 'DELETE', url: '/api/admin/posting-rules/2' })
  })
})

describe('SlipnetLayoutEditor — grid positions', () => {
  const pos = { node_name: 'plato-a', grid_row: 0, grid_col: 1 }

  it('moves a node to another cell', async () => {
    serve([pos])
    render(<SlipnetLayoutEditor />)

    await editCell('plato-a', 'plato-b')

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({
      method: 'PUT', url: '/api/admin/slipnet-layout/plato-a',
    })
    expect(calls[0].body).toEqual({ node_name: 'plato-a', grid_row: 0, grid_col: 1 })
  })

  it('creates a position', async () => {
    serve([pos])
    render(<SlipnetLayoutEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /\+ Add/ }))
    fireEvent.change(screen.getByLabelText('Node Name'), { target: { value: 'plato-z' } })
    fireEvent.change(screen.getByLabelText('Row'), { target: { value: '4' } })
    fireEvent.change(screen.getByLabelText('Col'), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body).toEqual({ node_name: 'plato-z', grid_row: 4, grid_col: 2 })
  })
})

describe('ParamsEditor — engine parameters', () => {
  const param = { name: 'rule_importance_threshold', value: '67', value_type: 'int' }

  it('updates a parameter value', async () => {
    serve([param])
    render(<ParamsEditor />)

    await editCell('67', '70')

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].method).toBe('PUT')
    expect(calls[0].url).toBe('/api/admin/params/rule_importance_threshold')
    expect(calls[0].body).toEqual({ value: '70', value_type: 'int' })
  })

  it('creates a parameter', async () => {
    serve([param])
    render(<ParamsEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /\+ Add/ }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'new_param' } })
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'int' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({ method: 'POST', url: '/api/admin/params' })
    expect(calls[0].body).toEqual({ name: 'new_param', value: '5', value_type: 'int' })
  })

  it('deletes a parameter', async () => {
    serve([param])
    render(<ParamsEditor />)

    fireEvent.click(await screen.findByTitle('Delete'))
    fireEvent.click(screen.getByRole('button', { name: /^Yes$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({
      method: 'DELETE', url: '/api/admin/params/rule_importance_threshold',
    })
  })
})

describe('SlipnetLinkEditor — a length of zero and a length left unsaid', () => {
  const link = {
    id: 7, from_node: 'plato-sameness', to_node: 'plato-bond-category',
    link_type: 'category', label_node: null, link_length: 20, fixed_length: true,
  }

  /** Fill the three fields a link needs before its length is considered. */
  function fillNewLink() {
    fireEvent.change(screen.getByLabelText('From'), { target: { value: 'plato-samegrp' } })
    fireEvent.change(screen.getByLabelText('To'), { target: { value: 'plato-group-category' } })
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'category' } })
  }

  it('creates a link of length zero', async () => {
    serve([link])
    render(<SlipnetLinkEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /\+ Add/ }))
    fillNewLink()
    fireEvent.change(screen.getByLabelText('Length'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({ method: 'POST', url: '/api/admin/slipnet/links' })
    expect(calls[0].body.link_length).toBe(0)
  })

  it('creates a link that leaves its length to the label node', async () => {
    serve([link])
    render(<SlipnetLinkEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /\+ Add/ }))
    fillNewLink()
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body.link_length).toBeNull()
  })

  it('sets an existing length to zero', async () => {
    serve([link])
    render(<SlipnetLinkEditor />)

    await editCell('20', '0')

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({ method: 'PUT', url: '/api/admin/slipnet/links/7' })
    expect(calls[0].body.link_length).toBe(0)
  })

  it('clears an existing length', async () => {
    serve([link])
    render(<SlipnetLinkEditor />)

    await editCell('20', '')

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body.link_length).toBeNull()
  })
})

describe('CodeletEditor — an urgency of zero and an urgency left unsaid', () => {
  const codelet = {
    name: 'bottom-up-bond-scout', family: 'scout', phase: 'scout',
    default_urgency: 35, description: '', execute_body: 'pass',
  }

  /** Open the type in the detail pane and put it into edit mode. */
  async function startEditing() {
    fireEvent.click(await screen.findByText('bottom-up-bond-scout'))
    fireEvent.click(screen.getByRole('button', { name: /^Edit$/ }))
  }

  it('saves an urgency of zero', async () => {
    serve([codelet])
    render(<CodeletEditor />)

    await startEditing()
    fireEvent.change(screen.getByLabelText(/Urgency/), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({
      method: 'PUT', url: '/api/admin/codelets/bottom-up-bond-scout',
    })
    expect(calls[0].body.default_urgency).toBe(0)
  })

  it('saves a blank urgency as none at all', async () => {
    serve([codelet])
    render(<CodeletEditor />)

    await startEditing()
    fireEvent.change(screen.getByLabelText(/Urgency/), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body.default_urgency).toBeNull()
  })
})

// --- the two long-text collections ------------------------------------------

describe('CommentaryTemplateEditor — the program\'s English', () => {
  const template = { id: 1, template_key: 'all', template_data: { greeting: 'hello' } }

  it('saves an edited template', async () => {
    serve([template])
    render(<CommentaryTemplateEditor />)

    fireEvent.click(await screen.findByText('all'))
    fireEvent.change(screen.getByLabelText(/Template data/), {
      target: { value: '{"greeting": "hi"}' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({
      method: 'PUT', url: '/api/admin/commentary-templates/1',
    })
    expect(calls[0].body).toEqual({
      template_key: 'all', template_data: { greeting: 'hi' },
    })
  })

  it('reports invalid JSON instead of sending it', async () => {
    serve([template])
    render(<CommentaryTemplateEditor />)

    fireEvent.click(await screen.findByText('all'))
    fireEvent.change(screen.getByLabelText(/Template data/), {
      target: { value: 'greeting: hi' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/valid JSON/))
    expect(calls).toHaveLength(0)
  })

  it('creates a template', async () => {
    serve([template])
    render(<CommentaryTemplateEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /\+ New template/ }))
    fireEvent.change(screen.getByLabelText('Key'), { target: { value: 'snags' } })
    fireEvent.change(screen.getByLabelText(/Template data/), { target: { value: '{}' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({
      method: 'POST', url: '/api/admin/commentary-templates',
    })
    expect(calls[0].body).toEqual({ template_key: 'snags', template_data: {} })
  })

  it('deletes a template', async () => {
    serve([template])
    render(<CommentaryTemplateEditor />)

    fireEvent.click(await screen.findByText('all'))
    fireEvent.click(screen.getByRole('button', { name: /^Delete$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({
      method: 'DELETE', url: '/api/admin/commentary-templates/1',
    })
  })
})

describe('HelpTopicEditor — the in-app help', () => {
  const topic = {
    id: 9, topic_type: 'concept', topic_key: 'themespace', title: 'Themespace',
    short_desc: 'short', full_desc: 'full',
  }

  it('saves an edited topic', async () => {
    serve([topic])
    render(<HelpTopicEditor />)

    fireEvent.click(await screen.findByText('themespace'))
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'The Themespace' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({ method: 'PUT', url: '/api/admin/help-topics/9' })
    expect(calls[0].body.title).toBe('The Themespace')
    expect(calls[0].body.full_desc).toBe('full')
  })

  it('creates a topic', async () => {
    serve([topic])
    render(<HelpTopicEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /\+ New topic/ }))
    fireEvent.change(screen.getByLabelText('Key'), { target: { value: 'jootsing' } })
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Jootsing' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({ method: 'POST', url: '/api/admin/help-topics' })
    expect(calls[0].body.topic_key).toBe('jootsing')
    expect(calls[0].body.title).toBe('Jootsing')
  })

  it('deletes a topic', async () => {
    serve([topic])
    render(<HelpTopicEditor />)

    fireEvent.click(await screen.findByText('themespace'))
    fireEvent.click(screen.getByRole('button', { name: /^Delete$/ }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({ method: 'DELETE', url: '/api/admin/help-topics/9' })
  })
})

// ---------------------------------------------------------------------------
// What each tab does when the server says no
// ---------------------------------------------------------------------------
//
// A configuration tab is where the domain knowledge is changed, and the reason a change
// was refused is the whole of what the reader needs: a name already taken, a value out
// of range and a row that has since gone each call for a different next move. These
// tests hold that every one of those reaches the screen, and says which one it is.
// ---------------------------------------------------------------------------

describe('A failed load says why, in place of the list', () => {
  it('names the collection and the kind of failure', async () => {
    stubFetch(() => refusal(500, 'Internal Server Error', 'seed data unavailable'))
    render(<DemoEditor />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('load the demo problems')
    expect(alert.textContent).toContain('the server failed to complete it')
    expect(alert.textContent).toContain('seed data unavailable')
  })

  it('reports an unreachable server as such', async () => {
    // A `fetch` that never reaches a server rejects with a TypeError, which carries no
    // status: there is nothing to report but the fact that nobody answered.
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    render(<PostingRuleEditor />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('load the posting rules')
    expect(alert.textContent).toContain('the server is unreachable')
  })

  it('offers the retry, and shows the list once it succeeds', async () => {
    const codelet = {
      name: 'bottom-up-bond-scout', family: 'scout', phase: 'scout',
      default_urgency: 35, description: '', execute_body: 'pass',
    }
    let answered = false
    stubFetch(() => {
      const reply = answered ? ok([codelet]) : refusal(503, 'Service Unavailable', 'database starting')
      answered = true
      return reply
    })
    render(<CodeletEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /^Retry$/ }))

    expect(await screen.findByText('bottom-up-bond-scout')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('says why the commentary templates are missing', async () => {
    stubFetch(() => refusal(500, 'Internal Server Error', 'templates unreadable'))
    render(<CommentaryTemplateEditor />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('load the commentary templates')
    expect(alert.textContent).toContain('templates unreadable')
  })

  it('says why the help topics are missing', async () => {
    stubFetch(() => refusal(500, 'Internal Server Error', 'topics unreadable'))
    render(<HelpTopicEditor />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('load the help topics')
    expect(alert.textContent).toContain('topics unreadable')
  })
})

describe('A refused write says which refusal it was', () => {
  const param = { name: 'rule_importance_threshold', value: '67', value_type: 'int' }

  it('tells a name already taken from a value the server will not take', async () => {
    stubFetch((_url, init) => {
      if (method(init) === 'POST') {
        return refusal(409, 'Conflict', "Parameter 'seed' already exists")
      }
      if (method(init) === 'PUT') {
        return refusal(422, 'Unprocessable Entity', fieldError('value_type', 'Input should be int, float, str or bool'))
      }
      return ok([param])
    })
    render(<ParamsEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /\+ Add/ }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'seed' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    const onConflict = (await screen.findByRole('alert')).textContent ?? ''
    expect(onConflict).toContain('add the parameter')
    expect(onConflict).toContain('conflicts with something already there')
    expect(onConflict).toContain("Parameter 'seed' already exists")

    await editCell('67', '70')

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('check the values entered')
    })
    const onInvalid = screen.getByRole('alert').textContent ?? ''
    expect(onInvalid).toContain('save the parameter')
    // The 422's field list is unwrapped, so the message names the box to go back to.
    expect(onInvalid).toContain('value_type: Input should be int, float, str or bool')
    expect(onInvalid).not.toBe(onConflict)
  })

  it('keeps the typed row on screen when a create is refused', async () => {
    stubFetch((_url, init) =>
      method(init) === 'POST'
        ? refusal(422, 'Unprocessable Entity', fieldError('slipnet_node', 'Unknown node'))
        : ok([{ id: 5, slipnet_node: 'plato-direction-category', valid_relations: ['identity'] }]),
    )
    render(<ThemeDimensionEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /\+ Add/ }))
    fireEvent.change(screen.getByLabelText('Slipnet Node'), { target: { value: 'plato-nowhere' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('add the theme dimension')
    expect(alert.textContent).toContain('slipnet_node: Unknown node')
    // The value that was refused is still in its box, ready to be corrected.
    expect((screen.getByLabelText('Slipnet Node') as HTMLInputElement).value).toBe('plato-nowhere')
  })

  it('names the row that has gone when an update finds nothing to update', async () => {
    stubFetch((_url, init) =>
      method(init) === 'PUT'
        ? refusal(404, 'Not Found', "Layout for node 'plato-a' not found")
        : ok([{ node_name: 'plato-a', grid_row: 0, grid_col: 1 }]),
    )
    render(<SlipnetLayoutEditor />)

    await editCell('plato-a', 'plato-b')

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('save the grid position')
    expect(alert.textContent).toContain('it no longer exists')
    expect(alert.textContent).toContain("Layout for node 'plato-a' not found")
  })
})

describe('A refused delete leaves the row where it is', () => {
  it('keeps the demo listed, with the reason it is still there', async () => {
    const demo = {
      id: 3, name: 'abc-xyz', section: '2.1', initial: 'abc', modified: 'abd',
      target: 'xyz', answer: null, seed: 7, mode: 'discovery', description: '',
    }
    stubFetch((_url, init) =>
      method(init) === 'DELETE'
        ? refusal(409, 'Conflict', 'Demo 3 is referenced by a recorded run')
        : ok([demo]),
    )
    render(<DemoEditor />)

    fireEvent.click(await screen.findByTitle('Delete'))
    fireEvent.click(screen.getByRole('button', { name: /^Yes$/ }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('delete the demo problem')
    expect(alert.textContent).toContain('conflicts with something already there')
    expect(alert.textContent).toContain('Demo 3 is referenced by a recorded run')
    // The server still holds the row, so the table still shows it.
    expect(screen.getByText('abc-xyz')).toBeTruthy()
  })

  it('keeps the posting rule listed, and offers the delete again', async () => {
    const rule = {
      id: 2, codelet_type: 'bottom-up-bond-scout', direction: 'bottom_up',
      urgency_when_posted: 30, urgency_formula: null, posting_formula: '',
      count_formula: '', count_values: null, condition: 'always',
      triggering_slipnodes: null,
    }
    stubFetch((_url, init) =>
      method(init) === 'DELETE'
        ? refusal(404, 'Not Found', 'Posting rule 2 not found')
        : ok([rule]),
    )
    render(<PostingRuleEditor />)

    fireEvent.click(await screen.findByTitle('Delete'))
    fireEvent.click(screen.getByRole('button', { name: /^Yes$/ }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('delete the posting rule')
    expect(alert.textContent).toContain('it no longer exists')
    expect(screen.getByText('bottom-up-bond-scout')).toBeTruthy()
    expect(screen.getByTitle('Delete')).toBeTruthy()
  })

  it('keeps the help topic listed and open', async () => {
    const topic = {
      id: 9, topic_type: 'concept', topic_key: 'themespace', title: 'Themespace',
      short_desc: 'short', full_desc: 'full',
    }
    stubFetch((_url, init) =>
      method(init) === 'DELETE'
        ? refusal(409, 'Conflict', 'Topic 9 is referenced by a component')
        : ok([topic]),
    )
    render(<HelpTopicEditor />)

    fireEvent.click(await screen.findByText('themespace'))
    fireEvent.click(screen.getByRole('button', { name: /^Delete$/ }))

    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toContain('delete the help topic')
    })
    const status = screen.getByRole('status').textContent ?? ''
    expect(status).toContain('conflicts with something already there')
    expect(status).toContain('Topic 9 is referenced by a component')
    expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('Themespace')
  })
})

describe('The two long-text editors report their own refusals', () => {
  const template = { id: 1, template_key: 'all', template_data: { greeting: 'hello' } }

  it('reports a template key already taken', async () => {
    stubFetch((_url, init) =>
      method(init) === 'POST'
        ? refusal(409, 'Conflict', "Template 'all' already exists")
        : ok([template]),
    )
    render(<CommentaryTemplateEditor />)

    fireEvent.click(await screen.findByRole('button', { name: /\+ New template/ }))
    fireEvent.change(screen.getByLabelText('Key'), { target: { value: 'all' } })
    fireEvent.change(screen.getByLabelText(/Template data/), { target: { value: '{}' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toContain('add the commentary template')
    })
    const status = screen.getByRole('status').textContent ?? ''
    expect(status).toContain('conflicts with something already there')
    expect(status).toContain("Template 'all' already exists")
    // The draft is still in the box it was typed into.
    expect((screen.getByLabelText('Key') as HTMLInputElement).value).toBe('all')
  })

  it('reports a codelet body the server will not take', async () => {
    const codelet = {
      name: 'bottom-up-bond-scout', family: 'scout', phase: 'scout',
      default_urgency: 35, description: '', execute_body: 'pass',
    }
    stubFetch((_url, init) =>
      method(init) === 'PUT'
        ? refusal(422, 'Unprocessable Entity', fieldError('execute_body', 'invalid syntax at line 1'))
        : ok([codelet]),
    )
    render(<CodeletEditor />)

    fireEvent.click(await screen.findByText('bottom-up-bond-scout'))
    fireEvent.click(screen.getByRole('button', { name: /^Edit$/ }))
    fireEvent.change(screen.getByDisplayValue('pass'), { target: { value: 'def(' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('save the codelet type')
    expect(alert.textContent).toContain('check the values entered')
    expect(alert.textContent).toContain('execute_body: invalid syntax at line 1')
    // The body that was refused is still in the editor.
    expect(screen.getByDisplayValue('def(')).toBeTruthy()
  })
})
