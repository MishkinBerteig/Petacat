// ---------------------------------------------------------------------------
// ProblemInputPanel — the problem to run: four strings, seed, demo, Reset
// ---------------------------------------------------------------------------
//
// This panel owns *what* gets run; RunControlsPanel owns *how*. Seed and Reset
// live here because they belong to the problem's identity rather than to the
// run mechanics: Reset re-initializes the current run with exactly the strings
// and seed shown here, which is only legible when they sit together. Changing
// any field instead means the next Run starts a new run.
// ---------------------------------------------------------------------------

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRunStore } from '@/store/runStore';
import type { DemoProblem } from '@/types';
import { getDemos, describeApiError } from '@/api/client';

export function ProblemInputPanel() {
  const workspace = useRunStore((s) => s.workspace);
  const runId = useRunStore((s) => s.runId);
  /** Last run whose problem we copied into the form. */
  const adoptedRunId = useRef<number | null>(null);
  const formInputs = useRunStore((s) => s.formInputs);
  const setFormInput = useRunStore((s) => s.setFormInput);
  const setFormInputs = useRunStore((s) => s.setFormInputs);
  const status = useRunStore((s) => s.status);
  const reset = useRunStore((s) => s.reset);
  const isRunning = status === 'running';
  const hasRun = runId !== null;

  const [demos, setDemos] = useState<DemoProblem[]>([]);
  const [selectedDemo, setSelectedDemo] = useState('');
  const [demosLoading, setDemosLoading] = useState(false);
  const [resetFlash, setResetFlash] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  const handleReset = useCallback(async () => {
    try {
      await reset();
    } catch (err) {
      // Reported beside the button that asked for it, in the same words the rest of
      // the app uses: `describeApiError` turns the status into a next move — the run
      // is gone, the values are wrong, the server is unreachable.
      setResetError(describeApiError(err, 'reset the run'));
      return;
    }
    setResetError(null);
    setResetFlash(true);
    setTimeout(() => setResetFlash(false), 1200);
  }, [reset]);

  // Adopt the problem of a newly-loaded run (e.g. via URL hash or history).
  //
  // Keyed on the run id, not on the workspace: this used to re-run on every
  // workspace refresh, so each poll during a run overwrote whatever the user
  // had typed with the running problem's strings — which made editing a
  // problem look like it did nothing at all.
  useEffect(() => {
    if (runId === null || runId === adoptedRunId.current || !workspace) return;
    adoptedRunId.current = runId;
    setFormInputs({
      initial: workspace.initial,
      modified: workspace.modified,
      target: workspace.target,
      answer: workspace.answer ?? '',
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, workspace]);

  // Fetch demos on mount
  useEffect(() => {
    setDemosLoading(true);
    getDemos()
      .then(setDemos)
      .catch(() => setDemos([]))
      .finally(() => setDemosLoading(false));
  }, []);

  const handleDemoSelect = useCallback(
    (value: string) => {
      setSelectedDemo(value);
      const demo = demos.find((d) => String(d.id) === value);
      if (demo) {
        setFormInputs({
          initial: demo.initial,
          modified: demo.modified,
          target: demo.target,
          answer: demo.answer ?? '',
          seed: String(demo.seed),
        });
      }
    },
    [demos, setFormInputs],
  );

  const labelStyle: React.CSSProperties = {
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

  return (
    <div className="flex-col" style={{ fontSize: 13 }}>
      <div style={fieldGroupStyle}>
        <label style={labelStyle} htmlFor="problem-initial">Initial</label>
        <input
          id="problem-initial"
          type="text"
          value={formInputs.initial}
          onChange={(e) => setFormInput('initial', e.target.value)}
          placeholder="abc"
          style={{ width: '100%' }}
          disabled={isRunning}
        />
      </div>

      <div style={fieldGroupStyle}>
        <label style={labelStyle} htmlFor="problem-modified">Modified</label>
        <input
          id="problem-modified"
          type="text"
          value={formInputs.modified}
          onChange={(e) => setFormInput('modified', e.target.value)}
          placeholder="abd"
          style={{ width: '100%' }}
          disabled={isRunning}
        />
      </div>

      <div style={fieldGroupStyle}>
        <label style={labelStyle} htmlFor="problem-target">Target</label>
        <input
          id="problem-target"
          type="text"
          value={formInputs.target}
          onChange={(e) => setFormInput('target', e.target.value)}
          placeholder="xyz"
          style={{ width: '100%' }}
          disabled={isRunning}
        />
      </div>

      <div style={fieldGroupStyle}>
        <label style={labelStyle} htmlFor="problem-answer">Answer (optional)</label>
        <input
          id="problem-answer"
          type="text"
          value={formInputs.answer}
          onChange={(e) => setFormInput('answer', e.target.value)}
          placeholder=""
          style={{ width: '100%' }}
          disabled={isRunning}
        />
      </div>

      <div style={fieldGroupStyle}>
        <label style={labelStyle} htmlFor="problem-seed">Seed (optional)</label>
        <input
          id="problem-seed"
          type="text"
          value={formInputs.seed}
          onChange={(e) => setFormInput('seed', e.target.value)}
          placeholder="0"
          style={{ width: '100%' }}
          disabled={isRunning}
        />
        <span className="text-xs text-muted">
          Same problem and seed reproduces a run exactly. Blank or 0 = seed 0.
        </span>
      </div>

      <div style={fieldGroupStyle}>
        <label style={labelStyle} htmlFor="problem-demo">Demo Problem</label>
        <select
          id="problem-demo"
          value={selectedDemo}
          onChange={(e) => handleDemoSelect(e.target.value)}
          style={{ width: '100%' }}
          disabled={isRunning || demosLoading}
        >
          <option value="">
            {demosLoading ? 'Loading...' : '-- Select Demo --'}
          </option>
          {demos.map((d) => (
            <option key={d.id} value={String(d.id)}>
              {d.name}: {d.initial} -&gt; {d.modified}; {d.target} -&gt; ?
            </option>
          ))}
        </select>
      </div>

      {/* Reset belongs to the problem, not to the run controls: it starts this
          same problem and seed over from scratch. Editing any field above is
          the other thing you might mean — that starts a *new* run instead. */}
      <div
        style={{
          borderTop: '1px solid var(--border)',
          paddingTop: 8,
          marginTop: 2,
        }}
      >
        <button
          onClick={handleReset}
          disabled={!hasRun || isRunning}
          title="Clear the workspace back to codelet 0, keeping this same problem and seed. Does not start running."
          style={{ width: '100%' }}
        >
          Reset to codelet 0
        </button>
        <div className="text-xs text-muted" style={{ marginTop: 4 }}>
          {hasRun
            ? `Clears run #${runId} back to bare strings, same problem and seed. Press Run to go again.`
            : 'Clears the current run back to bare strings, once one exists.'}
        </div>
        {resetError && (
          <div
            className="text-xs"
            style={{ marginTop: 4, color: 'var(--error)' }}
            role="alert"
          >
            {resetError}
          </div>
        )}
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
    </div>
  );
}
