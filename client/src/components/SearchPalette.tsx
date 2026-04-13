// ---------------------------------------------------------------------------
// SearchPalette -- Cmd+K / Ctrl+K search overlay
// ---------------------------------------------------------------------------
//
// A modal search palette that queries /api/docs/search and displays categorized
// results.  Clicking a result triggers the help system (useHelp) to show details
// in the HelpPopover.
// ---------------------------------------------------------------------------

import { useState, useEffect, useRef, useCallback } from 'react';
import { searchDocs } from '@/api/client';
import { useHelp } from '@/hooks/useHelp';
import type { HelpType } from '@/hooks/useHelp';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SearchResult {
  type: string;       // e.g. "concept", "codelet", "component", "glossary"
  name: string;
  description: string;
}

export interface SearchPaletteProps {
  open: boolean;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Category labels for display
// ---------------------------------------------------------------------------

const CATEGORY_LABELS: Record<string, string> = {
  concept: 'Slipnet Nodes',
  codelet: 'Codelet Types',
  component: 'Components',
  glossary: 'Glossary',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SearchPalette({ open, onClose }: SearchPaletteProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { showHelp } = useHelp();

  // Focus the input when the palette opens
  useEffect(() => {
    if (open) {
      setQuery('');
      setResults([]);
      setSelectedIndex(0);
      // Slight delay so the DOM has rendered the input
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Debounced search
  const performSearch = useCallback((q: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (q.trim().length === 0) {
      setResults([]);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const data = await searchDocs(q.trim());
        // The API may return items with { type, name, description }
        setResults(
          (data ?? []).map((item: any) => ({
            type: item.type ?? 'unknown',
            name: item.name ?? '',
            description: item.description ?? '',
          })),
        );
      } catch {
        setResults([]);
      } finally {
        setIsLoading(false);
      }
    }, 300);
  }, []);

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setQuery(value);
    setSelectedIndex(0);
    performSearch(value);
  };

  // Open help for a result
  const selectResult = useCallback(
    (result: SearchResult) => {
      const helpType: HelpType =
        result.type === 'concept' || result.type === 'codelet' || result.type === 'component'
          ? result.type
          : 'component'; // fallback for glossary or unknown types
      showHelp(helpType, result.name);
      onClose();
    },
    [showHelp, onClose],
  );

  // Keyboard navigation within the palette
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => Math.min(prev + 1, results.length - 1));
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => Math.max(prev - 1, 0));
      return;
    }
    if (e.key === 'Enter' && results.length > 0) {
      e.preventDefault();
      selectResult(results[selectedIndex]);
    }
  };

  // Group results by category for display
  const grouped = results.reduce<Record<string, SearchResult[]>>((acc, r) => {
    const cat = r.type || 'other';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(r);
    return acc;
  }, {});

  if (!open) return null;

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 3000,
        background: 'rgba(0, 0, 0, 0.45)',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'flex-start',
        paddingTop: 80,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
        style={{
          width: 480,
          maxHeight: '60vh',
          background: 'var(--bg-secondary, #1e1e1e)',
          border: '1px solid var(--text-accent, #61afef)',
          borderRadius: 8,
          boxShadow: '0 12px 48px rgba(0,0,0,0.6)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* Search input */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '8px 12px',
            borderBottom: '1px solid var(--border, #444)',
            gap: 8,
          }}
        >
          <span style={{ color: 'var(--text-secondary, #999)', fontSize: 14 }}>
            /
          </span>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={handleInputChange}
            placeholder="Search concepts, codelets, components..."
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--text-primary, #ddd)',
              fontFamily: 'var(--font-mono)',
              fontSize: 14,
            }}
          />
          {isLoading && (
            <span style={{ color: 'var(--text-muted, #666)', fontSize: 11 }}>
              ...
            </span>
          )}
        </div>

        {/* Results */}
        <div style={{ overflow: 'auto', flex: 1 }}>
          {query.trim().length > 0 && !isLoading && results.length === 0 && (
            <div
              style={{
                padding: '16px 12px',
                color: 'var(--text-muted, #666)',
                fontSize: 13,
                textAlign: 'center',
              }}
            >
              No results found
            </div>
          )}

          {Object.entries(grouped).map(([category, items]) => (
            <div key={category}>
              {/* Category header */}
              <div
                style={{
                  padding: '6px 12px 2px',
                  fontSize: 10,
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  color: 'var(--text-muted, #666)',
                }}
              >
                {CATEGORY_LABELS[category] ?? category}
              </div>

              {/* Items */}
              {items.map((item) => {
                const globalIdx = results.indexOf(item);
                const isSelected = globalIdx === selectedIndex;
                return (
                  <div
                    key={`${item.type}-${item.name}`}
                    onClick={() => selectResult(item)}
                    onMouseEnter={() => setSelectedIndex(globalIdx)}
                    style={{
                      padding: '6px 12px',
                      cursor: 'pointer',
                      background: isSelected
                        ? 'var(--bg-card, #2a2a2a)'
                        : 'transparent',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 2,
                    }}
                  >
                    <span
                      style={{
                        fontSize: 13,
                        fontFamily: 'var(--font-mono)',
                        color: isSelected
                          ? 'var(--text-accent, #61afef)'
                          : 'var(--text-primary, #ddd)',
                      }}
                    >
                      {item.name}
                    </span>
                    {item.description && (
                      <span
                        style={{
                          fontSize: 11,
                          color: 'var(--text-secondary, #999)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {item.description}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Footer hint */}
        <div
          style={{
            padding: '6px 12px',
            borderTop: '1px solid var(--border, #444)',
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 10,
            color: 'var(--text-muted, #666)',
          }}
        >
          <span>Up/Down to navigate, Enter to select</span>
          <span>Esc to close</span>
        </div>
      </div>
    </div>
  );
}
