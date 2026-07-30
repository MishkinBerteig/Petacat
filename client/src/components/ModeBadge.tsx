// ---------------------------------------------------------------------------
// ModeBadge -- a Run's persistence mode, and what that mode promises
// ---------------------------------------------------------------------------
//
// Lives here rather than in the review folder because the dashboard needs it too.
// The mode of the run you are watching is not only a fact about the record: it
// decides whether the run will appear in Run History at all, and a reader who
// discovers that by not finding it has been let down by the UI rather than by the
// mode.
//
// One definition, so the colour and the wording cannot drift between the live
// dashboard and the Review browser and leave the same mode looking like two.
// ---------------------------------------------------------------------------

/** Persistence mode to a colour, so a mixed session reads at a glance. */
export const MODE_COLORS: Record<string, string> = {
  fast: '#90a4ae',
  normal: '#4fc3f7',
  audit: '#ab47bc',
};

/**
 * What a mode promises to leave behind. Shown as a tooltip because "this run has
 * nothing to review" is a statement about the mode, not a fault, and a reader who
 * has not read the plan has no way to know that.
 */
export const MODE_NOTES: Record<string, string> = {
  fast: 'Fast: writes nothing, ever — there is no record to review.',
  normal: 'Normal: the complete state at Run start and Run end, and nothing between.',
  audit: 'Audit: every state-changing action, as a forward log.',
};

/** One-line description used where there is room for prose rather than a tooltip. */
export const MODE_DESCRIPTIONS: Record<string, string> = {
  fast:
    'Nothing is written down: no run row, no captures, no trace. The run will not '
    + 'appear in Run History or the Review browser, and its answer does not join '
    + 'Episodic Memory. Fastest, and disposable.',
  normal:
    'The complete engine state at Run start and at Run end, and nothing in between. '
    + 'Enough to re-execute the run and arrive at the recorded ending.',
  audit:
    'Every state-changing action, as a forward log you can step through tick by '
    + 'tick. Roughly 1.8x the wall time of Fast, by design.',
};

export function ModeBadge({ mode }: { mode: string }) {
  return (
    <span
      title={MODE_NOTES[mode] ?? mode}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        fontWeight: 700,
        textTransform: 'uppercase',
        padding: '1px 5px',
        borderRadius: 3,
        color: MODE_COLORS[mode] ?? 'var(--text-secondary)',
        border: `1px solid ${MODE_COLORS[mode] ?? 'var(--border)'}`,
      }}
    >
      {mode}
    </span>
  );
}
