// ---------------------------------------------------------------------------
// AuditRunReview -- the tick-level inspector, forward-stepping only (WP3.9)
// ---------------------------------------------------------------------------
//
// At any tick: the codelet that ran, the structures that changed, and the
// activation and temperature state at that instant.
//
// The first three come straight out of the recorded action log. The fourth does
// not -- Audit records the codelet and the temperature at every tick but not
// Slipnet or Themespace activation -- so the server reconstructs it by restoring
// the Run-start capture and re-executing forward, which is the mechanism WP3.8
// names. That is why this is forward-only in a way the UI cannot paper over: the
// engine on the other end really is walking the run again.
//
// Backwards scrubbing is deliberately not built. The controls therefore offer no
// way to ask for it, and if one is asked for anyway the server answers 409 -- which
// this component surfaces rather than silently restarting, because a scrubber that
// quietly re-ran two thousand codelets would be indistinguishable from one that had
// actually stepped back.
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useState } from 'react';
import {
  ApiError,
  advanceInspector,
  closeInspector,
  describeApiError,
  getAuditSummary,
  listAuditActions,
  openInspector,
} from '@/api/client';
import type { AuditAction, AuditActionSummary, InspectorState, RecordedRun } from '@/types';
import { Pager } from '@/components/Pager';
import { RecordedStatePanels } from './RecordedStateViews';

/** Jump sizes offered beside single-stepping. All forward. */
const STEPS = [1, 5, 15, 100];

/** How many recorded actions one window of the log holds. */
const LOG_PAGE_SIZE = 60;

const ACTION_COLORS: Record<string, string> = {
  codelet: 'var(--text-secondary)',
  trace_event: '#03a9f4',
  structure_built: '#4caf50',
  structure_broken: '#f44336',
  answer: 'var(--success)',
  valence: '#ffc107',
};

export function AuditRunReview({ run }: { run: RecordedRun }) {
  const [summary, setSummary] = useState<AuditActionSummary | null>(null);
  const [state, setState] = useState<InspectorState | null>(null);
  // The log is fetched in its own effect, so it lands a tick after the state does.
  // It carries the tick it was fetched for rather than being labelled from the
  // current position, which would caption a stale page with a tick it is not from.
  const [log, setLog] = useState<{ from: number; actions: AuditAction[]; total: number }>({
    from: 0,
    actions: [],
    total: 0,
  });
  // Where in the log the window starts. The server reports how many actions the
  // log holds from `from` onwards, and this is what reaches the ones past the
  // first window.
  const [logOffset, setLogOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  /** Why the recorded log below is empty. */
  const [logError, setLogError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Open on mount, and release on unmount: an open inspection holds a whole engine
  // on the server, so leaving one behind for every run somebody glanced at would
  // accumulate.
  //
  // The release is unconditional rather than guarded on the open having succeeded.
  // Unmounting while the open request is still in flight would otherwise leave an
  // inspection nobody holds a reference to, and closing one that was never opened
  // is answered with `closed: false` rather than an error.
  useEffect(() => {
    let cancelled = false;
    setState(null);
    setError(null);
    setBusy(true);
    setLogOffset(0);

    Promise.all([openInspector(run.run_id), getAuditSummary(run.run_id)])
      .then(([opened, s]) => {
        if (cancelled) return;
        setState(opened);
        setSummary(s);
      })
      .catch(
        (e) =>
          !cancelled &&
          setError(describeApiError(e, `open the inspector for run #${run.run_id}`)),
      )
      .finally(() => !cancelled && setBusy(false));

    return () => {
      cancelled = true;
      // The release is sent as this component goes away, and let go of: the
      // surface that carries a reason is going with it.
      void closeInspector(run.run_id).catch(() => {});
    };
  }, [run.run_id]);

  // A window of the recorded log around the current tick, so the reader can see
  // what the record says happened as well as what the reconstruction shows.
  useEffect(() => {
    if (!state) return;
    const from = Math.max(0, state.codelet_count - 2);
    listAuditActions(run.run_id, {
      from_codelet: from,
      limit: LOG_PAGE_SIZE,
      offset: logOffset,
    })
      .then((page) => {
        setLog({ from, actions: page.actions, total: page.total });
        setLogError(null);
      })
      .catch((e) => {
        // A window with no actions in it is a claim about the record, so a window
        // that could not be fetched says which of the two this is.
        setLog({ from, actions: [], total: 0 });
        setLogError(describeApiError(e, 'load the recorded action log'));
      });
  }, [run.run_id, state?.codelet_count, logOffset]);

  // Stepping moves the tick the log window is anchored on, so the window starts
  // again at the beginning of the new anchor.
  const step = useCallback(
    async (by: number) => {
      if (!state || busy) return;
      setBusy(true);
      setError(null);
      try {
        const next = await advanceInspector(run.run_id, state.codelet_count + by);
        setLogOffset(0);
        setState(next);
      } catch (e) {
        // A 409 is the one refusal with a meaning of its own: the destination is
        // behind the position the reconstruction has reached, and Phase 0 walks the
        // record forward.
        setError(
          e instanceof ApiError && e.status === 409
            ? 'The inspector steps forward only.'
            : describeApiError(e, 'step the inspection forward'),
        );
      } finally {
        setBusy(false);
      }
    },
    [run.run_id, state, busy],
  );

  const restart = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const opened = await openInspector(run.run_id);
      setLogOffset(0);
      setState(opened);
    } catch (e) {
      setError(describeApiError(e, 'start the inspection again'));
    } finally {
      setBusy(false);
    }
  }, [run.run_id]);

  if (run.action_count === 0) {
    return (
      <div className="text-muted text-sm" style={{ padding: 12 }}>
        Run #{run.run_id} recorded no actions. Only a Run created in <em>audit</em>{' '}
        mode records the per-tick log this inspector reads.
      </div>
    );
  }
  if (!state) {
    return (
      <div style={{ padding: 12, fontSize: 12 }}>
        {error ? (
          <span role="alert" style={{ color: 'var(--error)' }}>{error}</span>
        ) : (
          <span className="text-muted">Restoring the Run-start capture…</span>
        )}
      </div>
    );
  }

  const pct = state.final_codelet_count
    ? (state.codelet_count / state.final_codelet_count) * 100
    : 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {/* ---- Transport ---- */}
      <div
        style={{
          border: '1px solid var(--border)',
          borderRadius: 4,
          background: 'var(--bg-card)',
          padding: 8,
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>
            tick <strong>{state.codelet_count}</strong>
            <span className="text-muted"> / {state.final_codelet_count}</span>
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            T={state.temperature.toFixed(1)}
          </span>
          {state.recorded_temperature !== null && (
            <span
              className="text-xs"
              title="The temperature the audit log recorded at this tick. Equal to the reconstruction's, because the reconstruction is the same run."
              style={{
                color:
                  Math.abs(state.recorded_temperature - state.temperature) < 1e-6
                    ? '#4caf50'
                    : 'var(--error)',
              }}
            >
              {Math.abs(state.recorded_temperature - state.temperature) < 1e-6
                ? 'matches the record'
                : `record says ${state.recorded_temperature.toFixed(1)}`}
            </span>
          )}
          <span style={{ flex: 1 }} />
          {STEPS.map((n) => (
            <button
              key={n}
              onClick={() => step(n)}
              disabled={busy || state.at_end}
              style={btn}
              title={`Step forward ${n} codelet${n === 1 ? '' : 's'}`}
            >
              +{n}
            </button>
          ))}
          <button onClick={restart} disabled={busy} style={btn} title="Start the inspection again from the Run-start capture">
            ⟲ restart
          </button>
        </div>

        {/* A progress bar, not a scrubber: it reports position, it does not accept
            one, because Phase 0 cannot step backwards. */}
        <div
          role="progressbar"
          aria-valuenow={state.codelet_count}
          aria-valuemax={state.final_codelet_count}
          title="Position in the recorded Run. Forward-stepping only — backwards scrubbing is deferred (WP3.8)."
          style={{ height: 6, background: 'var(--bg-primary)', borderRadius: 3, overflow: 'hidden' }}
        >
          <div style={{ width: `${pct}%`, height: '100%', background: 'var(--text-accent)' }} />
        </div>

        {state.at_end && (
          <div className="text-xs text-muted">
            At the end of the record. Restart to walk it again.
          </div>
        )}
        {error && (
          <div role="alert" style={{ fontSize: 11, color: 'var(--error)' }}>
            {error}
          </div>
        )}
      </div>

      {/* ---- What happened at this tick ---- */}
      <div
        style={{
          border: '1px solid var(--border)',
          borderRadius: 4,
          background: 'var(--bg-card)',
          padding: 8,
          display: 'flex',
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div className="text-xs text-muted">codelet that ran</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            {state.codelet ? (
              <>
                {state.codelet.payload?.codelet_type}
                <span className="text-muted"> urgency {state.codelet.payload?.urgency}</span>
              </>
            ) : (
              <span className="text-muted">— (before the first codelet)</span>
            )}
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div className="text-xs text-muted">structures that changed</div>
          {state.structure_changes.length === 0 ? (
            <div className="text-muted" style={{ fontSize: 12 }}>none</div>
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {state.structure_changes.map((c) => (
                <span
                  key={c.sequence}
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    padding: '1px 5px',
                    borderRadius: 3,
                    border: `1px solid ${ACTION_COLORS[c.action_type] ?? 'var(--border)'}`,
                    color: ACTION_COLORS[c.action_type] ?? 'var(--text-secondary)',
                  }}
                  title={`strength ${c.payload?.strength}, level ${c.payload?.proposal_level}`}
                >
                  {c.action_type === 'structure_built' ? '+' : '−'}
                  {c.payload?.structure} #{c.payload?.id}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ---- The state at that instant ---- */}
      <RecordedStatePanels state={state} height={380} />

      {/* ---- The recorded log around here ---- */}
      <div>
        <div className="text-xs text-muted" style={{ marginBottom: 3 }}>
          Recorded action log from tick {log.from}
          {summary && <> · {summary.total} actions in this Run</>}
        </div>
        {logError !== null && (
          <div role="alert" className="text-xs" style={{ marginBottom: 3, color: 'var(--error)' }}>
            {logError}
          </div>
        )}
        <div
          style={{
            maxHeight: 180,
            overflow: 'auto',
            border: '1px solid var(--border)',
            borderRadius: 4,
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
          }}
        >
          {log.actions.map((a) => (
            <div
              key={a.sequence}
              style={{
                display: 'flex',
                gap: 8,
                padding: '1px 6px',
                background:
                  a.codelet_count === state.codelet_count
                    ? 'rgba(79, 195, 247, 0.12)'
                    : 'transparent',
              }}
            >
              <span style={{ width: 44, textAlign: 'right', color: 'var(--text-secondary)' }}>
                {a.sequence}
              </span>
              <span style={{ width: 44, textAlign: 'right', color: 'var(--text-secondary)' }}>
                c:{a.codelet_count}
              </span>
              <span style={{ width: 120, color: ACTION_COLORS[a.action_type] ?? 'var(--text-secondary)' }}>
                {a.action_type}
              </span>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {describe(a)}
              </span>
            </div>
          ))}
        </div>
        {/* The log runs to thousands of actions in an Audit Run, so the window has
            to move: this is what reaches the actions past the first sixty. */}
        <Pager
          offset={logOffset}
          limit={LOG_PAGE_SIZE}
          total={log.total}
          count={log.actions.length}
          onChange={setLogOffset}
          label={`actions from tick ${log.from}`}
        />
      </div>
    </div>
  );
}

/** One line of what an action says, per action type. */
function describe(a: AuditAction): string {
  const p = a.payload ?? {};
  switch (a.action_type) {
    case 'codelet':
      return `${p.codelet_type} (urgency ${p.urgency})`;
    case 'trace_event':
      return `${p.event_type}: ${p.description ?? ''}`;
    case 'structure_built':
    case 'structure_broken':
      return `${p.structure} #${p.id} strength ${p.strength}`;
    case 'answer':
      return `${p.answer} (quality ${Math.round(p.quality ?? 0)})`;
    case 'valence':
      return `${p.signal} ${p.strength}`;
    default:
      return JSON.stringify(p);
  }
}

const btn: React.CSSProperties = {
  fontSize: 11,
  padding: '2px 9px',
  borderRadius: 3,
  cursor: 'pointer',
  background: 'transparent',
  border: '1px solid var(--border)',
  color: 'var(--text-primary)',
};
