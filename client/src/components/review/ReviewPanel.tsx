// ---------------------------------------------------------------------------
// ReviewPanel -- the Review view: session browser on the left, the selected
// Run's review on the right (WP3.9)
// ---------------------------------------------------------------------------
//
// Which review a Run gets is decided by its mode, because the modes record
// genuinely different things and there is nothing sensible to show a reader who
// opens the wrong one:
//
//   normal  two complete state captures -> start, end, and what changed
//   audit   every state-changing action -> the forward tick inspector
//   fast    nothing at all              -> say so, plainly
// ---------------------------------------------------------------------------

import { useEffect, useState } from 'react';
import type { RecordedRun } from '@/types';
import { ApiError, describeApiError, getRecordedRun } from '@/api/client';
import { ModeBadge } from '@/components/ModeBadge';
import { SessionBrowser } from './SessionBrowser';
import { NormalRunReview } from './NormalRunReview';
import { AuditRunReview } from './AuditRunReview';

export interface ReviewPanelProps {
  /**
   * A Run to open straight away, from `#/review/runs/42`.
   *
   * Fetched by id rather than found by walking the sessions: the reader arriving from
   * Run History knows the run and not the session, and asking them to guess which
   * session contains it is the gap this closes.
   */
  initialRunId?: number | null;
}

export function ReviewPanel({ initialRunId = null }: ReviewPanelProps) {
  const [run, setRun] = useState<RecordedRun | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  useEffect(() => {
    if (initialRunId === null) return;
    let cancelled = false;
    getRecordedRun(initialRunId)
      .then((r) => {
        if (cancelled) return;
        setRun(r);
        setOpenError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setRun(null);
        // A 404 is the record being absent, which for a Fast Run is the mode
        // working. Every other status is the server failing to hand over a record
        // that may well exist, and says so in its own terms.
        setOpenError(
          err instanceof ApiError && err.status === 404
            ? `Run #${initialRunId} has no record to review. A Fast Run writes no row at `
              + 'all, which is the mode working rather than a gap; re-run the problem in '
              + 'Normal or Audit mode.'
            : describeApiError(err, `load the recorded run #${initialRunId}`),
        );
      });
    return () => {
      cancelled = true;
    };
  }, [initialRunId]);

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(320px, 1fr) minmax(0, 2fr)',
        gap: 10,
        height: '100%',
        minHeight: 0,
      }}
    >
      <div style={{ minHeight: 0, overflow: 'auto' }}>
        {/* Said here because its absence is otherwise unexplained: a Fast Run has
            no database row at all, so it is not merely empty in this list — it is
            not in it. Somebody who has just run one and comes looking needs to be
            told that on the page rather than in the plan. */}
        <div className="text-xs text-muted" style={{ marginBottom: 6 }}>
          A Training Session is a sequence of Runs sharing one Episodic Memory. It
          ends when the memory is cleared. Fast Runs do not appear: they write
          nothing, including the row that would list them.
        </div>
        <SessionBrowser
          selectedRunId={run?.run_id ?? null}
          onSelectRun={setRun}
          focusSessionId={run?.session_id ?? null}
        />
      </div>

      <div style={{ minHeight: 0, overflow: 'auto' }}>
        {run === null ? (
          <div
            role={openError !== null ? 'alert' : undefined}
            className={openError !== null ? 'text-sm' : 'text-muted text-sm'}
            style={{ padding: 16, color: openError !== null ? 'var(--warning)' : undefined }}
          >
            {openError ?? 'Select a Run to review it.'}
          </div>
        ) : (
          <>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                marginBottom: 8,
                paddingBottom: 6,
                borderBottom: '1px solid var(--border)',
              }}
            >
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                Run #{run.run_id}
              </span>
              <ModeBadge mode={run.mode} />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                {run.initial}→{run.modified}; {run.target}→{run.answer ?? '?'}
              </span>
              <span className="text-muted text-xs">seed {run.seed}</span>
              <span className="text-muted text-xs">{run.status}</span>
            </div>

            <RunReview run={run} />
          </>
        )}
      </div>
    </div>
  );
}

function RunReview({ run }: { run: RecordedRun }) {
  if (run.mode === 'audit') return <AuditRunReview run={run} />;
  if (run.mode === 'normal') return <NormalRunReview run={run} />;
  return (
    <div className="text-muted text-sm" style={{ padding: 12 }}>
      Run #{run.run_id} ran in <strong>{run.mode}</strong> mode, which records
      nothing. There is no record to review, which is the mode doing what it
      promises rather than a fault. Re-run the problem in <em>normal</em> mode for
      the two boundary states, or <em>audit</em> mode to step through it.
    </div>
  );
}
