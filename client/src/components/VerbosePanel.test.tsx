// ---------------------------------------------------------------------------
// Petacat -- the Verbose panel: Metacat's Verbose mode narration
// ---------------------------------------------------------------------------
//
// The lines come from `GET /runs/{id}/verbose` and are kept in a bounded buffer by the run
// store; these tests drive the store and the panel with the API mocked out.
// ---------------------------------------------------------------------------

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const getVerbose = vi.fn()
const setVerbose = vi.fn().mockResolvedValue({ verbose: true })
const clearVerbose = vi.fn().mockResolvedValue(undefined)
const stepRun = vi.fn().mockResolvedValue([])

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  getVerbose: (...a: unknown[]) => getVerbose(...a),
  setVerbose: (...a: unknown[]) => setVerbose(...a),
  clearVerbose: (...a: unknown[]) => clearVerbose(...a),
  stepRun: (...a: unknown[]) => stepRun(...a),
  getRun: vi.fn().mockResolvedValue({ status: 'paused', codelet_count: 1, temperature: 100 }),
  getWorkspace: vi.fn().mockResolvedValue(null),
  getSlipnet: vi.fn().mockResolvedValue(null),
  getCoderack: vi.fn().mockResolvedValue(null),
  getEeg: vi.fn().mockResolvedValue(null),
  getThemespace: vi.fn().mockResolvedValue(null),
  getTrace: vi.fn().mockResolvedValue([]),
  getTemperature: vi.fn().mockResolvedValue(null),
  getCommentary: vi.fn().mockResolvedValue(''),
  getRunMemory: vi.fn().mockResolvedValue({ answers: [], snags: [], scope: 'live', mode: 'normal' }),
}))

import { VerbosePanel, verboseFilename } from './VerbosePanel'
import { useRunStore, VERBOSE_CLIENT_LINES } from '@/store/runStore'
import { useDisplayStore } from '@/store/displayStore'

const ORIGINAL = useRunStore.getState()

const snap = (lines: string[], next: number, extra: object = {}) => ({
  run_id: 1, verbose: true, capacity: 5000, lines, next, first: 0, dropped: 0,
  total: next, ...extra,
})

beforeEach(() => {
  useRunStore.setState({ ...ORIGINAL, runId: 1 }, true)
  useDisplayStore.setState({ hidden: [] })
  getVerbose.mockReset()
  setVerbose.mockClear()
  clearVerbose.mockClear()
  stepRun.mockClear()
})

describe('VerbosePanel', () => {
  it('says what Verbose mode is when there is nothing to show', () => {
    getVerbose.mockResolvedValue(snap([], 0, { verbose: false }))
    render(<VerbosePanel />)
    expect(screen.getByText(/Verbose mode is off/)).toBeTruthy()
  })

  it('shows the narration the store holds', async () => {
    getVerbose.mockResolvedValue(snap(['In bond-builder codelet...', 'Building bond:'], 2))
    useRunStore.setState({ verboseMode: true })
    render(<VerbosePanel />)
    await waitFor(() => expect(screen.getByText(/Building bond:/)).toBeTruthy())
  })

  it('switches Verbose mode on the loaded run from its checkbox', async () => {
    getVerbose.mockResolvedValue(snap([], 0))
    render(<VerbosePanel />)
    fireEvent.click(screen.getByLabelText('Verbose mode'))
    await waitFor(() => expect(setVerbose).toHaveBeenCalledWith(1, true))
    expect(useRunStore.getState().verboseMode).toBe(true)
  })

  it('names the file it saves for the run', () => {
    expect(verboseFilename(7)).toBe('petacat-verbose-run-7.txt')
    expect(verboseFilename(null)).toBe('petacat-verbose.txt')
  })

  it('clears the narration', async () => {
    getVerbose.mockResolvedValue(snap([], 5))
    useRunStore.setState({ verboseLines: ['a', 'b'], verboseNext: 5, verboseMode: true })
    render(<VerbosePanel />)
    fireEvent.click(screen.getByText('Clear'))
    await waitFor(() => expect(clearVerbose).toHaveBeenCalledWith(1))
    expect(useRunStore.getState().verboseLines).toEqual([])
  })
})

describe('the run store and Verbose mode', () => {
  it('appends what is new and resumes where the last reply ended', async () => {
    useRunStore.setState({ verboseMode: true })
    getVerbose.mockResolvedValueOnce(snap(['a', 'b'], 2)).mockResolvedValueOnce(snap(['c'], 3))
    await useRunStore.getState().refreshVerbose()
    await useRunStore.getState().refreshVerbose()
    expect(useRunStore.getState().verboseLines).toEqual(['a', 'b', 'c'])
    expect(getVerbose).toHaveBeenNthCalledWith(1, 1, 0)
    expect(getVerbose).toHaveBeenNthCalledWith(2, 1, 2)
  })

  it('keeps a bounded buffer and counts what fell off', async () => {
    useRunStore.setState({
      verboseMode: true,
      verboseLines: Array.from({ length: VERBOSE_CLIENT_LINES }, (_, i) => `old ${i}`),
      verboseNext: VERBOSE_CLIENT_LINES,
    })
    getVerbose.mockResolvedValue(snap(['new 1', 'new 2'], VERBOSE_CLIENT_LINES + 2))
    await useRunStore.getState().refreshVerbose()
    const s = useRunStore.getState()
    expect(s.verboseLines).toHaveLength(VERBOSE_CLIENT_LINES)
    expect(s.verboseLines[s.verboseLines.length - 1]).toBe('new 2')
    expect(s.verboseLines[0]).toBe('old 2')
    expect(s.verboseDropped).toBe(2)
  })

  it('asks the server for nothing while the mode is off and the panel is hidden', async () => {
    useDisplayStore.setState({ hidden: ['verbose'] })
    useRunStore.setState({ verboseMode: false })
    await useRunStore.getState().refreshVerbose()
    expect(getVerbose).not.toHaveBeenCalled()
  })

  it('reads the narration of an open panel even with the mode off (step mode narrates)', async () => {
    getVerbose.mockResolvedValue(snap(['x'], 1, { verbose: false }))
    await useRunStore.getState().refreshVerbose()
    expect(useRunStore.getState().verboseLines).toEqual(['x'])
    expect(useRunStore.getState().verboseMode).toBe(false)
  })

  it('sends the Step button as step mode, for ten codelets or fewer', async () => {
    useRunStore.setState({ status: 'paused' })
    await useRunStore.getState().step(3)
    expect(stepRun).toHaveBeenLastCalledWith(1, 1, true)
    stepRun.mockClear()
    useRunStore.setState({ liveUpdate: false })
    await useRunStore.getState().step(25)
    expect(stepRun).toHaveBeenLastCalledWith(1, 25, false)
  })

  it('remembers the switch when no run is loaded, and sends it to the next run', async () => {
    useRunStore.setState({ runId: null })
    await useRunStore.getState().setVerboseMode(true)
    expect(setVerbose).not.toHaveBeenCalled()
    expect(useRunStore.getState().verboseMode).toBe(true)
  })
})
