// ---------------------------------------------------------------------------
// ThemespaceView -- Three-column grid of theme clusters
// ---------------------------------------------------------------------------

import { useRunStore } from '@/store/runStore';
import type { ClusterState, ThemeState } from '@/types';

/** Human-readable short names for dimensions. */
const DIM_LABELS: Record<string, string> = {
  'plato-letter-category': 'Letter',
  'plato-string-position-category': 'StrPos',
  'plato-alphabetic-position-category': 'AlphaPos',
  'plato-direction-category': 'Direction',
  'plato-bond-category': 'BondCtgy',
  'plato-group-category': 'GroupCtgy',
  'plato-length': 'Length',
  'plato-object-category': 'ObjCtgy',
  'plato-bond-facet': 'BondFacet',
};

/** Human-readable short names for relations. */
const REL_LABELS: Record<string, string> = {
  identity: 'id',
  successor: 'succ',
  predecessor: 'pred',
  opposite: 'opp',
  diff: 'diff',
};

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

/** Determine if a theme is dominant in its cluster. */
function isDominant(theme: ThemeState, cluster: ClusterState): boolean {
  if (cluster.themes.length <= 1) return false;
  const maxAct = Math.max(...cluster.themes.map(t => Math.abs(t.activation)));
  if (maxAct < 5) return false;
  return Math.abs(theme.activation) === maxAct;
}

/** Activation bar — horizontal bar showing positive (green) / negative (red) */
function ActivationBar({ theme, dominant }: { theme: ThemeState; dominant: boolean }) {
  const absAct = Math.abs(theme.activation);
  const barWidth = Math.min(absAct, 100);
  const isPositive = theme.activation >= 0;

  return (
    <div
      title={`${theme.relation ?? 'base'}: ${theme.activation.toFixed(1)} (pos: ${theme.positive_activation.toFixed(1)}, neg: ${theme.negative_activation.toFixed(1)})`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        height: 18,
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
        {REL_LABELS[theme.relation ?? ''] ?? theme.relation ?? ''}
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
    </div>
  );
}

/** One dimension row showing the dimension label and all its relation bars. */
function DimensionPanel({ cluster }: { cluster: ClusterState }) {
  const dimLabel = DIM_LABELS[cluster.dimension] ?? cluster.dimension.replace('plato-', '');
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
        title={cluster.dimension}
      >
        {dimLabel}
      </div>
      {/* Theme activation bars */}
      {cluster.themes.map((theme, i) => (
        <ActivationBar
          key={i}
          theme={theme}
          dominant={isDominant(theme, cluster)}
        />
      ))}
    </div>
  );
}

export function ThemespaceView() {
  const themespace = useRunStore((s) => s.themespace);

  if (!themespace) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        No themespace data. Create or load a run.
      </div>
    );
  }

  const { clusters, active_theme_types } = themespace;
  const grouped = groupByType(clusters);

  const columnOrder = ['top_bridge', 'vertical_bridge', 'bottom_bridge'];
  const activeColumns = columnOrder.filter(
    t =>
      grouped[t]?.length ||
      active_theme_types.some(at => at.toLowerCase().replace(/[-\s]/g, '_') === t),
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
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${displayKeys.length}, 1fr)`,
        gap: 6,
        overflow: 'auto',
        height: '100%',
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
              <DimensionPanel key={i} cluster={cluster} />
            ))}
            {!grouped[key]?.length && (
              <div className="text-xs text-muted" style={{ textAlign: 'center', padding: 8 }}>
                No clusters
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
