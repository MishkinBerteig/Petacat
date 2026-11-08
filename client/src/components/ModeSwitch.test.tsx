// ---------------------------------------------------------------------------
// Petacat -- the mode switch names the mode and moves between the two
// ---------------------------------------------------------------------------
// Metacat Mode is the views defined by v1.3; Training Mode is the Training Mode view. Run mode is
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
    ['training-mode', 'training-mode'],
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
    expect(MODE_LABELS).toEqual({ metacat: 'Metacat Mode', 'training-mode': 'Training Mode' })
  })

  it.each<[AppView, string, string]>([
    ['dashboard', 'Metacat Mode', 'Training Mode'],
    ['admin', 'Metacat Mode', 'Training Mode'],
    ['review', 'Metacat Mode', 'Training Mode'],
    ['training-mode', 'Training Mode', 'Metacat Mode'],
  ])('in the %s view marks %s as current', (view, current, other) => {
    render(<ModeSwitch view={view} onSelectView={vi.fn()} />)
    expect(screen.getByRole('button', { name: current })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: current })).toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('button', { name: other })).toHaveAttribute('aria-pressed', 'false')
  })

  it('goes to the dashboard for Metacat Mode and the Training Mode view for Training Mode', () => {
    const onSelect = vi.fn()
    const { rerender } = render(<ModeSwitch view="dashboard" onSelectView={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: 'Training Mode' }))
    expect(onSelect).toHaveBeenCalledWith('training-mode')

    onSelect.mockClear()
    rerender(<ModeSwitch view="training-mode" onSelectView={onSelect} />)
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
    render(<ModeSwitch view="training-mode" onSelectView={vi.fn()} />)
    expect(screen.getByTestId('mode-switch')).toHaveAttribute('data-mode', 'training-mode')
  })
})

describe('ModeSwitch on the Configurations view', () => {
  it('marks neither mode current, and either button still leaves for its mode', () => {
    const onSelectView = vi.fn()
    render(<ModeSwitch view="config" onSelectView={onSelectView} />)
    for (const id of ['mode-metacat', 'mode-training-mode']) {
      const b = screen.getByTestId(id)
      expect(b).toHaveAttribute('aria-pressed', 'false')
      expect(b).not.toHaveAttribute('aria-current')
    }
    expect(screen.getByTestId('mode-switch')).toHaveAttribute('data-mode', 'none')
    fireEvent.click(screen.getByTestId('mode-metacat'))
    expect(onSelectView).toHaveBeenLastCalledWith('dashboard')
    fireEvent.click(screen.getByTestId('mode-training-mode'))
    expect(onSelectView).toHaveBeenLastCalledWith('training-mode')
  })
})
