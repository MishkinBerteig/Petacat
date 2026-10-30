// ---------------------------------------------------------------------------
// Petacat -- the mode switch names the mode and moves between the two
// ---------------------------------------------------------------------------
// Metacat Mode is the v1.2 views; Training Mode is the Training view. Run mode is
// orthogonal and is not a third choice here.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { ModeSwitch, modeOfView, MODE_LABELS } from './ModeSwitch'
import { useHelpStore } from '@/hooks/useHelp'
import type { AppView } from './HamburgerMenu'

describe('modeOfView', () => {
  it.each<[AppView, string]>([
    ['dashboard', 'metacat'],
    ['review', 'metacat'],
    ['config', 'metacat'],
    ['admin', 'metacat'],
    ['training', 'training'],
  ])('puts %s in %s', (view, mode) => {
    expect(modeOfView(view)).toBe(mode)
  })
})

describe('ModeSwitch', () => {
  beforeEach(() => {
    useHelpStore.setState({ showHelp: vi.fn() } as never)
  })

  it('names both modes as proper names', () => {
    render(<ModeSwitch view="dashboard" onSelectView={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Metacat Mode' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Training Mode' })).toBeTruthy()
    expect(MODE_LABELS).toEqual({ metacat: 'Metacat Mode', training: 'Training Mode' })
  })

  it.each<[AppView, string, string]>([
    ['dashboard', 'Metacat Mode', 'Training Mode'],
    ['admin', 'Metacat Mode', 'Training Mode'],
    ['review', 'Metacat Mode', 'Training Mode'],
    ['training', 'Training Mode', 'Metacat Mode'],
  ])('in the %s view marks %s as current', (view, current, other) => {
    render(<ModeSwitch view={view} onSelectView={vi.fn()} />)
    expect(screen.getByRole('button', { name: current })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: current })).toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('button', { name: other })).toHaveAttribute('aria-pressed', 'false')
  })

  it('goes to the dashboard for Metacat Mode and the Training view for Training Mode', () => {
    const onSelect = vi.fn()
    const { rerender } = render(<ModeSwitch view="dashboard" onSelectView={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: 'Training Mode' }))
    expect(onSelect).toHaveBeenCalledWith('training')

    onSelect.mockClear()
    rerender(<ModeSwitch view="training" onSelectView={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: 'Metacat Mode' }))
    expect(onSelect).toHaveBeenCalledWith('dashboard')
  })

  it('does nothing when the current mode is chosen again (Admin stays in Admin)', () => {
    const onSelect = vi.fn()
    render(<ModeSwitch view="admin" onSelectView={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: 'Metacat Mode' }))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('cannot be switched while disabled', () => {
    const onSelect = vi.fn()
    render(<ModeSwitch view="dashboard" onSelectView={onSelect} disabled />)
    expect(screen.getByRole('button', { name: 'Training Mode' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Training Mode' }))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('links to the modes help topic', () => {
    const showHelp = vi.fn()
    useHelpStore.setState({ showHelp } as never)
    render(<ModeSwitch view="dashboard" onSelectView={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Show help for the modes' }))
    expect(showHelp).toHaveBeenCalledWith('component', 'modes')
  })

  it('exposes the current mode on its group for styling and tests', () => {
    render(<ModeSwitch view="training" onSelectView={vi.fn()} />)
    expect(screen.getByTestId('mode-switch')).toHaveAttribute('data-mode', 'training')
  })
})
