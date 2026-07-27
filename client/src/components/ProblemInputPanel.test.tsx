// ---------------------------------------------------------------------------
// Petacat -- Tests for the problem panel owning the problem's identity
// ---------------------------------------------------------------------------
//
// Reset and Seed used to sit in the Run Controls panel, Reset wedged next to
// "Step N" inside a box labelled "Live Updates" -- next to controls for *how*
// to run rather than *what* to run. Both belong to the problem's identity:
// Reset re-initializes the current run with exactly the strings and seed shown
// here, which is only legible when they sit together.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { ProblemInputPanel } from './ProblemInputPanel'
import { useRunStore } from '@/store/runStore'
import type { WorkspaceState } from '@/types'

vi.mock('@/api/client', () => ({
  getDemos: vi.fn().mockResolvedValue([]),
}))

function workspaceFor(
  initial: string,
  modified: string,
  target: string,
): WorkspaceState {
  return { initial, modified, target, answer: null } as unknown as WorkspaceState
}

const ORIGINAL = useRunStore.getState()

function setup(overrides: Partial<ReturnType<typeof useRunStore.getState>>) {
  useRunStore.setState({ ...ORIGINAL, ...overrides }, true)
}

describe('ProblemInputPanel — problem identity lives here', () => {
  let reset: ReturnType<typeof vi.fn>

  beforeEach(() => {
    reset = vi.fn().mockResolvedValue(undefined)
  })

  it('offers Reset alongside the problem it re-runs', async () => {
    setup({
      runId: 12,
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      reset,
    })

    render(<ProblemInputPanel />)
    fireEvent.click(screen.getByRole('button', { name: /reset to codelet 0/i }))
    await waitFor(() => expect(reset).toHaveBeenCalled())
  })

  it('disables Reset when there is no run to reset', () => {
    setup({
      runId: null,
      workspace: null,
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '' },
      reset,
    })

    render(<ProblemInputPanel />)
    expect(
      (screen.getByRole('button', { name: /reset to codelet 0/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
  })

  it('owns the seed, since Reset preserves it', () => {
    setup({
      runId: 12,
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      reset,
    })

    render(<ProblemInputPanel />)
    expect((screen.getByLabelText(/seed/i) as HTMLInputElement).value).toBe('7')
  })

  it('does not overwrite typed input when the workspace refreshes mid-run', () => {
    // The form adopts a run's problem once, keyed on run id. A later workspace
    // refresh for the *same* run must not stamp the old strings back over an
    // edit in progress -- that was the original "editing does nothing" bug.
    setup({
      runId: 12,
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      reset,
    })

    const { rerender } = render(<ProblemInputPanel />)

    // User retargets the problem.
    fireEvent.change(screen.getByLabelText(/^target$/i), {
      target: { value: 'mrrjjj' },
    })
    expect(useRunStore.getState().formInputs.target).toBe('mrrjjj')

    // A poll for the still-loaded run lands.
    useRunStore.setState({ workspace: workspaceFor('abc', 'abd', 'xyz') })
    rerender(<ProblemInputPanel />)

    expect(useRunStore.getState().formInputs.target).toBe('mrrjjj')
  })
})
