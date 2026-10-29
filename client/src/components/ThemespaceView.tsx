// ---------------------------------------------------------------------------
// ThemespaceView -- Three-column grid of theme clusters
// ---------------------------------------------------------------------------

import { useCallback, useMemo } from 'react';

import { clampThemes } from '@/api/client';
import { useSelfWatchingDisabled } from '@/components/SelfWatchingWarning';
import { useRunStore, type ThemeEditState } from '@/store/runStore';
import type { ClusterState, ThemespaceState, ThemeState } from '@/types';

/** Map a theme type key to a column heading. */
function columnLabel(themeType: string): string {
  const t = themeType.toLowerCase().replace(/[-\s]/g, '_');
  if (t.includes('top')) return 'TOP BRIDGE';
  if (t.includes('vertical')) return 'VERTICAL BRIDGE';
  if (t.includes('bottom')) return 'BOTTOM BRIDGE';
  return themeType;
}

/** Group clusters by their theme_type. */
function groupByType(clusters: ClusterState[]): Record<string, ClusterState[]> {
  const groups: Record<string, ClusterState[]> = {};
  for (const c of clusters) {
    const key = c.theme_type;
    if (!groups[key]) groups[key] = [];
    groups[key].push(c);
  }
  return groups;
}

/** Dominance is decided by the engine (margin of 90 over the runner-up), not here. */
function isDominant(theme: ThemeState, _cluster: ClusterState): boolean {
  return theme.dominant === true;
}

/** Activation bar — horizontal bar showing positive (green) / negative (red) */
function ActivationBar({
  theme,
  dominant,
  relationLabels,
  onClamp,
  clickSelect,
}: {
  theme: ThemeState;
  dominant: boolean;
  /**
   * Theme-edit mode: the bar itself takes the click (`theme-graphics.ss:35-63`), a
   * plain click selecting +100 and a shift- or right-click selecting -100.
   */
  clickSelect?: boolean;
  /** Metacat's relation names ("iden", "opp", ...), served with the state. */
  relationLabels?: Record<string, string>;
  /** Absent in the review surfaces, which show a recorded state and cannot steer it. */
  onClamp?: (activation: number) => void;
}) {
  const absAct = Math.abs(theme.activation);
  const barWidth = Math.min(absAct, 100);
  const isPositive = theme.activation >= 0;

  // theme-graphics.ss:35-63 — a clamp pins one theme in its dimension and zeroes the
  // rest; clamping a theme that already holds that value clears it again.
  const clampTo = (value: number) => {
    if (!onClamp) return;
    onClamp(theme.activation === value ? 0 : value);
  };

  const held = (value: number) => theme.activation === value;

  return (
    <div
      title={`${theme.relation ?? 'base'}: ${theme.activation.toFixed(1)}`}
      onClick={
        clickSelect && onClamp
          ? (e) => clampTo(e.shiftKey ? -100 : 100)
          : undefined
      }
      onContextMenu={
        clickSelect && onClamp
          ? (e) => {
              e.preventDefault();
              clampTo(-100);
            }
          : undefined
      }
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        height: 18,
        cursor: clickSelect && onClamp ? 'pointer' : undefined,
      }}
    >
      {/* Relation label */}
      <div
        style={{
          width: 32,
          fontSize: 10,
          fontFamily: 'var(--font-mono)',
          color: dominant ? '#ffd700' : 'var(--text-secondary)',
          fontWeight: dominant ? 700 : 400,
          textAlign: 'right',
          flexShrink: 0,
        }}
      >
        {relationLabels?.[theme.relation ?? ''] ?? theme.relation ?? ''}
      </div>
      {/* Bar container */}
      <div
        style={{
          flex: 1,
          height: 12,
          background: 'rgba(255,255,255,0.04)',
          borderRadius: 2,
          position: 'relative',
          overflow: 'hidden',
          border: dominant ? '1px solid #ffd700' : '1px solid transparent',
        }}
      >
        {absAct > 0.5 && (
          <div
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              height: '100%',
              width: `${barWidth}%`,
              background: isPositive
                ? `rgba(76, 175, 80, ${0.4 + absAct / 200})`
                : `rgba(244, 67, 54, ${0.4 + absAct / 200})`,
              borderRadius: 2,
              transition: 'width 0.3s ease',
            }}
          />
        )}
        {/* Value text on bar */}
        {absAct > 2 && (
          <div
            style={{
              position: 'absolute',
              left: 3,
              top: 0,
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              fontSize: 8,
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-primary)',
              opacity: 0.9,
            }}
          >
            {theme.activation > 0 ? '+' : ''}{theme.activation.toFixed(0)}
          </div>
        )}
      </div>
      {/* Frozen indicator */}
      {theme.frozen && (
        <div style={{ fontSize: 9, color: 'cyan', flexShrink: 0 }}>F</div>
      )}
      {/* Clamping.  Buttons rather than left/right click: a right-click that means
          something is undiscoverable, and clamping a theme negatively is the whole
          point of the affordance (§2.4.2) rather than a secondary gesture. */}
      {onClamp && (
        <div
          style={{ display: 'flex', gap: 3, flexShrink: 0 }}
          onClick={(e) => e.stopPropagation()}
        >
          <ClampButton
            label="Clamp +100"
            active={held(100)}
            colour="#4caf50"
            title={
              held(100)
                ? `Clear the clamp on ${theme.relation ?? 'this theme'}.`
                : `Clamp ${theme.relation ?? 'this theme'} to +100 — positive thematic ` +
                  `pressure. The program will favour structures compatible with this ` +
                  `idea, and the rest of this dimension is zeroed first.`
            }
            onClick={() => clampTo(100)}
          />
          <ClampButton
            label="Clamp -100"
            active={held(-100)}
            colour="#f44336"
            title={
              held(-100)
                ? `Clear the clamp on ${theme.relation ?? 'this theme'}.`
                : `Clamp ${theme.relation ?? 'this theme'} to -100 — negative thematic ` +
                  `pressure. The program will avoid structures compatible with this ` +
                  `idea and prefer ones incompatible with it (S2.4.2). This is the ` +
                  `manual counterpart of jootsing.`
            }
            onClick={() => clampTo(-100)}
          />
        </div>
      )}
    </div>
  );
}

/** One clamp control: small, labelled, and explained on hover. */
function ClampButton({
  label,
  title,
  colour,
  active,
  onClick,
}: {
  label: string;
  title: string;
  colour: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      style={{
        fontSize: 8,
        fontFamily: 'var(--font-mono)',
        lineHeight: 1.1,
        padding: '1px 4px',
        borderRadius: 2,
        cursor: 'pointer',
        whiteSpace: 'nowrap',
        border: `1px solid ${active ? colour : 'var(--border)'}`,
        background: active ? `${colour}33` : 'transparent',
        color: active ? colour : 'var(--text-secondary)',
      }}
    >
      {label}
    </button>
  );
}

/** One dimension row showing the dimension label and all its relation bars. */
function DimensionPanel({
  cluster,
  labels,
  relationLabels,
  abbreviate,
  onClamp,
  clickSelect,
}: {
  cluster: ClusterState;
  clickSelect?: boolean;
  /** The vertical column is the narrow one: Metacat abbreviates there. */
  abbreviate?: boolean;
  /** Metacat's full and abbreviated dimension names, served with the state. */
  labels?: { name: string; abbreviation: string };
  relationLabels?: Record<string, string>;
  onClamp?: (theme: ThemeState, activation: number) => void;
}) {
  const dimLabel = (abbreviate ? labels?.abbreviation : labels?.name) ?? cluster.dimension.replace('plato-', '');
  const hasDominant = cluster.themes.some(t => isDominant(t, cluster));

  return (
    <div
      style={{
        marginBottom: 6,
        padding: '4px 6px',
        borderRadius: 3,
        background: hasDominant ? 'rgba(255, 215, 0, 0.06)' : 'transparent',
        borderLeft: hasDominant ? '2px solid #ffd700' : '2px solid transparent',
      }}
    >
      {/* Dimension label */}
      <div
        style={{
          fontSize: 10,
          fontFamily: 'var(--font-mono)',
          fontWeight: 600,
          color: hasDominant ? '#ffd700' : 'var(--text-accent)',
          marginBottom: 2,
        }}
        title={labels && labels.abbreviation !== labels.name ? `${cluster.dimension} (${labels.abbreviation})` : cluster.dimension}
      >
        {dimLabel}
      </div>
      {/* Theme activation bars */}
      {cluster.themes.map((theme, i) => (
        <ActivationBar
          key={i}
          theme={theme}
          dominant={isDominant(theme, cluster)}
          relationLabels={relationLabels}
          onClamp={onClamp ? (a) => onClamp(theme, a) : undefined}
          clickSelect={clickSelect}
        />
      ))}
    </div>
  );
}

/**
 * The three-column grid, given its data.
 *
 * Split from `ThemespaceView` so the review surfaces can show the Themespace of a
 * *recorded* state (WP3.9). The grid was already a pure function of the themespace
 * state; only the store read tied it to a live run.
 */
export function ThemespaceGrid({
  themespace,
  onClamp,
  onRelease,
  editing,
}: {
  themespace: ThemespaceState | null;
  /**
   * Theme-edit mode: the theme types claimed so far. A window not yet claimed says
   * "Click to select themes" (`display-edit-mode-message`, `theme-graphics.ss:373`).
   */
  editing?: { edited: string[] };
  /** Omitted by the review surfaces: a recorded Themespace is not steerable. */
  onClamp?: (theme: ThemeState, cluster: ClusterState, activation: number) => void;
  /** Undo the last clamp, as the Options menu's "Undo last clamp" does. */
  onRelease?: () => void;
}) {
  if (!themespace) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        No themespace data. Create or load a run.
      </div>
    );
  }

  const { clusters, active_theme_types } = themespace;
  const possible = themespace.possible_theme_types ?? active_theme_types;
  const grouped = groupByType(clusters);

  const columnOrder = ['top_bridge', 'vertical_bridge', 'bottom_bridge'];
  const activeColumns = columnOrder.filter(
    t =>
      grouped[t]?.length ||
      possible.some(at => at.toLowerCase().replace(/[-\s]/g, '_') === t),
  );
  const displayKeys = activeColumns.length > 0 ? activeColumns : Object.keys(grouped);

  if (displayKeys.length === 0) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        No theme clusters active.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, height: '100%' }}>
      {/* Thematic pressure indicator.  Themes are passive representations most of
          the time; pressure is switched on deliberately, by clamping a pattern. */}
      <div
        style={{
          fontSize: 10,
          fontFamily: 'var(--font-mono)',
          padding: '3px 6px',
          borderRadius: 3,
          flexShrink: 0,
          background: themespace.thematic_pressure
            ? 'rgba(255, 193, 7, 0.15)'
            : 'rgba(255,255,255,0.03)',
          border: themespace.thematic_pressure
            ? '1px solid rgba(255, 193, 7, 0.5)'
            : '1px solid var(--border)',
          color: themespace.thematic_pressure ? '#ffc107' : 'var(--text-secondary)',
        }}
        title={
          themespace.thematic_pressure
            ? 'A clamped pattern is steering structure-building toward these ideas.'
            : 'Themes are accumulating evidence but exerting no top-down pressure.'
        }
      >
        {themespace.thematic_pressure
          ? `THEMATIC PRESSURE ON — ${active_theme_types.join(', ')}`
          : 'thematic pressure off (themes passive)'}
        <span style={{ float: 'right', opacity: 0.7, display: 'flex', gap: 8 }}>
          {onRelease && themespace.thematic_pressure && (
            <button
              onClick={onRelease}
              title="Undo the most recent clamp: its themes, concepts and codelet urgencies are released, and the run goes back to building on evidence alone."
              style={{
                fontSize: 10,
                padding: '0 4px',
                background: 'transparent',
                border: '1px solid currentColor',
                borderRadius: 2,
                color: 'inherit',
                cursor: 'pointer',
              }}
            >
              Undo last clamp
            </button>
          )}
          <span>dominance margin {themespace.dominant_theme_margin ?? 90}</span>
        </span>
      </div>
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${displayKeys.length}, 1fr)`,
        gap: 6,
        overflow: 'auto',
        flex: 1,
        minHeight: 0,
      }}
    >
      {displayKeys.map(key => {
        const isActive = active_theme_types.some(
          at => at.toLowerCase().replace(/[-\s]/g, '_') === key,
        );
        return (
          <div
            key={key}
            style={{
              background: isActive ? 'rgba(76, 175, 80, 0.05)' : 'var(--bg-card)',
              borderRadius: 4,
              padding: '6px 4px',
              border: isActive ? '1px solid rgba(76, 175, 80, 0.3)' : '1px solid var(--border)',
              overflow: 'auto',
            }}
          >
            {/* Column header */}
            <div
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: isActive ? '#4caf50' : 'var(--text-accent)',
                marginBottom: 6,
                textTransform: 'uppercase',
                letterSpacing: 0.5,
                textAlign: 'center',
                borderBottom: '1px solid var(--border)',
                paddingBottom: 4,
              }}
            >
              {columnLabel(key)}
              {isActive && (
                <span style={{ fontSize: 8, marginLeft: 4, color: '#4caf50' }}>ACTIVE</span>
              )}
            </div>
            {/* Dimension panels */}
            {(grouped[key] ?? []).map((cluster, i) => (
              <DimensionPanel
                key={i}
                cluster={cluster}
                labels={themespace.dimension_labels?.[cluster.dimension]}
                relationLabels={themespace.relation_labels}
                abbreviate={key === 'vertical_bridge'}
                clickSelect={editing !== undefined}
                onClamp={
                  onClamp ? (theme, a) => onClamp(theme, cluster, a) : undefined
                }
              />
            ))}
            {editing !== undefined && !editing.edited.includes(key) && possible.some((at) => at.toLowerCase().replace(/[-\s]/g, '_') === key) && (
              <div
                className="text-xs text-muted"
                style={{ textAlign: 'center', padding: 4 }}
                data-testid={`theme-edit-message-${key}`}
              >
                Click to select themes
              </div>
            )}
            {!grouped[key]?.length && (
              <div className="text-xs text-muted" style={{ textAlign: 'center', padding: 8 }}>
                No clusters
              </div>
            )}
          </div>
        );
      })}
    </div>
    </div>
  );
}

/**
 * The live Themespace: `ThemespaceGrid` fed from the run store, and clampable.
 *
 * MetaCat's theme windows take a left-click to clamp a theme to +100 and a right-click
 * to -100 (`theme-graphics.ss:35-63`). That is the user's only direct handle on
 * *negative* thematic pressure — the manual counterpart of jootsing — and it is how the
 * dissertation produced Figures 4.5 and 4.6. The engine and the API have always
 * supported it; only the client never asked.
 */
export function ThemespaceView() {
  const themespace = useRunStore((s) => s.themespace);
  const runId = useRunStore((s) => s.runId);
  const themeEdit = useRunStore((s) => s.themeEdit);
  const refreshThemespace = useRunStore((s) => s.refreshThemespace);
  const refreshTrace = useRunStore((s) => s.refreshTrace);
  const undoLastClamp = useRunStore((s) => s.undoLastClamp);
  const editThemeType = useRunStore((s) => s.editThemeType);
  const selectTheme = useRunStore((s) => s.selectTheme);
  const selfWatchingOff = useSelfWatchingDisabled('loaded');

  const handleClamp = useCallback(
    async (theme: ThemeState, cluster: ClusterState, activation: number) => {
      if (runId == null) return;
      await clampThemes(runId, [
        {
          type: cluster.theme_type,
          dimension: cluster.dimension,
          relation: theme.relation ?? null,
          activation,
        },
      ]);
      // The clamp changes the Themespace and records a manual-clamp Trace event.
      await refreshThemespace();
      await refreshTrace();
    },
    [runId, refreshThemespace, refreshTrace],
  );

  // In theme-edit mode a click only chooses (`theme-graphics.ss:35-63`): the first
  // click in a window claims its theme type, and the ones after select themes in it.
  // Nothing reaches the server until Clamp Themes.
  const handleEditClick = useCallback(
    (theme: ThemeState, cluster: ClusterState, activation: number) => {
      // The bottom bridge has themes only when there is an answer to justify
      // (`ready-to-edit?`, `gui.ss:840-843`).
      if (!(themespace?.possible_theme_types ?? []).includes(cluster.theme_type)) return;
      editThemeType(cluster.theme_type);
      // `activation` is what the grid would set (0 when toggling the same value off);
      // selectTheme does its own toggling from the +100 / -100 the gesture means.
      const value = activation === 0 ? (theme.activation === 100 ? 100 : -100) : activation;
      selectTheme(cluster.theme_type, cluster.dimension, theme.relation ?? null, value);
    },
    [editThemeType, selectTheme, themespace],
  );

  const displayed = useMemo(
    () => (themeEdit && themespace ? editView(themespace, themeEdit) : themespace),
    [themespace, themeEdit],
  );

  // With self-watching off the theme windows are hidden (`gui.ss:625-626`).
  if (selfWatchingOff) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        The Themespace is hidden while self-watching is disabled.
      </div>
    );
  }

  return (
    <ThemespaceGrid
      themespace={displayed}
      onClamp={runId == null ? undefined : themeEdit ? handleEditClick : handleClamp}
      onRelease={runId == null || themeEdit ? undefined : () => void undoLastClamp()}
      editing={themeEdit ? { edited: themeEdit.edited } : undefined}
    />
  );
}

/**
 * What the Themespace looks like in theme-edit mode: everything blank except the
 * types the user has claimed, which show the chosen themes (`gui.ss:861-866`).
 */
function editView(themespace: ThemespaceState, edit: ThemeEditState): ThemespaceState {
  return {
    ...themespace,
    thematic_pressure: false,
    active_theme_types: [],
    clusters: themespace.clusters.map((cluster) => ({
      ...cluster,
      frozen: false,
      dominant_relation: null,
      themes: cluster.themes.map((theme) => {
        const chosen = edit.selected.find(
          (t) =>
            t.type === cluster.theme_type &&
            t.dimension === cluster.dimension &&
            t.relation === (theme.relation ?? null),
        );
        return {
          ...theme,
          activation: chosen ? chosen.activation : 0,
          frozen: false,
          dominant: false,
        };
      }),
    })),
  };
}
