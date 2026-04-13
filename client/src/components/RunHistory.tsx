// ---------------------------------------------------------------------------
// RunHistory -- Table of past runs with load and delete actions
// ---------------------------------------------------------------------------

import { useState, useEffect, useCallback } from 'react';
import { useRunStore } from '@/store/runStore';
import { listRuns, deleteRun, getRun } from '@/api/client';
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
  const epoch = useRunStore((s) => s.epoch);
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

  // Fetch on mount, when the current run changes, or after destructive ops
  useEffect(() => {
    fetchRuns();
  }, [fetchRuns, currentRunId, epoch]);

  const handleRowClick = useCallback(
    async (runId: number) => {
      try {
        const info = await getRun(runId);
        // Directly set store state to point at this existing run,
        // then refresh all sub-states from the server.
        useRunStore.setState({
          runId: info.run_id,
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

  if (runs.length === 0) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        No runs yet.
      </div>
    );
  }

  return (
    <div style={{ fontSize: 11 }}>
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
        <span style={{ width: 64, flexShrink: 0 }}>Status</span>
        <span style={{ width: 48, flexShrink: 0, textAlign: 'right' }}>Cdlts</span>
        <span style={{ width: 30, flexShrink: 0, textAlign: 'right' }}>T</span>
        <span style={{ width: 24, flexShrink: 0 }}></span>
      </div>

      {/* Rows */}
      {runs.map((run) => {
        const isActive = run.run_id === currentRunId;
        const problem = `${run.initial}->${run.modified}; ${run.target}`;

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
              title={problem}
            >
              {problem}
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
              {run.status}
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
