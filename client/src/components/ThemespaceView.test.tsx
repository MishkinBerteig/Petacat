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
    expect(screen.queryByRole('button', { name: /Undo last clamp/i })).toBeNull()

    rerender(
      <ThemespaceGrid
        themespace={{ ...themespace(), thematic_pressure: true, active_theme_types: ['vertical_bridge'] }}
        onRelease={release}
      />,
    )
    expect(screen.getByRole('button', { name: /Undo last clamp/i })).toBeTruthy()
  })

  it('undoes the last clamp when pressed', () => {
    const release = vi.fn()
    render(
      <ThemespaceGrid
        themespace={{ ...themespace(), thematic_pressure: true, active_theme_types: ['vertical_bridge'] }}
        onRelease={release}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Undo last clamp/i }))

    expect(release).toHaveBeenCalledTimes(1)
  })

  it('withholds the release from a recorded run', () => {
    render(<ThemespaceGrid themespace={{ ...themespace(), thematic_pressure: true, active_theme_types: ['vertical_bridge'] }} />)

    expect(screen.queryByRole('button', { name: /Undo last clamp/i })).toBeNull()
  })
})

describe('ThemespaceGrid — Metacat\'s dimension and relation names', () => {
  const labelled = (): ThemespaceState => ({
    ...themespace(),
    dimension_labels: {
      'plato-string-position-category': { name: 'String Position', abbreviation: 'String Pos.' },
    },
    relation_labels: { identity: 'iden', opposite: 'opp' },
  })

  it('names the dimension and its relations as theme-graphics.ss does', () => {
    const topCluster = { ...CLUSTER, theme_type: 'top_bridge' }
    render(<ThemespaceGrid themespace={{ ...labelled(), clusters: [topCluster], possible_theme_types: ['top_bridge'] }} />)
    expect(screen.getByText('String Position')).toBeTruthy()
    expect(screen.getByText('iden')).toBeTruthy()
    expect(screen.getByText('opp')).toBeTruthy()
  })

  it('abbreviates in the narrow vertical-bridge column, as Metacat does', () => {
    render(<ThemespaceGrid themespace={labelled()} />)
    // The fixture cluster is a vertical bridge, so the abbreviation is what shows
    // there; the full name is for the wider top and bottom columns.
    expect(screen.queryByText('String Pos.')).toBeTruthy()
  })

  it('holds no domain names of its own: without served labels it shows the raw ones', () => {
    render(<ThemespaceGrid themespace={themespace()} />)
    expect(screen.queryByText('StrPos')).toBeNull()
    expect(screen.getByText('string-position-category')).toBeTruthy()
    expect(screen.getByText('identity')).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// Theme-edit mode — Metacat's "Clamp theme pattern" (`gui.ss:845-926`)
// ---------------------------------------------------------------------------

describe('ThemespaceGrid — theme-edit mode', () => {
  it('says "Click to select themes" in a window that has not been claimed', () => {
    const { rerender } = render(
      <ThemespaceGrid themespace={themespace()} onClamp={vi.fn()} editing={{ edited: [] }} />,
    );
    expect(screen.getByText('Click to select themes')).toBeTruthy();

    rerender(
      <ThemespaceGrid
        themespace={themespace()}
        onClamp={vi.fn()}
        editing={{ edited: ['vertical_bridge'] }}
      />,
    );
    expect(screen.queryByText('Click to select themes')).toBeNull();
  });

  it('selects +100 on a click and -100 on a shift-click or right-click', () => {
    const onClamp = vi.fn();
    render(
      <ThemespaceGrid
        themespace={themespace()}
        onClamp={onClamp}
        editing={{ edited: ['vertical_bridge'] }}
      />,
    );
    const rows = screen.getAllByTitle(/^(identity|opposite): /);

    fireEvent.click(rows[0]);
    expect(onClamp).toHaveBeenLastCalledWith(expect.anything(), expect.anything(), 100);

    fireEvent.click(rows[0], { shiftKey: true });
    expect(onClamp).toHaveBeenLastCalledWith(expect.anything(), expect.anything(), -100);

    fireEvent.contextMenu(rows[1]);
    expect(onClamp).toHaveBeenLastCalledWith(expect.anything(), expect.anything(), -100);
  });

  it('leaves clicking inert outside edit mode, where only the buttons clamp', () => {
    const onClamp = vi.fn();
    render(<ThemespaceGrid themespace={themespace()} onClamp={onClamp} />);

    fireEvent.click(screen.getAllByTitle(/^(identity|opposite): /)[0]);

    expect(onClamp).not.toHaveBeenCalled();
  });
});
