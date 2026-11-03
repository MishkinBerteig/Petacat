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
