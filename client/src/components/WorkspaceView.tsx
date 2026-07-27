// ---------------------------------------------------------------------------
// WorkspaceView -- SVG rendering of the four workspace strings with bonds,
// groups, and bridges, inspired by the original Scheme workspace-graphics.ss
// ---------------------------------------------------------------------------

import { useRunStore } from '@/store/runStore';

// Layout is organised into reserved horizontal bands so that nothing has to
// share a y with something else. Previously every bridge label was placed at the
// midpoint of its own line -- and since all the bridges of a type span the same
// two rows, every one of those midpoints was the *same* y, so the labels printed
// on top of each other into an unreadable smear. Group labels, string labels and
// the rule text collided for the same reason: fixed offsets with no reservation.
const LETTER_W = 28;
const LETTER_H = 32;
const ARROW_LEN = 40;
const ARROW_PAD = 12;
const SIDE_PAD = 20;
const BOND_ARC_H = 14;
const GROUP_PAD = 4;
const BRIDGE_Y_OFFSET = 6;

/** Chrome at the very top: the colour legend and the bridge counts. */
const TOP_CHROME = 32;

/** Space above a row's letters: rule text, string label, then group labels. */
const RULE_H = 11;
const RULE_BAND = 2 * RULE_H;
const LABEL_BAND = 18;
const GROUP_LANE_H = 10;
const GROUP_LABEL_BAND = 4 * GROUP_LANE_H;
const HEAD_BAND = RULE_BAND + LABEL_BAND + GROUP_LABEL_BAND;

/** Space below a row's letters: bond arcs, bond labels, then the B:/G: counts. */
const BOND_BAND = BOND_ARC_H + 30;
const COUNT_BAND = 14;
const FOOT_BAND = BOND_BAND + COUNT_BAND;

/** Minimum gap between rows; grown to fit the vertical bridges' badges. */
const BRIDGE_BAND = 64;
/** Vertical space each cross-row badge needs to stay clear of its neighbours. */
const BADGE_PITCH = 17;

/** How far bridges bow. Shallow: enough to separate paths, not to distract. */
const BOW_BASE = 20;
const BOW_STEP = 11;

const TOP_Y = TOP_CHROME + HEAD_BAND;

const BRIDGE_COLORS = { top: '#4fc3f7', vertical: '#ab47bc', bottom: '#66bb6a' };
type BridgeKind = keyof typeof BRIDGE_COLORS;

/** Long labels are clipped on screen; the full text stays in a <title>. */
function clip(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + '…' : text;
}

/**
 * Assign each item a lane so that items whose horizontal extents overlap end up
 * on different rows.
 *
 * Group category labels were all drawn at one y, so a string carrying several
 * groups -- especially nested ones sharing a left edge -- printed its labels on
 * top of each other. Greedy interval packing gives each label the lowest lane
 * that is still free at its x range.
 */
function assignLanes(extents: { x1: number; x2: number }[]): number[] {
  const order = extents
    .map((e, i) => ({ ...e, i }))
    .sort((a, b) => a.x1 - b.x1 || a.x2 - b.x2);

  const laneEnds: number[] = [];
  const lanes = new Array<number>(extents.length).fill(0);
  for (const { x1, x2, i } of order) {
    let lane = laneEnds.findIndex((end) => end <= x1);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(x2);
    } else {
      laneEnds[lane] = x2;
    }
    lanes[i] = lane;
  }
  return lanes;
}

/** Rough on-screen width of a label, for lane packing. */
function textWidth(text: string, fontSize: number): number {
  return text.length * fontSize * 0.6;
}

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
  /** Nesting level: 0 for a top-level group, 1 for a subgroup, etc. */
  depth?: number;
  length?: number;
}

interface ConceptMapping {
  from: string;
  to: string;
  label: string | null;
  /** The interesting half: a non-identity correspondence. */
  is_slippage?: boolean;
}

interface BridgeData {
  obj1_string: string;
  obj1_pos: number;
  obj1_right_pos?: number;
  obj2_string: string;
  obj2_pos: number;
  obj2_right_pos?: number;
  strength: number;
  built: boolean;
  concept_mappings: ConceptMapping[];
}

/**
 * What a bridge says, shortened to what is worth reading at a glance.
 *
 * A bridge often carries five or six concept-mappings, most of them identities
 * (`lmost→lmost`, `LetterCtgy→LetterCtgy`). Printing all of them produced labels
 * far wider than the whole diagram. The slippages are the substance -- they are
 * what makes an analogy fluid -- so they are shown, and the identities are
 * reduced to a count.
 */
function bridgeLabel(br: BridgeData): { short: string; full: string } {
  const slippages = br.concept_mappings.filter((cm) => cm.is_slippage);
  const identities = br.concept_mappings.length - slippages.length;

  const full = br.concept_mappings
    .map((cm) => (cm.is_slippage ? `${cm.from}⇒${cm.to}` : `${cm.from}=${cm.to}`))
    .join(', ');

  if (slippages.length === 0) {
    return { short: identities > 0 ? `${identities} identity` : '', full };
  }
  const shown = slippages.map((cm) => `${cm.from}⇒${cm.to}`).join(', ');
  return {
    short: identities > 0 ? `${shown} +${identities}id` : shown,
    full,
  };
}

interface RuleData {
  type: string;
  quality: number;
  /** §3.3.5's three independent measures, combined into `quality`. */
  uniformity?: number;
  abstractness?: number;
  succinctness?: number;
  clause_count?: number;
  verbatim?: boolean;
  english: string;
  built: boolean;
}

/** "q=72 u=100 a=61 s=80" — quality plus the measures it is built from. */
function ruleMeasures(r: RuleData): string {
  const parts = [`q=${r.quality}`];
  if (r.uniformity !== undefined) parts.push(`u=${r.uniformity}`);
  if (r.abstractness !== undefined) parts.push(`a=${r.abstractness}`);
  if (r.succinctness !== undefined) parts.push(`s=${r.succinctness}`);
  return parts.join(' ');
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
  rowY: number,
  svgW: number,
): { left: StringLayoutResult; right: StringLayoutResult | null; arrowX1: number; arrowX2: number } {
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
  // Adjacent bonds are one letter-width apart, narrower than their labels, and
  // two bonds can share a midpoint. Lane-pack rather than merely alternating.
  const lanes = assignLanes(
    s.bonds.map((b) => {
      const mid =
        s.x + ((b.from_pos + b.to_pos) / 2) * LETTER_W + LETTER_W / 2;
      const w = textWidth(b.category, 8) + 4;
      return { x1: mid - w / 2, x2: mid + w / 2 };
    }),
  );

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
              y={baseY + BOND_ARC_H + 8 + lanes[i] * 9}
              textAnchor="middle"
              fontSize={8}
              fill="var(--text-accent)"
              opacity={opacity}
              stroke="var(--bg-secondary)"
              strokeWidth={2.5}
              paintOrder="stroke"
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
  // Lane-pack the category labels up front, so overlapping ones step upward
  // instead of printing on top of each other.
  const labelText = (g: GroupData) =>
    g.category + (g.direction ? (g.direction === 'right' ? ' →' : ' ←') : '');
  const lanes = assignLanes(
    s.groups.map((g) => {
      const x1 = s.x + g.left_pos * LETTER_W - 4;
      return { x1, x2: x1 + textWidth(labelText(g), 8) + 6 };
    }),
  );

  return (
    <>
      {s.groups.map((g, i) => {
        // Box size grows with letter span, so an enclosing group draws outside
        // its subgroups instead of on top of them (groups.ss:147 sizing-factor).
        // Depth breaks the tie when a group and its subgroup span the same
        // letters -- the Scheme's singleton shrink-factor (groups.ss:149-158).
        const span = g.right_pos - g.left_pos + 1;
        const pad = Math.max(
          2,
          GROUP_PAD + Math.max(1, span - 1) * 2.5 - (g.depth ?? 0) * 2,
        );
        const gx = s.x + g.left_pos * LETTER_W - pad;
        const gw = (g.right_pos - g.left_pos + 1) * LETTER_W + pad * 2;
        const gy = s.y - pad - 2;
        const gh = LETTER_H + pad * 2 + 4;
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
            {/* Left-anchored at the box edge and lifted into its packed lane. */}
            <text
              x={gx + 1}
              y={s.y - 6 - lanes[i] * GROUP_LANE_H}
              fontSize={8}
              fill="var(--warning)"
              opacity={opacity}
              stroke="var(--bg-secondary)"
              strokeWidth={2.5}
              paintOrder="stroke"
            >
              {labelText(g)}
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

/**
 * One numbered entry per bridge: the line on the diagram, and a row in the
 * legend beneath it.
 *
 * Bridge labels used to be written onto the lines themselves. A bridge carries
 * several concept-mappings, so those labels were long; and since every bridge of
 * a type spans the same two rows, they were all placed at the same y. The result
 * was one illegible pile of text lying across the letters. Numbering the lines
 * keeps the diagram readable and moves the text somewhere it has room.
 */
interface NumberedBridge {
  bridge: BridgeData;
  kind: BridgeKind;
  index: number;
  endpoints: string;
}

/** Render bridge lines between strings */
function BridgeLines({
  bridges,
  layouts,
  color,
  firstNumber,
  countOfKind,
  gap,
  band,
}: {
  bridges: BridgeData[];
  layouts: StringLayoutResult[];
  color: string;
  firstNumber: number;
  countOfKind: number;
  /** Centre of the row's arrow gap — the one column on a row with no text in it. */
  gap?: { x: number; y: number };
  /** For cross-row bridges: the clear band between the rows, to keep badges in. */
  band?: { y1: number; y2: number };
}) {
  return (
    <>
      {bridges.map((br, i) => {
        const s1 = getStringLayout(br.obj1_string, layouts);
        const s2 = getStringLayout(br.obj2_string, layouts);
        if (!s1 || !s2) return null;

        // Attach at the centre of the object, so a bridge onto a group points at
        // the group rather than at its leftmost letter.
        const centre = (s: StringLayoutResult, left: number, right?: number) =>
          s.x + ((left + (right ?? left) + 1) / 2) * LETTER_W;
        const x1 = centre(s1, br.obj1_pos, br.obj1_right_pos);
        const x2 = centre(s2, br.obj2_pos, br.obj2_right_pos);

        const sameRow = s1.y === s2.y;
        const y1 = sameRow
          ? s1.y + LETTER_H / 2
          : s1.y + (s1.y < s2.y ? LETTER_H + BRIDGE_Y_OFFSET : -BRIDGE_Y_OFFSET);
        const y2 = sameRow
          ? s2.y + LETTER_H / 2
          : s2.y + (s2.y < s1.y ? LETTER_H + BRIDGE_Y_OFFSET : -BRIDGE_Y_OFFSET);

        const opacity = Math.max(0.35, br.strength / 100);
        const { full } = bridgeLabel(br);
        const number = firstNumber + i;

        // Bridges are drawn as shallow arcs rather than straight chords. Two
        // bridges with different endpoints can share almost the whole of a
        // straight path, which is exactly what made a crossing pair unreadable;
        // bowing each one by a different amount separates them along their length
        // instead of only at their ends. It also lifts a same-row bridge clear of
        // the letters it would otherwise be drawn straight through.
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2;
        const chord = Math.hypot(x2 - x1, y2 - y1) || 1;
        // Unit normal to the chord.
        const nx = -(y2 - y1) / chord;
        const ny = (x2 - x1) / chord;

        // Same-row bridges all bow the same way (up, away from the letters);
        // cross-row bridges fan to alternating sides so crossings stay distinct.
        const bow = sameRow
          ? -(BOW_BASE + i * BOW_STEP)
          : (i - (countOfKind - 1) / 2) * BOW_STEP;
        const cx = mx + nx * bow * 2;
        const cy = my + ny * bow * 2;

        // The apex of a quadratic at t=0.5 is midway between chord and control.
        let bx = (mx + cx) / 2;
        let by = (my + cy) / 2;
        if (sameRow && gap) {
          // Keep these in the arrow gap, the one column of a row with no text.
          bx = gap.x;
        }
        if (!sameRow) {
          // Nudge alternate badges so a tight fan cannot overlap.
          by += (i % 2) * 12 - 6;
          if (band) {
            const lo = Math.min(band.y1, band.y2);
            const hi = Math.max(band.y1, band.y2);
            by = Math.min(hi, Math.max(lo, by));
          }
        }

        return (
          <g key={`bridge-${i}`}>
            <title>{`${br.obj1_string}[${br.obj1_pos}] ↔ ${br.obj2_string}[${br.obj2_pos}]  (strength ${br.strength})\n${full}`}</title>
            <path
              d={`M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`}
              fill="none"
              stroke={color}
              strokeWidth={1.5}
              strokeDasharray={br.built ? 'none' : '3 3'}
              opacity={opacity}
            />
            {/* Dots make it unambiguous which two objects are bridged. */}
            <circle cx={x1} cy={y1} r={2.5} fill={color} opacity={opacity} />
            <circle cx={x2} cy={y2} r={2.5} fill={color} opacity={opacity} />
            {/* The badge, keyed to the legend row below the diagram. */}
            <circle
              cx={bx} cy={by} r={6}
              fill="var(--bg-secondary)"
              stroke={color}
              strokeWidth={1.5}
              opacity={Math.max(0.6, opacity)}
            />
            <text
              x={bx} y={by + 2.6}
              textAnchor="middle"
              fontSize={7.5}
              fill={color}
              fontFamily="var(--font-mono)"
            >
              {number}
            </text>
          </g>
        );
      })}
    </>
  );
}


/**
 * The bridge list under the diagram: number, the two objects, and what the
 * mapping says. Full width and one per line, so nothing has to compete for
 * space with the letters.
 */
function BridgeKey({
  entries,
  y,
  width,
}: {
  entries: NumberedBridge[];
  y: number;
  width: number;
}) {
  if (entries.length === 0) return null;
  return (
    <g>
      <line
        x1={SIDE_PAD} y1={y - 10} x2={width - SIDE_PAD} y2={y - 10}
        stroke="var(--border)" strokeWidth={1}
      />
      {entries.map(({ bridge, kind, index, endpoints }, row) => {
        const color = BRIDGE_COLORS[kind];
        const { short, full } = bridgeLabel(bridge);
        const ly = y + row * 12;
        return (
          <g key={`key-${index}`}>
            <title>{full}</title>
            <circle
              cx={SIDE_PAD + 6} cy={ly - 3} r={6}
              fill="var(--bg-secondary)" stroke={color} strokeWidth={1.5}
            />
            <text
              x={SIDE_PAD + 6} y={ly - 0.4}
              textAnchor="middle" fontSize={7.5} fill={color}
              fontFamily="var(--font-mono)"
            >
              {index}
            </text>
            <text x={SIDE_PAD + 17} y={ly} fontSize={8.5} fill={color} fontFamily="var(--font-mono)">
              {endpoints}
            </text>
            <text x={SIDE_PAD + 92} y={ly} fontSize={8.5} fill="var(--text-secondary)">
              {short ? clip(short, Math.max(20, Math.floor((width - SIDE_PAD - 100) / 4.8))) : '—'}
            </text>
          </g>
        );
      })}
    </g>
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

  // Bridges are numbered across all three kinds so a badge maps to exactly one
  // legend row.
  const bridgeKey: NumberedBridge[] = [];
  const objLabel = (s: string, from: number, to?: number) =>
    s.slice(from, (to ?? from) + 1) || '?';
  for (const [kind, list] of [
    ['top', topBridges],
    ['vertical', vertBridges],
    ['bottom', bottomBridges],
  ] as [BridgeKind, BridgeData[]][]) {
    for (const b of list) {
      bridgeKey.push({
        bridge: b,
        kind,
        index: bridgeKey.length + 1,
        endpoints: `${objLabel(b.obj1_string, b.obj1_pos, b.obj1_right_pos)}↔${objLabel(
          b.obj2_string, b.obj2_pos, b.obj2_right_pos,
        )}`,
      });
    }
  }

  // The inter-row band has to fit one badge per vertical bridge without them
  // crowding each other, so it grows with the bridge count instead of being a
  // fixed height everything is squeezed into.
  const bridgeBand = Math.max(BRIDGE_BAND, vertBridges.length * BADGE_PITCH + 20);
  const rowGap = FOOT_BAND + bridgeBand + HEAD_BAND;
  const botRowY = TOP_Y + LETTER_H + rowGap;

  // Tall enough for both rows' reserved bands, the bridge band between them and
  // the bridge key beneath — rather than a fixed 320 everything was squeezed
  // into.
  const KEY_Y = botRowY + LETTER_H + FOOT_BAND + 18;
  const SVG_H = KEY_Y + bridgeKey.length * 12 + 8;
  const topTotalW = initial.length * LETTER_W + ARROW_PAD + ARROW_LEN + ARROW_PAD + modified.length * LETTER_W;
  const botTotalW = target.length * LETTER_W + ARROW_PAD + ARROW_LEN + ARROW_PAD + (answer ? answer.length * LETTER_W : 3 * LETTER_W);
  const SVG_W = Math.max(500, Math.max(topTotalW, botTotalW) + 2 * SIDE_PAD + 120);

  const topPair = layoutPair(
    initial, 'initial', bondsFor(initial), groupsFor(initial),
    modified, 'modified', bondsFor(modified), groupsFor(modified),
    TOP_Y, SVG_W,
  );
  const botPair = layoutPair(
    target, 'target', bondsFor(target), groupsFor(target),
    answer, 'answer', answer ? bondsFor(answer) : [], answer ? groupsFor(answer) : [],
    botRowY, SVG_W,
  );

  const allStrings = [topPair.left, topPair.right, botPair.left, botPair.right].filter(
    (s): s is StringLayoutResult => s !== null,
  );

  const arrowY1 = TOP_Y + LETTER_H / 2;
  const arrowY2 = botRowY + LETTER_H / 2;

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMin meet"
      style={{ maxHeight: SVG_H, display: 'block' }}
    >
      <rect width={SVG_W} height={SVG_H} fill="var(--bg-secondary)" rx={4} />

      {/* Group enclosures (behind letters) */}
      {allStrings.map((s) => (
        <GroupBoxes key={`groups-${s.label}`} s={s} />
      ))}

      {/* Strings: letters */}
      {allStrings.map((s) => (
        <g key={s.label}>
          {/* In its own band above the group labels, which are themselves above
              the box. Both used to sit a fixed 12px up and overlap. */}
          <text
            x={s.x + (s.text.length * LETTER_W) / 2}
            y={s.y - GROUP_LABEL_BAND - 2}
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

      {/* Bridges, numbered continuously so each badge has one legend row */}
      <BridgeLines
        bridges={topBridges} layouts={allStrings} color={BRIDGE_COLORS.top}
        firstNumber={1} countOfKind={topBridges.length}
        gap={{ x: (topPair.arrowX1 + topPair.arrowX2) / 2, y: arrowY1 }}
      />
      <BridgeLines
        bridges={vertBridges} layouts={allStrings} color={BRIDGE_COLORS.vertical}
        firstNumber={1 + topBridges.length} countOfKind={vertBridges.length}
        band={{
          y1: topPair.left.y + LETTER_H + FOOT_BAND + 6,
          y2: botPair.left.y - HEAD_BAND - 6,
        }}
      />
      <BridgeLines
        bridges={bottomBridges} layouts={allStrings} color={BRIDGE_COLORS.bottom}
        firstNumber={1 + topBridges.length + vertBridges.length}
        countOfKind={bottomBridges.length}
        gap={{ x: (botPair.arrowX1 + botPair.arrowX2) / 2, y: arrowY2 }}
      />

      {/* Structure counts, drawn last of the per-string text so the bridge
          arcs that cross this band pass behind them. */}
      {allStrings.map((s) => (
        <text
          key={`counts-${s.label}`}
          x={s.x + (s.text.length * LETTER_W) / 2}
          y={s.y + LETTER_H + BOND_BAND + 8}
          textAnchor="middle"
          fill="var(--text-secondary)"
          fontSize={9}
          stroke="var(--bg-secondary)"
          strokeWidth={3}
          paintOrder="stroke"
        >
          B:{bondCountFor(s.text)} G:{groupCountFor(s.text)}
        </text>
      ))}

      <BridgeKey entries={bridgeKey} y={KEY_Y} width={SVG_W} />

      {/* Bridge counts */}
      <text x={SVG_W - 12} y={12} textAnchor="end" fill="var(--text-secondary)" fontSize={9}>
        bridges: top={num_top_bridges} vert={num_vertical_bridges} bot={num_bottom_bridges}
      </text>

      {/* Rules, in the reserved band above each row's string label. They used to
          be placed relative to the arrow and landed across the letters, the
          group boxes and the string labels all at once. */}
      {topRules.slice(0, 2).map((r, i) => (
        <text
          key={`top-rule-${i}`}
          x={SVG_W / 2} y={TOP_CHROME + RULE_H - 2 + i * RULE_H}
          textAnchor="middle"
          fill="var(--success)"
          fontSize={9}
          opacity={Math.max(0.4, r.quality / 100)}
        >
          <title>{`Top rule: ${r.english} (${ruleMeasures(r)})`}</title>
          Top: {clip(r.english, 60)} ({ruleMeasures(r)})
        </text>
      ))}
      {bottomRules.slice(0, 2).map((r, i) => (
        <text
          key={`bot-rule-${i}`}
          x={SVG_W / 2}
          y={botPair.left.y - HEAD_BAND + RULE_H - 2 + i * RULE_H}
          textAnchor="middle"
          fill="var(--success)"
          fontSize={9}
          opacity={Math.max(0.4, r.quality / 100)}
        >
          <title>{`Bottom rule: ${r.english} (${ruleMeasures(r)})`}</title>
          Bot: {clip(r.english, 60)} ({ruleMeasures(r)})
        </text>
      ))}

      {/* Which colour means what — the three bridge types are otherwise
          indistinguishable. Laid out in one row so it costs a single band. */}
      <g fontSize={8} fill="var(--text-secondary)">
        {(['top', 'vertical', 'bottom'] as BridgeKind[]).map((kind, i) => {
          const x = SIDE_PAD + i * 62;
          return (
            <g key={kind}>
              <line
                x1={x} y1={9} x2={x + 12} y2={9}
                stroke={BRIDGE_COLORS[kind]} strokeWidth={1.5}
              />
              <text x={x + 16} y={12}>{kind}</text>
            </g>
          );
        })}
      </g>

      <defs>
        <marker id="arrowhead" markerWidth={8} markerHeight={6} refX={7} refY={3} orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill="var(--text-accent)" />
        </marker>
      </defs>
    </svg>
  );
}
