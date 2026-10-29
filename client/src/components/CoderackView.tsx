// ---------------------------------------------------------------------------
// CoderackView -- Metacat's coderack window: counts and selection probabilities
// ---------------------------------------------------------------------------

import { useState, useEffect, useCallback } from 'react';

import {
  clampCodeletPattern,
  getCodeletPatterns,
  unclampCodeletPattern,
  type CodeletPattern,
} from '@/api/client';
import { useMomentStore } from '@/store/momentStore';
import { useRunStore } from '@/store/runStore';
import type { CoderackState } from '@/types';

/**
 * Metacat's greys for a slot whose urgency is clamped (`urgency-color`,
 * `coderack.ss:44-53`; thresholds `coderack.ss:25-31`, colours `constants.ss:943-949`).
 */
function clampColor(urgency: number): string {
  const tiers: [number, string][] = [
    [7, '#666666'],
    [21, '#808080'],
    [35, '#999999'],
    [49, '#b3b3b3'],
    [63, '#cccccc'],
    [77, '#e6e6e6'],
  ];
  for (const [limit, colour] of tiers) if (urgency <= limit) return colour;
  return '#ffffff';
}

/** `%last-codelet-color%` (`constants.ss:940`): "hot pink". */
const LAST_CODELET_COLOR = '#ff69b4';

/**
 * The coderack window, given its data -- so a *recorded* coderack draws the same way a
 * live one does (WP3.9).
 *
 * As Metacat's window (`coderack-graphics.ss`): a slot for every codelet type, the
 * number of codelets of that type on the left, and a bar for the type's relative
 * probability of being chosen to run next. The probability is the engine's own (the
 * urgency-weighted, temperature-adjusted figure the choice uses), served with the
 * state; nothing here estimates it. The type that ran last is shown in pink, and a type
 * whose urgency is clamped has a grey slot. The count column and the last-type marker
 * are the two switches Metacat has on its Options menu.
 */
export function CoderackBars({
  coderack,
  showCounts = true,
  showLast = true,
}: {
  coderack: CoderackState | null;
  showCounts?: boolean;
  showLast?: boolean;
}) {
  if (!coderack) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        No coderack data. Create or load a run.
      </div>
    );
  }

  const { type_counts, total_count } = coderack;
  const probabilities = coderack.type_probabilities ?? {};
  const clamped = coderack.clamped_urgencies ?? {};
  const names = coderack.codelet_types ?? Object.keys(type_counts).sort();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <div
        className="text-xs text-muted"
        style={{ display: 'flex', fontStyle: 'italic', marginBottom: 2 }}
      >
        <div style={{ width: showCounts ? 164 : 130, flexShrink: 0 }}>Codelet Type</div>
        <div style={{ flex: 1 }}>Selection Probability</div>
      </div>
      {names.map((typeName) => {
        const count = type_counts[typeName] ?? 0;
        const probability = probabilities[typeName] ?? 0;
        const isLast = showLast && coderack.last_codelet_type === typeName;
        const clampedAt = clamped[typeName];
        const slot = isLast
          ? LAST_CODELET_COLOR
          : clampedAt !== undefined
            ? clampColor(clampedAt)
            : 'transparent';
        const dark = isLast || clampedAt !== undefined;
        return (
          <div
            key={typeName}
            data-testid={`coderack-row-${typeName}`}
            data-last={isLast ? 'true' : undefined}
            style={{ display: 'flex', alignItems: 'center', gap: 4 }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                width: showCounts ? 160 : 130,
                flexShrink: 0,
                background: slot,
                borderRadius: 2,
              }}
            >
              {showCounts && (
                <div
                  className="mono text-xs"
                  style={{
                    width: 28,
                    textAlign: 'right',
                    color: dark ? '#000' : 'var(--text-primary)',
                    flexShrink: 0,
                  }}
                >
                  {count}
                </div>
              )}
              <div
                className="mono text-xs"
                style={{
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  color: dark ? '#000' : 'var(--text-secondary)',
                }}
                title={typeName}
              >
                {typeName}
              </div>
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
              {/* Metacat shows at least a sliver for any non-zero probability. */}
              {probability > 0 && (
                <div
                  data-testid={`coderack-bar-${typeName}`}
                  style={{
                    width: `${probability * 100}%`,
                    height: '100%',
                    background: 'var(--text-accent)',
                    borderRadius: 2,
                    transition: 'width 0.2s',
                    minWidth: 2,
                  }}
                />
              )}
            </div>
          </div>
        );
      })}
      {showCounts && (
        <div
          className="text-xs"
          style={{
            display: 'flex',
            borderTop: '2px double var(--border)',
            marginTop: 2,
            paddingTop: 2,
          }}
        >
          <div className="mono" style={{ width: 28, textAlign: 'right' }}>
            {total_count}
          </div>
          <div style={{ marginLeft: 8 }} className="text-muted">
            Total
          </div>
        </div>
      )}
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
  // Metacat's "Show codelet counts" and "Show last codelet type" (`gui.ss:652-660`).
  const [showCounts, setShowCounts] = useState(true);
  const [showLast, setShowLast] = useState(true);
  const displayed = useMomentStore((s) => s.displayed);
  if (displayed) {
    // A redisplayed moment blanks the Coderack (`blank-window "Coderack"`), or, for a
    // clamp, shows the codelet pattern it clamped (`display-patterns ... "Codelet Pattern"`).
    const { title, entries } = displayed.picture.coderack;
    return (
      <div data-testid="coderack-moment" style={{ height: '100%', overflow: 'auto' }}>
        <div className="text-xs" style={{ fontWeight: 600, color: 'var(--text-accent)' }}>
          {title}
        </div>
        {entries.length === 0 ? (
          <div className="text-muted text-xs" style={{ padding: 8 }}>
            (blank while a past moment is shown)
          </div>
        ) : (
          entries.map((e) => (
            <div key={e.type} className="mono text-xs" style={{ display: 'flex', gap: 8 }}>
              <span style={{ flex: 1 }}>{e.type}</span>
              <span>{e.urgency}</span>
            </div>
          ))
        )}
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        <CoderackBars coderack={coderack} showCounts={showCounts} showLast={showLast} />
      </div>
      <div
        className="text-xs text-muted"
        style={{ display: 'flex', gap: 12, marginTop: 4 }}
      >
        <label style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <input
            type="checkbox"
            checked={showCounts}
            onChange={(e) => setShowCounts(e.target.checked)}
          />
          Show codelet counts
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <input
            type="checkbox"
            checked={showLast}
            onChange={(e) => setShowLast(e.target.checked)}
          />
          Show last codelet type
        </label>
      </div>
      {runId != null && <CodeletPatternControls runId={runId} />}
    </div>
  );
}
