// ---------------------------------------------------------------------------
// Petacat -- the Admin panel's operations report what became of them
// ---------------------------------------------------------------------------
//
// Every button here is irreversible, and one of them draws a boundary the rest of
// the program is organised around: clearing Episodic Memory is what ends a Training
// Session, because episodic memory is the only thing that crosses a Run boundary.
//
// A clear that did not land leaves the session open and its answers stored, and the
// panel looks exactly as it does after a clear that did. So the outcome is stated:
// cleared, or the reason it was not.
//
// The panel's own text comes from the help SSOT over HTTP, so a section whose topic
// failed to load names that topic and the reason, and the sections beside it keep
// their own content.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { AdminPanel } from './AdminPanel'
import { useRunStore } from '@/store/runStore'

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

/** One `admin_*` help topic, in the shape `GET /docs/components/{key}` serves it. */
function topic(key: string) {
  return {
    name: key,
    topic_key: key,
    short_desc: `what ${key} does`,
    description: '',
    metadata: { kind: 'admin_action', user_description: [`bullet for ${key}`] },
  }
}

type Handler = (url: string, init?: RequestInit) => Promise<unknown>

let handler: Handler

const ORIGINAL = useRunStore.getState()

beforeEach(() => {
  useRunStore.setState({ ...ORIGINAL }, true)
  handler = async (url) => {
    const match = /\/api\/docs\/components\/(.+)$/.exec(url)
    if (match) return reply(topic(match[1]))
    return refusal(404, 'Not Found', `nothing serves ${url}`)
  }
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => handler(url, init)))
})

afterEach(() => {
  vi.unstubAllGlobals()
  useRunStore.setState({ ...ORIGINAL }, true)
})

describe('AdminPanel — clearing Episodic Memory', () => {
  it('reports the reason when the clear does not land', async () => {
    handler = async (url, init) => {
      const match = /\/api\/docs\/components\/(.+)$/.exec(url)
      if (match) return reply(topic(match[1]))
      if (url.endsWith('/api/memory') && init?.method === 'DELETE') {
        return refusal(500, 'Internal Server Error', 'the session rows are locked')
      }
      return refusal(404, 'Not Found', url)
    }
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<AdminPanel />)
    await screen.findByRole('button', { name: /Clear Episodic Memory/i })
    fireEvent.click(screen.getByRole('button', { name: /Clear Episodic Memory/i }))

    await waitFor(() =>
      expect(
        screen.getByText(/Could not clear episodic memory: the server failed to complete it/),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/the session rows are locked/)).toBeTruthy()
    // The session is still open, so nothing downstream was told it closed.
    expect(useRunStore.getState().epoch).toBe(ORIGINAL.epoch)

    vi.mocked(window.confirm).mockRestore()
  })

  it('says the session closed when the clear did land', async () => {
    handler = async (url, init) => {
      const match = /\/api\/docs\/components\/(.+)$/.exec(url)
      if (match) return reply(topic(match[1]))
      if (url.endsWith('/api/memory') && init?.method === 'DELETE') {
        return reply(null, 204, 'No Content')
      }
      return reply({ answers: [], snags: [] })
    }
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<AdminPanel />)
    await screen.findByRole('button', { name: /Clear Episodic Memory/i })
    fireEvent.click(screen.getByRole('button', { name: /Clear Episodic Memory/i }))

    await waitFor(() =>
      expect(screen.getByText(/this Training Session is closed/)).toBeTruthy(),
    )
    expect(useRunStore.getState().epoch).toBe(ORIGINAL.epoch + 1)

    vi.mocked(window.confirm).mockRestore()
  })

  it('asks the server for nothing when the confirmation is declined', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    render(<AdminPanel />)
    await screen.findByRole('button', { name: /Clear Episodic Memory/i })
    fireEvent.click(screen.getByRole('button', { name: /Clear Episodic Memory/i }))

    await waitFor(() =>
      expect(
        vi.mocked(fetch).mock.calls.every(([url]) => String(url).includes('/docs/components/')),
      ).toBe(true),
    )

    vi.mocked(window.confirm).mockRestore()
  })
})

describe('AdminPanel — help text the server would not serve', () => {
  it('names the topic and the reason in place of the section', async () => {
    handler = async (url) => {
      if (url.endsWith('/api/docs/components/admin_clear_memory')) {
        return refusal(404, 'Not Found', 'no help topic admin_clear_memory')
      }
      const match = /\/api\/docs\/components\/(.+)$/.exec(url)
      if (match) return reply(topic(match[1]))
      return refusal(404, 'Not Found', url)
    }

    render(<AdminPanel />)

    await waitFor(() =>
      expect(
        screen.getByText(
          /Could not load the help for admin_clear_memory: it no longer exists/,
        ),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/no help topic admin_clear_memory/)).toBeTruthy()
    // The other sections are unaffected: each topic is fetched on its own.
    expect(screen.getByText('bullet for admin_full_reset')).toBeTruthy()
  })

  it('reports a refused regeneration', async () => {
    handler = async (url, init) => {
      const match = /\/api\/docs\/components\/(.+)$/.exec(url)
      if (match) return reply(topic(match[1]))
      if (url.endsWith('/api/admin/help/regenerate') && init?.method === 'POST') {
        return refusal(500, 'Internal Server Error', 'HELP.md is not writable')
      }
      return refusal(404, 'Not Found', url)
    }

    render(<AdminPanel />)
    const button = await screen.findByRole('button', {
      name: /Regenerate Help Documentation/i,
    })
    fireEvent.click(button)

    await waitFor(() =>
      expect(
        screen.getByText(
          /Could not regenerate the help documentation: the server failed to complete it/,
        ),
      ).toBeTruthy(),
    )
    expect(screen.getByText(/HELP.md is not writable/)).toBeTruthy()
  })
})
