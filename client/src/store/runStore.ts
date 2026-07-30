// ---------------------------------------------------------------------------
// Petacat — Zustand store for run state management
// ---------------------------------------------------------------------------

import { create } from 'zustand';

import type {
  PersistenceMode,
  RunParameterValue,
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
  getRunMemory,
  setSpreadingThreshold as apiSetSpreadingThreshold,
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
  | 'answer_found'
  /** A jootser gave up: looping with no untried alternatives left (§4.5.2). */
  | 'gave_up';

export interface RunStore {
  // State
  runId: number | null;
  /**
   * The problem the loaded run was actually created with. The form inputs can
   * drift away from this (the user edits a string, or picks a demo), and when
   * they do the run buttons have to start a *new* run rather than carry on
   * with the old one.
   */
  runParams: RunParams | null;
  /**
   * The persistence mode the *loaded* run was created with, as the server reports
   * it. Distinct from `persistenceMode` below, which is the choice for the next
   * run: mode is fixed at creation, so the two differ exactly when running would
   * start a new run rather than continue this one.
   *
   * `null` while no run is loaded, or when a run was loaded from somewhere that
   * did not report it.
   */
  runMode: string | null;
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
  /**
   * Spreading activation threshold, 0-100 (100 = the original's behaviour).
   *
   * A Run Controls setting, so it belongs to the session rather than to one run:
   * it is re-applied to each new run as it is created. It used to live only on
   * the server's in-memory runner, which meant every new run silently reverted
   * to the default and Reset discarded it — so a chosen value usually never
   * reached the run that actually executed.
   */
  spreadingThreshold: number;
  /**
   * What the *next* run will write down: `fast`, `normal` or `audit`.
   *
   * Deliberately not persisted across reloads, unlike `spreadingThreshold`. The
   * threshold is remembered because it changes what a run does and a forgotten
   * value would silently change results; this changes only what is kept, and the
   * failure modes of a remembered value are the bad ones — coming back the next
   * day to find that a session's worth of work recorded nothing (fast), or ran at
   * 1.8x cost for a record nobody wanted (audit). It starts at `normal` every
   * time, which is the mode whose promise is hardest to be disappointed by.
   */
  persistenceMode: PersistenceMode;
  /**
   * Per-run overrides for the engine's fixed parameters, for the *next* run.
   *
   * Only what differs from the catalogue's default is held here, so an empty object
   * means "whatever the server's defaults are" rather than a frozen snapshot of them.
   * That matters because the defaults are editable in the Admin panel: a client that
   * sent all twenty-five values every time would silently pin a run to the defaults
   * that happened to be loaded when the page opened.
   */
  parameterOverrides: Record<string, RunParameterValue>;
  /**
   * The overrides the *loaded* run was created with, as the client sent them.
   *
   * The same relationship as `runMode` to `persistenceMode`: a Run's parameters are
   * fixed before its first codelet, so the two differ exactly when pressing Run has
   * to start a new run rather than continue this one.
   */
  runParameterOverrides: Record<string, RunParameterValue>;
  /**
   * Worker threads for the *next* run. 1 is the serial loop and the reference mode;
   * above 1 the run executes free-running and a seed no longer reproduces it.
   */
  workers: number;
  /** Worker count the loaded run was created with — fixed, like the mode. */
  runWorkers: number;
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
  setSpreadingThreshold: (value: number) => Promise<void>;
  setPersistenceMode: (mode: PersistenceMode) => void;
  setParameterOverride: (name: string, value: RunParameterValue) => void;
  clearParameterOverride: (name: string) => void;
  clearAllParameterOverrides: () => void;
  setWorkers: (workers: number) => void;
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

/**
 * The spreading threshold is a fundamental parameter -- it changes what a run
 * does -- so the chosen value outlives the page, not just the run. Each run also
 * records the value it used in the database; this is only the default handed to
 * the *next* run.
 */
const THRESHOLD_KEY = 'petacat.spreadingThreshold';

function loadSpreadingThreshold(): number {
  try {
    const raw = window.localStorage.getItem(THRESHOLD_KEY);
    if (raw === null) return 100;
    const value = Number.parseInt(raw, 10);
    return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 100;
  } catch {
    return 100; // storage unavailable (private mode, SSR)
  }
}

function saveSpreadingThreshold(value: number): void {
  try {
    window.localStorage.setItem(THRESHOLD_KEY, String(value));
  } catch {
    // Non-fatal: the setting just will not survive the reload.
  }
}

// Mutable flag outside of React state — controls the run loop without
// depending on store status (which gets overwritten by server responses).
let _stopRequested = false;

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useRunStore = create<RunStore>((set, get) => ({
  // ---- Default state -----------------------------------------------------
  runId: null,
  runParams: null,
  runMode: null,
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
  spreadingThreshold: loadSpreadingThreshold(),
  persistenceMode: 'normal',
  parameterOverrides: {},
  runParameterOverrides: {},
  workers: 1,
  runWorkers: 1,
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
    // All four of these are sent with the create rather than applied afterwards. The
    // threshold has to be, so the engine is initialised with it; the mode has to
    // be, because it selects the sink and a Run's mode cannot change once it has
    // begun writing (or not writing); the parameters and the worker count have to be
    // for the same reason as the mode — they are read before the first codelet.
    const overrides = get().parameterOverrides;
    // Audit refuses anything above 1 — its forward log would not describe the order
    // things actually happened in — so the request is built with what Audit will
    // accept rather than with what the selector last held. The control shows 1 and
    // says why, so this agrees with what is on screen; sending the other number
    // instead would turn a mode change into a 400 the reader did not ask for.
    const workers = get().persistenceMode === 'audit' ? 1 : get().workers;
    const info = await apiCreateRun({
      spreading_threshold: get().spreadingThreshold,
      mode: get().persistenceMode,
      workers,
      // Omitted entirely when empty, so a run with no overrides sends the same
      // request it always did.
      ...(Object.keys(overrides).length > 0 ? { parameters: overrides } : {}),
      ...params,
    });
    // Blank the panels as well as swapping the id. Without this the previous
    // problem's workspace, trace and commentary stay on screen until every
    // refresh lands — and stay forever if one of them fails.
    set({
      runId: info.run_id,
      runParams: params,
      runMode: info.mode ?? get().persistenceMode,
      // Recorded as sent, not as echoed: the response carries neither, and these are
      // what decide whether the next press of Run continues this run or starts one.
      runParameterOverrides: { ...overrides },
      runWorkers: workers,
      status: info.status as RunStatus,
      codeletCount: info.codelet_count,
      temperature: info.temperature,
      workspace: null,
      slipnet: null,
      coderack: null,
      themespace: null,
      trace: [],
      commentary: '',
      lastCodeletType: '',
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

          // Or if it gave up — a terminal outcome in its own right, not a stall
          if (r.gave_up) {
            set({ status: 'gave_up' });
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
      runParams: null,
      runMode: null,
      runParameterOverrides: {},
      runWorkers: 1,
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
      runParams: null,
      runMode: null,
      runParameterOverrides: {},
      runWorkers: 1,
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
    // Asked *of the run* whenever there is one, because which memory a run thinks
    // against is a property of the run: a Fast Run gets an ephemeral one of its own
    // and contributes nothing to the shared one. Reading the shared memory regardless
    // showed a Fast Run answers it could not be reminded of, and went on showing them
    // after it had found one that never appeared.
    const { runId } = get();
    try {
      const memory = runId === null ? await getMemory() : await getRunMemory(runId);
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

  setSpreadingThreshold: async (value: number): Promise<void> => {
    const clamped = Math.max(0, Math.min(100, Math.round(value)));
    set({ spreadingThreshold: clamped });
    saveSpreadingThreshold(clamped);
    // Also push it to the run on screen, so a mid-run change takes effect now.
    const { runId } = get();
    if (runId !== null) {
      try {
        await apiSetSpreadingThreshold(runId, clamped);
      } catch {
        // Run may have gone; the stored value still applies to the next one.
      }
    }
  },

  setPersistenceMode: (mode: PersistenceMode): void => {
    // Nothing is pushed to the server: a Run's mode is fixed at creation, so this
    // can only ever apply to the *next* run. Trying to change a running run's mode
    // would be a request the backend is right to have no endpoint for.
    set({ persistenceMode: mode });
  },

  // Nothing below is pushed to the server either, and for the same reason: every one
  // of these is read by the engine before the first codelet, so the only run they can
  // apply to is the next one.

  setParameterOverride: (name, value): void => {
    set({ parameterOverrides: { ...get().parameterOverrides, [name]: value } });
  },

  clearParameterOverride: (name): void => {
    // Removed rather than set back to the default's current value. The two look the
    // same today and differ the moment the default is edited in the Admin panel: a
    // parameter left pinned to yesterday's default is an override nobody chose.
    const { [name]: _removed, ...rest } = get().parameterOverrides;
    set({ parameterOverrides: rest });
  },

  clearAllParameterOverrides: (): void => {
    set({ parameterOverrides: {} });
  },

  setWorkers: (workers): void => {
    set({ workers: Math.max(1, Math.min(64, Math.round(workers))) });
  },

  setFormInput: (field, value): void => {
    set({ formInputs: { ...get().formInputs, [field]: value } });
  },

  setFormInputs: (values): void => {
    set({ formInputs: { ...get().formInputs, ...values } });
  },
}));
