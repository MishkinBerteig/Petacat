// ---------------------------------------------------------------------------
// Petacat — Context-sensitive help hook (shared-state)
// ---------------------------------------------------------------------------
//
// Provides on-demand help content for slipnet concepts, codelet types, and
// architecture components by calling the /api/docs/* endpoints.
//
// Implementation note: this hook is backed by a Zustand store so that every
// consumer (the PanelHelpButton that *calls* showHelp and the HelpPopover that
// *reads* helpContent) subscribes to the SAME state. If this were a plain
// useState-based hook, each caller would get its own independent state and
// clicks on the button would never reach the popover.
//
// The single source of truth for all help text is `seed_data/help_topics.en.json`
// (plus future locale files). That JSON is seeded into the `help_topics` table
// on every backend startup (idempotent upsert). The frontend fetches from the
// API and never hardcodes help content.
//
// To add or change a help topic: edit `seed_data/help_topics.{locale}.json`,
// then restart the backend. To regenerate derived documentation (HELP.md and
// the TypeScript key constants), run `scripts/generate_help_docs.py`.
// ---------------------------------------------------------------------------

import { create } from 'zustand';
import {
  getConceptHelp,
  getCodeletHelp,
  getComponentHelp,
} from '@/api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type HelpType = 'concept' | 'codelet' | 'component';

export interface ConceptHelpContent {
  type: 'concept';
  name: string;
  short_name: string;
  conceptual_depth: number;
  description: string;
}

export interface CodeletHelpContent {
  type: 'codelet';
  name: string;
  family: string;
  phase: string;
  default_urgency: number;
  description: string;
  source_file: string;
  source_line: number;
  execute_body: string;
}

export interface ComponentHelpContent {
  type: 'component';
  name: string;
  topic_key: string;
  short_desc: string;
  description: string;
  metadata: Record<string, unknown>;
}

export type HelpContent =
  | ConceptHelpContent
  | CodeletHelpContent
  | ComponentHelpContent;

export interface UseHelpReturn {
  helpContent: HelpContent | null;
  isLoading: boolean;
  error: string | null;
  showHelp: (type: HelpType, name: string) => void;
  hideHelp: () => void;
}

// ---------------------------------------------------------------------------
// Shared store
// ---------------------------------------------------------------------------

interface HelpStoreState {
  helpContent: HelpContent | null;
  isLoading: boolean;
  error: string | null;
  showHelp: (type: HelpType, name: string) => void;
  hideHelp: () => void;
}

export const useHelpStore = create<HelpStoreState>((set) => ({
  helpContent: null,
  isLoading: false,
  error: null,

  hideHelp: () => set({ helpContent: null, error: null, isLoading: false }),

  showHelp: (type: HelpType, name: string) => {
    set({ error: null, isLoading: true });

    const fetchHelp = async (): Promise<void> => {
      try {
        if (type === 'concept') {
          const data = await getConceptHelp(name);
          set({
            helpContent: {
              type: 'concept',
              name: data.name,
              short_name: data.short_name,
              conceptual_depth: data.conceptual_depth,
              description: data.description,
            },
            isLoading: false,
            error: null,
          });
        } else if (type === 'codelet') {
          const data = await getCodeletHelp(name);
          set({
            helpContent: {
              type: 'codelet',
              name: data.name,
              family: data.family,
              phase: data.phase,
              default_urgency: data.default_urgency,
              description: data.description,
              source_file: data.source_file,
              source_line: data.source_line,
              execute_body: data.execute_body,
            },
            isLoading: false,
            error: null,
          });
        } else if (type === 'component') {
          const data = await getComponentHelp(name);
          set({
            helpContent: {
              type: 'component',
              name: data.name,
              topic_key: data.topic_key,
              short_desc: data.short_desc,
              description: data.description,
              metadata: data.metadata ?? {},
            },
            isLoading: false,
            error: null,
          });
        }
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : `Failed to load ${type} help`;
        set({ error: message, helpContent: null, isLoading: false });
      }
    };

    void fetchHelp();
  },
}));

// ---------------------------------------------------------------------------
// Hook wrapper
// ---------------------------------------------------------------------------

export function useHelp(): UseHelpReturn {
  const helpContent = useHelpStore((s) => s.helpContent);
  const isLoading = useHelpStore((s) => s.isLoading);
  const error = useHelpStore((s) => s.error);
  const showHelp = useHelpStore((s) => s.showHelp);
  const hideHelp = useHelpStore((s) => s.hideHelp);

  return { helpContent, isLoading, error, showHelp, hideHelp };
}
