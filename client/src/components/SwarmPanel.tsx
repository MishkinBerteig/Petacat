// ---------------------------------------------------------------------------
// Petacat -- Swarm: the answer distribution of the current problem
// ---------------------------------------------------------------------------
//
// One run shows one answer; Petacat's behaviour is the *distribution* of answers over
// seeds. The swarm (server/parallel/swarm.py) runs the problem in the Problem Input
// panel across N seeds on every core, each run byte-for-byte the serial run with that
// seed, and this panel shows what came back: the answer table, the status counts and a
// telemetry line. A few thousand runs take seconds, so the distribution is available
// almost at once instead of one run at a time.
//
// The swarm persists nothing (Fast-mode semantics), so it never touches the run store's
// current run; it only reads the form (and the engine-parameter overrides) from it.
// The parallel subsystem is a detachable plugin: when GET /api/swarm reports
// `available: false` the panel disables itself and says why.
// ---------------------------------------------------------------------------

import { useEffect, useState } from 'react';
import { useRunStore } from '@/store/runStore';
import { useHelp } from '@/hooks/useHelp';
import { describeApiError, getSwarmStatus, runSwarm } from '@/api/client';
import type { SwarmResult, SwarmStatus } from '@/types';
import type { ComponentHelpKey } from '@/constants/helpTopics';

const DEFAULT_COUNT = 200;
const MIN_COUNT = 1;
const FALLBACK_MAX_COUNT = 10_000;
const DEFAULT_MAX_STEPS = 20_000;

/** A small "?" that opens the control's own help topic. */
function ControlHelp({ topic, label }: { topic: ComponentHelpKey; label: string }) {
  const { showHelp } = useHelp();
  return (
    <button
      type="button"
      onClick={() => showHelp('component', topic)}
      title={`Show help for ${label}`}
      aria-label={`Show help for ${label}`}
      style={helpButtonStyle}
    >
      ?
    </button>
  );
}

function formatDuration(seconds: number): string {
  return seconds < 10 ? seconds.toFixed(2) : seconds.toFixed(1);
}

export function SwarmPanel() {
  const formInputs = useRunStore((s) => s.formInputs);
  const overrides = useRunStore((s) => s.parameterOverrides);

  const [status, setStatus] = useState<SwarmStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [count, setCount] = useState(String(DEFAULT_COUNT));
  const [seedStart, setSeedStart] = useState('1');
  const [maxSteps, setMaxSteps] = useState(String(DEFAULT_MAX_STEPS));
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SwarmResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSwarmStatus()
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch((err: unknown) => {
        if (!cancelled) setStatusError(describeApiError(err, 'check the swarm'));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const maxCount = status?.limits?.max_runs_per_request ?? FALLBACK_MAX_COUNT;
  const upperCount = Math.min(maxCount, FALLBACK_MAX_COUNT);
  const countN = Number(count);
  const seedN = Number(seedStart);
  const stepsN = Number(maxSteps);
  const countOk = Number.isInteger(countN) && countN >= MIN_COUNT && countN <= upperCount;
  const seedOk = Number.isInteger(seedN) && seedStart.trim() !== '';
  const stepsOk = Number.isInteger(stepsN) && stepsN >= 1;
  const hasProblem =
    formInputs.initial.trim() !== '' &&
    formInputs.modified.trim() !== '' &&
    formInputs.target.trim() !== '';

  const unavailable = status !== null && !status.available;
  const reasonDisabled = unavailable
    ? (status?.reason ?? 'The parallel subsystem is not installed.')
    : statusError
      ? statusError
      : !hasProblem
        ? 'Enter a problem in Problem Input first.'
        : !countOk
          ? `Seed count must be a whole number from ${MIN_COUNT} to ${upperCount.toLocaleString()}.`
          : !seedOk
            ? 'First seed must be a whole number.'
            : !stepsOk
              ? 'Max steps must be a whole number of at least 1.'
              : null;
  const disabled = running || (status === null && !statusError) || reasonDisabled !== null;

  const handleRun = async () => {
    setRunning(true);
    setError(null);
    try {
      const hasOverrides = Object.keys(overrides).length > 0;
      const res = await runSwarm({
        initial: formInputs.initial,
        modified: formInputs.modified,
        target: formInputs.target,
        answer: formInputs.answer.trim() !== '' ? formInputs.answer : null,
        count: countN,
        seed_start: seedN,
        max_steps: stepsN,
        include_runs: false,
        ...(hasOverrides ? { parameters: overrides } : {}),
      });
      setResult(res);
    } catch (err) {
      setError(describeApiError(err, 'run the swarm'));
    } finally {
      setRunning(false);
    }
  };

  const justification = formInputs.answer.trim() !== '';
  const t = result?.telemetry;

  return (
    <div style={groupStyle} data-testid="swarm-panel">
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <div style={groupLabelStyle}>Swarm</div>
        <ControlHelp topic="swarm" label="Swarm" />
      </div>
      <div className="text-xs text-muted" style={{ margin: '4px 0 8px' }}>
        Run this problem over many seeds on every core and see the answer
        distribution.{' '}
        {justification ? 'Justification mode: the problem has an answer.' : 'Discovery mode.'}
        {status?.available && status.workers > 0 ? ` ${status.workers} cores.` : ''}
      </div>

      {unavailable && (
        <div role="status" style={noticeStyle}>
          Swarm unavailable: {status?.reason ?? 'the parallel subsystem is not installed.'}{' '}
          Petacat itself runs unchanged; use Run for serial runs.
        </div>
      )}
      {statusError && !unavailable && (
        <div role="alert" style={noticeStyle}>
          {statusError}
        </div>
      )}

      <div style={rowStyle}>
        <div style={fieldGroupStyle}>
          <span style={{ display: 'flex', alignItems: 'center' }}>
            <label style={labelStyle} htmlFor="swarm-count">
              Seeds
            </label>
            <ControlHelp topic="swarm_seed_count" label="Seeds" />
          </span>
          <input
            id="swarm-count"
            type="number"
            min={MIN_COUNT}
            max={upperCount}
            value={count}
            onChange={(e) => setCount(e.target.value)}
            style={{ width: 80 }}
            disabled={running || unavailable}
          />
        </div>
        <div style={fieldGroupStyle}>
          <span style={{ display: 'flex', alignItems: 'center' }}>
            <label style={labelStyle} htmlFor="swarm-seed-start">
              First seed
            </label>
            <ControlHelp topic="swarm_first_seed" label="First seed" />
          </span>
          <input
            id="swarm-seed-start"
            type="number"
            value={seedStart}
            onChange={(e) => setSeedStart(e.target.value)}
            style={{ width: 80 }}
            disabled={running || unavailable}
          />
        </div>
        <div style={fieldGroupStyle}>
          <span style={{ display: 'flex', alignItems: 'center' }}>
            <label style={labelStyle} htmlFor="swarm-max-steps">
              Max steps
            </label>
            <ControlHelp topic="swarm_max_steps" label="Max steps" />
          </span>
          <input
            id="swarm-max-steps"
            type="number"
            min={1}
            value={maxSteps}
            onChange={(e) => setMaxSteps(e.target.value)}
            style={{ width: 90 }}
            disabled={running || unavailable}
          />
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <button
          onClick={() => void handleRun()}
          disabled={disabled}
          title={reasonDisabled ?? 'Run the current problem over the seeds on every core'}
        >
          {running ? 'Running swarm…' : `Run ${countOk ? countN.toLocaleString() : ''} seeds`}
        </button>
        <ControlHelp topic="swarm_run" label="Run swarm" />
      </div>
      {reasonDisabled !== null && !unavailable && !statusError && (
        <div className="text-xs text-muted" style={{ marginTop: 4 }}>
          {reasonDisabled}
        </div>
      )}
      {error && (
        <div role="alert" style={{ ...noticeStyle, marginTop: 6 }}>
          {error}
        </div>
      )}

      {result && t && (
        <div style={{ marginTop: 10 }} data-testid="swarm-result">
          <div className="text-xs mono" data-testid="swarm-telemetry">
            {t.runs.toLocaleString()} runs in {formatDuration(t.seconds)} s on {t.workers} cores,{' '}
            {Math.round(t.runs_per_second).toLocaleString()} runs/s
            {t.errors > 0 ? `, ${t.errors} with errors` : ''}
          </div>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Answer</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Count</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>%</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Quality</th>
                <th style={thStyle} aria-label="Share" />
              </tr>
            </thead>
            <tbody>
              {result.distribution.map((d) => (
                <tr key={d.answer} data-testid="swarm-row">
                  <td style={tdStyle} className="mono">
                    {d.answer}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{d.count.toLocaleString()}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {(d.fraction * 100).toFixed(1)}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {d.mean_quality === null ? '–' : d.mean_quality.toFixed(1)}
                  </td>
                  <td style={{ ...tdStyle, width: '30%' }}>
                    <div
                      role="presentation"
                      data-testid="swarm-bar"
                      style={{
                        height: 8,
                        width: `${Math.max(1, d.fraction * 100)}%`,
                        background: 'var(--text-accent, #6cf)',
                        borderRadius: 2,
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-xs text-muted" data-testid="swarm-statuses">
            Status:{' '}
            {Object.entries(result.statuses)
              .map(([k, v]) => `${k.replace(/_/g, ' ')} ${v.toLocaleString()}`)
              .join(', ')}
          </div>
          <div className="text-xs text-muted">
            {t.codelets_per_second.toLocaleString(undefined, { maximumFractionDigits: 0 })}{' '}
            codelets/s, backend {t.backend}, config {t.config_hash.slice(0, 8)}
          </div>
        </div>
      )}
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

const rowStyle: React.CSSProperties = { display: 'flex', gap: 10, flexWrap: 'wrap' };

const helpButtonStyle: React.CSSProperties = {
  background: 'none',
  border: '1px solid var(--border, #444)',
  borderRadius: 4,
  color: 'var(--text-secondary, #999)',
  cursor: 'pointer',
  fontSize: 10,
  lineHeight: 1,
  padding: '1px 4px',
  marginLeft: 4,
  fontFamily: 'var(--font-mono)',
};

const noticeStyle: React.CSSProperties = {
  fontSize: 11,
  padding: '4px 6px',
  marginBottom: 8,
  border: '1px solid var(--border)',
  borderRadius: 4,
  color: 'var(--text-secondary)',
};

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 11,
  margin: '6px 0',
};

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  fontWeight: 600,
  color: 'var(--text-secondary)',
  borderBottom: '1px solid var(--border)',
  padding: '2px 4px',
};

const tdStyle: React.CSSProperties = { padding: '2px 4px' };
