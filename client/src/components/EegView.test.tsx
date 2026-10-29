/** The EEG window (`eeg-graphics.ss`): average Workspace activity and temperature. */

import { render, screen } from '@testing-library/react'
import { describe, expect, it, beforeEach } from 'vitest'

import { EegPlot, EegView } from './EegView'
import { useRunStore } from '@/store/runStore'
import type { EegHistory } from '@/types'

const EEG: EegHistory = {
  series: [
    { key: 'average_activity', label: 'Average Workspace Activity', color: 'yellow' },
    { key: 'temperature', label: 'Temperature', color: 'red' },
  ],
  initial_value: 100,
  samples: [
    { cycle: 0, codelet_count: 15, activity: 80, average_activity: 100, temperature: 90 },
    { cycle: 1, codelet_count: 30, activity: 60, average_activity: 90, temperature: 70 },
  ],
}

const ORIGINAL = useRunStore.getState()
beforeEach(() => {
  useRunStore.setState({ ...ORIGINAL }, true)
})

describe('EegPlot', () => {
  it('titles the two curves with their Metacat colours', () => {
    render(<EegPlot eeg={EEG} />)
    expect(screen.getByText(/Average Workspace Activity \(yellow\)/)).toBeTruthy()
    expect(screen.getByText(/Temperature \(red\)/)).toBeTruthy()
  })

  it('starts each curve at the initial value 100 and plots one point per cycle', () => {
    render(<EegPlot eeg={EEG} />)
    // y = 100 - value, so 100 is the top of the plot.
    expect(screen.getByTestId('eeg-curve-average_activity').getAttribute('points'))
      .toBe('0,0 0,0 1,10')
    expect(screen.getByTestId('eeg-curve-temperature').getAttribute('points'))
      .toBe('0,0 0,10 1,30')
  })

  it('says so when there is no EEG for the run', () => {
    render(<EegPlot eeg={null} />)
    expect(screen.getByText(/No EEG for this run/)).toBeTruthy()
  })

  it('reads the live run from the store', () => {
    useRunStore.setState({ eeg: EEG })
    render(<EegView />)
    expect(screen.getByTestId('eeg-curve-temperature')).toBeTruthy()
  })
})
