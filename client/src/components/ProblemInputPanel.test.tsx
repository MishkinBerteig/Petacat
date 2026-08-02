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

// `describeApiError` comes through as itself: the point of the panel using it is
// that the reset failure is worded like every other failure in the app, and a
// stand-in here would test the stand-in.
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
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

  it('says so when the reset does not complete', async () => {
    // A reset that fails leaves the run as it was, so the panel reports it rather than
    // presenting the run as cleared.
    const failing = vi.fn().mockRejectedValue(new Error('Run 12 not found'))
    setup({
      runId: 12,
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      reset: failing,
    })

    render(<ProblemInputPanel />)
    fireEvent.click(screen.getByRole('button', { name: /reset to codelet 0/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('Run 12 not found')
    })
  })

  it('reports a refused reset in the words the rest of the app uses', async () => {
    // The status is the reader's next move — a run that no longer exists calls for a
    // new run, not a retry — so the message carries it alongside the server's detail.
    const { ApiError } = await import('@/api/client')
    const failing = vi
      .fn()
      .mockRejectedValue(new ApiError(404, 'Not Found', '{"detail":"Run 12 not found"}'))
    setup({
      runId: 12,
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      reset: failing,
    })

    render(<ProblemInputPanel />)
    fireEvent.click(screen.getByRole('button', { name: /reset to codelet 0/i }))

    await waitFor(() => {
      const text = screen.getByRole('alert').textContent ?? ''
      expect(text).toContain('Could not reset the run')
      expect(text).toContain('it no longer exists')
      expect(text).toContain('Run 12 not found')
    })
  })

  it('clears the failure notice once a reset completes', async () => {
    const failing = vi.fn().mockRejectedValueOnce(new Error('Run 12 not found'))
      .mockResolvedValue(undefined)
    setup({
      runId: 12,
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      reset: failing,
    })

    render(<ProblemInputPanel />)
    const button = screen.getByRole('button', { name: /reset to codelet 0/i })

    fireEvent.click(button)
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())

    fireEvent.click(button)
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
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
