// ---------------------------------------------------------------------------
// Petacat — API client wrapping fetch() for all server endpoints
// ---------------------------------------------------------------------------

import type {
  RunParams,
  RunInfo,
  StepResult,
  WorkspaceState,
  SlipnetState,
  CoderackState,
  ThemespaceState,
  TraceEvent,
  MemoryState,
  DemoProblem,
  SlipnetNodeDef,
} from '../types';

const API_BASE = '/api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body: string,
  ) {
    super(`API ${status} ${statusText}: ${body}`);
    this.name = 'ApiError';
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string> | undefined),
    },
    ...options,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new ApiError(res.status, res.statusText, body);
  }

  // 204 No Content — nothing to parse
  if (res.status === 204) {
    return undefined as unknown as T;
  }

  return res.json() as Promise<T>;
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) {
      parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
    }
  }
  return parts.length > 0 ? `?${parts.join('&')}` : '';
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export async function createRun(params: RunParams): Promise<RunInfo> {
  return request<RunInfo>('/runs', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export async function getRun(runId: number): Promise<RunInfo> {
  return request<RunInfo>(`/runs/${runId}`);
}

export async function listRuns(
  limit?: number,
  offset?: number,
): Promise<{ runs: RunInfo[]; total: number }> {
  return request(`/runs${qs({ limit, offset })}`);
}

export async function stepRun(
  runId: number,
  n?: number,
): Promise<StepResult[]> {
  return request<StepResult[]>(`/runs/${runId}/step`, {
    method: 'POST',
    body: JSON.stringify({ n: n ?? 1 }),
  });
}

export async function runToCompletion(
  runId: number,
  maxSteps: number,
): Promise<RunInfo> {
  return request<RunInfo>(`/runs/${runId}/run`, {
    method: 'POST',
    body: JSON.stringify({ max_steps: maxSteps }),
  });
}

export async function stopRun(runId: number): Promise<void> {
  return request<void>(`/runs/${runId}/stop`, { method: 'POST' });
}

export async function resetRun(runId: number): Promise<RunInfo> {
  return request<RunInfo>(`/runs/${runId}/reset`, { method: 'POST' });
}

export async function deleteRun(runId: number): Promise<void> {
  return request<void>(`/runs/${runId}`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

export async function getWorkspace(runId: number): Promise<WorkspaceState> {
  return request<WorkspaceState>(`/runs/${runId}/workspace`);
}

export async function getSlipnet(runId: number): Promise<SlipnetState> {
  return request<SlipnetState>(`/runs/${runId}/slipnet`);
}

export async function getCoderack(runId: number): Promise<CoderackState> {
  return request<CoderackState>(`/runs/${runId}/coderack`);
}

export async function getThemespace(runId: number): Promise<ThemespaceState> {
  return request<ThemespaceState>(`/runs/${runId}/themespace`);
}

export async function getTrace(
  runId: number,
  opts?: { event_type?: string; limit?: number; offset?: number },
): Promise<TraceEvent[]> {
  return request<TraceEvent[]>(
    `/runs/${runId}/trace${qs(opts ?? {})}`,
  );
}

export async function getTemperature(runId: number): Promise<number> {
  return request<number>(`/runs/${runId}/temperature`);
}

export async function getCommentary(
  runId: number,
  elizaMode?: boolean,
): Promise<string> {
  return request<string>(
    `/runs/${runId}/commentary${qs({ eliza_mode: elizaMode })}`,
  );
}

export async function getMemory(): Promise<MemoryState> {
  return request<MemoryState>('/memory');
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

export async function setBreakpoint(
  runId: number,
  codeletCount: number,
): Promise<void> {
  return request<void>(`/runs/${runId}/breakpoint`, {
    method: 'POST',
    body: JSON.stringify({ codelet_count: codeletCount }),
  });
}

export async function clearBreakpoint(runId: number): Promise<void> {
  return request<void>(`/runs/${runId}/breakpoint`, { method: 'DELETE' });
}

export async function clampTemperature(
  runId: number,
  value: number,
  cycles: number,
): Promise<void> {
  return request<void>(`/runs/${runId}/temperature/clamp`, {
    method: 'POST',
    body: JSON.stringify({ value, cycles }),
  });
}

export async function unclampTemperature(runId: number): Promise<void> {
  return request<void>(`/runs/${runId}/temperature/clamp`, {
    method: 'DELETE',
  });
}

export async function clampNode(
  runId: number,
  nodeName: string,
  cycles: number,
): Promise<void> {
  return request<void>(`/runs/${runId}/slipnet/${encodeURIComponent(nodeName)}/clamp`, {
    method: 'POST',
    body: JSON.stringify({ cycles }),
  });
}

export async function unclampNode(
  runId: number,
  nodeName: string,
): Promise<void> {
  return request<void>(`/runs/${runId}/slipnet/${encodeURIComponent(nodeName)}/clamp`, {
    method: 'DELETE',
  });
}

export async function setSpreadingThreshold(
  runId: number,
  threshold: number,
): Promise<{ run_id: number; spreading_activation_threshold: number }> {
  return request(`/runs/${runId}/spreading-threshold`, {
    method: 'POST',
    body: JSON.stringify({ threshold }),
  });
}

export async function getSpreadingThreshold(
  runId: number,
): Promise<{ run_id: number; spreading_activation_threshold: number }> {
  return request(`/runs/${runId}/spreading-threshold`);
}

// ---------------------------------------------------------------------------
// Admin / reference data
// ---------------------------------------------------------------------------

export async function getSlipnetNodes(): Promise<SlipnetNodeDef[]> {
  return request<SlipnetNodeDef[]>('/admin/slipnet/nodes');
}

export async function getSlipnetLinks(): Promise<any[]> {
  return request<any[]>('/admin/slipnet/links');
}

export async function getCodeletTypes(): Promise<any[]> {
  return request<any[]>('/admin/codelets');
}

export async function getDemos(): Promise<DemoProblem[]> {
  return request<DemoProblem[]>('/admin/demos');
}

export async function getParams(): Promise<Record<string, any>[]> {
  return request<Record<string, any>[]>('/admin/params');
}

// ---------------------------------------------------------------------------
// Documentation / help
// ---------------------------------------------------------------------------

export async function getConceptHelp(name: string): Promise<any> {
  return request<any>(`/docs/concepts/${encodeURIComponent(name)}`);
}

export async function getCodeletHelp(name: string): Promise<any> {
  return request<any>(`/docs/codelets/${encodeURIComponent(name)}`);
}

export async function getComponentHelp(name: string): Promise<{
  name: string;
  topic_key: string;
  short_desc: string;
  description: string;
  metadata: Record<string, unknown>;
}> {
  return request(`/docs/components/${encodeURIComponent(name)}`);
}

export interface RegenerateHelpResult {
  status: string;
  db_synced: boolean;
  locale: string;
  topics_loaded: number;
  components: number;
  glossary: number;
  help_md_changed: boolean;
  ts_constants_changed: boolean;
  help_md_path: string;
  ts_constants_path: string;
}

export async function regenerateHelpDocs(): Promise<RegenerateHelpResult> {
  return request<RegenerateHelpResult>('/admin/help/regenerate', {
    method: 'POST',
  });
}

export async function searchDocs(query: string): Promise<any[]> {
  return request<any[]>(`/docs/search${qs({ q: query })}`);
}

// ---------------------------------------------------------------------------
// Convenience re-export as namespace-style object
// ---------------------------------------------------------------------------

export const api = {
  // Runs
  createRun,
  getRun,
  listRuns,
  stepRun,
  runToCompletion,
  stopRun,
  resetRun,
  deleteRun,

  // State
  getWorkspace,
  getSlipnet,
  getCoderack,
  getThemespace,
  getTrace,
  getTemperature,
  getCommentary,
  getMemory,

  // Controls
  setBreakpoint,
  clearBreakpoint,
  clampTemperature,
  unclampTemperature,
  clampNode,
  unclampNode,
  setSpreadingThreshold,
  getSpreadingThreshold,

  // Admin
  getSlipnetNodes,
  getSlipnetLinks,
  getCodeletTypes,
  getDemos,
  getParams,

  // Docs
  getConceptHelp,
  getCodeletHelp,
  searchDocs,
} as const;
