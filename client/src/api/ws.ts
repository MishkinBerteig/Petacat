// ---------------------------------------------------------------------------
// Petacat — WebSocket client for real-time run updates
// ---------------------------------------------------------------------------

import type { WsMessage } from '../types';

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
  onMessage: (msg: WsMessage) => void,
): WsHandle {
  let ws: WebSocket | null = null;
  let closed = false;
  let reconnectDelay = RECONNECT_DELAY_MS;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  function buildUrl(): string {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${window.location.host}/api/runs/${runId}/ws`;
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
        const msg: WsMessage = JSON.parse(event.data);
        onMessage(msg);
      } catch {
        // Non-JSON payload — forward as a generic message.
        onMessage({ type: 'raw', data: event.data });
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
