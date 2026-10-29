/**
 * Metacat's clamp and self-watching menu items (`gui.ss:594-626`, `:881-894`).
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ClampControls, themeEditInstructions } from './ClampControls';
import { useRunStore } from '@/store/runStore';

const api = vi.hoisted(() => ({
  undoLastClamp: vi.fn(async () => ({ undone: true, progress: 40 })),
  setSelfWatching: vi.fn(async (_id: number, enabled: boolean) => ({
    self_watching_enabled: enabled,
  })),
  clampThemePattern: vi.fn(async () => undefined),
}));

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  ...api,
  getThemespace: vi.fn(async () => ({
    clusters: [], possible_theme_types: [], active_theme_types: [],
    thematic_pressure: false, dominant_theme_margin: 90,
  })),
  getSlipnet: vi.fn(async () => null),
  getCoderack: vi.fn(async () => null),
  getCommentary: vi.fn(async () => ''),
  getTrace: vi.fn(async () => []),
}));

vi.mock('@/hooks/useParameterCatalogue', () => ({
  useParameterCatalogue: () => ({
    specs: [{ name: 'self_watching_enabled_default', kind: 'bool', default: true }],
  }),
}));

const ORIGINAL = useRunStore.getState();

beforeEach(() => {
  vi.clearAllMocks();
  useRunStore.setState({ ...ORIGINAL, runId: 7, runParameterOverrides: {}, themeEdit: null }, true);
});

describe('ClampControls', () => {
  it('undoes only the last clamp', async () => {
    render(<ClampControls />);
    fireEvent.click(screen.getByRole('button', { name: 'Undo last clamp' }));
    await waitFor(() => expect(api.undoLastClamp).toHaveBeenCalledWith(7));
  });

  it('switches self-watching off in mid-run and shows the warning', async () => {
    render(<ClampControls />);
    expect(screen.queryByTestId('self-watching-warning-loaded')).toBeNull();

    fireEvent.click(screen.getByLabelText('Self-watching mode'));

    await waitFor(() => expect(api.setSelfWatching).toHaveBeenCalledWith(7, false));
    await waitFor(() =>
      expect(screen.getByTestId('self-watching-warning-loaded')).toBeTruthy(),
    );
    // The clamp items are disabled while self-watching is off.
    expect((screen.getByRole('button', { name: 'Undo last clamp' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Clamp theme pattern' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('opens the instructions dialog and clamps the chosen themes together', async () => {
    render(<ClampControls />);
    fireEvent.click(screen.getByRole('button', { name: 'Clamp theme pattern' }));
    expect(screen.getByTestId('theme-edit-dialog').textContent).toContain(
      'To clamp a theme-pattern, click on one or more theme windows',
    );

    const store = useRunStore.getState();
    store.editThemeType('top_bridge');
    store.selectTheme('top_bridge', 'plato-letter-category', 'successor', 100);
    store.selectTheme('top_bridge', 'plato-direction-category', 'opposite', -100);
    store.editThemeType('vertical_bridge');
    store.selectTheme('vertical_bridge', 'plato-string-position-category', 'identity', 100);
    // A theme already holding the value is unselected.
    store.selectTheme('top_bridge', 'plato-direction-category', 'opposite', -100);

    fireEvent.click(screen.getByRole('button', { name: 'Clamp Themes' }));

    await waitFor(() => expect(api.clampThemePattern).toHaveBeenCalledTimes(1));
    expect(api.clampThemePattern).toHaveBeenCalledWith(7, [
      {
        type: 'top_bridge',
        themes: [{ dimension: 'plato-letter-category', relation: 'successor', activation: 100 }],
      },
      {
        type: 'vertical_bridge',
        themes: [
          { dimension: 'plato-string-position-category', relation: 'identity', activation: 100 },
        ],
      },
    ]);
    expect(useRunStore.getState().themeEdit).toBeNull();
  });

  it('changes nothing on Cancel', () => {
    render(<ClampControls />);
    fireEvent.click(screen.getByRole('button', { name: 'Clamp theme pattern' }));
    useRunStore.getState().editThemeType('top_bridge');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(api.clampThemePattern).not.toHaveBeenCalled();
    expect(useRunStore.getState().themeEdit).toBeNull();
  });

  it('words the click instructions for the platform, as gui.ss does', () => {
    expect(themeEditInstructions(false)[1]).toContain('Right-clicking selects maximum negative activation');
    expect(themeEditInstructions(true)[1]).toContain('Shift-clicking selects maximum negative activation');
  });
});
