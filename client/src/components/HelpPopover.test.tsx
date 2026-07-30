// ---------------------------------------------------------------------------
// Petacat -- the help popover can show a glossary term, and can say when it cannot
// ---------------------------------------------------------------------------
//
// `useHelp` knew three kinds of topic and the glossary was not one of them, so the
// twenty-nine glossary entries -- more than half of all the help content -- had no
// way to be opened. Adding a fourth kind is only half of the fix: the popover has
// to render it, and it has to stop closing silently when a lookup fails, because a
// popover that vanishes the instant a request 404s is indistinguishable from a
// button that does nothing. That is exactly how the unreachable entries presented.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'

import { HelpPopover } from './HelpPopover'
import { useHelpStore } from '@/hooks/useHelp'
import { getGlossaryHelp, getComponentHelp } from '@/api/client'

vi.mock('@/api/client', () => ({
  getConceptHelp: vi.fn(),
  getCodeletHelp: vi.fn(),
  getComponentHelp: vi.fn(),
  getGlossaryHelp: vi.fn(),
}))

const mockedGlossary = vi.mocked(getGlossaryHelp)
const mockedComponent = vi.mocked(getComponentHelp)

beforeEach(() => {
  mockedGlossary.mockReset()
  mockedComponent.mockReset()
  useHelpStore.setState({ helpContent: null, isLoading: false, error: null })
})

describe('HelpPopover — glossary terms', () => {
  it('shows a glossary term\'s title, definition and detail', async () => {
    mockedGlossary.mockResolvedValue({
      term: 'numeric_substrate',
      title: 'Numeric Substrate',
      definition: "The engine's array arithmetic, executed on the GPU through Metal.",
      details: 'Four implementations sit behind one interface.',
      metadata: {},
    })

    render(<HelpPopover />)
    act(() => {
      useHelpStore.getState().showHelp('glossary', 'numeric_substrate')
    })

    await waitFor(() => expect(screen.getByText('Numeric Substrate')).toBeTruthy())
    expect(screen.getByText(/executed on the GPU through Metal/)).toBeTruthy()
    expect(screen.getByText(/Four implementations sit behind one interface/)).toBeTruthy()
    // The key it was fetched by, so a reader can tell which row they are looking at.
    expect(screen.getByText('numeric_substrate')).toBeTruthy()
    expect(mockedGlossary).toHaveBeenCalledWith('numeric_substrate')
  })

  it('does not look a glossary term up as a component', async () => {
    mockedGlossary.mockResolvedValue({
      term: 'jootsing',
      title: 'Jootsing',
      definition: 'Jumping out of the system.',
      details: '',
      metadata: {},
    })

    render(<HelpPopover />)
    act(() => {
      useHelpStore.getState().showHelp('glossary', 'jootsing')
    })

    await waitFor(() => expect(screen.getByText('Jootsing')).toBeTruthy())
    expect(mockedComponent).not.toHaveBeenCalled()
  })
})

describe('HelpPopover — a lookup that fails', () => {
  it('stays open and says so, rather than closing as though nothing was clicked', async () => {
    mockedGlossary.mockRejectedValue(new Error('API 404 Not Found: no such term'))

    render(<HelpPopover />)
    act(() => {
      useHelpStore.getState().showHelp('glossary', 'not_a_term')
    })

    await waitFor(() => expect(screen.getByText(/API 404 Not Found/)).toBeTruthy())
    expect(screen.getByText('Not found')).toBeTruthy()
  })
})
