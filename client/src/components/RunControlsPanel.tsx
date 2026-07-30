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
// Group 2: Recording — the persistence mode the next run is created with
// Group 3: Engine parameters — the 25 the run is fixed with (collapsed)
// Group 4: What this run is — the derived, read-only half (collapsed)
// Group 5: Manual stepping — step size + Step N (orthogonal to both)
// Group 6: Settings — spreading threshold, Eliza toggle, breakpoint, status
//
// Groups 1-3 are all *fixed at creation*: the execution strategy is not, but the
// worker count, the persistence mode and every engine parameter are read before the
// first codelet and cannot change afterwards. They therefore share one rule, which
// `inputsMatchLoadedRun` below implements once for all of them: changing any of them
// means the next press of Run starts a new run rather than continuing this one.
//
// Reset lives in the Problem Input panel: it re-runs the problem defined there,
// so it belongs with that definition rather than among the run controls.
// ---------------------------------------------------------------------------

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useRunStore } from '@/store/runStore';
import { setBreakpoint, clearBreakpoint, getRunIdentity } from '@/api/client';
import { ModeBadge, MODE_DESCRIPTIONS } from '@/components/ModeBadge';
import { RunParametersPanel } from '@/components/RunParametersPanel';
import { RunDerivedPanel } from '@/components/RunDerivedPanel';
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
    if (!inputsMatchLoadedRun) {
      await store.createRun(pendingParams);
    }
  }, [store, inputsMatchLoadedRun, pendingParams]);

  const handleRun = useCallback(async () => {
    await ensureRunMatchesInputs();
    if (strategy === 'live') {
      // run() branches on this flag; set it from the strategy rather than relying
      // on the store default so the selector is the single source of truth.
      store.setLiveUpdate(true);
      await store.run();
    } else {
      await store.runToAnswer();
    }
  }, [store, ensureRunMatchesInputs, strategy]);

  const handleStep = useCallback(async () => {
    await ensureRunMatchesInputs();
    await store.step(stepSize);
  }, [store, ensureRunMatchesInputs, stepSize]);

  const handleSetBreakpoint = useCallback(async () => {
    if (!store.runId || !breakpointValue) return;
    try {
      await setBreakpoint(store.runId, parseInt(breakpointValue, 10));
    } catch {
      // ignore
    }
  }, [store.runId, breakpointValue]);

  const handleClearBreakpoint = useCallback(async () => {
    if (!store.runId) return;
    try {
      await clearBreakpoint(store.runId);
      setBreakpointValue('');
    } catch {
      // ignore
    }
  }, [store.runId]);


  const isRunning = store.status === 'running';
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
            disabled={isRunning}
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
            max={16}
            value={effectiveWorkers}
            onChange={(e) => store.setWorkers(parseInt(e.target.value, 10) || 1)}
            disabled={isRunning || store.persistenceMode === 'audit'}
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
                : 'Codelets execute across CPU cores with no global barrier — about 1.35x at '
                  + 'four workers. The expected range of answers is unchanged, but a seed no '
                  + 'longer reproduces a run, because execution order is not determined.'}
          </span>
        </div>

        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <button
            className="primary"
            onClick={handleRun}
            disabled={isRunning || !hasInputs || hasInvalidParameters}
            title={
              hasInvalidParameters
                ? `Out of the range the server accepts: ${invalidNames.join(', ')}`
                : strategy === 'batch'
                  ? 'Run the engine at full speed on the backend until an answer is found. The UI refreshes at the sampling interval.'
                  : 'Run the engine one codelet at a time, refreshing all panels after every step.'
            }
            style={{ flex: 1 }}
          >
            {strategy === 'batch' ? 'Run to Answer' : 'Run with Live Updates'}
          </button>
          <button
            onClick={() => store.stop()}
            disabled={!isRunning || store.isProcessing}
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
      {/* GROUP 2: Recording — the persistence mode (Phase 0 §A2)       */}
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
            disabled={isRunning}
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
            Fast runs leave no trace: no row in Run History, nothing in Review, and
            no contribution to Episodic Memory. They also get a negative run number,
            because there is no database row to take one from.
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------ */}
      {/* GROUP 3: Engine parameters — the settable half                */}
      {/*                                                              */}
      {/* Directly below Recording because they are the same kind of    */}
      {/* thing: chosen before the run, unchangeable during it, and     */}
      {/* changing either starts a new run. Collapsed, so the common    */}
      {/* path — press Run — is untouched.                              */}
      {/* ------------------------------------------------------------ */}
      <RunParametersPanel />

      {/* ------------------------------------------------------------ */}
      {/* GROUP 4: What this run is — the derived half                  */}
      {/*                                                              */}
      {/* Immediately after the settable half and visibly different     */}
      {/* from it (dashed border, "read-only" in the header), because   */}
      {/* the one mistake worth designing against here is reading a     */}
      {/* derived value as something that could have been set.          */}
      {/* ------------------------------------------------------------ */}
      <RunDerivedPanel />

      {/* ------------------------------------------------------------ */}
      {/* GROUP 5: Manual stepping — independent of both selectors      */}
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
              disabled={isRunning}
            />
          </div>
          <button
            onClick={handleStep}
            disabled={isRunning || !hasInputs}
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
      {/* GROUP 6: Settings                                            */}
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
            original. Kept across runs and applied to each new one.
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
          <label style={labelStyle}>Breakpoint (codelet #)</label>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <input
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
