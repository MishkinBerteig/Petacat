// ---------------------------------------------------------------------------
// Petacat -- Tests for the Swarm group (answer distribution over many seeds)
// ---------------------------------------------------------------------------
//
// What these defend: the panel sends the problem from the form (and its answer, for
// justification mode) with the seed count / first seed / max steps the researcher
// chose, shows the distribution and the telemetry line it gets back, and disables
// itself with a reason when the parallel plugin is detached or the inputs are invalid.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { SwarmPanel } from './SwarmPanel'
import { useRunStore } from '@/store/runStore'
import { getSwarmStatus, runSwarm } from '@/api/client'
import type { SwarmResult, SwarmStatus } from '@/types'

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  getSwarmStatus: vi.fn(),
  runSwarm: vi.fn(),
}))

const AVAILABLE: SwarmStatus = {
  available: true,
  reason: null,
  started: true,
  workers: 17,
  default_backend: 'off',
  limits: { max_runs_per_request: 20000, max_steps: 200000 },
}

const RESULT: SwarmResult = {
  distribution: [
    { answer: 'abd', count: 150, fraction: 0.75, mean_quality: 82.5 },
    { answer: 'abcd', count: 30, fraction: 0.15, mean_quality: 40 },
    { answer: '*NONE*', count: 20, fraction: 0.1, mean_quality: null },
  ],
  statuses: { answer_found: 180, step_limit: 20 },
  telemetry: {
    workers: 17,
    runs: 200,
    seconds: 3.1,
    runs_per_second: 64.5,
    codelets: 100000,
    codelets_per_second: 32258,
    backend: 'off',
    config_hash: 'abcdef0123456789',
    errors: 0,
  },
}

function setForm(values: Partial<ReturnType<typeof useRunStore.getState>['formInputs']>) {
  useRunStore.setState({
    formInputs: { initial: 'abc', modified: 'abd', target: 'ijk', answer: '', seed: '', ...values },
    parameterOverrides: {},
  })
}

describe('SwarmPanel', () => {
  beforeEach(() => {
    vi.mocked(getSwarmStatus).mockReset().mockResolvedValue(AVAILABLE)
    vi.mocked(runSwarm).mockReset().mockResolvedValue(RESULT)
    setForm({})
  })

  it('sends the problem and the chosen seeds, and shows the distribution and telemetry', async () => {
    render(<SwarmPanel />)
    fireEvent.change(screen.getByLabelText('Seeds'), { target: { value: '200' } })
    fireEvent.change(screen.getByLabelText('First seed'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('Max steps'), { target: { value: '3000' } })
    const button = await screen.findByRole('button', { name: /Run 200 seeds/ })
    await waitFor(() => expect(button).not.toBeDisabled())
    fireEvent.click(button)

    await waitFor(() => expect(screen.getAllByTestId('swarm-row')).toHaveLength(3))
    expect(runSwarm).toHaveBeenCalledWith({
      initial: 'abc', modified: 'abd', target: 'ijk', answer: null,
      count: 200, seed_start: 5, max_steps: 3000, include_runs: false,
    })
    const rows = screen.getAllByTestId('swarm-row')
    expect(rows[0]).toHaveTextContent('abd')
    expect(rows[0]).toHaveTextContent('150')
    expect(rows[0]).toHaveTextContent('75.0')
    expect(rows[0]).toHaveTextContent('82.5')
    expect(rows[2]).toHaveTextContent('–')
    expect(screen.getAllByTestId('swarm-bar')[0]).toHaveStyle({ width: '75%' })
    expect(screen.getByTestId('swarm-telemetry')).toHaveTextContent(
      '200 runs in 3.10 s on 17 cores, 65 runs/s',
    )
    expect(screen.getByTestId('swarm-statuses')).toHaveTextContent('answer found 180')
  })

  it('runs in justification mode when the problem has an answer', async () => {
    setForm({ answer: 'ijl' })
    render(<SwarmPanel />)
    expect(screen.getByText(/Justification mode/)).toBeInTheDocument()
    const button = await screen.findByRole('button', { name: /^Run.*seeds$/ })
    await waitFor(() => expect(button).not.toBeDisabled())
    fireEvent.click(button)
    await waitFor(() => expect(runSwarm).toHaveBeenCalled())
    expect(vi.mocked(runSwarm).mock.calls[0][0].answer).toBe('ijl')
  })

  it('disables itself and says why when the parallel plugin is detached', async () => {
    vi.mocked(getSwarmStatus).mockResolvedValue({
      ...AVAILABLE,
      available: false,
      reason: 'The parallel subsystem (server/parallel/) is not installed.',
      workers: 0,
    })
    render(<SwarmPanel />)
    expect(await screen.findByText(/Swarm unavailable/)).toHaveTextContent('not installed')
    expect(screen.getByRole('button', { name: /^Run.*seeds$/ })).toBeDisabled()
    expect(screen.getByLabelText('Seeds')).toBeDisabled()
  })

  it('refuses a seed count above the limit and explains', async () => {
    render(<SwarmPanel />)
    await screen.findByText(/17 cores/)
    fireEvent.change(screen.getByLabelText('Seeds'), { target: { value: '10001' } })
    expect(screen.getByRole('button', { name: /^Run.*seeds$/ })).toBeDisabled()
    expect(screen.getByText(/from 1 to 10,000/)).toBeInTheDocument()
  })

  it('needs a problem', async () => {
    setForm({ initial: '' })
    render(<SwarmPanel />)
    await screen.findByText(/17 cores/)
    expect(screen.getByRole('button', { name: /^Run.*seeds$/ })).toBeDisabled()
    expect(screen.getByText('Enter a problem in Problem Input first.')).toBeInTheDocument()
  })

  it('shows the server error without losing the form', async () => {
    vi.mocked(runSwarm).mockRejectedValue(new Error('boom'))
    render(<SwarmPanel />)
    const button = await screen.findByRole('button', { name: /^Run.*seeds$/ })
    await waitFor(() => expect(button).not.toBeDisabled())
    fireEvent.click(button)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByLabelText('Seeds')).toHaveValue(200)
  })
})
