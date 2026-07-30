// ---------------------------------------------------------------------------
// RecordedStateViews -- the dashboard's own panels, fed recorded state (WP3.9)
// ---------------------------------------------------------------------------
//
// The plan is specific that the review surfaces "build on `WorkspaceView`,
// `SlipnetView`, `TraceView`, `ThemespaceView` rendering *recorded* state rather
// than live state". This is where that happens, and it is deliberately thin:
// every component below is the same component the dashboard renders, given data
// from a capture instead of from the run store.
//
// That only works because a projected capture is field-for-field identical to
// what the live serializers produce -- which is not assumed, it is pinned by
// `tests/module/test_capture_projection.py`.
// ---------------------------------------------------------------------------

import { useState } from 'react';
import { WorkspaceDiagram } from '../WorkspaceView';
import { SlipnetView } from '../SlipnetView';
import { ThemespaceGrid } from '../ThemespaceView';
import { TraceList } from '../TraceView';
import { CoderackBars } from '../CoderackView';
import type {
  CoderackState,
  SlipnetState,
  ThemespaceState,
  TraceEvent,
  WorkspaceState,
} from '@/types';

export interface RecordedPanels {
  workspace: WorkspaceState;
  slipnet: SlipnetState;
  coderack: CoderackState;
  themespace: ThemespaceState;
  trace: TraceEvent[];
}

type PanelKey = 'workspace' | 'slipnet' | 'themespace' | 'coderack' | 'trace';

const PANEL_LABELS: Record<PanelKey, string> = {
  workspace: 'Workspace',
  slipnet: 'Slipnet',
  themespace: 'Themespace',
  coderack: 'Coderack',
  trace: 'Trace',
};

/**
 * Tabbed rather than the dashboard's grid, because a review pane sits beside the
 * session list and the comparison and has perhaps half the width the dashboard
 * gives these panels. Five of them tiled at that size would be five illegible
 * thumbnails.
 */
export function RecordedStatePanels({
  state,
  height = 420,
}: {
  state: RecordedPanels;
  height?: number;
}) {
  const [panel, setPanel] = useState<PanelKey>('workspace');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div role="tablist" style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {(Object.keys(PANEL_LABELS) as PanelKey[]).map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={panel === key}
            onClick={() => setPanel(key)}
            style={{
              fontSize: 11,
              padding: '2px 9px',
              borderRadius: 3,
              cursor: 'pointer',
              background: panel === key ? 'var(--bg-highlight, #2a2a2a)' : 'transparent',
              border: `1px solid ${panel === key ? 'var(--text-accent)' : 'var(--border)'}`,
              color: panel === key ? 'var(--text-accent)' : 'var(--text-secondary)',
              fontWeight: panel === key ? 700 : 400,
            }}
          >
            {PANEL_LABELS[key]}
          </button>
        ))}
      </div>

      <div
        style={{
          height,
          minHeight: 0,
          overflow: 'auto',
          border: '1px solid var(--border)',
          borderRadius: 4,
          padding: 6,
          background: 'var(--bg-card)',
        }}
      >
        {panel === 'workspace' && <WorkspaceDiagram workspace={state.workspace} />}
        {/* `readOnly`: a recorded Slipnet cannot be clamped, and offering the action
            would be offering something that could only fail. */}
        {panel === 'slipnet' && <SlipnetView slipnet={state.slipnet} readOnly />}
        {panel === 'themespace' && <ThemespaceGrid themespace={state.themespace} />}
        {panel === 'coderack' && <CoderackBars coderack={state.coderack} />}
        {panel === 'trace' && <TraceList trace={state.trace} />}
      </div>
    </div>
  );
}
