// ---------------------------------------------------------------------------
// CoderackView -- Horizontal bar chart of codelet types by count and urgency
// ---------------------------------------------------------------------------

import { useState, useEffect, useCallback } from 'react';

import {
  clampCodeletPattern,
  getCodeletPatterns,
  unclampCodeletPattern,
  type CodeletPattern,
} from '@/api/client';
import { useRunStore } from '@/store/runStore';
import type { CoderackState } from '@/types';

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

/**
 * The bar chart, given its data — so a *recorded* coderack draws the same way a
 * live one does (WP3.9).
 */
export function CoderackBars({ coderack }: { coderack: CoderackState | null }) {
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

/** The live coderack: `CoderackBars` fed from the run store. */
/**
 * Clamping a codelet pattern pins a whole line of work at high urgency: a scout
 * together with the evaluator and builder that finish what it proposes. MetaCat offers
 * the same five patterns on its Options menu (`gui.ss:597-603`), and it is the third of
 * its three manual clamp handles, beside Slipnet nodes and themes.
 */
function CodeletPatternControls({ runId }: { runId: number }) {
  const [patterns, setPatterns] = useState<CodeletPattern[]>([]);
  const [clamped, setClamped] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    getCodeletPatterns(runId)
      .then(p => { if (live) setPatterns(p); })
      .catch(() => { if (live) setPatterns([]); });
    return () => { live = false; };
  }, [runId]);

  // A run change leaves nothing clamped by this panel.
  useEffect(() => { setClamped(null); }, [runId]);

  const toggle = useCallback(async (name: string) => {
    setBusy(true);
    try {
      if (clamped === name) {
        await unclampCodeletPattern(runId, name);
        setClamped(null);
      } else {
        if (clamped) await unclampCodeletPattern(runId, clamped);
        await clampCodeletPattern(runId, name);
        setClamped(name);
      }
    } finally {
      setBusy(false);
    }
  }, [runId, clamped]);

  if (patterns.length === 0) return null;

  return (
    <div style={{ marginTop: 6, borderTop: '1px solid var(--border)', paddingTop: 4 }}>
      <div className="text-xs text-muted" style={{ marginBottom: 3 }}>
        Clamp codelet pattern
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {patterns.map(p => (
          <button
            key={p.name}
            onClick={() => toggle(p.name)}
            disabled={busy}
            title={
              `${p.label}: pins ${p.entries.length} codelet types at high urgency ` +
              `(${p.entries.map(e => e.codelet_type).join(', ')}). ` +
              'Press again to release.'
            }
            style={{
              fontSize: 10,
              padding: '1px 5px',
              borderRadius: 2,
              border: '1px solid var(--border)',
              background: clamped === p.name ? 'rgba(255,193,7,0.25)' : 'transparent',
              color: clamped === p.name ? '#ffc107' : 'var(--text-secondary)',
              cursor: busy ? 'default' : 'pointer',
            }}
          >
            {p.label.replace(' codelet pattern', '')}
          </button>
        ))}
      </div>
    </div>
  );
}

export function CoderackView() {
  const coderack = useRunStore((s) => s.coderack);
  const runId = useRunStore((s) => s.runId);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        <CoderackBars coderack={coderack} />
      </div>
      {runId != null && <CodeletPatternControls runId={runId} />}
    </div>
  );
}
