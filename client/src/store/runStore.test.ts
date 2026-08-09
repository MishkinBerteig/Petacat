// ---------------------------------------------------------------------------
// Petacat -- Tests for the spreading threshold outliving a page reload
// ---------------------------------------------------------------------------
//
// The threshold changes what a run does, so it is a fundamental parameter rather
// than a transient UI preference. It used to live only on the server's in-memory
// runner: it vanished on restart, every new run silently reverted to the
// default, and nothing reading the database could tell what a run had used.
//
// Two halves, tested here and in the API tests respectively:
//   - the *chosen* value survives a reload (localStorage) and is sent with each
//     new run, so the engine is initialised with it;
//   - the *used* value is recorded on the run row (see the e2e tests).
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import type { RunInfo } from '@/types'

const STORAGE_KEY = 'petacat.spreadingThreshold'

const createRun = vi.fn().mockResolvedValue({
  run_id: 1,
  status: 'initialized',
  codelet_count: 0,
  temperature: 100,
  initial: 'abc',
  modified: 'abd',
  target: 'xyz',
  answer: null,
})

const getRunMemory = vi
  .fn()
  .mockResolvedValue({ answers: [], snags: [], scope: 'live', mode: 'fast' })

/**
 * Declared outside the module factory, like `createRun` above, so the same handle
 * keeps recording calls across the module resets `freshStore` performs.
 */
const setSpreadingThresholdCall = vi.fn().mockResolvedValue({})

/** The clear-out the Admin panel asks for: every run, then the shared memory. */
const deleteAllRuns = vi.fn().mockResolvedValue({ deleted_count: 0 })
const clearMemory = vi.fn().mockResolvedValue({ cleared: true, removed: 0 })

// `ApiError` and `describeApiError` come through as themselves. They are the shared
// vocabulary the store reports failures in, so the tests below assert on the real
// sentences a user would read rather than on a stand-in.
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  createRun: (...args: unknown[]) => createRun(...args),
  getRun: vi.fn(),
  stepRun: vi.fn(),
  runToCompletion: vi.fn(),
  stopRun: vi.fn(),
  resetRun: vi.fn(),
  deleteRun: vi.fn(),
  getWorkspace: vi.fn().mockResolvedValue(null),
  getSlipnet: vi.fn().mockResolvedValue(null),
  getCoderack: vi.fn().mockResolvedValue(null),
  getThemespace: vi.fn().mockResolvedValue(null),
  getTrace: vi.fn().mockResolvedValue([]),
  getTemperature: vi.fn().mockResolvedValue({
    run_id: 1,
    temperature: 100,
    clamped: false,
    clamp_value: 0,
    clamp_cycles_remaining: 0,
  }),
  getCommentary: vi.fn().mockResolvedValue({ commentary: '' }),
  getMemory: vi.fn().mockResolvedValue({ answers: [], snags: [] }),
  getRunMemory: (...args: unknown[]) => getRunMemory(...args),
  setSpreadingThreshold: (...args: unknown[]) => setSpreadingThresholdCall(...args),
  deleteAllRuns: (...args: unknown[]) => deleteAllRuns(...args),
  clearMemory: (...args: unknown[]) => clearMemory(...args),
}))

/**
 * A deterministic in-memory localStorage.
 *
 * Node 26 ships its own experimental `localStorage` that is inert without a
 * backing file, and it shadows jsdom's. Installing an explicit stub keeps this
 * test about the store's behaviour rather than about which implementation the
 * environment happened to supply.
 */
function installStorage(): void {
  let data: Record<string, string> = {}
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (k: string) => (k in data ? data[k] : null),
      setItem: (k: string, v: string) => { data[k] = String(v) },
      removeItem: (k: string) => { delete data[k] },
      clear: () => { data = {} },
      key: (i: number) => Object.keys(data)[i] ?? null,
      get length() { return Object.keys(data).length },
    },
  })
}

/** Fresh module instance, so the store re-reads storage at import time. */
async function freshStore() {
  vi.resetModules()
  return (await import('./runStore')).useRunStore
}

beforeEach(() => {
  createRun.mockClear()
  getRunMemory.mockClear()
  setSpreadingThresholdCall.mockClear()
  deleteAllRuns.mockClear()
  clearMemory.mockClear()
  installStorage()
})

afterEach(() => {
  window.localStorage.clear()
})

describe('runStore — spreading threshold persistence', () => {
  it('defaults to 100, the original behaviour', async () => {
    const useRunStore = await freshStore()
    expect(useRunStore.getState().spreadingThreshold).toBe(100)
  })

  it('writes the chosen value to storage', async () => {
    const useRunStore = await freshStore()
    await useRunStore.getState().setSpreadingThreshold(35)
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('35')
    expect(useRunStore.getState().spreadingThreshold).toBe(35)
  })

  it('reads it back on a fresh load, as after a page reload', async () => {
    window.localStorage.setItem(STORAGE_KEY, '20')
    const useRunStore = await freshStore()
    expect(useRunStore.getState().spreadingThreshold).toBe(20)
  })

  it('clamps to 0-100 and ignores junk in storage', async () => {
    window.localStorage.setItem(STORAGE_KEY, 'not-a-number')
    let useRunStore = await freshStore()
    expect(useRunStore.getState().spreadingThreshold).toBe(100)

    useRunStore = await freshStore()
    await useRunStore.getState().setSpreadingThreshold(999)
    expect(useRunStore.getState().spreadingThreshold).toBe(100)
    await useRunStore.getState().setSpreadingThreshold(-5)
    expect(useRunStore.getState().spreadingThreshold).toBe(0)
  })

  it('sends the threshold with the run so the engine starts with it', async () => {
    window.localStorage.setItem(STORAGE_KEY, '40')
    const useRunStore = await freshStore()

    await useRunStore.getState().createRun({
      initial: 'abc', modified: 'abd', target: 'xyz', seed: 7,
    })

    expect(createRun).toHaveBeenCalledWith(
      expect.objectContaining({ spreading_threshold: 40, target: 'xyz', seed: 7 }),
    )
  })

  it('lets an explicit per-run value win over the session default', async () => {
    window.localStorage.setItem(STORAGE_KEY, '40')
    const useRunStore = await freshStore()

    await useRunStore.getState().createRun({
      initial: 'abc', modified: 'abd', target: 'xyz', seed: 7,
      spreading_threshold: 0,
    })

    expect(createRun).toHaveBeenCalledWith(
      expect.objectContaining({ spreading_threshold: 0 }),
    )
  })
})

// ---------------------------------------------------------------------------
// The threshold on screen is the threshold of the run on screen
// ---------------------------------------------------------------------------
//
// The threshold decides which Slipnet nodes spread activation, so it is a property
// of a run: the value shown belongs to the run being watched, and a run loaded from
// Run History brings its own. Storage holds one thing beside that -- the value a
// newly created run is given -- so a chosen preference survives a reload.

/** A run as `GET /api/runs/{id}` reports it. */
function runInfo(overrides: Partial<RunInfo> = {}): RunInfo {
  return {
    run_id: 5,
    status: 'paused',
    codelet_count: 120,
    temperature: 44,
    initial: 'abc',
    modified: 'abd',
    target: 'xyz',
    answer: null,
    spreading_threshold: 100,
    ...overrides,
  }
}

describe('runStore — the threshold belongs to the run on screen', () => {
  it('takes the loaded run\'s value, whatever is remembered', async () => {
    window.localStorage.setItem(STORAGE_KEY, '80')
    const store = await freshStore()

    store.getState().adoptRun(runInfo({ run_id: 5, spreading_threshold: 30 }))

    expect(store.getState().runId).toBe(5)
    expect(store.getState().spreadingThreshold).toBe(30)
  })

  it('reads a run with no recorded threshold as the 100 such a run used', async () => {
    window.localStorage.setItem(STORAGE_KEY, '80')
    const store = await freshStore()
    const { spreading_threshold: _omitted, ...withoutThreshold } = runInfo()

    store.getState().adoptRun(withoutThreshold as RunInfo)

    expect(store.getState().spreadingThreshold).toBe(100)
  })

  it('leaves the remembered default as the user set it', async () => {
    window.localStorage.setItem(STORAGE_KEY, '80')
    const store = await freshStore()

    store.getState().adoptRun(runInfo({ spreading_threshold: 30 }))

    expect(store.getState().defaultSpreadingThreshold).toBe(80)
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('80')
  })

  it('creates the next run at the remembered default', async () => {
    window.localStorage.setItem(STORAGE_KEY, '80')
    const store = await freshStore()
    store.getState().adoptRun(runInfo({ spreading_threshold: 30 }))

    await store.getState().createRun({
      initial: 'abc', modified: 'abd', target: 'xyz', seed: 7,
    })

    expect(createRun).toHaveBeenCalledWith(
      expect.objectContaining({ spreading_threshold: 80 }),
    )
  })

  it('shows the threshold the created run reports', async () => {
    const store = await freshStore()
    createRun.mockResolvedValueOnce({
      run_id: 2,
      status: 'initialized',
      codelet_count: 0,
      temperature: 100,
      initial: 'abc', modified: 'abd', target: 'xyz', answer: null,
      spreading_threshold: 65,
    })

    await store.getState().createRun({
      initial: 'abc', modified: 'abd', target: 'xyz', seed: 7,
      spreading_threshold: 65,
    })

    expect(store.getState().spreadingThreshold).toBe(65)
  })

  it('sends a slider move to the run on screen', async () => {
    window.localStorage.setItem(STORAGE_KEY, '80')
    const store = await freshStore()
    store.getState().adoptRun(runInfo({ run_id: 5, spreading_threshold: 30 }))

    await store.getState().setSpreadingThreshold(45)

    expect(setSpreadingThresholdCall).toHaveBeenCalledWith(5, 45)
    expect(store.getState().spreadingThreshold).toBe(45)
  })

  it('takes a slider move as the preference for the next run too', async () => {
    const store = await freshStore()
    store.getState().adoptRun(runInfo({ run_id: 5, spreading_threshold: 30 }))

    await store.getState().setSpreadingThreshold(45)

    expect(store.getState().defaultSpreadingThreshold).toBe(45)
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('45')
  })

  it('shows the default again once no run is loaded', async () => {
    window.localStorage.setItem(STORAGE_KEY, '80')
    const store = await freshStore()
    store.getState().adoptRun(runInfo({ run_id: 5, spreading_threshold: 30 }))

    await store.getState().deleteRun()

    expect(store.getState().runId).toBeNull()
    expect(store.getState().spreadingThreshold).toBe(80)
  })
})

// ---------------------------------------------------------------------------
// Persistence mode (Phase 0 §A2) -- what a run writes down
// ---------------------------------------------------------------------------
//
// Mode selects the sink before the first codelet runs, so it has to travel with
// the create request. A selector that only set a local value would look identical
// on screen and produce Normal runs forever, which nobody would notice, because
// Normal is also what they would have got without choosing.
//
// It is deliberately *not* persisted, unlike the threshold above: the threshold is
// remembered because forgetting it would silently change results, while this only
// changes what is kept, and a remembered value fails in the directions that hurt --
// a day's work recorded nothing, or every run paid Audit's 1.8x for a record
// nobody wanted.

describe('runStore — persistence mode', () => {
  it('defaults to normal', async () => {
    const useRunStore = await freshStore()
    expect(useRunStore.getState().persistenceMode).toBe('normal')
  })

  it('sends the chosen mode with the create, since it selects the sink', async () => {
    const useRunStore = await freshStore()
    useRunStore.getState().setPersistenceMode('audit')

    await useRunStore.getState().createRun({
      initial: 'abc', modified: 'abd', target: 'xyz', seed: 7,
    })

    expect(createRun).toHaveBeenCalledWith(
      expect.objectContaining({ mode: 'audit' }),
    )
  })

  it('records the mode the server reports, which is what the run actually is', async () => {
    const useRunStore = await freshStore()
    createRun.mockResolvedValueOnce({
      run_id: -1,
      mode: 'fast',
      status: 'initialized',
      codelet_count: 0,
      temperature: 100,
      initial: 'abc', modified: 'abd', target: 'xyz', answer: null,
    })
    useRunStore.getState().setPersistenceMode('fast')

    await useRunStore.getState().createRun({
      initial: 'abc', modified: 'abd', target: 'xyz', seed: 7,
    })

    expect(useRunStore.getState().runMode).toBe('fast')
    // Negative, because there is no row to take an identifier from.
    expect(useRunStore.getState().runId).toBe(-1)
  })

  it('does not survive a reload — it starts at normal every time', async () => {
    let useRunStore = await freshStore()
    useRunStore.getState().setPersistenceMode('fast')
    expect(useRunStore.getState().persistenceMode).toBe('fast')

    useRunStore = await freshStore()
    expect(useRunStore.getState().persistenceMode).toBe('normal')
  })
})

// ---------------------------------------------------------------------------
// Run parameters and worker count
// ---------------------------------------------------------------------------
//
// Both are read by the engine before the first codelet, so both have to be sent
// with the create rather than applied afterwards — exactly as the persistence mode
// is. The wrong version pushes them to a running engine, which has no endpoint for
// them and should not have one.

describe('runStore — fixed run parameters', () => {
  it('sends nothing at all when no parameter was changed', async () => {
    const store = await freshStore()
    await store.getState().createRun({ initial: 'abc', modified: 'abd', target: 'xyz', seed: 0 })

    expect(createRun).toHaveBeenCalledWith(
      expect.not.objectContaining({ parameters: expect.anything() }),
    )
  })

  it('sends only the overrides, so the run tracks the server\'s defaults for the rest', async () => {
    const store = await freshStore()
    store.getState().setParameterOverride('update_cycle_length', 40)
    await store.getState().createRun({ initial: 'abc', modified: 'abd', target: 'xyz', seed: 0 })

    expect(createRun).toHaveBeenCalledWith(
      expect.objectContaining({ parameters: { update_cycle_length: 40 } }),
    )
  })

  it('removes an override rather than pinning it to the default of the moment', async () => {
    const store = await freshStore()
    store.getState().setParameterOverride('update_cycle_length', 40)
    store.getState().clearParameterOverride('update_cycle_length')

    expect(store.getState().parameterOverrides).toEqual({})
  })

  it('resets every override at once', async () => {
    const store = await freshStore()
    store.getState().setParameterOverride('update_cycle_length', 40)
    store.getState().setParameterOverride('theme_boost_amount', 55)
    store.getState().clearAllParameterOverrides()

    expect(store.getState().parameterOverrides).toEqual({})
  })

  it('records what the created run was fixed with, so a later change starts a new run', async () => {
    const store = await freshStore()
    store.getState().setParameterOverride('update_cycle_length', 40)
    await store.getState().createRun({ initial: 'abc', modified: 'abd', target: 'xyz', seed: 0 })

    expect(store.getState().runParameterOverrides).toEqual({ update_cycle_length: 40 })
  })
})

describe('runStore — worker count', () => {
  it('defaults to the serial loop', async () => {
    const store = await freshStore()
    expect(store.getState().workers).toBe(1)
  })

  it('sends the chosen count with the create', async () => {
    const store = await freshStore()
    store.getState().setWorkers(4)
    await store.getState().createRun({ initial: 'abc', modified: 'abd', target: 'xyz', seed: 0 })

    expect(createRun).toHaveBeenCalledWith(expect.objectContaining({ workers: 4 }))
  })

  it('sends 1 under Audit, which refuses anything more with a 400', async () => {
    // The control shows 1 and says why; sending the other number would turn a mode
    // change into a rejected request the reader did not ask for.
    const store = await freshStore()
    store.getState().setWorkers(4)
    store.getState().setPersistenceMode('audit')
    await store.getState().createRun({ initial: 'abc', modified: 'abd', target: 'xyz', seed: 0 })

    expect(createRun).toHaveBeenCalledWith(expect.objectContaining({ workers: 1 }))
  })
})

// ---------------------------------------------------------------------------
// The error channel — failures a user asked for reach the user
// ---------------------------------------------------------------------------
//
// Two kinds of failure, told apart by who asked for the request:
//
//   - A user-initiated action (create, step, run, stop, delete, clear, threshold)
//     happened because somebody pressed something. If it does not happen, they are
//     owed a sentence saying so, and the status they can act on: a 404 means the run
//     is gone, a 422 means the values are wrong, a 5xx means try again.
//   - A poll runs on a timer. The tick after it reads the same endpoint again, so a
//     single failed read is recovered rather than reported, and the panels keep the
//     last value they had.
//
// The wrong version is the one that was here: every failure caught and dropped, so a
// run that could not be created was indistinguishable from a run that was created and
// found nothing.

describe('runStore — the error channel', () => {
  /** A server refusal, in the shape `request()` produces. */
  async function apiError(status: number, statusText: string, body: string) {
    const { ApiError } = await import('@/api/client')
    return new ApiError(status, statusText, body)
  }

  it('starts empty', async () => {
    const store = await freshStore()
    expect(store.getState().lastError).toBeNull()
  })

  it('says what a failed create means and what it was trying to do', async () => {
    const store = await freshStore()
    createRun.mockRejectedValueOnce(
      await apiError(500, 'Internal Server Error', '{"detail":"engine failed to start"}'),
    )

    await expect(
      store.getState().createRun({ initial: 'abc', modified: 'abd', target: 'xyz', seed: 0 }),
    ).rejects.toBeTruthy()

    const message = store.getState().lastError ?? ''
    expect(message).toContain('start a new run')
    expect(message).toContain('the server failed to complete it')
    // The server's own account of the failure, not just the status.
    expect(message).toContain('engine failed to start')
  })

  it('distinguishes a run that is gone from values the server will not take', async () => {
    const store = await freshStore()

    createRun.mockRejectedValueOnce(
      await apiError(404, 'Not Found', '{"detail":"Run 12 not found"}'),
    )
    await expect(
      store.getState().createRun({ initial: 'abc', modified: 'abd', target: 'xyz', seed: 0 }),
    ).rejects.toBeTruthy()
    const missing = store.getState().lastError ?? ''

    createRun.mockRejectedValueOnce(
      await apiError(
        422,
        'Unprocessable Entity',
        '{"detail":[{"loc":["body","seed"],"msg":"Input should be a valid integer"}]}',
      ),
    )
    await expect(
      store.getState().createRun({ initial: 'abc', modified: 'abd', target: 'xyz', seed: 0 }),
    ).rejects.toBeTruthy()
    const invalid = store.getState().lastError ?? ''

    expect(missing).toContain('it no longer exists')
    expect(missing).toContain('Run 12 not found')
    expect(invalid).toContain('check the values entered')
    // The field the server named, so the reader knows which box to look at.
    expect(invalid).toContain('seed: Input should be a valid integer')
    expect(invalid).not.toBe(missing)
  })

  it('names an unreachable server as such rather than as a rejection', async () => {
    const store = await freshStore()
    // What `fetch` throws when nothing answers on the other end.
    createRun.mockRejectedValueOnce(new TypeError('Failed to fetch'))

    await expect(
      store.getState().createRun({ initial: 'abc', modified: 'abd', target: 'xyz', seed: 0 }),
    ).rejects.toBeTruthy()

    expect(store.getState().lastError).toContain('the server is unreachable')
  })

  it('leaves a failed poll off the channel, since the next tick reads again', async () => {
    const store = await freshStore()
    store.setState({ runId: 7 })
    getRunMemory.mockRejectedValueOnce(
      await apiError(404, 'Not Found', '{"detail":"Run 7 not found"}'),
    )

    await store.getState().refreshMemory()

    expect(store.getState().lastError).toBeNull()
  })

  it('a whole refresh cycle of failed polls says nothing', async () => {
    const store = await freshStore()
    store.setState({ runId: 7 })
    getRunMemory.mockRejectedValueOnce(await apiError(503, 'Service Unavailable', ''))

    await store.getState().refreshAll()

    expect(store.getState().lastError).toBeNull()
  })

  it('clears the message when the next action succeeds', async () => {
    const store = await freshStore()
    createRun.mockRejectedValueOnce(await apiError(404, 'Not Found', ''))
    await expect(
      store.getState().createRun({ initial: 'abc', modified: 'abd', target: 'xyz', seed: 0 }),
    ).rejects.toBeTruthy()
    expect(store.getState().lastError).not.toBeNull()

    await store.getState().createRun({ initial: 'abc', modified: 'abd', target: 'xyz', seed: 0 })

    expect(store.getState().lastError).toBeNull()
  })

  it('is dismissable, so a message that has been read can be put away', async () => {
    const store = await freshStore()
    store.getState().setLastError('Could not stop the run: it no longer exists.')
    expect(store.getState().lastError).not.toBeNull()

    store.getState().clearLastError()

    expect(store.getState().lastError).toBeNull()
  })

  it('reports a threshold the run would not take, which changes what it computes', async () => {
    const store = await freshStore()
    store.getState().adoptRun(runInfo({ run_id: 5 }))
    setSpreadingThresholdCall.mockRejectedValueOnce(
      await apiError(404, 'Not Found', '{"detail":"Run 5 not found"}'),
    )

    await store.getState().setSpreadingThreshold(45)

    expect(store.getState().lastError).toContain('apply the spreading threshold')
  })

  it('reports a stop the engine did not take, since the engine is still going', async () => {
    const store = await freshStore()
    const { stopRun } = await import('@/api/client')
    vi.mocked(stopRun).mockRejectedValueOnce(await apiError(409, 'Conflict', ''))
    store.setState({ runId: 5 })

    await store.getState().stop()

    expect(store.getState().lastError).toContain('stop the run')
    expect(store.getState().lastError).toContain('conflicts with something already there')
  })

  it('reports a clear-out the server refused, since the runs are still there', async () => {
    const store = await freshStore()
    deleteAllRuns.mockRejectedValueOnce(await apiError(500, 'Internal Server Error', ''))

    await store.getState().fullReset()

    expect(store.getState().lastError).toContain('clear every run and the episodic memory')
    // Local state is cleared either way, which is what makes saying so necessary.
    expect(store.getState().runId).toBeNull()
  })

  it('goes through the API client to clear runs and memory', async () => {
    const store = await freshStore()
    await store.getState().fullReset()

    expect(deleteAllRuns).toHaveBeenCalled()
    expect(clearMemory).toHaveBeenCalled()
  })
})

describe('runStore — which Episodic Memory the panel reads', () => {
  it('asks the run, not the shared store, once a run is loaded', async () => {
    // The run-scoped read reaches the Training Session's memory by the right route in
    // every mode, including a Fast Run, which is served from the live object.
    const store = await freshStore()
    store.setState({ runId: 7 })
    await store.getState().refreshMemory()

    expect(getRunMemory).toHaveBeenCalledWith(7)
    expect(store.getState().memory.scope).toBe('live')
  })
})

// ---------------------------------------------------------------------------
// Ending a Training Session
// ---------------------------------------------------------------------------
//
// A session is not created and cannot be: it opens when a run needs one. What can
// be done is end it, and ending it *is* clearing Episodic Memory -- that memory is
// the only thing one run hands the next, so after the clear the runs on either
// side share nothing and do not belong together. The run on screen is deliberately
// left alone: it ran in the session that has just closed, and that stays true.

describe('runStore — ending a Training Session', () => {
  it('clears Episodic Memory, which is what the boundary is', async () => {
    const store = await freshStore()
    store.setState({ runId: 7 })

    await store.getState().startNewTrainingSession()

    expect(clearMemory).toHaveBeenCalled()
    expect(store.getState().memory.answers).toEqual([])
  })

  it('bumps the epoch so the panels re-read across the boundary', async () => {
    const store = await freshStore()
    const before = store.getState().epoch

    await store.getState().startNewTrainingSession()

    expect(store.getState().epoch).toBe(before + 1)
  })

  it('leaves the loaded run alone — it belongs to the session just closed', async () => {
    const store = await freshStore()
    store.setState({ runId: 7, codeletCount: 842, status: 'answer_found' })

    await store.getState().startNewTrainingSession()

    expect(store.getState().runId).toBe(7)
    expect(store.getState().codeletCount).toBe(842)
  })

  it('raises and says so when the clear was refused, since the session is still open', async () => {
    const { ApiError } = await import('@/api/client')
    const store = await freshStore()
    clearMemory.mockRejectedValueOnce(new ApiError(503, 'Service Unavailable', ''))

    await expect(store.getState().startNewTrainingSession()).rejects.toBeTruthy()

    expect(store.getState().lastError).toContain('start a new Training Session')
    // Nothing was discarded locally either: the memory on screen is still the
    // session's, because the session is still open.
    expect(store.getState().epoch).toBe(0)
  })
})
