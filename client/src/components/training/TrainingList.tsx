// ---------------------------------------------------------------------------
// Petacat -- Trainings: the list of trainings and the executor's state
// ---------------------------------------------------------------------------

import type { TrainingExecutorInfo, TrainingSummary } from '@/types';
import { fmtInt, ProgressBar, StateBadge } from './shared';

/** "swarm, 17 cores, 34 runs in flight, 12,000 queued" or "serial (parallel plugin not installed)". */
export function describeExecutor(e: TrainingExecutorInfo): string {
  if (e.kind === 'serial') return 'serial (parallel plugin not installed)';
  return `swarm, ${fmtInt(e.workers)} cores, ${fmtInt(e.in_flight)} runs in flight, ${fmtInt(e.queued_runs)} queued`;
}

interface Props {
  trainings: TrainingSummary[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export function TrainingList({ trainings, selectedId, onSelect }: Props) {
  if (trainings.length === 0) {
    return (
      <div className="text-muted text-sm" style={{ padding: 8 }}>
        No trainings yet. Use New training to run many problems over many seeds.
      </div>
    );
  }
  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }} data-testid="training-list">
      {trainings.map((b) => {
        const selected = b.id === selectedId;
        return (
          <li key={b.id}>
            <button
              type="button"
              onClick={() => onSelect(b.id)}
              aria-current={selected ? 'true' : undefined}
              data-testid="training-item"
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
                  {b.name || `Training ${b.id}`}
                </span>
                <StateBadge state={b.state} />
              </div>
              <div className="text-xs text-muted" style={{ margin: '2px 0 3px' }}>
                {fmtInt(b.problems.finished)}/{fmtInt(b.problems.total)} problems ·{' '}
                {fmtInt(b.runs.done)}/{fmtInt(b.runs.total)} runs
              </div>
              <ProgressBar done={b.runs.done} total={b.runs.total} label={`Progress of ${b.name || `training ${b.id}`}`} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
