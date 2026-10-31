// ---------------------------------------------------------------------------
// CollapsibleGroup — one Run Controls group behind a single-row header
// ---------------------------------------------------------------------------
//
// The Run Controls panel holds six groups used together, so they are sections that
// open independently rather than tabs that exclude each other. Closed, a group is
// one row (chevron, label, its `?` help), which keeps every group findable at once.
//
// A closed group is hidden, not unmounted: the Swarm group keeps its last result and
// its status fetch, and the breakpoint field keeps what was typed in it. Each
// group's open/closed state is remembered per browser; storage may be absent or
// throw (private windows, blocked site data), and the panel works without it.
// ---------------------------------------------------------------------------

import { useCallback, useState, type ReactNode } from 'react';
import { ControlHelp } from '@/components/training/shared';
import type { ComponentHelpKey } from '@/constants/helpTopics';

const STORAGE_PREFIX = 'petacat.runControls.open.';

function readOpen(id: string, fallback: boolean): boolean {
  try {
    const stored = window.localStorage.getItem(STORAGE_PREFIX + id);
    if (stored === 'true') return true;
    if (stored === 'false') return false;
  } catch {
    // No storage: the default stands.
  }
  return fallback;
}

function writeOpen(id: string, open: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + id, String(open));
  } catch {
    // Not remembered; the group still opens and closes.
  }
}

export interface CollapsibleGroupProps {
  /** Storage key and DOM id stem: `run-group-<id>` is the section, `-header` its button. */
  id: string;
  title: string;
  /** A muted aside after the title, e.g. what the group is not. */
  note?: string;
  defaultOpen: boolean;
  /** The group's help topic, shown as a `?` beside the header. */
  helpTopic?: ComponentHelpKey;
  children: ReactNode;
}

export function CollapsibleGroup({
  id,
  title,
  note,
  defaultOpen,
  helpTopic,
  children,
}: CollapsibleGroupProps) {
  const [open, setOpen] = useState(() => readOpen(id, defaultOpen));
  const toggle = useCallback(() => {
    setOpen(!open);
    writeOpen(id, !open);
  }, [id, open]);

  const bodyId = `run-group-${id}`;
  return (
    <div style={groupStyle} data-testid={`group-${id}`}>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <button
          type="button"
          id={`${bodyId}-header`}
          onClick={toggle}
          aria-expanded={open}
          aria-controls={bodyId}
          style={headerButtonStyle}
        >
          <span style={groupLabelStyle}>{title}</span>
          {note && <span className="text-xs text-muted">{note}</span>}
          <span className="text-muted" style={{ fontSize: 11 }} aria-hidden="true">
            {open ? '▾' : '▸'}
          </span>
        </button>
        <span style={{ flex: 1 }} />
        {helpTopic && <ControlHelp topic={helpTopic} label={title} />}
      </div>
      <div id={bodyId} role="region" aria-labelledby={`${bodyId}-header`} hidden={!open} style={{ marginTop: 8 }}>
        {children}
      </div>
    </div>
  );
}

const groupStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: 4,
  padding: '8px 10px',
};

const headerButtonStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  background: 'transparent',
  border: 'none',
  padding: 0,
  cursor: 'pointer',
  textAlign: 'left',
  color: 'var(--text-secondary)',
};

const groupLabelStyle: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: 0.6,
  color: 'var(--text-secondary)',
};
