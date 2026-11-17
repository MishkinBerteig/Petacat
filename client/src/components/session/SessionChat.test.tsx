// ---------------------------------------------------------------------------
// Petacat -- Tests for the chat client of Training Mode Sessions (multi-turn runs)
// ---------------------------------------------------------------------------
//
// What these defend: a person can mark problems multi-turn when creating a session and when adding
// problems (and a multi-turn problem takes no answer); the problems table marks such a problem, the
// summary counts the runs waiting for the teacher, and the runs table shows each run's state, turns,
// end and the turn it waits for; opening a run opens its chat, which shows every turn's four
// positions (context, second string, input, response) with who supplied each, the strings exactly as
// given, and a details section; the input box appears only when the run waits and the session would
// take the input; Send and End call the API with the right body; a stale, busy or 422 refusal is
// shown, and a stale one refreshes the chat; the chat polls while the run is not ended and stops.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react'

import { SessionPanel } from './SessionPanel'
import { RunChat, asWritten } from './RunChat'
import { useRunStore } from '@/store/runStore'
import {
  ApiError,
  addSessionProblems,
  createSession,
  getSession,
  getSessionConversation,
  getSessionProblem,
  getSessionProblemRuns,
  getSwarmStatus,
  listSessionProblems,
  listSessions,
  supplySessionInput,
} from '@/api/client'
import type {
  SessionConversation,
  SessionErrorPolicy,
  SessionListResponse,
  SessionProblemDetail,
  SessionProblemRow,
  SessionRun,
  SessionSummary,
  SessionTurn,
} from '@/types'

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  listSessions: vi.fn(),
  createSession: vi.fn(),
  getSession: vi.fn(),
  addSessionProblems: vi.fn(),
  listSessionProblems: vi.fn(),
  getSessionProblem: vi.fn(),
  getSessionProblemRuns: vi.fn(),
  getSessionConversation: vi.fn(),
  supplySessionInput: vi.fn(),
  getDemos: vi.fn(),
  getSwarmStatus: vi.fn(),
}))

const m = {
  listSessions: vi.mocked(listSessions),
  createSession: vi.mocked(createSession),
  getSession: vi.mocked(getSession),
  addSessionProblems: vi.mocked(addSessionProblems),
  listSessionProblems: vi.mocked(listSessionProblems),
  getSessionProblem: vi.mocked(getSessionProblem),
  getSessionProblemRuns: vi.mocked(getSessionProblemRuns),
  getSessionConversation: vi.mocked(getSessionConversation),
  supplySessionInput: vi.mocked(supplySessionInput),
  getSwarmStatus: vi.mocked(getSwarmStatus),
}

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
    settings: { seeds_per_problem: 100, seed_start: 1, max_codelets: 20000, parameters: null, backend: 'off' },
    policy: POLICY,
    memory: { answers: 0, snags: 0 },
    memory_version: 0,
    last_event: null,
    config_hash: 'abcdef012345',
    created_at: '2026-10-30T10:00:00',
    updated_at: '2026-10-30T10:05:00',
    stopped_at: null,
    stopped_from: null,
    stop_reason: null,
    problems: { total: 2, queued: 0, running: 2, finished: 0, cancelled: 0 },
    runs: { total: 4, done: 1, errors: 0, capped: 0, retries: 0, waiting: 0 },
    codelets: 100,
    runs_per_second: null,
    eta_seconds: null,
    finished_cursor: 0,
    source: 'live',
    persisted: false,
    saved_through: { stopped_at: null, configuration_revision: null, episode_version: 0 },
    unsaved: null,
    ...over,
  } as SessionSummary
}

function row(over: Partial<SessionProblemRow> = {}): SessionProblemRow {
  return {
    id: 10,
    session_id: 1,
    initial: 'abc',
    modified: 'abd',
    target: 'ijk',
    answer: null,
    seeds: 3,
    seed_start: 1,
    tag: null,
    multi_turn: true,
    status: 'running',
    runs_done: 0,
    errors: 0,
    capped: 0,
    mean_codelets: null,
    top: [],
    none_fraction: null,
    distinct: 0,
    statuses: {},
    finished_seq: null,
    added_at: '2026-10-30T10:00:00',
    started_at: null,
    finished_at: null,
    ...over,
  }
}

function detail(over: Partial<SessionProblemDetail> = {}): SessionProblemDetail {
  return { ...row(), distribution: [], first_error: null, ...over }
}

function run(over: Partial<SessionRun> = {}): SessionRun {
  return {
    seq: 1,
    memory_version: 0,
    seed: 1,
    status: 'answer_found',
    key: 'ijl',
    answer: 'ijl',
    answers: ['ijl'],
    codelets: 800,
    seconds: 0.2,
    temperature: 10,
    answer_quality: 80,
    error: null,
    config_hash: 'h',
    attempts: 1,
    memory_added: { answers: 0, snags: 0 },
    state: 'ended',
    turns: 1,
    waiting_for: null,
    end_reason: 'single-turn',
    end_label: null,
    ...over,
  }
}

function turn(over: Partial<SessionTurn> = {}): SessionTurn {
  return {
    turn: 1,
    positions: { context: 'abc', second: 'abd', input: 'ijk', response: 'ijl' },
    supplied_by: { context: 'problem', second: 'problem', input: 'problem', response: 'petacat' },
    status: 'answer_found',
    codelets: 812,
    seconds: 0.3,
    answers: ['ijl'],
    answer_quality: 80,
    temperature: 12,
    error: null,
    turn_seed: 5,
    attempts: 1,
    end_reason: null,
    end_label: null,
    proposals: [],
    evidence: {
      bonds: { successor: 2, predecessor: 0 },
      groups: { 'successor-group': 1 },
      rule: { top_rule: 'replace the last letter by its successor', bottom_rule: 'replace the last letter by its successor' },
      snags: ['snag-one'],
      unperceived: 0,
      coderack: { full_posts: 12, overflowing_batches: 3, evicted: 15 },
    },
    seq: 1,
    episode_version: 0,
    configuration_revision: 0,
    config_hash: 'h',
    ...over,
  }
}

/** `abc : abd :: ijk : ?` answered `ijl`, then given `xyz`; the run waits for the input of turn 3. */
function twoTurns(over: Partial<SessionConversation> = {}): SessionConversation {
  return {
    session_id: 1,
    problem_id: 10,
    seed: 1,
    multi_turn: true,
    problem: { initial: 'abc', modified: 'abd', target: 'ijk', tag: null },
    session_state: 'running',
    state: 'waiting',
    waiting_for: 3,
    accepts_input: true,
    end_reason: null,
    end_label: null,
    turn_count: 2,
    turns: [
      turn(),
      turn({
        turn: 2,
        positions: { context: 'abc abd ijk', second: 'ijl', input: 'xyz', response: 'xyd' },
        supplied_by: { context: 'window', second: 'window', input: 'teacher', response: 'petacat' },
      }),
    ],
    ...over,
  }
}

const LIST: SessionListResponse = {
  sessions: [session()],
  executor: { kind: 'swarm', workers: 2, in_flight: 0, queued_runs: 0 },
  limits: { max_problems_per_request: 1000, max_seeds_per_problem: 10000, max_codelets: 200000 },
  defaults: {
    settings: { seeds_per_problem: 100, seed_start: 1, max_codelets: 20000, parameters: null, backend: 'off' },
    policy: POLICY,
  },
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
  m.getSessionProblemRuns.mockResolvedValue({ runs: [] })
  m.getSessionConversation.mockResolvedValue(twoTurns())
  m.getSwarmStatus.mockResolvedValue({ available: true, reason: null, started: true, workers: 2, default_backend: 'off', backends: ['off'], limits: {} })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } })

// ---------------------------------------------------------------------------
// 1. Making a multi-turn problem
// ---------------------------------------------------------------------------

describe('chat client: the multi-turn mark', () => {
  async function openForm() {
    render(<SessionPanel />)
    await screen.findByText('Pilot')
    fireEvent.click(screen.getByRole('button', { name: 'New session' }))
    await screen.findByTestId('new-session-form')
    type(screen.getByLabelText('Name (required)'), 'Chatty')
  }

  it('creates multi-turn problems when the mark is on, and plain ones when it is off', async () => {
    m.createSession.mockResolvedValue({ session: session({ id: 7 }), added: 1, problem_ids: [1], persisted: true })
    m.getSession.mockResolvedValue(session({ id: 7 }))
    await openForm()
    expect(screen.getByLabelText(/Multi-turn: each run of these context-response analogy problems is a chat/)).not.toBeChecked()
    type(screen.getByLabelText('Problems'), 'abc → abd; ijk → ?')
    fireEvent.click(screen.getByRole('button', { name: 'Create session' }))
    await waitFor(() => expect(m.createSession).toHaveBeenCalledTimes(1))
    expect(m.createSession.mock.calls[0][0].problems).toEqual([
      { initial: 'abc', modified: 'abd', target: 'ijk', answer: null },
    ])
  })

  it('sends multi_turn: true for every problem when the mark is on', async () => {
    m.createSession.mockResolvedValue({ session: session({ id: 7 }), added: 2, problem_ids: [1, 2], persisted: true })
    m.getSession.mockResolvedValue(session({ id: 7 }))
    await openForm()
    type(screen.getByLabelText('Problems'), 'abc → abd; ijk → ?\nabc abd xyz')
    fireEvent.click(screen.getByLabelText(/Multi-turn/))
    expect(screen.getByTestId('preview-summary')).toHaveTextContent('2 problems parsed')
    expect(screen.getByTestId('preview-summary')).toHaveTextContent('each run is a chat')
    fireEvent.click(screen.getByRole('button', { name: 'Create session' }))
    await waitFor(() => expect(m.createSession).toHaveBeenCalledTimes(1))
    expect(m.createSession.mock.calls[0][0].problems).toEqual([
      { initial: 'abc', modified: 'abd', target: 'ijk', answer: null, multi_turn: true },
      { initial: 'abc', modified: 'abd', target: 'xyz', answer: null, multi_turn: true },
    ])
  })

  it('takes no answer while the mark is on: says why, and rejects a line that gives one', async () => {
    await openForm()
    type(screen.getByLabelText('Problems'), 'abc → abd; ijk → ijl\nabc → abd; xyz → ?')
    expect(screen.getByTestId('preview-summary')).toHaveTextContent('2 problems parsed, 0 lines rejected')
    expect(screen.queryByTestId('multi-turn-answer-note')).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText(/Multi-turn/))
    expect(screen.getByTestId('multi-turn-answer-note')).toHaveTextContent('Answer: not taken. Petacat constructs the response of every turn')
    expect(screen.getByTestId('preview-summary')).toHaveTextContent('1 problems parsed, 1 lines rejected')
    fireEvent.click(screen.getByRole('button', { name: 'Show rejected lines' }))
    expect(screen.getByTestId('rejected-list')).toHaveTextContent(/line 1.*takes no answer/)
    // Turning the mark off brings the answer back.
    fireEvent.click(screen.getByLabelText(/Multi-turn/))
    expect(screen.getByTestId('preview-summary')).toHaveTextContent('2 problems parsed, 0 lines rejected')
  })

  it('marks problems added to a session, too', async () => {
    m.addSessionProblems.mockResolvedValue({ session: session(), added: 1, problem_ids: [5], persisted: false })
    render(<SessionPanel initialSessionId={1} />)
    const box = await screen.findByTestId('add-problems')
    type(within(box).getByLabelText('Problems'), 'abc → abd; ijk → ?')
    fireEvent.click(within(box).getByLabelText(/Multi-turn/))
    fireEvent.click(within(box).getByRole('button', { name: 'Add 1 problems' }))
    await waitFor(() => expect(m.addSessionProblems).toHaveBeenCalledTimes(1))
    expect(m.addSessionProblems).toHaveBeenCalledWith(1, [
      { initial: 'abc', modified: 'abd', target: 'ijk', answer: null, multi_turn: true },
    ])
  })

  it('adds unmarked problems as before', async () => {
    m.addSessionProblems.mockResolvedValue({ session: session(), added: 1, problem_ids: [5], persisted: false })
    render(<SessionPanel initialSessionId={1} />)
    const box = await screen.findByTestId('add-problems')
    type(within(box).getByLabelText('Problems'), 'abc abd xyz wyz')
    fireEvent.click(within(box).getByRole('button', { name: 'Add 1 problems' }))
    await waitFor(() => expect(m.addSessionProblems).toHaveBeenCalledTimes(1))
    expect(m.addSessionProblems).toHaveBeenCalledWith(1, [{ initial: 'abc', modified: 'abd', target: 'xyz', answer: 'wyz' }])
  })
})

// ---------------------------------------------------------------------------
// 2. The problems table, the summary and the runs table
// ---------------------------------------------------------------------------

describe('chat client: the problems table, the summary and the runs table', () => {
  it('marks a multi-turn problem in the problems table, and no other', async () => {
    m.listSessionProblems.mockResolvedValue({
      total: 2,
      problems: [row(), row({ id: 11, initial: 'aab', multi_turn: false })],
    })
    render(<SessionPanel initialSessionId={1} />)
    const rows = await screen.findAllByTestId('problem-row')
    expect(within(rows[0]).getByTestId('multi-turn-badge')).toHaveTextContent('multi-turn')
    expect(within(rows[1]).queryByTestId('multi-turn-badge')).not.toBeInTheDocument()
  })

  it('shows the activity waiting and the count of runs waiting in the summary', async () => {
    m.getSession.mockResolvedValue(
      session({ activity: 'waiting', runs: { total: 4, done: 1, errors: 0, capped: 0, retries: 0, waiting: 3 } }),
    )
    render(<SessionPanel initialSessionId={1} />)
    await screen.findByTestId('session-runs-line')
    expect(within(screen.getByTestId('session-detail')).getByTestId('state-badge')).toHaveTextContent('waiting')
    expect(screen.getByTestId('session-runs-line')).toHaveTextContent('3 waiting for the teacher')
  })

  async function openRuns(problem: Partial<SessionProblemRow>, runs: SessionRun[]) {
    m.listSessionProblems.mockResolvedValue({ total: 1, problems: [row(problem)] })
    m.getSessionProblem.mockResolvedValue(detail(problem))
    m.getSessionProblemRuns.mockResolvedValue({ runs })
    render(<SessionPanel initialSessionId={1} />)
    fireEvent.click(await screen.findByTestId('problem-row'))
    return screen.findByTestId('runs-table')
  }

  it('shows each run state, its turns, its end and the turn a waiting run waits for; the waiting run stands out', async () => {
    const table = await openRuns({}, [
      run({ seed: 1, state: 'ended', turns: 3, end_reason: 'teacher', end_label: 'enough' }),
      run({ seed: 2, state: 'waiting', turns: 2, waiting_for: 3, end_reason: null }),
      run({ seed: 3, state: 'running', turns: 0, end_reason: null }),
      run({ seed: 4, state: 'ended', turns: 1, end_reason: 'no-answer' }),
    ])
    const rows = await within(table).findAllByTestId('run-row')
    expect(rows).toHaveLength(4)
    expect(within(rows[0]).getByTestId('run-state')).toHaveTextContent('ended')
    expect(within(rows[0]).getByTestId('run-turns')).toHaveTextContent('3')
    expect(within(rows[0]).getByTestId('run-ended-by')).toHaveTextContent('the teacher ended it (label: enough)')
    expect(within(rows[1]).getByTestId('run-state')).toHaveTextContent('waiting for the input of turn 3')
    expect(rows[1]).toHaveAttribute('data-state', 'waiting')
    expect(rows[1].style.fontWeight).toBe('600')
    expect(rows[0].style.fontWeight).toBe('')
    expect(within(rows[2]).getByTestId('run-state')).toHaveTextContent('running')
    expect(within(rows[3]).getByTestId('run-ended-by')).toHaveTextContent('a turn with no answer')
  })

  it('leaves the runs table of a single-turn problem as it was: no state, turns or chat columns', async () => {
    const table = await openRuns({ multi_turn: false }, [run()])
    await within(table).findAllByTestId('run-row')
    for (const name of ['State', 'Turns', 'Ended by']) {
      expect(within(table).queryByRole('columnheader', { name })).not.toBeInTheDocument()
    }
    expect(within(table).queryByRole('button', { name: /chat/i })).not.toBeInTheDocument()
  })

  it('opens the chat of a run of a multi-turn problem, and closes it', async () => {
    const table = await openRuns({}, [run({ seed: 7, state: 'waiting', waiting_for: 3, end_reason: null })])
    fireEvent.click(await within(table).findByRole('button', { name: 'Open the chat of seed 7' }))
    expect(await screen.findByTestId('run-chat')).toBeInTheDocument()
    await waitFor(() => expect(m.getSessionConversation).toHaveBeenCalledWith(1, 10, 7))
    expect(await screen.findAllByTestId('chat-turn')).toHaveLength(2)
    fireEvent.click(screen.getAllByRole('button', { name: 'Close chat' })[0])
    expect(screen.queryByTestId('run-chat')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 3. The chat
// ---------------------------------------------------------------------------

describe('chat client: the chat', () => {
  const renderChat = () => render(<RunChat sessionId={1} problemId={10} seed={1} onClose={() => {}} />)

  it('shows each turn with its four positions and who supplied each', async () => {
    renderChat()
    const turns = await screen.findAllByTestId('chat-turn')
    expect(turns).toHaveLength(2)
    const t1 = within(turns[0])
    expect(t1.getByTestId('string-context').textContent).toBe('abc')
    expect(t1.getByTestId('string-second').textContent).toBe('abd')
    expect(t1.getByTestId('string-input').textContent).toBe('ijk')
    expect(t1.getByTestId('string-response').textContent).toBe('ijl')
    expect(t1.getByTestId('supplied-by-context')).toHaveTextContent('1st · the problem')
    expect(t1.getByTestId('supplied-by-second')).toHaveTextContent('2nd · the problem')
    expect(t1.getByTestId('supplied-by-input')).toHaveTextContent('3rd · the problem')
    expect(t1.getByTestId('supplied-by-response')).toHaveTextContent('4th · Petacat')

    const t2 = within(turns[1])
    expect(t2.getByTestId('string-context').textContent).toBe('abc abd ijk')
    expect(t2.getByTestId('string-second').textContent).toBe('ijl')
    expect(t2.getByTestId('string-input').textContent).toBe('xyz')
    expect(t2.getByTestId('string-response').textContent).toBe('xyd')
    // The history reads as a conversation: where the window's strings come from is said.
    expect(t2.getByTestId('supplied-by-context')).toHaveTextContent(
      "the window: turn 1's context, second string and input, joined with single spaces",
    )
    expect(t2.getByTestId('supplied-by-second')).toHaveTextContent("the window: turn 1's response")
    expect(t2.getByTestId('supplied-by-input')).toHaveTextContent('3rd · the teacher')
  })

  it('says a turn with no response has none, with its end reason and label', async () => {
    m.getSessionConversation.mockResolvedValue(
      twoTurns({
        state: 'ended',
        waiting_for: null,
        accepts_input: false,
        end_reason: 'no-answer',
        turn_count: 2,
        turns: [
          turn(),
          turn({
            turn: 2,
            positions: { context: 'abc abd ijk', second: 'ijl', input: 'qqq', response: null },
            supplied_by: { context: 'window', second: 'window', input: 'teacher', response: 'petacat' },
            status: 'step_limit',
            end_reason: 'no-answer',
          }),
        ],
      }),
    )
    renderChat()
    const turns = await screen.findAllByTestId('chat-turn')
    expect(within(turns[1]).getByTestId('no-response')).toHaveTextContent('No response: this turn did not answer.')
    expect(within(turns[1]).getByTestId('turn-end')).toHaveTextContent('Ended the run: a turn with no answer')
    expect(within(turns[1]).getByTestId('turn-status')).toHaveTextContent('step_limit')
    expect(within(turns[0]).queryByTestId('turn-end')).not.toBeInTheDocument()
    expect(screen.getByTestId('chat-state')).toHaveTextContent('Ended: a turn with no answer.')
  })

  it('shows the teacher label of the end', async () => {
    m.getSessionConversation.mockResolvedValue(
      twoTurns({ state: 'ended', waiting_for: null, accepts_input: false, end_reason: 'teacher', end_label: 'good chat' }),
    )
    renderChat()
    expect(await screen.findByTestId('chat-state')).toHaveTextContent('Ended: the teacher ended it (label: good chat).')
  })

  it('shows strings exactly as given: spaces, a tab, a line break, an emoji and a combining mark', async () => {
    const odd = '  a  b\tc\nd 😀 é '
    m.getSessionConversation.mockResolvedValue(
      twoTurns({
        turns: [
          turn({
            positions: { context: odd, second: ' ', input: 'é', response: '\t' },
          }),
        ],
        turn_count: 1,
        waiting_for: 2,
      }),
    )
    renderChat()
    const t = within(await screen.findByTestId('chat-turn'))
    // Not trimmed, collapsed or normalised: the text is the string.
    expect(t.getByTestId('string-context').textContent).toBe(odd)
    expect(t.getByTestId('string-second').textContent).toBe(' ')
    expect(t.getByTestId('string-input').textContent).toBe('é')
    expect(t.getByTestId('string-input').textContent).not.toBe('é')
    expect(t.getByTestId('string-response').textContent).toBe('\t')
    // Its boundaries are visible: a box that keeps whitespace, and an "as written" line.
    expect(t.getByTestId('string-context').style.whiteSpace).toBe('pre-wrap')
    expect(t.getByTestId('written-context').textContent).toBe(
      'as written: "  a  b\\tc\\nd 😀 e\\u0301 " (16 characters)',
    )
    expect(t.getByTestId('written-context').style.whiteSpace).toBe('pre-wrap')
    expect(t.getByTestId('written-second').textContent).toBe('as written: " " (1 character)')
    expect(t.getByTestId('written-input').textContent).toBe('as written: "e\\u0301" (2 characters)')
    expect(t.getByTestId('written-response').textContent).toBe('as written: "\\t" (1 character)')
  })

  it('gives no "as written" line to plain words', async () => {
    renderChat()
    const turns = await screen.findAllByTestId('chat-turn')
    expect(within(turns[1]).queryByTestId('written-context')).not.toBeInTheDocument()
  })

  it('asWritten spells out marks and spaces other than a plain one', () => {
    expect(asWritten('a b')).toBe('"a b"')
    expect(asWritten('é')).toBe('"e\\u0301"')
    expect(asWritten(' ')).toBe('"\\u00a0"')
    expect(asWritten('x\u{1F600}')).toBe('"x\u{1F600}"')
  })

  it('keeps the details closed, and shows the evidence and the proposals when opened', async () => {
    m.getSessionConversation.mockResolvedValue(
      twoTurns({
        turns: [
          turn({ proposals: [{ op: 'add_node', name: 'q' }, { op: 'add_link', a: 'q' }] }),
          turn({ turn: 2, evidence: null, status: 'pending', positions: { context: 'abc abd ijk', second: 'ijl', input: 'xyz', response: null } }),
        ],
      }),
    )
    renderChat()
    const details = await screen.findAllByTestId('turn-details')
    expect(details).toHaveLength(2)
    expect(details[0]).not.toHaveAttribute('open')
    fireEvent.click(within(details[0]).getByText('Details of turn 1'))
    const ev = within(details[0]).getByTestId('evidence')
    expect(ev).toHaveTextContent('Bonds by category: successor 2, predecessor 0')
    expect(ev).toHaveTextContent('Groups by category: successor-group 1')
    expect(ev).toHaveTextContent('Rule: replace the last letter by its successor (top)')
    expect(ev).toHaveTextContent('Snags: snag-one')
    expect(ev).toHaveTextContent('Symbols still unperceived: 0')
    expect(ev).toHaveTextContent('Coderack pressure: 12 full posts, 3 overflowing batches, 15 evicted')
    expect(within(details[0]).getByTestId('proposal-count')).toHaveTextContent('2 proposals.')
    expect(within(details[0]).getByTestId('proposal-list').children).toHaveLength(2)
    expect(within(details[0]).getByTestId('proposal-list')).toHaveTextContent('{"op":"add_node","name":"q"}')
    expect(within(details[1]).getByTestId('no-evidence')).toBeInTheDocument()
    expect(within(details[1]).getByTestId('proposal-count')).toHaveTextContent('No proposals.')
    // a turn that has not finished has no response yet; it is not a turn that did not answer
    const cards = screen.getAllByTestId('chat-turn')
    expect(within(cards[1]).getByTestId('no-response')).toHaveTextContent('No response yet: this turn has not finished.')
  })

  it('heads the chat with the run state: running a turn, waiting for turn N, ended', async () => {
    m.getSessionConversation.mockResolvedValue(
      twoTurns({ state: 'running', waiting_for: null, accepts_input: false, turn_count: 1, turns: [turn(), turn({ turn: 2, status: 'pending', evidence: null, positions: { context: 'abc abd ijk', second: 'ijl', input: 'xyz', response: null } })] }),
    )
    const { unmount } = renderChat()
    expect(await screen.findByTestId('chat-state')).toHaveTextContent('Running turn 2.')
    unmount()
    m.getSessionConversation.mockResolvedValue(twoTurns())
    renderChat()
    await waitFor(() => expect(screen.getByTestId('chat-state')).toHaveTextContent('Waiting for the input of turn 3.'))
  })
})

// ---------------------------------------------------------------------------
// Supplying input
// ---------------------------------------------------------------------------

describe('chat client: supplying input', () => {
  const renderChat = () => render(<RunChat sessionId={1} problemId={10} seed={1} onClose={() => {}} />)

  it('shows the input box only when the run waits and accepts input', async () => {
    renderChat()
    const box = await screen.findByTestId('chat-input')
    expect(within(box).getByLabelText('Input for turn 3')).toBeInTheDocument()
    expect(within(box).getByRole('button', { name: 'Send' })).toBeInTheDocument()
    expect(within(box).getByRole('button', { name: 'End' })).toBeInTheDocument()
    expect(within(box).getByLabelText('End label (optional)')).toBeInTheDocument()
    expect(screen.queryByTestId('no-input-reason')).not.toBeInTheDocument()
  })

  it.each([
    ['running', { state: 'running', waiting_for: null, accepts_input: false } as Partial<SessionConversation>],
    ['ended', { state: 'ended', waiting_for: null, accepts_input: false, end_reason: 'teacher' } as Partial<SessionConversation>],
  ])('shows no input box and no reason when the run is %s', async (_n, over) => {
    m.getSessionConversation.mockResolvedValue(twoTurns(over))
    renderChat()
    await screen.findByTestId('chat-state')
    expect(screen.queryByTestId('chat-input')).not.toBeInTheDocument()
    expect(screen.queryByTestId('no-input-reason')).not.toBeInTheDocument()
  })

  it.each([
    ['stopped', 'Stopped: Start it'],
    ['starting', 'Starting: it takes input when that finishes'],
    ['stopping', 'Stopping: it takes input when that finishes'],
  ] as const)('says why instead of the box when the session is %s', async (state, words) => {
    m.getSessionConversation.mockResolvedValue(twoTurns({ session_state: state, accepts_input: false }))
    renderChat()
    expect(await screen.findByTestId('no-input-reason')).toHaveTextContent(words)
    expect(screen.queryByTestId('chat-input')).not.toBeInTheDocument()
  })

  it('Send calls supplySessionInput with the waiting turn and the text exactly as typed', async () => {
    const after = twoTurns({ state: 'running', waiting_for: null, accepts_input: false })
    m.supplySessionInput.mockResolvedValue(after)
    renderChat()
    const box = await screen.findByTestId('chat-input')
    const text = ' héllo\n\t😀 '
    type(within(box).getByLabelText('Input for turn 3'), text)
    fireEvent.click(within(box).getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(m.supplySessionInput).toHaveBeenCalledTimes(1))
    expect(m.supplySessionInput).toHaveBeenCalledWith(1, 10, 1, { turn: 3, text })
    // The answer is the conversation: the box goes while a turn runs.
    await waitFor(() => expect(screen.queryByTestId('chat-input')).not.toBeInTheDocument())
    expect(screen.getByTestId('chat-state')).toHaveTextContent('Running turn')
  })

  it('End calls supplySessionInput with end: true, and the label when there is one', async () => {
    m.supplySessionInput.mockResolvedValue(twoTurns({ state: 'ended', waiting_for: null, accepts_input: false, end_reason: 'teacher' }))
    renderChat()
    const box = await screen.findByTestId('chat-input')
    fireEvent.click(within(box).getByRole('button', { name: 'End' }))
    await waitFor(() => expect(m.supplySessionInput).toHaveBeenCalledTimes(1))
    expect(m.supplySessionInput).toHaveBeenLastCalledWith(1, 10, 1, { turn: 3, end: true })
  })

  it('End sends the label as typed', async () => {
    m.supplySessionInput.mockResolvedValue(twoTurns({ state: 'ended', waiting_for: null, accepts_input: false, end_reason: 'teacher', end_label: ' x ' }))
    renderChat()
    const box = await screen.findByTestId('chat-input')
    type(within(box).getByLabelText('End label (optional)'), ' x ')
    fireEvent.click(within(box).getByRole('button', { name: 'End' }))
    await waitFor(() => expect(m.supplySessionInput).toHaveBeenCalledTimes(1))
    expect(m.supplySessionInput).toHaveBeenLastCalledWith(1, 10, 1, { turn: 3, end: true, label: ' x ' })
  })

  it('refuses empty text, U+0000 and a lone surrogate, and nothing else', async () => {
    renderChat()
    const box = await screen.findByTestId('chat-input')
    const input = within(box).getByLabelText('Input for turn 3')
    const send = within(box).getByRole('button', { name: 'Send' })
    expect(send).toBeDisabled() // empty
    type(input, 'a\u0000b')
    expect(send).toBeDisabled()
    expect(within(box).getByTestId('chat-input-problem')).toHaveTextContent('U+0000')
    type(input, 'a\uD800b')
    expect(send).toBeDisabled()
    expect(within(box).getByTestId('chat-input-problem')).toHaveTextContent('lone surrogate')
    type(input, '   ')
    expect(send).not.toBeDisabled()
    type(input, 'Ünïcode — 日本語 😀')
    expect(send).not.toBeDisabled()
  })

  it('shows a stale refusal plainly and refreshes the conversation', async () => {
    m.supplySessionInput.mockRejectedValue(apiError(409, 'stale: run 1 is not waiting for turn 3'))
    renderChat()
    const box = await screen.findByTestId('chat-input')
    type(within(box).getByLabelText('Input for turn 3'), 'hi')
    const before = m.getSessionConversation.mock.calls.length
    m.getSessionConversation.mockResolvedValue(twoTurns({ waiting_for: 4, turn_count: 3 }))
    fireEvent.click(within(box).getByRole('button', { name: 'Send' }))
    const alert = await screen.findByTestId('chat-send-error')
    expect(alert).toHaveTextContent('the run has moved on')
    expect(alert).toHaveTextContent('stale: run 1 is not waiting for turn 3')
    await waitFor(() => expect(m.getSessionConversation.mock.calls.length).toBeGreaterThan(before))
    await waitFor(() => expect(screen.getByLabelText('Input for turn 4')).toBeInTheDocument())
  })

  it('shows a busy refusal and does not refresh because of it', async () => {
    m.supplySessionInput.mockRejectedValue(apiError(409, 'busy: session 1 is stopping; wait for it to finish'))
    renderChat()
    const box = await screen.findByTestId('chat-input')
    type(within(box).getByLabelText('Input for turn 3'), 'hi')
    const before = m.getSessionConversation.mock.calls.length
    fireEvent.click(within(box).getByRole('button', { name: 'Send' }))
    const alert = await screen.findByTestId('chat-send-error')
    expect(alert).toHaveTextContent('the Training Mode Session is busy')
    expect(alert).toHaveTextContent('busy: session 1 is stopping')
    expect(m.getSessionConversation.mock.calls.length).toBe(before)
    // The typed text is kept so that it can be sent again.
    expect(within(box).getByLabelText('Input for turn 3')).toHaveValue('hi')
  })

  it('shows a 422 plainly', async () => {
    m.supplySessionInput.mockRejectedValue(
      new ApiError(422, 'x', JSON.stringify({ detail: [{ loc: ['body', 'text'], msg: 'must not be empty' }] })),
    )
    renderChat()
    const box = await screen.findByTestId('chat-input')
    type(within(box).getByLabelText('Input for turn 3'), 'hi')
    fireEvent.click(within(box).getByRole('button', { name: 'Send' }))
    const alert = await screen.findByTestId('chat-send-error')
    expect(alert).toHaveTextContent('HTTP 422')
    expect(alert).toHaveTextContent('text: must not be empty')
  })
})

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

describe('chat client: polling', () => {
  const flush = async (ms: number) => {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms)
    })
  }

  it('polls every 1.5 s while a turn runs, every 5 s while the run waits, and stops when it ends', async () => {
    vi.useFakeTimers()
    const running = twoTurns({ state: 'running', waiting_for: null, accepts_input: false })
    m.getSessionConversation.mockResolvedValue(running)
    render(<RunChat sessionId={1} problemId={10} seed={1} onClose={() => {}} />)
    await flush(0)
    expect(m.getSessionConversation).toHaveBeenCalledTimes(1)
    await flush(1500)
    expect(m.getSessionConversation).toHaveBeenCalledTimes(2)
    await flush(1500)
    expect(m.getSessionConversation).toHaveBeenCalledTimes(3)

    // The run now waits: the next fetches are 5 s apart.
    m.getSessionConversation.mockResolvedValue(twoTurns())
    await flush(1500)
    const afterSwitch = m.getSessionConversation.mock.calls.length
    await flush(4900)
    expect(m.getSessionConversation.mock.calls.length).toBe(afterSwitch)
    await flush(200)
    expect(m.getSessionConversation.mock.calls.length).toBe(afterSwitch + 1)

    // The run ends: one more fetch at most, and then none.
    m.getSessionConversation.mockResolvedValue(twoTurns({ state: 'ended', waiting_for: null, accepts_input: false, end_reason: 'teacher' }))
    await flush(5000)
    const atEnd = m.getSessionConversation.mock.calls.length
    await flush(60000)
    expect(m.getSessionConversation.mock.calls.length).toBe(atEnd)
  })

  it('does not poll a run that has already ended, after the first fetch', async () => {
    vi.useFakeTimers()
    m.getSessionConversation.mockResolvedValue(twoTurns({ state: 'ended', waiting_for: null, accepts_input: false, end_reason: 'no-answer' }))
    render(<RunChat sessionId={1} problemId={10} seed={1} onClose={() => {}} />)
    await flush(0)
    await flush(60000)
    expect(m.getSessionConversation).toHaveBeenCalledTimes(1)
  })

  it('stops polling when the chat is closed', async () => {
    vi.useFakeTimers()
    m.getSessionConversation.mockResolvedValue(twoTurns({ state: 'running', waiting_for: null, accepts_input: false }))
    const { unmount } = render(<RunChat sessionId={1} problemId={10} seed={1} onClose={() => {}} />)
    await flush(0)
    await flush(3000)
    const calls = m.getSessionConversation.mock.calls.length
    expect(calls).toBeGreaterThan(1)
    unmount()
    await flush(60000)
    expect(m.getSessionConversation.mock.calls.length).toBe(calls)
  })

  it('shows a failed load as an alert and keeps trying', async () => {
    vi.useFakeTimers()
    m.getSessionConversation.mockRejectedValueOnce(apiError(404, 'no such run'))
    render(<RunChat sessionId={1} problemId={10} seed={1} onClose={() => {}} />)
    await flush(0)
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load the chat')
    await flush(1500)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getAllByTestId('chat-turn')).toHaveLength(2)
  })
})
