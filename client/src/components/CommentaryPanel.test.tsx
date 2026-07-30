// ---------------------------------------------------------------------------
// Petacat -- an empty commentary panel has two different causes
// ---------------------------------------------------------------------------
//
// Phase 0's WP3.10 made commentary a sink concern: the engine calls `emit_*`
// unconditionally, and in a Fast Run those calls land on a discarding writer. A
// Fast Run that has answered therefore returns zero paragraphs, and the panel's
// ordinary empty message -- "start a run to see commentary" -- is then advice to do
// the thing that has already been done.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

import { CommentaryPanel } from './CommentaryPanel'
import { useRunStore } from '@/store/runStore'

const ORIGINAL = useRunStore.getState()

beforeEach(() => {
  useRunStore.setState({ ...ORIGINAL }, true)
})

describe('CommentaryPanel', () => {
  it('shows the commentary when there is any', () => {
    useRunStore.setState({ commentary: 'I noticed a successor group.', runMode: 'normal' })
    render(<CommentaryPanel />)
    expect(screen.getByText(/I noticed a successor group/)).toBeTruthy()
  })

  it('tells a Fast run that its commentary was discarded, not missing', () => {
    useRunStore.setState({ commentary: '', runMode: 'fast', runId: -1, codeletCount: 2229 })
    render(<CommentaryPanel />)
    expect(screen.getByText(/discards commentary as it is produced/)).toBeTruthy()
    expect(screen.queryByText(/Start a run to see commentary/)).toBeNull()
  })

  it('keeps the ordinary invitation when no run has been started', () => {
    useRunStore.setState({ commentary: '', runMode: null, runId: null })
    render(<CommentaryPanel />)
    expect(screen.getByText(/Start a run to see commentary/)).toBeTruthy()
  })
})
