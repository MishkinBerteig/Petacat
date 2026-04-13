// ---------------------------------------------------------------------------
// Petacat — Custom hook for run lifecycle
// ---------------------------------------------------------------------------
//
// Wraps the Zustand store to expose a convenient subset of state and derived
// values for components that deal with the run lifecycle (control panels,
// status bars, etc.).
// ---------------------------------------------------------------------------

import { useRunStore } from '@/store/runStore';
import type { RunStatus } from '@/store/runStore';
import type { RunParams } from '@/types';

export interface UseRunReturn {
  // Core state
  runId: number | null;
  status: RunStatus;
  codeletCount: number;
  temperature: number;

  // Derived booleans
  isRunning: boolean;
  isPaused: boolean;
  hasRun: boolean;
  isIdle: boolean;
  canStep: boolean;
  canRun: boolean;
  canStop: boolean;
  canReset: boolean;

  // Actions
  createRun: (params: RunParams) => Promise<void>;
  step: (n?: number) => Promise<void>;
  run: (maxSteps?: number) => Promise<void>;
  stop: () => Promise<void>;
  reset: () => Promise<void>;
  deleteRun: () => Promise<void>;
}

export function useRun(): UseRunReturn {
  const runId = useRunStore((s) => s.runId);
  const status = useRunStore((s) => s.status);
  const codeletCount = useRunStore((s) => s.codeletCount);
  const temperature = useRunStore((s) => s.temperature);

  const createRun = useRunStore((s) => s.createRun);
  const step = useRunStore((s) => s.step);
  const run = useRunStore((s) => s.run);
  const stop = useRunStore((s) => s.stop);
  const reset = useRunStore((s) => s.reset);
  const deleteRun = useRunStore((s) => s.deleteRun);

  const isRunning = status === 'running';
  const isPaused = status === 'paused';
  const hasRun = runId !== null;
  const isIdle = status === 'idle';

  // Can step/run when a run exists and is not currently running
  const canStep = hasRun && !isRunning;
  const canRun = hasRun && !isRunning;
  const canStop = isRunning;
  const canReset = hasRun && !isRunning;

  return {
    runId,
    status,
    codeletCount,
    temperature,
    isRunning,
    isPaused,
    hasRun,
    isIdle,
    canStep,
    canRun,
    canStop,
    canReset,
    createRun,
    step,
    run,
    stop,
    reset,
    deleteRun,
  };
}
