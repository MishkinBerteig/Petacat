// ---------------------------------------------------------------------------
// RunControlsPanel — Run mode, manual stepping, settings
// ---------------------------------------------------------------------------
//
// "Run to Answer" and "Run with Live Updates" are not two features; they are
// two mutually exclusive strategies for executing the same run:
//
//   fast  — the backend runs flat out via /run, and the UI polls it
//            (paced by pollingInterval)
//   live  — the client drives one codelet at a time, refreshing every panel
//            after each (paced by stepDelay)
//
// Presenting them as two side-by-side buttons in separate boxes made that
// choice invisible and stranded each mode's pacing control in the wrong place:
// the polling slider sat under one button while stepDelay had no control at
// all. They are now one selector with the pacing control following the choice.
//
// Group 1: Run — mode selector + go/stop + the selected mode's pacing control
// Group 2: Manual stepping — step size + Step N (orthogonal to run mode)
// Group 3: Settings — spreading threshold, Eliza toggle, breakpoint, status
//
// Reset lives in the Problem Input panel: it re-runs the problem defined there,
// so it belongs with that definition rather than among the run controls.
// ---------------------------------------------------------------------------

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useRunStore } from '@/store/runStore';
import { setBreakpoint, clearBreakpoint } from '@/api/client';

/** How a run is executed. Mutually exclusive. */
type RunMode = 'fast' | 'live';

export function RunControlsPanel() {
  const store = useRunStore();
  const { formInputs } = store;

  const [runMode, setRunMode] = useState<RunMode>('fast');
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
  const inputsMatchLoadedRun = useMemo(() => {
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

  const ensureRunMatchesInputs = useCallback(async () => {
    if (!inputsMatchLoadedRun) {
      await store.createRun(pendingParams);
    }
  }, [store, inputsMatchLoadedRun, pendingParams]);

  const handleRun = useCallback(async () => {
    await ensureRunMatchesInputs();
    if (runMode === 'live') {
      // run() branches on this flag; set it from the mode rather than relying
      // on the store default so the selector is the single source of truth.
      store.setLiveUpdate(true);
      await store.run();
    } else {
      await store.runToAnswer();
    }
  }, [store, ensureRunMatchesInputs, runMode]);

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

  return (
    <div className="flex-col gap-2" style={{ fontSize: 13 }}>
      {/* ------------------------------------------------------------ */}
      {/* GROUP 1: Run — mode, go/stop, and that mode's pacing control  */}
      {/* ------------------------------------------------------------ */}
      <div style={groupStyle}>
        <div style={groupLabelStyle}>Run</div>

        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="run-mode">How to run</label>
          <select
            id="run-mode"
            value={runMode}
            onChange={(e) => setRunMode(e.target.value as RunMode)}
            style={{ width: '100%' }}
            disabled={isRunning}
          >
            <option value="fast">Run to answer — full speed</option>
            <option value="live">Live updates — codelet by codelet</option>
          </select>
          <span className="text-xs text-muted">
            {runMode === 'fast'
              ? 'The engine runs flat out on the backend; the UI samples it as it goes. Fastest way to an answer.'
              : 'One codelet at a time, refreshing every panel after each. Much slower, but every structure being built is visible.'}
          </span>
        </div>

        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <button
            className="primary"
            onClick={handleRun}
            disabled={isRunning || !hasInputs}
            title={
              runMode === 'fast'
                ? 'Run the engine at full speed on the backend until an answer is found. The UI refreshes at the sampling interval.'
                : 'Run the engine one codelet at a time, refreshing all panels after every step.'
            }
            style={{ flex: 1 }}
          >
            {runMode === 'fast' ? 'Run to Answer' : 'Run with Live Updates'}
          </button>
          <button
            onClick={() => store.stop()}
            disabled={!isRunning || store.isProcessing}
            title="Stop the running loop."
          >
            Stop
          </button>
        </div>

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
              Inputs differ from run #{store.runId} — running starts a new run.
            </span>
          )}
        </div>

        {/* Each mode is paced by a different value, so only the relevant one
            is shown. stepDelay previously had no control at all. */}
        {runMode === 'fast' ? (
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
      {/* GROUP 2: Manual stepping — independent of the run mode        */}
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
      {/* GROUP 3: Settings                                            */}
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
              <span className="text-xs text-muted">Run #{store.runId}</span>
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
