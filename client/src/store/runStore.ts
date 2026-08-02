// ---------------------------------------------------------------------------
// Petacat — Zustand store for run state management
// ---------------------------------------------------------------------------

import { create } from 'zustand';

import type {
  PersistenceMode,
  RunInfo,
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
  deleteAllRuns as apiDeleteAllRuns,
  clearMemory as apiClearMemory,
  describeApiError,
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
  /**
   * The engine is holding the temperature at its clamp value.
   *
   * Server state, read from `GET /runs/{id}/temperature` and refreshed by each
   * WebSocket snapshot, so the gauge's clamped indicator reports the engine and
   * outlives any one mounting of the gauge.
   */
  temperatureClamped: boolean;
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
   * Spreading activation threshold of the run on screen, 0-100 (100 = the
   * original's behaviour).
   *
   * A property of the run: it decides which Slipnet nodes spread activation, so the
   * value shown is the one the loaded run is executing with. Loading a run adopts
   * that run's value, and moving the slider applies the new value to that same run.
   * With no run loaded it shows `defaultSpreadingThreshold`, which is what the next
   * run will be created with.
   */
  spreadingThreshold: number;
  /**
   * The threshold a *newly created* run is given, remembered across page loads.
   *
   * This is the standing preference: it travels with each create request, and the
   * slider records the chosen value here and in local storage.
   */
  defaultSpreadingThreshold: number;
  /**
   * What the *next* run will write down: `fast`, `normal` or `audit`.
   *
   * Deliberately not persisted across reloads, unlike
   * `defaultSpreadingThreshold`. The
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
  /**
   * The one error channel: why the last thing the user asked for did not happen.
   *
   * One actionable sentence from `describeApiError`, rendered once in the header.
   * It carries failures of *user-initiated* actions — create, step, run, stop,
   * delete, clear, threshold — because each of those is a request somebody made and
   * is entitled to an answer about. Polling and refresh failures are recovered by
   * the tick that follows them, and keep to the console.
   *
   * Every user-initiated action clears the channel as it begins, so the message on
   * screen belongs to the most recent thing asked for.
   */
  lastError: string | null;

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
  /**
   * Point the store at an existing run, taking on the values that belong to it.
   *
   * Every route into a run that already exists goes through here — a Run History
   * row, a deep link — so the panels describe the run on screen: its mode, its
   * position, and the spreading threshold it is executing with.
   */
  adoptRun: (info: RunInfo) => void;
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

  // The error channel
  /** Put a message on the channel — for user-initiated work outside the store. */
  setLastError: (message: string) => void;
  /** Dismiss whatever is on the channel. */
  clearLastError: () => void;
}

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

function freshMemory(): MemoryState {
  return { answers: [], snags: [] };
}
const INITIAL_MEMORY = freshMemory();

/**
 * Where the standing preference for the spreading threshold is kept.
 *
 * Storage holds one thing: the value a *newly created* run is given, so a chosen
 * preference survives a reload. The value a run is executing with comes from the
 * run itself, and each run records it in the database.
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

/** Read once at load, so the display and the default start from one value. */
const REMEMBERED_THRESHOLD = loadSpreadingThreshold();

// Mutable flag outside of React state — controls the run loop without
// depending on store status (which gets overwritten by server responses).
let _stopRequested = false;

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

/**
 * Take the error channel for the action about to run, so the message on screen
 * always belongs to the most recent thing the user asked for.
 */
function beginAction(): void {
  useRunStore.setState({ lastError: null });
}

/**
 * Say why a user-initiated action did not happen, in one sentence the reader can
 * act on. `action` names the attempt in the reader's own terms: it completes
 * "Could not ...".
 */
function reportFailure(err: unknown, action: string): void {
  console.error(`${action} failed:`, err);
  useRunStore.setState({ lastError: describeApiError(err, action) });
}

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
  temperatureClamped: false,
  commentary: '',
  elizaMode: true,
  codeletCount: 0,
  stepDelay: 0,
  liveUpdate: true,
  lastCodeletType: '',
  epoch: 0,
  pollingInterval: 1000,
  spreadingThreshold: REMEMBERED_THRESHOLD,
  defaultSpreadingThreshold: REMEMBERED_THRESHOLD,
  persistenceMode: 'normal',
  parameterOverrides: {},
  runParameterOverrides: {},
  workers: 1,
  runWorkers: 1,
  isProcessing: false,
  lastError: null,
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
    beginAction();
    let info: RunInfo;
    try {
      info = await apiCreateRun({
        // The standing preference, so a new run starts at the value the user chose
        // and a run loaded in between hands on nothing of its own.
        spreading_threshold: get().defaultSpreadingThreshold,
        mode: get().persistenceMode,
        workers,
        // Omitted entirely when empty, so a run with no overrides sends the same
        // request it always did.
        ...(Object.keys(overrides).length > 0 ? { parameters: overrides } : {}),
        ...params,
      });
    } catch (err) {
      // Reported on the channel and raised: the caller asked for a run and there is
      // none, so whatever it meant to do with the new run stops here.
      reportFailure(err, 'start a new run');
      throw err;
    }
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
      temperatureClamped: false,
      // Taken from the response, which reports the threshold the engine was
      // initialised with — including when the caller asked for one of its own.
      spreadingThreshold: info.spreading_threshold ?? get().defaultSpreadingThreshold,
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

  adoptRun: (info: RunInfo): void => {
    set({
      runId: info.run_id,
      // Carried over so the run controls know whether pressing Run would continue
      // this run or start a new one under a different mode.
      runMode: info.mode ?? null,
      status: info.status as RunStatus,
      codeletCount: info.codelet_count,
      temperature: info.temperature,
      // The threshold belongs to the run, so the slider shows what this run is
      // executing with. A record that carries no threshold reads as 100, which is
      // the value such a run used and the original's behaviour.
      spreadingThreshold: info.spreading_threshold ?? 100,
    });
  },

  step: async (n?: number): Promise<void> => {
    const { runId, liveUpdate } = get();
    if (runId === null) return;

    const count = n ?? 1;
    beginAction();

    // A step the engine refuses is a request that produced nothing, so it is said
    // out loud and the remaining steps are abandoned: the run stands where it was.
    try {
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
    } catch (err) {
      reportFailure(err, 'step the run');
    }
  },

  run: async (maxSteps?: number): Promise<void> => {
    const { runId, liveUpdate } = get();
    if (runId === null) return;

    _stopRequested = false;
    beginAction();
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
          // The run stops here, so the reason it stopped is put on the channel: a
          // halt with no explanation looks like the engine giving up.
          reportFailure(err, 'run the engine');
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
          // A poll: the next tick reads the same panels again, so stepping carries on.
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
        // A poll for the status the loop has already finished with: the status shown
        // is halted either way, and the next action reads the run again.
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
        reportFailure(err, 'run the engine');
        set({ status: 'halted' });
        // Whatever state is still readable, so the panels show where the run got to.
        try {
          await get().refreshAll();
        } catch {
          // A poll: the panels keep what they last had, and the next action re-reads.
        }
      }
    }
  },

  runToAnswer: async (maxSteps?: number): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;

    _stopRequested = false;
    beginAction();
    set({ status: 'running', isProcessing: true });

    try {
      // Fire the backend /run request (returns when the run finishes).
      // We don't await it here — instead we poll the server-side status.
      const runPromise = apiRunToCompletion(runId, maxSteps ?? 0).catch((err) => {
        // The request that does the work: if it is refused, the polling below sees a
        // run that never moves, and this is the only account of why.
        reportFailure(err, 'run the engine');
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
          // A poll: the loop comes back at the sampling interval and reads again.
        }
      }

      // Let the /run request finish (may already be done)
      await runPromise;

      // Final refresh to get the definitive end state
      try {
        await get().refreshAll();
      } catch {
        // A poll: the panels hold what the last successful sample gave them.
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
        // A poll: the status shown is the last one the run reported.
      }
    } finally {
      set({ isProcessing: false });
    }
  },

  stop: async (): Promise<void> => {
    // Signal the live-update loop / run-to-answer polling to stop
    _stopRequested = true;
    beginAction();
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
    } catch (err) {
      // The client loop has stopped and the panel says paused; a refused stop means
      // the engine on the server is still going, which is worth saying.
      reportFailure(err, 'stop the run');
    }
  },

  reset: async (): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;

    beginAction();
    let info;
    try {
      info = await apiResetRun(runId);
    } catch (err) {
      // Raised to the caller, which is where this one is reported: the Reset button
      // renders the failure beside itself, next to the problem it was to re-run.
      console.error('Reset failed:', err);
      throw err;
    }
    // Clear all state first so panels visibly reset, then refresh
    set({
      runId: info.run_id,
      status: info.status as RunStatus,
      codeletCount: info.codelet_count,
      temperature: info.temperature,
      temperatureClamped: false,
      // A reset is the same run again, threshold included, so the display keeps
      // reporting what the engine is executing with.
      spreadingThreshold: info.spreading_threshold ?? get().spreadingThreshold,
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

    beginAction();
    try {
      await apiDeleteRun(runId);
    } catch (err) {
      // Said out loud and raised: the run is still on the server, so the store keeps
      // showing it rather than presenting it as gone.
      reportFailure(err, 'delete the run');
      throw err;
    }
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
      temperatureClamped: false,
      commentary: '',
      codeletCount: 0,
      lastCodeletType: '',
      epoch: get().epoch + 1,
      // With no run on screen the slider shows what the next one will be created
      // with.
      spreadingThreshold: get().defaultSpreadingThreshold,
    });
  },

  fullReset: async (): Promise<void> => {
    // Stop any running loop
    _stopRequested = true;
    beginAction();

    // Delete ALL runs, snapshots, trace events, and episodic memory on server.
    // Clearing the memory is also what closes the Training Session.
    try {
      await apiDeleteAllRuns();
      await apiClearMemory();
    } catch (err) {
      // The local state is cleared below regardless, so the message is what tells a
      // reader that the server still holds what the panels have stopped showing.
      reportFailure(err, 'clear every run and the episodic memory');
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
      temperatureClamped: false,
      commentary: '',
      codeletCount: 0,
      lastCodeletType: '',
      epoch: get().epoch + 1,
      // As above: nothing is loaded, so the display returns to the default.
      spreadingThreshold: get().defaultSpreadingThreshold,
    });
  },

  // ---- State refresh -----------------------------------------------------
  //
  // Every refresh below is a poll: it runs on a timer or after each codelet, and the
  // tick that follows reads the same endpoint again. A failed read therefore leaves
  // the panel showing its last good value and stays out of the error channel, which
  // is reserved for the things a user asked for by name.

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
      // A poll: the panel keeps what it has, and the next refresh reads it again.
    }
  },

  refreshSlipnet: async (): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;
    try {
      const slipnet = await getSlipnet(runId);
      set({ slipnet });
    } catch {
      // A poll: the panel keeps what it has, and the next refresh reads it again.
    }
  },

  refreshCoderack: async (): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;
    try {
      const coderack = await getCoderack(runId);
      set({ coderack });
    } catch {
      // A poll: the panel keeps what it has, and the next refresh reads it again.
    }
  },

  refreshThemespace: async (): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;
    try {
      const themespace = await getThemespace(runId);
      set({ themespace });
    } catch {
      // A poll: the panel keeps what it has, and the next refresh reads it again.
    }
  },

  refreshTrace: async (): Promise<void> => {
    const { runId, trace: existing } = get();
    if (runId === null) return;
    try {
      // Only fetch events newer than what we already have.
      // Use offset = existing.length to get incremental updates.
      const offset = existing.length;
      const raw = await getTrace(runId, { limit: 500, offset });
      if (raw.length > 0) {
        set({ trace: [...existing, ...raw] });
      }
    } catch {
      // A poll: the panel keeps what it has, and the next refresh reads it again.
    }
  },

  refreshMemory: async (): Promise<void> => {
    // Asked *of the run* whenever there is one. Every run shares the Training
    // Session's memory, and the run-scoped read is the one that reaches it by the
    // right route in every mode: a Fast Run has no database rows, so its memory is
    // served from the live object rather than from storage.
    const { runId } = get();
    try {
      const memory = runId === null ? await getMemory() : await getRunMemory(runId);
      set({ memory });
    } catch {
      // A poll: the panel keeps what it has, and the next refresh reads it again.
    }
  },

  refreshTemperature: async (): Promise<void> => {
    const { runId } = get();
    if (runId === null) return;
    try {
      // The clamp state travels with the value: both are the engine's, and the
      // gauge shows both.
      const state = await getTemperature(runId);
      set({ temperature: state.temperature, temperatureClamped: state.clamped });
    } catch {
      // A poll: the panel keeps what it has, and the next refresh reads it again.
    }
  },

  refreshCommentary: async (): Promise<void> => {
    const { runId, elizaMode } = get();
    if (runId === null) return;
    try {
      set({ commentary: await getCommentary(runId, elizaMode) });
    } catch {
      // A poll: the panel keeps what it has, and the next refresh reads it again.
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
    // Moving the slider states a preference as well as changing the run in front of
    // the user, so it sets both: what this run is executing with, and what the next
    // one will be created with.
    beginAction();
    set({ spreadingThreshold: clamped, defaultSpreadingThreshold: clamped });
    saveSpreadingThreshold(clamped);
    // Pushed to the run on screen, so the change takes effect on it now.
    const { runId } = get();
    if (runId !== null) {
      try {
        await apiSetSpreadingThreshold(runId, clamped);
      } catch (err) {
        // The slider has moved and the stored value applies to the next run, so a
        // refusal here means the run on screen is spreading by the old rule — which
        // changes what it computes, and is exactly what a reader needs told.
        reportFailure(err, 'apply the spreading threshold to this run');
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

  // ---- The error channel -------------------------------------------------

  setLastError: (message: string): void => {
    // For user-initiated work that runs outside the store — a breakpoint, a clamp —
    // so every failure a user asked for arrives in the same place, in the same voice.
    set({ lastError: message });
  },

  clearLastError: (): void => {
    set({ lastError: null });
  },
}));
