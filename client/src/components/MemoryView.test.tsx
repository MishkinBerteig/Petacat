// ---------------------------------------------------------------------------
// Petacat -- the Memory panel shows the memory the run is actually thinking against
// ---------------------------------------------------------------------------
//
// Every Run shares the Training Session's Episodic Memory, and the panel shows it. A
// Fast Run writes no database rows, so its copy is read from the live object the engine
// is using; `scope` reports which read was taken — `shared` from the rows, `live` from
// the object — and both are the same memory with the same answers under the same ids.
//
// The header's two actions therefore apply to either read: Clear deletes the session's
// answers, and Compare identifies two of them by id.
//
// The panel reads its own memory, so a blank panel has one meaning at a time: a memory
// holding nothing says so, and a memory the server would not give up says why. The
// tests below drive the real API client through a faked `fetch`, so every failure
// travels the path a live failure travels — status, server detail and all.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { MemoryView } from './MemoryView'
import { useRunStore } from '@/store/runStore'
import type { AnswerDescription, MemoryState } from '@/types'

function answer(overrides: Partial<AnswerDescription> = {}): AnswerDescription {
  return {
    answer_id: 1,
    problem: ['abc', 'abd', 'xyz', 'wyz'],
    quality: 72,
    temperature: 24,
    themes: {},
    top_rule_description: 'replace rightmost letter by successor',
    bottom_rule_description: 'replace leftmost letter by predecessor',
    ...overrides,
  }
}

function memory(overrides: Partial<MemoryState> = {}): MemoryState {
  return { answers: [], snags: [], ...overrides }
}

const EXPLANATION = {
  answer_id: 1,
  problem: ['abc', 'abd', 'xyz', 'wyz'],
  eliza_mode: true,
  text: 'This answer is based on seeing abc and xyz as going in opposite directions.  Personally, I think this answer is pretty good.',
  explanation: 'This answer is based on seeing abc and xyz as going in opposite directions.',
  eliza_text: 'x',
  technical_text: 'y',
  quality_phrase: 'pretty good',
  coherence_phrase: 'coherent',
  is_coherent: true,
}

// ---------------------------------------------------------------------------
// The faked server
// ---------------------------------------------------------------------------

/** The parts of a Response the API client's `request` reads. */
function reply(body: unknown, status = 200, statusText = 'OK') {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

/** A refusal in the shape FastAPI sends one. */
function refusal(status: number, statusText: string, detail: string) {
  return reply({ detail }, status, statusText)
}

/** Whether a URL is the panel's read of the Training Session's memory. */
function isMemoryRead(url: string): boolean {
  return url.endsWith('/api/memory') || /\/api\/runs\/-?\d+\/memory$/.test(url)
}

type Handler = (url: string, init?: RequestInit) => Promise<unknown>

/**
 * What the server answers, per test.
 *
 * The default serves the memory the test put in the store, so the panel's own read
 * lands on exactly the memory the test declared.
 */
let handler: Handler
let asked: string[]

const ORIGINAL = useRunStore.getState()

beforeEach(() => {
  useRunStore.setState({ ...ORIGINAL }, true)
  asked = []
  handler = async (url) => {
    if (isMemoryRead(url)) return reply(useRunStore.getState().memory)
    return refusal(404, 'Not Found', `nothing serves ${url}`)
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      asked.push(url)
      return handler(url, init)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('MemoryView — how the session memory was read', () => {
  it('says nothing extra when the memory came from the stored rows', () => {
    useRunStore.setState({
      memory: memory({ scope: 'shared', answers: [answer()] }),
    })

    render(<MemoryView />)
    expect(screen.queryByText(/Read live/)).toBeNull()
  })

  it('says the memory was read live when a Fast run is loaded', () => {
    // A Fast run writes no rows, so its memory is read from the live object. It is the
    // Training Session's memory either way.
    useRunStore.setState({
      memory: memory({ scope: 'live', mode: 'fast', answers: [answer()] }),
    })

    render(<MemoryView />)
    expect(screen.getByText(/Read live/)).toBeTruthy()
    expect(screen.getByText(/shares this memory and is reminded from it/)).toBeTruthy()
  })

  it('offers Clear Memory for a live read', () => {
    useRunStore.setState({
      memory: memory({ scope: 'live', mode: 'fast', answers: [answer()] }),
    })

    render(<MemoryView />)
    expect(screen.getByRole('button', { name: /Clear Memory/i })).toBeTruthy()
  })

  it('offers Clear Memory for a shared read', () => {
    useRunStore.setState({
      memory: memory({ scope: 'shared', answers: [answer()] }),
    })

    render(<MemoryView />)
    expect(screen.getByRole('button', { name: /Clear Memory/i })).toBeTruthy()
  })

  it('offers Compare for a live read, once there are two answers', () => {
    // One memory, one set of answer ids, so a comparison resolves either way.
    useRunStore.setState({
      memory: memory({
        scope: 'live',
        mode: 'fast',
        answers: [answer({ answer_id: 1 }), answer({ answer_id: 2 })],
      }),
    })

    render(<MemoryView />)
    expect(screen.getByRole('button', { name: /Compare/i })).toBeTruthy()
  })

  it('offers Compare for a shared read, once there are two answers', () => {
    useRunStore.setState({
      memory: memory({
        scope: 'shared',
        answers: [answer({ answer_id: 1 }), answer({ answer_id: 2 })],
      }),
    })

    render(<MemoryView />)
    expect(screen.getByRole('button', { name: /Compare/i })).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// `explain` (`answers.ss:310-333`) — the program's account of a single answer.
//
// MetaCat offers this alongside the two-answer comparison, and it is where the
// Eliza-mode switch is visible for an answer description: the closing sentence is the
// only part that differs between voices (§4.6, pp. 183-184), so the switch has to reach
// this request or the panel would always speak in one of them.
// ---------------------------------------------------------------------------

describe('MemoryView — explaining one answer', () => {
  it('asks for the explanation in the voice the Eliza switch is set to', async () => {
    handler = async (url) => {
      if (isMemoryRead(url)) return reply(useRunStore.getState().memory)
      return reply(EXPLANATION)
    }

    useRunStore.setState({
      memory: memory({ scope: 'shared', answers: [answer({ answer_id: 1 })] }),
      elizaMode: true,
    })

    render(<MemoryView />)
    fireEvent.click(screen.getByRole('button', { name: /explain/i }))

    await screen.findByText(/This answer is based on seeing/)
    const explanationUrl = asked.find((u) => u.includes('/explanation'))
    expect(explanationUrl).toContain('/memory/answers/1/explanation')
    expect(explanationUrl).toContain('eliza_mode=true')
  })

  it('puts the explanation away when asked again', async () => {
    handler = async (url) => {
      if (isMemoryRead(url)) return reply(useRunStore.getState().memory)
      return reply({ ...EXPLANATION, eliza_mode: false })
    }

    useRunStore.setState({
      memory: memory({ scope: 'shared', answers: [answer({ answer_id: 1 })] }),
    })

    render(<MemoryView />)
    fireEvent.click(screen.getByRole('button', { name: /explain/i }))
    await screen.findByText(/This answer is based on seeing/)

    fireEvent.click(screen.getByRole('button', { name: /explain/i }))
    await waitFor(() =>
      expect(screen.queryByText(/This answer is based on seeing/)).toBeNull(),
    )
  })

  it('says why there is no explanation when the server refuses to give one', async () => {
    handler = async (url) => {
      if (isMemoryRead(url)) return reply(useRunStore.getState().memory)
      return refusal(404, 'Not Found', 'answer 1 is no longer in memory')
    }

    useRunStore.setState({
      memory: memory({ scope: 'shared', answers: [answer({ answer_id: 1 })] }),
    })

    render(<MemoryView />)
    fireEvent.click(screen.getByRole('button', { name: /explain/i }))

    await waitFor(() =>
      expect(screen.getByText(/Could not explain the answer: it no longer exists/)).toBeTruthy(),
    )
    expect(screen.getByText(/answer 1 is no longer in memory/)).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// A memory that could not be read, told apart from a memory holding nothing
// ---------------------------------------------------------------------------
//
// "No answers stored" is a claim about the Training Session: it says the runs so far
// have found nothing worth remembering, which is the fact §5.2's experiments turn on.
// The panel reserves it for that case, and gives the reason when the read failed.
// ---------------------------------------------------------------------------

describe('MemoryView — a memory that would not load', () => {
  it('gives the reason instead of claiming the memory is empty', async () => {
    handler = async () =>
      refusal(503, 'Service Unavailable', 'the database is not accepting connections')

    render(<MemoryView />)

    await waitFor(() =>
      expect(
        screen.getByText(/Could not load episodic memory: the server failed to complete it/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/the database is not accepting connections/)).toBeTruthy()
    expect(screen.queryByText('No answers stored')).toBeNull()
  })

  it('says the memory is empty when it is genuinely empty', async () => {
    useRunStore.setState({ memory: memory({ scope: 'shared' }) })

    render(<MemoryView />)

    await waitFor(() => expect(screen.getByText('No answers stored')).toBeTruthy())
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('names an unreachable server as unreachable', async () => {
    handler = async () => {
      throw new TypeError('Failed to fetch')
    }

    render(<MemoryView />)

    await waitFor(() =>
      expect(
        screen.getByText(/Could not load episodic memory: the server is unreachable/),
      ).toBeTruthy(),
    )
  })
})

// ---------------------------------------------------------------------------
// The actions the panel offers, each reporting its own failure
// ---------------------------------------------------------------------------

describe('MemoryView — an action the server refuses', () => {
  function twoAnswers() {
    useRunStore.setState({
      memory: memory({
        scope: 'shared',
        answers: [answer({ answer_id: 1 }), answer({ answer_id: 2 })],
      }),
    })
  }

  /** Select both answer cards, which is what enables Compare. */
  function selectBoth() {
    const cards = screen.getAllByTitle(/click to select for comparison/)
    fireEvent.click(cards[0])
    fireEvent.click(cards[1])
  }

  it('reports a comparison the server would not make, rather than doing nothing', async () => {
    handler = async (url) => {
      if (isMemoryRead(url)) return reply(useRunStore.getState().memory)
      return refusal(422, 'Unprocessable Entity', 'answer_id_2: answer 2 has no themes')
    }
    twoAnswers()

    render(<MemoryView />)
    selectBoth()
    fireEvent.click(screen.getByRole('button', { name: /Compare/i }))

    await waitFor(() =>
      expect(
        screen.getByText(/Could not compare the two answers: check the values entered/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/answer 2 has no themes/)).toBeTruthy()
    // The button is usable again rather than stuck on "Comparing...".
    expect(screen.getByRole('button', { name: /Compare/i })).toBeTruthy()
  })

  it('shows the comparison when the server makes one', async () => {
    handler = async (url) => {
      if (isMemoryRead(url)) return reply(useRunStore.getState().memory)
      return reply({
        answer_id_1: 1,
        answer_id_2: 2,
        comparison: {},
        commentary: {
          text: 'The two answers differ in direction.',
          paragraphs: ['The two answers differ in direction.'],
          segments: [],
          verdict: '',
          eliza_text: '',
          technical_text: '',
          preferred: { answer: null, reason: '' },
        },
      })
    }
    twoAnswers()

    render(<MemoryView />)
    selectBoth()
    fireEvent.click(screen.getByRole('button', { name: /Compare/i }))

    await waitFor(() =>
      expect(screen.getByText('The two answers differ in direction.')).toBeTruthy(),
    )
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('reports an answer the server would not forget', async () => {
    handler = async (url, init) => {
      if (isMemoryRead(url) && (init?.method ?? 'GET') === 'GET') {
        return reply(useRunStore.getState().memory)
      }
      return refusal(404, 'Not Found', 'answer 1 is already gone')
    }
    useRunStore.setState({
      memory: memory({ scope: 'shared', answers: [answer({ answer_id: 1 })] }),
    })

    render(<MemoryView />)
    fireEvent.click(screen.getByRole('button', { name: /forget/i }))

    await waitFor(() =>
      expect(
        screen.getByText(/Could not forget the answer: it no longer exists/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/answer 1 is already gone/)).toBeTruthy()
  })

  it('reports a memory the server would not clear', async () => {
    handler = async (url, init) => {
      if (isMemoryRead(url) && (init?.method ?? 'GET') === 'GET') {
        return reply(useRunStore.getState().memory)
      }
      return refusal(500, 'Internal Server Error', 'the session rows are locked')
    }
    useRunStore.setState({
      memory: memory({ scope: 'shared', answers: [answer({ answer_id: 1 })] }),
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<MemoryView />)
    fireEvent.click(screen.getByRole('button', { name: /Clear Memory/i }))

    await waitFor(() =>
      expect(
        screen.getByText(/Could not clear episodic memory: the server failed to complete it/),
      ).toBeTruthy(),
    )
    // The answers are still stored, and the panel still shows them.
    expect(screen.getByText(/replace rightmost letter by successor/)).toBeTruthy()
    vi.mocked(window.confirm).mockRestore()
  })
})
