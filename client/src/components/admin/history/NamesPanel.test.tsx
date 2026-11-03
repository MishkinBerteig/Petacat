// ---------------------------------------------------------------------------
// Petacat -- "Names that no longer resolve" and the names a memory holds
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import { NamesPanel } from './NamesPanel'
import { memoryNames } from './memoryNames'
import { reply, serve } from './testing'

afterEach(() => { vi.unstubAllGlobals() })

const STORY = {
  name: 'plato-gone', configuration_id: 1, resolves: false, kind: null, current_name: 'plato-kept',
  events: [], restorable: null, text: "the node 'plato-gone' was merged into 'plato-kept' at revision 4 by source admin, actor dave",
}

describe('memoryNames', () => {
  it('collects the dimension and relation names of every theme pattern, sorted and distinct', () => {
    const names = memoryNames({
      answers: [
        { themes: { 'plato-length': 'identity' }, top_themes: { 'plato-letter-category': 'successor' }, bottom_themes: {}, extra: 1 },
        { vertical_themes: { 'plato-length': 'opposite' }, unjustified_themes: { 'plato-x': 3 } },
      ],
      snags: [{ theme_pattern: { 'plato-direction-category': 'opposite' } }, { theme_pattern: null }],
    })
    expect(names).toEqual([
      'identity', 'opposite', 'plato-direction-category', 'plato-length', 'plato-letter-category', 'plato-x', 'successor',
    ])
    expect(memoryNames(null)).toEqual([])
  })
})

describe('NamesPanel', () => {
  it('lists the names the configuration lacks, each with its story', async () => {
    const calls = serve({ 'POST /journal/check-names': () => reply(200, { configuration_id: 1, checked: 2, unresolved: [STORY] }) })
    render(<NamesPanel configurationId={1} names={['plato-gone', 'plato-kept']} memoryLabel="Metacat Mode's Episodic Memory" />)
    const panel = await screen.findByTestId('unresolved-names')
    expect(panel.textContent).toContain('Names that no longer resolve (1)')
    expect(panel.textContent).toContain("Metacat Mode's Episodic Memory")
    const item = screen.getByTestId('unresolved-name')
    expect(item.textContent).toContain('plato-gone')
    expect(item.textContent).toContain('merged into')
    expect(item.textContent).toContain('now plato-kept')
    expect(calls[0]).toEqual(['POST /journal/check-names', { configuration_id: 1, names: ['plato-gone', 'plato-kept'] }])
  })

  it('finds a session\'s configuration from its session id', async () => {
    const calls = serve({
      'GET /configurations': () => reply(200, { configurations: [{ id: 1, session_id: null }, { id: 9, session_id: 4 }] }),
      'POST /journal/check-names': () => reply(200, { configuration_id: 9, checked: 1, unresolved: [STORY] }),
    })
    render(<NamesPanel sessionId={4} names={['plato-gone']} memoryLabel="This Training Mode Session's Episodic Memory" />)
    await screen.findByTestId('unresolved-names')
    expect(calls.find(([k]) => k.startsWith('POST'))![1]).toEqual({ configuration_id: 9, names: ['plato-gone'] })
  })

  it('shows nothing when every name resolves, when there are no names, or when the check fails', async () => {
    const calls = serve({ 'POST /journal/check-names': () => reply(200, { configuration_id: 1, checked: 1, unresolved: [] }) })
    const { container, rerender } = render(<NamesPanel configurationId={1} names={['plato-a']} memoryLabel="m" />)
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(container.textContent).toBe('')
    rerender(<NamesPanel configurationId={1} names={[]} memoryLabel="m" />)
    expect(calls).toHaveLength(1)
    vi.unstubAllGlobals()
    serve({ 'POST /journal/check-names': () => reply(500, { detail: 'down' }) })
    const failed = render(<NamesPanel configurationId={1} names={['plato-a']} memoryLabel="m" />)
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    expect(failed.container.textContent).toBe('')
  })
})
