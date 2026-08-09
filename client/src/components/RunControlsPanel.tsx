// ---------------------------------------------------------------------------
// RunControlsPanel — execution strategy, recording, manual stepping, settings
// ---------------------------------------------------------------------------
//
// "Run to Answer" and "Run with Live Updates" are not two features; they are
// two mutually exclusive strategies for executing the same run:
//
//   batch — the backend runs flat out via /run, and the UI polls it
//            (paced by pollingInterval)
//   live  — the client drives one codelet at a time, refreshing every panel
//            after each (paced by stepDelay)
//
// Presenting them as two side-by-side buttons in separate boxes made that
// choice invisible and stranded each mode's pacing control in the wrong place:
// the polling slider sat under one button while stepDelay had no control at
// all. They are now one selector with the pacing control following the choice.
//
// A note on the word "fast", which Phase 0 made ambiguous. The batch strategy
// above was called `fast` here long before persistence modes existed, and Phase 0
// then named one of its three persistence modes Fast. They are unrelated: one is
// how often this browser reads a run, the other is whether the run is written to
// the database at all. The execution strategy is now `batch` internally and never
// says "fast" on screen; "Fast" in this panel means the persistence mode and
// nothing else.
//
// Group 1: Run — how to execute + workers + go/stop + the chosen strategy's pacing
// Group 2: Training Session — the sequence of runs the next one joins, and its end
// Group 3: Recording — the persistence mode the next run is created with
// Group 4: Engine parameters — the 25 the run is fixed with (collapsed)
// Group 5: What this run is — the derived, read-only half (collapsed)
// Group 6: Manual stepping — step size + Step N (orthogonal to both)
// Group 7: Settings — spreading threshold, Eliza toggle, breakpoint, status
//
// Groups 1, 3 and 4 are all *fixed at creation*: the execution strategy is not, but
// the worker count, the persistence mode and every engine parameter are read before
// the first codelet and cannot change afterwards. They therefore share one rule, which
// `inputsMatchLoadedRun` below implements once for all of them: changing any of them
// means the next press of Run starts a new run rather than continuing this one.
//
// `loadedRunIsFinished` is the second half of that rule, and the one that makes a
// Training Session usable from this panel at all: a run that has produced its outcome
// is never continued, so pressing Run again on an unchanged problem starts the *next*
// run rather than re-entering the last one.
//
// Reset lives in the Problem Input panel: it re-runs the problem defined there,
// so it belongs with that definition rather than among the run controls.
// ---------------------------------------------------------------------------

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useRunStore } from '@/store/runStore';
import {
  setBreakpoint,
  clearBreakpoint,
  getRunIdentity,
  describeApiError,
} from '@/api/client';
import { ModeBadge, MODE_DESCRIPTIONS } from '@/components/ModeBadge';
import { RunParametersPanel } from '@/components/RunParametersPanel';
import { RunDerivedPanel } from '@/components/RunDerivedPanel';
import { useMachine } from '@/hooks/useMachine';
import {
  parameterErrors,
  useParameterCatalogue,
} from '@/hooks/useParameterCatalogue';
import type { PersistenceMode, RunIdentity } from '@/types';

/** How a run is executed — a client-side strategy, invisible to the engine. */
type ExecutionStrategy = 'batch' | 'live';

export function RunControlsPanel() {
  const store = useRunStore();
  const { formInputs } = store;

  const [strategy, setStrategy] = useState<ExecutionStrategy>('batch');
  const [stepSize, setStepSize] = useState(1);
  const [breakpointValue, setBreakpointValue] = useState('');


  /**
   * Start a run for whatever is currently in the form, unless the loaded run
   * already *is* that problem.
   *
   * Previously this only fired when no run existed at all, so editing a string
   * or picking a different demo and hitting Run silently carried on with the
   * old problem — and the refresh then stamped the old strings back over the
   * form.
   */
  const pendingParams = useMemo(
    () => ({
      initial: formInputs.initial,
      modified: formInputs.modified,
      target: formInputs.target,
      answer: formInputs.answer || undefined,
      seed: formInputs.seed ? parseInt(formInputs.seed, 10) : 0,
    }),
    [formInputs],
  );

  /**
   * Does the loaded run already hold the problem sitting in the form?
   *
   * A run loaded from history or a URL hash has no recorded params, so fall
   * back to the problem its workspace reports (which carries no seed).
   */
  const problemMatchesLoadedRun = useMemo(() => {
    if (store.runId === null) return false;
    const loaded = store.runParams;
    const problem = loaded ?? store.workspace;
    return (
      problem != null &&
      problem.initial === pendingParams.initial &&
      problem.modified === pendingParams.modified &&
      problem.target === pendingParams.target &&
      (problem.answer ?? '') === (pendingParams.answer ?? '') &&
      (loaded === null || loaded.seed === pendingParams.seed)
    );
  }, [store.runId, store.runParams, store.workspace, pendingParams]);

  /**
   * A Run's persistence mode is fixed at creation — it selects the sink before the
   * first codelet — so choosing a different one has to mean a new run, exactly as
   * editing a string does. Without this, picking Audit and pressing Run would carry
   * on writing nothing extra and the audit record the reader came for would simply
   * not exist.
   *
   * Unknown mode (a run adopted from history) counts as matching: refusing to reuse
   * a run only because the store never learned its mode would be worse than the
   * occasional wrong guess.
   */
  const modeMatchesLoadedRun =
    store.runMode === null || store.runMode === store.persistenceMode;

  /**
   * Audit is serial by definition — it reconstructs intermediate states by replaying
   * its log forward, and free-running's log does not describe the order things
   * happened in — so the backend refuses anything above 1 with a 400. The control
   * shows 1 and says why rather than letting a request be sent that cannot succeed.
   */
  const effectiveWorkers = store.persistenceMode === 'audit' ? 1 : store.workers;

  /**
   * The ceiling on the worker count is the server's machine, not a number written
   * into this page: the workers are threads on the server's performance cores, so a
   * 32-core machine offers 24 and an 8-core one offers 4. `null` until the answer
   * arrives, and `null` if it cannot be reached, in which case the control states no
   * ceiling rather than inventing one.
   */
  const { machine, derived } = useMachine();
  const machineWorkers = derived?.workers ?? null;

  /**
   * The worker count and the engine parameters are fixed at creation for exactly the
   * same reason the mode is: the engine reads them before the first codelet. So they
   * follow the same rule — changing one means a new run.
   */
  const workersMatchLoadedRun = store.runWorkers === effectiveWorkers;

  const parametersMatchLoadedRun = useMemo(() => {
    const loaded = store.runParameterOverrides;
    const pending = store.parameterOverrides;
    const names = new Set([...Object.keys(loaded), ...Object.keys(pending)]);
    for (const name of names) {
      if (JSON.stringify(loaded[name]) !== JSON.stringify(pending[name])) return false;
    }
    return true;
  }, [store.runParameterOverrides, store.parameterOverrides]);

  const inputsMatchLoadedRun =
    problemMatchesLoadedRun
    && modeMatchesLoadedRun
    && workersMatchLoadedRun
    && parametersMatchLoadedRun;

  /**
   * The loaded run has already produced its outcome, so there is nothing to continue.
   *
   * Answer-found and gave-up are terminal — the engine has said what it has to say —
   * and re-entering such a run is not a run: the backend puts its status back to
   * `running` and steps it on past its own answer, in the same row, over the same
   * record. So pressing Run a second time on an unchanged problem produced no second
   * run at all, which is precisely the sequence a Training Session exists to hold:
   * repeat a problem and watch Episodic Memory push the next run somewhere else.
   *
   * Halted and paused are deliberately not terminal. A run stopped by hand or by the
   * step limit is one somebody meant to carry on with, and Run carries it on.
   */
  const loadedRunIsFinished =
    store.status === 'answer_found' || store.status === 'gave_up';

  /** Whether the next press of Run continues the loaded run or begins a new one. */
  const continuesLoadedRun = inputsMatchLoadedRun && !loadedRunIsFinished;

  /**
   * Parameters the server would reject, refused here rather than at the API.
   *
   * The same three checks `RunParameter.validate` makes, run against the catalogue's
   * own bounds — so a value out of range disables Run and says so, instead of
   * producing a 400 after the click with nothing on screen to explain it.
   */
  const { specs } = useParameterCatalogue();
  const paramErrors = useMemo(
    () => parameterErrors(specs, store.parameterOverrides),
    [specs, store.parameterOverrides],
  );
  const invalidNames = Object.keys(paramErrors);
  const hasInvalidParameters = invalidNames.length > 0;

  const ensureRunMatchesInputs = useCallback(async () => {
    if (!continuesLoadedRun) {
      await store.createRun(pendingParams);
    }
  }, [store, continuesLoadedRun, pendingParams]);

  /**
   * A press of Run or Step is in flight.
   *
   * `status` is not enough on its own. Creating a run is a round trip, and until it
   * comes back the engine is not running and nothing in the store says a run was
   * asked for — so a second click inside that window starts a second run, and the
   * first one is orphaned. This closes the window: the buttons are unavailable from
   * the press until whatever it started has ended.
   */
  const [busy, setBusy] = useState(false);

  // A run that cannot be created is reported by the store, on the channel the header
  // renders, so the button stops quietly here: pressing Run twice would otherwise
  // stack an unhandled rejection on top of a message that already says what happened.
  const handleRun = useCallback(async () => {
    setBusy(true);
    try {
      try {
        await ensureRunMatchesInputs();
      } catch {
        return;
      }
      if (strategy === 'live') {
        // run() branches on this flag; set it from the strategy rather than relying
        // on the store default so the selector is the single source of truth.
        store.setLiveUpdate(true);
        await store.run();
      } else {
        await store.runToAnswer();
      }
    } finally {
      setBusy(false);
    }
  }, [store, ensureRunMatchesInputs, strategy]);

  const handleStep = useCallback(async () => {
    setBusy(true);
    try {
      try {
        await ensureRunMatchesInputs();
      } catch {
        return;
      }
      await store.step(stepSize);
    } finally {
      setBusy(false);
    }
  }, [store, ensureRunMatchesInputs, stepSize]);

  // The breakpoint buttons speak through the same channel as the run buttons: a
  // breakpoint the server did not take is a breakpoint that will not stop the run.
  const handleSetBreakpoint = useCallback(async () => {
    if (!store.runId || !breakpointValue) return;
    try {
      await setBreakpoint(store.runId, parseInt(breakpointValue, 10));
      store.clearLastError();
    } catch (err) {
      store.setLastError(describeApiError(err, 'set the breakpoint'));
    }
  }, [store, breakpointValue]);

  const handleClearBreakpoint = useCallback(async () => {
    if (!store.runId) return;
    try {
      await clearBreakpoint(store.runId);
      setBreakpointValue('');
      store.clearLastError();
    } catch (err) {
      store.setLastError(describeApiError(err, 'clear the breakpoint'));
    }
  }, [store]);


  const isRunning = store.status === 'running';
  /**
   * A run is under way, by any of the three things that mean so: the engine reports
   * itself running, the store is driving a run-to-answer loop, or a press of Run has
   * not got that far yet. Everything that starts or reconfigures a run is unavailable
   * while this holds — Stop is the one control that has to stay live.
   */
  const runInProgress = isRunning || busy || store.isProcessing;
  const hasRun = store.runId !== null;
  const hasInputs = !!(formInputs.initial && formInputs.modified && formInputs.target);

  // The loaded run's recorded identity: which config and which Episodic Memory it
  // executed against. Fetched rather than derived because only the row has it, and
  // it is part of what makes two runs with the same seed different experiments.
  const [identity, setIdentity] = useState<RunIdentity | null>(null);
  useEffect(() => {
    if (store.runId === null) {
      setIdentity(null);
      return;
    }
    let cancelled = false;
    getRunIdentity(store.runId)
      .then((i) => {
        if (!cancelled) setIdentity(i);
      })
      .catch(() => {
        if (!cancelled) setIdentity(null);
      });
    return () => {
      cancelled = true;
    };
  }, [store.runId, store.epoch]);

  /** The session the loaded run belongs to, when it is one that was recorded. */
  const sessionId = identity?.session_id ?? null;

  /**
   * A session has been closed and nothing has opened the next one yet.
   *
   * Worth saying out loud for exactly as long as it is true: a closed session leaves
   * no visible trace on this panel — the run on screen still reports the session it
   * ran in, because that is still the session it ran in — so without this the button
   * looks as though it did nothing.
   */
  const [sessionEnded, setSessionEnded] = useState(false);
  useEffect(() => {
    setSessionEnded(false);
  }, [store.runId]);

  const handleNewSession = useCallback(async () => {
    if (
      !window.confirm(
        'Start a new Training Session?\n\n'
          + 'This clears Episodic Memory, which is what a session boundary is: the '
          + 'answers and snags from the runs so far are the only thing carried from '
          + 'one run to the next, so the runs after this point start from nothing.\n\n'
          + 'Recorded runs are not deleted — they stay in Run History and in Review, '
          + 'grouped under the session being closed.\n\n'
          + 'This cannot be undone.',
      )
    ) {
      return;
    }
    try {
      await store.startNewTrainingSession();
    } catch {
      // Said once, on the store's channel, which the header renders. Claiming a new
      // session here as well would contradict it.
      return;
    }
    setSessionEnded(true);
  }, [store]);

  return (
    <div className="flex-col gap-2" style={{ fontSize: 13 }}>
      {/* ------------------------------------------------------------ */}
      {/* GROUP 1: Run — strategy, go/stop, and that strategy's pacing  */}
      {/* ------------------------------------------------------------ */}
      <div style={groupStyle}>
        <div style={groupLabelStyle}>Run</div>

        <div style={fieldGroupStyle}>
          {/* `execution-strategy` rather than the old `run-mode`: "mode" now means
              the persistence mode, and two controls answering to one word is how a
              reader concludes that watching a run more slowly changes its record. */}
          <label style={labelStyle} htmlFor="execution-strategy">How to run</label>
          <select
            id="execution-strategy"
            value={strategy}
            onChange={(e) => setStrategy(e.target.value as ExecutionStrategy)}
            style={{ width: '100%' }}
            disabled={runInProgress}
          >
            <option value="batch">Run to answer — full speed</option>
            <option value="live">Live updates — codelet by codelet</option>
          </select>
          <span className="text-xs text-muted">
            {strategy === 'batch'
              ? 'The engine runs flat out on the backend; the UI samples it as it goes. Quickest way to an answer. Changes only how this browser watches the run, not what the run does or records.'
              : 'One codelet at a time, refreshing every panel after each. Much slower, but every structure being built is visible.'}
          </span>
        </div>

        {/* Worker count. In the Run group rather than among the engine parameters
            because it is not one: it changes how the run is executed, not what the
            architecture does. It is fixed at creation all the same. */}
        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="run-workers">
            Workers: {effectiveWorkers}
            {effectiveWorkers === 1 ? ' (serial — the reference mode)' : ' (free-running)'}
          </label>
          <input
            id="run-workers"
            type="number"
            min={1}
            max={machineWorkers ?? undefined}
            value={effectiveWorkers}
            onChange={(e) => store.setWorkers(parseInt(e.target.value, 10) || 1)}
            disabled={runInProgress || store.persistenceMode === 'audit'}
            style={{ width: 70 }}
          />
          <span className="text-xs text-muted">
            {store.persistenceMode === 'audit'
              ? 'Audit is serial by definition: it reconstructs states by replaying its '
                + 'action log forward, and under free-running that log does not record the '
                + 'order things happened in. Choose Normal or Fast to run in parallel.'
              : effectiveWorkers === 1
                ? 'One codelet at a time, in order. The same problem and seed reproduce the '
                  + 'run exactly, which is why this stays the reference mode.'
                : 'Codelets execute across CPU cores with no global barrier. The expected '
                  + 'range of answers is unchanged, but a seed no longer reproduces a run, '
                  + 'because execution order is not determined.'}
            {machineWorkers !== null && (
              <>
                {' '}
                {`The server has ${machineWorkers} performance core`}
                {machineWorkers === 1 ? '' : 's'}
                {machine?.chip ? ` (${machine.chip})` : ''}
                {', which is the ceiling here.'}
              </>
            )}
          </span>
        </div>

        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <button
            className="primary"
            onClick={handleRun}
            disabled={runInProgress || !hasInputs || hasInvalidParameters}
            title={
              runInProgress
                ? 'A run is under way. Stop it, or wait for it to finish, before starting another.'
                : hasInvalidParameters
                  ? `Out of the range the server accepts: ${invalidNames.join(', ')}`
                  : strategy === 'batch'
                    ? 'Run the engine at full speed on the backend until an answer is found. The UI refreshes at the sampling interval.'
                    : 'Run the engine one codelet at a time, refreshing all panels after every step.'
            }
            style={{ flex: 1 }}
          >
            {strategy === 'batch' ? 'Run to Answer' : 'Run with Live Updates'}
          </button>
          {/* Enabled for the whole of a run, including a batch one. `isProcessing` is
              set for as long as run-to-answer's polling loop lives, so gating Stop on
              it too left the only way out of a batch run disabled from the moment it
              started until the moment it no longer needed stopping. */}
          <button
            onClick={() => store.stop()}
            disabled={!isRunning && !store.isProcessing}
            title="Stop the running loop."
          >
            Stop
          </button>
        </div>

        {/* Refused before the request rather than after it: an out-of-range value
            would come back as a 400 with nothing on screen to attach it to. */}
        {hasInvalidParameters && (
          <div
            className="text-xs"
            style={{
              marginTop: 6,
              padding: '4px 6px',
              borderRadius: 3,
              border: '1px solid var(--error)',
              color: 'var(--error)',
            }}
          >
            {invalidNames.length === 1
              ? 'One engine parameter is outside the range the server accepts:'
              : `${invalidNames.length} engine parameters are outside the range the server accepts:`}
            {' '}
            {Object.values(paramErrors).join('; ')}.
          </div>
        )}

        {/* What the run button will actually act on. Without this it is not
            visible whether the workspace on screen belongs to the problem in
            the form or to a previous one. */}
        <div className="text-xs text-muted" style={{ marginTop: 6 }}>
          {store.runId === null ? (
            hasInputs ? 'Starts a new run.' : 'Enter a problem above to begin.'
          ) : inputsMatchLoadedRun && loadedRunIsFinished ? (
            /* The same problem again is not a repeat of run #N — it is the next run
               of this Training Session, and the one whose answer Episodic Memory can
               already tell it not to give twice. Saying so here is what makes the
               session visible from the button that builds it. */
            <span style={{ color: 'var(--text-accent)' }}>
              Run #{store.runId} {store.status === 'gave_up' ? 'gave up' : 'found its answer'}
              {' '}&mdash; running starts the next run of this Training Session, on the
              same problem, against the Episodic Memory this one leaves behind.
            </span>
          ) : inputsMatchLoadedRun ? (
            <>
              Showing run #{store.runId}: {store.workspace?.initial ?? '?'}&nbsp;&rarr;&nbsp;
              {store.workspace?.modified ?? '?'}; {store.workspace?.target ?? '?'}
              &nbsp;&rarr;&nbsp;{store.workspace?.answer ?? '?'}
            </>
          ) : (
            <span style={{ color: 'var(--warning)' }}>
              {!problemMatchesLoadedRun
                ? `Inputs differ from run #${store.runId}`
                : !modeMatchesLoadedRun
                  ? `Recording mode differs from run #${store.runId} (${store.runMode})`
                  : !workersMatchLoadedRun
                    ? `Worker count differs from run #${store.runId} (${store.runWorkers})`
                    : `Engine parameters differ from run #${store.runId}`}
              {' '}&mdash; running starts a new run.
            </span>
          )}
        </div>

        {/* Each strategy is paced by a different value, so only the relevant one
            is shown. stepDelay previously had no control at all. */}
        {strategy === 'batch' ? (
          <div style={{ marginTop: 8 }}>
            <label style={labelStyle}>
              Sampling interval: {store.pollingInterval === 0
                ? 'continuous'
                : `${(store.pollingInterval / 1000).toFixed(1)}s`}
            </label>
            <input
              type="range"
              min={0}
              max={5000}
              step={100}
              value={store.pollingInterval}
              onChange={(e) => store.setPollingInterval(parseInt(e.target.value, 10))}
              style={{ width: '100%' }}
            />
            <div className="text-xs text-muted">
              How often the UI reads the running engine. 0 = continuous (~100ms).
              Does not change how the engine runs.
            </div>
          </div>
        ) : (
          <div style={{ marginTop: 8 }}>
            <label style={labelStyle}>
              Delay per codelet: {store.stepDelay === 0
                ? 'none (as fast as the UI allows)'
                : `${store.stepDelay} ms`}
            </label>
            <input
              type="range"
              min={0}
              max={1000}
              step={10}
              value={store.stepDelay}
              onChange={(e) => store.setStepDelay(parseInt(e.target.value, 10))}
              style={{ width: '100%' }}
            />
            <div className="text-xs text-muted">
              Pause after each codelet. Raise it to follow the run by eye.
            </div>
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------ */}
      {/* GROUP 2: Training Session — what the runs accumulate into     */}
      {/*                                                              */}
      {/* Directly under the Run button because that button is what     */}
      {/* builds a session: each press adds a run to the open one, and  */}
      {/* Episodic Memory is what carries between them. The boundary    */}
      {/* was reachable only from the Admin view, under a name          */}
      {/* ("Clear Episodic Memory") that says what it removes rather    */}
      {/* than what it ends — so the unit the runs belong to could be   */}
      {/* read about in Review and never started from here.             */}
      {/* ------------------------------------------------------------ */}
      <div style={groupStyle}>
        <div style={groupLabelStyle}>Training Session</div>

        <div className="text-xs text-muted">
          A sequence of runs sharing one Episodic Memory — the only thing that
          crosses a run boundary. Every run joins the open session automatically;
          there is nothing to start.
          {sessionId !== null && (
            <>
              {' '}This run is in <strong>session {sessionId}</strong>.
            </>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
          <button
            onClick={handleNewSession}
            disabled={runInProgress}
            title={
              runInProgress
                ? 'A run is under way. A session boundary drawn mid-run would put the run and the memory it is thinking against on opposite sides of it.'
                : 'End this Training Session by clearing Episodic Memory. The next run starts a new session and inherits nothing.'
            }
          >
            Start a new Training Session
          </button>
          {sessionEnded && (
            <span className="text-xs" style={{ color: 'var(--success)' }}>
              Session closed — the next run opens a new one.
            </span>
          )}
        </div>

        <div className="text-xs text-muted" style={{ marginTop: 6 }}>
          Ending a session means clearing Episodic Memory, because that is the whole
          of what one run hands the next. Runs already recorded stay in Run History
          and in Review, grouped under the session being closed.
        </div>
      </div>

      {/* ------------------------------------------------------------ */}
      {/* GROUP 3: Recording — the persistence mode (Phase 0 §A2)       */}
      {/*                                                              */}
      {/* Its own group, immediately below the execution strategy       */}
      {/* rather than tucked into Settings, because the two are the     */}
      {/* pair most easily confused and putting them side by side is    */}
      {/* what makes the difference between them visible.               */}
      {/* ------------------------------------------------------------ */}
      <div style={groupStyle}>
        <div style={groupLabelStyle}>Recording</div>

        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="persistence-mode">
            What the run writes down
          </label>
          <select
            id="persistence-mode"
            value={store.persistenceMode}
            onChange={(e) =>
              store.setPersistenceMode(e.target.value as PersistenceMode)
            }
            style={{ width: '100%' }}
            disabled={runInProgress}
          >
            <option value="normal">Normal — state at start and end</option>
            <option value="audit">Audit — every action, step-through</option>
            <option value="fast">Fast — nothing is recorded</option>
          </select>
          <span className="text-xs text-muted">
            {MODE_DESCRIPTIONS[store.persistenceMode]}
          </span>
        </div>

        <div className="text-xs text-muted">
          Fixed when a run is created, so choosing a different one starts a new run.
          None of the three changes what the engine computes — the same problem and
          seed give the same answer in all three.
        </div>

        {/* Warned about before the run rather than discovered afterwards: a Fast
            Run is absent from Run History and from Review by construction, and
            somebody who has not been told that reads the absence as a bug. */}
        {store.persistenceMode === 'fast' && (
          <div
            className="text-xs"
            style={{
              marginTop: 6,
              padding: '4px 6px',
              borderRadius: 3,
              border: '1px solid var(--warning)',
              color: 'var(--warning)',
            }}
          >
            Fast runs write nothing to the database: no row in Run History and
            nothing in Review. They get a negative run number, because there is no
            database row to take one from. They take part in the Training Session's
            Episodic Memory and narrate themselves like any other run.
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------ */}
      {/* GROUP 4: Engine parameters — the settable half                */}
      {/*                                                              */}
      {/* Directly below Recording because they are the same kind of    */}
      {/* thing: chosen before the run, unchangeable during it, and     */}
      {/* changing either starts a new run. Collapsed, so the common    */}
      {/* path — press Run — is untouched.                              */}
      {/* ------------------------------------------------------------ */}
      <RunParametersPanel />

      {/* ------------------------------------------------------------ */}
      {/* GROUP 5: What this run is — the derived half                  */}
      {/*                                                              */}
      {/* Immediately after the settable half and visibly different     */}
      {/* from it (dashed border, "read-only" in the header), because   */}
      {/* the one mistake worth designing against here is reading a     */}
      {/* derived value as something that could have been set.          */}
      {/* ------------------------------------------------------------ */}
      <RunDerivedPanel />

      {/* ------------------------------------------------------------ */}
      {/* GROUP 6: Manual stepping — independent of both selectors      */}
      {/* ------------------------------------------------------------ */}
      <div style={groupStyle}>
        <div style={groupLabelStyle}>Manual stepping</div>

        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <label style={labelStyle}>Codelets</label>
            <input
              type="number"
              min={1}
              max={1000}
              value={stepSize}
              onChange={(e) =>
                setStepSize(Math.max(1, parseInt(e.target.value, 10) || 1))
              }
              style={{ width: 70 }}
              disabled={runInProgress}
            />
          </div>
          <button
            onClick={handleStep}
            disabled={runInProgress || !hasInputs}
            title={`Execute ${stepSize} codelet(s), then stop.`}
            style={{ flex: 1 }}
          >
            Step {stepSize}
          </button>
        </div>
        <div className="text-xs text-muted" style={{ marginTop: 6 }}>
          Advance a fixed number of codelets and stop. Useful for inspecting a
          specific moment.
        </div>
      </div>

      {/* ------------------------------------------------------------ */}
      {/* GROUP 7: Settings                                            */}
      {/* ------------------------------------------------------------ */}
      <div style={groupStyle}>
        <div style={groupLabelStyle}>Settings</div>

        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="spreading-threshold">
            Spreading threshold: {store.spreadingThreshold}
            {store.spreadingThreshold === 100 ? ' (original)' : ''}
          </label>
          <input
            id="spreading-threshold"
            type="range"
            min={0}
            max={100}
            step={1}
            value={store.spreadingThreshold}
            onChange={(e) => store.setSpreadingThreshold(parseInt(e.target.value, 10))}
            style={{ width: '100%' }}
          />
          <span className="text-xs text-muted">
            0 = all active nodes spread; 100 = only fully-active, matching the
            original. Shows what the run on screen is using; moving it changes
            that run, and the value chosen is what each new run starts with.
          </span>
        </div>

        <div style={{ ...fieldGroupStyle, marginTop: 4 }}>
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              cursor: 'pointer',
              fontSize: 12,
            }}
          >
            <input
              type="checkbox"
              checked={store.elizaMode}
              onChange={(e) => store.setElizaMode(e.target.checked)}
            />
            <span>Eliza commentary</span>
          </label>
          <span className="text-xs text-muted">
            Friendly narration style in the Commentary panel.
          </span>
        </div>

        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="run-breakpoint">
            Breakpoint (codelet #)
          </label>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <input
              id="run-breakpoint"
              type="number"
              min={0}
              value={breakpointValue}
              onChange={(e) => setBreakpointValue(e.target.value)}
              style={{ width: 80 }}
              disabled={!hasRun}
            />
            <button
              onClick={handleSetBreakpoint}
              disabled={!hasRun || !breakpointValue}
            >
              Set
            </button>
            <button onClick={handleClearBreakpoint} disabled={!hasRun}>
              Clear
            </button>
          </div>
        </div>

        {hasRun && (
          <div
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              padding: '6px 10px',
              marginTop: 6,
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <span
                className="text-xs text-muted"
                style={{ display: 'flex', alignItems: 'center', gap: 6 }}
              >
                Run #{store.runId}
                {store.runMode && <ModeBadge mode={store.runMode} />}
              </span>
              <span
                className="mono"
                style={{
                  fontSize: 16,
                  fontWeight: 700,
                  color: 'var(--text-accent)',
                }}
              >
                {store.codeletCount}
              </span>
            </div>
            <div className="text-xs text-muted" style={{ marginTop: 2 }}>
              codelets executed
            </div>

            {/* The run's identity as an experiment, next to the run number, because
                that is where a reader looks for "which run is this?". Shown live
                rather than only in the Review browser: by the time anyone is in
                Review, the run they were watching has ended. */}
            {identity !== null && identity.recorded && (
              <div className="text-xs text-muted" style={{ marginTop: 4 }}>
                <div
                  className="mono"
                  title={
                    `config ${identity.config_hash ?? '—'}\n`
                    + `memory ${identity.memory_hash ?? '—'}\n\n`
                    + 'Which configuration and which Episodic Memory this run '
                    + 'executed against. Two runs with one seed and different '
                    + 'hashes are not the same experiment.'
                  }
                >
                  cfg {(identity.config_hash ?? '——').slice(0, 8)} · mem{' '}
                  {(identity.memory_hash ?? '——').slice(0, 8)}
                </div>
                {identity.session_id !== null && (
                  <div title="The Training Session this run belongs to: the span between two Episodic Memory clears.">
                    Training Session {identity.session_id}
                  </div>
                )}
                {/* The other route into Review, beside the run you are actually
                    watching. Run History has one per row; this one is for the run
                    that has just finished, which is when the question arises. */}
                <button
                  onClick={() => {
                    window.location.hash = `/review/runs/${store.runId}`;
                  }}
                  title="Open this run in the Review browser."
                  style={{
                    background: 'none',
                    border: 'none',
                    padding: 0,
                    marginTop: 2,
                    color: 'var(--text-accent)',
                    cursor: 'pointer',
                    fontSize: 11,
                  }}
                >
                  Review this run &rarr;
                </button>
              </div>
            )}

            {/* Two ways to reach this: the endpoint said `recorded: false`, or it
                could not be reached at all while the loaded run is a Fast one. The
                second is not hypothetical — a Fast Run is required to complete with
                Postgres stopped, and the identity endpoint needs a session. Trusting
                the mode we already know keeps the explanation on screen in exactly
                the condition where the rest of the record is unavailable. */}
            {(store.runMode === 'fast' || (identity !== null && !identity.recorded)) && (
              <div
                className="text-xs"
                style={{ marginTop: 4, color: 'var(--warning)' }}
              >
                Not recorded — a Fast Run has no database row, so no config or
                memory hash, no Training Session, and no entry in Run History.
              </div>
            )}
            {store.lastCodeletType && (
              <div
                className="mono text-xs"
                style={{ marginTop: 2, color: 'var(--text-secondary)' }}
              >
                last: {store.lastCodeletType}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const groupStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: 4,
  padding: 10,
};

const groupLabelStyle: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: 0.6,
  color: 'var(--text-secondary)',
  marginBottom: 8,
};

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 11,
  color: 'var(--text-secondary)',
  marginBottom: 2,
};

const fieldGroupStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 3,
  marginBottom: 8,
};
