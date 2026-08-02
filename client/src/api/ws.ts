// ---------------------------------------------------------------------------
// Petacat — WebSocket client for real-time run updates
// ---------------------------------------------------------------------------

import type { WsSnapshot } from '../types';

/**
 * The path prefix every run socket lives under.
 *
 * It is the prefix `client/vite.config.ts` proxies with `ws: true`, which is what
 * carries the connection to the API through the dev server.
 */
export const WS_PATH_PREFIX = '/ws';

/** Default delay before attempting reconnection (milliseconds). */
const RECONNECT_DELAY_MS = 2000;

/** Maximum reconnection delay with exponential back-off (milliseconds). */
const MAX_RECONNECT_DELAY_MS = 30000;

/** Back-off multiplier applied after each failed reconnection attempt. */
const BACKOFF_FACTOR = 1.5;

export interface WsHandle {
  /** Close the WebSocket and stop any reconnection attempts. */
  close: () => void;
}

/**
 * Open a WebSocket connection for the given run and invoke `onMessage` for
 * every server-sent message.
 *
 * The connection automatically reconnects with exponential back-off when
 * the socket is closed unexpectedly (i.e. the caller has not explicitly
 * invoked `close()`).
 *
 * @param runId     The run to subscribe to.
 * @param onMessage Callback invoked with every parsed message from the server.
 * @returns A handle whose `close()` method tears down the connection.
 */
export function connectWebSocket(
  runId: number,
  onMessage: (msg: WsSnapshot) => void,
): WsHandle {
  let ws: WebSocket | null = null;
  let closed = false;
  let reconnectDelay = RECONNECT_DELAY_MS;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  /**
   * The socket URL for this run: the page's own origin, the `ws:`/`wss:` scheme
   * matching the page protocol, and the path `server/api/ws.py` declares —
   * `/ws/runs/{run_id}`.
   *
   * `client/vite.config.ts` proxies the `/ws` prefix to the API with WebSocket
   * upgrade enabled, so the same URL reaches the backend from the dev server and
   * from the production build alike. `ws.test.ts` pins it to the server route.
   */
  function buildUrl(): string {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${window.location.host}${WS_PATH_PREFIX}/runs/${runId}`;
  }

  function connect(): void {
    if (closed) return;

    ws = new WebSocket(buildUrl());

    ws.onopen = () => {
      // Reset back-off on successful connection.
      reconnectDelay = RECONNECT_DELAY_MS;
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const msg: WsSnapshot = JSON.parse(event.data);
        onMessage(msg);
      } catch {
        // The server sends JSON snapshots; anything else is not one to act on.
        console.warn('Ignoring non-JSON WebSocket frame');
      }
    };

    ws.onclose = () => {
      ws = null;
      if (!closed) {
        scheduleReconnect();
      }
    };

    ws.onerror = () => {
      // The browser fires `onerror` before `onclose`; actual reconnection
      // is handled in `onclose`.
      ws?.close();
    };
  }

  function scheduleReconnect(): void {
    if (closed) return;

    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, reconnectDelay);

    // Exponential back-off capped at the maximum.
    reconnectDelay = Math.min(
      reconnectDelay * BACKOFF_FACTOR,
      MAX_RECONNECT_DELAY_MS,
    );
  }

  // Kick off the initial connection.
  connect();

  return {
    close() {
      closed = true;

      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }

      if (ws) {
        ws.onclose = null; // Prevent reconnection from the close handler.
        ws.close();
        ws = null;
      }
    },
  };
}
