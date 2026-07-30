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
  .mockResolvedValue({ answers: [], snags: [], scope: 'run', mode: 'fast' })

vi.mock('@/api/client', () => ({
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
  getTemperature: vi.fn().mockResolvedValue({ temperature: 100 }),
  getCommentary: vi.fn().mockResolvedValue({ commentary: '' }),
  getMemory: vi.fn().mockResolvedValue({ answers: [], snags: [] }),
  getRunMemory: (...args: unknown[]) => getRunMemory(...args),
  setSpreadingThreshold: vi.fn().mockResolvedValue({}),
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

describe('runStore — which Episodic Memory the panel reads', () => {
  it('asks the run, not the shared store, once a run is loaded', async () => {
    // A Fast Run thinks against an ephemeral memory of its own. Reading the shared
    // one regardless showed it answers it could not be reminded of.
    const store = await freshStore()
    store.setState({ runId: 7 })
    await store.getState().refreshMemory()

    expect(getRunMemory).toHaveBeenCalledWith(7)
    expect(store.getState().memory.scope).toBe('run')
  })
})
