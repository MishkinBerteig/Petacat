/** The Windows menu's and the graphics switches' state (`gui.ss:638-651, 1091-1162`). */

import { beforeEach, describe, expect, it, vi } from 'vitest'

const getSlipnet = vi.fn().mockResolvedValue({ nodes: [] })
const getCoderack = vi.fn().mockResolvedValue({ total_count: 0 })
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  getSlipnet: (...a: unknown[]) => getSlipnet(...a),
  getCoderack: (...a: unknown[]) => getCoderack(...a),
}))


/** The test environment's own localStorage is not reliably present; a Map-backed one is. */
function memoryStorage() {
  const m = new Map<string, string>()
  return {
    getItem: (k: string) => (m.has(k) ? m.get(k)! : null),
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
    clear: () => m.clear(),
  }
}

import { useDisplayStore, WINDOW_PANELS } from './displayStore'
import { useRunStore } from './runStore'

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  useDisplayStore.setState({ hidden: [], slipnetGraphics: true, coderackGraphics: true })
  useRunStore.setState({ runId: 1 })
  getSlipnet.mockClear()
  getCoderack.mockClear()
})

describe('panel visibility', () => {
  it('has an entry for every panel including the EEG', () => {
    const keys = WINDOW_PANELS.map((w) => w.key)
    expect(keys).toContain('eeg')
    expect(keys).toContain('slipnet')
    expect(keys).toContain('themespace')
  })

  it('starts with the Verbose panel hidden, and gives a saved preference the same default', async () => {
    expect(WINDOW_PANELS.map((w) => w.key)).toContain('verbose')
    // A preference saved before the panel existed lists no panels as seen.
    localStorage.setItem(
      'petacat.display.v1',
      JSON.stringify({ hidden: ['eeg'], slipnetGraphics: true, coderackGraphics: true }),
    )
    vi.resetModules()
    const fresh = await import('./displayStore')
    expect(fresh.useDisplayStore.getState().hidden).toEqual(['eeg', 'verbose'])
    // Once the panel has been shown and the preference saved, it stays shown.
    fresh.useDisplayStore.getState().togglePanel('verbose')
    vi.resetModules()
    const again = await import('./displayStore')
    expect(again.useDisplayStore.getState().hidden).toEqual(['eeg'])
  })

  it('toggles one panel and shows or hides all', () => {
    useDisplayStore.getState().togglePanel('trace')
    expect(useDisplayStore.getState().hidden).toEqual(['trace'])
    useDisplayStore.getState().togglePanel('trace')
    expect(useDisplayStore.getState().hidden).toEqual([])
    useDisplayStore.getState().hideAll()
    expect(useDisplayStore.getState().hidden).toHaveLength(WINDOW_PANELS.length)
    useDisplayStore.getState().showAll()
    expect(useDisplayStore.getState().hidden).toEqual([])
  })

  it('remembers the choice in localStorage', () => {
    useDisplayStore.getState().togglePanel('eeg')
    useDisplayStore.getState().setSlipnetGraphics(false)
    const saved = JSON.parse(localStorage.getItem('petacat.display.v1') ?? '{}')
    expect(saved.hidden).toEqual(['eeg'])
    expect(saved.slipnetGraphics).toBe(false)
  })

  it('survives storage that throws', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => null,
      setItem: () => {
        throw new Error('blocked')
      },
    })
    expect(() => useDisplayStore.getState().togglePanel('memory')).not.toThrow()
    expect(useDisplayStore.getState().hidden).toEqual(['memory'])
  })
})

describe('graphics switches', () => {
  it('stop the Slipnet poll and the Coderack poll independently', async () => {
    useDisplayStore.getState().setSlipnetGraphics(false)
    await useRunStore.getState().refreshSlipnet()
    await useRunStore.getState().refreshCoderack()
    expect(getSlipnet).not.toHaveBeenCalled()
    expect(getCoderack).toHaveBeenCalledTimes(1)

    useDisplayStore.getState().setCoderackGraphics(false)
    await useRunStore.getState().refreshAll()
    expect(getCoderack).toHaveBeenCalledTimes(1)
  })

  it('resume polling when switched back on', async () => {
    useDisplayStore.getState().setSlipnetGraphics(false)
    useDisplayStore.getState().setSlipnetGraphics(true)
    await useRunStore.getState().refreshSlipnet()
    expect(getSlipnet).toHaveBeenCalledTimes(1)
  })
})
