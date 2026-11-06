// The run's vocabulary: comparing through the bindings, and what an unbound role does.

import { beforeEach, describe, expect, it } from 'vitest'

import { renamed, STANDARD_PAYLOAD } from '@/test/standardVocabulary'
import {
  behaviourOf,
  unboundName,
  useVocabularyStore,
  v,
} from './vocabulary'

beforeEach(() => {
  useVocabularyStore.getState().clear()
})

describe('vocabulary', () => {
  it('answers the name the run binds to a role', () => {
    useVocabularyStore.getState().adopt(STANDARD_PAYLOAD)
    expect(v('bridge_type.top')).toBe('top')
    expect(v('event_type.answer_found')).toBe('answer_found')
  })

  it('follows a renamed binding', () => {
    useVocabularyStore.getState().adopt(renamed({ 'bridge_type.top': 'x17' }))
    expect(v('bridge_type.top')).toBe('x17')
    expect(v('bridge_type.bottom')).toBe('bottom')
  })

  it('answers a name no real name equals for a role nothing binds, and does not throw', () => {
    // Nothing adopted yet: every role is unbound.
    const unbound = v('bridge_type.top')
    expect(unbound).toBe(unboundName('bridge_type.top'))
    expect(unbound === 'top').toBe(false)
    expect(unbound === '').toBe(false)
    // Two unbound roles are not equal to each other.
    expect(v('bridge_type.top') === v('bridge_type.bottom')).toBe(false)
  })

  it('does not take a prototype property for a binding', () => {
    useVocabularyStore.getState().adopt(STANDARD_PAYLOAD)
    expect(v('constructor')).toBe(unboundName('constructor'))
    expect(behaviourOf('constructor')).toBeNull()
  })

  it('compares a link type by its behaviour, whatever the type is called', () => {
    useVocabularyStore.getState().adopt(renamed({}, { lateral_sliplink: 'slip17' }))
    expect(behaviourOf('slip17')).toBe('slip')
    expect(behaviourOf('lateral_sliplink')).toBeNull()
    expect(behaviourOf('never-described')).toBeNull()
  })

  it('leaves the current vocabulary alone when a response carries none', () => {
    useVocabularyStore.getState().adopt(renamed({ 'bridge_type.top': 'x17' }))
    useVocabularyStore.getState().adopt({})
    useVocabularyStore.getState().adopt(null)
    expect(v('bridge_type.top')).toBe('x17')
  })
})
