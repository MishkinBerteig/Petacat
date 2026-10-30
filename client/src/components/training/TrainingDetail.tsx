// ---------------------------------------------------------------------------
// Petacat -- Training: one Training's header, controls, add-problems box and table
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useState } from 'react';
import {
  addTrainingProblems,
  trainingExportUrl,
  cancelTraining,
  closeTraining,
  deleteTraining,
  describeApiError,
  pauseTraining,
  resumeTraining,
  updateTraining,
} from '@/api/client';
import type { TrainingErrorPolicy, TrainingLimits, TrainingSummary } from '@/types';
import { chunk, parseProblemText } from './problemText';
import { MemoryTab } from './MemoryTab';
import { PolicyFields } from './PolicyFields';
import { ProblemPreview, ProblemTextInput } from './ProblemTextInput';
import { ProblemsTable } from './ProblemsTable';
import {
  cardStyle,
  ControlHelp,
  errorStyle,
  fmtEta,
  fmtInt,
  fmtRate,
  fmtTime,
  linkButtonStyle,
  noticeStyle,
  ProgressBar,
  sectionLabelStyle,
  StateBadge,
} from './shared';

const FALLBACK_REQUEST_SIZE = 500;

interface Props {
  training: TrainingSummary;
  limits: TrainingLimits | null;
  /** A message to show above the Training (e.g. a partly failed create). */
  notice: string | null;
  /** A newer summary came back from the server. */
  onTrainingChanged: (training: TrainingSummary) => void;
  onDeleted: () => void;
}

export function TrainingDetail({ training, limits, notice, onTrainingChanged, onDeleted }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'problems' | 'memory'>('problems');
  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState('');

  const acceptsProblems = training.status === 'open' || training.status === 'paused';
  const label = training.name || `Training ${training.id}`;
  const shared = training.settings.memory === 'shared';

  const act = async (what: string, fn: () => Promise<TrainingSummary>) => {
    setBusy(true);
    setError(null);
    try {
      onTrainingChanged(await fn());
    } catch (err) {
      setError(describeApiError(err, what));
    } finally {
      setBusy(false);
    }
  };

  const startRename = () => {
    setNewName(training.name);
    setRenaming(true);
  };

  const saveRename = async () => {
    const name = newName.trim();
    if (name === '') {
      setError('A Training needs a name.');
      return;
    }
    if (name === training.name) {
      setRenaming(false);
      return;
    }
    await act('rename the Training', () => updateTraining(training.id, { name }));
    setRenaming(false);
  };

  const handleCancel = () => {
    if (
      !window.confirm(
        `Cancel "${label}"? Queued and running problems become cancelled; finished runs are kept.`,
      )
    )
      return;
    void act('cancel the Training', () => cancelTraining(training.id));
  };

  const handleDelete = async () => {
    if (
      !window.confirm(
        `Delete "${label}"? Its problems, runs and memory are removed from the database. This cannot be undone.`,
      )
    )
      return;
    setBusy(true);
    setError(null);
    try {
      await deleteTraining(training.id);
      onDeleted();
    } catch (err) {
      setError(describeApiError(err, 'delete the Training'));
      setBusy(false);
    }
  };

  const p = training.problems;
  const s = training.settings;
  const overrideCount = s.parameters ? Object.keys(s.parameters).length : 0;

  return (
    <div data-testid="training-detail" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {notice && (
        <div role="status" style={noticeStyle}>
          {notice}
        </div>
      )}
      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}

      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {renaming ? (
            <>
              <input
                aria-label="New name"
                value={newName}
                maxLength={200}
                autoFocus
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void saveRename();
                  if (e.key === 'Escape') setRenaming(false);
                }}
                style={{ minWidth: 200 }}
              />
              <button disabled={busy} onClick={() => void saveRename()}>
                Save name
              </button>
              <button disabled={busy} onClick={() => setRenaming(false)}>
                Cancel rename
              </button>
            </>
          ) : (
            <>
              <h2 style={{ margin: 0, fontSize: 15 }}>{label}</h2>
              <button disabled={busy} onClick={startRename} title="Rename this Training">
                Rename
              </button>
            </>
          )}
          <StateBadge state={training.state} />
          <ControlHelp topic="training" label="Training" />
          <span className="text-xs text-muted">created {fmtTime(training.created_at)}</span>
        </div>
        {training.last_event && (
          <div
            role="status"
            data-testid="last-event"
            style={{
              marginTop: 6,
              padding: '4px 8px',
              border: '1px solid var(--warning)',
              borderRadius: 4,
              fontWeight: 600,
              fontSize: 12,
            }}
          >
            {training.last_event}
          </div>
        )}
        {training.stalled_reason && (
          <div role="status" style={{ ...errorStyle, marginTop: 6 }}>
            Stalled: {training.stalled_reason}
          </div>
        )}
        {training.note && <div className="text-xs text-muted">{training.note}</div>}

        <div className="text-xs mono" style={{ marginTop: 6 }} data-testid="training-problems-line">
          Problems: {fmtInt(p.total)} total · {fmtInt(p.finished)} finished · {fmtInt(p.running)} running ·{' '}
          {fmtInt(p.queued)} queued · {fmtInt(p.cancelled)} cancelled
        </div>
        <div className="text-xs mono" style={{ margin: '4px 0 3px' }} data-testid="training-runs-line">
          Runs: {fmtInt(training.runs.done)} / {fmtInt(training.runs.total)}
          {' · '}
          {fmtInt(training.runs.errors)} errors · {fmtInt(training.runs.capped)} gave up at max codelets ·{' '}
          {fmtInt(training.runs.retries)} retries
          {' · '}
          {fmtRate(training.runs_per_second)} · ETA {fmtEta(training.eta_seconds)} · {fmtInt(training.codelets)}{' '}
          codelets
        </div>
        <ProgressBar done={training.runs.done} total={training.runs.total} label="Runs done" />

        <div className="text-xs mono" style={{ marginTop: 4 }} data-testid="training-memory-line">
          {shared && training.memory
            ? `Memory: ${fmtInt(training.memory.answers)} answers, ${fmtInt(training.memory.snags)} snags, version ${fmtInt(training.memory_version ?? 0)}`
            : 'Memory: independent runs (nothing shared)'}
        </div>
        <div className="text-xs text-muted" style={{ marginTop: 4 }} data-testid="training-settings-line">
          Settings (fixed): {shared ? 'shared memory' : 'independent runs'} · backend {s.backend} ·{' '}
          {fmtInt(s.seeds_per_problem)} seeds per problem from {s.seed_start} · max codelets per run{' '}
          {fmtInt(s.max_codelets)}
          {overrideCount > 0 ? ` · ${overrideCount} parameter overrides` : ''}
        </div>

        <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {training.status === 'paused' ? (
            <button disabled={busy} onClick={() => void act('resume the Training', () => resumeTraining(training.id))}>
              Resume
            </button>
          ) : (
            <button
              disabled={busy || training.status !== 'open'}
              onClick={() => void act('pause the Training', () => pauseTraining(training.id))}
              title="Stop starting new runs; runs already on a core finish"
            >
              Pause
            </button>
          )}
          <button
            disabled={busy || !acceptsProblems}
            onClick={() => void act('close the Training', () => closeTraining(training.id))}
            title="Accept no more problems"
          >
            Close
          </button>
          <button
            disabled={busy || training.status === 'cancelled' || training.state === 'finished'}
            onClick={handleCancel}
          >
            Cancel
          </button>
          <button disabled={busy} onClick={() => void handleDelete()}>
            Delete
          </button>
          <ControlHelp topic="training_run_state" label="pause, close and cancel" />
          <span style={{ flex: 1 }} />
          <span className="text-xs text-muted">Export:</span>
          {(['problems', 'distribution', 'runs'] as const).map((what) => (
            <span key={what} style={{ display: 'inline-flex', gap: 2 }}>
              <a href={trainingExportUrl(training.id, what, 'csv')} download style={linkButtonStyle}>
                {what} (CSV)
              </a>
              <a
                href={trainingExportUrl(training.id, what, 'json')}
                download
                aria-label={`Export ${what} as JSON`}
                title={what === 'runs' ? 'One JSON object per line' : 'JSON'}
                style={linkButtonStyle}
              >
                JSON
              </a>
            </span>
          ))}
          <ControlHelp topic="training_export" label="export" />
        </div>

        <PolicyEditor training={training} onTrainingChanged={onTrainingChanged} />
      </div>

      <AddProblems training={training} limits={limits} enabled={acceptsProblems} onTrainingChanged={onTrainingChanged} />

      <div style={cardStyle}>
        <div role="tablist" aria-label="Training views" style={{ display: 'flex', gap: 2, marginBottom: 8 }}>
          {(['problems', ...(shared ? (['memory'] as const) : [])] as const).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              style={{
                fontSize: 11,
                padding: '2px 10px',
                cursor: 'pointer',
                background: tab === t ? 'var(--bg-panel)' : 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 3,
                color: 'var(--text-primary)',
                fontWeight: tab === t ? 700 : 400,
              }}
            >
              {t === 'problems' ? 'Problems' : 'Memory'}
            </button>
          ))}
          {tab === 'memory' && <ControlHelp topic="training_memory" label="the Memory tab" />}
        </div>
        {tab === 'memory' && shared ? <MemoryTab training={training} /> : <ProblemsTable training={training} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The error policy, editable after creation
// ---------------------------------------------------------------------------

function PolicyEditor({
  training,
  onTrainingChanged,
}: {
  training: TrainingSummary;
  onTrainingChanged: (t: TrainingSummary) => void;
}) {
  const [policy, setPolicy] = useState<TrainingErrorPolicy>(training.policy);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const serverPolicy = JSON.stringify(training.policy);
  const dirty = JSON.stringify(policy) !== serverPolicy;

  // Follow the server when the policy changes elsewhere (the Training pausing itself, say).
  useEffect(() => {
    setPolicy(JSON.parse(serverPolicy) as TrainingErrorPolicy);
  }, [serverPolicy]);

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      onTrainingChanged(await updateTraining(training.id, { policy }));
      setSaved(true);
    } catch (err) {
      setError(describeApiError(err, 'change the policy'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <details style={{ marginTop: 8 }} data-testid="policy-editor">
      <summary style={{ cursor: 'pointer', fontSize: 12 }}>When things go wrong</summary>
      <div style={{ marginTop: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center' }} className="text-xs text-muted">
          The error policy; changes apply from now on.
          <ControlHelp topic="training_error_policy" label="the error policy" />
        </div>
        <PolicyFields
          idPrefix="policy"
          policy={policy}
          onChange={(p) => {
            setSaved(false);
            setPolicy(p);
          }}
          disabled={busy}
        />
        {error && (
          <div role="alert" style={errorStyle}>
            {error}
          </div>
        )}
        <button disabled={busy || !dirty} onClick={() => void save()}>
          Save policy
        </button>
        {saved && (
          <span role="status" className="text-xs" style={{ marginLeft: 8 }}>
            Policy saved.
          </span>
        )}
      </div>
    </details>
  );
}

// ---------------------------------------------------------------------------
// Add problems to a training that is open or paused
// ---------------------------------------------------------------------------

function AddProblems({
  training,
  limits,
  enabled,
  onTrainingChanged,
}: {
  training: TrainingSummary;
  limits: TrainingLimits | null;
  enabled: boolean;
  onTrainingChanged: (b: TrainingSummary) => void;
}) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const parsed = useMemo(() => parseProblemText(text), [text]);

  const add = async () => {
    setBusy(true);
    setError(null);
    setDone(null);
    let added = 0;
    try {
      let latest = training;
      for (const part of chunk(parsed.problems, limits?.max_problems_per_request ?? FALLBACK_REQUEST_SIZE)) {
        if (part.length === 0) continue;
        const res = await addTrainingProblems(training.id, part);
        added += res.added;
        latest = res.training;
        onTrainingChanged(latest);
      }
      setDone(`Added ${added.toLocaleString()} problems.`);
      setText('');
    } catch (err) {
      setError(
        `${describeApiError(err, 'add the problems')}` +
          (added > 0 ? ` ${added.toLocaleString()} were added before this failed.` : ''),
      );
      if (added > 0) setText('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={cardStyle} data-testid="add-problems">
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <div style={sectionLabelStyle}>Add problems</div>
        <ControlHelp topic="training_add_problems" label="Add problems" />
      </div>
      {!enabled && (
        <div className="text-xs text-muted" style={{ margin: '4px 0' }}>
          This training is {training.status} and accepts no more problems.
        </div>
      )}
      <div style={{ marginTop: 6 }}>
        <ProblemTextInput id="add-problems-text" value={text} onChange={setText} disabled={!enabled || busy} demos rows={3} />
        <ProblemPreview parsed={parsed} seedsPerProblem={training.settings.seeds_per_problem} />
      </div>
      {error && (
        <div role="alert" style={{ ...errorStyle, marginTop: 6 }}>
          {error}
        </div>
      )}
      {done && (
        <div role="status" className="text-xs" style={{ marginTop: 6 }}>
          {done}
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        <button disabled={!enabled || busy || parsed.problems.length === 0} onClick={() => void add()}>
          {busy ? 'Adding…' : `Add ${parsed.problems.length.toLocaleString()} problems`}
        </button>
      </div>
    </div>
  );
}
