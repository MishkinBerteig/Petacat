// ---------------------------------------------------------------------------
// Petacat -- Training Mode Session: the Configuration tab
// ---------------------------------------------------------------------------
//
// A Training Mode Session has its own configuration, which starts as its Starting Conceptual State
// and changes through Training-Mode learning (the learning sources: the in-worker learner, the
// external route and the Admin view). This tab lets the user watch it evolve: a version slider, the
// Slipnet graph at that version, the journal timeline (filterable by source), a diff of any two
// versions and a per-table row browser. It is read-only; editing is done in the configuration
// manager (Admin view, Configurations tab). Metacat Mode's global configuration is never shown here.
//
// Every read says where it came from: Live (in memory) for a running, paused or stopping session at
// its current version, Stored (as of last stop) otherwise.
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  describeApiError,
  getSessionConfiguration,
  getSessionConfigurationDiff,
  getSessionJournal,
  getSessionSlipnet,
} from '@/api/client';
import type { SessionSummary } from '@/types';
import type {
  SessionConfigurationCounts,
  SessionConfigurationDiff,
  SessionConfigurationRows,
  SessionJournal,
  SessionReadLabel,
  SessionSlipnet,
} from '@/types/sessionConfiguration';
import { SlipnetGraphView, type SlipnetGraphData } from '../SlipnetGraphView';
import { cardStyle, errorStyle, fmtInt, fmtTime, tableStyle, tdStyle, thStyle } from './shared';

export const LIVE_LABEL = 'Live (in memory)';
export const STORED_LABEL = 'Stored (as of last stop)';
const DEFAULT_SOURCES = ['admin', 'external', 'learner', 'restore'];
const MAX_ROWS_SHOWN = 300;

type Sub = 'graph' | 'timeline' | 'diff' | 'rows';
const SUBS: Array<[Sub, string]> = [
  ['graph', 'Slipnet graph'],
  ['timeline', 'Timeline'],
  ['diff', 'Compare versions'],
  ['rows', 'Table rows'],
];

/** "Live (in memory)" or "Stored (as of last stop)", with what the database holds when live. */
function ReadLabel({ read, testId }: { read: SessionReadLabel; testId: string }) {
  const live = read.source === 'live';
  const u = read.unsaved;
  return (
    <span className="text-xs" data-testid={testId} style={{ fontWeight: 600 }}>
      {live ? LIVE_LABEL : STORED_LABEL}
      {live && u && (
        <span className="text-muted" style={{ fontWeight: 400 }}>
          {' '}
          — saved through version {read.saved_through.configuration_revision ?? 0}; {fmtInt(u.configuration_batches)}{' '}
          unsaved configuration {u.configuration_batches === 1 ? 'change' : 'changes'}
        </span>
      )}
    </span>
  );
}

function keyText(key: Record<string, unknown>): string {
  return Object.entries(key)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(', ');
}

function cell(v: unknown): string {
  if (v === null || v === undefined) return '';
  return typeof v === 'object' ? JSON.stringify(v) : String(v);
}

export function ConfigurationTab({ session }: { session: SessionSummary }) {
  const id = session.id;
  const [counts, setCounts] = useState<SessionConfigurationCounts | null>(null);
  /** null follows the current version, so a live session is watched evolving. */
  const [pinned, setPinned] = useState<number | null>(null);
  const [sub, setSub] = useState<Sub>('graph');
  const [error, setError] = useState<string | null>(null);

  const current = counts?.version ?? 0;
  const version = pinned === null ? current : Math.min(pinned, current);
  const refreshKey = `${id}|${session.state}|${session.unsaved?.configuration_batches ?? ''}|${session.saved_through.configuration_revision ?? ''}`;

  useEffect(() => {
    let live = true;
    getSessionConfiguration(id)
      .then((c) => {
        if (!live) return;
        setCounts(c as SessionConfigurationCounts);
        setError(null);
      })
      .catch((err) => {
        if (live) setError(describeApiError(err, "load this Training Mode Session's configuration"));
      });
    return () => {
      live = false;
    };
  }, [id, refreshKey]);

  const setVersion = (v: number) => setPinned(v >= current ? null : v);

  return (
    <div data-testid="configuration-tab">
      <div className="text-xs text-muted" style={{ marginBottom: 6 }}>
        This Training Mode Session&apos;s own configuration, which began as its Starting Conceptual State and changes through
        Training-Mode learning. It never affects Metacat Mode&apos;s global configuration. This tab is read-only; edit it in the{' '}
        <a
          href={counts ? `#/admin?configuration=${counts.configuration_id}` : '#/admin'}
          data-testid="edit-configuration-link"
        >
          configuration manager
        </a>{' '}
        (Admin view, opened on this session&apos;s configuration).
      </div>
      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}
      {counts && (
        <div style={{ ...cardStyle, marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <label htmlFor="config-version" style={{ fontSize: 11, fontWeight: 600 }}>
              Configuration version
            </label>
            <input
              id="config-version"
              type="range"
              min={0}
              max={current}
              step={1}
              value={version}
              onChange={(e) => setVersion(Number(e.target.value))}
              style={{ width: 240 }}
              aria-valuetext={`version ${version} of ${current}`}
            />
            <span className="mono text-xs" data-testid="config-version-readout">
              Version {version} of {current}
              {pinned === null ? ' (current)' : ''}
            </span>
            {pinned !== null && (
              <button onClick={() => setPinned(null)} title="Follow the current version as it changes">
                Show current version
              </button>
            )}
            <ReadLabel read={counts} testId="config-read-label" />
          </div>
          <div className="text-xs text-muted mono" style={{ marginTop: 4 }}>
            Configuration hash {counts.config_hash.slice(0, 12)}
            {version === 0 ? ' · Version 0 is the Starting Conceptual State' : ''}
          </div>
        </div>
      )}
      <div role="tablist" aria-label="Configuration views" style={{ display: 'flex', gap: 2, marginBottom: 8 }}>
        {SUBS.map(([key, text]) => (
          <button
            key={key}
            role="tab"
            aria-selected={sub === key}
            onClick={() => setSub(key)}
            style={{
              fontSize: 11,
              padding: '2px 10px',
              cursor: 'pointer',
              background: sub === key ? 'var(--bg-panel)' : 'transparent',
              border: '1px solid var(--border)',
              borderRadius: 3,
              color: 'var(--text-primary)',
              fontWeight: sub === key ? 700 : 400,
            }}
          >
            {text}
          </button>
        ))}
      </div>
      {counts && sub === 'graph' && (
        <GraphView sessionId={id} version={version} current={current} refreshKey={refreshKey} />
      )}
      {counts && sub === 'timeline' && (
        <Timeline
          sessionId={id}
          refreshKey={refreshKey}
          selected={version}
          onShowVersion={(v) => {
            setVersion(v);
            setSub('graph');
          }}
        />
      )}
      {counts && sub === 'diff' && <Diff sessionId={id} current={current} refreshKey={refreshKey} />}
      {counts && sub === 'rows' && (
        <Rows sessionId={id} version={version} current={current} tables={counts.tables} refreshKey={refreshKey} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The Slipnet graph at a version
// ---------------------------------------------------------------------------

function GraphView({
  sessionId,
  version,
  current,
  refreshKey,
}: {
  sessionId: number;
  version: number;
  current: number;
  refreshKey: string;
}) {
  const [slipnet, setSlipnet] = useState<SessionSlipnet | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setError(null);
    getSessionSlipnet(sessionId, version === current ? undefined : version)
      .then((s) => {
        if (live) setSlipnet(s);
      })
      .catch((err) => {
        if (live) {
          setSlipnet(null);
          setError(describeApiError(err, `load the Slipnet at version ${version}`));
        }
      });
    return () => {
      live = false;
    };
  }, [sessionId, version, current, refreshKey]);

  const graph = useMemo<SlipnetGraphData | null>(() => {
    if (!slipnet) return null;
    const layout: Record<string, [number, number]> = {};
    for (const r of slipnet.layout) layout[r.node_name] = [r.grid_row, r.grid_col];
    return { nodes: slipnet.nodes, links: slipnet.links, layout };
  }, [slipnet]);

  return (
    <div data-testid="configuration-graph">
      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}
      {slipnet && (
        <div className="text-xs" style={{ marginBottom: 4 }} data-testid="graph-caption">
          Slipnet at version {slipnet.version}: {fmtInt(slipnet.nodes.length)} nodes, {fmtInt(slipnet.links.length)} links.{' '}
          <ReadLabel read={slipnet} testId="graph-read-label" />
        </div>
      )}
      {slipnet && slipnet.unplaced.length > 0 && (
        <div role="status" className="text-xs" style={{ ...errorStyle, borderColor: 'var(--warning)', color: 'var(--text-primary)' }} data-testid="unplaced-nodes">
          Nodes with no place in the layout (drawn in the rows below the grid): {slipnet.unplaced.join(', ')}.
        </div>
      )}
      {graph && (
        <div style={{ height: 520 }}>
          <SlipnetGraphView graph={graph} slipnet={null} readOnly />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The timeline of journal entries, filterable by source
// ---------------------------------------------------------------------------

function Timeline({
  sessionId,
  refreshKey,
  selected,
  onShowVersion,
}: {
  sessionId: number;
  refreshKey: string;
  selected: number;
  onShowVersion: (version: number) => void;
}) {
  const [source, setSource] = useState('');
  const [journal, setJournal] = useState<SessionJournal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seen, setSeen] = useState<string[]>(DEFAULT_SOURCES);

  useEffect(() => {
    let live = true;
    getSessionJournal(sessionId, { source: source || undefined })
      .then((j) => {
        if (!live) return;
        setJournal(j);
        setError(null);
        setSeen((prev) => Array.from(new Set([...prev, ...j.entries.map((e) => e.source)])).sort());
      })
      .catch((err) => {
        if (live) setError(describeApiError(err, "load this Training Mode Session's journal"));
      });
    return () => {
      live = false;
    };
  }, [sessionId, source, refreshKey]);

  return (
    <div data-testid="configuration-timeline">
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
        <label htmlFor="timeline-source" style={{ fontSize: 11 }}>
          Source
        </label>
        <select id="timeline-source" value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">All sources</option>
          {seen.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {journal && (
          <span className="text-xs text-muted" data-testid="timeline-count">
            {fmtInt(journal.total)} {journal.total === 1 ? 'entry' : 'entries'}, newest first
          </span>
        )}
        {journal && <ReadLabel read={journal} testId="timeline-read-label" />}
      </div>
      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}
      {journal && journal.entries.length === 0 && (
        <div className="text-xs text-muted">No journal entries{source ? ` from the source ${source}` : ''}.</div>
      )}
      {journal && journal.entries.length > 0 && (
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Version</th>
              <th style={thStyle}>Source</th>
              <th style={thStyle}>Actor</th>
              <th style={thStyle}>When</th>
              <th style={thStyle}>Changes</th>
              <th style={thStyle}>Tables</th>
              <th style={thStyle}>Note</th>
              <th style={thStyle} />
            </tr>
          </thead>
          <tbody>
            {journal.entries.map((e) => (
              <tr
                key={`${e.revision}-${e.id ?? 'pending'}`}
                data-testid="timeline-row"
                style={e.revision === selected ? { background: 'var(--bg-panel)' } : undefined}
              >
                <td style={tdStyle} className="mono">
                  {e.revision}
                </td>
                <td style={tdStyle}>{e.source}</td>
                <td style={tdStyle}>{e.actor}</td>
                <td style={tdStyle}>{fmtTime(e.occurred_at)}</td>
                <td style={tdStyle} className="mono">
                  +{e.counts.insert} ~{e.counts.update} -{e.counts.delete}
                </td>
                <td style={tdStyle}>{e.tables.join(', ')}</td>
                <td style={tdStyle}>
                  {e.pending && (
                    <strong data-testid="pending-label">{e.label || 'not yet saved'}</strong>
                  )}
                  {e.pending && e.note ? ' · ' : ''}
                  {e.note}
                </td>
                <td style={tdStyle}>
                  <button
                    onClick={() => onShowVersion(e.revision)}
                    aria-label={`Show version ${e.revision}`}
                    title="Move the version slider here and show the Slipnet graph"
                  >
                    Show
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The differences between any two versions
// ---------------------------------------------------------------------------

function Diff({ sessionId, current, refreshKey }: { sessionId: number; current: number; refreshKey: string }) {
  const [from, setFrom] = useState(0);
  const [to, setTo] = useState(current);
  const [result, setResult] = useState<SessionConfigurationDiff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const followed = useRef(true);

  // "To" follows the current version until the user chooses one.
  useEffect(() => {
    if (followed.current) setTo(current);
  }, [current]);

  const versions = useMemo(() => Array.from({ length: current + 1 }, (_, i) => i), [current]);

  const compare = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await getSessionConfigurationDiff(sessionId, from, to));
    } catch (err) {
      setResult(null);
      setError(describeApiError(err, `compare versions ${from} and ${to}`));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    setResult(null);
  }, [refreshKey]);

  return (
    <div data-testid="configuration-diff">
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6, flexWrap: 'wrap' }}>
        <label htmlFor="diff-from" style={{ fontSize: 11 }}>
          From version
        </label>
        <select id="diff-from" value={from} onChange={(e) => setFrom(Number(e.target.value))}>
          {versions.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
        <label htmlFor="diff-to" style={{ fontSize: 11 }}>
          To version
        </label>
        <select
          id="diff-to"
          value={to}
          onChange={(e) => {
            followed.current = false;
            setTo(Number(e.target.value));
          }}
        >
          {versions.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
        <button disabled={busy} onClick={() => void compare()}>
          Show differences
        </button>
      </div>
      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}
      {result && (
        <>
          <div className="text-xs" data-testid="diff-summary" style={{ marginBottom: 4 }}>
            {result.same
              ? `Versions ${result.from} and ${result.to} are the same.`
              : `Version ${result.from} to version ${result.to}: ${fmtInt(result.added)} rows added, ${fmtInt(result.removed)} removed, ${fmtInt(result.changed)} changed.`}{' '}
            <ReadLabel read={result} testId="diff-read-label" />
          </div>
          {result.rows.length > 0 && (
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>Table</th>
                  <th style={thStyle}>Row</th>
                  <th style={thStyle}>Change</th>
                  <th style={thStyle}>Columns</th>
                </tr>
              </thead>
              <tbody>
                {result.rows.slice(0, MAX_ROWS_SHOWN).map((r, i) => (
                  <tr key={i} data-testid="diff-row">
                    <td style={tdStyle}>{r.table}</td>
                    <td style={tdStyle} className="mono">
                      {keyText(r.key)}
                    </td>
                    <td style={tdStyle}>{r.change}</td>
                    <td style={tdStyle}>
                      {r.change === 'changed'
                        ? r.columns.map((c) => `${c}: ${cell(r.from?.[c])} → ${cell(r.to?.[c])}`).join('; ')
                        : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {result.rows.length > MAX_ROWS_SHOWN && (
            <div className="text-xs text-muted">
              Showing the first {MAX_ROWS_SHOWN} of {fmtInt(result.rows.length)} rows.
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The rows of one table at the chosen version
// ---------------------------------------------------------------------------

function Rows({
  sessionId,
  version,
  current,
  tables,
  refreshKey,
}: {
  sessionId: number;
  version: number;
  current: number;
  tables: Record<string, number>;
  refreshKey: string;
}) {
  const names = Object.keys(tables);
  const [table, setTable] = useState(names.includes('slipnet_node_defs') ? 'slipnet_node_defs' : (names[0] ?? ''));
  const [data, setData] = useState<SessionConfigurationRows | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!table) return;
    let live = true;
    getSessionConfiguration(sessionId, { version: version === current ? undefined : version, table })
      .then((d) => {
        if (!live) return;
        setData(d as SessionConfigurationRows);
        setError(null);
      })
      .catch((err) => {
        if (live) {
          setData(null);
          setError(describeApiError(err, `load the rows of ${table} at version ${version}`));
        }
      });
    return () => {
      live = false;
    };
  }, [sessionId, version, current, table, refreshKey]);

  const columns = useMemo(() => {
    const cols: string[] = [];
    for (const r of data?.rows ?? []) for (const k of Object.keys(r)) if (!cols.includes(k)) cols.push(k);
    return cols;
  }, [data]);

  return (
    <div data-testid="configuration-rows">
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
        <label htmlFor="rows-table" style={{ fontSize: 11 }}>
          Table
        </label>
        <select id="rows-table" value={table} onChange={(e) => setTable(e.target.value)}>
          {names.map((n) => (
            <option key={n} value={n}>
              {n} ({fmtInt(tables[n])})
            </option>
          ))}
        </select>
        <span className="text-xs text-muted">at version {version}</span>
        {data && <ReadLabel read={data} testId="rows-read-label" />}
      </div>
      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}
      {data && (
        <>
          <div className="text-xs text-muted" data-testid="rows-count">
            {fmtInt(data.count)} rows; identified by {data.key_columns.join(', ')}.
          </div>
          <div style={{ overflow: 'auto', maxHeight: 420 }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c} style={thStyle}>
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.slice(0, MAX_ROWS_SHOWN).map((r, i) => (
                  <tr key={i} data-testid="config-row">
                    {columns.map((c) => (
                      <td key={c} style={tdStyle} className="mono">
                        {cell(r[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.rows.length > MAX_ROWS_SHOWN && (
            <div className="text-xs text-muted">
              Showing the first {MAX_ROWS_SHOWN} of {fmtInt(data.rows.length)} rows.
            </div>
          )}
        </>
      )}
    </div>
  );
}
