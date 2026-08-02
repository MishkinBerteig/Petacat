// ---------------------------------------------------------------------------
// Petacat — the temperature gauge reports the engine's clamp
// ---------------------------------------------------------------------------
//
// Temperature clamping is engine state: the Scheme keeps it in
// `*temperature-clamped?*`, set during a snag response (`answers.ss`) and cleared
// by `undo-snag-condition` (`trace.ss:195`), and the display reads it. Petacat
// serves the same flag on `GET /runs/{id}/temperature` and on every WebSocket
// snapshot, and the store carries it as `temperatureClamped`.
//
// Three claims follow from the indicator naming the server's state:
//   - a clamp the server refuses lights nothing, and says why;
//   - a clamp the server accepted stays lit across a remount, with the Unclamp
//     button that ends it;
//   - a clamp the engine imposed on itself shows without this display asking.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react'

import { TemperatureGauge } from './TemperatureGauge'
import { useRunStore } from '@/store/runStore'
import { ApiError } from '@/api/client'
import type { TemperatureState } from '@/types'

const clampTemperature = vi.fn(async () => undefined)
const unclampTemperature = vi.fn(async () => undefined)
const getTemperature = vi.fn(async () => served)

let served: TemperatureState

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  clampTemperature: (...args: unknown[]) => clampTemperature(...(args as [])),
  unclampTemperature: (...args: unknown[]) => unclampTemperature(...(args as [])),
  getTemperature: (...args: unknown[]) => getTemperature(...(args as [])),
}))

const ORIGINAL = useRunStore.getState()

function temperatureState(overrides: Partial<TemperatureState> = {}): TemperatureState {
  return {
    run_id: 7,
    temperature: 42,
    clamped: false,
    clamp_value: 0,
    clamp_cycles_remaining: 0,
    ...overrides,
  }
}

beforeEach(() => {
  clampTemperature.mockClear()
  unclampTemperature.mockClear()
  getTemperature.mockClear()
  served = temperatureState()
  useRunStore.setState(
    { ...ORIGINAL, runId: 7, temperature: 42, temperatureClamped: false },
    true,
  )
})

afterEach(() => {
  useRunStore.setState({ ...ORIGINAL }, true)
})

/** Open the clamp dialog by clicking the gauge. */
function openDialog(): void {
  fireEvent.click(screen.getByText('42'))
}

describe('TemperatureGauge — the clamped indicator', () => {
  it('is lit exactly when the server says the temperature is clamped', () => {
    render(<TemperatureGauge />)
    expect(screen.queryByText('Clamped')).toBeNull()

    // The engine clamps itself during a snag response; the snapshot carries it into
    // the store, and the gauge follows without this display having asked for it.
    act(() => {
      useRunStore.setState({ temperatureClamped: true })
    })

    expect(screen.getByText('Clamped')).toBeTruthy()
  })

  it('survives a remount while the clamp is in force, and keeps Unclamp reachable', () => {
    useRunStore.setState({ temperatureClamped: true })

    const first = render(<TemperatureGauge />)
    expect(screen.getByText('Clamped')).toBeTruthy()
    first.unmount()

    render(<TemperatureGauge />)
    expect(screen.getByText('Clamped')).toBeTruthy()

    openDialog()
    expect(screen.getByRole('button', { name: 'Unclamp' })).toBeTruthy()
  })

  it('follows the refreshed server state after a clamp the server accepted', async () => {
    served = temperatureState({ temperature: 40, clamped: true, clamp_value: 40 })

    render(<TemperatureGauge />)
    openDialog()
    fireEvent.click(screen.getByRole('button', { name: 'Clamp' }))

    await waitFor(() => expect(screen.getByText('Clamped')).toBeTruthy())
    expect(clampTemperature).toHaveBeenCalledWith(7, 50, 0)
    expect(useRunStore.getState().temperature).toBe(40)
  })
})

describe('TemperatureGauge — a clamp the server refuses', () => {
  it('leaves the indicator off and reports the refusal', async () => {
    clampTemperature.mockRejectedValueOnce(new Error('API 404 Not Found: no such run'))

    render(<TemperatureGauge />)
    openDialog()
    fireEvent.click(screen.getByRole('button', { name: 'Clamp' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(screen.getByRole('alert').textContent).toContain('no such run')

    // Nothing changed on the server, so nothing is lit here.
    expect(screen.queryByText('Clamped')).toBeNull()
    expect(useRunStore.getState().temperatureClamped).toBe(false)
    // The dialog stays open carrying the failure rather than closing on it.
    expect(screen.getByRole('button', { name: 'Clamp' })).toBeTruthy()
  })

  it('leaves the clamp lit when the server refuses to release it', async () => {
    useRunStore.setState({ temperatureClamped: true })
    unclampTemperature.mockRejectedValueOnce(new Error('API 500: engine busy'))

    render(<TemperatureGauge />)
    openDialog()
    fireEvent.click(screen.getByRole('button', { name: 'Unclamp' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(screen.getByText('Clamped')).toBeTruthy()
    expect(useRunStore.getState().temperatureClamped).toBe(true)
  })

  // The status says what kind of problem it is and the server's detail says which
  // one. Both are needed: the kind gives the reader their next move, the detail names
  // the thing, and the action names what they were trying to do.
  it('names the action, the kind of failure and the server\'s reason', async () => {
    clampTemperature.mockRejectedValueOnce(
      new ApiError(404, 'Not Found', JSON.stringify({ detail: 'no run with id 7' })),
    )

    render(<TemperatureGauge />)
    openDialog()
    fireEvent.click(screen.getByRole('button', { name: 'Clamp' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(screen.getByRole('alert').textContent).toContain(
      'Could not clamp the temperature: it no longer exists.',
    )
    expect(screen.getByRole('alert').textContent).toContain('no run with id 7')
  })

  it('names releasing the clamp as the action that failed', async () => {
    useRunStore.setState({ temperatureClamped: true })
    unclampTemperature.mockRejectedValueOnce(
      new ApiError(500, 'Internal Server Error', JSON.stringify({ detail: 'engine busy' })),
    )

    render(<TemperatureGauge />)
    openDialog()
    fireEvent.click(screen.getByRole('button', { name: 'Unclamp' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(screen.getByRole('alert').textContent).toContain(
      'Could not release the temperature clamp: the server failed to complete it.',
    )
    expect(screen.getByRole('alert').textContent).toContain('engine busy')
  })

  it('names an unreachable server as unreachable', async () => {
    clampTemperature.mockRejectedValueOnce(new TypeError('Failed to fetch'))

    render(<TemperatureGauge />)
    openDialog()
    fireEvent.click(screen.getByRole('button', { name: 'Clamp' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(screen.getByRole('alert').textContent).toContain(
      'Could not clamp the temperature: the server is unreachable.',
    )
  })
})
