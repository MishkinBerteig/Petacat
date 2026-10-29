// ---------------------------------------------------------------------------
// momentStore -- the Trace event, answer or snag currently redisplayed
// ---------------------------------------------------------------------------
//
// Metacat's `display` methods (`trace.ss:405-1250`, `memory.ss:268-395`) redraw the
// Workspace for a past moment, show the moment's concept pattern in the Slipnet, blank
// (or pattern) the Coderack and show the moment's temperature.  Those are four windows,
// so what is on show lives here, where each of them can read it, rather than in the
// Trace panel that was clicked.  `null` is the live state.

import { create } from 'zustand';

import type { DisplayResult } from '@/api/client';
import type { DisplayedMoment } from '@/types';
import { useRunStore } from '@/store/runStore';

interface MomentState {
  /** What the windows redraw; null when the live state is showing or nothing was kept to draw. */
  displayed: DisplayedMoment | null;
  /**
   * Which moment is over the live Themespace, with or without a picture -- what the
   * Trace and Memory panels mark as selected.
   */
  onShow: { kind: DisplayedMoment['kind']; id: number } | null;
  /** Put the result of a `display` call on show, or clear it when it restored the live state. */
  show: (
    kind: DisplayedMoment['kind'],
    id: number,
    result: DisplayResult,
    eventNumber?: number | null,
  ) => void;
  clear: () => void;
}

export const useMomentStore = create<MomentState>((set) => ({
  displayed: null,
  onShow: null,
  show: (kind, id, result, eventNumber = null) => {
    if (result.displaying == null) {
      set({ displayed: null, onShow: null });
      return;
    }
    set({
      onShow: { kind, id },
      // No picture means none was kept (stored before pictures were): only the
      // Themespace moved, and the other windows stay live.
      displayed: result.picture ? { kind, id, eventNumber, picture: result.picture } : null,
    });
  },
  clear: () => set({ displayed: null, onShow: null }),
}));

// A different run has different moments: whatever was on show belongs to the last one.
let lastRunId: number | null = useRunStore.getState().runId;
useRunStore.subscribe((state) => {
  if (state.runId !== lastRunId) {
    lastRunId = state.runId;
    useMomentStore.getState().clear();
  }
});
