// ---------------------------------------------------------------------------
// ws.test.ts — the URL the client opens is the route the server serves
// ---------------------------------------------------------------------------
//
// The two ends of this connection are declared in two languages in two trees:
// FastAPI names the path in `server/api/ws.py`, and `connectWebSocket` builds it
// in TypeScript. A mismatch produces a 404 handshake and a reconnect loop that
// retries forever, and nothing else on the page changes — so the agreement is
// asserted here against the declarations themselves, read as source. A rename on
// either side fails a test.
//
// Both sources arrive through Vite's `?raw` import, which hands the file over as
// a string at transform time.
// ---------------------------------------------------------------------------

import { afterEach, describe, expect, it, vi } from 'vitest'

import { connectWebSocket, WS_PATH_PREFIX } from './ws'
import serverWsSource from '../../../server/api/ws.py?raw'
import viteConfigSource from '../../vite.config.ts?raw'

/**
 * The path template `server/api/ws.py` declares, e.g. `/ws/runs/{run_id}`.
 *
 * Read out of the Python source rather than restated here: a copy would agree
 * with the route on the day it was written and never again.
 */
function serverRouteTemplate(): string {
  const matches = [...serverWsSource.matchAll(/@router\.websocket\(\s*["']([^"']+)["']/g)]
  expect(matches, 'server/api/ws.py declares exactly one websocket route').toHaveLength(1)
  return matches[0][1]
}

/** The path FastAPI serves for one concrete run. */
function serverPathForRun(runId: number): string {
  return serverRouteTemplate().replace('{run_id}', String(runId))
}

/**
 * A stand-in for the browser's `WebSocket` that records the URL it is handed and
 * stays quiet — the constructor is the whole subject of these tests.
 */
class RecordingWebSocket {
  static urls: string[] = []

  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(public url: string) {
    RecordingWebSocket.urls.push(url)
  }

  close(): void {}
}

/** Open a connection and return the URL the client asked for. */
function urlOpenedFor(runId: number): URL {
  RecordingWebSocket.urls = []
  vi.stubGlobal('WebSocket', RecordingWebSocket)

  const handle = connectWebSocket(runId, () => {})
  handle.close()

  expect(RecordingWebSocket.urls).toHaveLength(1)
  return new URL(RecordingWebSocket.urls[0])
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('connectWebSocket URL', () => {
  it('opens the path the server declares, with the run id filled in', () => {
    expect(urlOpenedFor(42).pathname).toBe(serverPathForRun(42))
  })

  it('agrees with the server route for any run id', () => {
    for (const runId of [1, 7, 12345, -3]) {
      expect(urlOpenedFor(runId).pathname).toBe(serverPathForRun(runId))
    }
  })

  it('uses the page origin and a ws scheme', () => {
    const url = urlOpenedFor(42)
    expect(url.protocol).toBe('ws:')
    expect(url.host).toBe(window.location.host)
  })
})

describe('Vite dev proxy', () => {
  /**
   * The body of the `WS_PATH_PREFIX` entry in `client/vite.config.ts`.
   *
   * Template literals are blanked first, so that the `${...}` inside the proxy
   * target leaves the entry's own braces as the only ones in play.
   */
  function proxyEntryBody(): string {
    const source = viteConfigSource.replace(/`[^`]*`/g, "''")
    const entry = source.match(
      new RegExp(`['"]${WS_PATH_PREFIX}['"]\\s*:\\s*\\{([^}]*)\\}`),
    )
    expect(entry, `vite.config.ts proxies the "${WS_PATH_PREFIX}" prefix`).not.toBeNull()
    return entry![1]
  }

  it('carries the socket path to the API as a WebSocket', () => {
    // `WS_PATH_PREFIX` is a path on the dev server; this entry is what turns it
    // into a connection to the backend, and `ws: true` is what makes the dev
    // server honour the upgrade rather than proxying plain HTTP.
    expect(urlOpenedFor(42).pathname.startsWith(WS_PATH_PREFIX)).toBe(true)

    const body = proxyEntryBody()
    expect(body).toMatch(/\bws\s*:\s*true\b/)
    expect(body).toMatch(/\btarget\s*:/)
  })
})
