// ---------------------------------------------------------------------------
// Petacat — WebSocket subscription hook for live state updates
// ---------------------------------------------------------------------------
//
// Connects to the server's WebSocket endpoint for a given run_id and pushes
// incoming snapshot data into the Zustand store. Automatically connects when
// runId is set and disconnects on cleanup or when runId changes.
//
// Built on top of the lower-level `connectWebSocket` from `@/api/ws`.
//
// The server pushes periodic JSON snapshots with fields:
//   run_id, status, codelet_count, temperature, temperature_clamped,
//   coderack_count, trace_event_count, snag_count, within_clamp_period
// ---------------------------------------------------------------------------

import { useEffect, useRef } from 'react';
import { connectWebSocket } from '@/api/ws';
import type { WsHandle } from '@/api/ws';
import { useRunStore } from '@/store/runStore';
import type { RunStatus } from '@/store/runStore';
import type { WsMessage } from '@/types';

/** Shape of the snapshot the server pushes over the WebSocket. */
interface WsSnapshot {
  run_id: number;
  status: string;
  codelet_count: number;
  temperature: number;
  temperature_clamped: boolean;
  coderack_count: number;
  trace_event_count: number;
  snag_count: number;
  within_clamp_period: boolean;
  error?: string;
}

/**
 * Connects to the run WebSocket and feeds snapshots into the Zustand store.
 *
 * Automatically connects when `runId` is non-null and disconnects when the
 * component unmounts or `runId` changes.
 *
 * Usage:
 *   useWebSocket(runId);
 */
export function useWebSocket(runId: number | null): void {
  const handleRef = useRef<WsHandle | null>(null);

  useEffect(() => {
    // Tear down any prior connection
    if (handleRef.current !== null) {
      handleRef.current.close();
      handleRef.current = null;
    }

    if (runId === null) return;

    const handle = connectWebSocket(runId, (msg: WsMessage) => {
      // The server sends snapshot objects directly; cast to our snapshot type
      const snapshot = msg as unknown as WsSnapshot;

      // Ignore error messages or snapshots for a different run
      if (snapshot.error || snapshot.run_id !== runId) return;

      // Push lightweight fields directly into the store
      const store = useRunStore.getState();
      const updates: Partial<{
        status: RunStatus;
        codeletCount: number;
        temperature: number;
      }> = {};

      if (snapshot.status) {
        updates.status = snapshot.status as RunStatus;
      }
      if (snapshot.codelet_count !== undefined) {
        updates.codeletCount = snapshot.codelet_count;
      }
      if (snapshot.temperature !== undefined) {
        updates.temperature = snapshot.temperature;
      }

      useRunStore.setState(updates);

      // When the status transitions away from "running", trigger a full
      // refresh so all panels have current data.
      if (snapshot.status !== 'running' && store.status === 'running') {
        void store.refreshAll();
      }
    });

    handleRef.current = handle;

    return () => {
      handle.close();
      handleRef.current = null;
    };
  }, [runId]);
}
