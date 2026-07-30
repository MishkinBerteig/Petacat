// ---------------------------------------------------------------------------
// Petacat -- the header says which processor the arithmetic is running on
// ---------------------------------------------------------------------------
//
// Phase 0's Workstream B put the numeric substrate on the GPU at every Slipnet
// size. Nothing on screen said so, and a GPU build is indistinguishable from a
// checkout with MLX missing until something is slow or a float32 rounding
// difference surfaces.
//
// Two claims worth holding onto:
//
//   1. It reports what the server actually resolved to, including the case where
//      the substrate declined and the engine is running its own loops -- which is
//      a real configuration (`PETACAT_NUMERIC_BACKEND=off`) and must not read as
//      "GPU".
//   2. It fails silently. This is a decoration in the header of every view, and a
//      header that turns into an error banner because one optional read failed is
//      worse than one that is simply not there.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { SubstrateBadge } from './SubstrateBadge'
import { getNumericSubstrate } from '@/api/client'
import { useHelpStore } from '@/hooks/useHelp'
import type { NumericSubstrate } from '@/types'

vi.mock('@/api/client', () => ({
  getNumericSubstrate: vi.fn(),
}))

const mocked = vi.mocked(getNumericSubstrate)

function substrate(overrides: Partial<NumericSubstrate> = {}): NumericSubstrate {
  return {
    policy: 'auto',
    backend: 'mlx',
    device: 'gpu',
    precision: 'float32',
    exact: false,
    available: ['python', 'numpy', 'mlx', 'mlx-cpu'],
    slipnet_nodes: 59,
    slipnet_links: 202,
    vectorise_threshold: 512,
    gpu_threshold: 0,
    summary: "Numeric substrate 'mlx' on the GPU (Metal via MLX), float32, over 59 Slipnet nodes.",
    ...overrides,
  }
}

beforeEach(() => {
  mocked.mockReset()
})

describe('SubstrateBadge', () => {
  it('names the device and the backend executing the numeric work', async () => {
    mocked.mockResolvedValue(substrate())

    render(<SubstrateBadge />)
    await waitFor(() => expect(screen.getByText('GPU · mlx')).toBeTruthy())
  })

  it('carries the detail a reader needs in the tooltip rather than on the page', async () => {
    mocked.mockResolvedValue(substrate())

    render(<SubstrateBadge />)
    const badge = await screen.findByText('GPU · mlx')
    const title = badge.getAttribute('title') ?? ''
    expect(title).toContain('59 Slipnet nodes')
    expect(title).toContain('Policy: auto')
    // float32 on the GPU is a real difference from the reference, so it is stated.
    expect(title).toContain('float32')
  })

  it('says so when the substrate declined and the engine runs its own loops', async () => {
    mocked.mockResolvedValue(
      substrate({
        policy: 'off',
        backend: null,
        device: 'cpu',
        precision: 'float64',
        exact: true,
        summary: 'No numeric substrate: the engine runs its own loops over 59 Slipnet nodes.',
      }),
    )

    render(<SubstrateBadge />)
    await waitFor(() => expect(screen.getByText('engine loops')).toBeTruthy())
  })

  it('renders nothing at all rather than an error when the read fails', async () => {
    mocked.mockRejectedValue(new Error('API 500'))

    const { container } = render(<SubstrateBadge />)
    await waitFor(() => expect(mocked).toHaveBeenCalled())
    expect(container.textContent).toBe('')
  })

  it('opens the glossary entry the tooltip cannot hold', async () => {
    // The badge raises a question -- what are the four backends, why does the GPU one
    // diverge -- that the `numeric_substrate` glossary entry answers and a tooltip
    // cannot. The entry existed and was unreachable: nothing in the UI could ask for
    // a glossary term at all.
    const showHelp = vi.fn()
    useHelpStore.setState({ showHelp })
    mocked.mockResolvedValue(substrate())

    render(<SubstrateBadge />)
    fireEvent.click(await screen.findByText('GPU · mlx'))

    expect(showHelp).toHaveBeenCalledWith('glossary', 'numeric_substrate')
  })
})
