// ---------------------------------------------------------------------------
// ModeSwitch -- the persistent switch between Metacat Mode and Training Mode
// ---------------------------------------------------------------------------
//
// Petacat has two modes, always written as proper names:
//   Metacat Mode  -- the v1.2 features exactly as they are: the dashboard's runs, Run
//                    History, Review, the one-problem Swarm, the Admin view and
//                    Configuration, and Metacat's own Episodic Memory.
//   Training Mode -- every extension since v1.2: Trainings, each with its own episode
//                    memory.
//
// Run mode (single-threaded or multi-core) is orthogonal to both and is not a third
// option here. The switch is shown in every view and names the current mode, so there
// is never a doubt about which one a screen belongs to.
//
// Colours come from the theme tokens only (no literal colours), so the badge follows
// whichever theme the page is using. Each mode also differs in its text and its
// position in the pair, never by colour alone.
// ---------------------------------------------------------------------------

import type { CSSProperties } from 'react';
import { useHelp } from '@/hooks/useHelp';
import type { ComponentHelpKey } from '@/constants/helpTopics';
import type { AppView } from '@/components/HamburgerMenu';

export type AppMode = 'metacat' | 'training';

export const MODE_LABELS: Record<AppMode, string> = {
  metacat: 'Metacat Mode',
  training: 'Training Mode',
};

export const MODE_TOOLTIPS: Record<AppMode, string> = {
  metacat:
    'Metacat Mode: Petacat exactly as v1.2 — runs, Run History, Review, the Swarm, Admin and '
    + "Configuration, and Metacat's own Episodic Memory (Metacat-Mode learning).",
  training:
    'Training Mode: Trainings — named episodes of many problems, each with its own episode '
    + 'memory. Nothing here reads or changes Metacat Mode.',
};

/** The accent each mode wears: a theme token, so light and dark themes both work. */
export const MODE_ACCENTS: Record<AppMode, string> = {
  metacat: 'var(--text-accent)',
  training: 'var(--accent)',
};

/** The help topic that explains the two modes. */
export const MODES_HELP_KEY: ComponentHelpKey = 'modes';

/** Which mode a view belongs to. Everything but the Training view is Metacat Mode's. */
export function modeOfView(view: AppView): AppMode {
  return view === 'training' ? 'training' : 'metacat';
}

interface Props {
  view: AppView;
  onSelectView: (view: AppView) => void;
  disabled?: boolean;
}

const groupStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 0,
  border: '1px solid var(--border)',
  borderRadius: 5,
  overflow: 'hidden',
};

export function ModeSwitch({ view, onSelectView, disabled = false }: Props) {
  const { showHelp } = useHelp();
  const current = modeOfView(view);

  const choose = (mode: AppMode) => {
    if (disabled || mode === current) return;
    onSelectView(mode === 'training' ? 'training' : 'dashboard');
  };

  return (
    <div
      role="group"
      aria-label="Mode"
      data-testid="mode-switch"
      data-mode={current}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
    >
      <div style={groupStyle}>
        {(['metacat', 'training'] as const).map((mode) => {
          const active = mode === current;
          return (
            <button
              key={mode}
              type="button"
              aria-pressed={active}
              aria-current={active ? 'true' : undefined}
              title={MODE_TOOLTIPS[mode]}
              disabled={disabled && !active}
              onClick={() => choose(mode)}
              data-testid={`mode-${mode}`}
              style={{
                border: 'none',
                borderRadius: 0,
                padding: '3px 10px',
                fontSize: 12,
                fontFamily: 'var(--font-mono)',
                fontWeight: active ? 700 : 400,
                cursor: active ? 'default' : disabled ? 'not-allowed' : 'pointer',
                opacity: disabled && !active ? 0.4 : 1,
                // Active: the mode's accent as the fill, with the page background
                // as the text so the pair stays legible in either theme.
                background: active ? MODE_ACCENTS[mode] : 'transparent',
                color: active ? 'var(--bg-primary)' : 'var(--text-primary)',
              }}
            >
              {MODE_LABELS[mode]}
            </button>
          );
        })}
      </div>
      <button
        type="button"
        onClick={() => showHelp('component', MODES_HELP_KEY)}
        title="Show help for the two modes"
        aria-label="Show help for the modes"
        style={{
          background: 'none',
          border: '1px solid var(--border, #444)',
          borderRadius: 4,
          color: 'var(--text-secondary, #999)',
          cursor: 'pointer',
          fontSize: 11,
          lineHeight: 1,
          padding: '1px 5px',
          fontFamily: 'var(--font-mono)',
        }}
      >
        ?
      </button>
    </div>
  );
}
