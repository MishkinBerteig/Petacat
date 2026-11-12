// ---------------------------------------------------------------------------
// Configuration status, comparison and reset (server/api/configurations.py)
// ---------------------------------------------------------------------------

/** One row of a configuration table, named by table and natural key. */
export interface ConfigurationRowRef {
  table: string
  key: Record<string, unknown>
}

export interface ConfigurationStatus {
  configuration_id: number
  kind: string
  revision: number
  /** The `config_hash` of the configuration in the database. */
  config_hash: string | null
  /** Digest of the Metacat Standard Configuration files the database was first loaded from. */
  standard_hash: string | null
  origin: string | null
  loaded_at: string | null
  /** The `config_hash` of the Metacat Standard Configuration (what `config_hash` is compared with). */
  standard_config_hash: string
  differs_rows: number
  equals_standard: boolean
}

export type ConfigurationChange = 'added' | 'removed' | 'changed'

export interface ConfigurationDiffRow extends ConfigurationRowRef {
  change: ConfigurationChange
  /** The row here (added), or the differing columns here (changed); null for a removed row. */
  current: Record<string, unknown> | null
  /** The row in the standard (removed), or the differing columns there (changed); null if added. */
  standard: Record<string, unknown> | null
  columns: string[]
}

export interface ConfigurationDiff {
  configuration_id: number
  revision: number
  count: number
  added: number
  removed: number
  changed: number
  rows: ConfigurationDiffRow[]
}

export interface ConfigurationWriteResult {
  configuration_id: number
  revision: number
  wrote: boolean
  entry_id: number | null
  ops: number
  config_hash: string | null
  skipped?: ConfigurationRowRef[]
}

export interface JournalVerifyReport {
  ok: boolean
  configuration_id: number
  revision: number
  entries: number
  problems: string[]
}

// ---------------------------------------------------------------------------
// The configuration manager (C9a): the list, compare and apply-from
// ---------------------------------------------------------------------------

/** One configuration as `GET /api/configurations` lists it. */
export interface ConfigurationSummary {
  id: number
  name: string
  note: string
  kind: 'global' | 'session'
  /** `Metacat Mode` or `Training Mode`. */
  mode: string
  /** `Metacat Mode`, or `Training Mode: <session name>`. */
  mode_label: string
  session_id: number | null
  session_name: string | null
  /** `stopped`, `starting`, `running`, `paused` or `stopping`; null for the global configuration. */
  session_state: string | null
  revision: number
  config_hash: string
  frozen: boolean
  created_from_configuration_id: number | null
  equals_standard: boolean
  differs_from_standard_rows: number
  last_change: {
    revision: number
    source: string
    actor: string
    channel: string
    recorded_at: string | null
  } | null
  /** `live` while the session is running or paused (the answer is its in-memory state). */
  source: 'stored' | 'live'
  live_revision?: number
  saved_through?: number
  saved_at?: string | null
  unsaved?: number
}

/** A side of a comparison: a configuration, the Metacat Standard Configuration, or the Training Mode Base Configuration, v2.0. */
export type NamedReference = 'standard' | 'training-v2'
export interface CompareSide {
  id: number | NamedReference
  name: string
  mode_label: string
  revision: number | null
}

export interface CompareRow extends ConfigurationRowRef {
  /** `added`: only A has the row. `removed`: only B has it. `changed`: both, with different columns. */
  change: ConfigurationChange
  /** The row in A (added), or A's differing columns (changed); null for a removed row. */
  a: Record<string, unknown> | null
  /** The row in B (removed), or B's differing columns (changed); null for an added row. */
  b: Record<string, unknown> | null
  columns: string[]
}

export interface ConfigurationCompare {
  a: CompareSide
  b: CompareSide
  same: boolean
  count: number
  added: number
  removed: number
  changed: number
  rows: CompareRow[]
}

/** The change API's report for an apply-from (a preview has `persisted: false`). */
export interface ApplyFromReport {
  ok?: boolean
  configuration_id: number
  wrote: boolean
  persisted?: boolean
  dry_run?: boolean
  ops: number
  revision?: number
  version_after?: number
  cascaded?: unknown[]
  effects?: unknown[]
  skipped_rows?: ConfigurationRowRef[]
}

// ---------------------------------------------------------------------------
// Edit-all (C12 routes, C9b UI): one change sent to chosen or all configurations
// ---------------------------------------------------------------------------

export type EditResult =
  | 'apply' | 'no_change' | 'differs' | 'not_applicable' | 'stale' | 'skipped_by_selection'

/** Which configurations a change goes to. `this` is the open one and never uses the edits routes. */
export interface EditScope {
  mode: 'this' | 'chosen' | 'all'
  /** The checklist of `chosen`. */
  ids: number[]
}

export interface EditPreviewTarget {
  configuration_id: number
  name: string
  mode: string
  mode_label: string
  session_id: number | null
  session_state: string | null
  frozen: boolean
  result: EditResult
  reason: string | null
  revision: number | null
  current_revision?: number
  report?: Record<string, unknown> | null
  /** False for a live session: the change is held in memory and saved at Stop. */
  persisted: boolean
}

export interface EditPreview {
  preview_token: string
  targets: EditPreviewTarget[]
  counts: Record<string, number>
}

export interface EditCommitTarget extends EditPreviewTarget {
  batch_id?: number | null
  version_before?: number | null
  version_after?: number | null
  /** Present for all-or-nothing; otherwise a target with result `apply` was written. */
  committed?: boolean
  /** What a stale target would do now. */
  re_preview?: { result: EditResult; reason: string | null; revision: number | null }
}

export interface EditCommit {
  group_id: string
  committed: boolean
  all_or_nothing: boolean
  blocked_by?: number[]
  persisted_false?: number[]
  targets: EditCommitTarget[]
  counts: Record<string, number>
}
