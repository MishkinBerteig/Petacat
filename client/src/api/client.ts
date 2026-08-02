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
  TrainingSessionSummary,
  TrainingSessionDetail,
  CaptureSummary,
  RecordedRun,
  RecordedState,
  RunComparison,
  AuditActionPage,
  AuditActionSummary,
  InspectorState,
  RunIdentity,
  NumericSubstrate,
  RunParameterSpec,
  RunParametersView,
  TraceEventDetail,
  AnswerExplanation,
  TemperatureState,
} from '../types';

const API_BASE = '/api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body: string,
  ) {
    super(`API ${status} ${statusText}: ${body}`);
    this.name = 'ApiError';
  }

  /** What the server said went wrong: FastAPI's `detail`, or the raw body. */
  get detail(): string {
    try {
      const parsed = JSON.parse(this.body);
      const d = parsed?.detail;
      if (typeof d === 'string') return d;
      // A 422 arrives as a list of field errors.
      if (Array.isArray(d)) {
        return d
          .map((e: any) => {
            const field = Array.isArray(e?.loc) ? e.loc.slice(1).join('.') : '';
            return field ? `${field}: ${e.msg}` : e.msg;
          })
          .filter(Boolean)
          .join('; ');
      }
    } catch {
      // Not JSON; the body is the message.
    }
    return this.body.trim();
  }
}

/**
 * One sentence a reader can act on, from whatever went wrong.
 *
 * The status says what kind of problem it is and the server's detail says which one, so
 * both appear: the kind gives the reader their next move, and the detail names the
 * thing. `action` names what was being attempted, in the reader's terms.
 */
/** Every sentence this produces opens with these words, which makes one recognisable. */
const DESCRIBED_PREFIX = 'Could not ';

export function describeApiError(error: unknown, action: string): string {
  if (error instanceof ApiError) {
    const detail = error.detail;
    const suffix = detail ? ` ${detail}` : '';
    switch (error.status) {
      case 400:
        return `Could not ${action}: the request was rejected.${suffix}`;
      case 404:
        return `Could not ${action}: it no longer exists.${suffix}`;
      case 409:
        return `Could not ${action}: that conflicts with something already there.${suffix}`;
      case 422:
        return `Could not ${action}: check the values entered.${suffix}`;
      case 500:
      case 502:
      case 503:
        return `Could not ${action}: the server failed to complete it.${suffix}`;
      default:
        return `Could not ${action} (HTTP ${error.status}).${suffix}`;
    }
  }
  if (error instanceof TypeError) {
    return `Could not ${action}: the server is unreachable.`;
  }
  const message = error instanceof Error ? error.message : String(error);
  // A message already describing a failure is passed through, so a caller that
  // describes its own action and a shared surface that describes a generic one
  // together produce the specific sentence rather than both of them.
  if (message.startsWith(DESCRIBED_PREFIX)) return message;
  return `Could not ${action}.${message ? ` ${message}` : ''}`;
}

/**
 * Every HTTP call the client makes goes through here, so a non-2xx always rejects with
 * an `ApiError` carrying the status and the server's detail.
 */
export async function request<T>(
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

/**
 * Which configuration and which Episodic Memory a run executed against.
 *
 * Answers for a live run, including a Fast one — which reports `recorded: false`
 * rather than 404, because "this run wrote nothing" is a fact about it.
 */
export async function getRunIdentity(runId: number): Promise<RunIdentity> {
  return request<RunIdentity>(`/runs/${runId}/identity`);
}

/**
 * Every settable run parameter, with its kind, bounds and current default.
 *
 * The form is driven from this rather than from a list in the client: these are the
 * same bounds the API validates against, and two copies would drift into a control
 * that offers a value the server refuses.
 */
export async function getParameterCatalogue(): Promise<RunParameterSpec[]> {
  const body = await request<{ parameters: RunParameterSpec[] }>(
    '/runs/parameters/catalogue',
  );
  return body.parameters;
}

/** What a Run was fixed with, and what running it produced. */
export async function getRunParameters(runId: number): Promise<RunParametersView> {
  return request<RunParametersView>(`/runs/${runId}/parameters`);
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

/**
 * Delete every run the server holds, with their captures and trace events.
 *
 * Goes through `request` like everything else, so a refusal arrives as an `ApiError`
 * and the caller can say that the runs are still there.
 */
export async function deleteAllRuns(): Promise<{ deleted_count: number }> {
  return request<{ deleted_count: number }>('/runs', { method: 'DELETE' });
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

/** The Trace arrives wrapped with its paging window; the events are what a caller wants. */
export async function getTrace(
  runId: number,
  opts?: { event_type?: string; limit?: number; offset?: number },
): Promise<TraceEvent[]> {
  const res = await request<{
    run_id: number;
    events: TraceEvent[];
    limit: number;
    offset: number;
  }>(`/runs/${runId}/trace${qs(opts ?? {})}`);
  return res.events;
}

/** The temperature and whether the engine is holding it clamped. */
export async function getTemperature(runId: number): Promise<TemperatureState> {
  return request<TemperatureState>(`/runs/${runId}/temperature`);
}

/**
 * Clamp the temperature to a fixed value for `cycles` update cycles (0 = indefinite).
 *
 * Rejects when the server refuses, so a caller learns that the clamp is not in force.
 */
export async function clampTemperature(
  runId: number,
  value: number,
  cycles: number,
): Promise<void> {
  return request<void>(`/runs/${runId}/clamp-temperature`, {
    method: 'POST',
    body: JSON.stringify({ value, cycles }),
  });
}

export async function unclampTemperature(runId: number): Promise<void> {
  return request<void>(`/runs/${runId}/clamp-temperature`, {
    method: 'DELETE',
  });
}

export async function getCommentary(
  runId: number,
  elizaMode?: boolean,
): Promise<string> {
  const res = await request<{
    run_id: number;
    commentary: string;
    eliza_mode: boolean;
  }>(`/runs/${runId}/commentary${qs({ eliza_mode: elizaMode })}`);
  return res.commentary;
}

export async function getMemory(): Promise<MemoryState> {
  return request<MemoryState>('/memory');
}

/**
 * Clear Episodic Memory, which is what a Training Session boundary means: after it,
 * no Run inherits anything from the ones before.
 */
export async function clearMemory(): Promise<{ cleared: boolean; removed: number }> {
  return request<{ cleared: boolean; removed: number }>('/memory', {
    method: 'DELETE',
  });
}

/**
 * The Episodic Memory a particular run is thinking against.
 *
 * The shared Training Session memory in every mode — a Fast Run takes part in the
 * session like any other, because mode chooses where a run is *recorded*, not what it
 * is. A Fast Run is served from the live object rather than the database, since it has
 * no rows; `scope` says which read was taken.
 */
export async function getRunMemory(runId: number): Promise<MemoryState> {
  return request<MemoryState>(`/runs/${runId}/memory`);
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

/**
 * Clamp themes in the Themespace.
 *
 * MetaCat's theme windows are mouse-driven: a left-click pins a theme to +100 and a
 * right-click to -100, first zeroing the rest of that dimension's cluster
 * (`theme-graphics.ss:35-63`). It is how the dissertation produced Figures 4.5 and 4.6,
 * and it is the user's only direct handle on *negative* thematic pressure — saying "not
 * this idea" and watching the program reorganise. The endpoint existed; nothing in the
 * client called it.
 */
export async function clampThemes(
  runId: number,
  themes: Array<{
    type: string;
    dimension: string;
    relation: string | null;
    activation: number;
  }>,
): Promise<void> {
  return request<void>(`/runs/${runId}/clamp-themes`, {
    method: 'POST',
    body: JSON.stringify({ themes }),
  });
}

export async function unclampThemes(runId: number): Promise<void> {
  return request<void>(`/runs/${runId}/clamp-themes`, {
    method: 'DELETE',
  });
}

/** One of the five clampable codelet patterns (`gui.ss:599-603`). */
export interface CodeletPattern {
  name: string;
  label: string;
  entries: { codelet_type: string; urgency_level: string }[];
}

export async function getCodeletPatterns(runId: number): Promise<CodeletPattern[]> {
  const res = await request<{ patterns: CodeletPattern[] }>(
    `/runs/${runId}/codelet-patterns`,
  );
  return res.patterns;
}

export async function clampCodeletPattern(
  runId: number,
  pattern: string,
): Promise<void> {
  return request<void>(`/runs/${runId}/clamp-codelet-pattern`, {
    method: 'POST',
    body: JSON.stringify({ pattern }),
  });
}

export async function unclampCodeletPattern(
  runId: number,
  pattern: string,
): Promise<void> {
  return request<void>(`/runs/${runId}/clamp-codelet-pattern`, {
    method: 'DELETE',
    body: JSON.stringify({ pattern }),
  });
}

/**
 * Fetch one Trace event in full — its structures, theme-pattern and strength.
 *
 * MetaCat's Trace is interrogable, not just readable: every event answers `display`,
 * which redraws the Workspace as it was, imposes the event's theme-pattern and shows
 * its concept-pattern in the Slipnet. §2.4.3 is why it matters — Trace events are
 * "themselves subject to examination", and a log you cannot address is exactly what the
 * Trace display exists not to be.
 */
/** Impose that event's theme-pattern over the live Themespace, or restore it. */
export async function displayTraceEvent(
  runId: number,
  eventNumber: number,
): Promise<{ displaying: number | null }> {
  return request<{ displaying: number | null }>(
    `/runs/${runId}/trace/${eventNumber}/display`,
    { method: 'POST' },
  );
}

/** Impose a stored answer's three theme-patterns (`memory.ss:275-277`), or restore. */
export async function displayAnswer(
  runId: number,
  answerId: number,
): Promise<{ displaying: number | null }> {
  return request<{ displaying: number | null }>(
    `/memory/answers/${answerId}/display?run_id=${runId}`,
    { method: 'POST' },
  );
}

/** Forget one answer (`memory.ss:42-54`); §5.2.3's experiment needs it. */
export async function forgetAnswer(answerId: number): Promise<void> {
  return request<void>(`/memory/answers/${answerId}`, { method: 'DELETE' });
}

/**
 * What one answer is based on, in the program's own words (`answers.ss:310-333`).
 *
 * `elizaMode` picks which voice `text` carries, the same toggle that governs the run
 * commentary; both voices come back regardless, since they are isomorphic (§4.6).
 */
export async function explainAnswer(
  answerId: number,
  elizaMode?: boolean,
): Promise<AnswerExplanation> {
  return request<AnswerExplanation>(
    `/memory/answers/${answerId}/explanation${qs({ eliza_mode: elizaMode })}`,
  );
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

/**
 * A glossary term: the vocabulary the architecture is described in.
 *
 * Distinct from a component, and the distinction is not cosmetic — they are different
 * rows with different shapes, and looking a glossary term up as a component 404s. That
 * is what used to happen to every glossary hit in the search palette.
 */
export async function getGlossaryHelp(term: string): Promise<{
  term: string;
  title: string;
  definition: string;
  details: string;
  metadata: Record<string, unknown>;
}> {
  return request(`/docs/glossary/${encodeURIComponent(term)}`);
}

export interface DocSearchHit {
  /** `slipnet_node` | `codelet_type` | `component` | `glossary`. */
  type: string;
  name: string;
  description: string;
  /** Present on component and glossary hits: the key those endpoints are keyed by. */
  topic_key?: string;
  short_name?: string;
}

/**
 * Free-text search across nodes, codelets, components and glossary terms.
 *
 * The endpoint answers `{query, results, total}`, and this used to be typed and used as
 * though it answered a bare array — so `results.map` threw on every search and the
 * palette's catch turned that into "No results found" for every query ever typed.
 */
export async function searchDocs(query: string): Promise<DocSearchHit[]> {
  const body = await request<{ results: DocSearchHit[] }>(
    `/docs/search${qs({ q: query })}`,
  );
  return body.results ?? [];
}

// ---------------------------------------------------------------------------
// System — what is executing, as opposed to what was recorded
//
// `/api/system` takes no database session, deliberately: a Fast Run is required to
// work with Postgres stopped, and "what is running?" is the first thing a reader
// asks when the panels go quiet.
// ---------------------------------------------------------------------------

export async function getNumericSubstrate(): Promise<NumericSubstrate> {
  return request<NumericSubstrate>('/system/numeric');
}

// ---------------------------------------------------------------------------
// Review (WP3.9) — reading back what the persistence modes wrote
//
// These never touch a live runner. `/api/review` is a separate router from
// `/api/runs` for that reason: a 404 from a run endpoint means "no engine with that
// id is loaded", and a 404 from these means "nothing was recorded" — which for a Fast
// Run is the mode working, not a fault.
// ---------------------------------------------------------------------------

export async function listTrainingSessions(
  limit?: number,
  offset?: number,
): Promise<{ sessions: TrainingSessionSummary[]; total: number }> {
  return request(`/review/sessions${qs({ limit, offset })}`);
}

export async function getTrainingSession(
  sessionId: number,
): Promise<TrainingSessionDetail> {
  return request<TrainingSessionDetail>(`/review/sessions/${sessionId}`);
}

/**
 * Name a Training Session.
 *
 * A session is not created deliberately — it is the span between two memory clears —
 * so a number and a date range is all that distinguishes one otherwise.
 */
export async function setSessionNote(
  sessionId: number,
  note: string,
): Promise<{ session_id: number; note: string }> {
  return request(`/review/sessions/${sessionId}/note`, {
    method: 'PUT',
    body: JSON.stringify({ note }),
  });
}

/**
 * One recorded Run by id, without knowing its session.
 *
 * The session browser reaches a Run by opening the session containing it, which is
 * the wrong way round for a reader arriving from Run History with a Run already in
 * mind: the session is precisely what they do not know.
 */
export async function getRecordedRun(runId: number): Promise<RecordedRun> {
  return request<RecordedRun>(`/review/runs/${runId}`);
}

export async function listCaptures(
  runId: number,
): Promise<{ run_id: number; captures: CaptureSummary[] }> {
  return request(`/review/runs/${runId}/captures`);
}

export async function getCapture(
  runId: number,
  boundary: 'start' | 'end',
): Promise<RecordedState> {
  return request<RecordedState>(`/review/runs/${runId}/captures/${boundary}`);
}

export async function getRunComparison(runId: number): Promise<RunComparison> {
  return request<RunComparison>(`/review/runs/${runId}/comparison`);
}

export async function listAuditActions(
  runId: number,
  opts?: { limit?: number; offset?: number; action_type?: string; from_codelet?: number },
): Promise<AuditActionPage> {
  return request<AuditActionPage>(
    `/review/runs/${runId}/actions${qs(opts ?? {})}`,
  );
}

export async function getAuditSummary(runId: number): Promise<AuditActionSummary> {
  return request<AuditActionSummary>(`/review/runs/${runId}/actions/summary`);
}

export async function openInspector(runId: number): Promise<InspectorState> {
  return request<InspectorState>(`/review/runs/${runId}/inspector`, {
    method: 'POST',
  });
}

/**
 * Step the inspection forward to a tick.
 *
 * A destination rather than a number of steps, so a retried request cannot
 * double-step. Asking to go backwards returns 409: Phase 0 is forward-only.
 */
export async function advanceInspector(
  runId: number,
  toCodelet: number,
): Promise<InspectorState> {
  return request<InspectorState>(`/review/runs/${runId}/inspector/advance`, {
    method: 'POST',
    body: JSON.stringify({ to_codelet: toCodelet }),
  });
}

export async function closeInspector(runId: number): Promise<void> {
  return request<void>(`/review/runs/${runId}/inspector`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// Convenience re-export as namespace-style object
// ---------------------------------------------------------------------------

export const api = {
  // Runs
  createRun,
  getRun,
  getRunIdentity,
  getParameterCatalogue,
  getRunParameters,
  listRuns,
  stepRun,
  runToCompletion,
  stopRun,
  resetRun,
  deleteRun,
  deleteAllRuns,

  // State
  getWorkspace,
  getSlipnet,
  getCoderack,
  getThemespace,
  getTrace,
  getTemperature,
  getCommentary,
  getMemory,
  getRunMemory,
  clearMemory,

  // Controls
  setBreakpoint,
  clearBreakpoint,
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
  getComponentHelp,
  getGlossaryHelp,
  searchDocs,

  // System
  getNumericSubstrate,

  // Review
  listTrainingSessions,
  getTrainingSession,
  setSessionNote,
  getRecordedRun,
  listCaptures,
  getCapture,
  getRunComparison,
  listAuditActions,
  getAuditSummary,
  openInspector,
  advanceInspector,
  closeInspector,
} as const;
