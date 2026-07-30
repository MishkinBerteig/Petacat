// ---------------------------------------------------------------------------
// RunHistory -- Table of past runs with load and delete actions
// ---------------------------------------------------------------------------

import { useState, useEffect, useCallback } from 'react';
import { useRunStore } from '@/store/runStore';
import { listRuns, deleteRun, getRun } from '@/api/client';
import { ModeBadge } from '@/components/ModeBadge';
import type { RunInfo } from '@/types';

function statusColor(status: string): string {
  switch (status.toLowerCase()) {
    case 'completed':
    case 'answer_found':
      return 'var(--success)';
    case 'running':
      return 'var(--text-accent)';
    case 'halted':
    case 'stopped':
      return 'var(--error)';
    // Giving up is a considered outcome, not an error (§4.5.2).
    case 'gave_up':
      return 'var(--warning)';
    case 'initialized':
    case 'paused':
      return 'var(--warning)';
    default:
      return 'var(--text-secondary)';
  }
}

export function RunHistory() {
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const currentRunId = useRunStore((s) => s.runId);
  const currentRunMode = useRunStore((s) => s.runMode);
  const epoch = useRunStore((s) => s.epoch);
  // Live figures for the active run, used to keep its row current between
  // fetches (see liveView below).
  const liveStatus = useRunStore((s) => s.status);
  const liveCodeletCount = useRunStore((s) => s.codeletCount);
  const liveTemperature = useRunStore((s) => s.temperature);
  const liveAnswer = useRunStore((s) => s.workspace?.answer ?? null);
  const store = useRunStore();

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listRuns(50, 0);
      setRuns(data.runs);
    } catch (e: any) {
      setError(e.message ?? 'Failed to load runs');
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch on mount, when the current run changes, after destructive ops, and
  // on every status transition.
  //
  // `liveStatus` matters: this panel is mounted for the whole session, so
  // without it the list was fetched once when a run was created and never
  // again. Finished runs kept showing the values they had a moment after
  // creation — "initialized, 0 codelets, T 100" — even though the API had the
  // real outcome all along.
  useEffect(() => {
    fetchRuns();
  }, [fetchRuns, currentRunId, epoch, liveStatus]);

  /**
   * Overlay the store's live figures onto the active run's row.
   *
   * A row is otherwise only as fresh as the last fetch, so during a run the
   * current row would sit at a stale codelet count until it terminated. The
   * store already tracks these for the running engine, so preferring them costs
   * no extra requests.
   */
  const liveView = useCallback(
    (run: RunInfo): RunInfo =>
      run.run_id === currentRunId
        ? {
            ...run,
            status: liveStatus === 'idle' ? run.status : liveStatus,
            codelet_count: Math.max(run.codelet_count, liveCodeletCount),
            temperature: liveTemperature,
            // So an answer shows the moment it is found, rather than at the
            // next fetch.
            answer: liveAnswer ?? run.answer,
          }
        : run,
    [currentRunId, liveStatus, liveCodeletCount, liveTemperature, liveAnswer],
  );

  const handleRowClick = useCallback(
    async (runId: number) => {
      try {
        const info = await getRun(runId);
        // Directly set store state to point at this existing run,
        // then refresh all sub-states from the server.
        useRunStore.setState({
          runId: info.run_id,
          // Carried over so the run controls know whether pressing Run would
          // continue this run or start a new one under a different mode.
          runMode: info.mode ?? null,
          status: info.status as any,
          codeletCount: info.codelet_count,
          temperature: info.temperature,
        });
        await store.refreshAll();
      } catch {
        // ignore
      }
    },
    [store],
  );

  /**
   * Open this run in the Review browser.
   *
   * The record was reachable only by browsing Training Sessions, which is the right
   * way round when the reader is exploring and the wrong way round when they have
   * just watched a run finish: the session is precisely the thing they do not know,
   * and the run they want is one of however many in it. The hash carries the run id
   * so the link survives a reload and can be shared.
   */
  const handleReview = useCallback((e: React.MouseEvent, runId: number) => {
    e.stopPropagation();
    window.location.hash = `/review/runs/${runId}`;
  }, []);

  const handleDelete = useCallback(
    async (e: React.MouseEvent, runId: number) => {
      e.stopPropagation();
      if (!window.confirm(`Delete run #${runId}?`)) return;
      try {
        await deleteRun(runId);
        await fetchRuns();
      } catch {
        // ignore
      }
    },
    [fetchRuns],
  );

  if (loading) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        Loading runs...
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-sm" style={{ padding: 16, textAlign: 'center', color: 'var(--error)' }}>
        {error}
      </div>
    );
  }

  /**
   * Why the run on screen is not in the list below.
   *
   * A Fast Run writes nothing, including the `runs` row this list is built from, so
   * it is not merely missing from the table — it cannot be in it. Without saying so,
   * the most visible consequence of choosing Fast looks exactly like the list having
   * failed to refresh, which is a bug this panel has actually had before.
   */
  const fastRunNote = currentRunMode === 'fast' && currentRunId !== null && (
    <div
      className="text-xs"
      style={{
        padding: '5px 6px',
        borderBottom: '1px solid var(--border)',
        color: 'var(--warning)',
      }}
    >
      Run #{currentRunId} is a <strong>Fast</strong> run and is not listed: Fast
      writes nothing, including the row this list reads. Choose Normal or Audit
      under Recording for a run that appears here.
    </div>
  );

  if (runs.length === 0) {
    return (
      <div style={{ fontSize: 11 }}>
        {fastRunNote}
        <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
          No runs yet.
        </div>
      </div>
    );
  }

  return (
    <div style={{ fontSize: 11 }}>
      {fastRunNote}

      {/* Table header */}
      <div
        style={{
          display: 'flex',
          gap: 4,
          padding: '3px 6px',
          borderBottom: '2px solid var(--border)',
          fontWeight: 600,
          color: 'var(--text-secondary)',
          fontSize: 10,
          textTransform: 'uppercase',
          letterSpacing: 0.5,
        }}
      >
        <span style={{ width: 36, flexShrink: 0 }}>ID</span>
        <span style={{ flex: 1 }}>Problem</span>
        {/* What the run wrote down, which decides what the Review browser can show
            of it. Only Normal and Audit can appear at all — see fastRunNote. */}
        <span
          style={{ width: 54, flexShrink: 0 }}
          title="Persistence mode: what the run recorded. Fast runs write no row and so are never listed."
        >
          Mode
        </span>
        <span style={{ width: 64, flexShrink: 0 }}>Status</span>
        <span style={{ width: 48, flexShrink: 0, textAlign: 'right' }}>Cdlts</span>
        <span style={{ width: 30, flexShrink: 0, textAlign: 'right' }}>T</span>
        <span
          style={{ width: 30, flexShrink: 0, textAlign: 'right' }}
          title="Spreading activation threshold: which Slipnet nodes were allowed to spread. 100 is the original's behaviour."
        >
          Spr
        </span>
        <span style={{ width: 46, flexShrink: 0 }}></span>
        <span style={{ width: 24, flexShrink: 0 }}></span>
      </div>

      {/* Rows */}
      {runs.map((fetched) => {
        const run = liveView(fetched);
        const isActive = run.run_id === currentRunId;
        const problem = `${run.initial}->${run.modified}; ${run.target}`;
        // Show the answer once there is one. A justify-mode run's answer was
        // *given* rather than found, so it is marked to keep the two apart.
        const answer = run.answer || null;
        const answerIsGiven = !!run.justify_mode;

        return (
          <div
            key={run.run_id}
            onClick={() => handleRowClick(run.run_id)}
            style={{
              display: 'flex',
              gap: 4,
              padding: '3px 6px',
              borderBottom: '1px solid var(--border)',
              background: isActive ? 'var(--bg-panel)' : 'transparent',
              cursor: 'pointer',
              alignItems: 'center',
              transition: 'background 0.1s',
            }}
            onMouseEnter={(e) => {
              if (!isActive) (e.currentTarget.style.background = 'var(--bg-card)');
            }}
            onMouseLeave={(e) => {
              if (!isActive) (e.currentTarget.style.background = 'transparent');
            }}
          >
            <span
              className="mono"
              style={{
                width: 36,
                flexShrink: 0,
                color: isActive ? 'var(--text-accent)' : 'var(--text-primary)',
              }}
            >
              #{run.run_id}
            </span>
            <span
              className="mono"
              style={{
                flex: 1,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              title={
                answer
                  ? `${problem} -> ${answer}${answerIsGiven ? ' (given, to justify)' : ' (found)'}`
                  : problem
              }
            >
              {problem}
              {answer && (
                <>
                  <span style={{ color: 'var(--text-secondary)' }}>{' -> '}</span>
                  <span
                    style={{
                      color: answerIsGiven ? 'var(--warning)' : 'var(--success)',
                      fontWeight: 700,
                    }}
                  >
                    {answer}
                  </span>
                  {answerIsGiven && (
                    <span style={{ color: 'var(--text-secondary)' }}>{' ?'}</span>
                  )}
                </>
              )}
            </span>
            <span style={{ width: 54, flexShrink: 0 }}>
              <ModeBadge mode={run.mode ?? 'normal'} />
            </span>
            <span
              style={{
                width: 64,
                flexShrink: 0,
                color: statusColor(run.status),
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {run.status.replace(/_/g, ' ')}
            </span>
            <span
              className="mono"
              style={{
                width: 48,
                flexShrink: 0,
                textAlign: 'right',
                color: 'var(--text-secondary)',
              }}
            >
              {run.codelet_count}
            </span>
            <span
              className="mono"
              style={{
                width: 30,
                flexShrink: 0,
                textAlign: 'right',
                color: 'var(--text-secondary)',
              }}
            >
              {run.temperature.toFixed(0)}
            </span>
            {/* A run at anything other than 100 is not comparable with the
                others, so the value belongs in the record of the run. */}
            <span
              className="mono"
              style={{
                width: 30,
                flexShrink: 0,
                textAlign: 'right',
                color:
                  (run.spreading_threshold ?? 100) === 100
                    ? 'var(--text-secondary)'
                    : 'var(--warning)',
              }}
              title={
                (run.spreading_threshold ?? 100) === 100
                  ? 'Spreading threshold 100 — the original behaviour'
                  : `Spreading threshold ${run.spreading_threshold} — not the original behaviour`
              }
            >
              {run.spreading_threshold ?? 100}
            </span>
            {/* Every row here has a database row behind it — a Fast run cannot be
                listed — so every one of them has something to review. */}
            <button
              onClick={(e) => handleReview(e, run.run_id)}
              style={{
                width: 46,
                flexShrink: 0,
                fontSize: 10,
                padding: '1px 4px',
                color: 'var(--text-accent)',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
              }}
              title={
                run.mode === 'audit'
                  ? `Step through run #${run.run_id} tick by tick in the Review browser.`
                  : `Open run #${run.run_id} in the Review browser: its start and end states, and what changed between them.`
              }
            >
              review
            </button>
            <button
              onClick={(e) => handleDelete(e, run.run_id)}
              style={{
                width: 24,
                flexShrink: 0,
                fontSize: 10,
                padding: '1px 4px',
                color: 'var(--error)',
                textAlign: 'center',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
              }}
              title={`Delete run #${run.run_id}`}
            >
              x
            </button>
          </div>
        );
      })}
    </div>
  );
}
