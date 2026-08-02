// ---------------------------------------------------------------------------
// Petacat — the Coderack panel's codelet-pattern clamps
// ---------------------------------------------------------------------------
//
// Clamping a codelet pattern pins a whole line of work at high urgency: a scout
// together with the evaluator and builder that finish what it proposes. MetaCat offers
// the same five on its Options menu, and it is the third of its three manual clamp
// handles, beside Slipnet nodes and themes.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { CoderackView } from './CoderackView'
import { useRunStore } from '@/store/runStore'

const PATTERNS = [
  {
    name: 'rule',
    label: 'Rule codelet pattern',
    entries: [
      { codelet_type: 'rule-scout', urgency_level: 'very_high' },
      { codelet_type: 'rule-builder', urgency_level: 'extremely_high' },
    ],
  },
  {
    name: 'group',
    label: 'Group codelet pattern',
    entries: [{ codelet_type: 'group-builder', urgency_level: 'extremely_high' }],
  },
]

const clampCodeletPattern = vi.fn(async () => undefined)
const unclampCodeletPattern = vi.fn(async () => undefined)

vi.mock('@/api/client', () => ({
  getCodeletPatterns: vi.fn(async () => PATTERNS),
  clampCodeletPattern: (...args: any[]) => clampCodeletPattern(...(args as [])),
  unclampCodeletPattern: (...args: any[]) => unclampCodeletPattern(...(args as [])),
}))

const ORIGINAL = useRunStore.getState()

beforeEach(() => {
  clampCodeletPattern.mockClear()
  unclampCodeletPattern.mockClear()
  useRunStore.setState(
    {
      ...ORIGINAL,
      runId: 5,
      coderack: { total_count: 3, type_counts: { 'rule-scout': 3 } },
    },
    true,
  )
})

afterEach(() => { useRunStore.setState({ ...ORIGINAL }, true) })

describe('CoderackView — clamping a codelet pattern', () => {
  it('offers every pattern the run reports', async () => {
    render(<CoderackView />)

    expect(await screen.findByRole('button', { name: 'Rule' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Group' })).toBeTruthy()
  })

  it('names the codelet types a pattern pins', async () => {
    render(<CoderackView />)

    const rule = await screen.findByRole('button', { name: 'Rule' })
    expect(rule.title).toContain('rule-scout')
    expect(rule.title).toContain('rule-builder')
    expect(rule.title).toContain('2 codelet types')
  })

  it('clamps a pattern when pressed', async () => {
    render(<CoderackView />)

    fireEvent.click(await screen.findByRole('button', { name: 'Rule' }))

    await waitFor(() => expect(clampCodeletPattern).toHaveBeenCalledWith(5, 'rule'))
  })

  it('releases the pattern when pressed a second time', async () => {
    render(<CoderackView />)

    const rule = await screen.findByRole('button', { name: 'Rule' })
    fireEvent.click(rule)
    await waitFor(() => expect(clampCodeletPattern).toHaveBeenCalled())
    fireEvent.click(rule)

    await waitFor(() => expect(unclampCodeletPattern).toHaveBeenCalledWith(5, 'rule'))
  })

  it('releases the previous pattern before clamping another', async () => {
    render(<CoderackView />)

    fireEvent.click(await screen.findByRole('button', { name: 'Rule' }))
    await waitFor(() => expect(clampCodeletPattern).toHaveBeenCalledWith(5, 'rule'))
    fireEvent.click(screen.getByRole('button', { name: 'Group' }))

    await waitFor(() => expect(unclampCodeletPattern).toHaveBeenCalledWith(5, 'rule'))
    expect(clampCodeletPattern).toHaveBeenCalledWith(5, 'group')
  })

  it('offers no clamps without a run', async () => {
    useRunStore.setState({ runId: null })
    render(<CoderackView />)

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Rule' })).toBeNull(),
    )
  })
})
