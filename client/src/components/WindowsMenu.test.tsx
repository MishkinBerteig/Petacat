import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { WindowsMenu } from './WindowsMenu'
import { useDisplayStore } from '@/store/displayStore'

beforeEach(() => {
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {} })
  useDisplayStore.setState({ hidden: [], slipnetGraphics: true, coderackGraphics: true })
})

const openMenu = () => fireEvent.click(screen.getByText('Windows'))

describe('WindowsMenu', () => {
  it('lists Hide/Show for each panel, including EEG', () => {
    render(<WindowsMenu />)
    openMenu()
    expect(screen.getByText('Hide EEG')).toBeTruthy()
    expect(screen.getByText('Hide Slipnet')).toBeTruthy()
    fireEvent.click(screen.getByText('Hide EEG'))
    openMenu()
    expect(screen.getByText('Show EEG')).toBeTruthy()
  })

  it('hides and shows all windows', () => {
    render(<WindowsMenu />)
    openMenu()
    fireEvent.click(screen.getByText('Hide all windows'))
    expect(useDisplayStore.getState().hidden.length).toBeGreaterThan(5)
    openMenu()
    fireEvent.click(screen.getByText('Show all windows'))
    expect(useDisplayStore.getState().hidden).toEqual([])
  })

  it('has Slipnet and Coderack graphics switches', () => {
    render(<WindowsMenu />)
    openMenu()
    fireEvent.click(screen.getByText(/Slipnet graphics/))
    expect(useDisplayStore.getState().slipnetGraphics).toBe(false)
    openMenu()
    fireEvent.click(screen.getByText(/Coderack graphics/))
    expect(useDisplayStore.getState().coderackGraphics).toBe(false)
  })
})
