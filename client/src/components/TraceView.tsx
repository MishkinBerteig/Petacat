// ---------------------------------------------------------------------------
// TraceView -- Scrollable, filterable list of temporal trace events
// ---------------------------------------------------------------------------

import { useState, useEffect, useRef } from 'react';
import { useRunStore } from '@/store/runStore';
import type { TraceEvent } from '@/types';

/** Event type to a short icon prefix for compact display. */
function eventIcon(eventType: string): string {
  const t = eventType.toUpperCase();
  if (t.includes('BOND') && t.includes('BUILT')) return '[B+]';
  if (t.includes('BOND') && t.includes('BROKEN')) return '[B-]';
  if (t.includes('BOND')) return '[B]';
  if (t.includes('GROUP') && t.includes('BUILT')) return '[G+]';
  if (t.includes('GROUP') && t.includes('BROKEN')) return '[G-]';
  if (t.includes('GROUP')) return '[G]';
  if (t.includes('BRIDGE') && t.includes('BUILT')) return '[BR+]';
  if (t.includes('BRIDGE') && t.includes('BROKEN')) return '[BR-]';
  if (t.includes('BRIDGE')) return '[BR]';
  if (t.includes('RULE')) return '[R]';
  if (t.includes('SNAG')) return '[!]';
  if (t.includes('CLAMP_START')) return '[C+]';
  if (t.includes('CLAMP_END')) return '[C-]';
  if (t.includes('CLAMP')) return '[C]';
  if (t.includes('ANSWER')) return '[A]';
  if (t.includes('JOOTSING')) return '[J]';
  if (t.includes('DESCRIPTION')) return '[D]';
  if (t.includes('PROGRESS')) return '[P]';
  return '[.]';
}

function eventColor(eventType: string): string {
  const t = eventType.toUpperCase();
  if (t.includes('SNAG') || t.includes('BROKEN')) return 'var(--error)';
  if (t.includes('ANSWER')) return 'var(--success)';
  if (t.includes('CLAMP') || t.includes('JOOTSING')) return 'var(--warning)';
  if (t.includes('BUILT')) return 'var(--text-accent)';
  return 'var(--text-secondary)';
}

/** Extract unique event types from a list. */
function uniqueTypes(events: TraceEvent[]): string[] {
  const seen = new Set<string>();
  for (const e of events) seen.add(e.event_type);
  return Array.from(seen).sort();
}

export function TraceView() {
  const trace = useRunStore((s) => s.trace);
  const [filter, setFilter] = useState<string>('');
  const [search, setSearch] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevLength = useRef(0);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (trace.length > prevLength.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    prevLength.current = trace.length;
  }, [trace.length]);

  let filtered = filter
    ? trace.filter((e) => e.event_type === filter)
    : trace;
  if (search) {
    const q = search.toLowerCase();
    filtered = filtered.filter(e =>
      e.description.toLowerCase().includes(q) ||
      e.event_type.toLowerCase().includes(q)
    );
  }

  const types = uniqueTypes(trace);

  if (trace.length === 0) {
    return (
      <div className="text-muted text-sm" style={{ padding: 16, textAlign: 'center' }}>
        No trace events yet.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Filter controls */}
      <div style={{ marginBottom: 4, flexShrink: 0, display: 'flex', gap: 4 }}>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ flex: 1, fontSize: 11 }}
        >
          <option value="">All events ({trace.length})</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t} ({trace.filter((e) => e.event_type === t).length})
            </option>
          ))}
        </select>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search..."
          style={{ width: 100, fontSize: 11, padding: '1px 4px' }}
        />
        <span className="text-muted text-xs" style={{ alignSelf: 'center' }}>
          {filtered.length}
        </span>
      </div>

      {/* Scrollable event list */}
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflow: 'auto',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          lineHeight: 1.6,
        }}
      >
        {filtered.map((evt) => (
          <div
            key={evt.event_number}
            style={{
              display: 'flex',
              gap: 6,
              padding: '1px 0',
              borderBottom: '1px solid var(--bg-primary)',
              alignItems: 'baseline',
            }}
          >
            <span
              style={{
                width: 32,
                textAlign: 'right',
                color: 'var(--text-secondary)',
                flexShrink: 0,
              }}
            >
              {evt.event_number}
            </span>
            <span
              style={{
                width: 36,
                color: eventColor(evt.event_type),
                fontWeight: 600,
                flexShrink: 0,
              }}
            >
              {eventIcon(evt.event_type)}
            </span>
            <span
              className="text-xs"
              style={{
                width: 40,
                color: 'var(--text-secondary)',
                flexShrink: 0,
              }}
              title="codelet count"
            >
              c:{evt.codelet_count}
            </span>
            <span
              className="text-xs"
              style={{
                width: 36,
                color: 'var(--text-secondary)',
                flexShrink: 0,
              }}
              title="temperature"
            >
              T:{evt.temperature.toFixed(0)}
            </span>
            <span
              style={{
                flex: 1,
                color: 'var(--text-primary)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              title={evt.description}
            >
              {evt.description}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
