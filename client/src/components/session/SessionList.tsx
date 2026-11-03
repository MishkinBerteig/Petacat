// ---------------------------------------------------------------------------
// Petacat -- Training Mode Sessions: the list of sessions and the executor's state
// ---------------------------------------------------------------------------

import type { SessionExecutorInfo, SessionSummary } from '@/types';
import { fmtInt, ProgressBar, StateBadge } from './shared';

/**
 * The run mode the server's executor gives Training Mode Sessions, as the user's two words and the
 * server's own:
 * "Run mode: multi-core (swarm, 17 workers; 34 runs in flight, 12,000 queued)" or
 * "Run mode: single-threaded (serial; parallel plugin not installed)".
 * Run mode is orthogonal to Training Mode and Metacat Mode; this only reports it.
 */
export function describeExecutor(e: SessionExecutorInfo): string {
  if (e.kind === 'serial') return 'Run mode: single-threaded (serial; parallel plugin not installed)';
  return `Run mode: multi-core (swarm, ${fmtInt(e.workers)} workers; ${fmtInt(e.in_flight)} runs in flight, ${fmtInt(e.queued_runs)} queued)`;
}

interface Props {
  sessions: SessionSummary[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export function SessionList({ sessions, selectedId, onSelect }: Props) {
  if (sessions.length === 0) {
    return (
      <div className="text-muted text-sm" style={{ padding: 8 }}>
        No sessions yet. Use New session to run many problems over many seeds.
      </div>
    );
  }
  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }} data-testid="session-list">
      {sessions.map((b) => {
        const selected = b.id === selectedId;
        return (
          <li key={b.id}>
            <button
              type="button"
              onClick={() => onSelect(b.id)}
              aria-current={selected ? 'true' : undefined}
              data-testid="session-item"
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '6px 8px',
                background: selected ? 'var(--bg-highlight, var(--bg-secondary))' : 'transparent',
                border: 'none',
                borderBottom: '1px solid var(--border)',
                borderLeft: selected ? '3px solid var(--text-accent)' : '3px solid transparent',
                color: 'var(--text-primary)',
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontWeight: 600, fontSize: 12, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {b.name || `Training Mode Session ${b.id}`}
                </span>
                <StateBadge state={b.state} activity={b.activity} />
              </div>
              <div className="text-xs text-muted" style={{ margin: '2px 0 3px' }}>
                {fmtInt(b.problems.finished)}/{fmtInt(b.problems.total)} problems ·{' '}
                {fmtInt(b.runs.done)}/{fmtInt(b.runs.total)} runs
              </div>
              <ProgressBar done={b.runs.done} total={b.runs.total} label={`Progress of ${b.name || `session ${b.id}`}`} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
