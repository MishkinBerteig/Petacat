// ---------------------------------------------------------------------------
// MemoryView -- Cards for episodic memory answer descriptions
// ---------------------------------------------------------------------------
//
// The panel loads the memory it shows, so a blank panel has one meaning at a time:
// an Episodic Memory holding nothing says "No answers stored", and a memory the
// server refused says why. Each action the header and the cards offer -- compare,
// clear, forget, display, explain -- reports its own failure where its result
// appears.
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useState } from 'react';
import {
  describeApiError,
  displayAnswer,
  explainAnswer,
  forgetAnswer,
  getMemory,
  getRunMemory,
  request,
} from '@/api/client';
import { useRunStore } from '@/store/runStore';
import type { AnswerComparisonResult, AnswerExplanation, MemoryState } from '@/types';

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
  const [selected, setSelected] = useState<number[]>([]);
  const [comparison, setComparison] = useState<AnswerComparisonResult | null>(null);
  const [comparing, setComparing] = useState(false);

  const runId = useRunStore((s) => s.runId);
  const elizaMode = useRunStore((s) => s.elizaMode);
  const refreshThemespace = useRunStore((s) => s.refreshThemespace);
  const [displaying, setDisplaying] = useState<number | null>(null);
  const [explanation, setExplanation] = useState<AnswerExplanation | null>(null);
  /** Why the memory on screen is not the memory the server holds. */
  const [loadError, setLoadError] = useState<string | null>(null);
  /** Why the last thing the reader asked for did not happen. */
  const [actionError, setActionError] = useState<string | null>(null);

  /**
   * Read the Training Session's Episodic Memory, by the route that reaches it.
   *
   * Every Run shares one memory; a Fast Run has no database rows, so the run-scoped
   * read serves its copy from the live object. The result goes into the store, which
   * is where the rest of the display reads it from.
   */
  const refreshMemory = useCallback(async () => {
    try {
      const next: MemoryState =
        runId === null ? await getMemory() : await getRunMemory(runId);
      useRunStore.setState({ memory: next });
      setLoadError(null);
    } catch (err) {
      setLoadError(describeApiError(err, 'load episodic memory'));
    }
  }, [runId]);

  useEffect(() => {
    void refreshMemory();
  }, [refreshMemory]);

  /**
   * Re-enter a stored episode.  `memory.ss:268-283`: clicking an answer icon redraws
   * its Workspace and imposes its vertical, top and bottom theme-patterns; clicking
   * again restores the live state.  The three patterns are kept apart for the reason
   * §4.7.1 gives — they characterise different halves of the analogy.
   */
  const onDisplay = useCallback(
    async (answerId: number) => {
      if (runId == null) return;
      try {
        const res = await displayAnswer(runId, answerId);
        setActionError(null);
        setDisplaying(res.displaying);
      } catch (err) {
        setActionError(describeApiError(err, "impose the answer's theme patterns"));
        return;
      }
      await refreshThemespace();
    },
    [runId, refreshThemespace],
  );

  /**
   * Ask the program what one answer is based on (`explain`, `answers.ss:310-333`).
   *
   * Rendered in whichever voice the Eliza-mode switch is currently in, because that is
   * the one place `explain` differs between voices — everything before its last
   * sentence is shared (§4.6, pp. 183-184).  Clicking again puts it away.
   */
  const onExplain = useCallback(
    async (answerId: number) => {
      if (explanation?.answer_id === answerId) {
        setExplanation(null);
        return;
      }
      try {
        setExplanation(await explainAnswer(answerId, elizaMode));
        setActionError(null);
      } catch (err) {
        setExplanation(null);
        setActionError(describeApiError(err, 'explain the answer'));
      }
    },
    [explanation, elizaMode],
  );

  /** Forget one answer (`memory.ss:42-54`), which §5.2.3's experiment depends on. */
  const onForget = useCallback(
    async (answerId: number) => {
      try {
        await forgetAnswer(answerId);
      } catch (err) {
        // The answer is still in memory, so the card stays and says why.
        setActionError(describeApiError(err, 'forget the answer'));
        return;
      }
      setActionError(null);
      setSelected((prev) => prev.filter((id) => id !== answerId));
      await refreshMemory();
    },
    [refreshMemory],
  );

  const toggleSelected = useCallback((answerId: number) => {
    setComparison(null);
    setActionError(null);
    setSelected((prev) =>
      prev.includes(answerId)
        ? prev.filter((id) => id !== answerId)
        : [...prev, answerId].slice(-2),
    );
  }, []);

  /** Compare two stored answers (§4.7.3), and say so when the comparison is refused. */
  const handleCompare = useCallback(async () => {
    if (selected.length !== 2) return;
    setComparing(true);
    try {
      const res = await request<AnswerComparisonResult>('/memory/compare', {
        method: 'POST',
        body: JSON.stringify({ answer_id_1: selected[0], answer_id_2: selected[1] }),
      });
      setComparison(res);
      setActionError(null);
    } catch (err) {
      setComparison(null);
      setActionError(describeApiError(err, 'compare the two answers'));
    } finally {
      setComparing(false);
    }
  }, [selected]);

  const handleClear = useCallback(async () => {
    if (!window.confirm('Clear all episodic memory? This cannot be undone.')) return;
    try {
      await request<void>('/memory', { method: 'DELETE' });
      setActionError(null);
    } catch (err) {
      // The answers below are still stored, so the panel keeps showing them.
      setActionError(describeApiError(err, 'clear episodic memory'));
      return;
    }
    await refreshMemory();
  }, [refreshMemory]);

  const { answers, snags } = memory;
  const isEmpty = answers.length === 0 && snags.length === 0;
  /**
   * Every Run shares the Training Session's Episodic Memory. `scope` says how this
   * copy of it was read: `shared` from the stored rows, `live` from the object the
   * engine is using. A Fast Run writes no rows, so its memory is read live — the same
   * answers, taken from the place that has them.
   */
  const isLiveRead = memory.scope === 'live';

  return (
    <div style={{ fontSize: 12 }}>
      {/* The memory was not read, and this is why. The empty state below carries
          the other fact a blank panel can report: the memory holds nothing. */}
      {loadError !== null && (
        <div
          role="alert"
          className="text-xs"
          style={{
            marginBottom: 6,
            padding: '4px 6px',
            borderRadius: 3,
            border: '1px solid var(--error)',
            color: 'var(--error)',
          }}
        >
          {loadError}
        </div>
      )}

      {isLiveRead && (
        <div
          className="text-xs"
          style={{
            marginBottom: 6,
            padding: '4px 6px',
            borderRadius: 3,
            border: '1px solid var(--border)',
            color: 'var(--text-secondary)',
          }}
        >
          Read live from the Training Session's memory. A <strong>Fast</strong> run
          shares this memory and is reminded from it, and the answers it finds are here
          for as long as the session runs.
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
        <span style={{ display: 'flex', gap: 8 }}>
          {answers.length >= 2 && (
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
          {!isEmpty && (
            <button
              onClick={handleClear}
              style={{ fontSize: 10, color: 'var(--error)' }}
            >
              Clear Memory
            </button>
          )}
        </span>
      </div>

      {/* Why the last thing asked for did not happen, in the place its result
          would have appeared. */}
      {actionError !== null && (
        <div
          role="alert"
          className="text-xs"
          style={{
            marginBottom: 6,
            padding: '4px 6px',
            borderRadius: 3,
            border: '1px solid var(--error)',
            color: 'var(--error)',
          }}
        >
          {actionError}
        </div>
      )}

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

      {/* Empty state: the memory was read, and it holds nothing. */}
      {isEmpty && loadError === null && (
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

          {/* Re-enter this episode, or forget it (memory.ss:268-283, memory.ss:42-54) */}
          <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
            <button
              onClick={(e) => { e.stopPropagation(); onDisplay(ans.answer_id); }}
              disabled={runId == null}
              title="Impose this answer's vertical, top and bottom theme-patterns on the Themespace; again to restore (memory.ss:275-277)"
              className="text-xs"
              style={{
                background: 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 3,
                color: displaying === ans.answer_id ? '#ffd700' : 'var(--text-secondary)',
                cursor: runId == null ? 'default' : 'pointer',
                padding: '1px 6px',
              }}
            >
              {displaying === ans.answer_id ? 'restore' : 'display'}
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onExplain(ans.answer_id); }}
              title="Ask what this answer is based on (answers.ss:310-333)"
              className="text-xs"
              style={{
                background: 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 3,
                color:
                  explanation?.answer_id === ans.answer_id
                    ? 'var(--text-accent)'
                    : 'var(--text-secondary)',
                cursor: 'pointer',
                padding: '1px 6px',
              }}
            >
              explain
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onForget(ans.answer_id); }}
              title="Forget just this answer (memory.ss:42-54) — §5.2.3's experiment needs it, and it is how you ask the program to find this answer again"
              className="text-xs"
              style={{
                background: 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 3,
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                padding: '1px 6px',
              }}
            >
              forget
            </button>
            <div
              className="text-xs text-muted"
              style={{ marginLeft: 'auto', textAlign: 'right' }}
            >
              {ans.is_coherent === false && (
                <span style={{ color: 'var(--warning)', marginRight: 6 }}>incoherent</span>
              )}
              T: {ans.temperature.toFixed(0)}
            </div>
          </div>

          {/* The program's own account of this answer (answers.ss:310-333) */}
          {explanation?.answer_id === ans.answer_id && (
            <p
              className="text-xs"
              style={{
                margin: '6px 0 0',
                paddingTop: 6,
                borderTop: '1px solid var(--border)',
                color: 'var(--text-primary)',
                lineHeight: 1.5,
              }}
            >
              {explanation.text}
            </p>
          )}
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
