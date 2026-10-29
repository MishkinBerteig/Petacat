// ---------------------------------------------------------------------------
// ClampControls -- Metacat's clamp and self-watching menu items
// ---------------------------------------------------------------------------
//
// Metacat's Options menu (`gui.ss:594-626`) has "Clamp theme pattern", "Undo last
// clamp" and a "Self-watching mode" check item. "Clamp theme pattern" opens a dialog
// with instructions while the user picks themes in the theme windows (`gui.ss:881-894`),
// which here is the Themespace panel in edit mode; "Clamp Themes" clamps them together
// as one pattern. Switching self-watching off in the middle of a run undoes the last
// clamp and deletes the themes, disables the clamp items and shows the red warning.
// ---------------------------------------------------------------------------

import { SelfWatchingWarning, useSelfWatchingDisabled } from '@/components/SelfWatchingWarning';
import { useRunStore } from '@/store/runStore';

/** The dialog's text, word for word from `gui.ss:881-894`; the click wording is the platform's. */
export function themeEditInstructions(macintosh: boolean): string[] {
  return [
    'To clamp a theme-pattern, click on one or more theme windows, select the themes ' +
      'to include in the pattern, and then click Clamp Themes.',
    macintosh
      ? 'Clicking on a theme selects maximum positive theme activation.  Shift-clicking ' +
        'selects maximum negative activation.  Clicking on an already-selected theme ' +
        'unselects it.'
      : 'Left-clicking on a theme selects maximum positive theme activation.  ' +
        'Right-clicking selects maximum negative activation.  Clicking on an ' +
        'already-selected theme unselects it.',
  ];
}

function isMacintosh(): boolean {
  try {
    return /Mac/i.test(navigator.platform);
  } catch {
    return false;
  }
}

export function ClampControls() {
  const runId = useRunStore((s) => s.runId);
  const themeEdit = useRunStore((s) => s.themeEdit);
  const beginThemeEdit = useRunStore((s) => s.beginThemeEdit);
  const cancelThemeEdit = useRunStore((s) => s.cancelThemeEdit);
  const commitThemeEdit = useRunStore((s) => s.commitThemeEdit);
  const undoLastClamp = useRunStore((s) => s.undoLastClamp);
  const setSelfWatching = useRunStore((s) => s.setSelfWatching);
  const verboseMode = useRunStore((s) => s.verboseMode);
  const setVerboseMode = useRunStore((s) => s.setVerboseMode);
  const selfWatchingOff = useSelfWatchingDisabled('loaded');

  const hasRun = runId !== null;
  const editing = themeEdit !== null;
  const clampsDisabled = !hasRun || selfWatchingOff || editing;

  return (
    <div
      data-testid="clamp-controls"
      style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}
    >
      <SelfWatchingWarning which="loaded" />
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        <button
          onClick={beginThemeEdit}
          disabled={!hasRun || selfWatchingOff || editing}
          title="Choose themes in the Themespace and clamp them together as one pattern."
        >
          Clamp theme pattern
        </button>
        <button
          onClick={() => void undoLastClamp()}
          disabled={clampsDisabled}
          title="Undo the most recent clamp, and only that one."
        >
          Undo last clamp
        </button>
      </div>
      <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
        <input
          type="checkbox"
          checked={!selfWatchingOff}
          disabled={!hasRun || editing}
          onChange={(e) => void setSelfWatching(e.target.checked)}
        />
        <span>Self-watching mode</span>
      </label>
      <label
        style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12 }}
        title="Narrate what the codelets do in the Verbose panel (slows the run down)."
      >
        <input
          type="checkbox"
          checked={verboseMode}
          onChange={(e) => void setVerboseMode(e.target.checked)}
        />
        <span>Verbose mode</span>
      </label>

      {editing && (
        <div
          role="dialog"
          aria-label="Clamp theme pattern"
          data-testid="theme-edit-dialog"
          style={{
            background: '#ffff00',
            color: '#000',
            border: '1px solid var(--border)',
            borderRadius: 4,
            padding: 10,
            fontSize: 12,
            textAlign: 'left',
          }}
        >
          {themeEditInstructions(isMacintosh()).map((paragraph) => (
            <p key={paragraph} style={{ margin: '0 0 8px' }}>
              {paragraph}
            </p>
          ))}
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={() => void commitThemeEdit()}>Clamp Themes</button>
            <button onClick={cancelThemeEdit}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
