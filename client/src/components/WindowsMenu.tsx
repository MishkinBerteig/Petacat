// ---------------------------------------------------------------------------
// WindowsMenu -- Metacat's Windows menu and graphics switches
// ---------------------------------------------------------------------------
//
// One entry per panel to show or hide it, then "Show all windows" and "Hide all
// windows" (`gui.ss:1091-1162`), and the "Slipnet graphics" / "Coderack graphics"
// check items from the Options menu (`gui.ss:638-651`).
// ---------------------------------------------------------------------------

import { useEffect, useRef, useState } from 'react';
import { useDisplayStore, WINDOW_PANELS } from '@/store/displayStore';
import { useRunStore } from '@/store/runStore';

export function WindowsMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const hidden = useDisplayStore((s) => s.hidden);
  const slipnetGraphics = useDisplayStore((s) => s.slipnetGraphics);
  const coderackGraphics = useDisplayStore((s) => s.coderackGraphics);
  const { togglePanel, showAll, hideAll, setSlipnetGraphics, setCoderackGraphics } =
    useDisplayStore.getState();

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const item = (label: string, onClick: () => void, on?: boolean) => (
    <button
      key={label}
      role="menuitem"
      onClick={() => {
        onClick();
        setOpen(false);
      }}
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        background: 'none',
        border: 'none',
        padding: '4px 12px',
        fontSize: 12,
        cursor: 'pointer',
        color: on === false ? 'var(--text-secondary, #999)' : 'var(--text-primary, #ddd)',
      }}
    >
      {label}
    </button>
  );

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block', marginRight: 8 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        title="Show or hide panels; switch the Slipnet and Coderack graphics"
        style={{
          background: 'none',
          border: '1px solid var(--border, #444)',
          borderRadius: 4,
          color: 'var(--text-primary, #ddd)',
          cursor: 'pointer',
          fontSize: 12,
          padding: '2px 8px',
        }}
      >
        Windows
      </button>
      {open && (
        <div
          role="menu"
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            marginTop: 4,
            background: 'var(--bg-panel, #1e1e1e)',
            border: '1px solid var(--border, #444)',
            borderRadius: 4,
            minWidth: 200,
            zIndex: 1000,
            boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
          }}
        >
          {WINDOW_PANELS.map((w) => {
            const shown = !hidden.includes(w.key);
            return item(`${shown ? 'Hide' : 'Show'} ${w.label}`, () => togglePanel(w.key), shown);
          })}
          <hr style={{ border: 0, borderTop: '1px solid var(--border, #444)', margin: '4px 0' }} />
          {item('Show all windows', showAll)}
          {item('Hide all windows', hideAll)}
          <hr style={{ border: 0, borderTop: '1px solid var(--border, #444)', margin: '4px 0' }} />
          {item(`${slipnetGraphics ? '✓' : '  '} Slipnet graphics`, () => {
            setSlipnetGraphics(!slipnetGraphics);
            // Switching back on restores the current state at once.
            if (!slipnetGraphics) void useRunStore.getState().refreshSlipnet();
          })}
          {item(`${coderackGraphics ? '✓' : '  '} Coderack graphics`, () => {
            setCoderackGraphics(!coderackGraphics);
            if (!coderackGraphics) void useRunStore.getState().refreshCoderack();
          })}
        </div>
      )}
    </div>
  );
}
