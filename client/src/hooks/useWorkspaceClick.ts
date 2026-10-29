// ---------------------------------------------------------------------------
// useWorkspaceClick -- "click anywhere in the Workspace window" (Metacat help.txt)
// ---------------------------------------------------------------------------
//
// "To interrupt execution, click Stop or click once anywhere in the Workspace window.
// Click Go or click on the Workspace again to resume execution."  And after Step,
// "single-stepping may be continued by clicking directly on the Workspace window".
// A click while the run is going stops it; the next click resumes it if the click is
// what stopped it, and otherwise takes one step.
// ---------------------------------------------------------------------------

import { useCallback, useRef } from 'react';
import type { MouseEvent } from 'react';
import { useRunStore } from '@/store/runStore';

const INTERACTIVE = 'button, a, input, select, textarea, label, [role="button"]';

export function useWorkspaceClick(): (e: MouseEvent) => void {
  const stoppedByClick = useRef(false);
  return useCallback((e: MouseEvent) => {
    if ((e.target as HTMLElement).closest?.(INTERACTIVE)) return;
    const { runId, status, isProcessing, run, stop, step } = useRunStore.getState();
    if (runId === null || isProcessing) return;
    if (status === 'running') {
      stoppedByClick.current = true;
      void stop();
    } else if (stoppedByClick.current) {
      stoppedByClick.current = false;
      void run();
    } else {
      void step();
    }
  }, []);
}
