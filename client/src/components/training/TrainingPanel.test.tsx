// ---------------------------------------------------------------------------
// Petacat -- Tests for the Trainings view
// ---------------------------------------------------------------------------
//
// What these defend: the list shows each training's progress and the executor line; a
// new training is created from the parsed problems and a long list is split to the
// server's per-request limit; problems can be added only while the training accepts
// them; the table filters by status and expands a row into its distribution; the
// controls call the right routes and show the server's complaint; polling stops when
// the view goes away.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react'

import { TrainingPanel } from './TrainingPanel'
import { useRunStore } from '@/store/runStore'
import {
  ApiError,
  addTrainingProblems,
  trainingExportUrl,
  cancelTraining,
  cancelTrainingProblem,
  closeTraining,
  createTraining,
  deleteTraining,
  getTraining,
  getTrainingProblem,
  getDemos,
  getSwarmStatus,
  updateTraining,
  getTrainingProblemRuns,
  getTrainingMemory,
  listTrainingProblems,
  listTrainings,
  pauseTraining,
  resumeTraining,
} from '@/api/client'
import type {
  TrainingErrorPolicy,
  TrainingListResponse,
  TrainingProblemDetail,
  TrainingProblemRow,
  TrainingSummary,
} from '@/types'

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  listTrainings: vi.fn(),
  createTraining: vi.fn(),
  getTraining: vi.fn(),
  addTrainingProblems: vi.fn(),
  listTrainingProblems: vi.fn(),
  getTrainingProblem: vi.fn(),
  cancelTrainingProblem: vi.fn(),
  pauseTraining: vi.fn(),
  resumeTraining: vi.fn(),
  closeTraining: vi.fn(),
  cancelTraining: vi.fn(),
  deleteTraining: vi.fn(),
  getDemos: vi.fn(),
  getSwarmStatus: vi.fn(),
  updateTraining: vi.fn(),
  getTrainingProblemRuns: vi.fn(),
  getTrainingMemory: vi.fn(),
}))

function apiError(status: number, detail: string): ApiError {
  return new ApiError(status, 'x', JSON.stringify({ detail }))
}

const POLICY: TrainingErrorPolicy = {
  on_run_error: 'record',
  max_errors_per_problem: null,
  max_errors_total: null,
  on_worker_failure: 'retry',
  max_retries: 3,
  on_config_change: 'pause',
}

function training(over: Partial<TrainingSummary> = {}): TrainingSummary {
  return {
    id: 1,
    name: 'Pilot',
    note: '',
    status: 'open',
    state: 'running',
    stalled_reason: null,
    settings: {
      memory: 'shared',
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
    closed_at: null,
    problems: { total: 4, queued: 1, running: 1, finished: 2, cancelled: 0 },
    runs: { total: 400, done: 250, errors: 2, capped: 5, retries: 1 },
    codelets: 1_234_567,
    runs_per_second: 42.5,
    eta_seconds: 125,
    finished_cursor: 2,
    ...over,
  }
}

function row(over: Partial<TrainingProblemRow> = {}): TrainingProblemRow {
  return {
    id: 10,
    training_id: 1,
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

function detail(over: Partial<TrainingProblemDetail> = {}): TrainingProblemDetail {
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

const LIST: TrainingListResponse = {
  trainings: [
    training(),
    training({
      id: 2,
      name: 'Done one',
      status: 'closed',
      state: 'finished',
      problems: { total: 2, queued: 0, running: 0, finished: 2, cancelled: 0 },
      runs: { total: 200, done: 200, errors: 0, capped: 0, retries: 0 },
    }),
  ],
  executor: { kind: 'swarm', workers: 17, in_flight: 34, queued_runs: 12000 },
  limits: { max_problems_per_request: 1000, max_seeds_per_problem: 10000, max_codelets: 200000 },
  defaults: {
    settings: { memory: 'shared', seeds_per_problem: 100, seed_start: 1, max_codelets: 20000, parameters: null, backend: 'off' },
    policy: POLICY,
  },
}

const m = {
  listTrainings: vi.mocked(listTrainings),
  createTraining: vi.mocked(createTraining),
  getTraining: vi.mocked(getTraining),
  addTrainingProblems: vi.mocked(addTrainingProblems),
  listTrainingProblems: vi.mocked(listTrainingProblems),
  getTrainingProblem: vi.mocked(getTrainingProblem),
  cancelTrainingProblem: vi.mocked(cancelTrainingProblem),
  pauseTraining: vi.mocked(pauseTraining),
  resumeTraining: vi.mocked(resumeTraining),
  closeTraining: vi.mocked(closeTraining),
  cancelTraining: vi.mocked(cancelTraining),
  deleteTraining: vi.mocked(deleteTraining),
  getDemos: vi.mocked(getDemos),
  getSwarmStatus: vi.mocked(getSwarmStatus),
  updateTraining: vi.mocked(updateTraining),
  getTrainingProblemRuns: vi.mocked(getTrainingProblemRuns),
  getTrainingMemory: vi.mocked(getTrainingMemory),
}

beforeEach(() => {
  vi.clearAllMocks()
  window.location.hash = ''
  useRunStore.setState({
    formInputs: { initial: '', modified: '', target: '', answer: '', seed: '' },
    parameterOverrides: {},
  })
  m.listTrainings.mockResolvedValue(LIST)
  m.getTraining.mockResolvedValue(training())
  m.listTrainingProblems.mockResolvedValue({ total: 1, problems: [row()] })
  m.getTrainingProblem.mockResolvedValue(detail())
  m.getDemos.mockResolvedValue([])
  m.getSwarmStatus.mockResolvedValue({ available: true, reason: null, started: true, workers: 17, default_backend: 'off', backends: ['numpy', 'off'], limits: {} })
  m.getTrainingProblemRuns.mockResolvedValue({ runs: [] })
  m.getTrainingMemory.mockResolvedValue({ answers: [], snags: [] })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

const user = {
  type: (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } }),
}

describe('TrainingPanel: the list', () => {
  it('shows each training with its state, problems, runs and the executor line', async () => {
    render(<TrainingPanel />)
    expect(await screen.findByText('Pilot')).toBeInTheDocument()
    expect(screen.getByText('Done one')).toBeInTheDocument()
    expect(screen.getByTestId('executor-line')).toHaveTextContent(
      'swarm, 17 cores, 34 runs in flight, 12,000 queued',
    )
    const items = screen.getAllByTestId('training-item')
    expect(items).toHaveLength(2)
    expect(within(items[0]).getByText('running')).toBeInTheDocument()
    expect(items[0]).toHaveTextContent('2/4 problems')
    expect(items[0]).toHaveTextContent('250/400 runs')
    expect(within(items[1]).getByText('finished')).toBeInTheDocument()
    expect(within(items[0]).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '250')
  })

  it('says the executor is serial when the parallel plugin is absent', async () => {
    m.listTrainings.mockResolvedValue({ ...LIST, executor: { kind: 'serial', workers: 1, in_flight: 0, queued_runs: 0 } })
    render(<TrainingPanel />)
    expect(await screen.findByTestId('executor-line')).toHaveTextContent(
      'serial (parallel plugin not installed)',
    )
  })

  it('shows an empty state when there are no trainings', async () => {
    m.listTrainings.mockResolvedValue({ ...LIST, trainings: [] })
    render(<TrainingPanel />)
    expect(await screen.findByText(/No trainings yet/)).toBeInTheDocument()
  })

  it('shows the server text when trainings are unavailable (503)', async () => {
    m.listTrainings.mockRejectedValue(apiError(503, 'Trainings need the database'))
    render(<TrainingPanel />)
    expect(await screen.findByTestId('trainings-unavailable')).toHaveTextContent('Trainings need the database')
    expect(screen.getByRole('button', { name: 'New training' })).toBeDisabled()
  })

  it('shows the server text on a 404 too', async () => {
    m.listTrainings.mockRejectedValue(apiError(404, 'Trainings need the database'))
    render(<TrainingPanel />)
    expect(await screen.findByTestId('trainings-unavailable')).toHaveTextContent('Trainings need the database')
  })

  it('shows other failures as an alert', async () => {
    m.listTrainings.mockRejectedValue(new TypeError('failed to fetch'))
    render(<TrainingPanel />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/server is unreachable/)
  })

  it('selecting a training loads it and writes #/training/<id>', async () => {
    render(<TrainingPanel />)
    fireEvent.click((await screen.findAllByTestId('training-item'))[0])
    expect(await screen.findByTestId('training-detail')).toBeInTheDocument()
    expect(window.location.hash).toBe('#/training/1')
    expect(m.getTraining).toHaveBeenCalledWith(1)
  })
})

describe('TrainingPanel: creating a training', () => {
  async function openForm() {
    render(<TrainingPanel />)
    await screen.findByText('Pilot')
    fireEvent.click(screen.getByRole('button', { name: 'New training' }))
    const form = await screen.findByTestId('new-training-form')
    user.type(screen.getByLabelText('Name (required)'), 'T')
    return form
  }

  it('previews what was parsed and creates the training with the form values', async () => {
    m.createTraining.mockResolvedValue({ training: training({ id: 7, name: 'Fresh' }), added: 2, problem_ids: [1, 2] })
    m.getTraining.mockResolvedValue(training({ id: 7, name: 'Fresh' }))
    await openForm()

    user.type(screen.getByLabelText('Name (required)'), 'Fresh')
    user.type(screen.getByLabelText('Seeds per problem'), '50')
    user.type(
      screen.getByLabelText('Problems'),
      'abc → abd; xyz → ?\nabc abd xyz\nabc -> abd; ijk -> ?\n1bc abd xyz',
    )
    expect(screen.getByTestId('preview-summary')).toHaveTextContent(
      '2 problems parsed, 1 lines rejected, 1 duplicates · 100 runs in total',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Show rejected lines' }))
    expect(screen.getByTestId('rejected-list')).toHaveTextContent(/line 4.*not letters only/)

    fireEvent.click(screen.getByRole('button', { name: 'Create training' }))
    await waitFor(() => expect(m.createTraining).toHaveBeenCalledTimes(1))
    expect(m.createTraining).toHaveBeenCalledWith({
      name: 'Fresh',
      settings: { memory: 'shared', seeds_per_problem: 50, seed_start: 1, max_codelets: 20000 },
      policy: POLICY,
      problems: [
        { initial: 'abc', modified: 'abd', target: 'xyz', answer: null },
        { initial: 'abc', modified: 'abd', target: 'ijk', answer: null },
      ],
    })
    expect(m.addTrainingProblems).not.toHaveBeenCalled()
    expect(await screen.findByRole('heading', { name: 'Fresh' })).toBeInTheDocument()
    expect(window.location.hash).toBe('#/training/7')
  })

  it('sends the dashboard overrides only when the box is ticked', async () => {
    useRunStore.setState({ parameterOverrides: { some_param: 3 } })
    m.createTraining.mockResolvedValue({ training: training({ id: 7 }), added: 1, problem_ids: [1] })
    await openForm()
    user.type(screen.getByLabelText('Problems'), 'abc abd xyz')
    fireEvent.click(screen.getByLabelText(/Use the dashboard's parameter overrides/))
    fireEvent.click(screen.getByRole('button', { name: 'Create training' }))
    await waitFor(() => expect(m.createTraining).toHaveBeenCalled())
    expect(m.createTraining.mock.calls[0][0].settings?.parameters).toEqual({ some_param: 3 })
  })

  it('splits problems into requests of at most the server limit', async () => {
    m.listTrainings.mockResolvedValue({
      ...LIST,
      limits: { ...LIST.limits, max_problems_per_request: 2 },
    })
    m.createTraining.mockResolvedValue({ training: training({ id: 7 }), added: 2, problem_ids: [1, 2] })
    m.addTrainingProblems.mockResolvedValue({ training: training({ id: 7 }), added: 2, problem_ids: [3, 4] })
    await openForm()
    user.type(
      screen.getByLabelText('Problems'),
      ['aa bb cc', 'dd ee ff', 'gg hh ii', 'jj kk ll', 'mm nn oo'].join('\n'),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Create training' }))
    await waitFor(() => expect(m.addTrainingProblems).toHaveBeenCalledTimes(2))
    expect(m.createTraining.mock.calls[0][0].problems).toHaveLength(2)
    expect(m.addTrainingProblems.mock.calls.map((c) => [c[0], c[1].length])).toEqual([
      [7, 2],
      [7, 1],
    ])
  })

  it('selects the training and says so when a later request fails', async () => {
    m.listTrainings.mockResolvedValue({ ...LIST, limits: { ...LIST.limits, max_problems_per_request: 1 } })
    m.createTraining.mockResolvedValue({ training: training({ id: 7 }), added: 1, problem_ids: [1] })
    m.addTrainingProblems.mockRejectedValue(apiError(422, 'too many'))
    m.getTraining.mockResolvedValue(training({ id: 7 }))
    await openForm()
    user.type(screen.getByLabelText('Problems'), 'aa bb cc\ndd ee ff')
    fireEvent.click(screen.getByRole('button', { name: 'Create training' }))
    expect(await screen.findByRole('status')).toHaveTextContent(/1 of 2 problems were added/)
    expect(window.location.hash).toBe('#/training/7')
  })

  it('shows the server error and stays on the form when creation fails', async () => {
    m.createTraining.mockRejectedValue(apiError(400, 'unknown parameter'))
    await openForm()
    fireEvent.click(screen.getByRole('button', { name: 'Create training' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('unknown parameter')
    expect(screen.getByTestId('new-training-form')).toBeInTheDocument()
  })

  it('refuses a seed count above the server limit', async () => {
    await openForm()
    user.type(screen.getByLabelText('Seeds per problem'), '999999')
    expect(screen.getByRole('button', { name: 'Create training' })).toBeDisabled()
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
    fireEvent.change(screen.getByTestId('training-problems-file'), { target: { files: [file] } })
    await waitFor(() => expect(screen.getByLabelText('Problems')).toHaveValue('abc,abd,xyz\n'))
    expect(screen.getByTestId('preview-summary')).toHaveTextContent('1 problems parsed')
  })
})

describe('TrainingPanel: the training detail', () => {
  async function open(b: Partial<TrainingSummary> = {}) {
    m.getTraining.mockResolvedValue(training(b))
    render(<TrainingPanel initialTrainingId={1} />)
    return screen.findByTestId('training-detail')
  }

  it('shows the header figures', async () => {
    await open()
    expect(screen.getByRole('heading', { name: 'Pilot' })).toBeInTheDocument()
    expect(screen.getByTestId('training-problems-line')).toHaveTextContent(
      '4 total · 2 finished · 1 running · 1 queued · 0 cancelled',
    )
    const runs = screen.getByTestId('training-runs-line')
    expect(runs).toHaveTextContent('250 / 400')
    expect(runs).toHaveTextContent('42.5 runs/s')
    expect(runs).toHaveTextContent('ETA 2 min 05 s')
    expect(runs).toHaveTextContent('1,234,567 codelets')
    expect(screen.getByText(/backend off · 100 seeds per problem from 1 · max codelets per run 20,000/)).toBeInTheDocument()
  })

  it('links the exports', async () => {
    await open()
    const link = screen.getByRole('link', { name: 'problems (CSV)' })
    expect(link).toHaveAttribute('href', trainingExportUrl(1, 'problems', 'csv'))
    expect(link.getAttribute('href')).toBe('/api/trainings/1/export?what=problems&format=csv')
    expect(screen.getByRole('link', { name: 'Export runs as JSON' })).toHaveAttribute(
      'href',
      '/api/trainings/1/export?what=runs&format=json',
    )
  })

  it('pauses an open training and resumes a paused one', async () => {
    m.pauseTraining.mockResolvedValue(training({ status: 'paused', state: 'paused' }))
    m.resumeTraining.mockResolvedValue(training())
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    await waitFor(() => expect(m.pauseTraining).toHaveBeenCalledWith(1))
    const resume = await screen.findByRole('button', { name: 'Resume' })
    fireEvent.click(resume)
    await waitFor(() => expect(m.resumeTraining).toHaveBeenCalledWith(1))
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()
  })

  it('closes with a tooltip that says what it means', async () => {
    m.closeTraining.mockResolvedValue(training({ status: 'closed' }))
    await open()
    const close = screen.getByRole('button', { name: 'Close' })
    expect(close).toHaveAttribute('title', 'Accept no more problems')
    fireEvent.click(close)
    await waitFor(() => expect(m.closeTraining).toHaveBeenCalledWith(1))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled())
  })

  it('shows the server complaint when a control fails', async () => {
    m.pauseTraining.mockRejectedValue(apiError(409, 'training is cancelled'))
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('training is cancelled')
  })

  it('cancels only after confirmation', async () => {
    m.cancelTraining.mockResolvedValue(training({ status: 'cancelled', state: 'cancelled' }))
    const confirm = vi.spyOn(window, 'confirm')
    await open()
    confirm.mockReturnValueOnce(false)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(m.cancelTraining).not.toHaveBeenCalled()
    confirm.mockReturnValueOnce(true)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(m.cancelTraining).toHaveBeenCalledWith(1))
  })

  it('deletes after confirmation and returns to the list', async () => {
    m.deleteTraining.mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(m.deleteTraining).toHaveBeenCalledWith(1))
    await waitFor(() => expect(screen.queryByTestId('training-detail')).not.toBeInTheDocument())
    expect(window.location.hash).toBe('#/training')
  })

  it('shows why a training is stalled', async () => {
    await open({ state: 'stalled', stalled_reason: 'the engine configuration changed' })
    expect(screen.getByText(/Stalled: the engine configuration changed/)).toBeInTheDocument()
  })
})

describe('TrainingPanel: adding problems', () => {
  it('adds the parsed problems to an open training', async () => {
    m.addTrainingProblems.mockResolvedValue({ training: training(), added: 2, problem_ids: [5, 6] })
    m.getTraining.mockResolvedValue(training())
    render(<TrainingPanel initialTrainingId={1} />)
    const box = await screen.findByTestId('add-problems')
    user.type(within(box).getByLabelText('Problems'), 'abc → abd; ijk → ?\nabc abd xyz wyz')
    expect(within(box).getByTestId('preview-summary')).toHaveTextContent('2 problems parsed')
    fireEvent.click(within(box).getByRole('button', { name: 'Add 2 problems' }))
    await waitFor(() => expect(m.addTrainingProblems).toHaveBeenCalledTimes(1))
    expect(m.addTrainingProblems).toHaveBeenCalledWith(1, [
      { initial: 'abc', modified: 'abd', target: 'ijk', answer: null },
      { initial: 'abc', modified: 'abd', target: 'xyz', answer: 'wyz' },
    ])
    expect(await within(box).findByText('Added 2 problems.')).toBeInTheDocument()
  })

  it('is disabled when the training is closed', async () => {
    m.getTraining.mockResolvedValue(training({ status: 'closed' }))
    render(<TrainingPanel initialTrainingId={1} />)
    const box = await screen.findByTestId('add-problems')
    expect(within(box).getByText(/accepts no more problems/)).toBeInTheDocument()
    expect(within(box).getByLabelText('Problems')).toBeDisabled()
    expect(within(box).getByRole('button', { name: /^Add \d/ })).toBeDisabled()
  })

  it('is enabled while paused', async () => {
    m.getTraining.mockResolvedValue(training({ status: 'paused', state: 'paused' }))
    render(<TrainingPanel initialTrainingId={1} />)
    const box = await screen.findByTestId('add-problems')
    expect(within(box).getByLabelText('Problems')).toBeEnabled()
  })

  it('shows the server complaint, such as a 409 from a closed training', async () => {
    m.addTrainingProblems.mockRejectedValue(apiError(409, 'training is closed'))
    render(<TrainingPanel initialTrainingId={1} />)
    const box = await screen.findByTestId('add-problems')
    user.type(within(box).getByLabelText('Problems'), 'abc abd xyz')
    fireEvent.click(within(box).getByRole('button', { name: 'Add 1 problems' }))
    expect(await within(box).findByRole('alert')).toHaveTextContent('training is closed')
  })
})

describe('TrainingPanel: the problems table', () => {
  async function open(b: Partial<TrainingSummary> = {}) {
    m.getTraining.mockResolvedValue(training(b))
    render(<TrainingPanel initialTrainingId={1} />)
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
    m.listTrainingProblems.mockResolvedValue({ total: 1, problems: [row({ answer: 'wyz' })] })
    await open()
    expect(await screen.findByTestId('problem-row')).toHaveTextContent('abc → abd; xyz → wyz')
  })

  it('shows "Add problems to start" for an empty training', async () => {
    await open({ problems: { total: 0, queued: 0, running: 0, finished: 0, cancelled: 0 }, state: 'idle' })
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
      expect(m.listTrainingProblems).toHaveBeenLastCalledWith(
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
      expect(m.listTrainingProblems).toHaveBeenLastCalledWith(1, expect.objectContaining({ q: 'xyz' })),
    )
    fireEvent.click(screen.getByRole('button', { name: /^Distinct/ }))
    await waitFor(() =>
      expect(m.listTrainingProblems).toHaveBeenLastCalledWith(
        1,
        expect.objectContaining({ sort: 'distinct', order: 'desc' }),
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: /^Distinct/ }))
    await waitFor(() =>
      expect(m.listTrainingProblems).toHaveBeenLastCalledWith(1, expect.objectContaining({ order: 'asc' })),
    )
  })

  it('pages with the server total', async () => {
    m.listTrainingProblems.mockResolvedValue({ total: 120, problems: Array.from({ length: 50 }, (_, i) => row({ id: i + 1 })) })
    await open()
    await screen.findAllByTestId('problem-row')
    fireEvent.click(screen.getByRole('button', { name: /Next page of problems/ }))
    await waitFor(() =>
      expect(m.listTrainingProblems).toHaveBeenLastCalledWith(1, expect.objectContaining({ offset: 50, limit: 50 })),
    )
  })

  it('expands a row into its distribution', async () => {
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    const d = await screen.findByTestId('problem-detail')
    await within(d).findAllByTestId('distribution-row')
    expect(m.getTrainingProblem).toHaveBeenCalledWith(1, 10)
    const rows = within(d).getAllByTestId('distribution-row')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent('xyd')
    expect(rows[0]).toHaveTextContent('40.0')
    expect(rows[2]).toHaveTextContent('no answer')
    fireEvent.click(screen.getByTestId('problem-row'))
    expect(screen.queryByTestId('problem-detail')).not.toBeInTheDocument()
  })

  it('shows the first error of a problem', async () => {
    m.getTrainingProblem.mockResolvedValue(detail({ errors: 1, first_error: 'ValueError: boom' }))
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    expect(await screen.findByText(/First error: ValueError: boom/)).toBeInTheDocument()
  })

  it('opens the problem in the dashboard', async () => {
    m.listTrainingProblems.mockResolvedValue({ total: 1, problems: [row({ answer: 'wyz' })] })
    m.getTrainingProblem.mockResolvedValue(detail({ answer: 'wyz' }))
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    fireEvent.click(await screen.findByRole('button', { name: 'Open in dashboard' }))
    const f = useRunStore.getState().formInputs
    expect([f.initial, f.modified, f.target, f.answer]).toEqual(['abc', 'abd', 'xyz', 'wyz'])
    expect(window.location.hash === '' || window.location.hash === '#').toBe(true)
  })

  it('cancels a running problem, and offers it only for queued or running ones', async () => {
    m.listTrainingProblems.mockResolvedValue({ total: 1, problems: [row({ status: 'running', runs_done: 10 })] })
    m.getTrainingProblem.mockResolvedValue(detail({ status: 'running', runs_done: 10 }))
    m.cancelTrainingProblem.mockResolvedValue(row({ status: 'cancelled' }))
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel problem' }))
    await waitFor(() => expect(m.cancelTrainingProblem).toHaveBeenCalledWith(1, 10))
  })

  it('does not offer to cancel a finished problem', async () => {
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    await screen.findByTestId('problem-detail')
    expect(screen.queryByRole('button', { name: 'Cancel problem' })).not.toBeInTheDocument()
  })

  it('shows an error when the problems cannot be loaded', async () => {
    m.listTrainingProblems.mockRejectedValue(apiError(500, 'database is locked'))
    await open()
    expect(await screen.findByText(/database is locked/)).toBeInTheDocument()
  })
})

describe('TrainingPanel: polling', () => {
  it('polls the list every 3 s, a running training every 1.5 s, and stops on unmount', async () => {
    vi.useFakeTimers()
    const { unmount } = render(<TrainingPanel initialTrainingId={1} />)
    const flush = async (ms: number) => {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ms)
      })
    }
    await flush(0)
    expect(m.listTrainings).toHaveBeenCalledTimes(1)
    expect(m.getTraining).toHaveBeenCalledTimes(1)
    expect(m.listTrainingProblems).toHaveBeenCalledTimes(1)

    await flush(3000)
    expect(m.listTrainings).toHaveBeenCalledTimes(2)
    expect(m.getTraining).toHaveBeenCalledTimes(3) // t=0, 1.5, 3
    expect(m.listTrainingProblems).toHaveBeenCalledTimes(3)

    unmount()
    const calls = [m.listTrainings, m.getTraining, m.listTrainingProblems].map((f) => f.mock.calls.length)
    await flush(20000)
    expect([m.listTrainings, m.getTraining, m.listTrainingProblems].map((f) => f.mock.calls.length)).toEqual(calls)
  })

  it('slows to 5 s when the training is not running', async () => {
    vi.useFakeTimers()
    m.getTraining.mockResolvedValue(training({ status: 'closed', state: 'finished' }))
    render(<TrainingPanel initialTrainingId={1} />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    const before = m.getTraining.mock.calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4900)
    })
    expect(m.getTraining.mock.calls.length).toBe(before)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200)
    })
    expect(m.getTraining.mock.calls.length).toBe(before + 1)
  })

  it('refetches an expanded running problem no more often than every 3 s', async () => {
    vi.useFakeTimers()
    m.listTrainingProblems.mockResolvedValue({ total: 1, problems: [row({ status: 'running', runs_done: 5 })] })
    m.getTrainingProblem.mockResolvedValue(detail({ status: 'running', runs_done: 5 }))
    render(<TrainingPanel initialTrainingId={1} />)
    const flush = async (ms: number) => {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ms)
      })
    }
    await flush(0)
    fireEvent.click(screen.getByTestId('problem-row'))
    await flush(0)
    expect(m.getTrainingProblem).toHaveBeenCalledTimes(1)
    await flush(2900)
    expect(m.getTrainingProblem).toHaveBeenCalledTimes(1)
    await flush(200)
    expect(m.getTrainingProblem).toHaveBeenCalledTimes(2)
  })
})


describe('TrainingPanel: v2 features', () => {
  async function open(b: Partial<TrainingSummary> = {}) {
    m.getTraining.mockResolvedValue(training(b))
    render(<TrainingPanel initialTrainingId={1} />)
    return screen.findByTestId('training-detail')
  }

  it('shows the settings read-only, the memory counts and the extra run counts', async () => {
    await open()
    expect(screen.getByTestId('training-settings-line')).toHaveTextContent(
      'shared memory · backend off · 100 seeds per problem from 1 · max codelets per run 20,000',
    )
    expect(screen.getByTestId('training-memory-line')).toHaveTextContent('12 answers, 3 snags, version 9')
    const runs = screen.getByTestId('training-runs-line')
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

  it('renames inline with PATCH', async () => {
    m.updateTraining.mockResolvedValue(training({ name: 'Renamed' }))
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
    user.type(screen.getByLabelText('New name'), 'Renamed')
    fireEvent.click(screen.getByRole('button', { name: 'Save name' }))
    await waitFor(() => expect(m.updateTraining).toHaveBeenCalledWith(1, { name: 'Renamed' }))
    expect(await screen.findByRole('heading', { name: 'Renamed' })).toBeInTheDocument()
  })

  it('edits and saves the policy with PATCH', async () => {
    m.updateTraining.mockResolvedValue(training({ policy: { ...POLICY, on_run_error: 'pause', max_errors_total: 5 } }))
    await open()
    const editor = screen.getByTestId('policy-editor')
    expect(within(editor).getByRole('button', { name: 'Save policy' })).toBeDisabled()
    fireEvent.change(within(editor).getByLabelText('When a run raises an error'), { target: { value: 'pause' } })
    fireEvent.change(within(editor).getByLabelText('Max errors total'), { target: { value: '5' } })
    fireEvent.click(within(editor).getByRole('button', { name: 'Save policy' }))
    await waitFor(() =>
      expect(m.updateTraining).toHaveBeenCalledWith(1, {
        policy: { ...POLICY, on_run_error: 'pause', max_errors_total: 5 },
      }),
    )
    expect(await within(editor).findByText('Policy saved.')).toBeInTheDocument()
  })

  it('shows a policy error from the server', async () => {
    m.updateTraining.mockRejectedValue(apiError(400, 'bad policy value'))
    await open()
    const editor = screen.getByTestId('policy-editor')
    fireEvent.change(within(editor).getByLabelText('When the engine configuration changes'), { target: { value: 'adopt' } })
    fireEvent.click(within(editor).getByRole('button', { name: 'Save policy' }))
    expect(await within(editor).findByRole('alert')).toHaveTextContent('bad policy value')
  })

  it('lists the episode memory in a Memory tab', async () => {
    m.getTrainingMemory.mockResolvedValue({
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
    expect(m.getTrainingMemory).toHaveBeenCalledWith(1)
    expect(screen.getByTestId('memory-tab')).toHaveTextContent('Version 9')
  })

  it('has no Memory tab for independent runs', async () => {
    await open({
      settings: { ...training().settings, memory: 'independent' },
      memory: null,
      memory_version: null,
    })
    expect(screen.queryByRole('tab', { name: 'Memory' })).not.toBeInTheDocument()
    expect(screen.getByTestId('training-memory-line')).toHaveTextContent('independent')
  })

  it('labels the non-answer outcomes in plain words', async () => {
    m.listTrainingProblems.mockResolvedValue({
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
    m.getTrainingProblem.mockResolvedValue(
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
    m.getTrainingProblemRuns.mockResolvedValue({
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
          memory_added: null,
        },
      ],
    })
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    const table = await screen.findByTestId('runs-table')
    expect(m.getTrainingProblemRuns).toHaveBeenCalledWith(1, 10)
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
      codelets: 10, seconds: 0.1, temperature: 1, answer_quality: 1, error: null, config_hash: 'h', attempts: 1, memory_added: null,
    })
    m.getTrainingProblemRuns.mockResolvedValue({ runs: Array.from({ length: 60 }, (_, i) => mk(i + 1)) })
    await open()
    fireEvent.click(await screen.findByTestId('problem-row'))
    const table = await screen.findByTestId('runs-table')
    expect(await within(table).findAllByTestId('run-row')).toHaveLength(25)
    fireEvent.click(within(table).getByRole('button', { name: /Next page of runs/ }))
    expect(within(table).getAllByTestId('run-row')[0]).toHaveTextContent('26')
  })
})

describe('TrainingPanel: the new-training form (v2)', () => {
  async function openForm() {
    render(<TrainingPanel />)
    await screen.findByText('Pilot')
    fireEvent.click(screen.getByRole('button', { name: 'New training' }))
    await screen.findByTestId('new-training-form')
  }

  it('needs a name', async () => {
    await openForm()
    expect(screen.getByRole('button', { name: 'Create training' })).toBeDisabled()
    user.type(screen.getByLabelText('Name (required)'), 'x')
    expect(screen.getByRole('button', { name: 'Create training' })).toBeEnabled()
  })

  it('offers shared memory by default, with a help line for each mode', async () => {
    await openForm()
    const select = screen.getByLabelText('Memory') as HTMLSelectElement
    expect(select.value).toBe('shared')
    expect(screen.getByRole('option', { name: 'Shared (one episode)' })).toBeInTheDocument()
    expect(screen.getByTestId('memory-help-line')).toHaveTextContent(/copies the episode memory when it starts/)
    fireEvent.change(select, { target: { value: 'independent' } })
    expect(screen.getByTestId('memory-help-line')).toHaveTextContent(/empty memory/)
  })

  it('takes the error policy defaults from the server', async () => {
    m.listTrainings.mockResolvedValue({
      ...LIST,
      defaults: { ...LIST.defaults, policy: { ...POLICY, max_retries: 7, max_errors_total: 20 } },
    })
    await openForm()
    expect(screen.getByLabelText('Retries per run')).toHaveValue(7)
    expect(screen.getByLabelText('Max errors total')).toHaveValue(20)
    expect(screen.getByLabelText('Max errors per problem')).toHaveValue(null)
    expect((screen.getByLabelText('When a run raises an error') as HTMLSelectElement).value).toBe('record')
  })

  it('sends the chosen memory, max codelets, backend and policy', async () => {
    m.createTraining.mockResolvedValue({ training: training({ id: 8 }), added: 1, problem_ids: [1] })
    await openForm()
    user.type(screen.getByLabelText('Name (required)'), 'Ep')
    fireEvent.change(screen.getByLabelText('Memory'), { target: { value: 'independent' } })
    user.type(screen.getByLabelText('Max codelets per run'), '5000')
    await screen.findByRole('option', { name: 'numpy' })
    fireEvent.change(screen.getByLabelText('Backend (advanced)'), { target: { value: 'numpy' } })
    fireEvent.change(screen.getByLabelText('When a run raises an error'), { target: { value: 'skip_problem' } })
    fireEvent.change(screen.getByLabelText('Max errors per problem'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('When the engine configuration changes'), { target: { value: 'adopt' } })
    user.type(screen.getByLabelText('Problems'), 'abc abd xyz')
    fireEvent.click(screen.getByRole('button', { name: 'Create training' }))
    await waitFor(() => expect(m.createTraining).toHaveBeenCalled())
    const req = m.createTraining.mock.calls[0][0]
    expect(req.settings).toEqual({
      memory: 'independent',
      seeds_per_problem: 100,
      seed_start: 1,
      max_codelets: 5000,
      backend: 'numpy',
    })
    expect(req.policy).toEqual({
      ...POLICY,
      on_run_error: 'skip_problem',
      max_errors_per_problem: 3,
      on_config_change: 'adopt',
    })
  })

  it('refuses max codelets above the server limit', async () => {
    await openForm()
    user.type(screen.getByLabelText('Name (required)'), 'x')
    user.type(screen.getByLabelText('Max codelets per run'), '999999999')
    expect(screen.getByRole('button', { name: 'Create training' })).toBeDisabled()
  })

  it('keeps the policy in a collapsible section', async () => {
    await openForm()
    const section = screen.getByTestId('policy-section')
    expect(section.tagName).toBe('DETAILS')
    expect(within(section).getByText('When things go wrong')).toBeInTheDocument()
  })
})
