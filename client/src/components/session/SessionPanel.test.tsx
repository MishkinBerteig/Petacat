// ---------------------------------------------------------------------------
// Petacat -- Tests for the Training Mode Sessions view
// ---------------------------------------------------------------------------
//
// What these defend: the list shows each session's progress and the executor line; a
// new session is created from the parsed problems and a long list is split to the
// server's per-request limit; problems can be added in every state; every Training Mode Session has
// an Episodic Memory and no control for its mode; the table filters by status and expands
// a row into its distribution; the controls (start, pause, resume, stop, cancel, delete)
// call the right routes and show the server's complaint; polling stops when the view
// goes away.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react'

import { SessionPanel } from './SessionPanel'
import { useRunStore } from '@/store/runStore'
import {
  ApiError,
  addSessionProblems,
  sessionExportUrl,
  cancelSession,
  cancelSessionProblem,
  createSession,
  deleteSession,
  getSession,
  getSessionProblem,
  getDemos,
  getSwarmStatus,
  updateSession,
  getSessionProblemRuns,
  getSessionMemory,
  listSessionProblems,
  listSessions,
  pauseSession,
  resumeSession,
  startSession,
  stopSession,
} from '@/api/client'
import type {
  SessionErrorPolicy,
  SessionListResponse,
  SessionProblemDetail,
  SessionProblemRow,
  SessionSummary,
} from '@/types'

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  listSessions: vi.fn(),
  createSession: vi.fn(),
  getSession: vi.fn(),
  addSessionProblems: vi.fn(),
  listSessionProblems: vi.fn(),
  getSessionProblem: vi.fn(),
  cancelSessionProblem: vi.fn(),
  pauseSession: vi.fn(),
  resumeSession: vi.fn(),
  startSession: vi.fn(),
  stopSession: vi.fn(),
  cancelSession: vi.fn(),
  deleteSession: vi.fn(),
  getDemos: vi.fn(),
  getSwarmStatus: vi.fn(),
  updateSession: vi.fn(),
  getSessionProblemRuns: vi.fn(),
  getSessionMemory: vi.fn(),
}))

function apiError(status: number, detail: string): ApiError {
  return new ApiError(status, 'x', JSON.stringify({ detail }))
}

const POLICY: SessionErrorPolicy = {
  on_run_error: 'record',
  max_errors_per_problem: null,
  max_errors_total: null,
  on_worker_failure: 'retry',
  max_retries: 3,
}

function session(over: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: 1,
    name: 'Pilot',
    note: '',
    state: 'running',
    activity: null,
    stalled_reason: null,
    settings: {
      seeds_per_problem: 100,
      seed_start: 1,
      max_codelets: 20000,
      parameters: null,
      backend: 'off',
    },
    policy: POLICY,
    memory: { answers: 12, snags: 3 },
    memory_version: 9,
    last_event: null,
    config_hash: 'abcdef012345',
    created_at: '2026-10-30T10:00:00',
    updated_at: '2026-10-30T10:05:00',
    stopped_at: null,
    stopped_from: null,
    stop_reason: null,
    problems: { total: 4, queued: 1, running: 1, finished: 2, cancelled: 0 },
    runs: { total: 400, done: 250, errors: 2, capped: 5, retries: 1 },
    codelets: 1_234_567,
    runs_per_second: 42.5,
    eta_seconds: 125,
    finished_cursor: 2,
    source: 'live',
    persisted: false,
    saved_through: { stopped_at: null, configuration_revision: null, episode_version: 0 },
    unsaved: { runs: 250, merges: 250, problems: 0, outcomes: 2, edits: 0, configuration_batches: 0 },
    ...over,
  }
}

function row(over: Partial<SessionProblemRow> = {}): SessionProblemRow {
  return {
    id: 10,
    session_id: 1,
    initial: 'abc',
    modified: 'abd',
    target: 'xyz',
    answer: null,
    seeds: 100,
    seed_start: 1,
    tag: null,
    status: 'finished',
    runs_done: 100,
    errors: 0,
    capped: 0,
    mean_codelets: 1234.4,
    top: [
      { answer: 'xyd', count: 40, fraction: 0.4, mean_quality: 50 },
      { answer: 'wyz', count: 30, fraction: 0.3, mean_quality: 90 },
    ],
    none_fraction: 0.05,
    distinct: 4,
    statuses: { answer_found: 95, step_limit: 5 },
    finished_seq: 1,
    added_at: '2026-10-30T10:00:00',
    started_at: '2026-10-30T10:00:01',
    finished_at: '2026-10-30T10:01:00',
    ...over,
  }
}

function detail(over: Partial<SessionProblemDetail> = {}): SessionProblemDetail {
  return {
    ...row(),
    distribution: [
      { answer: 'xyd', count: 40, fraction: 0.4, mean_quality: 50 },
      { answer: 'wyz', count: 30, fraction: 0.3, mean_quality: 90 },
      { answer: '*NONE*', count: 5, fraction: 0.05, mean_quality: null },
    ],
    first_error: null,
    ...over,
  }
}

const LIST: SessionListResponse = {
  sessions: [
    session(),
    session({
      id: 2,
      name: 'Done one',
      state: 'running',
      activity: 'idle',
      problems: { total: 2, queued: 0, running: 0, finished: 2, cancelled: 0 },
      runs: { total: 200, done: 200, errors: 0, capped: 0, retries: 0 },
    }),
  ],
  executor: { kind: 'swarm', workers: 17, in_flight: 34, queued_runs: 12000 },
  limits: { max_problems_per_request: 1000, max_seeds_per_problem: 10000, max_codelets: 200000 },
  defaults: {
    settings: { seeds_per_problem: 100, seed_start: 1, max_codelets: 20000, parameters: null, backend: 'off' },
    policy: POLICY,
  },
}

const m = {
  listSessions: vi.mocked(listSessions),
  createSession: vi.mocked(createSession),
  getSession: vi.mocked(getSession),
  addSessionProblems: vi.mocked(addSessionProblems),
  listSessionProblems: vi.mocked(listSessionProblems),
  getSessionProblem: vi.mocked(getSessionProblem),
  cancelSessionProblem: vi.mocked(cancelSessionProblem),
  pauseSession: vi.mocked(pauseSession),
  resumeSession: vi.mocked(resumeSession),
  startSession: vi.mocked(startSession),
  stopSession: vi.mocked(stopSession),
  cancelSession: vi.mocked(cancelSession),
  deleteSession: vi.mocked(deleteSession),
  getDemos: vi.mocked(getDemos),
  getSwarmStatus: vi.mocked(getSwarmStatus),
  updateSession: vi.mocked(updateSession),
  getSessionProblemRuns: vi.mocked(getSessionProblemRuns),
  getSessionMemory: vi.mocked(getSessionMemory),
}

beforeEach(() => {
  vi.clearAllMocks()
  window.location.hash = ''
  useRunStore.setState({
    formInputs: { initial: '', modified: '', target: '', answer: '', seed: '' },
    parameterOverrides: {},
  })
  m.listSessions.mockResolvedValue(LIST)
  m.getSession.mockResolvedValue(session())
  m.listSessionProblems.mockResolvedValue({ total: 1, problems: [row()] })
  m.getSessionProblem.mockResolvedValue(detail())
  m.getDemos.mockResolvedValue([])
  m.getSwarmStatus.mockResolvedValue({ available: true, reason: null, started: true, workers: 17, default_backend: 'off', backends: ['numpy', 'off'], limits: {} })
  m.getSessionProblemRuns.mockResolvedValue({ runs: [] })
  m.getSessionMemory.mockResolvedValue({ answers: [], snags: [] })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

const user = {
  type: (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } }),
}

describe('SessionPanel: the list', () => {
  it('shows each session with its state, problems, runs and the executor line', async () => {
    render(<SessionPanel />)
    expect(await screen.findByText('Pilot')).toBeInTheDocument()
    expect(screen.getByText('Done one')).toBeInTheDocument()
    expect(screen.getByTestId('executor-line')).toHaveTextContent(
      'Run mode: multi-core (swarm, 17 workers; 34 runs in flight, 12,000 queued)',
    )
    const items = screen.getAllByTestId('session-item')
    expect(items).toHaveLength(2)
    expect(within(items[0]).getByText('running')).toBeInTheDocument()
    expect(items[0]).toHaveTextContent('2/4 problems')
    expect(items[0]).toHaveTextContent('250/400 runs')
    expect(within(items[1]).getByText('idle')).toBeInTheDocument()
    expect(within(items[0]).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '250')
  })

  it('shows whether each session is live or stored, and its saved_through version', async () => {
    m.listSessions.mockResolvedValue({
      ...LIST,
      sessions: [
        session({ saved_through: { stopped_at: null, configuration_revision: 4, episode_version: 0 } }),
        session({ id: 2, name: 'Done one', state: 'stopped', source: 'stored', unsaved: null }),
      ],
    })
    render(<SessionPanel />)
    const saved = await screen.findAllByTestId('session-item-saved')
    expect(saved[0]).toHaveTextContent('Live (in memory) · 502 unsaved · saved through configuration version 4')
    expect(saved[1]).toHaveTextContent('Stored (as of last stop)')
  })

  it('says the executor is serial when the parallel plugin is absent', async () => {
    m.listSessions.mockResolvedValue({ ...LIST, executor: { kind: 'serial', workers: 1, in_flight: 0, queued_runs: 0 } })
    render(<SessionPanel />)
    expect(await screen.findByTestId('executor-line')).toHaveTextContent(
      'Run mode: single-threaded (serial; parallel plugin not installed)',
    )
  })

  it('shows an empty state when there are no sessions', async () => {
    m.listSessions.mockResolvedValue({ ...LIST, sessions: [] })
    render(<SessionPanel />)
    expect(await screen.findByText(/No sessions yet/)).toBeInTheDocument()
  })

  it('shows the server text when sessions are unavailable (503)', async () => {
    m.listSessions.mockRejectedValue(apiError(503, 'Training Mode Sessions need the database'))
    render(<SessionPanel />)
    expect(await screen.findByTestId('sessions-unavailable')).toHaveTextContent('Training Mode Sessions need the database')
    expect(screen.getByRole('button', { name: 'New session' })).toBeDisabled()
  })

  it('shows the server text on a 404 too', async () => {
    m.listSessions.mockRejectedValue(apiError(404, 'Training Mode Sessions need the database'))
    render(<SessionPanel />)
    expect(await screen.findByTestId('sessions-unavailable')).toHaveTextContent('Training Mode Sessions need the database')
  })

  it('shows other failures as an alert', async () => {
    m.listSessions.mockRejectedValue(new TypeError('failed to fetch'))
    render(<SessionPanel />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/server is unreachable/)
  })

  it('selecting a session loads it and writes #/training-mode/<id>', async () => {
    render(<SessionPanel />)
    fireEvent.click((await screen.findAllByTestId('session-item'))[0])
    expect(await screen.findByTestId('session-detail')).toBeInTheDocument()
    expect(window.location.hash).toBe('#/training-mode/1')
    expect(m.getSession).toHaveBeenCalledWith(1)
  })
})

describe('SessionPanel: creating a session', () => {
  async function openForm() {
    render(<SessionPanel />)
    await screen.findByText('Pilot')
    fireEvent.click(screen.getByRole('button', { name: 'New session' }))
    const form = await screen.findByTestId('new-session-form')
    user.type(screen.getByLabelText('Name (required)'), 'T')
    return form
  }

  it('previews what was parsed and creates the session with the form values', async () => {
    m.createSession.mockResolvedValue({ session: session({ id: 7, name: 'Fresh' }), added: 2, problem_ids: [1, 2], persisted: true })
    m.getSession.mockResolvedValue(session({ id: 7, name: 'Fresh' }))
    await openForm()

    user.type(screen.getByLabelText('Name (required)'), 'Fresh')
    user.type(screen.getByLabelText('Seeds per problem'), '50')
    user.type(
      screen.getByLabelText('Problems'),
      'abc → abd; xyz → ?\nabc abd xyz\nabc -> abd; ijk -> ?\nabc abd',
    )
    expect(screen.getByTestId('preview-summary')).toHaveTextContent(
      '2 problems parsed, 1 lines rejected, 1 duplicates · 100 runs in total',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Show rejected lines' }))
    expect(screen.getByTestId('rejected-list')).toHaveTextContent(/line 4.*3 or 4 fields/)

    fireEvent.click(screen.getByRole('button', { name: 'Create session' }))
    await waitFor(() => expect(m.createSession).toHaveBeenCalledTimes(1))
    expect(m.createSession).toHaveBeenCalledWith({
      name: 'Fresh',
      settings: { seeds_per_problem: 50, seed_start: 1, max_codelets: 20000 },
      policy: POLICY,
      problems: [
        { initial: 'abc', modified: 'abd', target: 'xyz', answer: null },
        { initial: 'abc', modified: 'abd', target: 'ijk', answer: null },
      ],
    })
    expect(m.addSessionProblems).not.toHaveBeenCalled()
    expect(await screen.findByRole('heading', { name: 'Fresh' })).toBeInTheDocument()
    expect(window.location.hash).toBe('#/training-mode/7')
  })

  it('takes a session name of any length: the input has no maxLength and the name is sent whole', async () => {
    const long = '名'.repeat(500) + ' 👨‍👩‍👧 ' + 'x'.repeat(300)
    m.createSession.mockResolvedValue({ session: session({ id: 8, name: long }), added: 1, problem_ids: [1], persisted: true })
    m.getSession.mockResolvedValue(session({ id: 8, name: long }))
    await openForm()
    const input = screen.getByLabelText('Name (required)')
    expect(input).not.toHaveAttribute('maxlength')
    user.type(input, long)
    expect(input).toHaveValue(long)
    user.type(screen.getByLabelText('Problems'), 'abc abd xyz')
    fireEvent.click(screen.getByRole('button', { name: 'Create session' }))
    await waitFor(() => expect(m.createSession).toHaveBeenCalledTimes(1))
    expect(m.createSession.mock.calls[0][0].name).toBe(long)
  })

  it('sends the dashboard overrides only when the box is ticked', async () => {
    useRunStore.setState({ parameterOverrides: { some_param: 3 } })
    m.createSession.mockResolvedValue({ session: session({ id: 7 }), added: 1, problem_ids: [1], persisted: true })
    await openForm()
    user.type(screen.getByLabelText('Problems'), 'abc abd xyz')
    fireEvent.click(screen.getByLabelText(/Use the dashboard's parameter overrides/))
    fireEvent.click(screen.getByRole('button', { name: 'Create session' }))
    await waitFor(() => expect(m.createSession).toHaveBeenCalled())
    expect(m.createSession.mock.calls[0][0].settings?.parameters).toEqual({ some_param: 3 })
  })

  it('splits problems into requests of at most the server limit', async () => {
    m.listSessions.mockResolvedValue({
      ...LIST,
      limits: { ...LIST.limits, max_problems_per_request: 2 },
    })
    m.createSession.mockResolvedValue({ session: session({ id: 7 }), added: 2, problem_ids: [1, 2], persisted: true })
    m.addSessionProblems.mockResolvedValue({ session: session({ id: 7 }), added: 2, problem_ids: [3, 4], persisted: true })
    await openForm()
    user.type(
      screen.getByLabelText('Problems'),
      ['aa bb cc', 'dd ee ff', 'gg hh ii', 'jj kk ll', 'mm nn oo'].join('\n'),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Create session' }))
    await waitFor(() => expect(m.addSessionProblems).toHaveBeenCalledTimes(2))
    expect(m.createSession.mock.calls[0][0].problems).toHaveLength(2)
    expect(m.addSessionProblems.mock.calls.map((c) => [c[0], c[1].length])).toEqual([
      [7, 2],
      [7, 1],
    ])
  })

  it('selects the session and says so when a later request fails', async () => {
    m.listSessions.mockResolvedValue({ ...LIST, limits: { ...LIST.limits, max_problems_per_request: 1 } })
    m.createSession.mockResolvedValue({ session: session({ id: 7 }), added: 1, problem_ids: [1], persisted: true })
    m.addSessionProblems.mockRejectedValue(apiError(422, 'too many'))
    m.getSession.mockResolvedValue(session({ id: 7 }))
    await openForm()
    user.type(screen.getByLabelText('Problems'), 'aa bb cc\ndd ee ff')
    fireEvent.click(screen.getByRole('button', { name: 'Create session' }))
    expect(await screen.findByRole('status')).toHaveTextContent(/1 of 2 problems were added/)
    expect(window.location.hash).toBe('#/training-mode/7')
  })

  it('shows the server error and stays on the form when creation fails', async () => {
    m.createSession.mockRejectedValue(apiError(400, 'unknown parameter'))
    await openForm()
    fireEvent.click(screen.getByRole('button', { name: 'Create session' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('unknown parameter')
    expect(screen.getByTestId('new-session-form')).toBeInTheDocument()
  })

  it('refuses a seed count above the server limit', async () => {
    await openForm()
    user.type(screen.getByLabelText('Seeds per problem'), '999999')
    expect(screen.getByRole('button', { name: 'Create session' })).toBeDisabled()
  })

  it('adds the demo problems to the text', async () => {
    m.getDemos.mockResolvedValue([
      { id: 1, name: 'a', section: 's', initial: 'abc', modified: 'abd', target: 'ijk', answer: null, seed: 1, mode: 'x', description: '' },
      { id: 2, name: 'b', section: 's', initial: 'abc', modified: 'abd', target: 'xyz', answer: 'wyz', seed: 1, mode: 'x', description: '' },
    ])
    await openForm()
    fireEvent.click(screen.getByRole('button', { name: 'Add the demo problems' }))
    await waitFor(() =>
      expect(screen.getByLabelText('Problems')).toHaveValue('abc → abd; ijk → ?\nabc → abd; xyz → wyz'),
    )
    expect(screen.getByTestId('preview-summary')).toHaveTextContent('2 problems parsed')
  })

  it('reads an uploaded file into the text', async () => {
    await openForm()
    const file = new File(['abc,abd,xyz\n'], 'p.csv', { type: 'text/csv' })
    fireEvent.change(screen.getByTestId('session-problems-file'), { target: { files: [file] } })
    await waitFor(() => expect(screen.getByLabelText('Problems')).toHaveValue('abc,abd,xyz\n'))
    expect(screen.getByTestId('preview-summary')).toHaveTextContent('1 problems parsed')
  })
})

describe('SessionPanel: the session detail', () => {
  async function open(b: Partial<SessionSummary> = {}) {
    m.getSession.mockResolvedValue(session(b))
    render(<SessionPanel initialSessionId={1} />)
    return screen.findByTestId('session-detail')
  }

  it('shows the header figures', async () => {
    await open()
    expect(screen.getByRole('heading', { name: 'Pilot' })).toBeInTheDocument()
    expect(screen.getByTestId('session-problems-line')).toHaveTextContent(
      '4 total · 2 finished · 1 running · 1 queued · 0 cancelled',
    )
    const runs = screen.getByTestId('session-runs-line')
    expect(runs).toHaveTextContent('250 / 400')
    expect(runs).toHaveTextContent('42.5 runs/s')
    expect(runs).toHaveTextContent('ETA 2 min 05 s')
    expect(runs).toHaveTextContent('1,234,567 codelets')
    expect(screen.getByText(/backend off · 100 seeds per problem from 1 · max codelets per run 20,000/)).toBeInTheDocument()
  })

  it('links the exports', async () => {
    await open()
    const link = screen.getByRole('link', { name: 'problems (CSV)' })
    expect(link).toHaveAttribute('href', sessionExportUrl(1, 'problems', 'csv'))
    expect(link.getAttribute('href')).toBe('/api/training-mode/sessions/1/export?what=problems&format=csv')
    expect(screen.getByRole('link', { name: 'Export runs as JSON' })).toHaveAttribute(
      'href',
      '/api/training-mode/sessions/1/export?what=runs&format=json',
    )
  })

  it('pauses a running session and resumes a paused one', async () => {
    m.pauseSession.mockResolvedValue(session({ state: 'paused' }))
    m.resumeSession.mockResolvedValue(session())
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    await waitFor(() => expect(m.pauseSession).toHaveBeenCalledWith(1))
    const resume = await screen.findByRole('button', { name: 'Resume' })
    fireEvent.click(resume)
    await waitFor(() => expect(m.resumeSession).toHaveBeenCalledWith(1))
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()
  })

  it('starts a stopped session and stops a live one, with no Close control', async () => {
    m.startSession.mockResolvedValue(session())
    m.stopSession.mockResolvedValue(
      session({ state: 'stopped', stopped_at: '2026-10-30T11:00:00', stopped_from: 'running', stop_reason: 'user' }),
    )
    await open({ state: 'stopped' })
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stop' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await waitFor(() => expect(m.startSession).toHaveBeenCalledWith(1))
    const stop = await screen.findByRole('button', { name: 'Stop' })
    await waitFor(() => expect(stop).toBeEnabled())
    fireEvent.click(stop)
    await waitFor(() => expect(m.stopSession).toHaveBeenCalledWith(1))
    expect(await screen.findByTestId('stopped-line')).toHaveTextContent('from running (user)')
    expect(await screen.findByRole('button', { name: 'Start' })).toBeInTheDocument()
  })

  it('shows the server complaint when a control fails', async () => {
    m.pauseSession.mockRejectedValue(apiError(409, 'session 1 is stopped; start it before you pause it'))
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('start it before you pause it')
  })

  it('cancels only after confirmation, and cancel leaves the state alone', async () => {
    m.cancelSession.mockResolvedValue(session())
    const confirm = vi.spyOn(window, 'confirm')
    await open()
    confirm.mockReturnValueOnce(false)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(m.cancelSession).not.toHaveBeenCalled()
    confirm.mockReturnValueOnce(true)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(m.cancelSession).toHaveBeenCalledWith(1))
  })

  it('deletes only after the session name is typed, and returns to the list', async () => {
    m.deleteSession.mockResolvedValue(undefined)
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    const confirm = screen.getByRole('button', { name: 'Delete this Training Mode Session' })
    expect(confirm).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Type the name/), { target: { value: 'pilot' } })
    expect(confirm).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Type the name/), { target: { value: 'Pilot' } })
    expect(confirm).toBeEnabled()
    expect(m.deleteSession).not.toHaveBeenCalled()
    fireEvent.click(confirm)
    await waitFor(() => expect(m.deleteSession).toHaveBeenCalledWith(1))
    await waitFor(() => expect(screen.queryByTestId('session-detail')).not.toBeInTheDocument())
    expect(window.location.hash).toBe('#/training-mode')
  })

  it('Keep it closes the delete confirmation without deleting', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    fireEvent.click(screen.getByRole('button', { name: 'Keep it' }))
    expect(screen.queryByTestId('delete-confirmation')).not.toBeInTheDocument()
    expect(m.deleteSession).not.toHaveBeenCalled()
  })

  it('shows why a session is stalled', async () => {
    await open({ activity: 'stalled', stalled_reason: 'the engine configuration changed' })
    expect(screen.getAllByText('stalled').length).toBeGreaterThan(0)
    expect(screen.getByText(/Stalled: the engine configuration changed/)).toBeInTheDocument()
  })
})

describe('SessionPanel: adding problems', () => {
  it('adds the parsed problems to an open session', async () => {
    m.addSessionProblems.mockResolvedValue({ session: session(), added: 2, problem_ids: [5, 6], persisted: false })
    m.getSession.mockResolvedValue(session())
    render(<SessionPanel initialSessionId={1} />)
    const box = await screen.findByTestId('add-problems')
    user.type(within(box).getByLabelText('Problems'), 'abc → abd; ijk → ?\nabc abd xyz wyz')
    expect(within(box).getByTestId('preview-summary')).toHaveTextContent('2 problems parsed')
    fireEvent.click(within(box).getByRole('button', { name: 'Add 2 problems' }))
    await waitFor(() => expect(m.addSessionProblems).toHaveBeenCalledTimes(1))
    expect(m.addSessionProblems).toHaveBeenCalledWith(1, [
      { initial: 'abc', modified: 'abd', target: 'ijk', answer: null },
      { initial: 'abc', modified: 'abd', target: 'xyz', answer: 'wyz' },
    ])
    // A live session holds them in memory until it is Stopped, and says so.
    expect(
      await within(box).findByText('Added 2 problems. They are held in memory until the session is Stopped.'),
    ).toBeInTheDocument()
  })

  it('says nothing about memory when the session is Stopped and the problems are stored at once', async () => {
    m.addSessionProblems.mockResolvedValue({
      session: session({ state: 'stopped', source: 'stored', persisted: true, unsaved: null }),
      added: 1,
      problem_ids: [3],
      persisted: true,
    })
    m.getSession.mockResolvedValue(session({ state: 'stopped', source: 'stored', persisted: true, unsaved: null }))
    render(<SessionPanel initialSessionId={1} />)
    const box = await screen.findByTestId('add-problems')
    user.type(within(box).getByLabelText('Problems'), 'abc abd xyz')
    fireEvent.click(within(box).getByRole('button', { name: 'Add 1 problems' }))
    expect(await within(box).findByText('Added 1 problems.')).toBeInTheDocument()
  })

  it('is enabled in every state: stopped, running and paused', async () => {
    for (const over of [{ state: 'stopped' as const }, { state: 'paused' as const }, {}]) {
      m.getSession.mockResolvedValue(session(over))
      const { unmount } = render(<SessionPanel initialSessionId={1} />)
      const box = await screen.findByTestId('add-problems')
      expect(within(box).getByLabelText('Problems')).toBeEnabled()
      if (over.state === 'stopped') expect(within(box).getByText(/stored now and run when it is started/)).toBeInTheDocument()
      else expect(within(box).queryByText(/stored now and run when it is started/)).not.toBeInTheDocument()
      unmount()
    }
  })

  it('shows the server complaint, such as a 422 from the server', async () => {
    m.addSessionProblems.mockRejectedValue(apiError(422, 'seeds must be 1..100000'))
    render(<SessionPanel initialSessionId={1} />)
    const box = await screen.findByTestId('add-problems')
    user.type(within(box).getByLabelText('Problems'), 'abc abd xyz')
    fireEvent.click(within(box).getByRole('button', { name: 'Add 1 problems' }))
    expect(await within(box).findByRole('alert')).toHaveTextContent('seeds must be 1..100000')
  })
})

describe('SessionPanel: the problems table', () => {
  async function open(b: Partial<SessionSummary> = {}) {
    m.getSession.mockResolvedValue(session(b))
    render(<SessionPanel initialSessionId={1} />)
    return screen.findByTestId('problems-table')
  }

  it('shows a row with its answers and percentages', async () => {
    await open()
    const r = await screen.findByTestId('problem-row')
    expect(r).toHaveTextContent('abc → abd; xyz')
    expect(r).toHaveTextContent('100 / 100')
    expect(r).toHaveTextContent('xyd 40.0%')
    expect(r).toHaveTextContent('wyz 30.0%')
    expect(r).toHaveTextContent('5.0%')
    expect(r).toHaveTextContent('1,234')
  })

  it('shows a justification problem with its answer', async () => {
    m.listSessionProblems.mockResolvedValue({ total: 1, problems: [row({ answer: 'wyz' })] })
    await open()
    expect(await screen.findByTestId('problem-row')).toHaveTextContent('abc → abd; xyz → wyz')
  })

  it('shows "Add problems to start" for an empty session', async () => {
    await open({ problems: { total: 0, queued: 0, running: 0, finished: 0, cancelled: 0 }, activity: 'idle' })
    expect(screen.getByText('Add problems to start.')).toBeInTheDocument()
  })

  it('has status tabs with counts that filter the query', async () => {
    await open()
    expect(screen.getByRole('tab', { name: 'All (4)' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Queued (1)' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Finished (2)' })).toBeInTheDocument()
    await screen.findByTestId('problem-row')
    fireEvent.click(screen.getByRole('tab', { name: 'Finished (2)' }))
    await waitFor(() =>
      expect(m.listSessionProblems).toHaveBeenLastCalledWith(
        1,
        expect.objectContaining({ status: 'finished', offset: 0 }),
      ),
    )
    expect(screen.getByRole('tab', { name: 'Finished (2)' })).toHaveAttribute('aria-selected', 'true')
  })

  it('searches and sorts through the server', async () => {
    await open()
    await screen.findByTestId('problem-row')
    fireEvent.change(screen.getByLabelText('Search problems'), { target: { value: 'xyz' } })
    await waitFor(() =>
      expect(m.listSessionProblems).toHaveBeenLastCalledWith(1, expect.objectContaining({ q: 'xyz' })),
    )
    fireEvent.click(screen.getByRole('button', { name: /^Distinct/ }))
    await waitFor(() =>
      expect(m.listSessionProblems).toHaveBeenLastCalledWith(
        1,
        expect.objectContaining({ sort: 'distinct', order: 'desc' }),
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: /^Distinct/ }))
    await waitFor(() =>
      expect(m.listSessionProblems).toHaveBeenLastCalledWith(1, expect.objectContaining({ order: 'asc' })),
    )
  })

  it('pages with the server total', async () => {
    m.listSessionProblems.mockResolvedValue({ total: 120, problems: Array.from({ length: 50 }, (_, i) => row({ id: i + 1 })) })
    await open()
    await screen.findAllByTestId('problem-row')
    fireEvent.click(screen.getByRole('button', { name: /Next page of problems/ }))
    await waitFor(() =>
      expect(m.listSessionProblems).toHaveBeenLastCalledWith(1, expect.objectContaining({ offset: 50, limit: 50 })),
    )
  })

  it('expands a row into its distribution', async () => {
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    const d = await screen.findByTestId('problem-detail')
    await within(d).findAllByTestId('distribution-row')
    expect(m.getSessionProblem).toHaveBeenCalledWith(1, 10)
    const rows = within(d).getAllByTestId('distribution-row')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent('xyd')
    expect(rows[0]).toHaveTextContent('40.0')
    expect(rows[2]).toHaveTextContent('no answer')
    fireEvent.click(screen.getByTestId('problem-row'))
    expect(screen.queryByTestId('problem-detail')).not.toBeInTheDocument()
  })

  it('shows the first error of a problem', async () => {
    m.getSessionProblem.mockResolvedValue(detail({ errors: 1, first_error: 'ValueError: boom' }))
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    expect(await screen.findByText(/First error: ValueError: boom/)).toBeInTheDocument()
  })

  it('opens the problem in the dashboard', async () => {
    m.listSessionProblems.mockResolvedValue({ total: 1, problems: [row({ answer: 'wyz' })] })
    m.getSessionProblem.mockResolvedValue(detail({ answer: 'wyz' }))
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    fireEvent.click(await screen.findByRole('button', { name: 'Open in dashboard' }))
    const f = useRunStore.getState().formInputs
    expect([f.initial, f.modified, f.target, f.answer]).toEqual(['abc', 'abd', 'xyz', 'wyz'])
    expect(window.location.hash === '' || window.location.hash === '#').toBe(true)
  })

  it('cancels a running problem, and offers it only for queued or running ones', async () => {
    m.listSessionProblems.mockResolvedValue({ total: 1, problems: [row({ status: 'running', runs_done: 10 })] })
    m.getSessionProblem.mockResolvedValue(detail({ status: 'running', runs_done: 10 }))
    m.cancelSessionProblem.mockResolvedValue(row({ status: 'cancelled' }))
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel problem' }))
    await waitFor(() => expect(m.cancelSessionProblem).toHaveBeenCalledWith(1, 10))
  })

  it('does not offer to cancel a finished problem', async () => {
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    await screen.findByTestId('problem-detail')
    expect(screen.queryByRole('button', { name: 'Cancel problem' })).not.toBeInTheDocument()
  })

  it('shows an error when the problems cannot be loaded', async () => {
    m.listSessionProblems.mockRejectedValue(apiError(500, 'database is locked'))
    await open()
    expect(await screen.findByText(/database is locked/)).toBeInTheDocument()
  })
})

describe('SessionPanel: polling', () => {
  it('polls the list every 3 s, a running session every 1.5 s, and stops on unmount', async () => {
    vi.useFakeTimers()
    const { unmount } = render(<SessionPanel initialSessionId={1} />)
    const flush = async (ms: number) => {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ms)
      })
    }
    await flush(0)
    expect(m.listSessions).toHaveBeenCalledTimes(1)
    expect(m.getSession).toHaveBeenCalledTimes(1)
    expect(m.listSessionProblems).toHaveBeenCalledTimes(1)

    await flush(3000)
    expect(m.listSessions).toHaveBeenCalledTimes(2)
    expect(m.getSession).toHaveBeenCalledTimes(3) // t=0, 1.5, 3
    expect(m.listSessionProblems).toHaveBeenCalledTimes(3)

    unmount()
    const calls = [m.listSessions, m.getSession, m.listSessionProblems].map((f) => f.mock.calls.length)
    await flush(20000)
    expect([m.listSessions, m.getSession, m.listSessionProblems].map((f) => f.mock.calls.length)).toEqual(calls)
  })

  it('slows to 5 s when the session is not running', async () => {
    vi.useFakeTimers()
    m.getSession.mockResolvedValue(session({ activity: 'idle' }))
    render(<SessionPanel initialSessionId={1} />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    const before = m.getSession.mock.calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4900)
    })
    expect(m.getSession.mock.calls.length).toBe(before)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200)
    })
    expect(m.getSession.mock.calls.length).toBe(before + 1)
  })

  it('refetches an expanded running problem no more often than every 3 s', async () => {
    vi.useFakeTimers()
    m.listSessionProblems.mockResolvedValue({ total: 1, problems: [row({ status: 'running', runs_done: 5 })] })
    m.getSessionProblem.mockResolvedValue(detail({ status: 'running', runs_done: 5 }))
    render(<SessionPanel initialSessionId={1} />)
    const flush = async (ms: number) => {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ms)
      })
    }
    await flush(0)
    fireEvent.click(screen.getByTestId('problem-row'))
    await flush(0)
    expect(m.getSessionProblem).toHaveBeenCalledTimes(1)
    await flush(2900)
    expect(m.getSessionProblem).toHaveBeenCalledTimes(1)
    await flush(200)
    expect(m.getSessionProblem).toHaveBeenCalledTimes(2)
  })
})


describe('SessionPanel: v2 features', () => {
  async function open(b: Partial<SessionSummary> = {}) {
    m.getSession.mockResolvedValue(session(b))
    render(<SessionPanel initialSessionId={1} />)
    return screen.findByTestId('session-detail')
  }

  it('shows the settings read-only, the memory counts and the extra run counts', async () => {
    await open()
    expect(screen.getByTestId('session-settings-line')).toHaveTextContent(
      'backend off · 100 seeds per problem from 1 · max codelets per run 20,000',
    )
    expect(screen.getByTestId('session-memory-line')).toHaveTextContent('12 answers, 3 snags, version 9')
    expect(screen.getByTestId('session-memory-line')).toHaveTextContent('never cleared')
    const runs = screen.getByTestId('session-runs-line')
    expect(runs).toHaveTextContent('2 errors')
    expect(runs).toHaveTextContent('5 gave up at max codelets')
    expect(runs).toHaveTextContent('1 retries')
  })

  it('shows last_event prominently when set, and not otherwise', async () => {
    await open({ last_event: 'paused: 5 errors reached max_errors_total' })
    expect(screen.getByTestId('last-event')).toHaveTextContent('paused: 5 errors reached max_errors_total')
  })

  it('has no last-event box when there is none', async () => {
    await open()
    expect(screen.queryByTestId('last-event')).not.toBeInTheDocument()
  })

  it('renames inline to a name of any length (no maxLength on the input)', async () => {
    const long = 'n'.repeat(400) + ' 漢字'
    m.updateSession.mockResolvedValue(session({ name: long }))
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
    const input = screen.getByLabelText('New name')
    expect(input).not.toHaveAttribute('maxlength')
    user.type(input, long)
    fireEvent.click(screen.getByRole('button', { name: 'Save name' }))
    await waitFor(() => expect(m.updateSession).toHaveBeenCalledWith(1, { name: long }))
  })

  it('renames inline with PATCH', async () => {
    m.updateSession.mockResolvedValue(session({ name: 'Renamed' }))
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
    user.type(screen.getByLabelText('New name'), 'Renamed')
    fireEvent.click(screen.getByRole('button', { name: 'Save name' }))
    await waitFor(() => expect(m.updateSession).toHaveBeenCalledWith(1, { name: 'Renamed' }))
    expect(await screen.findByRole('heading', { name: 'Renamed' })).toBeInTheDocument()
  })

  it('edits and saves the policy with PATCH', async () => {
    m.updateSession.mockResolvedValue(session({ policy: { ...POLICY, on_run_error: 'pause', max_errors_total: 5 } }))
    await open()
    const editor = screen.getByTestId('policy-editor')
    expect(within(editor).getByRole('button', { name: 'Save policy' })).toBeDisabled()
    fireEvent.change(within(editor).getByLabelText('When a run raises an error'), { target: { value: 'pause' } })
    fireEvent.change(within(editor).getByLabelText('Max errors total'), { target: { value: '5' } })
    fireEvent.click(within(editor).getByRole('button', { name: 'Save policy' }))
    await waitFor(() =>
      expect(m.updateSession).toHaveBeenCalledWith(1, {
        policy: { ...POLICY, on_run_error: 'pause', max_errors_total: 5 },
      }),
    )
    expect(await within(editor).findByText('Policy saved.')).toBeInTheDocument()
  })

  it('shows a policy error from the server', async () => {
    m.updateSession.mockRejectedValue(apiError(400, 'bad policy value'))
    await open()
    const editor = screen.getByTestId('policy-editor')
    fireEvent.change(within(editor).getByLabelText('When a run raises an error'), { target: { value: 'pause' } })
    fireEvent.click(within(editor).getByRole('button', { name: 'Save policy' }))
    expect(await within(editor).findByRole('alert')).toHaveTextContent('bad policy value')
  })

  it('lists the episode memory in a Memory tab', async () => {
    m.getSessionMemory.mockResolvedValue({
      answers: [
        {
          answer_id: 1,
          problem: ['abc', 'abd', 'xyz', 'xyd'],
          quality: 80,
          temperature: 30,
          themes: {},
          top_rule_description: 'replace the last letter by its successor',
          bottom_rule_description: 'replace the last letter by d',
        },
      ],
      snags: [
        {
          snag_id: 4,
          problem: ['abc', 'abd', 'xyz'],
          codelet_count: 900,
          temperature: 100,
          description: 'the rule found',
          explanation: 'z has no successor',
        },
      ],
    })
    await open()
    fireEvent.click(screen.getByRole('tab', { name: 'Memory' }))
    expect(await screen.findAllByTestId('memory-answer')).toHaveLength(1)
    expect(screen.getByTestId('memory-snag')).toHaveTextContent('z has no successor')
    expect(m.getSessionMemory).toHaveBeenCalledWith(1)
    expect(screen.getByTestId('memory-tab')).toHaveTextContent('Version 9')
  })

  it('always has a Memory tab, even for a stopped session', async () => {
    await open({ state: 'stopped', memory: { answers: 0, snags: 0 }, memory_version: 0 })
    expect(screen.getByRole('tab', { name: 'Memory' })).toBeInTheDocument()
    expect(screen.getByTestId('session-memory-line')).toHaveTextContent('0 answers, 0 snags, version 0')
    expect(screen.getByTestId('session-settings-line')).not.toHaveTextContent(/independent|shared/)
  })

  it('labels the non-answer outcomes in plain words', async () => {
    m.listSessionProblems.mockResolvedValue({
      total: 1,
      problems: [
        row({
          capped: 7,
          top: [
            { answer: '*CAP*', count: 7, fraction: 0.7, mean_quality: null },
            { answer: '*ERROR*', count: 2, fraction: 0.2, mean_quality: null },
          ],
        }),
      ],
    })
    m.getSessionProblem.mockResolvedValue(
      detail({
        distribution: [
          { answer: '*CAP*', count: 7, fraction: 0.7, mean_quality: null },
          { answer: '*ERROR*', count: 2, fraction: 0.2, mean_quality: null },
          { answer: '*NONE*', count: 1, fraction: 0.1, mean_quality: null },
        ],
      }),
    )
    await open()
    const r = await screen.findByTestId('problem-row')
    expect(r).toHaveTextContent('gave up at max codelets 70.0%')
    expect(r).toHaveTextContent('error 20.0%')
    fireEvent.click(r)
    const d = await screen.findByTestId('problem-detail')
    const rows = await within(d).findAllByTestId('distribution-row')
    expect(rows.map((x) => x.textContent)).toEqual([
      expect.stringContaining('gave up at max codelets'),
      expect.stringContaining('error'),
      expect.stringContaining('no answer'),
    ])
  })

  it('shows a Runs sub-table in the expanded row', async () => {
    m.getSessionProblemRuns.mockResolvedValue({
      runs: [
        {
          seq: 3,
          memory_version: 2,
          seed: 1,
          status: 'answer_found',
          key: 'xyd',
          answer: 'xyd',
          answers: ['xyd'],
          codelets: 1500,
          seconds: 0.4,
          temperature: 20,
          answer_quality: 77.5,
          error: null,
          config_hash: 'h',
          attempts: 1,
          memory_added: { answers: 1, snags: 0 },
        },
        {
          seq: 4,
          memory_version: 3,
          seed: 2,
          status: 'error',
          key: '*ERROR*',
          answer: '',
          answers: [],
          codelets: 0,
          seconds: 0.1,
          temperature: 0,
          answer_quality: null,
          error: 'ValueError: boom',
          config_hash: 'h',
          attempts: 2,
          memory_added: { answers: 0, snags: 0 },
        },
      ],
    })
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    const table = await screen.findByTestId('runs-table')
    expect(m.getSessionProblemRuns).toHaveBeenCalledWith(1, 10)
    const rows = await within(table).findAllByTestId('run-row')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('xyd')
    expect(rows[0]).toHaveTextContent('1,500')
    expect(rows[0]).toHaveTextContent('77.5')
    expect(rows[1]).toHaveTextContent('error')
    expect(rows[1]).toHaveTextContent('ValueError: boom')
    expect(rows[1]).toHaveTextContent('2') // attempts
    expect(within(table).getByRole('columnheader', { name: 'Memory version' })).toBeInTheDocument()
  })

  it('pages a long runs list', async () => {
    const mk = (seed: number) => ({
      seq: seed, memory_version: seed, seed, status: 'answer_found', key: 'a', answer: 'a', answers: ['a'],
      codelets: 10, seconds: 0.1, temperature: 1, answer_quality: 1, error: null, config_hash: 'h', attempts: 1, memory_added: { answers: 0, snags: 0 },
    })
    m.getSessionProblemRuns.mockResolvedValue({ runs: Array.from({ length: 60 }, (_, i) => mk(i + 1)) })
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    const table = await screen.findByTestId('runs-table')
    expect(await within(table).findAllByTestId('run-row')).toHaveLength(25)
    fireEvent.click(within(table).getByRole('button', { name: /Next page of runs/ }))
    expect(within(table).getAllByTestId('run-row')[0]).toHaveTextContent('26')
  })
})

describe('SessionPanel: the new-session form (v2)', () => {
  async function openForm() {
    render(<SessionPanel />)
    await screen.findByText('Pilot')
    fireEvent.click(screen.getByRole('button', { name: 'New session' }))
    await screen.findByTestId('new-session-form')
  }

  it('needs a name', async () => {
    await openForm()
    expect(screen.getByRole('button', { name: 'Create session' })).toBeDisabled()
    user.type(screen.getByLabelText('Name (required)'), 'x')
    expect(screen.getByRole('button', { name: 'Create session' })).toBeEnabled()
  })

  it('has no memory control: every Training Mode Session has an Episodic Memory', async () => {
    await openForm()
    expect(screen.queryByLabelText('Memory')).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Independent/ })).not.toBeInTheDocument()
    expect(screen.getByTestId('memory-help-line')).toHaveTextContent(/own Episodic Memory, never cleared/)
    expect(screen.getByTestId('memory-help-line')).toHaveTextContent(/A new Training Mode Session is stopped/)
  })

  it('takes the error policy defaults from the server', async () => {
    m.listSessions.mockResolvedValue({
      ...LIST,
      defaults: { ...LIST.defaults, policy: { ...POLICY, max_retries: 7, max_errors_total: 20 } },
    })
    await openForm()
    expect(screen.getByLabelText('Retries per run')).toHaveValue(7)
    expect(screen.getByLabelText('Max errors total')).toHaveValue(20)
    expect(screen.getByLabelText('Max errors per problem')).toHaveValue(null)
    expect((screen.getByLabelText('When a run raises an error') as HTMLSelectElement).value).toBe('record')
  })

  it('sends the max codelets, backend and policy, and no memory setting', async () => {
    m.createSession.mockResolvedValue({ session: session({ id: 8 }), added: 1, problem_ids: [1], persisted: true })
    await openForm()
    user.type(screen.getByLabelText('Name (required)'), 'Ep')
    user.type(screen.getByLabelText('Max codelets per run'), '5000')
    await screen.findByRole('option', { name: 'numpy' })
    fireEvent.change(screen.getByLabelText('Backend (advanced)'), { target: { value: 'numpy' } })
    fireEvent.change(screen.getByLabelText('When a run raises an error'), { target: { value: 'skip_problem' } })
    fireEvent.change(screen.getByLabelText('Max errors per problem'), { target: { value: '3' } })
    user.type(screen.getByLabelText('Problems'), 'abc abd xyz')
    fireEvent.click(screen.getByRole('button', { name: 'Create session' }))
    await waitFor(() => expect(m.createSession).toHaveBeenCalled())
    const req = m.createSession.mock.calls[0][0]
    expect(req.settings).toEqual({
      seeds_per_problem: 100,
      seed_start: 1,
      max_codelets: 5000,
      backend: 'numpy',
    })
    expect(req.policy).toEqual({
      ...POLICY,
      on_run_error: 'skip_problem',
      max_errors_per_problem: 3,
    })
  })

  it('refuses max codelets above the server limit', async () => {
    await openForm()
    user.type(screen.getByLabelText('Name (required)'), 'x')
    user.type(screen.getByLabelText('Max codelets per run'), '999999999')
    expect(screen.getByRole('button', { name: 'Create session' })).toBeDisabled()
  })

  it('keeps the policy in a collapsible section', async () => {
    await openForm()
    const section = screen.getByTestId('policy-section')
    expect(section.tagName).toBe('DETAILS')
    expect(within(section).getByText('When things go wrong')).toBeInTheDocument()
  })
})

describe('SessionPanel: the Stopped rule (live and stored, saved_through, unsaved, busy)', () => {
  async function open(b: Partial<SessionSummary> = {}) {
    m.getSession.mockResolvedValue(session(b))
    render(<SessionPanel initialSessionId={1} />)
    return screen.findByTestId('session-detail')
  }

  it('says a live session is held in memory, what the database holds and what is not yet saved', async () => {
    await open({
      saved_through: { stopped_at: '2026-10-30T09:00:00', configuration_revision: null, episode_version: 7 },
      unsaved: { runs: 250, merges: 250, problems: 3, outcomes: 2, edits: 1, configuration_batches: 0 },
    })
    const line = screen.getByTestId('session-saved-line')
    expect(line).toHaveTextContent('Live: held in memory, and written to the database only when it is Stopped')
    expect(line).toHaveTextContent('Episodic Memory version 7')
    expect(line).toHaveTextContent(
      'Not yet saved: 250 runs, 250 Episodic Memory merges, 3 added problems, 2 finished or cancelled problems, 1 edits.',
    )
  })

  it('says nothing is unsaved for a live session that has not changed since the Stop', async () => {
    await open({ unsaved: { runs: 0, merges: 0, problems: 0, outcomes: 0, edits: 0, configuration_batches: 0 } })
    expect(screen.getByTestId('session-saved-line')).toHaveTextContent('Not yet saved: nothing.')
  })

  it('says a Stopped session is what the database holds', async () => {
    await open({ state: 'stopped', source: 'stored', persisted: true, unsaved: null })
    expect(screen.getByTestId('session-saved-line')).toHaveTextContent('Stored: this is what the database holds.')
  })

  it.each(['starting', 'stopping'] as const)('freezes every control while %s, because the server answers busy', async (state) => {
    const detailBox = await open({ state })
    expect(within(detailBox).getByTestId('state-badge')).toHaveTextContent(state)
    expect(screen.getByRole('button', { name: state === 'starting' ? 'Starting…' : 'Stopping…' })).toBeDisabled()
    for (const name of ['Stop', 'Cancel', 'Delete']) expect(screen.getByRole('button', { name })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Pause' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Resume' })).not.toBeInTheDocument()
    const box = screen.getByTestId('add-problems')
    expect(within(box).getByTestId('add-problems-busy')).toHaveTextContent(`is ${state}`)
    user.type(within(box).getByLabelText('Problems'), 'abc abd xyz')
    expect(within(box).getByRole('button', { name: 'Add 1 problems' })).toBeDisabled()
  })

  it('shows the server busy refusal when a change is refused', async () => {
    m.pauseSession.mockRejectedValue(apiError(409, 'busy: session 1 is stopping; wait for it to finish before you pause it'))
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('busy: session 1 is stopping')
  })

  it('has no control for what a configuration change does (on_config_change is gone)', async () => {
    await open()
    expect(screen.queryByLabelText('When the engine configuration changes')).not.toBeInTheDocument()
  })

  it('says a live delete discards the unsaved state', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.getByTestId('delete-confirmation')).toHaveTextContent('discarded without being saved')
  })
})
