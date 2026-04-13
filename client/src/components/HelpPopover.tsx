// ---------------------------------------------------------------------------
// HelpPopover -- Floating panel for context-sensitive help
// ---------------------------------------------------------------------------
//
// Can be used in two ways:
// 1. Via the useHelp() hook (existing pattern) -- automatically shows help
//    when helpContent is non-null.
// 2. Via direct props (title, description, metadata) for simple use cases.
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useRef } from 'react';
import { useHelp } from '@/hooks/useHelp';

export interface HelpPopoverProps {
  /** Override: if provided, show this title instead of hook content. */
  title?: string;
  /** Override: if provided, show this description instead of hook content. */
  description?: string;
  /** Override: optional metadata key-value pairs. */
  metadata?: Record<string, string | number>;
  /** Override: control visibility externally. */
  open?: boolean;
  /** Override: external close handler. */
  onClose?: () => void;
}

export function HelpPopover(props: HelpPopoverProps) {
  const { helpContent, isLoading, hideHelp } = useHelp();
  const popoverRef = useRef<HTMLDivElement>(null);

  // Determine what to show: external props take priority over hook content
  const hasExternalContent = props.title !== undefined || props.description !== undefined;
  const isOpen = hasExternalContent ? (props.open ?? false) : (helpContent !== null || isLoading);
  const closeHandler = hasExternalContent ? (props.onClose ?? hideHelp) : hideHelp;

  // Derived display values
  const title = hasExternalContent
    ? (props.title ?? '')
    : (helpContent?.name ?? 'Help');

  let description = '';
  let metadata: Record<string, string | number> = {};

  if (hasExternalContent) {
    description = props.description ?? '';
    metadata = props.metadata ?? {};
  } else if (helpContent) {
    description = helpContent.description ?? '';
    if (helpContent.type === 'concept') {
      metadata = {
        'Short name': helpContent.short_name,
        'Conceptual depth': helpContent.conceptual_depth,
      };
    } else if (helpContent.type === 'codelet') {
      metadata = {
        Family: helpContent.family,
        Phase: helpContent.phase,
        'Default urgency': helpContent.default_urgency,
      };
      if (helpContent.source_file) {
        metadata['Source'] = `${helpContent.source_file}:${helpContent.source_line}`;
      }
    } else if (helpContent.type === 'component') {
      // Related glossary concepts from help_topics.{locale}.json metadata
      const related = helpContent.metadata?.key_concepts;
      if (Array.isArray(related) && related.length > 0) {
        metadata = { 'Related concepts': (related as string[]).join(', ') };
      }
    }
  }

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeHandler();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, closeHandler]);

  // Close on click outside
  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        closeHandler();
      }
    },
    [closeHandler],
  );

  if (!isOpen) return null;

  return (
    <div
      onClick={handleBackdropClick}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 2000,
        background: 'rgba(0, 0, 0, 0.2)',
      }}
    >
      <div
        ref={popoverRef}
        style={{
          position: 'fixed',
          top: 60,
          right: 20,
          width: 360,
          maxHeight: '70vh',
          background: 'var(--bg-secondary)',
          border: '1px solid var(--text-accent)',
          borderRadius: 6,
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          zIndex: 2001,
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '8px 12px',
            background: 'var(--bg-panel)',
            borderBottom: '1px solid var(--border)',
            flexShrink: 0,
          }}
        >
          <span
            className="text-sm"
            style={{
              fontWeight: 600,
              color: 'var(--text-accent)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            {isLoading ? 'Loading...' : title}
          </span>
          <button
            onClick={closeHandler}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: 16,
              padding: '0 4px',
              lineHeight: 1,
            }}
            aria-label="Close"
          >
            x
          </button>
        </div>

        {/* Content */}
        <div
          style={{
            padding: 12,
            overflow: 'auto',
            flex: 1,
            fontSize: 13,
          }}
        >
          {isLoading ? (
            <div className="text-muted">Loading...</div>
          ) : (
            <>
              {/* Description — preserve paragraph breaks from JSON */}
              {description && (
                <div
                  style={{
                    lineHeight: 1.6,
                    color: 'var(--text-primary)',
                    marginBottom: Object.keys(metadata).length > 0 ? 12 : 0,
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {description}
                </div>
              )}

              {/* Metadata table */}
              {Object.keys(metadata).length > 0 && (
                <div
                  style={{
                    borderTop: '1px solid var(--border)',
                    paddingTop: 8,
                  }}
                >
                  {Object.entries(metadata).map(([key, value]) => (
                    <div
                      key={key}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        gap: 12,
                        fontSize: 11,
                        lineHeight: 1.8,
                      }}
                    >
                      <span style={{ color: 'var(--text-secondary)' }}>{key}</span>
                      <span className="mono" style={{ color: 'var(--text-primary)' }}>
                        {String(value)}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Execute body (for codelet help) */}
              {!hasExternalContent &&
                helpContent?.type === 'codelet' &&
                helpContent.execute_body && (
                  <div style={{ marginTop: 8 }}>
                    <div className="text-xs text-muted mb-1">Execute body:</div>
                    <pre
                      style={{
                        background: 'var(--bg-card)',
                        padding: 8,
                        borderRadius: 3,
                        fontSize: 10,
                        overflow: 'auto',
                        maxHeight: 200,
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      {helpContent.execute_body}
                    </pre>
                  </div>
                )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
