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
  getTrainingSession,
  listTrainingSessions,
  listAuditActions,
  getAuditSummary,
  openInspector,
  advanceInspector,
  closeInspector,
  getRecordedRun,
  setSessionNote,
} from '@/api/client'
import type { AuditAction } from '@/types'
import {
  inspectorState,
  recordedRun,
  recordedState,
  runComparison,
  sessionDetail,
  sessionSummary,
} from './__fixtures__/recorded'

// The endpoints are faked; `ApiError` and `describeApiError` are the real ones, so a
// rejection here carries the status the server would have sent and the components
// read it the way they read a live failure.
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  listTrainingSessions: vi.fn(),
  getTrainingSession: vi.fn(),
  getCapture: vi.fn(),
  getRunComparison: vi.fn(),
  listAuditActions: vi.fn(),
  getAuditSummary: vi.fn(),
  openInspector: vi.fn(),
  advanceInspector: vi.fn(),
  closeInspector: vi.fn(),
  getRecordedRun: vi.fn(),
  setSessionNote: vi.fn(),
}))

/** A rejection shaped like the one `request` produces for a given status. */
function apiError(status: number, statusText: string, detail: string): ApiError {
  return new ApiError(status, statusText, JSON.stringify({ detail }))
}

const mocked = {
  listTrainingSessions: vi.mocked(listTrainingSessions),
  getTrainingSession: vi.mocked(getTrainingSession),
  getCapture: vi.mocked(getCapture),
  getRunComparison: vi.mocked(getRunComparison),
  listAuditActions: vi.mocked(listAuditActions),
  getAuditSummary: vi.mocked(getAuditSummary),
  openInspector: vi.mocked(openInspector),
  advanceInspector: vi.mocked(advanceInspector),
  closeInspector: vi.mocked(closeInspector),
  getRecordedRun: vi.mocked(getRecordedRun),
  setSessionNote: vi.mocked(setSessionNote),
}

/** Wire the browser to serve one session containing `runs`. */
function withRuns(runs = [recordedRun()]) {
  mocked.listTrainingSessions.mockResolvedValue({
    sessions: [sessionSummary({ run_count: runs.length })],
    total: 1,
  })
  mocked.getTrainingSession.mockResolvedValue(sessionDetail(runs))
}

beforeEach(() => {
  for (const m of Object.values(mocked)) m.mockReset()
  mocked.closeInspector.mockResolvedValue(undefined)
  mocked.listAuditActions.mockResolvedValue({
    run_id: 9, total: 0, limit: 60, offset: 0, actions: [],
  })
})

// ---------------------------------------------------------------------------
// The session browser
// ---------------------------------------------------------------------------

describe('SessionBrowser — the coarse-grained level', () => {
  it('lists sessions with their run counts and opens the newest', async () => {
    withRuns([recordedRun({ run_id: 7 }), recordedRun({ run_id: 8, mode: 'audit', action_count: 1200 })])
    render(<ReviewPanel />)

    // The newest session is expanded on mount: a browser that opens on an empty
    // pane makes the reader click to find out whether there is anything at all.
    // Waiting on a *run* row therefore waits on both fetches, the session list and
    // the session's detail, which land in separate ticks.
    await waitFor(() => expect(screen.getByText('#7')).toBeTruthy())
    expect(screen.getByText('Session 3')).toBeTruthy()
    expect(screen.getByText('2 runs')).toBeTruthy()
    expect(screen.getByText('#8')).toBeTruthy()
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

  // The memory clear is the event that defines a Training Session's extent, and it
  // is the only thing a session carries across Run boundaries. A browser that showed
  // OPEN and then nothing at all for the closed case left the boundary invisible: a
  // reader could see that a session stopped gaining Runs but not what stopped it.
  it('says when and why a closed session ended', async () => {
    mocked.listTrainingSessions.mockResolvedValue({
      sessions: [
        sessionSummary({ is_open: false, ended_at: '2026-07-29T10:30:00', run_count: 1 }),
      ],
      total: 1,
    })
    mocked.getTrainingSession.mockResolvedValue({
      ...sessionDetail([recordedRun()]),
      is_open: false,
      ended_at: '2026-07-29T10:30:00',
    })

    render(<ReviewPanel />)
    // Waiting on a run row waits on both fetches: the session list renders the
    // header (and its MEMORY CLEARED badge) a tick before the detail arrives with
    // the sentence underneath, so waiting on the badge alone races the second.
    await waitFor(() => expect(screen.getByText('#7')).toBeTruthy())
    expect(screen.getByText(/MEMORY CLEARED/)).toBeTruthy()
    expect(
      screen.getByText(/Runs after that point started from an empty memory/),
    ).toBeTruthy()
  })

  it('says of an open session that it is still accumulating', async () => {
    withRuns([recordedRun()])
    render(<ReviewPanel />)

    await waitFor(() => expect(screen.getByText('#7')).toBeTruthy())
    expect(screen.getByText(/still accumulating/)).toBeTruthy()
    expect(screen.queryByText(/MEMORY CLEARED/)).toBeNull()
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
    // And what it left for the next Run in the Training Session.
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
// The browser is organised by Training Session, which is right for exploring and
// wrong for a reader who has just watched a run finish on the dashboard: they know
// the run, and the session is precisely the thing they do not know. `#/review/runs/42`
// opens it directly.

describe('ReviewPanel — a Run opened by id', () => {
  it('opens the named Run without being told which session it is in', async () => {
    withRuns([recordedRun({ run_id: 42 })])
    mocked.getRecordedRun.mockResolvedValue(recordedRun({ run_id: 42, session_id: 3 }))
    mocked.getRunComparison.mockResolvedValue(runComparison())
    mocked.getCapture.mockResolvedValue(recordedState())

    render(<ReviewPanel initialRunId={42} />)

    await waitFor(() => expect(mocked.getRecordedRun).toHaveBeenCalledWith(42))
    await waitFor(() => expect(screen.getByText('Run #42')).toBeTruthy())
  })

  it('expands the session containing it, so the highlighted row is on screen', async () => {
    withRuns([recordedRun({ run_id: 42 })])
    mocked.getRecordedRun.mockResolvedValue(recordedRun({ run_id: 42, session_id: 3 }))
    mocked.getRunComparison.mockResolvedValue(runComparison())
    mocked.getCapture.mockResolvedValue(recordedState())

    render(<ReviewPanel initialRunId={42} />)

    await waitFor(() => expect(mocked.getTrainingSession).toHaveBeenCalledWith(3))
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
// The Training Session note
// ---------------------------------------------------------------------------
//
// A session is not created deliberately — it is the span between two Episodic Memory
// clears — so a number and a date range is all that distinguishes one from another.
// The note column has existed since WP3.0, carried by the model, the service and both
// review responses, and nothing ever rendered it or offered to set it.

describe('SessionBrowser — naming a Training Session', () => {
  it('shows a session\'s note beside its number', async () => {
    mocked.listTrainingSessions.mockResolvedValue({
      sessions: [sessionSummary({ note: 'sweep of the five-letter problems' })],
      total: 1,
    })
    mocked.getTrainingSession.mockResolvedValue(
      sessionDetail([recordedRun()], { note: 'sweep of the five-letter problems' }),
    )

    render(<ReviewPanel />)
    await waitFor(() =>
      expect(screen.getAllByText(/sweep of the five-letter problems/).length).toBeGreaterThan(0),
    )
  })

  it('saves an edited note and keeps both places it is shown in step', async () => {
    withRuns()
    mocked.setSessionNote.mockResolvedValue({ session_id: 3, note: 'baseline' })

    render(<ReviewPanel />)
    const field = await screen.findByLabelText('Note')

    fireEvent.change(field, { target: { value: 'baseline' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(mocked.setSessionNote).toHaveBeenCalledWith(3, 'baseline'))
    // The list carries the note as well as the detail, and both are fetched
    // separately: without updating both, the header keeps the old text and the save
    // reads as having failed.
    await waitFor(() =>
      expect(screen.getAllByText('baseline').length).toBeGreaterThan(0),
    )
  })

  it('does not offer to save an unchanged note', async () => {
    withRuns()

    render(<ReviewPanel />)
    await screen.findByLabelText('Note')
    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled()
  })

  it('says when a save did not land, rather than looking as though it did', async () => {
    withRuns()
    mocked.setSessionNote.mockRejectedValue(
      apiError(500, 'Internal Server Error', 'the session row is locked'),
    )

    render(<ReviewPanel />)
    fireEvent.change(await screen.findByLabelText('Note'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(screen.getByText('not saved')).toBeTruthy())
    // And why, so the reader has something to act on.
    expect(
      screen.getByText(/Could not save the session note: the server failed to complete it/),
    ).toBeTruthy()
    expect(screen.getByText(/the session row is locked/)).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// A listing that could not be read, told apart from a listing with nothing in it
// ---------------------------------------------------------------------------
//
// "No Training Sessions recorded yet" is a statement about the database, and so is a
// session with no Runs under it. Each is reserved for the case it describes, and a
// request that failed says so in its own words.

describe('SessionBrowser — a listing that failed to load', () => {
  it('gives the reason instead of saying no sessions have been recorded', async () => {
    mocked.listTrainingSessions.mockRejectedValue(
      apiError(503, 'Service Unavailable', 'the database is not accepting connections'),
    )

    render(<ReviewPanel />)

    await waitFor(() =>
      expect(
        screen.getByText(/Could not load the Training Sessions: the server failed to complete it/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/the database is not accepting connections/)).toBeTruthy()
    expect(screen.queryByText(/No Training Sessions recorded yet/)).toBeNull()
  })

  it('still says so when there genuinely are none', async () => {
    mocked.listTrainingSessions.mockResolvedValue({ sessions: [], total: 0 })

    render(<ReviewPanel />)

    await waitFor(() =>
      expect(screen.getByText(/No Training Sessions recorded yet/)).toBeTruthy(),
    )
  })

  it('reports a session whose Runs could not be read, keeping the list usable', async () => {
    mocked.listTrainingSessions.mockResolvedValue({
      sessions: [sessionSummary({ run_count: 2 })],
      total: 1,
    })
    mocked.getTrainingSession.mockRejectedValue(
      apiError(500, 'Internal Server Error', 'run join failed'),
    )

    render(<ReviewPanel />)

    await waitFor(() =>
      expect(
        screen.getByText(/Could not load the Runs in Training Session 3/),
      ).toBeTruthy(),
    )
    // The session header is still there to collapse, and the rest of the list with it.
    expect(screen.getByText('Session 3')).toBeTruthy()
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
// ---------------------------------------------------------------------------
//
// Both listings the review surfaces read are paged by the server: `GET
// /api/review/sessions` takes a limit and an offset, and so does `GET
// /api/review/runs/{id}/actions`. Each shows one window at a time, reports the
// total behind it, and moves the window on request, so every recorded session and
// every recorded action is reachable.

describe('SessionBrowser — paging', () => {
  it('asks for the next window of sessions and renders it', async () => {
    mocked.listTrainingSessions.mockImplementation(async (_limit, offset) => ({
      sessions: [sessionSummary({ session_id: offset === 0 ? 137 : 87 })],
      total: 137,
    }))
    mocked.getTrainingSession.mockImplementation(async (id) =>
      sessionDetail([recordedRun()], { session_id: id }),
    )
    mocked.getCapture.mockResolvedValue(recordedState())
    mocked.getRunComparison.mockResolvedValue(runComparison())

    render(<ReviewPanel />)
    await waitFor(() => expect(screen.getByText('Session 137')).toBeTruthy())
    expect(mocked.listTrainingSessions).toHaveBeenCalledWith(50, 0)
    expect(screen.getByText('1–1 of 137 Training Sessions')).toBeTruthy()

    await act(async () => {
      screen.getByRole('button', { name: /next page of Training Sessions/i }).click()
    })

    await waitFor(() => expect(mocked.listTrainingSessions).toHaveBeenCalledWith(50, 50))
    await waitFor(() => expect(screen.getByText('Session 87')).toBeTruthy())
    expect(screen.getByText('51–51 of 137 Training Sessions')).toBeTruthy()
    expect(screen.queryByText('Session 137')).toBeNull()
  })

  it('offers no next window when every session is on screen', async () => {
    withRuns()

    render(<ReviewPanel />)
    await waitFor(() => expect(screen.getByText('1–1 of 1 Training Sessions')).toBeTruthy())
    expect(screen.getByRole('button', { name: /next page of Training Sessions/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /previous page of Training Sessions/i })).toBeDisabled()
  })
})

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
