// ---------------------------------------------------------------------------
// useMachine -- what the server's machine is, and what was sized from it
// ---------------------------------------------------------------------------
//
// The worker count a run may ask for is a property of the server's CPU, not of
// this browser and not of a number written into the page. `GET /api/system/numeric`
// reports the detected machine alongside the sizes derived from it, and this hook
// is how a control reads them.
//
// It is a property of the process rather than of a run, so it does not change while
// the page is open: one fetch on mount, no polling. A failed fetch leaves both
// values null, and every caller treats null as "no limit stated" rather than
// substituting one of its own.
// ---------------------------------------------------------------------------

import { useEffect, useState } from 'react';
import { getNumericSubstrate } from '@/api/client';
import type { DerivedSizes, DetectedMachine } from '@/types';

export interface MachineInfo {
  machine: DetectedMachine | null;
  derived: DerivedSizes | null;
}

export function useMachine(): MachineInfo {
  const [info, setInfo] = useState<MachineInfo>({ machine: null, derived: null });

  useEffect(() => {
    let cancelled = false;
    getNumericSubstrate()
      .then((substrate) => {
        if (!cancelled) {
          setInfo({
            machine: substrate.hardware ?? null,
            derived: substrate.derived ?? null,
          });
        }
      })
      .catch(() => {
        // Left null on purpose -- see the header comment.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return info;
}
