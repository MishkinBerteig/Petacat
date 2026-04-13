// ---------------------------------------------------------------------------
// CoderackView -- Horizontal bar chart of codelet types by count and urgency
// ---------------------------------------------------------------------------

import { useRunStore } from '@/store/runStore';

/** Map urgency level to a display color. */
function urgencyColor(urgency: string): string {
  const u = urgency.toLowerCase();
  if (u.includes('extremely-low') || u.includes('very-low')) return '#1565c0';
  if (u.includes('low')) return '#42a5f5';
  if (u.includes('medium')) return '#ffc107';
  if (u.includes('high') && !u.includes('very') && !u.includes('extremely'))
    return '#ff9800';
  if (u.includes('very-high')) return '#f44336';
  if (u.includes('extremely-high')) return '#b71c1c';
  // Default: derive from simple numeric heuristic
  return '#90a4ae';
}

/** Heuristic: derive approximate urgency from codelet type name. */
function guessUrgency(typeName: string): string {
  if (typeName.includes('breaker')) return 'high';
  if (typeName.includes('scout')) return 'low';
  if (typeName.includes('evaluator')) return 'medium';
  if (typeName.includes('builder')) return 'medium';
  return 'medium';
}

export function CoderackView() {
  const coderack = useRunStore((s) => s.coderack);

  if (!coderack) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        No coderack data. Create or load a run.
      </div>
    );
  }

  const { type_counts, total_count } = coderack;
  const entries = Object.entries(type_counts).sort((a, b) => b[1] - a[1]);

  if (entries.length === 0 || total_count === 0) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        Empty
      </div>
    );
  }

  const maxCount = Math.max(...entries.map(([, c]) => c), 1);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <div className="text-xs text-muted" style={{ marginBottom: 4 }}>
        Total: {total_count}
      </div>
      {entries.map(([typeName, count]) => {
        const barPct = (count / maxCount) * 100;
        const color = urgencyColor(guessUrgency(typeName));
        return (
          <div key={typeName} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div
              className="mono text-xs"
              style={{
                width: 130,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                color: 'var(--text-secondary)',
                flexShrink: 0,
              }}
              title={typeName}
            >
              {typeName}
            </div>
            <div
              style={{
                flex: 1,
                height: 12,
                background: 'var(--bg-primary)',
                borderRadius: 2,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${barPct}%`,
                  height: '100%',
                  background: color,
                  borderRadius: 2,
                  transition: 'width 0.2s',
                  minWidth: 2,
                }}
              />
            </div>
            <div
              className="mono text-xs"
              style={{
                width: 28,
                textAlign: 'right',
                color: 'var(--text-primary)',
                flexShrink: 0,
              }}
            >
              {count}
            </div>
          </div>
        );
      })}
    </div>
  );
}
