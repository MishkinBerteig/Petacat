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
import type { WsSnapshot } from '@/types';

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

    const handle = connectWebSocket(runId, (snapshot: WsSnapshot) => {
      // A snapshot for another run, or one naming a run the server cannot find, says
      // nothing about the run on screen.
      if (snapshot.run_id !== runId || snapshot.status === 'not_found') return;

      // Push lightweight fields directly into the store
      const store = useRunStore.getState();
      const updates: Partial<{
        status: RunStatus;
        codeletCount: number;
        temperature: number;
        temperatureClamped: boolean;
      }> = {};

      // A run being stepped is running while each batch executes and paused between
      // batches. The client-driven loop owns that alternation and reports the run as
      // running for its duration, so the snapshot carries the status forward except
      // for the one transition the loop is already tracking.
      const steppingHere = store.status === 'running' && snapshot.status === 'paused';
      if (snapshot.status && !steppingHere) {
        updates.status = snapshot.status as RunStatus;
      }
      if (snapshot.codelet_count !== undefined) {
        updates.codeletCount = snapshot.codelet_count;
      }
      if (snapshot.temperature !== undefined) {
        updates.temperature = snapshot.temperature;
      }
      // Clamping is the engine's, and the snapshot is the fastest account of it:
      // a snag response clamps the temperature without the client asking.
      if (snapshot.temperature_clamped !== undefined) {
        updates.temperatureClamped = snapshot.temperature_clamped;
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
