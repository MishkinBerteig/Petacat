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
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'

import { RunHistory } from './RunHistory'
import { useRunStore } from '@/store/runStore'
import type { RunInfo } from '@/types'
import { ApiError, listRuns, getRun, deleteRun } from '@/api/client'

// The endpoints are faked; `ApiError` and `describeApiError` are the real ones, so a
// rejection carries the status a server would have sent and the panel reads it the
// way it reads a live failure.
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  listRuns: vi.fn(),
  deleteRun: vi.fn().mockResolvedValue({}),
  getRun: vi.fn().mockResolvedValue({}),
}))

/** A rejection shaped like the one `request` produces for a given status. */
function apiError(status: number, statusText: string, detail: string): ApiError {
  return new ApiError(status, statusText, JSON.stringify({ detail }))
}

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
  // Calls only: each test says for itself whether opening a run is expected, and
  // the resolved value the mock is declared with stays in place.
  vi.mocked(getRun).mockClear()
  vi.mocked(deleteRun).mockClear()
  vi.mocked(deleteRun).mockResolvedValue(undefined)
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

  // Opening a run means watching that run, threshold included: it decides which
  // Slipnet nodes spread activation, so the controls describe the run on screen.
  it('adopts the threshold of the run whose row is clicked', async () => {
    mockedListRuns.mockResolvedValue({
      runs: [runInfo({ run_id: 9, status: 'paused', spreading_threshold: 30 })],
      total: 1,
    })
    vi.mocked(getRun).mockResolvedValue(
      runInfo({ run_id: 9, status: 'paused', spreading_threshold: 30, mode: 'normal' }),
    )
    useRunStore.setState({ spreadingThreshold: 100, defaultSpreadingThreshold: 100 })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('#9')).toBeTruthy())

    await act(async () => {
      fireEvent.click(screen.getByText('#9'))
    })

    await waitFor(() => expect(useRunStore.getState().runId).toBe(9))
    expect(useRunStore.getState().spreadingThreshold).toBe(30)
    // The preference for the next run is the user's to set, so opening a run
    // leaves it where they left it.
    expect(useRunStore.getState().defaultSpreadingThreshold).toBe(100)
  })
})

// ---------------------------------------------------------------------------
// A Fast Run is absent by construction, and the absence has to be explained
// ---------------------------------------------------------------------------
//
// This list is built from the `runs` table, and a Fast Run writes no row -- so it
// is not missing from the list, it cannot be in it. Unexplained, that is
// indistinguishable from the bug this panel has actually had: a list that was
// fetched once and never refreshed.

describe('RunHistory — Fast runs cannot appear', () => {
  it('says why the run on screen is not in the list', async () => {
    mockedListRuns.mockResolvedValue({ runs: [], total: 0 })
    useRunStore.setState({ runId: -1, runMode: 'fast' })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText(/shown from memory/)).toBeTruthy())
    expect(screen.getByText(/writes nothing, including the row this list reads/)).toBeTruthy()
  })

  it('still says so when other, recorded runs are listed', async () => {
    mockedListRuns.mockResolvedValue({
      runs: [runInfo({ run_id: 4, mode: 'normal', status: 'answer_found' })],
      total: 1,
    })
    useRunStore.setState({ runId: -2, runMode: 'fast' })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText(/shown from memory/)).toBeTruthy())
    expect(screen.getByText('#4')).toBeTruthy()
  })

  it('says nothing when the loaded run is one that was recorded', async () => {
    mockedListRuns.mockResolvedValue({
      runs: [runInfo({ run_id: 4, mode: 'normal' })],
      total: 1,
    })
    useRunStore.setState({ runId: 4, runMode: 'normal' })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('#4')).toBeTruthy())
    expect(screen.queryByText(/shown from memory/)).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Each listed run shows what it recorded
// ---------------------------------------------------------------------------
//
// The mode decides what the Review browser can show of a run, so choosing a row to
// review without knowing its mode is guessing. Runs recorded before modes existed
// read as Normal, which is what they were.

describe('RunHistory — persistence mode per run', () => {
  it('shows each run its mode', async () => {
    mockedListRuns.mockResolvedValue({
      runs: [
        runInfo({ run_id: 9, mode: 'audit' }),
        runInfo({ run_id: 8, mode: 'normal' }),
      ],
      total: 2,
    })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('audit')).toBeTruthy())
    expect(screen.getByText('normal')).toBeTruthy()
  })

  it('treats a run with no recorded mode as normal', async () => {
    mockedListRuns.mockResolvedValue({ runs: [runInfo({ run_id: 7 })], total: 1 })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('normal')).toBeTruthy())
  })
})

// ---------------------------------------------------------------------------
// Reaching the record from the dashboard
// ---------------------------------------------------------------------------
//
// The review surfaces were reachable only by opening the Review view and browsing
// Training Sessions — which is the right way round for a reader who is exploring,
// and the wrong way round for one who has just watched a run finish: they know the
// run and not the session it landed in.

describe('RunHistory — opening a run in the Review browser', () => {
  it('offers a review route on every listed run', async () => {
    mockedListRuns.mockResolvedValue({
      runs: [runInfo({ run_id: 7, mode: 'normal', status: 'answer_found' })],
      total: 1,
    })

    render(<RunHistory />)
    const review = await screen.findByRole('button', { name: /^review$/i })
    fireEvent.click(review)

    expect(window.location.hash).toBe('#/review/runs/7')
  })

  it('does not also load the run onto the dashboard when review is clicked', async () => {
    // The row itself loads the run; the review button is a different action and must
    // not do both, or a click on it would replace the workspace being looked at.
    mockedListRuns.mockResolvedValue({
      runs: [runInfo({ run_id: 8, mode: 'audit' })],
      total: 1,
    })

    render(<RunHistory />)
    fireEvent.click(await screen.findByRole('button', { name: /^review$/i }))

    expect(vi.mocked(getRun)).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Reaching the runs past the first window
// ---------------------------------------------------------------------------
//
// `GET /api/runs` takes a limit and an offset and reports a total. The list shows
// one window at a time, says how many runs exist behind it, and moves the window
// on request, so every recorded run is reachable from here.

describe('RunHistory — paging', () => {
  it('reports the total the server has, not only what is on screen', async () => {
    mockedListRuns.mockResolvedValue({ runs: [runInfo({ run_id: 137 })], total: 137 })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('1–1 of 137 runs')).toBeTruthy())
  })

  it('asks for the next window and renders it', async () => {
    mockedListRuns.mockImplementation(async (_limit, offset) => ({
      runs: [runInfo({ run_id: offset === 0 ? 137 : 87 })],
      total: 137,
    }))

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('#137')).toBeTruthy())
    expect(mockedListRuns).toHaveBeenCalledWith(50, 0)

    await act(async () => {
      screen.getByRole('button', { name: /next page of runs/i }).click()
    })

    await waitFor(() => expect(mockedListRuns).toHaveBeenCalledWith(50, 50))
    await waitFor(() => expect(screen.getByText('#87')).toBeTruthy())
    expect(screen.getByText('51–51 of 137 runs')).toBeTruthy()
    expect(screen.queryByText('#137')).toBeNull()
  })

  it('goes back to the window before', async () => {
    mockedListRuns.mockImplementation(async (_limit, offset) => ({
      runs: [runInfo({ run_id: offset === 0 ? 137 : 87 })],
      total: 137,
    }))

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('#137')).toBeTruthy())
    // Nothing precedes the first window, so there is nowhere to go back to.
    expect(screen.getByRole('button', { name: /previous page of runs/i })).toBeDisabled()

    await act(async () => {
      screen.getByRole('button', { name: /next page of runs/i }).click()
    })
    await waitFor(() => expect(screen.getByText('#87')).toBeTruthy())

    await act(async () => {
      screen.getByRole('button', { name: /previous page of runs/i }).click()
    })
    await waitFor(() => expect(screen.getByText('#137')).toBeTruthy())
  })

  it('offers no next window when the whole list is on screen', async () => {
    mockedListRuns.mockResolvedValue({ runs: [runInfo({ run_id: 7 })], total: 1 })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('1–1 of 1 runs')).toBeTruthy())
    expect(screen.getByRole('button', { name: /next page of runs/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /previous page of runs/i })).toBeDisabled()
  })
})

// ---------------------------------------------------------------------------
// A run that writes no row still appears, with its results.
//
// A Fast run is absent from `GET /api/runs` by construction — it writes nothing,
// including the row the listing reads. Its state is known regardless: the store
// follows the running engine. So the panel lists it from memory and reports what
// it did, which is what a reader comes to this panel for.
// ---------------------------------------------------------------------------

describe('RunHistory — a run held only in memory', () => {
  beforeEach(() => {
    mockedListRuns.mockResolvedValue({ runs: [], total: 0 })
  })

  it('lists the run and reports the results it finished with', async () => {
    useRunStore.setState({
      ...ORIGINAL,
      runId: -1,
      runMode: 'fast',
      status: 'answer_found',
      codeletCount: 1875,
      temperature: 29,
      workspace: {
        initial: 'abc', modified: 'abd', target: 'xyz', answer: 'xyd',
      } as any,
    })

    render(<RunHistory />)

    await waitFor(() => expect(screen.getByText('#-1')).toBeTruthy())
    expect(screen.getByText('1875')).toBeTruthy()
    expect(screen.getByText(/answer found/i)).toBeTruthy()
    expect(screen.getByText(/xyd/)).toBeTruthy()
  })

  it('says the run is held in memory rather than recorded', async () => {
    useRunStore.setState({
      ...ORIGINAL,
      runId: -1,
      runMode: 'fast',
      status: 'answer_found',
      codeletCount: 1875,
      temperature: 29,
    })

    render(<RunHistory />)

    await waitFor(() =>
      expect(screen.getByText(/shown from memory/)).toBeTruthy(),
    )
    expect(screen.getByText(/not available in Review/)).toBeTruthy()
  })

  it('follows the run as it finishes rather than showing where it started', async () => {
    useRunStore.setState({
      ...ORIGINAL,
      runId: -1,
      runMode: 'fast',
      status: 'running',
      codeletCount: 40,
      temperature: 92,
    })

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('40')).toBeTruthy())

    // The run ends.
    act(() => {
      useRunStore.setState({
        status: 'answer_found',
        codeletCount: 1875,
        temperature: 29,
      })
    })

    await waitFor(() => expect(screen.getByText('1875')).toBeTruthy())
    expect(screen.queryByText('40')).toBeNull()
    expect(screen.getByText(/answer found/i)).toBeTruthy()
  })

  it('lists a recorded run once, from the listing', async () => {
    // A Normal run has a row, so the listing carries it and nothing is synthesised.
    mockedListRuns.mockResolvedValue({
      runs: [runInfo({ run_id: 7, status: 'answer_found', codelet_count: 900 })],
      total: 1,
    })
    useRunStore.setState({
      ...ORIGINAL,
      runId: 7,
      runMode: 'normal',
      status: 'answer_found',
      codeletCount: 900,
      temperature: 30,
    })

    render(<RunHistory />)

    await waitFor(() => expect(screen.getAllByText('#7')).toHaveLength(1))
    expect(screen.queryByText(/shown from memory/)).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// A list that could not be read, told apart from a list with nothing in it
// ---------------------------------------------------------------------------
//
// "No runs yet" is a claim about the database, and it is what a reader concludes
// from an empty table. It is reserved for the case it describes: a request that
// failed puts its reason in the table's place.

describe('RunHistory — a list that failed to load', () => {
  it('gives the reason instead of saying there are no runs', async () => {
    mockedListRuns.mockRejectedValue(
      apiError(503, 'Service Unavailable', 'the database is not accepting connections'),
    )

    render(<RunHistory />)

    await waitFor(() =>
      expect(
        screen.getByText(/Could not load the run history: the server failed to complete it/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/the database is not accepting connections/)).toBeTruthy()
    expect(screen.queryByText('No runs yet.')).toBeNull()
  })

  it('says there are no runs when there genuinely are none', async () => {
    mockedListRuns.mockResolvedValue({ runs: [], total: 0 })

    render(<RunHistory />)

    await waitFor(() => expect(screen.getByText('No runs yet.')).toBeTruthy())
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('names an unreachable server as unreachable', async () => {
    mockedListRuns.mockRejectedValue(new TypeError('Failed to fetch'))

    render(<RunHistory />)

    await waitFor(() =>
      expect(
        screen.getByText(/Could not load the run history: the server is unreachable/),
      ).toBeTruthy(),
    )
  })
})

// ---------------------------------------------------------------------------
// The two actions a row offers, each reporting its own failure
// ---------------------------------------------------------------------------

describe('RunHistory — an action the server refuses', () => {
  it('says why a run was not deleted, with the row still there', async () => {
    mockedListRuns.mockResolvedValue({ runs: [runInfo({ run_id: 7 })], total: 1 })
    vi.mocked(deleteRun).mockRejectedValue(
      apiError(409, 'Conflict', 'run 7 is still executing'),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('#7')).toBeTruthy())
    fireEvent.click(screen.getByTitle('Delete run #7'))

    await waitFor(() =>
      expect(
        screen.getByText(/Could not delete run #7: that conflicts with something already there/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/run 7 is still executing/)).toBeTruthy()
    expect(screen.getByText('#7')).toBeTruthy()
    vi.mocked(window.confirm).mockRestore()
  })

  it('says why a clicked run did not open', async () => {
    mockedListRuns.mockResolvedValue({ runs: [runInfo({ run_id: 9 })], total: 1 })
    vi.mocked(getRun).mockRejectedValue(
      apiError(404, 'Not Found', 'run 9 was deleted'),
    )

    render(<RunHistory />)
    await waitFor(() => expect(screen.getByText('#9')).toBeTruthy())

    await act(async () => {
      fireEvent.click(screen.getByText('#9'))
    })

    await waitFor(() =>
      expect(
        screen.getByText(/Could not load run #9: it no longer exists/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/run 9 was deleted/)).toBeTruthy()
    // The dashboard was not pointed at a run that could not be fetched.
    expect(useRunStore.getState().runId).toBeNull()
  })
})
