// ---------------------------------------------------------------------------
// Petacat — TypeScript types mirroring the server API responses
// ---------------------------------------------------------------------------

// --- Run types -------------------------------------------------------------

export interface RunParams {
  initial: string;
  modified: string;
  target: string;
  answer?: string;
  seed: number;
  /** Set at creation so the engine is initialised with it. Defaults to 100. */
  spreading_threshold?: number;
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

// --- WebSocket messages ----------------------------------------------------

export interface WsMessage {
  type: string;
  run_id?: number;
  data?: any;
}
