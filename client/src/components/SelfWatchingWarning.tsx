// ---------------------------------------------------------------------------
// SelfWatchingWarning -- "Warning: Self-watching is disabled"
// ---------------------------------------------------------------------------
//
// Metacat shows this in red at the top of its control panel whenever self-watching is
// off (`gui.ss:444-448`, shown and hidden at `gui.ss:613,620`). Self-watching changes
// how the program behaves -- no Themespace, no progress-watchers, no jootsing -- so a
// run without it should not look like an ordinary one.
//
// Here self-watching is the `self_watching_enabled_default` run parameter, set before a
// run starts; the warning therefore appears wherever that choice is made or shown:
// next to the engine parameters (for the next run) and on the loaded run's card (for the
// run on screen).
// ---------------------------------------------------------------------------

import { useParameterCatalogue } from '@/hooks/useParameterCatalogue';
import { useRunStore } from '@/store/runStore';

export const SELF_WATCHING_PARAMETER = 'self_watching_enabled_default';

/** Is self-watching off, given a set of overrides over the catalogue's default? */
export function useSelfWatchingDisabled(which: 'next' | 'loaded'): boolean {
  const { specs } = useParameterCatalogue();
  const overrides = useRunStore((s) =>
    which === 'next' ? s.parameterOverrides : s.runParameterOverrides,
  );
  const spec = specs.find((p) => p.name === SELF_WATCHING_PARAMETER);
  const value = overrides[SELF_WATCHING_PARAMETER] ?? spec?.default;
  return value === false;
}

export function SelfWatchingWarning({ which }: { which: 'next' | 'loaded' }) {
  const disabled = useSelfWatchingDisabled(which);
  if (!disabled) return null;
  return (
    <div
      role="alert"
      data-testid={`self-watching-warning-${which}`}
      style={{
        color: '#d32f2f',
        fontWeight: 700,
        fontSize: 12,
        padding: '2px 0',
      }}
      title={
        which === 'next'
          ? 'The next run will start with self-watching off: no Themespace, ' +
            'progress-watchers or jootsers.'
          : 'This run was started with self-watching off.'
      }
    >
      Warning: Self-watching is disabled
    </div>
  );
}
