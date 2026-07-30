// ---------------------------------------------------------------------------
// Petacat -- Main application layout
// ---------------------------------------------------------------------------
//
// Renders the full dashboard: header, control panel, workspace, slipnet,
// bottom-row panels (coderack, temperature, themespace, trace), and
// footer panels (memory, commentary, run history).
//
// Phase 6 additions:
//   - ErrorBoundary around every panel
//   - Global keyboard shortcuts (useKeyboardShortcuts)
//   - Cmd+K search palette (SearchPalette)
//   - HelpPopover always mounted for context-sensitive help
//   - URL hash routing: #/runs/:id loads a specific run on mount
//   - "?" help buttons on each panel header
// ---------------------------------------------------------------------------

import { useEffect, useState, useCallback } from 'react';
import { useRunStore } from '@/store/runStore';
import { useHelp } from '@/hooks/useHelp';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { getRun } from '@/api/client';
import type { RunStatus } from '@/store/runStore';

import { ErrorBoundary } from '@/components/ErrorBoundary';
import { ModeBadge } from '@/components/ModeBadge';
import { SubstrateBadge } from '@/components/SubstrateBadge';
import { SearchPalette } from '@/components/SearchPalette';
import { HelpPopover } from '@/components/HelpPopover';
import { HamburgerMenu } from '@/components/HamburgerMenu';
import type { AppView } from '@/components/HamburgerMenu';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { AdminPanel } from '@/components/AdminPanel';
import { ProblemInputPanel } from '@/components/ProblemInputPanel';
import { RunControlsPanel } from '@/components/RunControlsPanel';
import { WorkspaceView } from '@/components/WorkspaceView';
import { SlipnetView } from '@/components/SlipnetView';
import { CoderackView } from '@/components/CoderackView';
import { ThemespaceView } from '@/components/ThemespaceView';
import { TraceView } from '@/components/TraceView';
import { MemoryView } from '@/components/MemoryView';
import { TemperatureGauge } from '@/components/TemperatureGauge';
import { CommentaryPanel } from '@/components/CommentaryPanel';
import { RunHistory } from '@/components/RunHistory';
import { ReviewPanel } from '@/components/review/ReviewPanel';
import type { ComponentHelpKey } from '@/constants/helpTopics';

// ---------------------------------------------------------------------------
// PanelHelpButton -- small "?" button for each panel header
// ---------------------------------------------------------------------------
// componentName is constrained to ComponentHelpKey, a union generated from
// seed_data/help_topics.en.json by scripts/generate_help_docs.py. This makes
// typos a compile-time error and keeps the UI in sync with the SSOT.

function humanizeTopicKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function PanelHelpButton({ componentName }: { componentName: ComponentHelpKey }) {
  const { showHelp } = useHelp();
  const humanName = humanizeTopicKey(componentName);

  return (
    <button
      onClick={() => showHelp('component', componentName)}
      title={`Show help for ${humanName}`}
      aria-label={`Show help for ${humanName}`}
      style={{
        background: 'none',
        border: '1px solid var(--border, #444)',
        borderRadius: 4,
        color: 'var(--text-secondary, #999)',
        cursor: 'pointer',
        fontSize: 11,
        lineHeight: 1,
        padding: '1px 5px',
        marginLeft: 6,
        fontFamily: 'var(--font-mono)',
      }}
    >
      ?
    </button>
  );
}

// ---------------------------------------------------------------------------
// Hash routing helper
// ---------------------------------------------------------------------------

function parseRunIdFromHash(): number | null {
  // Expected format: #/runs/42
  const match = window.location.hash.match(/^#\/runs\/(\d+)$/);
  return match ? parseInt(match[1], 10) : null;
}

/**
 * Can this run be reached again by its URL?
 *
 * Only if it has a database row, and a Fast Run does not — it takes a negative id
 * from an in-process counter instead. A `#/runs/-1` link would survive the reload
 * that the run itself does not, and would then quietly fail to load anything, so no
 * link is written for one at all.
 */
function isDeepLinkable(runId: number | null): boolean {
  return runId !== null && runId > 0;
}

function parseViewFromHash(): AppView {
  if (window.location.hash.startsWith('#/config')) return 'config';
  if (window.location.hash.startsWith('#/admin')) return 'admin';
  if (window.location.hash.startsWith('#/review')) return 'review';
  return 'dashboard';
}

function parseConfigNodeFromHash(): string | null {
  // Expected format: #/config/slipnet/nodeName
  const match = window.location.hash.match(/^#\/config\/slipnet\/(.+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * A run to open in the Review browser: `#/review/runs/42`.
 *
 * The review surfaces were reachable only by browsing Training Sessions, which is
 * the wrong way round for a reader who has just watched a run finish — they know the
 * run and not the session. Putting the id in the hash also makes the link survive a
 * reload and be worth sending to somebody.
 */
function parseReviewRunFromHash(): number | null {
  const match = window.location.hash.match(/^#\/review\/runs\/(\d+)$/);
  return match ? parseInt(match[1], 10) : null;
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const { status, codeletCount, temperature, runId, runMode, refreshAll, isProcessing } =
    useRunStore();
  const [searchOpen, setSearchOpen] = useState(false);
  const [view, setView] = useState<AppView>(parseViewFromHash);
  const [configEditNode, setConfigEditNode] = useState<string | null>(parseConfigNodeFromHash);
  const [reviewRunId, setReviewRunId] = useState<number | null>(parseReviewRunFromHash);

  // Register global keyboard shortcuts
  const openSearch = useCallback(() => setSearchOpen(true), []);
  useKeyboardShortcuts({ onOpenSearch: openSearch });

  // Listen for hashchange events (e.g. from SlipnetView Edit button)
  useEffect(() => {
    const onHashChange = () => {
      const newView = parseViewFromHash();
      setView(newView);
      setConfigEditNode(parseConfigNodeFromHash());
      setReviewRunId(parseReviewRunFromHash());
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // Handle view switching with hash updates
  const handleViewChange = useCallback((newView: AppView) => {
    setView(newView);
    setConfigEditNode(null);
    // Choosing Review from the menu means "browse", not "reopen whatever run was
    // last deep-linked", so the pinned run is dropped along with the pinned node.
    setReviewRunId(null);
    if (newView === 'config') {
      window.location.hash = '/config';
    } else if (newView === 'admin') {
      window.location.hash = '/admin';
    } else if (newView === 'review') {
      window.location.hash = '/review';
    } else if (isDeepLinkable(runId)) {
      window.location.hash = `/runs/${runId}`;
    } else {
      history.replaceState(null, '', window.location.pathname + window.location.search);
    }
  }, [runId]);

  // On mount: check URL hash for a deep-linked run ID
  useEffect(() => {
    const deepLinkId = parseRunIdFromHash();
    if (deepLinkId === null) return;

    const loadRun = async () => {
      try {
        const info = await getRun(deepLinkId);
        useRunStore.setState({
          runId: info.run_id,
          runMode: info.mode ?? null,
          status: info.status as RunStatus,
          codeletCount: info.codelet_count,
          temperature: info.temperature,
        });
        await refreshAll();
      } catch (err) {
        console.error(`Failed to load run #${deepLinkId} from URL hash:`, err);
      }
    };

    void loadRun();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the URL hash in sync when runId changes (dashboard view only)
  useEffect(() => {
    if (view !== 'dashboard') return;
    if (isDeepLinkable(runId)) {
      window.location.hash = `/runs/${runId}`;
    } else {
      if (window.location.hash) {
        history.replaceState(null, '', window.location.pathname + window.location.search);
      }
    }
  }, [runId, view]);

  return (
    <div className="app-layout">
      {/* ---- Global overlays ---- */}
      <SearchPalette open={searchOpen} onClose={() => setSearchOpen(false)} />
      <HelpPopover />

      {/* ---- Header ---- */}
      <div className="app-header">
        <HamburgerMenu activeView={view} onSelect={handleViewChange} disabled={isProcessing} />
        <h1>Petacat</h1>
        <span className="text-muted text-sm">
          {view === 'config' ? (
            'Configuration'
          ) : view === 'admin' ? (
            'Admin'
          ) : view === 'review' ? (
            'Review — recorded Training Sessions'
          ) : (
            <>
              {runId ? `Run #${runId}` : 'No run'}
              {/* The mode belongs beside the run number rather than only in the
                  controls: it is the difference between a run that can be reopened
                  later and one that vanishes when the page does. */}
              {runId !== null && runMode && (
                <>
                  {' '}
                  <ModeBadge mode={runMode} />
                </>
              )}
              {' | '}
              Status: <span className="text-accent">{status}</span>
              {' | '}
              Codelets: {codeletCount}
              {' | '}
              T: {temperature.toFixed(1)}
            </>
          )}
          {' | '}
          <SubstrateBadge />
          {' | '}
          <button
            onClick={openSearch}
            title="Search (Cmd+K)"
            style={{
              background: 'none',
              border: '1px solid var(--border, #444)',
              borderRadius: 4,
              color: 'var(--text-secondary, #999)',
              cursor: 'pointer',
              fontSize: 11,
              padding: '1px 6px',
              fontFamily: 'var(--font-mono)',
            }}
          >
            Cmd+K
          </button>
        </span>
      </div>

      {/* ---- Config view ---- */}
      {view === 'config' && (
        <div className="panel" style={{ gridColumn: '1 / -1', minHeight: 500 }}>
          <div className="panel-content" style={{ height: '100%' }}>
            <AdminLayout editNodeName={configEditNode} onClearEditNode={() => setConfigEditNode(null)} />
          </div>
        </div>
      )}

      {/* ---- Review view (WP3.9) ----
          Reads the record rather than a live run, so it does not touch the run
          store at all and is unaffected by whatever is loaded on the dashboard. */}
      {view === 'review' && (
        <div className="panel" style={{ gridColumn: '1 / -1', gridRow: '2 / -1', minHeight: 600 }}>
          <div className="panel-content" style={{ height: '100%' }}>
            <ErrorBoundary fallback="Review">
              <ReviewPanel initialRunId={reviewRunId} />
            </ErrorBoundary>
          </div>
        </div>
      )}

      {/* ---- Admin view ---- */}
      {view === 'admin' && (
        <div className="panel" style={{ gridColumn: '1 / -1', gridRow: '2 / -1' }}>
          <div className="panel-content" style={{ height: '100%' }}>
            <ErrorBoundary fallback="Admin">
              <AdminPanel />
            </ErrorBoundary>
          </div>
        </div>
      )}

      {/* ---- Dashboard view ---- */}
      {view === 'dashboard' && <>

      {/* ---- Left column: Problem Input (top) + Run Controls (bottom) ---- */}
      <div className="left-column">
        <div className="panel problem-input-panel">
          <div className="panel-header">
            Problem Input
            <PanelHelpButton componentName="problem_input" />
          </div>
          <div className="panel-content">
            <ErrorBoundary fallback="Problem Input">
              <ProblemInputPanel />
            </ErrorBoundary>
          </div>
        </div>

        <div className="panel run-controls-panel">
          <div className="panel-header">
            Run Controls
            <PanelHelpButton componentName="run_controls" />
          </div>
          <div className="panel-content">
            <ErrorBoundary fallback="Run Controls">
              <RunControlsPanel />
            </ErrorBoundary>
          </div>
        </div>
      </div>

      {/* ---- Main row: Workspace (1/3) + Slipnet (2/3) ---- */}
      <div className="main-row">
        <div className="panel workspace-panel">
          <div className="panel-header">
            {isProcessing ? (
              <>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span className="processing-spinner-sm" />
                  <span style={{ color: 'var(--text-accent)', fontWeight: 700 }}>PROCESSING</span>
                </span>
                <button
                  onClick={() => useRunStore.getState().stop()}
                  style={{
                    background: 'var(--error)',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 3,
                    padding: '1px 8px',
                    fontSize: 10,
                    fontWeight: 600,
                    cursor: 'pointer',
                    marginLeft: 'auto',
                  }}
                >
                  STOP
                </button>
              </>
            ) : (
              <>
                Workspace
                <PanelHelpButton componentName="workspace" />
              </>
            )}
          </div>
          <div className="panel-content">
            <ErrorBoundary fallback="Workspace">
              <WorkspaceView />
            </ErrorBoundary>
          </div>
        </div>

        <div className="panel slipnet-panel">
          <div className="panel-header">
            Slipnet
            <PanelHelpButton componentName="slipnet" />
          </div>
          <div className="panel-content">
            <ErrorBoundary fallback="Slipnet">
              <SlipnetView />
            </ErrorBoundary>
          </div>
        </div>
      </div>

      {/* ---- Bottom row ---- */}
      <div className="bottom-row">
        <div className="panel">
          <div className="panel-header">
            Coderack
            <PanelHelpButton componentName="coderack" />
          </div>
          <div className="panel-content">
            <ErrorBoundary fallback="Coderack">
              <CoderackView />
            </ErrorBoundary>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            Temperature
            <PanelHelpButton componentName="temperature" />
          </div>
          <div className="panel-content">
            <ErrorBoundary fallback="Temperature">
              <TemperatureGauge />
            </ErrorBoundary>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            Themespace
            <PanelHelpButton componentName="themespace" />
          </div>
          <div className="panel-content">
            <ErrorBoundary fallback="Themespace">
              <ThemespaceView />
            </ErrorBoundary>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            Trace
            <PanelHelpButton componentName="trace" />
          </div>
          <div className="panel-content">
            <ErrorBoundary fallback="Trace">
              <TraceView />
            </ErrorBoundary>
          </div>
        </div>
      </div>

      {/* ---- Footer row: Memory + Commentary + History ---- */}
      <div className="bottom-row">
        <div className="panel">
          <div className="panel-header">
            Memory
            <PanelHelpButton componentName="memory" />
          </div>
          <div className="panel-content">
            <ErrorBoundary fallback="Memory">
              <MemoryView />
            </ErrorBoundary>
          </div>
        </div>

        <div className="panel" style={{ gridColumn: 'span 2' }}>
          <div className="panel-header">
            Commentary
            <PanelHelpButton componentName="commentary" />
          </div>
          <div className="panel-content">
            <ErrorBoundary fallback="Commentary">
              <CommentaryPanel />
            </ErrorBoundary>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            Run History
            <PanelHelpButton componentName="run_history" />
          </div>
          <div className="panel-content">
            <ErrorBoundary fallback="Run History">
              <RunHistory />
            </ErrorBoundary>
          </div>
        </div>
      </div>

      </>}
    </div>
  );
}
