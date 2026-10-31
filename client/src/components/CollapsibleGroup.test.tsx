// ---------------------------------------------------------------------------
// Petacat -- Tests for the collapsible Run Controls groups
// ---------------------------------------------------------------------------
//
// The Run Controls panel had six groups stacked open, and the Swarm group sat below
// the fold where nobody found it. Each group is now a single-row header that opens
// and closes independently, remembered per browser, and the panel must still work
// when the browser will not store anything.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { CollapsibleGroup } from './CollapsibleGroup'
import { RunControlsPanel } from './RunControlsPanel'
import { useRunStore } from '@/store/runStore'

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  getSwarmStatus: vi.fn().mockResolvedValue({ available: true, workers: 4, reason: null }),
  getParameterCatalogue: vi.fn().mockResolvedValue([]),
  getRunParameters: vi.fn().mockResolvedValue(null),
}))

const ORIGINAL = useRunStore.getState()
const header = (name: RegExp) => screen.getByRole('button', { name })

beforeEach(() => {
  window.localStorage.clear()
  useRunStore.setState({ ...ORIGINAL, runId: null }, true)
})

// Only the storage spies are restored: `restoreAllMocks` would also empty the API mocks.
const spies: { mockRestore: () => void }[] = []
afterEach(() => {
  while (spies.length > 0) spies.pop()!.mockRestore()
})

function breakStorage(...methods: ('getItem' | 'setItem')[]) {
  for (const m of methods) {
    spies.push(
      vi.spyOn(window.localStorage, m).mockImplementation(() => {
        throw new Error('blocked')
      }),
    )
  }
}

describe('CollapsibleGroup', () => {
  it('opens and closes from its header, which is a real button wired to its body', () => {
    render(
      <CollapsibleGroup id="t" title="Thing" defaultOpen={false}>
        <p>body text</p>
      </CollapsibleGroup>,
    )
    const button = header(/^thing$/i)
    expect(button).toHaveAttribute('aria-expanded', 'false')
    const body = document.getElementById(button.getAttribute('aria-controls')!)!
    expect(body).toBeTruthy()
    expect(body).not.toBeVisible()

    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    expect(body).toBeVisible()

    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'false')
  })

  it('keeps a closed group mounted, so what is in it survives closing', () => {
    render(
      <CollapsibleGroup id="t" title="Thing" defaultOpen>
        <input aria-label="typed" />
      </CollapsibleGroup>,
    )
    fireEvent.change(screen.getByLabelText('typed'), { target: { value: '42' } })
    fireEvent.click(header(/^thing$/i))
    fireEvent.click(header(/^thing$/i))
    expect(screen.getByLabelText('typed')).toHaveValue('42')
  })

  it('remembers its state across a remount', () => {
    const first = render(
      <CollapsibleGroup id="t" title="Thing" defaultOpen={false}>
        x
      </CollapsibleGroup>,
    )
    fireEvent.click(header(/^thing$/i))
    first.unmount()

    render(
      <CollapsibleGroup id="t" title="Thing" defaultOpen={false}>
        x
      </CollapsibleGroup>,
    )
    expect(header(/^thing$/i)).toHaveAttribute('aria-expanded', 'true')
  })

  it('works when storage throws on every read and write', () => {
    breakStorage('getItem', 'setItem')
    render(
      <CollapsibleGroup id="t" title="Thing" defaultOpen>
        x
      </CollapsibleGroup>,
    )
    const button = header(/^thing$/i)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'false')
  })
})

describe('RunControlsPanel — six groups, each behind one row', () => {
  const GROUPS: [RegExp, boolean][] = [
    [/^run$/i, true],
    [/^episodic memory$/i, true],
    [/^recording/i, false],
    [/^manual stepping$/i, false],
    [/^swarm$/i, false],
    [/^settings$/i, false],
  ]

  it('opens Run and Episodic Memory and starts the other four collapsed', () => {
    render(<RunControlsPanel />)
    for (const [name, open] of GROUPS) {
      expect(header(name)).toHaveAttribute('aria-expanded', String(open))
    }
  })

  it('opens the Swarm group from its header and shows its mode line', () => {
    render(<RunControlsPanel />)
    expect(screen.getByTestId('swarm-panel')).not.toBeVisible()
    fireEvent.click(header(/^swarm$/i))
    expect(screen.getByTestId('swarm-panel')).toBeVisible()
    expect(screen.getByText(/Discovery mode\./)).toBeVisible()
  })

  it('remembers which groups were opened when the panel is shown again', () => {
    const first = render(<RunControlsPanel />)
    fireEvent.click(header(/^settings$/i))
    fireEvent.click(header(/^run$/i))
    first.unmount()

    render(<RunControlsPanel />)
    expect(header(/^settings$/i)).toHaveAttribute('aria-expanded', 'true')
    expect(header(/^run$/i)).toHaveAttribute('aria-expanded', 'false')
    expect(header(/^episodic memory$/i)).toHaveAttribute('aria-expanded', 'true')
  })

  it('still renders with its defaults when storage throws', () => {
    breakStorage('getItem')
    render(<RunControlsPanel />)
    expect(header(/^run$/i)).toHaveAttribute('aria-expanded', 'true')
    expect(header(/^swarm$/i)).toHaveAttribute('aria-expanded', 'false')
  })
})
