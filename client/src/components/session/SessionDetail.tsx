// ---------------------------------------------------------------------------
// Petacat -- Training Mode Session: one Training Mode Session's header, controls, add-problems box and table
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useState } from 'react';
import {
  addSessionProblems,
  sessionExportUrl,
  cancelSession,
  deleteSession,
  describeApiError,
  pauseSession,
  resumeSession,
  startSession,
  stopSession,
  updateSession,
} from '@/api/client';
import type { SessionErrorPolicy, SessionLimits, SessionSummary } from '@/types';
import { chunk, parseProblemText } from './problemText';
import { MemoryTab } from './MemoryTab';
import { PolicyFields } from './PolicyFields';
import { ProblemPreview, ProblemTextInput } from './ProblemTextInput';
import { ProblemsTable } from './ProblemsTable';
import {
  cardStyle,
  ControlHelp,
  errorStyle,
  fmtEta,
  fmtInt,
  fmtRate,
  fmtTime,
  linkButtonStyle,
  noticeStyle,
  ProgressBar,
  sectionLabelStyle,
  StateBadge,
} from './shared';

const FALLBACK_REQUEST_SIZE = 500;

interface Props {
  session: SessionSummary;
  limits: SessionLimits | null;
  /** A message to show above the Training Mode Session (e.g. a partly failed create). */
  notice: string | null;
  /** A newer summary came back from the server. */
  onSessionChanged: (session: SessionSummary) => void;
  onDeleted: () => void;
}

export function SessionDetail({ session, limits, notice, onSessionChanged, onDeleted }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'problems' | 'memory'>('problems');
  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState('');

  const live = session.state !== 'stopped';
  const label = session.name || `Training Mode Session ${session.id}`;

  const act = async (what: string, fn: () => Promise<SessionSummary>) => {
    setBusy(true);
    setError(null);
    try {
      onSessionChanged(await fn());
    } catch (err) {
      setError(describeApiError(err, what));
    } finally {
      setBusy(false);
    }
  };

  const startRename = () => {
    setNewName(session.name);
    setRenaming(true);
  };

  const saveRename = async () => {
    const name = newName.trim();
    if (name === '') {
      setError('A Training Mode Session needs a name.');
      return;
    }
    if (name === session.name) {
      setRenaming(false);
      return;
    }
    await act('rename the Training Mode Session', () => updateSession(session.id, { name }));
    setRenaming(false);
  };

  const handleCancel = () => {
    if (
      !window.confirm(
        `Cancel the queued and running problems of "${label}"? Finished runs are kept and the Training Mode Session stays ${session.state}.`,
      )
    )
      return;
    void act('cancel the Training Mode Session', () => cancelSession(session.id));
  };

  const handleDelete = async () => {
    if (
      !window.confirm(
        `Delete "${label}"? Its problems, runs and Episodic Memory are removed from the database${live ? ', and its live state is discarded' : ''}. This cannot be undone.`,
      )
    )
      return;
    setBusy(true);
    setError(null);
    try {
      await deleteSession(session.id);
      onDeleted();
    } catch (err) {
      setError(describeApiError(err, 'delete the Training Mode Session'));
      setBusy(false);
    }
  };

  const p = session.problems;
  const s = session.settings;
  const overrideCount = s.parameters ? Object.keys(s.parameters).length : 0;

  return (
    <div data-testid="session-detail" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {notice && (
        <div role="status" style={noticeStyle}>
          {notice}
        </div>
      )}
      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}

      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {renaming ? (
            <>
              <input
                aria-label="New name"
                value={newName}
                maxLength={200}
                autoFocus
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void saveRename();
                  if (e.key === 'Escape') setRenaming(false);
                }}
                style={{ minWidth: 200 }}
              />
              <button disabled={busy} onClick={() => void saveRename()}>
                Save name
              </button>
              <button disabled={busy} onClick={() => setRenaming(false)}>
                Cancel rename
              </button>
            </>
          ) : (
            <>
              <h2 style={{ margin: 0, fontSize: 15 }}>{label}</h2>
              <button disabled={busy} onClick={startRename} title="Rename this Training Mode Session">
                Rename
              </button>
            </>
          )}
          <StateBadge state={session.state} activity={session.activity} />
          <ControlHelp topic="session" label="Training Mode Session" />
          <span className="text-xs text-muted">created {fmtTime(session.created_at)}</span>
        </div>
        {session.last_event && (
          <div
            role="status"
            data-testid="last-event"
            style={{
              marginTop: 6,
              padding: '4px 8px',
              border: '1px solid var(--warning)',
              borderRadius: 4,
              fontWeight: 600,
              fontSize: 12,
            }}
          >
            {session.last_event}
          </div>
        )}
        {session.state === 'stopped' && session.stopped_at && (
          <div className="text-xs text-muted" data-testid="stopped-line">
            Stopped {fmtTime(session.stopped_at)}
            {session.stopped_from ? ` from ${session.stopped_from}` : ''}
            {session.stop_reason ? ` (${session.stop_reason})` : ''}.
          </div>
        )}
        {session.stalled_reason && (
          <div role="status" style={{ ...errorStyle, marginTop: 6 }}>
            Stalled: {session.stalled_reason}
          </div>
        )}
        {session.note && <div className="text-xs text-muted">{session.note}</div>}

        <div className="text-xs mono" style={{ marginTop: 6 }} data-testid="session-problems-line">
          Problems: {fmtInt(p.total)} total · {fmtInt(p.finished)} finished · {fmtInt(p.running)} running ·{' '}
          {fmtInt(p.queued)} queued · {fmtInt(p.cancelled)} cancelled
        </div>
        <div className="text-xs mono" style={{ margin: '4px 0 3px' }} data-testid="session-runs-line">
          Runs: {fmtInt(session.runs.done)} / {fmtInt(session.runs.total)}
          {' · '}
          {fmtInt(session.runs.errors)} errors · {fmtInt(session.runs.capped)} gave up at max codelets ·{' '}
          {fmtInt(session.runs.retries)} retries
          {' · '}
          {fmtRate(session.runs_per_second)} · ETA {fmtEta(session.eta_seconds)} · {fmtInt(session.codelets)}{' '}
          codelets
        </div>
        <ProgressBar done={session.runs.done} total={session.runs.total} label="Runs done" />

        <div className="text-xs mono" style={{ marginTop: 4 }} data-testid="session-memory-line">
          {`Episodic Memory (this Training Mode Session's own, never cleared): ${fmtInt(session.memory.answers)} answers, ${fmtInt(session.memory.snags)} snags, version ${fmtInt(session.memory_version)}`}
        </div>
        <div className="text-xs text-muted" style={{ marginTop: 4 }} data-testid="session-settings-line">
          Settings (fixed): backend {s.backend} ·{' '}
          {fmtInt(s.seeds_per_problem)} seeds per problem from {s.seed_start} · max codelets per run{' '}
          {fmtInt(s.max_codelets)}
          {overrideCount > 0 ? ` · ${overrideCount} parameter overrides` : ''}
        </div>

        <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {session.state === 'stopped' ? (
            <button
              disabled={busy}
              onClick={() => void act('start the Training Mode Session', () => startSession(session.id))}
              title="Run the Training Mode Session from where it stopped"
            >
              Start
            </button>
          ) : session.state === 'paused' ? (
            <button disabled={busy} onClick={() => void act('resume the Training Mode Session', () => resumeSession(session.id))}>
              Resume
            </button>
          ) : (
            <button
              disabled={busy}
              onClick={() => void act('pause the Training Mode Session', () => pauseSession(session.id))}
              title="Stop starting new runs; runs already on a core finish"
            >
              Pause
            </button>
          )}
          <button
            disabled={busy || !live}
            onClick={() => void act('stop the Training Mode Session', () => stopSession(session.id))}
            title="Return to Stopped: runs in flight are dropped, everything else is kept, and Start continues from there"
          >
            Stop
          </button>
          <button disabled={busy} onClick={handleCancel} title="Cancel every queued and running problem; the state does not change">
            Cancel
          </button>
          <button disabled={busy} onClick={() => void handleDelete()}>
            Delete
          </button>
          <ControlHelp topic="session_run_state" label="start, pause, resume, stop and cancel" />
          <span style={{ flex: 1 }} />
          <span className="text-xs text-muted">Export:</span>
          {(['problems', 'distribution', 'runs'] as const).map((what) => (
            <span key={what} style={{ display: 'inline-flex', gap: 2 }}>
              <a href={sessionExportUrl(session.id, what, 'csv')} download style={linkButtonStyle}>
                {what} (CSV)
              </a>
              <a
                href={sessionExportUrl(session.id, what, 'json')}
                download
                aria-label={`Export ${what} as JSON`}
                title={what === 'runs' ? 'One JSON object per line' : 'JSON'}
                style={linkButtonStyle}
              >
                JSON
              </a>
            </span>
          ))}
          <ControlHelp topic="session_export" label="export" />
        </div>

        <PolicyEditor session={session} onSessionChanged={onSessionChanged} />
      </div>

      <AddProblems session={session} limits={limits} onSessionChanged={onSessionChanged} />

      <div style={cardStyle}>
        <div role="tablist" aria-label="Training Mode Session views" style={{ display: 'flex', gap: 2, marginBottom: 8 }}>
          {(['problems', 'memory'] as const).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              title={t === 'memory' ? "This Training Mode Session's own Episodic Memory (Training Mode), not Metacat Mode's" : undefined}
              style={{
                fontSize: 11,
                padding: '2px 10px',
                cursor: 'pointer',
                background: tab === t ? 'var(--bg-panel)' : 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 3,
                color: 'var(--text-primary)',
                fontWeight: tab === t ? 700 : 400,
              }}
            >
              {t === 'problems' ? 'Problems' : 'Memory'}
            </button>
          ))}
          {tab === 'memory' && <ControlHelp topic="training_mode_session_memory" label="the Memory tab" />}
        </div>
        {tab === 'memory' ? <MemoryTab session={session} /> : <ProblemsTable session={session} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The error policy, editable after creation
// ---------------------------------------------------------------------------

function PolicyEditor({
  session,
  onSessionChanged,
}: {
  session: SessionSummary;
  onSessionChanged: (t: SessionSummary) => void;
}) {
  const [policy, setPolicy] = useState<SessionErrorPolicy>(session.policy);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const serverPolicy = JSON.stringify(session.policy);
  const dirty = JSON.stringify(policy) !== serverPolicy;

  // Follow the server when the policy changes elsewhere (the Training Mode Session pausing itself, say).
  useEffect(() => {
    setPolicy(JSON.parse(serverPolicy) as SessionErrorPolicy);
  }, [serverPolicy]);

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      onSessionChanged(await updateSession(session.id, { policy }));
      setSaved(true);
    } catch (err) {
      setError(describeApiError(err, 'change the policy'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <details style={{ marginTop: 8 }} data-testid="policy-editor">
      <summary style={{ cursor: 'pointer', fontSize: 12 }}>When things go wrong</summary>
      <div style={{ marginTop: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center' }} className="text-xs text-muted">
          The error policy; changes apply from now on.
          <ControlHelp topic="session_error_policy" label="the error policy" />
        </div>
        <PolicyFields
          idPrefix="policy"
          policy={policy}
          onChange={(p) => {
            setSaved(false);
            setPolicy(p);
          }}
          disabled={busy}
        />
        {error && (
          <div role="alert" style={errorStyle}>
            {error}
          </div>
        )}
        <button disabled={busy || !dirty} onClick={() => void save()}>
          Save policy
        </button>
        {saved && (
          <span role="status" className="text-xs" style={{ marginLeft: 8 }}>
            Policy saved.
          </span>
        )}
      </div>
    </details>
  );
}

// ---------------------------------------------------------------------------
// Add problems to a Training Mode Session in any state
// ---------------------------------------------------------------------------

function AddProblems({
  session,
  limits,
  onSessionChanged,
}: {
  session: SessionSummary;
  limits: SessionLimits | null;
  onSessionChanged: (b: SessionSummary) => void;
}) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const parsed = useMemo(() => parseProblemText(text), [text]);

  const add = async () => {
    setBusy(true);
    setError(null);
    setDone(null);
    let added = 0;
    try {
      let latest = session;
      for (const part of chunk(parsed.problems, limits?.max_problems_per_request ?? FALLBACK_REQUEST_SIZE)) {
        if (part.length === 0) continue;
        const res = await addSessionProblems(session.id, part);
        added += res.added;
        latest = res.session;
        onSessionChanged(latest);
      }
      setDone(`Added ${added.toLocaleString()} problems.`);
      setText('');
    } catch (err) {
      setError(
        `${describeApiError(err, 'add the problems')}` +
          (added > 0 ? ` ${added.toLocaleString()} were added before this failed.` : ''),
      );
      if (added > 0) setText('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={cardStyle} data-testid="add-problems">
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <div style={sectionLabelStyle}>Add problems</div>
        <ControlHelp topic="session_add_problems" label="Add problems" />
      </div>
      {session.state === 'stopped' && (
        <div className="text-xs text-muted" style={{ margin: '4px 0' }}>
          This Training Mode Session is stopped: problems are stored now and run when it is started.
        </div>
      )}
      <div style={{ marginTop: 6 }}>
        <ProblemTextInput id="add-problems-text" value={text} onChange={setText} disabled={busy} demos rows={3} />
        <ProblemPreview parsed={parsed} seedsPerProblem={session.settings.seeds_per_problem} />
      </div>
      {error && (
        <div role="alert" style={{ ...errorStyle, marginTop: 6 }}>
          {error}
        </div>
      )}
      {done && (
        <div role="status" className="text-xs" style={{ marginTop: 6 }}>
          {done}
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        <button disabled={busy || parsed.problems.length === 0} onClick={() => void add()}>
          {busy ? 'Adding…' : `Add ${parsed.problems.length.toLocaleString()} problems`}
        </button>
      </div>
    </div>
  );
}
