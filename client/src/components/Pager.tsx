// ---------------------------------------------------------------------------
// Pager -- one window of a server-paged list, with the total behind it
// ---------------------------------------------------------------------------
//
// Three lists in Petacat are paged by the server: Run History, the Training
// Session browser and the audit action log. Each takes a `limit` and an `offset`
// and reports a `total`, and a reader needs both halves of that -- which window
// they are looking at, and how many records exist behind it.
//
// One component, so the wording and the controls read the same wherever a reader
// meets them.
// ---------------------------------------------------------------------------

interface Props {
  /** Where the current window starts, in records. */
  offset: number;
  /** How many records a window holds. */
  limit: number;
  /** How many records exist, as the server reports it. */
  total: number;
  /** How many records the current window actually holds. */
  count: number;
  /** Move to a window starting here. */
  onChange: (offset: number) => void;
  /**
   * What is being counted, plural — "runs", "sessions", "actions from tick 12".
   * Read straight after the numbers: "51–100 of 137 runs".
   */
  label: string;
}

export function Pager({ offset, limit, total, count, onChange, label }: Props) {
  const first = count === 0 ? 0 : offset + 1;
  const last = offset + count;
  const hasPrev = offset > 0;
  const hasNext = offset + count < total;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 6px',
        borderTop: '1px solid var(--border)',
        fontSize: 11,
      }}
    >
      <span className="text-muted" style={{ fontFamily: 'var(--font-mono)' }}>
        {first}–{last} of {total} {label}
      </span>
      <span style={{ flex: 1 }} />
      {/* Named by what they page, because a screen can hold more than one of these
          — the audit log sits inside the Run the Session browser is listing. */}
      <button
        onClick={() => onChange(Math.max(0, offset - limit))}
        disabled={!hasPrev}
        aria-label={`Previous page of ${label}`}
        title={`Show the previous ${limit} ${label}`}
        style={btn}
      >
        ‹ prev
      </button>
      <button
        onClick={() => onChange(offset + limit)}
        disabled={!hasNext}
        aria-label={`Next page of ${label}`}
        title={`Show the next ${limit} ${label}`}
        style={btn}
      >
        next ›
      </button>
    </div>
  );
}

const btn: React.CSSProperties = {
  fontSize: 10,
  padding: '1px 7px',
  borderRadius: 3,
  cursor: 'pointer',
  background: 'transparent',
  border: '1px solid var(--border)',
  color: 'var(--text-primary)',
};
