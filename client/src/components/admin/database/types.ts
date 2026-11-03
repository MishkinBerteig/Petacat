// The Database tab's wire types (server/api/database.py).

export type TableClass =
  | 'configuration'
  | 'content'
  | 'runtime'
  | 'journal'
  | 'session_managed'
  | 'episodic_memory'

export interface DbColumn {
  name: string
  type: string
  primary_key: boolean
  nullable: boolean
  /** A run column that places the run in a session's Episodic Memory: never edited. */
  protected: boolean
}

export interface DbTable {
  name: string
  class: TableClass
  class_label: string
  banner: string
  editable: boolean
  expert_required: boolean
  enum: boolean
  rows: number | null
  key_columns: string[]
  columns: DbColumn[]
}

export interface DbRow {
  values: Record<string, unknown>
  key: Record<string, unknown>
}

export interface DbRowPage {
  table: string
  class: TableClass
  class_label: string
  banner: string
  configuration: number
  total: number
  limit: number
  offset: number
  key_columns: string[]
  columns: DbColumn[]
  rows: DbRow[]
}

export interface SqlResult {
  columns: string[]
  rows: unknown[][]
  row_count: number
  truncated: boolean
  limit: number
  timeout_ms: number
}
