// ---------------------------------------------------------------------------
// CommentaryPanel -- Scrollable text area showing run commentary
// ---------------------------------------------------------------------------
//
// One wrinkle from Phase 0's WP3.10: commentary became a sink concern, and a Fast
// Run is handed a discarding writer. The engine still calls `emit_*` for every
// paragraph; nothing keeps them. So a Fast Run that has answered returns an empty
// commentary, and the panel's ordinary empty message ("start a run to see
// commentary") is then a lie about a run that has already finished.
// ---------------------------------------------------------------------------

import { useRef, useEffect, useCallback, useState } from 'react';
import { useRunStore } from '@/store/runStore';

/**
 * Save the commentary as a text file -- Metacat's "Save commentary to file"
 * (`gui.ss:356-368`). Metacat writes the paragraphs of the voice on screen (Eliza or
 * technical), one per block, so this saves what the panel shows, in the voice it is
 * showing.
 */
export function commentaryFilename(runId: number | null, elizaMode: boolean): string {
  return `petacat-commentary${runId !== null ? `-run-${runId}` : ''}-${
    elizaMode ? 'eliza' : 'technical'
  }.txt`;
}

/**
 * Metacat's "Commentary font face" and "Commentary font size" menus (`gui.ss:567-593`):
 * serif / sans-serif / fancy, each plain, italic, bold or bold italic, at six sizes
 * (tiny 8, small 10, medium 12, large 18, larger 24, huge 34). Metacat's medium is its
 * default and so is this one; the sizes are pixel sizes relative to the panel's 13px.
 */
const FONT_FACES: Record<string, string> = {
  serif: 'Georgia, "Times New Roman", serif',
  'sans-serif': 'var(--font-sans)',
  fancy: '"Brush Script MT", "Snell Roundhand", cursive',
};
const FONT_SIZES: Record<string, number> = {
  tiny: 8,
  small: 10,
  medium: 13,
  large: 18,
  larger: 24,
  huge: 34,
};

interface CommentaryFont {
  face: string;
  size: string;
  bold: boolean;
  italic: boolean;
}

const DEFAULT_FONT: CommentaryFont = {
  face: 'sans-serif',
  size: 'medium',
  bold: false,
  italic: false,
};
const FONT_KEY = 'petacat.commentary.font';

function loadFont(): CommentaryFont {
  try {
    const raw = window.localStorage.getItem(FONT_KEY);
    if (raw) {
      const f = JSON.parse(raw);
      if (f && f.face in FONT_FACES && f.size in FONT_SIZES) {
        return { ...DEFAULT_FONT, ...f };
      }
    }
  } catch {
    // Storage can be unavailable; the default font is a fine answer.
  }
  return DEFAULT_FONT;
}

export function CommentaryPanel() {
  const [font, setFont] = useState<CommentaryFont>(loadFont);
  const changeFont = (patch: Partial<CommentaryFont>) => {
    const next = { ...font, ...patch };
    setFont(next);
    try {
      window.localStorage.setItem(FONT_KEY, JSON.stringify(next));
    } catch {
      // A per-viewer convenience only.
    }
  };
  const commentary = useRunStore((s) => s.commentary);
  const runId = useRunStore((s) => s.runId);
  const elizaMode = useRunStore((s) => s.elizaMode);

  const save = useCallback(() => {
    const text = typeof commentary === 'string' ? commentary : '';
    const blob = new Blob([text.endsWith('\n') ? text : `${text}\n`], {
      type: 'text/plain;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = commentaryFilename(runId, elizaMode);
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, [commentary, runId, elizaMode]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const prevText = useRef('');

  // Auto-scroll when commentary changes
  useEffect(() => {
    const currentText = typeof commentary === 'string' ? commentary : '';
    if (currentText !== prevText.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    prevText.current = currentText;
  }, [commentary]);

  const displayText = typeof commentary === 'string' ? commentary : '';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          alignItems: 'center',
          gap: 6,
          marginBottom: 2,
          flexWrap: 'wrap',
        }}
        className="text-xs text-muted"
      >
        <select
          aria-label="Commentary font face"
          value={font.face}
          onChange={(e) => changeFont({ face: e.target.value })}
          style={{ fontSize: 10 }}
        >
          {Object.keys(FONT_FACES).map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
        <select
          aria-label="Commentary font size"
          value={font.size}
          onChange={(e) => changeFont({ size: e.target.value })}
          style={{ fontSize: 10 }}
        >
          {Object.keys(FONT_SIZES).map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
        <label><input type="checkbox" checked={font.bold} onChange={(e) => changeFont({ bold: e.target.checked })} /> bold</label>
        <label><input type="checkbox" checked={font.italic} onChange={(e) => changeFont({ italic: e.target.checked })} /> italic</label>
        <button
          type="button"
          onClick={save}
          disabled={!displayText}
          title="Save the commentary shown (in the voice shown) to a text file."
          style={{ fontSize: 10, padding: '1px 6px' }}
        >
          Save commentary to file
        </button>
      </div>
      {/* Commentary text */}
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
        {displayText ? (
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              wordWrap: 'break-word',
              fontFamily: FONT_FACES[font.face],
              fontSize: FONT_SIZES[font.size],
              fontWeight: font.bold ? 700 : 400,
              fontStyle: font.italic ? 'italic' : 'normal',
              lineHeight: 1.6,
              color: 'var(--text-primary)',
              margin: 0,
            }}
          >
            {displayText}
          </pre>
        ) : (
          <div className="text-muted text-sm" style={{ padding: 8 }}>
            No commentary yet. Start a run to see commentary.
          </div>
        )}
      </div>
    </div>
  );
}
