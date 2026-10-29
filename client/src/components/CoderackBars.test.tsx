/**
 * The Coderack window as Metacat draws it (`coderack-graphics.ss`): a slot per codelet
 * type with its count, a bar for its selection probability, the last-run type marked,
 * clamped types shaded, and the two switches from the Options menu. The bar is the
 * engine's figure; nothing here derives one from a type's name.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { CoderackBars, CoderackView } from './CoderackView'
import { useRunStore } from '@/store/runStore'
import type { CoderackState } from '@/types'

vi.mock('@/api/client', () => ({
  getCodeletPatterns: vi.fn(async () => []),
  clampCodeletPattern: vi.fn(),
  unclampCodeletPattern: vi.fn(),
}))

const STATE: CoderackState = {
  total_count: 6,
  type_counts: { 'bond-evaluator': 4, 'breaker': 1, 'rule-scout': 1 },
  type_probabilities: { 'bond-evaluator': 0.5, 'breaker': 0.1, 'rule-scout': 0.4 },
  last_codelet_type: 'breaker',
  codelet_types: ['rule-scout', 'bond-evaluator', 'breaker', 'answer-finder'],
  clamped_urgencies: { 'rule-scout': 91 },
}

const ORIGINAL = useRunStore.getState()
beforeEach(() => {
  useRunStore.setState({ ...ORIGINAL, runId: null, coderack: STATE }, true)
})

describe('CoderackBars', () => {
  it('has a slot for every codelet type, in the engine order, empty ones too', () => {
    render(<CoderackBars coderack={STATE} />)
    const rows = screen.getAllByTestId(/^coderack-row-/).map((r) => r.getAttribute('data-testid'))
    expect(rows).toEqual([
      'coderack-row-rule-scout',
      'coderack-row-bond-evaluator',
      'coderack-row-breaker',
      'coderack-row-answer-finder',
    ])
  })

  it("draws each bar at the engine's selection probability", () => {
    render(<CoderackBars coderack={STATE} />)
    expect(screen.getByTestId('coderack-bar-bond-evaluator').style.width).toBe('50%')
    expect(screen.getByTestId('coderack-bar-rule-scout').style.width).toBe('40%')
    expect(screen.getByTestId('coderack-bar-breaker').style.width).toBe('10%')
    // No codelets, no probability, no bar.
    expect(screen.queryByTestId('coderack-bar-answer-finder')).toBeNull()
  })

  it('does not colour or size anything from the type name', () => {
    // Same counts, probabilities swapped between two types of very different names.
    const swapped = {
      ...STATE,
      type_probabilities: { 'bond-evaluator': 0.1, 'breaker': 0.5, 'rule-scout': 0.4 },
    }
    render(<CoderackBars coderack={swapped} />)
    expect(screen.getByTestId('coderack-bar-breaker').style.width).toBe('50%')
    expect(screen.getByTestId('coderack-bar-bond-evaluator').style.width).toBe('10%')
  })

  it('shows the counts and the total, headed Selection Probability', () => {
    render(<CoderackBars coderack={STATE} />)
    expect(screen.getByText('Selection Probability')).toBeTruthy()
    expect(screen.getByText('Codelet Type')).toBeTruthy()
    expect(screen.getByText('Total')).toBeTruthy()
    expect(screen.getByText('6')).toBeTruthy()
    expect(screen.getByText('4')).toBeTruthy()
  })

  it('marks the last codelet type that ran', () => {
    render(<CoderackBars coderack={STATE} />)
    expect(screen.getByTestId('coderack-row-breaker').getAttribute('data-last')).toBe('true')
    expect(screen.getByTestId('coderack-row-rule-scout').getAttribute('data-last')).toBeNull()
  })

  it('can hide the counts and the last-type marker', () => {
    render(<CoderackBars coderack={STATE} showCounts={false} showLast={false} />)
    expect(screen.queryByText('Total')).toBeNull()
    expect(screen.getByTestId('coderack-row-breaker').getAttribute('data-last')).toBeNull()
  })

  it('still draws a recorded coderack that carries no probabilities', () => {
    render(<CoderackBars coderack={{ total_count: 2, type_counts: { b: 2 } }} />)
    expect(screen.getByTestId('coderack-row-b')).toBeTruthy()
  })
})

describe('CoderackView — Metacat\'s Options-menu switches', () => {
  it('toggles the count column with "Show codelet counts"', () => {
    render(<CoderackView />)
    expect(screen.getByText('Total')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('Show codelet counts'))
    expect(screen.queryByText('Total')).toBeNull()
  })

  it('toggles the pink marker with "Show last codelet type"', () => {
    render(<CoderackView />)
    fireEvent.click(screen.getByLabelText('Show last codelet type'))
    expect(screen.getByTestId('coderack-row-breaker').getAttribute('data-last')).toBeNull()
  })
})
