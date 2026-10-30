// ---------------------------------------------------------------------------
// Petacat -- Training: the episode's Episodic Memory (read-only)
// ---------------------------------------------------------------------------
//
// Follows MemoryView's presentation (answer cards with the quality colour, snag
// cards with the explanation) without its actions: those act on a dashboard run, and a
// Training's memory belongs to the episode.
// ---------------------------------------------------------------------------

import { useState } from 'react';
import { describeApiError, getTrainingMemory } from '@/api/client';
import type { TrainingMemory, TrainingSummary } from '@/types';
import { errorStyle, fmtInt, usePolling } from './shared';

const POLL_RUNNING_MS = 3000;
const POLL_IDLE_MS = 10000;

function qualityColor(quality: number): string {
  if (quality > 70) return 'var(--success)';
  if (quality > 40) return 'var(--warning)';
  return 'var(--error)';
}

const cardStyle: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 4,
  padding: '4px 8px',
  fontSize: 11,
};

export function MemoryTab({ training }: { training: TrainingSummary }) {
  const [memory, setMemory] = useState<TrainingMemory | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Refetched when a merge has happened, and slowly otherwise.
  usePolling(
    async () => {
      try {
        setMemory(await getTrainingMemory(training.id));
        setError(null);
      } catch (err) {
        setError(describeApiError(err, "load this Training's episode memory"));
      }
    },
    training.state === 'running' ? POLL_RUNNING_MS : POLL_IDLE_MS,
    `${training.id}|${training.memory_version}`,
  );

  return (
    <div data-testid="memory-tab">
      <div className="text-xs text-muted" style={{ marginBottom: 6 }}>
        This Training&apos;s own episode memory (Training Mode, not Metacat Mode&apos;s Episodic Memory), newest first. A run's additions reach it when the run finishes, and only
        runs that start afterwards can use them.
        {training.memory_version !== null && <> Version {fmtInt(training.memory_version)}.</>}
      </div>
      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}
      {memory && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
          <div>
            <div className="text-xs" style={{ fontWeight: 700, marginBottom: 4 }}>
              Answers ({fmtInt(memory.answers.length)})
            </div>
            {memory.answers.length === 0 && <div className="text-xs text-muted">No answers stored.</div>}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 360, overflow: 'auto' }}>
              {memory.answers.map((a) => (
                <div key={a.answer_id} style={cardStyle} data-testid="memory-answer">
                  <span className="mono">{a.problem.join(' → ')}</span>{' '}
                  <span style={{ color: qualityColor(a.quality), fontWeight: 700 }}>q {a.quality}</span>{' '}
                  <span className="text-muted">T {a.temperature.toFixed(0)}</span>
                  <div className="text-muted">{a.top_rule_description}</div>
                  <div className="text-muted">{a.bottom_rule_description}</div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="text-xs" style={{ fontWeight: 700, marginBottom: 4 }}>
              Snags ({fmtInt(memory.snags.length)})
            </div>
            {memory.snags.length === 0 && <div className="text-xs text-muted">No snags stored.</div>}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 360, overflow: 'auto' }}>
              {memory.snags.map((s) => (
                <div key={s.snag_id} style={cardStyle} data-testid="memory-snag">
                  <span className="mono">{s.problem.join(' → ')}</span>{' '}
                  <span className="text-muted">
                    {fmtInt(s.codelet_count)} codelets, T {s.temperature.toFixed(0)}
                  </span>
                  <div>{s.description}</div>
                  {s.explanation && <div className="text-muted">{s.explanation}</div>}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
