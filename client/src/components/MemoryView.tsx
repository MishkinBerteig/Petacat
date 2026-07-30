// ---------------------------------------------------------------------------
// MemoryView -- Cards for episodic memory answer descriptions
// ---------------------------------------------------------------------------

import { useCallback, useState } from 'react';
import { useRunStore } from '@/store/runStore';
import type { AnswerComparisonResult } from '@/types';

function qualityColor(quality: number): string {
  if (quality > 70) return 'var(--success)';
  if (quality > 40) return 'var(--warning)';
  return 'var(--error)';
}

/** §4.7.5 renders an answer's activation as a grey-scale fade: weakly-activated
 *  answers "appear to fade into the background of Metacat's memory". */
function activationOpacity(activation: number | undefined): number {
  if (activation === undefined) return 1;
  return 0.35 + 0.65 * Math.max(0, Math.min(100, activation)) / 100;
}

const THEME_LABELS: Record<string, string> = {
  'plato-string-position-category': 'string-position',
  'plato-alphabetic-position-category': 'alphabetic-position',
  'plato-direction-category': 'direction',
  'plato-group-category': 'group-type',
  'plato-bond-facet': 'bond-facet',
  'plato-letter-category': 'letter-category',
  'plato-length': 'length',
  'plato-object-category': 'object-type',
  'plato-bond-category': 'bond-type',
};

function themeChips(
  themes: Record<string, string> | undefined,
  tone: string,
  title: string,
) {
  const entries = Object.entries(themes ?? {});
  if (entries.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 3 }} title={title}>
      {entries.map(([dim, rel]) => (
        <span
          key={dim}
          className="mono"
          style={{
            fontSize: 9,
            padding: '1px 4px',
            borderRadius: 2,
            border: `1px solid ${tone}`,
            color: tone,
          }}
        >
          {(THEME_LABELS[dim] ?? dim.replace('plato-', ''))}:{rel}
        </span>
      ))}
    </div>
  );
}

export function MemoryView() {
  const memory = useRunStore((s) => s.memory);
  const refreshMemory = useRunStore((s) => s.refreshMemory);
  const [selected, setSelected] = useState<number[]>([]);
  const [comparison, setComparison] = useState<AnswerComparisonResult | null>(null);
  const [comparing, setComparing] = useState(false);

  const toggleSelected = useCallback((answerId: number) => {
    setComparison(null);
    setSelected((prev) =>
      prev.includes(answerId)
        ? prev.filter((id) => id !== answerId)
        : [...prev, answerId].slice(-2),
    );
  }, []);

  const handleCompare = useCallback(async () => {
    if (selected.length !== 2) return;
    setComparing(true);
    try {
      const res = await fetch('/api/memory/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answer_id_1: selected[0], answer_id_2: selected[1] }),
      });
      setComparison(res.ok ? await res.json() : null);
    } catch {
      setComparison(null);
    } finally {
      setComparing(false);
    }
  }, [selected]);

  const handleClear = useCallback(async () => {
    if (!window.confirm('Clear all episodic memory? This cannot be undone.')) return;
    try {
      await fetch('/api/memory', { method: 'DELETE' });
      await refreshMemory();
    } catch {
      // ignore
    }
  }, [refreshMemory]);

  if (!memory) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        No memory data loaded.
      </div>
    );
  }

  const { answers, snags } = memory;
  const isEmpty = answers.length === 0 && snags.length === 0;
  /**
   * A Fast Run is handed an ephemeral Episodic Memory of its own, so that it can
   * contribute nothing to the Training Session — which is the whole of what Fast
   * promises. This panel used to show the shared database memory regardless, which
   * made it a straightforward lie about the run on screen: the answers listed were
   * ones the run could not possibly be reminded of, and the answer it went on to find
   * never appeared among them.
   */
  const isEphemeral = memory.scope === 'run';

  return (
    <div style={{ fontSize: 12 }}>
      {isEphemeral && (
        <div
          className="text-xs"
          style={{
            marginBottom: 6,
            padding: '4px 6px',
            borderRadius: 3,
            border: '1px solid var(--warning)',
            color: 'var(--warning)',
          }}
        >
          This run's own memory, not the shared one. A <strong>Fast</strong> run gets
          an ephemeral Episodic Memory that starts empty, is not read from the
          database, and is discarded when the run is — so nothing here reaches the
          Training Session and nothing from it reaches here.
        </div>
      )}

      {/* Header with counts and clear button */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 6,
        }}
      >
        <span className="text-muted text-xs">
          {answers.length} answer{answers.length !== 1 ? 's' : ''}
          {snags.length > 0 && `, ${snags.length} snag${snags.length !== 1 ? 's' : ''}`}
        </span>
        {/* Both actions address the *shared* memory — comparison by answer id
            against `_global_memory`, clearing by deleting the stored rows — so
            neither is offered while an ephemeral one is on screen. Offering them
            would act on answers other than the ones being looked at, and the ids
            of the two memories are independent counters that collide. */}
        <span style={{ display: 'flex', gap: 8 }}>
          {answers.length >= 2 && !isEphemeral && (
            <button
              onClick={handleCompare}
              disabled={selected.length !== 2 || comparing}
              title="Compare the two selected answers (§4.7.3)"
              style={{
                fontSize: 10,
                color: selected.length === 2 ? 'var(--text-accent)' : 'var(--text-secondary)',
              }}
            >
              {comparing ? 'Comparing...' : `Compare (${selected.length}/2)`}
            </button>
          )}
          {!isEmpty && !isEphemeral && (
            <button
              onClick={handleClear}
              style={{ fontSize: 10, color: 'var(--error)' }}
            >
              Clear Memory
            </button>
          )}
        </span>
      </div>

      {/* Comparison commentary (§4.7.4) */}
      {comparison && (
        <div
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--text-accent)',
            borderRadius: 4,
            padding: 8,
            marginBottom: 8,
            fontSize: 11,
            lineHeight: 1.5,
          }}
        >
          {comparison.commentary.paragraphs.map((para, i) => (
            <p key={i} style={{ margin: i === 0 ? 0 : '6px 0 0' }}>
              {para}
            </p>
          ))}
        </div>
      )}

      {/* Empty state */}
      {isEmpty && (
        <div className="text-muted text-sm" style={{ textAlign: 'center', padding: 8 }}>
          No answers stored
        </div>
      )}

      {/* Answer cards */}
      {answers.map((ans) => (
        <div
          key={ans.answer_id}
          onClick={() => toggleSelected(ans.answer_id)}
          title={`Reminding activation ${(ans.activation ?? 0).toFixed(0)} — click to select for comparison`}
          style={{
            background: 'var(--bg-card)',
            borderRadius: 4,
            padding: 8,
            marginBottom: 6,
            cursor: 'pointer',
            opacity: activationOpacity(ans.activation),
            border: selected.includes(ans.answer_id)
              ? '1px solid var(--text-accent)'
              : '1px solid var(--border)',
          }}
        >
          {/* Problem string */}
          <div
            className="mono text-xs"
            style={{
              marginBottom: 4,
              color: 'var(--text-primary)',
              display: 'flex',
              justifyContent: 'space-between',
            }}
          >
            <span>{ans.problem.join(' -> ')}</span>
            {ans.activation !== undefined && (
              <span className="text-muted" style={{ fontSize: 9 }}>
                act {ans.activation.toFixed(0)}
              </span>
            )}
          </div>

          {/* Quality bar */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              marginBottom: 4,
            }}
          >
            <span className="text-xs text-muted" style={{ width: 54, flexShrink: 0 }}>
              Quality:
            </span>
            <div
              style={{
                flex: 1,
                height: 8,
                background: 'var(--bg-primary)',
                borderRadius: 4,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${Math.max(0, Math.min(100, ans.quality))}%`,
                  height: '100%',
                  background: qualityColor(ans.quality),
                  borderRadius: 4,
                  transition: 'width 0.2s',
                }}
              />
            </div>
            <span
              className="mono text-xs"
              style={{ width: 28, textAlign: 'right', flexShrink: 0 }}
            >
              {ans.quality.toFixed(0)}
            </span>
          </div>

          {/* Rule descriptions */}
          {ans.top_rule_description && (
            <div className="text-xs" style={{ color: 'var(--text-secondary)', marginBottom: 2 }}>
              Top: {ans.top_rule_description}
            </div>
          )}
          {ans.bottom_rule_description && (
            <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Bottom: {ans.bottom_rule_description}
            </div>
          )}

          {/* Theme patterns (§4.7.1) */}
          {themeChips(ans.vertical_themes ?? ans.themes, 'var(--text-accent)', 'Vertical themes')}
          {themeChips(ans.top_themes, '#4caf50', 'Top themes')}
          {themeChips(ans.bottom_themes, '#03a9f4', 'Bottom themes')}
          {themeChips(ans.unjustified_themes, 'var(--error)', 'Unjustified themes')}

          {/* Temperature at discovery */}
          <div
            className="text-xs text-muted"
            style={{ marginTop: 4, textAlign: 'right' }}
          >
            {ans.is_coherent === false && (
              <span style={{ color: 'var(--warning)', marginRight: 6 }}>incoherent</span>
            )}
            T: {ans.temperature.toFixed(0)}
          </div>
        </div>
      ))}

      {/* Snag summaries */}
      {snags.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div className="text-xs text-muted" style={{ marginBottom: 4, fontWeight: 600 }}>
            Snags
          </div>
          {snags.map((snag) => (
            <div
              key={snag.snag_id}
              style={{
                background: 'var(--bg-card)',
                borderRadius: 4,
                padding: 6,
                marginBottom: 4,
                border: '1px solid var(--error)',
                borderLeftWidth: 3,
              }}
            >
              <div className="mono text-xs" style={{ color: 'var(--error)' }}>
                Snag @ codelet {snag.codelet_count} (T: {snag.temperature.toFixed(0)})
              </div>
              <div className="text-xs text-muted" style={{ marginTop: 2 }}>
                {snag.description}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
