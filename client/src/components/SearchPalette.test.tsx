// ---------------------------------------------------------------------------
// Petacat -- Cmd+K search reaches every kind of help topic
// ---------------------------------------------------------------------------
//
// Two failures lived here, and each looked like the other's excuse.
//
// The endpoint answers `{query, results, total}`; the client treated it as a bare
// array and called `.map` on the object, which threw into the catch and rendered
// "No results found". So the palette returned nothing for every query ever typed,
// and the second bug was invisible behind it.
//
// The second: the search labels hits by table -- `slipnet_node`, `codelet_type`,
// `component`, `glossary` -- and the help endpoints are addressed differently, a
// component or glossary term by `topic_key` rather than by the title the search
// returns. Everything unrecognised was coerced to `component` and looked up by
// title, so every glossary hit 404'd. Glossary is over half the help content.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { SearchPalette } from './SearchPalette'
import { searchDocs } from '@/api/client'
import { useHelpStore } from '@/hooks/useHelp'
import type { DocSearchHit } from '@/api/client'

vi.mock('@/api/client', () => ({
  searchDocs: vi.fn(),
}))

const mockedSearch = vi.mocked(searchDocs)

const HITS: DocSearchHit[] = [
  { type: 'slipnet_node', name: 'plato-successor', description: 'The successor relation.' },
  { type: 'codelet_type', name: 'bond-scout', description: 'Looks for a bond.' },
  {
    type: 'component',
    name: 'Workspace',
    topic_key: 'workspace',
    description: 'The perceptual workspace.',
  },
  {
    type: 'glossary',
    name: 'Numeric Substrate',
    topic_key: 'numeric_substrate',
    description: "The engine's array arithmetic.",
  },
]

let showHelp: ReturnType<typeof vi.fn>

beforeEach(() => {
  mockedSearch.mockReset()
  mockedSearch.mockResolvedValue(HITS)
  showHelp = vi.fn()
  useHelpStore.setState({ showHelp })
})

/**
 * Type a query and wait for the 300ms debounce to fire.
 *
 * Real timers rather than fake ones: the palette focuses its input through
 * `requestAnimationFrame`, which fake timers leave pending, and the search is
 * debounced by less than `waitFor`'s default patience anyway.
 */
async function search(query: string) {
  fireEvent.change(screen.getByPlaceholderText(/Search concepts/), {
    target: { value: query },
  })
  await waitFor(() => expect(mockedSearch).toHaveBeenCalledWith(query))
}

describe('SearchPalette — reading the endpoint it actually talks to', () => {
  it('shows results rather than "no results" for a query that matched', async () => {
    render(<SearchPalette open onClose={() => {}} />)
    await search('substrate')

    await waitFor(() => expect(screen.getByText('Numeric Substrate')).toBeTruthy())
    expect(screen.queryByText('No results found')).toBeNull()
  })

  it('groups the hits under the categories the endpoint labels them with', async () => {
    render(<SearchPalette open onClose={() => {}} />)
    await search('substrate')

    await waitFor(() => expect(screen.getByText('Glossary')).toBeTruthy())
    expect(screen.getByText('Slipnet Nodes')).toBeTruthy()
    expect(screen.getByText('Codelet Types')).toBeTruthy()
    expect(screen.getByText('Components')).toBeTruthy()
  })
})

describe('SearchPalette — asking for help the way each endpoint is addressed', () => {
  it('opens a glossary term as glossary, by its topic_key', async () => {
    render(<SearchPalette open onClose={() => {}} />)
    await search('substrate')
    await waitFor(() => expect(screen.getByText('Numeric Substrate')).toBeTruthy())

    fireEvent.click(screen.getByText('Numeric Substrate'))
    expect(showHelp).toHaveBeenCalledWith('glossary', 'numeric_substrate')
  })

  it('opens a component by its topic_key rather than its title', async () => {
    render(<SearchPalette open onClose={() => {}} />)
    await search('substrate')
    await waitFor(() => expect(screen.getByText('Workspace')).toBeTruthy())

    fireEvent.click(screen.getByText('Workspace'))
    expect(showHelp).toHaveBeenCalledWith('component', 'workspace')
  })

  it('opens a Slipnet node as a concept, by node name', async () => {
    render(<SearchPalette open onClose={() => {}} />)
    await search('successor')
    await waitFor(() => expect(screen.getByText('plato-successor')).toBeTruthy())

    fireEvent.click(screen.getByText('plato-successor'))
    expect(showHelp).toHaveBeenCalledWith('concept', 'plato-successor')
  })

  it('opens a codelet type as a codelet', async () => {
    render(<SearchPalette open onClose={() => {}} />)
    await search('bond')
    await waitFor(() => expect(screen.getByText('bond-scout')).toBeTruthy())

    fireEvent.click(screen.getByText('bond-scout'))
    expect(showHelp).toHaveBeenCalledWith('codelet', 'bond-scout')
  })

  it('leaves an unrecognised hit type alone rather than guessing at it', async () => {
    // Guessing is what produced the bug this replaces.
    mockedSearch.mockResolvedValue([
      { type: 'something_new', name: 'Mystery', description: '' },
    ])
    render(<SearchPalette open onClose={() => {}} />)
    await search('mystery')
    await waitFor(() => expect(screen.getByText('Mystery')).toBeTruthy())

    fireEvent.click(screen.getByText('Mystery'))
    expect(showHelp).not.toHaveBeenCalled()
  })
})
