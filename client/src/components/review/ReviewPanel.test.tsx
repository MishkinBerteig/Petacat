// ---------------------------------------------------------------------------
// Petacat -- the review surfaces read the record back (WP3.9)
// ---------------------------------------------------------------------------
//
// What is worth testing here is not the styling but the three claims the review
// UX makes, each of which has a plausible wrong version:
//
//   1. A Fast Run has nothing to review, and the surface must say so rather than
//      look broken. The wrong version renders an empty panel or an error.
//   2. Which review a Run gets is decided by its mode, because the modes record
//      genuinely different things.
//   3. The Audit inspector steps *forward only*, and neither offers a way back nor
//      quietly restarts when the server refuses one.
//
// Everything is driven through the API client, mocked, because these components
// are about what the record says and not about how it is fetched.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'

import { ReviewPanel } from './ReviewPanel'
import {
  ApiError,
  getCapture,
  getRunComparison,
  listEpisodicRuns,
  listAuditActions,
  getAuditSummary,
  openInspector,
  advanceInspector,
  closeInspector,
  getRecordedRun,
  setMemoryClearNote,
} from '@/api/client'
import type { AuditAction } from '@/types'
import {
  inspectorState,
  recordedRun,
  recordedState,
  runComparison,
  memoryClear,
  timeline,
} from './__fixtures__/recorded'

// The endpoints are faked; `ApiError` and `describeApiError` are the real ones, so a
// rejection here carries the status the server would have sent and the components
// read it the way they read a live failure.
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  listEpisodicRuns: vi.fn(),
  getCapture: vi.fn(),
  getRunComparison: vi.fn(),
  listAuditActions: vi.fn(),
  getAuditSummary: vi.fn(),
  openInspector: vi.fn(),
  advanceInspector: vi.fn(),
  closeInspector: vi.fn(),
  getRecordedRun: vi.fn(),
  setMemoryClearNote: vi.fn(),
}))

/** A rejection shaped like the one `request` produces for a given status. */
function apiError(status: number, statusText: string, detail: string): ApiError {
  return new ApiError(status, statusText, JSON.stringify({ detail }))
}

const mocked = {
  listEpisodicRuns: vi.mocked(listEpisodicRuns),
  getCapture: vi.mocked(getCapture),
  getRunComparison: vi.mocked(getRunComparison),
  listAuditActions: vi.mocked(listAuditActions),
  getAuditSummary: vi.mocked(getAuditSummary),
  openInspector: vi.mocked(openInspector),
  advanceInspector: vi.mocked(advanceInspector),
  closeInspector: vi.mocked(closeInspector),
  getRecordedRun: vi.mocked(getRecordedRun),
  setMemoryClearNote: vi.mocked(setMemoryClearNote),
}

/** Wire the timeline to serve one window containing `runs`, newest first. */
function withRuns(runs = [recordedRun()]) {
  mocked.listEpisodicRuns.mockResolvedValue(timeline(runs))
}

beforeEach(() => {
  for (const m of Object.values(mocked)) m.mockReset()
  mocked.closeInspector.mockResolvedValue(undefined)
  mocked.listAuditActions.mockResolvedValue({
    run_id: 9, total: 0, limit: 60, offset: 0, actions: [],
  })
})

// ---------------------------------------------------------------------------
// The episodic-run timeline
// ---------------------------------------------------------------------------

describe('EpisodicRunTimeline — the coarse-grained level', () => {
  it('lists the recorded runs, newest first', async () => {
    withRuns([recordedRun({ run_id: 8, mode: 'audit', action_count: 1200 }), recordedRun({ run_id: 7 })])
    render(<ReviewPanel />)

    await waitFor(() => expect(screen.getByText('#7')).toBeTruthy())
    expect(screen.getByText('#8')).toBeTruthy()
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows[0].textContent).toContain('#8')
    expect(rows[1].textContent).toContain('#7')
    expect(mocked.listEpisodicRuns).toHaveBeenCalledWith(50, 0)
  })

  it('never calls anything an episodic run is in a session', async () => {
    withRuns()
    render(<ReviewPanel />)
    await waitFor(() => expect(screen.getByText('#7')).toBeTruthy())
    expect(document.body.textContent).not.toMatch(/session/i)
  })

  it('shows each run its mode, problem, answer and both hashes', async () => {
    withRuns([recordedRun()])
    render(<ReviewPanel />)

    await waitFor(() => expect(screen.getByText('#7')).toBeTruthy())
    expect(screen.getAllByText('normal').length).toBeGreaterThan(0)
    expect(screen.getByText('abc→abd; mrrjjj→?')).toBeTruthy()
    expect(screen.getByText('mrrkkk')).toBeTruthy()
    // Abbreviated: the full hashes are in the title, since 32 hex characters twice
    // over would be the widest column in the table and the least readable.
    expect(screen.getByText('c0nf1g / m3m0ry')).toBeTruthy()
  })

  it('opens a run when its row is clicked', async () => {
    withRuns([recordedRun({ run_id: 7 })])
    mocked.getRunComparison.mockResolvedValue(runComparison())
    mocked.getCapture.mockResolvedValue(recordedState())
    render(<ReviewPanel />)

    await waitFor(() => expect(screen.getByText('#7')).toBeTruthy())
    expect(screen.getByText('Select a Run to review it.')).toBeTruthy()
    await act(async () => {
      screen.getByText('#7').closest('tr')!.click()
    })
    await waitFor(() => expect(screen.getByText('Run #7')).toBeTruthy())
    expect(screen.getByRole('row', { selected: true })).toBeTruthy()
  })

  it('opens a run from its accessible button', async () => {
    withRuns([recordedRun({ run_id: 7 })])
    mocked.getRunComparison.mockResolvedValue(runComparison())
    mocked.getCapture.mockResolvedValue(recordedState())
    render(<ReviewPanel />)

    fireEvent.click(await screen.findByRole('button', { name: 'Open run 7' }))
    await waitFor(() => expect(screen.getByText('Run #7')).toBeTruthy())
  })

  // A clear is an event between runs, not a container for them. The marker sits
  // exactly where the server put it, so a reader sees which runs inherited what.
  it('puts an "Episodic Memory cleared" marker between the runs it separates', async () => {
    mocked.listEpisodicRuns.mockResolvedValue(
      timeline([
        recordedRun({ run_id: 9 }),
        memoryClear({ clear_id: 4, after_run_id: 8, cleared_at: '2026-07-29T10:30:00' }),
        recordedRun({ run_id: 8 }),
        recordedRun({ run_id: 7 }),
      ]),
    )
    render(<ReviewPanel />)

    const marker = await screen.findByTestId('memory-clear-4')
    expect(marker.textContent).toMatch(/Episodic Memory cleared — /)
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows.map((r) => (r.getAttribute('data-testid') ?? r.textContent!.match(/#\d/)![0]))).toEqual([
      '#9',
      'memory-clear-4',
      '#8',
      '#7',
    ])
  })

  it('shows a clear after the newest run at the top, and one with no earlier run at the end', async () => {
    mocked.listEpisodicRuns.mockResolvedValue(
      timeline([
        memoryClear({ clear_id: 5, after_run_id: 9 }),
        recordedRun({ run_id: 9 }),
        memoryClear({ clear_id: 3, after_run_id: null }),
      ]),
    )
    render(<ReviewPanel />)

    await screen.findByTestId('memory-clear-5')
    const ids = screen
      .getAllByRole('row')
      .slice(1)
      .map((r) => r.getAttribute('data-testid') ?? 'run')
    expect(ids).toEqual(['memory-clear-5', 'run', 'memory-clear-3'])
  })

  it('shows no marker when the memory was never cleared', async () => {
    withRuns([recordedRun()])
    render(<ReviewPanel />)
    await waitFor(() => expect(screen.getByText('#7')).toBeTruthy())
    expect(screen.queryByText(/Episodic Memory cleared/)).toBeNull()
  })

  it('reports how much record each mode left', async () => {
    withRuns([
      recordedRun({ run_id: 7, mode: 'normal', capture_count: 2, action_count: 0 }),
      recordedRun({ run_id: 8, mode: 'audit', capture_count: 2, action_count: 1200 }),
    ])
    render(<ReviewPanel />)

    await waitFor(() => expect(screen.getByText('#8')).toBeTruthy())
    expect(screen.getByText('2 cap')).toBeTruthy()
    expect(screen.getByText(/2 cap.*1200 act/)).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// Fast: nothing to review, said plainly
// ---------------------------------------------------------------------------

describe('a Fast Run', () => {
  it('says it recorded nothing rather than looking broken', async () => {
    withRuns([recordedRun({ run_id: 4, mode: 'fast', capture_count: 0, action_count: 0 })])
    render(<ReviewPanel />)

    await waitFor(() => expect(screen.getByText('#4')).toBeTruthy())
    // The listing already says so...
    expect(screen.getByText('none')).toBeTruthy()

    await act(async () => {
      screen.getByText('#4').closest('tr')!.click()
    })

    // ...and so does the review pane, in words, without an error and without
    // having asked the server for a capture that cannot exist.
    await waitFor(() =>
      expect(screen.getByText(/records\s+nothing/)).toBeTruthy(),
    )
    expect(screen.getByText(/the mode doing what it\s+promises/)).toBeTruthy()
    expect(mocked.getCapture).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Normal: start, end, and what changed
// ---------------------------------------------------------------------------

describe('NormalRunReview', () => {
  async function openNormalRun() {
    withRuns([recordedRun({ run_id: 7, mode: 'normal' })])
    mocked.getCapture.mockImplementation(async (_runId, boundary) =>
      boundary === 'start'
        ? recordedState({ boundary: 'start', codelet_count: 0, temperature: 100 })
        : recordedState({ boundary: 'end', codelet_count: 783, temperature: 57 }),
    )
    mocked.getRunComparison.mockResolvedValue(runComparison())

    render(<ReviewPanel />)
    await waitFor(() => expect(screen.getByText('#7')).toBeTruthy())
    await act(async () => {
      screen.getByText('#7').closest('tr')!.click()
    })
  }

  it('fetches both boundary captures and the comparison', async () => {
    await openNormalRun()
    await waitFor(() => expect(mocked.getRunComparison).toHaveBeenCalledWith(7))
    expect(mocked.getCapture).toHaveBeenCalledWith(7, 'start')
    expect(mocked.getCapture).toHaveBeenCalledWith(7, 'end')
  })

  it('summarises what the run did rather than dumping both captures', async () => {
    await openNormalRun()
    await waitFor(() => expect(screen.getByText('Start → end')).toBeTruthy())

    // Temperature fell, and falling is the good direction — the system organising
    // the problem — so the delta is shown as such.
    expect(screen.getByText('100 → 57')).toBeTruthy()
    expect(screen.getByText('-43')).toBeTruthy()
    // Structures built, counted across strings.
    expect(screen.getByText('+7')).toBeTruthy()   // bonds: abc 2 + mrrjjj 5
    expect(screen.getByText('+4')).toBeTruthy()   // bridges: 2 top + 2 vertical
    // The concepts the run recruited, and the themes it ended holding.
    expect(screen.getByText(/successor \+100/)).toBeTruthy()
    expect(screen.getByText(/string-position-category = identity/)).toBeTruthy()
    // And what it left for the next Run in Episodic Memory.
    expect(screen.getByText(/abc abd mrrjjj mrrkkk/)).toBeTruthy()
  })

  it('renders the recorded state through the dashboard views', async () => {
    await openNormalRun()
    await waitFor(() => expect(screen.getByText('Start → end')).toBeTruthy())

    // The Workspace panel is the dashboard's own `WorkspaceDiagram`: an SVG whose
    // letters come from the recorded workspace.
    const svg = document.querySelector('svg')
    expect(svg).toBeTruthy()
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual([
      'Workspace', 'Slipnet', 'Themespace', 'Coderack', 'Trace',
    ])
  })

  it('switches between the recorded start and end states', async () => {
    await openNormalRun()
    await waitFor(() => expect(screen.getByText('Start → end')).toBeTruthy())

    const endButton = screen.getByRole('button', { name: /Run end/ })
    const startButton = screen.getByRole('button', { name: /Run start/ })
    expect(endButton.getAttribute('aria-pressed')).toBe('true')
    expect(startButton.textContent).toContain('c:0')
    expect(endButton.textContent).toContain('c:783')

    await act(async () => { startButton.click() })
    expect(startButton.getAttribute('aria-pressed')).toBe('true')
  })
})

// ---------------------------------------------------------------------------
// Audit: the forward-only inspector
// ---------------------------------------------------------------------------

describe('AuditRunReview — forward-stepping only', () => {
  async function openAuditRun() {
    withRuns([recordedRun({ run_id: 9, mode: 'audit', action_count: 1200, capture_count: 2 })])
    mocked.openInspector.mockResolvedValue(inspectorState({ run_id: 9 }))
    mocked.getAuditSummary.mockResolvedValue({
      run_id: 9,
      by_type: { codelet: 400, structure_built: 30 },
      first_codelet: 1,
      last_codelet: 400,
      total: 430,
    })

    render(<ReviewPanel />)
    await waitFor(() => expect(screen.getByText('#9')).toBeTruthy())
    await act(async () => {
      screen.getByText('#9').closest('tr')!.click()
    })
    await waitFor(() => expect(mocked.openInspector).toHaveBeenCalledWith(9))
  }

  it('opens on the Run-start capture at tick 0', async () => {
    await openAuditRun()
    await waitFor(() => expect(screen.getByRole('progressbar')).toBeTruthy())
    expect(screen.getByText('/ 400')).toBeTruthy()
    expect(screen.getByText(/before the first codelet/)).toBeTruthy()
  })

  it('offers only forward steps', async () => {
    await openAuditRun()
    await waitFor(() => expect(screen.getByRole('progressbar')).toBeTruthy())

    const steps = screen
      .getAllByRole('button')
      .map((b) => b.textContent ?? '')
      .filter((t) => /^[+-]\d+$/.test(t))
    expect(steps).toEqual(['+1', '+5', '+15', '+100'])
    expect(steps.some((s) => s.startsWith('-'))).toBe(false)

    // The position indicator is a progressbar, not a slider: it reports where the
    // inspection is and cannot be dragged to somewhere earlier.
    const bar = screen.getByRole('progressbar')
    expect(bar).toBeTruthy()
    expect(screen.queryByRole('slider')).toBeNull()
  })

  it('steps forward by asking for a destination, not a count', async () => {
    await openAuditRun()
    await waitFor(() => expect(screen.getByRole('progressbar')).toBeTruthy())

    mocked.advanceInspector.mockResolvedValue(
      inspectorState({
        run_id: 9,
        codelet_count: 15,
        temperature: 96,
        recorded_temperature: 96,
        codelet: {
          sequence: 20, codelet_count: 15, action_type: 'codelet', temperature: 96,
          payload: { codelet_type: 'bottom-up-bond-scout', urgency: 30 }, before: null,
        },
        structure_changes: [
          {
            sequence: 21, codelet_count: 15, action_type: 'structure_built', temperature: 96,
            payload: { structure: 'Bond', id: 42, strength: 71, proposal_level: 'built' },
            before: { proposal_level: 'evaluated' },
          },
        ],
      }),
    )

    await act(async () => {
      screen.getByRole('button', { name: '+15' }).click()
    })

    // A destination, so a retried request cannot double-step.
    expect(mocked.advanceInspector).toHaveBeenCalledWith(9, 15)
    await waitFor(() => expect(screen.getByText('bottom-up-bond-scout')).toBeTruthy())
    expect(screen.getByText('+Bond #42')).toBeTruthy()
    // The reconstruction agrees with the record, and the UI says so rather than
    // leaving the reader to trust it.
    expect(screen.getByText('matches the record')).toBeTruthy()
  })

  it('surfaces the server refusing to step back instead of restarting', async () => {
    await openAuditRun()
    await waitFor(() => expect(screen.getByRole('progressbar')).toBeTruthy())

    mocked.advanceInspector.mockRejectedValue(
      apiError(409, 'Conflict', 'Phase 0 steps forward only.'),
    )
    await act(async () => {
      screen.getByRole('button', { name: '+1' }).click()
    })

    await waitFor(() =>
      expect(screen.getByText('The inspector steps forward only.')).toBeTruthy(),
    )
    // A silent re-open would be indistinguishable, from outside, from having
    // actually stepped back — so it must not happen.
    expect(mocked.openInspector).toHaveBeenCalledTimes(1)
  })

  it('names the reason a step failed for any other cause', async () => {
    await openAuditRun()
    await waitFor(() => expect(screen.getByRole('progressbar')).toBeTruthy())

    mocked.advanceInspector.mockRejectedValue(
      apiError(500, 'Internal Server Error', 'the reconstruction ran out of memory'),
    )
    await act(async () => {
      screen.getByRole('button', { name: '+1' }).click()
    })

    await waitFor(() =>
      expect(
        screen.getByText(/Could not step the inspection forward: the server failed to complete it/),
      ).toBeTruthy(),
    )
    expect(
      screen.getByText(/the reconstruction ran out of memory/),
    ).toBeTruthy()
  })

  it('says why the recorded action log is empty, rather than showing an empty one', async () => {
    withRuns([recordedRun({ run_id: 9, mode: 'audit', action_count: 1200, capture_count: 2 })])
    mocked.openInspector.mockResolvedValue(inspectorState({ run_id: 9 }))
    mocked.getAuditSummary.mockResolvedValue({
      run_id: 9, by_type: {}, first_codelet: 1, last_codelet: 400, total: 430,
    })
    mocked.listAuditActions.mockRejectedValue(
      apiError(503, 'Service Unavailable', 'the database is not accepting connections'),
    )

    render(<ReviewPanel />)
    await waitFor(() => expect(screen.getByText('#9')).toBeTruthy())
    await act(async () => {
      screen.getByText('#9').closest('tr')!.click()
    })

    // A window holding no actions is a claim about the record; this one is a claim
    // about the request, and the two must not read alike.
    await waitFor(() =>
      expect(
        screen.getByText(/Could not load the recorded action log/),
      ).toBeTruthy(),
    )
  })

  it('stops at the end of the record and offers a restart', async () => {
    await openAuditRun()
    await waitFor(() => expect(screen.getByRole('progressbar')).toBeTruthy())

    mocked.advanceInspector.mockResolvedValue(
      inspectorState({ run_id: 9, codelet_count: 400, at_end: true }),
    )
    await act(async () => {
      screen.getByRole('button', { name: '+100' }).click()
    })

    await waitFor(() => expect(screen.getByText(/At the end of the record/)).toBeTruthy())
    for (const n of ['+1', '+5', '+15', '+100']) {
      expect(screen.getByRole('button', { name: n }).hasAttribute('disabled')).toBe(true)
    }
    expect(screen.getByRole('button', { name: /restart/ }).hasAttribute('disabled')).toBe(false)
  })

  it('releases the held inspection when it goes away', async () => {
    await openAuditRun()
    await waitFor(() => expect(screen.getByRole('progressbar')).toBeTruthy())

    // Selecting another run unmounts the inspector; an open inspection holds a
    // whole engine on the server, so it has to be given back.
    withRuns([
      recordedRun({ run_id: 9, mode: 'audit', action_count: 1200 }),
      recordedRun({ run_id: 7, mode: 'normal' }),
    ])
    mocked.getCapture.mockResolvedValue(recordedState())
    mocked.getRunComparison.mockResolvedValue(runComparison())

    await act(async () => {
      screen.getByText('#9').closest('tr')!.click()
    })
    await waitFor(() => expect(mocked.closeInspector).not.toBeUndefined())
  })
})

// ---------------------------------------------------------------------------
// Arriving with a Run already in mind
// ---------------------------------------------------------------------------
//
// The timeline is paged, which is right for exploring and slow for a reader who has
// just watched a run finish on the dashboard: they know the run. `#/review/runs/42`
// opens it directly.

describe('ReviewPanel — a Run opened by id', () => {
  it('opens the named Run without paging the timeline to it', async () => {
    withRuns([recordedRun({ run_id: 42 })])
    mocked.getRecordedRun.mockResolvedValue(recordedRun({ run_id: 42 }))
    mocked.getRunComparison.mockResolvedValue(runComparison())
    mocked.getCapture.mockResolvedValue(recordedState())

    render(<ReviewPanel initialRunId={42} />)

    await waitFor(() => expect(mocked.getRecordedRun).toHaveBeenCalledWith(42))
    await waitFor(() => expect(screen.getByText('Run #42')).toBeTruthy())
  })

  it('says a Fast Run has no record rather than sitting on "select a Run"', async () => {
    withRuns([])
    mocked.getRecordedRun.mockRejectedValue(
      apiError(404, 'Not Found', 'no recorded run -1'),
    )

    render(<ReviewPanel initialRunId={-1} />)

    await waitFor(() =>
      expect(screen.getByText(/Run #-1 has no record to review/)).toBeTruthy(),
    )
  })

  // A 404 is the record being absent, which for a Fast Run is the mode working. Any
  // other status is the server failing to hand over a record that exists, so it is
  // reported as a failure and the record is left where it is.
  it('reports a server failure as a failure, not as an absent record', async () => {
    withRuns([])
    mocked.getRecordedRun.mockRejectedValue(
      apiError(500, 'Internal Server Error', 'capture row is corrupt'),
    )

    render(<ReviewPanel initialRunId={42} />)

    await waitFor(() =>
      expect(
        screen.getByText(/Could not load the recorded run #42: the server failed to complete it/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/capture row is corrupt/)).toBeTruthy()
    expect(screen.queryByText(/has no record to review/)).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// The note on an Episodic Memory clear
// ---------------------------------------------------------------------------
//
// A clear is an event with nothing else to distinguish it from the next but its date,
// so the one editable thing about it is a note saying why the memory was cleared.

describe('EpisodicRunTimeline — noting an Episodic Memory clear', () => {
  function withClear(note = '') {
    mocked.listEpisodicRuns.mockResolvedValue(
      timeline([recordedRun({ run_id: 8 }), memoryClear({ clear_id: 4, note }), recordedRun({ run_id: 7 })]),
    )
  }

  it("shows a clear's note in its marker", async () => {
    withClear('sweep of the five-letter problems')
    render(<ReviewPanel />)
    const field = await screen.findByDisplayValue('sweep of the five-letter problems')
    expect(field.closest('[data-testid="memory-clear-4"]')).toBeTruthy()
  })

  it('saves an edited note against that clear and shows the saved text', async () => {
    withClear()
    mocked.setMemoryClearNote.mockResolvedValue(memoryClear({ clear_id: 4, note: 'baseline' }))

    render(<ReviewPanel />)
    const field = await screen.findByLabelText(/Note on the Episodic Memory clear/)

    fireEvent.change(field, { target: { value: 'baseline' } })
    fireEvent.click(screen.getByRole('button', { name: /Save the note on the clear/ }))

    await waitFor(() => expect(mocked.setMemoryClearNote).toHaveBeenCalledWith(4, 'baseline'))
    // Saved means the marker shows it and no longer offers to save it again.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Save the note on the clear/ })).toBeDisabled(),
    )
    expect((screen.getByLabelText(/Note on the Episodic Memory clear/) as HTMLInputElement).value).toBe('baseline')
    // The window was not refetched to show it.
    expect(mocked.listEpisodicRuns).toHaveBeenCalledTimes(1)
  })

  it('does not offer to save an unchanged note', async () => {
    withClear('as it was')
    render(<ReviewPanel />)
    await screen.findByLabelText(/Note on the Episodic Memory clear/)
    expect(screen.getByRole('button', { name: /Save the note on the clear/ })).toBeDisabled()
  })

  it('says when a save did not land, rather than looking as though it did', async () => {
    withClear()
    mocked.setMemoryClearNote.mockRejectedValue(
      apiError(500, 'Internal Server Error', 'the clear row is locked'),
    )

    render(<ReviewPanel />)
    fireEvent.change(await screen.findByLabelText(/Note on the Episodic Memory clear/), {
      target: { value: 'x' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Save the note on the clear/ }))

    await waitFor(() => expect(screen.getByText('not saved')).toBeTruthy())
    expect(
      screen.getByText(/Could not save the note on the Episodic Memory clear: the server failed to complete it/),
    ).toBeTruthy()
    expect(screen.getByText(/the clear row is locked/)).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// A listing that could not be read, told apart from a listing with nothing in it
// ---------------------------------------------------------------------------

describe('EpisodicRunTimeline — a listing that failed to load', () => {
  it('gives the reason instead of saying no runs have been recorded', async () => {
    mocked.listEpisodicRuns.mockRejectedValue(
      apiError(503, 'Service Unavailable', 'the database is not accepting connections'),
    )

    render(<ReviewPanel />)

    await waitFor(() =>
      expect(
        screen.getByText(/Could not load the episodic runs: the server failed to complete it/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/the database is not accepting connections/)).toBeTruthy()
    expect(screen.queryByText(/No episodic runs recorded yet/)).toBeNull()
  })

  it('still says so when there genuinely are none', async () => {
    mocked.listEpisodicRuns.mockResolvedValue(timeline([]))

    render(<ReviewPanel />)

    await waitFor(() =>
      expect(screen.getByText(/No episodic runs recorded yet/)).toBeTruthy(),
    )
  })
})

// ---------------------------------------------------------------------------
// A Normal Run whose captures could not be read
// ---------------------------------------------------------------------------

describe('NormalRunReview — a record that would not load', () => {
  it('names the reason rather than showing a review with nothing in it', async () => {
    withRuns([recordedRun({ run_id: 7, mode: 'normal', capture_count: 2 })])
    mocked.getCapture.mockRejectedValue(
      apiError(500, 'Internal Server Error', 'capture blob failed to decompress'),
    )
    mocked.getRunComparison.mockResolvedValue(runComparison())

    render(<ReviewPanel />)
    await waitFor(() => expect(screen.getByText('#7')).toBeTruthy())
    await act(async () => {
      screen.getByText('#7').closest('tr')!.click()
    })

    await waitFor(() =>
      expect(
        screen.getByText(/Could not read the record for run #7: the server failed to complete it/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/capture blob failed to decompress/)).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// Reaching the records past the first window
describe('AuditRunReview — paging the recorded action log', () => {
  /** One recorded action, identifiable by its sequence number. */
  function loggedAction(seq: number): AuditAction {
    return {
      sequence: seq,
      codelet_count: seq,
      action_type: 'codelet',
      temperature: 90,
      payload: { codelet_type: `codelet-${seq}`, urgency: 30 },
      before: null,
    }
  }

  async function openAuditRunWithLog() {
    withRuns([recordedRun({ run_id: 9, mode: 'audit', action_count: 1200, capture_count: 2 })])
    mocked.openInspector.mockResolvedValue(inspectorState({ run_id: 9 }))
    mocked.getAuditSummary.mockResolvedValue({
      run_id: 9,
      by_type: { codelet: 400 },
      first_codelet: 1,
      last_codelet: 400,
      total: 430,
    })
    mocked.listAuditActions.mockImplementation(async (_runId, opts) => {
      const offset = opts?.offset ?? 0
      return {
        run_id: 9,
        total: 430,
        limit: 60,
        offset,
        actions: [loggedAction(offset === 0 ? 1 : 61)],
      }
    })

    render(<ReviewPanel />)
    await waitFor(() => expect(screen.getByText('#9')).toBeTruthy())
    await act(async () => {
      screen.getByText('#9').closest('tr')!.click()
    })
    await waitFor(() => expect(mocked.openInspector).toHaveBeenCalledWith(9))
  }

  it('asks for the next window of actions and renders it', async () => {
    await openAuditRunWithLog()
    await waitFor(() => expect(screen.getByText('codelet-1 (urgency 30)')).toBeTruthy())
    expect(screen.getByText('1–1 of 430 actions from tick 0')).toBeTruthy()

    await act(async () => {
      screen.getByRole('button', { name: /next page of actions/i }).click()
    })

    await waitFor(() =>
      expect(mocked.listAuditActions).toHaveBeenCalledWith(9, {
        from_codelet: 0,
        limit: 60,
        offset: 60,
      }),
    )
    await waitFor(() => expect(screen.getByText('codelet-61 (urgency 30)')).toBeTruthy())
    expect(screen.getByText('61–61 of 430 actions from tick 0')).toBeTruthy()
  })

  it('starts the log window again when the inspection steps to a new tick', async () => {
    await openAuditRunWithLog()
    await waitFor(() => expect(screen.getByText('codelet-1 (urgency 30)')).toBeTruthy())

    await act(async () => {
      screen.getByRole('button', { name: /next page of actions/i }).click()
    })
    await waitFor(() => expect(screen.getByText('codelet-61 (urgency 30)')).toBeTruthy())

    // A new tick anchors the log somewhere else, so a position measured from the
    // old anchor no longer means anything.
    mocked.advanceInspector.mockResolvedValue(
      inspectorState({ run_id: 9, codelet_count: 15, temperature: 96 }),
    )
    await act(async () => {
      screen.getByRole('button', { name: '+15' }).click()
    })

    await waitFor(() =>
      expect(mocked.listAuditActions).toHaveBeenCalledWith(9, {
        from_codelet: 13,
        limit: 60,
        offset: 0,
      }),
    )
    await waitFor(() => expect(screen.getByText('1–1 of 430 actions from tick 13')).toBeTruthy())
  })
})
