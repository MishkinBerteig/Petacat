// ---------------------------------------------------------------------------
// Petacat -- Trainings: small pieces and styles shared by the Trainings components
// ---------------------------------------------------------------------------

import { useEffect, useRef } from 'react';
import { useHelp } from '@/hooks/useHelp';
import type { ComponentHelpKey } from '@/constants/helpTopics';
import type { TrainingState } from '@/types';

/** A small "?" that opens the control's own help topic. */
export function ControlHelp({ topic, label }: { topic: ComponentHelpKey; label: string }) {
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

/**
 * Call `fn` now and then every `intervalMs`, until unmounted. A `null` interval calls it
 * once. A change of `restartKey` fetches at once; a change of `intervalMs` only changes
 * the delay. Failures are the callback's to report; a throw only ends that tick.
 */
export function usePolling(
  fn: () => Promise<unknown> | unknown,
  intervalMs: number | null,
  restartKey: unknown = null,
): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const intervalRef = useRef(intervalMs);
  intervalRef.current = intervalMs;
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const tickRef = useRef<() => void>(() => {});
  const inFlightRef = useRef(false);

  // A new key (a new filter, another training) fetches at once.
  useEffect(() => {
    let stopped = false;
    const schedule = () => {
      if (stopped || intervalRef.current === null) return;
      timerRef.current = setTimeout(() => void tick(), intervalRef.current);
    };
    const tick = async () => {
      timerRef.current = undefined;
      inFlightRef.current = true;
      try {
        await fnRef.current();
      } catch {
        // reported by the callback itself
      }
      inFlightRef.current = false;
      schedule();
    };
    tickRef.current = schedule;
    void tick();
    return () => {
      stopped = true;
      tickRef.current = () => {};
      if (timerRef.current !== undefined) clearTimeout(timerRef.current);
      timerRef.current = undefined;
    };
  }, [restartKey]);

  // A new interval takes effect from now, without an extra fetch.
  useEffect(() => {
    if (inFlightRef.current) return; // a fetch is in flight; it will reschedule
    if (timerRef.current !== undefined) clearTimeout(timerRef.current);
    timerRef.current = undefined;
    tickRef.current();
  }, [intervalMs]);
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

export function fmtInt(n: number): string {
  return n.toLocaleString();
}

export function fmtPct(fraction: number | null | undefined, digits = 1): string {
  return fraction === null || fraction === undefined ? '–' : `${(fraction * 100).toFixed(digits)}%`;
}

export function fmtEta(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '–';
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${String(s % 60).padStart(2, '0')} s`;
  const h = Math.floor(m / 60);
  return `${h} h ${String(m % 60).padStart(2, '0')} min`;
}

/** Server timestamps are naive UTC ISO strings. */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '–';
  const hasZone = /(Z|[+-]\d\d:?\d\d)$/.test(iso);
  const d = new Date(hasZone ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function fmtRate(r: number | null | undefined): string {
  return r === null || r === undefined ? '–' : `${r.toFixed(r < 10 ? 2 : 1)} runs/s`;
}

/** Plain words for the outcome keys that are not answers. */
export function outcomeLabel(key: string): string {
  switch (key) {
    case '*CAP*':
      return 'gave up at max codelets';
    case '*ERROR*':
      return 'error';
    case '*NONE*':
      return 'no answer';
    default:
      return key;
  }
}

// ---------------------------------------------------------------------------
// Badge and progress bar
// ---------------------------------------------------------------------------

const STATE_COLOUR: Record<TrainingState, string> = {
  running: 'var(--text-accent)',
  idle: 'var(--text-secondary)',
  paused: 'var(--warning)',
  finished: 'var(--success)',
  cancelled: 'var(--error)',
  stalled: 'var(--error)',
};

export function StateBadge({ state }: { state: TrainingState }) {
  return (
    <span
      data-testid="state-badge"
      style={{
        fontSize: 10,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: 0.5,
        padding: '1px 6px',
        borderRadius: 3,
        border: `1px solid ${STATE_COLOUR[state]}`,
        color: STATE_COLOUR[state],
      }}
    >
      {state}
    </span>
  );
}

export function ProgressBar({ done, total, label }: { done: number; total: number; label: string }) {
  const pct = total > 0 ? Math.min(100, (done / total) * 100) : 0;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={done}
      style={{ height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}
    >
      <div style={{ height: '100%', width: `${pct}%`, background: 'var(--text-accent)' }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

export const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: 4,
  padding: 10,
};

export const sectionLabelStyle: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: 0.6,
  color: 'var(--text-secondary)',
};

export const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 11,
  color: 'var(--text-secondary)',
  marginBottom: 2,
};

export const fieldGroupStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 3,
  marginBottom: 8,
};

export const helpButtonStyle: React.CSSProperties = {
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

export const noticeStyle: React.CSSProperties = {
  fontSize: 11,
  padding: '4px 6px',
  marginBottom: 8,
  border: '1px solid var(--border)',
  borderRadius: 4,
  color: 'var(--text-secondary)',
};

export const errorStyle: React.CSSProperties = {
  ...noticeStyle,
  borderColor: 'var(--error)',
  color: 'var(--error)',
};

export const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 11,
};

export const thStyle: React.CSSProperties = {
  textAlign: 'left',
  fontWeight: 600,
  color: 'var(--text-secondary)',
  borderBottom: '1px solid var(--border)',
  padding: '3px 4px',
  whiteSpace: 'nowrap',
};

export const tdStyle: React.CSSProperties = { padding: '3px 4px' };

export const linkButtonStyle: React.CSSProperties = {
  fontSize: 11,
  padding: '2px 8px',
  borderRadius: 3,
  border: '1px solid var(--border)',
  color: 'var(--text-primary)',
  textDecoration: 'none',
  background: 'transparent',
  cursor: 'pointer',
};
