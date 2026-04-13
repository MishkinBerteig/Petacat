// ---------------------------------------------------------------------------
// SlipnetView -- Graph view of slipnet nodes with activation + node focus
// ---------------------------------------------------------------------------

import { useState, useEffect, useMemo } from 'react';
import { useRunStore } from '@/store/runStore';
import { api } from '@/api/client';
import { SlipnetGraphView } from './SlipnetGraphView';

interface LinkDef {
  id: number;
  from_node: string;
  to_node: string;
  link_type: string;
  label_node: string | null;
  link_length: number | null;
}

// Link type display colors (same palette as SlipnetGraphView)
const LINK_TYPE_COLORS: Record<string, string> = {
  category: '#7799cc',
  instance: '#4a9eff',
  property: '#5dce5d',
  lateral: '#ffb347',
  lateral_sliplink: '#ff6b8a',
};

function activationColor(activation: number): string {
  const t = Math.max(0, Math.min(100, activation)) / 100;
  const r = Math.round(21 + t * (255 - 21));
  const g = Math.round(101 - t * 78);
  const b = Math.round(192 - t * 142);
  return `rgb(${r},${g},${b})`;
}

export function SlipnetView() {
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [focusedNode, setFocusedNode] = useState<string | null>(null);

  // Node focus view (replaces the graph when a node is double-clicked)
  if (focusedNode) {
    return (
      <SlipnetNodeFocus
        nodeName={focusedNode}
        onClose={() => setFocusedNode(null)}
      />
    );
  }

  // Graph view (default)
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ flex: 1, minHeight: 0 }}>
        <SlipnetGraphView
          selectedNode={selectedNode}
          onSelectNode={setSelectedNode}
          onDoubleClickNode={setFocusedNode}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SlipnetNodeFocus — Full-panel focused view of a single node + connections
// ---------------------------------------------------------------------------

interface FocusProps {
  nodeName: string;
  onClose: () => void;
}

export function SlipnetNodeFocus({ nodeName, onClose }: FocusProps) {
  const slipnet = useRunStore((s) => s.slipnet);
  const status = useRunStore((s) => s.status);
  const isProcessing = useRunStore((s) => s.isProcessing);
  // Editing slipnet config is safe whenever the engine isn't actively running
  // codelets. That includes idle, initialized, paused, halted, and answer_found
  // states — basically anything except an in-progress run. The Run-to-Answer
  // mode uses isProcessing as an extra guard in case status updates race the
  // polling loop.
  const canEdit = status !== 'running' && !isProcessing;
  const [allLinks, setAllLinks] = useState<LinkDef[]>([]);
  const [nodeDefs, setNodeDefs] = useState<Record<string, { short_name: string; conceptual_depth: number; description?: string }>>({});

  useEffect(() => {
    Promise.all([
      api.getSlipnetLinks(),
      api.getSlipnetNodes(),
    ]).then(([links, nodes]) => {
      setAllLinks(links);
      const map: typeof nodeDefs = {};
      for (const n of nodes) {
        map[n.name] = { short_name: n.short_name, conceptual_depth: n.conceptual_depth, description: (n as any).description };
      }
      setNodeDefs(map);
    });
  }, []);

  const nodeState = slipnet?.[nodeName];
  const nodeDef = nodeDefs[nodeName];

  // Gather all connections: outgoing and incoming
  const connections = useMemo(() => {
    const out: { direction: 'out' | 'in'; linkType: string; peerNode: string; labelNode: string | null }[] = [];
    for (const link of allLinks) {
      if (link.from_node === nodeName) {
        out.push({ direction: 'out', linkType: link.link_type, peerNode: link.to_node, labelNode: link.label_node });
      } else if (link.to_node === nodeName) {
        out.push({ direction: 'in', linkType: link.link_type, peerNode: link.from_node, labelNode: link.label_node });
      }
    }
    // Sort: outgoing first, then by link type, then by peer name
    out.sort((a, b) => {
      if (a.direction !== b.direction) return a.direction === 'out' ? -1 : 1;
      if (a.linkType !== b.linkType) return a.linkType.localeCompare(b.linkType);
      return a.peerNode.localeCompare(b.peerNode);
    });
    return out;
  }, [allLinks, nodeName]);

  const handleEdit = () => {
    window.location.hash = `/config/slipnet/${encodeURIComponent(nodeName)}`;
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  };

  return (
    <div style={{
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* Header with node name and action buttons */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 0',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontWeight: 700,
          fontSize: 14,
          color: 'var(--text-accent)',
        }}>
          {nodeName}
        </span>
        {nodeDef && (
          <span className="text-muted text-xs">
            ({nodeDef.short_name}) &middot; depth: {nodeDef.conceptual_depth}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {canEdit && (
          <button
            onClick={handleEdit}
            style={{
              fontSize: 11,
              padding: '3px 10px',
              background: 'var(--bg-card)',
              border: '1px solid var(--text-accent)',
              borderRadius: 4,
              color: 'var(--text-accent)',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            Edit
          </button>
        )}
        <button
          onClick={onClose}
          style={{
            fontSize: 11,
            padding: '3px 10px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            color: 'var(--text-primary)',
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          Close
        </button>
      </div>

      {/* Node state (live) */}
      {nodeState && (
        <div style={{ padding: '4px 0', fontSize: 12, flexShrink: 0 }}>
          Activation:{' '}
          <span style={{ fontWeight: 700, color: activationColor(nodeState.activation) }}>
            {nodeState.activation.toFixed(1)}
          </span>
          {nodeState.frozen && <span style={{ color: 'cyan', marginLeft: 8 }}>(clamped)</span>}
        </div>
      )}
      {!nodeState && (
        <div className="text-muted text-xs" style={{ padding: '4px 0', flexShrink: 0 }}>
          No active run — activation data unavailable
        </div>
      )}

      {nodeDef?.description && (
        <div className="text-muted text-xs" style={{ padding: '2px 0 4px', flexShrink: 0 }}>
          {nodeDef.description}
        </div>
      )}

      {/* Connected nodes list */}
      <div style={{
        flex: 1,
        overflow: 'auto',
        marginTop: 4,
      }}>
        <div className="text-xs text-muted" style={{ marginBottom: 4 }}>
          {connections.length} connection{connections.length !== 1 ? 's' : ''}
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              <th style={{ textAlign: 'left', padding: '3px 6px', fontWeight: 600 }}>Dir</th>
              <th style={{ textAlign: 'left', padding: '3px 6px', fontWeight: 600 }}>Link Type</th>
              <th style={{ textAlign: 'left', padding: '3px 6px', fontWeight: 600 }}>Node</th>
              <th style={{ textAlign: 'left', padding: '3px 6px', fontWeight: 600 }}>Label</th>
              <th style={{ textAlign: 'right', padding: '3px 6px', fontWeight: 600 }}>Activation</th>
            </tr>
          </thead>
          <tbody>
            {connections.map((conn, i) => {
              const peerState = slipnet?.[conn.peerNode];
              const peerActivation = peerState?.activation ?? 0;
              const peerFrozen = peerState?.frozen ?? false;
              const peerDef = nodeDefs[conn.peerNode];

              return (
                <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '3px 6px' }}>
                    <span style={{ color: conn.direction === 'out' ? '#5dce5d' : '#4a9eff', fontFamily: 'var(--font-mono)' }}>
                      {conn.direction === 'out' ? '\u2192' : '\u2190'}
                    </span>
                  </td>
                  <td style={{ padding: '3px 6px' }}>
                    <span style={{
                      color: LINK_TYPE_COLORS[conn.linkType] ?? 'var(--text-secondary)',
                      fontFamily: 'var(--font-mono)',
                    }}>
                      {conn.linkType}
                    </span>
                  </td>
                  <td style={{ padding: '3px 6px', fontFamily: 'var(--font-mono)' }}>
                    {conn.peerNode}
                    {peerDef && (
                      <span className="text-muted" style={{ marginLeft: 4, fontSize: 10 }}>
                        ({peerDef.short_name})
                      </span>
                    )}
                  </td>
                  <td style={{ padding: '3px 6px', fontFamily: 'var(--font-mono)' }}>
                    {conn.labelNode ? (
                      <span className="text-muted">{conn.labelNode}</span>
                    ) : (
                      <span style={{ color: 'var(--border)' }}>&mdash;</span>
                    )}
                  </td>
                  <td style={{
                    padding: '3px 6px',
                    textAlign: 'right',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: peerActivation > 0 ? 600 : 400,
                    color: peerActivation > 0 ? activationColor(peerActivation) : 'var(--text-secondary)',
                  }}>
                    {peerActivation.toFixed(0)}
                    {peerFrozen && <span style={{ color: 'cyan', marginLeft: 3, fontSize: 9 }}>C</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
