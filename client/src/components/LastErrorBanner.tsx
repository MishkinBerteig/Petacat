// ---------------------------------------------------------------------------
// LastErrorBanner — the one place a failed request is reported
// ---------------------------------------------------------------------------
//
// The store keeps a single error channel (`lastError`) holding one actionable
// sentence about the last thing the user asked for that did not happen. This
// renders it, in the header, so it is visible from whichever panel the click came
// from — a create refused in the run controls, a stop refused from the workspace
// header, a threshold the run would not take.
//
// It carries user-initiated failures only. A poll that fails is recovered by the
// tick after it and belongs in the console.
// ---------------------------------------------------------------------------

import { useRunStore } from '@/store/runStore';

export function LastErrorBanner() {
  const lastError = useRunStore((s) => s.lastError);
  const clearLastError = useRunStore((s) => s.clearLastError);

  if (lastError === null) return null;

  return (
    <span
      role="alert"
      title={lastError}
      style={{
        marginLeft: 'auto',
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        maxWidth: '55%',
        padding: '1px 8px',
        borderRadius: 3,
        border: '1px solid var(--error)',
        color: 'var(--error)',
        background: 'var(--bg-card)',
        fontSize: 11,
      }}
    >
      {/* The full sentence is in the `title` and in the accessible name, so a
          message wider than the header bar is still readable in full. */}
      <span
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {lastError}
      </span>
      <button
        onClick={clearLastError}
        aria-label="Dismiss error"
        title="Dismiss"
        style={{
          background: 'none',
          border: 'none',
          padding: 0,
          color: 'inherit',
          cursor: 'pointer',
          fontSize: 13,
          lineHeight: 1,
        }}
      >
        &times;
      </button>
    </span>
  );
}
