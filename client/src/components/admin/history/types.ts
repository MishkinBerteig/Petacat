// ---------------------------------------------------------------------------
// Petacat -- the History views of the journal (server/api/journal.py)
// ---------------------------------------------------------------------------

/** The label a live session's pending entry carries. */
export const NOT_YET_SAVED = 'not yet saved'

export interface JournalEntry {
  /** null for a pending entry of a live session (its id is assigned at Stop). */
  id: number | null
  configuration_id: number
  revision: number
  group_id: string | null
  source: string
  actor: string
  channel: string
  note: string
  causing_run_id: number | null
  episode_version: number | null
  config_hash: string | null
  occurred_at: string
  recorded_at: string | null
  counts: { insert: number; update: number; delete: number }
  tables: string[]
  pending: boolean
  saved: boolean
  /** "not yet saved" for a pending entry, else "". */
  label: string
  /** Present with `detail`. */
  proposed?: unknown
  resolved?: JournalOp[]
  before?: Array<Record<string, unknown> | null>
}

export interface JournalOp {
  op: 'insert' | 'update' | 'delete'
  table: string
  key: Record<string, unknown>
  row?: Record<string, unknown>
  set?: Record<string, unknown>
}

export interface JournalPage {
  entries: JournalEntry[]
  total: number
  limit: number
  offset: number
  live: { state: string; revision: number; saved_through: number; unsaved: number } | null
}

export interface JournalFilters {
  configuration_id?: number
  table?: string
  key?: Record<string, unknown>
  source?: string
  actor?: string
  group_id?: string
  revision_from?: number
  revision_to?: number
  limit?: number
  offset?: number
  detail?: boolean
}

export interface NameEvent {
  event: 'created' | 'deleted' | 'merged_into' | 'renamed' | 'renamed_from' | 'edited'
  kind: string
  table: string
  text: string
  entry_id: number
  revision: number
  source: string
  actor: string
  channel: string
  note: string
  group_id: string | null
  occurred_at: string
  to?: string
  from?: string
  into?: string | null
  columns?: string[]
}

export interface NameStory {
  name: string
  configuration_id: number
  resolves: boolean
  kind: string | null
  /** The name it carries now after renames and merges; null when it is gone. */
  current_name: string | null
  events: NameEvent[]
  restorable: { table: string; key: Record<string, unknown>; as_of_revision: number; entry_id: number } | null
  text: string
}

export interface CheckNamesReply {
  configuration_id: number
  checked: number
  unresolved: NameStory[]
}

export interface RestoreReply {
  configuration_id: number
  changed: boolean
  revision: number
  entry_id: number | null
  ops: number
  config_hash: string | null
}

/** One row the report names: a cascade, a dangling reference or an affected row. */
export interface ReportItem {
  cause_op?: number
  table: string
  key: Record<string, unknown>
  op?: string
  column?: string
  reason?: string | null
}

/** The parts of a dry-run report the deletion preview shows. */
export interface DryRunReport {
  ok: boolean
  persisted?: boolean
  cascaded: ReportItem[]
  dangling: ReportItem[]
  affected: ReportItem[]
  message?: string
}
