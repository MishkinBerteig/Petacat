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

import { restoreThemespace, type DisplayResult } from '@/api/client';
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

// What is on show ends when anything makes the live state matter again. Metacat redraws the
// Workspace, which puts every window back (`restore-current-state`, `workspace-graphics.ss:80-88`),
// before it moves the run (`go`, `run.ss:132`; `resume-current-problem`, `gui.ss:779`) and
// before it opens the Clamp Themes dialog (`theme-edit-mode-on`, `gui.ss:857`).
let lastRunId: number | null = useRunStore.getState().runId;
let lastDriveCount = useRunStore.getState().driveCount;
let lastThemeEdit = useRunStore.getState().themeEdit;
useRunStore.subscribe((state) => {
  const moment = useMomentStore.getState();
  const opened = lastThemeEdit === null && state.themeEdit !== null;
  const closed = lastThemeEdit !== null && state.themeEdit === null;
  const wasShowing = moment.onShow !== null;
  const runChanged = state.runId !== lastRunId;
  const driven = state.driveCount !== lastDriveCount;
  const runId = lastRunId;
  lastRunId = state.runId;
  lastDriveCount = state.driveCount;
  lastThemeEdit = state.themeEdit;

  // A different run has different moments: whatever was on show belongs to the last one.
  if (runChanged || driven || opened || closed) moment.clear();
  // The server restores before a Step or a Run, and before a clamp is applied, by itself. The
  // dialog is different: it opens on the Themespace as it stands, so that has to be the live
  // one before anyone selects a theme from it.
  if (opened && wasShowing && !runChanged && runId !== null) {
    void restoreThemespace(runId)
      .then(() => useRunStore.getState().refreshThemespace())
      .catch(() => {
        // The next refresh reads the Themespace again.
      });
  }
});
