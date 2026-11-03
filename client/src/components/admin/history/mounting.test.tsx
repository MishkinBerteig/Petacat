// ---------------------------------------------------------------------------
// Petacat -- the "names that no longer resolve" panel on both memory views
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'

import { MemoryTab } from '../../session/MemoryTab'
import { MemoryView } from '../../MemoryView'
import { reply, serve } from './testing'
import type { SessionSummary } from '@/types'

afterEach(() => { vi.unstubAllGlobals() })

const MEMORY = {
  answers: [{
    answer_id: 1, run_id: 1, problem: ['abc', 'abd', 'ijk'], top_rule_description: 'r', bottom_rule_description: 'r',
    quality: 80, temperature: 10, themes: { 'plato-gone': 'identity' }, top_themes: {}, bottom_themes: {},
    vertical_themes: {}, unjustified_themes: {}, unjustified_slippages: [], has_picture: false,
  }],
  snags: [],
}
const UNRESOLVED = {
  configuration_id: 1, checked: 1,
  unresolved: [{ name: 'plato-gone', configuration_id: 1, resolves: false, kind: null, current_name: null, events: [], restorable: null, text: "the node 'plato-gone' was deleted" }],
}

describe('the names panel on the memory views', () => {
  it('is on a Training Mode Session\'s Memory tab, checked against that session\'s configuration', async () => {
    const calls = serve({
      'GET /training-mode/sessions/4/memory': () => reply(200, MEMORY),
      'GET /configurations': () => reply(200, { configurations: [{ id: 1, session_id: null }, { id: 9, session_id: 4 }] }),
      'POST /journal/check-names': () => reply(200, UNRESOLVED),
    })
    render(<MemoryTab session={{ id: 4, state: 'stopped', activity: null, memory_version: 0 } as unknown as SessionSummary} />)
    const panel = await screen.findByTestId('unresolved-names')
    expect(panel.textContent).toContain("This Training Mode Session's Episodic Memory")
    expect(calls.find(([k]) => k.startsWith('POST'))![1]).toEqual({ configuration_id: 9, names: ['identity', 'plato-gone'] })
  })

  it('is on Metacat Mode\'s Episodic Memory view, checked against the global configuration', async () => {
    const calls = serve({
      'GET /memory': () => reply(200, MEMORY),
      'POST /journal/check-names': () => reply(200, UNRESOLVED),
    })
    render(<MemoryView />)
    const panel = await screen.findByTestId('unresolved-names')
    expect(panel.textContent).toContain("Metacat Mode's Episodic Memory")
    expect((calls.find(([k]) => k.startsWith('POST'))![1] as { configuration_id: number }).configuration_id).toBe(1)
  })
})
