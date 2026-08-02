// ---------------------------------------------------------------------------
// Fixtures for the review components (WP3.9)
// ---------------------------------------------------------------------------
//
// The workspace comes from the same captured API output the WorkspaceView tests
// use, because the point of the review surfaces is that a recorded workspace and a
// live one are the same shape -- so a fixture that was good enough for the live
// tests is exactly the right fixture here.
// ---------------------------------------------------------------------------

import mrrjjj from '../../__fixtures__/mrrjjj.json'
import type {
  InspectorState,
  RecordedRun,
  RecordedState,
  RunComparison,
  TrainingSessionDetail,
  TrainingSessionSummary,
} from '@/types'

export function recordedRun(overrides: Partial<RecordedRun> = {}): RecordedRun {
  return {
    run_id: 7,
    mode: 'normal',
    status: 'answer_found',
    initial: 'abc',
    modified: 'abd',
    target: 'mrrjjj',
    answer: 'mrrkkk',
    justify_mode: false,
    seed: 12345,
    codelet_count: 783,
    temperature: 57,
    spreading_threshold: 100,
    config_hash: 'c0nf1gh45h00000000000000000000aa',
    memory_hash: 'm3m0ryh45h00000000000000000000bb',
    created_at: '2026-07-29T09:00:00',
    capture_count: 2,
    action_count: 0,
    ...overrides,
  }
}

export function sessionSummary(
  overrides: Partial<TrainingSessionSummary> = {},
): TrainingSessionSummary {
  return {
    session_id: 3,
    started_at: '2026-07-29T08:00:00',
    ended_at: null,
    note: '',
    run_count: 2,
    first_run_at: '2026-07-29T08:01:00',
    last_run_at: '2026-07-29T09:00:00',
    is_open: true,
    ...overrides,
  }
}

export function sessionDetail(
  runs: RecordedRun[],
  overrides: Partial<TrainingSessionDetail> = {},
): TrainingSessionDetail {
  return {
    session_id: 3,
    started_at: '2026-07-29T08:00:00',
    ended_at: null,
    note: '',
    is_open: true,
    runs,
    ...overrides,
  }
}

const SLIPNET = {
  'plato-successor': { activation: 100, conceptual_depth: 50, frozen: false },
  'plato-letter-category': { activation: 62, conceptual_depth: 30, frozen: false },
  'plato-sameness': { activation: 8, conceptual_depth: 80, frozen: false },
}

const THEMESPACE = {
  clusters: [
    {
      theme_type: 'top_bridge',
      dimension: 'plato-string-position-category',
      frozen: false,
      dominant_relation: 'identity',
      themes: [
        {
          dimension: 'plato-string-position-category',
          relation: 'identity',
          activation: 96,
          frozen: false,
          dominant: true,
        },
        {
          dimension: 'plato-string-position-category',
          relation: 'opposite',
          activation: 2,
          frozen: false,
          dominant: false,
        },
      ],
    },
  ],
  possible_theme_types: ['top_bridge', 'vertical_bridge'],
  active_theme_types: [],
  thematic_pressure: false,
  dominant_theme_margin: 90,
}

export function recordedState(overrides: Partial<RecordedState> = {}): RecordedState {
  return {
    run_id: 7,
    boundary: 'end',
    problem: { initial: 'abc', modified: 'abd', target: 'mrrjjj', answer: null },
    codelet_count: 783,
    temperature: 57,
    workspace: mrrjjj as any,
    slipnet: SLIPNET as any,
    coderack: { total_count: 42, type_counts: { 'bottom-up-bond-scout': 12 } },
    themespace: THEMESPACE as any,
    trace: [
      {
        event_number: 1,
        event_type: 'group_built',
        codelet_count: 120,
        temperature: 94,
        description: 'a successor group was perceived',
      },
    ],
    memory: { answers: [], snags: [] },
    ...overrides,
  }
}

export function runComparison(overrides: Partial<RunComparison> = {}): RunComparison {
  return {
    run_id: 7,
    problem: { initial: 'abc', modified: 'abd', target: 'mrrjjj', answer: null },
    codelets: { start: 0, end: 783, executed: 783 },
    temperature: { start: 100, end: 57, delta: -43 },
    structures: {
      bonds: { start: {}, end: { abc: 2, mrrjjj: 5 }, built: { abc: 2, mrrjjj: 5 } },
      groups: { start: {}, end: { mrrjjj: 2 }, built: { mrrjjj: 2 } },
      bridges: {
        start: { top_bridges: 0, vertical_bridges: 0, bottom_bridges: 0 },
        end: { top_bridges: 2, vertical_bridges: 2, bottom_bridges: 0 },
        built: { top_bridges: 2, vertical_bridges: 2, bottom_bridges: 0 },
      },
      rules: {
        start: { top_rules: 0, bottom_rules: 0 },
        end: { top_rules: 1, bottom_rules: 0 },
        built: { top_rules: 1, bottom_rules: 0 },
      },
    },
    rules: {
      top: [{ type: 'top', quality: 95, english: 'change LetterCtgy by succ' }],
      bottom: [],
    },
    slipnet: {
      moved: [
        { node: 'plato-successor', start: 0, end: 100, delta: 100 },
        { node: 'plato-sameness', start: 40, end: 8, delta: -32 },
      ],
      moved_count: 31,
      fully_active_at_start: [],
      fully_active_at_end: ['plato-successor'],
    },
    themes: {
      moved: [],
      moved_count: 12,
      dominant_at_end: [
        {
          theme_type: 'top_bridge',
          dimension: 'plato-string-position-category',
          relation: 'identity',
        },
      ],
    },
    trace: { events_at_start: 0, events_at_end: 13, by_type: { group_built: 2 }, events: [] },
    memory: {
      answers_at_start: 0,
      answers_at_end: 1,
      snags_at_start: 0,
      snags_at_end: 0,
      added_answers: [
        {
          answer_id: 1,
          problem: ['abc', 'abd', 'mrrjjj', 'mrrkkk'],
          quality: 88,
          temperature: 57,
          themes: {},
          top_rule_description: 'change LetterCtgy by succ',
          bottom_rule_description: '',
        },
      ],
      added_snags: [],
    },
    ...overrides,
  }
}

export function inspectorState(overrides: Partial<InspectorState> = {}): InspectorState {
  const base = recordedState()
  return {
    run_id: 9,
    codelet_count: 0,
    final_codelet_count: 400,
    at_end: false,
    codelet: null,
    structure_changes: [],
    actions: [],
    temperature: 100,
    recorded_temperature: null,
    workspace: base.workspace,
    slipnet: base.slipnet,
    coderack: base.coderack,
    themespace: base.themespace,
    trace: base.trace,
    ...overrides,
  }
}
