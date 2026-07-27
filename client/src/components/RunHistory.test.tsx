// ---------------------------------------------------------------------------
// Petacat -- Tests for Run History staying current
// ---------------------------------------------------------------------------
//
// The original bug: this panel is mounted for the whole session, and its fetch
// effect depended only on [currentRunId, epoch]. Nothing in that list changes
// when a run *finishes*, so the list was fetched once just after a run was
// created and never again. Completed runs kept showing the values they had a
// moment after creation -- "initialized, 0 codelets, T 100" -- while the API had
// the real outcome all along.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'

import { RunHistory } from './RunHistory'
import { useRunStore } from '@/store/runStore'
import type { RunInfo } from '@/types'
import { listRuns } from '@/api/client'

vi.mock('@/api/client', () => ({
  listRuns: vi.fn(),
  deleteRun: vi.fn().mockResolvedValue({}),
  getRun: vi.fn().mockResolvedValue({}),
}))

function runInfo(overrides: Partial<RunInfo> = {}): RunInfo {
  return {
    run_id: 1,
    status: 'initialized',
    codelet_count: 0,
    temperature: 100,
    initial: 'abc',
    modified: 'abd',
    target: 'xyz',
    answer: null,
    spreading_threshold: 100,
    ...overrides,
  }
}

const ORIGINAL = useRunStore.getState()

const mockedListRuns = vi.mocked(listRuns)

beforeEach(() => {
  mockedListRuns.mockReset()
  useRunStore.setState({ ...ORIGINAL }, true)
})

describe('RunHistory — reflecting how runs actually ended', () => {
  it('refetches when the run reaches a terminal status', async () => {
    // First fetch catches the run just after creation...
    mockedListRuns.mockResolvedValueOnce({
      runs: [runInfo({ run_id: 7, status: 'initialized', codelet_count: 0, temperature: 100 })],
      total: 1,
    })

    useRunStore.setState({ runId: 7, status: 'initialized', codeletCount: 0, temperature: 100 })
    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText(/initialized/)).toBeTruthy())

    // ...and the second reflects the finished run.
    mockedListRuns.mockResolvedValueOnce({
      runs: [runInfo({ run_id: 7, status: 'answer_found', codelet_count: 842, temperature: 23 })],
      total: 1,
    })

    await act(async () => {
      useRunStore.setState({ status: 'answer_found', codeletCount: 842, temperature: 23 })
    })

    await waitFor(() => expect(mockedListRuns).toHaveBeenCalledTimes(2))
    expect(screen.getByText(/answer found/)).toBeTruthy()
    expect(screen.getByText('842')).toBeTruthy()
  })

  it('shows the active run at its live codelet count, not the last fetched one', async () => {
    // The fetch is stale: the engine has advanced since it landed.
    mockedListRuns.mockResolvedValue({
      runs: [runInfo({ run_id: 7, status: 'initialized', codelet_count: 15, temperature: 98 })],
      total: 1,
    })

    useRunStore.setState({ runId: 7, status: 'running', codeletCount: 400, temperature: 61 })
    render(<RunHistory />)

    await waitFor(() => expect(screen.getByText('400')).toBeTruthy())
    expect(screen.getByText(/running/)).toBeTruthy()
    expect(screen.queryByText('15')).toBeNull()
  })

  it('leaves the rows of other runs alone', async () => {
    mockedListRuns.mockResolvedValue({
      runs: [
        runInfo({ run_id: 7, status: 'running', codelet_count: 10, temperature: 90 }),
        runInfo({ run_id: 6, status: 'halted', codelet_count: 4000, temperature: 77 }),
      ],
      total: 2,
    })

    useRunStore.setState({ runId: 7, status: 'running', codeletCount: 33, temperature: 88 })
    render(<RunHistory />)

    await waitFor(() => expect(screen.getByText('33')).toBeTruthy())
    // Run 6 is not the active run, so its stored figures stand.
    expect(screen.getByText('4000')).toBeTruthy()
    expect(screen.getByText(/halted/)).toBeTruthy()
  })

  it('does not let an idle store blank out a stored status', async () => {
    mockedListRuns.mockResolvedValue({
      runs: [runInfo({ run_id: 7, status: 'answer_found', codelet_count: 500, temperature: 20 })],
      total: 1,
    })

    // runId still set while status has gone idle: the row must keep the real
    // outcome rather than displaying "idle".
    useRunStore.setState({ runId: 7, status: 'idle', codeletCount: 0, temperature: 100 })
    render(<RunHistory />)

    await waitFor(() => expect(screen.getByText(/answer found/)).toBeTruthy())
    expect(screen.getByText('500')).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// The answer belongs in the history row
// ---------------------------------------------------------------------------
//
// A run's outcome is the interesting part, and the row showed only the problem.
// The one subtlety: in justification mode the answer is *supplied* at creation
// for the engine to explain, so a non-null `answer` does not by itself mean the
// engine found anything. `justify_mode` keeps the two apart.

describe('RunHistory — showing the answer', () => {
  it('appends a discovered answer to the problem', async () => {
    mockedListRuns.mockResolvedValue({
      runs: [
        runInfo({
          run_id: 7, status: 'answer_found', codelet_count: 800,
          target: 'xyz', answer: 'xyd', justify_mode: false,
        }),
      ],
      total: 1,
    })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('xyd')).toBeTruthy())
    // The problem text and the answer sit in one cell, described in the tooltip.
    expect(screen.getByTitle(/abc->abd; xyz -> xyd \(found\)/)).toBeTruthy()
  })

  it('marks a justification answer as given rather than found', async () => {
    mockedListRuns.mockResolvedValue({
      runs: [
        runInfo({
          run_id: 8, status: 'answer_found', codelet_count: 300,
          target: 'xyz', answer: 'wyz', justify_mode: true,
        }),
      ],
      total: 1,
    })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('wyz')).toBeTruthy())
    expect(screen.getByTitle(/\(given, to justify\)/)).toBeTruthy()
  })

  it('shows no answer arrow for a run that never answered', async () => {
    mockedListRuns.mockResolvedValue({
      runs: [runInfo({ run_id: 9, status: 'halted', codelet_count: 4000, answer: null })],
      total: 1,
    })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText(/halted/)).toBeTruthy())
    expect(screen.getByTitle('abc->abd; xyz')).toBeTruthy()
  })

  it('shows the answer as soon as the engine finds it, before the next fetch', async () => {
    // The fetched row predates the answer; the workspace already has it.
    mockedListRuns.mockResolvedValue({
      runs: [runInfo({ run_id: 7, status: 'running', codelet_count: 100, answer: null })],
      total: 1,
    })

    useRunStore.setState({
      runId: 7,
      status: 'answer_found',
      codeletCount: 771,
      temperature: 44,
      workspace: { initial: 'abc', modified: 'abd', target: 'xyz', answer: 'xyd' } as any,
    })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('xyd')).toBeTruthy())
  })
})

// ---------------------------------------------------------------------------
// The spreading threshold belongs in the record of a run
// ---------------------------------------------------------------------------
//
// It changes what a run does -- the same problem at the same seed takes a
// different number of codelets -- so a run at anything other than 100 is not
// comparable with the others, and the list has to say so.

describe('RunHistory — spreading threshold per run', () => {
  it('shows the threshold each run used', async () => {
    mockedListRuns.mockResolvedValue({
      runs: [
        runInfo({ run_id: 9, status: 'answer_found', spreading_threshold: 30 }),
        runInfo({ run_id: 8, status: 'answer_found', spreading_threshold: 100 }),
      ],
      total: 2,
    })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('30')).toBeTruthy())
    expect(
      screen.getByTitle(/Spreading threshold 30 — not the original behaviour/),
    ).toBeTruthy()
    expect(
      screen.getByTitle(/Spreading threshold 100 — the original behaviour/),
    ).toBeTruthy()
  })

  it('treats a run with no recorded threshold as the original 100', async () => {
    const { spreading_threshold: _omitted, ...withoutThreshold } = runInfo({ run_id: 7 })
    mockedListRuns.mockResolvedValue({ runs: [withoutThreshold as any], total: 1 })

    render(<RunHistory />)
    await waitFor(() =>
      expect(screen.getByTitle(/Spreading threshold 100 — the original/)).toBeTruthy(),
    )
  })
})
