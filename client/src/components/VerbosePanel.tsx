// ---------------------------------------------------------------------------
// VerbosePanel -- Metacat's Verbose mode, the engine narrating what its codelets do
// ---------------------------------------------------------------------------
//
// Metacat prints this to the Interaction window when the Options menu's "Verbose mode" is
// checked (`gui.ss:664`): a dashed line and "In <codelet type> codelet..." for every
// codelet, then what it chose, what it tried and why it fizzled.  The help text calls the
// messages technical, useful "for debugging, or for seeing what individual codelets are
// doing", and warns that they slow the program down considerably (`help.txt:75`).
//
// The lines come from `GET /runs/{id}/verbose`, polled with the other panels, and are kept
// in a bounded buffer in the run store.  The panel asks for nothing while it is hidden and
// Verbose mode is off; a step of ten codelets or fewer narrates itself regardless
// (`set-verbose-step-mode`), so an open panel with the mode off still shows those.
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useRef } from 'react';
import { useRunStore } from '@/store/runStore';

/** Save the narration as a text file, as the commentary panel does for its text. */
export function verboseFilename(runId: number | null): string {
  return `petacat-verbose${runId !== null ? `-run-${runId}` : ''}.txt`;
}

export function VerbosePanel() {
  const runId = useRunStore((s) => s.runId);
  const verboseMode = useRunStore((s) => s.verboseMode);
  const lines = useRunStore((s) => s.verboseLines);
  const dropped = useRunStore((s) => s.verboseDropped);
  const setVerboseMode = useRunStore((s) => s.setVerboseMode);
  const clearVerbose = useRunStore((s) => s.clearVerbose);

  const scrollRef = useRef<HTMLDivElement>(null);
  // The panel opens on a run that may already hold narration it has not fetched.
  useEffect(() => {
    void useRunStore.getState().refreshVerbose();
  }, [runId]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [lines]);

  const save = useCallback(() => {
    const text = lines.join('\n');
    const blob = new Blob([text.endsWith('\n') ? text : `${text}\n`], {
      type: 'text/plain;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = verboseFilename(runId);
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, [lines, runId]);

  return (
    <div data-testid="verbose-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div
        className="text-xs text-muted"
        style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2, flexWrap: 'wrap' }}
      >
        <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <input
            type="checkbox"
            checked={verboseMode}
            onChange={(e) => void setVerboseMode(e.target.checked)}
          />
          <span>Verbose mode</span>
        </label>
        <span style={{ flex: 1 }} />
        <button
          type="button"
          onClick={() => void clearVerbose()}
          disabled={lines.length === 0}
          style={{ fontSize: 10, padding: '1px 6px' }}
          title="Empty the narration shown."
        >
          Clear
        </button>
        <button
          type="button"
          onClick={save}
          disabled={lines.length === 0}
          style={{ fontSize: 10, padding: '1px 6px' }}
          title="Save the narration shown to a text file."
        >
          Save to file
        </button>
      </div>
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflow: 'auto',
          padding: 4,
          background: 'var(--bg-card)',
          borderRadius: 4,
          border: '1px solid var(--border)',
        }}
      >
        {lines.length > 0 ? (
          <>
            {dropped > 0 && (
              <div className="text-muted text-xs" data-testid="verbose-dropped">
                {dropped} earlier line{dropped === 1 ? '' : 's'} no longer kept.
              </div>
            )}
            <pre
              style={{
                whiteSpace: 'pre-wrap',
                wordWrap: 'break-word',
                fontFamily: 'var(--font-mono, monospace)',
                fontSize: 11,
                lineHeight: 1.35,
                color: 'var(--text-primary)',
                margin: 0,
              }}
            >
              {lines.join('\n')}
            </pre>
          </>
        ) : (
          <div className="text-muted text-sm" style={{ padding: 8 }}>
            {verboseMode
              ? 'Verbose mode is on. Run or step to see what the codelets do.'
              : 'Verbose mode is off. Check it to narrate what the codelets do (it slows the run down), or press Step: a step of ten codelets or fewer is narrated anyway.'}
          </div>
        )}
      </div>
    </div>
  );
}
