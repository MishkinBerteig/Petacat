// ---------------------------------------------------------------------------
// NormalRunReview -- a recorded Run's start state, end state, and what changed
// ---------------------------------------------------------------------------
//
// Normal mode records the complete Petacat state at the two Run boundaries and
// nothing between, so this is the whole of what there is to look at: the state
// before the first codelet, the state after the last, and the difference.
//
// The difference is served pre-computed. Both captures are a few hundred kilobytes
// and almost entirely identical -- 59 Slipnet nodes, the same four strings, the same
// theme clusters -- so shipping both and diffing here would move a megabyte to show a
// dozen facts. `GET /api/review/runs/{id}/comparison` decides what is worth seeing.
// ---------------------------------------------------------------------------

import { useEffect, useState } from 'react';
import { describeApiError, getCapture, getRunComparison } from '@/api/client';
import type { RecordedRun, RecordedState, RunComparison } from '@/types';
import { RecordedStatePanels } from './RecordedStateViews';

type Boundary = 'start' | 'end';

export function NormalRunReview({ run }: { run: RecordedRun }) {
  const [boundary, setBoundary] = useState<Boundary>('end');
  const [captures, setCaptures] = useState<Partial<Record<Boundary, RecordedState>>>({});
  const [comparison, setComparison] = useState<RunComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setCaptures({});
    setComparison(null);

    Promise.all([
      getCapture(run.run_id, 'start'),
      getCapture(run.run_id, 'end'),
      getRunComparison(run.run_id),
    ])
      .then(([start, end, cmp]) => {
        if (cancelled) return;
        setCaptures({ start, end });
        setComparison(cmp);
      })
      .catch(
        (e) =>
          !cancelled &&
          setError(describeApiError(e, `read the record for run #${run.run_id}`)),
      )
      .finally(() => !cancelled && setLoading(false));

    return () => {
      cancelled = true;
    };
  }, [run.run_id]);

  if (run.capture_count === 0) {
    return (
      <div className="text-muted text-sm" style={{ padding: 12 }}>
        Run #{run.run_id} recorded no state captures. A Fast Run writes nothing at
        all — that is the mode, not a gap in the record.
      </div>
    );
  }
  if (loading) {
    return <div className="text-muted text-sm" style={{ padding: 12 }}>Loading captures…</div>;
  }
  if (error) {
    return (
      <div role="alert" style={{ padding: 12, color: 'var(--error)', fontSize: 12 }}>
        {error}
      </div>
    );
  }

  const shown = captures[boundary];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {comparison && <ComparisonSummary comparison={comparison} />}

      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span className="text-xs text-muted">Recorded state:</span>
        {(['start', 'end'] as Boundary[]).map((b) => (
          <button
            key={b}
            onClick={() => setBoundary(b)}
            aria-pressed={boundary === b}
            style={{
              fontSize: 11,
              padding: '2px 10px',
              borderRadius: 3,
              cursor: 'pointer',
              background: boundary === b ? 'var(--bg-highlight, #2a2a2a)' : 'transparent',
              border: `1px solid ${boundary === b ? 'var(--text-accent)' : 'var(--border)'}`,
              color: boundary === b ? 'var(--text-accent)' : 'var(--text-secondary)',
              fontWeight: boundary === b ? 700 : 400,
            }}
          >
            Run {b}
            {captures[b] && (
              <span className="text-muted" style={{ marginLeft: 5 }}>
                c:{captures[b]!.codelet_count} T:{captures[b]!.temperature.toFixed(0)}
              </span>
            )}
          </button>
        ))}
      </div>

      {shown && <RecordedStatePanels state={shown} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The comparison
// ---------------------------------------------------------------------------

function ComparisonSummary({ comparison }: { comparison: RunComparison }) {
  const { codelets, temperature, structures, slipnet, themes, trace, memory } = comparison;

  const builtBonds = sum(structures.bonds.built);
  const builtGroups = sum(structures.groups.built);
  const builtBridges = sum(structures.bridges.built);
  const builtRules = sum(structures.rules.built);

  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 4,
        background: 'var(--bg-card)',
        padding: 8,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-accent)' }}>
        Start → end
      </div>

      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <Stat label="codelets" value={String(codelets.executed)} />
        <Stat
          label="temperature"
          value={`${temperature.start.toFixed(0)} → ${temperature.end.toFixed(0)}`}
          delta={temperature.delta}
          /* Falling temperature is the system organising the problem, so a drop is
             the good direction and is coloured as such. */
          goodWhenNegative
        />
        <Stat label="bonds" value={`+${builtBonds}`} />
        <Stat label="groups" value={`+${builtGroups}`} />
        <Stat label="bridges" value={`+${builtBridges}`} />
        <Stat label="rules" value={`+${builtRules}`} />
        <Stat
          label="trace events"
          value={`${trace.events_at_start} → ${trace.events_at_end}`}
        />
        <Stat
          label="memory answers"
          value={`${memory.answers_at_start} → ${memory.answers_at_end}`}
        />
      </div>

      {comparison.rules.top.length + comparison.rules.bottom.length > 0 && (
        <Section title="Rules the Run ended holding">
          <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11 }}>
            {[...comparison.rules.top, ...comparison.rules.bottom].map((r: any, i) => (
              <li key={i} style={{ fontFamily: 'var(--font-mono)' }}>
                <span className="text-muted">{r.type}</span> {r.english}{' '}
                <span className="text-muted">(q={r.quality})</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {slipnet.moved.length > 0 && (
        <Section
          title={`Concepts recruited (${slipnet.moved_count} moved, top ${slipnet.moved.length})`}
        >
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {slipnet.moved.map((m) => (
              <span
                key={m.node}
                title={`${m.node}: ${m.start.toFixed(1)} → ${m.end.toFixed(1)}`}
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  padding: '1px 5px',
                  borderRadius: 3,
                  border: '1px solid var(--border)',
                  color: m.delta > 0 ? '#4caf50' : '#f44336',
                }}
              >
                {m.node.replace('plato-', '')} {m.delta > 0 ? '+' : ''}
                {m.delta.toFixed(0)}
              </span>
            ))}
          </div>
        </Section>
      )}

      {themes.dominant_at_end.length > 0 && (
        <Section title="Themes dominant at the end">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {themes.dominant_at_end.map((t, i) => (
              <span
                key={i}
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  padding: '1px 5px',
                  borderRadius: 3,
                  border: '1px solid #ffd700',
                  color: '#ffd700',
                }}
              >
                {t.theme_type}: {t.dimension.replace('plato-', '')} = {t.relation}
              </span>
            ))}
          </div>
        </Section>
      )}

      {memory.added_answers.length > 0 && (
        <Section title="Left in the Training Session's Episodic Memory">
          <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11 }}>
            {memory.added_answers.map((a, i) => (
              <li key={i} style={{ fontFamily: 'var(--font-mono)' }}>
                {a.problem.join(' ')} — quality {Math.round(a.quality)}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-muted" style={{ marginBottom: 3 }}>{title}</div>
      {children}
    </div>
  );
}

function Stat({
  label,
  value,
  delta,
  goodWhenNegative,
}: {
  label: string;
  value: string;
  delta?: number;
  goodWhenNegative?: boolean;
}) {
  const good = delta === undefined ? null : goodWhenNegative ? delta < 0 : delta > 0;
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <span className="text-xs text-muted">{label}</span>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>
        {value}
        {delta !== undefined && delta !== 0 && (
          <span style={{ marginLeft: 4, fontSize: 10, color: good ? '#4caf50' : '#ff9800' }}>
            {delta > 0 ? '+' : ''}
            {delta.toFixed(0)}
          </span>
        )}
      </span>
    </div>
  );
}

function sum(counts: Record<string, number>): number {
  return Object.values(counts).reduce((a, b) => a + b, 0);
}
