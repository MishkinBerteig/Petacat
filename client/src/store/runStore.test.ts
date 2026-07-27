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
