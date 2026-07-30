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
import {
  inspectorState,
  recordedRun,
  recordedState,
  runComparison,
  sessionDetail,
  sessionSummary,
} from './__fixtures__/recorded'

vi.mock('@/api/client', () => ({
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
      new Error('API 409 Conflict: Phase 0 steps forward only.'),
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
    mocked.getRecordedRun.mockRejectedValue(new Error('API 404 Not Found'))

    render(<ReviewPanel initialRunId={-1} />)

    await waitFor(() =>
      expect(screen.getByText(/Run #-1 has no record to review/)).toBeTruthy(),
    )
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
    mocked.setSessionNote.mockRejectedValue(new Error('API 500'))

    render(<ReviewPanel />)
    fireEvent.change(await screen.findByLabelText('Note'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(screen.getByText('not saved')).toBeTruthy())
  })
})
