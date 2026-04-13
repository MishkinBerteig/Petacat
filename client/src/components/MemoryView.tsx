// ---------------------------------------------------------------------------
// MemoryView -- Cards for episodic memory answer descriptions
// ---------------------------------------------------------------------------

import { useCallback } from 'react';
import { useRunStore } from '@/store/runStore';

function qualityColor(quality: number): string {
  if (quality > 70) return 'var(--success)';
  if (quality > 40) return 'var(--warning)';
  return 'var(--error)';
}

export function MemoryView() {
  const memory = useRunStore((s) => s.memory);
  const refreshMemory = useRunStore((s) => s.refreshMemory);

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

  return (
    <div style={{ fontSize: 12 }}>
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
        {!isEmpty && (
          <button
            onClick={handleClear}
            style={{ fontSize: 10, color: 'var(--error)' }}
          >
            Clear Memory
          </button>
        )}
      </div>

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
          style={{
            background: 'var(--bg-card)',
            borderRadius: 4,
            padding: 8,
            marginBottom: 6,
            border: '1px solid var(--border)',
          }}
        >
          {/* Problem string */}
          <div
            className="mono text-xs"
            style={{ marginBottom: 4, color: 'var(--text-primary)' }}
          >
            {ans.problem.join(' -> ')}
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

          {/* Temperature at discovery */}
          <div
            className="text-xs text-muted"
            style={{ marginTop: 4, textAlign: 'right' }}
          >
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
