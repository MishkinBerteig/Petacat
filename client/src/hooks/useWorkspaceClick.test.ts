import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkspaceClick } from './useWorkspaceClick'
import { useRunStore } from '@/store/runStore'

const stop = vi.fn()
const run = vi.fn()
const step = vi.fn()
const plain = { target: document.createElement('div') } as never

beforeEach(() => {
  stop.mockClear(); run.mockClear(); step.mockClear()
  useRunStore.setState({ runId: 1, status: 'idle', isProcessing: false, stop, run, step } as never)
})

describe('useWorkspaceClick', () => {
  it('steps when idle', () => {
    const { result } = renderHook(() => useWorkspaceClick())
    result.current(plain)
    expect(step).toHaveBeenCalledTimes(1)
  })

  it('stops a running run, then resumes it on the next click', () => {
    const { result } = renderHook(() => useWorkspaceClick())
    useRunStore.setState({ status: 'running' })
    result.current(plain)
    expect(stop).toHaveBeenCalledTimes(1)
    useRunStore.setState({ status: 'paused' })
    result.current(plain)
    expect(run).toHaveBeenCalledTimes(1)
    result.current(plain)
    expect(step).toHaveBeenCalledTimes(1)
  })

  it('ignores buttons and a run that is not there', () => {
    const { result } = renderHook(() => useWorkspaceClick())
    const b = document.createElement('button')
    result.current({ target: b } as never)
    useRunStore.setState({ runId: null })
    result.current(plain)
    expect(step).not.toHaveBeenCalled()
  })
})
