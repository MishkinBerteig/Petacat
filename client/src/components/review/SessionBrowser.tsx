// ---------------------------------------------------------------------------
// SessionBrowser -- Training Sessions and the Runs recorded in them (WP3.9)
// ---------------------------------------------------------------------------
//
// The coarse-grained half of the review UX: list sessions, open one, see its
// sequence of Runs and each Run's mode. Nothing here fetches a capture -- the
// point of this level is to be fast to scan, so each row shows only what the
// session and run listings already carry.
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useState } from 'react';
import {
  describeApiError,
  listTrainingSessions,
  getTrainingSession,
  setSessionNote,
} from '@/api/client';
import { ModeBadge, MODE_NOTES } from '@/components/ModeBadge';
import { Pager } from '@/components/Pager';
import type {
  RecordedRun,
  TrainingSessionDetail,
  TrainingSessionSummary,
} from '@/types';

/** How many Training Sessions one window of the browser holds. */
const PAGE_SIZE = 50;

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

interface Props {
  selectedRunId: number | null;
  onSelectRun: (run: RecordedRun) => void;
  /**
   * Open this session, because the Run being reviewed is in it.
   *
   * A Run reached by id — from Run History rather than from this list — leaves the
   * browser showing some other session expanded, so the row that is highlighted is
   * not on screen and the selection looks like it did nothing.
   */
  focusSessionId?: number | null;
}

export function SessionBrowser({ selectedRunId, onSelectRun, focusSessionId = null }: Props) {
  const [sessions, setSessions] = useState<TrainingSessionSummary[]>([]);
  const [openSessionId, setOpenSessionId] = useState<number | null>(null);
  const [detail, setDetail] = useState<TrainingSessionDetail | null>(null);
  /** Why there is no list of sessions. */
  const [error, setError] = useState<string | null>(null);
  /** Why an opened session shows no Runs. */
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Which window of sessions is on screen, and how many exist behind it. The
  // server pages this endpoint, so the offset is what reaches session 51 and later.
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    listTrainingSessions(PAGE_SIZE, offset)
      .then((r) => {
        setSessions(r.sessions);
        setTotal(r.total);
        // Open the newest session on the window straight away: a browser that opens
        // on an empty pane makes the reader do a click to find out there is anything
        // at all.
        if (r.sessions.length > 0) setOpenSessionId(r.sessions[0].session_id);
      })
      .catch((e) => setError(describeApiError(e, 'load the Training Sessions')))
      .finally(() => setLoading(false));
  }, [offset]);

  useEffect(() => {
    if (focusSessionId !== null) setOpenSessionId(focusSessionId);
  }, [focusSessionId]);

  // One session's Runs. A failure here is about that session, so it is reported
  // inside the expanded row and the rest of the list stays usable.
  useEffect(() => {
    if (openSessionId === null) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    getTrainingSession(openSessionId)
      .then((d) => {
        setDetail(d);
        setDetailError(null);
      })
      .catch((e) => {
        setDetail(null);
        setDetailError(
          describeApiError(e, `load the Runs in Training Session ${openSessionId}`),
        );
      });
  }, [openSessionId]);

  /**
   * Keep the note in both places the browser shows it.
   *
   * The list carries it and so does the detail, and they are fetched separately, so
   * saving without updating both leaves the header showing the old note until the
   * next reload — which reads as the save having failed.
   */
  const handleNoteSaved = useCallback((sessionId: number, note: string) => {
    setSessions((prev) =>
      prev.map((s) => (s.session_id === sessionId ? { ...s, note } : s)),
    );
    setDetail((prev) =>
      prev !== null && prev.session_id === sessionId ? { ...prev, note } : prev,
    );
  }, []);

  if (loading) {
    return <div className="text-muted text-sm" style={{ padding: 12 }}>Loading sessions…</div>;
  }
  if (error) {
    return (
      <div role="alert" style={{ padding: 12, color: 'var(--error)', fontSize: 12 }}>
        {error}
      </div>
    );
  }
  if (sessions.length === 0 && offset === 0) {
    return (
      <div className="text-muted text-sm" style={{ padding: 12 }}>
        No Training Sessions recorded yet. A session begins with the first Run and
        ends when Episodic Memory is cleared.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, height: '100%', overflow: 'auto' }}>
      {sessions.map((s) => {
        const isOpen = s.session_id === openSessionId;
        return (
          <div
            key={s.session_id}
            style={{
              border: '1px solid var(--border)',
              borderRadius: 4,
              background: 'var(--bg-card)',
            }}
          >
            <button
              onClick={() => setOpenSessionId(isOpen ? null : s.session_id)}
              aria-expanded={isOpen}
              style={{
                display: 'flex',
                width: '100%',
                alignItems: 'center',
                gap: 8,
                background: 'transparent',
                border: 'none',
                color: 'var(--text-primary)',
                cursor: 'pointer',
                padding: '6px 8px',
                fontSize: 12,
                textAlign: 'left',
              }}
            >
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-accent)', fontWeight: 700 }}>
                Session {s.session_id}
              </span>
              {/* The note is the only thing that distinguishes one session from
                  another at a glance — sessions are not created deliberately, so a
                  number and a date range is all they otherwise have. */}
              {s.note !== '' && (
                <span
                  title="Session note"
                  style={{
                    fontStyle: 'italic',
                    fontSize: 11,
                    maxWidth: 160,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {s.note}
                </span>
              )}
              <span className="text-muted text-xs">
                {s.run_count} run{s.run_count === 1 ? '' : 's'}
              </span>
              <span className="text-muted text-xs">
                {formatTime(s.first_run_at)} — {formatTime(s.last_run_at)}
              </span>
              <span style={{ flex: 1 }} />
              {s.is_open ? (
                <span
                  title="Episodic Memory has not been cleared, so this session can still gain Runs."
                  style={{ fontSize: 10, color: '#4caf50', fontWeight: 600 }}
                >
                  OPEN
                </span>
              ) : (
                // The closed case used to show nothing at all, which left the one
                // event that defines a session's extent invisible: a reader could see
                // that a session had stopped gaining Runs but not that the memory
                // clear is what stopped it, nor when.
                <span
                  title={
                    'Episodic Memory was cleared at this point, which is what ends a '
                    + 'Training Session. Runs after it inherit an empty memory and '
                    + 'belong to the next session.'
                  }
                  style={{ fontSize: 10, color: 'var(--text-secondary)', fontWeight: 600 }}
                >
                  MEMORY CLEARED {formatTime(s.ended_at)}
                </span>
              )}
              <span className="text-muted">{isOpen ? '▾' : '▸'}</span>
            </button>

            {isOpen && detailError !== null && (
              <div
                role="alert"
                className="text-xs"
                style={{
                  padding: '6px 8px',
                  borderTop: '1px solid var(--border)',
                  color: 'var(--error)',
                }}
              >
                {detailError}
              </div>
            )}

            {isOpen && detail && detail.session_id === s.session_id && (
              <>
                <SessionNoteEditor
                  sessionId={s.session_id}
                  note={detail.note}
                  onSaved={handleNoteSaved}
                />
                <RunTable
                  runs={detail.runs}
                  selectedRunId={selectedRunId}
                  onSelectRun={onSelectRun}
                />
                {/* Said under the Runs rather than beside the header, because this is
                    what the sequence above means: every Run in it saw what the Runs
                    before it put into Episodic Memory, and nothing from before the
                    session began. */}
                <div
                  className="text-xs text-muted"
                  style={{ padding: '4px 8px', borderTop: '1px solid var(--border)' }}
                >
                  {detail.is_open
                    ? 'These Runs share one Episodic Memory, which is still accumulating. '
                      + 'Clearing it from the Admin panel ends this session and starts the next.'
                    : `Episodic Memory was cleared at ${formatTime(detail.ended_at)}, ending `
                      + 'this session. Runs after that point started from an empty memory.'}
                </div>
              </>
            )}
          </div>
        );
      })}

      {/* The window on screen, and how many sessions exist behind it. The list is
          one page of a paged endpoint, so this is what reaches the sessions past
          the first window. */}
      <Pager
        offset={offset}
        limit={PAGE_SIZE}
        total={total}
        count={sessions.length}
        onChange={setOffset}
        label="Training Sessions"
      />
    </div>
  );
}

/**
 * The one editable thing about a Training Session.
 *
 * A session is not created deliberately — it is the span between two Episodic Memory
 * clears — so nothing about it is chosen except this. The column has existed since
 * WP3.0 and was carried by the model, the service and both review responses without
 * anything ever rendering it or offering to set it, which made a list of sessions a
 * list of numbers.
 *
 * Saved explicitly rather than on blur: the note is the record of what an experiment
 * was for, and a value that saves itself when focus moves is a value that can be
 * changed by a stray click and never noticed.
 */
function SessionNoteEditor({
  sessionId,
  note,
  onSaved,
}: {
  sessionId: number;
  note: string;
  onSaved: (sessionId: number, note: string) => void;
}) {
  const [draft, setDraft] = useState(note);
  const [saving, setSaving] = useState(false);
  /** Why the note in the field is still only in the field. */
  const [failure, setFailure] = useState<string | null>(null);

  // A different session is a different note; without this, expanding a second
  // session shows the first one's text sitting in the field.
  useEffect(() => {
    setDraft(note);
    setFailure(null);
  }, [sessionId, note]);

  const dirty = draft !== note;

  const save = async () => {
    setSaving(true);
    setFailure(null);
    try {
      await setSessionNote(sessionId, draft);
      onSaved(sessionId, draft);
    } catch (err) {
      setFailure(describeApiError(err, 'save the session note'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        padding: '4px 8px',
        borderTop: '1px solid var(--border)',
      }}
    >
      <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        <label
          htmlFor={`session-note-${sessionId}`}
          className="text-muted text-xs"
          style={{ flexShrink: 0 }}
        >
          Note
        </label>
        <input
          id={`session-note-${sessionId}`}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="What was this session for?"
          style={{ flex: 1, fontSize: 11 }}
        />
        <button onClick={save} disabled={!dirty || saving} style={{ fontSize: 10 }}>
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
  );
}

function RunTable({
  runs,
  selectedRunId,
  onSelectRun,
}: {
  runs: RecordedRun[];
  selectedRunId: number | null;
  onSelectRun: (run: RecordedRun) => void;
}) {
  if (runs.length === 0) {
    return (
      <div className="text-muted text-xs" style={{ padding: '6px 10px' }}>
        No Runs recorded in this session. A Fast Run leaves no row at all, which is
        the mode working rather than a gap.
      </div>
    );
  }

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
      <thead>
        <tr style={{ borderTop: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
          <th style={th}>Run</th>
          <th style={th}>Mode</th>
          <th style={th}>Problem</th>
          <th style={th}>Status</th>
          <th style={{ ...th, textAlign: 'right' }}>Codelets</th>
          <th style={th}>Answer</th>
          <th style={th}>config / memory</th>
          <th style={{ ...th, textAlign: 'right' }}>Record</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => {
          const selected = r.run_id === selectedRunId;
          return (
            <tr
              key={r.run_id}
              onClick={() => onSelectRun(r)}
              style={{
                borderTop: '1px solid var(--border)',
                cursor: 'pointer',
                background: selected ? 'rgba(79, 195, 247, 0.12)' : 'transparent',
              }}
            >
              <td style={{ ...td, fontFamily: 'var(--font-mono)', fontWeight: selected ? 700 : 400 }}>
                #{r.run_id}
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
        })}
      </tbody>
    </table>
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
