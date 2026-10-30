// ---------------------------------------------------------------------------
// EpisodicRunTimeline -- Metacat Mode's recorded episodic runs, newest first,
// with the moments Episodic Memory was cleared marked between them
// ---------------------------------------------------------------------------
//
// The coarse-grained half of the review UX: scan the recorded runs, see where the
// Episodic Memory was cleared, open a run. Nothing here fetches a capture -- the
// point of this level is to be fast to scan, so each row shows only what the
// listing already carries.
//
// A clear is an event, not a container: it sits between the run before it and the
// run after it, and carries an editable note. Paging counts runs; the server places
// the markers that belong to each page.
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useState } from 'react';
import { describeApiError, listEpisodicRuns, setMemoryClearNote } from '@/api/client';
import { ModeBadge, MODE_NOTES } from '@/components/ModeBadge';
import { Pager } from '@/components/Pager';
import type { EpisodicTimelineItem, MemoryClear, RecordedRun } from '@/types';

/** How many runs one window of the timeline holds. */
const PAGE_SIZE = 50;

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

interface Props {
  selectedRunId: number | null;
  onSelectRun: (run: RecordedRun) => void;
}

export function EpisodicRunTimeline({ selectedRunId, onSelectRun }: Props) {
  const [items, setItems] = useState<EpisodicTimelineItem[]>([]);
  /** Why there is no timeline. */
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Which window of runs is on screen, and how many exist behind it. The server
  // pages this endpoint by run, so the offset is what reaches run 51 and later.
  const [offset, setOffset] = useState(0);
  const [totalRuns, setTotalRuns] = useState(0);
  const [totalClears, setTotalClears] = useState(0);

  useEffect(() => {
    let cancelled = false;
    listEpisodicRuns(PAGE_SIZE, offset)
      .then((r) => {
        if (cancelled) return;
        setItems(r.items);
        setTotalRuns(r.total_runs);
        setTotalClears(r.total_clears);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(describeApiError(e, 'load the episodic runs'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [offset]);

  /** Keep the saved note on screen without refetching the window. */
  const handleNoteSaved = useCallback((saved: MemoryClear) => {
    setItems((prev) =>
      prev.map((it) =>
        it.kind === 'memory_cleared' && it.clear.clear_id === saved.clear_id
          ? { kind: 'memory_cleared', clear: saved }
          : it,
      ),
    );
  }, []);

  if (loading) {
    return <div className="text-muted text-sm" style={{ padding: 12 }}>Loading episodic runs…</div>;
  }
  if (error) {
    return (
      <div role="alert" style={{ padding: 12, color: 'var(--error)', fontSize: 12 }}>
        {error}
      </div>
    );
  }
  if (items.length === 0 && offset === 0) {
    return (
      <div className="text-muted text-sm" style={{ padding: 12 }}>
        No episodic runs recorded yet. Metacat Mode&apos;s runs appear here, newest first,
        with a marker wherever Episodic Memory was cleared.
      </div>
    );
  }

  const runCount = items.filter((i) => i.kind === 'run').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, height: '100%', overflow: 'auto' }}>
      <div
        style={{ border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg-card)' }}
      >
        <table
          aria-label="Episodic runs, newest first"
          style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}
        >
          <thead>
            <tr style={{ color: 'var(--text-secondary)' }}>
              <th scope="col" style={th}>Run</th>
              <th scope="col" style={th}>Mode</th>
              <th scope="col" style={th}>Problem</th>
              <th scope="col" style={th}>Status</th>
              <th scope="col" style={{ ...th, textAlign: 'right' }}>Codelets</th>
              <th scope="col" style={th}>Answer</th>
              <th scope="col" style={th}>config / memory</th>
              <th scope="col" style={{ ...th, textAlign: 'right' }}>Record</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) =>
              it.kind === 'run' ? (
                <RunRow
                  key={`run-${it.run.run_id}`}
                  run={it.run}
                  selected={it.run.run_id === selectedRunId}
                  onSelectRun={onSelectRun}
                />
              ) : (
                <ClearMarkerRow
                  key={`clear-${it.clear.clear_id}`}
                  clear={it.clear}
                  onSaved={handleNoteSaved}
                />
              ),
            )}
          </tbody>
        </table>
      </div>

      {/* The window on screen, and how many runs exist behind it. Paging counts
          runs; markers ride along with the runs they sit between. */}
      <Pager
        offset={offset}
        limit={PAGE_SIZE}
        total={totalRuns}
        count={runCount}
        onChange={setOffset}
        label="episodic runs"
      />
      {totalClears > 0 && (
        <div className="text-xs text-muted">
          Episodic Memory has been cleared {totalClears} time{totalClears === 1 ? '' : 's'}.
        </div>
      )}
    </div>
  );
}

/**
 * The marker for one clear of Episodic Memory, and its editable note.
 *
 * Saved explicitly rather than on blur: the note is the record of why the memory was
 * cleared, and a value that saves itself when focus moves is a value that can be
 * changed by a stray click and never noticed.
 */
export function ClearMarkerRow({
  clear,
  onSaved,
}: {
  clear: MemoryClear;
  onSaved: (clear: MemoryClear) => void;
}) {
  const [draft, setDraft] = useState(clear.note);
  /** The server's note as last seen, so a refresh can tell an edit from no edit. */
  const [seenNote, setSeenNote] = useState(clear.note);
  const [saving, setSaving] = useState(false);
  /** Why the note in the field is still only in the field. */
  const [failure, setFailure] = useState<string | null>(null);

  // Follow the server's note only while the field has not been edited. An effect
  // that reset the draft would run after the user's keystroke whenever it was
  // delayed (a late refresh, or the mount's own effect), and discard what they typed.
  if (clear.note !== seenNote) {
    setSeenNote(clear.note);
    if (draft === seenNote) setDraft(clear.note);
  }

  const when = formatTime(clear.cleared_at);
  const dirty = draft !== clear.note;
  const inputId = `memory-clear-note-${clear.clear_id}`;

  const save = async () => {
    setSaving(true);
    setFailure(null);
    try {
      onSaved(await setMemoryClearNote(clear.clear_id, draft));
    } catch (err) {
      setFailure(describeApiError(err, 'save the note on the Episodic Memory clear'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <tr
      data-testid={`memory-clear-${clear.clear_id}`}
      style={{
        borderTop: '1px solid var(--border)',
        background: 'var(--bg-secondary, transparent)',
      }}
    >
      <td colSpan={8} style={{ padding: '6px 8px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <div
            title="Episodic Memory was cleared at this point. Runs above this marker started with none."
            style={{ fontWeight: 700, color: 'var(--text-accent)', fontSize: 11 }}
          >
            Episodic Memory cleared — {when}
          </div>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <label htmlFor={inputId} className="text-muted text-xs" style={{ flexShrink: 0 }}>
              Note
            </label>
            <input
              id={inputId}
              type="text"
              value={draft}
              aria-label={`Note on the Episodic Memory clear of ${when}`}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Why was Episodic Memory cleared?"
              style={{ flex: 1, fontSize: 11 }}
            />
            <button
              onClick={save}
              disabled={!dirty || saving}
              aria-label={`Save the note on the clear of ${when}`}
              style={{ fontSize: 10 }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            {failure !== null && (
              <span className="text-xs" style={{ color: 'var(--error)' }}>
                not saved
              </span>
            )}
          </div>
          {failure !== null && (
            <span role="alert" className="text-xs" style={{ color: 'var(--error)' }}>
              {failure}
            </span>
          )}
        </div>
      </td>
    </tr>
  );
}

function RunRow({
  run: r,
  selected,
  onSelectRun,
}: {
  run: RecordedRun;
  selected: boolean;
  onSelectRun: (run: RecordedRun) => void;
}) {
  return (
    <tr
      onClick={() => onSelectRun(r)}
      aria-selected={selected}
      style={{
        borderTop: '1px solid var(--border)',
        cursor: 'pointer',
        background: selected ? 'rgba(79, 195, 247, 0.12)' : 'transparent',
      }}
    >
      <td style={{ ...td, fontFamily: 'var(--font-mono)', fontWeight: selected ? 700 : 400 }}>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onSelectRun(r);
          }}
          aria-label={`Open run ${r.run_id}`}
          style={{
            background: 'none',
            border: 'none',
            padding: 0,
            color: 'inherit',
            font: 'inherit',
            cursor: 'pointer',
          }}
        >
          #{r.run_id}
        </button>
      </td>
      <td style={td}><ModeBadge mode={r.mode} /></td>
      <td style={{ ...td, fontFamily: 'var(--font-mono)' }}>
        {r.initial}→{r.modified}; {r.target}→?
      </td>
      <td style={td}>{r.status}</td>
      <td style={{ ...td, textAlign: 'right', fontFamily: 'var(--font-mono)' }}>
        {r.codelet_count}
      </td>
      <td style={{ ...td, fontFamily: 'var(--font-mono)' }}>
        {r.answer ?? '—'}
        {r.answer && r.justify_mode && (
          <span className="text-muted" title="The answer was given for the engine to justify, not discovered by it.">
            {' '}(given)
          </span>
        )}
      </td>
      <td
        style={{ ...td, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}
        title={`config ${r.config_hash ?? '—'} / memory ${r.memory_hash ?? '—'}`}
      >
        {(r.config_hash ?? '——').slice(0, 6)} / {(r.memory_hash ?? '——').slice(0, 6)}
      </td>
      <td style={{ ...td, textAlign: 'right', color: 'var(--text-secondary)' }}>
        {r.capture_count === 0 && r.action_count === 0 ? (
          <span title={MODE_NOTES[r.mode]}>none</span>
        ) : (
          <>
            {r.capture_count} cap
            {r.action_count > 0 && ` · ${r.action_count} act`}
          </>
        )}
      </td>
    </tr>
  );
}

const th: React.CSSProperties = {
  textAlign: 'left',
  padding: '3px 6px',
  fontWeight: 600,
};

const td: React.CSSProperties = {
  padding: '3px 6px',
};
