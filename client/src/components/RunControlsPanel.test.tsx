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
import { ApiError, getRunIdentity, setBreakpoint } from '@/api/client'
import type { WorkspaceState } from '@/types'

// `ApiError` and `describeApiError` come through as themselves: the panel's failure
// messages are the shared ones, and asserting on a stand-in would prove nothing.
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  setBreakpoint: vi.fn().mockResolvedValue({}),
  clearBreakpoint: vi.fn().mockResolvedValue({}),
  setSpreadingThreshold: vi.fn().mockResolvedValue({}),
  getSpreadingThreshold: vi
    .fn()
    .mockResolvedValue({ run_id: 1, spreading_activation_threshold: 100 }),
  getRunIdentity: vi.fn().mockResolvedValue({
    run_id: 12,
    mode: 'normal',
    recorded: true,
    seed: 7,
    spreading_threshold: 100,
    config_hash: 'c0ffee1234567890',
    memory_hash: 'deadbeef12345678',
    session_id: 3,
    created_at: null,
  }),
  // The panel now mounts the parameter form and the derived read-out, both of which
  // fetch on mount. Stubbed rather than left out so a fetch failure in an unrelated
  // test reads as a failure of the thing under test.
  getParameterCatalogue: vi.fn().mockResolvedValue([
    {
      name: 'update_cycle_length',
      kind: 'int',
      group: 'Temperature and pacing',
      label: 'Update cycle length',
      description: 'How many codelets run between full recomputations.',
      minimum: 1,
      maximum: 1000,
      departs_from_original: true,
      default: 15,
    },
    {
      name: 'self_watching_enabled_default',
      kind: 'bool',
      group: 'Self-watching',
      label: 'Self-watching enabled',
      description: 'Whether the Themespace, progress-watchers and jootsers run.',
      minimum: null,
      maximum: null,
      departs_from_original: true,
      default: true,
    },
  ]),
  getRunParameters: vi.fn().mockResolvedValue({
    run_id: 12,
    fixed: { update_cycle_length: 15 },
    overridden: [],
    defaults: { update_cycle_length: 15 },
    derived: { mode: 'normal', workers: 1 },
  }),
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
// The execution strategy is a single mutually-exclusive choice
// ---------------------------------------------------------------------------
//
// "Run to Answer" and "Run with Live Updates" used to be two primary buttons in
// two separate boxes, which read as two unrelated features rather than two
// strategies for the same run. They are now one selector, and each strategy shows
// only its own pacing control -- `stepDelay` previously had no control at all,
// while the polling slider sat visible in both modes despite applying to one.
//
// The strategy's `fast` value was renamed `batch` when Phase 0 introduced a
// persistence mode also called Fast. They are unrelated, and two things in one
// panel answering to one name is how a reader ends up believing that watching a
// run more slowly changes what it records.

describe('RunControlsPanel — execution strategy selector', () => {
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

  it('defaults to batch execution and uses the backend run path', async () => {
    setupWithRun()
    render(<RunControlsPanel />)

    expect(
      (screen.getByLabelText(/how to run/i) as HTMLSelectElement).value,
    ).toBe('batch')
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

  it('shows only the pacing control that applies to the chosen strategy', () => {
    setupWithRun()
    render(<RunControlsPanel />)

    // Batch execution is paced by how often the UI samples the engine.
    expect(screen.getByText(/sampling interval/i)).toBeTruthy()
    expect(screen.queryByText(/delay per codelet/i)).toBeNull()

    fireEvent.change(screen.getByLabelText(/how to run/i), {
      target: { value: 'live' },
    })

    // Live mode is paced by the delay between codelets.
    expect(screen.getByText(/delay per codelet/i)).toBeTruthy()
    expect(screen.queryByText(/sampling interval/i)).toBeNull()
  })

  it('keeps manual stepping available regardless of strategy', () => {
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
// The spreading threshold slider reports the run on screen
// ---------------------------------------------------------------------------
//
// The threshold decides which Slipnet nodes spread activation, so the slider shows
// the value the loaded run is executing with, and moving it changes that run. With
// no run loaded it shows the value the next run will be created with, so the
// setting is adjustable from the moment the page opens.

describe('RunControlsPanel — spreading threshold reflects the loaded run', () => {
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

  it('shows the value the loaded run is executing with', () => {
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

  it('sends the moved-to value, so the run on screen changes', () => {
    const setSpreadingThreshold = vi.fn()
    setup({
      runId: 12,
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      spreadingThreshold: 30,
      setSpreadingThreshold,
    })

    render(<RunControlsPanel />)
    fireEvent.change(screen.getByLabelText(/spreading threshold/i), {
      target: { value: '45' },
    })

    expect(setSpreadingThreshold).toHaveBeenCalledWith(45)
  })
})

// ---------------------------------------------------------------------------
// Persistence mode -- what the run writes down (Phase 0 §A2)
// ---------------------------------------------------------------------------
//
// Three claims, each with a plausible wrong version:
//
//   1. The mode reaches the run. The wrong version renders a selector that changes
//      a local value the create request never sees, so every run is Normal and the
//      user cannot tell because Normal is also what they would have got.
//   2. Changing the mode starts a NEW run. Mode is fixed at creation, so the wrong
//      version silently carries on with the run that is already loaded -- and the
//      audit record the reader switched modes for does not exist afterwards.
//   3. Fast's consequences are stated before the run, not discovered after it.
//      Its absence from Run History is the mode working, and looks like a bug.

describe('RunControlsPanel — persistence mode', () => {
  function setupFor(
    persistenceMode: 'fast' | 'normal' | 'audit',
    overrides: Partial<ReturnType<typeof useRunStore.getState>> = {},
  ) {
    const createRun = vi.fn().mockResolvedValue(undefined)
    const runToAnswer = vi.fn().mockResolvedValue(undefined)
    const setPersistenceMode = vi.fn()
    setup({
      persistenceMode,
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      createRun,
      runToAnswer,
      setPersistenceMode,
      ...overrides,
    })
    return { createRun, runToAnswer, setPersistenceMode }
  }

  it('defaults to normal — the mode whose promise is hardest to be disappointed by', () => {
    setupFor('normal', { runId: null })
    render(<RunControlsPanel />)
    expect(
      (screen.getByLabelText(/what the run writes down/i) as HTMLSelectElement).value,
    ).toBe('normal')
  })

  it('is selectable before any run exists', () => {
    const { setPersistenceMode } = setupFor('normal', { runId: null })
    render(<RunControlsPanel />)

    fireEvent.change(screen.getByLabelText(/what the run writes down/i), {
      target: { value: 'audit' },
    })
    expect(setPersistenceMode).toHaveBeenCalledWith('audit')
  })

  it('sends the chosen mode with the create, since it selects the sink', async () => {
    const { createRun, runToAnswer } = setupFor('audit', { runId: null })
    render(<RunControlsPanel />)

    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))
    await waitFor(() => expect(runToAnswer).toHaveBeenCalled())
    // The store's createRun attaches the mode; the panel's job is to have asked
    // for a new run at all, which is claim 2 below.
    expect(createRun).toHaveBeenCalled()
  })

  it('starts a NEW run when only the mode was changed', async () => {
    // Same problem, same seed, loaded run is Normal, the selector now says Audit.
    const { createRun, runToAnswer } = setupFor('audit', {
      runId: 12,
      runMode: 'normal',
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
    })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(runToAnswer).toHaveBeenCalled())
    expect(createRun).toHaveBeenCalledWith(
      expect.objectContaining({ initial: 'abc', target: 'xyz', seed: 7 }),
    )
  })

  it('says on screen that a mode change will start a new run', () => {
    setupFor('audit', {
      runId: 12,
      runMode: 'normal',
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
    })

    render(<RunControlsPanel />)
    expect(screen.getByText(/Recording mode differs from run #12/)).toBeTruthy()
  })

  it('reuses the loaded run when the mode matches it', async () => {
    const { createRun, runToAnswer } = setupFor('normal', {
      runId: 12,
      runMode: 'normal',
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
    })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(runToAnswer).toHaveBeenCalled())
    expect(createRun).not.toHaveBeenCalled()
  })

  it('reuses a run whose mode the store never learned', async () => {
    // Adopted from a URL hash before modes were reported. Refusing to reuse it on
    // the strength of a value we do not have would be worse than the odd wrong guess.
    const { createRun, runToAnswer } = setupFor('audit', {
      runId: 12,
      runMode: null,
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
    })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(runToAnswer).toHaveBeenCalled())
    expect(createRun).not.toHaveBeenCalled()
  })

  it('warns what Fast costs before the run rather than after it', () => {
    setupFor('fast', { runId: null })
    render(<RunControlsPanel />)
    expect(screen.getByText(/no row in Run History/i)).toBeTruthy()
  })

  it('does not warn about Fast when Fast is not selected', () => {
    setupFor('normal', { runId: null })
    render(<RunControlsPanel />)
    expect(screen.queryByText(/no row in Run History/i)).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// A live run's identity -- which config and which memory it ran against
// ---------------------------------------------------------------------------
//
// The Review browser shows these, but by the time a reader is in the Review
// browser the run they were watching is over. A Fast Run has no row and so no
// hashes, and that has to read as the mode keeping its promise rather than as a
// failed lookup.

describe('RunControlsPanel — run identity', () => {
  it('shows the config and memory hashes of the loaded run', async () => {
    setup({
      runId: 12,
      runMode: 'normal',
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
    })

    render(<RunControlsPanel />)
    await waitFor(() => expect(screen.getByText(/cfg c0ffee12/)).toBeTruthy())
    expect(screen.getByText(/mem deadbeef/)).toBeTruthy()
    expect(screen.getByText(/Training Session 3/)).toBeTruthy()
  })

  it('explains, rather than blanks, a Fast Run that has no recorded identity', async () => {
    vi.mocked(getRunIdentity).mockResolvedValueOnce({
      run_id: -1,
      mode: 'fast',
      recorded: false,
      seed: null,
      spreading_threshold: 100,
      config_hash: null,
      memory_hash: null,
      session_id: null,
      created_at: null,
    })

    setup({
      runId: -1,
      runMode: 'fast',
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      persistenceMode: 'fast',
    })

    render(<RunControlsPanel />)
    await waitFor(() =>
      expect(screen.getByText(/Not recorded — a Fast Run has no database row/)).toBeTruthy(),
    )
  })

  it('still explains a Fast Run when the identity lookup itself is unreachable', async () => {
    // Not hypothetical: the identity endpoint needs a database session, and a Fast
    // Run is required to complete with Postgres stopped. The mode is already known
    // from the creation response, so the explanation does not depend on the lookup.
    vi.mocked(getRunIdentity).mockRejectedValueOnce(new Error('API 500'))

    setup({
      runId: -1,
      runMode: 'fast',
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      persistenceMode: 'fast',
    })

    render(<RunControlsPanel />)
    await waitFor(() =>
      expect(screen.getByText(/Not recorded — a Fast Run has no database row/)).toBeTruthy(),
    )
  })
})

// ---------------------------------------------------------------------------
// Worker count and engine parameters — the other two things fixed at creation
// ---------------------------------------------------------------------------
//
// Both behave exactly as the persistence mode does, and for the same reason: the
// engine reads them before the first codelet, so changing one cannot apply to a run
// that has already begun. The wrong version carries on with the old run and the
// reader gets a run that is not the experiment they set up.

describe('RunControlsPanel — worker count', () => {
  let createRun: ReturnType<typeof vi.fn>
  let runToAnswer: ReturnType<typeof vi.fn>

  beforeEach(() => {
    createRun = vi.fn().mockResolvedValue(undefined)
    runToAnswer = vi.fn().mockResolvedValue(undefined)
  })

  const LOADED = {
    runId: 12,
    runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
    workspace: workspaceFor('abc', 'abd', 'xyz'),
    formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
  }

  it('defaults to the serial loop and says that is the reference mode', () => {
    setup({ ...LOADED, createRun, runToAnswer })

    render(<RunControlsPanel />)
    expect(screen.getByLabelText(/Workers/)).toHaveValue(1)
    expect(
      screen.getByText(/The same problem and seed reproduce the run exactly/),
    ).toBeTruthy()
  })

  it('starts a NEW run when the worker count was changed', async () => {
    setup({ ...LOADED, runWorkers: 1, workers: 4, createRun, runToAnswer })

    render(<RunControlsPanel />)
    expect(screen.getByText(/Worker count differs from run #12/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))
    await waitFor(() => expect(createRun).toHaveBeenCalled())
  })

  it('reuses the loaded run when the worker count matches it', async () => {
    setup({ ...LOADED, runWorkers: 4, workers: 4, createRun, runToAnswer })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(runToAnswer).toHaveBeenCalled())
    expect(createRun).not.toHaveBeenCalled()
  })

  it('refuses free-running under Audit rather than letting the request 400', () => {
    // Audit reconstructs states by replaying its log forward, and under free-running
    // that log does not record the order things happened in — so the backend rejects
    // anything above 1. The control has to say so, not discover it.
    setup({ ...LOADED, workers: 4, persistenceMode: 'audit', createRun, runToAnswer })

    render(<RunControlsPanel />)
    const input = screen.getByLabelText(/Workers/)
    expect(input).toBeDisabled()
    expect(input).toHaveValue(1)
    expect(screen.getByText(/Audit is serial by definition/)).toBeTruthy()
  })
})

describe('RunControlsPanel — engine parameters', () => {
  let createRun: ReturnType<typeof vi.fn>
  let runToAnswer: ReturnType<typeof vi.fn>

  beforeEach(() => {
    createRun = vi.fn().mockResolvedValue(undefined)
    runToAnswer = vi.fn().mockResolvedValue(undefined)
  })

  const LOADED = {
    runId: 12,
    runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
    workspace: workspaceFor('abc', 'abd', 'xyz'),
    formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
  }

  it('starts a NEW run when a parameter was changed', async () => {
    setup({
      ...LOADED,
      runParameterOverrides: {},
      parameterOverrides: { update_cycle_length: 40 },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    expect(screen.getByText(/Engine parameters differ from run #12/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))
    await waitFor(() => expect(createRun).toHaveBeenCalled())
  })

  it('reuses the loaded run when the parameters match it', async () => {
    setup({
      ...LOADED,
      runParameterOverrides: { update_cycle_length: 40 },
      parameterOverrides: { update_cycle_length: 40 },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(runToAnswer).toHaveBeenCalled())
    expect(createRun).not.toHaveBeenCalled()
  })

  it('refuses to run at all while a parameter is outside the server\'s range', async () => {
    setup({
      ...LOADED,
      parameterOverrides: { update_cycle_length: 5000 },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    // The catalogue arrives asynchronously; until it does there are no bounds to
    // check against, so the refusal appears with it.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /run to answer/i })).toBeDisabled(),
    )
    expect(screen.getByText(/must be at most 1000/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))
    expect(createRun).not.toHaveBeenCalled()
    expect(runToAnswer).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Failures the run controls cause are reported, not swallowed
// ---------------------------------------------------------------------------
//
// Every button here starts something on the server, and each one used to drop its
// failure on the floor: a run that could not be created looked exactly like a run
// that was created and had not moved yet, and a breakpoint the server refused looked
// exactly like a breakpoint that was set and never reached.

describe('RunControlsPanel — a refused request reaches the error channel', () => {
  const LOADED = {
    runId: 12,
    runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
    workspace: workspaceFor('abc', 'abd', 'xyz'),
    formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
  }

  it('does not start running when the run could not be created', async () => {
    // The store reports the failure and raises; the panel stops rather than asking a
    // run that does not exist to execute.
    const createRun = vi.fn().mockRejectedValue(new ApiError(422, 'Unprocessable Entity', ''))
    const runToAnswer = vi.fn().mockResolvedValue(undefined)
    setup({
      runId: null,
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(createRun).toHaveBeenCalled())
    expect(runToAnswer).not.toHaveBeenCalled()
  })

  it('says why a breakpoint was refused, since it will not stop the run', async () => {
    vi.mocked(setBreakpoint).mockRejectedValueOnce(
      new ApiError(404, 'Not Found', '{"detail":"Run 12 not found"}'),
    )
    setup(LOADED)

    render(<RunControlsPanel />)
    fireEvent.change(screen.getByLabelText(/breakpoint/i), { target: { value: '250' } })
    fireEvent.click(screen.getByRole('button', { name: /^set$/i }))

    await waitFor(() => {
      const message = useRunStore.getState().lastError ?? ''
      expect(message).toContain('set the breakpoint')
      expect(message).toContain('Run 12 not found')
    })
  })

  it('clears the channel once a breakpoint is accepted', async () => {
    setup({ ...LOADED, lastError: 'Could not set the breakpoint: it no longer exists.' })

    render(<RunControlsPanel />)
    fireEvent.change(screen.getByLabelText(/breakpoint/i), { target: { value: '250' } })
    fireEvent.click(screen.getByRole('button', { name: /^set$/i }))

    await waitFor(() => expect(useRunStore.getState().lastError).toBeNull())
  })
})

// ---------------------------------------------------------------------------
// A finished run is not continued — it is followed
// ---------------------------------------------------------------------------
//
// Repeating a problem is the whole point of a Training Session: Episodic Memory
// carries the first run's answer into the second, which declines to give it again
// and goes somewhere else. Pressing Run twice on an unchanged problem used to
// re-enter the finished run instead -- the backend puts its status back to
// `running` and steps it on past its own answer, in the same row -- so the second
// run of a session could not be started from this panel at all, and the only
// workaround was to change the seed, which makes it a different experiment.
//
// Halted and paused are not terminal and must keep continuing, or Stop-then-Run
// would silently abandon the run it was meant to resume.

describe('RunControlsPanel — a finished run is followed by a new one', () => {
  let createRun: ReturnType<typeof vi.fn>
  let runToAnswer: ReturnType<typeof vi.fn>

  const SAME_PROBLEM = {
    runId: 12,
    runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
    workspace: workspaceFor('abc', 'abd', 'xyz'),
    formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
  }

  beforeEach(() => {
    createRun = vi.fn().mockResolvedValue(undefined)
    runToAnswer = vi.fn().mockResolvedValue(undefined)
  })

  it('starts a NEW run when the loaded one has found its answer', async () => {
    setup({ ...SAME_PROBLEM, status: 'answer_found', createRun, runToAnswer })

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

  it('starts a NEW run when the loaded one gave up', async () => {
    setup({ ...SAME_PROBLEM, status: 'gave_up', createRun, runToAnswer })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(createRun).toHaveBeenCalled())
  })

  it('continues a paused run rather than abandoning it', async () => {
    setup({ ...SAME_PROBLEM, status: 'paused', createRun, runToAnswer })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(runToAnswer).toHaveBeenCalled())
    expect(createRun).not.toHaveBeenCalled()
  })

  it('continues a halted run — the step limit is not an outcome', async () => {
    setup({ ...SAME_PROBLEM, status: 'halted', createRun, runToAnswer })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run to answer/i }))

    await waitFor(() => expect(runToAnswer).toHaveBeenCalled())
    expect(createRun).not.toHaveBeenCalled()
  })

  it('says the next press begins the next run of the session', () => {
    setup({ ...SAME_PROBLEM, status: 'answer_found', createRun, runToAnswer })

    render(<RunControlsPanel />)
    expect(
      screen.getByText(/starts the next run of this Training Session/i),
    ).toBeTruthy()
    // And not the caption that reads as "this is what you are looking at".
    expect(screen.queryByText(/Showing run #12/)).toBeNull()
  })

  it('steps into a new run too, rather than stepping a finished one on', async () => {
    const step = vi.fn().mockResolvedValue(undefined)
    setup({ ...SAME_PROBLEM, status: 'answer_found', createRun, runToAnswer, step })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /step 1/i }))

    await waitFor(() => expect(step).toHaveBeenCalledWith(1))
    expect(createRun).toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Nothing starts a second run while one is under way
// ---------------------------------------------------------------------------
//
// `status === 'running'` alone does not cover it. Creating a run is a round trip,
// and inside that window nothing in the store says a run was asked for -- so a
// second click starts a second run and orphans the first. Stop is the one control
// that has to stay live throughout, and it was the one that did not: it was gated
// on `isProcessing`, which run-to-answer holds for the whole of a batch run.

describe('RunControlsPanel — while a run is under way', () => {
  const LOADED = {
    runId: 12,
    runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
    workspace: workspaceFor('abc', 'abd', 'xyz'),
    formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
  }

  it('disables Run while the engine reports itself running', () => {
    setup({ ...LOADED, status: 'running' })

    render(<RunControlsPanel />)
    expect(screen.getByRole('button', { name: /run to answer/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /step 1/i })).toBeDisabled()
  })

  it('disables Run from the press, before the run exists to report itself', async () => {
    // The gap the status flag cannot cover: createRun is in flight.
    const createRun = vi.fn().mockReturnValue(new Promise(() => {}))
    const runToAnswer = vi.fn().mockResolvedValue(undefined)
    setup({
      runId: null,
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
      createRun,
      runToAnswer,
    })

    render(<RunControlsPanel />)
    const button = screen.getByRole('button', { name: /run to answer/i })
    fireEvent.click(button)

    await waitFor(() => expect(button).toBeDisabled())
    fireEvent.click(button)
    expect(createRun).toHaveBeenCalledTimes(1)
  })

  it('keeps Stop available through a batch run, which is when it is needed', () => {
    // run-to-answer holds `isProcessing` for the whole run, so gating Stop on it
    // disabled the only way out from the moment the run started.
    setup({ ...LOADED, status: 'running', isProcessing: true })

    render(<RunControlsPanel />)
    expect(screen.getByRole('button', { name: /^stop$/i })).not.toBeDisabled()
  })

  it('leaves Stop disabled when nothing is running', () => {
    setup({ ...LOADED, status: 'answer_found' })

    render(<RunControlsPanel />)
    expect(screen.getByRole('button', { name: /^stop$/i })).toBeDisabled()
  })
})

// ---------------------------------------------------------------------------
// Starting the next Training Session
// ---------------------------------------------------------------------------
//
// A session is the unit runs accumulate into, and its boundary was reachable only
// from the Admin view under a name that says what it removes ("Clear Episodic
// Memory") rather than what it ends. So the unit could be read about in Review and
// never started from the panel whose Run button builds it.

describe('RunControlsPanel — Training Session', () => {
  const LOADED = {
    runId: 12,
    runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
    workspace: workspaceFor('abc', 'abd', 'xyz'),
    formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
  }

  it('names the session the loaded run belongs to', async () => {
    setup(LOADED)
    render(<RunControlsPanel />)
    // Exact, because the run card further down says "Training Session 3" as well.
    await waitFor(() => expect(screen.getByText('session 3')).toBeTruthy())
  })

  it('ends the session on confirmation, since that is what the boundary is', async () => {
    const startNewTrainingSession = vi.fn().mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    setup({ ...LOADED, startNewTrainingSession })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /start a new training session/i }))

    await waitFor(() => expect(startNewTrainingSession).toHaveBeenCalled())
    expect(
      await screen.findByText(/the next run opens a new one/i),
    ).toBeTruthy()
  })

  it('does nothing when the confirmation is declined', () => {
    const startNewTrainingSession = vi.fn().mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    setup({ ...LOADED, startNewTrainingSession })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /start a new training session/i }))

    expect(startNewTrainingSession).not.toHaveBeenCalled()
  })

  it('does not claim a new session when the clear was refused', async () => {
    // The store reports the failure on the channel the header renders; claiming a
    // boundary here as well would contradict it — and the old session is still open.
    const startNewTrainingSession = vi
      .fn()
      .mockRejectedValue(new ApiError(503, 'Service Unavailable', ''))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    setup({ ...LOADED, startNewTrainingSession })

    render(<RunControlsPanel />)
    fireEvent.click(screen.getByRole('button', { name: /start a new training session/i }))

    await waitFor(() => expect(startNewTrainingSession).toHaveBeenCalled())
    expect(screen.queryByText(/the next run opens a new one/i)).toBeNull()
  })

  it('refuses to draw a session boundary in the middle of a run', () => {
    setup({ ...LOADED, status: 'running' })

    render(<RunControlsPanel />)
    expect(
      screen.getByRole('button', { name: /start a new training session/i }),
    ).toBeDisabled()
  })
})

describe('RunControlsPanel — reaching the record of the run on screen', () => {
  it('offers a route from the dashboard into the Review browser', async () => {
    setup({
      runId: 12,
      runParams: { initial: 'abc', modified: 'abd', target: 'xyz', seed: 7 },
      workspace: workspaceFor('abc', 'abd', 'xyz'),
      formInputs: { initial: 'abc', modified: 'abd', target: 'xyz', answer: '', seed: '7' },
    })

    render(<RunControlsPanel />)
    const link = await screen.findByRole('button', { name: /Review this run/i })
    fireEvent.click(link)
    expect(window.location.hash).toBe('#/review/runs/12')
  })
})
