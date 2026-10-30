// A refresh of the timeline must never discard a note that is being typed.

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { ClearMarkerRow } from './EpisodicRunTimeline'
import { memoryClear } from './__fixtures__/recorded'

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  setMemoryClearNote: vi.fn(),
}))

function row(clear = memoryClear({ clear_id: 4, note: 'from server' })) {
  return (
    <table>
      <tbody>
        <ClearMarkerRow clear={clear} onSaved={() => {}} />
      </tbody>
    </table>
  )
}

const field = () => screen.getByLabelText(/Note on the Episodic Memory clear/) as HTMLInputElement

describe('ClearMarkerRow — a late refresh', () => {
  it('keeps an in-progress edit when the same note arrives again', () => {
    const { rerender } = render(row())
    fireEvent.change(field(), { target: { value: 'typing' } })
    rerender(row(memoryClear({ clear_id: 4, note: 'from server' })))
    expect(field().value).toBe('typing')
  })

  it('keeps an in-progress edit when the server note changed underneath it', () => {
    const { rerender } = render(row())
    fireEvent.change(field(), { target: { value: 'typing' } })
    rerender(row(memoryClear({ clear_id: 4, note: 'changed elsewhere' })))
    expect(field().value).toBe('typing')
  })

  it('follows the server note when nothing was edited', () => {
    const { rerender } = render(row())
    rerender(row(memoryClear({ clear_id: 4, note: 'changed elsewhere' })))
    expect(field().value).toBe('changed elsewhere')
  })
})
