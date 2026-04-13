// ---------------------------------------------------------------------------
// Petacat — Zustand store for run state management
// ---------------------------------------------------------------------------

import { create } from 'zustand';

import type {
  RunParams,
  StepResult,
  WorkspaceState,
  SlipnetState,
  CoderackState,
  ThemespaceState,
  TraceEvent,
  MemoryState,
} from '@/types';

import {
  createRun as apiCreateRun,
  getRun as apiGetRun,
  stepRun as apiStepRun,
  runToCompletion as apiRunToCompletion,
  stopRun as apiStopRun,
  resetRun as apiResetRun,
  deleteRun as apiDeleteRun,
  getWorkspace,
  getSlipnet,
  getCoderack,
  getThemespace,
  getTrace,
  getTemperature,
  getCommentary,
  getMemory,
} from '@/api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type RunStatus =
  | 'idle'
  | 'initialized'
  | 'running'
  | 'paused'
  | 'completed'
  | 'halted'
  | 'answer_found';

export interface RunStore {
  // State
  runId: number | null;
  status: RunStatus;
  workspace: WorkspaceState | null;
  slipnet: SlipnetState | null;
  coderack: CoderackState | null;
  themespace: ThemespaceState | null;
  trace: TraceEvent[];
  memory: MemoryState;
  temperature: number;
  commentary: string;
  elizaMode: boolean;
  codeletCount: number;
  stepDelay: number; // ms between auto-steps (0 = max speed)
  liveUpdate: boolean; // refresh UI after every tick (default: true)
  lastCodeletType: string; // type of the most recently executed codelet
  /** Incremented on destructive ops — components watch this to re-fetch. */
  epoch: number;
  pollingInterval: number; // ms between state refreshes during run-to-answer (0 = continuous ~100ms)
  isProcessing: boolean; // true while run-to-answer is active

  // Problem form inputs (shared across ProblemInputPanel and RunControlsPanel)
  formInputs: {
    initial: string;
    modified: string;
    target: string;
    answer: string;
    seed: string;
  };

  // Actions
  createRun: (params: RunParams) => Promise<void>;
  step: (n?: number) => Promise<void>;
  run: (maxSteps?: number) => Promise<void>;
  runToAnswer: (maxSteps?: number) => Promise<void>;
  stop: () => Promise<void>;
  reset: () => Promise<void>;
  deleteRun: () => Promise<void>;
  fullReset: () => Promise<void>;

  // State refresh
  refreshAll: () => Promise<void>;
  refreshWorkspace: () => Promise<void>;
  refreshSlipnet: () => Promise<void>;
  refreshCoderack: () => Promise<void>;
  refreshThemespace: () => Promise<void>;
  refreshTrace: () => Promise<void>;
  refreshMemory: () => Promise<void>;
  refreshTemperature: () => Promise<void>;
  refreshCommentary: () => Promise<void>;

  // Settings
  setStepDelay: (ms: number) => void;
  setLiveUpdate: (enabled: boolean) => void;
  setElizaMode: (enabled: boolean) => void;
  setPollingInterval: (ms: number) => void;
  setFormInput: (field: keyof RunStore['formInputs'], value: string) => void;
  setFormInputs: (values: Partial<RunStore['formInputs']>) => void;
}

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

function freshMemory(): MemoryState {
  return { answers: [], snags: [] };
}
const INITIAL_MEMORY = freshMemory();

// Mutable flag outside of React state — controls the run loop without
// depending on store status (which gets overwritten by server responses).
let _stopRequested = false;

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useRunStore = create<RunStore>((set, get) => ({
  // ---- Default state -----------------------------------------------------
  runId: null,
  status: 'idle',
  workspace: null,
  slipnet: null,
  coderack: null,
  themespace: null,
  trace: [],
  memory: INITIAL_MEMORY,
  temperature: 100,
  commentary: '',
  elizaMode: true,
  codeletCount: 0,
  stepDelay: 0,
  liveUpdate: true,
  lastCodeletType: '',
  epoch: 0,
  pollingInterval: 1000,
  isProcessing: false,
  formInputs: {
    initial: '',
    modified: '',
    target: '',
    answer: '',
    seed: '',
  },

  // ---- Actions -----------------------------------------------------------

  createRun: async (params: RunParams): Promise<void> => {
    const info = await apiCreateRun(params);
    set({
      runId: info.run_id,
      status: info.status as RunStatus,
      codeletCount: info.codelet_count,
      temperature: info.temperature,
    });
    await get().refreshAll();
  },

  step: async (n?: number): Promise<void> => {
    const { runId, liveUpdate } = get();
    if (runId === null) return;

    const count = n ?? 1;

    if (liveUpdate && count > 1) {
      // Step one at a time, refreshing UI after each
      for (let i = 0; i < count; i++) {
        const state = get();
        if (state.status === 'idle' || state.runId === null) break;

        const results = await apiStepRun(runId, 1);
        if (results.length > 0) {
          set({
            codeletCount: results[0].codelet_count,
            lastCodeletType: results[0].codelet_type,
          });
        }
        await get().refreshAll();

        if (state.stepDelay > 0) {
          await new Promise(resolve => setTimeout(resolve, state.stepDelay));
        }
      }
      // Final status sync
      const info = await apiGetRun(runId);
      set({
        status: info.status as RunStatus,
        codeletCount: info.codelet_count,
        temperature: info.temperature,
      });
    } else {
      // Batch mode: step all at once, refresh once at the end
      const results = await apiStepRun(runId, count);
      if (results.length > 0) {
        const last = results[results.length - 1];
        set({
          codeletCount: last.codelet_count,
          lastCodeletType: last.codelet_type,
        });
      }
      const info = await apiGetRun(runId);
      set({
        status: info.status as RunStatus,
        codeletCount: info.codelet_count,
        temperature: info.temperature,
      });
      await get().refreshAll();
    }
  },

  run: async (maxSteps?: number): Promise<void> => {
    const { runId, liveUpdate } = get();
    if (runId === null) return;

    _stopRequested = false;
    set({ status: 'running' });

    if (liveUpdate) {
      // Step one codelet at a time, refreshing UI after each tick.
      // The loop is controlled by _stopRequested (set by stop()),
      // NOT by store.status (which gets overwritten by server responses).
      const limit = maxSteps ?? 100000;
      for (let i = 0; i < limit; i++) {
        if (_stopRequested || get().runId === null) break;

        let results: StepResult[];
        try {
          results = await apiStepRun(runId, 1);
        } catch (err) {
          console.error('Step failed:', err);
          set({ status: 'halted' });
          break;
        }

        if (results.length > 0) {
          const r = results[0];
          set({
            codeletCount: r.codelet_count,
            lastCodeletType: r.codelet_type,
          });

          // Stop if the engine found an answer
          if (r.answer_found) {
            set({ status: 'answer_found' });
            await get().refreshAll();
            break;
          }
        }

        try {
          await get().refreshAll();
        } catch {
          // Refresh failed — continue stepping
        }

        // Check for stop between refresh and next tick
        if (_stopRequested) break;

        const delay = get().stepDelay;
        if (delay > 0) {
          await new Promise(resolve => setTimeout(resolve, delay));
        }
      }

      // Loop ended — sync final status from server
      _stopRequested = false;
      try {
        const info = await apiGetRun(runId);
        set({
          status: (info.status === 'running' ? 'halted' : info.status) as RunStatus,
          codeletCount: info.codelet_count,
          temperature: info.temperature,
        });
      } catch {
        set({ status: 'halted' });
      }
    } else {
      // Batch mode: send all to server, update once at end
      try {
        const info = await apiRunToCompletion(runId, maxSteps ?? 0);
        set({
          status: info.status as RunStatus,
          codeletCount: info.codelet_count,
          temperature: info.temperature,
        });
        await get().refreshAll();
      } catch (err) {
        console.error('Run to completion failed:', err);
        set({ status: 'halted' });
        // Try to refresh whatever state we can
        try { await get().refreshAll(); } catch { /* ignore */ }
      }
    }
  },

  runToAnswer: async (maxSteps?: number): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;

    _stopRequested = false;
    set({ status: 'running', isProcessing: true });

    try {
      // Fire the backend /run request (returns when the run finishes).
      // We don't await it here — instead we poll the server-side status.
      const runPromise = apiRunToCompletion(runId, maxSteps ?? 0).catch((err) => {
        console.error('Run to completion failed:', err);
      });

      // Poll server status + refresh panels at the configured interval
      while (!_stopRequested) {
        const interval = get().pollingInterval;
        const delay = interval === 0 ? 100 : interval; // "continuous" = 100ms
        await new Promise((r) => setTimeout(r, delay));
        if (_stopRequested) break;

        try {
          // Check server-side run status — this is the authoritative source
          const info = await apiGetRun(runId);
          set({
            status: info.status as RunStatus,
            codeletCount: info.codelet_count,
            temperature: info.temperature,
          });

          if (info.status !== 'running') break;

          await get().refreshAll();
        } catch {
          // Refresh failed — continue polling
        }
      }

      // Let the /run request finish (may already be done)
      await runPromise;

      // Final refresh to get the definitive end state
      try {
        await get().refreshAll();
      } catch {
        /* ignore */
      }

      // Sync final status from server
      try {
        const info = await apiGetRun(runId);
        set({
          status: info.status as RunStatus,
          codeletCount: info.codelet_count,
          temperature: info.temperature,
        });
      } catch {
        /* ignore */
      }
    } finally {
      set({ isProcessing: false });
    }
  },

  stop: async (): Promise<void> => {
    // Signal the live-update loop / run-to-answer polling to stop
    _stopRequested = true;
    set({ status: 'paused', isProcessing: false });

    const { runId } = get();
    if (runId === null) return;

    try {
      await apiStopRun(runId);
      const info = await apiGetRun(runId);
      set({
        status: info.status as RunStatus,
        codeletCount: info.codelet_count,
        temperature: info.temperature,
      });
    } catch {
      // ignore — we already set paused
    }
  },

  reset: async (): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;

    const info = await apiResetRun(runId);
    // Clear all state first so panels visibly reset, then refresh
    set({
      runId: info.run_id,
      status: info.status as RunStatus,
      codeletCount: info.codelet_count,
      temperature: info.temperature,
      workspace: null,
      slipnet: null,
      coderack: null,
      themespace: null,
      trace: [],
      commentary: '',
    });
    await get().refreshAll();
  },

  deleteRun: async (): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;

    await apiDeleteRun(runId);
    set({
      runId: null,
      status: 'idle',
      workspace: null,
      slipnet: null,
      coderack: null,
      themespace: null,
      trace: [],
      memory: freshMemory(),
      temperature: 100,
      commentary: '',
      codeletCount: 0,
      lastCodeletType: '',
      epoch: get().epoch + 1,
    });
  },

  fullReset: async (): Promise<void> => {
    // Stop any running loop
    _stopRequested = true;

    // Delete ALL runs, snapshots, trace events, and episodic memory on server
    try {
      await fetch('/api/runs', { method: 'DELETE' });
      await fetch('/api/memory', { method: 'DELETE' });
    } catch {
      // ignore
    }

    // Clear all local state and bump epoch so components re-fetch
    set({
      runId: null,
      status: 'idle',
      workspace: null,
      slipnet: null,
      coderack: null,
      themespace: null,
      trace: [],
      memory: freshMemory(),
      temperature: 100,
      commentary: '',
      codeletCount: 0,
      lastCodeletType: '',
      epoch: get().epoch + 1,
    });
  },

  // ---- State refresh -----------------------------------------------------

  refreshAll: async (): Promise<void> => {
    const {
      refreshWorkspace,
      refreshSlipnet,
      refreshCoderack,
      refreshThemespace,
      refreshTrace,
      refreshMemory,
      refreshTemperature,
      refreshCommentary,
    } = get();

    await Promise.all([
      refreshWorkspace(),
      refreshSlipnet(),
      refreshCoderack(),
      refreshThemespace(),
      refreshTrace(),
      refreshMemory(),
      refreshTemperature(),
      refreshCommentary(),
    ]);
  },

  refreshWorkspace: async (): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;
    try {
      const workspace = await getWorkspace(runId);
      set({ workspace });
    } catch {
      // Run may have been deleted or not ready
    }
  },

  refreshSlipnet: async (): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;
    try {
      const slipnet = await getSlipnet(runId);
      set({ slipnet });
    } catch {
      // Run may have been deleted or not ready
    }
  },

  refreshCoderack: async (): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;
    try {
      const coderack = await getCoderack(runId);
      set({ coderack });
    } catch {
      // Run may have been deleted or not ready
    }
  },

  refreshThemespace: async (): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;
    try {
      const themespace = await getThemespace(runId);
      set({ themespace });
    } catch {
      // Run may have been deleted or not ready
    }
  },

  refreshTrace: async (): Promise<void> => {
    const { runId, trace: existing } = get();
    if (runId === null) return;
    try {
      // Only fetch events newer than what we already have.
      // Use offset = existing.length to get incremental updates.
      const offset = existing.length;
      const response = await getTrace(runId, { limit: 500, offset });
      const raw = Array.isArray(response)
        ? response
        : (response as unknown as { events: TraceEvent[] }).events;
      if (raw.length > 0) {
        set({ trace: [...existing, ...raw] });
      }
    } catch {
      // Run may have been deleted or not ready
    }
  },

  refreshMemory: async (): Promise<void> => {
    try {
      const memory = await getMemory();
      set({ memory });
    } catch {
      // Memory endpoint may not be available
    }
  },

  refreshTemperature: async (): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;
    try {
      const result = await getTemperature(runId);
      // Server returns { temperature: number }
      const temp = typeof result === 'number'
        ? result
        : (result as unknown as { temperature: number }).temperature;
      set({ temperature: temp });
    } catch {
      // Run may have been deleted or not ready
    }
  },

  refreshCommentary: async (): Promise<void> => {
    const { runId, elizaMode } = get();
    if (runId === null) return;
    try {
      const result = await getCommentary(runId, elizaMode);
      // Server returns { run_id, commentary, eliza_mode }
      const text = typeof result === 'string'
        ? result
        : (result as unknown as { commentary: string }).commentary;
      set({ commentary: text });
    } catch {
      // Run may have been deleted or not ready
    }
  },

  // ---- Settings ----------------------------------------------------------

  setStepDelay: (ms: number): void => {
    set({ stepDelay: ms });
  },

  setLiveUpdate: (enabled: boolean): void => {
    set({ liveUpdate: enabled });
  },

  setElizaMode: (enabled: boolean): void => {
    set({ elizaMode: enabled });
    get().refreshCommentary();
  },

  setPollingInterval: (ms: number): void => {
    set({ pollingInterval: ms === 0 ? 0 : Math.max(100, Math.min(10000, ms)) });
  },

  setFormInput: (field, value): void => {
    set({ formInputs: { ...get().formInputs, [field]: value } });
  },

  setFormInputs: (values): void => {
    set({ formInputs: { ...get().formInputs, ...values } });
  },
}));
