/** `gui.ss:444-448`: a red warning whenever self-watching is off. */

import { render, screen } from '@testing-library/react'
import { describe, expect, it, beforeEach } from 'vitest'

import { SelfWatchingWarning } from './SelfWatchingWarning'
import { useParameterCatalogueStore } from '@/hooks/useParameterCatalogue'
import { useRunStore } from '@/store/runStore'

const ORIGINAL = useRunStore.getState()

beforeEach(() => {
  useRunStore.setState({ ...ORIGINAL, parameterOverrides: {}, runParameterOverrides: {} }, true)
  useParameterCatalogueStore.setState({
    specs: [{
      name: 'self_watching_enabled_default', kind: 'bool', group: 'Self-watching',
      label: 'Self-watching enabled', description: '', minimum: null, maximum: null,
      departs_from_original: true, default: true,
    }] as any,
    isLoading: false,
    error: null,
  })
})

describe('SelfWatchingWarning', () => {
  it('is absent while self-watching is on', () => {
    render(<SelfWatchingWarning which="next" />)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('warns when the next run will have self-watching off', () => {
    useRunStore.setState({ parameterOverrides: { self_watching_enabled_default: false } })
    render(<SelfWatchingWarning which="next" />)
    expect(screen.getByRole('alert').textContent).toBe('Warning: Self-watching is disabled')
  })

  it('warns about the loaded run separately from the next one', () => {
    useRunStore.setState({ runParameterOverrides: { self_watching_enabled_default: false } })
    render(<SelfWatchingWarning which="loaded" />)
    expect(screen.getByTestId('self-watching-warning-loaded')).toBeTruthy()
    render(<SelfWatchingWarning which="next" />)
    expect(screen.queryByTestId('self-watching-warning-next')).toBeNull()
  })

  it('follows a catalogue default of off', () => {
    useParameterCatalogueStore.setState({
      specs: [{
        name: 'self_watching_enabled_default', kind: 'bool', group: 'Self-watching',
        label: 'x', description: '', minimum: null, maximum: null,
        departs_from_original: true, default: false,
      }] as any,
    })
    render(<SelfWatchingWarning which="next" />)
    expect(screen.getByRole('alert')).toBeTruthy()
  })
})
