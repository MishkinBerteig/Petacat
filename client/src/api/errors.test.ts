// ---------------------------------------------------------------------------
// Petacat — one failure, one sentence a reader can act on
// ---------------------------------------------------------------------------

import { describe, it, expect } from 'vitest'

import { ApiError, describeApiError } from './client'

const refusal = (status: number, detail: unknown) =>
  new ApiError(status, 'Error', JSON.stringify({ detail }))

describe('describeApiError — the kind of problem, and which one', () => {
  it('tells the four rejections apart', () => {
    const of = (status: number) => describeApiError(refusal(status, 'x'), 'save the demo')
    expect(of(400)).toContain('rejected')
    expect(of(404)).toContain('no longer exists')
    expect(of(409)).toContain('already there')
    expect(of(422)).toContain('check the values')
    expect(new Set([of(400), of(404), of(409), of(422)]).size).toBe(4)
  })

  it('names the action and carries the server detail', () => {
    const text = describeApiError(refusal(409, "Level 'high' exists"), 'save the urgency level')
    expect(text).toContain('save the urgency level')
    expect(text).toContain("Level 'high' exists")
  })

  it('unwraps a 422 field list', () => {
    const text = describeApiError(
      refusal(422, [{ loc: ['body', 'value_type'], msg: 'not a valid integer' }]),
      'save the parameter',
    )
    expect(text).toContain('value_type: not a valid integer')
  })

  it('names an unreachable server', () => {
    expect(describeApiError(new TypeError('fetch failed'), 'load the demos')).toContain(
      'unreachable',
    )
  })

  it('keeps the specific sentence when a described failure is described again', () => {
    // A caller that names its own action and a shared table that names a generic one
    // together yield the specific sentence.
    const specific = describeApiError(
      refusal(409, 'exists'),
      'delete the urgency level "high"',
    )
    expect(describeApiError(new Error(specific), 'delete the row')).toBe(specific)
  })
})
