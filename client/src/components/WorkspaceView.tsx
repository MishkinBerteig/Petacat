// ---------------------------------------------------------------------------
// WorkspaceView -- SVG rendering of the four workspace strings with bonds,
// groups, and bridges, inspired by the original Scheme workspace-graphics.ss
// ---------------------------------------------------------------------------

import { useRunStore } from '@/store/runStore';

const LETTER_W = 28;
const LETTER_H = 32;
const ARROW_LEN = 40;
const ARROW_PAD = 12;
const ROW_GAP = 100;
const TOP_Y = 50;
const SIDE_PAD = 20;
const BOND_ARC_H = 14;
const GROUP_PAD = 4;
const BRIDGE_Y_OFFSET = 8;

interface BondData {
  from_pos: number;
  to_pos: number;
  category: string;
  direction: string | null;
  strength: number;
  built: boolean;
}

interface GroupData {
  left_pos: number;
  right_pos: number;
  category: string;
  direction: string | null;
  strength: number;
  built: boolean;
}

interface BridgeData {
  obj1_string: string;
  obj1_pos: number;
  obj2_string: string;
  obj2_pos: number;
  strength: number;
  built: boolean;
  concept_mappings: { from: string; to: string; label: string | null }[];
}

interface RuleData {
  type: string;
  quality: number;
  english: string;
  built: boolean;
}

interface StringLayoutResult {
  x: number;
  y: number;
  text: string;
  label: string;
  bonds: BondData[];
  groups: GroupData[];
}

function layoutPair(
  leftText: string,
  leftLabel: string,
  leftBonds: BondData[],
  leftGroups: GroupData[],
  rightText: string | null,
  rightLabel: string,
  rightBonds: BondData[],
  rightGroups: GroupData[],
  rowIndex: number,
  svgW: number,
): { left: StringLayoutResult; right: StringLayoutResult | null; arrowX1: number; arrowX2: number } {
  const rowY = TOP_Y + rowIndex * (LETTER_H + ROW_GAP);
  const leftW = leftText.length * LETTER_W;
  const rightW = rightText ? rightText.length * LETTER_W : 0;
  const totalNeeded = leftW + ARROW_PAD + ARROW_LEN + ARROW_PAD + rightW;
  const startX = Math.max(SIDE_PAD, (svgW - totalNeeded) / 2);

  const leftX = startX;
  const arrowX1 = leftX + leftW + ARROW_PAD;
  const arrowX2 = arrowX1 + ARROW_LEN;
  const rightX = arrowX2 + ARROW_PAD;

  const left: StringLayoutResult = { x: leftX, y: rowY, text: leftText, label: leftLabel, bonds: leftBonds, groups: leftGroups };
  const right: StringLayoutResult | null = rightText
    ? { x: rightX, y: rowY, text: rightText, label: rightLabel, bonds: rightBonds, groups: rightGroups }
    : null;

  return { left, right, arrowX1, arrowX2 };
}

/** Render bond arcs below letters */
function BondArcs({ s }: { s: StringLayoutResult }) {
  return (
    <>
      {s.bonds.map((b, i) => {
        const x1 = s.x + b.from_pos * LETTER_W + LETTER_W / 2;
        const x2 = s.x + b.to_pos * LETTER_W + LETTER_W / 2;
        const midX = (x1 + x2) / 2;
        const baseY = s.y + LETTER_H + 2;
        const opacity = Math.max(0.3, b.strength / 100);
        return (
          <g key={`bond-${s.label}-${i}`}>
            <path
              d={`M ${x1} ${baseY} Q ${midX} ${baseY + BOND_ARC_H} ${x2} ${baseY}`}
              fill="none"
              stroke="var(--text-accent)"
              strokeWidth={1.5}
              opacity={opacity}
            />
            <text
              x={midX}
              y={baseY + BOND_ARC_H + 8}
              textAnchor="middle"
              fontSize={8}
              fill="var(--text-accent)"
              opacity={opacity}
            >
              {b.category}
            </text>
          </g>
        );
      })}
    </>
  );
}

/** Render group enclosures as rounded rectangles */
function GroupBoxes({ s }: { s: StringLayoutResult }) {
  return (
    <>
      {s.groups.map((g, i) => {
        const gx = s.x + g.left_pos * LETTER_W - GROUP_PAD;
        const gw = (g.right_pos - g.left_pos + 1) * LETTER_W + GROUP_PAD * 2;
        const gy = s.y - GROUP_PAD - 2;
        const gh = LETTER_H + GROUP_PAD * 2 + 4;
        const opacity = Math.max(0.3, g.strength / 100);
        return (
          <g key={`group-${s.label}-${i}`}>
            <rect
              x={gx}
              y={gy}
              width={gw}
              height={gh}
              fill="none"
              stroke="var(--warning)"
              strokeWidth={1.5}
              strokeDasharray={g.built ? 'none' : '4 2'}
              rx={5}
              opacity={opacity}
            />
            <text
              x={gx + gw / 2}
              y={gy - 2}
              textAnchor="middle"
              fontSize={8}
              fill="var(--warning)"
              opacity={opacity}
            >
              {g.category}
            </text>
          </g>
        );
      })}
    </>
  );
}

/** Map string text to its layout position */
function getStringLayout(
  text: string,
  layouts: StringLayoutResult[],
): StringLayoutResult | null {
  return layouts.find((l) => l.text === text) ?? null;
}

/** Render bridge lines between strings */
function BridgeLines({
  bridges,
  layouts,
  color,
}: {
  bridges: BridgeData[];
  layouts: StringLayoutResult[];
  color: string;
}) {
  return (
    <>
      {bridges.map((br, i) => {
        const s1 = getStringLayout(br.obj1_string, layouts);
        const s2 = getStringLayout(br.obj2_string, layouts);
        if (!s1 || !s2) return null;

        const x1 = s1.x + br.obj1_pos * LETTER_W + LETTER_W / 2;
        const y1 = s1.y + (s1.y < s2.y ? LETTER_H + BRIDGE_Y_OFFSET : -BRIDGE_Y_OFFSET);
        const x2 = s2.x + br.obj2_pos * LETTER_W + LETTER_W / 2;
        const y2 = s2.y + (s2.y < s1.y ? LETTER_H + BRIDGE_Y_OFFSET : -BRIDGE_Y_OFFSET);
        const opacity = Math.max(0.3, br.strength / 100);
        const midY = (y1 + y2) / 2;
        const label = br.concept_mappings
          .map((cm) => cm.label ? `${cm.from}→${cm.to}` : `${cm.from}=${cm.to}`)
          .join(', ');

        return (
          <g key={`bridge-${i}`}>
            <line
              x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={color}
              strokeWidth={1.5}
              strokeDasharray={br.built ? 'none' : '3 3'}
              opacity={opacity}
            />
            {label && (
              <text
                x={(x1 + x2) / 2 + 3}
                y={midY}
                fontSize={7}
                fill={color}
                opacity={opacity}
              >
                {label}
              </text>
            )}
          </g>
        );
      })}
    </>
  );
}


export function WorkspaceView() {
  const workspace = useRunStore((s) => s.workspace);

  if (!workspace) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        No workspace loaded. Create or load a run.
      </div>
    );
  }

  const {
    initial,
    modified,
    target,
    answer,
    bonds_per_string,
    groups_per_string,
    num_top_bridges,
    num_bottom_bridges,
    num_vertical_bridges,
  } = workspace;

  // Structure data (may be absent in older snapshots)
  const bondsData = (workspace as any).bonds ?? {};
  const groupsData = (workspace as any).groups ?? {};
  const topBridges: BridgeData[] = (workspace as any).top_bridges ?? [];
  const vertBridges: BridgeData[] = (workspace as any).vertical_bridges ?? [];
  const bottomBridges: BridgeData[] = (workspace as any).bottom_bridges ?? [];
  const topRules: RuleData[] = (workspace as any).top_rules ?? [];
  const bottomRules: RuleData[] = (workspace as any).bottom_rules ?? [];

  const bondsFor = (s: string): BondData[] => bondsData[s] ?? [];
  const groupsFor = (s: string): GroupData[] => groupsData[s] ?? [];
  const bondCountFor = (s: string) => bonds_per_string[s] ?? 0;
  const groupCountFor = (s: string) => groups_per_string[s] ?? 0;

  const SVG_H = 320;
  const topTotalW = initial.length * LETTER_W + ARROW_PAD + ARROW_LEN + ARROW_PAD + modified.length * LETTER_W;
  const botTotalW = target.length * LETTER_W + ARROW_PAD + ARROW_LEN + ARROW_PAD + (answer ? answer.length * LETTER_W : 3 * LETTER_W);
  const SVG_W = Math.max(500, Math.max(topTotalW, botTotalW) + 2 * SIDE_PAD + 120);

  const topPair = layoutPair(
    initial, 'initial', bondsFor(initial), groupsFor(initial),
    modified, 'modified', bondsFor(modified), groupsFor(modified),
    0, SVG_W,
  );
  const botPair = layoutPair(
    target, 'target', bondsFor(target), groupsFor(target),
    answer, 'answer', answer ? bondsFor(answer) : [], answer ? groupsFor(answer) : [],
    1, SVG_W,
  );

  const allStrings = [topPair.left, topPair.right, botPair.left, botPair.right].filter(
    (s): s is StringLayoutResult => s !== null,
  );

  const arrowY1 = TOP_Y + LETTER_H / 2;
  const arrowY2 = TOP_Y + LETTER_H + ROW_GAP + LETTER_H / 2;

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      width="100%"
      height="100%"
      style={{ maxHeight: 300 }}
    >
      <rect width={SVG_W} height={SVG_H} fill="var(--bg-secondary)" rx={4} />

      {/* Group enclosures (behind letters) */}
      {allStrings.map((s) => (
        <GroupBoxes key={`groups-${s.label}`} s={s} />
      ))}

      {/* Strings: letters */}
      {allStrings.map((s) => (
        <g key={s.label}>
          <text
            x={s.x + (s.text.length * LETTER_W) / 2}
            y={s.y - 12}
            textAnchor="middle"
            fill="var(--text-secondary)"
            fontSize={10}
          >
            {s.label}
          </text>

          {Array.from(s.text).map((ch, i) => {
            const lx = s.x + i * LETTER_W;
            return (
              <g key={`${s.label}-${i}`}>
                <rect
                  x={lx} y={s.y}
                  width={LETTER_W - 2} height={LETTER_H}
                  fill="var(--bg-card)"
                  stroke="var(--border)"
                  strokeWidth={1} rx={3}
                />
                <text
                  x={lx + LETTER_W / 2 - 1}
                  y={s.y + LETTER_H / 2 + 5}
                  textAnchor="middle"
                  fill="var(--text-primary)"
                  fontSize={16}
                  fontFamily="var(--font-mono)"
                >
                  {ch}
                </text>
              </g>
            );
          })}

          {/* Bond/group counts */}
          <text
            x={s.x + (s.text.length * LETTER_W) / 2}
            y={s.y + LETTER_H + BOND_ARC_H + 20}
            textAnchor="middle"
            fill="var(--text-secondary)"
            fontSize={9}
          >
            B:{bondCountFor(s.text)} G:{groupCountFor(s.text)}
          </text>
        </g>
      ))}

      {/* Bond arcs (below letters) */}
      {allStrings.map((s) => (
        <BondArcs key={`bonds-${s.label}`} s={s} />
      ))}

      {/* Top horizontal arrow */}
      <line
        x1={topPair.arrowX1} y1={arrowY1}
        x2={topPair.arrowX2} y2={arrowY1}
        stroke="var(--text-accent)" strokeWidth={1.5}
        markerEnd="url(#arrowhead)"
      />

      {/* Bottom horizontal arrow */}
      {answer ? (
        <line
          x1={botPair.arrowX1} y1={arrowY2}
          x2={botPair.arrowX2} y2={arrowY2}
          stroke="var(--text-accent)" strokeWidth={1.5}
          markerEnd="url(#arrowhead)"
        />
      ) : (
        <text
          x={botPair.arrowX2 + ARROW_PAD + 10}
          y={arrowY2 + 5}
          textAnchor="middle"
          fill="var(--text-accent)"
          fontSize={22}
          fontFamily="var(--font-mono)"
        >
          ?
        </text>
      )}

      {/* Bridges */}
      <BridgeLines bridges={topBridges} layouts={allStrings} color="#4fc3f7" />
      <BridgeLines bridges={vertBridges} layouts={allStrings} color="#ab47bc" />
      <BridgeLines bridges={bottomBridges} layouts={allStrings} color="#66bb6a" />

      {/* Bridge & rule summary */}
      <text x={SVG_W - 12} y={18} textAnchor="end" fill="var(--text-secondary)" fontSize={9}>
        bridges: top={num_top_bridges} vert={num_vertical_bridges} bot={num_bottom_bridges}
      </text>

      {/* Rules — shown with quality-based opacity and color */}
      {topRules.map((r, i) => (
        <text
          key={`top-rule-${i}`}
          x={SVG_W / 2} y={arrowY1 - 20 - i * 12}
          textAnchor="middle"
          fill="var(--success)"
          fontSize={9}
          opacity={Math.max(0.4, r.quality / 100)}
        >
          Top: {r.english} (q={r.quality})
        </text>
      ))}
      {bottomRules.map((r, i) => (
        <text
          key={`bot-rule-${i}`}
          x={SVG_W / 2} y={arrowY2 + 30 + i * 12}
          textAnchor="middle"
          fill="var(--success)"
          fontSize={9}
          opacity={Math.max(0.4, r.quality / 100)}
        >
          Bot: {r.english} (q={r.quality})
        </text>
      ))}

      <defs>
        <marker id="arrowhead" markerWidth={8} markerHeight={6} refX={7} refY={3} orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill="var(--text-accent)" />
        </marker>
      </defs>
    </svg>
  );
}
