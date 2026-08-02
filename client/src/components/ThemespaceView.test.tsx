/**
 * The Themespace grid is clampable — MetaCat's theme windows are mouse-driven.
 *
 * `theme-graphics.ss:35-63`: a left-press pins a theme to +100 and a right-press to
 * -100, each first zeroing the rest of that dimension's cluster, and pressing a theme
 * that already holds that value clears it. That is the user's only direct handle on
 * *negative* thematic pressure — saying "not this idea" and watching the program
 * reorganise — and it is how the dissertation produced Figures 4.5 and 4.6.
 *
 * These tests drive `ThemespaceGrid`, the presentational half, so they assert the
 * gesture semantics without standing up a run. The same split is what lets the review
 * surfaces render a *recorded* Themespace: they pass no `onClamp`, and the grid must
 * then be inert.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ThemespaceGrid } from './ThemespaceView';
import type { ClusterState, ThemespaceState, ThemeState } from '@/types';

function theme(relation: string, activation: number): ThemeState {
  return {
    dimension: 'plato-string-position-category',
    relation,
    activation,
    frozen: false,
    dominant: false,
  };
}

const CLUSTER: ClusterState = {
  theme_type: 'vertical_bridge',
  dimension: 'plato-string-position-category',
  frozen: false,
  dominant_relation: null,
  themes: [theme('identity', 0), theme('opposite', 0)],
};

function themespace(clusters: ClusterState[] = [CLUSTER]): ThemespaceState {
  return {
    clusters,
    active_theme_types: [],
    possible_theme_types: ['vertical_bridge'],
    thematic_pressure: false,
    dominant_theme_margin: 90,
  } as ThemespaceState;
}

/** The clamp controls, in theme order within the rendered cluster. */
function buttons(label: string): HTMLButtonElement[] {
  return screen.getAllByRole('button', { name: label }) as HTMLButtonElement[];
}

describe('ThemespaceGrid — clamping a theme', () => {
  it('clamps to +100 from a labelled button', () => {
    const onClamp = vi.fn();
    render(<ThemespaceGrid themespace={themespace()} onClamp={onClamp} />);

    fireEvent.click(buttons('Clamp +100')[1]);

    expect(onClamp).toHaveBeenCalledTimes(1);
    const [clamped, cluster, activation] = onClamp.mock.calls[0];
    expect(clamped.relation).toBe('opposite');
    expect(cluster.dimension).toBe('plato-string-position-category');
    expect(activation).toBe(100);
  });

  it('clamps to -100 from its own button', () => {
    const onClamp = vi.fn();
    render(<ThemespaceGrid themespace={themespace()} onClamp={onClamp} />);

    // Negative thematic pressure is the point: a negatively-activated theme promotes
    // structures *incompatible* with itself (§2.4.2). It gets a control of its own
    // rather than a right-click, which nothing would announce.
    fireEvent.click(buttons('Clamp -100')[1]);

    expect(onClamp).toHaveBeenCalledWith(
      expect.objectContaining({ relation: 'opposite' }),
      expect.anything(),
      -100,
    );
  });

  it('explains what each control does on hover', () => {
    render(<ThemespaceGrid themespace={themespace()} onClamp={vi.fn()} />);

    expect(buttons('Clamp +100')[0].title).toMatch(/positive thematic pressure/i);
    expect(buttons('Clamp -100')[0].title).toMatch(/negative thematic pressure/i);
    // The negative control is the manual counterpart of jootsing, and says so.
    expect(buttons('Clamp -100')[0].title).toMatch(/jootsing/i);
  });

  it('clears a theme already held at the value the button would set', () => {
    const onClamp = vi.fn();
    const held: ClusterState = {
      ...CLUSTER,
      themes: [theme('identity', 0), theme('opposite', 100)],
    };
    render(<ThemespaceGrid themespace={themespace([held])} onClamp={onClamp} />);

    const control = buttons('Clamp +100')[1];
    expect(control.title).toMatch(/clear/i);
    fireEvent.click(control);

    expect(onClamp).toHaveBeenCalledWith(expect.anything(), expect.anything(), 0);
  });

  it('offers no controls without a handler, so recorded Themespaces cannot be steered', () => {
    render(<ThemespaceGrid themespace={themespace()} />);

    expect(screen.queryAllByRole('button', { name: /Clamp/ })).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Releasing clamps — MetaCat's "Undo last clamp" (`gui.ss:604-606`)
// ---------------------------------------------------------------------------

describe('ThemespaceGrid — releasing thematic pressure', () => {
  it('offers the release only while pressure is on', () => {
    const release = vi.fn()

    const { rerender } = render(
      <ThemespaceGrid
        themespace={{ ...themespace(), thematic_pressure: false }}
        onRelease={release}
      />,
    )
    expect(screen.queryByRole('button', { name: /Release clamps/i })).toBeNull()

    rerender(
      <ThemespaceGrid
        themespace={{ ...themespace(), thematic_pressure: true, active_theme_types: ['vertical_bridge'] }}
        onRelease={release}
      />,
    )
    expect(screen.getByRole('button', { name: /Release clamps/i })).toBeTruthy()
  })

  it('releases every clamp when pressed', () => {
    const release = vi.fn()
    render(
      <ThemespaceGrid
        themespace={{ ...themespace(), thematic_pressure: true, active_theme_types: ['vertical_bridge'] }}
        onRelease={release}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Release clamps/i }))

    expect(release).toHaveBeenCalledTimes(1)
  })

  it('withholds the release from a recorded run', () => {
    render(<ThemespaceGrid themespace={{ ...themespace(), thematic_pressure: true, active_theme_types: ['vertical_bridge'] }} />)

    expect(screen.queryByRole('button', { name: /Release clamps/i })).toBeNull()
  })
})
