// ---------------------------------------------------------------------------
// Petacat -- Trainings: the problems of one training, filtered, sorted and paged
// ---------------------------------------------------------------------------
//
// Filtering, sorting and paging are the server's, so a training of thousands of
// problems stays quick. The rows of a running problem are partial and keep moving,
// and the order is not the order of processing.
// ---------------------------------------------------------------------------

import { Fragment, useEffect, useState } from 'react';
import { useRunStore } from '@/store/runStore';
import {
  cancelTrainingProblem,
  describeApiError,
  getTrainingProblem,
  getTrainingProblemRuns,
  listTrainingProblems,
} from '@/api/client';
import type {
  TrainingProblemDetail,
  TrainingProblemPage,
  TrainingProblemRow,
  TrainingProblemSort,
  TrainingProblemStatus,
  TrainingRun,
  TrainingSummary,
} from '@/types';
import { Pager } from '@/components/Pager';
import { formatProblem } from './problemText';
import {
  ControlHelp,
  errorStyle,
  fmtInt,
  fmtPct,
  outcomeLabel,
  sectionLabelStyle,
  tableStyle,
  tdStyle,
  thStyle,
  usePolling,
} from './shared';

const PAGE_SIZE = 50;
const POLL_RUNNING_MS = 1500;
const POLL_IDLE_MS = 5000;
const DETAIL_POLL_MS = 3000;
const SEARCH_DEBOUNCE_MS = 250;

type Tab = 'all' | TrainingProblemStatus;
const TABS: { key: Tab; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'queued', label: 'Queued' },
  { key: 'running', label: 'Running' },
  { key: 'finished', label: 'Finished' },
  { key: 'cancelled', label: 'Cancelled' },
];

interface Column {
  label: string;
  sort?: TrainingProblemSort;
  right?: boolean;
}
const COLUMNS: Column[] = [
  { label: 'Problem', sort: 'id' },
  { label: 'Status' },
  { label: 'Runs', sort: 'runs_done', right: true },
  { label: 'Top answer', sort: 'top_fraction' },
  { label: '2nd answer' },
  { label: 'No answer', sort: 'none_fraction', right: true },
  { label: 'Distinct', sort: 'distinct', right: true },
  { label: 'Codelets', sort: 'mean_codelets', right: true },
  { label: 'Errors', sort: 'errors', right: true },
  { label: 'Gave up', right: true },
];

function share(row: TrainingProblemRow, i: number): string {
  const s = row.top[i];
  return s ? `${outcomeLabel(s.answer)} ${fmtPct(s.fraction)}` : '–';
}

export function ProblemsTable({ training }: { training: TrainingSummary }) {
  const [tab, setTab] = useState<Tab>('all');
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<TrainingProblemSort>('id');
  const [order, setOrder] = useState<'asc' | 'desc'>('asc');
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<TrainingProblemPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  // The search box is applied a moment after typing stops.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search.trim());
      setOffset(0);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [search]);

  const interval = training.state === 'running' ? POLL_RUNNING_MS : POLL_IDLE_MS;
  const trainingId = training.id;
  const queryKey = `${trainingId}|${tab}|${q}|${sort}|${order}|${offset}`;

  usePolling(
    async () => {
      try {
        const res = await listTrainingProblems(trainingId, {
          status: tab === 'all' ? undefined : tab,
          q: q === '' ? undefined : q,
          sort,
          order,
          offset,
          limit: PAGE_SIZE,
        });
        setPage(res);
        setError(null);
      } catch (err) {
        setError(describeApiError(err, 'load the problems'));
      }
    },
    interval,
    queryKey,
  );

  const counts: Record<Tab, number> = {
    all: training.problems.total,
    queued: training.problems.queued,
    running: training.problems.running,
    finished: training.problems.finished,
    cancelled: training.problems.cancelled,
  };

  const clickSort = (col: TrainingProblemSort) => {
    if (col === sort) {
      setOrder(order === 'asc' ? 'desc' : 'asc');
    } else {
      setSort(col);
      setOrder(col === 'id' ? 'asc' : 'desc');
    }
    setOffset(0);
  };

  const rows = page?.problems ?? [];
  const empty = training.problems.total === 0;

  return (
    <div data-testid="problems-table">
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
        <div style={sectionLabelStyle}>Problems</div>
        <ControlHelp topic="training_problems_table" label="the problems table" />
      </div>

      {empty ? (
        <div className="text-muted text-sm" style={{ padding: 8 }}>
          Add problems to start.
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}>
            <div role="tablist" aria-label="Filter problems by status" style={{ display: 'flex', gap: 2 }}>
              {TABS.map((t) => (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={tab === t.key}
                  onClick={() => {
                    setTab(t.key);
                    setOffset(0);
                  }}
                  style={{
                    fontSize: 11,
                    padding: '2px 8px',
                    cursor: 'pointer',
                    background: tab === t.key ? 'var(--bg-panel)' : 'transparent',
                    border: '1px solid var(--border)',
                    borderRadius: 3,
                    color: 'var(--text-primary)',
                    fontWeight: tab === t.key ? 700 : 400,
                  }}
                >
                  {t.label} ({fmtInt(counts[t.key])})
                </button>
              ))}
            </div>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search strings"
              aria-label="Search problems"
              style={{ marginLeft: 'auto', width: 160 }}
            />
          </div>

          {error && (
            <div role="alert" style={errorStyle}>
              {error}
            </div>
          )}

          <div style={{ overflowX: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  {COLUMNS.map((c) => {
                    const active = c.sort !== undefined && c.sort === sort;
                    return (
                      <th
                        key={c.label}
                        style={{ ...thStyle, textAlign: c.right ? 'right' : 'left' }}
                        aria-sort={active ? (order === 'asc' ? 'ascending' : 'descending') : undefined}
                      >
                        {c.sort ? (
                          <button
                            type="button"
                            onClick={() => clickSort(c.sort!)}
                            title={`Sort by ${c.label.toLowerCase()}`}
                            style={sortButtonStyle}
                          >
                            {c.label}
                            {active ? (order === 'asc' ? ' ▲' : ' ▼') : ''}
                          </button>
                        ) : (
                          c.label
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.id}>
                    <tr
                      data-testid="problem-row"
                      onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                      aria-expanded={expanded === r.id}
                      style={{ cursor: 'pointer', background: expanded === r.id ? 'var(--bg-secondary)' : undefined }}
                    >
                      <td style={tdStyle} className="mono">
                        {formatProblem(r)}
                        {r.answer ? ` → ${r.answer}` : ''}
                      </td>
                      <td style={tdStyle}>{r.status}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>
                        {fmtInt(r.runs_done)} / {fmtInt(r.seeds)}
                      </td>
                      <td style={tdStyle} className="mono">
                        {share(r, 0)}
                      </td>
                      <td style={tdStyle} className="mono">
                        {share(r, 1)}
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtPct(r.none_fraction)}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>{r.runs_done > 0 ? r.distinct : '–'}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>
                        {r.mean_codelets === null ? '–' : fmtInt(Math.round(r.mean_codelets))}
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'right', color: r.errors > 0 ? 'var(--error)' : undefined }}>
                        {r.errors}
                      </td>
                      <td
                        style={{ ...tdStyle, textAlign: 'right' }}
                        title="Runs that reached max codelets without an answer"
                      >
                        {r.capped}
                      </td>
                    </tr>
                    {expanded === r.id && (
                      <tr>
                        <td colSpan={COLUMNS.length} style={{ ...tdStyle, padding: '6px 12px' }}>
                          <ProblemDetailView trainingId={trainingId} row={r} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
                {page && rows.length === 0 && (
                  <tr>
                    <td colSpan={COLUMNS.length} className="text-muted" style={{ ...tdStyle, padding: 8 }}>
                      No problems match.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            offset={offset}
            limit={PAGE_SIZE}
            total={page?.total ?? 0}
            count={rows.length}
            onChange={setOffset}
            label="problems"
          />
        </>
      )}
    </div>
  );
}

const sortButtonStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: 'inherit',
  font: 'inherit',
  fontWeight: 600,
  cursor: 'pointer',
  padding: 0,
};

// ---------------------------------------------------------------------------
// One expanded problem: its whole distribution
// ---------------------------------------------------------------------------

function ProblemDetailView({ trainingId, row }: { trainingId: number; row: TrainingProblemRow }) {
  const [detail, setDetail] = useState<TrainingProblemDetail | null>(null);
  const [runs, setRuns] = useState<TrainingRun[] | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  // Fetched on opening, then no more often than every 3 s while the problem is live.
  const live = (detail?.status ?? row.status) === 'queued' || (detail?.status ?? row.status) === 'running';
  usePolling(
    async () => {
      try {
        setDetail(await getTrainingProblem(trainingId, row.id));
        setError(null);
      } catch (err) {
        setError(describeApiError(err, 'load the problem'));
      }
      try {
        setRuns((await getTrainingProblemRuns(trainingId, row.id)).runs);
        setRunsError(null);
      } catch (err) {
        setRunsError(describeApiError(err, "load the problem's runs"));
      }
    },
    live ? DETAIL_POLL_MS : null,
    row.id,
  );

  const shown = detail ?? row;
  const canCancel = shown.status === 'queued' || shown.status === 'running';

  const openInDashboard = () => {
    useRunStore.getState().setFormInputs({
      initial: shown.initial,
      modified: shown.modified,
      target: shown.target,
      answer: shown.answer ?? '',
    });
    window.location.hash = '';
  };

  const cancel = async () => {
    setCancelling(true);
    setCancelError(null);
    try {
      await cancelTrainingProblem(trainingId, row.id);
      setDetail(await getTrainingProblem(trainingId, row.id));
    } catch (err) {
      setCancelError(describeApiError(err, 'cancel the problem'));
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div data-testid="problem-detail">
      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}
      {!detail && !error && <div className="text-xs text-muted">Loading…</div>}
      {detail && (
        <>
          <table style={{ ...tableStyle, width: 'auto', minWidth: 360 }}>
            <thead>
              <tr>
                <th style={thStyle}>Answer or outcome</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Count</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>%</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Quality</th>
                <th style={thStyle} aria-label="Share" />
              </tr>
            </thead>
            <tbody>
              {detail.distribution.map((d) => (
                <tr key={d.answer} data-testid="distribution-row">
                  <td style={tdStyle} className="mono">
                    {outcomeLabel(d.answer)}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtInt(d.count)}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{(d.fraction * 100).toFixed(1)}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {d.mean_quality === null ? '–' : d.mean_quality.toFixed(1)}
                  </td>
                  <td style={{ ...tdStyle, width: 160 }}>
                    <div
                      role="presentation"
                      style={{
                        height: 8,
                        width: `${Math.max(1, d.fraction * 100)}%`,
                        background: 'var(--text-accent, #6cf)',
                        borderRadius: 2,
                      }}
                    />
                  </td>
                </tr>
              ))}
              {detail.distribution.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-muted" style={tdStyle}>
                    No runs have finished yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <div className="text-xs text-muted" style={{ marginTop: 4 }}>
            Run status:{' '}
            {Object.entries(detail.statuses)
              .map(([k, v]) => `${k.replace(/_/g, ' ')} ${fmtInt(v)}`)
              .join(', ') || 'none yet'}
            {' · '}seeds {detail.seed_start} to {detail.seed_start + detail.seeds - 1}
          </div>
          {detail.first_error && (
            <div role="alert" style={{ ...errorStyle, marginTop: 6, whiteSpace: 'pre-wrap' }} className="mono">
              First error: {detail.first_error}
            </div>
          )}
          {runsError && (
            <div role="alert" style={{ ...errorStyle, marginTop: 6 }}>
              {runsError}
            </div>
          )}
          {runs && <RunsTable runs={runs} />}
        </>
      )}
      {cancelError && (
        <div role="alert" style={{ ...errorStyle, marginTop: 6 }}>
          {cancelError}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
        <button onClick={openInDashboard} title="Load this problem into Problem Input on the dashboard">
          Open in dashboard
        </button>
        {canCancel && (
          <button onClick={() => void cancel()} disabled={cancelling}>
            Cancel problem
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The runs of one problem, in seed order, paged
// ---------------------------------------------------------------------------

const RUNS_PAGE = 25;

function RunsTable({ runs }: { runs: TrainingRun[] }) {
  const [offset, setOffset] = useState(0);
  const shown = runs.slice(offset, offset + RUNS_PAGE);
  return (
    <div style={{ marginTop: 8 }} data-testid="runs-table">
      <div style={sectionLabelStyle}>Runs</div>
      {runs.length === 0 ? (
        <div className="text-xs text-muted">No runs have finished yet.</div>
      ) : (
        <>
          <div style={{ overflowX: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>Seed</th>
                  <th style={thStyle}>Outcome</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Codelets</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Quality</th>
                  <th style={{ ...thStyle, textAlign: 'right' }} title="The memory version the run started with">
                    Memory version
                  </th>
                  <th style={{ ...thStyle, textAlign: 'right' }} title="The run's merge order in the episode">
                    Seq
                  </th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Attempts</th>
                  <th style={thStyle}>Error</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.seed} data-testid="run-row">
                    <td style={tdStyle} className="mono">
                      {r.seed}
                    </td>
                    <td style={tdStyle} className="mono">
                      {outcomeLabel(r.key)}
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtInt(r.codelets)}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>
                      {r.answer_quality === null ? '–' : r.answer_quality.toFixed(1)}
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{r.memory_version ?? '–'}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{r.seq ?? '–'}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{r.attempts}</td>
                    <td
                      style={{ ...tdStyle, color: r.error ? 'var(--error)' : undefined, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={r.error ?? undefined}
                    >
                      {r.error ?? ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {runs.length > RUNS_PAGE && (
            <Pager
              offset={offset}
              limit={RUNS_PAGE}
              total={runs.length}
              count={shown.length}
              onChange={setOffset}
              label="runs"
            />
          )}
        </>
      )}
    </div>
  );
}
