// ---------------------------------------------------------------------------
// Petacat -- the Memory panel shows the memory the run is actually thinking against
// ---------------------------------------------------------------------------
//
// A Fast Run is handed an ephemeral `EpisodicMemory` of its own, so that it can
// contribute nothing to the Training Session — that is the whole of what Fast
// promises. The panel read the shared database memory regardless, which made it a
// straightforward lie about the run on screen: the answers listed were ones the run
// could not be reminded of, and the answer it went on to find never appeared among
// them.
//
// The two actions in the header make it worse, not better, because both address the
// *shared* memory: Clear deletes the stored rows, and Compare identifies answers by
// id against the global memory — and the two memories number their answers from
// independent counters, so comparing two ephemeral answers would compare whichever
// shared answers happened to have those ids.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

import { MemoryView } from './MemoryView'
import { useRunStore } from '@/store/runStore'
import type { AnswerDescription, MemoryState } from '@/types'

function answer(overrides: Partial<AnswerDescription> = {}): AnswerDescription {
  return {
    answer_id: 1,
    problem: ['abc', 'abd', 'xyz', 'wyz'],
    quality: 72,
    temperature: 24,
    themes: {},
    top_rule_description: 'replace rightmost letter by successor',
    bottom_rule_description: 'replace leftmost letter by predecessor',
    ...overrides,
  }
}

function memory(overrides: Partial<MemoryState> = {}): MemoryState {
  return { answers: [], snags: [], ...overrides }
}

const ORIGINAL = useRunStore.getState()

beforeEach(() => {
  useRunStore.setState({ ...ORIGINAL }, true)
})

describe('MemoryView — whose memory is on screen', () => {
  it('says nothing extra for the shared memory, which is the ordinary case', () => {
    useRunStore.setState({
      memory: memory({ scope: 'shared', answers: [answer()] }),
    })

    render(<MemoryView />)
    expect(screen.queryByText(/ephemeral Episodic Memory/)).toBeNull()
  })

  it('says the memory is the run\'s own when a Fast run is loaded', () => {
    useRunStore.setState({
      memory: memory({ scope: 'run', mode: 'fast', answers: [answer()] }),
    })

    render(<MemoryView />)
    expect(screen.getByText(/ephemeral Episodic Memory/)).toBeTruthy()
    expect(screen.getByText(/nothing here reaches the Training Session/)).toBeTruthy()
  })

  it('withholds Clear Memory while an ephemeral memory is shown', () => {
    // Clearing deletes the shared rows, which are not what is on screen.
    useRunStore.setState({
      memory: memory({ scope: 'run', mode: 'fast', answers: [answer()] }),
    })

    render(<MemoryView />)
    expect(screen.queryByRole('button', { name: /Clear Memory/i })).toBeNull()
  })

  it('offers Clear Memory for the shared one', () => {
    useRunStore.setState({
      memory: memory({ scope: 'shared', answers: [answer()] }),
    })

    render(<MemoryView />)
    expect(screen.getByRole('button', { name: /Clear Memory/i })).toBeTruthy()
  })

  it('withholds Compare while an ephemeral memory is shown', () => {
    // Comparison identifies answers by id against the shared memory, and the two
    // memories number from independent counters — so the ids collide.
    useRunStore.setState({
      memory: memory({
        scope: 'run',
        mode: 'fast',
        answers: [answer({ answer_id: 1 }), answer({ answer_id: 2 })],
      }),
    })

    render(<MemoryView />)
    expect(screen.queryByRole('button', { name: /Compare/i })).toBeNull()
  })

  it('offers Compare for the shared one, once there are two answers', () => {
    useRunStore.setState({
      memory: memory({
        scope: 'shared',
        answers: [answer({ answer_id: 1 }), answer({ answer_id: 2 })],
      }),
    })

    render(<MemoryView />)
    expect(screen.getByRole('button', { name: /Compare/i })).toBeTruthy()
  })
})
