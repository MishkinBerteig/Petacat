// ---------------------------------------------------------------------------
// Petacat — the run-parameter catalogue, fetched once and shared
// ---------------------------------------------------------------------------
//
// Two components need the same answer and must not disagree about it: the panel
// that renders a control per parameter, and the run controls, which have to refuse
// to start a run whose parameters the server would reject. Fetching it twice would
// mean a moment where one of them has bounds and the other does not.
//
// Backed by a Zustand store for the same reason `useHelp` is: a plain `useState`
// hook would give each caller its own copy, and the run button would be validating
// against an empty catalogue.
//
// The catalogue is served rather than hardcoded here on purpose. Its minima and
// maxima are the ones `server/engine/parameters.py` validates against, and a second
// copy in the client would drift into offering values the API refuses.
// ---------------------------------------------------------------------------

import { useEffect } from 'react';
import { create } from 'zustand';
import { getParameterCatalogue, describeApiError } from '@/api/client';
import type { RunParameterSpec, RunParameterValue } from '@/types';

interface CatalogueState {
  specs: RunParameterSpec[];
  isLoading: boolean;
  error: string | null;
  /** Fetch once per page; repeated calls while loaded are no-ops. */
  load: () => void;
}

export const useParameterCatalogueStore = create<CatalogueState>((set, get) => ({
  specs: [],
  isLoading: false,
  error: null,

  load: () => {
    const { specs, isLoading } = get();
    if (specs.length > 0 || isLoading) return;
    set({ isLoading: true, error: null });
    getParameterCatalogue()
      .then((s) => set({ specs: s, isLoading: false, error: null }))
      .catch((e: unknown) =>
        set({
          specs: [],
          isLoading: false,
          // The form has no bounds to offer without this, so the panel says what
          // happened in the same words the rest of the app uses.
          error: describeApiError(e, 'load the run parameters'),
        }),
      );
  },
}));

export function useParameterCatalogue(): CatalogueState {
  const specs = useParameterCatalogueStore((s) => s.specs);
  const isLoading = useParameterCatalogueStore((s) => s.isLoading);
  const error = useParameterCatalogueStore((s) => s.error);
  const load = useParameterCatalogueStore((s) => s.load);
  return { specs, isLoading, error, load };
}

/**
 * The configuration's value of a numeric run parameter, from the catalogue, or `null`
 * while the catalogue has not arrived (or does not offer that parameter).
 *
 * The client holds no copy of a configuration value: the activation ceiling, the
 * Themespace's ceiling and the spreading threshold the next run will start with are all
 * read from here, so a configuration that changes them is followed by the screen.
 */
export function catalogueNumber(specs: RunParameterSpec[], name: string): number | null {
  const value = specs.find((s) => s.name === name)?.default;
  return typeof value === 'number' ? value : null;
}

/** :func:`catalogueNumber` for a component: fetches the catalogue once and follows it. */
export function useCatalogueNumber(name: string): number | null {
  const specs = useParameterCatalogueStore((s) => s.specs);
  const load = useParameterCatalogueStore((s) => s.load);
  useEffect(() => {
    load();
  }, [load]);
  return catalogueNumber(specs, name);
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/**
 * Why the server would reject this value, or `null` if it would not.
 *
 * Deliberately the same three checks `RunParameter.validate` makes, in the same
 * order, so that what the form says and what the API says cannot disagree. The
 * client's copy exists to say so *before* the request rather than instead of it —
 * the server still validates, and is still the authority.
 */
export function parameterError(
  spec: RunParameterSpec,
  value: RunParameterValue | undefined,
): string | null {
  if (value === undefined) return null;

  if (spec.kind === 'bool') {
    return typeof value === 'boolean' ? null : `${spec.label} must be true or false`;
  }
  if (spec.kind === 'node_list' || spec.kind === 'node_map') {
    // Not offered as an editable control, so an override of one can only have come
    // from somewhere other than this form.
    return null;
  }

  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return `${spec.label} must be a number`;
  }
  if (spec.kind === 'int' && !Number.isInteger(value)) {
    return `${spec.label} must be a whole number`;
  }
  if (spec.minimum !== null && value < spec.minimum) {
    return `${spec.label} must be at least ${spec.minimum}`;
  }
  if (spec.maximum !== null && value > spec.maximum) {
    return `${spec.label} must be at most ${spec.maximum}`;
  }
  return null;
}

/** Every override the server would reject, by parameter name. */
export function parameterErrors(
  specs: RunParameterSpec[],
  overrides: Record<string, RunParameterValue>,
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const spec of specs) {
    const message = parameterError(spec, overrides[spec.name]);
    if (message !== null) errors[spec.name] = message;
  }
  return errors;
}
