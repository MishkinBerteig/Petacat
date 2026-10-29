// ---------------------------------------------------------------------------
// displayStore -- which panels are shown, and which graphics are switched on
// ---------------------------------------------------------------------------
//
// Metacat's Windows menu shows or hides each window and has "Show all windows" and
// "Hide all windows" (`gui.ss:1091-1162`); its Options menu has "Slipnet graphics" and
// "Coderack graphics" switches that blank those two windows and stop drawing them,
// which is what makes a long run faster (`gui.ss:638-651`).  This is the display half
// of both.  It is a per-viewer preference, so it lives in localStorage (guarded: the
// accessor can throw or come back empty) and never reaches the server.
// ---------------------------------------------------------------------------

import { create } from 'zustand';

/** Every panel the Windows menu can show or hide, in menu order. */
export const WINDOW_PANELS = [
  { key: 'workspace', label: 'Workspace' },
  { key: 'slipnet', label: 'Slipnet' },
  { key: 'coderack', label: 'Coderack' },
  { key: 'temperature', label: 'Temperature' },
  { key: 'themespace', label: 'Themespace' },
  { key: 'trace', label: 'Temporal Trace' },
  { key: 'memory', label: 'Episodic Memory' },
  { key: 'commentary', label: 'Commentary' },
  { key: 'verbose', label: 'Verbose' },
  { key: 'run_history', label: 'Run History' },
  { key: 'eeg', label: 'EEG' },
] as const;

export type PanelKey = (typeof WINDOW_PANELS)[number]['key'];

const STORAGE_KEY = 'petacat.display.v1';

/**
 * Panels that start hidden: Metacat's Verbose output goes to the Interaction window, which
 * the Windows menu does not list, and its narration is for debugging.  A preference saved
 * before a panel existed (`seen`) gets the panel's default rather than "shown".
 */
const DEFAULT_HIDDEN: PanelKey[] = ['verbose'];

interface Persisted {
  hidden: PanelKey[];
  slipnetGraphics: boolean;
  coderackGraphics: boolean;
}

interface Stored extends Persisted {
  seen?: string[];
}

function load(): Persisted {
  const fallback: Persisted = {
    hidden: [...DEFAULT_HIDDEN],
    slipnetGraphics: true,
    coderackGraphics: true,
  };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const p = JSON.parse(raw) as Partial<Stored>;
    const known = new Set<string>(WINDOW_PANELS.map((w) => w.key));
    const seen = new Set<string>(Array.isArray(p.seen) ? p.seen : []);
    const hidden = Array.isArray(p.hidden)
      ? (p.hidden.filter((k) => known.has(k)) as PanelKey[])
      : [];
    for (const k of DEFAULT_HIDDEN) {
      if (!seen.has(k) && !hidden.includes(k)) hidden.push(k);
    }
    return {
      hidden,
      slipnetGraphics: p.slipnetGraphics !== false,
      coderackGraphics: p.coderackGraphics !== false,
    };
  } catch {
    return fallback;
  }
}

function save(p: Persisted): void {
  try {
    const stored: Stored = { ...p, seen: WINDOW_PANELS.map((w) => w.key) };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
  } catch {
    // Private window or blocked storage: the choice holds for this page only.
  }
}

interface DisplayState extends Persisted {
  togglePanel: (key: PanelKey) => void;
  showAll: () => void;
  hideAll: () => void;
  setSlipnetGraphics: (on: boolean) => void;
  setCoderackGraphics: (on: boolean) => void;
}

export const useDisplayStore = create<DisplayState>((set, get) => {
  const persist = () => {
    const { hidden, slipnetGraphics, coderackGraphics } = get();
    save({ hidden, slipnetGraphics, coderackGraphics });
  };
  return {
    ...load(),
    togglePanel: (key) => {
      const hidden = get().hidden;
      set({ hidden: hidden.includes(key) ? hidden.filter((k) => k !== key) : [...hidden, key] });
      persist();
    },
    showAll: () => {
      set({ hidden: [] });
      persist();
    },
    hideAll: () => {
      set({ hidden: WINDOW_PANELS.map((w) => w.key) });
      persist();
    },
    setSlipnetGraphics: (on) => {
      set({ slipnetGraphics: on });
      persist();
    },
    setCoderackGraphics: (on) => {
      set({ coderackGraphics: on });
      persist();
    },
  };
});
