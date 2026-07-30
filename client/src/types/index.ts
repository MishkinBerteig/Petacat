// ---------------------------------------------------------------------------
// Petacat — TypeScript types mirroring the server API responses
// ---------------------------------------------------------------------------

// --- Run types -------------------------------------------------------------

/**
 * What a Run writes down. Chosen at creation and fixed for the Run's life.
 *
 * Not to be confused with the execution strategy in Run Controls, which is about
 * how the *UI* follows a run. This one changes nothing about what the engine
 * computes — only what survives it.
 *
 *   fast    nothing, ever; no database row, so no run history and no review
 *   normal  the complete state at Run start and Run end, and nothing between
 *   audit   every state-changing action, as a forward log (~1.8x slower)
 */
export type PersistenceMode = 'fast' | 'normal' | 'audit';

export interface RunParams {
  initial: string;
  modified: string;
  target: string;
  answer?: string;
  seed: number;
  /** Set at creation so the engine is initialised with it. Defaults to 100. */
  spreading_threshold?: number;
  /** Persistence mode. Omitted means the server default, `normal`. */
  mode?: PersistenceMode;
  /**
   * Worker threads. 1 — the default — is the serial loop, which stays the
   * reference mode. Above 1 the run executes free-running, and a seed no longer
   * reproduces it. Audit refuses anything above 1.
   */
  workers?: number;
  /**
   * Per-run overrides for the engine's fixed run parameters, by name. Omitted
   * names keep the global default; an unknown one is rejected with a 400.
   */
  parameters?: Record<string, RunParameterValue>;
}

// --- Run parameters --------------------------------------------------------

/**
 * A fixed run parameter's value. The five kinds the catalogue distinguishes come
 * down to these four shapes on the wire: `int` and `float` are both numbers.
 */
export type RunParameterValue =
  | number
  | boolean
  | string[]
  | Record<string, number>;

/**
 * One settable run parameter, exactly as the server describes it.
 *
 * Fetched rather than duplicated in the client: `minimum` and `maximum` are the
 * bounds the API validates against, and a second copy here would drift into
 * offering values the server rejects.
 */
export interface RunParameterSpec {
  name: string;
  kind: 'int' | 'float' | 'bool' | 'node_list' | 'node_map';
  group: string;
  label: string;
  description: string;
  minimum: number | null;
  maximum: number | null;
  /** Moving this off its default makes the run incomparable with the dissertation. */
  departs_from_original: boolean;
  default: RunParameterValue;
}

/** Free-running telemetry: the only account of how a parallel run was taken. */
export interface FreeRunTelemetry {
  status: string;
  answers: string[];
  workers: number;
  codelets: number;
  seconds: number;
  codelets_per_second: number;
  conflicts: number;
  conflict_rate: number;
  update_cycles: number;
  per_worker: number[];
}

/**
 * What a Run turned out to be: the parameters it was fixed with, and the values
 * that fell out of running it.
 *
 * The halves are kept apart deliberately. `fixed` are inputs, chosen before the
 * first codelet; `derived` are outputs, and presenting them as settings would be a
 * lie about how the engine works.
 */
export interface RunParametersView {
  run_id: number;
  /** The resolved set — every parameter, not only the overridden ones. */
  fixed: Record<string, RunParameterValue>;
  /** Names in `fixed` whose value differs from the current global default. */
  overridden: string[];
  defaults: Record<string, RunParameterValue>;
  derived: {
    mode?: string;
    workers?: number;
    config_hash?: string | null;
    memory_hash?: string | null;
    session_id?: number | null;
    seed?: number | null;
    recorded?: boolean;
    codelet_count?: number;
    temperature?: number;
    status?: string;
    justify_mode?: boolean;
    slipnet_nodes?: number;
    coderack_shards?: number;
    coderack_capacity_per_shard?: number;
    staleness_delay?: number;
    numeric_backend?: string | null;
    numeric_device?: string | null;
    free_running?: FreeRunTelemetry;
  };
}

export interface RunInfo {
  run_id: number;
  status: string;
  codelet_count: number;
  temperature: number;
  initial: string;
  modified: string;
  target: string;
  answer: string | null;
  /**
   * The answer was supplied for the engine to justify rather than discovered by
   * it. Both arrive in `answer`, so a display needs this to avoid reporting a
   * given answer as a found one.
   */
  justify_mode?: boolean;
  /**
   * Which Slipnet nodes were allowed to spread during this run (100 = the
   * original's behaviour). Recorded per run because it changes what the run
   * does, so a run at any other value is not comparable with the others.
   */
  spreading_threshold?: number;
  /** The persistence mode the run was created with. */
  mode?: string;
  /**
   * Only the run *listing* carries these: they come from the row, and a Fast Run
   * has no row. Undefined means "not looked up here", null means "no row".
   */
  config_hash?: string | null;
  memory_hash?: string | null;
}

/**
 * What identifies a Run as an experiment: which configuration and which Episodic
 * Memory it executed against, and which Training Session it belongs to.
 *
 * `recorded: false` is a Fast Run — there is no row to read the hashes from, which
 * is the mode keeping its promise rather than a lookup failure.
 */
export interface RunIdentity {
  run_id: number;
  mode: string;
  recorded: boolean;
  seed: number | null;
  spreading_threshold: number;
  config_hash: string | null;
  memory_hash: string | null;
  session_id: number | null;
  created_at: string | null;
}

/** Which implementation of the engine's arithmetic the server process is running. */
export interface NumericSubstrate {
  policy: string;
  /** `null` means the substrate declined and the engine runs its own loops. */
  backend: string | null;
  device: string;
  precision: string;
  exact: boolean;
  available: string[];
  slipnet_nodes: number;
  slipnet_links: number;
  vectorise_threshold: number;
  gpu_threshold: number;
  summary: string;
}

export interface StepResult {
  codelet_count: number;
  codelet_type: string;
  answer_found: boolean;
  answer: string | null;
  /** A jootser concluded the run is looping with nothing left to try (§4.5.2). */
  gave_up?: boolean;
}

// --- Workspace types -------------------------------------------------------

export interface WorkspaceState {
  initial: string;
  modified: string;
  target: string;
  answer: string | null;
  num_top_bridges: number;
  num_bottom_bridges: number;
  num_vertical_bridges: number;
  bonds_per_string: Record<string, number>;
  groups_per_string: Record<string, number>;
}

// --- Slipnet types ---------------------------------------------------------

export interface SlipnetNodeState {
  activation: number;
  conceptual_depth: number;
  frozen: boolean;
}

export type SlipnetState = Record<string, SlipnetNodeState>;

// --- Coderack types --------------------------------------------------------

export interface CoderackState {
  total_count: number;
  type_counts: Record<string, number>;
}

// --- Themespace types ------------------------------------------------------

export interface ThemeState {
  dimension: string;
  relation: string | null;
  activation: number;
  positive_activation: number;
  negative_activation: number;
  frozen: boolean;
  /** Decided server-side: leads its cluster by the dominance margin (default 90). */
  dominant: boolean;
}

export interface ClusterState {
  theme_type: string;
  dimension: string;
  frozen: boolean;
  dominant_relation: string | null;
  themes: ThemeState[];
}

export interface ThemespaceState {
  clusters: ClusterState[];
  /** Theme types meaningful for the current mode (bottom only in justify mode). */
  possible_theme_types: string[];
  /** Theme types currently exerting top-down thematic pressure. */
  active_theme_types: string[];
  thematic_pressure: boolean;
  dominant_theme_margin: number;
}

// --- Trace types -----------------------------------------------------------

export interface TraceEvent {
  event_number: number;
  event_type: string;
  codelet_count: number;
  temperature: number;
  description: string;
  theme_pattern?: unknown;
}

// --- Memory types ----------------------------------------------------------

export interface AnswerDescription {
  answer_id: number;
  problem: string[];
  quality: number;
  temperature: number;
  themes: Record<string, string>;
  top_rule_description: string;
  bottom_rule_description: string;
  /** 0-100: how strongly the program is currently reminded of this answer. */
  activation?: number;
  top_themes?: Record<string, string>;
  vertical_themes?: Record<string, string>;
  bottom_themes?: Record<string, string>;
  unjustified_themes?: Record<string, string>;
  top_rule_abstractness?: number;
  is_coherent?: boolean;
}

export interface AnswerComparison {
  common_themes: Record<string, string>;
  differing_themes: Record<string, [string, string]>;
  a_unique_themes: Record<string, string>;
  b_unique_themes: Record<string, string>;
  a_unjustified_themes: Record<string, string>;
  b_unjustified_themes: Record<string, string>;
  a_coherent: boolean;
  b_coherent: boolean;
  a_quality: number;
  b_quality: number;
  a_rule: string;
  b_rule: string;
  preferred: { answer: string | null; reason: string };
}

export interface AnswerComparisonResult {
  answer_id_1: number;
  answer_id_2: number;
  comparison: AnswerComparison;
  commentary: {
    text: string;
    paragraphs: string[];
    verdict: string;
  };
}

export interface SnagDescription {
  snag_id: number;
  problem: string[];
  codelet_count: number;
  temperature: number;
  description: string;
}

export interface MemoryState {
  answers: AnswerDescription[];
  snags: SnagDescription[];
  /**
   * Which memory this is.
   *
   *   shared  the Training Session's memory, read from the database
   *   run     the Run's own ephemeral memory — a Fast Run gets one of these, and
   *           contributes nothing to the shared one
   *
   * Absent from `/api/memory`, which is only ever the shared one.
   */
  scope?: 'shared' | 'run';
  /** The persistence mode of the run the memory was read for, when there was one. */
  mode?: string;
  run_id?: number;
}

// --- Demo types ------------------------------------------------------------

export interface DemoProblem {
  id: number;
  name: string;
  initial: string;
  modified: string;
  target: string;
  answer: string | null;
  seed: number;
  mode: string;
  description: string;
}

// --- Slipnet node definition (admin) ---------------------------------------

export interface SlipnetNodeDef {
  name: string;
  short_name: string;
  conceptual_depth: number;
  description?: string;
}

// --- Layout ----------------------------------------------------------------

export interface SlipnetLayout {
  grid_rows: number;
  grid_cols: number;
  node_positions: Record<string, [number, number]>;
}

// --- Review types (WP3.9) --------------------------------------------------
//
// The review surfaces render *recorded* state through the same components as live
// state, so a recorded Workspace is a `WorkspaceState`, a recorded Slipnet is a
// `SlipnetState`, and so on. Only the things that have no live equivalent — a
// Training Session, a capture, an audit action — need types of their own.

export interface TrainingSessionSummary {
  session_id: number;
  started_at: string | null;
  ended_at: string | null;
  note: string;
  run_count: number;
  first_run_at: string | null;
  last_run_at: string | null;
  /** A session ends when Episodic Memory is cleared; until then it can gain Runs. */
  is_open: boolean;
}

export interface RecordedRun {
  run_id: number;
  /** `fast` | `normal` | `audit` — chosen at creation, a property of this Run. */
  mode: string;
  status: string;
  initial: string;
  modified: string;
  target: string;
  answer: string | null;
  justify_mode: boolean;
  seed: number;
  codelet_count: number;
  temperature: number;
  spreading_threshold: number;
  /** Which configuration and which Episodic Memory the Run executed against. */
  config_hash: string | null;
  memory_hash: string | null;
  created_at: string | null;
  /** How much record the Run left. Zero and zero is a Fast Run, by design. */
  capture_count: number;
  action_count: number;
  /**
   * Which Training Session contains this Run. Only set when the Run was looked up
   * by id — reached through its session, the caller already knows.
   */
  session_id?: number | null;
}

export interface TrainingSessionDetail {
  session_id: number;
  started_at: string | null;
  ended_at: string | null;
  note: string;
  is_open: boolean;
  runs: RecordedRun[];
}

export interface CaptureSummary {
  capture_id: number;
  boundary: string;
  codelet_count: number;
  created_at: string | null;
}

/** One recorded capture, in the shapes the live views already read. */
export interface RecordedState {
  run_id: number;
  boundary: string;
  problem: { initial: string; modified: string; target: string; answer: string | null };
  codelet_count: number;
  temperature: number;
  workspace: WorkspaceState;
  slipnet: SlipnetState;
  coderack: CoderackState;
  themespace: ThemespaceState;
  trace: TraceEvent[];
  memory: MemoryState;
}

export interface ActivationMovement {
  node: string;
  start: number;
  end: number;
  delta: number;
}

export interface ThemeMovement {
  theme_type: string;
  dimension: string;
  relation: string | null;
  start: number;
  end: number;
  delta: number;
  dominant: boolean;
}

/** What changed between a Normal Run's two captures — not both blobs. */
export interface RunComparison {
  run_id: number;
  problem: { initial: string; modified: string; target: string; answer: string | null };
  codelets: { start: number; end: number; executed: number };
  temperature: { start: number; end: number; delta: number };
  structures: {
    bonds: { start: Record<string, number>; end: Record<string, number>; built: Record<string, number> };
    groups: { start: Record<string, number>; end: Record<string, number>; built: Record<string, number> };
    bridges: { start: Record<string, number>; end: Record<string, number>; built: Record<string, number> };
    rules: { start: Record<string, number>; end: Record<string, number>; built: Record<string, number> };
  };
  rules: { top: unknown[]; bottom: unknown[] };
  slipnet: {
    moved: ActivationMovement[];
    moved_count: number;
    fully_active_at_start: string[];
    fully_active_at_end: string[];
  };
  themes: {
    moved: ThemeMovement[];
    moved_count: number;
    dominant_at_end: { theme_type: string; dimension: string; relation: string | null }[];
  };
  trace: {
    events_at_start: number;
    events_at_end: number;
    by_type: Record<string, number>;
    events: TraceEvent[];
  };
  memory: {
    answers_at_start: number;
    answers_at_end: number;
    snags_at_start: number;
    snags_at_end: number;
    added_answers: AnswerDescription[];
    added_snags: SnagDescription[];
  };
}

export interface AuditAction {
  sequence: number;
  codelet_count: number;
  action_type: string;
  temperature: number;
  payload: Record<string, any> | null;
  /** Prior state, recorded so actions could be inverted later. Unused in Phase 0. */
  before: Record<string, any> | null;
}

export interface AuditActionPage {
  run_id: number;
  total: number;
  limit: number;
  offset: number;
  actions: AuditAction[];
}

export interface AuditActionSummary {
  run_id: number;
  by_type: Record<string, number>;
  first_codelet: number;
  last_codelet: number;
  total: number;
}

/** The inspector's position and everything visible from it. Forward-only. */
export interface InspectorState {
  run_id: number;
  codelet_count: number;
  final_codelet_count: number;
  at_end: boolean;
  /** The codelet whose execution produced this state, from the recorded log. */
  codelet: AuditAction | null;
  structure_changes: AuditAction[];
  actions: AuditAction[];
  temperature: number;
  recorded_temperature: number | null;
  workspace: WorkspaceState;
  slipnet: SlipnetState;
  coderack: CoderackState;
  themespace: ThemespaceState;
  trace: TraceEvent[];
}

// --- WebSocket messages ----------------------------------------------------

export interface WsMessage {
  type: string;
  run_id?: number;
  data?: any;
}
