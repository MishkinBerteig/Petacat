// ---------------------------------------------------------------------------
// useKeyboardShortcuts -- Global keyboard shortcuts for Petacat
// ---------------------------------------------------------------------------
//
// Registers document-level keydown listeners for quick access to common
// actions.  Shortcuts are only active when focus is *not* inside an input,
// textarea, or contentEditable element (to avoid hijacking text entry).
//
// Shortcuts:
//   Space       - step one codelet
//   Enter       - run to completion
//   Escape      - stop the current run
//   Cmd+K / Ctrl+K - open search palette
// ---------------------------------------------------------------------------

import { useEffect } from 'react';
import { useRunStore } from '@/store/runStore';

interface Options {
  /** Callback to open the search palette. */
  onOpenSearch: () => void;
}

function isInputFocused(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if ((el as HTMLElement).isContentEditable) return true;
  return false;
}

export function useKeyboardShortcuts({ onOpenSearch }: Options): void {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Cmd+K / Ctrl+K should always work, even inside inputs
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        onOpenSearch();
        return;
      }

      // The remaining shortcuts should not fire when typing in an input
      if (isInputFocused()) return;

      const { runId, status, step, run, stop } = useRunStore.getState();
      const hasRun = runId !== null;
      const isRunning = status === 'running';

      switch (e.key) {
        case ' ': // Space -> step
          if (hasRun && !isRunning) {
            e.preventDefault();
            void step();
          }
          break;

        case 'Enter': // Enter -> run
          if (hasRun && !isRunning) {
            e.preventDefault();
            void run();
          }
          break;

        case 'Escape': // Escape -> stop
          if (isRunning) {
            e.preventDefault();
            void stop();
          }
          break;
      }
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onOpenSearch]);
}
