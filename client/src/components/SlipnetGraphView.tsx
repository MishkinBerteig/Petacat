// ---------------------------------------------------------------------------
// SlipnetGraphView — SVG network graph of slipnet nodes and links
// ---------------------------------------------------------------------------

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useRunStore } from '@/store/runStore';
import { useLinkBehaviours } from '@/store/vocabulary';
import { api, describeApiError, request } from '@/api/client';
import type { SlipnetNodeDef, SlipnetState } from '@/types';

/** What `GET /api/admin/export` carries that the graph draws from. */
interface SlipnetExport {
  slipnet_nodes?: SlipnetNodeDef[];
  slipnet_layout?:
    | Array<{ node_name: string; grid_row: number; grid_col: number }>
    | { node_positions?: Record<string, [number, number]> };
}

export interface LinkDef {
  /** Absent in a configuration's link rows (they are keyed by their four natural-key columns). */
  id?: number;
  from_node: string;
  to_node: string;
  link_type: string;
  label_node: string | null;
  link_length: number | null;
  fixed_length: boolean;
}

// Link colours by BEHAVIOUR (what the engine does with a link of the type), never by the
// type's name: the run's configuration names its link types, and says each one's behaviour
// (`link_behaviours` in the run's vocabulary). Brighter/bolder for visibility on dark background.
const LINK_COLORS: Record<string, string> = {
  category: '#7799cc',
  instance: '#4a9eff',
  property: '#5dce5d',
  lateral: '#ffb347',
  slip: '#ff6b8a',
};

const LINK_DASH: Record<string, string> = {
  slip: '6,3',
};

function activationColor(activation: number): string {
  const t = Math.max(0, Math.min(100, activation)) / 100;
  const r = Math.round(21 + t * (255 - 21));
  const g = Math.round(101 - t * 78);
  const b = Math.round(192 - t * 142);
  return `rgb(${r},${g},${b})`;
}

/**
 * A Slipnet to draw that did not come from the live server: the nodes, the links and where the
 * layout puts each node as (row, column). A node the layout does not place is drawn in rows below
 * the grid (see `placeNodes`), so a configuration that has gained a node still shows it.
 */
export interface SlipnetGraphData {
  nodes: SlipnetNodeDef[];
  links: LinkDef[];
  layout: Record<string, [number, number]>;
}

/** Fewest columns an unplaced node's rows may use: the width of the Metacat Standard grid. */
const UNPLACED_COLS = 13;

/**
 * Where every node goes: its layout cell, or, for a node the layout does not place, the next free
 * cell in rows added below the grid (left to right, in node order). Returns the positions and the
 * names that were unplaced.
 */
export function placeNodes(
  names: string[],
  layout: Record<string, [number, number]>,
): { positions: Record<string, [number, number]>; unplaced: string[] } {
  const positions: Record<string, [number, number]> = {};
  let maxRow = -1;
  let maxCol = UNPLACED_COLS - 1;
  const unplaced: string[] = [];
  for (const name of names) {
    const p = layout[name];
    if (p) {
      positions[name] = p;
      maxRow = Math.max(maxRow, p[0]);
      maxCol = Math.max(maxCol, p[1]);
    } else {
      unplaced.push(name);
    }
  }
  const cols = maxCol + 1;
  unplaced.forEach((name, i) => {
    positions[name] = [maxRow + 2 + Math.floor(i / cols), i % cols];
  });
  return { positions, unplaced };
}

// Grid layout: 5 rows x 13 cols. Cell spacing for a clear, readable graph.
const CELL_W = 70;
const CELL_H = 80;
const PAD = 40;

interface GraphNode {
  name: string;
  shortName: string;
  depth: number;
  x: number;
  y: number;
}

interface Props {
  onSelectNode?: (name: string) => void;
  onDoubleClickNode?: (name: string) => void;
  selectedNode?: string | null;
  /**
   * Activations to draw. Omit for the live run; pass a recorded state to review one
   * (WP3.9).
   *
   * This component takes an override rather than being split into a pure part and a
   * store-reading wrapper, as `WorkspaceView` and the others were. The layout and the
   * drawing here really are pure, but the graph is also an *interactive* surface —
   * right-clicking a node clamps it in the live run — and clamping is meaningless on
   * a recording. Rather than tear the interaction out to a container, the review
   * caller passes `readOnly` and gets the same picture without the actions that only
   * a live engine can honour.
   */
  slipnet?: SlipnetState | null;
  /** Suppress the clamp menu: a recorded Slipnet cannot be clamped. */
  readOnly?: boolean;
  /**
   * The nodes, links and layout to draw. Omit them and the graph loads the global configuration's
   * from the server (Metacat Mode); pass them and it draws exactly these and makes no request
   * (a Training Mode Session's configuration at a version).
   */
  graph?: SlipnetGraphData;
}

export function SlipnetGraphView({
  onSelectNode,
  onDoubleClickNode,
  selectedNode,
  slipnet: slipnetOverride,
  readOnly = false,
  graph,
}: Props) {
  const liveSlipnet = useRunStore((s) => s.slipnet);
  const liveRunId = useRunStore((s) => s.runId);
  // `undefined` means "not supplied"; `null` is a supplied-but-empty recorded state,
  // which must not fall back to the live run's activations.
  const slipnet = slipnetOverride !== undefined ? slipnetOverride : liveSlipnet;
  const runId = readOnly ? null : liveRunId;

  const supplied = graph !== undefined;
  const [fetchedNodes, setNodeDefs] = useState<SlipnetNodeDef[]>([]);
  const [fetchedLinks, setLinks] = useState<LinkDef[]>([]);
  const [fetchedGrid, setGridPositions] = useState<Record<string, [number, number]>>({});
  const [fetchedLoading, setLoading] = useState(true);
  const loading = supplied ? false : fetchedLoading;
  const nodeDefs = supplied ? graph.nodes : fetchedNodes;
  const links = supplied ? graph.links : fetchedLinks;
  const suppliedLayout = supplied ? graph.layout : null;
  const gridPositions = useMemo(
    () => placeNodes(nodeDefs.map((n) => n.name), suppliedLayout ?? fetchedGrid).positions,
    [nodeDefs, suppliedLayout, fetchedGrid],
  );
  /** Why the graph is empty: the nodes and links did not arrive. */
  const [loadError, setLoadError] = useState<string | null>(null);
  /** Why the last clamp asked for is not in force. */
  const [actionError, setActionError] = useState<string | null>(null);
  // A link type is shown unless its box was unticked.
  const [linkFilters, setLinkFilters] = useState<Record<string, boolean>>({});
  const { behaviourOf, linkTypes } = useLinkBehaviours();
  const colourOf = (linkType: string) => LINK_COLORS[behaviourOf(linkType) ?? ''] ?? '#888';
  // The run's link types, then any the drawn links use that the run does not describe.
  const filterTypes = useMemo(() => {
    const out = [...linkTypes];
    for (const l of links) if (!out.includes(l.link_type)) out.push(l.link_type);
    return out;
  }, [linkTypes, links]);

  // Zoom and pan state
  const [zoomPct, setZoomPct] = useState(100);
  const [baseViewBox, setBaseViewBox] = useState({ x: 0, y: 0, w: 1000, h: 600 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 });
  const svgRef = useRef<SVGSVGElement>(null);

  // Context menu
  const [contextMenu, setContextMenu] = useState<{
    x: number; y: number; nodeName: string; frozen: boolean;
  } | null>(null);

  useEffect(() => {
    if (supplied) return;
    Promise.all([
      request<SlipnetExport>('/admin/export'),
      api.getSlipnetLinks(),
    ]).then(([exportData, linkData]) => {
      setNodeDefs(exportData.slipnet_nodes ?? []);

      // slipnet_layout is a list of {node_name, grid_row, grid_col}
      const layout = exportData.slipnet_layout;
      const posMap: Record<string, [number, number]> = {};
      if (Array.isArray(layout)) {
        for (const item of layout) {
          posMap[item.node_name] = [item.grid_row, item.grid_col];
        }
      } else if (layout?.node_positions) {
        // Fallback for dict format
        Object.assign(posMap, layout.node_positions);
      }
      setGridPositions(posMap);
      setLinks(linkData);
      setLoadError(null);
      setLoading(false);
    }).catch((err) => {
      // The 59 nodes and 202 links are what the graph draws; when they do not
      // arrive, the reason takes their place.
      setLoadError(describeApiError(err, 'load the Slipnet graph'));
      setLoading(false);
    });
  }, [supplied]);

  useEffect(() => {
    const handler = () => setContextMenu(null);
    window.addEventListener('click', handler);
    return () => window.removeEventListener('click', handler);
  }, []);

  // Place nodes on a semantic grid from slipnet_layout.json
  const graphNodes = useMemo<GraphNode[]>(() => {
    if (nodeDefs.length === 0) return [];

    return nodeDefs.map(def => {
      const pos = gridPositions[def.name] ?? [0, 0];
      return {
        name: def.name,
        shortName: def.short_name,
        depth: def.conceptual_depth,
        x: PAD + pos[1] * CELL_W + CELL_W / 2,
        y: PAD + pos[0] * CELL_H + CELL_H / 2,
      };
    });
  }, [nodeDefs, gridPositions]);

  // Compute base viewBox from grid bounds
  useEffect(() => {
    if (graphNodes.length === 0) return;
    let maxCol = 0, maxRow = 0;
    for (const name in gridPositions) {
      const p = gridPositions[name];
      if (p[0] > maxRow) maxRow = p[0];
      if (p[1] > maxCol) maxCol = p[1];
    }
    setBaseViewBox({
      x: 0,
      y: 0,
      w: PAD * 2 + (maxCol + 1) * CELL_W,
      h: PAD * 2 + (maxRow + 1) * CELL_H,
    });
    setZoomPct(100);
    setPanOffset({ x: 0, y: 0 });
  }, [graphNodes, gridPositions]);

  const viewBox = useMemo(() => {
    const scale = 100 / zoomPct;
    const cx = baseViewBox.x + baseViewBox.w / 2 - panOffset.x;
    const cy = baseViewBox.y + baseViewBox.h / 2 - panOffset.y;
    const w = baseViewBox.w * scale;
    const h = baseViewBox.h * scale;
    return { x: cx - w / 2, y: cy - h / 2, w, h };
  }, [baseViewBox, zoomPct, panOffset]);

  const nodeMap = useMemo(() => {
    const m: Record<string, GraphNode> = {};
    for (const n of graphNodes) m[n.name] = n;
    return m;
  }, [graphNodes]);

  const visibleLinks = useMemo(
    () => links.filter(l => linkFilters[l.link_type] !== false),
    [links, linkFilters],
  );

  // Zoom controls
  const zoomIn = useCallback(() => setZoomPct(z => Math.min(800, z + 25)), []);
  const zoomOut = useCallback(() => setZoomPct(z => Math.max(10, z - 25)), []);
  const zoomFit = useCallback(() => { setZoomPct(100); setPanOffset({ x: 0, y: 0 }); }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    if ((e.target as Element).closest('.graph-node')) return;
    setIsPanning(true);
    setPanStart({ x: e.clientX, y: e.clientY });
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isPanning || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const scale = 100 / zoomPct;
    const scaleX = (baseViewBox.w * scale) / rect.width;
    const scaleY = (baseViewBox.h * scale) / rect.height;
    const dx = (e.clientX - panStart.x) * scaleX;
    const dy = (e.clientY - panStart.y) * scaleY;
    setPanOffset(p => ({ x: p.x + dx, y: p.y + dy }));
    setPanStart({ x: e.clientX, y: e.clientY });
  }, [isPanning, panStart, zoomPct, baseViewBox]);

  const handleMouseUp = useCallback(() => setIsPanning(false), []);

  const handleClamp = useCallback(async () => {
    if (!contextMenu || !runId) return;
    try {
      await request<void>(`/runs/${runId}/clamp-node`, {
        method: 'POST',
        body: JSON.stringify({ node_name: contextMenu.nodeName, cycles: 0 }),
      });
      setActionError(null);
    } catch (err) {
      // The node draws itself from the run's activations, so a refused clamp leaves
      // the picture unchanged: the reason is the only thing that says what happened.
      setActionError(describeApiError(err, 'clamp the Slipnet node'));
    }
    setContextMenu(null);
  }, [contextMenu, runId]);

  const handleUnclamp = useCallback(async () => {
    if (!contextMenu || !runId) return;
    try {
      await request<void>(`/runs/${runId}/clamp-node`, {
        method: 'DELETE',
        body: JSON.stringify({ node_name: contextMenu.nodeName }),
      });
      setActionError(null);
    } catch (err) {
      setActionError(describeApiError(err, 'release the Slipnet node clamp'));
    }
    setContextMenu(null);
  }, [contextMenu, runId]);

  if (loading) {
    return <div className="text-muted text-sm" style={{ padding: 16 }}>Loading slipnet graph...</div>;
  }

  if (loadError !== null) {
    return (
      <div role="alert" className="text-sm" style={{ padding: 16, color: 'var(--error)' }}>
        {loadError}
      </div>
    );
  }

  const vb = `${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* A clamp that did not take hold, named. The node keeps drawing the run's
          own activation, so this is where the attempt shows. */}
      {actionError !== null && (
        <div
          role="alert"
          className="text-xs"
          style={{ padding: '3px 0', color: 'var(--error)', flexShrink: 0 }}
        >
          {actionError}
        </div>
      )}

      {/* Filter controls */}
      <div style={{ display: 'flex', gap: 8, padding: '4px 0', fontSize: 10, flexWrap: 'wrap', flexShrink: 0 }}>
        {filterTypes.map(lt => (
          <label key={lt} style={{ display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={linkFilters[lt] !== false}
              onChange={() => setLinkFilters(f => ({ ...f, [lt]: !f[lt] }))}
              style={{ width: 12, height: 12 }}
            />
            <span style={{ color: colourOf(lt) }}>{lt}</span>
          </label>
        ))}
      </div>

      {/* Zoom controls */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '2px 0', flexShrink: 0, fontSize: 10 }}>
        <button onClick={zoomOut} style={{ fontSize: 12, padding: '1px 6px', lineHeight: 1 }} title="Zoom out">-</button>
        <input
          type="range" min={10} max={800} step={5}
          value={zoomPct}
          onChange={e => setZoomPct(Number(e.target.value))}
          style={{ width: 100, height: 12, cursor: 'pointer' }}
        />
        <button onClick={zoomIn} style={{ fontSize: 12, padding: '1px 6px', lineHeight: 1 }} title="Zoom in">+</button>
        <span className="mono text-muted" style={{ minWidth: 36, textAlign: 'right' }}>{zoomPct}%</span>
        <button onClick={zoomFit} style={{ fontSize: 10, padding: '1px 6px' }}>Fit</button>
      </div>

      {/* SVG graph */}
      <svg
        ref={svgRef}
        viewBox={vb}
        style={{ flex: 1, minHeight: 0, cursor: isPanning ? 'grabbing' : 'grab' }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <defs>
          <filter id="link-glow">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Links — curved arcs to avoid overlap */}
        {visibleLinks.map(link => {
          const from = nodeMap[link.from_node];
          const to = nodeMap[link.to_node];
          if (!from || !to) return null;

          const labelActivation = link.label_node
            ? (slipnet?.[link.label_node]?.activation ?? 0)
            : 0;
          const labelFrozen = link.label_node
            ? (slipnet?.[link.label_node]?.frozen ?? false)
            : false;
          const fromAct = slipnet?.[link.from_node]?.activation ?? 0;
          const toAct = slipnet?.[link.to_node]?.activation ?? 0;
          const endpointProduct = (fromAct / 100) * (toAct / 100);

          // Much higher base visibility
          const baseOpacity = 0.35;
          const activationBoost = (labelActivation / 100) * 0.45;
          const endpointBoost = endpointProduct * 0.2;
          const opacity = Math.min(1, baseOpacity + activationBoost + endpointBoost);
          const strokeWidth = 1 + (labelActivation / 100) * 2 + endpointProduct * 1;

          const isSliplink = behaviourOf(link.link_type) === 'slip';
          const isFullyActive = labelActivation >= 50;
          const useGlow = (isSliplink && isFullyActive) || labelFrozen;

          // Use curved paths for non-adjacent nodes to reduce crossing clutter
          const dx = to.x - from.x;
          const dy = to.y - from.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const useCurve = dist > CELL_W * 1.8;
          // Arc curvature proportional to distance
          const arcBend = useCurve ? dist * 0.15 : 0;

          let pathD: string;
          if (useCurve) {
            // Quadratic bezier with control point offset perpendicular to the line
            const mx = (from.x + to.x) / 2;
            const my = (from.y + to.y) / 2;
            // Normal vector
            const nx = -dy / dist;
            const ny = dx / dist;
            const cx = mx + nx * arcBend;
            const cy = my + ny * arcBend;
            pathD = `M ${from.x} ${from.y} Q ${cx} ${cy} ${to.x} ${to.y}`;
          } else {
            pathD = `M ${from.x} ${from.y} L ${to.x} ${to.y}`;
          }

          return (
            <path
              key={link.id ?? `${link.from_node}|${link.to_node}|${link.link_type}|${link.label_node ?? ''}`}
              d={pathD}
              fill="none"
              stroke={labelFrozen ? 'cyan' : colourOf(link.link_type)}
              strokeWidth={strokeWidth}
              strokeOpacity={opacity}
              strokeDasharray={LINK_DASH[behaviourOf(link.link_type) ?? ''] ?? ''}
              filter={useGlow ? 'url(#link-glow)' : undefined}
              style={isSliplink && isFullyActive ? {
                animation: 'slipnet-pulse 0.6s ease-in-out infinite alternate',
              } : undefined}
            />
          );
        })}

        {/* Nodes */}
        {graphNodes.map(node => {
          const state = slipnet?.[node.name];
          const activation = state?.activation ?? 0;
          const frozen = state?.frozen ?? false;
          const radius = 8 + (node.depth / 100) * 10;
          const isSelected = selectedNode === node.name;

          return (
            <g
              key={node.name}
              className="graph-node"
              onClick={() => onSelectNode?.(node.name)}
              onDoubleClick={() => onDoubleClickNode?.(node.name)}
              onContextMenu={(e) => {
                e.preventDefault();
                setContextMenu({ x: e.clientX, y: e.clientY, nodeName: node.name, frozen });
              }}
              style={{ cursor: 'pointer' }}
            >
              {/* Activation glow */}
              {activation > 20 && (
                <circle
                  cx={node.x} cy={node.y}
                  r={radius + 5}
                  fill="none"
                  stroke={activationColor(activation)}
                  strokeWidth={2}
                  strokeOpacity={activation / 150}
                />
              )}
              {/* Node circle */}
              <circle
                cx={node.x} cy={node.y}
                r={radius}
                fill={activationColor(activation)}
                stroke={frozen ? 'cyan' : isSelected ? 'var(--text-accent)' : '#556'}
                strokeWidth={frozen || isSelected ? 2.5 : 1}
                fillOpacity={0.35 + (activation / 100) * 0.65}
              />
              {/* Label */}
              <text
                x={node.x} y={node.y - radius - 4}
                textAnchor="middle"
                fill="var(--text-primary)"
                fontSize={9}
                fontFamily="var(--font-mono)"
                fontWeight={activation > 50 ? 600 : 400}
              >
                {node.shortName}
              </text>
              {/* Activation value */}
              {activation > 0 && (
                <text
                  x={node.x} y={node.y + 3.5}
                  textAnchor="middle"
                  fill="var(--text-primary)"
                  fontSize={7}
                  fontFamily="var(--font-mono)"
                >
                  {activation.toFixed(0)}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* Context menu — clamping is a live-run action, so a review never offers it */}
      {contextMenu && !readOnly && (
        <div
          style={{
            position: 'fixed', left: contextMenu.x, top: contextMenu.y,
            background: 'var(--bg-panel)', border: '1px solid var(--border)',
            borderRadius: 4, padding: 4, zIndex: 1000,
            boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
          }}
          onClick={e => e.stopPropagation()}
        >
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-accent)', padding: '2px 8px', marginBottom: 2 }}>
            {contextMenu.nodeName}
          </div>
          {contextMenu.frozen ? (
            <button onClick={handleUnclamp} style={{ width: '100%', textAlign: 'left', fontSize: 11 }} disabled={!runId}>
              Unclamp
            </button>
          ) : (
            <button onClick={handleClamp} style={{ width: '100%', textAlign: 'left', fontSize: 11 }} disabled={!runId}>
              Clamp to 100
            </button>
          )}
        </div>
      )}
    </div>
  );
}
