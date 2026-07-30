// ---------------------------------------------------------------------------
// SubstrateBadge -- which processor the engine's arithmetic is running on
// ---------------------------------------------------------------------------
//
// Phase 0's Workstream B says the numeric work executes on the GPU cores, and
// `auto` now selects the Metal backend at every Slipnet size so that it actually
// does. Nothing on screen said so, which made the phase's second headline change
// invisible: a reader could not tell a GPU build from a checkout with MLX missing,
// and those two behave identically until something is slow or a float32 rounding
// difference shows up.
//
// Deliberately small and in the header. It is a property of the *process*, not of
// the run, so it does not belong in any panel, and it does not change while the
// page is open — hence one fetch on mount and no polling. It renders nothing at all
// until the answer arrives, and nothing if the fetch fails: a header decoration
// that turns into an error message is worse than one that is absent.
// ---------------------------------------------------------------------------

import { useEffect, useState } from 'react';
import { getNumericSubstrate } from '@/api/client';
import { useHelp } from '@/hooks/useHelp';
import type { NumericSubstrate } from '@/types';

/** GPU is the interesting case, so it is the one that gets a colour. */
function deviceColor(device: string): string {
  return device === 'gpu' ? 'var(--success, #4caf50)' : 'var(--text-secondary, #999)';
}

export function SubstrateBadge() {
  const [substrate, setSubstrate] = useState<NumericSubstrate | null>(null);
  const { showHelp } = useHelp();

  useEffect(() => {
    let cancelled = false;
    getNumericSubstrate()
      .then((s) => {
        if (!cancelled) setSubstrate(s);
      })
      .catch(() => {
        // Left blank on purpose — see the header comment.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (substrate === null) return null;

  const label =
    substrate.backend === null
      ? 'engine loops'
      : `${substrate.device.toUpperCase()} · ${substrate.backend}`;

  const detail = [
    substrate.summary,
    `Policy: ${substrate.policy}` +
      (substrate.policy === 'auto'
        ? ` (vectorise at ${substrate.vectorise_threshold} nodes, GPU at ${substrate.gpu_threshold})`
        : ''),
    `Available: ${substrate.available.join(', ') || 'none'}`,
    substrate.exact
      ? 'Computes in float64, matching the reference exactly.'
      : 'Computes in float32: MLX has no float64 on the GPU, so activations agree '
        + 'with the reference within a tolerance rather than bit-for-bit.',
    '',
    'Click for the full glossary entry.',
  ].join('\n');

  return (
    // A button rather than a span, because the tooltip is a summary and the glossary
    // has the rest. The `numeric_substrate` entry explains what the four backends are
    // and why the GPU one diverges, which is the question the badge raises and cannot
    // answer in a tooltip. It was unreachable until the help system learned about
    // glossary terms at all.
    <button
      onClick={() => showHelp('glossary', 'numeric_substrate')}
      title={detail}
      aria-label={`Numeric substrate: ${label}. Open the glossary entry.`}
      className="mono"
      style={{
        fontSize: 10,
        padding: '1px 6px',
        borderRadius: 4,
        border: '1px solid var(--border, #444)',
        background: 'none',
        color: deviceColor(substrate.device),
        cursor: 'pointer',
        whiteSpace: 'nowrap',
        fontFamily: 'var(--font-mono)',
      }}
    >
      {label}
    </button>
  );
}
