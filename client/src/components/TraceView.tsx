// ---------------------------------------------------------------------------
// TraceView -- Scrollable, filterable list of temporal trace events
// ---------------------------------------------------------------------------

import { useState, useEffect, useRef } from 'react';
import { useRunStore } from '@/store/runStore';
import type { TraceEvent } from '@/types';

/** The seven Trace event types of §4.4, in the order the dissertation lists them.
 *
 * The Trace is Metacat's *cognitive* level: a typical run is a few dozen of
 * these, each a "macroscopic" processing event that may itself comprise the
 * actions of many codelets.  Bond and description building never appears here.
 */
const EVENT_LABELS: Record<string, { icon: string; label: string; color: string }> = {
  concept_activation: { icon: '[◈]', label: 'concept activated', color: 'var(--text-accent)' },
  group_built: { icon: '[G]', label: 'group perceived', color: '#4caf50' },
  concept_mapping_built: { icon: '[⇒]', label: 'slippage', color: '#03a9f4' },
  rule_built: { icon: '[R]', label: 'rule created', color: '#9c27b0' },
  answer_found: { icon: '[A]', label: 'answer', color: 'var(--success)' },
  snag: { icon: '[!]', label: 'snag', color: 'var(--error)' },
  clamp_start: { icon: '[C]', label: 'pattern clamped', color: 'var(--warning)' },
};

/** Event type to a short icon prefix for compact display. */
function eventIcon(eventType: string): string {
  return EVENT_LABELS[eventType]?.icon ?? '[.]';
}

/** Human-readable name for an event type. */
function eventLabel(eventType: string): string {
  return EVENT_LABELS[eventType]?.label ?? eventType.replace(/_/g, ' ');
}

function eventColor(eventType: string): string {
  return EVENT_LABELS[eventType]?.color ?? 'var(--text-secondary)';
}


/** Extract unique event types from a list. */
function uniqueTypes(events: TraceEvent[]): string[] {
  const seen = new Set<string>();
  for (const e of events) seen.add(e.event_type);
  return Array.from(seen).sort();
}

/**
 * The event list, given its events.
 *
 * Split from `TraceView` so a review surface can show the Trace a recorded state
 * carried (WP3.9). The filtering, the search and the auto-scroll are all functions
 * of the event list, so nothing had to change to make them work on a recorded one.
 */
export function TraceList({ trace }: { trace: TraceEvent[] }) {
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
              {eventLabel(t)} ({trace.filter((e) => e.event_type === t).length})
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

/** The live Trace: `TraceList` fed from the run store. */
export function TraceView() {
  const trace = useRunStore((s) => s.trace);
  return <TraceList trace={trace} />;
}
