// ---------------------------------------------------------------------------
// Petacat -- Tests for the SlipnetNodeFocus Edit button visibility
// ---------------------------------------------------------------------------
//
// Regression guard: the "Edit" button in the slipnet node focus view must be
// visible whenever the engine is NOT actively running -- including after a
// completed run (status='answer_found' / 'halted') or a user-initiated stop
// (status='paused'). It must stay hidden only while a run is actively
// executing ('running', or the Run-to-Answer-driven isProcessing flag).
//
// The original bug: the component used `hasRun = runId !== null` as its gate,
// which incorrectly hid the Edit button after every finished run (because
// runId is still set once a run exists in the store). See the commit that
// replaced that with `status !== 'running' && !isProcessing`.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import { SlipnetNodeFocus } from './SlipnetView'
import { useRunStore, type RunStatus } from '@/store/runStore'

// The node focus view calls api.getSlipnetLinks() / api.getSlipnetNodes() on
// mount to populate the connections list. We don't care about that side
// effect for this test -- return empty arrays so the component's initial
// effect can settle without network errors.
vi.mock('@/api/client', () => ({
  api: {
    getSlipnetLinks: vi.fn().mockResolvedValue([]),
    getSlipnetNodes: vi.fn().mockResolvedValue([]),
  },
}))

interface Scenario {
  label: string
  status: RunStatus
  runId: number | null
  isProcessing: boolean
  shouldShowEdit: boolean
}

const SCENARIOS: Scenario[] = [
  // --- "Engine is idle" — Edit should be available ---
  { label: 'idle, no run',                  status: 'idle',         runId: null, isProcessing: false, shouldShowEdit: true },
  { label: 'initialized but not stepped',   status: 'initialized',  runId: 42,   isProcessing: false, shouldShowEdit: true },
  { label: 'paused mid-run (user hit Stop)',status: 'paused',       runId: 42,   isProcessing: false, shouldShowEdit: true },
  { label: 'halted (max steps reached)',    status: 'halted',       runId: 42,   isProcessing: false, shouldShowEdit: true },
  { label: 'answer_found (run completed)',  status: 'answer_found', runId: 42,   isProcessing: false, shouldShowEdit: true },

  // --- "Engine is actively working" — Edit must be hidden ---
  { label: 'running in live-update mode',           status: 'running', runId: 42, isProcessing: false, shouldShowEdit: false },
  { label: 'running in Run-to-Answer (isProcessing)', status: 'running', runId: 42, isProcessing: true,  shouldShowEdit: false },
]

function setRunState(partial: Partial<ReturnType<typeof useRunStore.getState>>) {
  useRunStore.setState(partial)
}

describe('SlipnetNodeFocus — Edit button visibility', () => {
  beforeEach(() => {
    // Reset the shared Zustand store to a clean baseline before each test so
    // one test can't leak state into the next.
    setRunState({
      runId: null,
      status: 'idle',
      isProcessing: false,
      slipnet: null,
      workspace: null,
      codeletCount: 0,
      temperature: 100,
    })
  })

  for (const scenario of SCENARIOS) {
    it(`${scenario.shouldShowEdit ? 'shows' : 'hides'} Edit when ${scenario.label}`, () => {
      setRunState({
        status: scenario.status,
        runId: scenario.runId,
        isProcessing: scenario.isProcessing,
      })

      render(<SlipnetNodeFocus nodeName="plato-a" onClose={() => {}} />)

      const editButton = screen.queryByRole('button', { name: /^Edit$/ })

      if (scenario.shouldShowEdit) {
        expect(editButton).toBeInTheDocument()
      } else {
        expect(editButton).not.toBeInTheDocument()
      }
    })
  }

  // --- Sanity: the Close button must always be present, regardless of state ---
  it('always shows the Close button', () => {
    for (const status of ['idle', 'running', 'paused', 'answer_found', 'halted'] as RunStatus[]) {
      setRunState({ status, runId: status === 'idle' ? null : 42, isProcessing: false })
      const { unmount } = render(<SlipnetNodeFocus nodeName="plato-a" onClose={() => {}} />)
      expect(screen.getByRole('button', { name: /^Close$/ })).toBeInTheDocument()
      unmount()
    }
  })
})
