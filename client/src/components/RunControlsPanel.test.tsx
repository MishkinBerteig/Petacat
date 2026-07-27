// ---------------------------------------------------------------------------
// Petacat -- Tests for starting a run on the problem the form actually shows
// ---------------------------------------------------------------------------
//
// The original bug: every run handler was guarded by `if (!store.runId)`, so a
// run was created only when none existed at all. Once one did, editing a
// string -- or picking a different demo -- and clicking Run silently carried
// on with the *previous* problem. The workspace never changed, which read as
// "the GUI won't reset".
//
// It compounded: ProblemInputPanel re-synced the form from `workspace` on
// every refresh, so the old problem's strings were then stamped back over
// whatever had just been typed.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { RunControlsPanel } from './RunControlsPanel'
import { useRunStore } from '@/store/runStore'
import type { WorkspaceState } from '@/types'

vi.mock('@/api/client', () => ({
  setBreakpoint: vi.fn().mockResolvedValue({}),
  clearBreakpoint: vi.fn().mockResolvedValue({}),
  setSpreadingThreshold: vi.fn().mockResolvedValue({}),
  getSpreadingThreshold: vi
    .fn()
    .mockResolvedValue({ run_id: 1, spreading_activation_threshold: 100 }),
}))

/** Minimal workspace standing in for a loaded run's problem. */
function workspaceFor(
  initial: string,
  modified: string,
  target: string,
): WorkspaceState {
  return {
    initial,
    modified,
    target,
    answer: null,
  } as unknown as WorkspaceState
}

const ORIGINAL = useRunStore.getState()

function setup(overrides: Partial<ReturnType<typeof useRunStore.getState>>) {
  useRunStore.setState({ ...ORIGINAL, ...overrides }, true)
}

describe('RunControlsPanel — which problem a run button acts on', () => {
  let createRun: ReturnType<typeof vi.fn>
  let runToAnswer: ReturnType<typeof vi.fn>

  beforeEach(() => {
    createRun = vi.fn().mockResolvedValue(undefined)
    runToAnswer = vi.fn().mockResolvedValue(undefined)
  })

  it('does not offer Reset — that belongs to the problem panel', () => {
    setup({
      runId: 12,
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    expect(screen.queryByRole('button', { name: /^reset/i })).toBeNull()
  })

  it('creates a run when none exists yet', async () => {
    setup({
      runId: null,
      runParams: null,
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(runToAnswer).toHaveBeenCalled())
    expect(createRun).toHaveBeenCalledWith({
      initial: 'abc',
      modified: 'abd',
      target: 'xyz',
      answer: undefined,
      seed: 7,
    })
  })

  it('reuses the loaded run when the form still shows its problem', async () => {
    setup({
      runId: 12,
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(runToAnswer).toHaveBeenCalled())
    expect(createRun).not.toHaveBeenCalled()
  })

  it('starts a NEW run when the target string was changed', async () => {
    setup({
      runId: 12,
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      // User switched the target to a different problem.
      formInputs: { initial: 'abc', modified: 'abd', target: 'mrrjjj', answer: '', seed: '7' },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() =>
      expect(createRun).toHaveBeenCalledWith({
        initial: 'abc',
        modified: 'abd',
        target: 'mrrjjj',
        answer: undefined,
        seed: 7,
      }),
    )
  })

  it('starts a NEW run when only the seed was changed', async () => {
    setup({
      runId: 12,
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '99' },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() =>
      expect(createRun).toHaveBeenCalledWith(expect.objectContaining({ seed: 99 })),
    )
  })

  it('starts a NEW run when an answer is added, switching to justification mode', async () => {
    setup({
      runId: 12,
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: 'xyd', seed: '7' },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() =>
      expect(createRun).toHaveBeenCalledWith(expect.objectContaining({ answer: 'xyd' })),
    )
  })

  it('warns on screen that the inputs no longer match the loaded run', () => {
    setup({
      runId: 12,
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'mrrjjj', answer: '', seed: '7' },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    expect(screen.getByText(/running starts a new run/i)).toBeTruthy()
  })

  it('reports the loaded run when the form matches it', () => {
    setup({
      runId: 12,
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    expect(screen.getByText(/Showing run #12/)).toBeTruthy()
  })

  it('reuses a history-loaded run, which has no recorded params', async () => {
    setup({
      runId: 12,
      // Loaded via URL hash: the store never saw the creation params.
      runParams: null,
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '' },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(runToAnswer).toHaveBeenCalled())
    expect(createRun).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Run mode is a single mutually-exclusive choice
// ---------------------------------------------------------------------------
//
// "Run to Answer" and "Run with Live Updates" used to be two primary buttons in
// two separate boxes, which read as two unrelated features rather than two
// strategies for the same run. They are now one selector, and each mode shows
// only its own pacing control -- `stepDelay` previously had no control at all,
// while the polling slider sat visible in both modes despite applying to one.

describe('RunControlsPanel — run mode selector', () => {
  let createRun: ReturnType<typeof vi.fn>
  let run: ReturnType<typeof vi.fn>
  let runToAnswer: ReturnType<typeof vi.fn>
  let setLiveUpdate: ReturnType<typeof vi.fn>

  function setupWithRun() {
    createRun = vi.fn().mockResolvedValue(undefined)
    run = vi.fn().mockResolvedValue(undefined)
    runToAnswer = vi.fn().mockResolvedValue(undefined)
    setLiveUpdate = vi.fn()
    setup({
      runId: 12,
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      createRun,
      run,
      runToAnswer,
      setLiveUpdate,
    })
  }

  it('defaults to fast mode and uses the backend run path', async () => {
    setupWithRun()
    render(<RunControlsPanel />)

    expect(
      (screen.getByLabelText(/how to run/i) as HTMLSelectElement).value,
    ).toBe('fast')
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(runToAnswer).toHaveBeenCalled())
    expect(run).not.toHaveBeenCalled()
  })

  it('drives the client-side stepping loop in live mode', async () => {
    setupWithRun()
    render(<RunControlsPanel />)

    fireEvent.change(screen.getByLabelText(/how to run/i), {
      target: { value: 'live' },
    })

    // The action button relabels to match the chosen mode.
    fireEvent.click(screen.getByRole('button', { name: /run with live updates/i }))

    await waitFor(() => expect(run).toHaveBeenCalled())
    expect(runToAnswer).not.toHaveBeenCalled()
    // The selector, not the store default, decides live stepping.
    expect(setLiveUpdate).toHaveBeenCalledWith(true)
  })

  it('shows only the pacing control that applies to the chosen mode', () => {
    setupWithRun()
    render(<RunControlsPanel />)

    // Fast mode is paced by how often the UI samples the engine.
    expect(screen.getByText(/sampling interval/i)).toBeTruthy()
    expect(screen.queryByText(/delay per codelet/i)).toBeNull()

    fireEvent.change(screen.getByLabelText(/how to run/i), {
      target: { value: 'live' },
    })

    // Live mode is paced by the delay between codelets.
    expect(screen.getByText(/delay per codelet/i)).toBeTruthy()
    expect(screen.queryByText(/sampling interval/i)).toBeNull()
  })

  it('keeps manual stepping available regardless of mode', () => {
    setupWithRun()
    render(<RunControlsPanel />)
    expect(screen.getByRole('button', { name: /step 1/i })).toBeTruthy()

    fireEvent.change(screen.getByLabelText(/how to run/i), {
      target: { value: 'live' },
    })
    expect(screen.getByRole('button', { name: /step 1/i })).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// The spreading threshold is a session setting, not per-run state
// ---------------------------------------------------------------------------
//
// It used to live only on the server's in-memory runner. Every new run reverted
// to the default and Reset discarded it, while the slider was disabled until a
// run existed -- so a chosen value usually never reached the run that actually
// executed, and the slider snapping back to 100 was telling the truth about the
// run rather than misreporting it.

describe('RunControlsPanel — spreading threshold persists across runs', () => {
  it('is adjustable before any run exists', () => {
    const setSpreadingThreshold = vi.fn()
    setup({
      runId: null,
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '' },
      setSpreadingThreshold,
    })

    render(<RunControlsPanel />)
    const slider = screen.getByLabelText(/spreading threshold/i) as HTMLInputElement
    expect(slider.disabled).toBe(false)

    fireEvent.change(slider, { target: { value: '40' } })
    expect(setSpreadingThreshold).toHaveBeenCalledWith(40)
  })

  it('shows the session value, not a per-run reset', () => {
    setup({
      runId: 12,
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      spreadingThreshold: 25,
    })

    render(<RunControlsPanel />)
    expect((screen.getByLabelText(/spreading threshold/i) as HTMLInputElement).value).toBe('25')
    expect(screen.getByText(/Spreading threshold: 25/)).toBeTruthy()
  })

  it('marks 100 as the original behaviour', () => {
    setup({ runId: null, spreadingThreshold: 100 })
    render(<RunControlsPanel />)
    expect(screen.getByText(/Spreading threshold: 100 \(original\)/)).toBeTruthy()
  })
})
