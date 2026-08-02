// ---------------------------------------------------------------------------
// Petacat -- the error channel is rendered where it can be seen
// ---------------------------------------------------------------------------
//
// The store can hold the best sentence in the world about why a run would not
// start; if nothing renders it, the button still looks like it did nothing. This
// is the one place `lastError` is shown, and it sits in the header so it is
// visible from whichever panel the click came from.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { LastErrorBanner } from './LastErrorBanner'
import { useRunStore } from '@/store/runStore'

beforeEach(() => {
  useRunStore.setState({ lastError: null })
})

describe('LastErrorBanner', () => {
  it('shows nothing while nothing has failed', () => {
    render(<LastErrorBanner />)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('announces the message on the channel', () => {
    useRunStore.setState({
      lastError: 'Could not start a new run: check the values entered. seed: not an integer',
    })

    render(<LastErrorBanner />)

    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain('Could not start a new run')
    expect(alert.textContent).toContain('seed: not an integer')
  })

  it('can be dismissed once it has been read', () => {
    useRunStore.setState({ lastError: 'Could not stop the run: it no longer exists.' })

    render(<LastErrorBanner />)
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }))

    expect(useRunStore.getState().lastError).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
