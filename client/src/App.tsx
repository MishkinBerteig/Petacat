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
import { useWorkspaceClick } from '@/hooks/useWorkspaceClick';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { getRun } from '@/api/client';

import { ErrorBoundary } from '@/components/ErrorBoundary';
import { ModeBadge } from '@/components/ModeBadge';
import { SubstrateBadge } from '@/components/SubstrateBadge';
import { SearchPalette } from '@/components/SearchPalette';
import { HelpPopover } from '@/components/HelpPopover';
import { HamburgerMenu } from '@/components/HamburgerMenu';
import { ModeSwitch, modeOfView, MODE_ACCENTS, MODE_LABELS } from '@/components/ModeSwitch';
import { WindowsMenu } from '@/components/WindowsMenu';
import { useDisplayStore, type PanelKey } from '@/store/displayStore';
import { LastErrorBanner } from '@/components/LastErrorBanner';
import type { AppView } from '@/components/HamburgerMenu';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { AdminPanel } from '@/components/AdminPanel';
import { ProblemInputPanel } from '@/components/ProblemInputPanel';
import { RunControlsPanel } from '@/components/RunControlsPanel';
import { WorkspaceView } from '@/components/WorkspaceView';
import { useWebSocket } from '@/hooks/useWebSocket';
import { SlipnetView } from '@/components/SlipnetView';
import { CoderackView } from '@/components/CoderackView';
import { EegView } from '@/components/EegView';
import { ThemespaceView } from '@/components/ThemespaceView';
import { TraceView } from '@/components/TraceView';
import { MemoryView } from '@/components/MemoryView';
import { TemperatureGauge } from '@/components/TemperatureGauge';
import { CommentaryPanel } from '@/components/CommentaryPanel';
import { VerbosePanel } from '@/components/VerbosePanel';
import { RunHistory } from '@/components/RunHistory';
import { ReviewPanel } from '@/components/review/ReviewPanel';
import { TrainingPanel } from '@/components/training/TrainingPanel';
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

/** The grid track list for a row of panels, leaving out the ones that are hidden. */
function columns(tracks: [boolean, string][]): string {
  const kept = tracks.filter(([on]) => on).map(([, width]) => width);
  return kept.length > 0 ? kept.join(' ') : '1fr';
}

/** What a panel shows with its graphics switched off, as Metacat blanks the window. */
function GraphicsOff({ name }: { name: string }) {
  return (
    <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
      {name} graphics are off (Windows menu). The panel is not being updated.
    </div>
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
  if (window.location.hash.startsWith('#/training')) return 'training';
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

/** A Training to select in the Training view: `#/training/7`. */
function parseTrainingIdFromHash(): number | null {
  const match = window.location.hash.match(/^#\/training\/(\d+)$/);
  return match ? parseInt(match[1], 10) : null;
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const { status, codeletCount, temperature, runId, runMode, refreshAll, isProcessing } =
    useRunStore();
  const hidden = useDisplayStore((s) => s.hidden);
  const slipnetGraphics = useDisplayStore((s) => s.slipnetGraphics);
  const coderackGraphics = useDisplayStore((s) => s.coderackGraphics);
  const onWorkspaceClick = useWorkspaceClick();
  const shown = (k: PanelKey) => !hidden.includes(k);
  const [searchOpen, setSearchOpen] = useState(false);
  const [view, setView] = useState<AppView>(parseViewFromHash);
  const [configEditNode, setConfigEditNode] = useState<string | null>(parseConfigNodeFromHash);
  const [reviewRunId, setReviewRunId] = useState<number | null>(parseReviewRunFromHash);
  const [trainingId, setTrainingId] = useState<number | null>(parseTrainingIdFromHash);

  // The engine's own account of the run, pushed as it moves rather than polled for.
  // A snag response clamping the temperature, or a run reaching an answer, reaches the
  // display without the client asking.
  useWebSocket(runId);

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
      setTrainingId(parseTrainingIdFromHash());
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
    setTrainingId(null);
    if (newView === 'config') {
      window.location.hash = '/config';
    } else if (newView === 'admin') {
      window.location.hash = '/admin';
    } else if (newView === 'review') {
      window.location.hash = '/review';
    } else if (newView === 'training') {
      window.location.hash = '/training';
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
        // The same route into an existing run that Run History takes, so a deep
        // link shows the run's own settings, its spreading threshold included.
        useRunStore.getState().adoptRun(info);
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
      <div
        className="app-header"
        data-mode={modeOfView(view)}
        // The mode's accent runs along the header's lower edge, so the mode can be
        // read without reading the switch.
        style={{ borderBottom: `3px solid ${MODE_ACCENTS[modeOfView(view)]}` }}
      >
        <HamburgerMenu activeView={view} onSelect={handleViewChange} disabled={isProcessing} />
        {view === 'dashboard' && <WindowsMenu />}
        <h1>Petacat</h1>
        <ModeSwitch view={view} onSelectView={handleViewChange} disabled={isProcessing} />
        <span className="text-muted text-sm">
          {view === 'config' ? (
            "Configuration — the global configuration Metacat Mode uses"
          ) : view === 'admin' ? (
            'Admin — the global configuration Metacat Mode uses'
          ) : view === 'review' ? (
            "Review — recorded Training Sessions (Metacat Mode's sessions)"
          ) : view === 'training' ? (
            `${MODE_LABELS.training} — Trainings: episodes of many problems over many seeds`
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

        {/* Why the last thing asked for did not happen, wherever it was asked from. */}
        <LastErrorBanner />
      </div>

      {/* ---- Config view ----
          Spans every content row, as Review and Admin do. Without the row span it
          occupied only the first (2fr) band at a fixed 500px, so the page stopped
          partway down the window whatever the window's height. minHeight 0 lets the
          grid shrink it, which is what allows the inner table to scroll rather than
          push the panel past the viewport. */}
      {view === 'config' && (
        <div
          className="panel"
          style={{ gridColumn: '1 / -1', gridRow: '2 / -1', minHeight: 0 }}
        >
          <div className="panel-content" style={{ height: '100%' }}>
            <AdminLayout editNodeName={configEditNode} onClearEditNode={() => setConfigEditNode(null)} />
          </div>
        </div>
      )}

      {/* ---- Review view (WP3.9) ----
          Reads the record rather than a live run, so it does not touch the run
          store at all and is unaffected by whatever is loaded on the dashboard. */}
      {view === 'review' && (
        <div
          className="panel"
          style={{ gridColumn: '1 / -1', gridRow: '2 / -1', minHeight: 0 }}
        >
          <div className="panel-content" style={{ height: '100%' }}>
            <ErrorBoundary fallback="Review">
              <ReviewPanel initialRunId={reviewRunId} />
            </ErrorBoundary>
          </div>
        </div>
      )}

      {/* ---- Training view ----
          Database-backed jobs, read from the server; independent of the run store
          except when "Open in dashboard" fills in the Problem Input form. */}
      {view === 'training' && (
        <div
          className="panel"
          style={{ gridColumn: '1 / -1', gridRow: '2 / -1', minHeight: 0 }}
        >
          <div className="panel-content" style={{ height: '100%' }}>
            <ErrorBoundary fallback="Training">
              <TrainingPanel initialTrainingId={trainingId} />
            </ErrorBoundary>
          </div>
        </div>
      )}

      {/* ---- Admin view ---- */}
      {view === 'admin' && (
        <div
          className="panel"
          style={{ gridColumn: '1 / -1', gridRow: '2 / -1', minHeight: 0 }}
        >
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
        {shown('workspace') && (
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
            <div className="panel-content" onClick={onWorkspaceClick}>
              <ErrorBoundary fallback="Workspace">
                <WorkspaceView />
              </ErrorBoundary>
            </div>
          </div>
        )}

        {shown('slipnet') && (
          <div className="panel slipnet-panel">
            <div className="panel-header">
              Slipnet
              <PanelHelpButton componentName="slipnet" />
            </div>
            <div className="panel-content">
              <ErrorBoundary fallback="Slipnet">
                {slipnetGraphics ? <SlipnetView /> : <GraphicsOff name="Slipnet" />}
              </ErrorBoundary>
            </div>
          </div>
        )}
      </div>

      {/* ---- Bottom row ---- */}
      <div
        className="bottom-row"
        style={{
          gridTemplateColumns: columns([
            [shown('coderack'), '1fr'],
            [shown('temperature'), '120px'],
            [shown('themespace'), '1fr'],
            [shown('trace'), '1fr'],
          ]),
        }}
      >
        {shown('coderack') && (
          <div className="panel">
            <div className="panel-header">
              Coderack
              <PanelHelpButton componentName="coderack" />
            </div>
            <div className="panel-content">
              <ErrorBoundary fallback="Coderack">
                {coderackGraphics ? <CoderackView /> : <GraphicsOff name="Coderack" />}
              </ErrorBoundary>
            </div>
          </div>
        )}

        {shown('temperature') && (
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
        )}

        {shown('themespace') && (
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
        )}

        {shown('trace') && (
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
        )}
      </div>

      {/* ---- Footer row: Memory + Commentary + History ---- */}
      <div
        className="bottom-row"
        style={{
          gridTemplateColumns: columns([
            [shown('memory'), '1fr'],
            [shown('commentary'), '2fr'],
            [shown('verbose'), '2fr'],
            [shown('run_history') || shown('eeg'), '1fr'],
          ]),
        }}
      >
        {shown('memory') && (
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
        )}

        {shown('commentary') && (
          <div className="panel">
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
        )}

        {shown('verbose') && (
          <div className="panel">
            <div className="panel-header">
              Verbose
              <PanelHelpButton componentName="verbose" />
            </div>
            <div className="panel-content">
              <ErrorBoundary fallback="Verbose">
                <VerbosePanel />
              </ErrorBoundary>
            </div>
          </div>
        )}

        {(shown('run_history') || shown('eeg')) && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minHeight: 0 }}>
            {shown('run_history') && (
              <div className="panel" style={{ flex: 1, minHeight: 0 }}>
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
            )}

            {shown('eeg') && (
              <div className="panel" style={{ flex: 1, minHeight: 0 }}>
                <div className="panel-header">
                  EEG
                  <PanelHelpButton componentName="eeg" />
                </div>
                <div className="panel-content">
                  <ErrorBoundary fallback="EEG">
                    <EegView />
                  </ErrorBoundary>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      </>}
    </div>
  );
}
