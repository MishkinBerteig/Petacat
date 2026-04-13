// ---------------------------------------------------------------------------
// SlipnetGraphView — SVG network graph of slipnet nodes and links
// ---------------------------------------------------------------------------

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useRunStore } from '@/store/runStore';
import { api } from '@/api/client';
import type { SlipnetNodeDef } from '@/types';

interface LinkDef {
  id: number;
  from_node: string;
  to_node: string;
  link_type: string;
  label_node: string | null;
  link_length: number | null;
  fixed_length: boolean;
}

// Link type colors — brighter/bolder for visibility on dark background
const LINK_COLORS: Record<string, string> = {
  category: '#7799cc',
  instance: '#4a9eff',
  property: '#5dce5d',
  lateral: '#ffb347',
  lateral_sliplink: '#ff6b8a',
};

const LINK_DASH: Record<string, string> = {
  lateral_sliplink: '6,3',
};

function activationColor(activation: number): string {
  const t = Math.max(0, Math.min(100, activation)) / 100;
  const r = Math.round(21 + t * (255 - 21));
  const g = Math.round(101 - t * 78);
  const b = Math.round(192 - t * 142);
  return `rgb(${r},${g},${b})`;
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
}

export function SlipnetGraphView({ onSelectNode, onDoubleClickNode, selectedNode }: Props) {
  const slipnet = useRunStore((s) => s.slipnet);
  const runId = useRunStore((s) => s.runId);

  const [nodeDefs, setNodeDefs] = useState<SlipnetNodeDef[]>([]);
  const [links, setLinks] = useState<LinkDef[]>([]);
  const [gridPositions, setGridPositions] = useState<Record<string, [number, number]>>({});
  const [loading, setLoading] = useState(true);
  const [linkFilters, setLinkFilters] = useState<Record<string, boolean>>({
    category: true,
    instance: true,
    property: true,
    lateral: true,
    lateral_sliplink: true,
  });

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
    Promise.all([
      fetch('/api/admin/export').then(r => r.json()),
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
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

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
      await fetch(`/api/runs/${runId}/clamp-node`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ node_name: contextMenu.nodeName, cycles: 0 }),
      });
    } catch { /* ignore */ }
    setContextMenu(null);
  }, [contextMenu, runId]);

  const handleUnclamp = useCallback(async () => {
    if (!contextMenu || !runId) return;
    try {
      await fetch(`/api/runs/${runId}/clamp-node`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ node_name: contextMenu.nodeName }),
      });
    } catch { /* ignore */ }
    setContextMenu(null);
  }, [contextMenu, runId]);

  if (loading) {
    return <div className="text-muted text-sm" style={{ padding: 16 }}>Loading slipnet graph...</div>;
  }

  const vb = `${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Filter controls */}
      <div style={{ display: 'flex', gap: 8, padding: '4px 0', fontSize: 10, flexWrap: 'wrap', flexShrink: 0 }}>
        {Object.keys(LINK_COLORS).map(lt => (
          <label key={lt} style={{ display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={linkFilters[lt] !== false}
              onChange={() => setLinkFilters(f => ({ ...f, [lt]: !f[lt] }))}
              style={{ width: 12, height: 12 }}
            />
            <span style={{ color: LINK_COLORS[lt] }}>{lt}</span>
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

          const isSliplink = link.link_type === 'lateral_sliplink';
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
              key={link.id}
              d={pathD}
              fill="none"
              stroke={labelFrozen ? 'cyan' : LINK_COLORS[link.link_type] ?? '#888'}
              strokeWidth={strokeWidth}
              strokeOpacity={opacity}
              strokeDasharray={LINK_DASH[link.link_type] ?? ''}
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

      {/* Context menu */}
      {contextMenu && (
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
