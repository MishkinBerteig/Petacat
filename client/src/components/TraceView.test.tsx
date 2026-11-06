// The Trace's icons, labels and filter follow the event-type names the run binds.

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { TraceList } from './TraceView'
import { useVocabularyStore } from '@/store/vocabulary'
import { renamed } from '@/test/standardVocabulary'
import type { TraceEvent } from '@/types'

function event(n: number, type: string): TraceEvent {
  return {
    event_number: n, event_type: type, description: `event ${n}`, codelet_count: n,
    temperature: 50, print_name: `E${n}`,
  } as unknown as TraceEvent
}

beforeEach(() => {
  useVocabularyStore.getState().clear()
})

describe('TraceList — event types through the vocabulary', () => {
  it('draws the answer icon and label for the standard name', () => {
    useVocabularyStore.getState().adopt(renamed({}))
    render(<TraceList trace={[event(1, 'answer_found')]} />)
    expect(screen.getByText('[A]')).toBeTruthy()
    expect(screen.getByRole('option', { name: /answer \(1\)/ })).toBeTruthy()
  })

  it('draws the answer icon and label for a renamed event type', () => {
    useVocabularyStore.getState().adopt(renamed({ 'event_type.answer_found': 'x17' }))
    render(<TraceList trace={[event(1, 'x17')]} />)
    expect(screen.getByText('[A]')).toBeTruthy()
    expect(screen.getByRole('option', { name: /answer \(1\)/ })).toBeTruthy()
  })

  it('gives the plain fallback for the old name once the row is renamed', () => {
    useVocabularyStore.getState().adopt(renamed({ 'event_type.answer_found': 'x17' }))
    render(<TraceList trace={[event(1, 'answer_found')]} />)
    expect(screen.queryByText('[A]')).toBeNull()
    expect(screen.getByText('[.]')).toBeTruthy()
  })

  it('filters by the bound name', () => {
    useVocabularyStore.getState().adopt(renamed({ 'event_type.snag': 's9' }))
    render(<TraceList trace={[event(1, 's9'), event(2, 'group_built')]} />)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 's9' } })
    expect(screen.getByText('E1')).toBeTruthy()
    expect(screen.queryByText('E2')).toBeNull()
  })

  it('does not crash with no vocabulary', () => {
    render(<TraceList trace={[event(1, 'answer_found')]} />)
    expect(screen.getByText('[.]')).toBeTruthy()
  })
})
