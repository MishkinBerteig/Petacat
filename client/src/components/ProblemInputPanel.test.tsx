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

  it('says a blank seed is a random one and that 0 is invalid, holding no copy of the rules', () => {
    setup({
      runId: null,
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '' },
      reset,
    })

    render(<ProblemInputPanel />)
    expect((screen.getByLabelText(/seed/i) as HTMLInputElement).placeholder).toBe('random')
    expect(screen.getByText(/Blank = a random seed/)).toBeTruthy()
    expect(screen.queryByText(/seed 0/)).toBeNull()
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

describe('ProblemInputPanel — the Answer field is the answer the user gives', () => {
  const withAnswer = (answer: string): WorkspaceState =>
    ({ initial: 'abc', modified: 'abd', target: 'xyz', answer }) as unknown as WorkspaceState

  const blankForm = { initial: '', modified: '', target: '', answer: '', seed: '' }
  const answerField = () => screen.getByLabelText(/answer/i) as HTMLInputElement

  it('leaves Answer empty when the adopted run discovered its answer', () => {
    // The run FOUND xyd; copying that into the field would make the next run, and the
    // Swarm, justify it instead of discovering one.
    setup({ runId: 3, runJustifyMode: false, workspace: withAnswer('xyd'), formInputs: blankForm })

    render(<ProblemInputPanel />)

    expect(answerField().value).toBe('')
    expect(useRunStore.getState().formInputs.target).toBe('xyz')
  })

  it('fills Answer with the given answer when the adopted run was a justification', () => {
    setup({ runId: 4, runJustifyMode: true, workspace: withAnswer('xyd'), formInputs: blankForm })

    render(<ProblemInputPanel />)

    expect(answerField().value).toBe('xyd')
  })

  it('keeps Answer empty when the panel remounts after a discovery run', () => {
    // Returning to the dashboard from Review remounts the panel, which re-adopts the
    // loaded run: the found answer must not leak in on the second pass either.
    setup({ runId: 3, runJustifyMode: false, workspace: withAnswer('xyd'), formInputs: blankForm })

    const first = render(<ProblemInputPanel />)
    first.unmount()
    render(<ProblemInputPanel />)

    expect(answerField().value).toBe('')
    expect(useRunStore.getState().formInputs.answer).toBe('')
  })
})

describe('ProblemInputPanel — a problem string is any text, line breaks included', () => {
  const blank = { initial: '', modified: '', target: '', answer: '', seed: '' }

  it('keeps a pasted line break, spaces and non-Latin text in all four fields', () => {
    const setFormInput = vi.fn()
    setup({ runId: null, workspace: null, formInputs: blank, setFormInput })
    render(<ProblemInputPanel />)
    const values: Record<string, string> = {
      Initial: 'a\nb',
      Modified: ' x  y ',
      Target: '漢字 😀\n',
      'Answer (optional)': 'é\tz',
    }
    const fields: Record<string, string> = {
      Initial: 'initial', Modified: 'modified', Target: 'target', 'Answer (optional)': 'answer',
    }
    for (const [label, value] of Object.entries(values)) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
      expect(setFormInput).toHaveBeenLastCalledWith(fields[label], value)
    }
  })

  it('shows a stored line break in its field, and the fields are one-row text areas', () => {
    setup({ runId: null, workspace: null, formInputs: { ...blank, initial: 'a\nb' } })
    render(<ProblemInputPanel />)
    const el = screen.getByLabelText('Initial') as HTMLTextAreaElement
    expect(el.tagName).toBe('TEXTAREA')
    expect(el.value).toBe('a\nb')
    expect(el.rows).toBe(1)
  })

  it('leaves Enter doing nothing, as in the input it replaces, and lets Shift+Enter through', () => {
    setup({ runId: null, workspace: null, formInputs: blank })
    render(<ProblemInputPanel />)
    const el = screen.getByLabelText('Initial')
    expect(fireEvent.keyDown(el, { key: 'Enter' })).toBe(false) // default prevented
    expect(fireEvent.keyDown(el, { key: 'Enter', shiftKey: true })).toBe(true)
  })
})
