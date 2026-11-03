// ---------------------------------------------------------------------------
// Petacat -- a Training Mode Session's configuration reads (S6's routes)
// ---------------------------------------------------------------------------

import type { SessionSummary } from '@/types';

/** The labels every read carries: stored or live, and where the database stands. */
export interface SessionReadLabel {
  session_id: number;
  state: SessionSummary['state'];
  source: 'live' | 'stored';
  saved_through: SessionSummary['saved_through'];
  unsaved: SessionSummary['unsaved'];
}

export interface SessionConfigurationCounts extends SessionReadLabel {
  configuration_id: number;
  version: number;
  config_hash: string;
  tables: Record<string, number>;
}

export interface SessionConfigurationRows extends SessionReadLabel {
  configuration_id: number;
  version: number;
  config_hash: string;
  table: string;
  key_columns: string[];
  count: number;
  rows: Array<Record<string, unknown>>;
}

export interface SessionSlipnetNodeRow {
  name: string;
  short_name: string;
  conceptual_depth: number;
  description?: string;
}

export interface SessionSlipnetLinkRow {
  from_node: string;
  to_node: string;
  link_type: string;
  label_node: string | null;
  link_length: number | null;
  fixed_length: boolean;
}

export interface SessionSlipnetLayoutRow {
  node_name: string;
  grid_row: number;
  grid_col: number;
}

export interface SessionSlipnet extends SessionReadLabel {
  configuration_id: number;
  version: number;
  config_hash: string;
  nodes: SessionSlipnetNodeRow[];
  links: SessionSlipnetLinkRow[];
  layout: SessionSlipnetLayoutRow[];
  /** Node names with no layout row; the view places them. */
  unplaced: string[];
}

export interface SessionDiffRow {
  table: string;
  key: Record<string, unknown>;
  change: 'added' | 'removed' | 'changed';
  from: Record<string, unknown> | null;
  to: Record<string, unknown> | null;
  columns: string[];
}

export interface SessionConfigurationDiff extends SessionReadLabel {
  configuration_id: number;
  from: number;
  to: number;
  same: boolean;
  count: number;
  added: number;
  removed: number;
  changed: number;
  rows: SessionDiffRow[];
}

export interface SessionJournalEntry {
  id: number | null;
  revision: number;
  source: string;
  actor: string;
  channel: string;
  note: string;
  causing_run_id: number | null;
  group_id: string | null;
  occurred_at: string;
  config_hash: string | null;
  counts: { insert: number; update: number; delete: number };
  tables: string[];
  pending: boolean;
  /** "not yet saved" for a pending entry, else "". */
  label: string;
}

export interface SessionJournal extends SessionReadLabel {
  entries: SessionJournalEntry[];
  total: number;
  limit: number;
  offset: number;
}
