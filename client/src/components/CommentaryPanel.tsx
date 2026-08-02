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

import { useRef, useEffect } from 'react';
import { useRunStore } from '@/store/runStore';

export function CommentaryPanel() {
  const commentary = useRunStore((s) => s.commentary);

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
              fontFamily: 'var(--font-sans)',
              fontSize: 13,
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
