// ---------------------------------------------------------------------------
// SessionPanel -- the Training Mode Sessions view: the list on the left, the selected session on the right
// ---------------------------------------------------------------------------
//
// A Training Mode Session runs many problems, each over many seeds, on every core, and keeps its
// results in the database (server/training_mode_sessions). This view creates them, adds problems to
// them while they run, and reads the results back as distributions.
//
// Polling: the list every 3 s; the selected session and the problems page every 1.5 s
// while the session is running and every 5 s otherwise. All of it stops on unmount.
// ---------------------------------------------------------------------------

import { useEffect, useState } from 'react';
import { ApiError, describeApiError, getSession, listSessions } from '@/api/client';
import type { SessionListResponse, SessionSummary } from '@/types';
import { SessionDetail } from './SessionDetail';
import { SessionList, describeExecutor } from './SessionList';
import { NewSessionForm, type ConfigurationBase } from './NewSessionForm';
import { ControlHelp, errorStyle, noticeStyle, sectionLabelStyle, usePolling } from './shared';

const LIST_POLL_MS = 3000;
const RUNNING_POLL_MS = 1500;
const IDLE_POLL_MS = 5000;

export interface SessionPanelProps {
  /** A session to select straight away, from `#/training-mode/42`. */
  initialSessionId?: number | null;
}

/** Unavailable (no database, feature off): the server's own explanation, plainly. */
function unavailableText(err: unknown): string | null {
  if (err instanceof ApiError && (err.status === 404 || err.status === 503)) {
    return err.detail || 'Training Mode Sessions are not available on this server.';
  }
  return null;
}

/**
 * The configuration manager's "New session from this configuration" lands here:
 * `#/training-mode/new?base=global` or `base=session:7&name=Name`.
 */
function parseNewSessionBase(): ConfigurationBase | null {
  const match = window.location.hash.match(/^#\/training-mode\/new\?(.*)$/);
  if (!match) return null;
  const params = new URLSearchParams(match[1]);
  const base = params.get('base') ?? '';
  if (base === 'global') return { value: 'global', label: 'the global configuration (Metacat Mode)' };
  const session = base.match(/^session:(\d+)$/);
  if (!session) return null;
  const name = params.get('name');
  return {
    value: { session_id: Number(session[1]) },
    label: name ? `Training Mode Session '${name}' configuration` : `Training Mode Session ${session[1]} configuration`,
  };
}

export function SessionPanel({ initialSessionId = null }: SessionPanelProps) {
  const [list, setList] = useState<SessionListResponse | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(initialSessionId);
  const [selected, setSelected] = useState<SessionSummary | null>(null);
  const [selectedError, setSelectedError] = useState<string | null>(null);
  const [newBase] = useState<ConfigurationBase | null>(parseNewSessionBase);
  const [creating, setCreating] = useState(newBase !== null);
  const [notice, setNotice] = useState<string | null>(null);

  // `#/training-mode/<id>` can change under us (a link followed while the view is open).
  useEffect(() => {
    if (initialSessionId !== null) setSelectedId(initialSessionId);
  }, [initialSessionId]);

  const refreshList = async () => {
    try {
      const res = await listSessions();
      setList(res);
      setListError(null);
      setUnavailable(null);
    } catch (err) {
      const text = unavailableText(err);
      if (text) {
        setUnavailable(text);
        setListError(null);
      } else {
        setListError(describeApiError(err, 'load the sessions'));
      }
    }
  };
  usePolling(refreshList, LIST_POLL_MS);

  // Working: running with something to do (no idle or stalled activity).
  const working = selected?.id === selectedId && selected.state === 'running' && selected.activity === null;
  usePolling(
    async () => {
      if (selectedId === null) return;
      try {
        const b = await getSession(selectedId);
        setSelected(b);
        setSelectedError(null);
      } catch (err) {
        setSelectedError(describeApiError(err, 'load the session'));
      }
    },
    selectedId === null ? null : working ? RUNNING_POLL_MS : IDLE_POLL_MS,
    selectedId,
  );

  const select = (id: number | null) => {
    setSelectedId(id);
    setSelected(null);
    setSelectedError(null);
    setNotice(null);
    setCreating(false);
    window.location.hash = id === null ? '/training-mode' : `/training-mode/${id}`;
  };

  const current = selected && selected.id === selectedId ? selected : null;
  const onSessionChanged = (b: SessionSummary) => {
    setSelected(b);
    void refreshList();
  };

  return (
    <div
      data-testid="sessions-panel"
      style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 280px) 1fr', gap: 10, height: '100%', minHeight: 0 }}
    >
      {/* ---- Left: the list ---- */}
      <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, borderRight: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '6px 8px', gap: 6 }}>
          <div style={sectionLabelStyle}>Training Mode Sessions</div>
          <ControlHelp topic="session" label="Training Mode Sessions" />
          <span style={{ flex: 1 }} />
          <button
            onClick={() => {
              setCreating(true);
              setNotice(null);
            }}
            disabled={unavailable !== null}
          >
            New session
          </button>
        </div>
        {list && (
          <div className="text-xs text-muted mono" style={{ padding: '0 8px 6px' }} data-testid="executor-line">
            {describeExecutor(list.executor)}
          </div>
        )}
        <div style={{ overflow: 'auto', flex: 1 }}>
          {unavailable && (
            <div role="status" style={{ ...noticeStyle, margin: 8 }} data-testid="sessions-unavailable">
              {unavailable}
            </div>
          )}
          {listError && (
            <div role="alert" style={{ ...errorStyle, margin: 8 }}>
              {listError}
            </div>
          )}
          {list && <SessionList sessions={list.sessions} selectedId={selectedId} onSelect={select} />}
        </div>
      </div>

      {/* ---- Right: the form or the selected session ---- */}
      <div style={{ overflow: 'auto', padding: '6px 8px 6px 0', minHeight: 0 }}>
        {creating ? (
          <NewSessionForm
            limits={list?.limits ?? null}
            defaults={list?.defaults ?? null}
            configurationBase={newBase}
            onCancel={() => {
              setCreating(false);
              if (newBase) window.location.hash = '/training-mode';
            }}
            onCreated={(session, warning) => {
              void refreshList();
              select(session.id);
              setSelected(session);
              setNotice(warning);
            }}
          />
        ) : selectedId === null ? (
          <div className="text-muted text-sm" style={{ padding: 12 }}>
            {unavailable
              ? 'Training Mode Sessions are unavailable on this server.'
              : list && list.sessions.length === 0
                ? 'Create a session to begin.'
                : 'Select a session to see its problems.'}
          </div>
        ) : current ? (
          <>
            {selectedError && (
              <div role="alert" style={errorStyle}>
                {selectedError}
              </div>
            )}
            <SessionDetail
              key={current.id}
              session={current}
              limits={list?.limits ?? null}
              notice={notice}
              onSessionChanged={onSessionChanged}
              onDeleted={() => {
                select(null);
                void refreshList();
              }}
            />
          </>
        ) : selectedError ? (
          <div role="alert" style={errorStyle}>
            {selectedError}
          </div>
        ) : (
          <div className="text-muted text-sm" style={{ padding: 12 }}>
            Loading session…
          </div>
        )}
      </div>
    </div>
  );
}
