// ---------------------------------------------------------------------------
// RunControlsPanel — Three grouped sections of run controls
// ---------------------------------------------------------------------------
//
// Group 1: Run to Answer + polling interval
// Group 2: Run with Live Updates + Stop + step size + Step + Reset
// Group 3: Seed, spreading threshold, Eliza toggle, breakpoint, run status
// ---------------------------------------------------------------------------

import { useState, useEffect, useCallback } from 'react';
import { useRunStore } from '@/store/runStore';
import { setBreakpoint, clearBreakpoint, setSpreadingThreshold, getSpreadingThreshold } from '@/api/client';

export function RunControlsPanel() {
  const store = useRunStore();
  const { formInputs } = store;

  const [stepSize, setStepSize] = useState(1);
  const [breakpointValue, setBreakpointValue] = useState('');
  const [spreadingThresholdLocal, setSpreadingThresholdLocal] = useState(100);
  const [resetFlash, setResetFlash] = useState(false);

  // Fetch spreading threshold when run loads
  useEffect(() => {
    if (store.runId) {
      getSpreadingThreshold(store.runId)
        .then((r) => setSpreadingThresholdLocal(r.spreading_activation_threshold))
        .catch(() => {});
    }
  }, [store.runId]);

  const handleRunLiveUpdates = useCallback(async () => {
    if (!store.runId) {
      await store.createRun({
        initial: formInputs.initial,
        modified: formInputs.modified,
        target: formInputs.target,
        answer: formInputs.answer || undefined,
        seed: formInputs.seed ? parseInt(formInputs.seed, 10) : 0,
      });
    }
    await store.run();
  }, [store, formInputs]);

  const handleRunToAnswer = useCallback(async () => {
    if (!store.runId) {
      await store.createRun({
        initial: formInputs.initial,
        modified: formInputs.modified,
        target: formInputs.target,
        answer: formInputs.answer || undefined,
        seed: formInputs.seed ? parseInt(formInputs.seed, 10) : 0,
      });
    }
    await store.runToAnswer();
  }, [store, formInputs]);

  const handleStep = useCallback(async () => {
    if (!store.runId) {
      await store.createRun({
        initial: formInputs.initial,
        modified: formInputs.modified,
        target: formInputs.target,
        answer: formInputs.answer || undefined,
        seed: formInputs.seed ? parseInt(formInputs.seed, 10) : 0,
      });
    }
    await store.step(stepSize);
  }, [store, formInputs, stepSize]);

  const handleReset = useCallback(async () => {
    await store.reset();
    setResetFlash(true);
    setTimeout(() => setResetFlash(false), 1200);
  }, [store]);

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

  const handleSpreadingThresholdChange = useCallback(
    async (value: number) => {
      setSpreadingThresholdLocal(value);
      if (store.runId) {
        try {
          await setSpreadingThreshold(store.runId, value);
        } catch {
          // ignore
        }
      }
    },
    [store.runId],
  );

  const isRunning = store.status === 'running';
  const hasRun = store.runId !== null;
  const hasInputs = !!(formInputs.initial && formInputs.modified && formInputs.target);

  return (
    <div className="flex-col gap-2" style={{ fontSize: 13 }}>
      {/* ------------------------------------------------------------ */}
      {/* GROUP 1: Run to Answer                                       */}
      {/* ------------------------------------------------------------ */}
      <div style={groupStyle}>
        <div style={groupLabelStyle}>Run to Answer</div>

        <button
          className="primary"
          onClick={handleRunToAnswer}
          disabled={isRunning || !hasInputs}
          title="Run engine at full speed on the backend until an answer is found. The UI refreshes periodically at the polling interval."
          style={{ width: '100%' }}
        >
          Run to Answer
        </button>

        <div style={{ marginTop: 8 }}>
          <label style={labelStyle}>
            Polling interval: {store.pollingInterval === 0
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
            How often the UI refreshes during "Run to Answer". 0 = continuous (~100ms).
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------ */}
      {/* GROUP 2: Live Updates / Step                                 */}
      {/* ------------------------------------------------------------ */}
      <div style={groupStyle}>
        <div style={groupLabelStyle}>Live Updates</div>

        <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            className="primary"
            onClick={handleRunLiveUpdates}
            disabled={isRunning || !hasInputs}
            title="Run the engine one codelet at a time, refreshing all panels after every step. Slower than Run to Answer but every codelet is visible."
          >
            Run with Live Updates
          </button>
          <button
            onClick={() => store.stop()}
            disabled={!isRunning || store.isProcessing}
            title="Stop the running loop."
          >
            Stop
          </button>
        </div>

        <div style={{ marginTop: 8, display: 'flex', gap: 4, alignItems: 'flex-end' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <label style={labelStyle}>Step size</label>
            <input
              type="number"
              min={1}
              max={1000}
              value={stepSize}
              onChange={(e) =>
                setStepSize(Math.max(1, parseInt(e.target.value, 10) || 1))
              }
              style={{ width: 60 }}
              disabled={isRunning}
            />
          </div>
          <button
            onClick={handleStep}
            disabled={isRunning || !hasInputs}
            title={`Execute ${stepSize} codelet(s), refreshing the UI after each.`}
          >
            Step {stepSize}
          </button>
          <button
            onClick={handleReset}
            disabled={!hasRun || isRunning}
            title="Re-initialize the current run with the same problem and seed."
          >
            Reset
          </button>
        </div>

        {resetFlash && (
          <div
            style={{
              background: 'var(--success)',
              color: '#fff',
              padding: '4px 8px',
              borderRadius: 3,
              fontSize: 11,
              fontWeight: 600,
              textAlign: 'center',
              marginTop: 6,
              animation: 'fadeOut 1.2s ease-out forwards',
            }}
          >
            Run reset to initial state
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------ */}
      {/* GROUP 3: Settings                                            */}
      {/* ------------------------------------------------------------ */}
      <div style={groupStyle}>
        <div style={groupLabelStyle}>Settings</div>

        <div style={fieldGroupStyle}>
          <label style={labelStyle}>Seed (optional)</label>
          <input
            type="text"
            value={formInputs.seed}
            onChange={(e) => store.setFormInput('seed', e.target.value)}
            placeholder="0"
            style={{ width: '100%' }}
            disabled={isRunning}
          />
        </div>

        <div style={fieldGroupStyle}>
          <label style={labelStyle}>
            Spreading threshold: {spreadingThresholdLocal}
          </label>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={spreadingThresholdLocal}
            onChange={(e) =>
              handleSpreadingThresholdChange(parseInt(e.target.value, 10))
            }
            style={{ width: '100%' }}
            disabled={!hasRun}
          />
          <span className="text-xs text-muted">
            0 = all active nodes spread; 100 = only fully-active (original)
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
