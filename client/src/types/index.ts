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
}

export interface StepResult {
  codelet_count: number;
  codelet_type: string;
  answer_found: boolean;
  answer: string | null;
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
}

export interface ClusterState {
  theme_type: string;
  dimension: string;
  frozen: boolean;
  themes: ThemeState[];
}

export interface ThemespaceState {
  clusters: ClusterState[];
  active_theme_types: string[];
}

// --- Trace types -----------------------------------------------------------

export interface TraceEvent {
  event_number: number;
  event_type: string;
  codelet_count: number;
  temperature: number;
  description: string;
}

// --- Memory types ----------------------------------------------------------

export interface AnswerDescription {
  answer_id: number;
  problem: string[];
  quality: number;
  temperature: number;
  themes: Record<string, any>;
  top_rule_description: string;
  bottom_rule_description: string;
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
