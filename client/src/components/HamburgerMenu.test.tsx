// ---------------------------------------------------------------------------
// Petacat -- Tests for the navigation menu
// ---------------------------------------------------------------------------
//
// What these defend: Training is a view of its own, between Review and
// Configuration, and choosing it reports the view to the app.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { HamburgerMenu } from './HamburgerMenu'

describe('HamburgerMenu', () => {
  it('lists Training between Review and Configuration', () => {
    render(<HamburgerMenu activeView="dashboard" onSelect={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Navigation menu' }))
    const labels = screen
      .getAllByRole('button')
      .map((b) => b.textContent?.replace('✓', '').trim())
      .filter((t) => t && t !== '☰')
    expect(labels).toEqual(['Run Dashboard', 'Review', 'Training', 'Configuration', 'Admin'])
  })

  it('selects the training view', () => {
    const onSelect = vi.fn()
    render(<HamburgerMenu activeView="dashboard" onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: 'Navigation menu' }))
    fireEvent.click(screen.getByRole('button', { name: 'Training' }))
    expect(onSelect).toHaveBeenCalledWith('training')
  })

  it('marks the active view', () => {
    render(<HamburgerMenu activeView="training" onSelect={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Navigation menu' }))
    expect(screen.getByRole('button', { name: /Training/ })).toHaveTextContent('✓')
  })
})
