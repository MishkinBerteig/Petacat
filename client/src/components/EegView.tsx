// ---------------------------------------------------------------------------
// EegView -- Metacat's EEG window: average Workspace activity and temperature
// ---------------------------------------------------------------------------
//
// `eeg-graphics.ss` plots two curves against time, one point per update cycle:
// the average of the last ten Workspace-activity readings (yellow) and the
// temperature (red), both 0-100, starting from 100. Metacat scrolls a 400-cycle
// window along the run; here the plot grows with the run and scrolls sideways,
// following the newest cycle while the run is live.
//
// The curves are the engine's: it records them at the moments Metacat samples them
// (`update-everything`), and this component only draws what it is given.
// ---------------------------------------------------------------------------

import { useEffect, useRef } from 'react';

import { useRunStore } from '@/store/runStore';
import type { EegHistory } from '@/types';

/** `%max-EEG-window-cycles%` (`eeg-graphics.ss:67`): cycles that fit one screen. */
const WINDOW_CYCLES = 400;
const HEIGHT = 100;

/** Metacat's colours are named in its table; the plot keeps them. */
function stroke(color: string): string {
  return color === 'yellow' ? '#ffd600' : color === 'red' ? '#ff5252' : color;
}

/** The plot, given its data -- usable for a live run or a recorded one. */
export function EegPlot({ eeg }: { eeg: EegHistory | null }) {
  const scroller = useRef<HTMLDivElement>(null);
  const count = eeg?.samples.length ?? 0;

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [count]);

  if (!eeg) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        No EEG for this run. It is recorded while a run is in memory.
      </div>
    );
  }

  const width = Math.max(WINDOW_CYCLES, count);
  // Plot y so that 100 is at the top; the curve starts at the table's initial value.
  const y = (value: number) => HEIGHT - Math.max(0, Math.min(100, value));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 4 }}>
      <div className="text-xs" style={{ textAlign: 'center', fontStyle: 'italic' }}>
        {eeg.series.map((s, i) => (
          <span key={s.key}>
            {i > 0 && ', '}
            <span style={{ color: stroke(s.color) }}>
              {s.label} ({s.color})
            </span>
          </span>
        ))}
      </div>
      <div
        ref={scroller}
        data-testid="eeg-scroller"
        style={{
          flex: 1,
          minHeight: 60,
          overflowX: 'auto',
          overflowY: 'hidden',
          background: '#111',
          border: '1px solid var(--border)',
          borderRadius: 3,
        }}
      >
        <svg
          viewBox={`0 0 ${width} ${HEIGHT}`}
          preserveAspectRatio="none"
          style={{ width: `${(width / WINDOW_CYCLES) * 100}%`, minWidth: '100%', height: '100%' }}
          role="img"
          aria-label="EEG: average Workspace activity and temperature over time"
        >
          {eeg.series.map((s) => {
            const points = [
              `0,${y(eeg.initial_value)}`,
              ...eeg.samples.map((p) => `${p.cycle},${y(p[s.key])}`),
            ];
            return (
              <polyline
                key={s.key}
                data-testid={`eeg-curve-${s.key}`}
                points={points.join(' ')}
                fill="none"
                stroke={stroke(s.color)}
                strokeWidth={1.5}
                vectorEffect="non-scaling-stroke"
              />
            );
          })}
        </svg>
      </div>
    </div>
  );
}

/** The live EEG: `EegPlot` fed from the run store. */
export function EegView() {
  const eeg = useRunStore((s) => s.eeg);
  return <EegPlot eeg={eeg} />;
}
